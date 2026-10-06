-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 6 : le dernier kilomètre
-- -----------------------------------------------------------------------------
-- Phase 9. À coller dans Supabase > SQL Editor APRÈS 001 à 005, après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site ».
--
-- Chauffeurs, véhicules, disponibilités, zones ; missions d'enlèvement et de livraison ; moteur
-- d'affectation (zone, distance, capacité, disponibilité, poids, volume, priorité, horaires, nombre
-- d'arrêts) qui EXPLIQUE chacune de ses décisions ; tournées ; preuve de livraison (nom, signature,
-- photo, heure, GPS, code à usage unique) ; incidents. Chaque opération produit un événement.
--
-- Une règle de fond, écrite dans la base et valable quel que soit le chemin : un colis ne passe
-- « livré » qu'avec une PREUVE DE LIVRAISON. Seule la direction peut déroger, avec un motif, et la
-- dérogation est tracée.
--
-- Ne touche à aucune ancienne table. Retour arrière au bas du fichier. Rejouable sans risque.
-- =============================================================================

-- 1. Catalogue et transitions de colis ---------------------------------------------------------------------------------
alter table logistics.event_type drop constraint if exists event_type_aggregate_type_check;
alter table logistics.event_type add constraint event_type_aggregate_type_check
  check (aggregate_type in ('parcel', 'shipment', 'consolidation', 'warehouse', 'delivery', 'pickup', 'trip', 'task', 'driver', 'incident',
                            'customs', 'invoice', 'payment', 'scan'));
insert into logistics.event_type (code, aggregate_type, description) values
  ('PickupRequested',     'pickup',   'Enlèvement demandé'),
  ('PickupCompleted',     'pickup',   'Enlèvement effectué'),
  ('DeliveryCreated',     'delivery', 'Livraison créée'),
  ('TaskAssigned',        'task',     'Mission proposée à un chauffeur'),
  ('TaskAccepted',        'task',     'Mission acceptée'),
  ('TaskRefused',         'task',     'Mission refusée par le chauffeur'),
  ('TaskReassigned',      'task',     'Mission réaffectée'),
  ('TaskStarted',         'task',     'Mission commencée'),
  ('TaskCompleted',       'task',     'Mission terminée'),
  ('TaskFailed',          'task',     'Mission échouée'),
  ('TaskCancelled',       'task',     'Mission annulée'),
  ('TaskRescheduled',     'task',     'Mission replanifiée'),
  ('TripCreated',         'trip',     'Tournée créée'),
  ('TripStarted',         'trip',     'Tournée commencée'),
  ('TripCompleted',       'trip',     'Tournée terminée'),
  ('DeliveryOtpIssued',   'task',     'Code de livraison émis'),
  ('ParcelReturnedToHub', 'parcel',   'Colis ramené au hub après une livraison manquée')
on conflict (code) do nothing;

-- Une livraison manquée ou annulée ramène le colis au hub : deux transitions de plus.
-- Un droit de plus, et un seul : « livraison ». Il n'ouvre que les trois transitions du dernier kilomètre (sortir en livraison,
-- livrer, ramener au hub), et SEULEMENT pour un chauffeur actif, pendant qu'une fonction de mission s'exécute (voir actor_can).
-- Un employé qui a « colis.statut » les garde comme avant ; la direction aussi.
alter table logistics.parcel_transition drop constraint if exists parcel_transition_required_right_check;
alter table logistics.parcel_transition add constraint parcel_transition_required_right_check
  check (required_right in ('colis.statut', 'direction', 'livraison'));
insert into logistics.parcel_transition (from_status, to_status, event_type, required_right, requires_customer, requires_reason, allow_system) values
  ('OUT_FOR_DELIVERY',  'AT_DESTINATION_HUB', 'ParcelReturnedToHub', 'livraison',   true, true, false),
  ('DELIVERY_ASSIGNED', 'AT_DESTINATION_HUB', 'ParcelReturnedToHub', 'colis.statut', true, true, false)
on conflict do nothing;
update logistics.parcel_transition set required_right = 'livraison'
 where (from_status, to_status) in (('DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY'), ('OUT_FOR_DELIVERY', 'DELIVERED'));

-- (plpgsql : la table des chauffeurs n'existe qu'à l'étape suivante du fichier ; une fonction SQL la vérifierait trop tôt.)
create or replace function logistics.actor_can(p_user uuid, p_right text)
returns boolean language plpgsql stable set search_path = '' as $$
begin
  return exists (
    select 1 from logistics.app_user u
    where u.id = p_user and u.active
      and (u.role in ('manager', 'admin')
           or (u.role = 'employee' and p_right <> 'direction'
               and (p_right = any (u.rights) or (p_right = 'livraison' and 'colis.statut' = any (u.rights))))
           -- Le chauffeur : le droit « livraison » et rien d'autre, jamais en dehors d'une fonction de mission.
           or (p_right = 'livraison'
               and coalesce(current_setting('logistics.last_mile', true), 'off') = 'on'
               and exists (select 1 from logistics.driver d where d.user_id = u.id and d.status = 'ACTIVE')))
  );
end;
$$;


-- 2. Chauffeurs, véhicules, zones, disponibilités ------------------------------------------------------------------------
create table if not exists logistics.vehicle (
  id            uuid primary key default gen_random_uuid(),
  plate         text not null unique,
  kind          text not null check (kind in ('MOTORCYCLE', 'CAR', 'VAN', 'TRUCK')),
  capacity_lb   numeric(10, 2) not null check (capacity_lb > 0),
  capacity_ft3  numeric(10, 2) check (capacity_ft3 is null or capacity_ft3 > 0),
  branch_id     uuid references logistics.branch (id) on delete restrict,
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);
create table if not exists logistics.delivery_zone (
  id         uuid primary key default gen_random_uuid(),
  branch_id  uuid references logistics.branch (id) on delete restrict,
  code       text not null unique,
  name       text not null default '',
  country    text not null check (country in ('HT', 'DO', 'US')),
  cities     text[] not null default '{}',
  active     boolean not null default true
);
create table if not exists logistics.driver (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null unique references logistics.app_user (id) on delete restrict,
  full_name          text not null,
  phone              text not null default '',
  license_no         text not null default '',
  status             text not null default 'ACTIVE' check (status in ('ACTIVE', 'INACTIVE', 'ON_LEAVE')),
  home_branch_id     uuid references logistics.branch (id) on delete restrict,
  default_vehicle_id uuid references logistics.vehicle (id) on delete restrict,
  max_stops          int not null default 30 check (max_stops > 0),
  last_latitude      numeric(9, 6) check (last_latitude between -90 and 90),
  last_longitude     numeric(9, 6) check (last_longitude between -180 and 180),
  last_position_at   timestamptz,
  created_at         timestamptz not null default now()
);
create table if not exists logistics.driver_zone (
  driver_id uuid not null references logistics.driver (id) on delete restrict,
  zone_id   uuid not null references logistics.delivery_zone (id) on delete restrict,
  primary key (driver_id, zone_id)
);
create table if not exists logistics.driver_availability (
  id        uuid primary key default gen_random_uuid(),
  driver_id uuid not null references logistics.driver (id) on delete restrict,
  starts_at timestamptz not null,
  ends_at   timestamptz not null,
  available boolean not null default true,
  note      text not null default '',
  check (ends_at > starts_at)
);
create index if not exists driver_availability_idx on logistics.driver_availability (driver_id, starts_at);

-- La livraison porte tout ce qu'il faut pour la décider : où, quand, pour qui, combien ça pèse.
alter table logistics.delivery add column if not exists zone_id uuid references logistics.delivery_zone (id) on delete restrict;
alter table logistics.delivery add column if not exists customer_id uuid references logistics.customer (id) on delete restrict;
alter table logistics.delivery add column if not exists recipient_name text not null default '';
alter table logistics.delivery add column if not exists recipient_phone text not null default '';
alter table logistics.delivery add column if not exists address text not null default '';
alter table logistics.delivery add column if not exists latitude numeric(9, 6) check (latitude between -90 and 90);
alter table logistics.delivery add column if not exists longitude numeric(9, 6) check (longitude between -180 and 180);
alter table logistics.delivery add column if not exists window_start timestamptz;
alter table logistics.delivery add column if not exists window_end timestamptz;
alter table logistics.delivery add column if not exists priority int not null default 3 check (priority between 1 and 5);
alter table logistics.delivery add column if not exists weight_lb numeric(10, 2) not null default 0;
alter table logistics.delivery add column if not exists volume_ft3 numeric(10, 3) not null default 0;
alter table logistics.delivery add column if not exists otp_required boolean not null default false;
alter table logistics.delivery add column if not exists otp_hash text;
alter table logistics.delivery add column if not exists otp_salt text;
alter table logistics.delivery add column if not exists otp_expires_at timestamptz;
alter table logistics.delivery add column if not exists otp_attempts int not null default 0;

create table if not exists logistics.task_status (
  code text primary key, sort_order int not null, is_terminal boolean not null default false, label_key text not null
);
insert into logistics.task_status (code, sort_order, is_terminal, label_key) values
  ('CREATED', 10, false, 'task-created'), ('ASSIGNED', 20, false, 'task-assigned'), ('ACCEPTED', 30, false, 'task-accepted'),
  ('STARTED', 40, false, 'task-started'), ('COMPLETED', 50, true, 'task-completed'), ('FAILED', 60, false, 'task-failed'), ('CANCELLED', 70, true, 'task-cancelled')
on conflict (code) do nothing;

create table if not exists logistics.task_transition (
  from_status text not null references logistics.task_status (code),
  to_status   text not null references logistics.task_status (code),
  event_type  text not null references logistics.event_type (code),
  actor_kind  text not null check (actor_kind in ('dispatcher', 'driver', 'direction')),
  primary key (from_status, to_status)
);
insert into logistics.task_transition (from_status, to_status, event_type, actor_kind) values
  ('CREATED',  'ASSIGNED',  'TaskAssigned',    'dispatcher'),
  ('ASSIGNED', 'ASSIGNED',  'TaskReassigned',  'dispatcher'),     -- réaffectation avant réponse
  ('ASSIGNED', 'ACCEPTED',  'TaskAccepted',    'driver'),
  ('ASSIGNED', 'CREATED',   'TaskRefused',     'driver'),
  ('ACCEPTED', 'ASSIGNED',  'TaskReassigned',  'dispatcher'),     -- réaffectation après acceptation
  ('ACCEPTED', 'STARTED',   'TaskStarted',     'driver'),
  ('STARTED',  'COMPLETED', 'TaskCompleted',   'driver'),
  ('STARTED',  'FAILED',    'TaskFailed',      'driver'),
  ('FAILED',   'CREATED',   'TaskRescheduled', 'dispatcher'),
  ('CREATED',  'CANCELLED', 'TaskCancelled',   'direction'),
  ('ASSIGNED', 'CANCELLED', 'TaskCancelled',   'direction'),
  ('ACCEPTED', 'CANCELLED', 'TaskCancelled',   'direction'),
  ('FAILED',   'CANCELLED', 'TaskCancelled',   'direction')
on conflict do nothing;

-- UNE table de missions pour les deux natures (enlèvement, livraison) : mêmes états, mêmes règles, mêmes services.
create table if not exists logistics.task (
  id             uuid primary key default gen_random_uuid(),
  kind           text not null check (kind in ('PICKUP', 'DELIVERY')),
  status         text not null default 'CREATED' references logistics.task_status (code),
  delivery_id    uuid references logistics.delivery (id) on delete restrict,
  customer_id    uuid references logistics.customer (id) on delete restrict,
  zone_id        uuid references logistics.delivery_zone (id) on delete restrict,
  address        text not null default '',
  latitude       numeric(9, 6) check (latitude between -90 and 90),
  longitude      numeric(9, 6) check (longitude between -180 and 180),
  scheduled_date date not null,
  window_start   timestamptz,
  window_end     timestamptz,
  priority       int not null default 3 check (priority between 1 and 5),
  weight_lb      numeric(10, 2) not null default 0,
  volume_ft3     numeric(10, 3) not null default 0,
  parcels_expected int not null default 0,
  driver_id      uuid references logistics.driver (id) on delete restrict,
  trip_id        uuid references logistics.trip (id) on delete restrict,
  failed_reason  text,
  created_by     uuid references logistics.app_user (id) on delete restrict,
  correlation_id uuid,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  check ((kind = 'DELIVERY') = (delivery_id is not null)),
  check (kind = 'DELIVERY' or customer_id is not null),
  check (window_end is null or window_start is null or window_end > window_start)
);
create index if not exists task_driver_day_idx on logistics.task (driver_id, scheduled_date, status);
create unique index if not exists task_one_live_per_delivery on logistics.task (delivery_id) where delivery_id is not null and status not in ('COMPLETED', 'CANCELLED', 'FAILED');
create or replace view logistics.pickup_task with (security_invoker = true) as select * from logistics.task where kind = 'PICKUP';
create or replace view logistics.delivery_task with (security_invoker = true) as select * from logistics.task where kind = 'DELIVERY';

create table if not exists logistics.pickup_parcel (
  task_id   uuid not null references logistics.task (id) on delete restrict,
  parcel_id uuid not null references logistics.parcel (id) on delete restrict,
  primary key (task_id, parcel_id)
);
create unique index if not exists pickup_parcel_once on logistics.pickup_parcel (parcel_id);
alter table logistics.stop add column if not exists task_id uuid references logistics.task (id) on delete restrict;
alter table logistics.trip add column if not exists driver_id uuid references logistics.driver (id) on delete restrict;
alter table logistics.trip add column if not exists vehicle_id uuid references logistics.vehicle (id) on delete restrict;
alter table logistics.trip add column if not exists trip_date date;
alter table logistics.incident add column if not exists task_id uuid references logistics.task (id) on delete restrict;

create table if not exists logistics.assignment (
  id           uuid primary key default gen_random_uuid(),
  task_id      uuid not null references logistics.task (id) on delete restrict,
  driver_id    uuid not null references logistics.driver (id) on delete restrict,
  status       text not null default 'OFFERED' check (status in ('OFFERED', 'ACCEPTED', 'REFUSED', 'CANCELLED', 'REASSIGNED', 'COMPLETED')),
  offered_by   uuid references logistics.app_user (id) on delete restrict,
  offered_at   timestamptz not null default now(),
  responded_at timestamptz,
  reason       text,
  score        numeric(8, 2),
  detail       jsonb not null default '{}'::jsonb
);
create unique index if not exists assignment_one_live on logistics.assignment (task_id) where status in ('OFFERED', 'ACCEPTED');
create index if not exists assignment_driver_idx on logistics.assignment (driver_id, status);

create table if not exists logistics.task_status_history (
  id             bigint generated always as identity primary key,
  task_id        uuid not null references logistics.task (id) on delete restrict,
  from_status    text references logistics.task_status (code),
  to_status      text not null references logistics.task_status (code),
  occurred_at    timestamptz not null default now(),
  actor_user_id  uuid references logistics.app_user (id) on delete restrict,
  actor_label    text not null default '',
  reason         text,
  correlation_id uuid not null
);
drop trigger if exists task_status_history_append_only on logistics.task_status_history;
create trigger task_status_history_append_only before update or delete on logistics.task_status_history for each row execute function logistics.forbid_mutation();

create table if not exists logistics.proof_of_delivery (
  id             uuid primary key default gen_random_uuid(),
  task_id        uuid not null unique references logistics.task (id) on delete restrict,
  delivery_id    uuid not null references logistics.delivery (id) on delete restrict,
  driver_id      uuid not null references logistics.driver (id) on delete restrict,
  recipient_name text not null check (btrim(recipient_name) <> ''),
  signature_path text check (signature_path is null or signature_path ~ '^pod/[0-9a-f-]{36}/[A-Za-z0-9._-]{1,120}$'),
  photo_path     text check (photo_path is null or photo_path ~ '^pod/[0-9a-f-]{36}/[A-Za-z0-9._-]{1,120}$'),
  delivered_at   timestamptz not null default now(),
  latitude       numeric(9, 6) not null check (latitude between -90 and 90),
  longitude      numeric(9, 6) not null check (longitude between -180 and 180),
  otp_required   boolean not null default false,
  otp_verified   boolean not null default false,
  correlation_id uuid not null,
  check (signature_path is not null or photo_path is not null),
  check (not otp_required or otp_verified)
);
comment on table logistics.proof_of_delivery is 'Nom du destinataire, signature OU photo, heure, GPS, et le code à usage unique si la livraison l''exigeait. Ajout seul.';
drop trigger if exists proof_of_delivery_append_only on logistics.proof_of_delivery;
create trigger proof_of_delivery_append_only before update or delete on logistics.proof_of_delivery for each row execute function logistics.forbid_mutation();


-- 3. Règle de fond : « livré » exige une preuve --------------------------------------------------------------------------
create or replace function logistics.guard_parcel_status()
returns trigger language plpgsql set search_path = '' as $$
declare
  v_dans_transition boolean := coalesce(current_setting('logistics.transition', true), 'off') = 'on';
  v_derogation boolean := coalesce(current_setting('logistics.pod_override', true), 'off') = 'on';
begin
  if tg_op = 'INSERT' then
    if new.source = 'native' and new.status <> 'CREATED' then
      raise exception 'Un colis naît en statut CREATED, pas %.', new.status using errcode = 'LG001';
    end if;
    return new;
  end if;
  if new.status is distinct from old.status
     and not v_dans_transition
     and not (old.status_authority = 'legacy' and new.status_authority = 'legacy') then
    raise exception 'Le statut d''un colis ne change que par une transition autorisée (logistics.transition_parcel).' using errcode = 'LG001';
  end if;
  if new.status_authority is distinct from old.status_authority and not v_dans_transition then
    raise exception 'L''autorité du statut ne change que par une transition (legacy → core, jamais l''inverse).' using errcode = 'LG001';
  end if;
  if old.status_authority = 'core' and new.status_authority = 'legacy' then
    raise exception 'L''autorité du statut ne revient jamais à l''ancien schéma.' using errcode = 'LG001';
  end if;
  -- Livré : jamais sans preuve (sauf dérogation de la direction, tracée par deliver_without_proof).
  if new.status = 'DELIVERED' and old.status is distinct from 'DELIVERED' and new.status_authority = 'core' and not v_derogation
     and not exists (select 1 from logistics.proof_of_delivery pod join logistics.delivery_parcel dp on dp.delivery_id = pod.delivery_id where dp.parcel_id = new.id) then
    raise exception 'Un colis ne passe « livré » qu''avec une PREUVE DE LIVRAISON.' using errcode = 'LG005';
  end if;
  return new;
end;
$$;


-- 4. Outils : distance, rôles, historique, transitions de mission ---------------------------------------------------------
create or replace function logistics.distance_km(lat1 numeric, lon1 numeric, lat2 numeric, lon2 numeric)
returns numeric language sql immutable set search_path = '' as $$
  select case when $1 is null or $2 is null or $3 is null or $4 is null then null else
    round((6371 * 2 * asin(sqrt(least(1, power(sin(radians(($3 - $1) / 2)), 2) + cos(radians($1)) * cos(radians($3)) * power(sin(radians(($4 - $2) / 2)), 2)))))::numeric, 2) end
$$;

create or replace function logistics.driver_of(p_user uuid)
returns uuid language sql stable set search_path = '' as $$
  select d.id from logistics.driver d join logistics.app_user u on u.id = d.user_id where d.user_id = p_user and u.active and d.status = 'ACTIVE'
$$;

create or replace function logistics.require_driver_of_task(p_actor uuid, p_task uuid)
returns uuid language plpgsql stable set search_path = '' as $$
declare v_d uuid := logistics.driver_of(p_actor); v_t uuid;
begin
  if v_d is null then raise exception 'Réservé aux chauffeurs actifs.' using errcode = 'LG003'; end if;
  select driver_id into v_t from logistics.task where id = p_task;
  if v_t is distinct from v_d then raise exception 'Cette mission n''est pas la vôtre.' using errcode = 'LG003'; end if;
  return v_d;
end;
$$;

create or replace function logistics.guard_task_status()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'INSERT' and new.status <> 'CREATED' then raise exception 'Une mission naît en CREATED.' using errcode = 'LG001'; end if;
  if tg_op = 'UPDATE' and new.status is distinct from old.status and coalesce(current_setting('logistics.task_transition', true), 'off') <> 'on' then
    raise exception 'Le statut d''une mission ne change que par une transition autorisée.' using errcode = 'LG001';
  end if;
  return new;
end;
$$;
drop trigger if exists guard_task_status on logistics.task;
create trigger guard_task_status before insert or update on logistics.task for each row execute function logistics.guard_task_status();
drop trigger if exists touch_updated_at on logistics.task;
create trigger touch_updated_at before update on logistics.task for each row execute function logistics.touch_updated_at();

-- LA transition d'une mission. p_kind dit QUI agit (répartiteur, chauffeur, direction) : le droit est contrôlé par l'appelant.
create or replace function logistics.move_task(p_task uuid, p_to text, p_actor uuid, p_corr uuid, p_reason text default null, p_meta jsonb default '{}'::jsonb)
returns logistics.task language plpgsql volatile set search_path = '' as $$
declare v_t logistics.task; v_tr logistics.task_transition; v_label text;
begin
  select * into v_t from logistics.task where id = p_task for update;
  if not found then raise exception 'Mission introuvable.' using errcode = 'LG002'; end if;
  select * into v_tr from logistics.task_transition where from_status = v_t.status and to_status = p_to;
  if not found then raise exception 'Transition de mission non autorisée : % → %.', v_t.status, p_to using errcode = 'LG001'; end if;
  perform set_config('logistics.task_transition', 'on', true);
  update logistics.task set status = p_to where id = p_task returning * into v_t;
  perform set_config('logistics.task_transition', 'off', true);
  v_label := coalesce((select email from auth.users where id = p_actor), p_actor::text, 'system');
  insert into logistics.task_status_history (task_id, from_status, to_status, actor_user_id, actor_label, reason, correlation_id) values (p_task, v_tr.from_status, p_to, p_actor, v_label, p_reason, p_corr);
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id, metadata)
  values (p_actor, v_label, 'task.transition', 'task', p_task::text, jsonb_build_object('status', v_tr.from_status), jsonb_build_object('status', p_to), p_corr, jsonb_build_object('reason', p_reason, 'kind', v_t.kind));
  -- Le statut de la livraison et celui de l'arrêt suivent la mission, au même endroit, jamais ailleurs.
  if v_t.kind = 'DELIVERY' then
    update logistics.delivery set status = case p_to when 'CREATED' then 'PLANNED' when 'ASSIGNED' then 'ASSIGNED' when 'ACCEPTED' then 'ASSIGNED'
                                                      when 'STARTED' then 'OUT_FOR_DELIVERY' when 'COMPLETED' then 'COMPLETED'
                                                      when 'FAILED' then 'FAILED' when 'CANCELLED' then 'CANCELLED' end
     where id = v_t.delivery_id;
  end if;
  if p_to = 'COMPLETED' then update logistics.stop set status = 'DEPARTED', actual_at = now() where task_id = p_task;
  elsif p_to in ('FAILED', 'CANCELLED') then update logistics.stop set status = 'SKIPPED', actual_at = now() where task_id = p_task and status = 'PLANNED'; end if;
  perform logistics.emit(v_tr.event_type, 'task', p_task::text, p_corr, p_actor,
                         jsonb_build_object('task_id', p_task, 'kind', v_t.kind, 'from_status', v_tr.from_status, 'to_status', p_to, 'driver_id', v_t.driver_id, 'reason', p_reason) || coalesce(p_meta, '{}'::jsonb));
  return v_t;
end;
$$;


-- 5. Missions : création --------------------------------------------------------------------------------------------------
create or replace function logistics.create_pickup_task(
  p_customer_id uuid, p_address text, p_scheduled_date date, p_actor uuid,
  p_latitude numeric default null, p_longitude numeric default null, p_window_start timestamptz default null, p_window_end timestamptz default null,
  p_parcels_expected int default 1, p_weight_lb numeric default 0, p_zone_id uuid default null, p_priority int default 3, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid := gen_random_uuid(); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid());
begin
  perform logistics.require_right(p_actor);
  if not exists (select 1 from logistics.customer where id = p_customer_id) then raise exception 'Client introuvable.' using errcode = 'LG002'; end if;
  if btrim(coalesce(p_address, '')) = '' then raise exception 'L''adresse d''enlèvement est obligatoire.' using errcode = 'LG005'; end if;
  if p_scheduled_date is null then raise exception 'La date d''enlèvement est obligatoire.' using errcode = 'LG005'; end if;
  insert into logistics.task (id, kind, customer_id, zone_id, address, latitude, longitude, scheduled_date, window_start, window_end, priority, weight_lb, parcels_expected, created_by, correlation_id)
  values (v_id, 'PICKUP', p_customer_id, p_zone_id, btrim(p_address), p_latitude, p_longitude, p_scheduled_date, p_window_start, p_window_end, p_priority, coalesce(p_weight_lb, 0), greatest(coalesce(p_parcels_expected, 1), 1), p_actor, v_corr);
  insert into logistics.task_status_history (task_id, from_status, to_status, actor_user_id, actor_label, correlation_id)
  values (v_id, null, 'CREATED', p_actor, coalesce((select email from auth.users where id = p_actor), ''), v_corr);
  perform logistics.emit('PickupRequested', 'pickup', v_id::text, v_corr, p_actor, jsonb_build_object('task_id', v_id, 'customer_id', p_customer_id, 'scheduled_date', p_scheduled_date));
  return jsonb_build_object('task_id', v_id, 'status', 'CREATED', 'kind', 'PICKUP', 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.create_delivery(
  p_parcel_ids uuid[], p_hub_branch uuid, p_scheduled_for date, p_actor uuid,
  p_recipient_name text default '', p_recipient_phone text default '', p_address text default '', p_latitude numeric default null, p_longitude numeric default null,
  p_zone_id uuid default null, p_window_start timestamptz default null, p_window_end timestamptz default null, p_priority int default 3, p_otp_required boolean default false,
  p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_id uuid := gen_random_uuid(); v_task uuid := gen_random_uuid(); v_x uuid; v_p logistics.parcel; v_w numeric := 0; v_v numeric := 0; v_cust uuid;
begin
  perform logistics.require_right(p_actor);
  if coalesce(cardinality(p_parcel_ids), 0) = 0 then raise exception 'Une livraison contient au moins un colis.' using errcode = 'LG005'; end if;
  if btrim(coalesce(p_address, '')) = '' then raise exception 'L''adresse de livraison est obligatoire.' using errcode = 'LG005'; end if;
  if p_scheduled_for is null then raise exception 'La date de livraison est obligatoire.' using errcode = 'LG005'; end if;
  foreach v_x in array p_parcel_ids loop
    select * into v_p from logistics.parcel where id = v_x for update;
    if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
    if v_p.status <> 'AT_DESTINATION_HUB' then raise exception 'Le colis % est en % : seul un colis AU HUB se livre.', v_p.tracking_number, v_p.status using errcode = 'LG005'; end if;
    if v_cust is not null and v_p.customer_id is distinct from v_cust then raise exception 'Une livraison ne réunit que les colis d''un MÊME client.' using errcode = 'LG005'; end if;
    v_cust := v_p.customer_id;
    if exists (select 1 from logistics.delivery_parcel dp join logistics.task t on t.delivery_id = dp.delivery_id where dp.parcel_id = v_x and t.status not in ('COMPLETED', 'CANCELLED')) then
      raise exception 'Le colis % est déjà dans une livraison en cours.', v_p.tracking_number using errcode = 'LG005';
    end if;
    v_w := v_w + coalesce(v_p.verified_weight_lb, v_p.weight_lb, 0); v_v := v_v + coalesce(v_p.volume_ft3, 0);
  end loop;
  insert into logistics.delivery (id, destination_branch_id, scheduled_for, zone_id, customer_id, recipient_name, recipient_phone, address, latitude, longitude, window_start, window_end, priority, weight_lb, volume_ft3, otp_required)
  values (v_id, p_hub_branch, p_scheduled_for, p_zone_id, v_cust, coalesce(p_recipient_name, ''), coalesce(p_recipient_phone, ''), btrim(p_address), p_latitude, p_longitude, p_window_start, p_window_end, p_priority, v_w, v_v, p_otp_required);
  foreach v_x in array p_parcel_ids loop
    insert into logistics.delivery_parcel (delivery_id, parcel_id) values (v_id, v_x);
    perform logistics.transition_parcel(v_x, 'DELIVERY_ASSIGNED', p_actor, null, v_corr, null, null, '', null, null, jsonb_build_object('delivery_id', v_id), 'api');
  end loop;
  insert into logistics.task (id, kind, delivery_id, customer_id, zone_id, address, latitude, longitude, scheduled_date, window_start, window_end, priority, weight_lb, volume_ft3, parcels_expected, created_by, correlation_id)
  values (v_task, 'DELIVERY', v_id, v_cust, p_zone_id, btrim(p_address), p_latitude, p_longitude, p_scheduled_for, p_window_start, p_window_end, p_priority, v_w, v_v, cardinality(p_parcel_ids), p_actor, v_corr);
  insert into logistics.task_status_history (task_id, from_status, to_status, actor_user_id, actor_label, correlation_id) values (v_task, null, 'CREATED', p_actor, coalesce((select email from auth.users where id = p_actor), ''), v_corr);
  perform logistics.emit('DeliveryCreated', 'delivery', v_id::text, v_corr, p_actor, jsonb_build_object('delivery_id', v_id, 'task_id', v_task, 'parcels', cardinality(p_parcel_ids), 'weight_lb', v_w, 'otp_required', p_otp_required));
  return jsonb_build_object('delivery_id', v_id, 'task_id', v_task, 'status', 'CREATED', 'weight_lb', v_w, 'volume_ft3', v_v, 'correlation_id', v_corr);
end;
$$;


-- 6. Le moteur d'affectation : il décide ET il explique ---------------------------------------------------------------------
-- Pour une mission, chaque chauffeur est évalué. Il est ÉCARTÉ (avec la raison) s'il est inactif, hors de la zone, indisponible, sans
-- véhicule, si le poids ou le volume dépasse son véhicule, ou s'il a déjà son maximum d'arrêts. Les autres reçoivent une note :
--   100  −  distance en km (×2 si la mission est prioritaire 1-2, plafonné à 60)  −  2 par mission déjà prévue ce jour-là.
-- Les journées s'entendent à l'heure d'Haïti : une seule définition, à changer ici si l'entreprise s'installe ailleurs.
create or replace function logistics.day_start(p_day date)
returns timestamptz language sql stable set search_path = '' as $$ select p_day::timestamp at time zone 'America/Port-au-Prince' $$;

create or replace function logistics.rank_drivers(p_task_id uuid)
returns table (driver_id uuid, eligible boolean, score numeric, reasons text[])
language plpgsql stable set search_path = '' as $$
declare
  t logistics.task; d record; v_ws timestamptz; v_we timestamptz; v_d0 timestamptz; v_d1 timestamptz; v_reasons text[]; v_elig boolean; v_score numeric;
  v_n int; v_w numeric; v_v numeric; v_km numeric; v_libre boolean; v_fenetre boolean;
begin
  select * into t from logistics.task where id = p_task_id;
  if not found then raise exception 'Mission introuvable.' using errcode = 'LG002'; end if;
  v_d0 := logistics.day_start(t.scheduled_date); v_d1 := logistics.day_start(t.scheduled_date + 1);
  v_fenetre := t.window_start is not null and t.window_end is not null;
  v_ws := case when v_fenetre then t.window_start else v_d0 end;
  v_we := case when v_fenetre then t.window_end else v_d1 end;
  for d in select dr.*, v.capacity_lb, v.capacity_ft3, v.active as vehicle_active
             from logistics.driver dr left join logistics.vehicle v on v.id = dr.default_vehicle_id order by dr.id loop
    v_elig := true; v_reasons := '{}'; v_score := 100;
    if d.status <> 'ACTIVE' or not exists (select 1 from logistics.app_user u where u.id = d.user_id and u.active) then v_elig := false; v_reasons := v_reasons || 'INACTIVE'::text; end if;
    if t.zone_id is not null and not exists (select 1 from logistics.driver_zone z where z.driver_id = d.id and z.zone_id = t.zone_id) then v_elig := false; v_reasons := v_reasons || 'ZONE'::text; end if;
    -- Avec une fenêtre horaire, un créneau disponible doit la COUVRIR et aucun blocage ne doit la toucher.
    -- Sans fenêtre (n'importe quand dans la journée), il suffit d'un créneau disponible ce jour-là et d'aucun blocage couvrant TOUTE la journée.
    if v_fenetre then
      v_libre := exists (select 1 from logistics.driver_availability a where a.driver_id = d.id and a.available and a.starts_at <= v_ws and a.ends_at >= v_we)
                 and not exists (select 1 from logistics.driver_availability a where a.driver_id = d.id and not a.available and a.starts_at < v_we and a.ends_at > v_ws);
    else
      v_libre := exists (select 1 from logistics.driver_availability a where a.driver_id = d.id and a.available and a.starts_at < v_d1 and a.ends_at > v_d0)
                 and not exists (select 1 from logistics.driver_availability a where a.driver_id = d.id and not a.available and a.starts_at <= v_d0 and a.ends_at >= v_d1);
    end if;
    if not v_libre then v_elig := false; v_reasons := v_reasons || 'UNAVAILABLE'::text; end if;
    if d.default_vehicle_id is null or not coalesce(d.vehicle_active, false) then v_elig := false; v_reasons := v_reasons || 'NO_VEHICLE'::text; end if;
    -- Un chauffeur qui a déjà refusé CETTE mission ne se la voit pas reproposer par le moteur.
    if exists (select 1 from logistics.assignment x where x.task_id = t.id and x.driver_id = d.id and x.status = 'REFUSED') then v_elig := false; v_reasons := v_reasons || 'REFUSED_BEFORE'::text; end if;
    select count(*), coalesce(sum(x.weight_lb), 0), coalesce(sum(x.volume_ft3), 0) into v_n, v_w, v_v
      from logistics.task x where x.driver_id = d.id and x.scheduled_date = t.scheduled_date and x.status in ('ASSIGNED', 'ACCEPTED', 'STARTED') and x.id <> t.id;
    if d.capacity_lb is not null and v_w + t.weight_lb > d.capacity_lb then v_elig := false; v_reasons := v_reasons || 'CAPACITY_WEIGHT'::text; end if;
    if d.capacity_ft3 is not null and t.volume_ft3 > 0 and v_v + t.volume_ft3 > d.capacity_ft3 then v_elig := false; v_reasons := v_reasons || 'CAPACITY_VOLUME'::text; end if;
    if v_n >= d.max_stops then v_elig := false; v_reasons := v_reasons || 'MAX_STOPS'::text; end if;
    if v_elig then
      v_km := logistics.distance_km(d.last_latitude, d.last_longitude, t.latitude, t.longitude);
      if v_km is not null then
        v_score := v_score - least(60, v_km * case when t.priority <= 2 then 2 else 1 end);
        v_reasons := v_reasons || ('DISTANCE_KM:' || v_km::text);
      else v_reasons := v_reasons || 'NO_POSITION'::text; end if;
      v_score := v_score - 2 * v_n;
      v_reasons := v_reasons || ('LOAD:' || v_n::text);
    else v_score := null; end if;
    driver_id := d.id; eligible := v_elig; score := v_score; reasons := v_reasons;
    return next;
  end loop;
end;
$$;

-- Propose la mission au meilleur chauffeur éligible. Rien d'éligible : rien n'est créé, les raisons sont rendues.
create or replace function logistics.auto_assign(p_task_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_best record; v_all jsonb; v_t logistics.task; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_a uuid;
begin
  perform logistics.require_right(p_actor);
  select * into v_t from logistics.task where id = p_task_id for update;
  if not found then raise exception 'Mission introuvable.' using errcode = 'LG002'; end if;
  if v_t.status <> 'CREATED' then raise exception 'Seule une mission CRÉÉE se propose (elle est %).', v_t.status using errcode = 'LG001'; end if;
  select coalesce(jsonb_agg(jsonb_build_object('driver_id', r.driver_id, 'eligible', r.eligible, 'score', r.score, 'reasons', to_jsonb(r.reasons)) order by r.score desc nulls last, r.driver_id), '[]'::jsonb)
    into v_all from logistics.rank_drivers(p_task_id) r;
  select * into v_best from logistics.rank_drivers(p_task_id) r where r.eligible order by r.score desc, r.driver_id limit 1;
  if not found then return jsonb_build_object('assigned', false, 'task_id', p_task_id, 'candidates', v_all); end if;
  insert into logistics.assignment (task_id, driver_id, offered_by, score, detail) values (p_task_id, v_best.driver_id, p_actor, v_best.score, jsonb_build_object('reasons', to_jsonb(v_best.reasons), 'mode', 'auto'))
    returning id into v_a;
  update logistics.task set driver_id = v_best.driver_id where id = p_task_id;
  perform logistics.move_task(p_task_id, 'ASSIGNED', p_actor, v_corr, null, jsonb_build_object('assignment_id', v_a, 'score', v_best.score));
  return jsonb_build_object('assigned', true, 'task_id', p_task_id, 'driver_id', v_best.driver_id, 'assignment_id', v_a, 'score', v_best.score, 'reasons', to_jsonb(v_best.reasons), 'candidates', v_all, 'correlation_id', v_corr);
end;
$$;

-- Toute la journée : priorité d'abord, puis l'heure d'ouverture de la fenêtre. Chaque affectation compte dans la charge de la suivante.
create or replace function logistics.auto_assign_day(p_date date, p_actor uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare r record; v_res jsonb; v_ok int := 0; v_ko jsonb := '[]'::jsonb; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  for r in select id from logistics.task where scheduled_date = p_date and status = 'CREATED' order by priority, coalesce(window_start, logistics.day_start(scheduled_date)), created_at, id loop
    v_res := logistics.auto_assign(r.id, p_actor, v_corr);
    if (v_res ->> 'assigned')::boolean then v_ok := v_ok + 1; else v_ko := v_ko || jsonb_build_object('task_id', r.id, 'candidates', v_res -> 'candidates'); end if;
  end loop;
  return jsonb_build_object('date', p_date, 'assigned', v_ok, 'unassigned', v_ko);
end;
$$;

-- Affectation manuelle : mêmes contrôles que le moteur ; la direction peut forcer, avec un motif, et c'est tracé.
create or replace function logistics.assign_task(p_task_id uuid, p_driver_id uuid, p_actor uuid, p_force boolean default false, p_reason text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_t logistics.task; v_r record; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_a uuid; v_old uuid;
begin
  perform logistics.require_right(p_actor);
  select * into v_t from logistics.task where id = p_task_id for update;
  if not found then raise exception 'Mission introuvable.' using errcode = 'LG002'; end if;
  if v_t.status not in ('CREATED', 'ASSIGNED', 'ACCEPTED') then raise exception 'Une mission % ne s''affecte pas.', v_t.status using errcode = 'LG001'; end if;
  select * into v_r from logistics.rank_drivers(p_task_id) r where r.driver_id = p_driver_id;
  if not found then raise exception 'Chauffeur introuvable.' using errcode = 'LG002'; end if;
  if not v_r.eligible then
    if not p_force then raise exception 'Chauffeur non éligible : %.', array_to_string(v_r.reasons, ', ') using errcode = 'LG005'; end if;
    perform logistics.require_right(p_actor, 'direction');
    if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour forcer une affectation.' using errcode = 'LG005'; end if;
    insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
    values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'task.assign_forced', 'task', p_task_id::text, jsonb_build_object('driver_id', p_driver_id, 'overridden', to_jsonb(v_r.reasons), 'reason', p_reason), v_corr);
  end if;
  select driver_id into v_old from logistics.assignment where task_id = p_task_id and status in ('OFFERED', 'ACCEPTED');
  update logistics.assignment set status = 'REASSIGNED', responded_at = now(), reason = p_reason where task_id = p_task_id and status in ('OFFERED', 'ACCEPTED');
  insert into logistics.assignment (task_id, driver_id, offered_by, score, detail) values (p_task_id, p_driver_id, p_actor, v_r.score, jsonb_build_object('reasons', to_jsonb(v_r.reasons), 'mode', case when v_old is null then 'manual' else 'reassign' end, 'forced', not v_r.eligible))
    returning id into v_a;
  update logistics.task set driver_id = p_driver_id, trip_id = null where id = p_task_id;
  update logistics.stop set status = 'SKIPPED', actual_at = now() where task_id = p_task_id and status = 'PLANNED';
  perform logistics.move_task(p_task_id, 'ASSIGNED', p_actor, v_corr, p_reason, jsonb_build_object('assignment_id', v_a, 'previous_driver_id', v_old));
  return jsonb_build_object('task_id', p_task_id, 'driver_id', p_driver_id, 'assignment_id', v_a, 'reassigned', v_old is not null, 'forced', not v_r.eligible, 'correlation_id', v_corr);
end;
$$;


-- 7. Le chauffeur : accepter, refuser, commencer, terminer, échouer -----------------------------------------------------------
create or replace function logistics.accept_task(p_task_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.require_driver_of_task(p_actor, p_task_id); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid());
begin
  update logistics.assignment set status = 'ACCEPTED', responded_at = now() where task_id = p_task_id and driver_id = v_d and status = 'OFFERED';
  if not found then raise exception 'Aucune proposition en attente pour vous.' using errcode = 'LG004'; end if;
  perform logistics.move_task(p_task_id, 'ACCEPTED', p_actor, v_corr);
  return jsonb_build_object('task_id', p_task_id, 'status', 'ACCEPTED', 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.refuse_task(p_task_id uuid, p_actor uuid, p_reason text, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.require_driver_of_task(p_actor, p_task_id); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid());
begin
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif de refus est obligatoire.' using errcode = 'LG005'; end if;
  update logistics.assignment set status = 'REFUSED', responded_at = now(), reason = left(p_reason, 500) where task_id = p_task_id and driver_id = v_d and status = 'OFFERED';
  if not found then raise exception 'Aucune proposition en attente pour vous (une mission acceptée ne se refuse plus : demandez une réaffectation).' using errcode = 'LG004'; end if;
  update logistics.task set driver_id = null where id = p_task_id;
  perform logistics.move_task(p_task_id, 'CREATED', p_actor, v_corr, p_reason, jsonb_build_object('refused_by_driver_id', v_d));
  return jsonb_build_object('task_id', p_task_id, 'status', 'CREATED', 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.start_task(p_task_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.require_driver_of_task(p_actor, p_task_id); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; r record; v_n int := 0;
begin
  v_t := logistics.move_task(p_task_id, 'STARTED', p_actor, v_corr);
  if v_t.kind = 'DELIVERY' then
    perform set_config('logistics.last_mile', 'on', true);
    for r in select dp.parcel_id from logistics.delivery_parcel dp where dp.delivery_id = v_t.delivery_id order by dp.parcel_id loop
      perform logistics.transition_parcel(r.parcel_id, 'OUT_FOR_DELIVERY', p_actor, null, v_corr, null, null, '', null, null, jsonb_build_object('task_id', p_task_id), 'api');
      v_n := v_n + 1;
    end loop;
    perform set_config('logistics.last_mile', 'off', true);
  end if;
  return jsonb_build_object('task_id', p_task_id, 'status', 'STARTED', 'parcels_out', v_n, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.complete_pickup(p_task_id uuid, p_actor uuid, p_parcel_ids uuid[], p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.require_driver_of_task(p_actor, p_task_id); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; v_x uuid; v_p logistics.parcel;
begin
  select * into v_t from logistics.task where id = p_task_id;
  if v_t.kind <> 'PICKUP' then raise exception 'Ce n''est pas un enlèvement.' using errcode = 'LG005'; end if;
  if coalesce(cardinality(p_parcel_ids), 0) = 0 then raise exception 'Un enlèvement termine avec au moins un colis collecté.' using errcode = 'LG005'; end if;
  foreach v_x in array p_parcel_ids loop
    select * into v_p from logistics.parcel where id = v_x;
    if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
    if v_p.customer_id is distinct from v_t.customer_id then raise exception 'Le colis % n''appartient pas au client de l''enlèvement.', v_p.tracking_number using errcode = 'LG005'; end if;
    if v_p.status <> 'CREATED' then raise exception 'Le colis % est en % : un colis déjà reçu ne s''enlève pas.', v_p.tracking_number, v_p.status using errcode = 'LG005'; end if;
    if exists (select 1 from logistics.pickup_parcel where parcel_id = v_x) then raise exception 'Le colis % a déjà été enlevé.', v_p.tracking_number using errcode = 'LG005'; end if;
    insert into logistics.pickup_parcel (task_id, parcel_id) values (p_task_id, v_x);
  end loop;
  perform logistics.move_task(p_task_id, 'COMPLETED', p_actor, v_corr, null, jsonb_build_object('collected', cardinality(p_parcel_ids)));
  update logistics.assignment set status = 'COMPLETED', responded_at = now() where task_id = p_task_id and status = 'ACCEPTED';
  perform logistics.emit('PickupCompleted', 'pickup', p_task_id::text, v_corr, p_actor, jsonb_build_object('task_id', p_task_id, 'parcels', to_jsonb(p_parcel_ids)));
  return jsonb_build_object('task_id', p_task_id, 'status', 'COMPLETED', 'collected', cardinality(p_parcel_ids), 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.issue_delivery_otp(p_task_id uuid, p_actor uuid, p_valid_hours int default 24, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_t logistics.task; v_code text; v_salt text := encode(sha256(convert_to(gen_random_uuid()::text, 'UTF8')), 'hex'); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid());
begin
  perform logistics.require_right(p_actor);
  select * into v_t from logistics.task where id = p_task_id;
  if not found or v_t.kind <> 'DELIVERY' then raise exception 'Livraison introuvable.' using errcode = 'LG002'; end if;
  if v_t.status in ('COMPLETED', 'CANCELLED') then raise exception 'Mission % : plus de code à émettre.', v_t.status using errcode = 'LG004'; end if;
  v_code := lpad(((('x' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 8))::bit(32)::bigint) % 1000000)::text, 6, '0');
  update logistics.delivery set otp_required = true, otp_salt = v_salt, otp_hash = encode(sha256(convert_to(v_salt || v_code, 'UTF8')), 'hex'),
         otp_expires_at = now() + make_interval(hours => p_valid_hours), otp_attempts = 0 where id = v_t.delivery_id;
  -- Le code part vers le DESTINATAIRE (notification), jamais vers le chauffeur : c'est ce qui prouve que la personne est là.
  insert into logistics.notification (customer_id, channel, template, payload)
  values (v_t.customer_id, 'whatsapp', 'DeliveryOtp', jsonb_build_object('task_id', p_task_id, 'code', v_code, 'expires_hours', p_valid_hours,
                     'recipient_phone', (select recipient_phone from logistics.delivery where id = v_t.delivery_id)));
  perform logistics.emit('DeliveryOtpIssued', 'task', p_task_id::text, v_corr, p_actor, jsonb_build_object('task_id', p_task_id, 'valid_hours', p_valid_hours));
  return jsonb_build_object('task_id', p_task_id, 'issued', true, 'valid_hours', p_valid_hours);
end;
$$;

create or replace function logistics.complete_delivery(
  p_task_id uuid, p_actor uuid, p_recipient_name text, p_latitude numeric, p_longitude numeric,
  p_signature_path text default null, p_photo_path text default null, p_otp text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_d uuid := logistics.require_driver_of_task(p_actor, p_task_id); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; v_del logistics.delivery;
  v_pod uuid := gen_random_uuid(); r record; v_n int := 0; v_ok boolean := false; v_tid uuid;
begin
  select * into v_t from logistics.task where id = p_task_id for update;
  if v_t.kind <> 'DELIVERY' then raise exception 'Ce n''est pas une livraison.' using errcode = 'LG005'; end if;
  if v_t.status <> 'STARTED' then raise exception 'La livraison doit être COMMENCÉE (elle est %).', v_t.status using errcode = 'LG001'; end if;
  if btrim(coalesce(p_recipient_name, '')) = '' then raise exception 'Le nom du destinataire est obligatoire.' using errcode = 'LG005'; end if;
  if p_latitude is null or p_longitude is null then raise exception 'La position GPS est obligatoire.' using errcode = 'LG005'; end if;
  if p_signature_path is null and p_photo_path is null then raise exception 'Une signature ou une photo est obligatoire.' using errcode = 'LG005'; end if;
  -- Les fichiers de preuve vivent sous pod/<id de la mission>/ : on ne s'appuie jamais sur le fichier d'une autre mission.
  if (p_signature_path is not null and p_signature_path not like 'pod/' || p_task_id::text || '/%')
     or (p_photo_path is not null and p_photo_path not like 'pod/' || p_task_id::text || '/%') then
    raise exception 'Les fichiers de preuve doivent se trouver sous pod/%/.', p_task_id using errcode = 'LG005';
  end if;
  select * into v_del from logistics.delivery where id = v_t.delivery_id for update;
  if v_del.otp_required then
    if v_del.otp_hash is null then raise exception 'Un code est exigé mais n''a pas été émis.' using errcode = 'LG005'; end if;
    if v_del.otp_attempts >= 5 then raise exception 'Trop d''essais : le code est bloqué, faites-en émettre un nouveau.' using errcode = 'LG004'; end if;
    if v_del.otp_expires_at < now() then raise exception 'Le code a expiré : faites-en émettre un nouveau.' using errcode = 'LG004'; end if;
    v_ok := coalesce(p_otp, '') <> '' and encode(sha256(convert_to(v_del.otp_salt || p_otp, 'UTF8')), 'hex') = v_del.otp_hash;
    if not v_ok then
      -- Le compteur doit survivre à l'erreur : on le note puis on échoue sans annuler cette écriture.
      update logistics.delivery set otp_attempts = otp_attempts + 1 where id = v_del.id;
      return jsonb_build_object('completed', false, 'reason', 'OTP_INVALID', 'attempts_left', 5 - (v_del.otp_attempts + 1));
    end if;
  end if;
  insert into logistics.proof_of_delivery (id, task_id, delivery_id, driver_id, recipient_name, signature_path, photo_path, latitude, longitude, otp_required, otp_verified, correlation_id)
  values (v_pod, p_task_id, v_t.delivery_id, v_d, btrim(p_recipient_name), p_signature_path, p_photo_path, p_latitude, p_longitude, v_del.otp_required, v_ok, v_corr);
  perform logistics.emit('ProofOfDeliveryCreated', 'delivery', v_t.delivery_id::text, v_corr, p_actor, jsonb_build_object('pod_id', v_pod, 'task_id', p_task_id, 'delivery_id', v_t.delivery_id, 'otp_verified', v_ok));
  perform set_config('logistics.last_mile', 'on', true);
  for r in select dp.parcel_id from logistics.delivery_parcel dp where dp.delivery_id = v_t.delivery_id order by dp.parcel_id loop
    perform logistics.transition_parcel(r.parcel_id, 'DELIVERED', p_actor, null, v_corr, null, null, '', null, null, jsonb_build_object('pod_id', v_pod), 'api');
    v_n := v_n + 1;
  end loop;
  perform set_config('logistics.last_mile', 'off', true);
  update logistics.delivery set otp_hash = null, otp_salt = null where id = v_t.delivery_id;
  perform logistics.move_task(p_task_id, 'COMPLETED', p_actor, v_corr, null, jsonb_build_object('pod_id', v_pod));
  update logistics.assignment set status = 'COMPLETED', responded_at = now() where task_id = p_task_id and status = 'ACCEPTED';
  return jsonb_build_object('completed', true, 'pod_id', v_pod, 'task_id', p_task_id, 'parcels_delivered', v_n, 'correlation_id', v_corr);
end;
$$;

-- Échec : l'incident est consigné, les colis reviennent au hub, la livraison est « échouée ». La mission peut être replanifiée.
create or replace function logistics.fail_task(p_task_id uuid, p_actor uuid, p_incident_type text, p_description text default '', p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.require_driver_of_task(p_actor, p_task_id); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; v_inc uuid; r record;
begin
  if p_incident_type not in ('CUSTOMER_ABSENT', 'WRONG_ADDRESS', 'DAMAGED', 'REFUSED', 'VEHICLE_PROBLEM', 'PAYMENT_PROBLEM', 'OTHER') then
    raise exception 'Type d''incident inconnu pour une mission : %.', p_incident_type using errcode = 'LG005';
  end if;
  select * into v_t from logistics.task where id = p_task_id for update;
  if v_t.status <> 'STARTED' then raise exception 'Seule une mission COMMENCÉE peut échouer (elle est %).', v_t.status using errcode = 'LG001'; end if;
  v_inc := (select logistics.report_incident_for_task(v_t.id, p_incident_type, p_description, p_actor, v_corr));
  update logistics.task set failed_reason = p_incident_type where id = p_task_id;
  perform logistics.move_task(p_task_id, 'FAILED', p_actor, v_corr, p_incident_type, jsonb_build_object('incident_id', v_inc));
  update logistics.assignment set status = 'COMPLETED', responded_at = now(), reason = p_incident_type where task_id = p_task_id and status = 'ACCEPTED';
  if v_t.kind = 'DELIVERY' then
    perform set_config('logistics.last_mile', 'on', true);
    for r in select dp.parcel_id from logistics.delivery_parcel dp where dp.delivery_id = v_t.delivery_id order by dp.parcel_id loop
      perform logistics.transition_parcel(r.parcel_id, 'AT_DESTINATION_HUB', p_actor, null, v_corr, null, null, '', null, 'Livraison manquée : ' || p_incident_type, jsonb_build_object('task_id', p_task_id), 'api');
    end loop;
    perform set_config('logistics.last_mile', 'off', true);
  end if;
  return jsonb_build_object('task_id', p_task_id, 'status', 'FAILED', 'incident_id', v_inc, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.report_incident_for_task(p_task uuid, p_type text, p_description text, p_actor uuid, p_corr uuid)
returns uuid language plpgsql volatile set search_path = '' as $$
declare v_id uuid; v_parcel uuid;
begin
  select dp.parcel_id into v_parcel from logistics.task t join logistics.delivery_parcel dp on dp.delivery_id = t.delivery_id where t.id = p_task order by dp.parcel_id limit 1;
  insert into logistics.incident (parcel_id, task_id, type, severity, description, reported_by, correlation_id)
  values (v_parcel, p_task, p_type, case when p_type in ('DAMAGED', 'REFUSED') then 'HIGH' else 'MEDIUM' end, left(coalesce(p_description, ''), 2000), p_actor, p_corr) returning id into v_id;
  perform logistics.emit('IncidentCreated', 'incident', v_id::text, p_corr, p_actor, jsonb_build_object('incident_id', v_id, 'type', p_type, 'task_id', p_task));
  return v_id;
end;
$$;

create or replace function logistics.reschedule_task(p_task_id uuid, p_actor uuid, p_new_date date, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; r record;
begin
  perform logistics.require_right(p_actor);
  if p_new_date is null then raise exception 'Une nouvelle date est obligatoire.' using errcode = 'LG005'; end if;
  select * into v_t from logistics.task where id = p_task_id for update;
  if v_t.status <> 'FAILED' then raise exception 'Seule une mission ÉCHOUÉE se replanifie (elle est %).', v_t.status using errcode = 'LG001'; end if;
  update logistics.task set driver_id = null, scheduled_date = p_new_date, failed_reason = null, trip_id = null where id = p_task_id;
  perform logistics.move_task(p_task_id, 'CREATED', p_actor, v_corr, 'replanifiée', jsonb_build_object('new_date', p_new_date));
  if v_t.kind = 'DELIVERY' then
    update logistics.delivery set scheduled_for = p_new_date where id = v_t.delivery_id;
    for r in select dp.parcel_id from logistics.delivery_parcel dp where dp.delivery_id = v_t.delivery_id order by dp.parcel_id loop
      perform logistics.transition_parcel(r.parcel_id, 'DELIVERY_ASSIGNED', p_actor, null, v_corr, null, null, '', null, null, jsonb_build_object('rescheduled', true), 'api');
    end loop;
  end if;
  return jsonb_build_object('task_id', p_task_id, 'status', 'CREATED', 'scheduled_date', p_new_date, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.cancel_task(p_task_id uuid, p_actor uuid, p_reason text, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; r record;
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif d''annulation est obligatoire.' using errcode = 'LG005'; end if;
  select * into v_t from logistics.task where id = p_task_id for update;
  perform logistics.move_task(p_task_id, 'CANCELLED', p_actor, v_corr, p_reason);
  update logistics.assignment set status = 'CANCELLED', responded_at = now(), reason = p_reason where task_id = p_task_id and status in ('OFFERED', 'ACCEPTED');
  if v_t.kind = 'DELIVERY' then
    for r in select dp.parcel_id from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = v_t.delivery_id and p.status = 'DELIVERY_ASSIGNED' order by dp.parcel_id loop
      perform logistics.transition_parcel(r.parcel_id, 'AT_DESTINATION_HUB', p_actor, null, v_corr, null, null, '', null, 'Livraison annulée : ' || p_reason, '{}', 'api');
    end loop;
  end if;
  return jsonb_build_object('task_id', p_task_id, 'status', 'CANCELLED', 'correlation_id', v_corr);
end;
$$;

-- La direction peut livrer SANS preuve (colis remis à un voisin, application en panne), avec un motif ; c'est tracé.
create or replace function logistics.deliver_without_proof(p_parcel_id uuid, p_actor uuid, p_reason text, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_r jsonb;
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour livrer sans preuve.' using errcode = 'LG005'; end if;
  perform set_config('logistics.pod_override', 'on', true);
  v_r := logistics.transition_parcel(p_parcel_id, 'DELIVERED', p_actor, null, v_corr, null, null, '', null, p_reason, jsonb_build_object('pod_override', true), 'manual');
  perform set_config('logistics.pod_override', 'off', true);
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'parcel.delivered_without_proof', 'parcel', p_parcel_id::text, jsonb_build_object('reason', p_reason), v_corr);
  return v_r;
end;
$$;

create or replace function logistics.update_driver_position(p_actor uuid, p_latitude numeric, p_longitude numeric)
returns void language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.driver_of(p_actor);
begin
  if v_d is null then raise exception 'Réservé aux chauffeurs actifs.' using errcode = 'LG003'; end if;
  if p_latitude not between -90 and 90 or p_longitude not between -180 and 180 then raise exception 'Position invalide.' using errcode = 'LG005'; end if;
  update logistics.driver set last_latitude = p_latitude, last_longitude = p_longitude, last_position_at = now() where id = v_d;
end;
$$;

create or replace function logistics.create_driver(p_user_id uuid, p_actor uuid, p_full_name text, p_phone text default '', p_vehicle_id uuid default null, p_home_branch uuid default null, p_max_stops int default 30)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid;
begin
  perform logistics.require_right(p_actor, 'direction');
  -- Un chauffeur est un membre de l'ÉQUIPE (jamais un client) qui a, en plus, une fiche chauffeur. Son rôle ne change pas.
  if not exists (select 1 from logistics.app_user where id = p_user_id and active) then raise exception 'Compte d''équipe introuvable ou inactif.' using errcode = 'LG002'; end if;
  insert into logistics.driver (user_id, full_name, phone, default_vehicle_id, home_branch_id, max_stops) values (p_user_id, p_full_name, p_phone, p_vehicle_id, p_home_branch, p_max_stops) returning id into v_id;
  return v_id;
end;
$$;


-- 8. Tournées : Dispatch → Route → Out for delivery ---------------------------------------------------------------------------
create or replace function logistics.create_trip(p_driver_id uuid, p_trip_date date, p_task_ids uuid[], p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_dr logistics.driver; v_veh logistics.vehicle; v_trip uuid := gen_random_uuid(); v_x uuid; v_t logistics.task; v_seq int := 0; v_w numeric := 0; v_v numeric := 0;
begin
  perform logistics.require_right(p_actor);
  select * into v_dr from logistics.driver where id = p_driver_id and status = 'ACTIVE';
  if not found then raise exception 'Chauffeur introuvable ou inactif.' using errcode = 'LG002'; end if;
  select * into v_veh from logistics.vehicle where id = v_dr.default_vehicle_id and active;
  if not found then raise exception 'Le chauffeur n''a pas de véhicule actif.' using errcode = 'LG005'; end if;
  if coalesce(cardinality(p_task_ids), 0) = 0 then raise exception 'Une tournée contient au moins une mission.' using errcode = 'LG005'; end if;
  if cardinality(p_task_ids) > v_dr.max_stops then raise exception 'Trop d''arrêts (% pour un maximum de %).', cardinality(p_task_ids), v_dr.max_stops using errcode = 'LG005'; end if;
  insert into logistics.trip (id, kind, driver_id, vehicle_id, trip_date, planned_departure_at) values (v_trip, 'LASTMILE', p_driver_id, v_veh.id, p_trip_date, p_trip_date::timestamptz);
  foreach v_x in array p_task_ids loop
    select * into v_t from logistics.task where id = v_x for update;
    if not found then raise exception 'Mission introuvable.' using errcode = 'LG002'; end if;
    if v_t.status <> 'ACCEPTED' or v_t.driver_id is distinct from p_driver_id then raise exception 'La mission % doit être ACCEPTÉE par ce chauffeur (elle est %).', v_x, v_t.status using errcode = 'LG005'; end if;
    if v_t.scheduled_date <> p_trip_date then raise exception 'La mission % est prévue un autre jour.', v_x using errcode = 'LG005'; end if;
    if v_t.trip_id is not null then raise exception 'La mission % est déjà dans une tournée.', v_x using errcode = 'LG005'; end if;
    v_w := v_w + v_t.weight_lb; v_v := v_v + v_t.volume_ft3; v_seq := v_seq + 1;
    insert into logistics.stop (trip_id, sequence, kind, task_id, planned_at) values (v_trip, v_seq, case when v_t.kind = 'PICKUP' then 'PICKUP' else 'DELIVERY' end, v_x, v_t.window_start);
    update logistics.task set trip_id = v_trip where id = v_x;
  end loop;
  if v_w > v_veh.capacity_lb then raise exception 'La tournée (% lb) dépasse la capacité du véhicule (% lb).', v_w, v_veh.capacity_lb using errcode = 'LG005'; end if;
  if v_veh.capacity_ft3 is not null and v_v > v_veh.capacity_ft3 then raise exception 'La tournée (% pi³) dépasse le volume du véhicule (% pi³).', v_v, v_veh.capacity_ft3 using errcode = 'LG005'; end if;
  perform logistics.emit('TripCreated', 'trip', v_trip::text, v_corr, p_actor, jsonb_build_object('trip_id', v_trip, 'driver_id', p_driver_id, 'stops', v_seq, 'weight_lb', v_w));
  return jsonb_build_object('trip_id', v_trip, 'stops', v_seq, 'weight_lb', v_w, 'volume_ft3', v_v, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.start_trip(p_trip_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.driver_of(p_actor); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_trip logistics.trip; r record; v_n int := 0;
begin
  if v_d is null then raise exception 'Réservé aux chauffeurs actifs.' using errcode = 'LG003'; end if;
  select * into v_trip from logistics.trip where id = p_trip_id for update;
  if not found or v_trip.driver_id is distinct from v_d then raise exception 'Cette tournée n''est pas la vôtre.' using errcode = 'LG003'; end if;
  if v_trip.status <> 'PLANNED' then raise exception 'La tournée est %.', v_trip.status using errcode = 'LG001'; end if;
  update logistics.trip set status = 'STARTED', actual_departure_at = now() where id = p_trip_id;
  for r in select t.id from logistics.task t where t.trip_id = p_trip_id and t.status = 'ACCEPTED' order by t.id loop
    perform logistics.start_task(r.id, p_actor, v_corr); v_n := v_n + 1;
  end loop;
  perform logistics.emit('TripStarted', 'trip', p_trip_id::text, v_corr, p_actor, jsonb_build_object('trip_id', p_trip_id, 'tasks_started', v_n));
  return jsonb_build_object('trip_id', p_trip_id, 'status', 'STARTED', 'tasks_started', v_n, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.complete_trip(p_trip_id uuid, p_actor uuid, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.driver_of(p_actor); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_open int;
begin
  if v_d is null then raise exception 'Réservé aux chauffeurs actifs.' using errcode = 'LG003'; end if;
  if not exists (select 1 from logistics.trip where id = p_trip_id and driver_id = v_d and status = 'STARTED') then raise exception 'Tournée introuvable, pas la vôtre, ou non commencée.' using errcode = 'LG001'; end if;
  select count(*) into v_open from logistics.task where trip_id = p_trip_id and status in ('ACCEPTED', 'STARTED');
  if v_open > 0 then raise exception '% mission(s) non terminée(s) : terminez-les ou déclarez l''échec.', v_open using errcode = 'LG005'; end if;
  update logistics.trip set status = 'COMPLETED', actual_arrival_at = now() where id = p_trip_id;
  perform logistics.emit('TripCompleted', 'trip', p_trip_id::text, v_corr, p_actor, jsonb_build_object('trip_id', p_trip_id));
  return jsonb_build_object('trip_id', p_trip_id, 'status', 'COMPLETED');
end;
$$;


-- 8 bis. Préparation, disponibilités, lecture --------------------------------------------------------------------------------
create or replace function logistics.create_vehicle(p_actor uuid, p_plate text, p_kind text, p_capacity_lb numeric, p_capacity_ft3 numeric default null, p_branch uuid default null)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid;
begin
  perform logistics.require_right(p_actor, 'direction');
  insert into logistics.vehicle (plate, kind, capacity_lb, capacity_ft3, branch_id) values (upper(btrim(p_plate)), p_kind, p_capacity_lb, p_capacity_ft3, p_branch) returning id into v_id;
  return v_id;
end;
$$;
create or replace function logistics.create_zone(p_actor uuid, p_code text, p_name text, p_country text, p_cities text[] default '{}', p_branch uuid default null)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid;
begin
  perform logistics.require_right(p_actor, 'direction');
  insert into logistics.delivery_zone (code, name, country, cities, branch_id) values (upper(btrim(p_code)), p_name, p_country, coalesce(p_cities, '{}'), p_branch) returning id into v_id;
  return v_id;
end;
$$;
create or replace function logistics.set_driver_zones(p_actor uuid, p_driver uuid, p_zone_ids uuid[])
returns void language plpgsql volatile security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'direction');
  delete from logistics.driver_zone where driver_id = p_driver;
  insert into logistics.driver_zone (driver_id, zone_id) select p_driver, z from unnest(coalesce(p_zone_ids, '{}')) z;
end;
$$;
-- Un chauffeur déclare SES disponibilités ; le personnel autorisé déclare celles de n'importe qui.
create or replace function logistics.set_availability(p_actor uuid, p_driver uuid, p_starts timestamptz, p_ends timestamptz, p_available boolean default true, p_note text default '')
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid;
begin
  if logistics.driver_of(p_actor) is distinct from p_driver then perform logistics.require_right(p_actor); end if;
  if p_ends is null or p_starts is null or p_ends <= p_starts then raise exception 'Créneau invalide : la fin doit suivre le début.' using errcode = 'LG005'; end if;
  insert into logistics.driver_availability (driver_id, starts_at, ends_at, available, note) values (p_driver, p_starts, p_ends, coalesce(p_available, true), coalesce(p_note, '')) returning id into v_id;
  return v_id;
end;
$$;

-- Ce que le chauffeur voit : SES missions en cours, rien d'autre. Jamais le code de livraison.
create or replace function logistics.my_tasks(p_actor uuid, p_date date default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_d uuid := logistics.driver_of(p_actor);
begin
  if v_d is null then raise exception 'Réservé aux chauffeurs actifs.' using errcode = 'LG003'; end if;
  return coalesce((
    select jsonb_agg(jsonb_build_object(
             'task_id', t.id, 'kind', t.kind, 'status', t.status, 'address', t.address, 'latitude', t.latitude, 'longitude', t.longitude,
             'scheduled_date', t.scheduled_date, 'window_start', t.window_start, 'window_end', t.window_end, 'priority', t.priority,
             'weight_lb', t.weight_lb, 'trip_id', t.trip_id, 'otp_required', coalesce(d.otp_required, false),
             'recipient_name', d.recipient_name, 'recipient_phone', d.recipient_phone,
             'parcels', coalesce((select jsonb_agg(jsonb_build_object('parcel_id', p.id, 'tracking_number', p.tracking_number, 'status', p.status) order by p.tracking_number)
                                    from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = t.delivery_id), '[]'::jsonb))
           order by t.priority, t.window_start nulls last, t.created_at, t.id)
      from logistics.task t left join logistics.delivery d on d.id = t.delivery_id
     where t.driver_id = v_d and t.status in ('ASSIGNED', 'ACCEPTED', 'STARTED') and (p_date is null or t.scheduled_date = p_date)), '[]'::jsonb);
end;
$$;
create or replace function logistics.task_board(p_actor uuid, p_date date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor);
  return coalesce((
    select jsonb_agg(jsonb_build_object('task_id', t.id, 'kind', t.kind, 'status', t.status, 'driver_id', t.driver_id, 'driver', dr.full_name, 'address', t.address,
                                        'priority', t.priority, 'weight_lb', t.weight_lb, 'failed_reason', t.failed_reason, 'trip_id', t.trip_id)
                     order by t.priority, t.id)
      from logistics.task t left join logistics.driver dr on dr.id = t.driver_id where t.scheduled_date = p_date), '[]'::jsonb);
end;
$$;


-- 9. Façade -----------------------------------------------------------------------------------------------------------------------------
create or replace function public.lg_create_pickup_task(p_customer_id uuid, p_address text, p_scheduled_date date, p_latitude numeric default null, p_longitude numeric default null,
  p_window_start timestamptz default null, p_window_end timestamptz default null, p_parcels_expected int default 1, p_weight_lb numeric default 0, p_zone_id uuid default null, p_priority int default 3)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_pickup_task(p_customer_id, p_address, p_scheduled_date, auth.uid(), p_latitude, p_longitude, p_window_start, p_window_end, p_parcels_expected, p_weight_lb, p_zone_id, p_priority, null) $$;
create or replace function public.lg_create_delivery(p_parcel_ids uuid[], p_hub_branch uuid, p_scheduled_for date, p_recipient_name text default '', p_recipient_phone text default '', p_address text default '',
  p_latitude numeric default null, p_longitude numeric default null, p_zone_id uuid default null, p_window_start timestamptz default null, p_window_end timestamptz default null, p_priority int default 3, p_otp_required boolean default false)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_delivery(p_parcel_ids, p_hub_branch, p_scheduled_for, auth.uid(), p_recipient_name, p_recipient_phone, p_address, p_latitude, p_longitude, p_zone_id, p_window_start, p_window_end, p_priority, p_otp_required, null) $$;
create or replace function public.lg_rank_drivers(p_task_id uuid)
returns table (driver_id uuid, eligible boolean, score numeric, reasons text[]) language plpgsql stable security definer set search_path = '' as $$
begin perform logistics.require_right(auth.uid()); return query select * from logistics.rank_drivers(p_task_id); end; $$;
create or replace function public.lg_auto_assign_task(p_task_id uuid) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.auto_assign(p_task_id, auth.uid(), null) $$;
create or replace function public.lg_auto_assign_day(p_date date) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.auto_assign_day(p_date, auth.uid()) $$;
create or replace function public.lg_assign_task(p_task_id uuid, p_driver_id uuid, p_force boolean default false, p_reason text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.assign_task(p_task_id, p_driver_id, auth.uid(), p_force, p_reason, null) $$;
create or replace function public.lg_accept_task(p_task_id uuid) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.accept_task(p_task_id, auth.uid(), null) $$;
create or replace function public.lg_refuse_task(p_task_id uuid, p_reason text) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.refuse_task(p_task_id, auth.uid(), p_reason, null) $$;
create or replace function public.lg_start_task(p_task_id uuid) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.start_task(p_task_id, auth.uid(), null) $$;
create or replace function public.lg_complete_pickup(p_task_id uuid, p_parcel_ids uuid[]) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.complete_pickup(p_task_id, auth.uid(), p_parcel_ids, null) $$;
create or replace function public.lg_complete_delivery(p_task_id uuid, p_recipient_name text, p_latitude numeric, p_longitude numeric, p_signature_path text default null, p_photo_path text default null, p_otp text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.complete_delivery(p_task_id, auth.uid(), p_recipient_name, p_latitude, p_longitude, p_signature_path, p_photo_path, p_otp, null) $$;
create or replace function public.lg_fail_task(p_task_id uuid, p_incident_type text, p_description text default '') returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.fail_task(p_task_id, auth.uid(), p_incident_type, p_description, null) $$;
create or replace function public.lg_reschedule_task(p_task_id uuid, p_new_date date) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.reschedule_task(p_task_id, auth.uid(), p_new_date, null) $$;
create or replace function public.lg_cancel_task(p_task_id uuid, p_reason text) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cancel_task(p_task_id, auth.uid(), p_reason, null) $$;
create or replace function public.lg_issue_delivery_otp(p_task_id uuid, p_valid_hours int default 24) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.issue_delivery_otp(p_task_id, auth.uid(), p_valid_hours, null) $$;
create or replace function public.lg_deliver_without_proof(p_parcel_id uuid, p_reason text) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.deliver_without_proof(p_parcel_id, auth.uid(), p_reason, null) $$;
create or replace function public.lg_update_driver_position(p_latitude numeric, p_longitude numeric) returns void language sql volatile security definer set search_path = '' as $$ select logistics.update_driver_position(auth.uid(), p_latitude, p_longitude) $$;
create or replace function public.lg_create_trip(p_driver_id uuid, p_trip_date date, p_task_ids uuid[]) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_trip(p_driver_id, p_trip_date, p_task_ids, auth.uid(), null) $$;
create or replace function public.lg_start_trip(p_trip_id uuid) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.start_trip(p_trip_id, auth.uid(), null) $$;
create or replace function public.lg_complete_trip(p_trip_id uuid) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.complete_trip(p_trip_id, auth.uid(), null) $$;

create or replace function public.lg_create_vehicle(p_plate text, p_kind text, p_capacity_lb numeric, p_capacity_ft3 numeric default null, p_branch uuid default null)
returns uuid language sql volatile security definer set search_path = '' as $$ select logistics.create_vehicle(auth.uid(), p_plate, p_kind, p_capacity_lb, p_capacity_ft3, p_branch) $$;
create or replace function public.lg_create_zone(p_code text, p_name text, p_country text, p_cities text[] default '{}', p_branch uuid default null)
returns uuid language sql volatile security definer set search_path = '' as $$ select logistics.create_zone(auth.uid(), p_code, p_name, p_country, p_cities, p_branch) $$;
create or replace function public.lg_create_driver(p_user_id uuid, p_full_name text, p_phone text default '', p_vehicle_id uuid default null, p_home_branch uuid default null, p_max_stops int default 30)
returns uuid language sql volatile security definer set search_path = '' as $$ select logistics.create_driver(p_user_id, auth.uid(), p_full_name, p_phone, p_vehicle_id, p_home_branch, p_max_stops) $$;
create or replace function public.lg_set_driver_zones(p_driver uuid, p_zone_ids uuid[])
returns void language sql volatile security definer set search_path = '' as $$ select logistics.set_driver_zones(auth.uid(), p_driver, p_zone_ids) $$;
create or replace function public.lg_set_availability(p_driver uuid, p_starts timestamptz, p_ends timestamptz, p_available boolean default true, p_note text default '')
returns uuid language sql volatile security definer set search_path = '' as $$ select logistics.set_availability(auth.uid(), p_driver, p_starts, p_ends, p_available, p_note) $$;
create or replace function public.lg_my_tasks(p_date date default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_tasks(auth.uid(), p_date) $$;
create or replace function public.lg_task_board(p_date date)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.task_board(auth.uid(), p_date) $$;


-- 10. Tout fermé, sauf la façade ------------------------------------------------------------------------------------------------------------
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
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\_%' loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
revoke all on logistics.event_health, logistics.pickup_task, logistics.delivery_task from public, anon, authenticated;
grant select on logistics.event_health to service_role;
grant execute on function logistics.dispatch_events(int, text) to service_role;
grant execute on function logistics.claim_deliveries(text, int, int) to service_role;
grant execute on function logistics.ack_delivery(bigint) to service_role;
grant execute on function logistics.nack_delivery(bigint, text) to service_role;
grant execute on function logistics.requeue_dead_letter(bigint, text) to service_role;

-- Pour retirer SEULEMENT cette étape : supprimer les fonctions public.lg_* de la section 9, puis
--   drop table if exists logistics.proof_of_delivery, logistics.task_status_history, logistics.assignment, logistics.pickup_parcel, logistics.task,
--        logistics.task_transition, logistics.task_status, logistics.driver_availability, logistics.driver_zone, logistics.driver, logistics.delivery_zone, logistics.vehicle cascade;
--   rétablir logistics.guard_parcel_status() et logistics.actor_can() de 003-machine-d-etats.sql, retirer les trois transitions de colis ajoutées ici
--   (delete from logistics.parcel_transition where to_status = 'AT_DESTINATION_HUB' and from_status in ('OUT_FOR_DELIVERY', 'DELIVERY_ASSIGNED')),
--   et remettre required_right = 'colis.statut' sur DELIVERY_ASSIGNED → OUT_FOR_DELIVERY et OUT_FOR_DELIVERY → DELIVERED.
