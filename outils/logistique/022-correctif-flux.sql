-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 22 : le flux du centre de commande répond de nouveau
-- -----------------------------------------------------------------------------
-- Correctif. À passer APRÈS 021, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- L'étape 016 a ajouté planned_arrival_at aux EXPÉDITIONS (l'arrivée prévue de l'expédition elle-même). Le flux (logistics.cc_flow,
-- étape 009) prenait toutes les colonnes de l'expédition (« s.* ») ET planned_arrival_at du TRANSPORT : deux colonnes du même nom, et
-- PostgreSQL répondait « column reference "planned_arrival_at" is ambiguous ». Les sections « Flux » et « Centre de commande » du
-- tableau de bord affichaient cette erreur. Aucune donnée n'était touchée.
--
-- Ici : la colonne du transport est renommée dans la requête, et l'arrivée prévue affichée est celle de l'expédition si elle en a une,
-- sinon celle du transport (la même règle que logistics.shipment_detail, étape 016). Même forme de réponse qu'avant.
-- outils/tests/logistique-fumee-essai.py appelle désormais TOUTES les lectures sur le noyau complet : une étape plus récente qui
-- casserait une fonction plus ancienne est vue avant la production.
-- Rejouable sans risque ; aucune donnée supprimée. Retour arrière : aucun nécessaire (le comportement d'avant était une erreur) ; ne
-- JAMAIS rejouer 009 après 022 (une étape ancienne ne se rejoue pas après une plus récente).
-- =============================================================================

-- 1. Le flux : expédition → transport → hub → livraison → chauffeur -------------------------------------------------------------------------
create or replace function logistics.cc_flow(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select s.*, t.carrier, t.reference as transport_ref, t.status as transport_status, t.planned_arrival_at as transport_planned_arrival_at, t.actual_departure_at, t.actual_arrival_at, b.country as dest_country
        from logistics.shipment s left join logistics.transport t on t.id = s.transport_id left join logistics.branch b on b.id = s.destination_branch_id
       where s.status not in ('DRAFT', 'CANCELLED')
         and (not v_f ? 'status' or s.status = v_f ->> 'status' or (v_f ->> 'status' = 'ACTIVE' and s.status <> 'CLOSED'))
         and (not v_f ? 'country' or b.country = v_f ->> 'country') and (not v_f ? 'service' or s.mode = v_f ->> 'service')
         and (logistics.cc_from(v_f) is null or s.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or s.created_at < logistics.cc_to(v_f))
         and (not v_f ? 'warehouse_id' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id where p.current_warehouse_id = (v_f ->> 'warehouse_id')::uuid))
         and (not v_f ? 'customer' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id join logistics.customer c on c.id = p.customer_id where logistics.cc_cust(v_f, c)))
         and (not v_f ? 'city' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id where position(lower(v_f ->> 'city') in lower(p.destination_city)) > 0)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f, 'items', coalesce((select jsonb_agg(jsonb_build_object(
        'shipment', x.code, 'mode', x.mode, 'status', x.status, 'created_at', x.created_at,
        'transport', case when x.transport_ref is not null then jsonb_build_object('reference', x.transport_ref, 'carrier', x.carrier, 'status', x.transport_status,
                           'departed_at', x.actual_departure_at, 'planned_arrival_at', coalesce(x.planned_arrival_at, x.transport_planned_arrival_at), 'arrived_at', x.actual_arrival_at) end,
        'hub', logistics.branch_label(x.destination_branch_id), 'country', x.dest_country,
        'parcels', jsonb_build_object('total', (select count(*) from logistics.shipment_parcels(x.id)),
                      'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select p.status, count(*) as n from logistics.shipment_parcels(x.id) sp join logistics.parcel p on p.id = sp.parcel_id group by p.status) g), '{}'::jsonb)),
        'deliveries', coalesce((select jsonb_agg(jsonb_build_object('status', d.status, 'scheduled_date', d.scheduled_date, 'driver', d.driver_name, 'parcels', d.n) order by d.scheduled_date, d.driver_name)
                                  from (select tk.id, tk.status, tk.scheduled_date, dr.full_name as driver_name, count(distinct dp.parcel_id) as n
                                          from logistics.shipment_parcels(x.id) sp join logistics.delivery_parcel dp on dp.parcel_id = sp.parcel_id
                                          join logistics.task tk on tk.delivery_id = dp.delivery_id and tk.kind = 'DELIVERY' left join logistics.driver dr on dr.id = tk.driver_id
                                         group by tk.id, tk.status, tk.scheduled_date, dr.full_name) d), '[]'::jsonb)) order by x.created_at desc, x.code)
                                from (select * from f order by created_at desc, code limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

-- 2. Fermé comme avant : seule la façade public.lg_cc_flow (étape 009, inchangée) l'appelle -----------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname = 'cc_flow' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
end
$$;
