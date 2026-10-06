-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 8 : l'API du portail client
-- -----------------------------------------------------------------------------
-- Phase 11. À coller dans Supabase > SQL Editor APRÈS 001 à 007, après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet ouvert est bien « speed-express-site ».
--
-- Ce que le site web (et plus tard l'application) appelle pour montrer au CLIENT : son tableau de bord, ses colis, le suivi daté de chacun
-- (le vrai journal du noyau, pas une maquette), ses expéditions et consolidations, ses factures, paiements et documents, ses adresses,
-- ses demandes d'enlèvement et de livraison, ses notifications et son support.
--
-- Règles tenues ici, dans la base, et JAMAIS dans le navigateur :
--   · l'identité du client est TOUJOURS le compte connecté (auth.uid()) ; aucune fonction ne prend un « client » en paramètre ;
--   · un client ne voit que ce qui est à lui, et un identifiant qui n'est pas à lui répond comme un identifiant qui n'existe pas (LG002) ;
--   · il ne voit jamais l'identité du personnel, les emplacements internes, les motifs internes, ni un brouillon ;
--   · il ne peut RIEN modifier d'autre que ses adresses, ses demandes, ses messages et l'état « lu » de ses notifications : ni rôle, ni droits,
--     ni statut de colis, ni facture, ni événement (les tables du noyau restent fermées ; ce fichier n'ouvre que des fonctions) ;
--   · des plafonds contre les abus (nombre d'adresses, de demandes ouvertes, de tickets, longueur des textes).
--
-- Ne touche à aucune ancienne table (il LIT l'ancien schéma pour dire si le noyau est à jour). Retour arrière au bas du fichier. Rejouable.
-- =============================================================================

-- 1. Catalogue d'événements : ce que le client a le droit de voir ----------------------------------------------------------------
alter table logistics.event_type drop constraint if exists event_type_aggregate_type_check;
alter table logistics.event_type add constraint event_type_aggregate_type_check
  check (aggregate_type in ('parcel', 'shipment', 'consolidation', 'warehouse', 'delivery', 'pickup', 'trip', 'task', 'driver', 'incident',
                            'customs', 'invoice', 'payment', 'scan', 'quote', 'expense', 'pricing', 'request', 'ticket'));
alter table logistics.event_type add column if not exists customer_visible boolean not null default false;
comment on column logistics.event_type.customer_visible is 'Vrai : le client voit cet événement dans le suivi de son colis. Les événements internes (rangement, mouvement, inspection) restent faux.';

insert into logistics.event_type (code, aggregate_type, description, customer_visible) values
  ('ParcelStatusChanged',       'parcel',  'Changement de statut repris de l''ancien schéma', true),
  ('PickupRequestCreated',      'request', 'Demande d''enlèvement déposée par le client', false),
  ('PickupRequestCancelled',    'request', 'Demande d''enlèvement annulée par le client', false),
  ('DeliveryRequestCreated',    'request', 'Demande de livraison déposée par le client', false),
  ('DeliveryRequestCancelled',  'request', 'Demande de livraison annulée par le client', false),
  ('SupportTicketOpened',       'ticket',  'Ticket de support ouvert par le client', false),
  ('SupportTicketReplied',      'ticket',  'Réponse ajoutée à un ticket de support', false),
  ('SupportTicketClosed',       'ticket',  'Ticket de support fermé', false)
on conflict (code) do nothing;
update logistics.event_type set customer_visible = (code in (
  'ParcelCreated', 'ParcelReceived', 'ParcelVerified', 'ParcelConsolidated', 'ParcelReadyForExport', 'ParcelInTransit', 'ParcelArrived',
  'CustomsStarted', 'CustomsCleared', 'ParcelAtDestinationHub', 'DeliveryAssigned', 'OutForDelivery', 'Delivered', 'ParcelOnHold', 'ParcelResumed',
  'ParcelCancelled', 'ParcelDamaged', 'ParcelLost', 'ParcelReturned', 'ParcelReturnedToHub', 'ParcelStatusChanged'))
 where aggregate_type = 'parcel';


-- 2. Le vocabulaire du client : peu d'étapes, claires ----------------------------------------------------------------------------
-- Les vingt statuts du colis sont un vocabulaire d'exploitation. Le client en voit sept étapes et cinq exceptions. La correspondance vit ICI,
-- une seule fois : le site et l'application ne la recopient pas.
create or replace function logistics.customer_stage(p_status text)
returns text language sql immutable set search_path = '' as $$
  select case p_status
    when 'CREATED' then 'registered'
    when 'RECEIVED' then 'received' when 'VERIFIED' then 'received' when 'STORED' then 'received'
    when 'CONSOLIDATION_PENDING' then 'received' when 'CONSOLIDATED' then 'received' when 'READY_FOR_EXPORT' then 'received'
    when 'IN_TRANSIT' then 'in_transit'
    when 'ARRIVED' then 'customs' when 'CUSTOMS_PROCESSING' then 'customs' when 'CUSTOMS_CLEARED' then 'customs'
    when 'AT_DESTINATION_HUB' then 'at_hub'
    when 'DELIVERY_ASSIGNED' then 'out_for_delivery' when 'OUT_FOR_DELIVERY' then 'out_for_delivery'
    when 'DELIVERED' then 'delivered'
    when 'ON_HOLD' then 'on_hold' when 'DAMAGED' then 'incident' when 'LOST' then 'lost'
    when 'CANCELLED' then 'cancelled' when 'RETURNED' then 'returned'
  end
$$;
create or replace function logistics.customer_shipment_stage(p_status text)
returns text language sql immutable set search_path = '' as $$
  select case p_status
    when 'DRAFT' then 'preparing' when 'READY' then 'preparing'
    when 'DISPATCHED' then 'in_transit' when 'IN_TRANSIT' then 'in_transit'
    when 'ARRIVED' then 'customs' when 'CUSTOMS_PROCESSING' then 'customs' when 'CUSTOMS_CLEARED' then 'customs'
    when 'AT_HUB' then 'at_hub' when 'CLOSED' then 'closed' when 'CANCELLED' then 'cancelled'
  end
$$;


-- 3. Tables du portail ---------------------------------------------------------------------------------------------------------------
create table if not exists logistics.customer_address (
  id             uuid primary key default gen_random_uuid(),
  customer_id    uuid not null references logistics.customer (id) on delete restrict,
  label          text not null default '' check (char_length(label) <= 40),
  recipient_name text not null default '' check (char_length(recipient_name) <= 120),
  phone          text not null default '' check (char_length(phone) <= 40),
  country        text not null check (country in ('HT', 'DO', 'US')),
  region         text not null default '' check (char_length(region) <= 80),
  city           text not null default '' check (char_length(city) <= 80),
  address        text not null check (btrim(address) <> '' and char_length(address) <= 200),
  instructions   text not null default '' check (char_length(instructions) <= 300),
  is_default     boolean not null default false,
  active         boolean not null default true,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create unique index if not exists customer_address_one_default on logistics.customer_address (customer_id) where is_default and active;
create index if not exists customer_address_customer_idx on logistics.customer_address (customer_id) where active;
drop trigger if exists touch_updated_at on logistics.customer_address;
create trigger touch_updated_at before update on logistics.customer_address for each row execute function logistics.touch_updated_at();

create table if not exists logistics.pickup_request (
  id             uuid primary key default gen_random_uuid(),
  number         text not null unique,
  customer_id    uuid not null references logistics.customer (id) on delete restrict,
  address_id     uuid references logistics.customer_address (id) on delete restrict,
  country        text not null check (country in ('HT', 'DO', 'US')),
  city           text not null default '' check (char_length(city) <= 80),
  address        text not null check (btrim(address) <> '' and char_length(address) <= 200),
  contact_name   text not null default '' check (char_length(contact_name) <= 120),
  contact_phone  text not null default '' check (char_length(contact_phone) <= 40),
  preferred_date date not null,
  preferred_window text not null default 'ANY' check (preferred_window in ('MORNING', 'AFTERNOON', 'ANY')),
  parcels_expected int not null default 1 check (parcels_expected between 1 and 100),
  notes          text not null default '' check (char_length(notes) <= 500),
  status         text not null default 'REQUESTED' check (status in ('REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED')),
  task_id        uuid references logistics.task (id) on delete restrict,
  review_message text check (review_message is null or char_length(review_message) <= 500),
  reviewed_by    uuid references logistics.app_user (id) on delete restrict,
  reviewed_at    timestamptz,
  correlation_id uuid not null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists pickup_request_customer_idx on logistics.pickup_request (customer_id, created_at desc);
create index if not exists pickup_request_open_idx on logistics.pickup_request (status) where status = 'REQUESTED';
comment on column logistics.pickup_request.review_message is 'Message du personnel destiné au CLIENT (visible dans son portail) : motif de refus, précisions.';

create table if not exists logistics.delivery_request (
  id             uuid primary key default gen_random_uuid(),
  number         text not null unique,
  customer_id    uuid not null references logistics.customer (id) on delete restrict,
  address_id     uuid references logistics.customer_address (id) on delete restrict,
  country        text not null check (country in ('HT', 'DO', 'US')),
  city           text not null default '' check (char_length(city) <= 80),
  address        text not null check (btrim(address) <> '' and char_length(address) <= 200),
  contact_name   text not null default '' check (char_length(contact_name) <= 120),
  contact_phone  text not null default '' check (char_length(contact_phone) <= 40),
  preferred_date date not null,
  preferred_window text not null default 'ANY' check (preferred_window in ('MORNING', 'AFTERNOON', 'ANY')),
  notes          text not null default '' check (char_length(notes) <= 500),
  status         text not null default 'REQUESTED' check (status in ('REQUESTED', 'APPROVED', 'REJECTED', 'CANCELLED')),
  delivery_id    uuid references logistics.delivery (id) on delete restrict,
  review_message text check (review_message is null or char_length(review_message) <= 500),
  reviewed_by    uuid references logistics.app_user (id) on delete restrict,
  reviewed_at    timestamptz,
  correlation_id uuid not null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index if not exists delivery_request_customer_idx on logistics.delivery_request (customer_id, created_at desc);
create index if not exists delivery_request_open_idx on logistics.delivery_request (status) where status = 'REQUESTED';
create table if not exists logistics.delivery_request_parcel (
  request_id uuid not null references logistics.delivery_request (id) on delete restrict,
  parcel_id  uuid not null references logistics.parcel (id) on delete restrict,
  primary key (request_id, parcel_id)
);

-- Une demande ne change que de statut, dans un seul sens ; elle ne se supprime pas ; ses champs ne se retouchent pas.
create or replace function logistics.guard_request()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then raise exception 'Une demande ne se supprime pas : on l''annule.' using errcode = 'LG004'; end if;
  if (to_jsonb(new) - 'status' - 'task_id' - 'delivery_id' - 'review_message' - 'reviewed_by' - 'reviewed_at' - 'updated_at')
     is distinct from (to_jsonb(old) - 'status' - 'task_id' - 'delivery_id' - 'review_message' - 'reviewed_by' - 'reviewed_at' - 'updated_at') then
    raise exception 'Les champs d''une demande déposée ne se modifient pas : annulez-la et déposez-en une autre.' using errcode = 'LG004';
  end if;
  if new.status is distinct from old.status and not (old.status = 'REQUESTED' and new.status in ('APPROVED', 'REJECTED', 'CANCELLED')) then
    raise exception 'Demande % : passage % → % interdit.', old.number, old.status, new.status using errcode = 'LG001';
  end if;
  return new;
end;
$$;
do $$
declare t text;
begin
  foreach t in array array['pickup_request', 'delivery_request'] loop
    execute format('drop trigger if exists guard_request on logistics.%I', t);
    execute format('create trigger guard_request before update or delete on logistics.%I for each row execute function logistics.guard_request()', t);
    execute format('drop trigger if exists touch_updated_at on logistics.%I', t);
    execute format('create trigger touch_updated_at before update on logistics.%I for each row execute function logistics.touch_updated_at()', t);
  end loop;
end
$$;
drop trigger if exists delivery_request_parcel_append_only on logistics.delivery_request_parcel;
create trigger delivery_request_parcel_append_only before update or delete on logistics.delivery_request_parcel for each row execute function logistics.forbid_mutation();

create table if not exists logistics.support_ticket (
  id          uuid primary key default gen_random_uuid(),
  number      text not null unique,
  customer_id uuid not null references logistics.customer (id) on delete restrict,
  subject     text not null check (char_length(btrim(subject)) between 3 and 120),
  category    text not null check (category in ('PARCEL', 'INVOICE', 'PICKUP', 'DELIVERY', 'ACCOUNT', 'OTHER')),
  parcel_id   uuid references logistics.parcel (id) on delete restrict,
  invoice_id  uuid references logistics.invoice (id) on delete restrict,
  status      text not null default 'OPEN' check (status in ('OPEN', 'ANSWERED', 'CLOSED')),
  closed_at   timestamptz,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  check ((status = 'CLOSED') = (closed_at is not null))
);
create index if not exists support_ticket_customer_idx on logistics.support_ticket (customer_id, updated_at desc);
create index if not exists support_ticket_open_idx on logistics.support_ticket (status) where status <> 'CLOSED';
drop trigger if exists touch_updated_at on logistics.support_ticket;
create trigger touch_updated_at before update on logistics.support_ticket for each row execute function logistics.touch_updated_at();
create table if not exists logistics.support_message (
  id             bigint generated always as identity primary key,
  ticket_id      uuid not null references logistics.support_ticket (id) on delete restrict,
  author_kind    text not null check (author_kind in ('CUSTOMER', 'STAFF')),
  author_user_id uuid references logistics.app_user (id) on delete restrict,
  body           text not null check (char_length(btrim(body)) between 1 and 4000),
  created_at     timestamptz not null default now(),
  check ((author_kind = 'STAFF') = (author_user_id is not null))
);
create index if not exists support_message_ticket_idx on logistics.support_message (ticket_id, id);
drop trigger if exists support_message_append_only on logistics.support_message;
create trigger support_message_append_only before update or delete on logistics.support_message for each row execute function logistics.forbid_mutation();
create or replace function logistics.guard_ticket()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then raise exception 'Un ticket ne se supprime pas : on le ferme.' using errcode = 'LG004'; end if;
  if (to_jsonb(new) - 'status' - 'closed_at' - 'updated_at') is distinct from (to_jsonb(old) - 'status' - 'closed_at' - 'updated_at') then
    raise exception 'Un ticket ouvert ne se retouche pas : répondez-y.' using errcode = 'LG004';
  end if;
  if old.status = 'CLOSED' and new.status <> 'CLOSED' then raise exception 'Ticket % fermé : ouvrez-en un nouveau.', old.number using errcode = 'LG001'; end if;
  return new;
end;
$$;
drop trigger if exists guard_ticket on logistics.support_ticket;
create trigger guard_ticket before update or delete on logistics.support_ticket for each row execute function logistics.guard_ticket();

-- Les notifications : un canal « in_app » (ce que le client voit dans son portail) et un état « lu ». (La refonte complète : phase 13.)
alter table logistics.notification add column if not exists read_at timestamptz;
alter table logistics.notification drop constraint if exists notification_channel_check;
alter table logistics.notification add constraint notification_channel_check check (channel in ('push', 'whatsapp', 'email', 'in_app', 'sms'));
create index if not exists notification_customer_inapp_idx on logistics.notification (customer_id, created_at desc) where channel = 'in_app';


-- 4. Outils internes -----------------------------------------------------------------------------------------------------------------------
create or replace function logistics.my_customer(p_user uuid)
returns uuid language sql stable security definer set search_path = '' as $$
  select c.id from logistics.customer c where p_user is not null and c.auth_user_id = p_user
$$;
create or replace function logistics.require_customer(p_user uuid)
returns uuid language plpgsql stable security definer set search_path = '' as $$
declare v uuid;
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  v := logistics.my_customer(p_user);
  if v is null then raise exception 'Compte client requis.' using errcode = 'LG003'; end if;
  return v;
end;
$$;
-- Le client n'est pas un membre du personnel : ni le journal d'audit, ni les événements ne peuvent le nommer comme « acteur » (clés étrangères
-- vers le personnel). On le trace donc par son code, avec l'acteur vide.
create or replace function logistics.cust_audit(p_customer uuid, p_action text, p_type text, p_id text, p_before jsonb, p_after jsonb, p_corr uuid)
returns void language plpgsql volatile set search_path = '' as $$
begin
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id, metadata)
  values (null, 'customer:' || coalesce((select code from logistics.customer where id = p_customer), p_customer::text), p_action, p_type, p_id, p_before, p_after, p_corr,
          jsonb_build_object('customer_id', p_customer));
end;
$$;
create or replace function logistics.emit_customer(p_type text, p_agg_type text, p_agg_id text, p_corr uuid, p_customer uuid, p_payload jsonb)
returns bigint language plpgsql volatile set search_path = '' as $$
declare v_id bigint;
begin
  insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_user_id, actor_label, payload)
  values (p_type, p_agg_type, p_agg_id, p_corr, null, 'customer:' || coalesce((select code from logistics.customer where id = p_customer), p_customer::text),
          coalesce(p_payload, '{}'::jsonb) || jsonb_build_object('customer_id', p_customer))
  returning id into v_id;
  return v_id;
end;
$$;

-- Le noyau est-il à jour POUR CE CLIENT ? Tant que l'ancien schéma reste la source de vérité, le noyau prend du retard dès que le site écrit
-- (stratégie de migration, §7). Le portail ne lit le noyau que si chaque colis et chaque facture de l'ancien schéma y a son pendant à jour.
create or replace function logistics.customer_in_sync(p_customer uuid, p_user uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select not exists (select 1 from public.colis c where c.client_id = p_user
                      and not exists (select 1 from logistics.parcel p where p.legacy_parcel_id = c.id and p.customer_id = p_customer
                                       and (p.status_authority = 'core' or p.legacy_status = c.statut)))
     and not exists (select 1 from public.factures f where f.client_id = p_user
                      and not exists (select 1 from logistics.invoice i where i.legacy_invoice_id = f.id and i.customer_id = p_customer
                                       and i.paid_amount = f.montant_paye))
$$;

-- Le nom d'un lieu tel que le client le lit : « Hub Port-au-Prince », « Miami, FL » : la ville s'ajoute au nom seulement si le nom ne la contient pas déjà.
create or replace function logistics.branch_label(p_branch uuid)
returns text language sql stable security definer set search_path = '' as $$
  select nullif(case when nullif(b.city, '') is null or position(lower(b.city) in lower(b.name)) > 0 then b.name else concat_ws(', ', nullif(b.name, ''), b.city) end, '')
    from logistics.branch b where b.id = p_branch
$$;

create or replace function logistics.parcel_place(p logistics.parcel)
returns text language sql stable security definer set search_path = '' as $$
  select case when p.status_authority = 'legacy' then nullif(p.current_location, '')
              else (select logistics.branch_label(w.branch_id) from logistics.warehouse w where w.id = p.current_warehouse_id) end
$$;

create or replace function logistics.parcel_card(p logistics.parcel)
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object('tracking_number', p.tracking_number, 'public_token', p.public_token, 'status', p.status,
           'stage', logistics.customer_stage(p.status), 'service_mode', p.service_mode, 'destination_country', p.destination_country,
           'destination_city', p.destination_city, 'description', p.description, 'sender_name', p.sender_name, 'recipient_name', p.recipient_name,
           'delivery_address', p.delivery_address, 'weight_lb', coalesce(p.verified_weight_lb, p.weight_lb), 'declared_value', p.declared_value,
           'place', logistics.parcel_place(p), 'created_at', p.created_at, 'updated_at', p.updated_at)
$$;

-- Le suivi du colis : le VRAI journal (tracking_event), filtré pour le client. Jamais l'auteur, jamais l'emplacement interne, jamais le motif.
create or replace function logistics.timeline_of(p_parcel uuid)
returns jsonb language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'at', e.occurred_at, 'event', e.event_type, 'status', e.to_status, 'stage', logistics.customer_stage(e.to_status),
           'place', case when e.source = 'legacy_backfill' then nullif(e.location_text, '')
                         else (select logistics.branch_label(w.branch_id) from logistics.warehouse w where w.id = e.warehouse_id) end,
           -- Seule la note de l'ancien schéma est reprise : le client la lisait déjà dans son historique.
           'note', case when e.source = 'legacy_backfill' then nullif(e.metadata ->> 'note', '') end)
         order by e.occurred_at, e.id), '[]'::jsonb)
    from logistics.tracking_event e join logistics.event_type t on t.code = e.event_type and t.customer_visible
   where e.parcel_id = p_parcel
$$;

-- Les expéditions qui portent un colis : en direct, par une consolidation, ou par une unité logistique.
create or replace function logistics.shipments_of_parcel(p_parcel uuid)
returns table (shipment_id uuid) language sql stable security definer set search_path = '' as $$
  select i.shipment_id from logistics.shipment_item i where i.parcel_id = p_parcel
  union
  select i.shipment_id from logistics.shipment_item i join logistics.consolidation_parcel cp on cp.consolidation_id = i.consolidation_id and cp.removed_at is null
   where cp.parcel_id = p_parcel
  union
  select i.shipment_id from logistics.shipment_item i join logistics.consolidation c on c.load_unit_id = i.load_unit_id
   join logistics.consolidation_parcel cp on cp.consolidation_id = c.id and cp.removed_at is null where i.load_unit_id is not null and cp.parcel_id = p_parcel
$$;

create or replace function logistics.shipment_card(p_shipment uuid, p_customer uuid)
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object('code', s.code, 'mode', s.mode, 'status', s.status, 'stage', logistics.customer_shipment_stage(s.status),
           'origin', logistics.branch_label(s.origin_branch_id), 'destination', logistics.branch_label(s.destination_branch_id),
           'carrier', t.carrier, 'reference', t.reference, 'planned_arrival_at', t.planned_arrival_at,
           'dispatched_at', s.dispatched_at, 'arrived_at', s.arrived_at,
           'customs', (select case d.status when 'CLEARED' then 'cleared' when 'REJECTED' then 'rejected' else 'processing' end
                         from logistics.customs_declaration d where d.shipment_id = s.id and d.status <> 'CANCELLED' order by d.created_at desc limit 1),
           -- Seuls les colis DU client : un envoi groupé n'en dit rien de plus.
           'my_parcels', coalesce((select jsonb_agg(jsonb_build_object('tracking_number', p.tracking_number, 'stage', logistics.customer_stage(p.status)) order by p.tracking_number)
                                     from logistics.parcel p where p.customer_id = p_customer and exists (select 1 from logistics.shipments_of_parcel(p.id) sp where sp.shipment_id = s.id)), '[]'::jsonb))
    from logistics.shipment s left join logistics.transport t on t.id = s.transport_id where s.id = p_shipment
$$;


-- 5. Lecture : tableau de bord, colis, suivi, expéditions, consolidations ---------------------------------------------------------------------
create or replace function logistics.my_dashboard(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c logistics.customer;
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  select * into v_c from logistics.customer c where c.auth_user_id = p_user;
  if not found then return jsonb_build_object('linked', false, 'in_sync', false); end if;
  return jsonb_build_object(
    'linked', true,
    'in_sync', logistics.customer_in_sync(v_c.id, p_user),
    'customer', jsonb_build_object('code', v_c.code, 'full_name', v_c.full_name, 'language', v_c.language),
    'parcels', jsonb_build_object(
        'total', (select count(*) from logistics.parcel p where p.customer_id = v_c.id),
        'by_stage', coalesce((select jsonb_object_agg(x.stage, x.n) from (select logistics.customer_stage(p.status) as stage, count(*) as n
                                                                          from logistics.parcel p where p.customer_id = v_c.id group by 1) x), '{}'::jsonb)),
    'invoices', jsonb_build_object(
        'unpaid', (select count(*) from logistics.invoice i where i.customer_id = v_c.id and i.status not in ('DRAFT', 'CANCELLED') and logistics.invoice_balance(i) > 0),
        'overdue', (select count(*) from logistics.invoice i where i.customer_id = v_c.id and i.status = 'OVERDUE'),
        'balances', coalesce((select jsonb_agg(jsonb_build_object('currency', b.currency, 'balance', b.balance) order by b.currency)
                                from logistics.customer_balance b where b.customer_id = v_c.id), '[]'::jsonb)),
    'deliveries', jsonb_build_object(
        'upcoming', coalesce((select jsonb_agg(jsonb_build_object('scheduled_date', x.scheduled_date, 'window_start', x.window_start, 'window_end', x.window_end,
                                                                    'status', x.status, 'parcels', x.n) order by x.scheduled_date, x.id)
                                from (select t.id, t.scheduled_date, t.window_start, t.window_end, t.status,
                                             (select count(*) from logistics.delivery_parcel dp where dp.delivery_id = d.id) as n
                                        from logistics.task t join logistics.delivery d on d.id = t.delivery_id
                                       where t.kind = 'DELIVERY' and d.customer_id = v_c.id and t.status in ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED')
                                       order by t.scheduled_date, t.id limit 5) x), '[]'::jsonb)),
    'pickups', jsonb_build_object('open', (select count(*) from logistics.pickup_request r where r.customer_id = v_c.id and r.status in ('REQUESTED', 'APPROVED')
                                              and (r.task_id is null or exists (select 1 from logistics.task t where t.id = r.task_id and t.status not in ('COMPLETED', 'CANCELLED', 'FAILED'))))),
    'notifications', jsonb_build_object('unread', (select count(*) from logistics.notification n where n.customer_id = v_c.id and n.channel = 'in_app' and n.read_at is null)),
    'tickets', jsonb_build_object('open', (select count(*) from logistics.support_ticket s where s.customer_id = v_c.id and s.status <> 'CLOSED')),
    'recent_events', coalesce((select jsonb_agg(jsonb_build_object('tracking_number', x.tracking_number, 'at', x.at, 'event', x.event, 'stage', x.stage) order by x.at desc, x.id desc)
                                 from (select e.id, p.tracking_number, e.occurred_at as at, e.event_type as event, logistics.customer_stage(e.to_status) as stage
                                         from logistics.tracking_event e join logistics.parcel p on p.id = e.parcel_id
                                         join logistics.event_type t on t.code = e.event_type and t.customer_visible
                                        where p.customer_id = v_c.id order by e.occurred_at desc, e.id desc limit 5) x), '[]'::jsonb));
end;
$$;

create or replace function logistics.my_parcels(p_user uuid, p_stage text default null, p_search text default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user); v_lim int := least(greatest(coalesce(p_limit, 50), 1), 200); v_off int := greatest(coalesce(p_offset, 0), 0);
        v_q text := lower(btrim(coalesce(p_search, '')));
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return jsonb_build_object('total', 0, 'by_stage', '{}'::jsonb, 'items', '[]'::jsonb); end if;
  return (
    with m as (select p.* from logistics.parcel p
                where p.customer_id = v_c
                  and (v_q = '' or position(v_q in lower(p.tracking_number)) > 0 or position(v_q in lower(p.description)) > 0 or position(v_q in lower(p.recipient_name)) > 0)),
         f as (select m.* from m where p_stage is null or p_stage = '' or logistics.customer_stage(m.status) = p_stage)
    select jsonb_build_object(
      'total', (select count(*) from f),
      'by_stage', coalesce((select jsonb_object_agg(x.stage, x.n) from (select logistics.customer_stage(m.status) as stage, count(*) as n from m group by 1) x), '{}'::jsonb),
      'items', coalesce((select jsonb_agg(logistics.parcel_card(g) order by g.updated_at desc, g.tracking_number)
                           from (select * from f order by updated_at desc, tracking_number limit v_lim offset v_off) g), '[]'::jsonb)));
end;
$$;

create or replace function logistics.my_parcel(p_user uuid, p_tracking text)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user); v_p logistics.parcel;
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  select * into v_p from logistics.parcel p where p.customer_id = v_c and p.tracking_number = upper(btrim(coalesce(p_tracking, '')));
  if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  return logistics.parcel_card(v_p) || jsonb_build_object(
    'timeline', logistics.timeline_of(v_p.id),
    'shipment', (select logistics.shipment_card(s.id, v_c) from logistics.shipment s
                  where s.id in (select sp.shipment_id from logistics.shipments_of_parcel(v_p.id) sp) and s.status not in ('DRAFT', 'CANCELLED')
                  order by s.created_at desc limit 1),
    'consolidation', (select jsonb_build_object('code', c.code, 'status', c.status, 'closed_at', c.closed_at)
                        from logistics.consolidation_parcel cp join logistics.consolidation c on c.id = cp.consolidation_id
                       where cp.parcel_id = v_p.id and cp.removed_at is null and c.status <> 'CANCELLED' order by cp.added_at desc limit 1),
    'delivery', (select jsonb_build_object('stage', case t.status when 'COMPLETED' then 'delivered' when 'STARTED' then 'on_the_way' when 'CANCELLED' then 'cancelled'
                                                                   when 'FAILED' then 'missed' else 'scheduled' end,
                                           'scheduled_date', t.scheduled_date, 'window_start', t.window_start, 'window_end', t.window_end,
                                           'otp_required', d.otp_required, 'otp_issued', d.otp_hash is not null, 'failure', t.failed_reason,
                                           'proof', (select jsonb_build_object('recipient_name', pod.recipient_name, 'delivered_at', pod.delivered_at)
                                                       from logistics.proof_of_delivery pod where pod.task_id = t.id))
                   from logistics.delivery_parcel dp join logistics.delivery d on d.id = dp.delivery_id
                   join logistics.task t on t.delivery_id = d.id and t.kind = 'DELIVERY'
                  where dp.parcel_id = v_p.id order by t.created_at desc limit 1),
    'invoices', coalesce((select jsonb_agg(jsonb_build_object('number', x.number, 'status', x.status, 'total', x.total, 'currency', x.currency) order by x.number)
                            from (select distinct i.number, i.status, i.total, i.currency from logistics.invoice_item it join logistics.invoice i on i.id = it.invoice_id
                                   where it.parcel_id = v_p.id and i.customer_id = v_c and i.status <> 'DRAFT') x), '[]'::jsonb));
end;
$$;

create or replace function logistics.my_shipments(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user);
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return '[]'::jsonb; end if;
  return coalesce((select jsonb_agg(logistics.shipment_card(x.id, v_c) order by x.created_at desc, x.code)
                     from (select distinct s.id, s.created_at, s.code from logistics.shipment s
                            where s.status not in ('DRAFT', 'CANCELLED')
                              and exists (select 1 from logistics.parcel p where p.customer_id = v_c and s.id in (select sp.shipment_id from logistics.shipments_of_parcel(p.id) sp))) x), '[]'::jsonb);
end;
$$;

create or replace function logistics.my_consolidations(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user);
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return '[]'::jsonb; end if;
  return coalesce((
    select jsonb_agg(jsonb_build_object('code', x.code, 'status', x.status, 'mode', x.mode, 'destination_country', x.destination_country,
                                        'opened_at', x.opened_at, 'closed_at', x.closed_at,
                                        'origin', (select logistics.branch_label(w.branch_id) from logistics.warehouse w where w.id = x.warehouse_id),
                                        'my_count', x.my_count, 'my_parcels', x.my_parcels,
                                        'shipment', (select s.code from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id
                                                      where i.consolidation_id = x.id and s.status <> 'CANCELLED' order by s.created_at desc limit 1)) order by x.opened_at desc, x.code)
      from (select c.id, c.code, c.status, c.mode, c.destination_country, c.opened_at, c.closed_at, c.warehouse_id,
                   count(*) as my_count, jsonb_agg(p.tracking_number order by p.tracking_number) as my_parcels
              from logistics.consolidation c join logistics.consolidation_parcel cp on cp.consolidation_id = c.id and cp.removed_at is null
              join logistics.parcel p on p.id = cp.parcel_id and p.customer_id = v_c
             where c.status <> 'CANCELLED' group by c.id) x), '[]'::jsonb);
end;
$$;


-- 6. Lecture : paiements et documents ---------------------------------------------------------------------------------------------------------
create or replace function logistics.my_payments(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user);
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return jsonb_build_object('payments', '[]'::jsonb, 'refunds', '[]'::jsonb, 'credits', '[]'::jsonb); end if;
  return jsonb_build_object(
    'payments', coalesce((select jsonb_agg(jsonb_build_object('number', p.number, 'invoice', i.number, 'amount', p.amount, 'currency', p.currency, 'method', p.method,
                                                              'tendered_amount', p.tendered_amount, 'tendered_currency', p.tendered_currency, 'paid_at', p.paid_at)
                                           order by p.paid_at desc, p.number)
                            from logistics.payment p join logistics.invoice i on i.id = p.invoice_id where p.customer_id = v_c), '[]'::jsonb),
    -- Le motif d'un remboursement reste interne ; le client voit le montant, la date et le mode.
    'refunds', coalesce((select jsonb_agg(jsonb_build_object('number', r.number, 'invoice', i.number, 'amount', r.amount, 'currency', r.currency, 'method', r.method, 'refunded_at', r.created_at)
                                          order by r.created_at desc, r.number)
                           from logistics.refund r join logistics.invoice i on i.id = r.invoice_id where r.customer_id = v_c), '[]'::jsonb),
    'credits', coalesce((select jsonb_agg(jsonb_build_object('number', c.number, 'invoice', i.number, 'amount', c.amount, 'currency', c.currency, 'reason', c.reason, 'issued_at', c.created_at)
                                          order by c.created_at desc, c.number)
                           from logistics.credit c join logistics.invoice i on i.id = c.invoice_id where c.customer_id = v_c), '[]'::jsonb));
end;
$$;

create or replace function logistics.my_documents(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user);
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return '[]'::jsonb; end if;
  return coalesce((select jsonb_agg(to_jsonb(d) - 'sort_key' order by d.sort_key desc, d.number) from (
    select 'INVOICE'::text as kind, i.number, i.issued_at as date, i.total as amount, i.currency, i.status, null::jsonb as extra, i.issued_at as sort_key
      from logistics.invoice i where i.customer_id = v_c and i.status <> 'DRAFT' and i.issued_at is not null
    union all
    select 'CREDIT_NOTE', c.number, c.created_at, c.amount, c.currency, 'ISSUED', jsonb_build_object('invoice', i.number, 'reason', c.reason), c.created_at
      from logistics.credit c join logistics.invoice i on i.id = c.invoice_id where c.customer_id = v_c
    union all
    select 'QUOTE', q.number, q.created_at, q.total, q.currency, q.status,
           jsonb_build_object('valid_until', q.valid_until, 'lines', coalesce((select jsonb_agg(jsonb_build_object('kind', l ->> 'kind', 'description', l ->> 'description', 'amount', (l ->> 'amount')::numeric))
                                                                               from jsonb_array_elements(q.calculation -> 'lines') l), '[]'::jsonb)), q.created_at
      from logistics.quote q where q.customer_id = v_c and q.status <> 'CANCELLED'
    union all
    select 'DELIVERY_RECEIPT', 'POD-' || upper(substr(replace(pod.id::text, '-', ''), 1, 8)), pod.delivered_at, null, null, 'DELIVERED',
           jsonb_build_object('recipient_name', pod.recipient_name,
                              'parcels', (select jsonb_agg(p.tracking_number order by p.tracking_number) from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = pod.delivery_id)),
           pod.delivered_at
      from logistics.proof_of_delivery pod join logistics.delivery d on d.id = pod.delivery_id where d.customer_id = v_c) d), '[]'::jsonb);
end;
$$;


-- 7. Adresses ---------------------------------------------------------------------------------------------------------------------------------
create or replace function logistics.my_addresses(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user);
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return '[]'::jsonb; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('address_id', a.id, 'label', a.label, 'recipient_name', a.recipient_name, 'phone', a.phone, 'country', a.country, 'region', a.region,
                                                       'city', a.city, 'address', a.address, 'instructions', a.instructions, 'is_default', a.is_default, 'created_at', a.created_at)
                                    order by a.is_default desc, a.created_at, a.id)
                     from logistics.customer_address a where a.customer_id = v_c and a.active), '[]'::jsonb);
end;
$$;

create or replace function logistics.save_address(p_user uuid, p_id uuid, p_label text, p_recipient_name text, p_phone text, p_country text, p_region text, p_city text,
                                                   p_address text, p_instructions text, p_default boolean)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid := logistics.require_customer(p_user); v_id uuid := p_id; v_corr uuid := gen_random_uuid(); v_n int; v_before jsonb; v_def boolean := coalesce(p_default, false);
begin
  if p_country is null or p_country not in ('HT', 'DO', 'US') then raise exception 'Pays inconnu (HT, DO ou US).' using errcode = 'LG005'; end if;
  if btrim(coalesce(p_address, '')) = '' then raise exception 'L''adresse est obligatoire.' using errcode = 'LG005'; end if;
  if char_length(p_address) > 200 or char_length(coalesce(p_label, '')) > 40 or char_length(coalesce(p_city, '')) > 80 or char_length(coalesce(p_region, '')) > 80
     or char_length(coalesce(p_recipient_name, '')) > 120 or char_length(coalesce(p_phone, '')) > 40 or char_length(coalesce(p_instructions, '')) > 300 then
    raise exception 'Un champ de l''adresse est trop long.' using errcode = 'LG005';
  end if;
  select count(*) into v_n from logistics.customer_address a where a.customer_id = v_c and a.active;
  if v_id is null then
    if v_n >= 20 then raise exception 'Vous avez atteint le maximum de 20 adresses : supprimez-en une.' using errcode = 'LG005'; end if;
    if v_n = 0 then v_def := true; end if;
    if v_def then update logistics.customer_address set is_default = false where customer_id = v_c and is_default; end if;
    insert into logistics.customer_address (customer_id, label, recipient_name, phone, country, region, city, address, instructions, is_default)
    values (v_c, btrim(coalesce(p_label, '')), btrim(coalesce(p_recipient_name, '')), btrim(coalesce(p_phone, '')), p_country, btrim(coalesce(p_region, '')), btrim(coalesce(p_city, '')),
            btrim(p_address), btrim(coalesce(p_instructions, '')), v_def) returning id into v_id;
    perform logistics.cust_audit(v_c, 'address.create', 'customer_address', v_id::text, null, jsonb_build_object('country', p_country, 'city', p_city), v_corr);
  else
    select to_jsonb(a) into v_before from logistics.customer_address a where a.id = v_id and a.customer_id = v_c and a.active for update;
    if v_before is null then raise exception 'Adresse introuvable.' using errcode = 'LG002'; end if;
    if v_def then update logistics.customer_address set is_default = false where customer_id = v_c and is_default and id <> v_id; end if;
    update logistics.customer_address set label = btrim(coalesce(p_label, '')), recipient_name = btrim(coalesce(p_recipient_name, '')), phone = btrim(coalesce(p_phone, '')), country = p_country,
           region = btrim(coalesce(p_region, '')), city = btrim(coalesce(p_city, '')), address = btrim(p_address), instructions = btrim(coalesce(p_instructions, '')),
           is_default = v_def or (is_default and p_default is null) where id = v_id;
    perform logistics.cust_audit(v_c, 'address.update', 'customer_address', v_id::text, jsonb_build_object('country', v_before ->> 'country', 'city', v_before ->> 'city'),
                                 jsonb_build_object('country', p_country, 'city', p_city), v_corr);
  end if;
  return jsonb_build_object('address_id', v_id, 'is_default', (select is_default from logistics.customer_address where id = v_id));
end;
$$;

create or replace function logistics.delete_address(p_user uuid, p_id uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid := logistics.require_customer(p_user); v_was boolean; v_corr uuid := gen_random_uuid(); v_next uuid;
begin
  select a.is_default into v_was from logistics.customer_address a where a.id = p_id and a.customer_id = v_c and a.active for update;
  if not found then raise exception 'Adresse introuvable.' using errcode = 'LG002'; end if;
  update logistics.customer_address set active = false, is_default = false where id = p_id;
  if v_was then
    select a.id into v_next from logistics.customer_address a where a.customer_id = v_c and a.active order by a.created_at desc, a.id limit 1;
    if v_next is not null then update logistics.customer_address set is_default = true where id = v_next; end if;
  end if;
  perform logistics.cust_audit(v_c, 'address.delete', 'customer_address', p_id::text, null, null, v_corr);
  return jsonb_build_object('address_id', p_id, 'deleted', true);
end;
$$;

-- Une adresse de demande : soit une adresse enregistrée du client, soit une adresse saisie ; jamais celle d'un autre client.
create or replace function logistics.resolve_address(p_customer uuid, p_address_id uuid, p_address text, p_city text, p_country text)
returns jsonb language plpgsql stable set search_path = '' as $$
declare a logistics.customer_address;
begin
  if p_address_id is not null then
    select * into a from logistics.customer_address x where x.id = p_address_id and x.customer_id = p_customer and x.active;
    if not found then raise exception 'Adresse introuvable.' using errcode = 'LG002'; end if;
    return jsonb_build_object('address_id', a.id, 'address', a.address, 'city', a.city, 'country', a.country, 'recipient_name', a.recipient_name, 'phone', a.phone);
  end if;
  if btrim(coalesce(p_address, '')) = '' then raise exception 'L''adresse est obligatoire.' using errcode = 'LG005'; end if;
  if char_length(p_address) > 200 or char_length(coalesce(p_city, '')) > 80 then raise exception 'Une partie de l''adresse est trop longue.' using errcode = 'LG005'; end if;
  if p_country is null or p_country not in ('HT', 'DO', 'US') then raise exception 'Pays inconnu (HT, DO ou US).' using errcode = 'LG005'; end if;
  return jsonb_build_object('address_id', null, 'address', btrim(p_address), 'city', btrim(coalesce(p_city, '')), 'country', p_country, 'recipient_name', '', 'phone', '');
end;
$$;


-- 8. Enlèvements et livraisons ---------------------------------------------------------------------------------------------------------------------
create or replace function logistics.pickup_stage(p_status text, p_task text)
returns text language sql immutable set search_path = '' as $$
  select case
    when p_status = 'REQUESTED' then 'requested' when p_status = 'REJECTED' then 'rejected' when p_status = 'CANCELLED' then 'cancelled'
    when p_task in ('COMPLETED') then 'completed' when p_task = 'STARTED' then 'on_the_way' when p_task = 'FAILED' then 'missed' when p_task = 'CANCELLED' then 'cancelled'
    else 'scheduled' end
$$;

create or replace function logistics.my_pickups(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user);
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return '[]'::jsonb; end if;
  return coalesce((select jsonb_agg(to_jsonb(x) - 'sort_key' order by x.sort_key desc, x.number) from (
    select r.id as pickup_id, r.number, 'REQUEST'::text as source, logistics.pickup_stage(r.status, t.status) as stage, r.status as request_status,
           r.address, r.city, r.country, coalesce(t.scheduled_date, r.preferred_date) as date, r.preferred_window as window, coalesce(t.parcels_expected, r.parcels_expected) as parcels_expected,
           r.notes, r.review_message as message, r.created_at, r.created_at as sort_key
      from logistics.pickup_request r left join logistics.task t on t.id = r.task_id where r.customer_id = v_c
    union all
    select t.id, 'PKT-' || upper(substr(replace(t.id::text, '-', ''), 1, 8)), 'STAFF', logistics.pickup_stage('APPROVED', t.status), null,
           t.address, '', '', t.scheduled_date, 'ANY', t.parcels_expected, '', null, t.created_at, t.created_at
      from logistics.task t where t.kind = 'PICKUP' and t.customer_id = v_c and not exists (select 1 from logistics.pickup_request r where r.task_id = t.id)) x), '[]'::jsonb);
end;
$$;

create or replace function logistics.request_pickup(p_user uuid, p_preferred_date date, p_parcels_expected int, p_address_id uuid, p_address text, p_city text, p_country text,
                                                     p_window text, p_notes text, p_contact_name text, p_contact_phone text, p_idempotency_key text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_c logistics.customer; v_cid uuid := logistics.require_customer(p_user); v_corr uuid := gen_random_uuid(); v_id uuid := gen_random_uuid(); v_addr jsonb; v_num text; v_key text;
  v_prior jsonb; v_hash text; v_res jsonb; v_win text := coalesce(nullif(btrim(p_window), ''), 'ANY');
begin
  select * into v_c from logistics.customer where id = v_cid;
  v_key := case when p_idempotency_key is null then null else v_cid::text || ':' || p_idempotency_key end;
  v_hash := md5(concat_ws('|', p_preferred_date, p_parcels_expected, p_address_id, p_address, p_city, p_country, p_window, p_notes, p_contact_name, p_contact_phone));
  v_prior := logistics.idem_begin(v_key, 'request_pickup', v_hash, v_cid::text);
  if v_prior is not null then return v_prior; end if;
  if p_preferred_date is null or p_preferred_date < current_date or p_preferred_date > current_date + 60 then raise exception 'La date souhaitée doit être comprise entre aujourd''hui et dans 60 jours.' using errcode = 'LG005'; end if;
  if v_win not in ('MORNING', 'AFTERNOON', 'ANY') then raise exception 'Créneau inconnu.' using errcode = 'LG005'; end if;
  if p_parcels_expected is null or p_parcels_expected < 1 or p_parcels_expected > 100 then raise exception 'Le nombre de colis doit être compris entre 1 et 100.' using errcode = 'LG005'; end if;
  if char_length(coalesce(p_notes, '')) > 500 or char_length(coalesce(p_contact_name, '')) > 120 or char_length(coalesce(p_contact_phone, '')) > 40 then raise exception 'Un texte est trop long.' using errcode = 'LG005'; end if;
  perform 1 from logistics.customer where id = v_cid for update;
  if (select count(*) from logistics.pickup_request r where r.customer_id = v_cid and r.status = 'REQUESTED') >= 5 then
    raise exception 'Vous avez déjà 5 demandes d''enlèvement en attente : attendez leur traitement ou annulez-en une.' using errcode = 'LG005';
  end if;
  v_addr := logistics.resolve_address(v_cid, p_address_id, p_address, p_city, p_country);
  v_num := logistics.next_number('pickup_request', 'PKR');
  insert into logistics.pickup_request (id, number, customer_id, address_id, country, city, address, contact_name, contact_phone, preferred_date, preferred_window, parcels_expected, notes, correlation_id)
  values (v_id, v_num, v_cid, (v_addr ->> 'address_id')::uuid, v_addr ->> 'country', v_addr ->> 'city', v_addr ->> 'address',
          btrim(coalesce(p_contact_name, nullif(v_addr ->> 'recipient_name', ''), v_c.full_name)), btrim(coalesce(p_contact_phone, nullif(v_addr ->> 'phone', ''), v_c.phone)),
          p_preferred_date, v_win, p_parcels_expected, btrim(coalesce(p_notes, '')), v_corr);
  perform logistics.cust_audit(v_cid, 'pickup_request.create', 'pickup_request', v_id::text, null, jsonb_build_object('number', v_num, 'date', p_preferred_date), v_corr);
  perform logistics.emit_customer('PickupRequestCreated', 'request', v_id::text, v_corr, v_cid, jsonb_build_object('request_id', v_id, 'number', v_num, 'preferred_date', p_preferred_date, 'parcels_expected', p_parcels_expected));
  v_res := jsonb_build_object('pickup_id', v_id, 'number', v_num, 'stage', 'requested', 'correlation_id', v_corr);
  return logistics.idem_end(v_key, v_res);
end;
$$;

create or replace function logistics.cancel_pickup_request(p_user uuid, p_id uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid := logistics.require_customer(p_user); r logistics.pickup_request; v_corr uuid := gen_random_uuid();
begin
  select * into r from logistics.pickup_request x where x.id = p_id and x.customer_id = v_c for update;
  if not found then raise exception 'Demande introuvable.' using errcode = 'LG002'; end if;
  if r.status <> 'REQUESTED' then raise exception 'Cette demande est déjà traitée (%) : écrivez au support pour la modifier.', r.status using errcode = 'LG004'; end if;
  update logistics.pickup_request set status = 'CANCELLED' where id = p_id;
  perform logistics.cust_audit(v_c, 'pickup_request.cancel', 'pickup_request', p_id::text, jsonb_build_object('status', 'REQUESTED'), jsonb_build_object('status', 'CANCELLED'), v_corr);
  perform logistics.emit_customer('PickupRequestCancelled', 'request', p_id::text, v_corr, v_c, jsonb_build_object('request_id', p_id, 'number', r.number));
  return jsonb_build_object('pickup_id', p_id, 'stage', 'cancelled');
end;
$$;

create or replace function logistics.delivery_stage(p_status text, p_task text)
returns text language sql immutable set search_path = '' as $$
  select case
    when p_status = 'REQUESTED' then 'requested' when p_status = 'REJECTED' then 'rejected' when p_status = 'CANCELLED' then 'cancelled'
    when p_task = 'COMPLETED' then 'delivered' when p_task = 'STARTED' then 'on_the_way' when p_task = 'FAILED' then 'missed' when p_task = 'CANCELLED' then 'cancelled'
    else 'scheduled' end
$$;

create or replace function logistics.my_deliveries(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user);
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return jsonb_build_object('requests', '[]'::jsonb, 'deliveries', '[]'::jsonb, 'at_hub', '[]'::jsonb); end if;
  return jsonb_build_object(
    'requests', coalesce((select jsonb_agg(jsonb_build_object('request_id', r.id, 'number', r.number, 'stage', logistics.delivery_stage(r.status, t.status), 'request_status', r.status,
                                                                'address', r.address, 'city', r.city, 'country', r.country, 'date', coalesce(t.scheduled_date, r.preferred_date), 'window', r.preferred_window,
                                                                'notes', r.notes, 'message', r.review_message, 'created_at', r.created_at,
                                                                'parcels', (select jsonb_agg(p.tracking_number order by p.tracking_number) from logistics.delivery_request_parcel rp join logistics.parcel p on p.id = rp.parcel_id where rp.request_id = r.id))
                                             order by r.created_at desc, r.number)
                            from logistics.delivery_request r left join logistics.task t on t.delivery_id = r.delivery_id and t.kind = 'DELIVERY' where r.customer_id = v_c), '[]'::jsonb),
    'deliveries', coalesce((select jsonb_agg(jsonb_build_object('delivery_id', d.id, 'stage', logistics.delivery_stage('APPROVED', t.status), 'address', d.address, 'date', t.scheduled_date,
                                                                  'window_start', t.window_start, 'window_end', t.window_end, 'otp_required', d.otp_required, 'otp_issued', d.otp_hash is not null,
                                                                  'failure', t.failed_reason,
                                                                  'parcels', (select jsonb_agg(p.tracking_number order by p.tracking_number) from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = d.id),
                                                                  'proof', (select jsonb_build_object('recipient_name', pod.recipient_name, 'delivered_at', pod.delivered_at) from logistics.proof_of_delivery pod where pod.task_id = t.id))
                                           order by t.scheduled_date desc, d.id)
                              from logistics.delivery d join logistics.task t on t.delivery_id = d.id and t.kind = 'DELIVERY' where d.customer_id = v_c), '[]'::jsonb),
    -- Les colis que le client peut demander à se faire livrer : au hub, et pas déjà dans une demande ou une livraison en cours.
    'at_hub', coalesce((select jsonb_agg(jsonb_build_object('tracking_number', p.tracking_number, 'description', p.description) order by p.tracking_number)
                          from logistics.parcel p where p.customer_id = v_c and p.status = 'AT_DESTINATION_HUB'
                           and not exists (select 1 from logistics.delivery_request_parcel rp join logistics.delivery_request r on r.id = rp.request_id where rp.parcel_id = p.id and r.status in ('REQUESTED', 'APPROVED')
                                              and (r.delivery_id is null or exists (select 1 from logistics.task t where t.delivery_id = r.delivery_id and t.status not in ('COMPLETED', 'CANCELLED', 'FAILED'))))
                           and not exists (select 1 from logistics.delivery_parcel dp join logistics.task t on t.delivery_id = dp.delivery_id and t.kind = 'DELIVERY' where dp.parcel_id = p.id and t.status not in ('COMPLETED', 'CANCELLED', 'FAILED'))), '[]'::jsonb));
end;
$$;

create or replace function logistics.request_delivery(p_user uuid, p_tracking_numbers text[], p_preferred_date date, p_address_id uuid, p_address text, p_city text, p_country text,
                                                       p_window text, p_notes text, p_contact_name text, p_contact_phone text, p_idempotency_key text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_c logistics.customer; v_cid uuid := logistics.require_customer(p_user); v_corr uuid := gen_random_uuid(); v_id uuid := gen_random_uuid(); v_addr jsonb; v_num text; v_key text;
  v_prior jsonb; v_hash text; v_res jsonb; v_win text := coalesce(nullif(btrim(p_window), ''), 'ANY'); v_t text; v_p logistics.parcel; v_seen uuid[] := '{}'; v_tracks text[];
begin
  select * into v_c from logistics.customer where id = v_cid;
  v_key := case when p_idempotency_key is null then null else v_cid::text || ':' || p_idempotency_key end;
  v_hash := md5(concat_ws('|', array_to_string(p_tracking_numbers, ','), p_preferred_date, p_address_id, p_address, p_city, p_country, p_window, p_notes, p_contact_name, p_contact_phone));
  v_prior := logistics.idem_begin(v_key, 'request_delivery', v_hash, v_cid::text);
  if v_prior is not null then return v_prior; end if;
  if coalesce(cardinality(p_tracking_numbers), 0) = 0 then raise exception 'Choisissez au moins un colis.' using errcode = 'LG005'; end if;
  if cardinality(p_tracking_numbers) > 50 then raise exception 'Au plus 50 colis par demande.' using errcode = 'LG005'; end if;
  if p_preferred_date is null or p_preferred_date < current_date or p_preferred_date > current_date + 60 then raise exception 'La date souhaitée doit être comprise entre aujourd''hui et dans 60 jours.' using errcode = 'LG005'; end if;
  if v_win not in ('MORNING', 'AFTERNOON', 'ANY') then raise exception 'Créneau inconnu.' using errcode = 'LG005'; end if;
  if char_length(coalesce(p_notes, '')) > 500 or char_length(coalesce(p_contact_name, '')) > 120 or char_length(coalesce(p_contact_phone, '')) > 40 then raise exception 'Un texte est trop long.' using errcode = 'LG005'; end if;
  perform 1 from logistics.customer where id = v_cid for update;
  if (select count(*) from logistics.delivery_request r where r.customer_id = v_cid and r.status = 'REQUESTED') >= 5 then
    raise exception 'Vous avez déjà 5 demandes de livraison en attente : attendez leur traitement ou annulez-en une.' using errcode = 'LG005';
  end if;
  v_addr := logistics.resolve_address(v_cid, p_address_id, p_address, p_city, p_country);
  select array_agg(distinct upper(btrim(x))) into v_tracks from unnest(p_tracking_numbers) x;
  foreach v_t in array v_tracks loop
    -- Un numéro qui n'est pas au client répond comme un numéro qui n'existe pas.
    select * into v_p from logistics.parcel p where p.tracking_number = v_t and p.customer_id = v_cid for update;
    if not found then raise exception 'Colis introuvable : %.', v_t using errcode = 'LG002'; end if;
    if v_p.status <> 'AT_DESTINATION_HUB' then raise exception 'Le colis % n''est pas au hub : seul un colis au hub peut être livré.', v_t using errcode = 'LG005'; end if;
    if exists (select 1 from logistics.delivery_request_parcel rp join logistics.delivery_request r on r.id = rp.request_id
                where rp.parcel_id = v_p.id and r.status in ('REQUESTED', 'APPROVED') and (r.delivery_id is null or exists (select 1 from logistics.task t where t.delivery_id = r.delivery_id and t.status not in ('COMPLETED', 'CANCELLED', 'FAILED'))))
       or exists (select 1 from logistics.delivery_parcel dp join logistics.task t on t.delivery_id = dp.delivery_id and t.kind = 'DELIVERY' where dp.parcel_id = v_p.id and t.status not in ('COMPLETED', 'CANCELLED', 'FAILED')) then
      raise exception 'Le colis % est déjà dans une demande ou une livraison en cours.', v_t using errcode = 'LG005';
    end if;
    v_seen := v_seen || v_p.id;
  end loop;
  v_num := logistics.next_number('delivery_request', 'DLR');
  insert into logistics.delivery_request (id, number, customer_id, address_id, country, city, address, contact_name, contact_phone, preferred_date, preferred_window, notes, correlation_id)
  values (v_id, v_num, v_cid, (v_addr ->> 'address_id')::uuid, v_addr ->> 'country', v_addr ->> 'city', v_addr ->> 'address',
          btrim(coalesce(p_contact_name, nullif(v_addr ->> 'recipient_name', ''), v_c.full_name)), btrim(coalesce(p_contact_phone, nullif(v_addr ->> 'phone', ''), v_c.phone)),
          p_preferred_date, v_win, btrim(coalesce(p_notes, '')), v_corr);
  insert into logistics.delivery_request_parcel (request_id, parcel_id) select v_id, unnest(v_seen);
  perform logistics.cust_audit(v_cid, 'delivery_request.create', 'delivery_request', v_id::text, null, jsonb_build_object('number', v_num, 'parcels', cardinality(v_seen)), v_corr);
  perform logistics.emit_customer('DeliveryRequestCreated', 'request', v_id::text, v_corr, v_cid, jsonb_build_object('request_id', v_id, 'number', v_num, 'parcels', cardinality(v_seen), 'preferred_date', p_preferred_date));
  v_res := jsonb_build_object('request_id', v_id, 'number', v_num, 'stage', 'requested', 'parcels', cardinality(v_seen), 'correlation_id', v_corr);
  return logistics.idem_end(v_key, v_res);
end;
$$;

create or replace function logistics.cancel_delivery_request(p_user uuid, p_id uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid := logistics.require_customer(p_user); r logistics.delivery_request; v_corr uuid := gen_random_uuid();
begin
  select * into r from logistics.delivery_request x where x.id = p_id and x.customer_id = v_c for update;
  if not found then raise exception 'Demande introuvable.' using errcode = 'LG002'; end if;
  if r.status <> 'REQUESTED' then raise exception 'Cette demande est déjà traitée (%) : écrivez au support pour la modifier.', r.status using errcode = 'LG004'; end if;
  update logistics.delivery_request set status = 'CANCELLED' where id = p_id;
  perform logistics.cust_audit(v_c, 'delivery_request.cancel', 'delivery_request', p_id::text, jsonb_build_object('status', 'REQUESTED'), jsonb_build_object('status', 'CANCELLED'), v_corr);
  perform logistics.emit_customer('DeliveryRequestCancelled', 'request', p_id::text, v_corr, v_c, jsonb_build_object('request_id', p_id, 'number', r.number));
  return jsonb_build_object('request_id', p_id, 'stage', 'cancelled');
end;
$$;


-- 9. Notifications --------------------------------------------------------------------------------------------------------------------------------------
create or replace function logistics.my_notifications(p_user uuid, p_unread_only boolean default false, p_limit int default 50)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user); v_lim int := least(greatest(coalesce(p_limit, 50), 1), 200);
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return jsonb_build_object('unread', 0, 'items', '[]'::jsonb); end if;
  return jsonb_build_object(
    'unread', (select count(*) from logistics.notification n where n.customer_id = v_c and n.channel = 'in_app' and n.read_at is null),
    'items', coalesce((select jsonb_agg(jsonb_build_object('id', x.id, 'template', x.template, 'created_at', x.created_at, 'read_at', x.read_at,
                           -- Une liste blanche : une clé interne ajoutée plus tard à la charge utile ne fuit jamais vers le client.
                           'payload', coalesce((select jsonb_object_agg(e.key, e.value) from jsonb_each(x.payload) e
                                                  where e.key in ('tracking_number', 'status', 'stage', 'invoice_number', 'amount', 'currency', 'shipment_code', 'code', 'expires_hours', 'message', 'date')), '{}'::jsonb))
                                          order by x.created_at desc, x.id desc)
                         from (select n.* from logistics.notification n where n.customer_id = v_c and n.channel = 'in_app' and (not coalesce(p_unread_only, false) or n.read_at is null)
                                order by n.created_at desc, n.id desc limit v_lim) x), '[]'::jsonb));
end;
$$;

create or replace function logistics.mark_notifications_read(p_user uuid, p_ids bigint[] default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid := logistics.require_customer(p_user); v_n int;
begin
  update logistics.notification n set read_at = now()
   where n.customer_id = v_c and n.channel = 'in_app' and n.read_at is null and (p_ids is null or n.id = any (p_ids));
  get diagnostics v_n = row_count;
  return jsonb_build_object('marked', v_n);
end;
$$;


-- 10. Support ---------------------------------------------------------------------------------------------------------------------------------------------
create or replace function logistics.my_tickets(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user);
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return '[]'::jsonb; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('ticket_id', t.id, 'number', t.number, 'subject', t.subject, 'category', t.category, 'status', t.status, 'created_at', t.created_at,
                                                       'updated_at', t.updated_at, 'messages', (select count(*) from logistics.support_message m where m.ticket_id = t.id),
                                                       'last_author', (select m.author_kind from logistics.support_message m where m.ticket_id = t.id order by m.id desc limit 1))
                                    order by t.updated_at desc, t.number)
                     from logistics.support_ticket t where t.customer_id = v_c), '[]'::jsonb);
end;
$$;

create or replace function logistics.my_ticket(p_user uuid, p_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user); t logistics.support_ticket;
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  select * into t from logistics.support_ticket x where x.id = p_id and x.customer_id = v_c;
  if not found then raise exception 'Ticket introuvable.' using errcode = 'LG002'; end if;
  return jsonb_build_object('ticket_id', t.id, 'number', t.number, 'subject', t.subject, 'category', t.category, 'status', t.status, 'created_at', t.created_at, 'closed_at', t.closed_at,
    'parcel', (select p.tracking_number from logistics.parcel p where p.id = t.parcel_id), 'invoice', (select i.number from logistics.invoice i where i.id = t.invoice_id),
    -- Le client voit « vous » ou « l'équipe » : jamais le nom ni le compte du membre du personnel.
    'messages', coalesce((select jsonb_agg(jsonb_build_object('author', m.author_kind, 'body', m.body, 'at', m.created_at) order by m.id)
                            from logistics.support_message m where m.ticket_id = t.id), '[]'::jsonb));
end;
$$;

create or replace function logistics.open_ticket(p_user uuid, p_subject text, p_category text, p_body text, p_tracking text, p_invoice_number text, p_idempotency_key text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid := logistics.require_customer(p_user); v_corr uuid := gen_random_uuid(); v_id uuid := gen_random_uuid(); v_num text; v_pid uuid; v_iid uuid; v_key text;
        v_prior jsonb; v_hash text; v_res jsonb;
begin
  v_key := case when p_idempotency_key is null then null else v_c::text || ':' || p_idempotency_key end;
  v_hash := md5(concat_ws('|', p_subject, p_category, p_body, p_tracking, p_invoice_number));
  v_prior := logistics.idem_begin(v_key, 'open_ticket', v_hash, v_c::text);
  if v_prior is not null then return v_prior; end if;
  if char_length(btrim(coalesce(p_subject, ''))) not between 3 and 120 then raise exception 'Le sujet doit compter de 3 à 120 caractères.' using errcode = 'LG005'; end if;
  if char_length(btrim(coalesce(p_body, ''))) not between 1 and 4000 then raise exception 'Le message doit compter de 1 à 4000 caractères.' using errcode = 'LG005'; end if;
  if p_category is null or p_category not in ('PARCEL', 'INVOICE', 'PICKUP', 'DELIVERY', 'ACCOUNT', 'OTHER') then raise exception 'Catégorie inconnue.' using errcode = 'LG005'; end if;
  perform 1 from logistics.customer where id = v_c for update;
  if (select count(*) from logistics.support_ticket t where t.customer_id = v_c and t.status <> 'CLOSED') >= 10 then raise exception 'Vous avez déjà 10 tickets ouverts : attendez nos réponses ou fermez-en.' using errcode = 'LG005'; end if;
  if (select count(*) from logistics.support_ticket t where t.customer_id = v_c and t.created_at > now() - interval '24 hours') >= 5 then raise exception 'Trop de tickets en 24 heures : réessayez demain, ou écrivez-nous sur WhatsApp.' using errcode = 'LG005'; end if;
  if nullif(btrim(coalesce(p_tracking, '')), '') is not null then
    select p.id into v_pid from logistics.parcel p where p.customer_id = v_c and p.tracking_number = upper(btrim(p_tracking));
    if v_pid is null then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  end if;
  if nullif(btrim(coalesce(p_invoice_number, '')), '') is not null then
    select i.id into v_iid from logistics.invoice i where i.customer_id = v_c and i.number = btrim(p_invoice_number) and i.status <> 'DRAFT';
    if v_iid is null then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  end if;
  v_num := logistics.next_number('support_ticket', 'SUP');
  insert into logistics.support_ticket (id, number, customer_id, subject, category, parcel_id, invoice_id) values (v_id, v_num, v_c, btrim(p_subject), p_category, v_pid, v_iid);
  insert into logistics.support_message (ticket_id, author_kind, body) values (v_id, 'CUSTOMER', btrim(p_body));
  perform logistics.cust_audit(v_c, 'ticket.open', 'support_ticket', v_id::text, null, jsonb_build_object('number', v_num, 'category', p_category), v_corr);
  perform logistics.emit_customer('SupportTicketOpened', 'ticket', v_id::text, v_corr, v_c, jsonb_build_object('ticket_id', v_id, 'number', v_num, 'category', p_category));
  v_res := jsonb_build_object('ticket_id', v_id, 'number', v_num, 'status', 'OPEN', 'correlation_id', v_corr);
  return logistics.idem_end(v_key, v_res);
end;
$$;

create or replace function logistics.reply_ticket(p_user uuid, p_id uuid, p_body text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid := logistics.require_customer(p_user); t logistics.support_ticket; v_corr uuid := gen_random_uuid();
begin
  if char_length(btrim(coalesce(p_body, ''))) not between 1 and 4000 then raise exception 'Le message doit compter de 1 à 4000 caractères.' using errcode = 'LG005'; end if;
  select * into t from logistics.support_ticket x where x.id = p_id and x.customer_id = v_c for update;
  if not found then raise exception 'Ticket introuvable.' using errcode = 'LG002'; end if;
  if t.status = 'CLOSED' then raise exception 'Ce ticket est fermé : ouvrez-en un nouveau.' using errcode = 'LG004'; end if;
  if (select count(*) from logistics.support_message m where m.ticket_id = p_id) >= 100 then raise exception 'Ce ticket a atteint 100 messages : ouvrez-en un nouveau.' using errcode = 'LG005'; end if;
  insert into logistics.support_message (ticket_id, author_kind, body) values (p_id, 'CUSTOMER', btrim(p_body));
  update logistics.support_ticket set status = 'OPEN' where id = p_id;
  perform logistics.emit_customer('SupportTicketReplied', 'ticket', p_id::text, v_corr, v_c, jsonb_build_object('ticket_id', p_id, 'number', t.number, 'author', 'CUSTOMER'));
  return jsonb_build_object('ticket_id', p_id, 'status', 'OPEN');
end;
$$;

create or replace function logistics.close_my_ticket(p_user uuid, p_id uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid := logistics.require_customer(p_user); t logistics.support_ticket; v_corr uuid := gen_random_uuid();
begin
  select * into t from logistics.support_ticket x where x.id = p_id and x.customer_id = v_c for update;
  if not found then raise exception 'Ticket introuvable.' using errcode = 'LG002'; end if;
  if t.status = 'CLOSED' then raise exception 'Ce ticket est déjà fermé.' using errcode = 'LG004'; end if;
  update logistics.support_ticket set status = 'CLOSED', closed_at = now() where id = p_id;
  perform logistics.emit_customer('SupportTicketClosed', 'ticket', p_id::text, v_corr, v_c, jsonb_build_object('ticket_id', p_id, 'number', t.number, 'by', 'CUSTOMER'));
  return jsonb_build_object('ticket_id', p_id, 'status', 'CLOSED');
end;
$$;


-- 11. Façade : l'acteur est TOUJOURS auth.uid() ----------------------------------------------------------------------------------------------------
create or replace function public.lg_my_dashboard() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_dashboard(auth.uid()) $$;
create or replace function public.lg_my_parcels(p_stage text default null, p_search text default null, p_limit int default 50, p_offset int default 0)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_parcels(auth.uid(), p_stage, p_search, p_limit, p_offset) $$;
create or replace function public.lg_my_parcel(p_tracking text) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_parcel(auth.uid(), p_tracking) $$;
create or replace function public.lg_my_shipments() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_shipments(auth.uid()) $$;
create or replace function public.lg_my_consolidations() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_consolidations(auth.uid()) $$;
create or replace function public.lg_my_payments() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_payments(auth.uid()) $$;
create or replace function public.lg_my_documents() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_documents(auth.uid()) $$;
create or replace function public.lg_my_addresses() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_addresses(auth.uid()) $$;
create or replace function public.lg_save_address(p_country text, p_address text, p_id uuid default null, p_label text default '', p_recipient_name text default '', p_phone text default '',
  p_region text default '', p_city text default '', p_instructions text default '', p_default boolean default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.save_address(auth.uid(), p_id, p_label, p_recipient_name, p_phone, p_country, p_region, p_city, p_address, p_instructions, p_default) $$;
create or replace function public.lg_delete_address(p_id uuid) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.delete_address(auth.uid(), p_id) $$;
create or replace function public.lg_my_pickups() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_pickups(auth.uid()) $$;
create or replace function public.lg_request_pickup(p_preferred_date date, p_parcels_expected int default 1, p_address_id uuid default null, p_address text default null, p_city text default null,
  p_country text default null, p_window text default 'ANY', p_notes text default '', p_contact_name text default null, p_contact_phone text default null, p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.request_pickup(auth.uid(), p_preferred_date, p_parcels_expected, p_address_id, p_address, p_city, p_country, p_window, p_notes, p_contact_name, p_contact_phone, p_idempotency_key) $$;
create or replace function public.lg_cancel_pickup_request(p_id uuid) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cancel_pickup_request(auth.uid(), p_id) $$;
create or replace function public.lg_my_deliveries() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_deliveries(auth.uid()) $$;
create or replace function public.lg_request_delivery(p_tracking_numbers text[], p_preferred_date date, p_address_id uuid default null, p_address text default null, p_city text default null,
  p_country text default null, p_window text default 'ANY', p_notes text default '', p_contact_name text default null, p_contact_phone text default null, p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.request_delivery(auth.uid(), p_tracking_numbers, p_preferred_date, p_address_id, p_address, p_city, p_country, p_window, p_notes, p_contact_name, p_contact_phone, p_idempotency_key) $$;
create or replace function public.lg_cancel_delivery_request(p_id uuid) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cancel_delivery_request(auth.uid(), p_id) $$;
create or replace function public.lg_my_notifications(p_unread_only boolean default false, p_limit int default 50) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_notifications(auth.uid(), p_unread_only, p_limit) $$;
create or replace function public.lg_mark_notifications_read(p_ids bigint[] default null) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.mark_notifications_read(auth.uid(), p_ids) $$;
create or replace function public.lg_my_tickets() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_tickets(auth.uid()) $$;
create or replace function public.lg_my_ticket(p_id uuid) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_ticket(auth.uid(), p_id) $$;
create or replace function public.lg_open_ticket(p_subject text, p_category text, p_body text, p_tracking text default null, p_invoice_number text default null, p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.open_ticket(auth.uid(), p_subject, p_category, p_body, p_tracking, p_invoice_number, p_idempotency_key) $$;
create or replace function public.lg_reply_ticket(p_id uuid, p_body text) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.reply_ticket(auth.uid(), p_id, p_body) $$;
create or replace function public.lg_close_my_ticket(p_id uuid) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.close_my_ticket(auth.uid(), p_id) $$;


-- 12. Tout fermé, sauf la façade --------------------------------------------------------------------------------------------------------------------------
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
revoke all on logistics.event_health, logistics.pickup_task, logistics.delivery_task, logistics.customer_balance from public, anon, authenticated;
grant select on logistics.event_health to service_role;

-- Pour retirer SEULEMENT cette étape : supprimer les fonctions public.lg_my_*, lg_save_address, lg_delete_address, lg_request_*, lg_cancel_*_request,
-- lg_mark_notifications_read, lg_open_ticket, lg_reply_ticket, lg_close_my_ticket, puis
--   drop table if exists logistics.support_message, logistics.support_ticket, logistics.delivery_request_parcel, logistics.delivery_request,
--        logistics.pickup_request, logistics.customer_address cascade;
--   alter table logistics.notification drop column if exists read_at;  alter table logistics.event_type drop column if exists customer_visible;
-- Aucune donnée de l'ancien schéma n'est en jeu.
