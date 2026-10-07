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
--   colis             les colis, chacun rattaché à un client (SES-4821937065…),
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

-- Numéros de colis : « SES- » et dix chiffres au hasard (SES-4821937065), tirés par
-- preparer_colis(). La séquence ne sert plus ; elle reste pour les bases qui l'ont.
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
              check (role in ('client', 'employe', 'gerant', 'admin')),
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
  -- Le numéro appelé à la livraison. Vide, l'étiquette reprend celui du
  -- compte client : le destinataire est le plus souvent le client lui-même.
  telephone_destinataire text not null default '',
  poids_lb          numeric(8, 2) check (poids_lb is null or poids_lb >= 0),
  -- Tarif d'expédition au livre, choisi colis par colis à l'enregistrement.
  -- Il reste attaché à ce colis : changer le tarif d'un colis suivant ne
  -- touche jamais celui-ci, ni la facture qui en est née.
  tarif_lb          numeric(10, 2) not null default 0 check (tarif_lb >= 0),
  -- Prix du colis saisi à la main par l'équipe, quand poids × tarif ne convient pas (forfait,
  -- geste commercial, colis hors gabarit). Vide : le prix est poids × tarif, comme toujours.
  prix_manuel       numeric(10, 2) check (prix_manuel is null or prix_manuel >= 0),
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
  -- Supprimer un colis conserve sa facture (pièce comptable) : le lien est
  -- retiré, mais le numéro et les prix restent figés dans « lignes ».
  colis_id    uuid references public.colis (id) on delete set null,
  -- « montant » est le grand total : colis + frais de service. C'est ce que
  -- le client doit, et c'est lui qui s'affiche partout dans le site.
  montant     numeric(10, 2) not null default 0 check (montant >= 0),
  frais_service numeric(10, 2) not null default 0 check (frais_service >= 0),
  montant_paye  numeric(10, 2) not null default 0 check (montant_paye >= 0),
  devise      text not null default 'USD',
  statut      text not null default 'impayee' check (statut in ('impayee', 'payee')),
  note        text not null default '',
  lignes      jsonb not null default '[]'::jsonb,
  echeance_le date,
  cree_le     timestamptz not null default now(),
  payee_le    timestamptz,
  -- Vrai quand la facture regroupe plusieurs colis (colis_id vide, une ligne par colis).
  groupee     boolean not null default false
);
-- Pour une base créée avant cette colonne (create table if not exists ne modifie pas l'existante).
alter table public.factures add column if not exists groupee boolean not null default false;

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
declare
  v_numero text;
begin
  if tg_op = 'INSERT' then
    if coalesce(trim(new.numero), '') = '' then
      -- « SES- » suivi de dix chiffres tirés au hasard (le premier jamais nul : un tableur
      -- n'en mange aucun), puisés dans gen_random_uuid(), aléa cryptographique : un numéro
      -- ne permet pas de deviner le suivant. On retire tant que le numéro existe déjà ; la
      -- contrainte « unique » de la colonne reste le dernier rempart.
      loop
        v_numero := 'SES-' || (1000000000
          + ('x' || substr(md5(gen_random_uuid()::text), 1, 15))::bit(60)::bigint % 9000000000)::text;
        exit when not exists (select 1 from public.colis c where c.numero = v_numero);
      end loop;
      new.numero := v_numero;
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

-- Tout colis enregistré reçoit aussitôt sa facture. Le calcul est fait ici, et
-- non dans le navigateur : la facture ne peut donc jamais manquer, ni viser le
-- mauvais client.
--
-- Tant que rien n'a été réglé, la facture suit le colis — corriger un poids mal
-- saisi corrige la facture. Dès qu'un paiement est enregistré, elle se fige :
-- c'est ce qui garantit qu'une facture ancienne ne bouge plus.
create or replace function public.facturer_colis()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  -- Le prix du colis : celui saisi à la main par l'équipe s'il y en a un, sinon poids × tarif.
  v_total numeric(10, 2) := coalesce(new.prix_manuel,
                                     round(coalesce(new.poids_lb, 0) * coalesce(new.tarif_lb, 0), 2));
  v_frais numeric(10, 2) := 10;
  v_ligne jsonb;
begin
  if new.client_id is null then
    return null;   -- sans client, il n'y a personne à facturer
  end if;

  v_ligne := jsonb_build_array(jsonb_build_object(
    'colis_id',    new.id,
    'numero',      new.numero,
    'description', new.description,
    'quantite',    1,
    'poids_lb',    coalesce(new.poids_lb, 0),
    'tarif_lb',    coalesce(new.tarif_lb, 0),
    'prix_manuel', new.prix_manuel is not null,
    'montant',     v_total));

  if tg_op = 'INSERT' then
    insert into public.factures (client_id, colis_id, montant, frais_service, lignes)
    values (new.client_id, new.id, v_total + v_frais, v_frais, v_ligne);
    return null;
  end if;

  if new.poids_lb is distinct from old.poids_lb
     or new.tarif_lb is distinct from old.tarif_lb
     or new.prix_manuel is distinct from old.prix_manuel
     or new.description is distinct from old.description
     or new.client_id is distinct from old.client_id then
    update public.factures
       set montant   = v_total + frais_service,
           lignes    = v_ligne,
           client_id = new.client_id
     where colis_id = new.id
       and statut = 'impayee'
       and montant_paye = 0;
  end if;
  return null;
end;
$$;

drop trigger if exists facturer_colis on public.colis;
create trigger facturer_colis
  after insert or update on public.colis
  for each row execute function public.facturer_colis();


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
  -- Le statut et le montant payé ne peuvent pas se contredire : une facture
  -- « payée » dont la balance resterait entière n'aurait aucun sens.
  if tg_op = 'INSERT' then
    if new.statut = 'payee' and new.montant_paye = 0 then
      new.montant_paye := new.montant;
    elsif new.montant > 0 and new.montant_paye >= new.montant then
      new.statut := 'payee';
    end if;
  elsif new.statut is distinct from old.statut then
    -- Basculer le statut à la main vaut règlement complet, ou remise à zéro.
    new.montant_paye := case when new.statut = 'payee' then new.montant else 0 end;
  elsif new.montant_paye is distinct from old.montant_paye
        or new.montant is distinct from old.montant then
    new.statut := case when new.montant > 0 and new.montant_paye >= new.montant
                       then 'payee' else 'impayee' end;
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

-- La direction : l'administrateur et le gérant. C'est elle qui tient l'activité
-- (tous les droits sur les colis, les factures et les clients) ; seul
-- l'administrateur, lui, nomme ou retire un gérant ou un administrateur.
create or replace function public.est_direction()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (select 1 from public.clients where id = auth.uid() and role in ('admin', 'gerant'))
$$;

-- Le contrôle unique dont dépendent toutes les règles ci-dessous : un
-- administrateur et un gérant peuvent tout ; un employé, seulement ce qui lui
-- a été coché ; un client, rien de tout cela — jamais, quel que soit le contenu
-- de sa colonne « droits ».
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
      and (role in ('admin', 'gerant') or (role = 'employe' and p_droit = any (droits)))
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
  using (id = (select auth.uid()) or (select public.est_direction()))
  with check (id = (select auth.uid()) or (select public.est_direction()));

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
     or new.telephone_destinataire is distinct from old.telephone_destinataire
     or new.poids_lb is distinct from old.poids_lb
     or new.tarif_lb is distinct from old.tarif_lb
     or new.prix_manuel is distinct from old.prix_manuel
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
--
-- Le jeton du QR code est facultatif : s'il est donné, il doit correspondre ; sans lui, le
-- numéro seul suffit (voir docs/security/TRACKING-SECURITY.md pour ce choix).
--
-- L'ancienne version à UN paramètre est retirée avant de créer celle-ci : sinon les deux
-- coexisteraient, et PostgreSQL répondrait « function … is not unique » à chaque appel
-- avec le seul numéro — le suivi public cesserait de fonctionner.
drop function if exists public.suivre_colis(text);

create or replace function public.suivre_colis(p_numero text, p_jeton text default null)
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
    and (p_jeton is null or c.jeton = p_jeton)
  limit 1
$$;

-- Chiffres du tableau de bord. (Version « invoker » : elle obéit aux règles de celui qui l'appelle ;
-- l'ancienne version « definer » est retirée — voir outils/supabase-dashboard.sql.)
-- Compatibilité : même signature jsonb, aucun agrégat d'un domaine interdit.
-- Le montant scalaire obsolète reste NULL : jamais de mélange de devises ni
-- de modification silencieuse en « USD seulement ». Le nouveau frontend ne
-- consomme plus cette RPC. Les soldes par devise sont explicitement séparés.
create or replace function public.statistiques_ses()
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare r jsonb;
begin
  if not public.a_droit('colis.lire') then raise exception 'Accès réservé' using errcode='42501'; end if;
  r := jsonb_build_object('colis',(select count(*) from public.colis),
    'statuts',coalesce((select jsonb_object_agg(statut,n) from (select statut,count(*) n from public.colis group by statut) x),'{}'::jsonb),
    'clients',null,'factures_impayees',null,'montant_impaye',null,'soldes_par_devise',null);
  if public.a_droit('clients.lire') then
    r := r || jsonb_build_object('clients',(select count(*) from public.clients where role='client'));
  end if;
  if public.a_droit('factures.lire') then
    r := r || jsonb_build_object('factures_impayees',(select count(*) from public.factures where montant>montant_paye),
      'soldes_par_devise',coalesce((select jsonb_agg(to_jsonb(x)) from (
        select devise,sum(greatest(montant-montant_paye,0))::text solde,
          sum(greatest(montant_paye-montant,0))::text trop_percu
        from public.factures group by devise order by devise
      ) x),'[]'::jsonb));
  end if;
  return r;
end $$;

-- Changer le rôle d'un compte, et les droits d'un employé. Réservé à qui a
-- le droit « roles.gerer » : l'administrateur, le gérant, ou un employé à qui
-- on l'a confié.
--
-- La hiérarchie, appliquée ICI et non dans le navigateur — un navigateur se
-- contourne, une fonction de base non :
--   · seul un administrateur nomme, modifie ou retire un gérant ou un
--     administrateur ; un gérant, lui, gère les employés et les clients ;
--   · personne ne modifie son propre rôle (un gérant ne peut pas s'accorder
--     plus, un administrateur ne peut pas fermer la porte de l'intérieur) ;
--   · le gérant et l'administrateur n'ont pas de droits à cocher : leur rôle
--     les donne tous. Seul l'employé a une liste de droits.
--
-- Et l'équipe n'est pas la clientèle : un membre de l'équipe n'a ni espace
-- client, ni colis, ni facture, donc pas d'identifiant client (SES-#####).
--   · devenir membre de l'équipe efface l'identifiant — et c'est refusé si le
--     compte a déjà des colis ou des factures : il reste un client, sinon ils
--     perdraient leur propriétaire ;
--   · redevenir client en reçoit un nouveau.
create or replace function public.definir_role(p_id uuid, p_role text, p_droits text[] default '{}')
returns public.clients
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_ligne  public.clients;
  v_actuel text;
  v_droits text[];
  v_liens  boolean;
begin
  if not public.a_droit('roles.gerer') then
    raise exception 'Gestion des rôles réservée.' using errcode = '42501';
  end if;
  if p_role not in ('client', 'employe', 'gerant', 'admin') then
    raise exception 'Rôle inconnu : %.', p_role using errcode = '22023';
  end if;

  select role into v_actuel from public.clients where id = p_id;
  if v_actuel is null then
    raise exception 'Aucun compte avec cet identifiant.' using errcode = '22023';
  end if;

  -- Un administrateur qui se « rend » administrateur ne change rien ; tout
  -- autre cas de soi-même est refusé.
  if p_id = auth.uid() and not (v_actuel = 'admin' and p_role = 'admin') then
    raise exception 'Un administrateur ne peut pas retirer son propre rôle.' using errcode = '42501';
  end if;

  -- Ni nommer un gérant ou un administrateur, ni toucher à l'un d'eux, sans
  -- être administrateur.
  if (p_role in ('admin', 'gerant') or v_actuel in ('admin', 'gerant'))
     and not public.est_admin() then
    raise exception 'Seul un administrateur peut nommer ou modifier un gérant ou un administrateur.'
      using errcode = '42501';
  end if;

  v_liens := exists (select 1 from public.colis where client_id = p_id)
          or exists (select 1 from public.factures where client_id = p_id);

  -- Un client qui a des colis ou des factures ne passe pas dans l'équipe.
  if v_actuel = 'client' and p_role <> 'client' and v_liens then
    raise exception 'Ce compte a des colis ou des factures : il reste un client.'
      using errcode = 'SE001';
  end if;

  v_droits := case
    when p_role = 'employe' then coalesce(p_droits, '{}')
    else array[]::text[]
  end;

  update public.clients
     set role = p_role,
         droits = v_droits,
         code = case
           when p_role = 'client' then coalesce(code, public.nouveau_code_client())
           -- Un compte d'équipe qui porte encore des colis (hérité d'avant cette
           -- règle) garde son identifiant : on ne coupe pas ce lien en silence.
           when v_liens then code
           else null
         end
   where id = p_id
   returning * into v_ligne;

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

-- L'équipe n'est pas la clientèle -----------------------------------------------
-- Un colis ou une facture ne se rattache qu'à un compte client. Sans cette
-- règle, un membre de l'équipe pourrait encore recevoir des colis, par le
-- tableau de bord ou en appelant la base directement.
--
-- Elle n'examine qu'un NOUVEAU rattachement : un colis ou une facture créés, ou
-- dont le client change réellement. Un colis hérité d'avant la règle, encore
-- rattaché à un compte d'équipe, garde sa vie normale : changements de statut,
-- de poids, paiements. (Le déclencheur « update of client_id » ne suffirait pas :
-- il part dès que la colonne figure dans la requête, même inchangée, et
-- facturer_colis() la réécrit à chaque modification de poids ou de tarif.)
create or replace function public.verifier_client_rattache()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE' and new.client_id is not distinct from old.client_id then
    return new;
  end if;
  if new.client_id is not null
     and not exists (select 1 from public.clients where id = new.client_id and role = 'client') then
    raise exception 'Un colis ou une facture ne se rattache qu''à un compte client, jamais à un membre de l''équipe.'
      using errcode = 'SE002';
  end if;
  return new;
end;
$$;

drop trigger if exists verifier_client_colis on public.colis;
create trigger verifier_client_colis
  before insert or update of client_id on public.colis
  for each row execute function public.verifier_client_rattache();

drop trigger if exists verifier_client_facture on public.factures;
create trigger verifier_client_facture
  before insert or update of client_id on public.factures
  for each row execute function public.verifier_client_rattache();

revoke execute on function public.verifier_client_rattache() from public, anon, authenticated;

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
revoke execute on function public.est_direction() from public, anon;
grant execute on function public.est_direction() to authenticated;
grant execute on function public.a_droit(text) to authenticated;
grant execute on function public.suivre_colis(text, text) to anon, authenticated;


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
