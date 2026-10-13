-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 19 : le tableau de bord, centre de commande
-- -----------------------------------------------------------------------------
-- Phase 7. À coller dans Supabase > SQL Editor APRÈS 018, d'abord en PRÉPRODUCTION,
-- puis en production après une sauvegarde « avant migration » vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site » (ou la préproduction).
--
-- Ce que le tableau de bord lit, décidé et compté ICI :
--   1. les MODULES qu'un compte peut ouvrir (dashboard_access) : administrateur tout ; gérant les opérations, la clientèle, la
--      facturation ; employé ses droits cochés ; chauffeur SES missions, SES tournées, SON pointage ; client rien ;
--   2. la vue TEMPS RÉEL du centre de commande (command_cards) : colis à traiter, scans récents, arrivages, départs, douane,
--      livraisons du jour, retards, incidents, paiements en attente, tâches, alertes — chaque carte nomme le module qu'elle ouvre ;
--   3. les listes qui manquaient : véhicules, tournées, dépenses ;
--   4. le POINTAGE EXPRESS : (a) le pointage des COLIS contre une liste attendue (arrivage, chargement, inventaire, liste libre) —
--      attendus, pointés, manquants, en trop, inconnus ; (b) le pointage du PERSONNEL — arrivée, pause, reprise, départ ; heures
--      travaillées et anomalies calculées par la base ; corrections par la direction, motivées, en ajout seul.
--
-- Le navigateur ne compte rien : il affiche. Rejouable sans risque ; aucune donnée supprimée. Aucune fonction redéfinie.
-- Retour arrière : docs/architecture/TABLEAU-DE-BORD.md §8.
-- =============================================================================

-- 1. Le vocabulaire ------------------------------------------------------------------------------------------------
do $$
declare v_types text[]; v_def text;
begin
  select pg_get_constraintdef(c.oid) into v_def from pg_constraint c where c.conrelid = 'logistics.event_type'::regclass and c.conname = 'event_type_aggregate_type_check';
  select array_agg(distinct x order by x) into v_types
    from (select m[1] as x from regexp_matches(coalesce(v_def, ''), '''([a-z_]+)''', 'g') m
          union select btrim(y) from unnest(string_to_array(substring(coalesce(v_def, '') from '\{([^}]*)\}'), ',')) y
          union select aggregate_type from logistics.event_type union select unnest(array['tally', 'staff'])) t;
  alter table logistics.event_type drop constraint if exists event_type_aggregate_type_check;
  execute format('alter table logistics.event_type add constraint event_type_aggregate_type_check check (aggregate_type = any (%L::text[]))', v_types);
end
$$;
insert into logistics.event_type (code, aggregate_type, description) values
  ('TallyOpened',         'tally', 'Pointage de colis ouvert (liste attendue figée)'),
  ('TallyClosed',         'tally', 'Pointage de colis clos : attendus, pointés, manquants, en trop'),
  ('StaffClocked',        'staff', 'Pointage du personnel : arrivée, pause, reprise ou départ'),
  ('StaffClockCorrected', 'staff', 'Pointage du personnel corrigé par la direction')
on conflict (code) do nothing;


-- 2. Le pointage des colis ------------------------------------------------------------------------------------------
create table if not exists logistics.tally_session (
  id             uuid primary key default gen_random_uuid(),
  number         text not null unique,
  kind           text not null check (kind in ('ARRIVAL', 'LOADING', 'INVENTORY', 'OTHER')),
  source_type    text not null check (source_type in ('shipment', 'consolidation', 'warehouse', 'list')),
  source_id      uuid,
  source_label   text not null default '',
  status         text not null default 'OPEN' check (status in ('OPEN', 'CLOSED')),
  opened_by      uuid references logistics.app_user (id) on delete restrict,
  opened_at      timestamptz not null default now(),
  closed_by      uuid references logistics.app_user (id) on delete restrict,
  closed_at      timestamptz,
  note           text not null default '',
  summary        jsonb,
  correlation_id uuid not null,
  check ((status = 'CLOSED') = (closed_at is not null)),
  check ((source_type = 'list') = (source_id is null))
);
comment on table logistics.tally_session is 'Pointage Express des colis : une liste attendue figée à l''ouverture, des lectures, un bilan à la clôture.';

create table if not exists logistics.tally_line (
  id              bigint generated always as identity primary key,
  session_id      uuid not null references logistics.tally_session (id) on delete restrict,
  tracking_number text not null,
  parcel_id       uuid references logistics.parcel (id) on delete restrict,
  expected        boolean not null,
  checked_at      timestamptz,
  checked_by      uuid references logistics.app_user (id) on delete restrict,
  code_kind       text,
  unique (session_id, tracking_number),
  check (expected or checked_at is not null)
);

-- Une ligne ne change qu'UNE fois (le pointage d'un attendu), et plus rien après la clôture.
create or replace function logistics.guard_tally()
returns trigger language plpgsql set search_path = '' as $$
declare v_st text;
begin
  if tg_op = 'DELETE' then raise exception 'Un pointage ne se supprime pas.' using errcode = 'LG004'; end if;
  if tg_table_name = 'tally_line' then
    select status into v_st from logistics.tally_session where id = coalesce(new.session_id, old.session_id);
    if v_st = 'CLOSED' then raise exception 'Pointage clos : il ne change plus.' using errcode = 'LG004'; end if;
    if tg_op = 'UPDATE' and (old.checked_at is not null or (new.session_id, new.tracking_number, new.parcel_id, new.expected) is distinct from (old.session_id, old.tracking_number, old.parcel_id, old.expected)) then
      raise exception 'Une ligne de pointage ne se pointe qu''une fois.' using errcode = 'LG004';
    end if;
  elsif tg_op = 'UPDATE' then
    if old.status = 'CLOSED' then raise exception 'Pointage clos : il ne change plus.' using errcode = 'LG004'; end if;
    if (new.number, new.kind, new.source_type, new.source_id, new.opened_by, new.opened_at) is distinct from (old.number, old.kind, old.source_type, old.source_id, old.opened_by, old.opened_at) then
      raise exception 'L''en-tête d''un pointage est figé.' using errcode = 'LG004';
    end if;
  end if;
  return new;
end;
$$;
drop trigger if exists guard_tally_session on logistics.tally_session;
create trigger guard_tally_session before update or delete on logistics.tally_session for each row execute function logistics.guard_tally();
drop trigger if exists guard_tally_line on logistics.tally_line;
create trigger guard_tally_line before insert or update or delete on logistics.tally_line for each row execute function logistics.guard_tally();


-- 3. Le pointage du personnel ----------------------------------------------------------------------------------------
-- Ajout seul. Une correction de la direction est un événement de plus (source CORRECTION, motif), jamais une réécriture.
create table if not exists logistics.staff_clock_event (
  id             bigint generated always as identity primary key,
  user_id        uuid not null references logistics.app_user (id) on delete restrict,
  kind           text not null check (kind in ('IN', 'BREAK_START', 'BREAK_END', 'OUT')),
  occurred_at    timestamptz not null default now(),
  source         text not null default 'WEB' check (source in ('WEB', 'APP', 'CORRECTION')),
  note           text not null default '' check (length(note) <= 500),
  recorded_by    uuid references logistics.app_user (id) on delete restrict,
  reason         text,
  correlation_id uuid not null,
  check ((source = 'CORRECTION') = (reason is not null and btrim(reason) <> ''))
);
create index if not exists staff_clock_user_idx on logistics.staff_clock_event (user_id, occurred_at);
drop trigger if exists staff_clock_append_only on logistics.staff_clock_event;
create trigger staff_clock_append_only before update or delete on logistics.staff_clock_event for each row execute function logistics.forbid_mutation();

do $$
declare t text;
begin
  foreach t in array array['tally_session', 'tally_line', 'staff_clock_event'] loop
    execute format('revoke all on logistics.%I from public, anon, authenticated', t);
    execute format('alter table logistics.%I enable row level security', t);
  end loop;
end
$$;


-- 4. Les modules qu'un compte peut ouvrir -------------------------------------------------------------------------------
-- La règle des rôles vit ici (et dans actor_can) : le site ne fait que cacher ce qu'on lui dit de cacher. Chaque fonction de
-- chaque module revérifie ses droits à chaque appel.
create or replace function logistics.dashboard_access(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  u logistics.app_user; v_ops boolean; v_stat boolean; v_fin boolean; v_cli boolean; v_dir boolean; v_roles boolean; v_drv boolean; v_any boolean; m text[] := '{}';
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  select * into u from logistics.app_user where id = p_actor and active;
  if not found then
    -- Un client (ou un compte désactivé) : jamais le tableau de bord opérationnel.
    return jsonb_build_object('staff', false, 'modules', '[]'::jsonb);
  end if;
  v_ops := logistics.actor_can(p_actor, 'colis.lire'); v_stat := logistics.actor_can(p_actor, 'colis.statut');
  v_fin := logistics.actor_can(p_actor, 'factures.lire'); v_cli := logistics.actor_can(p_actor, 'clients.lire');
  v_dir := logistics.actor_can(p_actor, 'direction'); v_roles := v_dir or 'roles.gerer' = any (u.rights);
  v_drv := logistics.driver_of(p_actor) is not null;
  v_any := v_ops or v_fin or v_cli or v_dir;
  if v_any then m := m || array['vue-generale', 'commande']; end if;
  if v_ops then m := m || array['colis', 'prealertes']; end if;
  if v_stat then m := m || 'scanner'::text; end if;
  if v_ops then m := m || array['entrepots', 'consolidations', 'expeditions', 'transport', 'douane']; end if;
  if v_ops or v_drv then m := m || 'livraisons'::text; end if;
  if v_ops then m := m || array['chauffeurs', 'vehicules']; end if;
  if v_ops or v_drv then m := m || 'tournees'::text; end if;
  if v_ops then m := m || 'incidents'::text; end if;
  if v_cli then m := m || 'clients'::text; end if;
  if v_fin then m := m || array['factures', 'encaissements', 'depenses']; end if;
  if v_any then m := m || 'rapports'::text; end if;
  if v_dir then m := m || 'analytique'::text; end if;
  if v_ops then m := m || 'notifications'::text; end if;
  if v_roles then m := m || 'equipe'::text; end if;
  m := m || array['pointage', 'parametres'];
  if v_dir then m := m || 'sante'::text; end if;
  return jsonb_build_object('staff', true, 'role', u.role, 'driver', v_drv, 'driver_only', v_drv and not v_any, 'direction', v_dir,
                            'can', jsonb_build_object('ops', v_ops, 'status', v_stat, 'finance', v_fin, 'customers', v_cli, 'roles', v_roles),
                            'modules', to_jsonb(m), 'today', logistics.today());
end;
$$;


-- 5. Le centre de commande : la vue temps réel ---------------------------------------------------------------------------
-- Une carte = { key, module (ce qu'elle ouvre), count, severity (ok, info, warn, bad), detail, items }. Une carte n'est rendue
-- qu'à qui a le droit de la lire. Tout est compté ici ; l'écran se relit à chaque signal temps réel.
create or replace function logistics.command_cards(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  a jsonb := logistics.dashboard_access(p_actor); v_ops boolean; v_fin boolean; v_dir boolean; v_drv uuid; v_cli boolean;
  v_day date := logistics.today(); v_d0 timestamptz; v_d1 timestamptz; c jsonb := '[]'::jsonb; v_n int; v_x jsonb; v_items jsonb; v_m int;
begin
  if not (a ->> 'staff')::boolean then raise exception 'Réservé à l''équipe.' using errcode = 'LG003'; end if;
  v_ops := (a -> 'can' ->> 'ops')::boolean; v_fin := (a -> 'can' ->> 'finance')::boolean; v_dir := (a ->> 'direction')::boolean;
  v_cli := (a -> 'can' ->> 'customers')::boolean; v_drv := logistics.driver_of(p_actor);
  v_d0 := logistics.day_start(v_day); v_d1 := logistics.day_start(v_day + 1);

  if v_ops then
    -- colis à traiter : reçus à vérifier, vérifiés à ranger, en attente ; demandes de clients à examiner
    select jsonb_build_object('received', count(*) filter (where status = 'RECEIVED'), 'verified', count(*) filter (where status = 'VERIFIED'),
                              'on_hold', count(*) filter (where status = 'ON_HOLD')) into v_x
      from logistics.parcel where status in ('RECEIVED', 'VERIFIED', 'ON_HOLD');
    v_x := v_x || jsonb_build_object('pickup_requests', (select count(*) from logistics.pickup_request where status = 'REQUESTED'),
                                     'delivery_requests', (select count(*) from logistics.delivery_request where status = 'REQUESTED'));
    select coalesce(jsonb_agg(jsonb_build_object('tracking_number', z.tracking_number, 'status', z.status, 'since', z.updated_at) order by z.updated_at), '[]'::jsonb) into v_items
      from (select tracking_number, status, updated_at from logistics.parcel where status in ('RECEIVED', 'VERIFIED', 'ON_HOLD') order by updated_at limit 5) z;
    v_n := (v_x ->> 'received')::int + (v_x ->> 'verified')::int + (v_x ->> 'on_hold')::int + (v_x ->> 'pickup_requests')::int + (v_x ->> 'delivery_requests')::int;
    c := c || jsonb_build_object('key', 'to_process', 'module', 'colis', 'count', v_n, 'severity', case when (v_x ->> 'on_hold')::int > 0 then 'warn' when v_n > 0 then 'info' else 'ok' end,
                                 'detail', v_x, 'items', v_items);

    -- scans récents
    select jsonb_build_object('last_hour', count(*) filter (where scanned_at >= now() - interval '1 hour'),
                              'today', count(*) filter (where scanned_at >= v_d0),
                              'refused_today', count(*) filter (where scanned_at >= v_d0 and result not in ('ACCEPTED', 'DUPLICATE'))) into v_x
      from logistics.scan where scanned_at >= least(v_d0, now() - interval '1 hour');
    select coalesce(jsonb_agg(jsonb_build_object('code', z.scanned_code, 'purpose', z.purpose, 'result', z.result, 'at', z.scanned_at) order by z.scanned_at desc), '[]'::jsonb) into v_items
      from (select scanned_code, purpose, result, scanned_at from logistics.scan order by scanned_at desc, id desc limit 6) z;
    c := c || jsonb_build_object('key', 'scans', 'module', 'scanner', 'count', (v_x ->> 'last_hour')::int,
                                 'severity', case when (v_x ->> 'refused_today')::int > 0 then 'warn' else 'ok' end, 'detail', v_x, 'items', v_items);

    -- arrivages : arrivés aujourd'hui, attendus aujourd'hui
    select jsonb_build_object(
             'arrived_today', count(*) filter (where s.arrived_at >= v_d0 and s.arrived_at < v_d1),
             'expected_today', count(*) filter (where s.status in ('DISPATCHED', 'IN_TRANSIT') and coalesce(s.planned_arrival_at, t.planned_arrival_at) < v_d1
                                                      and coalesce(s.planned_arrival_at, t.planned_arrival_at) >= v_d0),
             'at_hub_today', count(*) filter (where s.status = 'AT_HUB' and s.arrived_at >= v_d0)) into v_x
      from logistics.shipment s left join logistics.transport t on t.id = s.transport_id;
    select coalesce(jsonb_agg(jsonb_build_object('code', z.code, 'status', z.status, 'at', z.at) order by z.at), '[]'::jsonb) into v_items
      from (select s.code, s.status, coalesce(s.arrived_at, s.planned_arrival_at, t.planned_arrival_at) as at from logistics.shipment s left join logistics.transport t on t.id = s.transport_id
             where (s.arrived_at >= v_d0 and s.arrived_at < v_d1) or (s.status in ('DISPATCHED', 'IN_TRANSIT') and coalesce(s.planned_arrival_at, t.planned_arrival_at) >= v_d0
                                                                      and coalesce(s.planned_arrival_at, t.planned_arrival_at) < v_d1)
             order by 3 limit 5) z;
    c := c || jsonb_build_object('key', 'arrivals', 'module', 'expeditions', 'count', (v_x ->> 'arrived_today')::int + (v_x ->> 'expected_today')::int,
                                 'severity', 'info', 'detail', v_x, 'items', v_items);

    -- départs : prêtes à partir, parties aujourd'hui, transports prévus aujourd'hui
    select jsonb_build_object('ready', (select count(*) from logistics.shipment where status = 'READY'),
                              'dispatched_today', (select count(*) from logistics.shipment where dispatched_at >= v_d0 and dispatched_at < v_d1),
                              'transports_today', (select count(*) from logistics.transport where status = 'PLANNED' and planned_departure_at >= v_d0 and planned_departure_at < v_d1)) into v_x;
    select coalesce(jsonb_agg(jsonb_build_object('code', z.code, 'status', z.status, 'mode', z.mode) order by z.code), '[]'::jsonb) into v_items
      from (select code, status, mode from logistics.shipment where status = 'READY' order by created_at limit 5) z;
    c := c || jsonb_build_object('key', 'departures', 'module', 'transport', 'count', (v_x ->> 'ready')::int + (v_x ->> 'dispatched_today')::int,
                                 'severity', 'info', 'detail', v_x, 'items', v_items);

    -- douane
    select jsonb_build_object('arrived', count(*) filter (where status = 'ARRIVED'), 'processing', count(*) filter (where status = 'CUSTOMS_PROCESSING')) into v_x
      from logistics.shipment where status in ('ARRIVED', 'CUSTOMS_PROCESSING');
    v_x := v_x || jsonb_build_object('open_exceptions', (select count(*) from logistics.customs_exception where status = 'OPEN'),
                                     'duties_unpaid', (select count(*) from logistics.customs_declaration where status in ('SUBMITTED', 'UNDER_REVIEW') and duties_amount is not null and duties_paid_at is null));
    c := c || jsonb_build_object('key', 'customs', 'module', 'douane', 'count', (v_x ->> 'arrived')::int + (v_x ->> 'processing')::int,
                                 'severity', case when (v_x ->> 'open_exceptions')::int > 0 then 'warn' else 'info' end, 'detail', v_x, 'items', '[]'::jsonb);
  end if;

  if v_ops or v_drv is not null then
    -- livraisons du jour (le chauffeur : les siennes)
    select jsonb_build_object('total', count(*) filter (where t.status <> 'CANCELLED'), 'completed', count(*) filter (where t.status = 'COMPLETED'),
                              'in_progress', count(*) filter (where t.status = 'STARTED'), 'failed', count(*) filter (where t.status = 'FAILED'),
                              'unassigned', count(*) filter (where t.status = 'CREATED')) into v_x
      from logistics.task t where t.scheduled_date = v_day and (v_ops or t.driver_id = v_drv);
    c := c || jsonb_build_object('key', 'deliveries_today', 'module', 'livraisons', 'count', (v_x ->> 'total')::int,
                                 'severity', case when (v_x ->> 'failed')::int > 0 then 'warn' else 'ok' end, 'detail', v_x, 'items', '[]'::jsonb);
    -- retards
    select jsonb_build_object('deliveries', count(*)) into v_x from logistics.task t
     where t.status in ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED') and coalesce(t.window_end, logistics.day_start(t.scheduled_date + 1)) < now() and (v_ops or t.driver_id = v_drv);
    if v_ops then
      v_x := v_x || jsonb_build_object('shipments', (select count(*) from logistics.shipment s left join logistics.transport tr on tr.id = s.transport_id
                                                      where s.status in ('DISPATCHED', 'IN_TRANSIT') and coalesce(s.planned_arrival_at, tr.planned_arrival_at) < now()));
    else v_x := v_x || jsonb_build_object('shipments', 0); end if;
    v_n := (v_x ->> 'deliveries')::int + (v_x ->> 'shipments')::int;
    c := c || jsonb_build_object('key', 'delays', 'module', case when (v_x ->> 'deliveries')::int > 0 or not v_ops then 'livraisons' else 'expeditions' end, 'count', v_n,
                                 'severity', case when v_n > 0 then 'bad' else 'ok' end, 'detail', v_x, 'items', '[]'::jsonb);
  end if;

  if v_ops then
    select jsonb_build_object('open', count(*), 'high', count(*) filter (where severity = 'HIGH'), 'today', count(*) filter (where created_at >= v_d0)) into v_x
      from logistics.incident where status in ('OPEN', 'IN_PROGRESS');
    c := c || jsonb_build_object('key', 'incidents', 'module', 'incidents', 'count', (v_x ->> 'open')::int,
                                 'severity', case when (v_x ->> 'high')::int > 0 then 'bad' when (v_x ->> 'open')::int > 0 then 'warn' else 'ok' end, 'detail', v_x, 'items', '[]'::jsonb);
  end if;

  if v_fin then
    -- paiements en attente : factures du moteur non soldées (par devise), en retard, paiements en ligne en cours, écarts à examiner
    select jsonb_build_object('unpaid', count(*), 'overdue', count(*) filter (where i.status = 'OVERDUE'),
                              'balances', coalesce((select jsonb_agg(jsonb_build_object('currency', x.currency, 'balance', x.s) order by x.currency)
                                                      from (select i2.currency, sum(logistics.invoice_balance(i2)) s from logistics.invoice i2 where logistics.cc_unpaid(i2) group by i2.currency) x), '[]'::jsonb)) into v_x
      from logistics.invoice i where logistics.cc_unpaid(i);
    v_x := v_x || jsonb_build_object('online_pending', (select count(*) from logistics.payment_intent where status = 'PENDING'),
                                     'to_review', (select count(*) from logistics.payment_reconciliation() r where r.blocking));
    c := c || jsonb_build_object('key', 'payments_pending', 'module', 'encaissements', 'count', (v_x ->> 'unpaid')::int,
                                 'severity', case when (v_x ->> 'overdue')::int > 0 or (v_x ->> 'to_review')::int > 0 then 'warn' else 'info' end, 'detail', v_x, 'items', '[]'::jsonb);
  end if;

  -- tâches : ce qui attend une personne (missions sans chauffeur, pointages ouverts, tickets, ma journée)
  v_x := jsonb_build_object(
    'unassigned_tasks', case when v_ops then (select count(*) from logistics.task where status = 'CREATED' and scheduled_date <= v_day) else 0 end,
    'open_tallies', (select count(*) from logistics.tally_session where status = 'OPEN' and (v_ops or opened_by = p_actor)),
    'tickets_waiting', case when v_cli then (select count(*) from logistics.support_ticket where status = 'OPEN') else 0 end,
    'my_missions', case when v_drv is not null then (select count(*) from logistics.task where driver_id = v_drv and status in ('ASSIGNED', 'ACCEPTED', 'STARTED')) else 0 end,
    'clocked_in', logistics.clock_state(p_actor, now()) in ('IN', 'BREAK_START'));
  v_n := (v_x ->> 'unassigned_tasks')::int + (v_x ->> 'open_tallies')::int + (v_x ->> 'tickets_waiting')::int + (v_x ->> 'my_missions')::int;
  c := c || jsonb_build_object('key', 'tasks', 'module', case when (v_x ->> 'my_missions')::int > 0 or (v_x ->> 'unassigned_tasks')::int > 0 then 'livraisons'
                                                             when (v_x ->> 'open_tallies')::int > 0 then 'pointage' when (v_x ->> 'tickets_waiting')::int > 0 then 'clients' else 'pointage' end,
                               'count', v_n, 'severity', case when v_n > 0 then 'info' else 'ok' end, 'detail', v_x, 'items', '[]'::jsonb);

  -- alertes : la file « à traiter » existante, et la santé du système pour la direction
  v_m := 0; v_items := '[]'::jsonb;
  if v_ops or v_fin or v_cli then
    v_items := coalesce((logistics.cc_attention(p_actor) -> 'items'), '[]'::jsonb);
    v_m := coalesce((select sum((x ->> 'count')::int) from jsonb_array_elements(v_items) x), 0);
  end if;
  v_x := jsonb_build_object('attention', v_m);
  if v_dir then
    begin
      v_x := v_x || jsonb_build_object('health', (select ops.status(p_actor) ->> 'overall'));
    exception when others then
      v_x := v_x || jsonb_build_object('health', null);
    end;
  else v_x := v_x || jsonb_build_object('health', null); end if;
  -- (une carte n'ouvre jamais un module que ce compte ne peut pas ouvrir : le chauffeur, sans centre de commande, va à ses livraisons)
  c := c || jsonb_build_object('key', 'alerts', 'module', case when v_dir and coalesce(v_x ->> 'health', 'OK') <> 'OK' then 'sante'
                                                              when (a -> 'modules') ? 'commande' then 'commande' else 'livraisons' end,
                               'count', v_m + case when coalesce(v_x ->> 'health', 'OK') <> 'OK' then 1 else 0 end,
                               'severity', case when v_x ->> 'health' = 'FAIL' then 'bad' when v_x ->> 'health' = 'WARN' or v_m > 0 then 'warn' else 'ok' end,
                               'detail', v_x, 'items', v_items);

  return jsonb_build_object('as_of', now(), 'today', v_day, 'cards', c, 'modules', a -> 'modules');
end;
$$;


-- 6. Les listes qui manquaient -------------------------------------------------------------------------------------------
create or replace function logistics.cc_vehicles(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_day date := logistics.today();
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  return jsonb_build_object('as_of', now(),
    'by_status', coalesce((select jsonb_object_agg(status, n) from (select status, count(*) n from logistics.vehicle group by status) x), '{}'::jsonb),
    'items', coalesce((select jsonb_agg(jsonb_build_object(
        'vehicle_id', v.id, 'plate', v.plate, 'kind', v.kind, 'status', v.status, 'status_reason', v.status_reason, 'capacity_lb', v.capacity_lb, 'capacity_ft3', v.capacity_ft3,
        'branch', logistics.branch_label(v.branch_id),
        'drivers', coalesce((select jsonb_agg(d.full_name order by d.full_name) from logistics.driver d where d.default_vehicle_id = v.id), '[]'::jsonb),
        'trip_today', (select jsonb_build_object('status', tr.status, 'stops', (select count(*) from logistics.stop s where s.trip_id = tr.id and s.status <> 'SKIPPED'))
                         from logistics.trip tr where tr.vehicle_id = v.id and tr.trip_date = v_day and tr.status <> 'CANCELLED' order by tr.status = 'STARTED' desc limit 1))
        order by (v.status = 'ACTIVE') desc, v.plate) from logistics.vehicle v), '[]'::jsonb));
end;
$$;

-- Les tournées d'un jour. Le chauffeur ne voit que les siennes.
create or replace function logistics.cc_trips(p_actor uuid, p_date date default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_day date := coalesce(p_date, logistics.today()); v_drv uuid := logistics.driver_of(p_actor); v_ops boolean := logistics.actor_can(p_actor, 'colis.lire');
begin
  if not v_ops and v_drv is null then raise exception 'Droit insuffisant (exige : colis.lire).' using errcode = 'LG003'; end if;
  return jsonb_build_object('as_of', now(), 'date', v_day, 'mine_only', not v_ops,
    'items', coalesce((select jsonb_agg(jsonb_build_object(
        'trip_id', tr.id, 'status', tr.status, 'driver', d.full_name, 'vehicle', v.plate,
        'stops', (select count(*) from logistics.stop s where s.trip_id = tr.id and s.status <> 'SKIPPED'),
        'done', (select count(*) from logistics.stop s join logistics.task t on t.id = s.task_id where s.trip_id = tr.id and s.status <> 'SKIPPED' and t.status = 'COMPLETED'),
        'failed', (select count(*) from logistics.stop s join logistics.task t on t.id = s.task_id where s.trip_id = tr.id and s.status <> 'SKIPPED' and t.status = 'FAILED'),
        'load_lb', (select coalesce(sum(t.weight_lb), 0) from logistics.task t where t.trip_id = tr.id and t.status <> 'CANCELLED'),
        'capacity_lb', v.capacity_lb, 'started_at', tr.actual_departure_at, 'completed_at', tr.actual_arrival_at)
        order by tr.status = 'STARTED' desc, d.full_name, tr.id)
      from logistics.trip tr left join logistics.driver d on d.id = tr.driver_id left join logistics.vehicle v on v.id = tr.vehicle_id
     where tr.kind = 'LASTMILE' and tr.trip_date = v_day and (v_ops or tr.driver_id = v_drv)), '[]'::jsonb));
end;
$$;

-- Les dépenses d'une période, et leurs totaux (par catégorie et par devise, et en dollars) — comptés ICI.
create or replace function logistics.cc_expenses(p_actor uuid, p_from date default null, p_to date default null, p_category text default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_from date := coalesce(p_from, date_trunc('month', logistics.today())::date); v_to date := coalesce(p_to, logistics.today());
begin
  perform logistics.require_right(p_actor, 'factures.lire');
  if v_to < v_from then raise exception 'Période invalide.' using errcode = 'LG005'; end if;
  return (with f as (select * from logistics.expense e where e.incurred_on between v_from and v_to and (p_category is null or e.category = p_category))
    select jsonb_build_object('from', v_from, 'to', v_to, 'category', p_category,
      'total_usd', coalesce((select sum(base_amount_usd) from f where status = 'RECORDED'), 0),
      'by_category', coalesce((select jsonb_agg(jsonb_build_object('category', category, 'count', n, 'total_usd', s) order by s desc)
                                 from (select category, count(*) n, sum(base_amount_usd) s from f where status = 'RECORDED' group by category) x), '[]'::jsonb),
      'by_currency', coalesce((select jsonb_agg(jsonb_build_object('currency', currency, 'total', s) order by currency)
                                 from (select currency, sum(amount) s from f where status = 'RECORDED' group by currency) x), '[]'::jsonb),
      'voided', (select count(*) from f where status = 'VOIDED'),
      'items', coalesce((select jsonb_agg(jsonb_build_object('number', number, 'category', category, 'description', description, 'amount', amount, 'currency', currency,
                                                              'amount_usd', base_amount_usd, 'incurred_on', incurred_on, 'supplier', supplier, 'status', status)
                                           order by incurred_on desc, number desc) from (select * from f order by incurred_on desc, number desc limit 200) z), '[]'::jsonb)));
end;
$$;


-- 7. Pointage des colis : ouvrir, pointer, clore ----------------------------------------------------------------------------
create or replace function logistics.open_tally(p_actor uuid, p_kind text, p_source_type text, p_source_id uuid default null, p_tracking_numbers text[] default null, p_note text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid := gen_random_uuid(); v_num text; v_corr uuid := gen_random_uuid(); v_label text; v_n int;
begin
  perform logistics.require_right(p_actor);
  if p_kind not in ('ARRIVAL', 'LOADING', 'INVENTORY', 'OTHER') then raise exception 'Genre de pointage inconnu : %.', p_kind using errcode = 'LG005'; end if;
  if p_source_type not in ('shipment', 'consolidation', 'warehouse', 'list') then raise exception 'Source inconnue : %.', p_source_type using errcode = 'LG005'; end if;
  if (p_source_type = 'list') <> (p_source_id is null) then raise exception 'Une liste libre n''a pas de source ; les autres en ont une.' using errcode = 'LG005'; end if;
  v_label := case p_source_type
    when 'shipment' then (select code from logistics.shipment where id = p_source_id)
    when 'consolidation' then (select code from logistics.consolidation where id = p_source_id)
    when 'warehouse' then (select code from logistics.warehouse where id = p_source_id)
    else 'liste' end;
  if v_label is null then raise exception 'Source introuvable.' using errcode = 'LG002'; end if;
  v_num := logistics.next_number('tally', 'PTG');
  insert into logistics.tally_session (id, number, kind, source_type, source_id, source_label, opened_by, note, correlation_id)
  values (v_id, v_num, p_kind, p_source_type, p_source_id, v_label, p_actor, left(coalesce(p_note, ''), 500), v_corr);
  -- La liste ATTENDUE, figée maintenant : un colis ajouté à l'expédition plus tard sera « en trop », pas attendu.
  insert into logistics.tally_line (session_id, tracking_number, parcel_id, expected)
  select v_id, p.tracking_number, p.id, true from logistics.parcel p
   where case p_source_type
           when 'shipment' then p.id in (select parcel_id from logistics.shipment_parcels(p_source_id)) and logistics.parcel_current_shipment(p.id) = p_source_id
           when 'consolidation' then p.id in (select cp.parcel_id from logistics.consolidation_parcel cp where cp.consolidation_id = p_source_id and cp.removed_at is null)
           when 'warehouse' then p.current_warehouse_id = p_source_id and p.status in ('RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'AT_DESTINATION_HUB', 'ON_HOLD')
           else false end;
  if p_source_type = 'list' then
    insert into logistics.tally_line (session_id, tracking_number, parcel_id, expected)
    select distinct on (n) v_id, n, (select p.id from logistics.parcel p where p.tracking_number = n), true
      from (select upper(btrim(x)) n from unnest(coalesce(p_tracking_numbers, '{}')) x where btrim(x) <> '') z;
  end if;
  get diagnostics v_n = row_count;
  v_n := (select count(*) from logistics.tally_line where session_id = v_id);
  if v_n = 0 then raise exception 'Rien à pointer : la liste attendue est vide.' using errcode = 'LG005'; end if;
  perform logistics.fin_audit(p_actor, 'tally.open', 'tally', v_id::text, null, jsonb_build_object('number', v_num, 'kind', p_kind, 'source', v_label, 'expected', v_n), v_corr);
  perform logistics.emit('TallyOpened', 'tally', v_id::text, v_corr, p_actor, jsonb_build_object('tally_id', v_id, 'number', v_num, 'kind', p_kind, 'expected', v_n));
  return logistics.tally_detail(p_actor, v_id);
end;
$$;

create or replace function logistics.tally_scan(p_actor uuid, p_session uuid, p_code text, p_code_kind text default 'unknown', p_idempotency_key text default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_s logistics.tally_session; v_num text; v_l logistics.tally_line; v_pid uuid; v_res text; v_prior jsonb; v_out jsonb;
begin
  perform logistics.require_right(p_actor);
  v_prior := logistics.idem_begin(p_idempotency_key, 'tally_scan', md5(concat_ws('|', p_session, p_code)), coalesce(p_session::text, ''));
  if v_prior is not null then return v_prior; end if;
  select * into v_s from logistics.tally_session where id = p_session for update;
  if not found then raise exception 'Pointage introuvable.' using errcode = 'LG002'; end if;
  if v_s.status <> 'OPEN' then raise exception 'Pointage clos.' using errcode = 'LG004'; end if;
  -- Le même lecteur que le poste de scan : numéro, QR du site, code-barres.
  v_num := coalesce(logistics.parse_code(p_code) ->> 'number', upper(btrim(coalesce(p_code, ''))));
  if btrim(coalesce(v_num, '')) = '' then raise exception 'Code illisible.' using errcode = 'LG005'; end if;
  select * into v_l from logistics.tally_line where session_id = p_session and tracking_number = v_num for update;
  if found then
    if v_l.checked_at is not null then v_res := 'DUPLICATE';
    else
      update logistics.tally_line set checked_at = now(), checked_by = p_actor, code_kind = left(coalesce(p_code_kind, 'unknown'), 20) where id = v_l.id;
      v_res := 'CHECKED';
    end if;
  else
    select id into v_pid from logistics.parcel where tracking_number = v_num;
    insert into logistics.tally_line (session_id, tracking_number, parcel_id, expected, checked_at, checked_by, code_kind)
    values (p_session, v_num, v_pid, false, now(), p_actor, left(coalesce(p_code_kind, 'unknown'), 20));
    v_res := case when v_pid is null then 'UNKNOWN' else 'EXTRA' end;
  end if;
  v_out := jsonb_build_object('result', v_res, 'tracking_number', v_num,
                              'expected', (select count(*) from logistics.tally_line where session_id = p_session and expected),
                              'checked', (select count(*) from logistics.tally_line where session_id = p_session and expected and checked_at is not null),
                              'extra', (select count(*) from logistics.tally_line where session_id = p_session and not expected));
  return logistics.idem_end(p_idempotency_key, v_out);
end;
$$;

create or replace function logistics.tally_detail(p_actor uuid, p_session uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_s logistics.tally_session;
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  select * into v_s from logistics.tally_session where id = p_session;
  if not found then raise exception 'Pointage introuvable.' using errcode = 'LG002'; end if;
  return jsonb_build_object('tally_id', v_s.id, 'number', v_s.number, 'kind', v_s.kind, 'source_type', v_s.source_type, 'source', v_s.source_label, 'status', v_s.status,
    'opened_at', v_s.opened_at, 'closed_at', v_s.closed_at, 'note', v_s.note,
    'expected', (select count(*) from logistics.tally_line where session_id = v_s.id and expected),
    'checked', (select count(*) from logistics.tally_line where session_id = v_s.id and expected and checked_at is not null),
    'missing', coalesce((select jsonb_agg(l.tracking_number order by l.tracking_number) from logistics.tally_line l where l.session_id = v_s.id and l.expected and l.checked_at is null), '[]'::jsonb),
    'extra', coalesce((select jsonb_agg(l.tracking_number order by l.tracking_number) from logistics.tally_line l where l.session_id = v_s.id and not l.expected and l.parcel_id is not null), '[]'::jsonb),
    'unknown', coalesce((select jsonb_agg(l.tracking_number order by l.tracking_number) from logistics.tally_line l where l.session_id = v_s.id and not l.expected and l.parcel_id is null), '[]'::jsonb),
    'recent', coalesce((select jsonb_agg(jsonb_build_object('tracking_number', z.tracking_number, 'expected', z.expected, 'known', z.parcel_id is not null, 'at', z.checked_at) order by z.checked_at desc)
                          from (select * from logistics.tally_line where session_id = v_s.id and checked_at is not null order by checked_at desc, id desc limit 10) z), '[]'::jsonb));
end;
$$;

create or replace function logistics.close_tally(p_actor uuid, p_session uuid, p_note text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_s logistics.tally_session; v_sum jsonb; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor);
  select * into v_s from logistics.tally_session where id = p_session for update;
  if not found then raise exception 'Pointage introuvable.' using errcode = 'LG002'; end if;
  if v_s.status <> 'OPEN' then raise exception 'Pointage déjà clos.' using errcode = 'LG004'; end if;
  v_sum := logistics.tally_detail(p_actor, p_session) - 'recent';
  update logistics.tally_session set status = 'CLOSED', closed_by = p_actor, closed_at = now(), summary = v_sum,
         note = case when btrim(coalesce(p_note, '')) = '' then note else left(btrim(note || ' ' || p_note), 500) end where id = p_session;
  perform logistics.fin_audit(p_actor, 'tally.close', 'tally', p_session::text, jsonb_build_object('status', 'OPEN'),
                              jsonb_build_object('status', 'CLOSED', 'expected', v_sum -> 'expected', 'checked', v_sum -> 'checked',
                                                 'missing', jsonb_array_length(v_sum -> 'missing'), 'extra', jsonb_array_length(v_sum -> 'extra'), 'unknown', jsonb_array_length(v_sum -> 'unknown')), v_corr);
  perform logistics.emit('TallyClosed', 'tally', p_session::text, v_corr, p_actor,
                         jsonb_build_object('tally_id', p_session, 'number', v_s.number, 'missing', jsonb_array_length(v_sum -> 'missing'), 'extra', jsonb_array_length(v_sum -> 'extra')));
  return v_sum || jsonb_build_object('status', 'CLOSED');
end;
$$;

create or replace function logistics.cc_tallies(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  return coalesce((select jsonb_agg(jsonb_build_object('tally_id', s.id, 'number', s.number, 'kind', s.kind, 'source', s.source_label, 'status', s.status, 'opened_at', s.opened_at, 'closed_at', s.closed_at,
                    'expected', (select count(*) from logistics.tally_line l where l.session_id = s.id and l.expected),
                    'checked', (select count(*) from logistics.tally_line l where l.session_id = s.id and l.expected and l.checked_at is not null),
                    'extra', (select count(*) from logistics.tally_line l where l.session_id = s.id and not l.expected)) order by s.status = 'OPEN' desc, s.opened_at desc)
                   from (select * from logistics.tally_session order by status = 'OPEN' desc, opened_at desc limit 50) s), '[]'::jsonb);
end;
$$;


-- 8. Pointage du personnel ----------------------------------------------------------------------------------------------
-- L'état d'un membre à un instant : le dernier événement de SA journée (heure d'Haïti), ou OUT.
create or replace function logistics.clock_state(p_user uuid, p_at timestamptz)
returns text language sql stable security definer set search_path = '' as $$
  select coalesce((select e.kind from logistics.staff_clock_event e
                    where e.user_id = p_user and e.occurred_at <= p_at and e.occurred_at >= logistics.day_start((p_at at time zone 'America/Port-au-Prince')::date)
                    order by e.occurred_at desc, e.id desc limit 1), 'OUT')
$$;

create or replace function logistics.clock(p_actor uuid, p_kind text, p_source text default 'WEB', p_note text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_st text; v_corr uuid := gen_random_uuid(); v_ok boolean;
begin
  perform logistics.require_staff(p_actor);
  if p_kind not in ('IN', 'BREAK_START', 'BREAK_END', 'OUT') then raise exception 'Pointage inconnu : %.', p_kind using errcode = 'LG005'; end if;
  if p_source not in ('WEB', 'APP') then raise exception 'Source inconnue.' using errcode = 'LG005'; end if;
  perform pg_advisory_xact_lock(hashtext('clock:' || p_actor::text));
  v_st := logistics.clock_state(p_actor, now());
  v_ok := case p_kind when 'IN' then v_st = 'OUT' when 'BREAK_START' then v_st in ('IN', 'BREAK_END') when 'BREAK_END' then v_st = 'BREAK_START' when 'OUT' then v_st in ('IN', 'BREAK_END') end;
  if not v_ok then raise exception 'Pointage % impossible : vous êtes « % ».', p_kind, v_st using errcode = 'LG004'; end if;
  insert into logistics.staff_clock_event (user_id, kind, source, note, recorded_by, correlation_id) values (p_actor, p_kind, p_source, left(coalesce(p_note, ''), 500), p_actor, v_corr);
  perform logistics.emit('StaffClocked', 'staff', p_actor::text, v_corr, p_actor, jsonb_build_object('kind', p_kind));
  return logistics.clock_day(p_actor, p_actor, logistics.today());
end;
$$;

-- Une journée d'un membre : ses événements, le temps travaillé et en pause (minutes), l'état, les anomalies — calculés ICI.
create or replace function logistics.clock_day(p_actor uuid, p_user uuid, p_day date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare r record; v_in timestamptz; v_brk timestamptz; v_work numeric := 0; v_break numeric := 0; v_last text := 'OUT'; v_anom text[] := '{}'; v_fin timestamptz;
        v_d0 timestamptz := logistics.day_start(p_day); v_d1 timestamptz := logistics.day_start(p_day + 1); v_ev jsonb := '[]'::jsonb;
begin
  if p_user is distinct from p_actor then perform logistics.require_right(p_actor, 'direction'); else perform logistics.require_staff(p_actor); end if;
  for r in select * from logistics.staff_clock_event where user_id = p_user and occurred_at >= v_d0 and occurred_at < v_d1 order by occurred_at, id loop
    v_ev := v_ev || jsonb_build_object('kind', r.kind, 'at', r.occurred_at, 'source', r.source, 'reason', r.reason);
    if r.kind = 'IN' then
      if v_last <> 'OUT' then v_anom := v_anom || 'DOUBLE_IN'::text; end if;
      v_in := r.occurred_at;
    elsif r.kind = 'BREAK_START' then
      if v_last not in ('IN', 'BREAK_END') then v_anom := v_anom || 'SEQUENCE'::text; end if;
      if v_in is not null then v_work := v_work + extract(epoch from (r.occurred_at - v_in)) / 60; v_in := null; end if;
      v_brk := r.occurred_at;
    elsif r.kind = 'BREAK_END' then
      if v_last <> 'BREAK_START' then v_anom := v_anom || 'SEQUENCE'::text; end if;
      if v_brk is not null then v_break := v_break + extract(epoch from (r.occurred_at - v_brk)) / 60; v_brk := null; end if;
      v_in := r.occurred_at;
    else
      if v_last not in ('IN', 'BREAK_END') then v_anom := v_anom || 'SEQUENCE'::text; end if;
      if v_in is not null then v_work := v_work + extract(epoch from (r.occurred_at - v_in)) / 60; v_in := null; end if;
    end if;
    v_last := r.kind;
  end loop;
  -- Une journée encore ouverte : jusqu'à maintenant si c'est aujourd'hui, sinon une anomalie (départ non pointé).
  v_fin := least(now(), v_d1);
  if v_last in ('IN', 'BREAK_END') and v_in is not null then
    if p_day >= logistics.today() then v_work := v_work + extract(epoch from (v_fin - v_in)) / 60; else v_anom := v_anom || 'NO_OUT'::text; end if;
  elsif v_last = 'BREAK_START' then
    if p_day >= logistics.today() then v_break := v_break + extract(epoch from (v_fin - v_brk)) / 60; else v_anom := v_anom || 'NO_OUT'::text; end if;
  end if;
  return jsonb_build_object('user_id', p_user, 'date', p_day, 'state', case when p_day >= logistics.today() then v_last else 'OUT' end,
    'worked_minutes', floor(v_work)::int, 'break_minutes', floor(v_break)::int, 'anomalies', to_jsonb(array(select distinct x from unnest(v_anom) x order by 1)), 'events', v_ev);
end;
$$;

-- Le relevé de la direction : par membre et par jour, sur une période (31 jours au plus).
create or replace function logistics.clock_report(p_actor uuid, p_from date, p_to date, p_user uuid default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare d date; r record; v_out jsonb := '[]'::jsonb; v_j jsonb;
begin
  perform logistics.require_right(p_actor, 'direction');
  if p_from is null or p_to is null or p_to < p_from or p_to - p_from > 31 then raise exception 'Période invalide (31 jours au plus).' using errcode = 'LG005'; end if;
  for r in select u.id, coalesce(c.nom, au.email, u.id::text) as nom, u.staff_code
             from logistics.app_user u left join auth.users au on au.id = u.id
             left join lateral (select coalesce(au.raw_user_meta_data ->> 'nom_complet', '') as nom) c on true
            where u.active and (p_user is null or u.id = p_user)
              and exists (select 1 from logistics.staff_clock_event e where e.user_id = u.id and e.occurred_at >= logistics.day_start(p_from) and e.occurred_at < logistics.day_start(p_to + 1))
            order by 2, 1 loop
    d := p_from;
    while d <= p_to loop
      v_j := logistics.clock_day(p_actor, r.id, d);
      if jsonb_array_length(v_j -> 'events') > 0 then
        v_out := v_out || (v_j - 'events' - 'user_id' || jsonb_build_object('user_id', r.id, 'name', nullif(r.nom, ''), 'staff_code', r.staff_code,
                                                                             'first_in', (select min((x ->> 'at')::timestamptz) from jsonb_array_elements(v_j -> 'events') x where x ->> 'kind' = 'IN'),
                                                                             'last_out', (select max((x ->> 'at')::timestamptz) from jsonb_array_elements(v_j -> 'events') x where x ->> 'kind' = 'OUT')));
      end if;
      d := d + 1;
    end loop;
  end loop;
  return jsonb_build_object('from', p_from, 'to', p_to, 'rows', v_out,
                            'total_minutes', coalesce((select sum((x ->> 'worked_minutes')::int) from jsonb_array_elements(v_out) x), 0),
                            'anomalies', coalesce((select count(*) from jsonb_array_elements(v_out) x where jsonb_array_length(x -> 'anomalies') > 0), 0));
end;
$$;

create or replace function logistics.clock_correct(p_actor uuid, p_user uuid, p_kind text, p_at timestamptz, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour corriger un pointage.' using errcode = 'LG005'; end if;
  if p_kind not in ('IN', 'BREAK_START', 'BREAK_END', 'OUT') then raise exception 'Pointage inconnu : %.', p_kind using errcode = 'LG005'; end if;
  if p_at is null or p_at > now() or p_at < now() - interval '62 days' then raise exception 'Heure invalide (ni future, ni de plus de 62 jours).' using errcode = 'LG005'; end if;
  if not exists (select 1 from logistics.app_user where id = p_user) then raise exception 'Membre introuvable.' using errcode = 'LG002'; end if;
  insert into logistics.staff_clock_event (user_id, kind, occurred_at, source, recorded_by, reason, correlation_id) values (p_user, p_kind, p_at, 'CORRECTION', p_actor, left(btrim(p_reason), 500), v_corr);
  perform logistics.fin_audit(p_actor, 'staff.clock_correct', 'staff', p_user::text, null, jsonb_build_object('kind', p_kind, 'at', p_at, 'reason', left(btrim(p_reason), 500)), v_corr);
  perform logistics.emit('StaffClockCorrected', 'staff', p_user::text, v_corr, p_actor, jsonb_build_object('kind', p_kind, 'at', p_at));
  return logistics.clock_day(p_actor, p_user, (p_at at time zone 'America/Port-au-Prince')::date);
end;
$$;


-- 9. La façade ----------------------------------------------------------------------------------------------------------------
create or replace function public.lg_dashboard_access() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.dashboard_access(auth.uid()) $$;
create or replace function public.lg_cc_command() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.command_cards(auth.uid()) $$;
create or replace function public.lg_cc_vehicles() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_vehicles(auth.uid()) $$;
create or replace function public.lg_cc_trips(p_date date default null) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_trips(auth.uid(), p_date) $$;
create or replace function public.lg_cc_expenses(p_from date default null, p_to date default null, p_category text default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_expenses(auth.uid(), p_from, p_to, p_category) $$;
create or replace function public.lg_cc_tallies() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_tallies(auth.uid()) $$;
create or replace function public.lg_open_tally(p_kind text, p_source_type text, p_source_id uuid default null, p_tracking_numbers text[] default null, p_note text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.open_tally(auth.uid(), p_kind, p_source_type, p_source_id, p_tracking_numbers, p_note) $$;
create or replace function public.lg_tally_scan(p_tally_id uuid, p_code text, p_code_kind text default 'unknown', p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.tally_scan(auth.uid(), p_tally_id, p_code, p_code_kind, p_idempotency_key) $$;
create or replace function public.lg_tally_detail(p_tally_id uuid) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.tally_detail(auth.uid(), p_tally_id) $$;
create or replace function public.lg_close_tally(p_tally_id uuid, p_note text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.close_tally(auth.uid(), p_tally_id, p_note) $$;
create or replace function public.lg_clock(p_kind text, p_source text default 'WEB', p_note text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.clock(auth.uid(), p_kind, p_source, p_note) $$;
create or replace function public.lg_my_clock(p_date date default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.clock_day(auth.uid(), auth.uid(), coalesce(p_date, logistics.today())) $$;
create or replace function public.lg_clock_report(p_from date, p_to date, p_user_id uuid default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.clock_report(auth.uid(), p_from, p_to, p_user_id) $$;
create or replace function public.lg_clock_correct(p_user_id uuid, p_kind text, p_at timestamptz, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.clock_correct(auth.uid(), p_user_id, p_kind, p_at, p_reason) $$;


-- 10. Tout fermé, sauf la façade, réservée aux comptes connectés -------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('guard_tally', 'dashboard_access', 'command_cards', 'cc_vehicles', 'cc_trips', 'cc_expenses', 'open_tally', 'tally_scan',
              'tally_detail', 'close_tally', 'cc_tallies', 'clock_state', 'clock', 'clock_day', 'clock_report', 'clock_correct') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_dashboard_access', 'lg_cc_command', 'lg_cc_vehicles', 'lg_cc_trips', 'lg_cc_expenses', 'lg_cc_tallies', 'lg_open_tally',
              'lg_tally_scan', 'lg_tally_detail', 'lg_close_tally', 'lg_clock', 'lg_my_clock', 'lg_clock_report', 'lg_clock_correct') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
