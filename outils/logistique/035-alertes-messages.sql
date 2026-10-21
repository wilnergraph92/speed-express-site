-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 35 : les alertes d'un nouveau message
-- -----------------------------------------------------------------------------
-- À passer APRÈS 034, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Demande du propriétaire (21/10/2026) : « validé alertes d'un nouveau message ». La messagerie (032) prévient maintenant hors de
-- l'application, par le circuit des notifications (010, 027) — le même travailleur d'envoi, les mêmes canaux, les mêmes préférences :
--   1. le CLIENT, quand l'équipe lui écrit : notification sur le téléphone et e-mail, selon ses préférences (ChatMessage) ;
--   2. l'ÉQUIPE, quand un client ou un collègue lui écrit : notification sur le téléphone de SES Opérations (ChatMessageStaff). Le circuit
--      ne connaissait que des clients : une notification peut désormais viser un membre de l'équipe (recipient_user_id), et un téléphone de
--      l'équipe s'enregistre (lg_register_staff_device) ;
--   3. JAMAIS une alerte par ligne : au plus une toutes les dix minutes par destinataire et par conversation ; un message déjà lu n'en
--      déclenche plus ;
--   4. une alerte ne peut jamais faire échouer l'envoi d'un message (comme le signal temps réel).
-- Le texte de l'alerte : le prénom de qui écrit (le client ne voit jamais plus de l'équipe) et le début du message, 120 caractères.
-- Rien ne part réellement tant que le travailleur d'envoi n'est pas installé avec ses secrets (docs/architecture/NOTIFICATIONS.md §11).
-- Rejouable sans risque ; aucune suppression.
-- =============================================================================

-- 1. Une notification peut viser un membre de l'équipe ----------------------------------------------------------------------------------
alter table logistics.notification add column if not exists recipient_user_id uuid references logistics.app_user (id) on delete restrict;
alter table logistics.notification alter column customer_id drop not null;
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'notification_destinataire_check') then
    alter table logistics.notification add constraint notification_destinataire_check check (customer_id is not null or recipient_user_id is not null);
  end if;
end
$$;
create index if not exists notification_staff_idx on logistics.notification (recipient_user_id, created_at desc) where recipient_user_id is not null;
alter table logistics.notification add column if not exists conversation_id uuid references logistics.chat_conversation (id) on delete restrict;
create index if not exists notification_conversation_idx on logistics.notification (conversation_id, created_at desc) where conversation_id is not null;
comment on column logistics.notification.recipient_user_id is '035 : un membre de l''équipe (alerte de la messagerie) ; customer_id est alors vide.';

-- Un téléphone de l'équipe (SES Opérations)
alter table logistics.device drop constraint if exists device_kind_check;
alter table logistics.device add constraint device_kind_check check (kind in ('customer_push', 'staff_push', 'phone_camera', 'usb_scanner', 'desktop_scanner', 'handheld_scanner'));

-- Le destinataire, figé à la création (027) : aussi pour l'équipe.
create or replace function logistics.nt_fill_recipient()
returns trigger language plpgsql set search_path = '' as $$
begin
  if new.recipient is null then
    if new.customer_id is not null then
      new.recipient := left(logistics.nt_recipient_of(new.customer_id, new.channel, new.payload), 200);
    elsif new.channel = 'push' then
      new.recipient := 'appareils:' || (select count(*) from logistics.device d where d.owner_user_id = new.recipient_user_id and d.active and d.push_token is not null);
    elsif new.channel = 'email' then
      new.recipient := left((select a.email from auth.users a where a.id = new.recipient_user_id), 200);
    end if;
  end if;
  return new;
end;
$$;

-- Le travailleur prend une notification : l'adresse d'un client, ou celle d'un membre de l'équipe (ses téléphones, son e-mail). La même
-- fonction que 010, un destinataire de plus.
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
    if n.customer_id is null then
      -- 035 : un membre de l'équipe
      v_rec := case n.channel
        when 'email' then (select case when coalesce(btrim(a.email), '') <> '' then jsonb_build_object('email', a.email, 'name', logistics.chat_name(a.id)) end
                             from auth.users a where a.id = n.recipient_user_id)
        when 'push' then (select case when count(*) > 0 then jsonb_build_object('tokens', jsonb_agg(d.push_token order by d.push_token)) end
                            from logistics.device d where d.owner_user_id = n.recipient_user_id and d.active and d.push_token is not null) end;
    else
      select * into c from logistics.customer where id = n.customer_id;
      v_rec := case n.channel
        when 'email' then case when coalesce(btrim(c.email), '') <> '' then jsonb_build_object('email', c.email, 'name', c.full_name) end
        when 'push' then (select case when count(*) > 0 then jsonb_build_object('tokens', jsonb_agg(d.push_token order by d.push_token)) end
                            from logistics.device d where d.owner_customer_id = c.id and d.active and d.push_token is not null)
        else case when coalesce(n.payload ->> 'recipient_phone', c.phone, '') <> '' then jsonb_build_object('phone', coalesce(nullif(n.payload ->> 'recipient_phone', ''), c.phone)) end end;
    end if;
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

-- Les données d'un push (020) : une alerte de la messagerie ouvre la messagerie de l'application qui la reçoit.
create or replace function logistics.nt_push_data(p_ids bigint[])
returns jsonb language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_object_agg(n.id::text, jsonb_strip_nulls(jsonb_build_object(
           'template', n.template,
           'tracking_number', n.payload ->> 'tracking_number',
           'invoice_number', n.payload ->> 'invoice_number',
           'conversation_id', n.conversation_id,
           'url', case when n.template = 'ChatMessage' then 'speedexpress://messages'
                       when n.template = 'ChatMessageStaff' then 'speedexpressops://conversation/' || n.conversation_id
                       when n.payload ->> 'tracking_number' is not null then 'speedexpress://colis/' || (n.payload ->> 'tracking_number')
                       when n.payload ->> 'invoice_number' is not null then 'speedexpress://factures'
                       else 'speedexpress://notifications' end))), '{}'::jsonb)
    from logistics.notification n
   where n.id = any (coalesce(p_ids, '{}')) and n.channel = 'push'
$$;

-- 2. Les téléphones de l'équipe -----------------------------------------------------------------------------------------------------
create or replace function logistics.register_staff_device(p_user uuid, p_token text, p_platform text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_jeton text := btrim(coalesce(p_token, '')); v_id uuid; v_avant uuid;
begin
  if not logistics.chat_is_staff(p_user) then raise exception 'Réservé à l''équipe.' using errcode = 'LG003'; end if;
  if v_jeton !~ '^Expo(nent)?PushToken\[[A-Za-z0-9_-]{8,200}\]$' then raise exception 'Jeton de notification illisible.' using errcode = 'LG005'; end if;
  if p_platform not in ('ios', 'android') then raise exception 'Plateforme inconnue : %.', p_platform using errcode = 'LG005'; end if;
  perform ops.rate_limit(p_user, 'staff.device', 20, 3600);
  select id, owner_user_id into v_id, v_avant from logistics.device where push_token = v_jeton for update;
  if found then
    -- le même téléphone passé d'un compte à un autre : il ne reçoit plus que pour celui-ci
    update logistics.device set owner_user_id = p_user, owner_customer_id = null, kind = 'staff_push', platform = p_platform, active = true,
                                last_seen_at = now(), updated_at = now()
     where id = v_id;
  else
    insert into logistics.device (kind, platform, push_token, owner_user_id, label, active, last_seen_at, source)
    values ('staff_push', p_platform, v_jeton, p_user, 'SES Opérations', true, now(), 'native')
    returning id into v_id;
  end if;
  update logistics.device set active = false, updated_at = now()
   where id in (select id from logistics.device where owner_user_id = p_user and active and kind = 'staff_push'
                 order by last_seen_at desc nulls last, created_at desc offset 5);
  return jsonb_build_object('registered', true, 'platform', p_platform, 'reassigned', v_avant is not null and v_avant <> p_user);
end;
$$;

create or replace function logistics.unregister_staff_device(p_user uuid, p_token text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v int;
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  update logistics.device set active = false, updated_at = now() where push_token = btrim(coalesce(p_token, '')) and owner_user_id = p_user and active;
  get diagnostics v = row_count;
  return jsonb_build_object('unregistered', v > 0);
end;
$$;

-- 3. Les alertes d'un message --------------------------------------------------------------------------------------------------------
-- La langue d'un membre de l'équipe : celle de sa fiche (ancien schéma), sinon le français.
create or replace function logistics.chat_staff_language(p_user uuid)
returns text language sql stable security definer set search_path = '' as $$
  select coalesce((select case when c.langue in ('fr', 'en', 'es', 'ht') then c.langue end from public.clients c where c.id = p_user), 'fr')
$$;

create or replace function logistics.chat_alert(p_message bigint)
returns void language plpgsql volatile security definer set search_path = '' as $$
declare m logistics.chat_message; v logistics.chat_conversation; c logistics.customer; t logistics.notification_template; v_ch text; v_u uuid;
        v_apercu text; v_vals jsonb; v_lang text;
begin
  begin
    select * into m from logistics.chat_message where id = p_message;
    select * into v from logistics.chat_conversation where id = m.conversation_id;
    v_apercu := left(regexp_replace(btrim(coalesce(nullif(m.body, ''), '📷')), '\s+', ' ', 'g'), 120);

    -- a. Le client, quand l'équipe lui écrit : son téléphone et son e-mail, selon ses préférences ; le prénom de qui écrit.
    if v.kind = 'CUSTOMER' and m.author_kind = 'STAFF' then
      select * into c from logistics.customer where id = v.customer_id;
      v_vals := jsonb_build_object('message', logistics.chat_first_name(m.author_user_id) || ' : ' || v_apercu);
      foreach v_ch in array array['push', 'email'] loop
        continue when not logistics.nt_reachable(c, v_ch);
        -- au plus une toutes les dix minutes par conversation
        continue when exists (select 1 from logistics.notification x where x.customer_id = c.id and x.conversation_id = v.id and x.channel = v_ch
                                                                        and x.template = 'ChatMessage' and x.created_at > now() - interval '10 minutes');
        select * into t from logistics.notification_template x where x.code = 'ChatMessage' and x.language = coalesce(c.language, 'fr') and x.active;
        if not found then select * into t from logistics.notification_template x where x.code = 'ChatMessage' and x.language = 'fr' and x.active; end if;
        continue when not found;
        insert into logistics.notification (customer_id, conversation_id, channel, template, payload, language, title, body)
        values (c.id, v.id, v_ch, 'ChatMessage', v_vals, t.language, logistics.nt_render(t.title, v_vals), logistics.nt_render(t.body, v_vals));
      end loop;
    end if;

    -- b. L'équipe, sur son téléphone : les membres d'un direct ou d'un groupe ; pour un client, ceux qui lisent les clients. Jamais l'auteur.
    if coalesce((select ch.enabled from logistics.notification_channel ch where ch.code = 'push'), false) then
      for v_u in
        select m2.user_id from logistics.chat_member m2 where m2.conversation_id = v.id and m2.left_at is null and v.kind <> 'CUSTOMER'
        union
        -- (pour un client : seulement quand c'est LUI qui écrit ; la réponse d'un collègue n'alerte pas toute l'équipe)
        select u.id from logistics.app_user u where v.kind = 'CUSTOMER' and m.author_kind = 'CUSTOMER' and u.active and logistics.actor_can(u.id, 'clients.lire')
      loop
        continue when v_u = m.author_user_id;
        continue when not exists (select 1 from logistics.device d where d.owner_user_id = v_u and d.active and d.push_token is not null);
        -- déjà lu (il est dans la conversation) : rien ; sinon, au plus une toutes les dix minutes par conversation
        continue when coalesce((select r.last_read_id from logistics.chat_read r where r.conversation_id = v.id and r.user_id = v_u), 0) >= m.id;
        continue when exists (select 1 from logistics.notification x where x.recipient_user_id = v_u and x.conversation_id = v.id and x.template = 'ChatMessageStaff'
                                                                        and x.created_at > now() - interval '10 minutes');
        v_lang := logistics.chat_staff_language(v_u);
        select * into t from logistics.notification_template x where x.code = 'ChatMessageStaff' and x.language = v_lang and x.active;
        if not found then select * into t from logistics.notification_template x where x.code = 'ChatMessageStaff' and x.language = 'fr' and x.active; end if;
        continue when not found;
        v_vals := jsonb_build_object('message', logistics.chat_name(m.author_user_id)
                                                || case when v.kind = 'GROUP' then ' (' || v.title || ')' else '' end || ' : ' || v_apercu);
        insert into logistics.notification (recipient_user_id, conversation_id, channel, template, payload, language, title, body)
        values (v_u, v.id, 'push', 'ChatMessageStaff', v_vals, t.language, logistics.nt_render(t.title, v_vals), logistics.nt_render(t.body, v_vals));
      end loop;
    end if;
  exception when others then
    null;   -- une alerte manquée n'est jamais une raison d'annuler un message
  end;
end;
$$;

create or replace function logistics.chat_alert_trigger()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  perform logistics.chat_alert(new.id);
  return null;
end;
$$;
drop trigger if exists chat_alert on logistics.chat_message;
create trigger chat_alert after insert on logistics.chat_message for each row execute function logistics.chat_alert_trigger();

-- 4. Les modèles (les mêmes textes que le portail : écrits par outils/portail-textes.py) ------------------------------------------------------
-- modeles:debut
-- Écrit par outils/portail-textes.py : ne pas modifier à la main.
insert into logistics.notification_template (code, language, title, body) values
  ('ChatMessage', 'fr', 'Nouveau message de Speed Express', 'Vous avez un message : {message} — Ouvrez l''application Speed Express pour répondre.'),
  ('ChatMessage', 'en', 'New message from Speed Express', 'You have a message: {message} — Open the Speed Express app to reply.'),
  ('ChatMessage', 'es', 'Nuevo mensaje de Speed Express', 'Tiene un mensaje: {message} — Abra la aplicación Speed Express para responder.'),
  ('ChatMessage', 'ht', 'Nouvo mesaj Speed Express', 'Ou gen yon mesaj : {message} — Louvri aplikasyon Speed Express la pou reponn.'),
  ('ChatMessageStaff', 'fr', 'Nouveau message', 'Message reçu de {message}'),
  ('ChatMessageStaff', 'en', 'New message', 'Message received from {message}'),
  ('ChatMessageStaff', 'es', 'Nuevo mensaje', 'Mensaje recibido de {message}'),
  ('ChatMessageStaff', 'ht', 'Nouvo mesaj', 'Mesaj resevwa nan men {message}')
on conflict (code, language) do update set title = excluded.title, body = excluded.body
  where (logistics.notification_template.title, logistics.notification_template.body) is distinct from (excluded.title, excluded.body);
-- modeles:fin

-- 5. Le débit, les façades ---------------------------------------------------------------------------------------------------------------
create or replace function public.lg_register_staff_device(p_token text, p_platform text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.register_staff_device(auth.uid(), p_token, p_platform) $$;
create or replace function public.lg_unregister_staff_device(p_token text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.unregister_staff_device(auth.uid(), p_token) $$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('register_staff_device', 'unregister_staff_device', 'chat_staff_language', 'chat_alert', 'chat_alert_trigger',
                                                             'nt_claim', 'nt_push_data', 'nt_fill_recipient') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_register_staff_device', 'lg_unregister_staff_device') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;

-- Pour retirer SEULEMENT cette étape : supprimer le déclencheur chat_alert, les fonctions logistics.chat_alert*, chat_staff_language,
-- register_staff_device, unregister_staff_device et leurs façades, puis remettre nt_claim (010), nt_push_data (020), nt_fill_recipient (027).
-- Les colonnes recipient_user_id et conversation_id restent (des notifications les portent) ; on ne les efface pas.
