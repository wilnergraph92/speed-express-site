-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 32 : la messagerie
-- -----------------------------------------------------------------------------
-- À passer APRÈS 031, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Demande du propriétaire (20/10/2026) : « un système de chat interne entre le tableau de bord et les deux applications, pour une
-- communication professionnelle et interne » ; « chat direct avec le client, l'espace chat dans l'application » ; messages directs,
-- groupes, lier un colis, photos.
--
-- Même principe que tout le reste : le tableau de bord, l'application client et l'application SES Opérations parlent DIRECTEMENT à la base,
-- par les MÊMES fonctions (public.lg_chat_*). Aucun serveur entre eux. La base décide qui lit et qui écrit, à chaque appel.
--
--   1. Trois sortes de conversation :
--        DIRECT   — deux membres de l'équipe, en tête-à-tête (une seule conversation par paire) ;
--        GROUP    — plusieurs membres, créée et gérée par la direction (gérant, administrateur) ; on la quitte, on l'archive, on
--                   ne l'efface jamais ;
--        CUSTOMER — UNE conversation par client, entre lui et l'équipe : la boîte partagée de ceux qui lisent les clients
--                   (« clients.lire », comme le support). Le client n'y voit que le prénom de qui lui répond.
--      Un client ne voit JAMAIS une conversation interne, ni la liste de l'équipe.
--   2. Les messages sont en ajout seul (un échange professionnel ne se réécrit pas) ; chaque envoi porte une clé d'idempotence (un
--      double appui, un réseau qui hésite : un seul message) ; texte, colis cité (son numéro) et photo.
--   3. Les photos vont dans un dossier PRIVÉ du stockage (« messagerie »), rangées par conversation : seuls ceux qui lisent la
--      conversation peuvent les déposer et les ouvrir (adresse signée, de courte durée). La base vérifie qu'une photo citée est bien
--      dans le dossier de SA conversation, déposée par celui qui l'envoie.
--   4. Le temps réel : public.ses_chat_signal, une ligne par destinataire et SANS AUCUNE DONNÉE (pas même la conversation) ; l'écran
--      relit par ces fonctions. Un signal manqué n'est qu'un rafraîchissement manqué : jamais une raison d'annuler un envoi.
--   5. Le tableau de bord gagne le module « Messagerie », ouvert à toute l'équipe (dashboard_access redéfinie : la liste de 019, plus
--      celui-ci).
--
-- Rejouable sans risque ; aucune suppression.
-- =============================================================================

-- 1. Les tables ----------------------------------------------------------------------------------------------------------------------
create table if not exists logistics.chat_conversation (
  id              uuid primary key default gen_random_uuid(),
  kind            text not null check (kind in ('DIRECT', 'GROUP', 'CUSTOMER')),
  title           text check (title is null or char_length(btrim(title)) between 2 and 80),
  customer_id     uuid references logistics.customer (id) on delete restrict,
  direct_key      text unique,
  created_by      uuid references auth.users (id) on delete restrict,
  archived_at     timestamptz,
  last_message_at timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  check ((kind = 'GROUP') = (title is not null)),
  check ((kind = 'CUSTOMER') = (customer_id is not null)),
  check ((kind = 'DIRECT') = (direct_key is not null)),
  check (archived_at is null or kind = 'GROUP')
);
comment on table logistics.chat_conversation is 'Messagerie (032) : DIRECT (deux membres), GROUP (la direction la gère), CUSTOMER (un client et l''équipe). Jamais effacée.';
create unique index if not exists chat_conversation_customer_idx on logistics.chat_conversation (customer_id) where kind = 'CUSTOMER';
create index if not exists chat_conversation_recent_idx on logistics.chat_conversation (last_message_at desc nulls last);
drop trigger if exists touch_updated_at on logistics.chat_conversation;
create trigger touch_updated_at before update on logistics.chat_conversation for each row execute function logistics.touch_updated_at();

create table if not exists logistics.chat_member (
  conversation_id uuid not null references logistics.chat_conversation (id) on delete restrict,
  user_id         uuid not null references logistics.app_user (id) on delete restrict,
  added_by        uuid references auth.users (id) on delete restrict,
  joined_at       timestamptz not null default now(),
  left_at         timestamptz,
  primary key (conversation_id, user_id)
);
comment on table logistics.chat_member is 'Les membres d''une conversation DIRECT ou GROUP. Quitter un groupe pose left_at : l''historique reste.';
create index if not exists chat_member_user_idx on logistics.chat_member (user_id) where left_at is null;

create table if not exists logistics.chat_message (
  id              bigint generated always as identity primary key,
  conversation_id uuid not null references logistics.chat_conversation (id) on delete restrict,
  author_user_id  uuid not null references auth.users (id) on delete restrict,
  author_kind     text not null check (author_kind in ('STAFF', 'CUSTOMER')),
  body            text not null default '' check (char_length(body) <= 4000),
  parcel_id       uuid references logistics.parcel (id) on delete restrict,
  photo_path      text check (photo_path is null or photo_path ~ '^[0-9a-f-]{36}/[A-Za-z0-9_-]{8,80}\.(jpg|png|webp)$'),
  client_key      text not null check (client_key ~ '^[A-Za-z0-9_-]{8,80}$'),
  created_at      timestamptz not null default now(),
  check (btrim(body) <> '' or photo_path is not null),
  unique (author_user_id, client_key)
);
comment on table logistics.chat_message is 'Un message (032) : en ajout seul. Texte, colis cité, photo (adresse dans le dossier privé « messagerie »).';
create index if not exists chat_message_conversation_idx on logistics.chat_message (conversation_id, id desc);
drop trigger if exists chat_message_append_only on logistics.chat_message;
create trigger chat_message_append_only before update or delete on logistics.chat_message for each row execute function logistics.forbid_mutation();

create table if not exists logistics.chat_read (
  conversation_id uuid not null references logistics.chat_conversation (id) on delete restrict,
  user_id         uuid not null references auth.users (id) on delete restrict,
  last_read_id    bigint not null default 0,
  read_at         timestamptz not null default now(),
  primary key (conversation_id, user_id)
);
comment on table logistics.chat_read is 'Jusqu''où chacun a lu une conversation (les « non lus »). Pour une conversation CUSTOMER, chaque membre de l''équipe a la sienne.';

-- Rien de tout cela ne se lit directement : seulement par les fonctions ci-dessous.
do $$
declare t text;
begin
  foreach t in array array['chat_conversation', 'chat_member', 'chat_message', 'chat_read'] loop
    execute format('alter table logistics.%I enable row level security', t);
    execute format('revoke all on logistics.%I from public, anon, authenticated', t);
  end loop;
end
$$;

-- Le signal temps réel de la messagerie : une ligne par destinataire, aucune donnée.
create table if not exists public.ses_chat_signal (
  id         bigint generated always as identity primary key,
  user_id    uuid not null,
  created_at timestamptz not null default now()
);
comment on table public.ses_chat_signal is 'Signal temps réel de la messagerie (032) : « relisez vos conversations ». Aucune donnée, pas même la conversation. Purgé au passage (deux jours).';
create index if not exists ses_chat_signal_user_idx on public.ses_chat_signal (user_id, id);
create index if not exists ses_chat_signal_age_idx on public.ses_chat_signal (created_at);
alter table public.ses_chat_signal enable row level security;
revoke all on public.ses_chat_signal from public, anon, authenticated;
grant select on public.ses_chat_signal to authenticated;
drop policy if exists ses_chat_signal_lecture on public.ses_chat_signal;
create policy ses_chat_signal_lecture on public.ses_chat_signal for select to authenticated using (user_id = (select auth.uid()));
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'ses_chat_signal') then
    execute 'alter publication supabase_realtime add table public.ses_chat_signal';
  end if;
end
$$;

-- 2. Qui est qui ---------------------------------------------------------------------------------------------------------------------
-- Un membre ACTIF de l'équipe (un chauffeur en est un).
create or replace function logistics.chat_is_staff(p_actor uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select p_actor is not null and exists (select 1 from logistics.app_user u where u.id = p_actor and u.active)
$$;

-- Le nom d'un compte : celui de sa fiche, sinon de sa fiche de chauffeur, sinon le début de son e-mail.
create or replace function logistics.chat_name(p_user uuid)
returns text language sql stable security definer set search_path = '' as $$
  select coalesce(nullif(btrim((select c.nom_complet from public.clients c where c.id = p_user)), ''),
                  nullif(btrim((select d.full_name from logistics.driver d where d.user_id = p_user)), ''),
                  nullif(split_part((select a.email from auth.users a where a.id = p_user), '@', 1), ''), '—')
$$;

-- Ce que le client voit de qui lui répond : le prénom seulement, et « Speed Express ».
create or replace function logistics.chat_first_name(p_user uuid)
returns text language sql stable security definer set search_path = '' as $$ select split_part(logistics.chat_name(p_user), ' ', 1) $$;

-- L'accès d'un compte à une conversation : 'member' (direct, groupe), 'customer' (le client de SA conversation), 'team' (un membre qui
-- lit les clients, dans une conversation CUSTOMER), ou null.
create or replace function logistics.chat_access(p_actor uuid, p_conversation uuid)
returns text language plpgsql stable security definer set search_path = '' as $$
declare v logistics.chat_conversation;
begin
  if p_actor is null or p_conversation is null then return null; end if;
  select * into v from logistics.chat_conversation where id = p_conversation;
  if not found then return null; end if;
  if v.kind = 'CUSTOMER' then
    if exists (select 1 from logistics.customer c where c.id = v.customer_id and c.auth_user_id = p_actor) then return 'customer'; end if;
    if logistics.actor_can(p_actor, 'clients.lire') then return 'team'; end if;
    return null;
  end if;
  if logistics.chat_is_staff(p_actor) and exists (select 1 from logistics.chat_member m where m.conversation_id = p_conversation and m.user_id = p_actor and m.left_at is null) then
    return 'member';
  end if;
  return null;
end;
$$;

-- Le signal : à chaque destinataire d'une conversation (l'auteur compris : ses autres appareils se mettent à jour).
create or replace function logistics.chat_signal(p_conversation uuid)
returns void language plpgsql volatile security definer set search_path = '' as $$
declare v logistics.chat_conversation;
begin
  begin
    select * into v from logistics.chat_conversation where id = p_conversation;
    if v.kind = 'CUSTOMER' then
      insert into public.ses_chat_signal (user_id)
      select c.auth_user_id from logistics.customer c where c.id = v.customer_id and c.auth_user_id is not null
      union
      select u.id from logistics.app_user u where u.active and logistics.actor_can(u.id, 'clients.lire');
    else
      insert into public.ses_chat_signal (user_id) select m.user_id from logistics.chat_member m where m.conversation_id = p_conversation and m.left_at is null;
    end if;
    -- Les vieux signaux : effacés au passage, par petits paquets (ce ne sont que des « relisez »).
    delete from public.ses_chat_signal where id in (select id from public.ses_chat_signal where created_at < now() - interval '2 days' order by id limit 500);
  exception when others then
    null;   -- un signal manqué n'est qu'un rafraîchissement manqué : jamais une raison d'annuler un envoi
  end;
end;
$$;

-- Le nombre de messages non lus d'une conversation pour un compte (ceux des autres, après son dernier lu).
create or replace function logistics.chat_unread_in(p_actor uuid, p_conversation uuid)
returns int language sql stable security definer set search_path = '' as $$
  select count(*)::int from logistics.chat_message m
   where m.conversation_id = p_conversation and m.author_user_id <> p_actor
     and m.id > coalesce((select r.last_read_id from logistics.chat_read r where r.conversation_id = p_conversation and r.user_id = p_actor), 0)
$$;

-- Les conversations qu'un compte peut lire.
create or replace function logistics.chat_visible(p_actor uuid)
returns setof uuid language sql stable security definer set search_path = '' as $$
  select m.conversation_id from logistics.chat_member m
   where m.user_id = p_actor and m.left_at is null and logistics.chat_is_staff(p_actor)
  union
  select v.id from logistics.chat_conversation v join logistics.customer c on c.id = v.customer_id
   where v.kind = 'CUSTOMER' and c.auth_user_id = p_actor
  union
  select v.id from logistics.chat_conversation v
   where v.kind = 'CUSTOMER' and logistics.actor_can(p_actor, 'clients.lire')
$$;

-- 3. La boîte de réception ------------------------------------------------------------------------------------------------------------
create or replace function logistics.chat_inbox(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_staff boolean; v_cust uuid; v_items jsonb;
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  v_staff := logistics.chat_is_staff(p_actor);
  v_cust := logistics.my_customer(p_actor);
  if not v_staff and v_cust is null then raise exception 'Messagerie réservée à l''équipe et aux clients.' using errcode = 'LG003'; end if;
  select coalesce(jsonb_agg(x.item order by x.recent desc nulls last, x.created_at desc), '[]'::jsonb) into v_items from (
    select v.last_message_at as recent, v.created_at, jsonb_build_object(
      'conversation_id', v.id, 'kind', v.kind, 'archived', v.archived_at is not null,
      'title', case when v.kind = 'GROUP' then v.title
                    when v.kind = 'CUSTOMER' and v_staff then (select c.full_name from logistics.customer c where c.id = v.customer_id)
                    when v.kind = 'CUSTOMER' then 'Speed Express'
                    else (select logistics.chat_name(m.user_id) from logistics.chat_member m where m.conversation_id = v.id and m.user_id <> p_actor limit 1) end,
      'peer', case when v.kind = 'DIRECT' then (select jsonb_build_object('user_id', m.user_id, 'name', logistics.chat_name(m.user_id), 'role', u.role, 'staff_code', u.staff_code)
                                                  from logistics.chat_member m join logistics.app_user u on u.id = m.user_id
                                                 where m.conversation_id = v.id and m.user_id <> p_actor limit 1) end,
      'customer', case when v.kind = 'CUSTOMER' and v_staff then (select jsonb_build_object('customer_id', c.id, 'code', c.code, 'name', c.full_name) from logistics.customer c where c.id = v.customer_id) end,
      'members', case when v.kind = 'GROUP' then (select count(*) from logistics.chat_member m where m.conversation_id = v.id and m.left_at is null) end,
      'last', (select jsonb_build_object('id', l.id, 'at', l.created_at, 'mine', l.author_user_id = p_actor, 'photo', l.photo_path is not null,
                                         'body', left(l.body, 140), 'parcel', (select p.tracking_number from logistics.parcel p where p.id = l.parcel_id),
                                         'author', case when l.author_user_id = p_actor then null
                                                        when not v_staff and l.author_kind = 'STAFF' then logistics.chat_first_name(l.author_user_id)
                                                        else logistics.chat_name(l.author_user_id) end)
                 from logistics.chat_message l where l.conversation_id = v.id order by l.id desc limit 1),
      'unread', logistics.chat_unread_in(p_actor, v.id)) as item
      from logistics.chat_conversation v
     where v.id in (select logistics.chat_visible(p_actor))
       -- une conversation de client vide n'encombre pas la boîte de l'équipe
       and not (v.kind = 'CUSTOMER' and v_staff and v.last_message_at is null and v.created_by is distinct from p_actor)
     order by v.last_message_at desc nulls last, v.created_at desc
     limit 200) x;
  return jsonb_build_object(
    'me', jsonb_build_object('user_id', p_actor, 'kind', case when v_staff then 'STAFF' else 'CUSTOMER' end, 'name', logistics.chat_name(p_actor)),
    'can', jsonb_build_object('direct', v_staff, 'groups', v_staff and logistics.actor_can(p_actor, 'direction'), 'customers', v_staff and logistics.actor_can(p_actor, 'clients.lire')),
    'unread', (select coalesce(sum((i ->> 'unread')::int), 0) from jsonb_array_elements(v_items) i),
    'items', v_items);
end;
$$;

-- Le seul nombre (la pastille d'un onglet) : sans tout relire.
create or replace function logistics.chat_unread(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if not logistics.chat_is_staff(p_actor) and logistics.my_customer(p_actor) is null then return jsonb_build_object('unread', 0); end if;
  return jsonb_build_object('unread', coalesce((select sum(logistics.chat_unread_in(p_actor, x)) from logistics.chat_visible(p_actor) x), 0));
end;
$$;

-- 4. Une conversation : ses messages ---------------------------------------------------------------------------------------------------
create or replace function logistics.chat_messages(p_actor uuid, p_conversation uuid, p_before bigint default null, p_limit int default 50)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v logistics.chat_conversation; v_acc text; v_lim int := least(greatest(coalesce(p_limit, 50), 1), 100); v_staff boolean; v_items jsonb; v_more boolean; v_min bigint;
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  v_acc := logistics.chat_access(p_actor, p_conversation);
  if v_acc is null then raise exception 'Conversation introuvable.' using errcode = 'LG002'; end if;
  select * into v from logistics.chat_conversation where id = p_conversation;
  v_staff := v_acc <> 'customer';
  select coalesce(jsonb_agg(x.item order by x.id), '[]'::jsonb), min(x.id) into v_items, v_min from (
    select m.id, jsonb_build_object(
      'id', m.id, 'at', m.created_at, 'body', m.body, 'mine', m.author_user_id = p_actor, 'photo_path', m.photo_path,
      'author', jsonb_build_object('kind', m.author_kind,
                                   'name', case when not v_staff and m.author_kind = 'STAFF' then logistics.chat_first_name(m.author_user_id) else logistics.chat_name(m.author_user_id) end),
      'parcel', (select jsonb_build_object('tracking_number', p.tracking_number) from logistics.parcel p where p.id = m.parcel_id)) as item
      from logistics.chat_message m
     where m.conversation_id = p_conversation and (p_before is null or m.id < p_before)
     order by m.id desc limit v_lim) x;
  -- Des messages plus anciens attendent : l'écran propose de les charger (p_before = le plus ancien affiché).
  v_more := v_min is not null and exists (select 1 from logistics.chat_message m where m.conversation_id = p_conversation and m.id < v_min);
  return jsonb_build_object(
    'conversation', jsonb_build_object('conversation_id', v.id, 'kind', v.kind, 'archived', v.archived_at is not null,
      'title', case when v.kind = 'GROUP' then v.title
                    when v.kind = 'CUSTOMER' and v_staff then (select c.full_name from logistics.customer c where c.id = v.customer_id)
                    when v.kind = 'CUSTOMER' then 'Speed Express'
                    else (select logistics.chat_name(m.user_id) from logistics.chat_member m where m.conversation_id = v.id and m.user_id <> p_actor limit 1) end,
      'customer', case when v.kind = 'CUSTOMER' and v_staff then (select jsonb_build_object('customer_id', c.id, 'code', c.code, 'name', c.full_name) from logistics.customer c where c.id = v.customer_id) end,
      'members', case when v_staff and v.kind <> 'CUSTOMER' then (select coalesce(jsonb_agg(jsonb_build_object('user_id', m.user_id, 'name', logistics.chat_name(m.user_id), 'role', u.role, 'staff_code', u.staff_code)
                                                                         order by logistics.chat_name(m.user_id)), '[]'::jsonb)
                                                                    from logistics.chat_member m join logistics.app_user u on u.id = m.user_id
                                                                   where m.conversation_id = v.id and m.left_at is null) end,
      'can_send', v.archived_at is null,
      'can_manage', v.kind = 'GROUP' and v_staff and logistics.actor_can(p_actor, 'direction')),
    'items', v_items, 'has_more', v_more,
    'unread', logistics.chat_unread_in(p_actor, p_conversation));
end;
$$;

-- 5. Écrire ---------------------------------------------------------------------------------------------------------------------------
create or replace function logistics.chat_send(p_actor uuid, p_conversation uuid, p_body text, p_client_key text, p_parcel text default null, p_photo_path text default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v logistics.chat_conversation; v_acc text; v_body text := btrim(coalesce(p_body, '')); v_parcel uuid; v_owner uuid; v_prior logistics.chat_message;
        v_id bigint; v_photo text := nullif(btrim(coalesce(p_photo_path, '')), ''); v_ok boolean;
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if p_client_key is null or p_client_key !~ '^[A-Za-z0-9_-]{8,80}$' then raise exception 'Clé d''envoi invalide.' using errcode = 'LG005'; end if;
  -- Le même envoi rejoué (double appui, réseau) : le message déjà enregistré, rien de plus.
  select * into v_prior from logistics.chat_message where author_user_id = p_actor and client_key = p_client_key;
  if found then
    return jsonb_build_object('message_id', v_prior.id, 'conversation_id', v_prior.conversation_id, 'at', v_prior.created_at, 'replayed', true);
  end if;
  v_acc := logistics.chat_access(p_actor, p_conversation);
  if v_acc is null then raise exception 'Conversation introuvable.' using errcode = 'LG002'; end if;
  select * into v from logistics.chat_conversation where id = p_conversation for update;
  if v.archived_at is not null then raise exception 'Ce groupe est archivé : on le lit, on n''y écrit plus.' using errcode = 'LG005'; end if;
  if v_body = '' and v_photo is null then raise exception 'Un message vide ne part pas.' using errcode = 'LG005'; end if;
  if char_length(v_body) > 4000 then raise exception 'Un message fait au plus 4 000 caractères.' using errcode = 'LG005'; end if;
  -- Un colis cité : son numéro. Le client ne cite que les siens ; dans la conversation d'un client, l'équipe ne cite que ceux de CE client
  -- (sinon le numéro et le statut du colis d'un autre lui seraient montrés).
  if nullif(btrim(coalesce(p_parcel, '')), '') is not null then
    select p.id, p.customer_id into v_parcel, v_owner from logistics.parcel p where p.tracking_number = upper(btrim(p_parcel));
    if v_parcel is null then raise exception 'Colis introuvable : %.', upper(btrim(p_parcel)) using errcode = 'LG002'; end if;
    if v.kind = 'CUSTOMER' and v_owner is distinct from v.customer_id then
      raise exception 'Ce colis n''appartient pas à ce client.' using errcode = 'LG003';
    end if;
  end if;
  -- Une photo : dans le dossier de SA conversation, et (sur Supabase) bien déposée, par celui qui l'envoie.
  if v_photo is not null then
    if v_photo !~ ('^' || p_conversation::text || '/[A-Za-z0-9_-]{8,80}\.(jpg|png|webp)$') then
      raise exception 'Photo invalide : elle doit être déposée dans le dossier de cette conversation.' using errcode = 'LG005';
    end if;
    if to_regclass('storage.objects') is not null then
      execute 'select exists (select 1 from storage.objects o where o.bucket_id = ''messagerie'' and o.name = $1
                                and coalesce(to_jsonb(o) ->> ''owner_id'', to_jsonb(o) ->> ''owner'') = $2::text)'
        into v_ok using v_photo, p_actor;
      if not v_ok then raise exception 'Photo introuvable : déposez-la d''abord.' using errcode = 'LG005'; end if;
    end if;
  end if;
  insert into logistics.chat_message (conversation_id, author_user_id, author_kind, body, parcel_id, photo_path, client_key)
  values (p_conversation, p_actor, case when v_acc = 'customer' then 'CUSTOMER' else 'STAFF' end, v_body, v_parcel, v_photo, p_client_key)
  returning id into v_id;
  update logistics.chat_conversation set last_message_at = now() where id = p_conversation;
  -- Écrire, c'est avoir lu jusque-là.
  insert into logistics.chat_read as r (conversation_id, user_id, last_read_id) values (p_conversation, p_actor, v_id)
  on conflict (conversation_id, user_id) do update set last_read_id = greatest(r.last_read_id, excluded.last_read_id), read_at = now();
  perform logistics.chat_signal(p_conversation);
  return jsonb_build_object('message_id', v_id, 'conversation_id', p_conversation, 'at', now(), 'replayed', false);
end;
$$;

create or replace function logistics.chat_mark_read(p_actor uuid, p_conversation uuid, p_message_id bigint)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_max bigint;
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if logistics.chat_access(p_actor, p_conversation) is null then raise exception 'Conversation introuvable.' using errcode = 'LG002'; end if;
  -- On ne « lit » jamais plus loin que le dernier message qui existe.
  select max(id) into v_max from logistics.chat_message where conversation_id = p_conversation and id <= coalesce(p_message_id, 0);
  if v_max is null then return jsonb_build_object('conversation_id', p_conversation, 'last_read_id', 0); end if;
  insert into logistics.chat_read as r (conversation_id, user_id, last_read_id) values (p_conversation, p_actor, v_max)
  on conflict (conversation_id, user_id) do update set last_read_id = greatest(r.last_read_id, excluded.last_read_id), read_at = now();
  return jsonb_build_object('conversation_id', p_conversation, 'last_read_id', (select last_read_id from logistics.chat_read where conversation_id = p_conversation and user_id = p_actor));
end;
$$;

-- 6. Ouvrir une conversation ------------------------------------------------------------------------------------------------------------
-- L'annuaire : l'équipe (pour un message direct ou un groupe) et, pour qui lit les clients, les clients qui ont un compte.
create or replace function logistics.chat_directory(p_actor uuid, p_search text default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_q text := lower(btrim(coalesce(p_search, '')));
begin
  if not logistics.chat_is_staff(p_actor) then raise exception 'Réservé à l''équipe.' using errcode = 'LG003'; end if;
  return jsonb_build_object(
    'staff', coalesce((select jsonb_agg(x.item order by x.nom) from (
        select logistics.chat_name(u.id) as nom, jsonb_build_object('user_id', u.id, 'name', logistics.chat_name(u.id), 'role', u.role, 'staff_code', u.staff_code,
               'branch', logistics.branch_label(u.branch_id), 'driver', exists (select 1 from logistics.driver d where d.user_id = u.id)) as item
          from logistics.app_user u
         where u.active and u.id <> p_actor
           and (v_q = '' or position(v_q in lower(logistics.chat_name(u.id))) > 0 or position(v_q in lower(coalesce(u.staff_code, ''))) > 0)
         limit 200) x), '[]'::jsonb),
    'customers', case when logistics.actor_can(p_actor, 'clients.lire') and char_length(v_q) >= 2 then coalesce((select jsonb_agg(x.item order by x.nom) from (
        select c.full_name as nom, jsonb_build_object('customer_id', c.id, 'code', c.code, 'name', c.full_name, 'city', c.city, 'country', c.country) as item
          from logistics.customer c
         where c.auth_user_id is not null and c.source <> 'legacy_staff_account'
           and (position(v_q in lower(c.full_name)) > 0 or position(v_q in lower(coalesce(c.code, ''))) > 0 or position(v_q in lower(c.email)) > 0)
         order by c.full_name limit 20) x), '[]'::jsonb) else '[]'::jsonb end);
end;
$$;

-- Un message direct : la conversation de la paire, créée au premier besoin (une seule, quel que soit celui qui l'ouvre).
create or replace function logistics.chat_open_direct(p_actor uuid, p_user uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_key text; v_id uuid;
begin
  if not logistics.chat_is_staff(p_actor) then raise exception 'Réservé à l''équipe.' using errcode = 'LG003'; end if;
  if p_user is null or p_user = p_actor or not logistics.chat_is_staff(p_user) then
    raise exception 'Choisissez un autre membre actif de l''équipe.' using errcode = 'LG005';
  end if;
  v_key := least(p_actor::text, p_user::text) || ':' || greatest(p_actor::text, p_user::text);
  select id into v_id from logistics.chat_conversation where direct_key = v_key;
  if v_id is null then
    insert into logistics.chat_conversation (kind, direct_key, created_by) values ('DIRECT', v_key, p_actor)
    on conflict (direct_key) do nothing returning id into v_id;
    if v_id is null then select id into v_id from logistics.chat_conversation where direct_key = v_key; end if;
  end if;
  insert into logistics.chat_member (conversation_id, user_id, added_by) values (v_id, p_actor, p_actor), (v_id, p_user, p_actor)
  on conflict (conversation_id, user_id) do update set left_at = null;
  return jsonb_build_object('conversation_id', v_id);
end;
$$;

-- La conversation d'un client : la sienne (sans paramètre, pour le client), ou celle d'un client choisi (pour qui lit les clients).
create or replace function logistics.chat_open_customer(p_actor uuid, p_customer uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid; v_id uuid;
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if p_customer is null then
    v_c := logistics.require_customer(p_actor);
    if exists (select 1 from logistics.customer c where c.id = v_c and c.source = 'legacy_staff_account') then
      raise exception 'Un compte d''équipe n''a pas de conversation client.' using errcode = 'LG003';
    end if;
  else
    if not (logistics.chat_is_staff(p_actor) and logistics.actor_can(p_actor, 'clients.lire')) then raise exception 'Réservé à qui lit les clients.' using errcode = 'LG003'; end if;
    select c.id into v_c from logistics.customer c where c.id = p_customer and c.auth_user_id is not null and c.source <> 'legacy_staff_account';
    if v_c is null then raise exception 'Client introuvable, ou sans compte : il ne pourrait pas lire la réponse.' using errcode = 'LG002'; end if;
  end if;
  select id into v_id from logistics.chat_conversation where kind = 'CUSTOMER' and customer_id = v_c;
  if v_id is null then
    insert into logistics.chat_conversation (kind, customer_id, created_by) values ('CUSTOMER', v_c, p_actor)
    on conflict (customer_id) where kind = 'CUSTOMER' do nothing returning id into v_id;
    if v_id is null then select id into v_id from logistics.chat_conversation where kind = 'CUSTOMER' and customer_id = v_c; end if;
  end if;
  return jsonb_build_object('conversation_id', v_id);
end;
$$;

-- 7. Les groupes : la direction les crée et les gère ------------------------------------------------------------------------------------
create or replace function logistics.chat_create_group(p_actor uuid, p_title text, p_members uuid[])
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid; v_title text := btrim(coalesce(p_title, '')); v_m uuid[]; v_bad int;
begin
  if not (logistics.chat_is_staff(p_actor) and logistics.actor_can(p_actor, 'direction')) then raise exception 'Seule la direction crée un groupe.' using errcode = 'LG003'; end if;
  if char_length(v_title) not between 2 and 80 then raise exception 'Le nom du groupe fait de 2 à 80 caractères.' using errcode = 'LG005'; end if;
  v_m := array(select distinct x from unnest(coalesce(p_members, '{}'::uuid[]) || p_actor) x where x is not null);
  select count(*) into v_bad from unnest(v_m) x where not logistics.chat_is_staff(x);
  if v_bad > 0 then raise exception 'Un groupe ne réunit que des membres actifs de l''équipe.' using errcode = 'LG005'; end if;
  if array_length(v_m, 1) < 2 then raise exception 'Choisissez au moins un autre membre.' using errcode = 'LG005'; end if;
  insert into logistics.chat_conversation (kind, title, created_by) values ('GROUP', v_title, p_actor) returning id into v_id;
  insert into logistics.chat_member (conversation_id, user_id, added_by) select v_id, x, p_actor from unnest(v_m) x;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'chat.group.create', 'chat_conversation', v_id::text, jsonb_build_object('title', v_title, 'members', array_length(v_m, 1)), gen_random_uuid());
  perform logistics.chat_signal(v_id);
  return jsonb_build_object('conversation_id', v_id, 'members', array_length(v_m, 1));
end;
$$;

create or replace function logistics.chat_update_group(p_actor uuid, p_conversation uuid, p_title text default null, p_add uuid[] default null, p_remove uuid[] default null, p_archived boolean default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v logistics.chat_conversation; v_title text := nullif(btrim(coalesce(p_title, '')), ''); v_bad int; v_left int;
begin
  if not (logistics.chat_is_staff(p_actor) and logistics.actor_can(p_actor, 'direction')) then raise exception 'Seule la direction gère un groupe.' using errcode = 'LG003'; end if;
  select * into v from logistics.chat_conversation where id = p_conversation for update;
  if not found or v.kind <> 'GROUP' then raise exception 'Groupe introuvable.' using errcode = 'LG002'; end if;
  if v_title is not null and char_length(v_title) not between 2 and 80 then raise exception 'Le nom du groupe fait de 2 à 80 caractères.' using errcode = 'LG005'; end if;
  select count(*) into v_bad from unnest(coalesce(p_add, '{}'::uuid[])) x where not logistics.chat_is_staff(x);
  if v_bad > 0 then raise exception 'Un groupe ne réunit que des membres actifs de l''équipe.' using errcode = 'LG005'; end if;
  if v_title is not null then update logistics.chat_conversation set title = v_title where id = p_conversation; end if;
  insert into logistics.chat_member as cm (conversation_id, user_id, added_by) select p_conversation, x, p_actor from unnest(coalesce(p_add, '{}'::uuid[])) x where x is not null
  on conflict (conversation_id, user_id) do update set left_at = null, added_by = excluded.added_by, joined_at = case when cm.left_at is null then cm.joined_at else now() end;
  -- Retirer quelqu'un : il quitte le groupe (left_at), l'historique reste.
  update logistics.chat_member set left_at = now() where conversation_id = p_conversation and left_at is null and user_id = any (coalesce(p_remove, '{}'::uuid[]));
  get diagnostics v_left = row_count;
  if p_archived is not null then
    update logistics.chat_conversation set archived_at = case when p_archived then coalesce(archived_at, now()) end where id = p_conversation;
  end if;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'chat.group.update', 'chat_conversation', p_conversation::text,
          jsonb_strip_nulls(jsonb_build_object('title', v_title, 'added', cardinality(coalesce(p_add, '{}'::uuid[])), 'removed', v_left, 'archived', p_archived)), gen_random_uuid());
  perform logistics.chat_signal(p_conversation);
  return jsonb_build_object('conversation_id', p_conversation,
                            'members', (select count(*) from logistics.chat_member where conversation_id = p_conversation and left_at is null),
                            'archived', (select archived_at is not null from logistics.chat_conversation where id = p_conversation));
end;
$$;

-- 8. Les photos : le dossier privé « messagerie » du stockage de Supabase ---------------------------------------------------------------
-- Une adresse « <conversation>/<nom>.jpg » : ceux qui lisent la conversation la déposent (si elle n'est pas archivée) et l'ouvrent.
create or replace function public.ses_chat_peut_lire(p_name text) returns boolean language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid;
begin
  if p_name is null or p_name !~ '^[0-9a-f-]{36}/' then return false; end if;
  v_c := split_part(p_name, '/', 1)::uuid;
  return logistics.chat_access(auth.uid(), v_c) is not null;
exception when others then
  return false;
end;
$$;
create or replace function public.ses_chat_peut_deposer(p_name text) returns boolean language plpgsql stable security definer set search_path = '' as $$
begin
  if p_name is null or p_name !~ '^[0-9a-f-]{36}/[A-Za-z0-9_-]{8,80}\.(jpg|png|webp)$' then return false; end if;
  return public.ses_chat_peut_lire(p_name)
     and exists (select 1 from logistics.chat_conversation v where v.id = split_part(p_name, '/', 1)::uuid and v.archived_at is null);
exception when others then
  return false;
end;
$$;
do $$
begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public) values ('messagerie', 'messagerie', false) on conflict (id) do nothing;
    -- 5 Mo au plus, des images seulement (si cette version de Supabase connaît ces colonnes).
    if exists (select 1 from information_schema.columns where table_schema = 'storage' and table_name = 'buckets' and column_name = 'file_size_limit') then
      execute $u$update storage.buckets set file_size_limit = 5242880, allowed_mime_types = array['image/jpeg', 'image/png', 'image/webp'] where id = 'messagerie'$u$;
    end if;
  end if;
  if to_regclass('storage.objects') is not null then
    execute 'drop policy if exists ses_messagerie_depot on storage.objects';
    execute $p$create policy ses_messagerie_depot on storage.objects for insert to authenticated
             with check (bucket_id = 'messagerie' and public.ses_chat_peut_deposer(name))$p$;
    execute 'drop policy if exists ses_messagerie_lecture on storage.objects';
    -- Lire (et donc signer une adresse) : ceux qui lisent la conversation. Personne ne remplace ni ne supprime une photo envoyée.
    execute $p$create policy ses_messagerie_lecture on storage.objects for select to authenticated
             using (bucket_id = 'messagerie' and public.ses_chat_peut_lire(name))$p$;
  end if;
end
$$;

-- 9. La limitation de débit (013) : deux seaux de plus ; la liste complète, redéfinie ici ----------------------------------------------
create or replace function ops.limit_of(p_bucket text) returns int[] language sql immutable set search_path = '' as $$
  select case p_bucket
    when 'portal.pickup_request'   then array[10, 3600]
    when 'portal.delivery_request' then array[10, 3600]
    when 'portal.support_ticket'   then array[10, 3600]
    when 'portal.support_message'  then array[60, 3600]
    when 'portal.customer_address' then array[30, 3600]
    when 'mobile.command'          then array[1200, 600]   -- une file hors connexion qui se vide d'un coup passe ; un robot, non
    when 'warehouse.scan'          then array[1200, 600]   -- deux scans par seconde, en continu
    when 'client.error'            then array[20, 3600]
    when 'chat.message'            then array[600, 3600]   -- dix messages par minute, pendant une heure
    when 'chat.conversation'       then array[60, 3600]
  end
$$;
do $$
declare r record;
begin
  for r in select * from (values ('logistics', 'chat_message', 'chat.message'), ('logistics', 'chat_conversation', 'chat.conversation')) v(s, t, seau) loop
    execute format('drop trigger if exists ops_rate_limit on %I.%I', r.s, r.t);
    execute format('create trigger ops_rate_limit before insert on %I.%I for each row execute function ops.limit_trigger(%L)', r.s, r.t, r.seau);
  end loop;
end
$$;

-- 10. Le module « Messagerie » du tableau de bord : la liste de 019, plus celui-ci, ouvert à toute l'équipe -----------------------------
create or replace function logistics.dashboard_access(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  u logistics.app_user; v_ops boolean; v_stat boolean; v_fin boolean; v_cli boolean; v_dir boolean; v_roles boolean; v_drv boolean; v_any boolean; m text[] := '{}';
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  select * into u from logistics.app_user where id = p_actor and active;
  if not found then
    -- Un client (ou un compte désactivé) : jamais le tableau de bord opérationnel.
    return jsonb_build_object('staff', false, 'modules', '[]'::jsonb);
  end if;
  v_ops := logistics.actor_can(p_actor, 'colis.lire'); v_stat := logistics.actor_can(p_actor, 'colis.statut');
  v_fin := logistics.actor_can(p_actor, 'factures.lire'); v_cli := logistics.actor_can(p_actor, 'clients.lire');
  v_dir := logistics.actor_can(p_actor, 'direction'); v_roles := v_dir or 'roles.gerer' = any (u.rights);
  v_drv := logistics.driver_of(p_actor) is not null;
  v_any := v_ops or v_fin or v_cli or v_dir;
  if v_any then m := m || array['vue-generale', 'commande']; end if;
  if v_ops then m := m || array['colis', 'prealertes']; end if;
  if v_stat then m := m || 'scanner'::text; end if;
  if v_ops then m := m || array['entrepots', 'consolidations', 'expeditions', 'transport', 'douane']; end if;
  if v_ops or v_drv then m := m || 'livraisons'::text; end if;
  if v_ops then m := m || array['chauffeurs', 'vehicules']; end if;
  if v_ops or v_drv then m := m || 'tournees'::text; end if;
  if v_ops then m := m || 'incidents'::text; end if;
  if v_cli then m := m || 'clients'::text; end if;
  if v_fin then m := m || array['factures', 'encaissements', 'depenses']; end if;
  if v_any then m := m || 'rapports'::text; end if;
  if v_dir then m := m || 'analytique'::text; end if;
  if v_ops then m := m || 'notifications'::text; end if;
  -- 032 : la messagerie, pour toute l'équipe (un chauffeur compris).
  m := m || 'messagerie'::text;
  if v_roles then m := m || 'equipe'::text; end if;
  m := m || array['pointage', 'parametres'];
  if v_dir then m := m || 'sante'::text; end if;
  return jsonb_build_object('staff', true, 'role', u.role, 'driver', v_drv, 'driver_only', v_drv and not v_any, 'direction', v_dir,
                            'can', jsonb_build_object('ops', v_ops, 'status', v_stat, 'finance', v_fin, 'customers', v_cli, 'roles', v_roles),
                            'modules', to_jsonb(m), 'today', logistics.today());
end;
$$;

-- 11. Les façades : ce que le site et les deux applications appellent ---------------------------------------------------------------------
create or replace function public.lg_chat_inbox() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.chat_inbox(auth.uid()) $$;
create or replace function public.lg_chat_unread() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.chat_unread(auth.uid()) $$;
create or replace function public.lg_chat_messages(p_conversation_id uuid, p_before bigint default null, p_limit int default 50)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.chat_messages(auth.uid(), p_conversation_id, p_before, p_limit) $$;
create or replace function public.lg_chat_send(p_conversation_id uuid, p_body text, p_client_key text, p_parcel text default null, p_photo_path text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.chat_send(auth.uid(), p_conversation_id, p_body, p_client_key, p_parcel, p_photo_path) $$;
create or replace function public.lg_chat_mark_read(p_conversation_id uuid, p_message_id bigint)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.chat_mark_read(auth.uid(), p_conversation_id, p_message_id) $$;
create or replace function public.lg_chat_directory(p_search text default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.chat_directory(auth.uid(), p_search) $$;
create or replace function public.lg_chat_open_direct(p_user_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.chat_open_direct(auth.uid(), p_user_id) $$;
create or replace function public.lg_chat_open_customer(p_customer_id uuid default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.chat_open_customer(auth.uid(), p_customer_id) $$;
create or replace function public.lg_chat_create_group(p_title text, p_member_ids uuid[])
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.chat_create_group(auth.uid(), p_title, p_member_ids) $$;
create or replace function public.lg_chat_update_group(p_conversation_id uuid, p_title text default null, p_add uuid[] default null, p_remove uuid[] default null, p_archived boolean default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.chat_update_group(auth.uid(), p_conversation_id, p_title, p_add, p_remove, p_archived) $$;

-- 12. Tout fermé, sauf les façades ----------------------------------------------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('chat_is_staff', 'chat_name', 'chat_first_name', 'chat_access', 'chat_signal', 'chat_unread_in', 'chat_visible',
                                                             'chat_inbox', 'chat_unread', 'chat_messages', 'chat_send', 'chat_mark_read', 'chat_directory', 'chat_open_direct',
                                                             'chat_open_customer', 'chat_create_group', 'chat_update_group', 'dashboard_access') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'ops' and p.proname = 'limit_of' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_chat_inbox', 'lg_chat_unread', 'lg_chat_messages', 'lg_chat_send', 'lg_chat_mark_read', 'lg_chat_directory',
                                                          'lg_chat_open_direct', 'lg_chat_open_customer', 'lg_chat_create_group', 'lg_chat_update_group',
                                                          'ses_chat_peut_lire', 'ses_chat_peut_deposer') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
revoke truncate, references, trigger on public.ses_chat_signal from anon, authenticated;

-- Pour retirer SEULEMENT cette étape : supprimer les façades public.lg_chat_*, public.ses_chat_peut_lire, public.ses_chat_peut_deposer, les
-- fonctions logistics.chat_*, les déclencheurs ops_rate_limit des deux tables de conversation, (sur Supabase) les règles ses_messagerie_* et le
-- dossier « messagerie », puis remettre dashboard_access (019) et ops.limit_of (013). Les tables chat_* et public.ses_chat_signal gardent les
-- messages : on ne les efface pas.
