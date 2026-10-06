-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 4 : l'entrepôt et les scanners
-- -----------------------------------------------------------------------------
-- Phase 7. À coller dans Supabase > SQL Editor APRÈS 001, 002 et 003, après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site ».
--
-- Ce que fait ce script : zones d'entrepôt, réception, vérification (poids, dimensions, état,
-- photos), rangement, mouvements, incidents, et le SCAN : un seul point d'entrée, indifférent au
-- type de lecteur (caméra, QR, code-barres, scanner USB, bureau). Chaque scan est enregistré —
-- accepté OU refusé — avec le colis, l'événement, l'utilisateur, l'entrepôt, l'emplacement,
-- l'heure, l'appareil et les métadonnées.
--
-- Ce qu'il ne fait pas : il ne touche à aucune ancienne table ni à aucune des étapes 001-003 (il
-- les prolonge), et n'est appelé par aucune page ni application tant que vous ne les branchez pas.
--
-- Retour arrière : drop function public.lg_scan_parcel(…), public.lg_inspect_parcel(…),
--   public.lg_report_incident(…), public.lg_add_parcel_photo(…) ; puis les objets listés au bas du fichier.
-- Rejouable sans risque.
-- =============================================================================

-- 1. Le catalogue d'événements s'élargit ---------------------------------------------------------------
alter table logistics.event_type drop constraint if exists event_type_aggregate_type_check;
alter table logistics.event_type add constraint event_type_aggregate_type_check
  check (aggregate_type in ('parcel', 'shipment', 'consolidation', 'warehouse', 'delivery', 'pickup', 'trip', 'incident',
                            'customs', 'invoice', 'payment', 'scan'));
insert into logistics.event_type (code, aggregate_type, description) values
  ('ParcelInspected', 'parcel',   'Colis pesé, mesuré et inspecté'),
  ('ParcelMoved',     'parcel',   'Colis déplacé d''un emplacement à un autre'),
  ('ScanRejected',    'scan',     'Scan refusé (colis inconnu, doublon, mauvais entrepôt…)')
on conflict (code) do nothing;


-- 2. Zones, état et mesures du colis ----------------------------------------------------------------------
create table if not exists logistics.warehouse_zone (
  id           uuid primary key default gen_random_uuid(),
  warehouse_id uuid not null references logistics.warehouse (id) on delete restrict,
  code         text not null,
  name         text not null default '',
  kind         text not null default 'storage' check (kind in ('receiving', 'storage', 'staging', 'dispatch', 'quarantine', 'damaged')),
  active       boolean not null default true,
  created_at   timestamptz not null default now(),
  unique (warehouse_id, code)
);
alter table logistics.warehouse_location add column if not exists zone_id uuid references logistics.warehouse_zone (id) on delete restrict;

alter table logistics.parcel add column if not exists condition text not null default 'UNKNOWN';
alter table logistics.parcel drop constraint if exists parcel_condition_check;
alter table logistics.parcel add constraint parcel_condition_check check (condition in ('UNKNOWN', 'GOOD', 'MINOR_DAMAGE', 'DAMAGED'));
alter table logistics.parcel add column if not exists verified_weight_lb numeric(8, 2) check (verified_weight_lb is null or verified_weight_lb > 0);
alter table logistics.parcel add column if not exists length_in numeric(8, 2) check (length_in is null or length_in > 0);
alter table logistics.parcel add column if not exists width_in  numeric(8, 2) check (width_in  is null or width_in  > 0);
alter table logistics.parcel add column if not exists height_in numeric(8, 2) check (height_in is null or height_in > 0);
alter table logistics.parcel add column if not exists is_prohibited boolean not null default false;
alter table logistics.parcel add column if not exists prohibited_reason text;
alter table logistics.parcel add column if not exists received_at timestamptz;
-- Volume en pieds cubes : sert aux capacités des véhicules (phase 9) et à la tarification volumétrique (phase 10).
do $$
begin
  if not exists (select 1 from information_schema.columns where table_schema = 'logistics' and table_name = 'parcel' and column_name = 'volume_ft3') then
    alter table logistics.parcel add column volume_ft3 numeric(10, 3)
      generated always as (round(length_in * width_in * height_in / 1728.0, 3)) stored;
  end if;
end
$$;


-- 3. Scans, inspections, photos, mouvements, incidents ---------------------------------------------------------
create table if not exists logistics.scan (
  id              uuid primary key default gen_random_uuid(),
  scanned_code    text not null,
  code_kind       text not null check (code_kind in ('barcode', 'qr', 'manual', 'rfid', 'unknown')),
  purpose         text not null check (purpose in ('receive', 'verify', 'store', 'move', 'consolidate', 'dispatch', 'lookup')),
  result          text not null check (result in ('ACCEPTED', 'UNKNOWN_PARCEL', 'INVALID_CODE', 'DUPLICATE', 'WRONG_WAREHOUSE',
                                                  'ALREADY_DISPATCHED', 'DAMAGED', 'PROHIBITED', 'NO_CUSTOMER', 'WRONG_STATE')),
  parcel_id       uuid references logistics.parcel (id) on delete restrict,
  actor_user_id   uuid not null references logistics.app_user (id) on delete restrict,
  warehouse_id    uuid not null references logistics.warehouse (id) on delete restrict,
  location_id     uuid references logistics.warehouse_location (id) on delete restrict,
  device_id       uuid references logistics.device (id) on delete restrict,
  tracking_event_id bigint references logistics.tracking_event (id) on delete restrict,
  scanned_at      timestamptz not null default now(),
  correlation_id  uuid not null,
  idempotency_key text unique,
  metadata        jsonb not null default '{}'::jsonb
);
create index if not exists scan_parcel_idx on logistics.scan (parcel_id, scanned_at);
create index if not exists scan_warehouse_idx on logistics.scan (warehouse_id, scanned_at);
comment on table logistics.scan is 'Chaque lecture, acceptée ou refusée. Ajout seul : c''est la trace de ce qui s''est passé (et de ce qu''on a essayé) dans l''entrepôt.';
-- Ajout seul, avec UNE seule exception : le lien vers l'événement de suivi, posé juste après la transition
-- (l'événement n'existe pas encore quand le scan est écrit). De vide à une valeur, une fois ; rien d'autre ne change.
create or replace function logistics.guard_scan()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'UPDATE'
     and old.tracking_event_id is null and new.tracking_event_id is not null
     and (to_jsonb(new) - 'tracking_event_id') = (to_jsonb(old) - 'tracking_event_id') then
    return new;
  end if;
  raise exception 'Table en ajout seul : % interdit sur scan.', tg_op using errcode = 'LG004';
end;
$$;
drop trigger if exists scan_append_only on logistics.scan;
create trigger scan_append_only before update or delete on logistics.scan for each row execute function logistics.guard_scan();

create table if not exists logistics.parcel_inspection (
  id              uuid primary key default gen_random_uuid(),
  parcel_id       uuid not null references logistics.parcel (id) on delete restrict,
  scan_id         uuid references logistics.scan (id) on delete restrict,
  inspected_by    uuid not null references logistics.app_user (id) on delete restrict,
  warehouse_id    uuid not null references logistics.warehouse (id) on delete restrict,
  device_id       uuid references logistics.device (id) on delete restrict,
  inspected_at    timestamptz not null default now(),
  weight_lb       numeric(8, 2) not null check (weight_lb > 0),
  length_in       numeric(8, 2) check (length_in > 0),
  width_in        numeric(8, 2) check (width_in > 0),
  height_in       numeric(8, 2) check (height_in > 0),
  condition       text not null check (condition in ('GOOD', 'MINOR_DAMAGE', 'DAMAGED')),
  prohibited      boolean not null default false,
  prohibited_reason text,
  notes           text not null default '',
  correlation_id  uuid not null,
  check (num_nonnulls(length_in, width_in, height_in) in (0, 3))    -- les trois dimensions, ou aucune
);
create index if not exists parcel_inspection_parcel_idx on logistics.parcel_inspection (parcel_id, inspected_at);
drop trigger if exists parcel_inspection_append_only on logistics.parcel_inspection;
create trigger parcel_inspection_append_only before update or delete on logistics.parcel_inspection for each row execute function logistics.forbid_mutation();

create table if not exists logistics.parcel_photo (
  id            uuid primary key default gen_random_uuid(),
  parcel_id     uuid not null references logistics.parcel (id) on delete restrict,
  inspection_id uuid references logistics.parcel_inspection (id) on delete restrict,
  storage_path  text not null unique check (storage_path ~ '^parcels/[0-9a-f-]{36}/[A-Za-z0-9._-]{1,120}$'),
  kind          text not null default 'RECEIVING' check (kind in ('RECEIVING', 'DAMAGE', 'LABEL', 'CONTENT', 'OTHER')),
  taken_by      uuid not null references logistics.app_user (id) on delete restrict,
  device_id     uuid references logistics.device (id) on delete restrict,
  taken_at      timestamptz not null default now()
);
comment on table logistics.parcel_photo is 'Le chemin d''une photo dans un compartiment PRIVÉ de Supabase Storage (jamais l''image elle-même, jamais une adresse publique).';
create index if not exists parcel_photo_parcel_idx on logistics.parcel_photo (parcel_id);

create table if not exists logistics.parcel_movement (
  id                bigint generated always as identity primary key,
  parcel_id         uuid not null references logistics.parcel (id) on delete restrict,
  from_warehouse_id uuid references logistics.warehouse (id) on delete restrict,
  from_location_id  uuid references logistics.warehouse_location (id) on delete restrict,
  to_warehouse_id   uuid not null references logistics.warehouse (id) on delete restrict,
  to_location_id    uuid not null references logistics.warehouse_location (id) on delete restrict,
  moved_by          uuid not null references logistics.app_user (id) on delete restrict,
  moved_at          timestamptz not null default now(),
  reason            text not null default 'storage' check (reason in ('storage', 'move', 'quarantine', 'correction')),
  scan_id           uuid references logistics.scan (id) on delete restrict,
  correlation_id    uuid not null
);
create index if not exists parcel_movement_parcel_idx on logistics.parcel_movement (parcel_id, moved_at);
drop trigger if exists parcel_movement_append_only on logistics.parcel_movement;
create trigger parcel_movement_append_only before update or delete on logistics.parcel_movement for each row execute function logistics.forbid_mutation();

create table if not exists logistics.incident (
  id             uuid primary key default gen_random_uuid(),
  parcel_id      uuid references logistics.parcel (id) on delete restrict,
  scan_id        uuid references logistics.scan (id) on delete restrict,
  warehouse_id   uuid references logistics.warehouse (id) on delete restrict,
  type           text not null check (type in ('DAMAGED', 'PROHIBITED_ITEM', 'UNKNOWN_PARCEL', 'FORGED_LABEL', 'WRONG_WAREHOUSE', 'NO_CUSTOMER',
                                               'CUSTOMER_ABSENT', 'WRONG_ADDRESS', 'REFUSED', 'VEHICLE_PROBLEM', 'PAYMENT_PROBLEM', 'OTHER')),
  severity       text not null default 'MEDIUM' check (severity in ('LOW', 'MEDIUM', 'HIGH')),
  status         text not null default 'OPEN' check (status in ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CANCELLED')),
  description    text not null default '',
  reported_by    uuid references logistics.app_user (id) on delete restrict,
  correlation_id uuid not null,
  created_at     timestamptz not null default now(),
  resolved_at    timestamptz,
  resolved_by    uuid references logistics.app_user (id) on delete restrict,
  resolution     text,
  check ((status in ('RESOLVED', 'CANCELLED')) = (resolved_at is not null))
);
create index if not exists incident_open_idx on logistics.incident (status, type);
comment on table logistics.incident is 'Un incident (entrepôt, puis dernier kilomètre en phase 9). Jamais supprimé : résolu avec sa note.';
create index if not exists incident_parcel_idx on logistics.incident (parcel_id);


-- 4. La décision d'un scan : une fonction PURE, donc testable cas par cas -----------------------------------------
-- Elle ne lit ni n'écrit rien : elle reçoit l'état du colis et ce que l'opérateur veut faire, et rend le résultat.
-- Ordre des vérifications (le premier qui s'applique gagne) :
--   déjà parti > perdu/annulé > interdit > en attente > endommagé > mauvais entrepôt > état incompatible > doublon > sans client.
create or replace function logistics.assess_scan(
  p_status text, p_is_prohibited boolean, p_has_customer boolean,
  p_parcel_warehouse uuid, p_parcel_location uuid,
  p_purpose text, p_warehouse uuid, p_location uuid)
returns text
language plpgsql immutable set search_path = ''
as $$
begin
  if p_purpose = 'lookup' then return 'ACCEPTED'; end if;
  if p_status in ('IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED',
                  'OUT_FOR_DELIVERY', 'DELIVERED', 'RETURNED') then
    return 'ALREADY_DISPATCHED';
  end if;
  if p_status in ('CANCELLED', 'LOST') then return 'WRONG_STATE'; end if;
  if p_is_prohibited then return 'PROHIBITED'; end if;
  if p_status = 'ON_HOLD' then return 'WRONG_STATE'; end if;
  if p_status = 'DAMAGED' and p_purpose in ('receive', 'verify', 'store', 'consolidate', 'dispatch') then return 'DAMAGED'; end if;
  if p_parcel_warehouse is not null and p_parcel_warehouse <> p_warehouse then return 'WRONG_WAREHOUSE'; end if;

  if p_purpose = 'receive' then
    if p_status = 'CREATED' then return 'ACCEPTED'; end if;
    if p_status in ('RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT') then return 'DUPLICATE'; end if;
  elsif p_purpose = 'verify' then
    if p_status = 'RECEIVED' then return 'ACCEPTED'; end if;
    if p_status in ('VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT') then return 'DUPLICATE'; end if;
  elsif p_purpose = 'store' then
    if p_status = 'VERIFIED' then return 'ACCEPTED'; end if;
    if p_status = 'STORED' and p_parcel_location is not distinct from p_location then return 'DUPLICATE'; end if;
  elsif p_purpose = 'move' then
    if p_status in ('RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'DAMAGED')
       and p_location is not null then
      if p_parcel_location is not distinct from p_location then return 'DUPLICATE'; end if;
      return 'ACCEPTED';
    end if;
  elsif p_purpose = 'consolidate' then
    if p_status = 'STORED' then
      if not p_has_customer then return 'NO_CUSTOMER'; end if;
      return 'ACCEPTED';
    end if;
    if p_status in ('CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT') then return 'DUPLICATE'; end if;
  elsif p_purpose = 'dispatch' then
    if p_status = 'READY_FOR_EXPORT' then return 'ACCEPTED'; end if;
  end if;
  return 'WRONG_STATE';
end;
$$;
comment on function logistics.assess_scan is 'La décision d''un scan, sans lecture ni écriture : rend le résultat selon l''état du colis et l''intention.';


-- 5. Lire un code, quel que soit le lecteur ------------------------------------------------------------------------
-- Un code-barres donne « SES-10001-HT » ; un QR donne l'adresse de suivi « …suivi.html?colis=SES-10001-HT&j=… » ;
-- un opérateur peut taper en minuscules avec des espaces. Le métier reçoit un texte, jamais « la caméra ».
create or replace function logistics.parse_code(p_code text)
returns jsonb language plpgsql immutable set search_path = '' as $$
declare
  v_brut   text := btrim(coalesce(p_code, ''));
  v_numero text;
  v_jeton  text;
begin
  if v_brut = '' or length(v_brut) > 500 then
    raise exception 'Code illisible.' using errcode = 'LG005';
  end if;
  if v_brut ~* '[?&]colis=' then
    v_numero := substring(v_brut from '(?i)[?&]colis=([^&#[:space:]]+)');
    v_jeton  := substring(v_brut from '(?i)[?&]j=([^&#[:space:]]+)');
  else
    v_numero := v_brut;
  end if;
  v_numero := upper(regexp_replace(coalesce(v_numero, ''), '[[:space:][:cntrl:]]', '', 'g'));
  if v_numero !~ '^[A-Z0-9-]{4,60}$' then
    raise exception 'Code illisible.' using errcode = 'LG005';
  end if;
  return jsonb_build_object('number', v_numero, 'token', nullif(btrim(coalesce(v_jeton, '')), ''));
end;
$$;


-- 6. Incidents ----------------------------------------------------------------------------------------------------
create or replace function logistics.report_incident(
  p_type text, p_parcel_id uuid, p_actor uuid, p_description text default '', p_severity text default 'MEDIUM',
  p_warehouse_id uuid default null, p_scan_id uuid default null, p_correlation_id uuid default null)
returns uuid
language plpgsql volatile security definer set search_path = ''
as $$
declare
  v_id   uuid;
  v_corr uuid := coalesce(p_correlation_id, gen_random_uuid());
  v_label text;
begin
  if p_actor is not null and not logistics.actor_can(p_actor, 'colis.statut') then
    raise exception 'Droit insuffisant pour déclarer un incident.' using errcode = 'LG003';
  end if;
  v_label := coalesce((select email from auth.users where id = p_actor), 'system');
  insert into logistics.incident (parcel_id, scan_id, warehouse_id, type, severity, description, reported_by, correlation_id)
  values (p_parcel_id, p_scan_id, p_warehouse_id, p_type, p_severity, left(coalesce(p_description, ''), 2000), p_actor, v_corr)
  returning id into v_id;
  insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_user_id, actor_label, payload)
  values ('IncidentCreated', 'incident', v_id::text, v_corr, p_actor, v_label,
          jsonb_build_object('incident_id', v_id, 'type', p_type, 'severity', p_severity, 'parcel_id', p_parcel_id, 'scan_id', p_scan_id));
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, v_label, 'incident.create', 'incident', v_id::text,
          jsonb_build_object('type', p_type, 'severity', p_severity, 'parcel_id', p_parcel_id), v_corr);
  return v_id;
end;
$$;

create or replace function logistics.resolve_incident(p_incident_id uuid, p_actor uuid, p_resolution text, p_cancel boolean default false)
returns void language plpgsql volatile security definer set search_path = '' as $$
begin
  if not logistics.actor_can(p_actor, 'direction') then
    raise exception 'La résolution d''un incident est réservée à la direction.' using errcode = 'LG003';
  end if;
  if btrim(coalesce(p_resolution, '')) = '' then raise exception 'Une note de résolution est obligatoire.' using errcode = 'LG005'; end if;
  update logistics.incident
     set status = case when p_cancel then 'CANCELLED' else 'RESOLVED' end, resolved_at = now(), resolved_by = p_actor, resolution = left(p_resolution, 2000)
   where id = p_incident_id and status in ('OPEN', 'IN_PROGRESS');
  if not found then raise exception 'Incident introuvable ou déjà clos.' using errcode = 'LG002'; end if;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'incident.resolve', 'incident', p_incident_id::text,
          jsonb_build_object('resolution', p_resolution, 'cancelled', p_cancel));
end;
$$;


-- 7. LE scan -------------------------------------------------------------------------------------------------------
create or replace function logistics.scan_parcel(
  p_code            text,
  p_purpose         text,
  p_actor           uuid,
  p_warehouse_id    uuid,
  p_location_id     uuid  default null,
  p_device_id       uuid  default null,
  p_code_kind       text  default 'unknown',
  p_idempotency_key text  default null,
  p_metadata        jsonb default '{}'::jsonb,
  p_correlation_id  uuid  default null)
returns jsonb
language plpgsql volatile security definer set search_path = ''
as $$
declare
  v_corr     uuid := coalesce(p_correlation_id, gen_random_uuid());
  v_hash     text;
  v_prior    jsonb;
  v_prior_h  text;
  v_wh       logistics.warehouse;
  v_branch   uuid;
  v_user_br  uuid;
  v_loc      logistics.warehouse_location;
  v_dev_kind text;
  v_code     jsonb;
  v_parcel   logistics.parcel;
  v_result   text;
  v_scan     uuid := gen_random_uuid();
  v_te       bigint;
  v_trans    jsonb;
  v_warnings text[] := '{}';
  v_out      jsonb;
  v_incident uuid;
  v_label    text;
begin
  -- Ce qui relève d'une demande MAL FORMÉE ou NON AUTORISÉE lève une erreur ; tout le reste est un RÉSULTAT.
  if p_purpose not in ('receive', 'verify', 'store', 'move', 'consolidate', 'dispatch', 'lookup') then
    raise exception 'Intention de scan inconnue : %.', p_purpose using errcode = 'LG005';
  end if;
  if p_code_kind not in ('barcode', 'qr', 'manual', 'rfid', 'unknown') then
    raise exception 'Type de lecteur inconnu : %.', p_code_kind using errcode = 'LG005';
  end if;
  if p_actor is null or not logistics.actor_can(p_actor, 'colis.statut') then
    raise exception 'Droit insuffisant pour scanner (exige : colis.statut).' using errcode = 'LG003';
  end if;
  select * into v_wh from logistics.warehouse where id = p_warehouse_id and active;
  if not found then raise exception 'Entrepôt inconnu ou inactif.' using errcode = 'LG005'; end if;
  select branch_id into v_user_br from logistics.app_user where id = p_actor;
  if v_user_br is not null and v_user_br <> v_wh.branch_id then
    raise exception 'Cet entrepôt n''est pas celui de votre succursale.' using errcode = 'LG003';
  end if;
  if p_location_id is not null then
    select * into v_loc from logistics.warehouse_location where id = p_location_id and active;
    if not found or v_loc.warehouse_id <> p_warehouse_id then
      raise exception 'Emplacement inconnu, inactif, ou d''un autre entrepôt.' using errcode = 'LG005';
    end if;
  end if;
  if p_purpose in ('store', 'move') and p_location_id is null then
    raise exception 'Un emplacement est obligatoire pour « % ».', p_purpose using errcode = 'LG005';
  end if;
  if p_device_id is not null then
    select kind into v_dev_kind from logistics.device where id = p_device_id and active;
    if v_dev_kind is null or v_dev_kind not in ('phone_camera', 'usb_scanner', 'desktop_scanner', 'handheld_scanner') then
      raise exception 'Appareil inconnu, inactif, ou qui n''est pas un lecteur.' using errcode = 'LG005';
    end if;
  end if;
  v_code := logistics.parse_code(p_code);
  v_label := coalesce((select email from auth.users where id = p_actor), p_actor::text);

  -- Idempotence : un scan rejoué (réseau coupé, double appui) ne se compte pas deux fois.
  v_hash := md5(concat_ws('|', p_code, p_purpose, p_actor, p_warehouse_id, p_location_id, p_device_id, p_code_kind, p_metadata::text));
  if p_idempotency_key is not null then
    insert into logistics.command_log (idempotency_key, command, request_hash, entity_type, entity_id)
    values (p_idempotency_key, 'scan_parcel', v_hash, 'scan', v_scan::text) on conflict (idempotency_key) do nothing;
    if not found then
      select request_hash, result into v_prior_h, v_prior from logistics.command_log where idempotency_key = p_idempotency_key;
      if v_prior_h <> v_hash then raise exception 'Clé d''idempotence déjà utilisée pour une AUTRE demande.' using errcode = 'LG006'; end if;
      return coalesce(v_prior, '{}'::jsonb) || jsonb_build_object('replayed', true);
    end if;
  end if;

  -- Quel colis ?
  select * into v_parcel from logistics.parcel where tracking_number = v_code ->> 'number';
  if not found then
    v_result := 'UNKNOWN_PARCEL';
  elsif v_code ->> 'token' is not null and v_code ->> 'token' <> v_parcel.public_token then
    v_result := 'INVALID_CODE';           -- numéro connu, jeton faux : une étiquette falsifiée
  else
    v_result := logistics.assess_scan(v_parcel.status, v_parcel.is_prohibited, v_parcel.customer_id is not null,
                                      v_parcel.current_warehouse_id, v_parcel.current_location_id,
                                      p_purpose, p_warehouse_id, p_location_id);
  end if;

  -- Verrouiller le colis AVANT d'agir (deux scans simultanés du même colis ne se croisent pas) et réévaluer.
  if v_result = 'ACCEPTED' and p_purpose <> 'lookup' then
    select * into v_parcel from logistics.parcel where id = v_parcel.id for update;
    v_result := logistics.assess_scan(v_parcel.status, v_parcel.is_prohibited, v_parcel.customer_id is not null,
                                      v_parcel.current_warehouse_id, v_parcel.current_location_id,
                                      p_purpose, p_warehouse_id, p_location_id);
  end if;

  -- Toujours enregistrer le scan (le refusé aussi : c'est une preuve) ---------------------------------------
  insert into logistics.scan (id, scanned_code, code_kind, purpose, result, parcel_id, actor_user_id, warehouse_id, location_id,
                              device_id, correlation_id, idempotency_key, metadata)
  values (v_scan, left(p_code, 500), p_code_kind, p_purpose, v_result, v_parcel.id, p_actor, p_warehouse_id, p_location_id,
          p_device_id, v_corr, p_idempotency_key, coalesce(p_metadata, '{}'::jsonb));

  -- Ce que le résultat entraîne -----------------------------------------------------------------------------
  if v_result = 'ACCEPTED' then
    if p_purpose = 'receive' then
      v_trans := logistics.transition_parcel(v_parcel.id, 'RECEIVED', p_actor, null, v_corr, p_warehouse_id, p_location_id, '', p_device_id,
                                             null, jsonb_build_object('scan_id', v_scan), 'scan');
      update logistics.parcel set received_at = coalesce(received_at, now()) where id = v_parcel.id;
      if v_parcel.customer_id is null then
        v_warnings := array_append(v_warnings, 'NO_CUSTOMER');
        v_incident := logistics.report_incident('NO_CUSTOMER', v_parcel.id, p_actor,
                        'Colis reçu sans client : à rattacher avant toute consolidation.', 'MEDIUM', p_warehouse_id, v_scan, v_corr);
      end if;
    elsif p_purpose = 'store' then
      v_trans := logistics.transition_parcel(v_parcel.id, 'STORED', p_actor, null, v_corr, p_warehouse_id, p_location_id, '', p_device_id,
                                             null, jsonb_build_object('scan_id', v_scan), 'scan');
      insert into logistics.parcel_movement (parcel_id, from_warehouse_id, from_location_id, to_warehouse_id, to_location_id, moved_by, reason, scan_id, correlation_id)
      values (v_parcel.id, v_parcel.current_warehouse_id, v_parcel.current_location_id, p_warehouse_id, p_location_id, p_actor, 'storage', v_scan, v_corr);
    elsif p_purpose = 'consolidate' then
      v_trans := logistics.transition_parcel(v_parcel.id, 'CONSOLIDATION_PENDING', p_actor, null, v_corr, p_warehouse_id, p_location_id, '', p_device_id,
                                             null, jsonb_build_object('scan_id', v_scan), 'scan');
    elsif p_purpose = 'move' then
      insert into logistics.parcel_movement (parcel_id, from_warehouse_id, from_location_id, to_warehouse_id, to_location_id, moved_by, reason, scan_id, correlation_id)
      values (v_parcel.id, v_parcel.current_warehouse_id, v_parcel.current_location_id, p_warehouse_id, p_location_id, p_actor,
              case when v_loc.kind in ('quarantine', 'damaged') then 'quarantine' else 'move' end, v_scan, v_corr);
      update logistics.parcel set current_warehouse_id = p_warehouse_id, current_location_id = p_location_id, current_location = v_loc.code where id = v_parcel.id;
      insert into logistics.tracking_event (parcel_id, event_type, from_status, to_status, occurred_at, actor_user_id, actor_label, warehouse_id, location_id,
                                            location_text, device_id, source, metadata, correlation_id)
      values (v_parcel.id, 'ParcelMoved', v_parcel.status, v_parcel.status, now(), p_actor, v_label, p_warehouse_id, p_location_id, v_loc.code, p_device_id,
              'scan', jsonb_build_object('scan_id', v_scan, 'from_location_id', v_parcel.current_location_id), v_corr)
      returning id into v_te;
      insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_user_id, actor_label, payload)
      values ('ParcelMoved', 'parcel', v_parcel.id::text, v_corr, p_actor, v_label,
              jsonb_build_object('parcel_id', v_parcel.id, 'tracking_number', v_parcel.tracking_number, 'to_location', v_loc.code, 'tracking_event_id', v_te));
    end if;
    -- verify, dispatch, lookup : le scan IDENTIFIE ; l'acte suit (inspection, expédition).
    if v_trans is not null then v_te := (v_trans ->> 'tracking_event_id')::bigint; end if;
    if v_te is not null then update logistics.scan set tracking_event_id = v_te where id = v_scan; end if;
  else
    -- Un refus laisse une trace d'incident quand il signale un vrai problème, une seule fois par code et par entrepôt.
    if v_result in ('UNKNOWN_PARCEL', 'INVALID_CODE', 'PROHIBITED')
       and not exists (select 1 from logistics.incident i join logistics.scan s on s.id = i.scan_id
                       where i.status in ('OPEN', 'IN_PROGRESS') and s.scanned_code = left(p_code, 500) and s.warehouse_id = p_warehouse_id
                         and i.type = case v_result when 'UNKNOWN_PARCEL' then 'UNKNOWN_PARCEL' when 'INVALID_CODE' then 'FORGED_LABEL' else 'PROHIBITED_ITEM' end) then
      v_incident := logistics.report_incident(case v_result when 'UNKNOWN_PARCEL' then 'UNKNOWN_PARCEL' when 'INVALID_CODE' then 'FORGED_LABEL' else 'PROHIBITED_ITEM' end,
                      v_parcel.id, p_actor,
                      case v_result when 'UNKNOWN_PARCEL' then 'Code lu inconnu : ' || left(p_code, 80)
                                    when 'INVALID_CODE' then 'Numéro connu mais jeton faux : étiquette douteuse.'
                                    else 'Colis marqué interdit présenté au scan.' end,
                      case when v_result = 'UNKNOWN_PARCEL' then 'MEDIUM' else 'HIGH' end, p_warehouse_id, v_scan, v_corr);
    end if;
    insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_user_id, actor_label, payload)
    values ('ScanRejected', 'scan', v_scan::text, v_corr, p_actor, v_label,
            jsonb_build_object('scan_id', v_scan, 'result', v_result, 'purpose', p_purpose, 'warehouse_id', p_warehouse_id, 'parcel_id', v_parcel.id));
  end if;

  select * into v_parcel from logistics.parcel where id = v_parcel.id;
  v_out := jsonb_build_object('scan_id', v_scan, 'result', v_result, 'accepted', v_result = 'ACCEPTED', 'purpose', p_purpose,
                              'parcel_id', v_parcel.id, 'tracking_number', coalesce(v_parcel.tracking_number, v_code ->> 'number'),
                              'status', v_parcel.status, 'warnings', to_jsonb(v_warnings), 'incident_id', v_incident,
                              'correlation_id', v_corr, 'replayed', false);
  if p_idempotency_key is not null then
    update logistics.command_log set result = v_out where idempotency_key = p_idempotency_key;
  end if;
  return v_out;
end;
$$;
comment on function logistics.scan_parcel is 'Le seul point d''entrée d''un scan. Ne dépend pas du lecteur : il reçoit un texte, une intention, un entrepôt. Refusé ou accepté, le scan est tracé.';


-- 8. L'inspection : peser, mesurer, constater, photographier ------------------------------------------------------
create or replace function logistics.inspect_parcel(
  p_code text, p_actor uuid, p_warehouse_id uuid,
  p_weight_lb numeric, p_length_in numeric default null, p_width_in numeric default null, p_height_in numeric default null,
  p_condition text default 'GOOD', p_prohibited boolean default false, p_prohibited_reason text default null,
  p_notes text default '', p_photos jsonb default '[]'::jsonb, p_device_id uuid default null,
  p_code_kind text default 'unknown', p_idempotency_key text default null, p_correlation_id uuid default null)
returns jsonb
language plpgsql volatile security definer set search_path = ''
as $$
declare
  v_corr    uuid := coalesce(p_correlation_id, gen_random_uuid());
  v_scan    jsonb;
  v_parcel  logistics.parcel;
  v_insp    uuid := gen_random_uuid();
  v_to      text;
  v_reason  text;
  v_trans   jsonb;
  v_hash    text;
  v_prior   jsonb; v_prior_h text;
  v_photo   jsonb;
  v_warn    text[] := '{}';
  v_incident uuid;
  v_label   text;
  v_out     jsonb;
begin
  if p_condition not in ('GOOD', 'MINOR_DAMAGE', 'DAMAGED') then
    raise exception 'État inconnu : %.', p_condition using errcode = 'LG005';
  end if;
  if p_weight_lb is null or p_weight_lb <= 0 or p_weight_lb > 2000 then
    raise exception 'Le poids est obligatoire (entre 0 et 2000 lb).' using errcode = 'LG005';
  end if;
  if num_nonnulls(p_length_in, p_width_in, p_height_in) not in (0, 3) or coalesce(least(p_length_in, p_width_in, p_height_in), 1) <= 0 then
    raise exception 'Les trois dimensions, positives, ou aucune.' using errcode = 'LG005';
  end if;
  if p_prohibited and btrim(coalesce(p_prohibited_reason, '')) = '' then
    raise exception 'Un motif est obligatoire pour un objet interdit.' using errcode = 'LG005';
  end if;
  if jsonb_typeof(coalesce(p_photos, '[]'::jsonb)) <> 'array' then raise exception 'Photos : un tableau attendu.' using errcode = 'LG005'; end if;

  v_hash := md5(concat_ws('|', p_code, p_actor, p_warehouse_id, p_weight_lb, p_length_in, p_width_in, p_height_in, p_condition, p_prohibited,
                          p_prohibited_reason, p_notes, p_photos::text, p_device_id));
  if p_idempotency_key is not null then
    insert into logistics.command_log (idempotency_key, command, request_hash, entity_type, entity_id)
    values (p_idempotency_key, 'inspect_parcel', v_hash, 'parcel', p_code) on conflict (idempotency_key) do nothing;
    if not found then
      select request_hash, result into v_prior_h, v_prior from logistics.command_log where idempotency_key = p_idempotency_key;
      if v_prior_h <> v_hash then raise exception 'Clé d''idempotence déjà utilisée pour une AUTRE demande.' using errcode = 'LG006'; end if;
      return coalesce(v_prior, '{}'::jsonb) || jsonb_build_object('replayed', true);
    end if;
  end if;

  -- 1. l'identification (même règles, même trace que tout scan)
  v_scan := logistics.scan_parcel(p_code, 'verify', p_actor, p_warehouse_id, null, p_device_id, p_code_kind, null,
                                  jsonb_build_object('inspection', v_insp), v_corr);
  if v_scan ->> 'result' <> 'ACCEPTED' then
    v_out := v_scan || jsonb_build_object('inspected', false);
    if p_idempotency_key is not null then update logistics.command_log set result = v_out where idempotency_key = p_idempotency_key; end if;
    return v_out;
  end if;
  select * into v_parcel from logistics.parcel where id = (v_scan ->> 'parcel_id')::uuid for update;
  v_label := coalesce((select email from auth.users where id = p_actor), p_actor::text);

  -- 2. le constat
  insert into logistics.parcel_inspection (id, parcel_id, scan_id, inspected_by, warehouse_id, device_id, weight_lb, length_in, width_in, height_in,
                                           condition, prohibited, prohibited_reason, notes, correlation_id)
  values (v_insp, v_parcel.id, (v_scan ->> 'scan_id')::uuid, p_actor, p_warehouse_id, p_device_id, p_weight_lb, p_length_in, p_width_in, p_height_in,
          p_condition, p_prohibited, p_prohibited_reason, left(coalesce(p_notes, ''), 2000), v_corr);
  for v_photo in select * from jsonb_array_elements(coalesce(p_photos, '[]'::jsonb)) loop
    insert into logistics.parcel_photo (parcel_id, inspection_id, storage_path, kind, taken_by, device_id)
    values (v_parcel.id, v_insp, v_photo ->> 'path', coalesce(v_photo ->> 'kind', 'RECEIVING'), p_actor, p_device_id);
  end loop;
  update logistics.parcel
     set verified_weight_lb = p_weight_lb, length_in = p_length_in, width_in = p_width_in, height_in = p_height_in,
         condition = p_condition, is_prohibited = p_prohibited or is_prohibited,
         prohibited_reason = case when p_prohibited then p_prohibited_reason else prohibited_reason end
   where id = v_parcel.id;
  if v_parcel.weight_lb is not null and v_parcel.weight_lb > 0 and abs(p_weight_lb - v_parcel.weight_lb) / v_parcel.weight_lb > 0.10 then
    v_warn := array_append(v_warn, 'WEIGHT_DIFFERS');       -- plus de 10 % d'écart avec le poids déclaré : à la tarification d'en tenir compte
  end if;

  -- 3. la conséquence : vérifié, endommagé, ou en attente
  if p_prohibited then
    v_to := 'ON_HOLD'; v_reason := 'Objet interdit : ' || p_prohibited_reason;
    v_incident := logistics.report_incident('PROHIBITED_ITEM', v_parcel.id, p_actor, v_reason, 'HIGH', p_warehouse_id, (v_scan ->> 'scan_id')::uuid, v_corr);
  elsif p_condition = 'DAMAGED' then
    v_to := 'DAMAGED'; v_reason := 'Colis endommagé à la réception' || case when coalesce(p_notes, '') <> '' then ' : ' || p_notes else '' end;
    v_incident := logistics.report_incident('DAMAGED', v_parcel.id, p_actor, v_reason, 'HIGH', p_warehouse_id, (v_scan ->> 'scan_id')::uuid, v_corr);
  else
    v_to := 'VERIFIED';
    if p_condition = 'MINOR_DAMAGE' then
      v_warn := array_append(v_warn, 'MINOR_DAMAGE');
      v_incident := logistics.report_incident('DAMAGED', v_parcel.id, p_actor, 'Dommage mineur constaté : ' || coalesce(p_notes, ''), 'LOW', p_warehouse_id, (v_scan ->> 'scan_id')::uuid, v_corr);
    end if;
  end if;
  v_trans := logistics.transition_parcel(v_parcel.id, v_to, p_actor, null, v_corr, p_warehouse_id, null, '', p_device_id, v_reason,
                                         jsonb_build_object('inspection_id', v_insp, 'scan_id', v_scan ->> 'scan_id'), 'scan');
  insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_user_id, actor_label, payload)
  values ('ParcelInspected', 'parcel', v_parcel.id::text, v_corr, p_actor, v_label,
          jsonb_build_object('parcel_id', v_parcel.id, 'inspection_id', v_insp, 'weight_lb', p_weight_lb, 'condition', p_condition, 'prohibited', p_prohibited, 'result_status', v_to));

  v_out := v_scan || jsonb_build_object('inspected', true, 'inspection_id', v_insp, 'status', v_to, 'warnings', to_jsonb(v_warn), 'incident_id', v_incident);
  if p_idempotency_key is not null then update logistics.command_log set result = v_out where idempotency_key = p_idempotency_key; end if;
  return v_out;
end;
$$;

-- Une photo ajoutée après coup (le chemin seulement : le fichier vit dans un compartiment privé).
create or replace function logistics.add_parcel_photo(p_parcel_id uuid, p_actor uuid, p_storage_path text, p_kind text default 'OTHER', p_device_id uuid default null)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid;
begin
  if p_actor is null or not logistics.actor_can(p_actor, 'colis.statut') then
    raise exception 'Droit insuffisant (colis.statut).' using errcode = 'LG003';
  end if;
  if not exists (select 1 from logistics.parcel where id = p_parcel_id) then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  if p_storage_path !~ ('^parcels/' || p_parcel_id::text || '/[A-Za-z0-9._-]{1,120}$') then
    raise exception 'Chemin de photo invalide : parcels/<colis>/<fichier>.' using errcode = 'LG005';
  end if;
  insert into logistics.parcel_photo (parcel_id, storage_path, kind, taken_by, device_id)
  values (p_parcel_id, p_storage_path, p_kind, p_actor, p_device_id) returning id into v_id;
  return v_id;
end;
$$;


-- 9. La façade : l'acteur est TOUJOURS le compte connecté -------------------------------------------------------------
create or replace function public.lg_scan_parcel(
  p_code text, p_purpose text, p_warehouse_id uuid, p_location_id uuid default null, p_device_id uuid default null,
  p_code_kind text default 'unknown', p_idempotency_key text default null, p_metadata jsonb default '{}'::jsonb)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  perform logistics.require_staff(auth.uid());
  return logistics.scan_parcel(p_code, p_purpose, auth.uid(), p_warehouse_id, p_location_id, p_device_id, p_code_kind, p_idempotency_key, p_metadata, null);
end;
$$;

create or replace function public.lg_inspect_parcel(
  p_code text, p_warehouse_id uuid, p_weight_lb numeric, p_length_in numeric default null, p_width_in numeric default null,
  p_height_in numeric default null, p_condition text default 'GOOD', p_prohibited boolean default false, p_prohibited_reason text default null,
  p_notes text default '', p_photos jsonb default '[]'::jsonb, p_device_id uuid default null, p_code_kind text default 'unknown',
  p_idempotency_key text default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  return logistics.inspect_parcel(p_code, auth.uid(), p_warehouse_id, p_weight_lb, p_length_in, p_width_in, p_height_in, p_condition, p_prohibited,
                                  p_prohibited_reason, p_notes, p_photos, p_device_id, p_code_kind, p_idempotency_key, null);
end;
$$;

create or replace function public.lg_report_incident(
  p_type text, p_parcel_id uuid default null, p_description text default '', p_severity text default 'MEDIUM', p_warehouse_id uuid default null)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  return logistics.report_incident(p_type, p_parcel_id, auth.uid(), p_description, p_severity, p_warehouse_id, null, null);
end;
$$;

create or replace function public.lg_add_parcel_photo(p_parcel_id uuid, p_storage_path text, p_kind text default 'OTHER', p_device_id uuid default null)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  return logistics.add_parcel_photo(p_parcel_id, auth.uid(), p_storage_path, p_kind, p_device_id);
end;
$$;


-- 10. Tout fermé, sauf la façade ------------------------------------------------------------------------------------
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
end
$$;
revoke all on logistics.event_health from public, anon, authenticated;
grant select on logistics.event_health to service_role;
grant execute on function logistics.dispatch_events(int, text) to service_role;
grant execute on function logistics.claim_deliveries(text, int, int) to service_role;
grant execute on function logistics.ack_delivery(bigint) to service_role;
grant execute on function logistics.nack_delivery(bigint, text) to service_role;
grant execute on function logistics.requeue_dead_letter(bigint, text) to service_role;

revoke all on function public.lg_scan_parcel(text, text, uuid, uuid, uuid, text, text, jsonb) from public, anon;
revoke all on function public.lg_inspect_parcel(text, uuid, numeric, numeric, numeric, numeric, text, boolean, text, text, jsonb, uuid, text, text) from public, anon;
revoke all on function public.lg_report_incident(text, uuid, text, text, uuid) from public, anon;
revoke all on function public.lg_add_parcel_photo(uuid, text, text, uuid) from public, anon;
grant execute on function public.lg_scan_parcel(text, text, uuid, uuid, uuid, text, text, jsonb) to authenticated;
grant execute on function public.lg_inspect_parcel(text, uuid, numeric, numeric, numeric, numeric, text, boolean, text, text, jsonb, uuid, text, text) to authenticated;
grant execute on function public.lg_report_incident(text, uuid, text, text, uuid) to authenticated;
grant execute on function public.lg_add_parcel_photo(uuid, text, text, uuid) to authenticated;

-- Pour retirer SEULEMENT cette étape :
--   drop function if exists public.lg_scan_parcel(text, text, uuid, uuid, uuid, text, text, jsonb);
--   drop function if exists public.lg_inspect_parcel(text, uuid, numeric, numeric, numeric, numeric, text, boolean, text, text, jsonb, uuid, text, text);
--   drop function if exists public.lg_report_incident(text, uuid, text, text, uuid);
--   drop function if exists public.lg_add_parcel_photo(uuid, text, text, uuid);
--   drop table if exists logistics.incident, logistics.parcel_movement, logistics.parcel_photo, logistics.parcel_inspection,
--                        logistics.scan, logistics.warehouse_zone cascade;   (les colonnes ajoutées à logistics.parcel restent, sans effet)
