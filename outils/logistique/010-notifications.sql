-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 10 : notifications et temps réel
-- -----------------------------------------------------------------------------
-- Phase 13. À coller dans Supabase > SQL Editor APRÈS 001 à 009, après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet ouvert est bien « speed-express-site ».
--
-- Le circuit :
--   événement (domain_event) ──▶ abonné interne « notification_engine » ──▶ une notification par canal (in_app, push, e-mail, SMS, WhatsApp)
--        │                         règle (notification_rule) + modèle traduit (notification_template) + préférences du client
--        └──▶ signal temps réel (public.ses_signal) : « quelque chose a changé dans tel domaine », sans aucune donnée métier
--   notification « in_app » : visible tout de suite dans le portail ;
--   les autres canaux : un TRAVAILLEUR (scripts/notifications/envoyer.mjs, clé secrète côté serveur) les réclame avec un bail,
--   les envoie, et rend compte — succès, nouvel essai avec attente doublée, ou échec définitif ; chaque essai est journalisé.
--
-- Règles tenues ici :
--   · une notification n'est JAMAIS dans la transaction de l'opération métier : une panne d'envoi ne bloque aucun colis ;
--   · idempotence : un événement ne produit qu'une notification par canal (unique (event_row_id, channel)), même rejoué ;
--   · les canaux sans fournisseur (SMS, WhatsApp) sont DÉCLARÉS mais éteints : rien n'est créé pour eux tant que la direction ne les allume pas ;
--   · le texte est figé à la création, dans la langue du client (repli sur le français) : un modèle modifié ne réécrit pas l'historique ;
--   · le journal des essais est en ajout seul ; les erreurs des fournisseurs sont tronquées et nettoyées de tout ce qui ressemble à une clé ;
--   · le signal temps réel ne porte AUCUNE donnée : il dit seulement « relisez », et la relecture passe par les fonctions qui contrôlent les droits.
--
-- Ne touche à aucune ancienne table métier. Retour arrière au bas du fichier. Rejouable sans risque.
-- =============================================================================

-- 1. Les canaux --------------------------------------------------------------------------------------------------------------------------
create table if not exists logistics.notification_channel (
  code            text primary key check (code in ('in_app', 'push', 'email', 'sms', 'whatsapp')),
  enabled         boolean not null default false,
  provider        text not null default '',
  max_attempts    int not null default 5 check (max_attempts between 1 and 20),
  backoff_seconds int not null default 60 check (backoff_seconds between 10 and 86400),
  updated_at      timestamptz not null default now()
);
comment on table logistics.notification_channel is 'Un canal d''envoi. Éteint = aucune notification n''est créée pour lui (SMS et WhatsApp : architecture prête, fournisseur à choisir).';
insert into logistics.notification_channel (code, enabled, provider, max_attempts, backoff_seconds) values
  ('in_app', true, 'base', 1, 60), ('push', true, 'expo', 5, 60), ('email', true, 'brevo', 5, 120), ('sms', false, '', 5, 60), ('whatsapp', false, '', 5, 60)
on conflict (code) do nothing;

-- 2. Les modèles, dans les quatre langues -------------------------------------------------------------------------------------------------
create table if not exists logistics.notification_template (
  code       text not null,
  language   text not null check (language in ('fr', 'en', 'es', 'ht')),
  title      text not null check (char_length(title) between 1 and 120),
  body       text not null check (char_length(body) between 1 and 600),
  active     boolean not null default true,
  version    int not null default 1,
  updated_at timestamptz not null default now(),
  primary key (code, language)
);
comment on table logistics.notification_template is 'Le texte d''une notification, par langue. Écrit par outils/portail-textes.py (même table que les textes du portail) : ne pas modifier à la main.';

-- (les modèles eux-mêmes sont insérés plus bas, après le garde qui vérifie leurs variables)

-- Les seules variables qu'un modèle peut citer : celles que le moteur sait remplir, et que le portail a le droit de montrer.
create or replace function logistics.nt_placeholders()
returns text[] language sql immutable set search_path = '' as $$
  select array['tracking_number', 'stage', 'shipment_code', 'invoice_number', 'amount', 'currency', 'date', 'message', 'code', 'expires_hours']
$$;

create or replace function logistics.guard_notification_template()
returns trigger language plpgsql set search_path = '' as $$
declare v text;
begin
  for v in select (regexp_matches(new.title || ' ' || new.body, '\{([a-z_]+)\}', 'g'))[1] loop
    if not (v = any (logistics.nt_placeholders())) then raise exception 'Variable inconnue dans le modèle % (%) : {%}.', new.code, new.language, v using errcode = 'LG005'; end if;
  end loop;
  if tg_op = 'UPDATE' and (new.title, new.body) is distinct from (old.title, old.body) then new.version := old.version + 1; new.updated_at := now(); end if;
  return new;
end;
$$;
drop trigger if exists guard_notification_template on logistics.notification_template;
create trigger guard_notification_template before insert or update on logistics.notification_template for each row execute function logistics.guard_notification_template();

-- modeles:debut
-- Écrit par outils/portail-textes.py : ne pas modifier à la main.
insert into logistics.notification_template (code, language, title, body) values
  ('ParcelReceived', 'fr', 'Colis reçu', 'Votre colis {tracking_number} est arrivé à l''entrepôt.'),
  ('ParcelReceived', 'en', 'Parcel received', 'Your parcel {tracking_number} has arrived at the warehouse.'),
  ('ParcelReceived', 'es', 'Paquete recibido', 'Su paquete {tracking_number} ha llegado al almacén.'),
  ('ParcelReceived', 'ht', 'Kolis resevwa', 'Kolis ou a {tracking_number} rive nan depo a.'),
  ('ParcelInTransit', 'fr', 'Colis en route', 'Votre colis {tracking_number} est en route.'),
  ('ParcelInTransit', 'en', 'Parcel on its way', 'Your parcel {tracking_number} is on its way.'),
  ('ParcelInTransit', 'es', 'Paquete en camino', 'Su paquete {tracking_number} está en camino.'),
  ('ParcelInTransit', 'ht', 'Kolis sou wout', 'Kolis ou a {tracking_number} sou wout.'),
  ('ParcelArrived', 'fr', 'Colis arrivé', 'Votre colis {tracking_number} est arrivé à destination : il passe la douane.'),
  ('ParcelArrived', 'en', 'Parcel arrived', 'Your parcel {tracking_number} has arrived at its destination: it is going through customs.'),
  ('ParcelArrived', 'es', 'Paquete llegado', 'Su paquete {tracking_number} ha llegado a destino: pasa la aduana.'),
  ('ParcelArrived', 'ht', 'Kolis rive', 'Kolis ou a {tracking_number} rive : l ap pase dwàn.'),
  ('CustomsCleared', 'fr', 'Colis dédouané', 'Votre colis {tracking_number} est dédouané.'),
  ('CustomsCleared', 'en', 'Parcel cleared', 'Your parcel {tracking_number} has cleared customs.'),
  ('CustomsCleared', 'es', 'Paquete despachado', 'Su paquete {tracking_number} ha sido despachado en aduana.'),
  ('CustomsCleared', 'ht', 'Kolis pase dwàn', 'Kolis ou a {tracking_number} pase dwàn.'),
  ('ParcelAtDestinationHub', 'fr', 'Colis disponible', 'Votre colis {tracking_number} est disponible au hub.'),
  ('ParcelAtDestinationHub', 'en', 'Package available', 'Your parcel {tracking_number} is available at the hub.'),
  ('ParcelAtDestinationHub', 'es', 'Paquete disponible', 'Su paquete {tracking_number} está disponible en el hub.'),
  ('ParcelAtDestinationHub', 'ht', 'Kolis disponib', 'Kolis ou a {tracking_number} disponib nan hub la.'),
  ('OutForDelivery', 'fr', 'Colis en livraison', 'Votre colis {tracking_number} est en cours de livraison.'),
  ('OutForDelivery', 'en', 'Parcel out for delivery', 'Your parcel {tracking_number} is out for delivery.'),
  ('OutForDelivery', 'es', 'Paquete en reparto', 'Su paquete {tracking_number} está en reparto.'),
  ('OutForDelivery', 'ht', 'Kolis ap livre', 'Kolis ou a {tracking_number} ap livre.'),
  ('Delivered', 'fr', 'Colis livré', 'Votre colis {tracking_number} a été livré.'),
  ('Delivered', 'en', 'Package delivered', 'Your parcel {tracking_number} has been delivered.'),
  ('Delivered', 'es', 'Paquete entregado', 'Su paquete {tracking_number} ha sido entregado.'),
  ('Delivered', 'ht', 'Kolis livre', 'Kolis ou a {tracking_number} livre.'),
  ('ParcelOnHold', 'fr', 'Colis en attente', 'Votre colis {tracking_number} est en attente. Notre équipe vous contactera si besoin.'),
  ('ParcelOnHold', 'en', 'Parcel on hold', 'Your parcel {tracking_number} is on hold. Our team will contact you if needed.'),
  ('ParcelOnHold', 'es', 'Paquete en espera', 'Su paquete {tracking_number} está en espera. Nuestro equipo le contactará si es necesario.'),
  ('ParcelOnHold', 'ht', 'Kolis an atant', 'Kolis ou a {tracking_number} an atant. Ekip nou an ap kontakte w si sa nesesè.'),
  ('ParcelDamaged', 'fr', 'Incident sur un colis', 'Un incident est signalé sur votre colis {tracking_number}. Notre équipe s''en occupe.'),
  ('ParcelDamaged', 'en', 'Issue with a parcel', 'An issue has been reported on your parcel {tracking_number}. Our team is handling it.'),
  ('ParcelDamaged', 'es', 'Incidencia en un paquete', 'Se ha señalado una incidencia en su paquete {tracking_number}. Nuestro equipo se encarga.'),
  ('ParcelDamaged', 'ht', 'Pwoblèm sou yon kolis', 'Yo siyale yon pwoblèm sou kolis ou a {tracking_number}. Ekip nou an ap okipe l.'),
  ('ParcelLost', 'fr', 'Colis perdu', 'Votre colis {tracking_number} est déclaré perdu. Notre équipe vous contacte.'),
  ('ParcelLost', 'en', 'Parcel lost', 'Your parcel {tracking_number} has been declared lost. Our team will contact you.'),
  ('ParcelLost', 'es', 'Paquete perdido', 'Su paquete {tracking_number} ha sido declarado perdido. Nuestro equipo le contactará.'),
  ('ParcelLost', 'ht', 'Kolis pèdi', 'Yo deklare kolis ou a {tracking_number} pèdi. Ekip nou an ap kontakte w.'),
  ('ParcelReturned', 'fr', 'Colis retourné', 'Votre colis {tracking_number} est retourné à l''expéditeur.'),
  ('ParcelReturned', 'en', 'Parcel returned', 'Your parcel {tracking_number} has been returned to the sender.'),
  ('ParcelReturned', 'es', 'Paquete devuelto', 'Su paquete {tracking_number} ha sido devuelto al remitente.'),
  ('ParcelReturned', 'ht', 'Kolis retounen', 'Kolis ou a {tracking_number} retounen bay moun ki voye l la.'),
  ('InvoiceIssued', 'fr', 'Nouvelle facture', 'Nouvelle facture {invoice_number} : {amount} {currency}, à régler avant le {date}.'),
  ('InvoiceIssued', 'en', 'New invoice', 'New invoice {invoice_number}: {amount} {currency}, due by {date}.'),
  ('InvoiceIssued', 'es', 'Nueva factura', 'Nueva factura {invoice_number}: {amount} {currency}, a pagar antes del {date}.'),
  ('InvoiceIssued', 'ht', 'Nouvo fakti', 'Nouvo fakti {invoice_number} : {amount} {currency}, pou peye anvan {date}.'),
  ('InvoiceOverdue', 'fr', 'Facture en retard', 'La facture {invoice_number} est en retard de paiement : il reste {amount} {currency}.'),
  ('InvoiceOverdue', 'en', 'Overdue invoice', 'Invoice {invoice_number} is overdue: {amount} {currency} remain to be paid.'),
  ('InvoiceOverdue', 'es', 'Factura vencida', 'La factura {invoice_number} está vencida: quedan {amount} {currency} por pagar.'),
  ('InvoiceOverdue', 'ht', 'Fakti an reta', 'Fakti {invoice_number} an reta : rete {amount} {currency} pou peye.'),
  ('PaymentReceived', 'fr', 'Paiement reçu', 'Paiement reçu : {amount} {currency} pour la facture {invoice_number}. Merci !'),
  ('PaymentReceived', 'en', 'Payment received', 'Payment received: {amount} {currency} for invoice {invoice_number}. Thank you!'),
  ('PaymentReceived', 'es', 'Pago recibido', 'Pago recibido: {amount} {currency} para la factura {invoice_number}. ¡Gracias!'),
  ('PaymentReceived', 'ht', 'Peman resevwa', 'Nou resevwa peman an : {amount} {currency} pou fakti {invoice_number}. Mèsi !'),
  ('PickupRequestApproved', 'fr', 'Enlèvement accepté', 'Votre demande d''enlèvement est acceptée pour le {date}. {message}'),
  ('PickupRequestApproved', 'en', 'Pickup accepted', 'Your pickup request is accepted for {date}. {message}'),
  ('PickupRequestApproved', 'es', 'Recogida aceptada', 'Su solicitud de recogida está aceptada para el {date}. {message}'),
  ('PickupRequestApproved', 'ht', 'Ranmasaj aksepte', 'Demann ranmasaj ou a aksepte pou {date}. {message}'),
  ('PickupRequestRejected', 'fr', 'Enlèvement refusé', 'Votre demande d''enlèvement n''a pas pu être acceptée : {message}'),
  ('PickupRequestRejected', 'en', 'Pickup refused', 'Your pickup request could not be accepted: {message}'),
  ('PickupRequestRejected', 'es', 'Recogida rechazada', 'Su solicitud de recogida no pudo ser aceptada: {message}'),
  ('PickupRequestRejected', 'ht', 'Ranmasaj refize', 'Nou pa t ka aksepte demann ranmasaj ou a : {message}'),
  ('DeliveryRequestApproved', 'fr', 'Livraison planifiée', 'Votre livraison est planifiée pour le {date}. {message}'),
  ('DeliveryRequestApproved', 'en', 'Delivery scheduled', 'Your delivery is scheduled for {date}. {message}'),
  ('DeliveryRequestApproved', 'es', 'Entrega programada', 'Su entrega está planificada para el {date}. {message}'),
  ('DeliveryRequestApproved', 'ht', 'Livrezon planifye', 'Livrezon ou a planifye pou {date}. {message}'),
  ('DeliveryRequestRejected', 'fr', 'Livraison refusée', 'Votre demande de livraison n''a pas pu être acceptée : {message}'),
  ('DeliveryRequestRejected', 'en', 'Delivery refused', 'Your delivery request could not be accepted: {message}'),
  ('DeliveryRequestRejected', 'es', 'Entrega rechazada', 'Su solicitud de entrega no pudo ser aceptada: {message}'),
  ('DeliveryRequestRejected', 'ht', 'Livrezon refize', 'Nou pa t ka aksepte demann livrezon ou a : {message}'),
  ('SupportTicketAnswered', 'fr', 'Réponse du support', 'Notre équipe a répondu à votre message.'),
  ('SupportTicketAnswered', 'en', 'Support reply', 'Our team has replied to your message.'),
  ('SupportTicketAnswered', 'es', 'Respuesta del soporte', 'Nuestro equipo ha respondido a su mensaje.'),
  ('SupportTicketAnswered', 'ht', 'Repons sipò a', 'Ekip nou an reponn mesaj ou a.'),
  ('DeliveryOtp', 'fr', 'Votre code de livraison', 'Code de livraison : {code} (valable {expires_hours} h). Ne le donnez au livreur qu''au moment de la remise du colis.'),
  ('DeliveryOtp', 'en', 'Your delivery code', 'Delivery code: {code} (valid {expires_hours} h). Only give it to the courier when you receive the parcel.'),
  ('DeliveryOtp', 'es', 'Su código de entrega', 'Código de entrega: {code} (válido {expires_hours} h). Solo dáselo al repartidor al recibir el paquete.'),
  ('DeliveryOtp', 'ht', 'Kòd livrezon ou', 'Kòd livrezon : {code} (valab {expires_hours} è). Pa bay livrè a li sof le w ap resevwa kolis la.')
on conflict (code, language) do update set title = excluded.title, body = excluded.body
  where (logistics.notification_template.title, logistics.notification_template.body) is distinct from (excluded.title, excluded.body);
-- modeles:fin

-- 3. Les règles : quel événement prévient le client, par quels canaux -----------------------------------------------------------------------
create table if not exists logistics.notification_rule (
  event_type text primary key references logistics.event_type (code) on delete restrict,
  template   text not null,
  channels   text[] not null check (channels <@ array['in_app', 'push', 'email', 'sms', 'whatsapp'] and cardinality(channels) > 0),
  active     boolean not null default true
);
insert into logistics.notification_rule (event_type, template, channels) values
  ('ParcelReceived',          'ParcelReceived',          array['in_app', 'push', 'email']),
  ('ParcelInTransit',         'ParcelInTransit',         array['in_app', 'push']),
  ('ParcelArrived',           'ParcelArrived',           array['in_app', 'push']),
  ('CustomsCleared',          'CustomsCleared',          array['in_app', 'push']),
  ('ParcelAtDestinationHub',  'ParcelAtDestinationHub',  array['in_app', 'push', 'email', 'sms']),
  ('OutForDelivery',          'OutForDelivery',          array['in_app', 'push', 'sms']),
  ('Delivered',               'Delivered',               array['in_app', 'push', 'email']),
  ('ParcelOnHold',            'ParcelOnHold',            array['in_app', 'push', 'email']),
  ('ParcelDamaged',           'ParcelDamaged',           array['in_app', 'push', 'email']),
  ('ParcelLost',              'ParcelLost',              array['in_app', 'email']),
  ('ParcelReturned',          'ParcelReturned',          array['in_app', 'push', 'email']),
  ('InvoiceIssued',           'InvoiceIssued',           array['in_app', 'email']),
  ('InvoiceOverdue',          'InvoiceOverdue',          array['in_app', 'email']),
  ('PaymentReceived',         'PaymentReceived',         array['in_app', 'email']),
  ('PickupRequestApproved',   'PickupRequestApproved',   array['in_app', 'push', 'email']),
  ('PickupRequestRejected',   'PickupRequestRejected',   array['in_app', 'push', 'email']),
  ('DeliveryRequestApproved', 'DeliveryRequestApproved', array['in_app', 'push', 'email']),
  ('DeliveryRequestRejected', 'DeliveryRequestRejected', array['in_app', 'push', 'email']),
  ('SupportTicketAnswered',   'SupportTicketAnswered',   array['in_app', 'push', 'email'])
on conflict (event_type) do nothing;

-- 4. Les préférences du client (absentes = réglage par défaut du canal) -----------------------------------------------------------------------
create table if not exists logistics.notification_preference (
  customer_id uuid not null references logistics.customer (id) on delete restrict,
  channel     text not null check (channel in ('push', 'email', 'sms', 'whatsapp')),   -- « in_app » ne se coupe pas : c'est le portail lui-même
  enabled     boolean not null,
  updated_at  timestamptz not null default now(),
  primary key (customer_id, channel)
);
create or replace function logistics.nt_wants(p_customer uuid, p_channel text)
returns boolean language sql stable set search_path = '' as $$
  select case when p_channel = 'in_app' then true
              else coalesce((select p.enabled from logistics.notification_preference p where p.customer_id = p_customer and p.channel = p_channel),
                            p_channel in ('push', 'email')) end     -- SMS et WhatsApp : seulement si le client l'a demandé
$$;

-- 5. La notification elle-même : le texte figé, l'état de l'envoi ----------------------------------------------------------------------------
alter table logistics.notification add column if not exists language        text;
alter table logistics.notification add column if not exists title           text;
alter table logistics.notification add column if not exists body            text;
alter table logistics.notification add column if not exists attempts        int not null default 0;
alter table logistics.notification add column if not exists next_attempt_at timestamptz not null default now();
alter table logistics.notification add column if not exists locked_until    timestamptz;
alter table logistics.notification add column if not exists last_error      text;
alter table logistics.notification add column if not exists provider_ref    text;
create index if not exists notification_due_idx on logistics.notification (status, channel, next_attempt_at) where status = 'PENDING';

create table if not exists logistics.notification_attempt (
  id              bigint generated always as identity primary key,
  notification_id bigint not null references logistics.notification (id) on delete restrict,
  attempt         int not null,
  at              timestamptz not null default now(),
  outcome         text not null check (outcome in ('SENT', 'RETRY', 'FAILED', 'SKIPPED')),
  provider_ref    text,
  error           text,
  worker          text not null default ''
);
create index if not exists notification_attempt_idx on logistics.notification_attempt (notification_id, id);
comment on table logistics.notification_attempt is 'Le journal de livraison : un essai, une ligne. En ajout seul.';
drop trigger if exists notification_attempt_append_only on logistics.notification_attempt;
create trigger notification_attempt_append_only before update or delete on logistics.notification_attempt for each row execute function logistics.forbid_mutation();

-- Une erreur de fournisseur peut contenir une clé ou un jeton : on la tronque, et on masque tout ce qui y ressemble.
create or replace function logistics.nt_clean(p_error text)
returns text language sql immutable set search_path = '' as $$
  select nullif(left(regexp_replace(regexp_replace(coalesce(p_error, ''), '(xkeysib-|xsmtpsib-|sb_secret_|sk_live_|eyJ)[A-Za-z0-9._-]+', '[masqué]', 'g'),
                                     'ExponentPushToken\[[^\]]*\]', 'ExponentPushToken[masqué]', 'g'), 300), '')
$$;

-- Remplir les {variables} d'un modèle. Une variable sans valeur devient vide (le modèle reste lisible).
create or replace function logistics.nt_render(p_text text, p_values jsonb)
returns text language plpgsql immutable set search_path = '' as $$
declare v text; o text := p_text;
begin
  foreach v in array logistics.nt_placeholders() loop
    o := replace(o, '{' || v || '}', coalesce(p_values ->> v, ''));
  end loop;
  return o;
end;
$$;

-- 6. Le moteur : un abonné interne du moteur d'événements (phase 6) -----------------------------------------------------------------------------
create or replace function logistics.nt_customer_of(ev logistics.domain_event)
returns uuid language plpgsql stable set search_path = '' as $$
declare v uuid;
begin
  if ev.aggregate_type = 'parcel' then select p.customer_id into v from logistics.parcel p where p.id::text = ev.aggregate_id;
  elsif ev.aggregate_type = 'invoice' then select i.customer_id into v from logistics.invoice i where i.id::text = ev.aggregate_id;
  elsif ev.aggregate_type = 'payment' then select p.customer_id into v from logistics.payment p where p.id::text = ev.aggregate_id;
  elsif ev.payload ? 'customer_id' then v := nullif(ev.payload ->> 'customer_id', '')::uuid;
  end if;
  return v;
exception when others then return null;
end;
$$;

-- Les valeurs qu'un événement apporte à son modèle : seulement les variables permises, jamais de donnée interne.
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
  end if;
  return jsonb_strip_nulls(o);
end;
$$;

-- Ce canal peut-il atteindre ce client ? (allumé, voulu, et une adresse où l'atteindre)
create or replace function logistics.nt_reachable(c logistics.customer, p_channel text)
returns boolean language sql stable set search_path = '' as $$
  select coalesce((select ch.enabled from logistics.notification_channel ch where ch.code = p_channel), false)
     and logistics.nt_wants(c.id, p_channel)
     and case p_channel
           when 'in_app' then c.auth_user_id is not null
           when 'email' then coalesce(btrim(c.email), '') <> ''
           when 'push' then exists (select 1 from logistics.device d where d.owner_customer_id = c.id and d.active and d.push_token is not null)
           else coalesce(btrim(c.phone), '') <> '' end
$$;

create or replace function logistics.handle_notification_engine(ev logistics.domain_event)
returns void language plpgsql set search_path = '' as $$
declare r logistics.notification_rule; c logistics.customer; v_ch text; v_vals jsonb; t logistics.notification_template; v_parcel uuid;
begin
  select * into r from logistics.notification_rule where event_type = ev.event_type and active;
  if not found then return; end if;
  select * into c from logistics.customer where id = logistics.nt_customer_of(ev);
  if not found or c.source = 'legacy_staff_account' then return; end if;       -- l'équipe n'est pas la clientèle
  v_vals := logistics.nt_values(ev);
  v_parcel := case when ev.aggregate_type = 'parcel' then ev.aggregate_id::uuid end;
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

insert into logistics.event_subscriber (code, kind, event_types, handler)
select 'notification_engine', 'internal', array_agg(event_type order by event_type), 'logistics.handle_notification_engine'::regproc from logistics.notification_rule
on conflict (code) do update set event_types = excluded.event_types, handler = excluded.handler
  where logistics.event_subscriber.event_types is distinct from excluded.event_types or logistics.event_subscriber.handler is distinct from excluded.handler;
-- L'ancien planificateur (phase 6) ne faisait que des « push » sans texte : le moteur le remplace.
update logistics.event_subscriber set active = false where code = 'notification_planner' and active;

-- Le code de livraison (phase 9) part par WhatsApp vers le destinataire. Tant que WhatsApp n'a pas de fournisseur, il est RELAYÉ au client :
-- dans son portail et par e-mail. L'original est marqué « non envoyé », avec la raison.
create or replace function logistics.nt_relay_otp()
returns trigger language plpgsql security definer set search_path = '' as $$
declare c logistics.customer; v_vals jsonb; t logistics.notification_template; v_ch text;
begin
  if new.template <> 'DeliveryOtp' or new.channel in ('in_app', 'email') or new.status <> 'PENDING' then return null; end if;
  if coalesce((select enabled from logistics.notification_channel where code = new.channel), false) then return null; end if;
  select * into c from logistics.customer where id = new.customer_id;
  v_vals := jsonb_build_object('code', new.payload ->> 'code', 'expires_hours', new.payload ->> 'expires_hours');
  foreach v_ch in array array['in_app', 'email'] loop
    continue when not logistics.nt_reachable(c, v_ch);
    select * into t from logistics.notification_template x where x.code = 'DeliveryOtp' and x.language = coalesce(c.language, 'fr') and x.active;
    if not found then select * into t from logistics.notification_template x where x.code = 'DeliveryOtp' and x.language = 'fr' and x.active; end if;
    continue when not found;
    insert into logistics.notification (customer_id, channel, template, payload, language, title, body, status, sent_at)
    values (c.id, v_ch, 'DeliveryOtp', v_vals, t.language, logistics.nt_render(t.title, v_vals), logistics.nt_render(t.body, v_vals),
            case when v_ch = 'in_app' then 'SENT' else 'PENDING' end, case when v_ch = 'in_app' then now() end);
  end loop;
  update logistics.notification set status = 'SKIPPED', last_error = 'Canal ' || new.channel || ' sans fournisseur : code relayé au client (portail, e-mail).' where id = new.id;
  insert into logistics.notification_attempt (notification_id, attempt, outcome, error, worker) values (new.id, 0, 'SKIPPED', 'canal sans fournisseur', 'base');
  return null;
end;
$$;
drop trigger if exists nt_relay_otp on logistics.notification;
create trigger nt_relay_otp after insert on logistics.notification for each row execute function logistics.nt_relay_otp();

-- 7. Le travailleur : réclamer, envoyer, rendre compte (clé secrète seulement, jamais un navigateur) -------------------------------------------
create or replace function logistics.nt_claim(p_worker text, p_channels text[], p_limit int default 20, p_lease_seconds int default 120)
returns table (notification_id bigint, channel text, attempt int, language text, title text, body text, template text, recipient jsonb)
language plpgsql volatile security definer set search_path = '' as $$
declare n record; c logistics.customer; v_rec jsonb;
begin
  if coalesce(btrim(p_worker), '') = '' then raise exception 'Nommez le travailleur.' using errcode = 'LG005'; end if;
  for n in
    select x.* from logistics.notification x join logistics.notification_channel ch on ch.code = x.channel and ch.enabled
     where x.status = 'PENDING' and x.channel <> 'in_app' and x.channel = any (coalesce(p_channels, array['push', 'email', 'sms', 'whatsapp']))
       and x.next_attempt_at <= now() and (x.locked_until is null or x.locked_until < now())
     order by x.next_attempt_at, x.id
     limit least(greatest(coalesce(p_limit, 20), 1), 200)
     for update of x skip locked
  loop
    select * into c from logistics.customer where id = n.customer_id;
    v_rec := case n.channel
      when 'email' then case when coalesce(btrim(c.email), '') <> '' then jsonb_build_object('email', c.email, 'name', c.full_name) end
      when 'push' then (select case when count(*) > 0 then jsonb_build_object('tokens', jsonb_agg(d.push_token order by d.push_token)) end
                          from logistics.device d where d.owner_customer_id = c.id and d.active and d.push_token is not null)
      else case when coalesce(n.payload ->> 'recipient_phone', c.phone, '') <> '' then jsonb_build_object('phone', coalesce(nullif(n.payload ->> 'recipient_phone', ''), c.phone)) end end;
    if v_rec is null then
      -- l'adresse a disparu depuis la création (appareil retiré, e-mail effacé) : rien à envoyer, et on le dit
      update logistics.notification x set status = 'SKIPPED', last_error = 'Plus de destinataire pour ce canal.', locked_until = null where x.id = n.id;
      insert into logistics.notification_attempt (notification_id, attempt, outcome, error, worker) values (n.id, n.attempts + 1, 'SKIPPED', 'plus de destinataire', p_worker);
      continue;
    end if;
    update logistics.notification x set attempts = x.attempts + 1, locked_until = now() + make_interval(secs => least(greatest(coalesce(p_lease_seconds, 120), 10), 3600)) where x.id = n.id;
    notification_id := n.id; channel := n.channel; attempt := n.attempts + 1; language := n.language; title := n.title; body := n.body; template := n.template; recipient := v_rec;
    return next;
  end loop;
end;
$$;

create or replace function logistics.nt_report(p_id bigint, p_ok boolean, p_provider_ref text default null, p_error text default null, p_worker text default '', p_permanent boolean default false)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare n logistics.notification; ch logistics.notification_channel; v_wait int;
begin
  select * into n from logistics.notification where id = p_id for update;
  if not found then raise exception 'Notification introuvable.' using errcode = 'LG002'; end if;
  if n.status <> 'PENDING' or n.locked_until is null then raise exception 'Notification % : aucun envoi en cours.', p_id using errcode = 'LG004'; end if;
  select * into ch from logistics.notification_channel where code = n.channel;
  if coalesce(p_ok, false) then
    update logistics.notification set status = 'SENT', sent_at = now(), provider_ref = left(p_provider_ref, 200), locked_until = null, last_error = null where id = p_id;
    insert into logistics.notification_attempt (notification_id, attempt, outcome, provider_ref, worker) values (p_id, n.attempts, 'SENT', left(p_provider_ref, 200), coalesce(p_worker, ''));
    return jsonb_build_object('notification_id', p_id, 'status', 'SENT');
  end if;
  if coalesce(p_permanent, false) or n.attempts >= ch.max_attempts then
    update logistics.notification set status = 'FAILED', locked_until = null, last_error = logistics.nt_clean(p_error) where id = p_id;
    insert into logistics.notification_attempt (notification_id, attempt, outcome, error, worker) values (p_id, n.attempts, 'FAILED', logistics.nt_clean(p_error), coalesce(p_worker, ''));
    return jsonb_build_object('notification_id', p_id, 'status', 'FAILED');
  end if;
  v_wait := ch.backoff_seconds * power(2, greatest(n.attempts - 1, 0))::int;
  update logistics.notification set locked_until = null, last_error = logistics.nt_clean(p_error), next_attempt_at = now() + make_interval(secs => v_wait) where id = p_id;
  insert into logistics.notification_attempt (notification_id, attempt, outcome, error, worker) values (p_id, n.attempts, 'RETRY', logistics.nt_clean(p_error), coalesce(p_worker, ''));
  return jsonb_build_object('notification_id', p_id, 'status', 'PENDING', 'retry_in_seconds', v_wait);
end;
$$;

-- Un appareil dont le jeton est refusé par le service de notifications (« DeviceNotRegistered ») est désactivé, pas supprimé.
create or replace function logistics.nt_disable_tokens(p_tokens text[])
returns int language plpgsql volatile security definer set search_path = '' as $$
declare v int;
begin
  update logistics.device set active = false, updated_at = now() where push_token = any (coalesce(p_tokens, '{}')) and active;
  get diagnostics v = row_count;
  return v;
end;
$$;

-- 8. Le signal temps réel : « relisez », sans donnée métier ---------------------------------------------------------------------------------------
create table if not exists public.ses_signal (
  id         bigint generated always as identity primary key,
  audience   text not null check (audience in ('staff', 'customer')),
  user_id    uuid,
  topic      text not null check (topic ~ '^[a-z_]{1,30}$'),
  created_at timestamptz not null default now(),
  check ((audience = 'customer') = (user_id is not null))
);
comment on table public.ses_signal is 'Signal temps réel : un domaine a changé (colis, expédition, facture…). Aucune donnée : l''écran relit par les fonctions qui contrôlent les droits. Purgeable (logistics.purge_signals).';
create index if not exists ses_signal_user_idx on public.ses_signal (user_id, id) where audience = 'customer';
alter table public.ses_signal enable row level security;
revoke all on public.ses_signal from public, anon, authenticated;
grant select on public.ses_signal to authenticated;
drop policy if exists ses_signal_lecture on public.ses_signal;
create policy ses_signal_lecture on public.ses_signal for select to authenticated using (
  (audience = 'customer' and user_id = (select auth.uid()))
  or (audience = 'staff' and ((select public.a_droit('colis.lire')) or (select public.a_droit('clients.lire')) or (select public.a_droit('factures.lire')))));

create or replace function logistics.nt_signal()
returns trigger language plpgsql security definer set search_path = '' as $$
declare v_user uuid; v_topic text := lower(new.aggregate_type);
begin
  begin
    insert into public.ses_signal (audience, topic) values ('staff', v_topic);
    select c.auth_user_id into v_user from logistics.customer c where c.id = logistics.nt_customer_of(new) and c.source <> 'legacy_staff_account';
    if v_user is not null then insert into public.ses_signal (audience, user_id, topic) values ('customer', v_user, v_topic); end if;
  exception when others then
    null;   -- un signal manqué n'est qu'un rafraîchissement manqué : jamais une raison d'annuler l'opération métier
  end;
  return null;
end;
$$;
drop trigger if exists nt_signal on logistics.domain_event;
create trigger nt_signal after insert on logistics.domain_event for each row execute function logistics.nt_signal();

-- Le temps réel de Supabase diffuse les insertions de cette table (si la publication existe : en local, elle n'existe pas).
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'ses_signal') then
    execute 'alter publication supabase_realtime add table public.ses_signal';
  end if;
end
$$;

create or replace function logistics.purge_signals(p_keep interval default interval '2 days')
returns int language plpgsql volatile security definer set search_path = '' as $$
declare v int;
begin
  if p_keep < interval '1 hour' then raise exception 'Gardez au moins une heure de signaux.' using errcode = 'LG005'; end if;
  delete from public.ses_signal where created_at < now() - p_keep;
  get diagnostics v = row_count;
  return v;
end;
$$;

-- 9. Ce que le client règle, ce que l'équipe surveille ---------------------------------------------------------------------------------------------
create or replace function logistics.my_notification_prefs(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid := logistics.my_customer(p_user);
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if v_c is null then return '[]'::jsonb; end if;
  return (select jsonb_agg(jsonb_build_object('channel', ch.code, 'available', ch.enabled, 'enabled', logistics.nt_wants(v_c, ch.code), 'locked', ch.code = 'in_app') order by ch.code)
            from logistics.notification_channel ch);
end;
$$;

create or replace function logistics.set_notification_pref(p_user uuid, p_channel text, p_enabled boolean)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid := logistics.require_customer(p_user); v_avant boolean;
begin
  if p_channel is null or p_channel not in ('push', 'email', 'sms', 'whatsapp') then raise exception 'Canal inconnu, ou qui ne se coupe pas.' using errcode = 'LG005'; end if;
  if p_enabled is null then raise exception 'Choisissez : oui ou non.' using errcode = 'LG005'; end if;
  v_avant := logistics.nt_wants(v_c, p_channel);
  insert into logistics.notification_preference (customer_id, channel, enabled) values (v_c, p_channel, p_enabled)
  on conflict (customer_id, channel) do update set enabled = excluded.enabled, updated_at = now();
  if v_avant is distinct from p_enabled then
    perform logistics.cust_audit(v_c, 'notification.preference', 'customer', v_c::text, jsonb_build_object(p_channel, v_avant), jsonb_build_object(p_channel, p_enabled), gen_random_uuid());
  end if;
  return logistics.my_notification_prefs(p_user);
end;
$$;

-- La santé des envois, pour le centre de commande (droit « colis.lire ») : rien de personnel, seulement des comptes et des erreurs nettoyées.
create or replace function logistics.cc_notification_health(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  return jsonb_build_object('as_of', now(),
    'channels', coalesce((select jsonb_agg(jsonb_build_object('channel', ch.code, 'enabled', ch.enabled, 'provider', ch.provider,
        'pending', (select count(*) from logistics.notification n where n.channel = ch.code and n.status = 'PENDING' and (n.locked_until is null or n.locked_until < now())),
        'sending', (select count(*) from logistics.notification n where n.channel = ch.code and n.status = 'PENDING' and n.locked_until >= now()),
        'sent_24h', (select count(*) from logistics.notification n where n.channel = ch.code and n.status = 'SENT' and n.sent_at >= now() - interval '24 hours'),
        'failed_24h', (select count(*) from logistics.notification_attempt a join logistics.notification n on n.id = a.notification_id where n.channel = ch.code and a.outcome = 'FAILED' and a.at >= now() - interval '24 hours'),
        'retries_24h', (select count(*) from logistics.notification_attempt a join logistics.notification n on n.id = a.notification_id where n.channel = ch.code and a.outcome = 'RETRY' and a.at >= now() - interval '24 hours'),
        'oldest_pending_at', (select min(n.created_at) from logistics.notification n where n.channel = ch.code and n.status = 'PENDING')) order by ch.code)
      from logistics.notification_channel ch), '[]'::jsonb),
    'recent_errors', coalesce((select jsonb_agg(jsonb_build_object('at', x.at, 'channel', x.channel, 'template', x.template, 'outcome', x.outcome, 'error', x.error) order by x.at desc, x.id desc)
      from (select a.id, a.at, a.outcome, a.error, n.channel, n.template from logistics.notification_attempt a join logistics.notification n on n.id = a.notification_id
             where a.outcome in ('FAILED', 'RETRY') order by a.at desc, a.id desc limit 10) x), '[]'::jsonb),
    'events', (select jsonb_build_object('pending', count(*) filter (where status in ('PENDING', 'FAILED')), 'dead', count(*) filter (where status = 'DEAD')) from logistics.event_delivery));
end;
$$;

-- 10. Les façades ---------------------------------------------------------------------------------------------------------------------------------------
create or replace function public.lg_my_notification_prefs() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_notification_prefs(auth.uid()) $$;
create or replace function public.lg_set_notification_pref(p_channel text, p_enabled boolean) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.set_notification_pref(auth.uid(), p_channel, p_enabled) $$;
create or replace function public.lg_cc_notification_health() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_notification_health(auth.uid()) $$;
-- Le travailleur (clé secrète). Préfixe « ses_nt_ » : JAMAIS « lg_ », que les migrations ouvrent aux comptes connectés.
create or replace function public.ses_nt_dispatch(p_limit int default 500) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.dispatch_events(p_limit, null) $$;
create or replace function public.ses_nt_claim(p_worker text, p_channels text[] default null, p_limit int default 20, p_lease_seconds int default 120)
returns table (notification_id bigint, channel text, attempt int, language text, title text, body text, template text, recipient jsonb)
language sql volatile security definer set search_path = '' as $$ select * from logistics.nt_claim(p_worker, p_channels, p_limit, p_lease_seconds) $$;
create or replace function public.ses_nt_report(p_id bigint, p_ok boolean, p_provider_ref text default null, p_error text default null, p_worker text default '', p_permanent boolean default false)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.nt_report(p_id, p_ok, p_provider_ref, p_error, p_worker, p_permanent) $$;
create or replace function public.ses_nt_disable_tokens(p_tokens text[]) returns int language sql volatile security definer set search_path = '' as $$ select logistics.nt_disable_tokens(p_tokens) $$;
create or replace function public.ses_nt_purge_signals() returns int language sql volatile security definer set search_path = '' as $$ select logistics.purge_signals(interval '2 days') $$;


-- 11. Tout fermé, sauf la façade ; le travailleur, seulement pour la clé secrète ---------------------------------------------------------------------------
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
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'ses\_nt\_%' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to service_role', r.sig);
  end loop;
end
$$;
revoke all on logistics.event_health, logistics.pickup_task, logistics.delivery_task, logistics.customer_balance from public, anon, authenticated;
grant select on logistics.event_health to service_role;

-- Pour retirer SEULEMENT cette étape : supprimer les fonctions public.ses_nt_*, public.lg_my_notification_prefs, public.lg_set_notification_pref,
-- public.lg_cc_notification_health, les déclencheurs nt_signal (logistics.domain_event) et nt_relay_otp (logistics.notification), réactiver
-- l'abonné « notification_planner » et désactiver « notification_engine ». Les tables notification_channel, notification_template,
-- notification_rule, notification_preference, notification_attempt et public.ses_signal peuvent rester (vides de sens sans le moteur).
