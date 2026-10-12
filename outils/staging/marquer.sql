-- =============================================================================
-- Speed Express Shipping — MARQUER une base comme préproduction (staging)
-- -----------------------------------------------------------------------------
-- Pose ses_meta.environnement = 'staging', le marqueur qu'exigent
-- donnees-synthetiques.sql, reinitialiser.sql et anonymiser.sql. Il est repris
-- en tête de l'installation (assembler-installation.py) : on ne le passe seul
-- que sur un PostgreSQL LOCAL et VIDE qui va recevoir une copie à anonymiser
-- (docs/production/ENVIRONNEMENTS.md §6), avant la restauration.
--
-- Il REFUSE toute base qui porte déjà l'espace client sans être marquée :
-- la production, le projet Goship, une copie déjà restaurée. Jamais
-- « speed-express-site ».
-- =============================================================================

begin;

create schema if not exists ses_meta;
revoke all on schema ses_meta from public;

do $$
declare
  v_marquee boolean := false;
begin
  -- Lecture dynamique : la table du marqueur n'existe pas encore sur une base neuve.
  if to_regclass('ses_meta.environnement') is not null then
    execute 'select exists (select 1 from ses_meta.environnement where nom = ''staging'')' into v_marquee;
  end if;
  if v_marquee then
    return;   -- préproduction déjà marquée : réinstaller est sans risque (tout est rejouable)
  end if;
  if to_regclass('public.clients') is not null then
    raise exception 'ARRÊT : cette base porte déjà l''espace client et n''est pas marquée « staging ». Est-ce la PRODUCTION ? Rien n''a été modifié.'
      using errcode = 'SE900';
  end if;
  create table ses_meta.environnement (
    nom      text primary key check (nom = 'staging'),
    marque_le timestamptz not null default now()
  );
  insert into ses_meta.environnement (nom) values ('staging');
end
$$;
revoke all on all tables in schema ses_meta from public, anon, authenticated;

commit;
