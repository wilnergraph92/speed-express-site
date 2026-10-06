-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 12 : l'analytique et les rapports
-- -----------------------------------------------------------------------------
-- Phase 16. À coller dans Supabase > SQL Editor APRÈS 001 à 011, après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet ouvert est bien « speed-express-site ».
--
-- Deux mondes séparés (ADR 0014) :
--   · TRANSACTIONNEL : le schéma « logistics », où vivent les colis, les missions, les factures. Rien ici n'y écrit (sinon des index) ;
--   · ANALYTIQUE : le schéma « analytics », écrit SEULEMENT par analytics.refresh, lu SEULEMENT par la façade public.lg_an_*.
--
-- Comment un chiffre naît :
--   1. analytics.refresh(du, au) calcule des FAITS QUOTIDIENS (un jour d'Haïti, une mesure, une dimension, une valeur) à partir des seuls
--      journaux en ajout seul du noyau : événements de suivi, historiques de statut des expéditions et des missions, scans, incidents,
--      écritures de revenu, paiements, remboursements, tickets, fiches client. Un jour passé se recalcule donc à l'identique ;
--   2. chaque calcul est une EXÉCUTION tracée (analytics.report_run) : qui, quand, sur quels jours, combien de lignes, l'empreinte des faits
--      (md5), l'état des sources sur la période (nombre de lignes de chaque journal). Les faits et les exécutions sont en ajout seul ; le
--      chiffre en vigueur d'un jour est celui de sa dernière exécution réussie ;
--   3. les rapports semaine, mois, trimestre, année ADDITIONNENT les jours : aucun chiffre agrégé n'est stocké, aucun ne peut diverger ;
--   4. analytics.verify_run(n) recalcule l'exécution n et compare : « reproductible », ou « les sources ont changé » (un rattrapage dans un
--      journal), ou « le calcul a changé » (même sources, autre résultat : le code a évolué).
--
-- Droits : lire une mesure d'activité exige « colis.lire », une mesure financière « factures.lire », une mesure clientèle « clients.lire » ;
-- recalculer exige la direction (ou le travailleur, avec la clé secrète). Un jour qui n'a jamais été calculé est signalé, jamais compté zéro
-- en silence. Rejouable sans risque ; aucune suppression.
-- =============================================================================

create schema if not exists analytics;
revoke all on schema analytics from public, anon, authenticated;

-- 1. Les mesures : un registre, pour que chaque chiffre ait une définition écrite -----------------------------------------------------
create table if not exists analytics.metric (
  code        text primary key,
  domain      text not null check (domain in ('ops', 'finance', 'customers')),
  unit        text not null check (unit in ('count', 'usd', 'hours')),
  definition  text not null check (btrim(definition) <> '')
);
insert into analytics.metric (code, domain, unit, definition) values
  ('parcels_received',     'ops',       'count', 'Colis passés à RECEIVED ce jour-là (événements de suivi), par mode de service.'),
  ('parcels_delivered',    'ops',       'count', 'Colis passés à DELIVERED ce jour-là, par mode de service.'),
  ('parcels_on_hold',      'ops',       'count', 'Colis mis en attente (ON_HOLD) ce jour-là.'),
  ('parcels_damaged',      'ops',       'count', 'Colis déclarés endommagés (DAMAGED) ce jour-là.'),
  ('parcels_lost',         'ops',       'count', 'Colis déclarés perdus (LOST) ce jour-là.'),
  ('parcels_returned',     'ops',       'count', 'Colis retournés (RETURNED) ce jour-là.'),
  ('transit_hours_sum',    'ops',       'hours', 'Pour les colis livrés ce jour-là : somme des heures entre leur première réception et leur livraison, par mode.'),
  ('transit_count',        'ops',       'count', 'Nombre de colis livrés ce jour-là dont la réception est connue (diviseur du délai moyen), par mode.'),
  ('shipments_dispatched', 'ops',       'count', 'Expéditions passées à DISPATCHED ce jour-là.'),
  ('shipments_arrived',    'ops',       'count', 'Expéditions passées à ARRIVED ce jour-là.'),
  ('tasks_completed',      'ops',       'count', 'Missions terminées (COMPLETED) ce jour-là, par genre (PICKUP, DELIVERY).'),
  ('tasks_failed',         'ops',       'count', 'Missions échouées (FAILED) ce jour-là, par genre.'),
  ('scans_total',          'ops',       'count', 'Scans enregistrés ce jour-là, par entrepôt.'),
  ('scans_rejected',       'ops',       'count', 'Scans dont le verdict n''est pas ACCEPTED, par entrepôt.'),
  ('incidents_opened',     'ops',       'count', 'Incidents ouverts ce jour-là, par type.'),
  ('tickets_opened',       'customers', 'count', 'Tickets de support ouverts ce jour-là.'),
  ('customers_new',        'customers', 'count', 'Fiches client créées ce jour-là.'),
  ('revenue_net_usd',      'finance',   'usd',   'Écritures de revenu (hors taxe) à cette date comptable, en dollars de base, par catégorie.'),
  ('revenue_tax_usd',      'finance',   'usd',   'Taxes des écritures de revenu à cette date comptable, en dollars de base.'),
  ('payments_usd',         'finance',   'usd',   'Paiements reçus ce jour-là, en dollars de base, par moyen.'),
  ('payments_count',       'finance',   'count', 'Nombre de paiements reçus ce jour-là, par moyen.'),
  ('refunds_usd',          'finance',   'usd',   'Remboursements faits ce jour-là, en dollars de base.')
on conflict (code) do update set domain = excluded.domain, unit = excluded.unit, definition = excluded.definition;

-- 2. Les exécutions et les faits : en ajout seul --------------------------------------------------------------------------------------
create table if not exists analytics.report_run (
  id               bigint generated always as identity primary key,
  period_start     date not null,
  period_end       date not null,
  generated_at     timestamptz not null default now(),
  generated_by     uuid,                                        -- null : le travailleur (clé secrète)
  generated_label  text not null default '',
  partial          boolean not null,                            -- la période touche aujourd'hui : chiffres provisoires
  row_count        integer not null,
  checksum         text not null,
  source_watermark jsonb not null,
  duration_ms      integer not null,
  check (period_end >= period_start)
);
create table if not exists analytics.daily_fact (
  run_id    bigint not null references analytics.report_run (id) on delete restrict,
  day       date not null,
  metric    text not null references analytics.metric (code) on delete restrict,
  dimension text not null default '',
  value     numeric(18, 4) not null,
  primary key (run_id, day, metric, dimension)
);
create index if not exists daily_fact_day_idx on analytics.daily_fact (day, run_id);
create index if not exists report_run_period_idx on analytics.report_run (period_start, period_end, id);

create or replace function analytics.forbid_mutation() returns trigger language plpgsql set search_path = '' as $$
begin
  raise exception 'Analytique en ajout seul : % interdit sur %.', tg_op, tg_table_name using errcode = 'LG004';
end;
$$;
drop trigger if exists report_run_append_only on analytics.report_run;
create trigger report_run_append_only before update or delete on analytics.report_run for each row execute function analytics.forbid_mutation();
drop trigger if exists daily_fact_append_only on analytics.daily_fact;
create trigger daily_fact_append_only before update or delete on analytics.daily_fact for each row execute function analytics.forbid_mutation();

-- Les journaux lus par période : des index sur les dates (aucune donnée touchée ; tables du noyau encore petites).
create index if not exists tracking_event_occurred_idx on logistics.tracking_event (occurred_at);
create index if not exists shipment_status_history_occurred_idx on logistics.shipment_status_history (occurred_at);
create index if not exists task_status_history_occurred_idx on logistics.task_status_history (occurred_at);
create index if not exists scan_scanned_at_idx on logistics.scan (scanned_at);
create index if not exists incident_created_idx on logistics.incident (created_at);
create index if not exists payment_paid_at_idx on logistics.payment (paid_at);
create index if not exists refund_created_idx on logistics.refund (created_at);
create index if not exists support_ticket_created_idx on logistics.support_ticket (created_at);
create index if not exists customer_created_idx on logistics.customer (created_at);

-- 3. Le calcul ------------------------------------------------------------------------------------------------------------------------
-- Un instant → son jour à Haïti (celui de logistics.today()).
create or replace function analytics.day_of(p_ts timestamptz) returns date language sql immutable set search_path = '' as $$
  select (p_ts at time zone 'America/Port-au-Prince')::date
$$;

-- Les faits d'une période, SANS rien écrire : la seule définition des chiffres (refresh l'enregistre, verify_run la recompare).
create or replace function analytics.compute_facts(p_from date, p_to date)
returns table (day date, metric text, dimension text, value numeric)
language sql stable set search_path = '' as $$
  with bornes as (select logistics.day_start(p_from) as t0, logistics.day_start(p_to + 1) as t1),
  te as (
    select analytics.day_of(e.occurred_at) as d, e.parcel_id, e.to_status, e.occurred_at, p.service_mode
      from logistics.tracking_event e join logistics.parcel p on p.id = e.parcel_id, bornes b
     where e.occurred_at >= b.t0 and e.occurred_at < b.t1 and e.to_status is not null
  ),
  livres as (
    select te.d, te.service_mode, extract(epoch from te.occurred_at - r.recu) / 3600.0 as heures
      from te
      left join lateral (select min(x.occurred_at) as recu from logistics.tracking_event x
                          where x.parcel_id = te.parcel_id and x.to_status = 'RECEIVED' and x.occurred_at <= te.occurred_at) r on true
     where te.to_status = 'DELIVERED'
  ),
  faits as (
    select d, 'parcels_received'::text as metric, service_mode as dimension, count(distinct parcel_id)::numeric as value from te where to_status = 'RECEIVED' group by d, service_mode
    union all
    select d, 'parcels_delivered', service_mode, count(distinct parcel_id) from te where to_status = 'DELIVERED' group by d, service_mode
    union all
    select d, case to_status when 'ON_HOLD' then 'parcels_on_hold' when 'DAMAGED' then 'parcels_damaged' when 'LOST' then 'parcels_lost' else 'parcels_returned' end, '', count(distinct parcel_id)
      from te where to_status in ('ON_HOLD', 'DAMAGED', 'LOST', 'RETURNED') group by d, to_status
    union all
    select d, 'transit_hours_sum', service_mode, round(sum(heures)::numeric, 4) from livres where heures is not null group by d, service_mode
    union all
    select d, 'transit_count', service_mode, count(*) from livres where heures is not null group by d, service_mode
    union all
    select analytics.day_of(h.occurred_at), case h.to_status when 'DISPATCHED' then 'shipments_dispatched' else 'shipments_arrived' end, '', count(distinct h.shipment_id)
      from logistics.shipment_status_history h, bornes b
     where h.occurred_at >= b.t0 and h.occurred_at < b.t1 and h.to_status in ('DISPATCHED', 'ARRIVED') group by 1, h.to_status
    union all
    select analytics.day_of(h.occurred_at), case h.to_status when 'COMPLETED' then 'tasks_completed' else 'tasks_failed' end, t.kind, count(distinct h.task_id)
      from logistics.task_status_history h join logistics.task t on t.id = h.task_id, bornes b
     where h.occurred_at >= b.t0 and h.occurred_at < b.t1 and h.to_status in ('COMPLETED', 'FAILED') group by 1, h.to_status, t.kind
    union all
    select analytics.day_of(s.scanned_at), 'scans_total', w.code, count(*) from logistics.scan s join logistics.warehouse w on w.id = s.warehouse_id, bornes b
     where s.scanned_at >= b.t0 and s.scanned_at < b.t1 group by 1, w.code
    union all
    select analytics.day_of(s.scanned_at), 'scans_rejected', w.code, count(*) from logistics.scan s join logistics.warehouse w on w.id = s.warehouse_id, bornes b
     where s.scanned_at >= b.t0 and s.scanned_at < b.t1 and s.result <> 'ACCEPTED' group by 1, w.code
    union all
    select analytics.day_of(i.created_at), 'incidents_opened', i.type, count(*) from logistics.incident i, bornes b
     where i.created_at >= b.t0 and i.created_at < b.t1 group by 1, i.type
    union all
    select analytics.day_of(k.created_at), 'tickets_opened', '', count(*) from logistics.support_ticket k, bornes b
     where k.created_at >= b.t0 and k.created_at < b.t1 group by 1
    union all
    select analytics.day_of(c.created_at), 'customers_new', '', count(*) from logistics.customer c, bornes b
     where c.created_at >= b.t0 and c.created_at < b.t1 group by 1
    union all
    select r.entry_date, 'revenue_net_usd', r.category, sum(r.net_base_usd) from logistics.revenue_entry r
     where r.entry_date between p_from and p_to group by r.entry_date, r.category
    union all
    select r.entry_date, 'revenue_tax_usd', '', sum(r.tax_base_usd) from logistics.revenue_entry r
     where r.entry_date between p_from and p_to group by r.entry_date
    union all
    select analytics.day_of(y.paid_at), 'payments_usd', y.method, sum(y.base_amount_usd) from logistics.payment y, bornes b
     where y.paid_at >= b.t0 and y.paid_at < b.t1 group by 1, y.method
    union all
    select analytics.day_of(y.paid_at), 'payments_count', y.method, count(*) from logistics.payment y, bornes b
     where y.paid_at >= b.t0 and y.paid_at < b.t1 group by 1, y.method
    union all
    select analytics.day_of(f.created_at), 'refunds_usd', '', sum(f.base_amount_usd) from logistics.refund f, bornes b
     where f.created_at >= b.t0 and f.created_at < b.t1 group by 1
  )
  -- Des valeurs nulles ne s'écrivent pas : un jour sans activité n'a pas de ligne, mais il A une exécution (il est « calculé »).
  select d, metric, dimension, round(value, 4) from faits where value <> 0 and d between p_from and p_to
$$;

-- L'empreinte d'un ensemble de faits : stable (ordre fixe, valeurs à 4 décimales).
create or replace function analytics.checksum(p_rows jsonb) returns text language sql immutable set search_path = '' as $$
  select md5(coalesce((select string_agg(x ->> 'day' || '|' || (x ->> 'metric') || '|' || (x ->> 'dimension') || '|' || trim_scale((x ->> 'value')::numeric)::text, E'\n'
                                         order by x ->> 'day', x ->> 'metric', x ->> 'dimension')
                         from jsonb_array_elements(coalesce(p_rows, '[]'::jsonb)) x), ''))
$$;

-- L'état des sources sur la période : combien de lignes chaque journal y compte. Changé entre deux calculs = un rattrapage a eu lieu.
create or replace function analytics.source_watermark(p_from date, p_to date) returns jsonb language sql stable set search_path = '' as $$
  with b as (select logistics.day_start(p_from) as t0, logistics.day_start(p_to + 1) as t1)
  select jsonb_build_object(
    'tracking_event',          (select count(*) from logistics.tracking_event x, b where x.occurred_at >= b.t0 and x.occurred_at < b.t1),
    'shipment_status_history', (select count(*) from logistics.shipment_status_history x, b where x.occurred_at >= b.t0 and x.occurred_at < b.t1),
    'task_status_history',     (select count(*) from logistics.task_status_history x, b where x.occurred_at >= b.t0 and x.occurred_at < b.t1),
    'scan',                    (select count(*) from logistics.scan x, b where x.scanned_at >= b.t0 and x.scanned_at < b.t1),
    'incident',                (select count(*) from logistics.incident x, b where x.created_at >= b.t0 and x.created_at < b.t1),
    'support_ticket',          (select count(*) from logistics.support_ticket x, b where x.created_at >= b.t0 and x.created_at < b.t1),
    'customer',                (select count(*) from logistics.customer x, b where x.created_at >= b.t0 and x.created_at < b.t1),
    'revenue_entry',           (select count(*) from logistics.revenue_entry x where x.entry_date between p_from and p_to),
    'payment',                 (select count(*) from logistics.payment x, b where x.paid_at >= b.t0 and x.paid_at < b.t1),
    'refund',                  (select count(*) from logistics.refund x, b where x.created_at >= b.t0 and x.created_at < b.t1))
$$;

-- Enregistrer une exécution. p_actor null = le travailleur (la façade ses_an_refresh n'est ouverte qu'à la clé secrète).
create or replace function analytics.refresh(p_actor uuid, p_from date, p_to date, p_label text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_t timestamptz := clock_timestamp(); v_rows jsonb; v_run bigint; v_n int; v_today date := logistics.today();
begin
  if p_actor is not null then perform logistics.require_right(p_actor, 'direction'); end if;
  if p_from is null or p_to is null or p_to < p_from then raise exception 'Période invalide.' using errcode = 'LG005'; end if;
  if p_to > v_today then raise exception 'On ne calcule pas l''avenir : au plus tard aujourd''hui (%).', v_today using errcode = 'LG005'; end if;
  if p_to - p_from > 366 then raise exception 'Au plus 367 jours par calcul.' using errcode = 'LG005'; end if;
  select coalesce(jsonb_agg(jsonb_build_object('day', f.day, 'metric', f.metric, 'dimension', f.dimension, 'value', f.value)), '[]'::jsonb), count(*)
    into v_rows, v_n from analytics.compute_facts(p_from, p_to) f;
  insert into analytics.report_run (period_start, period_end, generated_by, generated_label, partial, row_count, checksum, source_watermark, duration_ms)
  values (p_from, p_to, p_actor, left(coalesce(p_label, ''), 120), p_to >= v_today, v_n, analytics.checksum(v_rows), analytics.source_watermark(p_from, p_to),
          (extract(epoch from clock_timestamp() - v_t) * 1000)::int)
  returning id into v_run;
  insert into analytics.daily_fact (run_id, day, metric, dimension, value)
  select v_run, (x ->> 'day')::date, x ->> 'metric', x ->> 'dimension', (x ->> 'value')::numeric from jsonb_array_elements(v_rows) x;
  return (select jsonb_build_object('run_id', r.id, 'period_start', r.period_start, 'period_end', r.period_end, 'rows', r.row_count, 'checksum', r.checksum,
                                    'partial', r.partial, 'duration_ms', r.duration_ms) from analytics.report_run r where r.id = v_run);
end;
$$;

-- Recalculer une exécution passée et comparer.
create or replace function analytics.verify_run(p_actor uuid, p_run bigint)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare r analytics.report_run; v_rows jsonb; v_sum text; v_wm jsonb;
begin
  perform logistics.require_right(p_actor, 'direction');
  select * into r from analytics.report_run where id = p_run;
  if not found then raise exception 'Exécution inconnue.' using errcode = 'LG002'; end if;
  select coalesce(jsonb_agg(jsonb_build_object('day', f.day, 'metric', f.metric, 'dimension', f.dimension, 'value', f.value)), '[]'::jsonb)
    into v_rows from analytics.compute_facts(r.period_start, r.period_end) f;
  v_sum := analytics.checksum(v_rows);
  v_wm := analytics.source_watermark(r.period_start, r.period_end);
  -- L'empreinte enregistrée est aussi recomparée à ses propres faits : une exécution dont les faits ne correspondent plus à l'empreinte
  -- aurait été altérée (les déclencheurs l'interdisent, ce contrôle le prouve).
  return jsonb_build_object('run_id', r.id, 'period_start', r.period_start, 'period_end', r.period_end, 'partial', r.partial,
    'checksum_then', r.checksum, 'checksum_now', v_sum, 'reproducible', v_sum = r.checksum,
    'stored_intact', r.checksum = analytics.checksum((select coalesce(jsonb_agg(jsonb_build_object('day', d.day, 'metric', d.metric, 'dimension', d.dimension, 'value', d.value)), '[]'::jsonb)
                                                       from analytics.daily_fact d where d.run_id = r.id)),
    'sources_changed', v_wm <> r.source_watermark,
    'verdict', case when v_sum = r.checksum then 'REPRODUCIBLE' when v_wm <> r.source_watermark then 'SOURCES_CHANGED' else 'COMPUTATION_CHANGED' end);
end;
$$;

-- 4. La lecture : seulement les mesures que ce compte a le droit de voir ---------------------------------------------------------------
create or replace function analytics.allowed_domains(p_actor uuid) returns text[] language sql stable set search_path = '' as $$
  select array_remove(array[case when logistics.actor_can(p_actor, 'colis.lire') then 'ops' end,
                            case when logistics.actor_can(p_actor, 'factures.lire') then 'finance' end,
                            case when logistics.actor_can(p_actor, 'clients.lire') then 'customers' end], null)
$$;

-- Le chiffre en vigueur d'un jour : celui de la dernière exécution réussie qui couvre ce jour.
create or replace function analytics.current_run_of(p_day date) returns bigint language sql stable set search_path = '' as $$
  select max(r.id) from analytics.report_run r where p_day between r.period_start and r.period_end
$$;

create or replace function analytics.report(p_actor uuid, p_grain text, p_from date, p_to date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_dom text[]; v_trunc text;
begin
  perform logistics.require_staff(p_actor);
  v_dom := analytics.allowed_domains(p_actor);
  if cardinality(v_dom) = 0 then raise exception 'Aucun droit de lecture sur les rapports.' using errcode = 'LG003'; end if;
  if p_grain is null or p_grain not in ('day', 'week', 'month', 'quarter', 'year') then raise exception 'Grain inconnu (day, week, month, quarter, year).' using errcode = 'LG005'; end if;
  if p_from is null or p_to is null or p_to < p_from or p_to - p_from > 3700 then raise exception 'Période invalide (dix ans au plus).' using errcode = 'LG005'; end if;
  v_trunc := p_grain;
  return (
    with jours as (select d::date as day, analytics.current_run_of(d::date) as run_id from generate_series(p_from, p_to, interval '1 day') d),
    faits as (
      select date_trunc(v_trunc, j.day::timestamp)::date as period, f.metric, f.dimension, sum(f.value) as value
        from jours j join analytics.daily_fact f on f.run_id = j.run_id and f.day = j.day
        join analytics.metric m on m.code = f.metric and m.domain = any (v_dom)
       group by 1, 2, 3
    ),
    execs as (select distinct j.run_id from jours j where j.run_id is not null)
    select jsonb_build_object(
      'grain', p_grain, 'from', p_from, 'to', p_to, 'domains', to_jsonb(v_dom),
      'rows', coalesce((select jsonb_agg(jsonb_build_object('period', x.period, 'metric', x.metric, 'dimension', x.dimension, 'value', x.value) order by x.period, x.metric, x.dimension) from faits x), '[]'::jsonb),
      -- les totaux d'une mesure par période, toutes dimensions confondues : l'écran les affiche sans rien additionner lui-même
      'totals', coalesce((select jsonb_agg(jsonb_build_object('period', y.period, 'metric', y.metric, 'value', y.value) order by y.period, y.metric)
                            from (select x.period, x.metric, sum(x.value) as value from faits x group by x.period, x.metric) y), '[]'::jsonb),
      'periods', (select jsonb_agg(x.period order by x.period) from (select distinct date_trunc(v_trunc, j.day::timestamp)::date as period from jours j) x),
      'metrics', (select jsonb_agg(jsonb_build_object('code', m.code, 'domain', m.domain, 'unit', m.unit, 'definition', m.definition) order by m.domain, m.code) from analytics.metric m where m.domain = any (v_dom)),
      'missing_days', coalesce((select jsonb_agg(j.day order by j.day) from jours j where j.run_id is null), '[]'::jsonb),
      'partial', exists (select 1 from execs e join analytics.report_run r on r.id = e.run_id where r.partial),
      'runs', coalesce((select jsonb_agg(jsonb_build_object('run_id', r.id, 'generated_at', r.generated_at, 'checksum', r.checksum, 'partial', r.partial) order by r.id)
                          from execs e join analytics.report_run r on r.id = e.run_id), '[]'::jsonb))
  );
end;
$$;

-- Les indicateurs d'une période et de la précédente de même longueur : les rapports, et non le navigateur, font les divisions.
create or replace function analytics.kpis(p_actor uuid, p_from date, p_to date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_dom text[]; v_len int;
begin
  perform logistics.require_staff(p_actor);
  v_dom := analytics.allowed_domains(p_actor);
  if cardinality(v_dom) = 0 then raise exception 'Aucun droit de lecture sur les rapports.' using errcode = 'LG003'; end if;
  if p_from is null or p_to is null or p_to < p_from or p_to - p_from > 3700 then raise exception 'Période invalide (dix ans au plus).' using errcode = 'LG005'; end if;
  v_len := p_to - p_from + 1;
  return (
    with periodes as (select 'current'::text as p, p_from as d0, p_to as d1 union all select 'previous', p_from - v_len, p_from - 1),
    tot as (
      select pe.p, f.metric, f.dimension, sum(f.value) as v
        from periodes pe cross join lateral generate_series(pe.d0, pe.d1, interval '1 day') g(d)
        join analytics.daily_fact f on f.day = g.d::date and f.run_id = analytics.current_run_of(g.d::date)
        join analytics.metric m on m.code = f.metric and m.domain = any (v_dom)
       group by pe.p, f.metric, f.dimension
    ),
    m as (select p, metric, sum(v) as v from tot group by p, metric),
    val as (select p.p, (select v from m where m.p = p.p and m.metric = k) as v, k from periodes p, unnest(array(select code from analytics.metric where domain = any (v_dom))) k),
    -- les rapports dérivés : seulement si leurs deux termes sont visibles
    derive as (
      select pe.p,
        case when 'ops' = any (v_dom) then
          (select round(100.0 * sum(v) filter (where metric = 'tasks_completed') / nullif(sum(v) filter (where metric in ('tasks_completed', 'tasks_failed')), 0), 1)
             from tot where tot.p = pe.p and tot.dimension = 'DELIVERY') end as delivery_success_pct,
        case when 'ops' = any (v_dom) then
          (select round(sum(v) filter (where metric = 'transit_hours_sum') / nullif(sum(v) filter (where metric = 'transit_count'), 0), 1) from tot where tot.p = pe.p) end as avg_transit_hours,
        case when 'ops' = any (v_dom) then
          (select round(100.0 * sum(v) filter (where metric = 'scans_rejected') / nullif(sum(v) filter (where metric = 'scans_total'), 0), 1) from tot where tot.p = pe.p) end as scan_rejection_pct,
        case when 'finance' = any (v_dom) then
          (select round(100.0 * sum(v) filter (where metric = 'payments_usd') / nullif(sum(v) filter (where metric = 'revenue_net_usd'), 0), 1) from tot where tot.p = pe.p) end as collection_pct
        from periodes pe
    )
    select jsonb_build_object('from', p_from, 'to', p_to, 'previous_from', p_from - v_len, 'previous_to', p_from - 1, 'domains', to_jsonb(v_dom),
      'current',  (select jsonb_object_agg(k, coalesce(v, 0)) from val where p = 'current'),
      'previous', (select jsonb_object_agg(k, coalesce(v, 0)) from val where p = 'previous'),
      'ratios_current',  (select to_jsonb(d) - 'p' from derive d where d.p = 'current'),
      'ratios_previous', (select to_jsonb(d) - 'p' from derive d where d.p = 'previous'),
      'missing_days', coalesce((select jsonb_agg(g.d::date order by g.d) from generate_series(p_from, p_to, interval '1 day') g(d) where analytics.current_run_of(g.d::date) is null), '[]'::jsonb))
  );
end;
$$;

create or replace function analytics.runs(p_actor uuid, p_limit int default 30)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_staff(p_actor);
  if cardinality(analytics.allowed_domains(p_actor)) = 0 then raise exception 'Aucun droit de lecture sur les rapports.' using errcode = 'LG003'; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('run_id', r.id, 'period_start', r.period_start, 'period_end', r.period_end, 'generated_at', r.generated_at,
                                                      'generated_by', case when r.generated_by is null then 'system' else coalesce((select a.email from auth.users a where a.id = r.generated_by), '') end,
                                                      'label', r.generated_label, 'partial', r.partial, 'rows', r.row_count, 'checksum', r.checksum, 'duration_ms', r.duration_ms) order by r.id desc)
                     from (select * from analytics.report_run order by id desc limit greatest(1, least(coalesce(p_limit, 30), 200))) r), '[]'::jsonb);
end;
$$;

-- 5. Les façades -----------------------------------------------------------------------------------------------------------------------
create or replace function public.lg_an_report(p_grain text, p_from date, p_to date)
returns jsonb language sql stable security definer set search_path = '' as $$ select analytics.report(auth.uid(), p_grain, p_from, p_to) $$;
create or replace function public.lg_an_kpis(p_from date, p_to date)
returns jsonb language sql stable security definer set search_path = '' as $$ select analytics.kpis(auth.uid(), p_from, p_to) $$;
create or replace function public.lg_an_runs(p_limit int default 30)
returns jsonb language sql stable security definer set search_path = '' as $$ select analytics.runs(auth.uid(), p_limit) $$;
create or replace function public.lg_an_refresh(p_from date, p_to date)
returns jsonb language sql volatile security definer set search_path = '' as $$
  select analytics.refresh(auth.uid(), p_from, p_to, coalesce((select a.email from auth.users a where a.id = auth.uid()), ''))
$$;
create or replace function public.lg_an_verify(p_run_id bigint)
returns jsonb language sql stable security definer set search_path = '' as $$ select analytics.verify_run(auth.uid(), p_run_id) $$;
-- Le travailleur planifié (clé secrète) : recalcule hier et aujourd'hui, ou une période donnée.
create or replace function public.ses_an_refresh(p_from date default null, p_to date default null)
returns jsonb language sql volatile security definer set search_path = '' as $$
  select analytics.refresh(null, coalesce(p_from, logistics.today() - 1), coalesce(p_to, logistics.today()), 'travailleur')
$$;

-- 6. Tout fermé, sauf la façade ----------------------------------------------------------------------------------------------------------
revoke all on all tables in schema analytics from public, anon, authenticated;
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'analytics' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\_an\_%' loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname = 'ses_an_refresh' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    if exists (select 1 from pg_roles where rolname = 'service_role') then execute format('grant execute on function %s to service_role', r.sig); end if;
  end loop;
end
$$;

-- Planifier (geste du propriétaire, pas automatique) : sur Supabase, extension pg_cron, puis
--   select cron.schedule('ses-analytique', '15 5 * * *', $$select public.ses_an_refresh()$$);   -- chaque nuit, 0 h 15 à Haïti en été
-- Pour retirer SEULEMENT cette étape : supprimer les fonctions public.lg_an_*, public.ses_an_refresh, puis le schéma analytics (ses tables
-- ne contiennent que des chiffres recalculables) ; les index ajoutés au schéma logistics peuvent rester.
