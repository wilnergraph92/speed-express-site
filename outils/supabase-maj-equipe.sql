-- =============================================================================
-- Speed Express Shipping — mise à jour : l'identifiant de chaque membre de l'équipe
-- -----------------------------------------------------------------------------
-- Tout sélectionner, copier, coller dans Supabase > SQL Editor, puis Run.
--
-- AVANT DE LANCER : vérifiez en haut de la page que le projet ouvert est bien
-- « speed-express-site ». Ce script ne doit jamais être passé sur la base de
-- Goship Express : les deux entreprises ont leurs propres données.
--
-- Ce qu'elle ajoute :
--   · un IDENTIFIANT D'ÉQUIPE (« matricule ») attribué par la base elle-même, au
--     moment où un rôle est donné : ADM- (administrateur), GER- (gérant) ou EMP-
--     (employé), suivi de quatre chiffres tirés au hasard (ADM-4821). Personne ne
--     le choisit, et une écriture directe ne le change pas ;
--   · il ne change QU'AVEC LE RÔLE : un employé promu gérant reçoit un nouvel
--     identifiant GER-…, l'ancien est retiré. Un changement de droits, de nom ou
--     de quoi que ce soit d'autre ne le touche jamais ;
--   · un identifiant n'est JAMAIS réutilisé : le registre public.matricules_attribues
--     garde chaque identifiant donné (à qui, quand, et quand il a été retiré).
--     Il ne se modifie ni ne s'efface ; la direction peut le lire ;
--   · les membres de l'équipe déjà en place reçoivent le leur tout de suite.
--
-- Rejouable sans risque : rien n'est supprimé, aucun identifiant déjà attribué
-- ne change, et le passer deux fois ne change rien.
-- =============================================================================

alter table public.clients
  add column if not exists matricule text;

create unique index if not exists clients_matricule_idx
  on public.clients (matricule) where matricule is not null;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'clients_matricule_format') then
    alter table public.clients
      add constraint clients_matricule_format check (matricule is null or matricule ~ '^(ADM|GER|EMP)-[1-9][0-9]{3}$');
  end if;
end $$;

-- Le registre : chaque identifiant jamais donné, pour qu'il ne serve qu'une fois.
create table if not exists public.matricules_attribues (
  matricule   text primary key check (matricule ~ '^(ADM|GER|EMP)-[1-9][0-9]{3}$'),
  client_id   uuid not null,
  role        text not null check (role in ('employe', 'gerant', 'admin')),
  attribue_le timestamptz not null default now(),
  retire_le   timestamptz
);
create index if not exists matricules_attribues_client_idx on public.matricules_attribues (client_id, attribue_le desc);

alter table public.matricules_attribues enable row level security;
drop policy if exists matricules_lecture on public.matricules_attribues;
create policy matricules_lecture on public.matricules_attribues
  for select to authenticated using ((select public.est_direction()));
revoke all on public.matricules_attribues from anon, authenticated;
grant select on public.matricules_attribues to authenticated;
grant select, insert, update on public.matricules_attribues to service_role;

-- Le registre ne se réécrit pas : seule la date de retrait se pose, une fois, et rien ne s'efface.
create or replace function public.proteger_registre_matricules()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Le registre des identifiants d''équipe ne s''efface pas.' using errcode = '42501';
  end if;
  if new.matricule is distinct from old.matricule or new.client_id is distinct from old.client_id
     or new.role is distinct from old.role or new.attribue_le is distinct from old.attribue_le
     or (old.retire_le is not null and new.retire_le is distinct from old.retire_le) then
    raise exception 'Le registre des identifiants d''équipe ne se réécrit pas.' using errcode = '42501';
  end if;
  return new;
end;
$$;

drop trigger if exists proteger_registre_matricules on public.matricules_attribues;
create trigger proteger_registre_matricules
  before update or delete on public.matricules_attribues
  for each row execute function public.proteger_registre_matricules();

-- Le préfixe d'un rôle d'équipe ; rien pour un client.
create or replace function public.prefixe_matricule(p_role text)
returns text
language sql
immutable
set search_path = ''
as $$
  select case p_role when 'admin' then 'ADM' when 'gerant' then 'GER' when 'employe' then 'EMP' end
$$;

-- Le préfixe et quatre chiffres tirés au hasard (aléa cryptographique de gen_random_uuid), le premier jamais nul ;
-- on retire tant que l'identifiant a déjà servi, à qui que ce soit, même retiré. Neuf mille par préfixe.
create or replace function public.nouveau_matricule(p_prefixe text)
returns text
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_matricule text;
  v_essais int := 0;
begin
  if p_prefixe not in ('ADM', 'GER', 'EMP') then
    raise exception 'Préfixe d''identifiant inconnu : %', p_prefixe using errcode = '22023';
  end if;
  loop
    v_essais := v_essais + 1;
    if v_essais > 500 then
      raise exception 'Plus d''identifiant libre pour le préfixe %.', p_prefixe using errcode = 'SE005';
    end if;
    v_matricule := p_prefixe || '-' || (1000
      + ('x' || substr(md5(gen_random_uuid()::text), 1, 7))::bit(28)::bigint % 9000)::text;
    exit when not exists (select 1 from public.matricules_attribues m where m.matricule = v_matricule)
          and not exists (select 1 from public.clients c where c.matricule = v_matricule);
  end loop;
  return v_matricule;
end;
$$;

-- Le gardien. La valeur écrite par l'appelant n'est jamais prise : l'identifiant reste celui qui existait
-- tant que le rôle ne change pas ; un nouveau rôle d'équipe en reçoit un nouveau (l'ancien est retiré au
-- registre) ; un retour à la clientèle retire l'identifiant.
create or replace function public.attribuer_matricule()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_prefixe text := public.prefixe_matricule(new.role);
begin
  if tg_op = 'UPDATE' then
    new.matricule := old.matricule;
    if old.matricule is not null and (v_prefixe is null or split_part(old.matricule, '-', 1) <> v_prefixe) then
      update public.matricules_attribues set retire_le = now()
       where matricule = old.matricule and retire_le is null;
      new.matricule := null;
    end if;
  else
    new.matricule := null;
  end if;
  if new.matricule is null and v_prefixe is not null then
    new.matricule := public.nouveau_matricule(v_prefixe);
    insert into public.matricules_attribues (matricule, client_id, role) values (new.matricule, new.id, new.role);
  end if;
  return new;
end;
$$;

drop trigger if exists attribuer_matricule on public.clients;
create trigger attribuer_matricule
  before insert or update on public.clients
  for each row execute function public.attribuer_matricule();

revoke execute on function public.prefixe_matricule(text) from public, anon, authenticated;
revoke execute on function public.nouveau_matricule(text) from public, anon, authenticated;
revoke execute on function public.attribuer_matricule() from public, anon, authenticated;
revoke execute on function public.proteger_registre_matricules() from public, anon, authenticated;

-- L'équipe déjà en place reçoit son identifiant (une seule fois : ensuite, il ne change qu'avec le rôle).
update public.clients
   set role = role
 where role <> 'client' and matricule is null;
