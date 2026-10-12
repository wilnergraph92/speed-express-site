-- =============================================================================
-- Speed Express Shipping — RÉINITIALISER la préproduction (staging)
-- -----------------------------------------------------------------------------
-- À coller UNIQUEMENT dans le SQL Editor du projet de PRÉPRODUCTION, jamais
-- « speed-express-site ». Ce script EFFACE : il refuse toute base sans le
-- marqueur « staging », et toute base qui compte plus de 25 comptes réels.
--
-- Ce qu'il efface : toutes les données d'activité (colis, historique,
-- factures, pré-alertes, téléphones) et les comptes synthétiques
-- (@exemple.test). Ce qu'il garde : le schéma, et les comptes que vous avez
-- créés vous-même sur la préproduction (avec leur rôle).
-- Ensuite : donnees-synthetiques.sql pour repartir d'un jeu propre.
--
-- Tout tient dans une transaction : si le garde-fou refuse, rien n'est effacé.
-- =============================================================================

begin;

do $$
declare
  v_marquee boolean := false;
begin
  -- Lecture dynamique : sur une base non marquée, la table du marqueur n'existe pas.
  if to_regclass('ses_meta.environnement') is not null then
    execute 'select exists (select 1 from ses_meta.environnement where nom = ''staging'')' into v_marquee;
  end if;
  if not v_marquee then
    raise exception 'ARRÊT : cette base n''est pas la préproduction (marqueur « staging » absent). Rien n''a été effacé.'
      using errcode = 'SE900';
  end if;
  if (select count(*) from auth.users where email not like '%@exemple.test') > 25 then
    raise exception 'ARRÊT : plus de 25 comptes réels dans cette base : ce n''est pas une préproduction. Rien n''a été effacé.'
      using errcode = 'SE900';
  end if;
end
$$;

delete from public.prealertes;
delete from public.factures;
delete from public.colis;              -- l'historique part avec ses colis
delete from public.appareils;

-- Le registre des identifiants d'équipe ne s'efface jamais en production (son déclencheur l'interdit) ; en
-- préproduction, on en retire les seuls comptes synthétiques, le temps de cette transaction.
alter table public.matricules_attribues disable trigger proteger_registre_matricules;
delete from public.matricules_attribues
 where client_id in (select id from auth.users where email like '%@exemple.test');
alter table public.matricules_attribues enable trigger proteger_registre_matricules;

delete from auth.users where email like '%@exemple.test';   -- leurs profils partent avec eux

commit;
