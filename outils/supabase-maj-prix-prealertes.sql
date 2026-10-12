-- =============================================================================
-- Speed Express Shipping — mise à jour : prix saisi à la main, pré-alertes
-- -----------------------------------------------------------------------------
-- Tout sélectionner, copier, coller dans Supabase > SQL Editor, puis Run.
--
-- AVANT DE LANCER : vérifiez en haut de la page que le projet ouvert est bien
-- « speed-express-site ». Ce script ne doit jamais être passé sur la base de
-- Goship Express : les deux entreprises ont leurs propres données.
--
-- Ce qu'elle ajoute :
--   · le PRIX D'UN COLIS SAISI À LA MAIN par l'équipe (colonne « prix_manuel ») :
--     quand il est rempli, la facture le prend à la place de poids × tarif ;
--     vide, rien ne change. Les 10 $ de frais de service s'ajoutent toujours,
--     et une facture déjà payée (même en partie) ne bouge plus ;
--   · les PRÉ-ALERTES : le client annonce un achat depuis l'application, la
--     pré-alerte s'enregistre ici et apparaît dans le tableau de bord ; l'équipe
--     la marque reçue (en la reliant au colis) ou annulée.
--
-- Rejouable sans risque : rien n'est supprimé, aucun colis, aucune facture
-- existante n'est modifiée. Les fonctions sont les mêmes, mot pour mot, que
-- dans supabase.sql et supabase-maj.sql (test outils/tests/prealertes-sql.cjs).
-- =============================================================================


-- 1. Le prix saisi à la main ----------------------------------------------------

alter table public.colis
  add column if not exists prix_manuel numeric(10, 2) check (prix_manuel is null or prix_manuel >= 0);

-- La vue du tableau de bord reprend « c.* » : on la reconstruit pour qu'elle voie la colonne.
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


-- 2. Les pré-alertes -------------------------------------------------------------
-- Une pré-alerte appartient au client qui l'a faite. Il la crée et la relit ;
-- il ne la modifie pas. L'équipe (droit « colis.lire ») les voit toutes ;
-- avec « colis.statut » ou « colis.modifier », elle les marque reçues ou annulées
-- et les relie au colis arrivé. Personne ne les supprime par l'API.

create table if not exists public.prealertes (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid not null references public.clients (id) on delete cascade,
  magasin       text not null check (length(btrim(magasin)) between 1 and 80),
  contenu       text not null check (length(btrim(contenu)) between 1 and 200),
  -- Le numéro de suivi donné par le magasin (Amazon TBA…, UPS 1Z…) : c'est lui
  -- que l'entrepôt lit sur le carton à l'arrivée.
  numero_suivi  text not null default '' check (length(numero_suivi) <= 60),
  valeur        numeric(10, 2) check (valeur is null or valeur >= 0),
  service       text not null default 'aerien' check (service in ('aerien', 'maritime')),
  statut        text not null default 'attendue' check (statut in ('attendue', 'recue', 'annulee')),
  colis_id      uuid references public.colis (id) on delete set null,
  note          text not null default '' check (length(note) <= 400),
  cree_le       timestamptz not null default now(),
  maj_le        timestamptz not null default now()
);

create index if not exists prealertes_client_idx on public.prealertes (client_id, cree_le desc);
create index if not exists prealertes_attente_idx on public.prealertes (statut, cree_le desc);
create index if not exists prealertes_suivi_idx on public.prealertes (numero_suivi) where numero_suivi <> '';

-- Ce que chacun peut écrire, vérifié ici et pas seulement dans l'application :
--   · à la création, un client ne choisit ni le statut, ni le colis, ni la note, et
--     pas plus de 30 pré-alertes par 24 heures (un téléphone qui s'emballe ou un abus) ;
--   · ensuite, seuls le statut, le colis relié et la note changent, et le colis
--     relié doit appartenir au même client.
create or replace function public.preparer_prealerte()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'INSERT' then
    new.magasin := btrim(new.magasin);
    new.contenu := btrim(new.contenu);
    new.numero_suivi := upper(btrim(coalesce(new.numero_suivi, '')));
    new.statut := 'attendue';
    new.colis_id := null;
    new.note := '';
    new.cree_le := now();
    if (select count(*) from public.prealertes p
         where p.client_id = new.client_id and p.cree_le > now() - interval '24 hours') >= 30 then
      raise exception 'Trop de pré-alertes en 24 heures : réessayez plus tard ou écrivez-nous.'
        using errcode = 'SE003';
    end if;
  else
    if new.client_id is distinct from old.client_id
       or new.magasin is distinct from old.magasin
       or new.contenu is distinct from old.contenu
       or new.numero_suivi is distinct from old.numero_suivi
       or new.valeur is distinct from old.valeur
       or new.service is distinct from old.service
       or new.cree_le is distinct from old.cree_le then
      raise exception 'Une pré-alerte ne se modifie pas : seuls son statut, le colis relié et la note changent.'
        using errcode = '42501';
    end if;
    if new.colis_id is not null
       and not exists (select 1 from public.colis c where c.id = new.colis_id and c.client_id = new.client_id) then
      raise exception 'Ce colis n''appartient pas au client de la pré-alerte.'
        using errcode = 'SE004';
    end if;
  end if;
  new.maj_le := now();
  return new;
end;
$$;

drop trigger if exists preparer_prealerte on public.prealertes;
create trigger preparer_prealerte
  before insert or update on public.prealertes
  for each row execute function public.preparer_prealerte();

revoke execute on function public.preparer_prealerte() from public, anon, authenticated;

alter table public.prealertes enable row level security;

drop policy if exists prealertes_lecture on public.prealertes;
create policy prealertes_lecture on public.prealertes
  for select to authenticated
  using (client_id = (select auth.uid()) or (select public.a_droit('colis.lire')));

-- Seul un CLIENT crée une pré-alerte, et seulement pour lui-même.
drop policy if exists prealertes_ajout on public.prealertes;
create policy prealertes_ajout on public.prealertes
  for insert to authenticated
  with check (client_id = (select auth.uid())
              and exists (select 1 from public.clients c where c.id = (select auth.uid()) and c.role = 'client'));

drop policy if exists prealertes_traitement on public.prealertes;
create policy prealertes_traitement on public.prealertes
  for update to authenticated
  using ((select public.a_droit('colis.statut')) or (select public.a_droit('colis.modifier')))
  with check ((select public.a_droit('colis.statut')) or (select public.a_droit('colis.modifier')));

revoke all on public.prealertes from anon;
revoke insert, update, delete, truncate, references, trigger on public.prealertes from authenticated;
grant select on public.prealertes to authenticated;
grant insert (client_id, magasin, contenu, numero_suivi, valeur, service) on public.prealertes to authenticated;
grant update (statut, colis_id, note) on public.prealertes to authenticated;
grant select, insert, update, delete on public.prealertes to service_role;
