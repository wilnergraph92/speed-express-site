-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 3 : machine d'états et événements
-- -----------------------------------------------------------------------------
-- Phase 6. À coller dans Supabase > SQL Editor APRÈS 001 et 002, après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site ».
--
-- Ce que fait ce script :
--   · la MACHINE D'ÉTATS du colis, pilotée par des données (table parcel_transition) :
--     un statut ne change JAMAIS arbitrairement, seulement par logistics.transition_parcel() ;
--   · chaque transition est autorisée, validée, et produit, dans la MÊME transaction :
--     un événement de suivi, une trace d'audit et un événement de domaine (boîte d'envoi) ;
--   · le MOTEUR D'ÉVÉNEMENTS interne : persistance, idempotence, corrélation, relances
--     avec attente croissante, file des échecs (dead-letter), abonnés internes et externes ;
--   · UNE fonction publique, public.lg_transition_parcel (façade, ADR 0002), réservée au personnel.
--
-- Ce qu'il NE fait PAS : il ne modifie aucune ancienne table, ne change aucun statut existant,
-- et n'est appelé par aucune page ni application. Tant que l'étape 4 de MIGRATION-STRATEGY.md
-- n'est pas décidée, N'UTILISEZ PAS transition_parcel sur les colis réels : l'ancien tableau de
-- bord écrit encore l'ancien statut.
--
-- Retour arrière : drop function public.lg_transition_parcel(uuid, text, text, uuid, uuid, uuid, text, text, jsonb);
--                  puis drop schema logistics cascade;  (ou, pour ne retirer que cette étape, voir le bas du fichier)
-- Rejouable sans risque : « si absent » / « create or replace » partout, aucune suppression de donnée.
-- =============================================================================

-- 1. Catalogue des types d'événements ----------------------------------------------------------------
create table if not exists logistics.event_type (
  code           text primary key,
  aggregate_type text not null check (aggregate_type in ('parcel', 'shipment', 'delivery', 'incident', 'invoice', 'customs')),
  description    text not null default ''
);
comment on table logistics.event_type is 'Registre fermé : un événement d''un type inconnu est refusé.';

insert into logistics.event_type (code, aggregate_type, description) values
  ('ParcelCreated',              'parcel',   'Colis enregistré'),
  ('ParcelReceived',             'parcel',   'Colis reçu à l''entrepôt'),
  ('ParcelVerified',             'parcel',   'Colis vérifié (poids, dimensions, état)'),
  ('ParcelStored',               'parcel',   'Colis rangé à un emplacement'),
  ('ParcelConsolidationPending', 'parcel',   'Colis en attente de consolidation'),
  ('ParcelConsolidated',         'parcel',   'Colis ajouté à une consolidation fermée'),
  ('ParcelReadyForExport',       'parcel',   'Colis prêt pour l''export'),
  ('ParcelInTransit',            'parcel',   'Colis en transit (son expédition est partie)'),
  ('ParcelArrived',              'parcel',   'Colis arrivé à destination'),
  ('CustomsStarted',             'parcel',   'Dédouanement commencé'),
  ('CustomsCleared',             'parcel',   'Dédouanement terminé'),
  ('ParcelAtDestinationHub',     'parcel',   'Colis au hub de destination'),
  ('DeliveryAssigned',           'parcel',   'Colis affecté à une livraison'),
  ('OutForDelivery',             'parcel',   'Colis en cours de livraison'),
  ('Delivered',                  'parcel',   'Colis livré'),
  ('ParcelOnHold',               'parcel',   'Colis mis en attente'),
  ('ParcelResumed',              'parcel',   'Colis repris après attente'),
  ('ParcelCancelled',            'parcel',   'Colis annulé'),
  ('ParcelDamaged',              'parcel',   'Colis endommagé'),
  ('ParcelLost',                 'parcel',   'Colis perdu'),
  ('ParcelReturned',             'parcel',   'Colis retourné à l''expéditeur'),
  ('ShipmentCreated',            'shipment', 'Expédition créée (phase 8)'),
  ('ShipmentDispatched',         'shipment', 'Expédition partie (phase 8)'),
  ('ShipmentArrived',            'shipment', 'Expédition arrivée (phase 8)'),
  ('ProofOfDeliveryCreated',     'delivery', 'Preuve de livraison enregistrée (phase 9)'),
  ('IncidentCreated',            'incident', 'Incident déclaré (phases 7 et 9)')
on conflict (code) do nothing;


-- 2. Les transitions autorisées : la machine d'états, en données -----------------------------------------
create table if not exists logistics.parcel_transition (
  from_status        text not null references logistics.parcel_status (code),
  to_status          text not null references logistics.parcel_status (code),
  event_type         text not null references logistics.event_type (code),
  required_right     text not null default 'colis.statut' check (required_right in ('colis.statut', 'direction')),
  requires_warehouse boolean not null default false,
  requires_location  boolean not null default false,
  requires_reason    boolean not null default false,
  requires_customer  boolean not null default false,
  allow_system       boolean not null default false,
  resume             boolean not null default false,
  primary key (from_status, to_status),
  check (from_status <> to_status)
);
comment on table logistics.parcel_transition is
  'Tout ce qui n''est pas ici est INTERDIT. required_right : colis.statut = un employé qui a ce droit suffit ; direction = gérant ou administrateur. allow_system : un événement interne (expédition, douane) peut la demander sans personne derrière.';

do $$
declare
  flux text[] := array['CREATED', 'RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT',
                       'IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB',
                       'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY'];
  apres_reception text[];
  s text;
begin
  apres_reception := flux[2:14];
  -- Le flux nominal, un pas à la fois.
  insert into logistics.parcel_transition (from_status, to_status, event_type, requires_warehouse, requires_location, requires_customer, allow_system) values
    ('CREATED',               'RECEIVED',              'ParcelReceived',             true,  false, false, false),
    ('RECEIVED',              'VERIFIED',              'ParcelVerified',             true,  false, false, false),
    ('VERIFIED',              'STORED',                'ParcelStored',               false, true,  false, false),
    ('STORED',                'CONSOLIDATION_PENDING', 'ParcelConsolidationPending', false, false, true,  false),
    ('CONSOLIDATION_PENDING', 'CONSOLIDATED',          'ParcelConsolidated',         false, false, true,  true),
    ('CONSOLIDATED',          'READY_FOR_EXPORT',      'ParcelReadyForExport',       false, false, true,  true),
    ('READY_FOR_EXPORT',      'IN_TRANSIT',            'ParcelInTransit',            false, false, true,  true),
    ('IN_TRANSIT',            'ARRIVED',               'ParcelArrived',              false, false, true,  true),
    ('ARRIVED',               'CUSTOMS_PROCESSING',    'CustomsStarted',             false, false, true,  true),
    ('CUSTOMS_PROCESSING',    'CUSTOMS_CLEARED',       'CustomsCleared',             false, false, true,  true),
    ('CUSTOMS_CLEARED',       'AT_DESTINATION_HUB',    'ParcelAtDestinationHub',     false, false, true,  true),
    ('AT_DESTINATION_HUB',    'DELIVERY_ASSIGNED',     'DeliveryAssigned',           false, false, true,  true),
    ('DELIVERY_ASSIGNED',     'OUT_FOR_DELIVERY',      'OutForDelivery',             false, false, true,  false),
    ('OUT_FOR_DELIVERY',      'DELIVERED',             'Delivered',                  false, false, true,  false)
  on conflict do nothing;

  -- Retours en arrière légitimes (sortir un colis d'une consolidation) : deux, pas plus.
  insert into logistics.parcel_transition (from_status, to_status, event_type, requires_customer) values
    ('CONSOLIDATED',          'CONSOLIDATION_PENDING', 'ParcelConsolidationPending', true),
    ('CONSOLIDATION_PENDING', 'STORED',                'ParcelStored',               false)
  on conflict do nothing;
  update logistics.parcel_transition set requires_location = true where from_status = 'CONSOLIDATION_PENDING' and to_status = 'STORED';

  -- Exceptions. Tout opérateur peut SIGNALER (attente, dommage) ; la direction DÉCIDE (reprise, annulation, perte, retour).
  foreach s in array flux loop
    insert into logistics.parcel_transition (from_status, to_status, event_type, requires_reason)
      values (s, 'ON_HOLD', 'ParcelOnHold', true) on conflict do nothing;                          -- mise en attente
    insert into logistics.parcel_transition (from_status, to_status, event_type, required_right, resume)
      values ('ON_HOLD', s, 'ParcelResumed', 'direction', true) on conflict do nothing;            -- reprise (vers le statut d'avant)
  end loop;
  foreach s in array apres_reception loop
    insert into logistics.parcel_transition (from_status, to_status, event_type, requires_reason)
      values (s, 'DAMAGED', 'ParcelDamaged', true) on conflict do nothing;
    insert into logistics.parcel_transition (from_status, to_status, event_type, required_right, requires_reason)
      values (s, 'LOST', 'ParcelLost', 'direction', true) on conflict do nothing;
  end loop;
  foreach s in array array['ON_HOLD', 'DAMAGED'] loop
    insert into logistics.parcel_transition (from_status, to_status, event_type, required_right, requires_reason) values
      (s, 'LOST',      'ParcelLost',      'direction', true),
      (s, 'CANCELLED', 'ParcelCancelled', 'direction', true),
      (s, 'RETURNED',  'ParcelReturned',  'direction', true)
    on conflict do nothing;
  end loop;
  foreach s in array array['CREATED', 'RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING'] loop
    insert into logistics.parcel_transition (from_status, to_status, event_type, required_right, requires_reason)
      values (s, 'CANCELLED', 'ParcelCancelled', 'direction', true) on conflict do nothing;
  end loop;
  foreach s in array array['AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY'] loop
    insert into logistics.parcel_transition (from_status, to_status, event_type, required_right, requires_reason)
      values (s, 'RETURNED', 'ParcelReturned', 'direction', true) on conflict do nothing;
  end loop;
  insert into logistics.parcel_transition (from_status, to_status, event_type, required_right, requires_reason) values
    ('ON_HOLD', 'DAMAGED', 'ParcelDamaged', 'direction', true),
    ('DAMAGED', 'ON_HOLD', 'ParcelOnHold',  'direction', true)
  on conflict do nothing;
end
$$;


-- 3. Le moteur d'événements --------------------------------------------------------------------------
create table if not exists logistics.domain_event (
  id              bigint generated always as identity primary key,
  event_id        uuid not null unique default gen_random_uuid(),
  event_type      text not null references logistics.event_type (code),
  version         int not null default 1,
  aggregate_type  text not null,
  aggregate_id    text not null,
  occurred_at     timestamptz not null default now(),
  correlation_id  uuid not null,
  causation_id    uuid,
  idempotency_key text,
  actor_user_id   uuid references logistics.app_user (id) on delete restrict,
  actor_label     text not null default '',
  payload         jsonb not null default '{}'::jsonb
);
create index if not exists domain_event_aggregate_idx on logistics.domain_event (aggregate_type, aggregate_id, id);
create index if not exists domain_event_correlation_idx on logistics.domain_event (correlation_id);
comment on table logistics.domain_event is 'Boîte d''envoi (ADR 0003) : écrite dans la même transaction que le changement d''état ; en ajout seul.';

drop trigger if exists domain_event_append_only on logistics.domain_event;
create trigger domain_event_append_only
  before update or delete on logistics.domain_event
  for each row execute function logistics.forbid_mutation();

create table if not exists logistics.event_subscriber (
  code            text primary key,
  kind            text not null check (kind in ('internal', 'external')),
  event_types     text[] not null,
  handler         regproc,                         -- fonction SQL appelée pour un abonné « internal »
  active          boolean not null default true,
  max_attempts    int not null default 5 check (max_attempts > 0),
  backoff_seconds int not null default 30 check (backoff_seconds >= 0),
  check ((kind = 'internal') = (handler is not null))
);
comment on table logistics.event_subscriber is 'internal : une fonction SQL appelée par dispatch_events. external : un travailleur (Edge Function) qui réclame ses événements par claim_deliveries.';

create table if not exists logistics.event_delivery (
  id              bigint generated always as identity primary key,
  event_row_id    bigint not null references logistics.domain_event (id) on delete restrict,
  subscriber_code text not null references logistics.event_subscriber (code) on delete restrict,
  status          text not null default 'PENDING' check (status in ('PENDING', 'IN_PROGRESS', 'DELIVERED', 'FAILED', 'DEAD')),
  attempts        int not null default 0,
  next_attempt_at timestamptz not null default now(),
  locked_until    timestamptz,
  last_error      text,
  delivered_at    timestamptz,
  created_at      timestamptz not null default now(),
  unique (event_row_id, subscriber_code)           -- un abonné ne reçoit JAMAIS deux fois le même événement
);
create index if not exists event_delivery_due_idx on logistics.event_delivery (status, next_attempt_at);

create table if not exists logistics.dead_letter (
  id              bigint generated always as identity primary key,
  delivery_id     bigint not null references logistics.event_delivery (id) on delete restrict,
  event_row_id    bigint not null references logistics.domain_event (id) on delete restrict,
  subscriber_code text not null,
  error           text,
  failed_at       timestamptz not null default now(),
  resolved_at     timestamptz,
  resolution_note text
);
comment on table logistics.dead_letter is 'File des échecs : un événement que son abonné n''a pas su traiter après tous les essais. Jamais supprimé ; résolu à la main.';

create table if not exists logistics.command_log (
  idempotency_key text primary key,
  command         text not null,
  request_hash    text not null,
  entity_type     text not null,
  entity_id       text not null,
  result          jsonb,
  created_at      timestamptz not null default now()
);
comment on table logistics.command_log is 'Idempotence : rejouée avec la même clé, une commande renvoie son résultat d''origine sans rien refaire.';

create table if not exists logistics.notification (
  id           bigint generated always as identity primary key,
  customer_id  uuid not null references logistics.customer (id) on delete restrict,
  parcel_id    uuid references logistics.parcel (id) on delete restrict,
  event_row_id bigint references logistics.domain_event (id) on delete restrict,
  channel      text not null default 'push' check (channel in ('push', 'whatsapp', 'email')),
  template     text not null,
  payload      jsonb not null default '{}'::jsonb,
  status       text not null default 'PENDING' check (status in ('PENDING', 'SENT', 'FAILED', 'SKIPPED')),
  created_at   timestamptz not null default now(),
  sent_at      timestamptz,
  unique (event_row_id, channel)
);
comment on table logistics.notification is 'File d''envoi des notifications : planifiée par un abonné interne, envoyée par un travailleur externe. Un échec d''envoi ne touche jamais le colis.';

-- Fan-out à l'écriture, dans la même transaction : un événement qui existe a TOUJOURS ses livraisons.
create or replace function logistics.fan_out_event()
returns trigger language plpgsql set search_path = '' as $$
begin
  insert into logistics.event_delivery (event_row_id, subscriber_code)
  select new.id, s.code from logistics.event_subscriber s
  where s.active and new.event_type = any (s.event_types)
  on conflict do nothing;
  return null;
end;
$$;
drop trigger if exists fan_out_event on logistics.domain_event;
create trigger fan_out_event after insert on logistics.domain_event
  for each row execute function logistics.fan_out_event();

-- Échec d'une livraison : attente croissante (x2 à chaque essai), puis file des échecs.
create or replace function logistics.record_delivery_failure(p_delivery_id bigint, p_error text)
returns text language plpgsql set search_path = '' as $$
declare
  d logistics.event_delivery;
  s logistics.event_subscriber;
  v_status text;
begin
  select * into d from logistics.event_delivery where id = p_delivery_id for update;
  if not found then raise exception 'Livraison introuvable.' using errcode = 'LG002'; end if;
  select * into s from logistics.event_subscriber where code = d.subscriber_code;
  v_status := case when d.attempts >= s.max_attempts then 'DEAD' else 'FAILED' end;
  update logistics.event_delivery
     set status = v_status, last_error = left(coalesce(p_error, ''), 2000), locked_until = null,
         next_attempt_at = now() + make_interval(secs => s.backoff_seconds * power(2, greatest(d.attempts - 1, 0)))
   where id = d.id;
  if v_status = 'DEAD' then
    insert into logistics.dead_letter (delivery_id, event_row_id, subscriber_code, error)
    values (d.id, d.event_row_id, d.subscriber_code, left(coalesce(p_error, ''), 2000));
  end if;
  return v_status;
end;
$$;

-- Les abonnés INTERNES : appelés ici, chacun dans sa propre sous-transaction.
-- Un abonné défaillant n'arrête ni les autres, ni l'opération métier (qui est déjà validée).
create or replace function logistics.dispatch_events(p_limit int default 100, p_subscriber text default null)
returns jsonb
language plpgsql volatile security definer set search_path = ''
as $$
declare
  d record;
  ev logistics.domain_event;
  v_handler regproc;
  v_ok int := 0; v_failed int := 0; v_dead int := 0;
  v_status text;
begin
  for d in
    select ed.id, ed.event_row_id, ed.subscriber_code
    from logistics.event_delivery ed
    join logistics.event_subscriber s on s.code = ed.subscriber_code
    where s.kind = 'internal' and s.active and ed.status in ('PENDING', 'FAILED') and ed.next_attempt_at <= now()
      and (p_subscriber is null or ed.subscriber_code = p_subscriber)
    order by ed.id
    limit p_limit
    for update of ed skip locked
  loop
    update logistics.event_delivery set attempts = attempts + 1, status = 'IN_PROGRESS' where id = d.id;
    select * into ev from logistics.domain_event where id = d.event_row_id;
    select handler into v_handler from logistics.event_subscriber where code = d.subscriber_code;
    begin
      execute format('select %s($1)', v_handler) using ev;
      update logistics.event_delivery set status = 'DELIVERED', delivered_at = now(), last_error = null where id = d.id;
      v_ok := v_ok + 1;
    exception when others then
      v_status := logistics.record_delivery_failure(d.id, sqlerrm);
      if v_status = 'DEAD' then v_dead := v_dead + 1; else v_failed := v_failed + 1; end if;
    end;
  end loop;
  return jsonb_build_object('delivered', v_ok, 'failed', v_failed, 'dead', v_dead);
end;
$$;

-- Les abonnés EXTERNES (Edge Functions) : ils réclament, traitent, puis confirment ou refusent.
create or replace function logistics.claim_deliveries(p_subscriber text, p_limit int default 50, p_lease_seconds int default 60)
returns table (delivery_id bigint, attempt int, envelope jsonb)
language plpgsql volatile security definer set search_path = ''
as $$
begin
  if not exists (select 1 from logistics.event_subscriber where code = p_subscriber and kind = 'external' and active) then
    raise exception 'Abonné externe inconnu ou inactif : %.', p_subscriber using errcode = 'LG002';
  end if;
  return query
  with due as (
    select ed.id from logistics.event_delivery ed
    where ed.subscriber_code = p_subscriber
      and ((ed.status in ('PENDING', 'FAILED') and ed.next_attempt_at <= now())
        or (ed.status = 'IN_PROGRESS' and ed.locked_until < now()))      -- un travailleur tombé : son bail expire, l'événement revient
    order by ed.id limit p_limit for update skip locked
  ), taken as (
    update logistics.event_delivery ed
       set status = 'IN_PROGRESS', attempts = ed.attempts + 1, locked_until = now() + make_interval(secs => p_lease_seconds)
      from due where ed.id = due.id
    returning ed.id, ed.attempts, ed.event_row_id
  )
  select t.id, t.attempts,
         jsonb_build_object('id', e.event_id, 'type', e.event_type, 'version', e.version, 'occurred_at', e.occurred_at,
                            'aggregate', jsonb_build_object('type', e.aggregate_type, 'id', e.aggregate_id),
                            'correlation_id', e.correlation_id, 'causation_id', e.causation_id,
                            'idempotency_key', e.idempotency_key,
                            'actor', jsonb_build_object('user_id', e.actor_user_id, 'label', e.actor_label),
                            'payload', e.payload)
  from taken t join logistics.domain_event e on e.id = t.event_row_id
  order by t.id;
end;
$$;

create or replace function logistics.ack_delivery(p_delivery_id bigint)
returns void language plpgsql volatile security definer set search_path = '' as $$
begin
  update logistics.event_delivery set status = 'DELIVERED', delivered_at = now(), locked_until = null, last_error = null
   where id = p_delivery_id and status = 'IN_PROGRESS';
  if not found then raise exception 'Livraison % non en cours.', p_delivery_id using errcode = 'LG004'; end if;
end;
$$;

create or replace function logistics.nack_delivery(p_delivery_id bigint, p_error text)
returns text language plpgsql volatile security definer set search_path = '' as $$
begin
  if not exists (select 1 from logistics.event_delivery where id = p_delivery_id and status = 'IN_PROGRESS') then
    raise exception 'Livraison % non en cours.', p_delivery_id using errcode = 'LG004';
  end if;
  return logistics.record_delivery_failure(p_delivery_id, p_error);
end;
$$;

-- Remettre un événement mort en circulation, après avoir corrigé la cause. La trace reste.
create or replace function logistics.requeue_dead_letter(p_dead_letter_id bigint, p_note text)
returns void language plpgsql volatile security definer set search_path = '' as $$
declare v_delivery bigint;
begin
  update logistics.dead_letter set resolved_at = now(), resolution_note = left(coalesce(p_note, ''), 500)
   where id = p_dead_letter_id and resolved_at is null returning delivery_id into v_delivery;
  if not found then raise exception 'File des échecs : entrée % introuvable ou déjà résolue.', p_dead_letter_id using errcode = 'LG002'; end if;
  update logistics.event_delivery set status = 'PENDING', attempts = 0, next_attempt_at = now(), last_error = null, locked_until = null
   where id = v_delivery;
end;
$$;

-- Surveillance : combien d'événements attendent, échouent, sont morts ?
create or replace view logistics.event_health with (security_invoker = true) as
  select subscriber_code,
         count(*) filter (where status = 'PENDING') as pending,
         count(*) filter (where status = 'IN_PROGRESS') as in_progress,
         count(*) filter (where status = 'FAILED') as failed,
         count(*) filter (where status = 'DEAD') as dead,
         count(*) filter (where status = 'DELIVERED') as delivered,
         coalesce(extract(epoch from now() - min(created_at) filter (where status in ('PENDING', 'FAILED'))), 0)::int as oldest_waiting_seconds
  from logistics.event_delivery group by subscriber_code;

-- Un abonné interne réel : prévoit les notifications des événements que le client voit.
create or replace function logistics.handle_notification_planner(ev logistics.domain_event)
returns void language plpgsql set search_path = '' as $$
declare v_parcel logistics.parcel;
begin
  if ev.aggregate_type <> 'parcel' then return; end if;
  select * into v_parcel from logistics.parcel where id = ev.aggregate_id::uuid;
  if not found or v_parcel.customer_id is null then return; end if;
  if not exists (select 1 from logistics.device d where d.owner_customer_id = v_parcel.customer_id and d.active and d.push_token is not null) then
    return;                                    -- pas d'application installée : rien à envoyer
  end if;
  insert into logistics.notification (customer_id, parcel_id, event_row_id, channel, template, payload)
  values (v_parcel.customer_id, v_parcel.id, ev.id, 'push', ev.event_type,
          jsonb_build_object('tracking_number', v_parcel.tracking_number, 'to_status', ev.payload ->> 'to_status'))
  on conflict (event_row_id, channel) do nothing;
end;
$$;

insert into logistics.event_subscriber (code, kind, event_types, handler) values
  ('notification_planner', 'internal',
   array['ParcelReceived', 'ParcelInTransit', 'ParcelArrived', 'CustomsCleared', 'ParcelAtDestinationHub', 'OutForDelivery',
         'Delivered', 'ParcelOnHold', 'ParcelDamaged', 'ParcelLost', 'ParcelReturned'],
   'logistics.handle_notification_planner'::regproc)
on conflict (code) do nothing;


-- 4. Le garde du statut : personne ne le change « à la main » -------------------------------------------
create or replace function logistics.guard_parcel_status()
returns trigger language plpgsql set search_path = '' as $$
declare v_dans_transition boolean := coalesce(current_setting('logistics.transition', true), 'off') = 'on';
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
  return new;
end;
$$;
drop trigger if exists guard_parcel_status on logistics.parcel;
create trigger guard_parcel_status before insert or update on logistics.parcel
  for each row execute function logistics.guard_parcel_status();


-- 5. La transition : LE seul chemin pour changer un statut ---------------------------------------------
create or replace function logistics.actor_can(p_user uuid, p_right text)
returns boolean language sql stable set search_path = '' as $$
  select exists (
    select 1 from logistics.app_user u
    where u.id = p_user and u.active
      and (u.role in ('manager', 'admin') or (u.role = 'employee' and p_right <> 'direction' and p_right = any (u.rights)))
  )
$$;

create or replace function logistics.transition_parcel(
  p_parcel_id       uuid,
  p_to_status       text,
  p_actor_user_id   uuid  default null,
  p_idempotency_key text  default null,
  p_correlation_id  uuid  default null,
  p_warehouse_id    uuid  default null,
  p_location_id     uuid  default null,
  p_location_text   text  default '',
  p_device_id       uuid  default null,
  p_reason          text  default null,
  p_metadata        jsonb default '{}'::jsonb,
  p_source          text  default 'api')
returns jsonb
language plpgsql volatile security definer set search_path = ''
as $$
declare
  v_parcel     logistics.parcel;
  v_tr         logistics.parcel_transition;
  v_corr       uuid := coalesce(p_correlation_id, gen_random_uuid());
  v_hash       text;
  v_prior_hash text;
  v_prior      jsonb;
  v_prev       text;
  v_label      text := '';
  v_loc_code   text;
  v_loc_wh     uuid;
  v_event_id   uuid := gen_random_uuid();
  v_te         bigint;
  v_de         bigint;
  v_result     jsonb;
begin
  if p_source not in ('system', 'scan', 'manual', 'api') then
    raise exception 'Source inconnue : %.', p_source using errcode = 'LG005';
  end if;
  v_hash := md5(concat_ws('|', p_parcel_id, p_to_status, p_actor_user_id, p_warehouse_id, p_location_id, p_location_text,
                          p_device_id, p_reason, p_metadata::text, p_source));

  -- Idempotence : la même clé rejouée rend le résultat d'origine, sans rien refaire.
  if p_idempotency_key is not null then
    insert into logistics.command_log (idempotency_key, command, request_hash, entity_type, entity_id)
    values (p_idempotency_key, 'transition_parcel', v_hash, 'parcel', p_parcel_id::text)
    on conflict (idempotency_key) do nothing;
    if not found then
      select request_hash, result into v_prior_hash, v_prior from logistics.command_log where idempotency_key = p_idempotency_key;
      if v_prior_hash <> v_hash then
        raise exception 'Clé d''idempotence déjà utilisée pour une AUTRE demande.' using errcode = 'LG006';
      end if;
      return coalesce(v_prior, '{}'::jsonb) || jsonb_build_object('replayed', true);
    end if;
  end if;

  select * into v_parcel from logistics.parcel where id = p_parcel_id for update;
  if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;

  -- Qui ? Un membre actif du personnel, ou le système (événement interne) pour les transitions qui le permettent.
  if p_actor_user_id is not null then
    v_label := coalesce((select email from auth.users where id = p_actor_user_id), p_actor_user_id::text);
  elsif p_source <> 'system' then
    raise exception 'Acteur obligatoire (seul le système interne peut agir sans personne derrière).' using errcode = 'LG003';
  else
    v_label := 'system';
  end if;

  -- Quoi ? La transition doit exister.
  select * into v_tr from logistics.parcel_transition where from_status = v_parcel.status and to_status = p_to_status;
  if not found then
    raise exception 'Transition non autorisée : % → %.', v_parcel.status, p_to_status using errcode = 'LG001';
  end if;

  -- A-t-il le droit ?
  if p_actor_user_id is null then
    if not v_tr.allow_system then
      raise exception 'Cette transition (% → %) ne peut pas être demandée par le système seul.', v_tr.from_status, v_tr.to_status using errcode = 'LG003';
    end if;
  elsif not logistics.actor_can(p_actor_user_id, v_tr.required_right) then
    raise exception 'Droit insuffisant pour % → % (exige : %).', v_tr.from_status, v_tr.to_status, v_tr.required_right using errcode = 'LG003';
  end if;

  -- Les conditions de la transition.
  if v_tr.requires_reason and btrim(coalesce(p_reason, '')) = '' then
    raise exception 'Un motif est obligatoire pour % → %.', v_tr.from_status, v_tr.to_status using errcode = 'LG005';
  end if;
  if v_tr.requires_warehouse and coalesce(p_warehouse_id, v_parcel.current_warehouse_id) is null then
    raise exception 'Un entrepôt est obligatoire pour % → %.', v_tr.from_status, v_tr.to_status using errcode = 'LG005';
  end if;
  if v_tr.requires_location and coalesce(p_location_id, v_parcel.current_location_id) is null then
    raise exception 'Un emplacement est obligatoire pour % → %.', v_tr.from_status, v_tr.to_status using errcode = 'LG005';
  end if;
  if v_tr.requires_customer and v_parcel.customer_id is null then
    raise exception 'Un colis sans client ne peut pas avancer au-delà du rangement.' using errcode = 'LG005';
  end if;
  if p_location_id is not null then
    select code, warehouse_id into v_loc_code, v_loc_wh from logistics.warehouse_location where id = p_location_id and active;
    if not found then raise exception 'Emplacement inconnu ou inactif.' using errcode = 'LG005'; end if;
    if p_warehouse_id is not null and p_warehouse_id <> v_loc_wh then
      raise exception 'L''emplacement n''appartient pas à l''entrepôt indiqué.' using errcode = 'LG005';
    end if;
  end if;
  if v_tr.resume then
    -- La reprise ramène le colis là où il était avant sa mise en attente, pas ailleurs.
    select e.from_status into v_prev from logistics.tracking_event e
     where e.parcel_id = p_parcel_id and e.to_status = 'ON_HOLD' order by e.id desc limit 1;
    if v_prev is not null and v_prev <> p_to_status then
      raise exception 'Reprise vers % impossible : le colis était en % avant sa mise en attente.', p_to_status, v_prev using errcode = 'LG001';
    end if;
  end if;

  -- Appliquer.
  perform set_config('logistics.transition', 'on', true);
  update logistics.parcel
     set status = p_to_status, status_authority = 'core',
         current_warehouse_id = coalesce(p_warehouse_id, v_loc_wh, current_warehouse_id),
         current_location_id  = coalesce(p_location_id, current_location_id),
         current_location     = case when coalesce(p_location_text, '') <> '' then p_location_text
                                     when v_loc_code is not null then v_loc_code else current_location end
   where id = p_parcel_id;
  perform set_config('logistics.transition', 'off', true);

  -- Tracer : événement de suivi, audit et événement de domaine, dans LA MÊME transaction.
  insert into logistics.tracking_event (parcel_id, event_type, from_status, to_status, occurred_at, actor_user_id, actor_label,
                                        warehouse_id, location_id, location_text, device_id, source, metadata, correlation_id)
  values (p_parcel_id, v_tr.event_type, v_tr.from_status, p_to_status, now(), p_actor_user_id, v_label,
          coalesce(p_warehouse_id, v_loc_wh), p_location_id, coalesce(nullif(p_location_text, ''), v_loc_code, ''), p_device_id,
          p_source, coalesce(p_metadata, '{}'::jsonb) || case when p_reason is null then '{}'::jsonb else jsonb_build_object('reason', p_reason) end, v_corr)
  returning id into v_te;

  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id, metadata)
  values (p_actor_user_id, v_label, 'parcel.transition', 'parcel', p_parcel_id::text,
          jsonb_build_object('status', v_tr.from_status, 'location', v_parcel.current_location),
          jsonb_build_object('status', p_to_status, 'location', coalesce(nullif(p_location_text, ''), v_loc_code, v_parcel.current_location)),
          v_corr, jsonb_build_object('event_type', v_tr.event_type, 'reason', p_reason, 'source', p_source));

  insert into logistics.domain_event (event_id, event_type, aggregate_type, aggregate_id, correlation_id, idempotency_key,
                                      actor_user_id, actor_label, payload)
  values (v_event_id, v_tr.event_type, 'parcel', p_parcel_id::text, v_corr, p_idempotency_key, p_actor_user_id, v_label,
          jsonb_build_object('parcel_id', p_parcel_id, 'tracking_number', v_parcel.tracking_number, 'from_status', v_tr.from_status,
                             'to_status', p_to_status, 'location', coalesce(nullif(p_location_text, ''), v_loc_code, ''),
                             'warehouse_id', coalesce(p_warehouse_id, v_loc_wh), 'tracking_event_id', v_te, 'reason', p_reason))
  returning id into v_de;

  v_result := jsonb_build_object('parcel_id', p_parcel_id, 'from_status', v_tr.from_status, 'to_status', p_to_status,
                                 'tracking_event_id', v_te, 'event_id', v_event_id, 'correlation_id', v_corr, 'replayed', false);
  if p_idempotency_key is not null then
    update logistics.command_log set result = v_result where idempotency_key = p_idempotency_key;
  end if;
  return v_result;
end;
$$;
comment on function logistics.transition_parcel is
  'LE seul chemin pour changer le statut d''un colis. Autorise, valide, trace (suivi + audit + événement) dans une même transaction ; idempotent.';


-- 6. La façade : une fonction publique, réservée au personnel (ADR 0002) -------------------------------
create or replace function public.lg_transition_parcel(
  p_parcel_id       uuid,
  p_to_status       text,
  p_idempotency_key text  default null,
  p_correlation_id  uuid  default null,
  p_warehouse_id    uuid  default null,
  p_location_id     uuid  default null,
  p_location_text   text  default '',
  p_reason          text  default null,
  p_metadata        jsonb default '{}'::jsonb)
returns jsonb
language plpgsql volatile security definer set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'Connexion requise.' using errcode = '42501';
  end if;
  -- L'acteur est TOUJOURS le compte connecté : il ne se passe jamais en paramètre.
  return logistics.transition_parcel(p_parcel_id, p_to_status, auth.uid(), p_idempotency_key, p_correlation_id,
                                     p_warehouse_id, p_location_id, p_location_text, null, p_reason, p_metadata, 'api');
end;
$$;
comment on function public.lg_transition_parcel is 'Façade du noyau : change le statut d''un colis par une transition autorisée. Personnel seulement.';


-- 7. Tout fermé, sauf ce qui doit s'ouvrir -------------------------------------------------------------
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

-- La façade : fermée aux visiteurs, ouverte aux comptes connectés (le contrôle de rôle est DANS la fonction).
revoke all on function public.lg_transition_parcel(uuid, text, text, uuid, uuid, uuid, text, text, jsonb) from public, anon;
grant execute on function public.lg_transition_parcel(uuid, text, text, uuid, uuid, uuid, text, text, jsonb) to authenticated;

-- Le répartiteur et les travailleurs externes passent par la clé de service, côté serveur seulement.
grant usage on schema logistics to service_role;
grant execute on function logistics.dispatch_events(int, text) to service_role;
grant execute on function logistics.claim_deliveries(text, int, int) to service_role;
grant execute on function logistics.ack_delivery(bigint) to service_role;
grant execute on function logistics.nack_delivery(bigint, text) to service_role;
grant execute on function logistics.requeue_dead_letter(bigint, text) to service_role;
grant select on logistics.event_health to service_role;

-- Pour retirer SEULEMENT cette étape (garder 001 et 002) :
--   drop function if exists public.lg_transition_parcel(uuid, text, text, uuid, uuid, uuid, text, text, jsonb);
--   drop trigger if exists guard_parcel_status on logistics.parcel;
--   drop view if exists logistics.event_health;
--   drop table if exists logistics.notification, logistics.command_log, logistics.dead_letter, logistics.event_delivery,
--                        logistics.event_subscriber, logistics.domain_event, logistics.parcel_transition, logistics.event_type cascade;
