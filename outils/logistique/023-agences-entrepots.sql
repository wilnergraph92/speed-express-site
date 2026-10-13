-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 23 : les agences, les entrepôts et leurs emplacements
-- -----------------------------------------------------------------------------
-- À passer APRÈS 022, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- L'ancien schéma n'a jamais enregistré d'agence ni d'entrepôt, et la migration n'en invente pas (DATA-MIGRATION-MAP.md §4) : en
-- production, logistics.branch et logistics.warehouse sont VIDES. Or tout le reste en dépend : une expédition part d'une agence et
-- arrive à un HUB ; le poste de scan reçoit un colis DANS un entrepôt ; un rangement vise un emplacement. Aucune fonction ne savait
-- les créer (les essais les insèrent en SQL). Ici, la direction les saisit elle-même depuis le tableau de bord :
--   · une agence : code, nom, genre (bureau, HUB, agence, site d'entrepôt), pays (HT, DO, US), ville — le pays ne change plus ensuite
--     (des expéditions et des douanes en dépendent) ; on la désactive au lieu de la supprimer ;
--   · un entrepôt, rattaché à une agence ; un emplacement (étagère, quai…), rattaché à un entrepôt, avec son genre.
-- Chaque création et chaque modification est tracée dans le journal d'audit (avant / après). Rien ne se supprime.
-- Lire : lg_sites (tout membre de l'équipe) — les agences, leurs entrepôts et leurs emplacements, avec leurs identifiants.
-- Rejouable sans risque ; aucune donnée supprimée. Retour arrière : laisser ces fonctions ; fermer l'écriture par
-- « revoke execute on function public.lg_create_branch(text, text, text, text, text) … from authenticated; ».
-- =============================================================================

-- 1. Lire : les agences, leurs entrepôts, leurs emplacements ----------------------------------------------------------------------------------
create or replace function logistics.sites(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_staff(p_actor);
  return jsonb_build_object('branches', coalesce((select jsonb_agg(jsonb_build_object(
      'branch_id', b.id, 'code', b.code, 'name', b.name, 'kind', b.kind, 'country', b.country, 'city', b.city, 'active', b.active,
      'warehouses', coalesce((select jsonb_agg(jsonb_build_object('warehouse_id', w.id, 'code', w.code, 'name', w.name, 'active', w.active,
          'locations', coalesce((select jsonb_agg(jsonb_build_object('location_id', l.id, 'code', l.code, 'zone', l.zone, 'kind', l.kind, 'active', l.active)
                                   order by l.active desc, l.zone, l.code) from logistics.warehouse_location l where l.warehouse_id = w.id), '[]'::jsonb))
          order by w.active desc, w.code) from logistics.warehouse w where w.branch_id = b.id), '[]'::jsonb))
      order by b.active desc, b.country, b.code) from logistics.branch b), '[]'::jsonb),
    'can_manage', logistics.actor_can(p_actor, 'direction'));
end;
$$;


-- 2. Les agences ---------------------------------------------------------------------------------------------------------------------------
create or replace function logistics.site_code(p_code text)
returns text language plpgsql immutable set search_path = '' as $$
declare v text := upper(btrim(coalesce(p_code, '')));
begin
  if v !~ '^[A-Z0-9][A-Z0-9-]{1,19}$' then
    raise exception 'Code « % » refusé : 2 à 20 caractères, lettres, chiffres et tirets (ex. MIA, PAP-HUB).', p_code using errcode = 'LG005';
  end if;
  return v;
end;
$$;

create or replace function logistics.create_branch(p_actor uuid, p_code text, p_name text, p_kind text, p_country text, p_city text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_code text; v_id uuid; v_org uuid; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  v_code := logistics.site_code(p_code);
  if btrim(coalesce(p_name, '')) = '' then raise exception 'Le nom de l''agence est obligatoire.' using errcode = 'LG005'; end if;
  if p_kind is null or p_kind not in ('office', 'hub', 'agency', 'warehouse_site') then raise exception 'Genre d''agence inconnu : %.', p_kind using errcode = 'LG005'; end if;
  if p_country is null or p_country not in ('HT', 'DO', 'US') then raise exception 'Pays inconnu : % (HT, DO ou US).', p_country using errcode = 'LG005'; end if;
  select id into v_org from logistics.organization order by created_at limit 1;
  if exists (select 1 from logistics.branch where organization_id = v_org and code = v_code) then
    raise exception 'Une agence porte déjà le code %.', v_code using errcode = 'LG005';
  end if;
  insert into logistics.branch (organization_id, code, name, kind, country, city) values (v_org, v_code, btrim(p_name), p_kind, p_country, btrim(coalesce(p_city, '')))
  returning id into v_id;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'branch.create', 'branch', v_id::text,
          jsonb_build_object('code', v_code, 'name', btrim(p_name), 'kind', p_kind, 'country', p_country, 'city', btrim(coalesce(p_city, ''))), v_corr);
  return jsonb_build_object('branch_id', v_id, 'code', v_code, 'correlation_id', v_corr);
end;
$$;

-- Le pays et le code ne changent pas (des expéditions, des douanes et des étiquettes les portent) : nom, genre, ville, actif.
create or replace function logistics.update_branch(p_actor uuid, p_branch uuid, p_name text default null, p_kind text default null, p_city text default null, p_active boolean default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_b logistics.branch; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  select * into v_b from logistics.branch where id = p_branch for update;
  if not found then raise exception 'Agence introuvable.' using errcode = 'LG002'; end if;
  if p_name is not null and btrim(p_name) = '' then raise exception 'Le nom de l''agence ne peut pas être vide.' using errcode = 'LG005'; end if;
  if p_kind is not null and p_kind not in ('office', 'hub', 'agency', 'warehouse_site') then raise exception 'Genre d''agence inconnu : %.', p_kind using errcode = 'LG005'; end if;
  if p_kind is not null and v_b.kind = 'hub' and p_kind <> 'hub'
     and exists (select 1 from logistics.shipment where destination_branch_id = p_branch and status not in ('CLOSED', 'CANCELLED')) then
    raise exception 'Des expéditions en cours arrivent à ce HUB : il reste un HUB tant qu''elles ne sont pas clôturées.' using errcode = 'LG004';
  end if;
  update logistics.branch set name = coalesce(btrim(p_name), name), kind = coalesce(p_kind, kind), city = coalesce(btrim(p_city), city),
                              active = coalesce(p_active, active), updated_at = now()
   where id = p_branch;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  select p_actor, logistics.lm_label(p_actor), 'branch.update', 'branch', p_branch::text,
         jsonb_build_object('name', v_b.name, 'kind', v_b.kind, 'city', v_b.city, 'active', v_b.active),
         jsonb_build_object('name', b.name, 'kind', b.kind, 'city', b.city, 'active', b.active), v_corr
    from logistics.branch b where b.id = p_branch;
  return jsonb_build_object('branch_id', p_branch, 'correlation_id', v_corr);
end;
$$;


-- 3. Les entrepôts -------------------------------------------------------------------------------------------------------------------------
create or replace function logistics.create_warehouse(p_actor uuid, p_branch uuid, p_code text, p_name text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_code text; v_id uuid; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  if not exists (select 1 from logistics.branch where id = p_branch and active) then raise exception 'Agence introuvable ou inactive.' using errcode = 'LG002'; end if;
  v_code := logistics.site_code(p_code);
  if btrim(coalesce(p_name, '')) = '' then raise exception 'Le nom de l''entrepôt est obligatoire.' using errcode = 'LG005'; end if;
  if exists (select 1 from logistics.warehouse where code = v_code) then raise exception 'Un entrepôt porte déjà le code %.', v_code using errcode = 'LG005'; end if;
  insert into logistics.warehouse (branch_id, code, name) values (p_branch, v_code, btrim(p_name)) returning id into v_id;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'warehouse.create', 'warehouse', v_id::text, jsonb_build_object('branch_id', p_branch, 'code', v_code, 'name', btrim(p_name)), v_corr);
  return jsonb_build_object('warehouse_id', v_id, 'code', v_code, 'correlation_id', v_corr);
end;
$$;

-- Désactiver un entrepôt qui garde des colis serait les perdre de vue : refusé tant qu'un colis y est.
create or replace function logistics.update_warehouse(p_actor uuid, p_warehouse uuid, p_name text default null, p_active boolean default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_w logistics.warehouse; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  select * into v_w from logistics.warehouse where id = p_warehouse for update;
  if not found then raise exception 'Entrepôt introuvable.' using errcode = 'LG002'; end if;
  if p_name is not null and btrim(p_name) = '' then raise exception 'Le nom de l''entrepôt ne peut pas être vide.' using errcode = 'LG005'; end if;
  if p_active is false and v_w.active and exists (select 1 from logistics.parcel where current_warehouse_id = p_warehouse
                                                    and status not in ('DELIVERED', 'RETURNED', 'CANCELLED', 'LOST')) then
    raise exception 'Des colis sont encore dans cet entrepôt : déplacez-les avant de le désactiver.' using errcode = 'LG004';
  end if;
  update logistics.warehouse set name = coalesce(btrim(p_name), name), active = coalesce(p_active, active), updated_at = now() where id = p_warehouse;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  select p_actor, logistics.lm_label(p_actor), 'warehouse.update', 'warehouse', p_warehouse::text,
         jsonb_build_object('name', v_w.name, 'active', v_w.active), jsonb_build_object('name', w.name, 'active', w.active), v_corr
    from logistics.warehouse w where w.id = p_warehouse;
  return jsonb_build_object('warehouse_id', p_warehouse, 'correlation_id', v_corr);
end;
$$;


-- 4. Les emplacements ----------------------------------------------------------------------------------------------------------------------
create or replace function logistics.create_location(p_actor uuid, p_warehouse uuid, p_code text, p_zone text default '', p_kind text default 'storage')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_code text; v_id uuid; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  if not exists (select 1 from logistics.warehouse where id = p_warehouse and active) then raise exception 'Entrepôt introuvable ou inactif.' using errcode = 'LG002'; end if;
  v_code := logistics.site_code(p_code);
  if p_kind is null or p_kind not in ('receiving', 'storage', 'staging', 'dispatch', 'quarantine', 'damaged') then
    raise exception 'Genre d''emplacement inconnu : %.', p_kind using errcode = 'LG005';
  end if;
  if exists (select 1 from logistics.warehouse_location where warehouse_id = p_warehouse and code = v_code) then
    raise exception 'Cet entrepôt a déjà un emplacement %.', v_code using errcode = 'LG005';
  end if;
  insert into logistics.warehouse_location (warehouse_id, code, zone, kind) values (p_warehouse, v_code, btrim(coalesce(p_zone, '')), p_kind) returning id into v_id;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'location.create', 'warehouse_location', v_id::text,
          jsonb_build_object('warehouse_id', p_warehouse, 'code', v_code, 'zone', btrim(coalesce(p_zone, '')), 'kind', p_kind), v_corr);
  return jsonb_build_object('location_id', v_id, 'code', v_code, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.set_location_active(p_actor uuid, p_location uuid, p_active boolean)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_l logistics.warehouse_location; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  select * into v_l from logistics.warehouse_location where id = p_location for update;
  if not found then raise exception 'Emplacement introuvable.' using errcode = 'LG002'; end if;
  if p_active is null then raise exception 'Actif ou non : à préciser.' using errcode = 'LG005'; end if;
  if not p_active and exists (select 1 from logistics.parcel where current_location_id = p_location and status not in ('DELIVERED', 'RETURNED', 'CANCELLED', 'LOST')) then
    raise exception 'Des colis sont encore rangés à cet emplacement : déplacez-les avant de le désactiver.' using errcode = 'LG004';
  end if;
  update logistics.warehouse_location set active = p_active where id = p_location;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'location.active', 'warehouse_location', p_location::text,
          jsonb_build_object('active', v_l.active), jsonb_build_object('active', p_active), v_corr);
  return jsonb_build_object('location_id', p_location, 'active', p_active, 'correlation_id', v_corr);
end;
$$;


-- 5. Les façades (comptes connectés ; la base décide qui peut) ---------------------------------------------------------------------------
create or replace function public.lg_sites() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.sites(auth.uid()) $$;
create or replace function public.lg_create_branch(p_code text, p_name text, p_kind text, p_country text, p_city text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_branch(auth.uid(), p_code, p_name, p_kind, p_country, p_city) $$;
create or replace function public.lg_update_branch(p_branch_id uuid, p_name text default null, p_kind text default null, p_city text default null, p_active boolean default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.update_branch(auth.uid(), p_branch_id, p_name, p_kind, p_city, p_active) $$;
create or replace function public.lg_create_warehouse(p_branch_id uuid, p_code text, p_name text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_warehouse(auth.uid(), p_branch_id, p_code, p_name) $$;
create or replace function public.lg_update_warehouse(p_warehouse_id uuid, p_name text default null, p_active boolean default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.update_warehouse(auth.uid(), p_warehouse_id, p_name, p_active) $$;
create or replace function public.lg_create_location(p_warehouse_id uuid, p_code text, p_zone text default '', p_kind text default 'storage')
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_location(auth.uid(), p_warehouse_id, p_code, p_zone, p_kind) $$;
create or replace function public.lg_set_location_active(p_location_id uuid, p_active boolean)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.set_location_active(auth.uid(), p_location_id, p_active) $$;


-- 6. Tout fermé, sauf les façades -------------------------------------------------------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('sites', 'site_code', 'create_branch', 'update_branch', 'create_warehouse', 'update_warehouse',
                                                            'create_location', 'set_location_active') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_sites', 'lg_create_branch', 'lg_update_branch', 'lg_create_warehouse', 'lg_update_warehouse',
                                                         'lg_create_location', 'lg_set_location_active') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
