-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 1 : le modèle de domaine
-- -----------------------------------------------------------------------------
-- Phase 5. À coller dans Supabase > SQL Editor, APRÈS sauvegarde vérifiée.
--
-- AVANT DE LANCER : vérifiez en haut de la page que le projet ouvert est bien
-- « speed-express-site », jamais celui de Goship Express.
--
-- Ce que fait ce script :
--   · crée le schéma « logistics » et ses tables (organisation, succursale, entrepôt,
--     client, appareil, colis, événements de suivi, consolidation, expédition,
--     transport, livraison, facture, journal d'audit) ;
--   · crée les listes de statuts (colis, expédition, facture) ;
--   · ferme TOUT à l'API : aucune table n'est accordée à « anon » ni « authenticated »
--     (ADR 0002). Seul le propriétaire de la base, depuis le SQL Editor, y accède.
--
-- Ce qu'il NE fait PAS :
--   · il ne touche à AUCUNE table existante (clients, colis, colis_historique,
--     factures, appareils) : ni lecture, ni écriture, ni modification ;
--   · il ne copie aucune donnée : c'est l'étape 002 (rattrapage), séparée et rejouable ;
--   · il n'est lu par aucune page ni application : le site et l'application
--     continuent de fonctionner exactement comme avant.
--
-- Retour arrière complet : drop schema logistics cascade;   (rien d'autre n'en dépend)
-- Rejouable sans risque : « si absent » partout, aucune suppression.
-- =============================================================================

create schema if not exists logistics;
comment on schema logistics is
  'Noyau logistique de Speed Express (ADR 0001-0006). Fermé à l''API : accès par fonctions de la façade public.lg_* seulement.';

-- Une seule fonction commune : tient « updated_at » à jour.
create or replace function logistics.touch_updated_at()
returns trigger language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- Aucune table du noyau ne se modifie après coup quand elle sert de preuve.
create or replace function logistics.forbid_mutation()
returns trigger language plpgsql set search_path = '' as $$
begin
  raise exception 'Table en ajout seul : % interdit sur %.', tg_op, tg_table_name using errcode = 'LG004';
end;
$$;


-- 1. Listes de statuts ------------------------------------------------------------
-- Les codes sont stables et jamais traduits en base ; l'interface a ses libellés.

create table if not exists logistics.parcel_status (
  code        text primary key,
  sort_order  int  not null,
  is_terminal boolean not null default false,
  is_exception boolean not null default false,
  label_key   text not null
);
comment on table logistics.parcel_status is 'Cycle de vie du COLIS (phase 6 y ajoute les transitions autorisées).';

insert into logistics.parcel_status (code, sort_order, is_terminal, is_exception, label_key) values
  ('CREATED',               10, false, false, 'status-created'),
  ('RECEIVED',              20, false, false, 'status-received'),
  ('VERIFIED',              30, false, false, 'status-verified'),
  ('STORED',                40, false, false, 'status-stored'),
  ('CONSOLIDATION_PENDING', 50, false, false, 'status-consolidation-pending'),
  ('CONSOLIDATED',          60, false, false, 'status-consolidated'),
  ('READY_FOR_EXPORT',      70, false, false, 'status-ready-for-export'),
  ('IN_TRANSIT',            80, false, false, 'status-in-transit'),
  ('ARRIVED',               90, false, false, 'status-arrived'),
  ('CUSTOMS_PROCESSING',   100, false, false, 'status-customs-processing'),
  ('CUSTOMS_CLEARED',      110, false, false, 'status-customs-cleared'),
  ('AT_DESTINATION_HUB',   120, false, false, 'status-at-destination-hub'),
  ('DELIVERY_ASSIGNED',    130, false, false, 'status-delivery-assigned'),
  ('OUT_FOR_DELIVERY',     140, false, false, 'status-out-for-delivery'),
  ('DELIVERED',            150, true,  false, 'status-delivered'),
  ('ON_HOLD',              200, false, true,  'status-on-hold'),
  ('CANCELLED',            210, true,  true,  'status-cancelled'),
  ('DAMAGED',              220, false, true,  'status-damaged'),
  ('LOST',                 230, true,  true,  'status-lost'),
  ('RETURNED',             240, true,  true,  'status-returned')
on conflict (code) do nothing;

create table if not exists logistics.shipment_status (
  code        text primary key,
  sort_order  int  not null,
  is_terminal boolean not null default false,
  label_key   text not null
);
comment on table logistics.shipment_status is 'Cycle de vie de l''EXPÉDITION, séparé de celui du colis (ADR 0006). Transitions : phase 8.';

insert into logistics.shipment_status (code, sort_order, is_terminal, label_key) values
  ('DRAFT',               10, false, 'shipment-draft'),
  ('READY',               20, false, 'shipment-ready'),
  ('DISPATCHED',          30, false, 'shipment-dispatched'),
  ('IN_TRANSIT',          40, false, 'shipment-in-transit'),
  ('ARRIVED',             50, false, 'shipment-arrived'),
  ('CUSTOMS_PROCESSING',  60, false, 'shipment-customs-processing'),
  ('CUSTOMS_CLEARED',     70, false, 'shipment-customs-cleared'),
  ('AT_HUB',              80, false, 'shipment-at-hub'),
  ('CLOSED',              90, true,  'shipment-closed'),
  ('CANCELLED',          100, true,  'shipment-cancelled')
on conflict (code) do nothing;

create table if not exists logistics.invoice_status (
  code        text primary key,
  sort_order  int  not null,
  is_terminal boolean not null default false,
  label_key   text not null
);
comment on table logistics.invoice_status is 'Cycle de vie de la FACTURE. Règles de transition : phase 10.';

insert into logistics.invoice_status (code, sort_order, is_terminal, label_key) values
  ('DRAFT',          10, false, 'invoice-draft'),
  ('ISSUED',         20, false, 'invoice-issued'),
  ('PARTIALLY_PAID', 30, false, 'invoice-partially-paid'),
  ('PAID',           40, false, 'invoice-paid'),
  ('OVERDUE',        50, false, 'invoice-overdue'),
  ('CANCELLED',      60, true,  'invoice-cancelled'),
  ('REFUNDED',       70, true,  'invoice-refunded')
on conflict (code) do nothing;


-- 2. Organisation, succursales, personnel ---------------------------------------

create table if not exists logistics.organization (
  id               uuid primary key default gen_random_uuid(),
  name             text not null unique,
  legal_name       text,
  tax_id           text,
  default_currency text not null default 'USD' check (default_currency in ('USD', 'DOP', 'HTG')),
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
comment on table logistics.organization is 'L''entreprise. Une seule aujourd''hui ; la colonne organization_id partout prépare le multi-entreprise sans l''activer.';

-- L''entreprise elle-même : sans elle, rien ne peut s''y rattacher. Ce n''est pas une donnée inventée.
insert into logistics.organization (name) values ('Speed Express Shipping') on conflict (name) do nothing;

create table if not exists logistics.branch (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references logistics.organization (id) on delete restrict,
  code            text not null,
  name            text not null,
  kind            text not null default 'office' check (kind in ('office', 'hub', 'agency', 'warehouse_site')),
  country         text not null check (country in ('HT', 'DO', 'US')),
  city            text not null default '',
  active          boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (organization_id, code)
);
comment on table logistics.branch is 'Succursale, agence ou hub. Vide : aucune n''a jamais été enregistrée, la migration n''en invente pas.';

-- Le personnel : l'ancien « clients » avec un rôle d'équipe. Même identifiant que le compte Auth.
create table if not exists logistics.app_user (
  id              uuid primary key references auth.users (id) on delete restrict,
  organization_id uuid not null references logistics.organization (id) on delete restrict,
  branch_id       uuid references logistics.branch (id) on delete restrict,
  role            text not null check (role in ('employee', 'manager', 'admin')),
  rights          text[] not null default '{}',
  active          boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
comment on table logistics.app_user is 'Compte du personnel (employé, gérant, administrateur). Les rôles chauffeur et opérateur d''entrepôt s''ajoutent aux phases 7 et 9.';


-- 3. Clients et appareils ------------------------------------------------------------

create table if not exists logistics.customer (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null references logistics.organization (id) on delete restrict,
  code             text unique,
  auth_user_id     uuid unique references auth.users (id) on delete set null,
  full_name        text not null default '',
  country          text not null default '',
  region           text not null default '',
  city             text not null default '',
  address          text not null default '',
  phone            text not null default '',
  email            text not null default '',
  language         text not null default 'fr' check (language in ('fr', 'en', 'es', 'ht')),
  source           text not null default 'native' check (source in ('native', 'legacy_backfill', 'legacy_staff_account')),
  legacy_client_id uuid unique,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);
comment on table logistics.customer is 'Un client est une PERSONNE ou une société qui expédie. Il peut exister sans compte (auth_user_id vide) : client déposé au comptoir.';
comment on column logistics.customer.source is 'legacy_staff_account : compte d''équipe hérité qui porte encore des colis ou des factures (avant la règle « équipe ≠ clientèle »).';

create table if not exists logistics.device (
  id                uuid primary key default gen_random_uuid(),
  kind              text not null check (kind in ('customer_push', 'phone_camera', 'usb_scanner', 'desktop_scanner', 'handheld_scanner')),
  platform          text,
  push_token        text unique,
  owner_customer_id uuid references logistics.customer (id) on delete restrict,
  owner_user_id     uuid references logistics.app_user (id) on delete restrict,
  label             text not null default '',
  active            boolean not null default true,
  last_seen_at      timestamptz,
  source            text not null default 'native' check (source in ('native', 'legacy_backfill')),
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
comment on table logistics.device is 'Un téléphone qui reçoit des notifications, ou (phase 7) un appareil qui scanne.';


-- 4. Entrepôts (squelette ; phase 7 les peuple et les fait vivre) -------------------------

create table if not exists logistics.warehouse (
  id         uuid primary key default gen_random_uuid(),
  branch_id  uuid not null references logistics.branch (id) on delete restrict,
  code       text not null unique,
  name       text not null,
  active     boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists logistics.warehouse_location (
  id           uuid primary key default gen_random_uuid(),
  warehouse_id uuid not null references logistics.warehouse (id) on delete restrict,
  code         text not null,
  zone         text not null default '',
  kind         text not null default 'storage' check (kind in ('receiving', 'storage', 'staging', 'dispatch', 'quarantine', 'damaged')),
  active       boolean not null default true,
  created_at   timestamptz not null default now(),
  unique (warehouse_id, code)
);


-- 5. Colis et son suivi ----------------------------------------------------------------

create table if not exists logistics.parcel (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references logistics.organization (id) on delete restrict,
  tracking_number     text not null unique,
  public_token        text not null,
  customer_id         uuid references logistics.customer (id) on delete restrict,
  description         text not null default '',
  sender_name         text not null default '',
  recipient_name      text not null default '',
  recipient_phone     text not null default '',
  delivery_address    text not null default '',
  destination_country text not null check (destination_country in ('HT', 'DO', 'US')),
  destination_city    text not null default '',
  declared_value      numeric(12, 2) check (declared_value is null or declared_value >= 0),
  weight_lb           numeric(8, 2)  check (weight_lb is null or weight_lb >= 0),
  rate_per_lb         numeric(10, 2) not null default 0 check (rate_per_lb >= 0),
  service_mode        text not null check (service_mode in ('air', 'sea', 'ground')),
  status              text not null references logistics.parcel_status (code),
  status_authority    text not null default 'legacy' check (status_authority in ('legacy', 'core')),
  legacy_status       text,
  current_location    text not null default '',
  current_warehouse_id uuid references logistics.warehouse (id) on delete restrict,
  current_location_id  uuid references logistics.warehouse_location (id) on delete restrict,
  note                text not null default '',
  source              text not null default 'native' check (source in ('native', 'legacy_backfill')),
  legacy_parcel_id    uuid unique,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index if not exists parcel_customer_idx on logistics.parcel (customer_id);
create index if not exists parcel_status_idx on logistics.parcel (status);
comment on table logistics.parcel is 'Un COLIS : un objet qu''un client envoie. Il n''est PAS une expédition (ADR 0006).';
comment on column logistics.parcel.status_authority is 'legacy : le statut vient encore de l''ancien schéma (le rattrapage le recopie). core : la machine d''états du noyau en est seule maîtresse ; le rattrapage n''y touche plus.';
comment on column logistics.parcel.public_token is 'Jeton du QR de l''étiquette. L''identifiant interne (id) n''est jamais montré au public.';

create table if not exists logistics.tracking_event (
  id                bigint generated always as identity primary key,
  parcel_id         uuid not null references logistics.parcel (id) on delete restrict,
  event_type        text not null,
  from_status       text references logistics.parcel_status (code),
  to_status         text references logistics.parcel_status (code),
  occurred_at       timestamptz not null,
  recorded_at       timestamptz not null default now(),
  actor_user_id     uuid references logistics.app_user (id) on delete restrict,
  actor_label       text not null default '',
  warehouse_id      uuid references logistics.warehouse (id) on delete restrict,
  location_id       uuid references logistics.warehouse_location (id) on delete restrict,
  location_text     text not null default '',
  device_id         uuid references logistics.device (id) on delete restrict,
  source            text not null check (source in ('legacy_backfill', 'system', 'scan', 'manual', 'api')),
  metadata          jsonb not null default '{}'::jsonb,
  correlation_id    uuid,
  legacy_history_id bigint unique
);
create index if not exists tracking_event_parcel_idx on logistics.tracking_event (parcel_id, occurred_at);
comment on table logistics.tracking_event is 'Journal du colis : on y AJOUTE, on n''y modifie ni supprime jamais.';

drop trigger if exists tracking_event_append_only on logistics.tracking_event;
create trigger tracking_event_append_only
  before update or delete on logistics.tracking_event
  for each row execute function logistics.forbid_mutation();


-- 6. Consolidation, expédition, transport, livraison -----------------------------------------
-- Colis ≠ Expédition. Un client a plusieurs colis ; plusieurs colis entrent dans une
-- consolidation ; une consolidation entre dans une expédition ; l'expédition voyage par un
-- transport et arrive dans un hub ; les colis sont ensuite affectés à des livraisons.

create table if not exists logistics.consolidation (
  id                  uuid primary key default gen_random_uuid(),
  code                text not null unique,
  warehouse_id        uuid references logistics.warehouse (id) on delete restrict,
  destination_country text not null check (destination_country in ('HT', 'DO', 'US')),
  mode                text not null check (mode in ('air', 'sea', 'ground')),
  status              text not null default 'OPEN' check (status in ('OPEN', 'CLOSED', 'SHIPPED', 'CANCELLED')),
  opened_at           timestamptz not null default now(),
  closed_at           timestamptz,
  created_by          uuid references logistics.app_user (id) on delete restrict,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  check (closed_at is null or closed_at >= opened_at)
);

create table if not exists logistics.consolidation_parcel (
  id               bigint generated always as identity primary key,
  consolidation_id uuid not null references logistics.consolidation (id) on delete restrict,
  parcel_id        uuid not null references logistics.parcel (id) on delete restrict,
  added_at         timestamptz not null default now(),
  removed_at       timestamptz,
  check (removed_at is null or removed_at >= added_at)
);
-- Un colis n'est dans qu'UNE consolidation à la fois ; l'historique des retraits reste.
create unique index if not exists consolidation_parcel_one_active
  on logistics.consolidation_parcel (parcel_id) where removed_at is null;
create index if not exists consolidation_parcel_consolidation_idx on logistics.consolidation_parcel (consolidation_id);

create table if not exists logistics.transport (
  id                    uuid primary key default gen_random_uuid(),
  mode                  text not null check (mode in ('air', 'sea', 'ground')),
  carrier               text not null default '',
  reference             text not null default '',
  vehicle_label         text not null default '',
  origin_branch_id      uuid references logistics.branch (id) on delete restrict,
  destination_branch_id uuid references logistics.branch (id) on delete restrict,
  planned_departure_at  timestamptz,
  planned_arrival_at    timestamptz,
  actual_departure_at   timestamptz,
  actual_arrival_at     timestamptz,
  status                text not null default 'PLANNED' check (status in ('PLANNED', 'DEPARTED', 'ARRIVED', 'CANCELLED')),
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);
comment on table logistics.transport is 'Un voyage (vol, traversée, camion). Plusieurs expéditions peuvent le partager. Modes futurs : ajouter à la contrainte « mode ».';

create table if not exists logistics.shipment (
  id                    uuid primary key default gen_random_uuid(),
  code                  text not null unique,
  mode                  text not null check (mode in ('air', 'sea', 'ground')),
  origin_branch_id      uuid references logistics.branch (id) on delete restrict,
  destination_branch_id uuid references logistics.branch (id) on delete restrict,
  transport_id          uuid references logistics.transport (id) on delete restrict,
  status                text not null default 'DRAFT' references logistics.shipment_status (code),
  dispatched_at         timestamptz,
  arrived_at            timestamptz,
  created_by            uuid references logistics.app_user (id) on delete restrict,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  check (arrived_at is null or dispatched_at is null or arrived_at >= dispatched_at)
);
comment on table logistics.shipment is 'Une EXPÉDITION : un envoi groupé vers un hub. Statuts propres, distincts de ceux d''un colis.';

create table if not exists logistics.shipment_item (
  id               bigint generated always as identity primary key,
  shipment_id      uuid not null references logistics.shipment (id) on delete restrict,
  consolidation_id uuid references logistics.consolidation (id) on delete restrict,
  parcel_id        uuid references logistics.parcel (id) on delete restrict,
  added_at         timestamptz not null default now(),
  check (num_nonnulls(consolidation_id, parcel_id) = 1),   -- une consolidation OU un colis seul (unité logistique : phase 8)
  unique (shipment_id, consolidation_id),
  unique (shipment_id, parcel_id)
);

create table if not exists logistics.delivery (
  id                    uuid primary key default gen_random_uuid(),
  destination_branch_id uuid references logistics.branch (id) on delete restrict,
  status                text not null default 'PLANNED' check (status in ('PLANNED', 'ASSIGNED', 'OUT_FOR_DELIVERY', 'COMPLETED', 'FAILED', 'CANCELLED')),
  scheduled_for         date,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);
comment on table logistics.delivery is 'Squelette : la tournée, l''arrêt, le chauffeur et la preuve de livraison viennent en phase 9.';

create table if not exists logistics.delivery_parcel (
  delivery_id uuid not null references logistics.delivery (id) on delete restrict,
  parcel_id   uuid not null references logistics.parcel (id) on delete restrict,
  added_at    timestamptz not null default now(),
  primary key (delivery_id, parcel_id)
);


-- 7. Factures (le moteur financier complet vient en phase 10) --------------------------------

create table if not exists logistics.invoice (
  id                uuid primary key default gen_random_uuid(),
  organization_id   uuid not null references logistics.organization (id) on delete restrict,
  number            text not null unique,
  customer_id       uuid not null references logistics.customer (id) on delete restrict,
  currency          text not null default 'USD' check (currency in ('USD', 'DOP', 'HTG')),
  status            text not null references logistics.invoice_status (code),
  status_authority  text not null default 'legacy' check (status_authority in ('legacy', 'core')),
  total             numeric(14, 2) not null default 0 check (total >= 0),
  service_fee       numeric(14, 2) not null default 0 check (service_fee >= 0),
  paid_amount       numeric(14, 2) not null default 0 check (paid_amount >= 0),
  is_grouped        boolean not null default false,
  issued_at         timestamptz,
  due_date          date,
  paid_at           timestamptz,
  note              text not null default '',
  source            text not null default 'native' check (source in ('native', 'legacy_backfill')),
  legacy_invoice_id uuid unique,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index if not exists invoice_customer_idx on logistics.invoice (customer_id);
comment on column logistics.invoice.paid_amount is 'Montant payé agrégé, repris tel quel de l''ancien schéma. Aucun paiement individuel n''a été fabriqué : la table payment (phase 10) naîtra des paiements réellement saisis.';

create table if not exists logistics.invoice_item (
  id              bigint generated always as identity primary key,
  invoice_id      uuid not null references logistics.invoice (id) on delete restrict,
  parcel_id       uuid references logistics.parcel (id) on delete restrict,
  description     text not null default '',
  quantity        numeric(10, 2) not null default 1,
  weight_lb       numeric(8, 2),
  unit_price      numeric(12, 2),
  amount          numeric(14, 2) not null default 0,
  position        int not null default 0,
  legacy_line_key text unique
);
create index if not exists invoice_item_invoice_idx on logistics.invoice_item (invoice_id);
create index if not exists invoice_item_parcel_idx on logistics.invoice_item (parcel_id);


-- 8. Journal d'audit ------------------------------------------------------------------------

create table if not exists logistics.audit_log (
  id             bigint generated always as identity primary key,
  occurred_at    timestamptz not null default now(),
  actor_user_id  uuid references logistics.app_user (id) on delete restrict,
  actor_label    text not null default '',
  action         text not null,
  entity_type    text not null,
  entity_id      text not null,
  before         jsonb,
  after          jsonb,
  correlation_id uuid,
  metadata       jsonb not null default '{}'::jsonb
);
create index if not exists audit_log_entity_idx on logistics.audit_log (entity_type, entity_id, occurred_at);
comment on table logistics.audit_log is 'Qui a fait quoi, quand, avec quoi avant/après. En ajout seul.';

drop trigger if exists audit_log_append_only on logistics.audit_log;
create trigger audit_log_append_only
  before update or delete on logistics.audit_log
  for each row execute function logistics.forbid_mutation();


-- 9. « updated_at » tenu à jour --------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array['organization', 'branch', 'app_user', 'customer', 'device', 'warehouse', 'parcel',
                           'consolidation', 'transport', 'shipment', 'delivery', 'invoice']
  loop
    execute format('drop trigger if exists touch_updated_at on logistics.%I', t);
    execute format('create trigger touch_updated_at before update on logistics.%I for each row execute function logistics.touch_updated_at()', t);
  end loop;
end
$$;


-- 10. TOUT fermé à l'API ----------------------------------------------------------------------
-- RLS activée partout, aucune politique, aucun droit pour « anon » ni « authenticated ».
-- (Un rôle qui contourne la RLS, comme le propriétaire, garde l'accès : c'est voulu.)
do $$
declare r record;
begin
  for r in select tablename from pg_tables where schemaname = 'logistics' loop
    execute format('alter table logistics.%I enable row level security', r.tablename);
    execute format('revoke all on logistics.%I from public, anon, authenticated', r.tablename);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'logistics' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
end
$$;
revoke all on schema logistics from public, anon, authenticated;
