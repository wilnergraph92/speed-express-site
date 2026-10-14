-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 27 : le centre de notifications (phase 11)
-- -----------------------------------------------------------------------------
-- À passer APRÈS 026, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Le circuit de l'étape 010 reste le même : domain_event → event_delivery → moteur (règle × modèle × langue × préférence × canal) →
-- notification → travailleur côté serveur → fournisseur. Chaque notification porte déjà l'événement (event_row_id), le canal, la langue, le
-- modèle, le statut, les essais, la dernière erreur et la date d'envoi ; un événement ne crée qu'UNE notification par canal (unique). Ici :
--   · le DESTINATAIRE est écrit sur chaque notification à sa création (adresse e-mail, téléphone, appareils, portail) : on sait à qui elle
--     est partie, même si le client change d'adresse ensuite ;
--   · l'INSCRIPTION : un message de bienvenue, UNE fois par client (index unique), après la confirmation de son adresse e-mail, jamais pour
--     un compte ancien ; un déclencheur sur auth.users qui ne peut jamais faire échouer une confirmation ;
--   · le DOCUMENT NÉCESSAIRE : une exception de douane « document manquant » prévient le client (DocumentRequired) ; la mise en attente
--     qu'elle provoque ne prévient pas une seconde fois (même corrélation) ; les autres exceptions gardent le message « en attente » ;
--   · WHATSAPP : le canal a son fournisseur (WhatsApp Cloud API de Meta, par le travailleur) mais reste ÉTEINT ; il entre dans les règles qui
--     comptent (au HUB, en livraison, livreur affecté, livré, livraison manquée, document nécessaire, facture, paiement). Le client doit l'avoir
--     demandé (préférence, réglage par défaut : non) ;
--   · le SUIVI des fournisseurs : un accusé (remis, lu) ou un rebond (adresse refusée, numéro injoignable) arrive par une fonction serveur
--     (scripts/notifications/webhook-fournisseurs.mjs) et ses_nt_provider_event, en ajout seul ; un rebond fait passer la notification en échec ;
--   · la SURVEILLANCE : ses_nt_alert (pour le travailleur, qui ouvre une alerte quand les échecs dépassent un seuil) ; la direction relance
--     une notification en échec (lg_nt_retry, motif, tracé) — la MÊME notification, jamais une seconde.
-- Rejouable sans risque ; aucune donnée supprimée.
-- =============================================================================

-- 1. Le destinataire, sur chaque notification --------------------------------------------------------------------------------------------
alter table logistics.notification add column if not exists recipient       text;
alter table logistics.notification add column if not exists provider_status text;
alter table logistics.notification add column if not exists delivered_at    timestamptz;
comment on column logistics.notification.recipient is 'À qui elle part, figé à la création : e-mail, téléphone, « appareils:n », « portail ».';

create or replace function logistics.nt_recipient_of(p_customer uuid, p_channel text, p_payload jsonb)
returns text language sql stable set search_path = '' as $$
  select case p_channel
    when 'in_app' then 'portail'
    when 'email' then nullif(btrim(c.email), '')
    when 'push' then 'appareils:' || (select count(*) from logistics.device d where d.owner_customer_id = c.id and d.active and d.push_token is not null)
    else nullif(btrim(coalesce(nullif(p_payload ->> 'recipient_phone', ''), c.phone)), '') end
  from logistics.customer c where c.id = p_customer
$$;

create or replace function logistics.nt_fill_recipient()
returns trigger language plpgsql set search_path = '' as $$
begin
  if new.recipient is null then new.recipient := left(logistics.nt_recipient_of(new.customer_id, new.channel, new.payload), 200); end if;
  return new;
end;
$$;
drop trigger if exists nt_fill_recipient on logistics.notification;
create trigger nt_fill_recipient before insert on logistics.notification for each row execute function logistics.nt_fill_recipient();
-- les notifications déjà créées reçoivent le destinataire d'aujourd'hui (une information de plus, rien d'effacé)
update logistics.notification n set recipient = left(logistics.nt_recipient_of(n.customer_id, n.channel, n.payload), 200) where n.recipient is null;


-- 2. Les nouveaux événements -------------------------------------------------------------------------------------------------------------
do $$
declare v_types text[];
begin
  select array_agg(distinct x order by x) into v_types
    from (select aggregate_type as x from logistics.event_type union select 'customer') t;
  alter table logistics.event_type drop constraint if exists event_type_aggregate_type_check;
  execute format('alter table logistics.event_type add constraint event_type_aggregate_type_check check (aggregate_type = any (%L::text[]))', v_types);
end
$$;
insert into logistics.event_type (code, aggregate_type, description) values
  ('CustomerRegistered', 'customer', 'Client inscrit, adresse e-mail confirmée (bienvenue)')
on conflict (code) do nothing;

-- UNE bienvenue par client, quoi qu'il arrive (deux déclencheurs peuvent la demander, la recopie peut rejouer)
create unique index if not exists domain_event_une_bienvenue on logistics.domain_event (aggregate_id) where event_type = 'CustomerRegistered';

create or replace function logistics.nt_welcome(p_auth_user uuid)
returns void language plpgsql security definer set search_path = '' as $$
declare c logistics.customer; v_conf timestamptz; v_cree timestamptz;
begin
  if p_auth_user is null then return; end if;
  select u.email_confirmed_at, u.created_at into v_conf, v_cree from auth.users u where u.id = p_auth_user;
  -- confirmée, et récente : un compte ancien (déjà client avant ce centre) ne reçoit jamais de « bienvenue »
  if v_conf is null or v_cree is null or v_cree < now() - interval '7 days' then return; end if;
  select * into c from logistics.customer where auth_user_id = p_auth_user;
  if not found or c.source = 'legacy_staff_account' then return; end if;   -- pas encore recopié : le déclencheur du client s'en chargera
  insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_label, payload)
  values ('CustomerRegistered', 'customer', c.id::text, gen_random_uuid(), 'inscription', jsonb_build_object('customer_id', c.id))
  on conflict (aggregate_id) where event_type = 'CustomerRegistered' do nothing;
end;
$$;

-- Ni l'un ni l'autre ne peut faire échouer une inscription, une confirmation ou une recopie : une erreur est avalée.
create or replace function logistics.nt_welcome_on_confirm()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  begin perform logistics.nt_welcome(new.id); exception when others then null; end;
  return null;
end;
$$;
create or replace function logistics.nt_welcome_on_customer()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  begin perform logistics.nt_welcome(new.auth_user_id); exception when others then null; end;
  return null;
end;
$$;
do $$
begin
  if to_regclass('auth.users') is not null then
    execute 'drop trigger if exists ses_nt_bienvenue on auth.users';
    execute 'create trigger ses_nt_bienvenue after update of email_confirmed_at on auth.users for each row
             when (old.email_confirmed_at is null and new.email_confirmed_at is not null) execute function logistics.nt_welcome_on_confirm()';
  end if;
end
$$;
drop trigger if exists nt_bienvenue on logistics.customer;
create trigger nt_bienvenue after insert or update of auth_user_id on logistics.customer for each row execute function logistics.nt_welcome_on_customer();


-- 3. Ce que chaque événement apporte à son modèle (redéfinie depuis l'étape 010) ------------------------------------------------------------
create or replace function logistics.nt_values(ev logistics.domain_event)
returns jsonb language plpgsql stable set search_path = '' as $$
declare o jsonb := '{}'::jsonb; p logistics.parcel; i logistics.invoice; py logistics.payment;
begin
  if ev.aggregate_type = 'parcel' then
    select * into p from logistics.parcel x where x.id::text = ev.aggregate_id;
    if found then o := jsonb_build_object('tracking_number', p.tracking_number, 'stage', logistics.customer_stage(coalesce(ev.payload ->> 'to_status', p.status))); end if;
  elsif ev.aggregate_type = 'invoice' then
    select * into i from logistics.invoice x where x.id::text = ev.aggregate_id;
    if found then o := jsonb_build_object('invoice_number', i.number, 'amount', to_char(case when ev.event_type = 'InvoiceIssued' then i.total else logistics.invoice_balance(i) end, 'FM999999990.00'), 'currency', i.currency, 'date', i.due_date::text); end if;
  elsif ev.aggregate_type = 'payment' then
    select * into py from logistics.payment x where x.id::text = ev.aggregate_id;
    if found then o := jsonb_build_object('amount', to_char(py.amount, 'FM999999990.00'), 'currency', py.currency, 'invoice_number', (select number from logistics.invoice where id = py.invoice_id)); end if;
  elsif ev.event_type like 'PickupRequest%' then
    o := jsonb_build_object('date', coalesce(ev.payload ->> 'date', (select preferred_date::text from logistics.pickup_request where id::text = ev.aggregate_id)),
                            'message', (select review_message from logistics.pickup_request where id::text = ev.aggregate_id));
  elsif ev.event_type like 'DeliveryRequest%' then
    o := jsonb_build_object('date', coalesce(ev.payload ->> 'date', (select preferred_date::text from logistics.delivery_request where id::text = ev.aggregate_id)),
                            'message', (select review_message from logistics.delivery_request where id::text = ev.aggregate_id));
  elsif ev.event_type = 'CustomerRegistered' then
    o := jsonb_build_object('code', (select c.code from logistics.customer c where c.id::text = ev.aggregate_id));
  elsif ev.event_type = 'CustomsExceptionRaised' then
    -- le numéro du colis, rien d'autre : la description de l'exception est un texte INTERNE, il ne part jamais
    o := jsonb_build_object('tracking_number', (select x.tracking_number from logistics.parcel x where x.id::text = ev.payload ->> 'parcel_id'));
  end if;
  return jsonb_strip_nulls(o);
end;
$$;

create or replace function logistics.nt_customer_of(ev logistics.domain_event)
returns uuid language plpgsql stable set search_path = '' as $$
declare v uuid;
begin
  if ev.aggregate_type = 'parcel' then select p.customer_id into v from logistics.parcel p where p.id::text = ev.aggregate_id;
  elsif ev.aggregate_type = 'invoice' then select i.customer_id into v from logistics.invoice i where i.id::text = ev.aggregate_id;
  elsif ev.aggregate_type = 'payment' then select p.customer_id into v from logistics.payment p where p.id::text = ev.aggregate_id;
  elsif ev.aggregate_type = 'customer' then v := ev.aggregate_id::uuid;
  elsif ev.event_type = 'CustomsExceptionRaised' then select p.customer_id into v from logistics.parcel p where p.id::text = ev.payload ->> 'parcel_id';
  elsif ev.payload ? 'customer_id' then v := nullif(ev.payload ->> 'customer_id', '')::uuid;
  end if;
  return v;
exception when others then return null;
end;
$$;

-- Une règle peut ne pas s'appliquer à TOUT son type d'événement.
create or replace function logistics.nt_applies(ev logistics.domain_event)
returns boolean language plpgsql stable set search_path = '' as $$
begin
  if ev.event_type = 'CustomsExceptionRaised' then
    return coalesce(ev.payload ->> 'kind', '') = 'MISSING_DOCUMENT';     -- les autres exceptions : le message « en attente » suffit
  elsif ev.event_type = 'ParcelOnHold' then
    -- mis en attente PAR une exception « document manquant » : le client reçoit DocumentRequired, pas un second message
    return not exists (select 1 from logistics.customs_exception x where x.correlation_id = ev.correlation_id and x.kind = 'MISSING_DOCUMENT');
  end if;
  return true;
exception when undefined_table then return true;
end;
$$;

-- Le moteur (redéfini depuis l'étape 010) : la même chose, plus la règle qui ne s'applique pas toujours.
create or replace function logistics.handle_notification_engine(ev logistics.domain_event)
returns void language plpgsql set search_path = '' as $$
declare r logistics.notification_rule; c logistics.customer; v_ch text; v_vals jsonb; t logistics.notification_template; v_parcel uuid;
begin
  select * into r from logistics.notification_rule where event_type = ev.event_type and active;
  if not found or not logistics.nt_applies(ev) then return; end if;
  select * into c from logistics.customer where id = logistics.nt_customer_of(ev);
  if not found or c.source = 'legacy_staff_account' then return; end if;       -- l'équipe n'est pas la clientèle
  v_vals := logistics.nt_values(ev);
  v_parcel := case when ev.aggregate_type = 'parcel' then ev.aggregate_id::uuid
                   when ev.event_type = 'CustomsExceptionRaised' then nullif(ev.payload ->> 'parcel_id', '')::uuid end;
  foreach v_ch in array r.channels loop
    continue when not logistics.nt_reachable(c, v_ch);
    select * into t from logistics.notification_template x where x.code = r.template and x.language = coalesce(c.language, 'fr') and x.active;
    if not found then select * into t from logistics.notification_template x where x.code = r.template and x.language = 'fr' and x.active; end if;
    continue when not found;                                                       -- pas de texte : on ne prévient pas avec un message vide
    insert into logistics.notification (customer_id, parcel_id, event_row_id, channel, template, payload, language, title, body, status, sent_at)
    values (c.id, v_parcel, ev.id, v_ch, r.template, v_vals, t.language, logistics.nt_render(t.title, v_vals), logistics.nt_render(t.body, v_vals),
            case when v_ch = 'in_app' then 'SENT' else 'PENDING' end, case when v_ch = 'in_app' then now() end)
    on conflict (event_row_id, channel) do nothing;
  end loop;
end;
$$;


-- 4. Les modèles (les mêmes textes que le portail : écrits par outils/portail-textes.py) ------------------------------------------------------
-- modeles:debut
-- Écrit par outils/portail-textes.py : ne pas modifier à la main.
insert into logistics.notification_template (code, language, title, body) values
  ('Welcome', 'fr', 'Bienvenue chez Speed Express Shipping', 'Votre code client est {code} : indiquez-le sur chacun de vos achats. Votre adresse d''expédition à Miami vous attend dans votre espace client.'),
  ('Welcome', 'en', 'Welcome to Speed Express Shipping', 'Your customer code is {code}: add it to each of your purchases. Your Miami shipping address is waiting in your customer area.'),
  ('Welcome', 'es', 'Bienvenido a Speed Express Shipping', 'Su código de cliente es {code}: indíquelo en cada una de sus compras. Su dirección de envío en Miami le espera en su espacio de cliente.'),
  ('Welcome', 'ht', 'Byenvini nan Speed Express Shipping', 'Kòd kliyan ou se {code} : mete l sou chak acha ou. Adrès ekspedisyon ou nan Miami ap tann ou nan espas kliyan ou.'),
  ('DocumentRequired', 'fr', 'Document demandé par la douane', 'La douane demande un document pour votre colis {tracking_number}. Ouvrez votre espace client ou écrivez au support pour le transmettre.'),
  ('DocumentRequired', 'en', 'Document requested by customs', 'Customs is asking for a document for your parcel {tracking_number}. Open your customer area or write to support to send it.'),
  ('DocumentRequired', 'es', 'Documento solicitado por la aduana', 'La aduana solicita un documento para su paquete {tracking_number}. Abra su espacio de cliente o escriba al soporte para enviarlo.'),
  ('DocumentRequired', 'ht', 'Dokiman dwàn mande', 'Dwàn mande yon dokiman pou kolis ou a {tracking_number}. Louvri espas kliyan ou oswa ekri sipò a pou voye l.')
on conflict (code, language) do update set title = excluded.title, body = excluded.body
  where (logistics.notification_template.title, logistics.notification_template.body) is distinct from (excluded.title, excluded.body);
-- modeles:fin


-- 5. Les règles : les deux nouvelles, et WhatsApp là où il compte ---------------------------------------------------------------------------
insert into logistics.notification_rule (event_type, template, channels) values
  ('CustomerRegistered',     'Welcome',          array['in_app', 'email']),
  ('CustomsExceptionRaised', 'DocumentRequired', array['in_app', 'push', 'email', 'whatsapp'])
on conflict (event_type) do nothing;
update logistics.notification_rule set channels = channels || array['whatsapp']
 where event_type in ('ParcelAtDestinationHub', 'OutForDelivery', 'DeliveryAssigned', 'Delivered', 'DeliveryFailed', 'InvoiceIssued', 'PaymentReceived')
   and not ('whatsapp' = any (channels));
update logistics.event_subscriber
   set event_types = (select array_agg(event_type order by event_type) from logistics.notification_rule)
 where code = 'notification_engine'
   and event_types is distinct from (select array_agg(event_type order by event_type) from logistics.notification_rule);
-- Le fournisseur de WhatsApp est nommé ; le canal reste ÉTEINT tant que le propriétaire ne l'allume pas (modèles approuvés par Meta,
-- secrets posés dans le travailleur) : un canal éteint ne crée rien.
update logistics.notification_channel set provider = 'meta' where code = 'whatsapp' and provider = '';


-- 6. Ce que le travailleur doit savoir pour WhatsApp : le modèle, la langue, les variables, le pays (indicatif) ----------------------------------
-- Les variables sont celles que le moteur a déjà retenues (nt_values : seulement les dix permises) ; rien d'autre ne part chez Meta.
-- Le pays du client, en code (l'ancien schéma l'écrit en toutes lettres : « Haïti », « République dominicaine »…) : l'indicatif du téléphone en dépend.
create or replace function logistics.nt_country_code(p text)
returns text language sql immutable set search_path = '' as $$
  select case
    when p is null or btrim(p) = '' then null
    when upper(btrim(p)) in ('HT', 'HTI') or translate(lower(btrim(p)), 'ïÏíÍ', 'iiii') in ('haiti', 'ayiti') then 'HT'
    when upper(btrim(p)) in ('DO', 'DOM', 'RD') or translate(lower(btrim(p)), 'éÉúÚ', 'eeuu') like any (array['%dominica%', '%dominicaine%']) then 'DO'
    when upper(btrim(p)) in ('US', 'USA') or translate(lower(btrim(p)), 'éÉ', 'ee') like any (array['%etats-unis%', '%etats unis%', '%united states%', '%estados unidos%', '%eta zini%']) then 'US'
    else null end
$$;

create or replace function logistics.nt_template_data(p_ids bigint[])
returns jsonb language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_object_agg(n.id::text, jsonb_build_object('template', n.template, 'language', n.language,
           'variables', (select coalesce(jsonb_object_agg(k, v), '{}'::jsonb) from jsonb_each_text(n.payload) e(k, v) where k = any (logistics.nt_placeholders())),
           'country', logistics.nt_country_code(c.country))), '{}'::jsonb)
    from logistics.notification n join logistics.customer c on c.id = n.customer_id
   where n.id = any (coalesce(p_ids, '{}')) and n.channel in ('whatsapp', 'sms')
$$;


-- 7. Le suivi des fournisseurs : remis, lu, rebondi — en ajout seul ---------------------------------------------------------------------------
create table if not exists logistics.notification_provider_event (
  id              bigint generated always as identity primary key,
  provider        text not null check (provider in ('meta', 'brevo', 'expo', 'sms')),
  provider_ref    text not null check (char_length(provider_ref) between 1 and 200),
  status          text not null check (status in ('SENT', 'DELIVERED', 'READ', 'BOUNCED', 'FAILED', 'COMPLAINT')),
  error           text,
  occurred_at     timestamptz,
  received_at     timestamptz not null default now(),
  notification_id bigint references logistics.notification (id) on delete restrict,
  unique (provider, provider_ref, status)
);
comment on table logistics.notification_provider_event is 'Accusés des fournisseurs (remis, lu, rebond), reçus par une fonction serveur vérifiée. Ajout seul.';
drop trigger if exists notification_provider_event_append_only on logistics.notification_provider_event;
create trigger notification_provider_event_append_only before update or delete on logistics.notification_provider_event for each row execute function logistics.forbid_mutation();
alter table logistics.notification_provider_event enable row level security;
revoke all on logistics.notification_provider_event from public, anon, authenticated;

create or replace function logistics.nt_provider_event(p_provider text, p_ref text, p_status text, p_error text default null, p_occurred_at timestamptz default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare n logistics.notification; v_id bigint;
begin
  if p_provider not in ('meta', 'brevo', 'expo', 'sms') then raise exception 'Fournisseur inconnu.' using errcode = 'LG005'; end if;
  if p_status not in ('SENT', 'DELIVERED', 'READ', 'BOUNCED', 'FAILED', 'COMPLAINT') then raise exception 'Statut inconnu.' using errcode = 'LG005'; end if;
  if coalesce(btrim(p_ref), '') = '' then raise exception 'Référence du fournisseur manquante.' using errcode = 'LG005'; end if;
  -- la notification que le fournisseur a acceptée sous cette référence (un push Expo peut en porter plusieurs, séparées par des virgules)
  select * into n from logistics.notification x
   where x.provider_ref = left(btrim(p_ref), 200) or (x.channel = 'push' and left(btrim(p_ref), 200) = any (string_to_array(x.provider_ref, ',')))
   order by x.id desc limit 1;
  insert into logistics.notification_provider_event (provider, provider_ref, status, error, occurred_at, notification_id)
  values (p_provider, left(btrim(p_ref), 200), p_status, logistics.nt_clean(p_error), p_occurred_at, n.id)
  on conflict (provider, provider_ref, status) do nothing returning id into v_id;
  if v_id is null then return jsonb_build_object('result', 'DUPLICATE'); end if;                 -- le même accusé, deux fois : rien de plus
  if n.id is null then return jsonb_build_object('result', 'UNKNOWN_REF'); end if;               -- gardé, mais ne touche aucune notification
  if p_status in ('DELIVERED', 'READ') then
    update logistics.notification set provider_status = p_status, delivered_at = coalesce(delivered_at, coalesce(p_occurred_at, now())) where id = n.id;
  elsif p_status in ('BOUNCED', 'FAILED', 'COMPLAINT') then
    -- envoyée, mais jamais arrivée : c'est un échec, à voir dans la santé des envois (et pas un nouvel essai : l'adresse est en cause)
    update logistics.notification set provider_status = p_status, status = case when status = 'SENT' then 'FAILED' else status end,
           last_error = logistics.nt_clean(coalesce(p_error, lower(p_status))) where id = n.id;
    insert into logistics.notification_attempt (notification_id, attempt, outcome, provider_ref, error, worker)
    values (n.id, n.attempts, 'FAILED', left(btrim(p_ref), 200), logistics.nt_clean('fournisseur : ' || coalesce(p_error, lower(p_status))), p_provider);
  else
    update logistics.notification set provider_status = coalesce(provider_status, p_status) where id = n.id;
  end if;
  return jsonb_build_object('result', 'APPLIED', 'notification_id', n.id, 'status', p_status);
end;
$$;


-- 8. La surveillance : l'alerte du travailleur, et la relance par la direction --------------------------------------------------------------
create or replace function logistics.nt_alert()
returns jsonb language sql stable security definer set search_path = '' as $$
  with c as (
    select ch.code, ch.enabled,
           (select count(*) from logistics.notification n where n.channel = ch.code and n.status = 'FAILED' and n.created_at >= now() - interval '24 hours') as echecs,
           (select count(*) from logistics.notification n where n.channel = ch.code and n.created_at >= now() - interval '24 hours' and n.status in ('SENT', 'FAILED')) as total,
           (select extract(epoch from now() - min(n.next_attempt_at)) / 60 from logistics.notification n where n.channel = ch.code and n.status = 'PENDING' and n.next_attempt_at <= now()) as retard_min
      from logistics.notification_channel ch where ch.code <> 'in_app')
  select jsonb_build_object('as_of', now(),
    'alert', coalesce(bool_or(enabled and (echecs >= 10 or (total >= 10 and echecs * 5 >= total) or coalesce(retard_min, 0) >= 60)), false),
    'channels', coalesce(jsonb_agg(jsonb_build_object('channel', code, 'enabled', enabled, 'failed_24h', echecs, 'finished_24h', total,
                                                      'oldest_due_minutes', round(coalesce(retard_min, 0)::numeric, 1)) order by code), '[]'::jsonb))
  from c
$$;

create or replace function logistics.nt_retry(p_actor uuid, p_id bigint, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare n logistics.notification; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Le motif de la relance est obligatoire.' using errcode = 'LG005'; end if;
  select * into n from logistics.notification where id = p_id for update;
  if not found then raise exception 'Notification introuvable.' using errcode = 'LG002'; end if;
  if n.status <> 'FAILED' then raise exception 'Seule une notification en échec se relance (elle est %).', n.status using errcode = 'LG004'; end if;
  if not coalesce((select enabled from logistics.notification_channel where code = n.channel), false) then
    raise exception 'Le canal % est éteint.', n.channel using errcode = 'LG004';
  end if;
  -- la MÊME notification repart (jamais une seconde) : un essai de plus, tout de suite
  update logistics.notification set status = 'PENDING', next_attempt_at = now(), locked_until = null, attempts = 0, provider_status = null where id = p_id;
  insert into logistics.notification_attempt (notification_id, attempt, outcome, error, worker)
  values (p_id, n.attempts, 'RETRY', logistics.nt_clean('relancée par la direction : ' || left(btrim(p_reason), 200)), 'equipe');
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'notification.retry', 'notification', p_id::text,
          jsonb_build_object('status', 'FAILED', 'error', n.last_error), jsonb_build_object('status', 'PENDING', 'reason', left(btrim(p_reason), 200)), v_corr);
  return jsonb_build_object('notification_id', p_id, 'status', 'PENDING');
end;
$$;

-- Les échecs, un par un, pour l'équipe : le destinataire MASQUÉ (assez pour reconnaître, pas pour réutiliser), jamais le texte envoyé.
create or replace function logistics.nt_mask(p text)
returns text language sql immutable set search_path = '' as $$
  select case when p is null then null
              when p like '%@%' then left(p, 1) || '***@' || split_part(p, '@', 2)
              when p ~ '^\+?[0-9 ().-]{6,}$' then '***' || right(regexp_replace(p, '[^0-9]', '', 'g'), 3)
              else p end
$$;
create or replace function logistics.cc_notification_failures(p_actor uuid, p_limit int default 50)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  return jsonb_build_object('can_retry', logistics.actor_can(p_actor, 'direction'),
    'items', coalesce((select jsonb_agg(jsonb_build_object('notification_id', x.id, 'channel', x.channel, 'template', x.template, 'language', x.language,
        'recipient', logistics.nt_mask(x.recipient), 'customer', jsonb_build_object('code', c.code, 'name', c.full_name), 'attempts', x.attempts,
        'last_error', x.last_error, 'provider_status', x.provider_status, 'created_at', x.created_at,
        'channel_enabled', coalesce((select enabled from logistics.notification_channel where code = x.channel), false)) order by x.created_at desc, x.id desc)
      from (select * from logistics.notification where status = 'FAILED' order by created_at desc, id desc limit least(greatest(coalesce(p_limit, 50), 1), 200)) x
      left join logistics.customer c on c.id = x.customer_id), '[]'::jsonb));
end;
$$;


-- 9. Les façades, et tout le reste fermé -----------------------------------------------------------------------------------------------------
create or replace function public.ses_nt_template_data(p_ids bigint[])
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.nt_template_data(p_ids) $$;
create or replace function public.ses_nt_provider_event(p_provider text, p_ref text, p_status text, p_error text default null, p_occurred_at timestamptz default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.nt_provider_event(p_provider, p_ref, p_status, p_error, p_occurred_at) $$;
create or replace function public.ses_nt_alert()
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.nt_alert() $$;
create or replace function public.lg_nt_retry(p_notification_id bigint, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.nt_retry(auth.uid(), p_notification_id, p_reason) $$;
create or replace function public.lg_cc_notification_failures(p_limit int default 50)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_notification_failures(auth.uid(), p_limit) $$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('nt_recipient_of', 'nt_fill_recipient', 'nt_welcome', 'nt_welcome_on_confirm', 'nt_welcome_on_customer',
                                                            'nt_values', 'nt_customer_of', 'nt_applies', 'handle_notification_engine', 'nt_template_data', 'nt_provider_event',
                                                            'nt_alert', 'nt_retry', 'nt_mask', 'cc_notification_failures', 'nt_country_code') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  -- le travailleur et les fonctions serveur : la clé secrète seulement
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('ses_nt_template_data', 'ses_nt_provider_event', 'ses_nt_alert') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    if exists (select 1 from pg_roles where rolname = 'service_role') then execute format('grant execute on function %s to service_role', r.sig); end if;
  end loop;
  -- l'équipe
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_nt_retry', 'lg_cc_notification_failures') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
