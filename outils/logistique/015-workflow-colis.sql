-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 15 : le workflow opérationnel du colis
-- -----------------------------------------------------------------------------
-- Phase 3. À coller dans Supabase > SQL Editor APRÈS 014, d'abord en PRÉPRODUCTION,
-- puis en production après une sauvegarde « avant migration » vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site » (ou la préproduction).
--
-- Ce que cette étape ajoute à la machine d'états de l'étape 3 (sans la réécrire) :
--   1. deux statuts du workflow cible : LOADED (chargé dans son transport, scan de sortie)
--      et FAILED_DELIVERY (livraison manquée) ; et le NOM MÉTIER de chaque statut
--      (RECEIVED_AT_WAREHOUSE, INSPECTED, READY_FOR_SHIPMENT, ARRIVED_AT_HUB, CUSTOMS,
--      CLEARED, READY_FOR_DELIVERY…), accepté aussi par la façade ;
--   2. leurs transitions, en données, comme les autres (tout le reste reste INTERDIT) ;
--   3. la COHÉRENCE colis / livraison / mission, vérifiée au moment de valider chaque
--      transaction : un colis ne peut être « affecté », « en livraison », « livraison
--      manquée » ou « livré » que si sa mission le justifie, et « chargé » que s'il
--      appartient à une expédition prête — quel que soit le chemin pris ;
--   4. l'entrepôt : scan de SORTIE (load), scan d'INVENTAIRE, recherche d'emplacement,
--      inventaire par entrepôt et par emplacement ;
--   5. la mission échouée met ses colis en FAILED_DELIVERY (et non plus directement au
--      hub) ; la replanification et l'annulation en tiennent compte ; le client est
--      prévenu (règle de notification DeliveryFailed) ;
--   6. l'expédition qui part emmène ses colis CHARGÉS, et compte ceux partis sans scan
--      de sortie ; rouverte ou annulée, elle les décharge d'abord.
--
-- Fonctions redéfinies (copies des étapes 4, 5, 6 et 8, modifiées seulement là où c'est
-- dit) : assess_scan, scan_parcel, cascade_parcels, fail_task, reschedule_task,
-- cancel_task, customer_stage, et la façade lg_transition_parcel.
-- Rejouable sans risque ; rien n'est supprimé. Retour arrière : docs/architecture/PARCEL-STATE-MACHINE.md §7.
-- =============================================================================

-- 1. Les statuts et leurs noms métier ----------------------------------------------------------------------------
insert into logistics.parcel_status (code, sort_order, is_terminal, is_exception, label_key) values
  ('LOADED',           75, false, false, 'status-loaded'),
  ('FAILED_DELIVERY', 250, false, true,  'status-failed-delivery')
on conflict (code) do nothing;

alter table logistics.parcel_status add column if not exists business_name text;
update logistics.parcel_status s set business_name = m.nom
  from (values ('CREATED', 'CREATED'), ('RECEIVED', 'RECEIVED_AT_WAREHOUSE'), ('VERIFIED', 'INSPECTED'), ('STORED', 'STORED'),
               ('CONSOLIDATION_PENDING', 'CONSOLIDATION_PENDING'), ('CONSOLIDATED', 'CONSOLIDATED'), ('READY_FOR_EXPORT', 'READY_FOR_SHIPMENT'),
               ('LOADED', 'LOADED'), ('IN_TRANSIT', 'IN_TRANSIT'), ('ARRIVED', 'ARRIVED_AT_HUB'), ('CUSTOMS_PROCESSING', 'CUSTOMS'),
               ('CUSTOMS_CLEARED', 'CLEARED'), ('AT_DESTINATION_HUB', 'READY_FOR_DELIVERY'), ('DELIVERY_ASSIGNED', 'DELIVERY_ASSIGNED'),
               ('OUT_FOR_DELIVERY', 'OUT_FOR_DELIVERY'), ('DELIVERED', 'DELIVERED'), ('ON_HOLD', 'ON_HOLD'), ('DAMAGED', 'DAMAGED'),
               ('LOST', 'LOST'), ('RETURNED', 'RETURNED'), ('FAILED_DELIVERY', 'FAILED_DELIVERY'), ('CANCELLED', 'CANCELLED')) m (code, nom)
 where s.code = m.code and s.business_name is distinct from m.nom;
create unique index if not exists parcel_status_business_name_idx on logistics.parcel_status (business_name);
comment on column logistics.parcel_status.business_name is 'Le nom du statut dans le workflow métier (docs/architecture/PARCEL-STATE-MACHINE.md). Le code reste la clé.';

-- Un statut se donne par son code OU par son nom métier ; rien d'autre n'est accepté.
create or replace function logistics.status_code(p_name text)
returns text language sql stable set search_path = '' as $$
  select code from logistics.parcel_status where code = upper(btrim(p_name)) or business_name = upper(btrim(p_name)) limit 1
$$;

insert into logistics.event_type (code, aggregate_type, description) values
  ('ParcelLoaded',   'parcel', 'Colis chargé dans son transport (scan de sortie)'),
  ('ParcelUnloaded', 'parcel', 'Colis déchargé avant le départ'),
  ('DeliveryFailed', 'parcel', 'Livraison manquée')
on conflict (code) do nothing;


-- 2. Les transitions --------------------------------------------------------------------------------------------
insert into logistics.parcel_transition (from_status, to_status, event_type, required_right, requires_customer, requires_reason, allow_system) values
  -- le chargement : seul le scan de sortie y mène ; le départ de l'expédition emmène le colis
  ('READY_FOR_EXPORT', 'LOADED',             'ParcelLoaded',          'colis.statut', true,  false, false),
  ('LOADED',           'IN_TRANSIT',         'ParcelInTransit',       'colis.statut', true,  false, true),
  ('LOADED',           'READY_FOR_EXPORT',   'ParcelUnloaded',        'colis.statut', true,  true,  false),
  -- la livraison manquée : déclarée par le chauffeur de la mission (droit « livraison », étape 6), puis replanifiée,
  -- ramenée au hub ou retournée
  ('OUT_FOR_DELIVERY', 'FAILED_DELIVERY',    'DeliveryFailed',        'livraison',    true,  true,  false),
  ('FAILED_DELIVERY',  'DELIVERY_ASSIGNED',  'DeliveryAssigned',      'colis.statut', true,  false, false),
  ('FAILED_DELIVERY',  'AT_DESTINATION_HUB', 'ParcelReturnedToHub',   'colis.statut', true,  true,  false),
  ('FAILED_DELIVERY',  'RETURNED',           'ParcelReturned',        'direction',    false, true,  false)
on conflict do nothing;
-- Les exceptions, comme pour les autres statuts : tout opérateur SIGNALE (attente, dommage), la direction DÉCIDE.
insert into logistics.parcel_transition (from_status, to_status, event_type, required_right, requires_reason, resume) values
  ('LOADED',          'ON_HOLD',         'ParcelOnHold',  'colis.statut', true,  false),
  ('ON_HOLD',         'LOADED',          'ParcelResumed', 'direction',    false, true),
  ('LOADED',          'DAMAGED',         'ParcelDamaged', 'colis.statut', true,  false),
  ('LOADED',          'LOST',            'ParcelLost',    'direction',    true,  false),
  ('FAILED_DELIVERY', 'ON_HOLD',         'ParcelOnHold',  'colis.statut', true,  false),
  ('ON_HOLD',         'FAILED_DELIVERY', 'ParcelResumed', 'direction',    false, true),
  ('FAILED_DELIVERY', 'DAMAGED',         'ParcelDamaged', 'colis.statut', true,  false),
  ('FAILED_DELIVERY', 'LOST',            'ParcelLost',    'direction',    true,  false)
on conflict do nothing;

-- Le client est prévenu d'une livraison manquée (le modèle, en quatre langues, vient de outils/portail-textes.py → 010).
insert into logistics.notification_rule (event_type, template, channels) values
  ('DeliveryFailed', 'DeliveryFailed', array['in_app', 'push', 'email'])
on conflict (event_type) do nothing;
-- Le moteur de notifications n'écoute que les types d'événements qui ont une règle : on lui ajoute celui-ci (même
-- instruction que l'étape 10, qui la rejoue à l'identique si on la repasse).
update logistics.event_subscriber
   set event_types = (select array_agg(event_type order by event_type) from logistics.notification_rule)
 where code = 'notification_engine'
   and event_types is distinct from (select array_agg(event_type order by event_type) from logistics.notification_rule);


-- 3. Les liens colis ↔ expédition, et la cohérence colis / livraison / mission --------------------------------------
-- L'expédition encore à quai (dans les statuts donnés) qui emporte ce colis, directement ou par sa consolidation.
create or replace function logistics.parcel_open_shipment(p_parcel_id uuid, p_statuses text[] default array['DRAFT', 'READY'])
returns uuid language sql stable set search_path = '' as $$
  select s.id from logistics.shipment s
   where s.status = any (p_statuses)
     and exists (select 1 from logistics.shipment_parcels(s.id) x where x.parcel_id = p_parcel_id)
   order by s.created_at desc limit 1
$$;

-- Ce qui cloche pour ce colis, ou rien. Lue par le contrôle de fin de transaction et par le rapport de cohérence.
create or replace function logistics.parcel_coherence_issue(p_parcel_id uuid)
returns text language plpgsql stable set search_path = '' as $$
declare
  v_p logistics.parcel;
  v_missions text[];
begin
  select * into v_p from logistics.parcel where id = p_parcel_id;
  if not found or v_p.status_authority <> 'core' then return null; end if;
  select coalesce(array_agg(t.status), '{}') into v_missions
    from logistics.delivery_parcel dp join logistics.task t on t.delivery_id = dp.delivery_id and t.kind = 'DELIVERY'
   where dp.parcel_id = p_parcel_id;
  if v_p.status = 'LOADED' and logistics.parcel_open_shipment(p_parcel_id, array['READY']) is null then
    return 'chargé sans expédition prête';
  elsif v_p.status = 'DELIVERY_ASSIGNED' and not (v_missions && array['CREATED', 'ASSIGNED', 'ACCEPTED']) then
    return 'affecté à une livraison sans mission en attente';
  elsif v_p.status = 'OUT_FOR_DELIVERY' and not (v_missions && array['STARTED']) then
    return 'en livraison sans mission commencée';
  elsif v_p.status = 'FAILED_DELIVERY' and not (v_missions && array['FAILED']) then
    return 'livraison manquée sans mission échouée';
  elsif v_p.status = 'DELIVERED' and not (v_missions && array['COMPLETED'])
        and not exists (select 1 from logistics.audit_log a where a.action = 'parcel.delivered_without_proof' and a.entity_id = p_parcel_id::text) then
    return 'livré sans mission terminée ni dérogation de la direction';
  end if;
  return null;
end;
$$;

-- (security definer : à la validation, il s'exécute sous l'identité de la personne connectée, qui n'a pas accès au noyau.)
-- Le contrôle de fin de transaction : DIFFÉRÉ, il voit l'état final (une fonction de mission change la mission et ses
-- colis dans un ordre qui lui est propre) ; il refuse la transaction entière si un colis y est resté incohérent.
create or replace function logistics.check_parcel_coherence()
returns trigger language plpgsql security definer set search_path = '' as $$
declare v_pb text; v_num text;
begin
  v_pb := logistics.parcel_coherence_issue(new.id);
  if v_pb is not null then
    select tracking_number into v_num from logistics.parcel where id = new.id;
    raise exception 'Statut incohérent pour le colis % : %.', v_num, v_pb using errcode = 'LG001';
  end if;
  return null;
end;
$$;
drop trigger if exists parcel_workflow_coherence on logistics.parcel;
create constraint trigger parcel_workflow_coherence
  after update of status on logistics.parcel
  deferrable initially deferred
  for each row when (new.status is distinct from old.status and new.status_authority = 'core')
  execute function logistics.check_parcel_coherence();

-- Le même contrôle, du côté de la mission : une mission qui change d'état ne laisse pas ses colis dans un statut qu'elle
-- ne justifie plus.
create or replace function logistics.check_task_coherence()
returns trigger language plpgsql security definer set search_path = '' as $$
declare r record; v_pb text;
begin
  if new.kind <> 'DELIVERY' or new.delivery_id is null then return null; end if;
  for r in select p.id, p.tracking_number from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id
            where dp.delivery_id = new.delivery_id loop
    v_pb := logistics.parcel_coherence_issue(r.id);
    if v_pb is not null then
      raise exception 'Statut incohérent pour le colis % : %.', r.tracking_number, v_pb using errcode = 'LG001';
    end if;
  end loop;
  return null;
end;
$$;
drop trigger if exists task_workflow_coherence on logistics.task;
create constraint trigger task_workflow_coherence
  after update of status on logistics.task
  deferrable initially deferred
  for each row when (new.status is distinct from old.status)
  execute function logistics.check_task_coherence();

-- Le rapport de cohérence, pour la surveillance et avant toute bascule : chaque colis du noyau dont le statut ne
-- correspond pas à sa mission, à son expédition ou à son emplacement. Lecture seule.
create or replace function logistics.workflow_inconsistencies()
returns table (tracking_number text, status text, issue text)
language sql stable set search_path = '' as $$
  select p.tracking_number, p.status, logistics.parcel_coherence_issue(p.id)
    from logistics.parcel p where p.status_authority = 'core' and logistics.parcel_coherence_issue(p.id) is not null
  union all
  select p.tracking_number, p.status, 'parti sans expédition partie'
    from logistics.parcel p
   where p.status_authority = 'core' and p.status in ('IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED')
     and logistics.parcel_open_shipment(p.id, array['DISPATCHED', 'IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_HUB', 'CLOSED']) is null
  union all
  select p.tracking_number, p.status, 'rangé sans emplacement'
    from logistics.parcel p where p.status_authority = 'core' and p.status = 'STORED' and p.current_location_id is null
$$;


-- 4. Le scan : sortie et inventaire --------------------------------------------------------------------------------
alter table logistics.scan drop constraint if exists scan_purpose_check;
alter table logistics.scan add constraint scan_purpose_check
  check (purpose in ('receive', 'verify', 'store', 'move', 'consolidate', 'dispatch', 'lookup', 'load', 'inventory'));

create or replace function logistics.assess_scan(
  p_status text, p_is_prohibited boolean, p_has_customer boolean,
  p_parcel_warehouse uuid, p_parcel_location uuid,
  p_purpose text, p_warehouse uuid, p_location uuid)
returns text
language plpgsql immutable set search_path = ''
as $$
begin
  if p_purpose = 'lookup' then return 'ACCEPTED'; end if;
  -- Inventaire : constater qu'un colis est physiquement là, quel que soit son statut d'entrepôt (même retenu ou abîmé).
  if p_purpose = 'inventory' then
    if p_status not in ('RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'LOADED', 'ON_HOLD', 'DAMAGED') then
      return 'WRONG_STATE';
    end if;
    if p_parcel_warehouse is not null and p_parcel_warehouse <> p_warehouse then return 'WRONG_WAREHOUSE'; end if;
    return 'ACCEPTED';
  end if;
  if p_status in ('IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED',
                  'OUT_FOR_DELIVERY', 'DELIVERED', 'RETURNED', 'FAILED_DELIVERY') then
    return 'ALREADY_DISPATCHED';
  end if;
  if p_status in ('CANCELLED', 'LOST') then return 'WRONG_STATE'; end if;
  if p_is_prohibited then return 'PROHIBITED'; end if;
  if p_status = 'ON_HOLD' then return 'WRONG_STATE'; end if;
  if p_status = 'DAMAGED' and p_purpose in ('receive', 'verify', 'store', 'consolidate', 'dispatch') then return 'DAMAGED'; end if;
  if p_parcel_warehouse is not null and p_parcel_warehouse <> p_warehouse then return 'WRONG_WAREHOUSE'; end if;

  if p_purpose = 'receive' then
    if p_status = 'CREATED' then return 'ACCEPTED'; end if;
    if p_status in ('RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'LOADED') then return 'DUPLICATE'; end if;
  elsif p_purpose = 'verify' then
    if p_status = 'RECEIVED' then return 'ACCEPTED'; end if;
    if p_status in ('VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'LOADED') then return 'DUPLICATE'; end if;
  elsif p_purpose = 'store' then
    if p_status = 'VERIFIED' then return 'ACCEPTED'; end if;
    if p_status = 'STORED' and p_parcel_location is not distinct from p_location then return 'DUPLICATE'; end if;
  elsif p_purpose = 'move' then
    if p_status in ('RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'DAMAGED')
       and p_location is not null then
      if p_parcel_location is not distinct from p_location then return 'DUPLICATE'; end if;
      return 'ACCEPTED';
    end if;
  elsif p_purpose = 'consolidate' then
    if p_status = 'STORED' then
      if not p_has_customer then return 'NO_CUSTOMER'; end if;
      return 'ACCEPTED';
    end if;
    if p_status in ('CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'LOADED') then return 'DUPLICATE'; end if;
  elsif p_purpose = 'dispatch' then
    if p_status in ('READY_FOR_EXPORT', 'LOADED') then return 'ACCEPTED'; end if;
  elsif p_purpose = 'load' then
    -- Le scan de SORTIE : le colis quitte l'entrepôt pour son transport. L'expédition prête est vérifiée par scan_parcel.
    if p_status = 'READY_FOR_EXPORT' then return 'ACCEPTED'; end if;
    if p_status = 'LOADED' then return 'DUPLICATE'; end if;
  end if;
  return 'WRONG_STATE';
end;
$$;

create or replace function logistics.scan_parcel(
  p_code            text,
  p_purpose         text,
  p_actor           uuid,
  p_warehouse_id    uuid,
  p_location_id     uuid  default null,
  p_device_id       uuid  default null,
  p_code_kind       text  default 'unknown',
  p_idempotency_key text  default null,
  p_metadata        jsonb default '{}'::jsonb,
  p_correlation_id  uuid  default null)
returns jsonb
language plpgsql volatile security definer set search_path = ''
as $$
declare
  v_corr     uuid := coalesce(p_correlation_id, gen_random_uuid());
  v_hash     text;
  v_prior    jsonb;
  v_prior_h  text;
  v_wh       logistics.warehouse;
  v_branch   uuid;
  v_user_br  uuid;
  v_loc      logistics.warehouse_location;
  v_dev_kind text;
  v_code     jsonb;
  v_parcel   logistics.parcel;
  v_result   text;
  v_scan     uuid := gen_random_uuid();
  v_te       bigint;
  v_trans    jsonb;
  v_warnings text[] := '{}';
  v_out      jsonb;
  v_incident uuid;
  v_label    text;
  v_ship     uuid;
begin
  -- Ce qui relève d'une demande MAL FORMÉE ou NON AUTORISÉE lève une erreur ; tout le reste est un RÉSULTAT.
  if p_purpose not in ('receive', 'verify', 'store', 'move', 'consolidate', 'dispatch', 'lookup', 'load', 'inventory') then
    raise exception 'Intention de scan inconnue : %.', p_purpose using errcode = 'LG005';
  end if;
  if p_code_kind not in ('barcode', 'qr', 'manual', 'rfid', 'unknown') then
    raise exception 'Type de lecteur inconnu : %.', p_code_kind using errcode = 'LG005';
  end if;
  if p_actor is null or not logistics.actor_can(p_actor, 'colis.statut') then
    raise exception 'Droit insuffisant pour scanner (exige : colis.statut).' using errcode = 'LG003';
  end if;
  select * into v_wh from logistics.warehouse where id = p_warehouse_id and active;
  if not found then raise exception 'Entrepôt inconnu ou inactif.' using errcode = 'LG005'; end if;
  select branch_id into v_user_br from logistics.app_user where id = p_actor;
  if v_user_br is not null and v_user_br <> v_wh.branch_id then
    raise exception 'Cet entrepôt n''est pas celui de votre succursale.' using errcode = 'LG003';
  end if;
  if p_location_id is not null then
    select * into v_loc from logistics.warehouse_location where id = p_location_id and active;
    if not found or v_loc.warehouse_id <> p_warehouse_id then
      raise exception 'Emplacement inconnu, inactif, ou d''un autre entrepôt.' using errcode = 'LG005';
    end if;
  end if;
  if p_purpose in ('store', 'move') and p_location_id is null then
    raise exception 'Un emplacement est obligatoire pour « % ».', p_purpose using errcode = 'LG005';
  end if;
  if p_device_id is not null then
    select kind into v_dev_kind from logistics.device where id = p_device_id and active;
    if v_dev_kind is null or v_dev_kind not in ('phone_camera', 'usb_scanner', 'desktop_scanner', 'handheld_scanner') then
      raise exception 'Appareil inconnu, inactif, ou qui n''est pas un lecteur.' using errcode = 'LG005';
    end if;
  end if;
  v_code := logistics.parse_code(p_code);
  v_label := coalesce((select email from auth.users where id = p_actor), p_actor::text);

  -- Idempotence : un scan rejoué (réseau coupé, double appui) ne se compte pas deux fois.
  v_hash := md5(concat_ws('|', p_code, p_purpose, p_actor, p_warehouse_id, p_location_id, p_device_id, p_code_kind, p_metadata::text));
  if p_idempotency_key is not null then
    insert into logistics.command_log (idempotency_key, command, request_hash, entity_type, entity_id)
    values (p_idempotency_key, 'scan_parcel', v_hash, 'scan', v_scan::text) on conflict (idempotency_key) do nothing;
    if not found then
      select request_hash, result into v_prior_h, v_prior from logistics.command_log where idempotency_key = p_idempotency_key;
      if v_prior_h <> v_hash then raise exception 'Clé d''idempotence déjà utilisée pour une AUTRE demande.' using errcode = 'LG006'; end if;
      return coalesce(v_prior, '{}'::jsonb) || jsonb_build_object('replayed', true);
    end if;
  end if;

  -- Quel colis ?
  select * into v_parcel from logistics.parcel where tracking_number = v_code ->> 'number';
  if not found then
    v_result := 'UNKNOWN_PARCEL';
  elsif v_code ->> 'token' is not null and v_code ->> 'token' <> v_parcel.public_token then
    v_result := 'INVALID_CODE';           -- numéro connu, jeton faux : une étiquette falsifiée
  else
    v_result := logistics.assess_scan(v_parcel.status, v_parcel.is_prohibited, v_parcel.customer_id is not null,
                                      v_parcel.current_warehouse_id, v_parcel.current_location_id,
                                      p_purpose, p_warehouse_id, p_location_id);
  end if;

  -- Verrouiller le colis AVANT d'agir (deux scans simultanés du même colis ne se croisent pas) et réévaluer.
  if v_result = 'ACCEPTED' and p_purpose <> 'lookup' then
    select * into v_parcel from logistics.parcel where id = v_parcel.id for update;
    v_result := logistics.assess_scan(v_parcel.status, v_parcel.is_prohibited, v_parcel.customer_id is not null,
                                      v_parcel.current_warehouse_id, v_parcel.current_location_id,
                                      p_purpose, p_warehouse_id, p_location_id);
  end if;

  -- Sortie : le colis doit appartenir à une expédition PRÊTE (manifeste fait), sinon il ne monte pas.
  if v_result = 'ACCEPTED' and p_purpose = 'load' then
    v_ship := logistics.parcel_open_shipment(v_parcel.id, array['READY']);
    if v_ship is null then
      v_result := 'WRONG_STATE';
      v_warnings := array_append(v_warnings, 'NO_READY_SHIPMENT');
    end if;
  end if;
  if v_result = 'ACCEPTED' and p_purpose = 'inventory' and p_location_id is not null
     and v_parcel.current_location_id is distinct from p_location_id then
    v_warnings := array_append(v_warnings, 'LOCATION_MISMATCH');   -- trouvé ailleurs que là où le système le croit
  end if;

  -- Toujours enregistrer le scan (le refusé aussi : c'est une preuve) ---------------------------------------
  insert into logistics.scan (id, scanned_code, code_kind, purpose, result, parcel_id, actor_user_id, warehouse_id, location_id,
                              device_id, correlation_id, idempotency_key, metadata)
  values (v_scan, left(p_code, 500), p_code_kind, p_purpose, v_result, v_parcel.id, p_actor, p_warehouse_id, p_location_id,
          p_device_id, v_corr, p_idempotency_key, coalesce(p_metadata, '{}'::jsonb));

  -- Ce que le résultat entraîne -----------------------------------------------------------------------------
  if v_result = 'ACCEPTED' then
    if p_purpose = 'receive' then
      v_trans := logistics.transition_parcel(v_parcel.id, 'RECEIVED', p_actor, null, v_corr, p_warehouse_id, p_location_id, '', p_device_id,
                                             null, jsonb_build_object('scan_id', v_scan), 'scan');
      update logistics.parcel set received_at = coalesce(received_at, now()) where id = v_parcel.id;
      if v_parcel.customer_id is null then
        v_warnings := array_append(v_warnings, 'NO_CUSTOMER');
        v_incident := logistics.report_incident('NO_CUSTOMER', v_parcel.id, p_actor,
                        'Colis reçu sans client : à rattacher avant toute consolidation.', 'MEDIUM', p_warehouse_id, v_scan, v_corr);
      end if;
    elsif p_purpose = 'store' then
      v_trans := logistics.transition_parcel(v_parcel.id, 'STORED', p_actor, null, v_corr, p_warehouse_id, p_location_id, '', p_device_id,
                                             null, jsonb_build_object('scan_id', v_scan), 'scan');
      insert into logistics.parcel_movement (parcel_id, from_warehouse_id, from_location_id, to_warehouse_id, to_location_id, moved_by, reason, scan_id, correlation_id)
      values (v_parcel.id, v_parcel.current_warehouse_id, v_parcel.current_location_id, p_warehouse_id, p_location_id, p_actor, 'storage', v_scan, v_corr);
    elsif p_purpose = 'consolidate' then
      v_trans := logistics.transition_parcel(v_parcel.id, 'CONSOLIDATION_PENDING', p_actor, null, v_corr, p_warehouse_id, p_location_id, '', p_device_id,
                                             null, jsonb_build_object('scan_id', v_scan), 'scan');
    elsif p_purpose = 'load' then
      v_trans := logistics.transition_parcel(v_parcel.id, 'LOADED', p_actor, null, v_corr, p_warehouse_id, null, '', p_device_id,
                                             null, jsonb_build_object('scan_id', v_scan, 'shipment_id', v_ship), 'scan');
    elsif p_purpose = 'move' then
      insert into logistics.parcel_movement (parcel_id, from_warehouse_id, from_location_id, to_warehouse_id, to_location_id, moved_by, reason, scan_id, correlation_id)
      values (v_parcel.id, v_parcel.current_warehouse_id, v_parcel.current_location_id, p_warehouse_id, p_location_id, p_actor,
              case when v_loc.kind in ('quarantine', 'damaged') then 'quarantine' else 'move' end, v_scan, v_corr);
      update logistics.parcel set current_warehouse_id = p_warehouse_id, current_location_id = p_location_id, current_location = v_loc.code where id = v_parcel.id;
      insert into logistics.tracking_event (parcel_id, event_type, from_status, to_status, occurred_at, actor_user_id, actor_label, warehouse_id, location_id,
                                            location_text, device_id, source, metadata, correlation_id)
      values (v_parcel.id, 'ParcelMoved', v_parcel.status, v_parcel.status, now(), p_actor, v_label, p_warehouse_id, p_location_id, v_loc.code, p_device_id,
              'scan', jsonb_build_object('scan_id', v_scan, 'from_location_id', v_parcel.current_location_id), v_corr)
      returning id into v_te;
      insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_user_id, actor_label, payload)
      values ('ParcelMoved', 'parcel', v_parcel.id::text, v_corr, p_actor, v_label,
              jsonb_build_object('parcel_id', v_parcel.id, 'tracking_number', v_parcel.tracking_number, 'to_location', v_loc.code, 'tracking_event_id', v_te));
    end if;
    -- verify, dispatch, lookup, inventory : le scan IDENTIFIE ou CONSTATE ; l'acte suit (inspection, expédition).
    if v_trans is not null then v_te := (v_trans ->> 'tracking_event_id')::bigint; end if;
    if v_te is not null then update logistics.scan set tracking_event_id = v_te where id = v_scan; end if;
  else
    -- Un refus laisse une trace d'incident quand il signale un vrai problème, une seule fois par code et par entrepôt.
    if v_result in ('UNKNOWN_PARCEL', 'INVALID_CODE', 'PROHIBITED')
       and not exists (select 1 from logistics.incident i join logistics.scan s on s.id = i.scan_id
                       where i.status in ('OPEN', 'IN_PROGRESS') and s.scanned_code = left(p_code, 500) and s.warehouse_id = p_warehouse_id
                         and i.type = case v_result when 'UNKNOWN_PARCEL' then 'UNKNOWN_PARCEL' when 'INVALID_CODE' then 'FORGED_LABEL' else 'PROHIBITED_ITEM' end) then
      v_incident := logistics.report_incident(case v_result when 'UNKNOWN_PARCEL' then 'UNKNOWN_PARCEL' when 'INVALID_CODE' then 'FORGED_LABEL' else 'PROHIBITED_ITEM' end,
                      v_parcel.id, p_actor,
                      case v_result when 'UNKNOWN_PARCEL' then 'Code lu inconnu : ' || left(p_code, 80)
                                    when 'INVALID_CODE' then 'Numéro connu mais jeton faux : étiquette douteuse.'
                                    else 'Colis marqué interdit présenté au scan.' end,
                      case when v_result = 'UNKNOWN_PARCEL' then 'MEDIUM' else 'HIGH' end, p_warehouse_id, v_scan, v_corr);
    end if;
    insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_user_id, actor_label, payload)
    values ('ScanRejected', 'scan', v_scan::text, v_corr, p_actor, v_label,
            jsonb_build_object('scan_id', v_scan, 'result', v_result, 'purpose', p_purpose, 'warehouse_id', p_warehouse_id, 'parcel_id', v_parcel.id));
  end if;

  select * into v_parcel from logistics.parcel where id = v_parcel.id;
  v_out := jsonb_build_object('scan_id', v_scan, 'result', v_result, 'accepted', v_result = 'ACCEPTED', 'purpose', p_purpose,
                              'parcel_id', v_parcel.id, 'tracking_number', coalesce(v_parcel.tracking_number, v_code ->> 'number'),
                              'status', v_parcel.status, 'warnings', to_jsonb(v_warnings), 'incident_id', v_incident,
                              'correlation_id', v_corr, 'replayed', false);
  if p_idempotency_key is not null then
    update logistics.command_log set result = v_out where idempotency_key = p_idempotency_key;
  end if;
  return v_out;
end;
$$;


-- 5. Trouver un colis, faire l'inventaire ----------------------------------------------------------------------------
-- Où est ce colis ? Par son numéro, son QR ou ce qu'un opérateur tape ; lecture seule, droit « colis.lire ».
create or replace function logistics.locate_parcel(p_actor uuid, p_code text)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_code jsonb; v_p logistics.parcel;
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_code := logistics.parse_code(p_code);
  select * into v_p from logistics.parcel where tracking_number = v_code ->> 'number';
  if not found then
    return jsonb_build_object('found', false, 'tracking_number', v_code ->> 'number');
  end if;
  return jsonb_build_object(
    'found', true, 'tracking_number', v_p.tracking_number, 'status', v_p.status,
    'business_status', (select business_name from logistics.parcel_status where code = v_p.status),
    'warehouse', (select jsonb_build_object('id', w.id, 'code', w.code, 'name', w.name) from logistics.warehouse w where w.id = v_p.current_warehouse_id),
    'location', (select jsonb_build_object('id', l.id, 'code', l.code, 'zone', z.code, 'zone_kind', z.kind)
                   from logistics.warehouse_location l left join logistics.warehouse_zone z on z.id = l.zone_id where l.id = v_p.current_location_id),
    'location_text', v_p.current_location,
    'last_scan', (select jsonb_build_object('at', s.scanned_at, 'purpose', s.purpose, 'result', s.result)
                    from logistics.scan s where s.parcel_id = v_p.id order by s.scanned_at desc limit 1),
    'last_inventory_at', (select max(s.scanned_at) from logistics.scan s where s.parcel_id = v_p.id and s.purpose = 'inventory' and s.result = 'ACCEPTED'));
end;
$$;

-- L'inventaire d'un entrepôt (ou d'un emplacement) : chaque colis que le système y croit, son emplacement, et s'il a
-- été vu au scan d'inventaire depuis p_since. Ceux qui ne l'ont pas été sont « à chercher ».
create or replace function logistics.warehouse_inventory(p_actor uuid, p_warehouse_id uuid, p_location_id uuid default null,
                                                         p_since timestamptz default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_since timestamptz := coalesce(p_since, now() - interval '24 hours');
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  if not exists (select 1 from logistics.warehouse where id = p_warehouse_id) then
    raise exception 'Entrepôt inconnu.' using errcode = 'LG002';
  end if;
  return (
    with attendus as (
      select p.id, p.tracking_number, p.status, l.code as location,
             (select max(s.scanned_at) from logistics.scan s
               where s.parcel_id = p.id and s.purpose = 'inventory' and s.result = 'ACCEPTED' and s.scanned_at >= v_since) as seen_at
        from logistics.parcel p left join logistics.warehouse_location l on l.id = p.current_location_id
       where p.current_warehouse_id = p_warehouse_id
         and p.status in ('RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'LOADED', 'ON_HOLD', 'DAMAGED')
         and (p_location_id is null or p.current_location_id = p_location_id)
    )
    select jsonb_build_object(
      'warehouse_id', p_warehouse_id, 'location_id', p_location_id, 'since', v_since,
      'expected', (select count(*) from attendus),
      'seen', (select count(*) from attendus where seen_at is not null),
      'missing', (select count(*) from attendus where seen_at is null),
      'parcels', coalesce((select jsonb_agg(jsonb_build_object('tracking_number', a.tracking_number, 'status', a.status, 'location', a.location,
                                                               'seen_at', a.seen_at) order by a.location nulls last, a.tracking_number) from attendus a), '[]'::jsonb))
  );
end;
$$;

create or replace function public.lg_locate_parcel(p_code text)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.locate_parcel(auth.uid(), p_code) $$;
create or replace function public.lg_warehouse_inventory(p_warehouse_id uuid, p_location_id uuid default null, p_since timestamptz default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.warehouse_inventory(auth.uid(), p_warehouse_id, p_location_id, p_since) $$;


-- 6. L'expédition et ses colis chargés --------------------------------------------------------------------------------
create or replace function logistics.cascade_parcels(p_shipment_id uuid, p_from text, p_to text, p_actor uuid, p_corr uuid, p_warehouse uuid default null)
returns jsonb language plpgsql volatile set search_path = '' as $$
declare r record; v_done int := 0; v_skipped jsonb := '[]'::jsonb; v_charges int := 0; v_sans_scan int := 0;
begin
  for r in select p.id, p.status, p.tracking_number from logistics.parcel p where p.id in (select parcel_id from logistics.shipment_parcels(p_shipment_id)) order by p.tracking_number loop
    if r.status = p_from then
      perform logistics.transition_parcel(r.id, p_to, p_actor, null, p_corr, p_warehouse, null, '', null, null,
                                          jsonb_build_object('shipment_id', p_shipment_id), 'api');
      v_done := v_done + 1;
      if p_from = 'READY_FOR_EXPORT' and p_to = 'IN_TRANSIT' then v_sans_scan := v_sans_scan + 1; end if;
    elsif r.status = 'LOADED' and p_from = 'READY_FOR_EXPORT' then
      -- Un colis CHARGÉ part avec son expédition ; si elle est rouverte ou annulée, il est d'abord déchargé.
      if p_to = 'IN_TRANSIT' then
        perform logistics.transition_parcel(r.id, 'IN_TRANSIT', p_actor, null, p_corr, p_warehouse, null, '', null, null,
                                            jsonb_build_object('shipment_id', p_shipment_id), 'api');
        v_charges := v_charges + 1;
      else
        perform logistics.transition_parcel(r.id, 'READY_FOR_EXPORT', p_actor, null, p_corr, p_warehouse, null, '', null,
                                            'Expédition rouverte ou annulée : colis déchargé', jsonb_build_object('shipment_id', p_shipment_id), 'api');
        perform logistics.transition_parcel(r.id, p_to, p_actor, null, p_corr, p_warehouse, null, '', null, null,
                                            jsonb_build_object('shipment_id', p_shipment_id), 'api');
      end if;
      v_done := v_done + 1;
    else
      v_skipped := v_skipped || jsonb_build_object('tracking_number', r.tracking_number, 'status', r.status);
    end if;
  end loop;
  return jsonb_build_object('moved', v_done, 'skipped', v_skipped, 'loaded', v_charges, 'not_scanned_at_loading', v_sans_scan);
end;
$$;


-- 7. La mission échouée, replanifiée, annulée ---------------------------------------------------------------------------
create or replace function logistics.fail_task(p_task_id uuid, p_actor uuid, p_incident_type text, p_description text default '', p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_d uuid := logistics.require_driver_of_task(p_actor, p_task_id); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; v_inc uuid; r record;
begin
  if p_incident_type not in ('CUSTOMER_ABSENT', 'WRONG_ADDRESS', 'DAMAGED', 'REFUSED', 'VEHICLE_PROBLEM', 'PAYMENT_PROBLEM', 'OTHER') then
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

create or replace function logistics.reschedule_task(p_task_id uuid, p_actor uuid, p_new_date date, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; r record;
begin
  perform logistics.require_right(p_actor);
  if p_new_date is null then raise exception 'Une nouvelle date est obligatoire.' using errcode = 'LG005'; end if;
  select * into v_t from logistics.task where id = p_task_id for update;
  if v_t.status <> 'FAILED' then raise exception 'Seule une mission ÉCHOUÉE se replanifie (elle est %).', v_t.status using errcode = 'LG001'; end if;
  update logistics.task set driver_id = null, scheduled_date = p_new_date, failed_reason = null, trip_id = null where id = p_task_id;
  perform logistics.move_task(p_task_id, 'CREATED', p_actor, v_corr, 'replanifiée', jsonb_build_object('new_date', p_new_date));
  if v_t.kind = 'DELIVERY' then
    update logistics.delivery set scheduled_for = p_new_date where id = v_t.delivery_id;
    for r in select dp.parcel_id from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id
              where dp.delivery_id = v_t.delivery_id and p.status in ('FAILED_DELIVERY', 'AT_DESTINATION_HUB') order by dp.parcel_id loop
      perform logistics.transition_parcel(r.parcel_id, 'DELIVERY_ASSIGNED', p_actor, null, v_corr, null, null, '', null, null, jsonb_build_object('rescheduled', true), 'api');
    end loop;
  end if;
  return jsonb_build_object('task_id', p_task_id, 'status', 'CREATED', 'scheduled_date', p_new_date, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.cancel_task(p_task_id uuid, p_actor uuid, p_reason text, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_t logistics.task; r record;
begin
  perform logistics.require_right(p_actor, 'direction');
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


-- 8. Ce que voit le client ---------------------------------------------------------------------------------------------
create or replace function logistics.customer_stage(p_status text)
returns text language sql immutable set search_path = '' as $$
  select case p_status
    when 'CREATED' then 'registered'
    when 'RECEIVED' then 'received' when 'VERIFIED' then 'received' when 'STORED' then 'received'
    when 'CONSOLIDATION_PENDING' then 'received' when 'CONSOLIDATED' then 'received' when 'READY_FOR_EXPORT' then 'received'
    when 'LOADED' then 'received'
    when 'IN_TRANSIT' then 'in_transit'
    when 'ARRIVED' then 'customs' when 'CUSTOMS_PROCESSING' then 'customs' when 'CUSTOMS_CLEARED' then 'customs'
    when 'AT_DESTINATION_HUB' then 'at_hub'
    when 'DELIVERY_ASSIGNED' then 'out_for_delivery' when 'OUT_FOR_DELIVERY' then 'out_for_delivery'
    when 'DELIVERED' then 'delivered'
    when 'ON_HOLD' then 'on_hold' when 'DAMAGED' then 'incident' when 'LOST' then 'lost'
    when 'CANCELLED' then 'cancelled' when 'RETURNED' then 'returned'
    when 'FAILED_DELIVERY' then 'incident'
  end
$$;


-- 9. La façade accepte le nom métier d'un statut -------------------------------------------------------------------------
create or replace function public.lg_transition_parcel(
  p_parcel_id       uuid,
  p_to_status       text,
  p_idempotency_key text  default null,
  p_correlation_id  uuid  default null,
  p_warehouse_id    uuid  default null,
  p_location_id     uuid  default null,
  p_location_text   text  default '',
  p_reason          text  default null,
  p_metadata        jsonb default '{}'::jsonb)
returns jsonb
language plpgsql volatile security definer set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'Connexion requise.' using errcode = '42501';
  end if;
  perform logistics.require_staff(auth.uid());
  -- L'acteur est TOUJOURS le compte connecté : il ne se passe jamais en paramètre. Le statut se donne par son code ou par
  -- son nom métier (READY_FOR_SHIPMENT, CLEARED…) ; un nom inconnu reste refusé par la machine.
  return logistics.transition_parcel(p_parcel_id, coalesce(logistics.status_code(p_to_status), p_to_status), auth.uid(), p_idempotency_key,
                                     p_correlation_id, p_warehouse_id, p_location_id, p_location_text, null, p_reason, p_metadata, 'api');
end;
$$;


-- 10. Tout reste fermé, sauf les façades ---------------------------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('status_code', 'parcel_open_shipment', 'parcel_coherence_issue', 'check_parcel_coherence',
              'check_task_coherence', 'workflow_inconsistencies', 'assess_scan', 'scan_parcel', 'locate_parcel', 'warehouse_inventory', 'cascade_parcels',
              'fail_task', 'reschedule_task', 'cancel_task', 'customer_stage') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
end
$$;
revoke all on function public.lg_locate_parcel(text) from public, anon;
revoke all on function public.lg_warehouse_inventory(uuid, uuid, timestamptz) from public, anon;
grant execute on function public.lg_locate_parcel(text) to authenticated;
grant execute on function public.lg_warehouse_inventory(uuid, uuid, timestamptz) to authenticated;
revoke all on function public.lg_transition_parcel(uuid, text, text, uuid, uuid, uuid, text, text, jsonb) from public, anon;
grant execute on function public.lg_transition_parcel(uuid, text, text, uuid, uuid, uuid, text, text, jsonb) to authenticated;
