-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 11 : ce que les applications mobiles demandent
-- -----------------------------------------------------------------------------
-- Phase 14. À coller dans Supabase > SQL Editor APRÈS 001 à 010, après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet ouvert est bien « speed-express-site ».
--
-- Deux choses, pas plus — tout le reste existe déjà dans la façade (missions, scans, preuve de livraison, tableau des tournées) :
--   1. lg_my_staff_profile() : QUI je suis pour l'application « Opérations » — chauffeur, agent d'entrepôt, agent de livraison —, décidé
--      ICI à partir des droits, du rôle, de la fiche chauffeur et de la succursale ; l'application ne fait qu'afficher les onglets qui en
--      découlent ;
--   2. lg_mobile_command(clé, commande, arguments) : la porte UNIQUE des actions faites hors connexion et rejouées au retour du réseau.
--      Chaque action porte une clé générée sur le téléphone : rejouée, elle rend son résultat d'origine sans rien refaire ; une même clé
--      pour une autre action est refusée (LG006) ; une action refusée (colis déjà livré, mission retirée) ne consomme pas sa clé.
--      Une position GPS ancienne ne remplace jamais une plus récente.
--
-- Rien n'est calculé par le téléphone : il propose, la base décide (droits, transitions, preuve). Rejouable sans risque.
-- =============================================================================

-- 1. Qui suis-je pour l'application « Opérations » ---------------------------------------------------------------------------------------------
create or replace function logistics.staff_profile(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare u logistics.app_user; v_driver jsonb; v_kind text; v_p text[] := '{}'; v_statut boolean;
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  select * into u from logistics.app_user x where x.id = p_actor and x.active;
  if not found then
    -- Un client (ou un compte d'équipe désactivé) : l'application « Opérations » n'a rien pour lui.
    return jsonb_build_object('staff', false, 'profiles', case when exists (select 1 from logistics.customer c where c.auth_user_id = p_actor) then '["CUSTOMER"]'::jsonb else '[]'::jsonb end);
  end if;
  select jsonb_build_object('driver_id', d.id, 'name', d.full_name, 'status', d.status, 'vehicle', (select v.plate from logistics.vehicle v where v.id = d.default_vehicle_id))
    into v_driver from logistics.driver d where d.user_id = p_actor;
  v_statut := logistics.actor_can(p_actor, 'colis.statut');
  select b.kind into v_kind from logistics.branch b where b.id = u.branch_id;
  if v_driver is not null and v_driver ->> 'status' = 'ACTIVE' then v_p := v_p || 'DRIVER'::text; end if;
  -- Avec le droit de faire avancer les colis : l'entrepôt (scans) et la livraison (tournées). La succursale de rattachement
  -- restreint au métier du lieu : un hub fait la livraison, un bureau ou un site d'entrepôt fait l'entrepôt ; sans succursale, les deux.
  if v_statut and coalesce(v_kind, '') <> 'hub' then v_p := v_p || 'WAREHOUSE_AGENT'::text; end if;
  if v_statut and coalesce(v_kind, 'hub') in ('hub', 'agency') then v_p := v_p || 'DELIVERY_AGENT'::text; end if;
  return jsonb_build_object('staff', true, 'role', u.role, 'profiles', to_jsonb(v_p), 'driver', v_driver, 'today', logistics.today(),
    'branch', logistics.branch_label(u.branch_id),
    'warehouses', case when 'WAREHOUSE_AGENT' = any (v_p) then coalesce((select jsonb_agg(jsonb_build_object('warehouse_id', w.id, 'code', w.code, 'name', w.name) order by (w.branch_id = u.branch_id) desc, w.code)
                                                                    from logistics.warehouse w where w.active and (u.branch_id is null or w.branch_id = u.branch_id or not exists (select 1 from logistics.warehouse w2 where w2.branch_id = u.branch_id and w2.active))), '[]'::jsonb)
                        else '[]'::jsonb end);
end;
$$;

-- 2. La porte des actions hors connexion -----------------------------------------------------------------------------------------------------
create or replace function logistics.mobile_command(p_actor uuid, p_key text, p_command text, p_args jsonb)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare a jsonb := coalesce(p_args, '{}'::jsonb); v_key text; v_prior jsonb; v_out jsonb; v_task uuid; v_d uuid; v_at timestamptz; v_lat numeric; v_lon numeric; v_n int;
begin
  perform logistics.require_staff(p_actor);                                     -- la porte se ferme AVANT toute validation
  if coalesce(btrim(p_key), '') !~ '^[A-Za-z0-9._:-]{8,80}$' then raise exception 'Clé d''action invalide (8 à 80 caractères simples).' using errcode = 'LG005'; end if;
  if p_command is null or p_command not in ('accept_task', 'refuse_task', 'start_task', 'complete_delivery', 'fail_task', 'complete_pickup', 'scan_parcel', 'report_incident', 'position') then
    raise exception 'Action inconnue.' using errcode = 'LG005';
  end if;
  if jsonb_typeof(a) <> 'object' or pg_column_size(a) > 8192 then raise exception 'Arguments invalides.' using errcode = 'LG005'; end if;
  v_key := 'mobile:' || p_actor::text || ':' || btrim(p_key);                  -- la clé d'un appareil ne peut jamais rencontrer celle d'un autre
  v_prior := logistics.idem_begin(v_key, 'mobile.' || p_command, md5(p_command || '|' || a::text), p_actor::text);
  if v_prior is not null then return v_prior; end if;
  if p_command in ('accept_task', 'refuse_task', 'start_task', 'complete_delivery', 'fail_task', 'complete_pickup') then
    begin v_task := (a ->> 'task_id')::uuid; exception when others then v_task := null; end;
    if v_task is null then raise exception 'Mission manquante.' using errcode = 'LG005'; end if;
  end if;
  case p_command
    when 'accept_task' then v_out := logistics.accept_task(v_task, p_actor, null);
    when 'refuse_task' then v_out := logistics.refuse_task(v_task, p_actor, a ->> 'reason', null);
    when 'start_task' then v_out := logistics.start_task(v_task, p_actor, null);
    when 'complete_delivery' then
      v_out := logistics.complete_delivery(v_task, p_actor, a ->> 'recipient_name', (a ->> 'latitude')::numeric, (a ->> 'longitude')::numeric,
                                           nullif(a ->> 'signature_path', ''), nullif(a ->> 'photo_path', ''), nullif(a ->> 'otp', ''), null);
    when 'fail_task' then v_out := logistics.fail_task(v_task, p_actor, a ->> 'incident_type', coalesce(a ->> 'description', ''), null);
    when 'complete_pickup' then
      v_out := logistics.complete_pickup(v_task, p_actor, (select coalesce(array_agg(x::uuid), '{}') from jsonb_array_elements_text(coalesce(a -> 'parcel_ids', '[]'::jsonb)) x), null);
    when 'scan_parcel' then
      v_out := logistics.scan_parcel(a ->> 'code', a ->> 'purpose', p_actor, nullif(a ->> 'warehouse_id', '')::uuid, nullif(a ->> 'location_id', '')::uuid, null,
                                     coalesce(nullif(a ->> 'code_kind', ''), 'unknown'), null, jsonb_build_object('source', 'mobile', 'recorded_at', a ->> 'recorded_at'), null);
    when 'report_incident' then
      v_out := jsonb_build_object('incident_id', logistics.report_incident(a ->> 'type', nullif(a ->> 'parcel_id', '')::uuid, p_actor, coalesce(a ->> 'description', ''),
                                                                           coalesce(nullif(a ->> 'severity', ''), 'MEDIUM'), nullif(a ->> 'warehouse_id', '')::uuid, null, null));
    when 'position' then
      v_d := logistics.driver_of(p_actor);
      if v_d is null then raise exception 'Réservé aux chauffeurs actifs.' using errcode = 'LG003'; end if;
      begin v_at := (a ->> 'recorded_at')::timestamptz; v_lat := (a ->> 'latitude')::numeric; v_lon := (a ->> 'longitude')::numeric;
      exception when others then raise exception 'Position invalide.' using errcode = 'LG005'; end;
      if v_at is null or v_lat is null or v_lon is null or v_lat not between -90 and 90 or v_lon not between -180 and 180 then raise exception 'Position invalide.' using errcode = 'LG005'; end if;
      if v_at > now() + interval '5 minutes' or v_at < now() - interval '24 hours' then raise exception 'Heure de la position invalide (ni future, ni de plus de 24 h).' using errcode = 'LG005'; end if;
      -- Une position ancienne (rejouée après une coupure) ne remplace jamais une plus récente.
      update logistics.driver set last_latitude = v_lat, last_longitude = v_lon, last_position_at = least(v_at, now())
       where id = v_d and (last_position_at is null or last_position_at < least(v_at, now()));
      get diagnostics v_n = row_count;
      v_out := jsonb_build_object('applied', v_n = 1);
  end case;
  return logistics.idem_end(v_key, coalesce(v_out, '{}'::jsonb) || jsonb_build_object('command', p_command));
end;
$$;

-- 3. Les façades -------------------------------------------------------------------------------------------------------------------------------------
create or replace function public.lg_my_staff_profile() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.staff_profile(auth.uid()) $$;
create or replace function public.lg_mobile_command(p_key text, p_command text, p_args jsonb default '{}'::jsonb)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.mobile_command(auth.uid(), p_key, p_command, p_args) $$;

-- 4. Les preuves de livraison (photo, signature) : un dossier privé du stockage de Supabase. Ce bloc ne fait rien hors de Supabase
--    (le schéma « storage » n'existe pas sur une base locale) ; sur Supabase, il crée le dossier s'il manque et ses règles d'accès.
create or replace function public.ses_peut_deposer_preuve() returns boolean language sql stable security definer set search_path = '' as $$ select logistics.driver_of(auth.uid()) is not null $$;
do $$
begin
  if to_regclass('storage.buckets') is not null then
    insert into storage.buckets (id, name, public) values ('preuves', 'preuves', false) on conflict (id) do nothing;
  end if;
  if to_regclass('storage.objects') is not null then
    execute 'drop policy if exists ses_preuves_depot on storage.objects';
    -- Un chauffeur actif dépose sous pod/<mission>/… ; personne ne lit, ne remplace ni ne supprime depuis un téléphone (l'équipe lit par le tableau de bord, plus tard, avec une URL signée).
    execute $p$create policy ses_preuves_depot on storage.objects for insert to authenticated
             with check (bucket_id = 'preuves' and (storage.foldername(name))[1] = 'pod' and public.ses_peut_deposer_preuve())$p$;
  end if;
end
$$;

-- 5. Tout fermé, sauf la façade -------------------------------------------------------------------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and p.proname in ('staff_profile', 'mobile_command') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname in ('lg_my_staff_profile', 'lg_mobile_command', 'ses_peut_deposer_preuve') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;

-- Pour retirer SEULEMENT cette étape : supprimer public.lg_my_staff_profile, public.lg_mobile_command, public.ses_peut_deposer_preuve,
-- logistics.staff_profile, logistics.mobile_command (et, sur Supabase, la règle ses_preuves_depot). Aucune table n'est créée ici.
