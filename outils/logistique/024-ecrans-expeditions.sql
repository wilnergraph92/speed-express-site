-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 24 : les écrans des expéditions et des transports
-- -----------------------------------------------------------------------------
-- À passer APRÈS 023, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Les gestes existent depuis les étapes 005 et 016 (créer, planifier, préparer, faire partir, arriver, douane, réception au HUB,
-- clôture) ; il manquait aux écrans de quoi les viser :
--   · les listes du centre de commande rendent désormais l'IDENTIFIANT de chaque transport et de chaque expédition (la forme d'avant
--     est gardée : des clés s'ajoutent, aucune ne change), plus, pour un transport, son numéro de voyage, sa capacité et sa charge ;
--   · lg_ready_for_shipment : ce qui peut partir, pour un mode — les colis « à consolider » d'un client (les seuls que
--     create_shipment accepte en vrac) et les consolidations FERMÉES qui ne sont dans aucune expédition. Les mêmes règles que
--     create_shipment, lues au même endroit : l'écran ne propose que ce que la base acceptera ;
--   · lg_shipment_parcels : les colis d'une expédition (numéro, client, statut, poids, pays et ville de destination) ;
--   · lg_prepare_parcels : « préparer au départ » une liste de colis (§4), par les gestes officiels du poste de scan.
-- Les lectures : droit « colis.lire » ; la préparation : « colis.statut ». Rejouable sans risque ; aucune donnée supprimée. Ne JAMAIS rejouer 009 après 024.
-- =============================================================================

-- 1. Les transports et les expéditions, avec leurs identifiants ----------------------------------------------------------------------------
create or replace function logistics.cc_transports(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select t.* from logistics.transport t
       where (not v_f ? 'status' or t.status = v_f ->> 'status') and (not v_f ? 'service' or t.mode = v_f ->> 'service')
         and (not v_f ? 'country' or exists (select 1 from logistics.branch b where b.id = t.destination_branch_id and b.country = v_f ->> 'country'))
         and (logistics.cc_from(v_f) is null or coalesce(t.planned_departure_at, t.created_at) >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or coalesce(t.planned_departure_at, t.created_at) < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'items', coalesce((select jsonb_agg(jsonb_build_object('transport_id', x.id, 'reference', x.reference, 'voyage_number', x.voyage_number, 'carrier', x.carrier, 'mode', x.mode, 'status', x.status, 'origin', logistics.branch_label(x.origin_branch_id), 'destination', logistics.branch_label(x.destination_branch_id),
          'planned_departure_at', x.planned_departure_at, 'actual_departure_at', x.actual_departure_at, 'planned_arrival_at', x.planned_arrival_at, 'actual_arrival_at', x.actual_arrival_at,
          'late', x.status in ('PLANNED', 'DEPARTED') and x.planned_arrival_at is not null and x.planned_arrival_at < now(),
          'shipments', (select count(*) from logistics.shipment s where s.transport_id = x.id and s.status <> 'CANCELLED'),
          'capacity_weight_lb', x.capacity_weight_lb, 'capacity_volume_ft3', x.capacity_volume_ft3, 'load_weight_lb', logistics.transport_load_lb(x.id)) order by coalesce(x.planned_departure_at, x.created_at) desc, x.reference)
          from (select * from f order by coalesce(planned_departure_at, created_at) desc, reference limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_shipments(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select s.*, b.country as dest_country from logistics.shipment s left join logistics.branch b on b.id = s.destination_branch_id
       where (not v_f ? 'status' or s.status = v_f ->> 'status') and (not v_f ? 'country' or b.country = v_f ->> 'country') and (not v_f ? 'service' or s.mode = v_f ->> 'service')
         and (not v_f ? 'warehouse_id' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id where p.current_warehouse_id = (v_f ->> 'warehouse_id')::uuid))
         and (not v_f ? 'customer' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id join logistics.customer c on c.id = p.customer_id where logistics.cc_cust(v_f, c)))
         and (not v_f ? 'city' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id where position(lower(v_f ->> 'city') in lower(p.destination_city)) > 0))
         and (logistics.cc_from(v_f) is null or s.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or s.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select status, count(*) as n from f group by status) g), '{}'::jsonb),
      'items', coalesce((select jsonb_agg(jsonb_build_object('shipment_id', x.id, 'transport_id', x.transport_id, 'code', x.code, 'mode', x.mode, 'status', x.status, 'origin', logistics.branch_label(x.origin_branch_id), 'destination', logistics.branch_label(x.destination_branch_id),
          'transport', (select t.reference from logistics.transport t where t.id = x.transport_id), 'parcels', (select count(*) from logistics.shipment_parcels(x.id)),
          'weight_lb', (select coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb)), 0) from logistics.shipment_parcels(x.id) sp join logistics.parcel p on p.id = sp.parcel_id),
          'dispatched_at', x.dispatched_at, 'arrived_at', x.arrived_at, 'created_at', x.created_at) order by x.created_at desc, x.code)
                           from (select * from f order by created_at desc, code limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

-- 2. Ce qui peut partir, pour un mode -----------------------------------------------------------------------------------------------------------
create or replace function logistics.ready_for_shipment(p_actor uuid, p_mode text default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  return jsonb_build_object(
    'parcels', coalesce((select jsonb_agg(jsonb_build_object('parcel_id', p.id, 'tracking_number', p.tracking_number, 'mode', p.service_mode,
        'customer', jsonb_build_object('code', c.code, 'name', c.full_name), 'weight_lb', coalesce(p.verified_weight_lb, p.weight_lb),
        'destination_country', p.destination_country, 'destination_city', p.destination_city, 'warehouse', w.code)
        order by p.destination_country, p.tracking_number)
      from logistics.parcel p join logistics.customer c on c.id = p.customer_id left join logistics.warehouse w on w.id = p.current_warehouse_id
     where p.status = 'CONSOLIDATION_PENDING' and (p_mode is null or p.service_mode = p_mode)
       and not exists (select 1 from logistics.consolidation_parcel cp where cp.parcel_id = p.id and cp.removed_at is null)), '[]'::jsonb),
    'consolidations', coalesce((select jsonb_agg(jsonb_build_object('consolidation_id', k.id, 'code', k.code, 'mode', k.mode, 'destination_country', k.destination_country,
        'parcels', (select count(*) from logistics.consolidation_parcel cp where cp.consolidation_id = k.id and cp.removed_at is null),
        'weight_lb', (select coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb)), 0) from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id
                       where cp.consolidation_id = k.id and cp.removed_at is null)) order by k.destination_country, k.code)
      from logistics.consolidation k
     where k.status = 'CLOSED' and (p_mode is null or k.mode = p_mode)
       and not exists (select 1 from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id where i.consolidation_id = k.id and s.status <> 'CANCELLED')), '[]'::jsonb));
end;
$$;


-- 3. Les colis d'une expédition ----------------------------------------------------------------------------------------------------------------
create or replace function logistics.shipment_parcel_list(p_actor uuid, p_shipment uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  if not exists (select 1 from logistics.shipment where id = p_shipment) then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('parcel_id', p.id, 'tracking_number', p.tracking_number, 'status', p.status,
      'customer', jsonb_build_object('code', c.code, 'name', c.full_name), 'weight_lb', coalesce(p.verified_weight_lb, p.weight_lb),
      'destination_country', p.destination_country, 'destination_city', p.destination_city) order by p.destination_country, p.tracking_number)
    from logistics.shipment_parcels(p_shipment) sp join logistics.parcel p on p.id = sp.parcel_id left join logistics.customer c on c.id = p.customer_id), '[]'::jsonb);
end;
$$;


-- 4. Préparer au départ : le chemin du poste de scan, colis par colis ------------------------------------------------------------------------
-- Un colis ne part en vrac que « à consolider » (create_shipment). Le chemin officiel y mène en quatre gestes : reçu (scan), vérifié (pesée,
-- inspect_parcel), rangé à un emplacement (scan), à consolider (scan). Le poste de scan du bureau n'offre pas la pesée : sans ce geste,
-- aucun colis ne pouvait devenir prêt depuis le site. Ici, pour une liste de numéros (saisis ou scannés), chaque colis fait le chemin qui
-- lui reste, par ces MÊMES fonctions (mêmes contrôles, mêmes traces, mêmes événements) ; la vérification reprend le poids connu (pesé, ou
-- celui de l'ancien schéma) — sans poids, le colis s'arrête et doit être pesé. Un colis bloqué (mauvais entrepôt, en attente, abîmé…)
-- s'arrête là où il est, avec la raison ; les autres continuent. Droit « colis.statut ». 200 numéros au plus par appel.
create or replace function logistics.prepare_parcels(p_actor uuid, p_codes text[], p_warehouse uuid, p_location uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_code text; v_p logistics.parcel; v_r jsonb; v_out jsonb := '[]'::jsonb; v_ok int := 0; v_tour int; v_poids numeric; v_raison text;
begin
  perform logistics.require_right(p_actor, 'colis.statut');
  if coalesce(cardinality(p_codes), 0) = 0 then raise exception 'Aucun numéro de colis.' using errcode = 'LG005'; end if;
  if cardinality(p_codes) > 200 then raise exception 'Au plus 200 colis à la fois.' using errcode = 'LG005'; end if;
  if not exists (select 1 from logistics.warehouse where id = p_warehouse and active) then raise exception 'Entrepôt introuvable ou inactif.' using errcode = 'LG002'; end if;
  if not exists (select 1 from logistics.warehouse_location where id = p_location and warehouse_id = p_warehouse and active) then
    raise exception 'Choisissez un emplacement actif de cet entrepôt.' using errcode = 'LG005';
  end if;
  foreach v_code in array p_codes loop
    v_code := upper(btrim(coalesce(v_code, '')));
    continue when v_code = '';
    v_raison := null;
    begin
      for v_tour in 1..5 loop
        select * into v_p from logistics.parcel where upper(tracking_number) = v_code;
        if not found then v_raison := 'NOT_FOUND'; exit; end if;
        exit when v_p.status = 'CONSOLIDATION_PENDING';
        if v_p.status = 'CREATED' then
          v_r := logistics.scan_parcel(v_code, 'receive', p_actor, p_warehouse, null);
        elsif v_p.status = 'RECEIVED' then
          v_poids := coalesce(v_p.verified_weight_lb, v_p.weight_lb);
          if v_poids is null or v_poids <= 0 then v_raison := 'NO_WEIGHT'; exit; end if;
          v_r := logistics.inspect_parcel(v_code, p_actor, p_warehouse, v_poids);
          -- la pesée passe par un scan « verify » : son verdict est celui du poste de scan ; « inspected » dit si la pesée a eu lieu
          if coalesce((v_r ->> 'inspected')::boolean, v_r ->> 'result' = 'ACCEPTED') is not true then v_r := jsonb_build_object('result', coalesce(v_r ->> 'result', 'REFUSED')); end if;
        elsif v_p.status = 'VERIFIED' then
          v_r := logistics.scan_parcel(v_code, 'store', p_actor, p_warehouse, p_location);
        elsif v_p.status = 'STORED' then
          v_r := logistics.scan_parcel(v_code, 'consolidate', p_actor, p_warehouse, p_location);
        else
          v_raison := 'WRONG_STATE'; exit;
        end if;
        if coalesce(v_r ->> 'result', '') <> 'ACCEPTED' then v_raison := coalesce(v_r ->> 'result', 'REFUSED'); exit; end if;
      end loop;
    exception when others then
      v_raison := sqlerrm;
    end;
    select * into v_p from logistics.parcel where upper(tracking_number) = v_code;
    if v_raison is null and found and v_p.status = 'CONSOLIDATION_PENDING' then v_ok := v_ok + 1; end if;
    v_out := v_out || jsonb_build_array(jsonb_build_object('code', v_code, 'ready', v_raison is null and found and v_p.status = 'CONSOLIDATION_PENDING',
                                                           'status', case when found then v_p.status end, 'reason', v_raison));
  end loop;
  return jsonb_build_object('prepared', v_ok, 'results', v_out);
end;
$$;


-- 5. Les façades, et tout le reste fermé --------------------------------------------------------------------------------------------------------
create or replace function public.lg_ready_for_shipment(p_mode text default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.ready_for_shipment(auth.uid(), p_mode) $$;
create or replace function public.lg_prepare_parcels(p_tracking_numbers text[], p_warehouse_id uuid, p_location_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.prepare_parcels(auth.uid(), p_tracking_numbers, p_warehouse_id, p_location_id) $$;
create or replace function public.lg_shipment_parcels(p_shipment_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.shipment_parcel_list(auth.uid(), p_shipment_id) $$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('cc_transports', 'cc_shipments', 'ready_for_shipment', 'shipment_parcel_list', 'prepare_parcels') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_ready_for_shipment', 'lg_shipment_parcels', 'lg_prepare_parcels') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
