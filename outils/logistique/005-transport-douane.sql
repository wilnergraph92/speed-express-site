-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 5 : consolidation, expédition, transport, douane
-- -----------------------------------------------------------------------------
-- Phase 8. À coller dans Supabase > SQL Editor APRÈS 001 à 004, après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site ».
--
-- Le flux : Colis → Entrepôt → Consolidation → Expédition → Transport → Destination → Douane → Hub.
-- L'expédition a SA machine d'états, séparée de celle du colis ; elle ne modifie JAMAIS un statut de colis
-- directement : ses services demandent, colis par colis, une transition à la machine du colis, qui la valide.
-- Un colis en attente, endommagé ou perdu ne part donc pas avec le lot.
--
-- Aucune règle, aucun tarif n'est écrit dans une page : tout est ici. Les modes de transport sont des
-- DONNÉES (table transport_mode) : en ajouter un (rail, fluvial…) est une ligne, pas une migration.
--
-- Ne touche à aucune ancienne table, ni à 001-004 sauf pour les prolonger. Retour arrière au bas du fichier.
-- Rejouable sans risque.
-- =============================================================================

-- 1. Les modes de transport deviennent des données --------------------------------------------------------
create table if not exists logistics.transport_mode (
  code      text primary key check (code ~ '^[a-z][a-z_]{1,19}$'),
  label_key text not null,
  active    boolean not null default true
);
insert into logistics.transport_mode (code, label_key) values ('air', 'mode-air'), ('sea', 'mode-sea'), ('ground', 'mode-ground') on conflict (code) do nothing;

do $$
declare r record;
begin
  for r in select * from (values ('consolidation', 'mode', 'consolidation_mode_check'), ('transport', 'mode', 'transport_mode_check'),
                                 ('shipment', 'mode', 'shipment_mode_check'), ('parcel', 'service_mode', 'parcel_service_mode_check')) v(tb, col, ck) loop
    execute format('alter table logistics.%I drop constraint if exists %I', r.tb, r.ck);
    if not exists (select 1 from pg_constraint where conname = r.tb || '_' || r.col || '_fk' and conrelid = ('logistics.' || r.tb)::regclass) then
      execute format('alter table logistics.%I add constraint %I foreign key (%I) references logistics.transport_mode (code)', r.tb, r.tb || '_' || r.col || '_fk', r.col);
    end if;
  end loop;
end
$$;


-- 2. Événements -------------------------------------------------------------------------------------------
insert into logistics.event_type (code, aggregate_type, description) values
  ('ConsolidationOpened',          'consolidation', 'Consolidation ouverte'),
  ('ConsolidationClosed',          'consolidation', 'Consolidation fermée (ses colis sont consolidés)'),
  ('ManifestGenerated',            'shipment',      'Manifeste de l''expédition généré'),
  ('ShipmentReady',                'shipment',      'Expédition prête au départ'),
  ('ShipmentReopened',             'shipment',      'Expédition rouverte avant départ'),
  ('ShipmentInTransit',            'shipment',      'Expédition en transit'),
  ('ShipmentCustomsStarted',       'shipment',      'Dédouanement de l''expédition commencé'),
  ('ShipmentCustomsCleared',       'shipment',      'Expédition dédouanée'),
  ('ShipmentAtHub',                'shipment',      'Expédition reçue au hub'),
  ('ShipmentClosed',               'shipment',      'Expédition close (tous ses colis pris en charge)'),
  ('ShipmentCancelled',            'shipment',      'Expédition annulée'),
  ('CustomsDeclarationSubmitted',  'customs',       'Déclaration en douane déposée'),
  ('CustomsDeclarationCleared',    'customs',       'Déclaration en douane acceptée'),
  ('CustomsDeclarationRejected',   'customs',       'Déclaration en douane refusée')
on conflict (code) do nothing;

-- Un colis rouvert avec son expédition revient à « consolidé » (la seule marche arrière de plus).
insert into logistics.parcel_transition (from_status, to_status, event_type, requires_customer, allow_system)
values ('READY_FOR_EXPORT', 'CONSOLIDATED', 'ParcelConsolidated', true, true) on conflict do nothing;


-- 3. Itinéraires, voyages, arrêts, unités logistiques ----------------------------------------------------------
create table if not exists logistics.route (
  id                    uuid primary key default gen_random_uuid(),
  code                  text not null unique,
  kind                  text not null check (kind in ('LINEHAUL', 'LASTMILE')),
  name                  text not null default '',
  mode                  text references logistics.transport_mode (code),
  origin_branch_id      uuid references logistics.branch (id) on delete restrict,
  destination_branch_id uuid references logistics.branch (id) on delete restrict,
  active                boolean not null default true,
  created_at            timestamptz not null default now()
);
create table if not exists logistics.trip (
  id                   uuid primary key default gen_random_uuid(),
  route_id             uuid references logistics.route (id) on delete restrict,
  kind                 text not null check (kind in ('LINEHAUL', 'LASTMILE')),
  transport_id         uuid references logistics.transport (id) on delete restrict,
  planned_departure_at timestamptz,
  planned_arrival_at   timestamptz,
  actual_departure_at  timestamptz,
  actual_arrival_at    timestamptz,
  status               text not null default 'PLANNED' check (status in ('PLANNED', 'STARTED', 'COMPLETED', 'CANCELLED')),
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);
create table if not exists logistics.stop (
  id         uuid primary key default gen_random_uuid(),
  trip_id    uuid not null references logistics.trip (id) on delete restrict,
  sequence   int not null check (sequence > 0),
  kind       text not null check (kind in ('ORIGIN', 'HUB', 'CUSTOMS', 'DESTINATION', 'PICKUP', 'DELIVERY')),
  branch_id  uuid references logistics.branch (id) on delete restrict,
  planned_at timestamptz,
  actual_at  timestamptz,
  status     text not null default 'PLANNED' check (status in ('PLANNED', 'ARRIVED', 'DEPARTED', 'SKIPPED')),
  unique (trip_id, sequence)
);
alter table logistics.shipment add column if not exists trip_id uuid references logistics.trip (id) on delete restrict;

create table if not exists logistics.load_unit (
  id            uuid primary key default gen_random_uuid(),
  code          text not null unique,
  kind          text not null check (kind in ('CONTAINER', 'PALLET', 'ULD', 'BAG')),
  seal_number   text,
  max_weight_lb numeric(10, 2) check (max_weight_lb is null or max_weight_lb > 0),
  status        text not null default 'OPEN' check (status in ('OPEN', 'SEALED', 'OPENED')),
  created_at    timestamptz not null default now()
);
comment on table logistics.load_unit is 'Conteneur, palette, ULD aérien, sac : une unité logistique qui peut contenir des consolidations et entrer telle quelle dans une expédition.';
alter table logistics.consolidation add column if not exists load_unit_id uuid references logistics.load_unit (id) on delete restrict;
alter table logistics.shipment_item add column if not exists load_unit_id uuid references logistics.load_unit (id) on delete restrict;
alter table logistics.shipment_item drop constraint if exists shipment_item_check;
alter table logistics.shipment_item drop constraint if exists shipment_item_one_target;
alter table logistics.shipment_item add constraint shipment_item_one_target check (num_nonnulls(consolidation_id, parcel_id, load_unit_id) = 1);
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'shipment_item_shipment_load_unit_key') then
    alter table logistics.shipment_item add constraint shipment_item_shipment_load_unit_key unique (shipment_id, load_unit_id);
  end if;
end $$;


-- 4. L'expédition : sa propre machine d'états -----------------------------------------------------------------------
create table if not exists logistics.shipment_transition (
  from_status    text not null references logistics.shipment_status (code),
  to_status      text not null references logistics.shipment_status (code),
  event_type     text not null references logistics.event_type (code),
  required_right text not null default 'colis.statut' check (required_right in ('colis.statut', 'direction')),
  primary key (from_status, to_status),
  check (from_status <> to_status)
);
insert into logistics.shipment_transition (from_status, to_status, event_type, required_right) values
  ('DRAFT',              'READY',              'ShipmentReady',          'colis.statut'),
  ('READY',              'DRAFT',              'ShipmentReopened',       'colis.statut'),
  ('READY',              'DISPATCHED',         'ShipmentDispatched',     'colis.statut'),
  ('DISPATCHED',         'IN_TRANSIT',         'ShipmentInTransit',      'colis.statut'),
  ('DISPATCHED',         'ARRIVED',            'ShipmentArrived',        'colis.statut'),
  ('IN_TRANSIT',         'ARRIVED',            'ShipmentArrived',        'colis.statut'),
  ('ARRIVED',            'CUSTOMS_PROCESSING', 'ShipmentCustomsStarted', 'colis.statut'),
  ('CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED',    'ShipmentCustomsCleared', 'colis.statut'),
  ('CUSTOMS_CLEARED',    'AT_HUB',             'ShipmentAtHub',          'colis.statut'),
  ('AT_HUB',             'CLOSED',             'ShipmentClosed',         'colis.statut'),
  ('DRAFT',              'CANCELLED',          'ShipmentCancelled',      'direction')
on conflict do nothing;

create table if not exists logistics.shipment_status_history (
  id             bigint generated always as identity primary key,
  shipment_id    uuid not null references logistics.shipment (id) on delete restrict,
  from_status    text references logistics.shipment_status (code),
  to_status      text not null references logistics.shipment_status (code),
  occurred_at    timestamptz not null default now(),
  actor_user_id  uuid references logistics.app_user (id) on delete restrict,
  actor_label    text not null default '',
  reason         text,
  correlation_id uuid not null,
  metadata       jsonb not null default '{}'::jsonb
);
create index if not exists shipment_status_history_idx on logistics.shipment_status_history (shipment_id, occurred_at);
drop trigger if exists shipment_status_history_append_only on logistics.shipment_status_history;
create trigger shipment_status_history_append_only before update or delete on logistics.shipment_status_history
  for each row execute function logistics.forbid_mutation();

create or replace function logistics.guard_shipment_status()
returns trigger language plpgsql set search_path = '' as $$
declare v_ok boolean := coalesce(current_setting('logistics.shipment_transition', true), 'off') = 'on';
begin
  if tg_op = 'INSERT' then
    if new.status <> 'DRAFT' then raise exception 'Une expédition naît en DRAFT, pas %.', new.status using errcode = 'LG001'; end if;
    return new;
  end if;
  if new.status is distinct from old.status and not v_ok then
    raise exception 'Le statut d''une expédition ne change que par une transition autorisée.' using errcode = 'LG001';
  end if;
  return new;
end;
$$;
drop trigger if exists guard_shipment_status on logistics.shipment;
create trigger guard_shipment_status before insert or update on logistics.shipment for each row execute function logistics.guard_shipment_status();


-- 5. La douane et le manifeste --------------------------------------------------------------------------------------
create table if not exists logistics.customs_declaration (
  id                  uuid primary key default gen_random_uuid(),
  shipment_id         uuid not null references logistics.shipment (id) on delete restrict,
  reference           text not null default '',
  status              text not null default 'SUBMITTED' check (status in ('DRAFT', 'SUBMITTED', 'UNDER_REVIEW', 'CLEARED', 'REJECTED')),
  broker_name         text not null default '',
  origin_country      text,
  destination_country text,
  declared_value      numeric(14, 2) not null default 0 check (declared_value >= 0),
  currency            text not null default 'USD' check (currency in ('USD', 'DOP', 'HTG')),
  snapshot            jsonb not null default '[]'::jsonb,
  submitted_at        timestamptz,
  cleared_at          timestamptz,
  rejected_reason     text,
  created_by          uuid references logistics.app_user (id) on delete restrict,
  correlation_id      uuid,
  created_at          timestamptz not null default now()
);
-- Une seule déclaration vivante par expédition : une refusée peut être remplacée, pas doublée.
create unique index if not exists customs_declaration_one_live on logistics.customs_declaration (shipment_id) where status <> 'REJECTED';

create table if not exists logistics.customs_document (
  id             uuid primary key default gen_random_uuid(),
  declaration_id uuid not null references logistics.customs_declaration (id) on delete restrict,
  doc_type       text not null check (doc_type in ('INVOICE', 'PACKING_LIST', 'BILL_OF_LADING', 'AIR_WAYBILL', 'PERMIT', 'CERTIFICATE', 'OTHER')),
  reference      text not null default '',
  storage_path   text check (storage_path is null or storage_path ~ '^customs/[0-9a-f-]{36}/[A-Za-z0-9._-]{1,120}$'),
  created_by     uuid references logistics.app_user (id) on delete restrict,
  created_at     timestamptz not null default now()
);

create table if not exists logistics.shipment_manifest (
  id           uuid primary key default gen_random_uuid(),
  shipment_id  uuid not null references logistics.shipment (id) on delete restrict,
  version      int not null,
  generated_at timestamptz not null default now(),
  generated_by uuid references logistics.app_user (id) on delete restrict,
  content      jsonb not null,
  content_hash text not null,
  unique (shipment_id, version)
);
drop trigger if exists shipment_manifest_append_only on logistics.shipment_manifest;
create trigger shipment_manifest_append_only before update or delete on logistics.shipment_manifest for each row execute function logistics.forbid_mutation();


-- 6. Outils internes -----------------------------------------------------------------------------------------------
create or replace function logistics.emit(p_type text, p_agg_type text, p_agg_id text, p_corr uuid, p_actor uuid, p_payload jsonb)
returns bigint language plpgsql volatile set search_path = '' as $$
declare v_id bigint;
begin
  insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_user_id, actor_label, payload)
  values (p_type, p_agg_type, p_agg_id, p_corr, p_actor, coalesce((select email from auth.users where id = p_actor), 'system'), coalesce(p_payload, '{}'::jsonb))
  returning id into v_id;
  return v_id;
end;
$$;

-- Idempotence commune : rend le résultat d'origine d'une commande rejouée, ou null pour une commande neuve.
create or replace function logistics.idem_begin(p_key text, p_command text, p_hash text, p_entity text)
returns jsonb language plpgsql volatile set search_path = '' as $$
declare v_h text; v_r jsonb;
begin
  if p_key is null then return null; end if;
  insert into logistics.command_log (idempotency_key, command, request_hash, entity_type, entity_id)
  values (p_key, p_command, p_hash, 'command', p_entity) on conflict (idempotency_key) do nothing;
  if found then return null; end if;
  select request_hash, result into v_h, v_r from logistics.command_log where idempotency_key = p_key;
  if v_h <> p_hash then raise exception 'Clé d''idempotence déjà utilisée pour une AUTRE demande.' using errcode = 'LG006'; end if;
  return coalesce(v_r, '{}'::jsonb) || jsonb_build_object('replayed', true);
end;
$$;
create or replace function logistics.idem_end(p_key text, p_result jsonb)
returns jsonb language plpgsql volatile set search_path = '' as $$
begin
  if p_key is not null then update logistics.command_log set result = p_result where idempotency_key = p_key; end if;
  return p_result;
end;
$$;

create or replace function logistics.require_right(p_actor uuid, p_right text default 'colis.statut')
returns void language plpgsql stable set search_path = '' as $$
begin
  if p_actor is null or not logistics.actor_can(p_actor, p_right) then
    raise exception 'Droit insuffisant (exige : %).', p_right using errcode = 'LG003';
  end if;
end;
$$;

-- Les colis d'une expédition : en direct, par consolidation, ou par unité logistique. Actifs seulement.
create or replace function logistics.shipment_parcels(p_shipment_id uuid)
returns table (parcel_id uuid)
language sql stable set search_path = '' as $$
  select i.parcel_id from logistics.shipment_item i where i.shipment_id = p_shipment_id and i.parcel_id is not null
  union
  select cp.parcel_id from logistics.shipment_item i join logistics.consolidation_parcel cp on cp.consolidation_id = i.consolidation_id and cp.removed_at is null
   where i.shipment_id = p_shipment_id and i.consolidation_id is not null
  union
  select cp.parcel_id from logistics.shipment_item i join logistics.consolidation c on c.load_unit_id = i.load_unit_id
   join logistics.consolidation_parcel cp on cp.consolidation_id = c.id and cp.removed_at is null
   where i.shipment_id = p_shipment_id and i.load_unit_id is not null
$$;

-- Demande, colis par colis, une transition à la machine du colis. Ceux qui ne sont pas dans l'état attendu
-- (en attente, endommagés, perdus) sont SAUTÉS et rapportés : ils ne partent pas avec le lot.
create or replace function logistics.cascade_parcels(p_shipment_id uuid, p_from text, p_to text, p_actor uuid, p_corr uuid, p_warehouse uuid default null)
returns jsonb language plpgsql volatile set search_path = '' as $$
declare r record; v_done int := 0; v_skipped jsonb := '[]'::jsonb;
begin
  for r in select p.id, p.status, p.tracking_number from logistics.parcel p where p.id in (select parcel_id from logistics.shipment_parcels(p_shipment_id)) order by p.tracking_number loop
    if r.status = p_from then
      perform logistics.transition_parcel(r.id, p_to, p_actor, null, p_corr, p_warehouse, null, '', null, null,
                                          jsonb_build_object('shipment_id', p_shipment_id), 'api');
      v_done := v_done + 1;
    else
      v_skipped := v_skipped || jsonb_build_object('tracking_number', r.tracking_number, 'status', r.status);
    end if;
  end loop;
  return jsonb_build_object('moved', v_done, 'skipped', v_skipped);
end;
$$;

-- LA transition d'une expédition : le seul chemin pour changer son statut.
create or replace function logistics.move_shipment(p_id uuid, p_to text, p_actor uuid, p_corr uuid, p_reason text default null, p_meta jsonb default '{}'::jsonb)
returns logistics.shipment
language plpgsql volatile set search_path = '' as $$
declare v_s logistics.shipment; v_t logistics.shipment_transition; v_label text;
begin
  select * into v_s from logistics.shipment where id = p_id for update;
  if not found then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  select * into v_t from logistics.shipment_transition where from_status = v_s.status and to_status = p_to;
  if not found then raise exception 'Transition d''expédition non autorisée : % → %.', v_s.status, p_to using errcode = 'LG001'; end if;
  perform logistics.require_right(p_actor, v_t.required_right);
  if p_to = 'CANCELLED' and btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour annuler.' using errcode = 'LG005'; end if;
  perform set_config('logistics.shipment_transition', 'on', true);
  update logistics.shipment set status = p_to,
         dispatched_at = case when p_to = 'DISPATCHED' then now() else dispatched_at end,
         arrived_at    = case when p_to = 'ARRIVED' then now() else arrived_at end
   where id = p_id returning * into v_s;
  perform set_config('logistics.shipment_transition', 'off', true);
  v_label := coalesce((select email from auth.users where id = p_actor), p_actor::text);
  insert into logistics.shipment_status_history (shipment_id, from_status, to_status, actor_user_id, actor_label, reason, correlation_id, metadata)
  values (p_id, v_t.from_status, p_to, p_actor, v_label, p_reason, p_corr, coalesce(p_meta, '{}'::jsonb));
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id, metadata)
  values (p_actor, v_label, 'shipment.transition', 'shipment', p_id::text, jsonb_build_object('status', v_t.from_status), jsonb_build_object('status', p_to), p_corr,
          jsonb_build_object('event_type', v_t.event_type, 'reason', p_reason));
  perform logistics.emit(v_t.event_type, 'shipment', p_id::text, p_corr, p_actor,
                         jsonb_build_object('shipment_id', p_id, 'code', v_s.code, 'from_status', v_t.from_status, 'to_status', p_to, 'reason', p_reason) || coalesce(p_meta, '{}'::jsonb));
  return v_s;
end;
$$;


-- 7. Consolidation ------------------------------------------------------------------------------------------------------
create or replace function logistics.open_consolidation(p_code text, p_warehouse_id uuid, p_destination_country text, p_mode text, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid());
begin
  perform logistics.require_right(p_actor);
  if btrim(coalesce(p_code, '')) = '' then raise exception 'Un code de consolidation est obligatoire.' using errcode = 'LG005'; end if;
  if p_destination_country not in ('HT', 'DO', 'US') then raise exception 'Pays de destination inconnu.' using errcode = 'LG005'; end if;
  if not exists (select 1 from logistics.transport_mode where code = p_mode and active) then raise exception 'Mode de transport inconnu : %.', p_mode using errcode = 'LG005'; end if;
  if p_warehouse_id is not null and not exists (select 1 from logistics.warehouse where id = p_warehouse_id and active) then raise exception 'Entrepôt inconnu.' using errcode = 'LG005'; end if;
  insert into logistics.consolidation (code, warehouse_id, destination_country, mode, created_by) values (btrim(p_code), p_warehouse_id, p_destination_country, p_mode, p_actor) returning id into v_id;
  perform logistics.emit('ConsolidationOpened', 'consolidation', v_id::text, v_corr, p_actor, jsonb_build_object('consolidation_id', v_id, 'code', btrim(p_code), 'destination_country', p_destination_country, 'mode', p_mode));
  return jsonb_build_object('consolidation_id', v_id, 'code', btrim(p_code), 'status', 'OPEN', 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.add_parcel_to_consolidation(p_consolidation_id uuid, p_parcel_id uuid, p_actor uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c logistics.consolidation; v_p logistics.parcel;
begin
  perform logistics.require_right(p_actor);
  select * into v_c from logistics.consolidation where id = p_consolidation_id for update;
  if not found then raise exception 'Consolidation introuvable.' using errcode = 'LG002'; end if;
  if v_c.status <> 'OPEN' then raise exception 'La consolidation % est %, on n''y ajoute plus rien.', v_c.code, v_c.status using errcode = 'LG004'; end if;
  select * into v_p from logistics.parcel where id = p_parcel_id for update;
  if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  if v_p.status <> 'CONSOLIDATION_PENDING' then raise exception 'Le colis % est en % : seul un colis « en attente de consolidation » peut y entrer.', v_p.tracking_number, v_p.status using errcode = 'LG005'; end if;
  if v_p.customer_id is null then raise exception 'Un colis sans client ne se consolide pas.' using errcode = 'LG005'; end if;
  if v_p.destination_country <> v_c.destination_country then raise exception 'Destination différente (% contre %).', v_p.destination_country, v_c.destination_country using errcode = 'LG005'; end if;
  if v_p.service_mode <> v_c.mode then raise exception 'Mode différent (% contre %).', v_p.service_mode, v_c.mode using errcode = 'LG005'; end if;
  insert into logistics.consolidation_parcel (consolidation_id, parcel_id) values (p_consolidation_id, p_parcel_id);
  return jsonb_build_object('consolidation_id', p_consolidation_id, 'parcel_id', p_parcel_id, 'tracking_number', v_p.tracking_number);
end;
$$;

create or replace function logistics.remove_parcel_from_consolidation(p_consolidation_id uuid, p_parcel_id uuid, p_actor uuid)
returns void language plpgsql volatile security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor);
  if exists (select 1 from logistics.consolidation where id = p_consolidation_id and status <> 'OPEN') then
    raise exception 'La consolidation est close : on n''en retire plus de colis.' using errcode = 'LG004';
  end if;
  update logistics.consolidation_parcel set removed_at = now() where consolidation_id = p_consolidation_id and parcel_id = p_parcel_id and removed_at is null;
  if not found then raise exception 'Ce colis n''est pas dans cette consolidation.' using errcode = 'LG002'; end if;
end;
$$;

-- FERMER : tous les colis passent « consolidés », ou rien ne se passe.
create or replace function logistics.close_consolidation(p_consolidation_id uuid, p_actor uuid, p_idempotency_key text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c logistics.consolidation; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_prior jsonb; v_n int; v_bad record; v_w numeric; v_out jsonb;
begin
  perform logistics.require_right(p_actor);
  v_prior := logistics.idem_begin(p_idempotency_key, 'close_consolidation', md5(p_consolidation_id::text || p_actor::text), p_consolidation_id::text);
  if v_prior is not null then return v_prior; end if;
  select * into v_c from logistics.consolidation where id = p_consolidation_id for update;
  if not found then raise exception 'Consolidation introuvable.' using errcode = 'LG002'; end if;
  if v_c.status <> 'OPEN' then raise exception 'La consolidation % est déjà %.', v_c.code, v_c.status using errcode = 'LG004'; end if;
  select count(*), coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb, 0)), 0) into v_n, v_w
    from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id where cp.consolidation_id = p_consolidation_id and cp.removed_at is null;
  if v_n = 0 then raise exception 'Une consolidation vide ne se ferme pas.' using errcode = 'LG005'; end if;
  select p.tracking_number, p.status into v_bad from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id
   where cp.consolidation_id = p_consolidation_id and cp.removed_at is null and p.status <> 'CONSOLIDATION_PENDING' limit 1;
  if found then raise exception 'Le colis % est en % : il doit être « en attente de consolidation ».', v_bad.tracking_number, v_bad.status using errcode = 'LG005'; end if;
  perform logistics.transition_parcel(cp.parcel_id, 'CONSOLIDATED', p_actor, null, v_corr, null, null, '', null, null, jsonb_build_object('consolidation_id', p_consolidation_id), 'api')
    from logistics.consolidation_parcel cp where cp.consolidation_id = p_consolidation_id and cp.removed_at is null order by cp.id;
  update logistics.consolidation set status = 'CLOSED', closed_at = now() where id = p_consolidation_id;
  perform logistics.emit('ConsolidationClosed', 'consolidation', p_consolidation_id::text, v_corr, p_actor,
                         jsonb_build_object('consolidation_id', p_consolidation_id, 'code', v_c.code, 'parcels', v_n, 'total_weight_lb', v_w));
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'consolidation.close', 'consolidation', p_consolidation_id::text,
          jsonb_build_object('status', 'OPEN'), jsonb_build_object('status', 'CLOSED', 'parcels', v_n), v_corr);
  v_out := jsonb_build_object('consolidation_id', p_consolidation_id, 'status', 'CLOSED', 'parcels', v_n, 'total_weight_lb', v_w, 'correlation_id', v_corr, 'replayed', false);
  return logistics.idem_end(p_idempotency_key, v_out);
end;
$$;


-- 8. Expédition ----------------------------------------------------------------------------------------------------------
create or replace function logistics.create_shipment(
  p_code text, p_mode text, p_origin_branch uuid, p_destination_branch uuid, p_actor uuid,
  p_consolidation_ids uuid[] default '{}', p_parcel_ids uuid[] default '{}', p_load_unit_ids uuid[] default '{}',
  p_idempotency_key text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_prior jsonb; v_id uuid := gen_random_uuid(); v_hub logistics.branch; v_x uuid; v_c logistics.consolidation;
  v_p logistics.parcel; v_label text; v_out jsonb;
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
    if exists (select 1 from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id where i.consolidation_id = v_x and s.status not in ('CANCELLED') and s.id <> v_id) then
      raise exception 'La consolidation % est déjà dans une autre expédition.', v_c.code using errcode = 'LG005';
    end if;
    insert into logistics.shipment_item (shipment_id, consolidation_id) values (v_id, v_x);
  end loop;
  foreach v_x in array coalesce(p_load_unit_ids, '{}') loop
    if not exists (select 1 from logistics.load_unit where id = v_x) then raise exception 'Unité logistique introuvable.' using errcode = 'LG002'; end if;
    if exists (select 1 from logistics.consolidation where load_unit_id = v_x and status <> 'CLOSED') then raise exception 'Une consolidation de cette unité n''est pas fermée.' using errcode = 'LG005'; end if;
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

-- Le contenu du manifeste : déterministe (même ordre, mêmes champs), donc comparable.
create or replace function logistics.manifest_content(p_shipment_id uuid)
returns jsonb language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'shipment', jsonb_build_object('code', s.code, 'mode', s.mode, 'origin', (select code from logistics.branch where id = s.origin_branch_id),
                                   'destination', (select code from logistics.branch where id = s.destination_branch_id)),
    'parcels', coalesce((select jsonb_agg(jsonb_build_object(
                  'tracking_number', p.tracking_number, 'description', p.description, 'recipient', p.recipient_name,
                  'destination_city', p.destination_city, 'weight_lb', coalesce(p.verified_weight_lb, p.weight_lb), 'declared_value', p.declared_value,
                  'held', p.status in ('ON_HOLD', 'DAMAGED', 'LOST', 'CANCELLED'),
                  'consolidation', (select c.code from logistics.consolidation_parcel cp join logistics.consolidation c on c.id = cp.consolidation_id where cp.parcel_id = p.id and cp.removed_at is null limit 1))
                  order by p.tracking_number)
                from logistics.parcel p where p.id in (select parcel_id from logistics.shipment_parcels(s.id))), '[]'::jsonb),
    'totals', (select jsonb_build_object('parcels', count(*), 'weight_lb', coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb, 0)), 0),
                                         'declared_value', coalesce(sum(coalesce(p.declared_value, 0)), 0), 'held', count(*) filter (where p.status in ('ON_HOLD', 'DAMAGED', 'LOST', 'CANCELLED')))
               from logistics.parcel p where p.id in (select parcel_id from logistics.shipment_parcels(s.id))))
  from logistics.shipment s where s.id = p_shipment_id
$$;

create or replace function logistics.generate_manifest(p_shipment_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_s logistics.shipment; v_c jsonb; v_h text; v_v int; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_id uuid;
begin
  perform logistics.require_right(p_actor);
  select * into v_s from logistics.shipment where id = p_shipment_id for update;
  if not found then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  if v_s.status not in ('DRAFT', 'READY') then raise exception 'Le manifeste ne se régénère plus une fois l''expédition partie (%).', v_s.status using errcode = 'LG001'; end if;
  v_c := logistics.manifest_content(p_shipment_id);
  if (v_c -> 'totals' ->> 'parcels')::int = 0 then raise exception 'Une expédition sans colis n''a pas de manifeste.' using errcode = 'LG005'; end if;
  v_h := md5(v_c::text);
  select coalesce(max(version), 0) + 1 into v_v from logistics.shipment_manifest where shipment_id = p_shipment_id;
  insert into logistics.shipment_manifest (shipment_id, version, generated_by, content, content_hash) values (p_shipment_id, v_v, p_actor, v_c, v_h) returning id into v_id;
  perform logistics.emit('ManifestGenerated', 'shipment', p_shipment_id::text, v_corr, p_actor, jsonb_build_object('shipment_id', p_shipment_id, 'manifest_id', v_id, 'version', v_v, 'hash', v_h, 'parcels', v_c -> 'totals' ->> 'parcels'));
  return jsonb_build_object('manifest_id', v_id, 'version', v_v, 'hash', v_h, 'content', v_c);
end;
$$;

-- Le manifeste le plus récent est-il encore exact ?
create or replace function logistics.manifest_is_fresh(p_shipment_id uuid)
returns boolean language sql stable set search_path = '' as $$
  select coalesce((select m.content_hash = md5(logistics.manifest_content(p_shipment_id)::text)
                     from logistics.shipment_manifest m where m.shipment_id = p_shipment_id order by m.version desc limit 1), false)
$$;

create or replace function logistics.mark_shipment_ready(p_shipment_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_c jsonb;
begin
  perform logistics.require_right(p_actor);
  if not exists (select 1 from logistics.shipment where id = p_shipment_id) then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  if not exists (select 1 from logistics.shipment_parcels(p_shipment_id)) then raise exception 'Une expédition sans colis ne se prépare pas.' using errcode = 'LG005'; end if;
  if not logistics.manifest_is_fresh(p_shipment_id) then raise exception 'Le manifeste est absent ou périmé : générez-le de nouveau.' using errcode = 'LG005'; end if;
  perform logistics.move_shipment(p_shipment_id, 'READY', p_actor, v_corr);
  v_c := logistics.cascade_parcels(p_shipment_id, 'CONSOLIDATED', 'READY_FOR_EXPORT', p_actor, v_corr);
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'READY', 'parcels', v_c, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.reopen_shipment(p_shipment_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_c jsonb;
begin
  perform logistics.require_right(p_actor);
  perform logistics.move_shipment(p_shipment_id, 'DRAFT', p_actor, v_corr);
  v_c := logistics.cascade_parcels(p_shipment_id, 'READY_FOR_EXPORT', 'CONSOLIDATED', p_actor, v_corr);
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'DRAFT', 'parcels', v_c, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.cancel_shipment(p_shipment_id uuid, p_actor uuid, p_reason text, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_st text;
begin
  perform logistics.require_right(p_actor, 'direction');
  select status into v_st from logistics.shipment where id = p_shipment_id for update;
  if not found then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  if v_st = 'READY' then perform logistics.reopen_shipment(p_shipment_id, p_actor, v_corr); end if;
  perform logistics.move_shipment(p_shipment_id, 'CANCELLED', p_actor, v_corr, p_reason);
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'CANCELLED', 'correlation_id', v_corr);
end;
$$;


-- 9. Transport, arrivée, douane, hub ---------------------------------------------------------------------------------------
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
  if not logistics.manifest_is_fresh(p_shipment_id) then raise exception 'Le manifeste est périmé (le contenu a changé depuis sa génération) : régénérez-le.' using errcode = 'LG005'; end if;
  update logistics.shipment set transport_id = p_transport_id where id = p_shipment_id;
  perform logistics.move_shipment(p_shipment_id, 'DISPATCHED', p_actor, v_corr, null, jsonb_build_object('transport_id', p_transport_id));
  update logistics.transport set status = 'DEPARTED', actual_departure_at = coalesce(actual_departure_at, now()) where id = p_transport_id and status = 'PLANNED';
  v_c := logistics.cascade_parcels(p_shipment_id, 'READY_FOR_EXPORT', 'IN_TRANSIT', p_actor, v_corr);
  v_out := jsonb_build_object('shipment_id', p_shipment_id, 'status', 'DISPATCHED', 'transport_id', p_transport_id, 'parcels', v_c, 'correlation_id', v_corr, 'replayed', false);
  return logistics.idem_end(p_idempotency_key, v_out);
end;
$$;

create or replace function logistics.mark_shipment_in_transit(p_shipment_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid());
begin
  perform logistics.require_right(p_actor);
  perform logistics.move_shipment(p_shipment_id, 'IN_TRANSIT', p_actor, v_corr);
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'IN_TRANSIT', 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.arrive_shipment(p_shipment_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_s logistics.shipment; v_c jsonb;
begin
  perform logistics.require_right(p_actor);
  v_s := logistics.move_shipment(p_shipment_id, 'ARRIVED', p_actor, v_corr);
  v_c := logistics.cascade_parcels(p_shipment_id, 'IN_TRANSIT', 'ARRIVED', p_actor, v_corr);
  -- Le transport est arrivé quand TOUTES ses expéditions le sont.
  update logistics.transport t set status = 'ARRIVED', actual_arrival_at = now()
   where t.id = v_s.transport_id and t.status = 'DEPARTED'
     and not exists (select 1 from logistics.shipment x where x.transport_id = t.id and x.status in ('DISPATCHED', 'IN_TRANSIT'));
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'ARRIVED', 'parcels', v_c, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.start_customs(p_shipment_id uuid, p_actor uuid, p_reference text default '', p_broker text default '', p_documents jsonb default '[]'::jsonb, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_s logistics.shipment; v_d uuid := gen_random_uuid(); v_snap jsonb; v_val numeric; v_c jsonb; v_doc jsonb;
begin
  perform logistics.require_right(p_actor);
  select * into v_s from logistics.shipment where id = p_shipment_id for update;
  if not found then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  if v_s.status <> 'ARRIVED' then raise exception 'La douane commence quand l''expédition est ARRIVÉE (elle est %).', v_s.status using errcode = 'LG001'; end if;
  if jsonb_typeof(coalesce(p_documents, '[]'::jsonb)) <> 'array' then raise exception 'Documents : un tableau attendu.' using errcode = 'LG005'; end if;
  select coalesce(jsonb_agg(jsonb_build_object('tracking_number', p.tracking_number, 'description', p.description, 'weight_lb', coalesce(p.verified_weight_lb, p.weight_lb), 'declared_value', coalesce(p.declared_value, 0)) order by p.tracking_number), '[]'::jsonb),
         coalesce(sum(coalesce(p.declared_value, 0)), 0)
    into v_snap, v_val from logistics.parcel p where p.id in (select parcel_id from logistics.shipment_parcels(p_shipment_id)) and p.status = 'ARRIVED';
  insert into logistics.customs_declaration (id, shipment_id, reference, status, broker_name, origin_country, destination_country, declared_value, snapshot, submitted_at, created_by, correlation_id)
  values (v_d, p_shipment_id, coalesce(p_reference, ''), 'SUBMITTED', coalesce(p_broker, ''),
          (select country from logistics.branch where id = v_s.origin_branch_id), (select country from logistics.branch where id = v_s.destination_branch_id), v_val, v_snap, now(), p_actor, v_corr);
  for v_doc in select * from jsonb_array_elements(coalesce(p_documents, '[]'::jsonb)) loop
    insert into logistics.customs_document (declaration_id, doc_type, reference, storage_path, created_by)
    values (v_d, v_doc ->> 'type', coalesce(v_doc ->> 'reference', ''), v_doc ->> 'path', p_actor);
  end loop;
  perform logistics.move_shipment(p_shipment_id, 'CUSTOMS_PROCESSING', p_actor, v_corr, null, jsonb_build_object('declaration_id', v_d));
  v_c := logistics.cascade_parcels(p_shipment_id, 'ARRIVED', 'CUSTOMS_PROCESSING', p_actor, v_corr);
  perform logistics.emit('CustomsDeclarationSubmitted', 'customs', v_d::text, v_corr, p_actor, jsonb_build_object('declaration_id', v_d, 'shipment_id', p_shipment_id, 'declared_value', v_val));
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'CUSTOMS_PROCESSING', 'declaration_id', v_d, 'declared_value', v_val, 'parcels', v_c, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.clear_customs(p_shipment_id uuid, p_actor uuid, p_reference text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_d uuid; v_c jsonb;
begin
  perform logistics.require_right(p_actor);
  select id into v_d from logistics.customs_declaration where shipment_id = p_shipment_id and status in ('SUBMITTED', 'UNDER_REVIEW') for update;
  if not found then raise exception 'Aucune déclaration en cours pour cette expédition.' using errcode = 'LG002'; end if;
  perform logistics.move_shipment(p_shipment_id, 'CUSTOMS_CLEARED', p_actor, v_corr, null, jsonb_build_object('declaration_id', v_d));
  update logistics.customs_declaration set status = 'CLEARED', cleared_at = now(), reference = coalesce(nullif(p_reference, ''), reference) where id = v_d;
  v_c := logistics.cascade_parcels(p_shipment_id, 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', p_actor, v_corr);
  perform logistics.emit('CustomsDeclarationCleared', 'customs', v_d::text, v_corr, p_actor, jsonb_build_object('declaration_id', v_d, 'shipment_id', p_shipment_id));
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'CUSTOMS_CLEARED', 'declaration_id', v_d, 'parcels', v_c, 'correlation_id', v_corr);
end;
$$;

-- Refus de la douane : l'expédition RESTE en douane ; une nouvelle déclaration peut être déposée.
create or replace function logistics.reject_customs(p_shipment_id uuid, p_actor uuid, p_reason text, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_d uuid;
begin
  perform logistics.require_right(p_actor);
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif de refus est obligatoire.' using errcode = 'LG005'; end if;
  update logistics.customs_declaration set status = 'REJECTED', rejected_reason = left(p_reason, 1000)
   where shipment_id = p_shipment_id and status in ('SUBMITTED', 'UNDER_REVIEW') returning id into v_d;
  if not found then raise exception 'Aucune déclaration en cours pour cette expédition.' using errcode = 'LG002'; end if;
  perform logistics.emit('CustomsDeclarationRejected', 'customs', v_d::text, v_corr, p_actor, jsonb_build_object('declaration_id', v_d, 'shipment_id', p_shipment_id, 'reason', p_reason));
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'customs.reject', 'customs', v_d::text, jsonb_build_object('reason', p_reason), v_corr);
  return jsonb_build_object('declaration_id', v_d, 'status', 'REJECTED', 'shipment_status', (select status from logistics.shipment where id = p_shipment_id));
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
  perform logistics.move_shipment(p_shipment_id, 'AT_HUB', p_actor, v_corr);
  v_c := logistics.cascade_parcels(p_shipment_id, 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB', p_actor, v_corr, p_hub_warehouse_id);
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'AT_HUB', 'parcels', v_c, 'correlation_id', v_corr);
end;
$$;

-- Close : tous les colis ont été pris en charge pour la livraison (aucun n'attend encore au hub).
create or replace function logistics.close_shipment(p_shipment_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_n int;
begin
  perform logistics.require_right(p_actor);
  select count(*) into v_n from logistics.parcel p where p.id in (select parcel_id from logistics.shipment_parcels(p_shipment_id)) and p.status in ('CUSTOMS_CLEARED', 'AT_DESTINATION_HUB');
  if v_n > 0 then raise exception '% colis attendent encore au hub : l''expédition ne se ferme pas.', v_n using errcode = 'LG005'; end if;
  perform logistics.move_shipment(p_shipment_id, 'CLOSED', p_actor, v_corr);
  return jsonb_build_object('shipment_id', p_shipment_id, 'status', 'CLOSED', 'correlation_id', v_corr);
end;
$$;


-- 10. La façade : l'acteur est TOUJOURS le compte connecté -------------------------------------------------------------------
create or replace function public.lg_open_consolidation(p_code text, p_warehouse_id uuid, p_destination_country text, p_mode text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.open_consolidation(p_code, p_warehouse_id, p_destination_country, p_mode, auth.uid(), null) $$;
create or replace function public.lg_add_parcel_to_consolidation(p_consolidation_id uuid, p_parcel_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.add_parcel_to_consolidation(p_consolidation_id, p_parcel_id, auth.uid()) $$;
create or replace function public.lg_close_consolidation(p_consolidation_id uuid, p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.close_consolidation(p_consolidation_id, auth.uid(), p_idempotency_key, null) $$;
create or replace function public.lg_create_shipment(p_code text, p_mode text, p_origin_branch uuid, p_destination_branch uuid,
  p_consolidation_ids uuid[] default '{}', p_parcel_ids uuid[] default '{}', p_load_unit_ids uuid[] default '{}', p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$
  select logistics.create_shipment(p_code, p_mode, p_origin_branch, p_destination_branch, auth.uid(), p_consolidation_ids, p_parcel_ids, p_load_unit_ids, p_idempotency_key, null) $$;
create or replace function public.lg_generate_manifest(p_shipment_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.generate_manifest(p_shipment_id, auth.uid(), null) $$;
create or replace function public.lg_mark_shipment_ready(p_shipment_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.mark_shipment_ready(p_shipment_id, auth.uid(), null) $$;
create or replace function public.lg_dispatch_shipment(p_shipment_id uuid, p_transport_id uuid, p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.dispatch_shipment(p_shipment_id, p_transport_id, auth.uid(), p_idempotency_key, null) $$;
create or replace function public.lg_arrive_shipment(p_shipment_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.arrive_shipment(p_shipment_id, auth.uid(), null) $$;
create or replace function public.lg_start_customs(p_shipment_id uuid, p_reference text default '', p_broker text default '', p_documents jsonb default '[]'::jsonb)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.start_customs(p_shipment_id, auth.uid(), p_reference, p_broker, p_documents, null) $$;
create or replace function public.lg_clear_customs(p_shipment_id uuid, p_reference text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.clear_customs(p_shipment_id, auth.uid(), p_reference, null) $$;
create or replace function public.lg_receive_at_hub(p_shipment_id uuid, p_hub_warehouse_id uuid default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.receive_at_hub(p_shipment_id, auth.uid(), p_hub_warehouse_id, null) $$;
create or replace function public.lg_remove_parcel_from_consolidation(p_consolidation_id uuid, p_parcel_id uuid)
returns void language sql volatile security definer set search_path = '' as $$ select logistics.remove_parcel_from_consolidation(p_consolidation_id, p_parcel_id, auth.uid()) $$;
create or replace function public.lg_mark_shipment_in_transit(p_shipment_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.mark_shipment_in_transit(p_shipment_id, auth.uid(), null) $$;
create or replace function public.lg_reject_customs(p_shipment_id uuid, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.reject_customs(p_shipment_id, auth.uid(), p_reason, null) $$;
create or replace function public.lg_close_shipment(p_shipment_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.close_shipment(p_shipment_id, auth.uid(), null) $$;
create or replace function public.lg_reopen_shipment(p_shipment_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.reopen_shipment(p_shipment_id, auth.uid(), null) $$;
create or replace function public.lg_cancel_shipment(p_shipment_id uuid, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cancel_shipment(p_shipment_id, auth.uid(), p_reason, null) $$;


-- 11. Tout fermé, sauf la façade --------------------------------------------------------------------------------------------------
do $$
declare r record;
begin
  for r in select tablename from pg_tables where schemaname = 'logistics' loop
    execute format('alter table logistics.%I enable row level security', r.tablename);
    execute format('revoke all on logistics.%I from public, anon, authenticated', r.tablename);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public' and p.proname in ('lg_open_consolidation', 'lg_add_parcel_to_consolidation', 'lg_close_consolidation', 'lg_create_shipment', 'lg_generate_manifest',
             'lg_mark_shipment_ready', 'lg_dispatch_shipment', 'lg_arrive_shipment', 'lg_start_customs', 'lg_clear_customs', 'lg_receive_at_hub', 'lg_cancel_shipment',
             'lg_remove_parcel_from_consolidation', 'lg_mark_shipment_in_transit', 'lg_reject_customs', 'lg_close_shipment', 'lg_reopen_shipment') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
revoke all on logistics.event_health from public, anon, authenticated;
grant select on logistics.event_health to service_role;
grant execute on function logistics.dispatch_events(int, text) to service_role;
grant execute on function logistics.claim_deliveries(text, int, int) to service_role;
grant execute on function logistics.ack_delivery(bigint) to service_role;
grant execute on function logistics.nack_delivery(bigint, text) to service_role;
grant execute on function logistics.requeue_dead_letter(bigint, text) to service_role;

-- Pour retirer SEULEMENT cette étape : supprimer les fonctions public.lg_* ci-dessus, puis
--   drop table if exists logistics.shipment_manifest, logistics.customs_document, logistics.customs_declaration,
--        logistics.shipment_status_history, logistics.shipment_transition, logistics.stop, logistics.trip, logistics.route, logistics.load_unit cascade;
--   drop trigger if exists guard_shipment_status on logistics.shipment;
-- (les modes de transport restent des données ; la table transport_mode n'est pas retirée.)
