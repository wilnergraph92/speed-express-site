-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 17 : le dernier kilomètre, au complet
-- -----------------------------------------------------------------------------
-- Phase 5. À coller dans Supabase > SQL Editor APRÈS 016, d'abord en PRÉPRODUCTION,
-- puis en production après une sauvegarde « avant migration » vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site » (ou la préproduction).
--
-- L'étape 6 a posé le dernier kilomètre (chauffeurs, véhicules, zones, missions et leurs sept états, moteur
-- d'affectation, tournées, preuve de livraison en ajout seul, incidents). Celle-ci le termine :
--   1. QUATRE PROFILS : chauffeur (fiche chauffeur active), agent de livraison (« colis.statut »), responsable
--      de livraison (« colis.statut » + « livraisons.gerer »), manager des opérations (gérant ou administrateur) ;
--   2. chauffeur : statut actif / inactif / en congé avec MOTIF (refusé tant qu'il a des missions ouvertes),
--      véhicule (un véhicule actif, à un seul chauffeur), fiche (téléphone, permis, succursale, nombre d'arrêts) ;
--   3. véhicule : statut ACTIF / EN MAINTENANCE / HORS SERVICE avec motif ; le moteur d'affectation l'écarte ;
--   4. zone : SECTEURS (quartiers), mise à jour, et la zone trouvée seule pour une livraison (pays, ville, secteur) ;
--   5. affectation : réaffecter EXIGE un motif (proposer, accepter, refuser l'exigeaient déjà) ;
--   6. tournée : ordre des arrêts, ajout et retrait d'une mission, annulation, fiche de la tournée ;
--   7. preuve de livraison : l'heure du TÉLÉPHONE au moment de la remise (une preuve rejouée après une coupure
--      garde son heure réelle), toujours en ajout seul ;
--   8. incidents : téléphone incorrect, colis manquant, livraison impossible (en plus de client absent, adresse
--      incorrecte, refus, dommage) ;
--   9. le TABLEAU DU DERNIER KILOMÈTRE : missions du jour, livraisons en cours, chauffeurs actifs, échecs,
--      incidents, SLA, preuves manquantes — calculé ici, rendu tel quel au centre de commande, relu à chaque
--      signal temps réel (étape 10).
--
-- Fonctions redéfinies (copies des étapes 6, 11 ou 15, modifiées seulement là où c'est dit, mêmes signatures) :
-- report_incident_for_task, fail_task, cancel_task, assign_task, complete_delivery, create_delivery, staff_profile,
-- mobile_command. Rejouable sans risque ; aucune donnée supprimée. Retour arrière : docs/architecture/DERNIER-KILOMETRE.md §9.
-- =============================================================================

-- 1. Le vocabulaire ------------------------------------------------------------------------------------------------
do $$
declare v_types text[]; v_def text;
begin
  -- La liste d'avant (lue dans la contrainte elle-même), plus ce qui est déjà employé, plus les deux nouveaux genres.
  select pg_get_constraintdef(c.oid) into v_def from pg_constraint c where c.conrelid = 'logistics.event_type'::regclass and c.conname = 'event_type_aggregate_type_check';
  select array_agg(distinct x order by x) into v_types
    -- (deux écritures possibles : ARRAY['a'::text, …] à l'étape 6, '{a,b,…}'::text[] depuis l'étape 16)
    from (select m[1] as x from regexp_matches(coalesce(v_def, ''), '''([a-z_]+)''', 'g') m
          union select btrim(y) from unnest(string_to_array(substring(coalesce(v_def, '') from '\{([^}]*)\}'), ',')) y
          union select aggregate_type from logistics.event_type union select unnest(array['vehicle', 'zone'])) t;
  alter table logistics.event_type drop constraint if exists event_type_aggregate_type_check;
  execute format('alter table logistics.event_type add constraint event_type_aggregate_type_check check (aggregate_type = any (%L::text[]))', v_types);
end
$$;
insert into logistics.event_type (code, aggregate_type, description) values
  ('DriverStatusChanged',  'driver',  'Statut du chauffeur changé (actif, inactif, en congé)'),
  ('DriverVehicleChanged', 'driver',  'Véhicule du chauffeur changé'),
  ('DriverUpdated',        'driver',  'Fiche du chauffeur mise à jour'),
  ('VehicleStatusChanged', 'vehicle', 'Statut du véhicule changé (actif, maintenance, hors service)'),
  ('ZoneUpdated',          'zone',    'Zone de livraison mise à jour (villes, secteurs)'),
  ('TripStopsReordered',   'trip',    'Ordre des arrêts de la tournée changé'),
  ('TripTaskAdded',        'trip',    'Mission ajoutée à une tournée'),
  ('TripTaskRemoved',      'trip',    'Mission retirée d''une tournée'),
  ('TripCancelled',        'trip',    'Tournée annulée')
on conflict (code) do nothing;

-- Les incidents d'une livraison : trois genres de plus (la contrainte garde tous ceux d'avant).
do $$
declare v_types text[]; v_def text;
begin
  select pg_get_constraintdef(c.oid) into v_def from pg_constraint c where c.conrelid = 'logistics.incident'::regclass and c.conname = 'incident_type_check';
  select array_agg(distinct x order by x) into v_types
    from (select m[1] as x from regexp_matches(coalesce(v_def, ''), '''([A-Z_]+)''', 'g') m
          union select btrim(y) from unnest(string_to_array(substring(coalesce(v_def, '') from '\{([^}]*)\}'), ',')) y
          union select unnest(array['DAMAGED', 'PROHIBITED_ITEM', 'UNKNOWN_PARCEL', 'FORGED_LABEL', 'WRONG_WAREHOUSE', 'NO_CUSTOMER', 'CUSTOMER_ABSENT', 'WRONG_ADDRESS',
                                    'REFUSED', 'VEHICLE_PROBLEM', 'PAYMENT_PROBLEM', 'OTHER', 'WRONG_PHONE', 'MISSING_PARCEL', 'DELIVERY_IMPOSSIBLE'])) t;
  alter table logistics.incident drop constraint if exists incident_type_check;
  execute format('alter table logistics.incident add constraint incident_type_check check (type = any (%L::text[]))', v_types);
end
$$;


-- 2. Ce que les tables ne portaient pas -----------------------------------------------------------------------------
alter table logistics.vehicle add column if not exists status text not null default 'ACTIVE';
alter table logistics.vehicle add column if not exists status_reason text;
alter table logistics.vehicle drop constraint if exists vehicle_status_check;
alter table logistics.vehicle add constraint vehicle_status_check check (status in ('ACTIVE', 'MAINTENANCE', 'OUT_OF_SERVICE'));
-- Un véhicule déjà désactivé (étape 6) devient « hors service » ; un véhicule « actif » l'est des deux côtés.
update logistics.vehicle set status = 'OUT_OF_SERVICE' where not active and status = 'ACTIVE';
alter table logistics.vehicle drop constraint if exists vehicle_status_active;
alter table logistics.vehicle add constraint vehicle_status_active check (active = (status = 'ACTIVE'));

alter table logistics.delivery_zone add column if not exists sectors text[] not null default '{}';
comment on column logistics.delivery_zone.sectors is 'Secteurs (quartiers) de la zone : ce qui départage deux zones d''une même ville.';

-- L'heure de la remise selon le téléphone (une preuve envoyée après une coupure garde son heure réelle). delivered_at reste
-- l'heure d'enregistrement par la base. Nulle pour les preuves d'avant cette étape.
alter table logistics.proof_of_delivery add column if not exists captured_at timestamptz;
comment on column logistics.proof_of_delivery.captured_at is 'Heure de la remise relevée par le téléphone (7 jours au plus avant l''enregistrement, jamais dans le futur).';


-- 3. Le responsable de livraison ---------------------------------------------------------------------------------------
-- « livraisons.gerer » : gérer les chauffeurs, les véhicules, les zones, réaffecter et annuler des missions. La direction
-- (gérant, administrateur = manager des opérations) l'a d'office. Les gestes d'un agent (créer une livraison, affecter,
-- former une tournée) restent sous « colis.statut ».
create or replace function logistics.require_delivery_manager(p_actor uuid)
returns void language plpgsql stable set search_path = '' as $$
begin
  if p_actor is null or not (logistics.actor_can(p_actor, 'livraisons.gerer') or logistics.actor_can(p_actor, 'direction')) then
    raise exception 'Droit insuffisant (exige : livraisons.gerer).' using errcode = 'LG003';
  end if;
end;
$$;

create or replace function logistics.lm_label(p_actor uuid)
returns text language sql stable security definer set search_path = '' as $$ select coalesce((select email from auth.users where id = p_actor), '') $$;


-- 4. Chauffeurs ----------------------------------------------------------------------------------------------------------
create or replace function logistics.set_driver_status(p_actor uuid, p_driver uuid, p_status text, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d logistics.driver; v_corr uuid := gen_random_uuid(); v_open jsonb;
begin
  perform logistics.require_delivery_manager(p_actor);
  if p_status not in ('ACTIVE', 'INACTIVE', 'ON_LEAVE') then raise exception 'Statut de chauffeur inconnu : % (ACTIVE, INACTIVE, ON_LEAVE).', p_status using errcode = 'LG005'; end if;
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour changer le statut d''un chauffeur.' using errcode = 'LG005'; end if;
  select * into v_d from logistics.driver where id = p_driver for update;
  if not found then raise exception 'Chauffeur introuvable.' using errcode = 'LG002'; end if;
  if v_d.status = p_status then raise exception 'Le chauffeur est déjà %.', p_status using errcode = 'LG004'; end if;
  if p_status <> 'ACTIVE' then
    select jsonb_agg(jsonb_build_object('task_id', t.id, 'status', t.status) order by t.scheduled_date, t.id) into v_open
      from logistics.task t where t.driver_id = p_driver and t.status in ('ASSIGNED', 'ACCEPTED', 'STARTED');
    if v_open is not null then
      raise exception 'Le chauffeur a % mission(s) ouverte(s) : réaffectez-les d''abord.', jsonb_array_length(v_open) using errcode = 'LG005', detail = v_open::text;
    end if;
  else
    if not exists (select 1 from logistics.app_user u where u.id = v_d.user_id and u.active) then
      raise exception 'Le compte d''équipe du chauffeur est désactivé.' using errcode = 'LG005';
    end if;
  end if;
  update logistics.driver set status = p_status where id = p_driver;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'driver.status', 'driver', p_driver::text, jsonb_build_object('status', v_d.status),
          jsonb_build_object('status', p_status, 'reason', left(btrim(p_reason), 500)), v_corr);
  perform logistics.emit('DriverStatusChanged', 'driver', p_driver::text, v_corr, p_actor,
                         jsonb_build_object('driver_id', p_driver, 'from_status', v_d.status, 'to_status', p_status, 'reason', left(btrim(p_reason), 500)));
  return jsonb_build_object('driver_id', p_driver, 'status', p_status, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.set_driver_vehicle(p_actor uuid, p_driver uuid, p_vehicle uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d logistics.driver; v_v logistics.vehicle; v_autre text; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_delivery_manager(p_actor);
  select * into v_d from logistics.driver where id = p_driver for update;
  if not found then raise exception 'Chauffeur introuvable.' using errcode = 'LG002'; end if;
  if exists (select 1 from logistics.trip tr where tr.driver_id = p_driver and tr.status = 'STARTED') then
    raise exception 'Le chauffeur est en tournée : on ne change pas son véhicule en route.' using errcode = 'LG004';
  end if;
  if p_vehicle is not null then
    select * into v_v from logistics.vehicle where id = p_vehicle;
    if not found then raise exception 'Véhicule introuvable.' using errcode = 'LG002'; end if;
    if v_v.status <> 'ACTIVE' then raise exception 'Le véhicule % est % : il ne s''attribue pas.', v_v.plate, v_v.status using errcode = 'LG005'; end if;
    select d.full_name into v_autre from logistics.driver d where d.default_vehicle_id = p_vehicle and d.id <> p_driver and d.status = 'ACTIVE' limit 1;
    if v_autre is not null then raise exception 'Le véhicule % est déjà celui de %.', v_v.plate, v_autre using errcode = 'LG005'; end if;
  end if;
  update logistics.driver set default_vehicle_id = p_vehicle where id = p_driver;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'driver.vehicle', 'driver', p_driver::text, jsonb_build_object('vehicle_id', v_d.default_vehicle_id),
          jsonb_build_object('vehicle_id', p_vehicle), v_corr);
  perform logistics.emit('DriverVehicleChanged', 'driver', p_driver::text, v_corr, p_actor,
                         jsonb_build_object('driver_id', p_driver, 'previous_vehicle_id', v_d.default_vehicle_id, 'vehicle_id', p_vehicle));
  return jsonb_build_object('driver_id', p_driver, 'vehicle', (select jsonb_build_object('plate', v.plate, 'kind', v.kind) from logistics.vehicle v where v.id = p_vehicle));
end;
$$;

-- Une valeur nulle laisse le champ tel quel.
create or replace function logistics.update_driver(p_actor uuid, p_driver uuid, p_full_name text default null, p_phone text default null,
                                                   p_license_no text default null, p_home_branch uuid default null, p_max_stops int default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d logistics.driver; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_delivery_manager(p_actor);
  select * into v_d from logistics.driver where id = p_driver for update;
  if not found then raise exception 'Chauffeur introuvable.' using errcode = 'LG002'; end if;
  if p_full_name is not null and btrim(p_full_name) = '' then raise exception 'Le nom du chauffeur ne peut pas être vide.' using errcode = 'LG005'; end if;
  if p_max_stops is not null and p_max_stops not between 1 and 200 then raise exception 'Nombre d''arrêts maximal entre 1 et 200.' using errcode = 'LG005'; end if;
  if p_home_branch is not null and not exists (select 1 from logistics.branch b where b.id = p_home_branch and b.active) then raise exception 'Succursale inconnue.' using errcode = 'LG005'; end if;
  update logistics.driver set full_name = coalesce(btrim(p_full_name), full_name), phone = coalesce(btrim(p_phone), phone), license_no = coalesce(btrim(p_license_no), license_no),
         home_branch_id = coalesce(p_home_branch, home_branch_id), max_stops = coalesce(p_max_stops, max_stops) where id = p_driver;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'driver.update', 'driver', p_driver::text,
          jsonb_build_object('full_name', v_d.full_name, 'phone', v_d.phone, 'license_no', v_d.license_no, 'home_branch_id', v_d.home_branch_id, 'max_stops', v_d.max_stops),
          (select jsonb_build_object('full_name', d.full_name, 'phone', d.phone, 'license_no', d.license_no, 'home_branch_id', d.home_branch_id, 'max_stops', d.max_stops) from logistics.driver d where d.id = p_driver), v_corr);
  perform logistics.emit('DriverUpdated', 'driver', p_driver::text, v_corr, p_actor, jsonb_build_object('driver_id', p_driver));
  return (select jsonb_build_object('driver_id', d.id, 'name', d.full_name, 'phone', d.phone, 'max_stops', d.max_stops, 'status', d.status) from logistics.driver d where d.id = p_driver);
end;
$$;


-- 5. Véhicules -------------------------------------------------------------------------------------------------------------
create or replace function logistics.set_vehicle_status(p_actor uuid, p_vehicle uuid, p_status text, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_v logistics.vehicle; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_delivery_manager(p_actor);
  if p_status not in ('ACTIVE', 'MAINTENANCE', 'OUT_OF_SERVICE') then raise exception 'Statut de véhicule inconnu : % (ACTIVE, MAINTENANCE, OUT_OF_SERVICE).', p_status using errcode = 'LG005'; end if;
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour changer le statut d''un véhicule.' using errcode = 'LG005'; end if;
  select * into v_v from logistics.vehicle where id = p_vehicle for update;
  if not found then raise exception 'Véhicule introuvable.' using errcode = 'LG002'; end if;
  if v_v.status = p_status then raise exception 'Le véhicule est déjà %.', p_status using errcode = 'LG004'; end if;
  if p_status <> 'ACTIVE' and exists (select 1 from logistics.trip tr where tr.vehicle_id = p_vehicle and tr.status = 'STARTED') then
    raise exception 'Le véhicule % est en tournée : terminez-la d''abord.', v_v.plate using errcode = 'LG005';
  end if;
  update logistics.vehicle set status = p_status, active = (p_status = 'ACTIVE'), status_reason = left(btrim(p_reason), 500) where id = p_vehicle;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'vehicle.status', 'vehicle', p_vehicle::text, jsonb_build_object('status', v_v.status),
          jsonb_build_object('status', p_status, 'reason', left(btrim(p_reason), 500)), v_corr);
  perform logistics.emit('VehicleStatusChanged', 'vehicle', p_vehicle::text, v_corr, p_actor,
                         jsonb_build_object('vehicle_id', p_vehicle, 'plate', v_v.plate, 'from_status', v_v.status, 'to_status', p_status, 'reason', left(btrim(p_reason), 500)));
  return jsonb_build_object('vehicle_id', p_vehicle, 'plate', v_v.plate, 'status', p_status,
                            'drivers', coalesce((select jsonb_agg(d.full_name order by d.full_name) from logistics.driver d where d.default_vehicle_id = p_vehicle and d.status = 'ACTIVE'), '[]'::jsonb));
end;
$$;


-- 6. Zones et secteurs ------------------------------------------------------------------------------------------------------
create or replace function logistics.update_zone(p_actor uuid, p_zone uuid, p_name text default null, p_cities text[] default null, p_sectors text[] default null, p_active boolean default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_z logistics.delivery_zone; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_delivery_manager(p_actor);
  select * into v_z from logistics.delivery_zone where id = p_zone for update;
  if not found then raise exception 'Zone introuvable.' using errcode = 'LG002'; end if;
  if p_active is false and exists (select 1 from logistics.task t where t.zone_id = p_zone and t.status in ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED')) then
    raise exception 'La zone a des missions ouvertes : elle ne se désactive pas.' using errcode = 'LG005';
  end if;
  update logistics.delivery_zone set name = coalesce(btrim(p_name), name),
         cities = coalesce((select array_agg(distinct btrim(c) order by btrim(c)) from unnest(p_cities) c where btrim(c) <> ''), case when p_cities is null then cities else '{}' end),
         sectors = coalesce((select array_agg(distinct btrim(s) order by btrim(s)) from unnest(p_sectors) s where btrim(s) <> ''), case when p_sectors is null then sectors else '{}' end),
         active = coalesce(p_active, active) where id = p_zone;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'zone.update', 'zone', p_zone::text, jsonb_build_object('name', v_z.name, 'cities', v_z.cities, 'sectors', v_z.sectors, 'active', v_z.active),
          (select jsonb_build_object('name', z.name, 'cities', z.cities, 'sectors', z.sectors, 'active', z.active) from logistics.delivery_zone z where z.id = p_zone), v_corr);
  perform logistics.emit('ZoneUpdated', 'zone', p_zone::text, v_corr, p_actor, jsonb_build_object('zone_id', p_zone, 'code', v_z.code));
  return (select jsonb_build_object('zone_id', z.id, 'code', z.code, 'name', z.name, 'country', z.country, 'cities', z.cities, 'sectors', z.sectors, 'active', z.active)
            from logistics.delivery_zone z where z.id = p_zone);
end;
$$;

-- La zone d'une adresse : d'abord le SECTEUR (le plus précis), sinon la VILLE ; une seule zone active doit répondre, sinon
-- aucune (deux zones possibles : c'est à l'équipe de choisir, la base ne devine pas). Majuscules, accents et espaces ignorés.
create or replace function logistics.zone_norm(p text)
returns text language sql immutable set search_path = '' as $$
  select lower(regexp_replace(translate(btrim(coalesce(p, '')), 'ÀÂÄÁÃÇÉÈÊËÍÎÏÌÑÓÔÖÒÕÚÛÜÙÝàâäáãçéèêëíîïìñóôöòõúûüùý', 'AAAAACEEEEIIIINOOOOOUUUUYaaaaaceeeeiiiinooooouuuuy'), '\s+', ' ', 'g'))
$$;

create or replace function logistics.resolve_zone(p_country text, p_city text, p_sector text default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_ids uuid[]; v_by text;
begin
  if nullif(btrim(coalesce(p_sector, '')), '') is not null then
    select array_agg(z.id order by z.code) into v_ids from logistics.delivery_zone z
     where z.active and z.country = p_country and exists (select 1 from unnest(z.sectors) s where logistics.zone_norm(s) = logistics.zone_norm(p_sector))
       and (nullif(btrim(coalesce(p_city, '')), '') is null or cardinality(z.cities) = 0 or exists (select 1 from unnest(z.cities) c where logistics.zone_norm(c) = logistics.zone_norm(p_city)));
    v_by := 'sector';
  end if;
  if coalesce(cardinality(v_ids), 0) = 0 and nullif(btrim(coalesce(p_city, '')), '') is not null then
    select array_agg(z.id order by z.code) into v_ids from logistics.delivery_zone z
     where z.active and z.country = p_country and exists (select 1 from unnest(z.cities) c where logistics.zone_norm(c) = logistics.zone_norm(p_city));
    v_by := 'city';
  end if;
  if coalesce(cardinality(v_ids), 0) = 0 then return jsonb_build_object('zone', null, 'matched_by', null, 'candidates', '[]'::jsonb); end if;
  return jsonb_build_object(
    'zone', case when cardinality(v_ids) = 1 then (select jsonb_build_object('zone_id', z.id, 'code', z.code, 'name', z.name) from logistics.delivery_zone z where z.id = v_ids[1]) end,
    'matched_by', v_by,
    'candidates', (select jsonb_agg(jsonb_build_object('zone_id', z.id, 'code', z.code, 'name', z.name) order by z.code) from logistics.delivery_zone z where z.id = any (v_ids)));
end;
$$;


-- 7. Tournées : ordre des arrêts, ajout, retrait, annulation, fiche -----------------------------------------------------------
-- Le chauffeur de la tournée peut réordonner SES arrêts encore à faire ; l'équipe (« colis.statut ») aussi.
create or replace function logistics.reorder_trip(p_actor uuid, p_trip uuid, p_task_ids uuid[])
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_tr logistics.trip; v_prevus uuid[]; v_corr uuid := gen_random_uuid(); v_i int; v_base int;
begin
  select * into v_tr from logistics.trip where id = p_trip for update;
  if not found or v_tr.kind <> 'LASTMILE' then raise exception 'Tournée introuvable.' using errcode = 'LG002'; end if;
  if logistics.driver_of(p_actor) is distinct from v_tr.driver_id then perform logistics.require_right(p_actor); end if;
  if v_tr.status not in ('PLANNED', 'STARTED') then raise exception 'La tournée est % : son ordre ne change plus.', v_tr.status using errcode = 'LG004'; end if;
  select coalesce(array_agg(s.task_id order by s.sequence), '{}') into v_prevus from logistics.stop s where s.trip_id = p_trip and s.status = 'PLANNED';
  if coalesce(cardinality(p_task_ids), 0) <> cardinality(v_prevus) or exists (select 1 from unnest(p_task_ids) x where x <> all (v_prevus))
     or (select count(distinct x) from unnest(p_task_ids) x) <> cardinality(v_prevus) then
    raise exception 'L''ordre doit citer EXACTEMENT les % arrêt(s) encore à faire, chacun une fois.', cardinality(v_prevus) using errcode = 'LG005';
  end if;
  -- Les arrêts déjà faits gardent leur rang ; ceux à faire se rangent après, dans l'ordre demandé.
  select coalesce(max(sequence), 0) into v_base from logistics.stop where trip_id = p_trip and status <> 'PLANNED';
  update logistics.stop set sequence = sequence + 100000 where trip_id = p_trip and status = 'PLANNED';
  for v_i in 1 .. cardinality(p_task_ids) loop
    update logistics.stop set sequence = v_base + v_i where trip_id = p_trip and task_id = p_task_ids[v_i] and status = 'PLANNED';
  end loop;
  perform logistics.emit('TripStopsReordered', 'trip', p_trip::text, v_corr, p_actor, jsonb_build_object('trip_id', p_trip, 'order', to_jsonb(p_task_ids)));
  return logistics.trip_detail(p_actor, p_trip);
end;
$$;

create or replace function logistics.add_task_to_trip(p_actor uuid, p_trip uuid, p_task uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_tr logistics.trip; v_t logistics.task; v_veh logistics.vehicle; v_dr logistics.driver; v_n int; v_w numeric; v_v numeric; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  select * into v_tr from logistics.trip where id = p_trip for update;
  if not found or v_tr.kind <> 'LASTMILE' then raise exception 'Tournée introuvable.' using errcode = 'LG002'; end if;
  if v_tr.status <> 'PLANNED' then raise exception 'Seule une tournée PRÉVUE reçoit une mission (elle est %).', v_tr.status using errcode = 'LG004'; end if;
  select * into v_t from logistics.task where id = p_task for update;
  if not found then raise exception 'Mission introuvable.' using errcode = 'LG002'; end if;
  if v_t.status <> 'ACCEPTED' or v_t.driver_id is distinct from v_tr.driver_id then raise exception 'La mission doit être ACCEPTÉE par le chauffeur de la tournée (elle est %).', v_t.status using errcode = 'LG005'; end if;
  if v_t.scheduled_date <> v_tr.trip_date then raise exception 'La mission est prévue un autre jour.' using errcode = 'LG005'; end if;
  if v_t.trip_id is not null then raise exception 'La mission est déjà dans une tournée.' using errcode = 'LG005'; end if;
  select * into v_dr from logistics.driver where id = v_tr.driver_id;
  select * into v_veh from logistics.vehicle where id = v_tr.vehicle_id;
  select count(*), coalesce(sum(t.weight_lb), 0), coalesce(sum(t.volume_ft3), 0) into v_n, v_w, v_v from logistics.task t where t.trip_id = p_trip and t.status not in ('CANCELLED');
  if v_n + 1 > v_dr.max_stops then raise exception 'Trop d''arrêts (% pour un maximum de %).', v_n + 1, v_dr.max_stops using errcode = 'LG005'; end if;
  if v_w + v_t.weight_lb > v_veh.capacity_lb then raise exception 'La tournée dépasserait la capacité du véhicule (% lb).', v_veh.capacity_lb using errcode = 'LG005'; end if;
  if v_veh.capacity_ft3 is not null and v_v + v_t.volume_ft3 > v_veh.capacity_ft3 then raise exception 'La tournée dépasserait le volume du véhicule.' using errcode = 'LG005'; end if;
  insert into logistics.stop (trip_id, sequence, kind, task_id, planned_at)
  values (p_trip, (select coalesce(max(sequence), 0) + 1 from logistics.stop where trip_id = p_trip), case when v_t.kind = 'PICKUP' then 'PICKUP' else 'DELIVERY' end, p_task, v_t.window_start);
  update logistics.task set trip_id = p_trip where id = p_task;
  perform logistics.emit('TripTaskAdded', 'trip', p_trip::text, v_corr, p_actor, jsonb_build_object('trip_id', p_trip, 'task_id', p_task));
  return logistics.trip_detail(p_actor, p_trip);
end;
$$;

create or replace function logistics.remove_task_from_trip(p_actor uuid, p_trip uuid, p_task uuid, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_tr logistics.trip; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour retirer une mission d''une tournée.' using errcode = 'LG005'; end if;
  select * into v_tr from logistics.trip where id = p_trip for update;
  if not found or v_tr.kind <> 'LASTMILE' then raise exception 'Tournée introuvable.' using errcode = 'LG002'; end if;
  if v_tr.status <> 'PLANNED' then raise exception 'Seule une tournée PRÉVUE se modifie (elle est %).', v_tr.status using errcode = 'LG004'; end if;
  if not exists (select 1 from logistics.task where id = p_task and trip_id = p_trip) then raise exception 'Cette mission n''est pas dans cette tournée.' using errcode = 'LG002'; end if;
  update logistics.stop set status = 'SKIPPED', actual_at = now() where trip_id = p_trip and task_id = p_task and status = 'PLANNED';
  update logistics.task set trip_id = null where id = p_task;
  perform logistics.emit('TripTaskRemoved', 'trip', p_trip::text, v_corr, p_actor, jsonb_build_object('trip_id', p_trip, 'task_id', p_task, 'reason', left(btrim(p_reason), 500)));
  return logistics.trip_detail(p_actor, p_trip);
end;
$$;

create or replace function logistics.cancel_trip(p_actor uuid, p_trip uuid, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_tr logistics.trip; v_corr uuid := gen_random_uuid(); v_n int;
begin
  perform logistics.require_delivery_manager(p_actor);
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour annuler une tournée.' using errcode = 'LG005'; end if;
  select * into v_tr from logistics.trip where id = p_trip for update;
  if not found or v_tr.kind <> 'LASTMILE' then raise exception 'Tournée introuvable.' using errcode = 'LG002'; end if;
  if v_tr.status <> 'PLANNED' then raise exception 'Seule une tournée PRÉVUE s''annule (elle est %).', v_tr.status using errcode = 'LG004'; end if;
  update logistics.stop set status = 'SKIPPED', actual_at = now() where trip_id = p_trip and status = 'PLANNED';
  update logistics.task set trip_id = null where trip_id = p_trip;
  get diagnostics v_n = row_count;
  update logistics.trip set status = 'CANCELLED' where id = p_trip;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'trip.cancel', 'trip', p_trip::text, jsonb_build_object('reason', left(btrim(p_reason), 500), 'tasks_released', v_n), v_corr);
  perform logistics.emit('TripCancelled', 'trip', p_trip::text, v_corr, p_actor, jsonb_build_object('trip_id', p_trip, 'reason', left(btrim(p_reason), 500), 'tasks_released', v_n));
  return jsonb_build_object('trip_id', p_trip, 'status', 'CANCELLED', 'tasks_released', v_n);
end;
$$;

-- La fiche d'une tournée : le chauffeur voit la sienne, l'équipe toutes. Les arrêts dans l'ordre, avec l'état de chaque mission.
create or replace function logistics.trip_detail(p_actor uuid, p_trip uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_tr logistics.trip;
begin
  select * into v_tr from logistics.trip where id = p_trip;
  if not found or v_tr.kind <> 'LASTMILE' then raise exception 'Tournée introuvable.' using errcode = 'LG002'; end if;
  if logistics.driver_of(p_actor) is distinct from v_tr.driver_id then perform logistics.require_right(p_actor, 'colis.lire'); end if;
  return jsonb_build_object(
    'trip_id', v_tr.id, 'date', v_tr.trip_date, 'status', v_tr.status,
    'driver', (select jsonb_build_object('driver_id', d.id, 'name', d.full_name, 'max_stops', d.max_stops) from logistics.driver d where d.id = v_tr.driver_id),
    'vehicle', (select jsonb_build_object('plate', v.plate, 'kind', v.kind, 'capacity_lb', v.capacity_lb, 'capacity_ft3', v.capacity_ft3, 'status', v.status) from logistics.vehicle v where v.id = v_tr.vehicle_id),
    'started_at', v_tr.actual_departure_at, 'completed_at', v_tr.actual_arrival_at,
    'load_lb', (select coalesce(sum(t.weight_lb), 0) from logistics.task t where t.trip_id = v_tr.id and t.status <> 'CANCELLED'),
    'stops', coalesce((select jsonb_agg(jsonb_build_object('sequence', s.sequence, 'stop_status', s.status, 'task_id', t.id, 'kind', t.kind, 'task_status', t.status,
                                                          'address', t.address, 'window_start', t.window_start, 'window_end', t.window_end, 'priority', t.priority,
                                                          'weight_lb', t.weight_lb, 'done_at', s.actual_at) order by s.sequence)
                         from logistics.stop s join logistics.task t on t.id = s.task_id where s.trip_id = v_tr.id and s.status <> 'SKIPPED'), '[]'::jsonb));
end;
$$;


-- 8. Les fonctions des étapes 6, 11 et 15, complétées -----------------------------------------------------------------------
create or replace function logistics.report_incident_for_task(p_task uuid, p_type text, p_description text, p_actor uuid, p_corr uuid)
returns uuid language plpgsql volatile set search_path = '' as $$
declare v_id uuid; v_parcel uuid;
begin
  select dp.parcel_id into v_parcel from logistics.task t join logistics.delivery_parcel dp on dp.delivery_id = t.delivery_id where t.id = p_task order by dp.parcel_id limit 1;
  insert into logistics.incident (parcel_id, task_id, type, severity, description, reported_by, correlation_id)
  values (v_parcel, p_task, p_type, case when p_type in ('DAMAGED', 'REFUSED', 'MISSING_PARCEL') then 'HIGH' else 'MEDIUM' end, left(coalesce(p_description, ''), 2000), p_actor, p_corr) returning id into v_id;
  perform logistics.emit('IncidentCreated', 'incident', v_id::text, p_corr, p_actor, jsonb_build_object('incident_id', v_id, 'type', p_type, 'task_id', p_task));
  return v_id;
end;
$$;

create or replace function logistics.fail_task(p_task_id uuid, p_actor uuid, p_incident_type text, p_description text default '', p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.require_driver_of_task(p_actor, p_task_id); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; v_inc uuid; r record;
begin
  if p_incident_type not in ('CUSTOMER_ABSENT', 'WRONG_ADDRESS', 'WRONG_PHONE', 'DAMAGED', 'MISSING_PARCEL', 'REFUSED', 'DELIVERY_IMPOSSIBLE',
                             'VEHICLE_PROBLEM', 'PAYMENT_PROBLEM', 'OTHER') then
    raise exception 'Type d''incident inconnu pour une mission : %.', p_incident_type using errcode = 'LG005';
  end if;
  select * into v_t from logistics.task where id = p_task_id for update;
  if v_t.status <> 'STARTED' then raise exception 'Seule une mission COMMENCÉE peut échouer (elle est %).', v_t.status using errcode = 'LG001'; end if;
  v_inc := (select logistics.report_incident_for_task(v_t.id, p_incident_type, p_description, p_actor, v_corr));
  update logistics.task set failed_reason = p_incident_type where id = p_task_id;
  perform logistics.move_task(p_task_id, 'FAILED', p_actor, v_corr, p_incident_type, jsonb_build_object('incident_id', v_inc));
  update logistics.assignment set status = 'COMPLETED', responded_at = now(), reason = p_incident_type where task_id = p_task_id and status = 'ACCEPTED';
  if v_t.kind = 'DELIVERY' then
    perform set_config('logistics.last_mile', 'on', true);
    for r in select dp.parcel_id from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id
              where dp.delivery_id = v_t.delivery_id and p.status = 'OUT_FOR_DELIVERY' order by dp.parcel_id loop
      perform logistics.transition_parcel(r.parcel_id, 'FAILED_DELIVERY', p_actor, null, v_corr, null, null, '', null, 'Livraison manquée : ' || p_incident_type, jsonb_build_object('task_id', p_task_id), 'api');
    end loop;
    perform set_config('logistics.last_mile', 'off', true);
  end if;
  return jsonb_build_object('task_id', p_task_id, 'status', 'FAILED', 'incident_id', v_inc, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.cancel_task(p_task_id uuid, p_actor uuid, p_reason text, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; r record;
begin
  perform logistics.require_delivery_manager(p_actor);
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif d''annulation est obligatoire.' using errcode = 'LG005'; end if;
  select * into v_t from logistics.task where id = p_task_id for update;
  perform logistics.move_task(p_task_id, 'CANCELLED', p_actor, v_corr, p_reason);
  update logistics.assignment set status = 'CANCELLED', responded_at = now(), reason = p_reason where task_id = p_task_id and status in ('OFFERED', 'ACCEPTED');
  if v_t.kind = 'DELIVERY' then
    for r in select dp.parcel_id from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = v_t.delivery_id and p.status in ('DELIVERY_ASSIGNED', 'FAILED_DELIVERY') order by dp.parcel_id loop
      perform logistics.transition_parcel(r.parcel_id, 'AT_DESTINATION_HUB', p_actor, null, v_corr, null, null, '', null, 'Livraison annulée : ' || p_reason, '{}', 'api');
    end loop;
  end if;
  return jsonb_build_object('task_id', p_task_id, 'status', 'CANCELLED', 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.assign_task(p_task_id uuid, p_driver_id uuid, p_actor uuid, p_force boolean default false, p_reason text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_t logistics.task; v_r record; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_a uuid; v_old uuid;
begin
  perform logistics.require_right(p_actor);
  select * into v_t from logistics.task where id = p_task_id for update;
  if not found then raise exception 'Mission introuvable.' using errcode = 'LG002'; end if;
  if v_t.status not in ('CREATED', 'ASSIGNED', 'ACCEPTED') then raise exception 'Une mission % ne s''affecte pas.', v_t.status using errcode = 'LG001'; end if;
  select * into v_r from logistics.rank_drivers(p_task_id) r where r.driver_id = p_driver_id;
  if not found then raise exception 'Chauffeur introuvable.' using errcode = 'LG002'; end if;
  if not v_r.eligible then
    if not p_force then raise exception 'Chauffeur non éligible : %.', array_to_string(v_r.reasons, ', ') using errcode = 'LG005'; end if;
    perform logistics.require_right(p_actor, 'direction');
    if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour forcer une affectation.' using errcode = 'LG005'; end if;
    insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
    values (p_actor, coalesce((select email from auth.users where id = p_actor), ''), 'task.assign_forced', 'task', p_task_id::text, jsonb_build_object('driver_id', p_driver_id, 'overridden', to_jsonb(v_r.reasons), 'reason', p_reason), v_corr);
  end if;
  select driver_id into v_old from logistics.assignment where task_id = p_task_id and status in ('OFFERED', 'ACCEPTED');
  -- Réaffecter retire la mission à quelqu'un : on dit pourquoi (le chauffeur précédent le verra dans l'historique).
  if v_old is not null and btrim(coalesce(p_reason, '')) = '' then
    raise exception 'Un motif est obligatoire pour réaffecter une mission.' using errcode = 'LG005';
  end if;
  update logistics.assignment set status = 'REASSIGNED', responded_at = now(), reason = p_reason where task_id = p_task_id and status in ('OFFERED', 'ACCEPTED');
  insert into logistics.assignment (task_id, driver_id, offered_by, score, detail) values (p_task_id, p_driver_id, p_actor, v_r.score, jsonb_build_object('reasons', to_jsonb(v_r.reasons), 'mode', case when v_old is null then 'manual' else 'reassign' end, 'forced', not v_r.eligible))
    returning id into v_a;
  update logistics.task set driver_id = p_driver_id, trip_id = null where id = p_task_id;
  update logistics.stop set status = 'SKIPPED', actual_at = now() where task_id = p_task_id and status = 'PLANNED';
  perform logistics.move_task(p_task_id, 'ASSIGNED', p_actor, v_corr, p_reason, jsonb_build_object('assignment_id', v_a, 'previous_driver_id', v_old));
  return jsonb_build_object('task_id', p_task_id, 'driver_id', p_driver_id, 'assignment_id', v_a, 'reassigned', v_old is not null, 'forced', not v_r.eligible, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.complete_delivery(
  p_task_id uuid, p_actor uuid, p_recipient_name text, p_latitude numeric, p_longitude numeric,
  p_signature_path text default null, p_photo_path text default null, p_otp text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_d uuid := logistics.require_driver_of_task(p_actor, p_task_id); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; v_del logistics.delivery;
  v_pod uuid := gen_random_uuid(); r record; v_n int := 0; v_ok boolean := false; v_tid uuid; v_capte timestamptz;
begin
  select * into v_t from logistics.task where id = p_task_id for update;
  if v_t.kind <> 'DELIVERY' then raise exception 'Ce n''est pas une livraison.' using errcode = 'LG005'; end if;
  if v_t.status <> 'STARTED' then raise exception 'La livraison doit être COMMENCÉE (elle est %).', v_t.status using errcode = 'LG001'; end if;
  if btrim(coalesce(p_recipient_name, '')) = '' then raise exception 'Le nom du destinataire est obligatoire.' using errcode = 'LG005'; end if;
  if p_latitude is null or p_longitude is null then raise exception 'La position GPS est obligatoire.' using errcode = 'LG005'; end if;
  if p_signature_path is null and p_photo_path is null then raise exception 'Une signature ou une photo est obligatoire.' using errcode = 'LG005'; end if;
  -- Les fichiers de preuve vivent sous pod/<id de la mission>/ : on ne s'appuie jamais sur le fichier d'une autre mission.
  if (p_signature_path is not null and p_signature_path not like 'pod/' || p_task_id::text || '/%')
     or (p_photo_path is not null and p_photo_path not like 'pod/' || p_task_id::text || '/%') then
    raise exception 'Les fichiers de preuve doivent se trouver sous pod/%/.', p_task_id using errcode = 'LG005';
  end if;
  select * into v_del from logistics.delivery where id = v_t.delivery_id for update;
  if v_del.otp_required then
    if v_del.otp_hash is null then raise exception 'Un code est exigé mais n''a pas été émis.' using errcode = 'LG005'; end if;
    if v_del.otp_attempts >= 5 then raise exception 'Trop d''essais : le code est bloqué, faites-en émettre un nouveau.' using errcode = 'LG004'; end if;
    if v_del.otp_expires_at < now() then raise exception 'Le code a expiré : faites-en émettre un nouveau.' using errcode = 'LG004'; end if;
    v_ok := coalesce(p_otp, '') <> '' and encode(sha256(convert_to(v_del.otp_salt || p_otp, 'UTF8')), 'hex') = v_del.otp_hash;
    if not v_ok then
      -- Le compteur doit survivre à l'erreur : on le note puis on échoue sans annuler cette écriture.
      update logistics.delivery set otp_attempts = otp_attempts + 1 where id = v_del.id;
      return jsonb_build_object('completed', false, 'reason', 'OTP_INVALID', 'attempts_left', 5 - (v_del.otp_attempts + 1));
    end if;
  end if;
  -- L'heure de la remise : celle du téléphone si l'application l'a transmise (mobile_command), bornée ; sinon maintenant.
  begin v_capte := nullif(current_setting('logistics.pod_captured_at', true), '')::timestamptz; exception when others then v_capte := null; end;
  if v_capte is null or v_capte > now() or v_capte < now() - interval '7 days' then v_capte := now(); end if;
  insert into logistics.proof_of_delivery (id, task_id, delivery_id, driver_id, recipient_name, signature_path, photo_path, latitude, longitude, otp_required, otp_verified, correlation_id, captured_at)
  values (v_pod, p_task_id, v_t.delivery_id, v_d, btrim(p_recipient_name), p_signature_path, p_photo_path, p_latitude, p_longitude, v_del.otp_required, v_ok, v_corr, v_capte);
  perform logistics.emit('ProofOfDeliveryCreated', 'delivery', v_t.delivery_id::text, v_corr, p_actor, jsonb_build_object('pod_id', v_pod, 'task_id', p_task_id, 'delivery_id', v_t.delivery_id, 'otp_verified', v_ok));
  perform set_config('logistics.last_mile', 'on', true);
  for r in select dp.parcel_id from logistics.delivery_parcel dp where dp.delivery_id = v_t.delivery_id order by dp.parcel_id loop
    perform logistics.transition_parcel(r.parcel_id, 'DELIVERED', p_actor, null, v_corr, null, null, '', null, null, jsonb_build_object('pod_id', v_pod), 'api');
    v_n := v_n + 1;
  end loop;
  perform set_config('logistics.last_mile', 'off', true);
  update logistics.delivery set otp_hash = null, otp_salt = null where id = v_t.delivery_id;
  perform logistics.move_task(p_task_id, 'COMPLETED', p_actor, v_corr, null, jsonb_build_object('pod_id', v_pod));
  update logistics.assignment set status = 'COMPLETED', responded_at = now() where task_id = p_task_id and status = 'ACCEPTED';
  return jsonb_build_object('completed', true, 'pod_id', v_pod, 'task_id', p_task_id, 'parcels_delivered', v_n, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.create_delivery(
  p_parcel_ids uuid[], p_hub_branch uuid, p_scheduled_for date, p_actor uuid,
  p_recipient_name text default '', p_recipient_phone text default '', p_address text default '', p_latitude numeric default null, p_longitude numeric default null,
  p_zone_id uuid default null, p_window_start timestamptz default null, p_window_end timestamptz default null, p_priority int default 3, p_otp_required boolean default false,
  p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_id uuid := gen_random_uuid(); v_task uuid := gen_random_uuid(); v_x uuid; v_p logistics.parcel; v_w numeric := 0; v_v numeric := 0; v_cust uuid;
begin
  perform logistics.require_right(p_actor);
  if coalesce(cardinality(p_parcel_ids), 0) = 0 then raise exception 'Une livraison contient au moins un colis.' using errcode = 'LG005'; end if;
  if btrim(coalesce(p_address, '')) = '' then raise exception 'L''adresse de livraison est obligatoire.' using errcode = 'LG005'; end if;
  if p_scheduled_for is null then raise exception 'La date de livraison est obligatoire.' using errcode = 'LG005'; end if;
  foreach v_x in array p_parcel_ids loop
    select * into v_p from logistics.parcel where id = v_x for update;
    if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
    if v_p.status <> 'AT_DESTINATION_HUB' then raise exception 'Le colis % est en % : seul un colis AU HUB se livre.', v_p.tracking_number, v_p.status using errcode = 'LG005'; end if;
    if v_cust is not null and v_p.customer_id is distinct from v_cust then raise exception 'Une livraison ne réunit que les colis d''un MÊME client.' using errcode = 'LG005'; end if;
    v_cust := v_p.customer_id;
    if exists (select 1 from logistics.delivery_parcel dp join logistics.task t on t.delivery_id = dp.delivery_id where dp.parcel_id = v_x and t.status not in ('COMPLETED', 'CANCELLED')) then
      raise exception 'Le colis % est déjà dans une livraison en cours.', v_p.tracking_number using errcode = 'LG005';
    end if;
    v_w := v_w + coalesce(v_p.verified_weight_lb, v_p.weight_lb, 0); v_v := v_v + coalesce(v_p.volume_ft3, 0);
  end loop;
  -- Sans zone donnée : celle de la ville du colis, si une seule zone active la couvre (sinon aucune : l'équipe choisira).
  if p_zone_id is null then p_zone_id := ((logistics.resolve_zone(v_p.destination_country, v_p.destination_city, null)) -> 'zone' ->> 'zone_id')::uuid; end if;
  insert into logistics.delivery (id, destination_branch_id, scheduled_for, zone_id, customer_id, recipient_name, recipient_phone, address, latitude, longitude, window_start, window_end, priority, weight_lb, volume_ft3, otp_required)
  values (v_id, p_hub_branch, p_scheduled_for, p_zone_id, v_cust, coalesce(p_recipient_name, ''), coalesce(p_recipient_phone, ''), btrim(p_address), p_latitude, p_longitude, p_window_start, p_window_end, p_priority, v_w, v_v, p_otp_required);
  foreach v_x in array p_parcel_ids loop
    insert into logistics.delivery_parcel (delivery_id, parcel_id) values (v_id, v_x);
    perform logistics.transition_parcel(v_x, 'DELIVERY_ASSIGNED', p_actor, null, v_corr, null, null, '', null, null, jsonb_build_object('delivery_id', v_id), 'api');
  end loop;
  insert into logistics.task (id, kind, delivery_id, customer_id, zone_id, address, latitude, longitude, scheduled_date, window_start, window_end, priority, weight_lb, volume_ft3, parcels_expected, created_by, correlation_id)
  values (v_task, 'DELIVERY', v_id, v_cust, p_zone_id, btrim(p_address), p_latitude, p_longitude, p_scheduled_for, p_window_start, p_window_end, p_priority, v_w, v_v, cardinality(p_parcel_ids), p_actor, v_corr);
  insert into logistics.task_status_history (task_id, from_status, to_status, actor_user_id, actor_label, correlation_id) values (v_task, null, 'CREATED', p_actor, coalesce((select email from auth.users where id = p_actor), ''), v_corr);
  perform logistics.emit('DeliveryCreated', 'delivery', v_id::text, v_corr, p_actor, jsonb_build_object('delivery_id', v_id, 'task_id', v_task, 'parcels', cardinality(p_parcel_ids), 'weight_lb', v_w, 'otp_required', p_otp_required));
  return jsonb_build_object('delivery_id', v_id, 'task_id', v_task, 'status', 'CREATED', 'weight_lb', v_w, 'volume_ft3', v_v, 'correlation_id', v_corr);
end;
$$;

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
  -- Étape 17 : qui gère la livraison (« livraisons.gerer ») et qui dirige les opérations (gérant, administrateur).
  if logistics.actor_can(p_actor, 'direction') then v_p := v_p || 'OPERATIONS_MANAGER'::text;
  elsif logistics.actor_can(p_actor, 'livraisons.gerer') then v_p := v_p || 'DELIVERY_MANAGER'::text; end if;
  return jsonb_build_object('staff', true, 'role', u.role, 'profiles', to_jsonb(v_p), 'driver', v_driver, 'today', logistics.today(),
    'branch', logistics.branch_label(u.branch_id),
    'warehouses', case when 'WAREHOUSE_AGENT' = any (v_p) then coalesce((select jsonb_agg(jsonb_build_object('warehouse_id', w.id, 'code', w.code, 'name', w.name) order by (w.branch_id = u.branch_id) desc, w.code)
                                                                    from logistics.warehouse w where w.active and (u.branch_id is null or w.branch_id = u.branch_id or not exists (select 1 from logistics.warehouse w2 where w2.branch_id = u.branch_id and w2.active))), '[]'::jsonb)
                        else '[]'::jsonb end);
end;
$$;

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
  end case;
  return logistics.idem_end(v_key, coalesce(v_out, '{}'::jsonb) || jsonb_build_object('command', p_command));
end;
$$;


-- 9. Le tableau du dernier kilomètre ------------------------------------------------------------------------------------------
-- Tout ce que l'écran affiche est compté ICI. Les définitions :
--   · « à l'heure » : remise (heure du téléphone, sinon de la base) avant la fin de la fenêtre promise, ou avant la fin de la
--     journée prévue quand il n'y a pas de fenêtre ;
--   · « en retard » : mission ouverte dont la fenêtre (ou la journée) est passée ;
--   · « premier passage » : livraison réussie sans échec antérieur sur la même mission ;
--   · « preuve manquante » : colis livré sans preuve de livraison — par dérogation de la direction (tracée) ou, anomalie, sans
--     rien ; et mission terminée sans preuve (ne doit jamais arriver : la base l'interdit).
-- La cible du SLA (95 % à l'heure) est une constante de l'entreprise : la changer ici.
create or replace function logistics.last_mile_dashboard(p_actor uuid, p_date date default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  v_day date := coalesce(p_date, logistics.today()); v_d0 timestamptz; v_d1 timestamptz; v_cible numeric := 0.95;
  v_taches jsonb; v_sla jsonb; v_chauffeurs jsonb; v_cours jsonb; v_echecs jsonb; v_inc jsonb; v_pod jsonb;
begin
  if p_actor is null or not (logistics.actor_can(p_actor, 'colis.lire') or logistics.actor_can(p_actor, 'livraisons.gerer')) then
    raise exception 'Droit insuffisant (exige : colis.lire).' using errcode = 'LG003';
  end if;
  v_d0 := logistics.day_start(v_day); v_d1 := logistics.day_start(v_day + 1);

  -- Les missions du jour (livraisons et enlèvements), par état.
  select jsonb_build_object(
           'total', count(*) filter (where t.status <> 'CANCELLED'),
           'deliveries', count(*) filter (where t.kind = 'DELIVERY' and t.status <> 'CANCELLED'),
           'pickups', count(*) filter (where t.kind = 'PICKUP' and t.status <> 'CANCELLED'),
           'by_status', jsonb_build_object('CREATED', count(*) filter (where t.status = 'CREATED'), 'ASSIGNED', count(*) filter (where t.status = 'ASSIGNED'),
                                           'ACCEPTED', count(*) filter (where t.status = 'ACCEPTED'), 'STARTED', count(*) filter (where t.status = 'STARTED'),
                                           'COMPLETED', count(*) filter (where t.status = 'COMPLETED'), 'FAILED', count(*) filter (where t.status = 'FAILED'),
                                           'CANCELLED', count(*) filter (where t.status = 'CANCELLED')),
           'unassigned', count(*) filter (where t.status = 'CREATED'),
           'late', count(*) filter (where t.status in ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED') and coalesce(t.window_end, v_d1) < now()))
    into v_taches from logistics.task t where t.scheduled_date = v_day;

  -- Le SLA des livraisons prévues ce jour.
  with l as (
    select t.id, t.status, coalesce(t.window_end, v_d1) as limite,
           (select coalesce(p.captured_at, p.delivered_at) from logistics.proof_of_delivery p where p.task_id = t.id) as remis,
           exists (select 1 from logistics.task_status_history h where h.task_id = t.id and h.to_status = 'FAILED') as deja_echoue
      from logistics.task t where t.kind = 'DELIVERY' and t.scheduled_date = v_day and t.status <> 'CANCELLED')
  select jsonb_build_object(
           'planned', count(*), 'completed', count(*) filter (where status = 'COMPLETED'),
           'on_time', count(*) filter (where status = 'COMPLETED' and remis <= limite),
           'late_completed', count(*) filter (where status = 'COMPLETED' and remis > limite),
           'late_open', count(*) filter (where status in ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED') and limite < now()),
           'failed', count(*) filter (where status = 'FAILED'),
           'first_attempt', count(*) filter (where status = 'COMPLETED' and not deja_echoue),
           'on_time_rate', case when count(*) filter (where status = 'COMPLETED') = 0 then null
                                else round(count(*) filter (where status = 'COMPLETED' and remis <= limite)::numeric / count(*) filter (where status = 'COMPLETED'), 4) end,
           'success_rate', case when count(*) filter (where status in ('COMPLETED', 'FAILED')) = 0 then null
                                else round(count(*) filter (where status = 'COMPLETED')::numeric / count(*) filter (where status in ('COMPLETED', 'FAILED')), 4) end,
           'first_attempt_rate', case when count(*) filter (where status = 'COMPLETED') = 0 then null
                                      else round(count(*) filter (where status = 'COMPLETED' and not deja_echoue)::numeric / count(*) filter (where status = 'COMPLETED'), 4) end,
           'target', v_cible,
           'met', case when count(*) filter (where status = 'COMPLETED') = 0 then null
                       else count(*) filter (where status = 'COMPLETED' and remis <= limite)::numeric / count(*) filter (where status = 'COMPLETED') >= v_cible end)
    into v_sla from l;

  -- Les livraisons en cours (commencées), la plus en retard d'abord.
  select coalesce(jsonb_agg(x order by (x ->> 'late')::boolean desc, x ->> 'window_end' nulls last, x ->> 'started_at'), '[]'::jsonb) into v_cours from (
    select jsonb_build_object('task_id', t.id, 'kind', t.kind, 'address', t.address, 'driver', dr.full_name, 'priority', t.priority, 'window_end', t.window_end,
             'started_at', (select max(h.occurred_at) from logistics.task_status_history h where h.task_id = t.id and h.to_status = 'STARTED'),
             'late', coalesce(t.window_end, logistics.day_start(t.scheduled_date + 1)) < now(),
             'parcels', (select count(*) from logistics.delivery_parcel dp where dp.delivery_id = t.delivery_id)) as x
      from logistics.task t left join logistics.driver dr on dr.id = t.driver_id where t.status = 'STARTED') z;

  -- Les chauffeurs ACTIFS : disponibilité du jour, véhicule, charge, arrêts, position, en tournée ou non.
  select coalesce(jsonb_agg(x order by (x ->> 'on_duty')::boolean desc, x ->> 'name'), '[]'::jsonb) into v_chauffeurs from (
    select jsonb_build_object('driver_id', d.id, 'name', d.full_name,
             'vehicle', (select jsonb_build_object('plate', v.plate, 'kind', v.kind, 'status', v.status, 'capacity_lb', v.capacity_lb) from logistics.vehicle v where v.id = d.default_vehicle_id),
             'available_today', exists (select 1 from logistics.driver_availability a where a.driver_id = d.id and a.available and a.starts_at < v_d1 and a.ends_at > v_d0)
                                and not exists (select 1 from logistics.driver_availability a where a.driver_id = d.id and not a.available and a.starts_at <= v_d0 and a.ends_at >= v_d1),
             'on_duty', exists (select 1 from logistics.task t where t.driver_id = d.id and t.status = 'STARTED')
                        or exists (select 1 from logistics.trip tr where tr.driver_id = d.id and tr.status = 'STARTED'),
             'tasks_today', (select count(*) from logistics.task t where t.driver_id = d.id and t.scheduled_date = v_day and t.status <> 'CANCELLED'),
             'completed_today', (select count(*) from logistics.task t where t.driver_id = d.id and t.scheduled_date = v_day and t.status = 'COMPLETED'),
             'failed_today', (select count(*) from logistics.task t where t.driver_id = d.id and t.scheduled_date = v_day and t.status = 'FAILED'),
             'open', (select count(*) from logistics.task t where t.driver_id = d.id and t.status in ('ASSIGNED', 'ACCEPTED', 'STARTED')),
             'load_lb', (select coalesce(sum(t.weight_lb), 0) from logistics.task t where t.driver_id = d.id and t.scheduled_date = v_day and t.status in ('ASSIGNED', 'ACCEPTED', 'STARTED')),
             'max_stops', d.max_stops,
             'position_age_min', case when d.last_position_at is null then null else round(extract(epoch from (now() - d.last_position_at)) / 60)::int end) as x
      from logistics.driver d join logistics.app_user u on u.id = d.user_id and u.active where d.status = 'ACTIVE') z;

  -- Les échecs du jour (même ceux replanifiés depuis), avec le genre d'incident.
  select coalesce(jsonb_agg(jsonb_build_object('task_id', h.task_id, 'at', h.occurred_at, 'reason', h.reason, 'driver', dr.full_name, 'address', t.address,
                                               'now', t.status) order by h.occurred_at desc), '[]'::jsonb)
    into v_echecs from logistics.task_status_history h join logistics.task t on t.id = h.task_id left join logistics.driver dr on dr.id = t.driver_id
   where h.to_status = 'FAILED' and h.occurred_at >= v_d0 and h.occurred_at < v_d1;

  -- Les incidents ouverts du dernier kilomètre (rattachés à une mission), par genre, et les plus récents.
  select jsonb_build_object(
           'open', (select count(*) from logistics.incident i where i.task_id is not null and i.status in ('OPEN', 'IN_PROGRESS')),
           'high', (select count(*) from logistics.incident i where i.task_id is not null and i.status in ('OPEN', 'IN_PROGRESS') and i.severity = 'HIGH'),
           'by_type', coalesce((select jsonb_object_agg(g.type, g.n) from (select i.type, count(*) as n from logistics.incident i where i.task_id is not null and i.status in ('OPEN', 'IN_PROGRESS') group by i.type) g), '{}'::jsonb),
           'today', (select count(*) from logistics.incident i where i.task_id is not null and i.created_at >= v_d0 and i.created_at < v_d1),
           'recent', coalesce((select jsonb_agg(jsonb_build_object('incident_id', i.id, 'type', i.type, 'severity', i.severity, 'at', i.created_at, 'task_id', i.task_id,
                                                                  'tracking_number', (select p.tracking_number from logistics.parcel p where p.id = i.parcel_id)) order by i.created_at desc)
                                 from (select * from logistics.incident x where x.task_id is not null and x.status in ('OPEN', 'IN_PROGRESS') order by x.created_at desc limit 20) i), '[]'::jsonb))
    into v_inc;

  -- Les preuves manquantes.
  select jsonb_build_object(
           'derogations_today', (select count(*) from logistics.audit_log a where a.action = 'parcel.delivered_without_proof' and a.occurred_at >= v_d0 and a.occurred_at < v_d1),
           'derogations_30_days', (select count(*) from logistics.audit_log a where a.action = 'parcel.delivered_without_proof' and a.occurred_at >= v_d0 - interval '30 days'),
           'anomalies', (select count(*) from logistics.parcel p where p.status = 'DELIVERED' and p.status_authority = 'core'
                           and not exists (select 1 from logistics.delivery_parcel dp join logistics.proof_of_delivery pod on pod.delivery_id = dp.delivery_id where dp.parcel_id = p.id)
                           and not exists (select 1 from logistics.audit_log a where a.action = 'parcel.delivered_without_proof' and a.entity_id = p.id::text)),
           'completed_tasks_without_proof', (select count(*) from logistics.task t where t.kind = 'DELIVERY' and t.status = 'COMPLETED'
                                               and not exists (select 1 from logistics.proof_of_delivery pod where pod.task_id = t.id)),
           'items', coalesce((select jsonb_agg(jsonb_build_object('tracking_number', p.tracking_number, 'at', a.occurred_at, 'reason', a.after ->> 'reason', 'kind', 'derogation') order by a.occurred_at desc)
                                from logistics.audit_log a join logistics.parcel p on p.id::text = a.entity_id
                               where a.action = 'parcel.delivered_without_proof' and a.occurred_at >= v_d0 - interval '30 days'), '[]'::jsonb))
    into v_pod;

  return jsonb_build_object('as_of', now(), 'date', v_day, 'tasks', v_taches, 'sla', v_sla, 'in_progress', v_cours,
    'drivers', jsonb_build_object('active', jsonb_array_length(v_chauffeurs),
                                  'available_today', (select count(*) from jsonb_array_elements(v_chauffeurs) x where (x ->> 'available_today')::boolean),
                                  'on_duty', (select count(*) from jsonb_array_elements(v_chauffeurs) x where (x ->> 'on_duty')::boolean),
                                  'items', v_chauffeurs),
    'failed', jsonb_build_object('count', jsonb_array_length(v_echecs), 'items', v_echecs),
    'incidents', v_inc, 'missing_pod', v_pod);
end;
$$;


-- 10. La façade : l'acteur est TOUJOURS le compte connecté ----------------------------------------------------------------
create or replace function public.lg_set_driver_status(p_driver_id uuid, p_status text, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.set_driver_status(auth.uid(), p_driver_id, p_status, p_reason) $$;
create or replace function public.lg_set_driver_vehicle(p_driver_id uuid, p_vehicle_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.set_driver_vehicle(auth.uid(), p_driver_id, p_vehicle_id) $$;
create or replace function public.lg_update_driver(p_driver_id uuid, p_full_name text default null, p_phone text default null, p_license_no text default null,
                                                   p_home_branch uuid default null, p_max_stops int default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.update_driver(auth.uid(), p_driver_id, p_full_name, p_phone, p_license_no, p_home_branch, p_max_stops) $$;
create or replace function public.lg_set_vehicle_status(p_vehicle_id uuid, p_status text, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.set_vehicle_status(auth.uid(), p_vehicle_id, p_status, p_reason) $$;
create or replace function public.lg_update_zone(p_zone_id uuid, p_name text default null, p_cities text[] default null, p_sectors text[] default null, p_active boolean default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.update_zone(auth.uid(), p_zone_id, p_name, p_cities, p_sectors, p_active) $$;
create or replace function public.lg_resolve_zone(p_country text, p_city text, p_sector text default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(auth.uid(), 'colis.lire');
  return logistics.resolve_zone(p_country, p_city, p_sector);
end;
$$;
create or replace function public.lg_reorder_trip(p_trip_id uuid, p_task_ids uuid[])
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.reorder_trip(auth.uid(), p_trip_id, p_task_ids) $$;
create or replace function public.lg_add_task_to_trip(p_trip_id uuid, p_task_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.add_task_to_trip(auth.uid(), p_trip_id, p_task_id) $$;
create or replace function public.lg_remove_task_from_trip(p_trip_id uuid, p_task_id uuid, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.remove_task_from_trip(auth.uid(), p_trip_id, p_task_id, p_reason) $$;
create or replace function public.lg_cancel_trip(p_trip_id uuid, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cancel_trip(auth.uid(), p_trip_id, p_reason) $$;
create or replace function public.lg_trip_detail(p_trip_id uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.trip_detail(auth.uid(), p_trip_id) $$;
create or replace function public.lg_cc_last_mile(p_date date default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.last_mile_dashboard(auth.uid(), p_date) $$;


-- 11. Tout fermé, sauf la façade, réservée aux comptes connectés ---------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('require_delivery_manager', 'lm_label', 'set_driver_status', 'set_driver_vehicle', 'update_driver', 'set_vehicle_status',
              'update_zone', 'zone_norm', 'resolve_zone', 'reorder_trip', 'add_task_to_trip', 'remove_task_from_trip', 'cancel_trip', 'trip_detail', 'report_incident_for_task',
              'fail_task', 'cancel_task', 'assign_task', 'complete_delivery', 'create_delivery', 'staff_profile', 'mobile_command', 'last_mile_dashboard') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_set_driver_status', 'lg_set_driver_vehicle', 'lg_update_driver', 'lg_set_vehicle_status', 'lg_update_zone', 'lg_resolve_zone',
              'lg_reorder_trip', 'lg_add_task_to_trip', 'lg_remove_task_from_trip', 'lg_cancel_trip', 'lg_trip_detail', 'lg_cc_last_mile') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
