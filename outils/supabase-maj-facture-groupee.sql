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
