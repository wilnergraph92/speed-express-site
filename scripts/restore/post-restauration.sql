-- =============================================================================
-- Speed Express Shipping — ce qu'une sauvegarde du schéma « public » n'emporte pas
-- -----------------------------------------------------------------------------
-- Exécuté APRÈS la restauration des données, sur un projet Supabase neuf comme
-- sur un PostgreSQL de secours. Rejouable.
--
--   1. Le déclencheur qui crée le profil à l'inscription : il est posé sur
--      auth.users, une table du schéma « auth », donc absent d'une sauvegarde
--      de « public ». Sans lui, un nouvel inscrit n'aurait AUCUN profil, donc
--      aucun espace client. (Texte identique à outils/supabase.sql : un test
--      vérifie qu'ils ne divergent pas.)
--   2. La publication du temps réel (colis, historique, factures).
--
-- Reste à faire à la main, sur un projet Supabase neuf : l'extension « pg_net »
-- (notifications) et les réglages d'Auth (SMTP, URL de redirection) — voir
-- docs/backup/RESTORE-PROCEDURE.md.
-- =============================================================================

drop trigger if exists creer_profil_client on auth.users;
create trigger creer_profil_client
  after insert on auth.users
  for each row execute function public.creer_profil_client();

do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
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
