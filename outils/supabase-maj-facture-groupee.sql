-- =============================================================================
-- Speed Express Shipping — mise à jour : vraie facture groupée
-- -----------------------------------------------------------------------------
-- Tout sélectionner, copier, coller dans Supabase > SQL Editor, puis Run.
--
-- AVANT DE LANCER : vérifiez en haut de la page que le projet ouvert est bien
-- « speed-express-site ». Ce script ne doit jamais être passé sur la base de
-- Goship Express : les deux entreprises ont leurs propres données.
--
-- Ce qu'elle ajoute :
--   · la case « groupée » sur la facture : plusieurs colis d'un même client
--     réunis en une seule facture persistée, avec son propre numéro, payable
--     et imprimable comme les autres.
--
-- Une facture groupée est une facture normale (même table, mêmes statuts) :
-- sans colis unique (colis_id vide), avec une ligne figée par colis et les
-- frais de service comptés une seule fois. Le regroupement lui-même est fait
-- par le tableau de bord : créer la groupée, puis retirer les factures
-- individuelles impayées qu'elle remplace.
--
-- Rejouable sans risque : colonne ajoutée une seule fois, aucune donnée
-- existante n'est touchée, et le passer deux fois ne change rien.
-- =============================================================================


-- 1. La case « groupée » -------------------------------------------------------
alter table public.factures
  add column if not exists groupee boolean not null default false;

comment on column public.factures.groupee is
  'Vrai quand la facture regroupe plusieurs colis (colis_id vide, une ligne par colis). Les factures individuelles impayées remplacées sont retirées au regroupement.';


-- 2. La vue des factures doit voir la nouvelle colonne ---------------------------------
-- « factures_details » reprend « f.* » : PostgreSQL fige la liste des colonnes à sa création. Sans
-- cette reconstruction, la colonne « groupee » restait invisible dans la vue, et le tableau de bord
-- ne pouvait pas savoir qu'une facture est groupée.
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

revoke all on public.factures_details from anon;
grant select on public.factures_details to authenticated, service_role;

