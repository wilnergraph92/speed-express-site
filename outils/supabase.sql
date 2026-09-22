-- =============================================================================
-- Speed Express Shipping — base de données de l'espace client (Supabase)
--
-- À exécuter une fois : Supabase > SQL Editor > New query > coller tout ce
-- fichier > Run. Le script peut être relancé sans risque : il ne supprime
-- aucune donnée. Relancez-le après chaque mise à jour du site.
--
-- Contenu :
--   clients           un compte, son identifiant SES-#####, son rôle et,
--                     pour un employé, la liste de ce qu'il a le droit de faire
--   colis             les colis, chacun rattaché à un client (SES-10001-HT…),
--                     avec le jeton unique qui sert au QR code de l'étiquette
--   colis_historique  chaque changement de statut : date, heure, lieu, note,
--                     et qui l'a fait
--   factures          les factures, payées ou impayées, avec leurs lignes
--
-- Sécurité. Tout est décidé par le serveur, jamais par la page :
--   • un client ne peut lire que son profil, ses colis et ses factures ;
--   • un employé ne peut faire que ce que l'administrateur lui a coché ;
--   • un administrateur voit et fait tout ;
--   • les mots de passe restent chez Supabase (Auth), hachés : ni ce schéma
--     ni le site ne les voient jamais.
--
-- Après avoir créé votre compte sur la page « Créer un compte » du site,
-- faites-en l'administrateur :
--     select public.definir_admin('votre-adresse@exemple.com');
-- =============================================================================


-- 1. Numérotation --------------------------------------------------------------

-- Numéros de colis : SES-10001-HT, SES-10002-DO…
create sequence if not exists public.numero_colis_seq start with 10000;
-- Numéros de facture : FAC-2026-0001
create sequence if not exists public.numero_facture_seq start with 1;

-- Identifiant client : « SES- » suivi de cinq chiffres (SES-67491), jamais deux
-- fois le même. 90 000 identifiants sont possibles (10000 à 99999). Sans la
-- limite d'essais, une base presque pleine ferait tourner la boucle sans fin :
-- mieux vaut un message qui nomme le problème.
create or replace function public.nouveau_code_client()
returns text
language plpgsql
volatile
set search_path = ''
as $$
declare
  v_code text;
  v_essais int := 0;
begin
  loop
    v_code := 'SES-' || (10000 + floor(random() * 90000))::int;
    exit when not exists (select 1 from public.clients where code = v_code);
    v_essais := v_essais + 1;
    if v_essais >= 400 then
      raise exception 'Plus d''identifiant client libre au format SES-00000 : % déjà pris sur 90 000.',
        (select count(*) from public.clients where code is not null);
    end if;
  end loop;
  return v_code;
end;
$$;


-- 2. Tables -------------------------------------------------------------------

create table if not exists public.clients (
  id          uuid primary key references auth.users (id) on delete cascade,
  code        text unique,
  nom_complet text not null default '',
  pays        text not null default '',
  region      text not null default '',
  ville       text not null default '',
  adresse     text not null default '',
  telephone   text not null default '',
  email       text not null default '',
  langue      text not null default 'fr',
  role        text not null default 'client'
              check (role in ('client', 'employe', 'admin')),
  -- Ce qu'un employé a le droit de faire. Vide pour un client ; sans effet
  -- pour un administrateur, qui a tout.
  droits      text[] not null default '{}',
  cree_le     timestamptz not null default now()
);

create index if not exists clients_role_idx on public.clients (role);

create table if not exists public.colis (
  id                uuid primary key default gen_random_uuid(),
  numero            text unique,
  -- Jeton tiré au hasard, écrit dans le QR code de l'étiquette : l'adresse de
  -- suivi d'un colis ne se devine pas à partir de son numéro.
  jeton             text not null default encode(gen_random_bytes(8), 'hex'),
  client_id         uuid references public.clients (id) on delete set null,
  description       text not null default '',
  expediteur        text not null default '',
  destinataire      text not null default '',
  poids_lb          numeric(8, 2) check (poids_lb is null or poids_lb >= 0),
  service           text not null default 'aerien'
                    check (service in ('aerien', 'maritime', 'terrestre')),
  pays_destination  text not null default 'DO' check (pays_destination in ('HT', 'DO', 'US')),
  ville_destination text not null default '',
  adresse_livraison text not null default '',
  valeur_declaree   numeric(10, 2) check (valeur_declaree is null or valeur_declaree >= 0),
  statut            text not null default 'confirme'
                    check (statut in ('confirme', 'expedie', 'disponible', 'livre', 'action')),
  lieu              text not null default '',
  note              text not null default '',   -- visible par le client
  cree_le           timestamptz not null default now(),
  maj_le            timestamptz not null default now()
);

create index if not exists colis_client_idx on public.colis (client_id);
create index if not exists colis_maj_idx on public.colis (maj_le desc);
create index if not exists colis_statut_idx on public.colis (statut);

create table if not exists public.colis_historique (
  id       bigint generated always as identity primary key,
  colis_id uuid not null references public.colis (id) on delete cascade,
  statut   text not null,
  lieu     text not null default '',
  note     text not null default '',
  auteur   text not null default '',   -- qui a fait le changement
  cree_le  timestamptz not null default now()
);

create index if not exists colis_historique_idx on public.colis_historique (colis_id, cree_le);

create table if not exists public.factures (
  id          uuid primary key default gen_random_uuid(),
  numero      text unique,
  client_id   uuid not null references public.clients (id) on delete cascade,
  colis_id    uuid references public.colis (id) on delete set null,
  montant     numeric(10, 2) not null default 0 check (montant >= 0),
  devise      text not null default 'USD',
  statut      text not null default 'impayee' check (statut in ('impayee', 'payee')),
  note        text not null default '',
  lignes      jsonb not null default '[]'::jsonb,
  echeance_le date,
  cree_le     timestamptz not null default now(),
  payee_le    timestamptz
);

create index if not exists factures_client_idx on public.factures (client_id, cree_le desc);
create index if not exists factures_statut_idx on public.factures (statut);


-- 3. Automatismes -------------------------------------------------------------

-- Profil créé à l'inscription, avec son identifiant unique. Le rôle est
-- toujours « client » : il ne peut pas être demandé depuis le formulaire.
create or replace function public.creer_profil_client()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  m jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
begin
  insert into public.clients (id, code, nom_complet, pays, region, ville, adresse, telephone, email, langue)
  values (
    new.id,
    public.nouveau_code_client(),
    left(trim(coalesce(m ->> 'nom_complet', '')), 120),
    left(trim(coalesce(m ->> 'pays', '')), 60),
    left(trim(coalesce(m ->> 'region', '')), 80),
    left(trim(coalesce(m ->> 'ville', '')), 80),
    left(trim(coalesce(m ->> 'adresse', '')), 200),
    left(trim(coalesce(m ->> 'telephone', '')), 40),
    coalesce(new.email, ''),
    case when m ->> 'langue' in ('fr', 'en', 'es', 'ht') then m ->> 'langue' else 'fr' end
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists creer_profil_client on auth.users;
create trigger creer_profil_client
  after insert on auth.users
  for each row execute function public.creer_profil_client();

-- Numéro et jeton attribués à l'enregistrement, et jamais modifiés ensuite :
-- une étiquette déjà imprimée doit rester valable jusqu'à la livraison.
create or replace function public.preparer_colis()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    if coalesce(trim(new.numero), '') = '' then
      new.numero := 'SES-' || nextval('public.numero_colis_seq') || '-' || new.pays_destination;
    end if;
    new.numero := upper(trim(new.numero));
    new.cree_le := now();
  else
    new.numero := old.numero;
    new.jeton := old.jeton;
    new.cree_le := old.cree_le;
  end if;
  new.maj_le := now();
  return new;
end;
$$;

drop trigger if exists preparer_colis on public.colis;
create trigger preparer_colis
  before insert or update on public.colis
  for each row execute function public.preparer_colis();

-- Chaque changement de statut, de lieu ou de note entre dans l'historique,
-- daté, avec le nom de celui qui l'a fait.
create or replace function public.historiser_colis()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_auteur text := coalesce(
    (select nullif(c.email, '') from public.clients c where c.id = auth.uid()), '');
begin
  if tg_op = 'INSERT' then
    insert into public.colis_historique (colis_id, statut, lieu, note, auteur)
    values (new.id, new.statut, new.lieu, new.note, v_auteur);
  elsif new.statut is distinct from old.statut
        or new.lieu is distinct from old.lieu
        or new.note is distinct from old.note then
    insert into public.colis_historique (colis_id, statut, lieu, note, auteur)
    values (new.id, new.statut, new.lieu, new.note, v_auteur);
  end if;
  return null;
end;
$$;

drop trigger if exists historiser_colis on public.colis;
create trigger historiser_colis
  after insert or update on public.colis
  for each row execute function public.historiser_colis();

-- Numéro de facture, et date de règlement posée (ou retirée) avec le statut.
create or replace function public.preparer_facture()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if coalesce(trim(new.numero), '') = '' then
    new.numero := 'FAC-' || to_char(now(), 'YYYY') || '-'
                  || lpad(nextval('public.numero_facture_seq')::text, 4, '0');
  end if;
  if new.statut = 'payee' and new.payee_le is null then
    new.payee_le := now();
  elsif new.statut = 'impayee' then
    new.payee_le := null;
  end if;
  return new;
end;
$$;

drop trigger if exists preparer_facture on public.factures;
create trigger preparer_facture
  before insert or update on public.factures
  for each row execute function public.preparer_facture();


-- 4. Rôles et permissions -------------------------------------------------------

create or replace function public.est_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (select 1 from public.clients where id = auth.uid() and role = 'admin')
$$;

-- Le contrôle unique dont dépendent toutes les règles ci-dessous : un
-- administrateur peut tout ; un employé, seulement ce qui lui a été coché ;
-- un client, rien de tout cela.
create or replace function public.a_droit(p_droit text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.clients
    where id = auth.uid()
      and (role = 'admin' or (role = 'employe' and p_droit = any (droits)))
  )
$$;

alter table public.clients enable row level security;
alter table public.colis enable row level security;
alter table public.colis_historique enable row level security;
alter table public.factures enable row level security;

-- --- clients ---
drop policy if exists clients_lecture on public.clients;
create policy clients_lecture on public.clients
  for select to authenticated
  using (id = (select auth.uid()) or (select public.a_droit('clients.lire')));

drop policy if exists clients_modification on public.clients;
create policy clients_modification on public.clients
  for update to authenticated
  using (id = (select auth.uid()) or (select public.est_admin()))
  with check (id = (select auth.uid()) or (select public.est_admin()));

-- --- colis ---
drop policy if exists colis_lecture on public.colis;
create policy colis_lecture on public.colis
  for select to authenticated
  using (client_id = (select auth.uid()) or (select public.a_droit('colis.lire')));

drop policy if exists colis_ajout on public.colis;
create policy colis_ajout on public.colis
  for insert to authenticated
  with check ((select public.a_droit('colis.creer')));

-- « colis.modifier » couvre la fiche entière ; « colis.statut » ne sert qu'au
-- statut, au lieu et à la note. La vérification fine est faite par le
-- déclencheur ci-dessous : une règle de ligne ne sait pas quelles colonnes
-- ont changé.
drop policy if exists colis_modification on public.colis;
create policy colis_modification on public.colis
  for update to authenticated
  using ((select public.a_droit('colis.modifier')) or (select public.a_droit('colis.statut')))
  with check ((select public.a_droit('colis.modifier')) or (select public.a_droit('colis.statut')));

create or replace function public.verifier_modification_colis()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if public.a_droit('colis.modifier') then
    return new;
  end if;
  -- Sans ce droit, seuls le statut, le lieu et la note peuvent changer.
  if new.client_id is distinct from old.client_id
     or new.description is distinct from old.description
     or new.expediteur is distinct from old.expediteur
     or new.destinataire is distinct from old.destinataire
     or new.poids_lb is distinct from old.poids_lb
     or new.service is distinct from old.service
     or new.pays_destination is distinct from old.pays_destination
     or new.ville_destination is distinct from old.ville_destination
     or new.adresse_livraison is distinct from old.adresse_livraison
     or new.valeur_declaree is distinct from old.valeur_declaree then
    raise exception 'Modification du colis réservée : il vous manque le droit « colis.modifier ».'
      using errcode = '42501';
  end if;
  return new;
end;
$$;

drop trigger if exists verifier_modification_colis on public.colis;
create trigger verifier_modification_colis
  before update on public.colis
  for each row execute function public.verifier_modification_colis();

drop policy if exists colis_suppression on public.colis;
create policy colis_suppression on public.colis
  for delete to authenticated
  using ((select public.a_droit('colis.supprimer')));

-- --- historique ---
drop policy if exists historique_lecture on public.colis_historique;
create policy historique_lecture on public.colis_historique
  for select to authenticated
  using (
    (select public.a_droit('colis.lire'))
    or exists (select 1 from public.colis c where c.id = colis_id and c.client_id = (select auth.uid()))
  );

-- --- factures ---
drop policy if exists factures_lecture on public.factures;
create policy factures_lecture on public.factures
  for select to authenticated
  using (client_id = (select auth.uid()) or (select public.a_droit('factures.lire')));

drop policy if exists factures_ajout on public.factures;
create policy factures_ajout on public.factures
  for insert to authenticated
  with check ((select public.a_droit('factures.creer')));

drop policy if exists factures_modification on public.factures;
create policy factures_modification on public.factures
  for update to authenticated
  using ((select public.a_droit('factures.modifier')))
  with check ((select public.a_droit('factures.modifier')));

drop policy if exists factures_suppression on public.factures;
create policy factures_suppression on public.factures
  for delete to authenticated
  using ((select public.a_droit('factures.supprimer')));


-- 5. Droits sur les tables ------------------------------------------------------
-- Depuis 2026, Supabase n'ouvre plus automatiquement les nouvelles tables :
-- chaque droit est accordé ici, et les règles ci-dessus limitent ensuite les
-- lignes que chacun voit.

grant usage on schema public to anon, authenticated, service_role;

revoke all on public.clients, public.colis, public.colis_historique, public.factures from anon;

grant select on public.clients, public.colis_historique to authenticated;
grant select, insert, update, delete on public.colis, public.factures to authenticated;
grant select, insert, update, delete on
  public.clients, public.colis, public.colis_historique, public.factures to service_role;

-- Un client ne modifie que ses coordonnées : jamais son identifiant, jamais
-- son rôle, jamais ses droits. Le rôle passe par definir_role() et rien d'autre.
revoke insert, update, delete on public.clients from authenticated;
grant update (nom_complet, pays, region, ville, adresse, telephone, langue)
  on public.clients to authenticated;
revoke insert, update, delete on public.colis_historique from authenticated;


-- 6. Vues du tableau de bord ----------------------------------------------------
-- « security_invoker » : la vue obéit aux règles de celui qui la lit, pas à
-- celles de son auteur. Un client n'y verra donc que ses propres lignes.

drop view if exists public.colis_details;
create view public.colis_details
with (security_invoker = true) as
  select c.*,
         cl.code        as code_client,
         cl.nom_complet as nom_client,
         cl.telephone   as telephone_client,
         cl.email       as email_client,
         cl.ville       as ville_client,
         cl.pays        as pays_client
  from public.colis c
  left join public.clients cl on cl.id = c.client_id;

drop view if exists public.factures_details;
create view public.factures_details
with (security_invoker = true) as
  select f.*,
         cl.code        as code_client,
         cl.nom_complet as nom_client,
         cl.email       as email_client,
         co.numero      as numero_colis
  from public.factures f
  left join public.clients cl on cl.id = f.client_id
  left join public.colis co on co.id = f.colis_id;

revoke all on public.colis_details, public.factures_details from anon;
grant select on public.colis_details, public.factures_details to authenticated, service_role;


-- 7. Fonctions appelées par le site ---------------------------------------------

-- Suivi public (formulaire « Où est mon colis ? ») : statut et étapes
-- seulement. Ni nom, ni adresse, ni note interne — cette fonction est
-- ouverte aux visiteurs.
create or replace function public.suivre_colis(p_numero text)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select jsonb_build_object(
    'numero', c.numero,
    'statut', c.statut,
    'service', c.service,
    'pays_destination', c.pays_destination,
    'maj_le', c.maj_le,
    'historique', coalesce((
      select jsonb_agg(jsonb_build_object('statut', h.statut, 'lieu', h.lieu, 'cree_le', h.cree_le)
                       order by h.cree_le)
      from public.colis_historique h
      where h.colis_id = c.id), '[]'::jsonb))
  from public.colis c
  where length(trim(coalesce(p_numero, ''))) >= 4
    and c.numero = upper(trim(p_numero))
  limit 1
$$;

-- Chiffres du tableau de bord
create or replace function public.statistiques_ses()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  if not public.a_droit('colis.lire') then
    raise exception 'Accès réservé' using errcode = '42501';
  end if;
  return jsonb_build_object(
    'clients', (select count(*) from public.clients where role = 'client'),
    'colis', (select count(*) from public.colis),
    'statuts', coalesce((select jsonb_object_agg(s.statut, s.n)
                         from (select statut, count(*) as n from public.colis group by statut) s),
                        '{}'::jsonb),
    'factures_impayees', (select count(*) from public.factures where statut = 'impayee'),
    'montant_impaye', (select coalesce(sum(montant), 0) from public.factures where statut = 'impayee'));
end;
$$;

-- Changer le rôle d'un compte, et les droits d'un employé. Réservé à qui a
-- le droit « roles.gerer », c'est-à-dire un administrateur ou un employé à
-- qui un administrateur l'a confié.
create or replace function public.definir_role(p_id uuid, p_role text, p_droits text[] default '{}')
returns public.clients
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_ligne public.clients;
  v_droits text[];
begin
  if not public.a_droit('roles.gerer') then
    raise exception 'Gestion des rôles réservée.' using errcode = '42501';
  end if;
  if p_role not in ('client', 'employe', 'admin') then
    raise exception 'Rôle inconnu : %.', p_role using errcode = '22023';
  end if;
  -- Personne ne se retire ses propres droits d'administration : sans cette
  -- règle, le dernier administrateur pourrait fermer la porte de l'intérieur.
  if p_id = auth.uid() and p_role <> 'admin' then
    raise exception 'Un administrateur ne peut pas retirer son propre rôle.' using errcode = '42501';
  end if;
  -- Seul un administrateur nomme un administrateur.
  if p_role = 'admin' and not public.est_admin() then
    raise exception 'Seul un administrateur peut en nommer un autre.' using errcode = '42501';
  end if;

  v_droits := case
    when p_role = 'admin' then array[]::text[]
    when p_role = 'employe' then coalesce(p_droits, '{}')
    else array[]::text[]
  end;

  update public.clients
     set role = p_role,
         droits = v_droits,
         -- L'identifiant client est conservé quel que soit le rôle : un employé
         -- peut lui aussi recevoir des colis.
         code = coalesce(code, public.nouveau_code_client())
   where id = p_id
   returning * into v_ligne;

  if v_ligne.id is null then
    raise exception 'Aucun compte avec cet identifiant.' using errcode = '22023';
  end if;
  return v_ligne;
end;
$$;

-- Désigner le premier administrateur (depuis le SQL Editor uniquement).
create or replace function public.definir_admin(p_email text)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_id uuid;
begin
  select id into v_id from public.clients where lower(email) = lower(trim(p_email));
  if v_id is null then
    raise exception 'Aucun compte avec l''adresse %. Créez d''abord le compte sur la page « Créer un compte ».', p_email;
  end if;
  update public.clients set role = 'admin', droits = '{}' where id = v_id;
  return 'Le compte ' || p_email || ' est maintenant administrateur.';
end;
$$;

-- Qui peut appeler quoi
revoke execute on function public.creer_profil_client() from public, anon, authenticated;
revoke execute on function public.nouveau_code_client() from public, anon, authenticated;
revoke execute on function public.preparer_colis() from public, anon, authenticated;
revoke execute on function public.historiser_colis() from public, anon, authenticated;
revoke execute on function public.preparer_facture() from public, anon, authenticated;
revoke execute on function public.verifier_modification_colis() from public, anon, authenticated;
revoke execute on function public.definir_admin(text) from public, anon, authenticated;
revoke execute on function public.statistiques_ses() from public, anon;
revoke execute on function public.definir_role(uuid, text, text[]) from public, anon;
grant execute on function public.statistiques_ses() to authenticated;
grant execute on function public.definir_role(uuid, text, text[]) to authenticated;
grant execute on function public.est_admin() to authenticated;
grant execute on function public.a_droit(text) to authenticated;
grant execute on function public.suivre_colis(text) to anon, authenticated;


-- 8. Temps réel ------------------------------------------------------------------
-- L'espace client et le tableau de bord se mettent à jour d'eux-mêmes quand un
-- colis change. Les règles de sécurité s'appliquent aussi à ces messages :
-- un client ne reçoit que ce qui le concerne.

do $$
begin
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'colis') then
    alter publication supabase_realtime add table public.colis;
  end if;
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'colis_historique') then
    alter publication supabase_realtime add table public.colis_historique;
  end if;
  if not exists (select 1 from pg_publication_tables
                 where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'factures') then
    alter publication supabase_realtime add table public.factures;
  end if;
end
$$;
