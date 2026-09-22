-- =============================================================================
-- Speed Express Shipping — mise à jour : téléphone du destinataire
-- -----------------------------------------------------------------------------
-- À passer une seule fois dans Supabase → SQL Editor, sur une base déjà en
-- service. Une installation neuve n'en a pas besoin : outils/supabase.sql
-- contient déjà la colonne.
--
-- Le script est sans danger s'il tourne deux fois : la colonne n'est ajoutée
-- que si elle manque, la vue et la fonction sont simplement réécrites.
-- Aucune donnée existante n'est touchée.
-- =============================================================================

alter table public.colis
  add column if not exists telephone_destinataire text not null default '';

comment on column public.colis.telephone_destinataire is
  'Numéro appelé à la livraison. Vide, l''étiquette reprend celui du compte client.';

-- La vue reprend « c.* » : il faut la reconstruire pour qu'elle voie la
-- nouvelle colonne.
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

-- Un employé qui n'a que le droit « colis.statut » ne doit pas pouvoir
-- changer ce numéro non plus.
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
