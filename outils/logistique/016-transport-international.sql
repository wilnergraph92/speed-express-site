-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 16 : le transport international
-- -----------------------------------------------------------------------------
-- Phase 4. À coller dans Supabase > SQL Editor APRÈS 015, d'abord en PRÉPRODUCTION,
-- puis en production après une sauvegarde « avant migration » vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site » (ou la préproduction).
--
-- Miami → Haïti et Miami → République dominicaine, en avion, en bateau ou en camion,
-- en DIRECT ou avec TRANSBORDEMENT (Miami → Saint-Domingue en bateau, puis camion vers
-- Haïti : le colis reste « en transit » au hub intermédiaire et ne passe la douane qu'à
-- l'arrivée dans son pays). Ce que cette étape ajoute à l'étape 5, sans la réécrire :
--   1. consolidation : responsable, et sa fiche (nombre de colis, poids et volume totaux,
--      valeur, entrepôt source, unité logistique) ;
--   2. transport (vol, traversée, camion) : création par la façade, numéro de voyage,
--      fournisseur, dates prévues, CAPACITÉ en poids et en volume, vérifiée au départ ;
--   3. expédition : départ et arrivée prévus, hub de destination, fiche complète avec ses
--      étapes ; ÉTAPE SUIVANTE depuis un hub intermédiaire (create_onward_shipment) ;
--   4. unité logistique (palette, sac, conteneur, ULD) : création, chargement des
--      consolidations dans la limite du poids et du volume, SCELLÉ obligatoire au départ,
--      ouverture tracée (inspection) ;
--   5. douane : montant des droits (payés avant la libération), inspection, EXCEPTION par
--      colis (le colis est retenu ; levée, il reprend le flux ; saisi, il est perdu) ;
--   6. le SUIVI CLIENT : un parcours métier en huit étapes (Réception, Entrepôt,
--      Consolidation, Départ, Transit, Arrivée, Douane, Livraison), calculé ICI et rendu
--      tel quel aux écrans (lg_my_parcel_journey, lg_parcel_journey).
--
-- Fonctions redéfinies (copies de l'étape 5 ou 15, modifiées seulement là où c'est dit) :
-- cascade_parcels (même signature), arrive_shipment, receive_at_hub, dispatch_shipment, clear_customs.
-- Rejouable sans risque ; aucune donnée supprimée. Retour arrière : docs/architecture/TRANSPORT-INTERNATIONAL.md §8.
-- =============================================================================

-- 1. Le vocabulaire ------------------------------------------------------------------------------------------------
do $$
declare v_types text[];
begin
  select array_agg(distinct x order by x) into v_types
    from (select aggregate_type as x from logistics.event_type
          union select unnest(array['parcel', 'shipment', 'consolidation', 'warehouse', 'delivery', 'pickup', 'trip', 'task', 'driver', 'incident',
                                    'customs', 'invoice', 'payment', 'scan', 'quote', 'expense', 'pricing', 'request', 'ticket', 'load_unit', 'transport'])) t;
  alter table logistics.event_type drop constraint if exists event_type_aggregate_type_check;
  execute format('alter table logistics.event_type add constraint event_type_aggregate_type_check check (aggregate_type = any (%L::text[]))', v_types);
end
$$;
insert into logistics.event_type (code, aggregate_type, description) values
  ('ParcelTransitHubReached',          'parcel',        'Colis arrivé à un hub de transit (il continue vers son pays)'),
  ('ParcelTransshipped',               'parcel',        'Colis reparti d''un hub de transit (étape suivante)'),
  ('TransportCreated',                 'transport',     'Transport créé (vol, traversée, camion)'),
  ('TransportScheduled',               'transport',     'Horaires du transport modifiés'),
  ('ShipmentPlanned',                  'shipment',      'Dates prévues et hub de destination de l''expédition'),
  ('OnwardShipmentCreated',            'shipment',      'Étape suivante créée depuis un hub de transit'),
  ('ConsolidationResponsibleAssigned', 'consolidation', 'Responsable de la consolidation désigné'),
  ('LoadUnitCreated',                  'load_unit',     'Unité logistique créée'),
  ('LoadUnitLoaded',                   'load_unit',     'Consolidation chargée dans une unité logistique'),
  ('LoadUnitSealed',                   'load_unit',     'Unité logistique scellée'),
  ('LoadUnitOpened',                   'load_unit',     'Unité logistique ouverte (inspection)'),
  ('CustomsDutiesAssessed',            'customs',       'Droits et taxes de douane fixés'),
  ('CustomsDutiesPaid',                'customs',       'Droits et taxes de douane payés'),
  ('CustomsInspectionRecorded',        'customs',       'Inspection de douane'),
  ('CustomsExceptionRaised',           'customs',       'Exception de douane sur un colis'),
  ('CustomsExceptionResolved',         'customs',       'Exception de douane levée')
on conflict (code) do nothing;
-- Ce que le client voit dans son suivi daté (le parcours en huit étapes, lui, se calcule plus bas).
update logistics.event_type set customer_visible = true
 where code in ('ParcelTransitHubReached', 'ParcelTransshipped') and not customer_visible;

-- Une expédition dont tous les colis continuent ailleurs passe du statut « arrivée » au hub sans douane locale.
insert into logistics.shipment_transition (from_status, to_status, event_type, required_right) values
  ('ARRIVED', 'AT_HUB', 'ShipmentAtHub', 'colis.statut')
on conflict do nothing;


-- 2. Ce que les tables ne portaient pas -----------------------------------------------------------------------------
alter table logistics.consolidation add column if not exists responsible_user_id uuid references logistics.app_user (id) on delete restrict;

alter table logistics.transport add column if not exists voyage_number text not null default '';
alter table logistics.transport add column if not exists capacity_weight_lb numeric(12, 2) check (capacity_weight_lb is null or capacity_weight_lb > 0);
alter table logistics.transport add column if not exists capacity_volume_ft3 numeric(12, 3) check (capacity_volume_ft3 is null or capacity_volume_ft3 > 0);
comment on column logistics.transport.voyage_number is 'Numéro de vol, de voyage (navire) ou de tournée (camion).';

alter table logistics.shipment add column if not exists planned_departure_at timestamptz;
alter table logistics.shipment add column if not exists planned_arrival_at timestamptz;
alter table logistics.shipment add column if not exists destination_hub_warehouse_id uuid references logistics.warehouse (id) on delete restrict;
alter table logistics.shipment_item add column if not exists from_shipment_id uuid references logistics.shipment (id) on delete restrict;
comment on column logistics.shipment_item.from_shipment_id is 'Étape suivante : l''expédition qui a amené ce colis au hub intermédiaire.';

alter table logistics.load_unit add column if not exists max_volume_ft3 numeric(10, 3) check (max_volume_ft3 is null or max_volume_ft3 > 0);
alter table logistics.load_unit add column if not exists sealed_at timestamptz;
alter table logistics.load_unit add column if not exists sealed_by uuid references logistics.app_user (id) on delete restrict;
alter table logistics.load_unit add column if not exists opened_reason text;

alter table logistics.customs_declaration add column if not exists duties_amount numeric(14, 2) check (duties_amount is null or duties_amount >= 0);
alter table logistics.customs_declaration add column if not exists duties_currency text not null default 'USD' check (duties_currency in ('USD', 'DOP', 'HTG'));
alter table logistics.customs_declaration add column if not exists duties_assessed_at timestamptz;
alter table logistics.customs_declaration add column if not exists duties_paid_at timestamptz;

create table if not exists logistics.customs_inspection (
  id             uuid primary key default gen_random_uuid(),
  declaration_id uuid not null references logistics.customs_declaration (id) on delete restrict,
  inspected_at   timestamptz not null default now(),
  inspected_by   uuid references logistics.app_user (id) on delete restrict,
  result         text not null check (result in ('PASSED', 'ISSUES_FOUND')),
  parcels        text[] not null default '{}',
  notes          text not null default '' check (length(notes) <= 2000),
  correlation_id uuid not null
);
drop trigger if exists customs_inspection_append_only on logistics.customs_inspection;
create trigger customs_inspection_append_only before update or delete on logistics.customs_inspection for each row execute function logistics.forbid_mutation();

create table if not exists logistics.customs_exception (
  id             uuid primary key default gen_random_uuid(),
  declaration_id uuid not null references logistics.customs_declaration (id) on delete restrict,
  parcel_id      uuid not null references logistics.parcel (id) on delete restrict,
  kind           text not null check (kind in ('MISSING_DOCUMENT', 'UNDERVALUED', 'PROHIBITED_ITEM', 'DUTIES_UNPAID', 'INSPECTION_HOLD', 'SEIZED', 'OTHER')),
  description    text not null default '' check (length(description) <= 2000),
  status         text not null default 'OPEN' check (status in ('OPEN', 'RESOLVED')),
  outcome        text check (outcome in ('RELEASED', 'SEIZED')),
  raised_by      uuid references logistics.app_user (id) on delete restrict,
  raised_at      timestamptz not null default now(),
  resolved_by    uuid references logistics.app_user (id) on delete restrict,
  resolved_at    timestamptz,
  resolution     text,
  correlation_id uuid not null,
  check ((status = 'RESOLVED') = (resolved_at is not null and outcome is not null))
);
create index if not exists customs_exception_parcel_idx on logistics.customs_exception (parcel_id, status);
create unique index if not exists customs_exception_one_open on logistics.customs_exception (parcel_id) where status = 'OPEN';

do $$
declare t text;
begin
  foreach t in array array['customs_inspection', 'customs_exception'] loop
    execute format('revoke all on logistics.%I from public, anon, authenticated', t);
    execute format('alter table logistics.%I enable row level security', t);
  end loop;
end
$$;


-- 3. Les outils de calcul (lecture seule) ------------------------------------------------------------------------------
-- L'expédition COURANTE d'un colis : la plus récente qui le porte, hors annulées. Après un transbordement, c'est l'étape
-- suivante ; l'expédition d'avant ne le déplace plus.
create or replace function logistics.parcel_current_shipment(p_parcel uuid)
returns uuid language sql stable security definer set search_path = '' as $$
  select s.id from logistics.shipment s
   where s.id in (select x.shipment_id from logistics.shipments_of_parcel(p_parcel) x) and s.status <> 'CANCELLED'
     -- Celle qu'une étape suivante (non annulée) a prolongée pour ce colis n'est plus la sienne, quelle que soit l'horloge.
     and not exists (select 1 from logistics.shipment_item i join logistics.shipment n on n.id = i.shipment_id
                      where i.parcel_id = p_parcel and i.from_shipment_id = s.id and n.status <> 'CANCELLED')
   order by s.created_at desc, s.id desc limit 1
$$;

-- Une étape du voyage qui ne change pas le statut (hub de transit, transbordement) : suivi + audit + événement, même corrélation.
create or replace function logistics.record_parcel_milestone(p_parcel uuid, p_event text, p_actor uuid, p_corr uuid, p_place text, p_meta jsonb default '{}'::jsonb)
returns bigint language plpgsql volatile security definer set search_path = '' as $$
declare v_p logistics.parcel; v_te bigint; v_label text;
begin
  select * into v_p from logistics.parcel where id = p_parcel;
  v_label := coalesce((select email from auth.users where id = p_actor), 'system');
  insert into logistics.tracking_event (parcel_id, event_type, from_status, to_status, occurred_at, actor_user_id, actor_label, location_text, source, metadata, correlation_id)
  values (p_parcel, p_event, v_p.status, v_p.status, now(), p_actor, v_label, coalesce(p_place, ''), case when p_actor is null then 'system' else 'api' end,
          coalesce(p_meta, '{}'::jsonb), p_corr)
  returning id into v_te;
  update logistics.parcel set current_location = coalesce(nullif(p_place, ''), current_location) where id = p_parcel;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id, metadata)
  values (p_actor, v_label, 'parcel.milestone', 'parcel', p_parcel::text, jsonb_build_object('event', p_event, 'status', v_p.status, 'place', p_place), p_corr, coalesce(p_meta, '{}'::jsonb));
  insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_user_id, actor_label, payload)
  values (p_event, 'parcel', p_parcel::text, p_corr, p_actor, v_label,
          jsonb_build_object('parcel_id', p_parcel, 'tracking_number', v_p.tracking_number, 'status', v_p.status, 'place', p_place, 'tracking_event_id', v_te) || coalesce(p_meta, '{}'::jsonb));
  return v_te;
end;
$$;

create or replace function logistics.shipment_weight_lb(p_shipment uuid)
returns numeric language sql stable security definer set search_path = '' as $$
  select coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb, 0)), 0) from logistics.parcel p
   where p.id in (select parcel_id from logistics.shipment_parcels(p_shipment)) and logistics.parcel_current_shipment(p.id) = p_shipment
$$;
create or replace function logistics.shipment_volume_ft3(p_shipment uuid)
returns numeric language sql stable security definer set search_path = '' as $$
  select coalesce(sum(coalesce(p.volume_ft3, 0)), 0) from logistics.parcel p
   where p.id in (select parcel_id from logistics.shipment_parcels(p_shipment)) and logistics.parcel_current_shipment(p.id) = p_shipment
$$;
create or replace function logistics.transport_load_lb(p_transport uuid)
returns numeric language sql stable security definer set search_path = '' as $$
  select coalesce(sum(logistics.shipment_weight_lb(s.id)), 0) from logistics.shipment s where s.transport_id = p_transport and s.status <> 'CANCELLED'
$$;
create or replace function logistics.transport_volume_ft3(p_transport uuid)
returns numeric language sql stable security definer set search_path = '' as $$
  select coalesce(sum(logistics.shipment_volume_ft3(s.id)), 0) from logistics.shipment s where s.transport_id = p_transport and s.status <> 'CANCELLED'
$$;
create or replace function logistics.load_unit_contents(p_unit uuid)
returns table (parcels bigint, weight_lb numeric, volume_ft3 numeric, consolidations bigint)
language sql stable security definer set search_path = '' as $$
  select count(cp.id), coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb, 0)), 0), coalesce(sum(coalesce(p.volume_ft3, 0)), 0),
         (select count(*) from logistics.consolidation c2 where c2.load_unit_id = p_unit)
    from logistics.consolidation c join logistics.consolidation_parcel cp on cp.consolidation_id = c.id and cp.removed_at is null
    join logistics.parcel p on p.id = cp.parcel_id
   where c.load_unit_id = p_unit
$$;


-- 4. Consolidation -----------------------------------------------------------------------------------------------------
create or replace function logistics.consolidation_summary(p_actor uuid, p_consolidation uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c logistics.consolidation;
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  select * into v_c from logistics.consolidation where id = p_consolidation;
  if not found then raise exception 'Consolidation introuvable.' using errcode = 'LG002'; end if;
  return jsonb_build_object(
    'consolidation_id', v_c.id, 'code', v_c.code, 'status', v_c.status, 'mode', v_c.mode, 'destination_country', v_c.destination_country,
    'warehouse', (select jsonb_build_object('id', w.id, 'code', w.code, 'name', w.name) from logistics.warehouse w where w.id = v_c.warehouse_id),
    'responsible', (select jsonb_build_object('user_id', u.id, 'label', coalesce(au.email, ''), 'staff_code', u.staff_code)
                      from logistics.app_user u left join auth.users au on au.id = u.id where u.id = coalesce(v_c.responsible_user_id, v_c.created_by)),
    'parcels', (select count(*) from logistics.consolidation_parcel cp where cp.consolidation_id = v_c.id and cp.removed_at is null),
    'total_weight_lb', (select coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb, 0)), 0) from logistics.consolidation_parcel cp
                         join logistics.parcel p on p.id = cp.parcel_id where cp.consolidation_id = v_c.id and cp.removed_at is null),
    'total_volume_ft3', (select coalesce(sum(coalesce(p.volume_ft3, 0)), 0) from logistics.consolidation_parcel cp
                          join logistics.parcel p on p.id = cp.parcel_id where cp.consolidation_id = v_c.id and cp.removed_at is null),
    'declared_value', (select coalesce(sum(coalesce(p.declared_value, 0)), 0) from logistics.consolidation_parcel cp
                        join logistics.parcel p on p.id = cp.parcel_id where cp.consolidation_id = v_c.id and cp.removed_at is null),
    'load_unit', (select jsonb_build_object('code', l.code, 'kind', l.kind, 'status', l.status) from logistics.load_unit l where l.id = v_c.load_unit_id),
    'opened_at', v_c.opened_at, 'closed_at', v_c.closed_at);
end;
$$;

create or replace function logistics.assign_consolidation_responsible(p_actor uuid, p_consolidation uuid, p_user uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := gen_random_uuid(); v_avant uuid;
begin
  perform logistics.require_right(p_actor);
  if not exists (select 1 from logistics.app_user where id = p_user and active) then
    raise exception 'Le responsable doit être un membre actif de l''équipe.' using errcode = 'LG005';
  end if;
  select coalesce(responsible_user_id, created_by) into v_avant from logistics.consolidation where id = p_consolidation for update;
  if not found then raise exception 'Consolidation introuvable.' using errcode = 'LG002'; end if;
  update logistics.consolidation set responsible_user_id = p_user where id = p_consolidation;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'consolidation.responsible', 'consolidation', p_consolidation::text,
          jsonb_build_object('responsible', v_avant), jsonb_build_object('responsible', p_user), v_corr);
  perform logistics.emit('ConsolidationResponsibleAssigned', 'consolidation', p_consolidation::text, v_corr, p_actor,
                         jsonb_build_object('consolidation_id', p_consolidation, 'responsible', p_user));
  return logistics.consolidation_summary(p_actor, p_consolidation);
end;
$$;


-- 5. Transport -----------------------------------------------------------------------------------------------------------
create or replace function logistics.create_transport(p_actor uuid, p_mode text, p_carrier text, p_reference text, p_voyage_number text,
  p_origin_branch uuid, p_destination_branch uuid, p_planned_departure timestamptz, p_planned_arrival timestamptz,
  p_capacity_weight_lb numeric default null, p_capacity_volume_ft3 numeric default null, p_vehicle_label text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid; v_corr uuid := gen_random_uuid(); v_po text; v_pd text;
begin
  perform logistics.require_right(p_actor);
  if not exists (select 1 from logistics.transport_mode where code = p_mode and active) then raise exception 'Mode de transport inconnu : %.', p_mode using errcode = 'LG005'; end if;
  if btrim(coalesce(p_carrier, '')) = '' then raise exception 'Le fournisseur (compagnie, armateur, transporteur) est obligatoire.' using errcode = 'LG005'; end if;
  if btrim(coalesce(p_reference, '')) = '' and btrim(coalesce(p_voyage_number, '')) = '' then
    raise exception 'Une référence ou un numéro de voyage est obligatoire.' using errcode = 'LG005';
  end if;
  if p_planned_departure is null or p_planned_arrival is null or p_planned_arrival <= p_planned_departure then
    raise exception 'Dates prévues manquantes, ou arrivée avant le départ.' using errcode = 'LG005';
  end if;
  select country into v_po from logistics.branch where id = p_origin_branch and active;
  if not found then raise exception 'Succursale d''origine inconnue.' using errcode = 'LG005'; end if;
  select country into v_pd from logistics.branch where id = p_destination_branch and active;
  if not found then raise exception 'Succursale de destination inconnue.' using errcode = 'LG005'; end if;
  if p_origin_branch = p_destination_branch then raise exception 'Un transport relie deux succursales différentes.' using errcode = 'LG005'; end if;
  -- Par la route : seulement à l'intérieur de l'île (Haïti ↔ République dominicaine, ou dans un même pays). Miami ne se rejoint pas en camion.
  if p_mode = 'ground' and not (v_po in ('HT', 'DO') and v_pd in ('HT', 'DO')) and v_po <> v_pd then
    raise exception 'Un camion ne relie pas % et % : choisissez l''avion ou le bateau.', v_po, v_pd using errcode = 'LG005';
  end if;
  insert into logistics.transport (mode, carrier, reference, voyage_number, vehicle_label, origin_branch_id, destination_branch_id,
                                   planned_departure_at, planned_arrival_at, capacity_weight_lb, capacity_volume_ft3)
  values (p_mode, btrim(p_carrier), btrim(coalesce(p_reference, '')), upper(btrim(coalesce(p_voyage_number, ''))), btrim(coalesce(p_vehicle_label, '')),
          p_origin_branch, p_destination_branch, p_planned_departure, p_planned_arrival, p_capacity_weight_lb, p_capacity_volume_ft3)
  returning id into v_id;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'transport.create', 'transport', v_id::text,
          jsonb_build_object('mode', p_mode, 'carrier', p_carrier, 'voyage_number', p_voyage_number), v_corr);
  perform logistics.emit('TransportCreated', 'transport', v_id::text, v_corr, p_actor,
                         jsonb_build_object('transport_id', v_id, 'mode', p_mode, 'carrier', btrim(p_carrier), 'voyage_number', upper(btrim(coalesce(p_voyage_number, '')))));
  return jsonb_build_object('transport_id', v_id, 'status', 'PLANNED', 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.schedule_transport(p_actor uuid, p_transport uuid, p_planned_departure timestamptz, p_planned_arrival timestamptz)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_t logistics.transport; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  select * into v_t from logistics.transport where id = p_transport for update;
  if not found then raise exception 'Transport introuvable.' using errcode = 'LG002'; end if;
  if v_t.status <> 'PLANNED' then raise exception 'Le transport est % : ses horaires ne changent plus.', v_t.status using errcode = 'LG004'; end if;
  if p_planned_departure is null or p_planned_arrival is null or p_planned_arrival <= p_planned_departure then
    raise exception 'Dates prévues manquantes, ou arrivée avant le départ.' using errcode = 'LG005';
  end if;
  update logistics.transport set planned_departure_at = p_planned_departure, planned_arrival_at = p_planned_arrival where id = p_transport;
  perform logistics.emit('TransportScheduled', 'transport', p_transport::text, v_corr, p_actor,
                         jsonb_build_object('transport_id', p_transport, 'planned_departure_at', p_planned_departure, 'planned_arrival_at', p_planned_arrival));
  return jsonb_build_object('transport_id', p_transport, 'planned_departure_at', p_planned_departure, 'planned_arrival_at', p_planned_arrival);
end;
$$;


-- 6. Unités logistiques ----------------------------------------------------------------------------------------------------
create or replace function logistics.create_load_unit(p_actor uuid, p_code text, p_kind text, p_max_weight_lb numeric default null, p_max_volume_ft3 numeric default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  if btrim(coalesce(p_code, '')) = '' then raise exception 'Un code d''unité logistique est obligatoire.' using errcode = 'LG005'; end if;
  if p_kind not in ('CONTAINER', 'PALLET', 'ULD', 'BAG') then raise exception 'Type d''unité inconnu : % (CONTAINER, PALLET, ULD, BAG).', p_kind using errcode = 'LG005'; end if;
  insert into logistics.load_unit (code, kind, max_weight_lb, max_volume_ft3) values (upper(btrim(p_code)), p_kind, p_max_weight_lb, p_max_volume_ft3) returning id into v_id;
  perform logistics.emit('LoadUnitCreated', 'load_unit', v_id::text, v_corr, p_actor, jsonb_build_object('load_unit_id', v_id, 'code', upper(btrim(p_code)), 'kind', p_kind));
  return jsonb_build_object('load_unit_id', v_id, 'code', upper(btrim(p_code)), 'kind', p_kind, 'status', 'OPEN');
end;
$$;

create or replace function logistics.load_unit_summary(p_actor uuid, p_unit uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_u logistics.load_unit; v_x record;
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  select * into v_u from logistics.load_unit where id = p_unit;
  if not found then raise exception 'Unité logistique introuvable.' using errcode = 'LG002'; end if;
  select * into v_x from logistics.load_unit_contents(p_unit);
  return jsonb_build_object('load_unit_id', v_u.id, 'code', v_u.code, 'kind', v_u.kind, 'status', v_u.status, 'seal_number', v_u.seal_number,
    'sealed_at', v_u.sealed_at, 'opened_reason', v_u.opened_reason, 'max_weight_lb', v_u.max_weight_lb, 'max_volume_ft3', v_u.max_volume_ft3,
    'consolidations', v_x.consolidations, 'parcels', v_x.parcels, 'weight_lb', v_x.weight_lb, 'volume_ft3', v_x.volume_ft3);
end;
$$;

create or replace function logistics.put_consolidation_in_load_unit(p_actor uuid, p_consolidation uuid, p_unit uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c logistics.consolidation; v_u logistics.load_unit; v_x record; v_w numeric; v_v numeric; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  select * into v_u from logistics.load_unit where id = p_unit for update;
  if not found then raise exception 'Unité logistique introuvable.' using errcode = 'LG002'; end if;
  if v_u.status <> 'OPEN' then raise exception 'L''unité % est % : on n''y charge plus rien.', v_u.code, v_u.status using errcode = 'LG004'; end if;
  select * into v_c from logistics.consolidation where id = p_consolidation for update;
  if not found then raise exception 'Consolidation introuvable.' using errcode = 'LG002'; end if;
  if v_c.status <> 'CLOSED' then raise exception 'La consolidation % est % : il faut la FERMER avant de la charger.', v_c.code, v_c.status using errcode = 'LG005'; end if;
  if v_c.load_unit_id is not null then raise exception 'La consolidation % est déjà dans une unité logistique.', v_c.code using errcode = 'LG005'; end if;
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

create or replace function logistics.seal_load_unit(p_actor uuid, p_unit uuid, p_seal_number text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_u logistics.load_unit; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  select * into v_u from logistics.load_unit where id = p_unit for update;
  if not found then raise exception 'Unité logistique introuvable.' using errcode = 'LG002'; end if;
  if v_u.status = 'SEALED' then raise exception 'L''unité % est déjà scellée (scellé %).', v_u.code, v_u.seal_number using errcode = 'LG004'; end if;
  if btrim(coalesce(p_seal_number, '')) = '' then raise exception 'Le numéro du scellé est obligatoire.' using errcode = 'LG005'; end if;
  if not exists (select 1 from logistics.consolidation where load_unit_id = p_unit) then raise exception 'Une unité vide ne se scelle pas.' using errcode = 'LG005'; end if;
  update logistics.load_unit set status = 'SEALED', seal_number = upper(btrim(p_seal_number)), sealed_at = now(), sealed_by = p_actor, opened_reason = null where id = p_unit;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'load_unit.seal', 'load_unit', p_unit::text,
          jsonb_build_object('status', v_u.status, 'seal', v_u.seal_number), jsonb_build_object('status', 'SEALED', 'seal', upper(btrim(p_seal_number))), v_corr);
  perform logistics.emit('LoadUnitSealed', 'load_unit', p_unit::text, v_corr, p_actor, jsonb_build_object('load_unit_id', p_unit, 'seal_number', upper(btrim(p_seal_number))));
  return logistics.load_unit_summary(p_actor, p_unit);
end;
$$;

create or replace function logistics.open_load_unit(p_actor uuid, p_unit uuid, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_u logistics.load_unit; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  select * into v_u from logistics.load_unit where id = p_unit for update;
  if not found then raise exception 'Unité logistique introuvable.' using errcode = 'LG002'; end if;
  if v_u.status <> 'SEALED' then raise exception 'Seule une unité SCELLÉE s''ouvre (elle est %).', v_u.status using errcode = 'LG004'; end if;
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Le motif de l''ouverture est obligatoire (inspection, contrôle…).' using errcode = 'LG005'; end if;
  update logistics.load_unit set status = 'OPENED', opened_reason = left(btrim(p_reason), 500) where id = p_unit;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'load_unit.open', 'load_unit', p_unit::text,
          jsonb_build_object('status', 'SEALED', 'seal', v_u.seal_number), jsonb_build_object('status', 'OPENED', 'reason', p_reason), v_corr);
  perform logistics.emit('LoadUnitOpened', 'load_unit', p_unit::text, v_corr, p_actor, jsonb_build_object('load_unit_id', p_unit, 'seal_number', v_u.seal_number, 'reason', p_reason));
  return logistics.load_unit_summary(p_actor, p_unit);
end;
$$;


-- 7. Expédition : dates prévues, hub, étape suivante, fiche ------------------------------------------------------------
create or replace function logistics.plan_shipment(p_actor uuid, p_shipment uuid, p_planned_departure timestamptz, p_planned_arrival timestamptz,
                                                   p_hub_warehouse uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_s logistics.shipment; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  select * into v_s from logistics.shipment where id = p_shipment for update;
  if not found then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  if v_s.status not in ('DRAFT', 'READY') then raise exception 'L''expédition est % : son plan ne change plus.', v_s.status using errcode = 'LG004'; end if;
  if p_planned_departure is not null and p_planned_arrival is not null and p_planned_arrival <= p_planned_departure then
    raise exception 'L''arrivée prévue précède le départ prévu.' using errcode = 'LG005';
  end if;
  if p_hub_warehouse is not null and not exists (select 1 from logistics.warehouse w where w.id = p_hub_warehouse and w.active and w.branch_id = v_s.destination_branch_id) then
    raise exception 'Cet entrepôt n''est pas celui du hub de destination.' using errcode = 'LG005';
  end if;
  update logistics.shipment set planned_departure_at = p_planned_departure, planned_arrival_at = p_planned_arrival,
         destination_hub_warehouse_id = coalesce(p_hub_warehouse, destination_hub_warehouse_id) where id = p_shipment;
  perform logistics.emit('ShipmentPlanned', 'shipment', p_shipment::text, v_corr, p_actor,
                         jsonb_build_object('shipment_id', p_shipment, 'planned_departure_at', p_planned_departure, 'planned_arrival_at', p_planned_arrival));
  return logistics.shipment_summary(p_actor, p_shipment);
end;
$$;

-- L'ÉTAPE SUIVANTE : depuis un hub intermédiaire, une nouvelle expédition emmène des colis EN TRANSIT vers leur pays.
create or replace function logistics.create_onward_shipment(p_actor uuid, p_code text, p_mode text, p_origin_branch uuid, p_destination_branch uuid,
                                                            p_parcel_ids uuid[], p_idempotency_key text default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := gen_random_uuid(); v_prior jsonb; v_id uuid := gen_random_uuid(); v_x uuid; v_p logistics.parcel; v_avant uuid; v_s logistics.shipment;
        v_dest logistics.branch; v_label text; v_out jsonb;
begin
  perform logistics.require_right(p_actor);
  v_prior := logistics.idem_begin(p_idempotency_key, 'create_onward_shipment', md5(concat_ws('|', p_code, p_mode, p_origin_branch, p_destination_branch, p_parcel_ids::text)), p_code);
  if v_prior is not null then return v_prior; end if;
  if btrim(coalesce(p_code, '')) = '' then raise exception 'Un code d''expédition est obligatoire.' using errcode = 'LG005'; end if;
  if not exists (select 1 from logistics.transport_mode where code = p_mode and active) then raise exception 'Mode de transport inconnu : %.', p_mode using errcode = 'LG005'; end if;
  select * into v_dest from logistics.branch where id = p_destination_branch and active;
  if not found or v_dest.kind <> 'hub' then raise exception 'La destination d''une expédition est un HUB.' using errcode = 'LG005'; end if;
  if p_origin_branch = p_destination_branch then raise exception 'L''étape suivante part ailleurs que là où elle arrive.' using errcode = 'LG005'; end if;
  if coalesce(cardinality(p_parcel_ids), 0) = 0 then raise exception 'Une étape suivante emmène au moins un colis.' using errcode = 'LG005'; end if;
  insert into logistics.shipment (id, code, mode, origin_branch_id, destination_branch_id, created_by) values (v_id, btrim(p_code), p_mode, p_origin_branch, p_destination_branch, p_actor);
  foreach v_x in array p_parcel_ids loop
    select * into v_p from logistics.parcel where id = v_x for update;
    if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
    if v_p.status <> 'IN_TRANSIT' then raise exception 'Le colis % est en % : seule un colis EN TRANSIT au hub repart en étape suivante.', v_p.tracking_number, v_p.status using errcode = 'LG005'; end if;
    v_avant := logistics.parcel_current_shipment(v_x);
    select * into v_s from logistics.shipment where id = v_avant;
    if v_avant is null or v_avant = v_id or v_s.destination_branch_id <> p_origin_branch or v_s.status not in ('ARRIVED', 'AT_HUB', 'CLOSED') then
      raise exception 'Le colis % n''est pas arrivé à ce hub (son expédition courante : %).', v_p.tracking_number, coalesce(v_s.code, 'aucune') using errcode = 'LG005';
    end if;
    insert into logistics.shipment_item (shipment_id, parcel_id, from_shipment_id) values (v_id, v_x, v_avant);
  end loop;
  v_label := coalesce((select email from auth.users where id = p_actor), '');
  insert into logistics.shipment_status_history (shipment_id, from_status, to_status, actor_user_id, actor_label, correlation_id) values (v_id, null, 'DRAFT', p_actor, v_label, v_corr);
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, v_label, 'shipment.create_onward', 'shipment', v_id::text, jsonb_build_object('code', btrim(p_code), 'mode', p_mode, 'parcels', cardinality(p_parcel_ids)), v_corr);
  perform logistics.emit('OnwardShipmentCreated', 'shipment', v_id::text, v_corr, p_actor,
                         jsonb_build_object('shipment_id', v_id, 'code', btrim(p_code), 'mode', p_mode, 'origin_branch_id', p_origin_branch, 'destination_branch_id', p_destination_branch));
  v_out := jsonb_build_object('shipment_id', v_id, 'code', btrim(p_code), 'status', 'DRAFT', 'parcels', cardinality(p_parcel_ids), 'correlation_id', v_corr, 'replayed', false);
  return logistics.idem_end(p_idempotency_key, v_out);
end;
$$;

create or replace function logistics.shipment_summary(p_actor uuid, p_shipment uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_s logistics.shipment;
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  select * into v_s from logistics.shipment where id = p_shipment;
  if not found then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  return jsonb_build_object(
    'shipment_id', v_s.id, 'code', v_s.code, 'mode', v_s.mode, 'status', v_s.status,
    'origin', (select jsonb_build_object('code', b.code, 'label', logistics.branch_label(b.id), 'country', b.country) from logistics.branch b where b.id = v_s.origin_branch_id),
    'destination', (select jsonb_build_object('code', b.code, 'label', logistics.branch_label(b.id), 'country', b.country) from logistics.branch b where b.id = v_s.destination_branch_id),
    'hub_warehouse', (select jsonb_build_object('code', w.code, 'name', w.name) from logistics.warehouse w where w.id = v_s.destination_hub_warehouse_id),
    'planned_departure_at', coalesce(v_s.planned_departure_at, (select planned_departure_at from logistics.transport where id = v_s.transport_id)),
    'planned_arrival_at', coalesce(v_s.planned_arrival_at, (select planned_arrival_at from logistics.transport where id = v_s.transport_id)),
    'dispatched_at', v_s.dispatched_at, 'arrived_at', v_s.arrived_at,
    'transport', (select jsonb_build_object('mode', t.mode, 'carrier', t.carrier, 'reference', t.reference, 'voyage_number', t.voyage_number, 'status', t.status,
                                            'planned_departure_at', t.planned_departure_at, 'planned_arrival_at', t.planned_arrival_at,
                                            'actual_departure_at', t.actual_departure_at, 'actual_arrival_at', t.actual_arrival_at,
                                            'capacity_weight_lb', t.capacity_weight_lb, 'capacity_volume_ft3', t.capacity_volume_ft3,
                                            'load_weight_lb', logistics.transport_load_lb(t.id))
                    from logistics.transport t where t.id = v_s.transport_id),
    'parcels', (select count(*) from logistics.shipment_parcels(v_s.id) x where logistics.parcel_current_shipment(x.parcel_id) = v_s.id),
    'moved_on', (select count(*) from logistics.shipment_parcels(v_s.id) x where logistics.parcel_current_shipment(x.parcel_id) <> v_s.id),
    'weight_lb', logistics.shipment_weight_lb(v_s.id), 'volume_ft3', logistics.shipment_volume_ft3(v_s.id),
    'by_destination', coalesce((select jsonb_object_agg(d, n) from (select p.destination_country d, count(*) n from logistics.parcel p
                                  where p.id in (select parcel_id from logistics.shipment_parcels(v_s.id)) and logistics.parcel_current_shipment(p.id) = v_s.id group by 1) z), '{}'::jsonb),
    'load_units', coalesce((select jsonb_agg(jsonb_build_object('code', l.code, 'kind', l.kind, 'status', l.status, 'seal_number', l.seal_number) order by l.code)
                              from logistics.load_unit l where l.id in (select i.load_unit_id from logistics.shipment_item i where i.shipment_id = v_s.id
                                                                        union select c.load_unit_id from logistics.shipment_item i join logistics.consolidation c on c.id = i.consolidation_id where i.shipment_id = v_s.id)), '[]'::jsonb),
    'previous_legs', coalesce((select jsonb_agg(distinct s2.code) from logistics.shipment_item i join logistics.shipment s2 on s2.id = i.from_shipment_id where i.shipment_id = v_s.id), '[]'::jsonb),
    'onward_legs', coalesce((select jsonb_agg(distinct s2.code) from logistics.shipment_item i join logistics.shipment s2 on s2.id = i.shipment_id where i.from_shipment_id = v_s.id), '[]'::jsonb),
    'customs', (select jsonb_build_object('reference', d.reference, 'status', d.status, 'declared_value', d.declared_value, 'currency', d.currency,
                                          'duties_amount', d.duties_amount, 'duties_currency', d.duties_currency, 'duties_paid', d.duties_paid_at is not null,
                                          'documents', (select count(*) from logistics.customs_document x where x.declaration_id = d.id),
                                          'inspections', (select count(*) from logistics.customs_inspection x where x.declaration_id = d.id),
                                          'open_exceptions', (select count(*) from logistics.customs_exception x where x.declaration_id = d.id and x.status = 'OPEN'))
                  from logistics.customs_declaration d where d.shipment_id = v_s.id order by d.created_at desc limit 1));
end;
$$;


-- 8. Douane : droits, inspection, exceptions -----------------------------------------------------------------------------
create or replace function logistics.current_declaration(p_shipment uuid)
returns logistics.customs_declaration language sql stable security definer set search_path = '' as $$
  select * from logistics.customs_declaration where shipment_id = p_shipment and status in ('SUBMITTED', 'UNDER_REVIEW') order by created_at desc limit 1
$$;

create or replace function logistics.customs_assess_duties(p_actor uuid, p_shipment uuid, p_amount numeric, p_currency text default 'USD')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d logistics.customs_declaration; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  v_d := logistics.current_declaration(p_shipment);
  if v_d.id is null then raise exception 'Aucune déclaration en cours pour cette expédition.' using errcode = 'LG002'; end if;
  if p_amount is null or p_amount < 0 then raise exception 'Montant des droits invalide.' using errcode = 'LG005'; end if;
  if p_currency not in ('USD', 'DOP', 'HTG') then raise exception 'Devise inconnue : %.', p_currency using errcode = 'LG005'; end if;
  update logistics.customs_declaration set duties_amount = p_amount, duties_currency = p_currency, duties_assessed_at = now(),
         duties_paid_at = case when p_amount = 0 then now() else null end where id = v_d.id;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'customs.duties', 'customs', v_d.id::text,
          jsonb_build_object('duties', v_d.duties_amount), jsonb_build_object('duties', p_amount, 'currency', p_currency), v_corr);
  perform logistics.emit('CustomsDutiesAssessed', 'customs', v_d.id::text, v_corr, p_actor, jsonb_build_object('declaration_id', v_d.id, 'amount', p_amount, 'currency', p_currency));
  return logistics.shipment_summary(p_actor, p_shipment) -> 'customs';
end;
$$;

create or replace function logistics.customs_mark_duties_paid(p_actor uuid, p_shipment uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d logistics.customs_declaration; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  v_d := logistics.current_declaration(p_shipment);
  if v_d.id is null then raise exception 'Aucune déclaration en cours pour cette expédition.' using errcode = 'LG002'; end if;
  if v_d.duties_amount is null then raise exception 'Les droits ne sont pas encore fixés.' using errcode = 'LG005'; end if;
  if v_d.duties_paid_at is not null then raise exception 'Les droits sont déjà payés.' using errcode = 'LG004'; end if;
  update logistics.customs_declaration set duties_paid_at = now() where id = v_d.id;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'customs.duties_paid', 'customs', v_d.id::text,
          jsonb_build_object('amount', v_d.duties_amount, 'currency', v_d.duties_currency), v_corr);
  perform logistics.emit('CustomsDutiesPaid', 'customs', v_d.id::text, v_corr, p_actor, jsonb_build_object('declaration_id', v_d.id, 'amount', v_d.duties_amount, 'currency', v_d.duties_currency));
  return logistics.shipment_summary(p_actor, p_shipment) -> 'customs';
end;
$$;

create or replace function logistics.customs_inspect(p_actor uuid, p_shipment uuid, p_result text, p_notes text default '', p_tracking_numbers text[] default '{}')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d logistics.customs_declaration; v_corr uuid := gen_random_uuid(); v_id uuid;
begin
  perform logistics.require_right(p_actor);
  v_d := logistics.current_declaration(p_shipment);
  if v_d.id is null then raise exception 'Aucune déclaration en cours pour cette expédition.' using errcode = 'LG002'; end if;
  if p_result not in ('PASSED', 'ISSUES_FOUND') then raise exception 'Résultat d''inspection inconnu : %.', p_result using errcode = 'LG005'; end if;
  insert into logistics.customs_inspection (declaration_id, inspected_by, result, parcels, notes, correlation_id)
  values (v_d.id, p_actor, p_result, coalesce(p_tracking_numbers, '{}'), left(coalesce(p_notes, ''), 2000), v_corr) returning id into v_id;
  update logistics.customs_declaration set status = 'UNDER_REVIEW' where id = v_d.id and status = 'SUBMITTED';
  perform logistics.emit('CustomsInspectionRecorded', 'customs', v_d.id::text, v_corr, p_actor,
                         jsonb_build_object('declaration_id', v_d.id, 'inspection_id', v_id, 'result', p_result, 'parcels', coalesce(p_tracking_numbers, '{}')));
  return jsonb_build_object('inspection_id', v_id, 'declaration_status', 'UNDER_REVIEW', 'result', p_result);
end;
$$;

-- Une EXCEPTION de douane retient UN colis (en attente, motif « Douane : … ») ; le reste de l'expédition suit son cours.
create or replace function logistics.customs_raise_exception(p_actor uuid, p_shipment uuid, p_parcel uuid, p_kind text, p_description text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d logistics.customs_declaration; v_p logistics.parcel; v_corr uuid := gen_random_uuid(); v_id uuid;
begin
  perform logistics.require_right(p_actor);
  v_d := logistics.current_declaration(p_shipment);
  if v_d.id is null then raise exception 'Aucune déclaration en cours pour cette expédition.' using errcode = 'LG002'; end if;
  select * into v_p from logistics.parcel where id = p_parcel for update;
  if not found or logistics.parcel_current_shipment(p_parcel) is distinct from p_shipment then
    raise exception 'Ce colis n''est pas dans cette expédition.' using errcode = 'LG002';
  end if;
  if v_p.status <> 'CUSTOMS_PROCESSING' then raise exception 'Le colis % est en % : une exception de douane vise un colis EN DOUANE.', v_p.tracking_number, v_p.status using errcode = 'LG005'; end if;
  if btrim(coalesce(p_description, '')) = '' then raise exception 'Une description est obligatoire.' using errcode = 'LG005'; end if;
  insert into logistics.customs_exception (declaration_id, parcel_id, kind, description, raised_by, correlation_id)
  values (v_d.id, p_parcel, p_kind, left(btrim(p_description), 2000), p_actor, v_corr) returning id into v_id;
  perform logistics.transition_parcel(p_parcel, 'ON_HOLD', p_actor, null, v_corr, null, null, '', null, 'Douane : ' || p_kind || ' — ' || left(btrim(p_description), 200),
                                      jsonb_build_object('customs_exception_id', v_id), 'api');
  perform logistics.emit('CustomsExceptionRaised', 'customs', v_d.id::text, v_corr, p_actor,
                         jsonb_build_object('declaration_id', v_d.id, 'exception_id', v_id, 'parcel_id', p_parcel, 'kind', p_kind));
  return jsonb_build_object('exception_id', v_id, 'parcel_status', 'ON_HOLD', 'kind', p_kind);
end;
$$;

-- Lever l'exception (direction) : LIBÉRÉ, le colis reprend là où en est son expédition ; SAISI, il est perdu pour le client.
create or replace function logistics.customs_resolve_exception(p_actor uuid, p_exception uuid, p_outcome text, p_resolution text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_x logistics.customs_exception; v_s logistics.shipment; v_corr uuid := gen_random_uuid(); v_hub uuid;
begin
  perform logistics.require_right(p_actor, 'direction');
  select * into v_x from logistics.customs_exception where id = p_exception for update;
  if not found then raise exception 'Exception introuvable.' using errcode = 'LG002'; end if;
  if v_x.status <> 'OPEN' then raise exception 'Cette exception est déjà levée.' using errcode = 'LG004'; end if;
  if p_outcome not in ('RELEASED', 'SEIZED') then raise exception 'Issue inconnue : % (RELEASED ou SEIZED).', p_outcome using errcode = 'LG005'; end if;
  if btrim(coalesce(p_resolution, '')) = '' then raise exception 'La décision doit être expliquée.' using errcode = 'LG005'; end if;
  update logistics.customs_exception set status = 'RESOLVED', outcome = p_outcome, resolution = left(btrim(p_resolution), 2000),
         resolved_by = p_actor, resolved_at = now() where id = p_exception;
  if p_outcome = 'SEIZED' then
    perform logistics.transition_parcel(v_x.parcel_id, 'LOST', p_actor, null, v_corr, null, null, '', null, 'Saisi par la douane : ' || left(btrim(p_resolution), 200),
                                        jsonb_build_object('customs_exception_id', p_exception), 'api');
  else
    perform logistics.transition_parcel(v_x.parcel_id, 'CUSTOMS_PROCESSING', p_actor, null, v_corr, null, null, '', null, null,
                                        jsonb_build_object('customs_exception_id', p_exception), 'api');
    -- L'expédition a peut-être continué sans lui : il la rejoint là où elle en est.
    select s.* into v_s from logistics.customs_declaration d join logistics.shipment s on s.id = d.shipment_id where d.id = v_x.declaration_id;
    if v_s.status in ('CUSTOMS_CLEARED', 'AT_HUB', 'CLOSED') then
      perform logistics.transition_parcel(v_x.parcel_id, 'CUSTOMS_CLEARED', p_actor, null, v_corr, null, null, '', null, null, jsonb_build_object('customs_exception_id', p_exception), 'api');
    end if;
    if v_s.status in ('AT_HUB', 'CLOSED') then
      v_hub := coalesce(v_s.destination_hub_warehouse_id, (select w.id from logistics.warehouse w where w.branch_id = v_s.destination_branch_id and w.active order by w.code limit 1));
      perform logistics.transition_parcel(v_x.parcel_id, 'AT_DESTINATION_HUB', p_actor, null, v_corr, v_hub, null, '', null, null, jsonb_build_object('customs_exception_id', p_exception), 'api');
    end if;
  end if;
  perform logistics.emit('CustomsExceptionResolved', 'customs', v_x.declaration_id::text, v_corr, p_actor,
                         jsonb_build_object('exception_id', p_exception, 'parcel_id', v_x.parcel_id, 'outcome', p_outcome));
  return jsonb_build_object('exception_id', p_exception, 'outcome', p_outcome, 'parcel_status', (select status from logistics.parcel where id = v_x.parcel_id));
end;
$$;


-- 9. Les fonctions de l'étape 5 (et 15), complétées -----------------------------------------------------------------------
create or replace function logistics.cascade_parcels(p_shipment_id uuid, p_from text, p_to text, p_actor uuid, p_corr uuid, p_warehouse uuid default null)
returns jsonb language plpgsql volatile set search_path = '' as $$
declare r record; v_done int := 0; v_skipped jsonb := '[]'::jsonb; v_charges int := 0; v_sans_scan int := 0; v_transbordes int := 0; v_ailleurs jsonb := '[]'::jsonb;
begin
  for r in select p.id, p.status, p.tracking_number from logistics.parcel p where p.id in (select parcel_id from logistics.shipment_parcels(p_shipment_id))
               -- À l'arrivée, seuls les colis arrivés DANS LEUR PAYS passent « arrivé » ; les autres sont en transit à ce hub.
               and (p_to <> 'ARRIVED' or p.destination_country is not distinct from
                    (select b.country from logistics.shipment s join logistics.branch b on b.id = s.destination_branch_id where s.id = p_shipment_id)) order by p.tracking_number loop
    -- Un colis passé à une étape suivante (transbordement) n'appartient plus à cette expédition-ci : elle ne le déplace plus.
    if logistics.parcel_current_shipment(r.id) is distinct from p_shipment_id then
      v_ailleurs := v_ailleurs || jsonb_build_object('tracking_number', r.tracking_number, 'status', r.status);
      continue;
    end if;
    if r.status = 'IN_TRANSIT' and p_from = 'READY_FOR_EXPORT' and p_to = 'IN_TRANSIT' then
      -- Départ d'une ÉTAPE SUIVANTE : le colis, déjà en transit, repart du hub intermédiaire.
      perform logistics.record_parcel_milestone(r.id, 'ParcelTransshipped', p_actor, p_corr,
                                                (select logistics.branch_label(s.origin_branch_id) from logistics.shipment s where s.id = p_shipment_id),
                                                jsonb_build_object('shipment_id', p_shipment_id));
      v_transbordes := v_transbordes + 1;
      v_done := v_done + 1;
      continue;
    end if;
    if r.status = p_from then
      perform logistics.transition_parcel(r.id, p_to, p_actor, null, p_corr, p_warehouse, null, '', null, null,
                                          jsonb_build_object('shipment_id', p_shipment_id), 'api');
      v_done := v_done + 1;
      if p_from = 'READY_FOR_EXPORT' and p_to = 'IN_TRANSIT' then v_sans_scan := v_sans_scan + 1; end if;
    elsif r.status = 'LOADED' and p_from = 'READY_FOR_EXPORT' then
      -- Un colis CHARGÉ part avec son expédition ; si elle est rouverte ou annulée, il est d'abord déchargé.
      if p_to = 'IN_TRANSIT' then
        perform logistics.transition_parcel(r.id, 'IN_TRANSIT', p_actor, null, p_corr, p_warehouse, null, '', null, null,
                                            jsonb_build_object('shipment_id', p_shipment_id), 'api');
        v_charges := v_charges + 1;
      else
        perform logistics.transition_parcel(r.id, 'READY_FOR_EXPORT', p_actor, null, p_corr, p_warehouse, null, '', null,
                                            'Expédition rouverte ou annulée : colis déchargé', jsonb_build_object('shipment_id', p_shipment_id), 'api');
        perform logistics.transition_parcel(r.id, p_to, p_actor, null, p_corr, p_warehouse, null, '', null, null,
                                            jsonb_build_object('shipment_id', p_shipment_id), 'api');
      end if;
      v_done := v_done + 1;
    else
      v_skipped := v_skipped || jsonb_build_object('tracking_number', r.tracking_number, 'status', r.status);
    end if;
  end loop;
  return jsonb_build_object('moved', v_done, 'skipped', v_skipped, 'loaded', v_charges, 'not_scanned_at_loading', v_sans_scan,
                            'transshipped', v_transbordes, 'moved_on', v_ailleurs);
end;
$$;

create or replace function logistics.arrive_shipment(p_shipment_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_s logistics.shipment; v_c jsonb; v_pays text; v_lieu text; r record; v_transit int := 0;
begin
  perform logistics.require_right(p_actor);
  v_s := logistics.move_shipment(p_shipment_id, 'ARRIVED', p_actor, v_corr);
  select b.country, logistics.branch_label(b.id) into v_pays, v_lieu from logistics.branch b where b.id = v_s.destination_branch_id;
  -- Les colis dont le pays de destination n'est pas celui du hub d'arrivée y sont EN TRANSIT : un événement, pas de changement de
  -- statut, ni douane ni hub local ; une étape suivante (create_onward_shipment) les emmènera.
  for r in select p.id from logistics.parcel p
            where p.id in (select parcel_id from logistics.shipment_parcels(p_shipment_id)) and p.status = 'IN_TRANSIT'
              and p.destination_country is distinct from v_pays and logistics.parcel_current_shipment(p.id) = p_shipment_id loop
    perform logistics.record_parcel_milestone(r.id, 'ParcelTransitHubReached', p_actor, v_corr, v_lieu, jsonb_build_object('shipment_id', p_shipment_id));
    v_transit := v_transit + 1;
  end loop;
  v_c := logistics.cascade_parcels(p_shipment_id, 'IN_TRANSIT', 'ARRIVED', p_actor, v_corr);
  -- Le transport est arrivé quand TOUTES ses expéditions le sont.
  update logistics.transport t set status = 'ARRIVED', actual_arrival_at = now()
   where t.id = v_s.transport_id and t.status = 'DEPARTED'
     and not exists (select 1 from logistics.shipment x where x.transport_id = t.id and x.status in ('DISPATCHED', 'IN_TRANSIT'));
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'ARRIVED', 'parcels', v_c, 'in_transit_here', v_transit, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.receive_at_hub(p_shipment_id uuid, p_actor uuid, p_hub_warehouse_id uuid default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_s logistics.shipment; v_c jsonb;
begin
  perform logistics.require_right(p_actor);
  select * into v_s from logistics.shipment where id = p_shipment_id;
  if not found then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  if p_hub_warehouse_id is not null and not exists (select 1 from logistics.warehouse w where w.id = p_hub_warehouse_id and w.active and w.branch_id = v_s.destination_branch_id) then
    raise exception 'Cet entrepôt n''est pas celui du hub de destination.' using errcode = 'LG005';
  end if;
  if v_s.status = 'ARRIVED' and exists (select 1 from logistics.parcel p where p.id in (select parcel_id from logistics.shipment_parcels(p_shipment_id))
                                           and p.status in ('ARRIVED', 'CUSTOMS_PROCESSING') and logistics.parcel_current_shipment(p.id) = p_shipment_id) then
    raise exception 'Des colis de cette expédition doivent d''abord passer la douane de ce pays.' using errcode = 'LG005';
  end if;
  perform logistics.move_shipment(p_shipment_id, 'AT_HUB', p_actor, v_corr);
  v_c := logistics.cascade_parcels(p_shipment_id, 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB', p_actor, v_corr, coalesce(p_hub_warehouse_id, v_s.destination_hub_warehouse_id));
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'AT_HUB', 'parcels', v_c, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.dispatch_shipment(p_shipment_id uuid, p_transport_id uuid, p_actor uuid, p_idempotency_key text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_prior jsonb; v_s logistics.shipment; v_t logistics.transport; v_c jsonb; v_out jsonb;
begin
  perform logistics.require_right(p_actor);
  v_prior := logistics.idem_begin(p_idempotency_key, 'dispatch_shipment', md5(p_shipment_id::text || coalesce(p_transport_id::text, '')), p_shipment_id::text);
  if v_prior is not null then return v_prior; end if;
  select * into v_s from logistics.shipment where id = p_shipment_id for update;
  if not found then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  if v_s.status <> 'READY' then raise exception 'Seule une expédition PRÊTE peut partir (elle est %).', v_s.status using errcode = 'LG001'; end if;
  select * into v_t from logistics.transport where id = p_transport_id for update;
  if not found then raise exception 'Transport introuvable.' using errcode = 'LG002'; end if;
  if v_t.status not in ('PLANNED', 'DEPARTED') then raise exception 'Le transport est % : on n''y charge plus.', v_t.status using errcode = 'LG005'; end if;
  if v_t.mode <> v_s.mode then raise exception 'Le transport est en mode %, l''expédition en %.', v_t.mode, v_s.mode using errcode = 'LG005'; end if;
  if exists (select 1 from logistics.load_unit l where l.status <> 'SEALED' and l.id in (
               select i.load_unit_id from logistics.shipment_item i where i.shipment_id = p_shipment_id
               union select c.load_unit_id from logistics.shipment_item i join logistics.consolidation c on c.id = i.consolidation_id where i.shipment_id = p_shipment_id)) then
    raise exception 'Une unité logistique de l''expédition n''est pas scellée : scellez-la avant le départ.' using errcode = 'LG005';
  end if;
  if v_t.capacity_weight_lb is not null and logistics.transport_load_lb(p_transport_id) + logistics.shipment_weight_lb(p_shipment_id) > v_t.capacity_weight_lb then
    raise exception 'Capacité du transport dépassée : % lb chargées + % lb de cette expédition > % lb.', logistics.transport_load_lb(p_transport_id),
      logistics.shipment_weight_lb(p_shipment_id), v_t.capacity_weight_lb using errcode = 'LG005';
  end if;
  if v_t.capacity_volume_ft3 is not null and logistics.transport_volume_ft3(p_transport_id) + logistics.shipment_volume_ft3(p_shipment_id) > v_t.capacity_volume_ft3 then
    raise exception 'Volume du transport dépassé (% ft³ disponibles).', v_t.capacity_volume_ft3 - logistics.transport_volume_ft3(p_transport_id) using errcode = 'LG005';
  end if;
  if not logistics.manifest_is_fresh(p_shipment_id) then raise exception 'Le manifeste est périmé (le contenu a changé depuis sa génération) : régénérez-le.' using errcode = 'LG005'; end if;
  update logistics.shipment set transport_id = p_transport_id where id = p_shipment_id;
  perform logistics.move_shipment(p_shipment_id, 'DISPATCHED', p_actor, v_corr, null, jsonb_build_object('transport_id', p_transport_id));
  update logistics.transport set status = 'DEPARTED', actual_departure_at = coalesce(actual_departure_at, now()) where id = p_transport_id and status = 'PLANNED';
  v_c := logistics.cascade_parcels(p_shipment_id, 'READY_FOR_EXPORT', 'IN_TRANSIT', p_actor, v_corr);
  v_out := jsonb_build_object('shipment_id', p_shipment_id, 'status', 'DISPATCHED', 'transport_id', p_transport_id, 'parcels', v_c, 'correlation_id', v_corr, 'replayed', false);
  return logistics.idem_end(p_idempotency_key, v_out);
end;
$$;

create or replace function logistics.clear_customs(p_shipment_id uuid, p_actor uuid, p_reference text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_d uuid; v_c jsonb;
begin
  perform logistics.require_right(p_actor);
  select id into v_d from logistics.customs_declaration where shipment_id = p_shipment_id and status in ('SUBMITTED', 'UNDER_REVIEW') for update;
  if not found then raise exception 'Aucune déclaration en cours pour cette expédition.' using errcode = 'LG002'; end if;
  if exists (select 1 from logistics.customs_declaration d where d.id = v_d and d.duties_amount is not null and d.duties_paid_at is null) then
    raise exception 'Les droits de douane fixés ne sont pas payés : la marchandise ne peut pas être libérée.' using errcode = 'LG005';
  end if;
  perform logistics.move_shipment(p_shipment_id, 'CUSTOMS_CLEARED', p_actor, v_corr, null, jsonb_build_object('declaration_id', v_d));
  update logistics.customs_declaration set status = 'CLEARED', cleared_at = now(), reference = coalesce(nullif(p_reference, ''), reference) where id = v_d;
  v_c := logistics.cascade_parcels(p_shipment_id, 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', p_actor, v_corr);
  perform logistics.emit('CustomsDeclarationCleared', 'customs', v_d::text, v_corr, p_actor, jsonb_build_object('declaration_id', v_d, 'shipment_id', p_shipment_id));
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'CUSTOMS_CLEARED', 'declaration_id', v_d, 'parcels', v_c, 'correlation_id', v_corr);
end;
$$;


-- 10. Le parcours du client : huit étapes, calculées ici -----------------------------------------------------------------
-- Chaque étape : « done » (franchie), « current » (en cours), « upcoming » (à venir), « stopped » (le voyage s'est arrêté avant).
-- Une étape franchie sans trace propre (un colis repris de l'ancien schéma, par exemple) est « done » sans date.
-- L'écran affiche ce qu'il reçoit : il ne recalcule ni l'étape, ni l'état, ni l'exception.
create or replace function logistics.parcel_journey(p_parcel uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  v_p logistics.parcel;
  v_cles text[] := array['reception', 'warehouse', 'consolidation', 'departure', 'transit', 'arrival', 'customs', 'delivery'];
  v_statuts text[][] := array[
    array['RECEIVED', '', '', ''],
    array['VERIFIED', 'STORED', '', ''],
    array['CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'LOADED'],
    array['IN_TRANSIT', '', '', ''],
    array['IN_TRANSIT', '', '', ''],
    array['ARRIVED', '', '', ''],
    array['CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', '', ''],
    array['AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY', 'DELIVERED']];
  v_rang_actuel int := 0;   -- l'étape la plus avancée atteinte (1 à 8 ; 0 = enregistré seulement)
  v_premier timestamptz[] := array[null, null, null, null, null, null, null, null]::timestamptz[];
  v_lieu text[] := array[null, null, null, null, null, null, null, null]::text[];
  r record; i int; v_etat text; v_etapes jsonb := '[]'::jsonb; v_arret text; v_depart jsonb; v_transit jsonb; v_terminee boolean;
begin
  select * into v_p from logistics.parcel where id = p_parcel;
  if not found then return null; end if;
  -- Le chemin réel : chaque statut atteint, dans l'ordre, avec sa date et son lieu.
  for r in select e.to_status, e.occurred_at, e.event_type,
                  coalesce(nullif(e.location_text, ''), (select logistics.branch_label(w.branch_id) from logistics.warehouse w where w.id = e.warehouse_id)) as lieu
             from logistics.tracking_event e where e.parcel_id = p_parcel order by e.occurred_at, e.id loop
    -- « Transit » se date par le premier hub intermédiaire (un vol direct n'en a pas : l'étape est franchie sans date propre).
    if r.event_type in ('ParcelTransitHubReached', 'ParcelTransshipped') then
      if v_premier[5] is null then v_premier[5] := r.occurred_at; v_lieu[5] := r.lieu; end if;
      continue;
    end if;
    for i in 1 .. 8 loop
      continue when i = 5;
      if r.to_status = any (v_statuts[i:i][1:4]) then
        if v_premier[i] is null then v_premier[i] := r.occurred_at; v_lieu[i] := r.lieu; end if;
        if i > v_rang_actuel then v_rang_actuel := i; end if;
      end if;
    end loop;
  end loop;
  -- Le statut présent fait foi (un colis repris de l'ancien schéma n'a pas tout son historique).
  for i in 1 .. 8 loop
    if v_p.status = any (v_statuts[i:i][1:4]) and i <> 5 and i > v_rang_actuel then v_rang_actuel := i; end if;
  end loop;
  -- Les lieux que le journal ne porte pas (la cascade d'une expédition n'écrit pas de lieu) : le départ se fait de l'origine
  -- de la PREMIÈRE étape, l'arrivée et la douane à la destination de l'étape COURANTE.
  if v_premier[4] is not null and v_lieu[4] is null then
    v_lieu[4] := (select logistics.branch_label(s.origin_branch_id) from logistics.shipment s
                   where s.id in (select x.shipment_id from logistics.shipments_of_parcel(p_parcel) x) and s.status <> 'CANCELLED' order by s.created_at, s.id limit 1);
  end if;
  for i in 6 .. 7 loop
    if v_premier[i] is not null and v_lieu[i] is null then
      v_lieu[i] := (select logistics.branch_label(s.destination_branch_id) from logistics.shipment s where s.id = logistics.parcel_current_shipment(p_parcel));
    end if;
  end loop;
  -- « Départ » franchi ⇒ « Transit » en cours tant que le colis n'est pas arrivé.
  if v_rang_actuel = 4 then v_rang_actuel := 5; end if;
  v_terminee := v_p.status = 'DELIVERED';
  v_arret := case when v_p.status in ('ON_HOLD', 'DAMAGED', 'FAILED_DELIVERY') then 'paused'
                  when v_p.status in ('LOST', 'RETURNED', 'CANCELLED') then 'stopped' end;
  for i in 1 .. 8 loop
    v_etat := case when i < v_rang_actuel or (i = v_rang_actuel and v_terminee) then 'done'
                   when i = v_rang_actuel then 'current'
                   when v_arret = 'stopped' then 'stopped'
                   else 'upcoming' end;
    v_etapes := v_etapes || jsonb_build_object('key', v_cles[i], 'state', v_etat, 'at', v_premier[i], 'place', v_lieu[i]);
  end loop;
  -- Le moyen du départ et les hubs de transit, pour que « Départ » et « Transit » disent quelque chose de concret.
  select jsonb_build_object('mode', s.mode, 'carrier', t.carrier, 'voyage_number', nullif(t.voyage_number, ''), 'origin', logistics.branch_label(s.origin_branch_id),
                            'destination', logistics.branch_label(s.destination_branch_id), 'planned_arrival_at', coalesce(s.planned_arrival_at, t.planned_arrival_at))
    into v_depart
    from logistics.shipment s left join logistics.transport t on t.id = s.transport_id
   where s.id = logistics.parcel_current_shipment(p_parcel) and s.status not in ('DRAFT', 'CANCELLED');
  select coalesce(jsonb_agg(jsonb_build_object('event', e.event_type, 'at', e.occurred_at, 'place', e.location_text) order by e.occurred_at, e.id), '[]'::jsonb) into v_transit
    from logistics.tracking_event e where e.parcel_id = p_parcel and e.event_type in ('ParcelTransitHubReached', 'ParcelTransshipped');
  return jsonb_build_object(
    'tracking_number', v_p.tracking_number, 'destination_country', v_p.destination_country, 'service_mode', v_p.service_mode,
    'steps', v_etapes, 'current_step', case when v_rang_actuel = 0 then null else v_cles[v_rang_actuel] end,
    'completed', v_terminee,
    'exception', case when v_arret is null then null else jsonb_build_object('status', v_p.status, 'kind', v_arret, 'stage', logistics.customer_stage(v_p.status)) end,
    'transport', v_depart, 'transit_hubs', v_transit);
end;
$$;

create or replace function logistics.my_parcel_journey(p_user uuid, p_tracking text)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid; v_id uuid;
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  v_c := logistics.my_customer(p_user);
  select id into v_id from logistics.parcel where customer_id = v_c and tracking_number = upper(btrim(coalesce(p_tracking, '')));
  if v_id is null then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  return logistics.parcel_journey(v_id);
end;
$$;

create or replace function logistics.staff_parcel_journey(p_actor uuid, p_code text)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_id uuid;
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  select id into v_id from logistics.parcel where tracking_number = (logistics.parse_code(p_code) ->> 'number');
  if v_id is null then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  return logistics.parcel_journey(v_id);
end;
$$;


-- 11. La façade : l'acteur est TOUJOURS le compte connecté ----------------------------------------------------------------
create or replace function public.lg_create_transport(p_mode text, p_carrier text, p_reference text, p_voyage_number text, p_origin_branch uuid, p_destination_branch uuid,
  p_planned_departure timestamptz, p_planned_arrival timestamptz, p_capacity_weight_lb numeric default null, p_capacity_volume_ft3 numeric default null, p_vehicle_label text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$
  select logistics.create_transport(auth.uid(), p_mode, p_carrier, p_reference, p_voyage_number, p_origin_branch, p_destination_branch, p_planned_departure, p_planned_arrival,
                                    p_capacity_weight_lb, p_capacity_volume_ft3, p_vehicle_label) $$;
create or replace function public.lg_schedule_transport(p_transport_id uuid, p_planned_departure timestamptz, p_planned_arrival timestamptz)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.schedule_transport(auth.uid(), p_transport_id, p_planned_departure, p_planned_arrival) $$;
create or replace function public.lg_plan_shipment(p_shipment_id uuid, p_planned_departure timestamptz, p_planned_arrival timestamptz, p_hub_warehouse_id uuid default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.plan_shipment(auth.uid(), p_shipment_id, p_planned_departure, p_planned_arrival, p_hub_warehouse_id) $$;
create or replace function public.lg_create_onward_shipment(p_code text, p_mode text, p_origin_branch uuid, p_destination_branch uuid, p_parcel_ids uuid[], p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_onward_shipment(auth.uid(), p_code, p_mode, p_origin_branch, p_destination_branch, p_parcel_ids, p_idempotency_key) $$;
create or replace function public.lg_shipment_summary(p_shipment_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.shipment_summary(auth.uid(), p_shipment_id) $$;
create or replace function public.lg_consolidation_summary(p_consolidation_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.consolidation_summary(auth.uid(), p_consolidation_id) $$;
create or replace function public.lg_assign_consolidation_responsible(p_consolidation_id uuid, p_user_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.assign_consolidation_responsible(auth.uid(), p_consolidation_id, p_user_id) $$;
create or replace function public.lg_create_load_unit(p_code text, p_kind text, p_max_weight_lb numeric default null, p_max_volume_ft3 numeric default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_load_unit(auth.uid(), p_code, p_kind, p_max_weight_lb, p_max_volume_ft3) $$;
create or replace function public.lg_put_consolidation_in_load_unit(p_consolidation_id uuid, p_load_unit_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.put_consolidation_in_load_unit(auth.uid(), p_consolidation_id, p_load_unit_id) $$;
create or replace function public.lg_seal_load_unit(p_load_unit_id uuid, p_seal_number text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.seal_load_unit(auth.uid(), p_load_unit_id, p_seal_number) $$;
create or replace function public.lg_open_load_unit(p_load_unit_id uuid, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.open_load_unit(auth.uid(), p_load_unit_id, p_reason) $$;
create or replace function public.lg_load_unit_summary(p_load_unit_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.load_unit_summary(auth.uid(), p_load_unit_id) $$;
create or replace function public.lg_customs_assess_duties(p_shipment_id uuid, p_amount numeric, p_currency text default 'USD')
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.customs_assess_duties(auth.uid(), p_shipment_id, p_amount, p_currency) $$;
create or replace function public.lg_customs_mark_duties_paid(p_shipment_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.customs_mark_duties_paid(auth.uid(), p_shipment_id) $$;
create or replace function public.lg_customs_inspect(p_shipment_id uuid, p_result text, p_notes text default '', p_tracking_numbers text[] default '{}')
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.customs_inspect(auth.uid(), p_shipment_id, p_result, p_notes, p_tracking_numbers) $$;
create or replace function public.lg_customs_raise_exception(p_shipment_id uuid, p_parcel_id uuid, p_kind text, p_description text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.customs_raise_exception(auth.uid(), p_shipment_id, p_parcel_id, p_kind, p_description) $$;
create or replace function public.lg_customs_resolve_exception(p_exception_id uuid, p_outcome text, p_resolution text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.customs_resolve_exception(auth.uid(), p_exception_id, p_outcome, p_resolution) $$;
create or replace function public.lg_my_parcel_journey(p_tracking_number text)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_parcel_journey(auth.uid(), p_tracking_number) $$;
create or replace function public.lg_parcel_journey(p_code text)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.staff_parcel_journey(auth.uid(), p_code) $$;


-- 12. Tout fermé, sauf la façade, réservée aux comptes connectés -------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('parcel_current_shipment', 'record_parcel_milestone', 'shipment_weight_lb', 'shipment_volume_ft3',
              'transport_load_lb', 'transport_volume_ft3', 'load_unit_contents', 'consolidation_summary', 'assign_consolidation_responsible', 'create_transport',
              'schedule_transport', 'create_load_unit', 'load_unit_summary', 'put_consolidation_in_load_unit', 'seal_load_unit', 'open_load_unit', 'plan_shipment',
              'create_onward_shipment', 'shipment_summary', 'current_declaration', 'customs_assess_duties', 'customs_mark_duties_paid', 'customs_inspect',
              'customs_raise_exception', 'customs_resolve_exception', 'cascade_parcels', 'arrive_shipment', 'receive_at_hub', 'dispatch_shipment', 'clear_customs',
              'parcel_journey', 'my_parcel_journey', 'staff_parcel_journey') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_create_transport', 'lg_schedule_transport', 'lg_plan_shipment', 'lg_create_onward_shipment',
              'lg_shipment_summary', 'lg_consolidation_summary', 'lg_assign_consolidation_responsible', 'lg_create_load_unit', 'lg_put_consolidation_in_load_unit',
              'lg_seal_load_unit', 'lg_open_load_unit', 'lg_load_unit_summary', 'lg_customs_assess_duties', 'lg_customs_mark_duties_paid', 'lg_customs_inspect',
              'lg_customs_raise_exception', 'lg_customs_resolve_exception', 'lg_my_parcel_journey', 'lg_parcel_journey') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
