-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 21 : l'application « SES Opérations » sur le terrain
-- -----------------------------------------------------------------------------
-- Phase 9. À coller dans Supabase > SQL Editor APRÈS 020, d'abord en PRÉPRODUCTION,
-- puis en production après une sauvegarde « avant migration » vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site » (ou la préproduction).
--
-- La porte unique des téléphones de l'équipe (lg_mobile_command, étapes 11 puis 17) apprend quatre gestes, tous compatibles avec la
-- file hors connexion (une clé par geste ; même clé rejouée → résultat d'origine ; autre geste sous la même clé → LG006) :
--   · arrive_stop     — le chauffeur est arrivé à l'arrêt d'une mission COMMENCÉE : l'heure du téléphone, et la position de CE moment
--                       (le GPS ne sert qu'aux gestes du métier : arrivée, remise, échec, incident — jamais un suivi permanent) ;
--   · start_trip / complete_trip — démarrer et terminer SA tournée ;
--   · reschedule_task — replanifier une mission ÉCHOUÉE (droit « colis.statut », vérifié par la base).
-- Et deux lectures pour l'équipe : la preuve d'une livraison (lg_task_proof) — nom, heure, code vérifié, photo et signature présentes ;
-- les emplacements d'un entrepôt (lg_warehouse_locations), pour ranger et transférer un colis en scannant l'étiquette de l'étagère.
--
-- La base décide de tout : qui est chauffeur, quelle mission et quelle tournée sont les siennes, quel geste est permis, dans quel ordre.
-- Un geste dans le mauvais ordre répond LG001 (la file du téléphone le classe « conflit ») ; un geste interdit répond LG003 (« refusé »).
-- Rejouable sans risque ; aucune donnée supprimée. Retour arrière : docs/architecture/MOBILE-OPERATIONS.md §7.
-- =============================================================================

-- 1. Le vocabulaire ------------------------------------------------------------------------------------------------------------------
insert into logistics.event_type (code, aggregate_type, description) values
  ('StopArrived', 'trip', 'Le chauffeur est arrivé à un arrêt de sa tournée (heure du téléphone)')
on conflict (code) do nothing;


-- 2. Arrivé à l'arrêt --------------------------------------------------------------------------------------------------------------------
-- Seulement le chauffeur de la mission (require_driver_of_task), seulement une mission COMMENCÉE (sinon LG001 : on n'arrive pas avant d'être
-- parti). L'heure est celle du téléphone, bornée : ni future, ni de plus de 24 h (une coupure ne la change pas). Déjà arrivé : la réponse le dit,
-- rien ne change. La position, si le téléphone la donne, est celle de l'arrivée ; une position plus ancienne n'en remplace jamais une plus récente.
create or replace function logistics.arrive_stop(p_actor uuid, p_task uuid, p_at timestamptz, p_lat numeric, p_lon numeric, p_corr uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.require_driver_of_task(p_actor, p_task); v_t logistics.task; v_s logistics.stop; v_at timestamptz;
begin
  select * into v_t from logistics.task where id = p_task for update;
  if v_t.status <> 'STARTED' then raise exception 'Mission % : commencez-la avant d''arriver à l''arrêt.', v_t.status using errcode = 'LG001'; end if;
  select * into v_s from logistics.stop where task_id = p_task and status <> 'SKIPPED' order by sequence desc limit 1 for update;
  if not found then raise exception 'Cette mission n''est sur aucune tournée.' using errcode = 'LG001'; end if;
  if p_at is not null and (p_at > now() + interval '5 minutes' or p_at < now() - interval '24 hours') then
    raise exception 'Heure d''arrivée invalide (ni future, ni de plus de 24 h).' using errcode = 'LG005';
  end if;
  if (p_lat is null) <> (p_lon is null) or (p_lat is not null and (p_lat not between -90 and 90 or p_lon not between -180 and 180)) then
    raise exception 'Position invalide.' using errcode = 'LG005';
  end if;
  if v_s.status <> 'PLANNED' then
    return jsonb_build_object('task_id', p_task, 'stop_status', v_s.status, 'arrived_at', v_s.actual_at, 'already', true);
  end if;
  v_at := least(coalesce(p_at, now()), now());
  update logistics.stop set status = 'ARRIVED', actual_at = v_at where id = v_s.id;
  if p_lat is not null then
    update logistics.driver set last_latitude = p_lat, last_longitude = p_lon, last_position_at = v_at
     where id = v_d and (last_position_at is null or last_position_at < v_at);
  end if;
  perform logistics.emit('StopArrived', 'trip', v_s.trip_id::text, p_corr, p_actor,
                         jsonb_build_object('trip_id', v_s.trip_id, 'task_id', p_task, 'sequence', v_s.sequence, 'arrived_at', v_at));
  return jsonb_build_object('task_id', p_task, 'stop_status', 'ARRIVED', 'arrived_at', v_at, 'sequence', v_s.sequence, 'already', false);
end;
$$;


-- 3. La porte des téléphones : les neuf gestes d'avant, plus quatre ----------------------------------------------------------------------
create or replace function logistics.mobile_command(p_actor uuid, p_key text, p_command text, p_args jsonb)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare a jsonb := coalesce(p_args, '{}'::jsonb); v_key text; v_prior jsonb; v_out jsonb; v_task uuid; v_trip uuid; v_d uuid; v_at timestamptz; v_lat numeric; v_lon numeric; v_n int;
        v_date date; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_staff(p_actor);                                     -- la porte se ferme AVANT toute validation
  if coalesce(btrim(p_key), '') !~ '^[A-Za-z0-9._:-]{8,80}$' then raise exception 'Clé d''action invalide (8 à 80 caractères simples).' using errcode = 'LG005'; end if;
  if p_command is null or p_command not in ('accept_task', 'refuse_task', 'start_task', 'complete_delivery', 'fail_task', 'complete_pickup', 'scan_parcel', 'report_incident', 'position',
                                            'arrive_stop', 'start_trip', 'complete_trip', 'reschedule_task') then
    raise exception 'Action inconnue.' using errcode = 'LG005';
  end if;
  if jsonb_typeof(a) <> 'object' or pg_column_size(a) > 8192 then raise exception 'Arguments invalides.' using errcode = 'LG005'; end if;
  v_key := 'mobile:' || p_actor::text || ':' || btrim(p_key);                  -- la clé d'un appareil ne peut jamais rencontrer celle d'un autre
  v_prior := logistics.idem_begin(v_key, 'mobile.' || p_command, md5(p_command || '|' || a::text), p_actor::text);
  if v_prior is not null then return v_prior; end if;
  if p_command in ('accept_task', 'refuse_task', 'start_task', 'complete_delivery', 'fail_task', 'complete_pickup', 'arrive_stop', 'reschedule_task') then
    begin v_task := (a ->> 'task_id')::uuid; exception when others then v_task := null; end;
    if v_task is null then raise exception 'Mission manquante.' using errcode = 'LG005'; end if;
  end if;
  if p_command in ('start_trip', 'complete_trip') then
    begin v_trip := (a ->> 'trip_id')::uuid; exception when others then v_trip := null; end;
    if v_trip is null then raise exception 'Tournée manquante.' using errcode = 'LG005'; end if;
  end if;
  case p_command
    when 'accept_task' then v_out := logistics.accept_task(v_task, p_actor, null);
    when 'refuse_task' then v_out := logistics.refuse_task(v_task, p_actor, a ->> 'reason', null);
    when 'start_task' then v_out := logistics.start_task(v_task, p_actor, null);
    when 'complete_delivery' then
      -- L'heure relevée par le téléphone au moment de la remise (étape 17) : une preuve envoyée après une coupure garde son heure.
      begin v_at := (a ->> 'recorded_at')::timestamptz; exception when others then v_at := null; end;
      perform set_config('logistics.pod_captured_at', coalesce(v_at::text, ''), true);
      v_out := logistics.complete_delivery(v_task, p_actor, a ->> 'recipient_name', (a ->> 'latitude')::numeric, (a ->> 'longitude')::numeric,
                                           nullif(a ->> 'signature_path', ''), nullif(a ->> 'photo_path', ''), nullif(a ->> 'otp', ''), null);
      perform set_config('logistics.pod_captured_at', '', true);
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
    when 'arrive_stop' then
      begin v_at := (a ->> 'recorded_at')::timestamptz; v_lat := (a ->> 'latitude')::numeric; v_lon := (a ->> 'longitude')::numeric;
      exception when others then raise exception 'Heure ou position invalide.' using errcode = 'LG005'; end;
      v_out := logistics.arrive_stop(p_actor, v_task, v_at, v_lat, v_lon, v_corr);
    when 'start_trip' then v_out := logistics.start_trip(v_trip, p_actor, v_corr);
    when 'complete_trip' then v_out := logistics.complete_trip(v_trip, p_actor, v_corr);
    when 'reschedule_task' then
      begin v_date := (a ->> 'new_date')::date; exception when others then v_date := null; end;
      if v_date is null or v_date < logistics.today() or v_date > logistics.today() + 60 then
        raise exception 'Nouvelle date invalide (aujourd''hui à soixante jours).' using errcode = 'LG005';
      end if;
      v_out := logistics.reschedule_task(v_task, p_actor, v_date, v_corr);
  end case;
  return logistics.idem_end(v_key, coalesce(v_out, '{}'::jsonb) || jsonb_build_object('command', p_command));
end;
$$;


-- 4. La preuve d'une livraison, pour l'équipe ----------------------------------------------------------------------------------------------
-- Le chauffeur de la mission, ou un membre qui lit les colis. Ce que la base sait de la remise — jamais les fichiers eux-mêmes (l'équipe les
-- ouvre depuis le tableau de bord, par une adresse signée) : nom, heure (celle du téléphone), position, code exigé et vérifié, photo et
-- signature présentes. Mission sans preuve : « proof » vide, et son statut (un échec dit pourquoi).
create or replace function logistics.task_proof(p_actor uuid, p_task uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_t logistics.task;
begin
  select * into v_t from logistics.task where id = p_task;
  if not found then raise exception 'Mission introuvable.' using errcode = 'LG002'; end if;
  if logistics.driver_of(p_actor) is distinct from v_t.driver_id or v_t.driver_id is null then perform logistics.require_right(p_actor, 'colis.lire'); end if;
  return jsonb_build_object(
    'task_id', v_t.id, 'kind', v_t.kind, 'status', v_t.status, 'failed_reason', v_t.failed_reason, 'address', v_t.address, 'scheduled_date', v_t.scheduled_date,
    'parcels', coalesce((select jsonb_agg(jsonb_build_object('tracking_number', p.tracking_number, 'status', p.status) order by p.tracking_number)
                           from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = v_t.delivery_id), '[]'::jsonb),
    'proof', (select jsonb_build_object('recipient_name', pod.recipient_name, 'delivered_at', pod.delivered_at, 'latitude', pod.latitude, 'longitude', pod.longitude,
                                        'otp_required', pod.otp_required, 'otp_verified', pod.otp_verified,
                                        'has_photo', pod.photo_path is not null, 'has_signature', pod.signature_path is not null,
                                        'driver', (select d.full_name from logistics.driver d where d.id = pod.driver_id))
                from logistics.proof_of_delivery pod where pod.task_id = v_t.id));
end;
$$;


-- 4 bis. Les emplacements d'un entrepôt ---------------------------------------------------------------------------------------------------
-- Pour qui fait avancer les colis (« colis.statut ») : l'agent range (« store ») ou transfère (« move ») vers un emplacement qu'il choisit dans
-- cette liste ou dont il scanne l'étiquette (le code). Seulement les emplacements actifs d'un entrepôt actif.
create or replace function logistics.warehouse_locations(p_actor uuid, p_warehouse uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor);
  if not exists (select 1 from logistics.warehouse where id = p_warehouse and active) then raise exception 'Entrepôt introuvable.' using errcode = 'LG002'; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('location_id', l.id, 'code', l.code, 'zone', l.zone, 'kind', l.kind) order by l.zone, l.code)
                     from logistics.warehouse_location l where l.warehouse_id = p_warehouse and l.active), '[]'::jsonb);
end;
$$;


-- 5. La façade ----------------------------------------------------------------------------------------------------------------------------
create or replace function public.lg_task_proof(p_task_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.task_proof(auth.uid(), p_task_id) $$;
create or replace function public.lg_warehouse_locations(p_warehouse_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.warehouse_locations(auth.uid(), p_warehouse_id) $$;


-- 6. Tout fermé, sauf la façade ------------------------------------------------------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('arrive_stop', 'mobile_command', 'task_proof', 'warehouse_locations') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_task_proof', 'lg_warehouse_locations') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;

-- 7. Retour arrière (docs/architecture/MOBILE-OPERATIONS.md §7) : ne JAMAIS rejouer 017 après 021 (une étape ancienne ne se rejoue pas après
-- une plus récente). Les quatre gestes ajoutés ne servent qu'aux téléphones de l'équipe : les laisser ; fermer la lecture des preuves par
-- « revoke execute on function public.lg_task_proof(uuid), public.lg_warehouse_locations(uuid) from authenticated; ».
