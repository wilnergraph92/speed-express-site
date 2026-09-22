-- =============================================================================
-- Speed Express Shipping — mise à jour : facturation au poids
-- -----------------------------------------------------------------------------
-- À passer une seule fois dans Supabase → SQL Editor, sur une base déjà en
-- service. Une installation neuve n'en a pas besoin : outils/supabase.sql
-- contient déjà tout ceci.
--
-- Ce qu'il change :
--   · le colis porte son tarif au livre, choisi à l'enregistrement ;
--   · la facture porte ses frais de service et le montant déjà payé ;
--   · tout colis enregistré reçoit aussitôt sa facture, calculée ici ;
--   · le statut « payée / impayée » et le montant payé restent d'accord.
--
-- Rejouable sans risque : rien n'est supprimé, aucune donnée existante n'est
-- touchée. Les colis déjà enregistrés reçoivent un tarif de 0 — reprenez-les
-- depuis le tableau de bord pour leur donner le bon tarif.
-- =============================================================================

alter table public.colis
  add column if not exists tarif_lb numeric(10, 2) not null default 0;

alter table public.factures
  add column if not exists frais_service numeric(10, 2) not null default 0;

alter table public.factures
  add column if not exists montant_paye numeric(10, 2) not null default 0;

comment on column public.colis.tarif_lb is
  'Tarif d''expédition au livre, figé avec le colis.';
comment on column public.factures.montant is
  'Grand total : colis + frais de service.';


-- La vue reprend « c.* » : il faut la reconstruire pour qu'elle voie le tarif.
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


-- Le tarif ne se change pas sans le droit « colis.modifier ».
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
  v_total numeric(10, 2) := round(coalesce(new.poids_lb, 0) * coalesce(new.tarif_lb, 0), 2);
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
    'montant',     v_total));

  if tg_op = 'INSERT' then
    insert into public.factures (client_id, colis_id, montant, frais_service, lignes)
    values (new.client_id, new.id, v_total + v_frais, v_frais, v_ligne);
    return null;
  end if;

  if new.poids_lb is distinct from old.poids_lb
     or new.tarif_lb is distinct from old.tarif_lb
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
