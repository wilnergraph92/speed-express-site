-- =============================================================================
-- Speed Express Shipping — socle d'une base PostgreSQL VIDE (hors Supabase)
-- -----------------------------------------------------------------------------
-- Sert aux restaurations de TEST (contrôle quotidien de la sauvegarde, répétition
-- de sinistre sur un PostgreSQL de secours). Il reproduit ce que Supabase fournit
-- d'office : les rôles, le schéma « auth » et ses fonctions, le schéma
-- « extensions », la publication du temps réel.
--
-- Sur un projet Supabase NEUF, il ne faut PAS l'exécuter : tout cela existe déjà.
-- Les tables auth.users et auth.identities, elles, viennent de l'archive.
--
-- Rejouable : tout est « si absent ».
-- =============================================================================

do $$
declare r text;
begin
  foreach r in array array['anon', 'authenticated', 'service_role', 'authenticator', 'supabase_admin',
                           'supabase_auth_admin', 'supabase_storage_admin', 'dashboard_user', 'pgbouncer']
  loop
    if not exists (select 1 from pg_roles where rolname = r) then
      execute format('create role %I nologin', r);
    end if;
  end loop;
end
$$;

create schema if not exists auth;
create schema if not exists extensions;
grant usage on schema auth to anon, authenticated, service_role;
grant usage on schema extensions to anon, authenticated, service_role;

-- Les fonctions d'identité sur lesquelles reposent toutes les règles de sécurité.
create or replace function auth.uid() returns uuid language sql stable
  as $f$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $f$;
create or replace function auth.role() returns text language sql stable
  as $f$ select nullif(current_setting('request.jwt.claim.role', true), '')::text $f$;

-- Le jeton des colis utilise gen_random_bytes (pgcrypto). Le vrai module si la
-- base le propose, sinon un équivalent de remplacement : une restauration ne
-- tire jamais de nouveau jeton, il faut seulement que la fonction existe.
do $$
begin
  begin
    create extension if not exists pgcrypto with schema extensions;
  exception when others then
    if not exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                   where n.nspname = 'extensions' and p.proname = 'gen_random_bytes') then
      execute $f$create function extensions.gen_random_bytes(n int) returns bytea language sql
                 as 'select decode(md5(random()::text), ''hex'')'$f$;
    end if;
  end;
end
$$;

do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
end
$$;
