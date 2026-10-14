-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 26 : consolidations, unités logistiques et transbordement, depuis le tableau de bord
-- -----------------------------------------------------------------------------
-- À passer APRÈS 025, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Les règles existent depuis les étapes 005 et 016 (ouvrir, remplir, fermer une consolidation ; créer, charger, sceller, ouvrir une unité
-- logistique — palette, conteneur, ULD, sac ; l'étape suivante d'un transbordement). Il manquait de quoi s'en servir depuis un écran, et
-- trois trous que l'écran aurait rendus visibles :
--   · une consolidation chargée dans une unité pouvait AUSSI partir seule dans une autre expédition (deux fois expédiée) ; une unité pouvait
--     recevoir une consolidation déjà expédiée ; une expédition pouvait emporter une unité VIDE ou d'un autre mode → create_shipment et
--     put_consolidation_in_load_unit le refusent désormais ;
--   · rien ne retirait une consolidation chargée par erreur → remove_consolidation_from_load_unit, avec motif, tracé ;
--   · aucune lecture ne disait quelles unités existent, ni quels colis attendent leur étape suivante à un hub de transit.
-- Ajouts :
--   · lg_cc_consolidations rend l'identifiant de chaque consolidation et son unité (pour agir depuis la liste) ;
--   · lg_consolidation_parcels : les colis d'une consolidation ;
--   · lg_fill_consolidation : remplir une consolidation d'une liste de numéros (scannés ou cochés), colis par colis, avec la raison de chaque
--     refus (NOT_FOUND, WRONG_STATE, NO_CUSTOMER, OTHER_COUNTRY, OTHER_MODE, IN_CONSOLIDATION, REFUSED) — les autres entrent quand même ;
--   · lg_cc_load_units : les unités logistiques, leur contenu, leur scellé, leur expédition ;
--   · lg_remove_consolidation_from_load_unit ;
--   · lg_ready_for_shipment rend aussi les unités prêtes à partir, et ne propose plus seule une consolidation déjà dans une unité ;
--   · lg_awaiting_onward : les colis arrivés à un hub de TRANSIT (pas leur pays), qui attendent leur étape suivante.
-- Lectures : « colis.lire » ; gestes : « colis.statut » (logistics.require_right). Rejouable sans risque ; aucune donnée supprimée.
-- Ne JAMAIS rejouer 005, 009, 016 ou 024 après 026 (elles redéfinissent des fonctions que celle-ci complète).
-- =============================================================================

-- 1. La liste des consolidations, avec leur identifiant et leur unité (redéfinie depuis l'étape 009) -------------------------------------------
create or replace function logistics.cc_consolidations(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select c.* from logistics.consolidation c
       where (not v_f ? 'status' or c.status = v_f ->> 'status') and (not v_f ? 'country' or c.destination_country = v_f ->> 'country') and (not v_f ? 'service' or c.mode = v_f ->> 'service')
         and (not v_f ? 'warehouse_id' or c.warehouse_id = (v_f ->> 'warehouse_id')::uuid)
         and (not v_f ? 'customer' or exists (select 1 from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id join logistics.customer cu on cu.id = p.customer_id where cp.consolidation_id = c.id and cp.removed_at is null and logistics.cc_cust(v_f, cu)))
         and (logistics.cc_from(v_f) is null or c.opened_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or c.opened_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'items', coalesce((select jsonb_agg(jsonb_build_object('consolidation_id', x.id, 'code', x.code, 'status', x.status, 'mode', x.mode, 'destination_country', x.destination_country,
          'warehouse', (select logistics.branch_label(w.branch_id) from logistics.warehouse w where w.id = x.warehouse_id),
          'parcels', (select count(*) from logistics.consolidation_parcel cp where cp.consolidation_id = x.id and cp.removed_at is null),
          'customers', (select count(distinct p.customer_id) from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id where cp.consolidation_id = x.id and cp.removed_at is null),
          'weight_lb', (select coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb)), 0) from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id where cp.consolidation_id = x.id and cp.removed_at is null),
          'shipment', coalesce((select s.code from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id where i.consolidation_id = x.id and s.status <> 'CANCELLED' order by s.created_at desc limit 1),
                               (select s.code from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id where x.load_unit_id is not null and i.load_unit_id = x.load_unit_id and s.status <> 'CANCELLED' order by s.created_at desc limit 1)),
          'load_unit', (select jsonb_build_object('load_unit_id', l.id, 'code', l.code, 'kind', l.kind, 'status', l.status) from logistics.load_unit l where l.id = x.load_unit_id),
          'opened_at', x.opened_at, 'closed_at', x.closed_at) order by x.opened_at desc, x.code) from (select * from f order by opened_at desc, code limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;


-- 2. Les colis d'une consolidation, et la remplir d'une liste de numéros ---------------------------------------------------------------------
create or replace function logistics.consolidation_parcel_list(p_actor uuid, p_consolidation uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  if not exists (select 1 from logistics.consolidation where id = p_consolidation) then raise exception 'Consolidation introuvable.' using errcode = 'LG002'; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('parcel_id', p.id, 'tracking_number', p.tracking_number, 'status', p.status,
      'weight_lb', coalesce(p.verified_weight_lb, p.weight_lb), 'destination_city', p.destination_city,
      'customer', jsonb_build_object('code', c.code, 'name', c.full_name), 'added_at', cp.added_at) order by cp.added_at, p.tracking_number)
    from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id left join logistics.customer c on c.id = p.customer_id
   where cp.consolidation_id = p_consolidation and cp.removed_at is null), '[]'::jsonb);
end;
$$;

-- Chaque numéro est jugé seul : un numéro inconnu ou un colis d'un autre pays ne bloque pas les autres. Les conditions sont celles de
-- add_parcel_to_consolidation, lues avant l'appel pour donner une RAISON lisible ; l'appel lui-même reste le seul chemin d'écriture.
create or replace function logistics.fill_consolidation(p_actor uuid, p_consolidation uuid, p_tracking_numbers text[])
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c logistics.consolidation; v_code text; v_p logistics.parcel; v_res jsonb := '[]'::jsonb; v_ok int := 0; v_raison text; v_vus text[] := '{}';
begin
  perform logistics.require_right(p_actor);
  select * into v_c from logistics.consolidation where id = p_consolidation;
  if not found then raise exception 'Consolidation introuvable.' using errcode = 'LG002'; end if;
  if v_c.status <> 'OPEN' then raise exception 'La consolidation % est %, on n''y ajoute plus rien.', v_c.code, v_c.status using errcode = 'LG004'; end if;
  if coalesce(cardinality(p_tracking_numbers), 0) = 0 then raise exception 'Aucun numéro de colis.' using errcode = 'LG005'; end if;
  if cardinality(p_tracking_numbers) > 500 then raise exception 'Au plus 500 colis à la fois.' using errcode = 'LG005'; end if;
  foreach v_code in array p_tracking_numbers loop
    v_code := upper(btrim(coalesce(v_code, '')));
    continue when v_code = '' or v_code = any (v_vus);
    v_vus := v_vus || v_code;
    v_raison := null;
    select * into v_p from logistics.parcel where upper(tracking_number) = v_code;
    if not found then v_raison := 'NOT_FOUND';
    elsif exists (select 1 from logistics.consolidation_parcel where parcel_id = v_p.id and removed_at is null) then v_raison := 'IN_CONSOLIDATION';
    elsif v_p.status <> 'CONSOLIDATION_PENDING' then v_raison := 'WRONG_STATE';
    elsif v_p.customer_id is null then v_raison := 'NO_CUSTOMER';
    elsif v_p.destination_country <> v_c.destination_country then v_raison := 'OTHER_COUNTRY';
    elsif v_p.service_mode <> v_c.mode then v_raison := 'OTHER_MODE';
    end if;
    if v_raison is null then
      begin
        perform logistics.add_parcel_to_consolidation(p_consolidation, v_p.id, p_actor);
        v_ok := v_ok + 1;
      exception when others then
        v_raison := 'REFUSED';
      end;
    end if;
    v_res := v_res || jsonb_build_object('code', v_code, 'added', v_raison is null, 'reason', v_raison,
                                         'status', case when v_p.id is not null then v_p.status end);
  end loop;
  return jsonb_build_object('consolidation_id', p_consolidation, 'added', v_ok, 'results', v_res,
                            'parcels', (select count(*) from logistics.consolidation_parcel where consolidation_id = p_consolidation and removed_at is null));
end;
$$;


-- 3. Les unités logistiques -----------------------------------------------------------------------------------------------------------------
-- Une unité n'a pas de mode ni de destination à elle : ce sont ceux de ses consolidations (put_consolidation_in_load_unit n'y mêle jamais deux
-- modes ni deux pays).
create or replace function logistics.load_unit_shipment(p_unit uuid)
returns uuid language sql stable security definer set search_path = '' as $$
  select s.id from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id
   where i.load_unit_id = p_unit and s.status <> 'CANCELLED' order by s.created_at desc limit 1
$$;

create or replace function logistics.cc_load_units(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select l.*, (select c.mode from logistics.consolidation c where c.load_unit_id = l.id limit 1) as u_mode,
             (select c.destination_country from logistics.consolidation c where c.load_unit_id = l.id limit 1) as u_country
        from logistics.load_unit l),
    g as (
      select * from f
       where (not v_f ? 'status' or f.status = v_f ->> 'status') and (not v_f ? 'service' or f.u_mode = v_f ->> 'service') and (not v_f ? 'country' or f.u_country = v_f ->> 'country')
         and (logistics.cc_from(v_f) is null or f.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or f.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from g), 'filters', v_f,
      'items', coalesce((select jsonb_agg(jsonb_build_object('load_unit_id', x.id, 'code', x.code, 'kind', x.kind, 'status', x.status, 'seal_number', x.seal_number,
          'sealed_at', x.sealed_at, 'opened_reason', x.opened_reason, 'max_weight_lb', x.max_weight_lb, 'max_volume_ft3', x.max_volume_ft3,
          'mode', x.u_mode, 'destination_country', x.u_country,
          'consolidations', coalesce((select jsonb_agg(jsonb_build_object('consolidation_id', c.id, 'code', c.code, 'status', c.status) order by c.code)
                                        from logistics.consolidation c where c.load_unit_id = x.id), '[]'::jsonb),
          'parcels', k.parcels, 'weight_lb', k.weight_lb, 'volume_ft3', k.volume_ft3,
          'shipment', (select jsonb_build_object('shipment_id', s.id, 'code', s.code, 'status', s.status) from logistics.shipment s where s.id = logistics.load_unit_shipment(x.id)),
          'created_at', x.created_at) order by x.created_at desc, x.code)
          from (select * from g order by created_at desc, code limit v_lim offset v_off) x cross join lateral logistics.load_unit_contents(x.id) k), '[]'::jsonb)));
end;
$$;

-- Charger : en plus des règles de l'étape 016, une consolidation déjà dans une expédition n'entre pas dans une unité (elle partirait deux fois),
-- et une unité déjà dans une expédition qui n'est plus en brouillon ne se remplit plus (son manifeste est fait).
create or replace function logistics.put_consolidation_in_load_unit(p_actor uuid, p_consolidation uuid, p_unit uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c logistics.consolidation; v_u logistics.load_unit; v_x record; v_w numeric; v_v numeric; v_corr uuid := gen_random_uuid(); v_s logistics.shipment;
begin
  perform logistics.require_right(p_actor);
  select * into v_u from logistics.load_unit where id = p_unit for update;
  if not found then raise exception 'Unité logistique introuvable.' using errcode = 'LG002'; end if;
  if v_u.status <> 'OPEN' then raise exception 'L''unité % est % : on n''y charge plus rien.', v_u.code, v_u.status using errcode = 'LG004'; end if;
  select * into v_c from logistics.consolidation where id = p_consolidation for update;
  if not found then raise exception 'Consolidation introuvable.' using errcode = 'LG002'; end if;
  if v_c.status <> 'CLOSED' then raise exception 'La consolidation % est % : il faut la FERMER avant de la charger.', v_c.code, v_c.status using errcode = 'LG005'; end if;
  if v_c.load_unit_id is not null then raise exception 'La consolidation % est déjà dans une unité logistique.', v_c.code using errcode = 'LG005'; end if;
  if exists (select 1 from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id where i.consolidation_id = p_consolidation and s.status <> 'CANCELLED') then
    raise exception 'La consolidation % est déjà dans une expédition : elle n''entre plus dans une unité.', v_c.code using errcode = 'LG005';
  end if;
  select * into v_s from logistics.shipment where id = logistics.load_unit_shipment(p_unit);
  if found then
    if v_s.status <> 'DRAFT' then raise exception 'L''unité % part avec l''expédition % (%) : on n''y charge plus rien.', v_u.code, v_s.code, v_s.status using errcode = 'LG004'; end if;
    if v_s.mode <> v_c.mode then raise exception 'L''unité part en %, la consolidation est en %.', v_s.mode, v_c.mode using errcode = 'LG005'; end if;
  end if;
  if exists (select 1 from logistics.consolidation c where c.load_unit_id = p_unit and (c.destination_country <> v_c.destination_country or c.mode <> v_c.mode)) then
    raise exception 'Une unité logistique ne mêle pas des destinations ou des modes différents.' using errcode = 'LG005';
  end if;
  select * into v_x from logistics.load_unit_contents(p_unit);
  select coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb, 0)), 0), coalesce(sum(coalesce(p.volume_ft3, 0)), 0) into v_w, v_v
    from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id where cp.consolidation_id = p_consolidation and cp.removed_at is null;
  if v_u.max_weight_lb is not null and v_x.weight_lb + v_w > v_u.max_weight_lb then
    raise exception 'Poids maximal de l''unité % dépassé (% + % > % lb).', v_u.code, v_x.weight_lb, v_w, v_u.max_weight_lb using errcode = 'LG005';
  end if;
  if v_u.max_volume_ft3 is not null and v_x.volume_ft3 + v_v > v_u.max_volume_ft3 then
    raise exception 'Volume maximal de l''unité % dépassé.', v_u.code using errcode = 'LG005';
  end if;
  update logistics.consolidation set load_unit_id = p_unit where id = p_consolidation;
  perform logistics.emit('LoadUnitLoaded', 'load_unit', p_unit::text, v_corr, p_actor, jsonb_build_object('load_unit_id', p_unit, 'consolidation_id', p_consolidation));
  return logistics.load_unit_summary(p_actor, p_unit);
end;
$$;

-- Retirer une consolidation chargée par erreur : unité ouverte (pas scellée), pas encore partie (expédition en brouillon ou aucune), motif.
create or replace function logistics.remove_consolidation_from_load_unit(p_actor uuid, p_consolidation uuid, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c logistics.consolidation; v_u logistics.load_unit; v_s logistics.shipment; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  select * into v_c from logistics.consolidation where id = p_consolidation for update;
  if not found then raise exception 'Consolidation introuvable.' using errcode = 'LG002'; end if;
  if v_c.load_unit_id is null then raise exception 'La consolidation % n''est dans aucune unité.', v_c.code using errcode = 'LG005'; end if;
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Le motif du retrait est obligatoire.' using errcode = 'LG005'; end if;
  select * into v_u from logistics.load_unit where id = v_c.load_unit_id for update;
  if v_u.status = 'SEALED' then raise exception 'L''unité % est scellée : ouvrez-la (avec un motif) avant d''en retirer quoi que ce soit.', v_u.code using errcode = 'LG004'; end if;
  select * into v_s from logistics.shipment where id = logistics.load_unit_shipment(v_u.id);
  if found and v_s.status <> 'DRAFT' then
    raise exception 'L''unité % part avec l''expédition % (%) : on n''en retire plus rien.', v_u.code, v_s.code, v_s.status using errcode = 'LG004';
  end if;
  update logistics.consolidation set load_unit_id = null where id = p_consolidation;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'load_unit.unload', 'load_unit', v_u.id::text,
          jsonb_build_object('consolidation', v_c.code), jsonb_build_object('consolidation', null, 'reason', left(btrim(p_reason), 500)), v_corr);
  perform logistics.emit('LoadUnitUnloaded', 'load_unit', v_u.id::text, v_corr, p_actor,
                         jsonb_build_object('load_unit_id', v_u.id, 'consolidation_id', p_consolidation, 'reason', left(btrim(p_reason), 500)));
  return logistics.load_unit_summary(p_actor, v_u.id);
end;
$$;

insert into logistics.event_type (code, aggregate_type, description) values
  ('LoadUnitUnloaded', 'load_unit', 'Consolidation retirée d''une unité logistique')
on conflict (code) do nothing;


-- 4. Créer une expédition : les trous fermés (redéfinie depuis l'étape 005) -----------------------------------------------------------------
create or replace function logistics.create_shipment(
  p_code text, p_mode text, p_origin_branch uuid, p_destination_branch uuid, p_actor uuid,
  p_consolidation_ids uuid[] default '{}', p_parcel_ids uuid[] default '{}', p_load_unit_ids uuid[] default '{}',
  p_idempotency_key text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_prior jsonb; v_id uuid := gen_random_uuid(); v_hub logistics.branch; v_x uuid; v_c logistics.consolidation;
  v_p logistics.parcel; v_label text; v_out jsonb; v_u logistics.load_unit;
begin
  perform logistics.require_right(p_actor);
  v_prior := logistics.idem_begin(p_idempotency_key, 'create_shipment', md5(concat_ws('|', p_code, p_mode, p_origin_branch, p_destination_branch, p_consolidation_ids::text, p_parcel_ids::text, p_load_unit_ids::text)), p_code);
  if v_prior is not null then return v_prior; end if;
  if btrim(coalesce(p_code, '')) = '' then raise exception 'Un code d''expédition est obligatoire.' using errcode = 'LG005'; end if;
  if not exists (select 1 from logistics.transport_mode where code = p_mode and active) then raise exception 'Mode de transport inconnu : %.', p_mode using errcode = 'LG005'; end if;
  select * into v_hub from logistics.branch where id = p_destination_branch and active;
  if not found or v_hub.kind <> 'hub' then raise exception 'La destination d''une expédition est un HUB.' using errcode = 'LG005'; end if;
  if not exists (select 1 from logistics.branch where id = p_origin_branch and active) then raise exception 'Succursale d''origine inconnue.' using errcode = 'LG005'; end if;
  if coalesce(cardinality(p_consolidation_ids), 0) + coalesce(cardinality(p_parcel_ids), 0) + coalesce(cardinality(p_load_unit_ids), 0) = 0 then
    raise exception 'Une expédition contient au moins une consolidation, un colis ou une unité logistique.' using errcode = 'LG005';
  end if;
  insert into logistics.shipment (id, code, mode, origin_branch_id, destination_branch_id, created_by) values (v_id, btrim(p_code), p_mode, p_origin_branch, p_destination_branch, p_actor);

  foreach v_x in array coalesce(p_consolidation_ids, '{}') loop
    select * into v_c from logistics.consolidation where id = v_x for update;
    if not found then raise exception 'Consolidation introuvable.' using errcode = 'LG002'; end if;
    if v_c.status <> 'CLOSED' then raise exception 'La consolidation % est % : il faut la FERMER avant de l''expédier.', v_c.code, v_c.status using errcode = 'LG005'; end if;
    if v_c.mode <> p_mode then raise exception 'La consolidation % est en mode %, l''expédition en %.', v_c.code, v_c.mode, p_mode using errcode = 'LG005'; end if;
    if v_c.load_unit_id is not null then
      raise exception 'La consolidation % est dans l''unité % : expédiez l''unité.', v_c.code, (select code from logistics.load_unit where id = v_c.load_unit_id) using errcode = 'LG005';
    end if;
    if exists (select 1 from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id where i.consolidation_id = v_x and s.status not in ('CANCELLED') and s.id <> v_id) then
      raise exception 'La consolidation % est déjà dans une autre expédition.', v_c.code using errcode = 'LG005';
    end if;
    insert into logistics.shipment_item (shipment_id, consolidation_id) values (v_id, v_x);
  end loop;
  foreach v_x in array coalesce(p_load_unit_ids, '{}') loop
    select * into v_u from logistics.load_unit where id = v_x for update;
    if not found then raise exception 'Unité logistique introuvable.' using errcode = 'LG002'; end if;
    if not exists (select 1 from logistics.consolidation where load_unit_id = v_x) then raise exception 'L''unité % est vide : chargez-la d''abord.', v_u.code using errcode = 'LG005'; end if;
    if exists (select 1 from logistics.consolidation where load_unit_id = v_x and status <> 'CLOSED') then raise exception 'Une consolidation de cette unité n''est pas fermée.' using errcode = 'LG005'; end if;
    if exists (select 1 from logistics.consolidation where load_unit_id = v_x and mode <> p_mode) then
      raise exception 'L''unité % n''est pas en mode % : l''expédition et son contenu voyagent de la même façon.', v_u.code, p_mode using errcode = 'LG005';
    end if;
    if exists (select 1 from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id where i.load_unit_id = v_x and s.status not in ('CANCELLED') and s.id <> v_id) then
      raise exception 'Cette unité logistique est déjà dans une autre expédition.' using errcode = 'LG005';
    end if;
    insert into logistics.shipment_item (shipment_id, load_unit_id) values (v_id, v_x);
  end loop;
  foreach v_x in array coalesce(p_parcel_ids, '{}') loop
    select * into v_p from logistics.parcel where id = v_x for update;
    if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
    if v_p.status <> 'CONSOLIDATION_PENDING' or v_p.customer_id is null or v_p.service_mode <> p_mode then
      raise exception 'Le colis % ne peut pas partir en vrac (statut %, mode %, client %).', v_p.tracking_number, v_p.status, v_p.service_mode, case when v_p.customer_id is null then 'absent' else 'présent' end using errcode = 'LG005';
    end if;
    if exists (select 1 from logistics.consolidation_parcel where parcel_id = v_x and removed_at is null) then raise exception 'Le colis % est dans une consolidation : expédiez la consolidation.', v_p.tracking_number using errcode = 'LG005'; end if;
    perform logistics.transition_parcel(v_x, 'CONSOLIDATED', p_actor, null, v_corr, null, null, '', null, null, jsonb_build_object('shipment_id', v_id, 'loose', true), 'api');
    insert into logistics.shipment_item (shipment_id, parcel_id) values (v_id, v_x);
  end loop;

  v_label := coalesce((select email from auth.users where id = p_actor), '');
  insert into logistics.shipment_status_history (shipment_id, from_status, to_status, actor_user_id, actor_label, correlation_id) values (v_id, null, 'DRAFT', p_actor, v_label, v_corr);
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, v_label, 'shipment.create', 'shipment', v_id::text, jsonb_build_object('code', btrim(p_code), 'mode', p_mode), v_corr);
  perform logistics.emit('ShipmentCreated', 'shipment', v_id::text, v_corr, p_actor,
                         jsonb_build_object('shipment_id', v_id, 'code', btrim(p_code), 'mode', p_mode, 'destination_branch_id', p_destination_branch));
  v_out := jsonb_build_object('shipment_id', v_id, 'code', btrim(p_code), 'status', 'DRAFT', 'parcels', (select count(*) from logistics.shipment_parcels(v_id)), 'correlation_id', v_corr, 'replayed', false);
  return logistics.idem_end(p_idempotency_key, v_out);
end;
$$;


-- 5. Ce qui peut partir : les unités en plus (redéfinie depuis l'étape 024) -----------------------------------------------------------------
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


-- 6. Le transbordement : ce qui attend son étape suivante à un hub de transit ---------------------------------------------------------------
-- Les conditions de create_onward_shipment (016), lues au même endroit : un colis EN TRANSIT dont l'expédition courante est arrivée à ce hub.
create or replace function logistics.awaiting_onward(p_actor uuid, p_hub_branch uuid default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  return coalesce((select jsonb_agg(jsonb_build_object('parcel_id', x.id, 'tracking_number', x.tracking_number, 'mode', x.service_mode,
      'weight_lb', coalesce(x.verified_weight_lb, x.weight_lb), 'destination_country', x.destination_country, 'destination_city', x.destination_city,
      'customer', jsonb_build_object('code', c.code, 'name', c.full_name),
      'hub', jsonb_build_object('branch_id', b.id, 'code', b.code, 'country', b.country),
      'from_shipment', jsonb_build_object('shipment_id', s.id, 'code', s.code, 'status', s.status)) order by b.code, x.destination_country, x.tracking_number)
    from (select p.*, logistics.parcel_current_shipment(p.id) as courante from logistics.parcel p where p.status = 'IN_TRANSIT') x
    join logistics.shipment s on s.id = x.courante join logistics.branch b on b.id = s.destination_branch_id
    left join logistics.customer c on c.id = x.customer_id
   where s.status in ('ARRIVED', 'AT_HUB', 'CLOSED') and (p_hub_branch is null or b.id = p_hub_branch)), '[]'::jsonb);
end;
$$;


-- 7. Les façades, et tout le reste fermé --------------------------------------------------------------------------------------------------
create or replace function public.lg_consolidation_parcels(p_consolidation_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.consolidation_parcel_list(auth.uid(), p_consolidation_id) $$;
create or replace function public.lg_fill_consolidation(p_consolidation_id uuid, p_tracking_numbers text[])
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.fill_consolidation(auth.uid(), p_consolidation_id, p_tracking_numbers) $$;
create or replace function public.lg_cc_load_units(p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_load_units(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_remove_consolidation_from_load_unit(p_consolidation_id uuid, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.remove_consolidation_from_load_unit(auth.uid(), p_consolidation_id, p_reason) $$;
create or replace function public.lg_awaiting_onward(p_hub_branch uuid default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.awaiting_onward(auth.uid(), p_hub_branch) $$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('cc_consolidations', 'consolidation_parcel_list', 'fill_consolidation', 'load_unit_shipment', 'cc_load_units',
                                                            'put_consolidation_in_load_unit', 'remove_consolidation_from_load_unit', 'create_shipment', 'ready_for_shipment',
                                                            'awaiting_onward') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_consolidation_parcels', 'lg_fill_consolidation', 'lg_cc_load_units', 'lg_remove_consolidation_from_load_unit',
                                                         'lg_awaiting_onward') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
