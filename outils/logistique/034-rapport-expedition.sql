-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 34 : le rapport d'une expédition
-- -----------------------------------------------------------------------------
-- À passer APRÈS 033, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Demande du propriétaire (21/10/2026) : à la création d'une expédition, un rapport imprimable (PDF) de tous ses colis, avec la date de
-- création ; pour chaque colis : nom et code du client, contenu, poids, pays et ville de livraison, facture payée, impayée ou payée en
-- partie ; le total des colis ; en tête, clairement, le pays et la ville d'arrivée ; la signature de l'employé qui prépare et du chauffeur
-- qui expédie ; les colis CLASSÉS PAR CLIENT.
--
-- Une seule lecture, shipment_report : la base rassemble et compte (colis, poids, clients, montants) ; l'écran ne fait que mettre en page.
-- Le paiement vient de la facturation EN SERVICE (l'ancien schéma, public.factures, tant que la Finance n'a pas basculé) : la facture du
-- colis, ou la facture groupée qui le contient (une ligne par colis). Payée en partie = impayée avec un montant déjà payé. Les MONTANTS ne
-- sont rendus qu'à qui lit les factures (« factures.lire ») ; le statut de paiement, à tous ceux qui lisent les colis.
-- Aucune écriture, aucune table. Rejouable sans risque ; aucune suppression.
-- =============================================================================

-- La facture en service d'un colis de l'ancien schéma : la sienne, sinon la facture groupée qui le porte dans ses lignes.
create or replace function logistics.report_invoice(p_legacy_parcel uuid, p_money boolean)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v jsonb;
begin
  if p_legacy_parcel is null or to_regclass('public.factures') is null then return jsonb_build_object('status', 'NONE'); end if;
  execute $q$
    select jsonb_build_object('number', f.numero, 'status', case when f.statut = 'payee' then 'PAID' when coalesce(f.montant_paye, 0) > 0 then 'PARTIAL' else 'UNPAID' end,
                              'currency', f.devise, 'amount', case when $2 then f.montant end, 'paid', case when $2 then coalesce(f.montant_paye, case when f.statut = 'payee' then f.montant else 0 end) end,
                              'grouped', coalesce(f.groupee, false))
      from public.factures f
     where f.colis_id = $1 or f.lignes @> jsonb_build_array(jsonb_build_object('colis_id', $1::text))
     order by (f.colis_id = $1) desc nulls last, f.cree_le desc
     limit 1 $q$ into v using p_legacy_parcel, p_money;
  return coalesce(v, jsonb_build_object('status', 'NONE'));
end;
$$;

create or replace function logistics.shipment_report(p_actor uuid, p_shipment uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_s logistics.shipment; v_money boolean; v_clients jsonb; v_lieu jsonb;
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  select * into v_s from logistics.shipment where id = p_shipment;
  if not found then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  v_money := logistics.actor_can(p_actor, 'factures.lire');
  with p as (
    select x.*, coalesce(nullif(btrim(lc.description), ''), x.description) as contenu, logistics.report_invoice(x.legacy_parcel_id, v_money) as facture
      from logistics.parcel x
      left join public.colis lc on lc.id = x.legacy_parcel_id
     where x.id in (select parcel_id from logistics.shipment_parcels(p_shipment))),
  c as (
    select p.customer_id, jsonb_agg(jsonb_build_object(
             'tracking_number', p.tracking_number, 'contents', p.contenu, 'weight_lb', coalesce(p.verified_weight_lb, p.weight_lb),
             'destination_country', p.destination_country, 'destination_city', p.destination_city, 'invoice', p.facture)
             order by p.tracking_number) as parcels,
           count(*) as n, sum(coalesce(p.verified_weight_lb, p.weight_lb, 0)) as poids
      from p group by p.customer_id),
  -- l'argent se compte par FACTURE, une seule fois : une facture groupée couvre plusieurs colis du même client
  f as (
    select d.customer_id, sum(d.montant) as montant, sum(d.paye) as paye
      from (select distinct on (p.customer_id, p.facture ->> 'number') p.customer_id, (p.facture ->> 'amount')::numeric as montant, (p.facture ->> 'paid')::numeric as paye
              from p where p.facture ->> 'number' is not null) d
     group by d.customer_id)
  select coalesce(jsonb_agg(jsonb_build_object(
           'customer_id', k.id, 'code', k.code, 'name', k.full_name, 'phone', k.phone,
           'parcels', c.parcels, 'count', c.n, 'weight_lb', c.poids,
           'amount', case when v_money then f.montant end, 'paid', case when v_money then f.paye end)
           order by k.full_name, k.code), '[]'::jsonb)
    into v_clients
    from c left join logistics.customer k on k.id = c.customer_id left join f on f.customer_id = c.customer_id;
  v_lieu := (select jsonb_build_object('code', b.code, 'name', b.name, 'kind', b.kind, 'country', b.country, 'city', b.city) from logistics.branch b where b.id = v_s.destination_branch_id);
  return jsonb_build_object(
    'shipment', jsonb_build_object('shipment_id', v_s.id, 'code', v_s.code, 'mode', v_s.mode, 'status', v_s.status, 'created_at', v_s.created_at,
      'prepared_by', case when v_s.created_by is null then null else logistics.chat_name(v_s.created_by) end,
      'origin', (select jsonb_build_object('code', b.code, 'name', b.name, 'country', b.country, 'city', b.city) from logistics.branch b where b.id = v_s.origin_branch_id),
      'destination', v_lieu,
      'transport', (select jsonb_build_object('carrier', t.carrier, 'reference', t.reference, 'voyage_number', t.voyage_number, 'vehicle', t.vehicle_label)
                      from logistics.transport t where t.id = v_s.transport_id),
      'planned_departure_at', v_s.planned_departure_at),
    'customers', v_clients,
    'money', v_money,
    'totals', jsonb_build_object(
      'parcels', (select coalesce(sum((x ->> 'count')::int), 0) from jsonb_array_elements(v_clients) x),
      'customers', jsonb_array_length(v_clients),
      'weight_lb', (select coalesce(sum((x ->> 'weight_lb')::numeric), 0) from jsonb_array_elements(v_clients) x),
      'amount', case when v_money then (select sum((x ->> 'amount')::numeric) from jsonb_array_elements(v_clients) x) end,
      'paid', case when v_money then (select sum((x ->> 'paid')::numeric) from jsonb_array_elements(v_clients) x) end,
      'unpaid_parcels', (select count(*) from jsonb_array_elements(v_clients) x, jsonb_array_elements(x -> 'parcels') y where y -> 'invoice' ->> 'status' in ('UNPAID', 'PARTIAL'))),
    'generated_at', now(), 'generated_by', logistics.chat_name(p_actor));
end;
$$;

create or replace function public.lg_shipment_report(p_shipment_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.shipment_report(auth.uid(), p_shipment_id) $$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('report_invoice', 'shipment_report') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname = 'lg_shipment_report' loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;

-- Pour retirer SEULEMENT cette étape : supprimer public.lg_shipment_report, logistics.shipment_report, logistics.report_invoice.
