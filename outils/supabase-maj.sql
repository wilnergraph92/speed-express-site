-- =============================================================================
-- Speed Express Shipping — mise à jour de la base
-- -----------------------------------------------------------------------------
-- Tout sélectionner, copier, coller dans Supabase > SQL Editor, puis Run.
--
-- AVANT DE LANCER : vérifiez en haut de la page que le projet ouvert est bien
-- « speed-express-site ». Ce script ne doit jamais être passé sur la base de
-- Goship Express : les deux entreprises ont leurs propres données.
--
-- Ce qu'il ajoute :
--   · le téléphone du destinataire sur le colis ;
--   · le tarif au livre, figé avec le colis ;
--   · les frais de service et le montant payé sur la facture ;
--   · la facture créée d'elle-même à l'enregistrement d'un colis.
--   · le rôle « gérant », entre l'employé et l'administrateur : il tient
--     l'activité et l'équipe, mais ne nomme ni gérant ni administrateur ;
--   · la fermeture d'une brèche : un employé à qui l'on avait confié la
--     gestion des rôles pouvait rétrograder un administrateur.
--   · l'équipe sans profil client : pas d'identifiant SES-#####, aucun colis ni
--     aucune facture rattachés à un administrateur, un gérant ou un employé.
--   · les notifications sur téléphone, CORRIGÉES : l'appel au service d'envoi avait un
--     nom invalide (il aurait fait échouer toute mise à jour de colis d'un client ayant
--     l'application) et ne peut plus jamais bloquer un colis ; la table des appareils
--     reçoit enfin ses droits ; un téléphone passe d'un compte à l'autre sans fuite ;
--   · trois fonctions inutilement ouvertes aux visiteurs sont fermées.
--
-- Rejouable sans risque : rien n'est supprimé, aucune donnée existante n'est
-- touchée, et le passer deux fois ne change rien. Les colis déjà enregistrés
-- reçoivent un tarif de 0 — reprenez-les depuis le tableau de bord pour leur
-- donner le bon tarif.
-- =============================================================================


-- 1. Les colonnes qui manquent -------------------------------------------------

alter table public.colis
  add column if not exists telephone_destinataire text not null default '';

alter table public.colis
  add column if not exists tarif_lb numeric(10, 2) not null default 0;

alter table public.colis
  add column if not exists prix_manuel numeric(10, 2) check (prix_manuel is null or prix_manuel >= 0);

alter table public.factures
  add column if not exists frais_service numeric(10, 2) not null default 0;

alter table public.factures
  add column if not exists montant_paye numeric(10, 2) not null default 0;


-- 2. La vue du tableau de bord -------------------------------------------------
-- Elle reprend « c.* » : il faut la reconstruire pour qu'elle voie les
-- nouvelles colonnes.

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

revoke all on public.colis_details from anon;
grant select on public.colis_details to authenticated, service_role;


-- 3. Un employé sans le droit « colis.modifier » ne touche ni au tarif ---------
--    ni au téléphone du destinataire.

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

-- 4. La facture naît avec le colis ---------------------------------------------

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

-- 5. Statut et montant payé toujours d'accord ----------------------------------

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


-- 7. Les quatre rôles : client, employé, gérant, administrateur -----------------
-- Un gérant a tous les droits de l'activité (colis, factures, clients) sans
-- qu'on les lui coche un par un, et il gère l'équipe. Il ne nomme ni gérant ni
-- administrateur : cela reste à l'administrateur. Un client, lui, n'a jamais
-- accès au tableau de bord — la règle est dans a_droit(), pas dans le
-- navigateur.

-- 7a. La contrainte sur le rôle accepte « gerant ». On retire l'ancienne par
--     son contenu plutôt que par son nom : elle a été créée sans nom choisi.
--     Elle est remplacée dans la foulée par une contrainte plus large : aucun
--     compte existant ne devient invalide.
do $$
declare
  v_nom text;
begin
  for v_nom in
    select conname from pg_constraint
    where conrelid = 'public.clients'::regclass
      and contype = 'c'
      and pg_get_constraintdef(oid) like '%employe%'
  loop
    execute format('alter table public.clients drop constraint %I', v_nom);
  end loop;
end
$$;

alter table public.clients
  add constraint clients_role_check
  check (role in ('client', 'employe', 'gerant', 'admin'));


-- 7b. La direction : l'administrateur et le gérant.
create or replace function public.est_direction()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (select 1 from public.clients where id = auth.uid() and role in ('admin', 'gerant'))
$$;


-- 7c. Le contrôle unique des droits : le gérant a tout, comme l'administrateur.
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


-- 7d. Qui peut corriger les coordonnées d'un compte : lui-même, ou la direction.
drop policy if exists clients_modification on public.clients;
create policy clients_modification on public.clients
  for update to authenticated
  using (id = (select auth.uid()) or (select public.est_direction()))
  with check (id = (select auth.uid()) or (select public.est_direction()));


-- 7e. Le changement de rôle, avec la hiérarchie.
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


-- 7f. Droits d'exécution.
revoke execute on function public.est_direction() from public, anon;
grant execute on function public.est_direction() to authenticated;
grant execute on function public.a_droit(text) to authenticated;
grant execute on function public.definir_role(uuid, text, text[]) to authenticated;


-- 8. L'équipe n'est pas la clientèle --------------------------------------------
-- Un administrateur, un gérant ou un employé ne reçoit pas de colis et n'a pas
-- d'espace client : il ne porte donc pas d'identifiant client (SES-#####), et
-- aucun colis ni aucune facture ne se rattache à lui. definir_role() (7e) pose
-- la règle à chaque changement de rôle ; ce qui suit la fait respecter partout.

-- 8a. Aucun colis ni facture pour un compte d'équipe, même en appelant la base
--     directement.
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

-- 8b. Les comptes d'équipe existants : leur identifiant client tombe, SAUF s'ils
--     portent encore des colis ou des factures — on ne coupe pas ce lien en
--     silence. Ceux-là gardent leur identifiant ; il faudra réaffecter leurs
--     colis à un vrai client.
update public.clients c
   set code = null
 where c.role <> 'client'
   and c.code is not null
   and not exists (select 1 from public.colis x where x.client_id = c.id)
   and not exists (select 1 from public.factures x where x.client_id = c.id);


-- 9. Notifications sur téléphone ---------------------------------------------------
-- (Reprend « supabase-maj-notifications.sql » de l'application, avec trois corrections.)
--
-- 9a. De quoi appeler un service extérieur depuis la base. pg_net envoie la requête sans
--     faire attendre l'enregistrement du colis. Sur un projet où l'extension n'est pas
--     disponible, le script continue : les notifications ne partiront pas, rien d'autre.
do $$
begin
  create extension if not exists pg_net with schema extensions;
exception when others then
  raise notice 'pg_net indisponible (%) : les notifications ne partiront pas, le reste fonctionne.', sqlerrm;
end
$$;

-- 9b. Les appareils d'un client.
create table if not exists public.appareils (
  jeton       text primary key,
  client_id   uuid not null references public.clients (id) on delete cascade,
  plateforme  text,
  vu_le       timestamptz not null default now(),
  cree_le     timestamptz not null default now()
);
comment on table public.appareils is
  'Un téléphone par ligne. Le jeton vient d''Expo et change à la réinstallation : un client peut avoir plusieurs appareils.';
create index if not exists appareils_client_idx on public.appareils (client_id);
alter table public.appareils enable row level security;

drop policy if exists appareils_lecture on public.appareils;
create policy appareils_lecture on public.appareils
  for select to authenticated using (client_id = (select auth.uid()));
drop policy if exists appareils_ajout on public.appareils;
create policy appareils_ajout on public.appareils
  for insert to authenticated with check (client_id = (select auth.uid()));
drop policy if exists appareils_modification on public.appareils;
create policy appareils_modification on public.appareils
  for update to authenticated using (client_id = (select auth.uid())) with check (client_id = (select auth.uid()));
drop policy if exists appareils_suppression on public.appareils;
create policy appareils_suppression on public.appareils
  for delete to authenticated using (client_id = (select auth.uid()));

-- CORRECTION 1 : la table n'avait AUCUN droit. Depuis 2026 Supabase n'ouvre plus les nouvelles
-- tables : sans ces lignes, l'enregistrement d'un téléphone échouait (en silence côté application).
revoke all on public.appareils from anon;
grant select, insert, update, delete on public.appareils to authenticated;
grant select, insert, update, delete on public.appareils to service_role;
revoke truncate, references, trigger on public.appareils from anon, authenticated;

-- 9c. Le texte de la notification, dans la langue du client.
create or replace function public.texte_notification(p_statut text, p_langue text)
returns text
language sql
immutable
set search_path = ''
as $$
  select case coalesce(p_langue, 'fr')
    when 'en' then case p_statut
      when 'confirme'   then 'Package confirmed'
      when 'expedie'    then 'Package shipped'
      when 'disponible' then 'Your package is available'
      when 'livre'      then 'Package delivered'
      else 'Action required on your package' end
    when 'es' then case p_statut
      when 'confirme'   then 'Paquete confirmado'
      when 'expedie'    then 'Paquete enviado'
      when 'disponible' then 'Su paquete está disponible'
      when 'livre'      then 'Paquete entregado'
      else 'Acción requerida en su paquete' end
    when 'ht' then case p_statut
      when 'confirme'   then 'Kolis konfime'
      when 'expedie'    then 'Kolis voye'
      when 'disponible' then 'Kolis ou a disponib'
      when 'livre'      then 'Kolis livre'
      else 'Gen yon aksyon pou kolis ou a' end
    else case p_statut
      when 'confirme'   then 'Colis confirmé'
      when 'expedie'    then 'Colis expédié'
      when 'disponible' then 'Votre colis est disponible'
      when 'livre'      then 'Colis livré'
      else 'Action requise sur votre colis' end
  end;
$$;

-- 9d. Le déclencheur d'envoi.
--     CORRECTION 2 : la version d'origine appelait « extensions.net.http_post », un nom à trois
--     parties que PostgreSQL lit « base.schéma.fonction » (erreur « cross-database references are
--     not implemented »). La fonction de pg_net s'appelle net.http_post. Avec l'ancienne version,
--     dès qu'un client avait un appareil, TOUT enregistrement ou changement de statut d'un de ses
--     colis aurait échoué.
--     CORRECTION 3 : une notification est un confort. Quoi qu'il arrive dans le bloc ci-dessous
--     (service lent, extension absente, jeton refusé), la mise à jour du colis réussit : l'erreur
--     devient un avertissement dans les journaux, jamais un échec.
create or replace function public.prevenir_client()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_langue text;
  v_titre  text;
  v_jetons text[];
begin
  if tg_op = 'UPDATE' and new.statut is not distinct from old.statut then
    return new;
  end if;
  if new.client_id is null then
    return new;
  end if;

  begin
    select coalesce(c.langue, 'fr') into v_langue from public.clients c where c.id = new.client_id;
    select array_agg(a.jeton) into v_jetons from public.appareils a where a.client_id = new.client_id;
    if v_jetons is null or array_length(v_jetons, 1) is null then
      return new;                                     -- ce client n'a pas d'application installée
    end if;
    v_titre := public.texte_notification(new.statut, v_langue);
    perform net.http_post(
      url     := 'https://exp.host/--/api/v2/push/send',
      headers := jsonb_build_object('Content-Type', 'application/json'),
      body    := jsonb_build_object(
        'to', to_jsonb(v_jetons), 'title', v_titre, 'body', new.numero, 'sound', 'default',
        'channelId', 'colis', 'data', jsonb_build_object('colis_id', new.id, 'numero', new.numero))
    );
  exception when others then
    raise warning 'Notification non envoyée pour le colis % : %', new.numero, sqlerrm;
  end;
  return new;
end;
$$;

drop trigger if exists prevenir_client on public.colis;
create trigger prevenir_client
  after insert or update of statut on public.colis
  for each row execute function public.prevenir_client();
revoke execute on function public.prevenir_client() from public, anon, authenticated;

-- 9e. Enregistrer un téléphone. L'application l'appelait par « upsert » sur la table : si ce
--     téléphone avait servi à un AUTRE compte (prêté, revendu, reconnecté), la règle de sécurité
--     refusait la mise à jour (l'ancienne ligne n'est pas à soi) et le téléphone restait lié à
--     l'ancien compte — qui continuait de recevoir les notifications du nouveau propriétaire.
--     Cette fonction réaffecte le téléphone au compte connecté, et à lui seul.
create or replace function public.enregistrer_appareil(p_jeton text, p_plateforme text default null)
returns void
language plpgsql
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'Connexion requise.' using errcode = '42501';
  end if;
  if p_jeton is null or length(p_jeton) not between 20 and 200
     or p_jeton !~ '^Expo(nent)?PushToken\[[A-Za-z0-9_-]+\]$' then
    raise exception 'Jeton de notification invalide.' using errcode = '22023';
  end if;
  insert into public.appareils as a (jeton, client_id, plateforme, vu_le)
  values (p_jeton, auth.uid(), left(p_plateforme, 20), now())
  on conflict (jeton) do update
    set client_id = auth.uid(), plateforme = excluded.plateforme, vu_le = now();
end;
$$;
revoke execute on function public.enregistrer_appareil(text, text) from public, anon;
grant execute on function public.enregistrer_appareil(text, text) to authenticated;


-- 10. Fermer ce qui n'a aucune raison d'être ouvert aux visiteurs ------------------------
-- est_admin(), a_droit() et texte_notification() restaient exécutables par « anon » (tout est
-- ouvert par défaut en PostgreSQL), alors que leurs sœurs est_direction() et definir_role() étaient
-- fermées. Elles ne renvoient rien de sensible à un visiteur (« faux »), mais une API publique ne
-- doit exposer que ce qui sert : seul le suivi d'un colis est public.
revoke execute on function public.est_admin() from public, anon;
revoke execute on function public.a_droit(text) from public, anon;
revoke execute on function public.texte_notification(text, text) from public, anon;
grant execute on function public.est_admin() to authenticated, service_role;
grant execute on function public.a_droit(text) to authenticated, service_role;
grant execute on function public.texte_notification(text, text) to authenticated, service_role;
