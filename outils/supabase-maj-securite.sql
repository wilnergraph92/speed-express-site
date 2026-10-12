-- =============================================================================
-- Speed Express Shipping — mise à jour : refermer ce que Supabase ouvre d'office
-- -----------------------------------------------------------------------------
-- Tout sélectionner, copier, coller dans Supabase > SQL Editor, puis Run.
--
-- AVANT DE LANCER : vérifiez en haut de la page que le projet ouvert est bien
-- « speed-express-site ». Ce script ne doit jamais être passé sur la base de
-- Goship Express : les deux entreprises ont leurs propres données.
--
-- Pourquoi : sur un projet Supabase, tout ce qui est créé dans le schéma
-- « public » est ouvert d'office aux visiteurs (anon) et aux comptes connectés
-- (authenticated), sauf retrait explicite. L'audit du catalogue
-- (outils/tests/securite-catalogue.py) a trouvé trois restes de cette ouverture :
--   · la fonction prefixe_matricule, utile au seul déclencheur des identifiants
--     d'équipe, était appelable par n'importe quel visiteur ;
--   · les comptes connectés avaient TRUNCATE, TRIGGER et REFERENCES sur chaque
--     table (TRUNCATE ignore la sécurité par ligne). L'API ne les expose pas,
--     mais rien ne justifie de les laisser ;
--   · les séquences des numéros étaient utilisables par un visiteur.
--
-- Ce qu'elle fait : elle RETIRE ces droits, rien d'autre. Aucune table, aucune
-- colonne, aucune donnée n'est touchée ; aucun droit utile n'est retiré (lire,
-- écrire, la sécurité par ligne et les fonctions du site restent identiques).
--
-- Rejouable sans risque : la passer deux fois ne change rien.
-- =============================================================================


-- 1. La fonction de préfixe : réservée au déclencheur (qui s'exécute avec les
--    droits de son auteur et n'a donc pas besoin qu'on l'ouvre à quiconque).
do $$
begin
  if to_regprocedure('public.prefixe_matricule(text)') is not null then
    revoke execute on function public.prefixe_matricule(text) from public, anon, authenticated;
  end if;
end
$$;


-- 2. TRUNCATE, TRIGGER, REFERENCES : jamais utiles à un visiteur ni à un compte
--    connecté, sur aucune table du schéma public (présente ou à venir dans ce script).
do $$
declare
  t regclass;
begin
  for t in
    select c.oid::regclass from pg_class c
     where c.relnamespace = 'public'::regnamespace and c.relkind in ('r', 'p')
  loop
    execute format('revoke truncate, references, trigger on %s from anon, authenticated', t);
  end loop;
end
$$;


-- 3. Les séquences (numéros de colis, de factures, de lignes d'historique) : elles
--    ne servent qu'aux fonctions de la base ; un visiteur n'a pas à les lire ni à
--    les avancer.
revoke all on all sequences in schema public from anon;
