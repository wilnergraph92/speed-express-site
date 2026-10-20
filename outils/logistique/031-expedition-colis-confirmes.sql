-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 31 : expédier les colis confirmés
-- -----------------------------------------------------------------------------
-- À passer APRÈS 030, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Demande du propriétaire (20/10/2026) : « pour l'instant l'ancien parcours (confirmé, expédié, disponible, livré) ; garder le module
-- d'expédition ; quand je prépare une expédition, tous les colis confirmés doivent apparaître dans la fenêtre pour être sélectionnés ».
--
--   1. La fenêtre « Nouvelle expédition » (ready_for_shipment) propose aussi les colis CONFIRMÉS : enregistrés, reçus, vérifiés ou rangés,
--      pas encore prêts à partir ;
--   2. créer une expédition avec des colis confirmés (create_shipment_prepared) : la base fait, pour chacun, le chemin du poste de scan
--      (reçu, vérifié avec son poids, rangé, à consolider — prepare_parcels, 024) à l'entrepôt et à l'emplacement choisis, puis crée
--      l'expédition. Tout ou rien : un seul colis qui ne peut pas être préparé (poids manquant…) et rien n'est fait, avec la raison ;
--   3. un colis entré dans ce parcours avance désormais avec son expédition : départ → « expédié », arrivée au hub → « disponible », par
--      le reflet de 030. L'onglet Colis ne peut plus changer SON statut à la main (erreur SE005, message clair) : sinon l'ancien schéma et le
--      noyau se contrediraient sans bruit. Sa livraison se fait par Livraisons (remise au comptoir ou mission). Les autres colis, eux,
--      gardent l'ancien parcours dans l'onglet Colis, comme avant.
--
-- Rejouable sans risque ; aucune suppression.
-- =============================================================================

-- 1. La fenêtre « Nouvelle expédition » : ce qui est prêt, et les colis confirmés -----------------------------------------------------------
create or replace function logistics.ready_for_shipment(p_actor uuid, p_mode text default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  return jsonb_build_object(
    -- 031 : les colis CONFIRMÉS (enregistrés, pas encore prêts à partir) : la fenêtre « Nouvelle expédition » les propose aussi ; la base les
    -- prépare à la création de l'expédition (create_shipment_prepared).
    'confirmed', coalesce((select jsonb_agg(jsonb_build_object('parcel_id', p.id, 'tracking_number', p.tracking_number, 'mode', p.service_mode, 'status', p.status,
        'customer', jsonb_build_object('code', c.code, 'name', c.full_name), 'weight_lb', coalesce(p.verified_weight_lb, p.weight_lb),
        'destination_country', p.destination_country, 'destination_city', p.destination_city)
        order by p.destination_country, p.tracking_number)
      from logistics.parcel p join logistics.customer c on c.id = p.customer_id
     where p.status in ('CREATED', 'RECEIVED', 'VERIFIED', 'STORED') and (p_mode is null or p.service_mode = p_mode)
       and not exists (select 1 from logistics.consolidation_parcel cp where cp.parcel_id = p.id and cp.removed_at is null)), '[]'::jsonb),
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
     where k.status = 'CLOSED' and k.load_unit_id is null and (p_mode is null or k.mode = p_mode)
       and not exists (select 1 from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id where i.consolidation_id = k.id and s.status <> 'CANCELLED')), '[]'::jsonb),
    'load_units', coalesce((select jsonb_agg(jsonb_build_object('load_unit_id', l.id, 'code', l.code, 'kind', l.kind, 'status', l.status, 'seal_number', l.seal_number,
        'mode', m.mode, 'destination_country', m.destination_country, 'consolidations', m.n, 'parcels', x.parcels, 'weight_lb', x.weight_lb) order by m.destination_country, l.code)
      from logistics.load_unit l
      join lateral (select min(c.mode) as mode, min(c.destination_country) as destination_country, count(*) as n, bool_and(c.status = 'CLOSED') as fermees
                      from logistics.consolidation c where c.load_unit_id = l.id) m on m.n > 0
      cross join lateral logistics.load_unit_contents(l.id) x
     where m.fermees and (p_mode is null or m.mode = p_mode) and logistics.load_unit_shipment(l.id) is null), '[]'::jsonb));
end;
$$;

-- 2. Créer une expédition en préparant d'abord les colis confirmés : une seule transaction ----------------------------------------------------
create or replace function logistics.create_shipment_prepared(p_actor uuid, p_code text, p_mode text, p_origin_branch uuid, p_destination_branch uuid,
  p_confirmed_ids uuid[], p_parcel_ids uuid[], p_consolidation_ids uuid[], p_load_unit_ids uuid[], p_warehouse_id uuid, p_location_id uuid,
  p_idempotency_key text default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_codes text[]; v_prep jsonb; v_refus text;
begin
  perform logistics.require_right(p_actor, 'colis.statut');
  if coalesce(cardinality(p_confirmed_ids), 0) > 0 then
    if (select count(*) from logistics.parcel p where p.id = any (p_confirmed_ids)) <> cardinality(p_confirmed_ids) then
      raise exception 'Colis introuvable.' using errcode = 'LG002';
    end if;
    -- seulement ceux qui restent à préparer : un second envoi de la même demande (double clic, réseau) les trouve déjà dans l'expédition, et
    -- create_shipment rend alors la première (même clé d'idempotence)
    select array_agg(p.tracking_number order by p.tracking_number) into v_codes from logistics.parcel p
     where p.id = any (p_confirmed_ids) and p.status in ('CREATED', 'RECEIVED', 'VERIFIED', 'STORED');
    if p_warehouse_id is null or p_location_id is null then
      raise exception 'Choisissez l''entrepôt et l''emplacement où les colis confirmés sont préparés.' using errcode = 'LG005';
    end if;
    if coalesce(cardinality(v_codes), 0) > 0 then v_prep := logistics.prepare_parcels(p_actor, v_codes, p_warehouse_id, p_location_id); end if;
    select string_agg((x ->> 'code') || ' (' || coalesce(x ->> 'reason', x ->> 'status', '?') || ')', ', ') into v_refus
      from jsonb_array_elements(coalesce(v_prep -> 'results', '[]'::jsonb)) x where not coalesce((x ->> 'ready')::boolean, false);
    if v_refus is not null then
      -- tout ou rien : l'exception défait aussi les préparations déjà faites dans cette transaction
      raise exception 'Préparation impossible : %.', v_refus using errcode = 'LG005';
    end if;
  end if;
  return logistics.create_shipment(p_code, p_mode, p_origin_branch, p_destination_branch, p_actor, coalesce(p_consolidation_ids, '{}'),
                                   coalesce(p_parcel_ids, '{}') || coalesce(p_confirmed_ids, '{}'), coalesce(p_load_unit_ids, '{}'), p_idempotency_key, null);
end;
$$;

-- 3. Un colis qui suit son expédition : son statut ne se change plus à la main dans l'onglet Colis -------------------------------------------
-- Le reflet (030) écrit sous « ses.reflet = on » : il passe. Toute autre écriture du statut d'un colis sous l'autorité du noyau est refusée.
create or replace function logistics.guard_legacy_status() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.statut is distinct from old.statut and coalesce(current_setting('ses.reflet', true), '') <> 'on'
     and exists (select 1 from logistics.parcel p where p.legacy_parcel_id = new.id and p.status_authority = 'core') then
    raise exception 'Le colis % suit son expédition : son statut avance par les modules Expéditions et Livraisons.', new.numero using errcode = 'SE005';
  end if;
  return new;
end;
$$;
drop trigger if exists garde_statut_noyau on public.colis;
create trigger garde_statut_noyau before update of statut on public.colis for each row execute function logistics.guard_legacy_status();

-- 4. La façade, et tout le reste fermé ----------------------------------------------------------------------------------------------------
create or replace function public.lg_create_shipment_prepared(p_code text, p_mode text, p_origin_branch uuid, p_destination_branch uuid,
  p_confirmed_ids uuid[] default '{}', p_parcel_ids uuid[] default '{}', p_consolidation_ids uuid[] default '{}', p_load_unit_ids uuid[] default '{}',
  p_warehouse_id uuid default null, p_location_id uuid default null, p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$
  select logistics.create_shipment_prepared(auth.uid(), p_code, p_mode, p_origin_branch, p_destination_branch, p_confirmed_ids, p_parcel_ids,
                                            p_consolidation_ids, p_load_unit_ids, p_warehouse_id, p_location_id, p_idempotency_key) $$;
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('ready_for_shipment', 'create_shipment_prepared', 'guard_legacy_status') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname = 'lg_create_shipment_prepared' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
