-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 29 : l'analytique complète, ses alertes et son recalcul planifié
-- -----------------------------------------------------------------------------
-- Phase 12 (monitoring, analytique et rapports). À passer APRÈS 028, par l'outil de migration (scripts/migration/migrer.py), qui fait la
-- sauvegarde vérifiée d'avant. Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- L'étape 012 a posé le chemin d'un chiffre : des faits QUOTIDIENS calculés par la base à partir des seuls journaux du noyau, chaque calcul
-- tracé (empreinte, état des sources) et vérifiable. Celle-ci le complète, sans rien changer à ce principe :
--
--   1. CINQ FAMILLES de mesures (opérations, transport, dernier kilomètre, finance, clientèle) : les colis en transit et en retard, les
--      scans par usage, les expéditions créées et à l'heure, leur délai, les livraisons par chauffeur, par zone et par tournée, les dépenses,
--      ce qui reste dû, les clients actifs et leur fréquence ;
--   2. trois façons d'agréger une mesure sur une période, déclarées dans le registre (analytics.metric.aggregation) et appliquées par la
--      base, jamais par l'écran :
--        · « sum »      : un flux (colis reçus) — la période est la somme de ses jours ;
--        · « end »      : un stock (colis en transit À LA FIN du jour) — la période vaut son DERNIER jour, jamais une somme ;
--        · « distinct » : des clients actifs — la période compte les clients DISTINCTS, pas la somme des jours (un client actif lundi
--                         et mardi est un client actif de la semaine, pas deux) ;
--   3. les indicateurs dérivés (taux, délais, facturé, marge, fréquence) calculés par la base pour chaque période d'un rapport ;
--   4. la traçabilité de chaque calcul : horodatage, SOURCE (à la main, planifié, travailleur), période, VERSION DE CALCUL (un numéro et
--      l'empreinte du code même qui a calculé), empreinte des faits, STATUT DE GÉNÉRATION (complet, provisoire, en échec) ; un calcul
--      planifié qui échoue est journalisé (analytics.run_failure), jamais perdu ;
--   5. les ALERTES (analytics.alert, en ajout seul, sans doublon) : KPI impossible, données manquantes, recalcul non exécuté ou en échec,
--      anomalie ; la direction les acquitte (analytics.alert_ack, en ajout seul) ;
--   6. le recalcul planifié : analytics.scheduled_refresh() (chaque nuit) et analytics.watch() (chaque heure), à installer par
--      scripts/exploitation/interrupteurs.py analytique-planifier (pg_cron, DANS la base, comme la recopie).
--
-- Rejouable sans risque ; aucune suppression ; rien n'est réécrit dans les faits ni dans les exécutions passées (ajout seul). Les jours
-- calculés par la version précédente restent lisibles et sont signalés « à recalculer » ; le recalcul planifié les reprend.
-- =============================================================================

-- 1. Le registre des mesures : la famille, l'agrégation, le genre de dimension ----------------------------------------------------------
alter table analytics.metric add column if not exists family text;
alter table analytics.metric add column if not exists aggregation text not null default 'sum';
alter table analytics.metric add column if not exists dimension_kind text not null default '';
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'metric_family_check') then
    alter table analytics.metric add constraint metric_family_check check (family in ('operations', 'transport', 'last_mile', 'finance', 'customers'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'metric_aggregation_check') then
    alter table analytics.metric add constraint metric_aggregation_check check (aggregation in ('sum', 'end', 'distinct'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'metric_dimension_kind_check') then
    alter table analytics.metric add constraint metric_dimension_kind_check check (dimension_kind in
      ('', 'mode', 'task_kind', 'warehouse', 'scan_purpose', 'incident_type', 'revenue_category', 'payment_method', 'expense_category', 'driver', 'zone', 'route', 'customer'));
  end if;
end
$$;

insert into analytics.metric (code, domain, unit, definition, family, aggregation, dimension_kind) values
  -- celles de 012, rangées dans leur famille (les expéditions sont désormais détaillées par mode)
  ('parcels_received',     'ops',       'count', 'Colis passés à RECEIVED ce jour-là (événements de suivi), par mode de service.', 'operations', 'sum', 'mode'),
  ('parcels_delivered',    'ops',       'count', 'Colis passés à DELIVERED ce jour-là, par mode de service.', 'operations', 'sum', 'mode'),
  ('parcels_on_hold',      'ops',       'count', 'Colis mis en attente (ON_HOLD) ce jour-là.', 'operations', 'sum', ''),
  ('parcels_damaged',      'ops',       'count', 'Colis déclarés endommagés (DAMAGED) ce jour-là.', 'operations', 'sum', ''),
  ('parcels_lost',         'ops',       'count', 'Colis déclarés perdus (LOST) ce jour-là.', 'operations', 'sum', ''),
  ('parcels_returned',     'ops',       'count', 'Colis retournés (RETURNED) ce jour-là.', 'operations', 'sum', ''),
  ('transit_hours_sum',    'ops',       'hours', 'Pour les colis livrés ce jour-là : somme des heures entre leur première réception et leur livraison, par mode.', 'operations', 'sum', 'mode'),
  ('transit_count',        'ops',       'count', 'Nombre de colis livrés ce jour-là dont la réception est connue (diviseur du délai moyen), par mode.', 'operations', 'sum', 'mode'),
  ('scans_total',          'ops',       'count', 'Scans enregistrés ce jour-là, par entrepôt.', 'operations', 'sum', 'warehouse'),
  ('scans_rejected',       'ops',       'count', 'Scans dont le verdict n''est pas ACCEPTED, par entrepôt.', 'operations', 'sum', 'warehouse'),
  ('incidents_opened',     'ops',       'count', 'Incidents ouverts ce jour-là, par type.', 'operations', 'sum', 'incident_type'),
  ('shipments_dispatched', 'ops',       'count', 'Expéditions passées à DISPATCHED ce jour-là, par mode.', 'transport', 'sum', 'mode'),
  ('shipments_arrived',    'ops',       'count', 'Expéditions passées à ARRIVED ce jour-là, par mode.', 'transport', 'sum', 'mode'),
  ('tasks_completed',      'ops',       'count', 'Missions terminées (COMPLETED) ce jour-là, par genre (PICKUP, DELIVERY).', 'last_mile', 'sum', 'task_kind'),
  ('tasks_failed',         'ops',       'count', 'Missions échouées (FAILED) ce jour-là, par genre.', 'last_mile', 'sum', 'task_kind'),
  ('tickets_opened',       'customers', 'count', 'Tickets de support ouverts ce jour-là.', 'customers', 'sum', ''),
  ('customers_new',        'customers', 'count', 'Fiches client créées ce jour-là.', 'customers', 'sum', ''),
  ('revenue_net_usd',      'finance',   'usd',   'Écritures de revenu (hors taxe) à cette date comptable, en dollars de base, par catégorie.', 'finance', 'sum', 'revenue_category'),
  ('revenue_tax_usd',      'finance',   'usd',   'Taxes des écritures de revenu à cette date comptable, en dollars de base.', 'finance', 'sum', ''),
  ('payments_usd',         'finance',   'usd',   'Paiements reçus ce jour-là, en dollars de base, par moyen.', 'finance', 'sum', 'payment_method'),
  ('payments_count',       'finance',   'count', 'Nombre de paiements reçus ce jour-là, par moyen.', 'finance', 'sum', 'payment_method'),
  ('refunds_usd',          'finance',   'usd',   'Remboursements faits ce jour-là, en dollars de base.', 'finance', 'sum', ''),
  -- opérations
  ('parcels_in_transit',   'ops',       'count', 'Colis EN TRANSIT à la fin du jour (minuit, heure d''Haïti) : leur dernier statut connu va du chargement (LOADED) à la sortie en livraison (OUT_FOR_DELIVERY), échec de livraison compris, par mode. Un stock : la période vaut son dernier jour.', 'operations', 'end', 'mode'),
  ('parcels_late',         'ops',       'count', 'Colis EN RETARD à la fin du jour : leur mission de livraison est encore ouverte alors que sa fenêtre promise (ou, sans fenêtre, sa journée prévue) est passée, par mode. Un stock : la période vaut son dernier jour.', 'operations', 'end', 'mode'),
  ('scans_by_purpose',     'ops',       'count', 'Scans enregistrés ce jour-là, par usage (réception, vérification, rangement, déplacement, consolidation, départ, recherche).', 'operations', 'sum', 'scan_purpose'),
  -- transport
  ('shipments_created',    'ops',       'count', 'Expéditions créées ce jour-là (premier statut DRAFT), par mode.', 'transport', 'sum', 'mode'),
  ('shipments_late',       'ops',       'count', 'Expéditions parties et pas encore arrivées à la fin du jour alors que l''arrivée prévue de leur transport est passée, par mode. Un stock : la période vaut son dernier jour.', 'transport', 'end', 'mode'),
  ('shipments_arrived_planned', 'ops',  'count', 'Expéditions arrivées ce jour-là dont le transport avait une arrivée prévue (diviseur de la ponctualité), par mode.', 'transport', 'sum', 'mode'),
  ('shipments_arrived_on_time', 'ops',  'count', 'Expéditions arrivées ce jour-là au plus tard à l''arrivée prévue de leur transport, par mode.', 'transport', 'sum', 'mode'),
  ('shipment_transit_hours_sum', 'ops', 'hours', 'Pour les expéditions arrivées ce jour-là : somme des heures depuis leur premier départ (DISPATCHED), par mode.', 'transport', 'sum', 'mode'),
  ('shipment_transit_count', 'ops',     'count', 'Expéditions arrivées ce jour-là dont le départ est connu (diviseur du délai moyen), par mode.', 'transport', 'sum', 'mode'),
  -- dernier kilomètre
  ('deliveries_completed_driver', 'ops', 'count', 'Livraisons réussies ce jour-là, par chauffeur affecté (vide : aucun chauffeur).', 'last_mile', 'sum', 'driver'),
  ('deliveries_failed_driver',    'ops', 'count', 'Livraisons échouées ce jour-là, par chauffeur affecté (vide : aucun chauffeur).', 'last_mile', 'sum', 'driver'),
  ('deliveries_completed_zone',   'ops', 'count', 'Livraisons réussies ce jour-là, par zone de livraison (vide : sans zone).', 'last_mile', 'sum', 'zone'),
  ('deliveries_failed_zone',      'ops', 'count', 'Livraisons échouées ce jour-là, par zone de livraison (vide : sans zone).', 'last_mile', 'sum', 'zone'),
  ('deliveries_completed_route',  'ops', 'count', 'Livraisons réussies ce jour-là, par tournée (code de la route de la tournée ; vide : hors tournée).', 'last_mile', 'sum', 'route'),
  ('deliveries_failed_route',     'ops', 'count', 'Livraisons échouées ce jour-là, par tournée (vide : hors tournée).', 'last_mile', 'sum', 'route'),
  ('deliveries_on_time',          'ops', 'count', 'Livraisons réussies ce jour-là et remises (heure de la preuve) avant la fin de leur fenêtre promise, ou de leur journée prévue sans fenêtre.', 'last_mile', 'sum', ''),
  -- finance
  ('expenses_usd',         'finance',   'usd',   'Dépenses engagées ce jour-là (non annulées), en dollars de base, par catégorie.', 'finance', 'sum', 'expense_category'),
  ('receivables_usd',      'finance',   'usd',   'Reste dû à la fin du jour : pour chaque facture, ses écritures de revenu (taxes comprises) moins ses paiements plus ses remboursements, jamais négatif, en dollars de base. Un stock : la période vaut son dernier jour.', 'finance', 'end', ''),
  -- clientèle
  ('customers_active',     'customers', 'count', 'Clients actifs : un événement de suivi sur un de leurs colis, un paiement ou un ticket ce jour-là. La période compte les clients DISTINCTS.', 'customers', 'distinct', 'customer'),
  ('customers_shipping',   'customers', 'count', 'Clients qui ont fait recevoir au moins un colis ce jour-là (valeur : leurs colis reçus). La période compte les clients DISTINCTS ; leur fréquence = colis reçus / clients.', 'customers', 'distinct', 'customer')
on conflict (code) do update set domain = excluded.domain, unit = excluded.unit, definition = excluded.definition, family = excluded.family,
                                 aggregation = excluded.aggregation, dimension_kind = excluded.dimension_kind;
do $$
begin
  if exists (select 1 from analytics.metric where family is null) then raise exception 'Une mesure sans famille.'; end if;
  alter table analytics.metric alter column family set not null;
end
$$;

-- 2. La traçabilité de chaque calcul -----------------------------------------------------------------------------------------------------
-- Colonnes nulles pour les exécutions d'avant (on n'y écrit rien : ajout seul) ; analytics.run_meta les lit.
alter table analytics.report_run add column if not exists calc_version text;
alter table analytics.report_run add column if not exists calc_fingerprint text;
alter table analytics.report_run add column if not exists source text;
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'report_run_source_check') then
    alter table analytics.report_run add constraint report_run_source_check check (source is null or source in ('manual', 'scheduler', 'worker'));
  end if;
end
$$;

-- Un calcul planifié en échec : journalisé, en ajout seul (le calcul lui-même n'a rien écrit).
create table if not exists analytics.run_failure (
  id            bigint generated always as identity primary key,
  attempted_at  timestamptz not null default now(),
  period_start  date,
  period_end    date,
  source        text not null check (source in ('manual', 'scheduler', 'worker')),
  calc_version  text not null,
  sqlstate      text not null default '',
  message       text not null default ''
);
drop trigger if exists run_failure_append_only on analytics.run_failure;
create trigger run_failure_append_only before update or delete on analytics.run_failure for each row execute function analytics.forbid_mutation();

-- La version du calcul : un numéro lisible, à monter avec compute_facts, et l'empreinte du code même (qui change seule si le code change).
create or replace function analytics.calc_version() returns text language sql immutable set search_path = '' as $$ select '029'::text $$;
create or replace function analytics.calc_fingerprint() returns text language sql stable set search_path = '' as $$
  select md5(pg_get_functiondef('analytics.compute_facts(date,date)'::regprocedure))
$$;

-- 3. Le calcul (version 029) : les mesures de 012, et les nouvelles -----------------------------------------------------------------------
-- Les stocks de fin de jour se lisent dans les mêmes journaux en ajout seul : le statut d'un colis, d'une mission ou d'une expédition « à
-- minuit » est le dernier de son historique avant minuit (heure d'Haïti). Seuls les rendez-vous (fenêtre d'une mission, arrivée prévue d'un
-- transport) sont lus tels qu'ils sont aujourd'hui : replanifier change donc, après coup, ce qui était « en retard » (verify_run le dira).
create or replace function analytics.compute_facts(p_from date, p_to date)
returns table (day date, metric text, dimension text, value numeric)
language sql stable set search_path = '' as $$
  with bornes as (select logistics.day_start(p_from) as t0, logistics.day_start(p_to + 1) as t1),
  jours as (select g.d::date as d, logistics.day_start(g.d::date + 1) as minuit from generate_series(p_from, p_to, interval '1 day') g(d)),
  te as (
    select analytics.day_of(e.occurred_at) as d, e.parcel_id, e.to_status, e.occurred_at, p.service_mode, p.customer_id
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
  -- les intervalles de statut d'un colis : [cet événement, le suivant)
  statuts_colis as (
    select e.parcel_id, p.service_mode, e.to_status, e.occurred_at as debut,
           lead(e.occurred_at) over (partition by e.parcel_id order by e.occurred_at, e.id) as fin
      from logistics.tracking_event e join logistics.parcel p on p.id = e.parcel_id, bornes b
     where e.to_status is not null and e.occurred_at < b.t1
  ),
  en_transit as (
    select j.d, s.service_mode, count(distinct s.parcel_id) as n
      from statuts_colis s join jours j on s.debut < j.minuit and (s.fin is null or s.fin >= j.minuit)
     where s.to_status in ('LOADED', 'IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY', 'FAILED_DELIVERY')
     group by j.d, s.service_mode
  ),
  -- les intervalles de statut d'une mission de livraison
  statuts_mission as (
    select h.task_id, h.to_status, h.occurred_at as debut,
           lead(h.occurred_at) over (partition by h.task_id order by h.occurred_at, h.id) as fin
      from logistics.task_status_history h join logistics.task t on t.id = h.task_id and t.kind = 'DELIVERY', bornes b
     where h.occurred_at < b.t1
  ),
  en_retard as (
    select j.d, p.service_mode, count(distinct p.id) as n
      from statuts_mission s join jours j on s.debut < j.minuit and (s.fin is null or s.fin >= j.minuit)
      join logistics.task t on t.id = s.task_id
      join logistics.delivery_parcel dp on dp.delivery_id = t.delivery_id
      join logistics.parcel p on p.id = dp.parcel_id
     where s.to_status in ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED')
       and coalesce(t.window_end, logistics.day_start(t.scheduled_date + 1)) <= j.minuit
     group by j.d, p.service_mode
  ),
  -- les intervalles de statut d'une expédition
  statuts_exp as (
    select h.shipment_id, h.to_status, h.occurred_at as debut,
           lead(h.occurred_at) over (partition by h.shipment_id order by h.occurred_at, h.id) as fin
      from logistics.shipment_status_history h, bornes b
     where h.occurred_at < b.t1
  ),
  exp_retard as (
    select j.d, s2.mode, count(distinct s.shipment_id) as n
      from statuts_exp s join jours j on s.debut < j.minuit and (s.fin is null or s.fin >= j.minuit)
      join logistics.shipment s2 on s2.id = s.shipment_id
      join logistics.transport tr on tr.id = s2.transport_id
     where s.to_status in ('DISPATCHED', 'IN_TRANSIT') and tr.planned_arrival_at is not null and tr.planned_arrival_at < j.minuit
     group by j.d, s2.mode
  ),
  -- les arrivées d'expéditions : la première de chaque expédition dans la journée
  arrivees as (
    select analytics.day_of(h.occurred_at) as d, h.shipment_id, min(h.occurred_at) as arrivee
      from logistics.shipment_status_history h, bornes b
     where h.occurred_at >= b.t0 and h.occurred_at < b.t1 and h.to_status = 'ARRIVED'
     group by 1, 2
  ),
  arrivees_detail as (
    select a.d, s.mode, a.arrivee, tr.planned_arrival_at as prevue,
           (select min(x.occurred_at) from logistics.shipment_status_history x where x.shipment_id = a.shipment_id and x.to_status = 'DISPATCHED' and x.occurred_at <= a.arrivee) as depart
      from arrivees a join logistics.shipment s on s.id = a.shipment_id
      left join logistics.transport tr on tr.id = s.transport_id
  ),
  -- les livraisons terminées ou échouées, avec chauffeur, zone, tournée et ponctualité
  fins_livraison as (
    select analytics.day_of(h.occurred_at) as d, h.task_id, h.to_status, t.driver_id, z.code as zone, r.code as route, t.window_end, t.scheduled_date
      from logistics.task_status_history h join logistics.task t on t.id = h.task_id and t.kind = 'DELIVERY'
      left join logistics.delivery_zone z on z.id = t.zone_id
      left join logistics.trip tp on tp.id = t.trip_id
      left join logistics.route r on r.id = tp.route_id, bornes b
     where h.occurred_at >= b.t0 and h.occurred_at < b.t1 and h.to_status in ('COMPLETED', 'FAILED')
  ),
  -- ce qui reste dû, facture par facture : écritures de revenu − paiements + remboursements, cumulés jusqu'à la fin du jour
  mouvements as (
    select r.invoice_id, r.entry_date as d, (r.net_base_usd + r.tax_base_usd) as m from logistics.revenue_entry r where r.entry_date <= p_to
    union all
    select y.invoice_id, analytics.day_of(y.paid_at), -y.base_amount_usd from logistics.payment y, bornes b where y.paid_at < b.t1
    union all
    select f.invoice_id, analytics.day_of(f.created_at), f.base_amount_usd from logistics.refund f, bornes b where f.created_at < b.t1
  ),
  soldes as (
    select j.d, sum(greatest(s.solde, 0)) as v
      from jours j cross join lateral (select m.invoice_id, sum(m.m) as solde from mouvements m where m.d <= j.d group by m.invoice_id) s
     group by j.d
  ),
  -- l'activité des clients
  activite as (
    select te.d, te.customer_id from te where te.customer_id is not null
    union
    select analytics.day_of(y.paid_at), y.customer_id from logistics.payment y, bornes b where y.paid_at >= b.t0 and y.paid_at < b.t1
    union
    select analytics.day_of(k.created_at), k.customer_id from logistics.support_ticket k, bornes b where k.created_at >= b.t0 and k.created_at < b.t1 and k.customer_id is not null
  ),
  faits as (
    -- ===== 012, inchangées (sauf les expéditions, désormais par mode)
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
    select analytics.day_of(h.occurred_at), case h.to_status when 'DISPATCHED' then 'shipments_dispatched' else 'shipments_arrived' end, s.mode, count(distinct h.shipment_id)
      from logistics.shipment_status_history h join logistics.shipment s on s.id = h.shipment_id, bornes b
     where h.occurred_at >= b.t0 and h.occurred_at < b.t1 and h.to_status in ('DISPATCHED', 'ARRIVED') group by 1, h.to_status, s.mode
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
    -- ===== 029 : opérations
    union all
    select d, 'parcels_in_transit', service_mode, n from en_transit
    union all
    select d, 'parcels_late', service_mode, n from en_retard
    union all
    select analytics.day_of(s.scanned_at), 'scans_by_purpose', s.purpose, count(*) from logistics.scan s, bornes b
     where s.scanned_at >= b.t0 and s.scanned_at < b.t1 group by 1, s.purpose
    -- ===== transport
    union all
    select analytics.day_of(h.occurred_at), 'shipments_created', s.mode, count(distinct h.shipment_id)
      from logistics.shipment_status_history h join logistics.shipment s on s.id = h.shipment_id, bornes b
     where h.occurred_at >= b.t0 and h.occurred_at < b.t1 and h.from_status is null and h.to_status = 'DRAFT' group by 1, s.mode
    union all
    select d, 'shipments_late', mode, n from exp_retard
    union all
    select d, 'shipments_arrived_planned', mode, count(*) from arrivees_detail where prevue is not null group by d, mode
    union all
    select d, 'shipments_arrived_on_time', mode, count(*) from arrivees_detail where prevue is not null and arrivee <= prevue group by d, mode
    union all
    select d, 'shipment_transit_hours_sum', mode, round(sum(extract(epoch from arrivee - depart) / 3600.0)::numeric, 4) from arrivees_detail where depart is not null group by d, mode
    union all
    select d, 'shipment_transit_count', mode, count(*) from arrivees_detail where depart is not null group by d, mode
    -- ===== dernier kilomètre
    union all
    select d, case to_status when 'COMPLETED' then 'deliveries_completed_driver' else 'deliveries_failed_driver' end, coalesce(driver_id::text, ''), count(distinct task_id)
      from fins_livraison group by d, to_status, driver_id
    union all
    select d, case to_status when 'COMPLETED' then 'deliveries_completed_zone' else 'deliveries_failed_zone' end, coalesce(zone, ''), count(distinct task_id)
      from fins_livraison group by d, to_status, zone
    union all
    select d, case to_status when 'COMPLETED' then 'deliveries_completed_route' else 'deliveries_failed_route' end, coalesce(route, ''), count(distinct task_id)
      from fins_livraison group by d, to_status, route
    union all
    select fl.d, 'deliveries_on_time', '', count(distinct fl.task_id)
      from fins_livraison fl join logistics.proof_of_delivery pod on pod.task_id = fl.task_id
     where fl.to_status = 'COMPLETED' and coalesce(pod.captured_at, pod.delivered_at) <= coalesce(fl.window_end, logistics.day_start(fl.scheduled_date + 1))
     group by fl.d
    -- ===== finance
    union all
    select x.incurred_on, 'expenses_usd', x.category, sum(x.base_amount_usd) from logistics.expense x
     where x.incurred_on between p_from and p_to and x.status = 'RECORDED' group by x.incurred_on, x.category
    union all
    select d, 'receivables_usd', '', v from soldes
    -- ===== clientèle
    union all
    select d, 'customers_active', customer_id::text, 1 from activite
    union all
    select d, 'customers_shipping', customer_id::text, count(distinct parcel_id) from te where to_status = 'RECEIVED' and customer_id is not null group by d, customer_id
  )
  -- Des valeurs nulles ne s'écrivent pas : un jour sans activité n'a pas de ligne, mais il A une exécution (il est « calculé »).
  select d, metric, dimension, round(value, 4) from faits where value <> 0 and d between p_from and p_to
$$;

-- L'état des sources : 012 comptait les lignes de la période ; les stocks lisent aussi l'historique d'avant, compté jusqu'à la fin de la période.
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
    'refund',                  (select count(*) from logistics.refund x, b where x.created_at >= b.t0 and x.created_at < b.t1),
    -- 029
    'tracking_event_to_end',   (select count(*) from logistics.tracking_event x, b where x.occurred_at < b.t1),
    'task_history_to_end',     (select count(*) from logistics.task_status_history x, b where x.occurred_at < b.t1),
    'shipment_history_to_end', (select count(*) from logistics.shipment_status_history x, b where x.occurred_at < b.t1),
    'revenue_entry_to_end',    (select count(*) from logistics.revenue_entry x where x.entry_date <= p_to),
    'payment_to_end',          (select count(*) from logistics.payment x, b where x.paid_at < b.t1),
    'refund_to_end',           (select count(*) from logistics.refund x, b where x.created_at < b.t1),
    'expense',                 (select count(*) from logistics.expense x where x.incurred_on between p_from and p_to),
    'expense_voided',          (select count(*) from logistics.expense x where x.incurred_on between p_from and p_to and x.status = 'VOIDED'),
    'proof_of_delivery',       (select count(*) from logistics.proof_of_delivery x, b where x.delivered_at < b.t1))
$$;

-- 4. Les alertes : en ajout seul, sans doublon (une clé par fait signalé), acquittées par la direction --------------------------------------
create table if not exists analytics.alert (
  id          bigint generated always as identity primary key,
  raised_at   timestamptz not null default now(),
  code        text not null check (code in ('KPI_IMPOSSIBLE', 'DATA_MISSING', 'REFRESH_NOT_RUN', 'REFRESH_FAILED', 'ANOMALY')),
  severity    text not null check (severity in ('WARN', 'FAIL')),
  domain      text not null check (domain in ('ops', 'finance', 'customers', 'system')),
  subject     text not null check (subject ~ '^[a-z_]{2,60}$'),
  day         date,
  detail      jsonb not null default '{}'::jsonb,
  run_id      bigint references analytics.report_run (id) on delete restrict,
  dedupe_key  text not null unique
);
create index if not exists alert_raised_idx on analytics.alert (raised_at desc);
drop trigger if exists alert_append_only on analytics.alert;
create trigger alert_append_only before update or delete on analytics.alert for each row execute function analytics.forbid_mutation();

create table if not exists analytics.alert_ack (
  alert_id  bigint primary key references analytics.alert (id) on delete restrict,
  acked_by  uuid not null,
  acked_at  timestamptz not null default now(),
  note      text not null default '' check (length(note) <= 300)
);
drop trigger if exists alert_ack_append_only on analytics.alert_ack;
create trigger alert_ack_append_only before update or delete on analytics.alert_ack for each row execute function analytics.forbid_mutation();

create or replace function analytics.raise_alert(p_code text, p_severity text, p_domain text, p_subject text, p_day date, p_detail jsonb, p_run bigint, p_key text)
returns boolean language plpgsql volatile security definer set search_path = '' as $$
declare v_id bigint;
begin
  insert into analytics.alert (code, severity, domain, subject, day, detail, run_id, dedupe_key)
  values (p_code, p_severity, p_domain, p_subject, p_day, coalesce(p_detail, '{}'::jsonb), p_run, p_key)
  on conflict (dedupe_key) do nothing returning id into v_id;
  return v_id is not null;
end;
$$;

-- Les seuils d'une anomalie : un écart à la moyenne des 28 jours précédents de plus de 3 écarts-types ET d'au moins ce plancher (un petit
-- volume ne crie pas au loup), avec au moins 14 jours d'historique calculé.
create or replace function analytics.anomaly_floor(p_unit text) returns numeric language sql immutable set search_path = '' as $$
  select case p_unit when 'usd' then 100 when 'hours' then 24 else 5 end::numeric
$$;

-- Ce qu'un calcul révèle, sur ses jours CLOS (aujourd'hui, provisoire, n'alerte pas) : KPI impossible, données manquantes, anomalie.
create or replace function analytics.detect(p_run bigint)
returns int language plpgsql volatile security definer set search_path = '' as $$
declare r analytics.report_run; v_today date := logistics.today(); v_n int := 0; x record;
begin
  select * into r from analytics.report_run where id = p_run;
  if not found then return 0; end if;
  -- les totaux par jour clos de cette exécution
  for x in
    with t as (
      select f.day, f.metric, sum(f.value) as v, sum(f.value) filter (where f.dimension = '') as v_vide, sum(f.value) filter (where f.dimension = 'DELIVERY') as v_liv
        from analytics.daily_fact f where f.run_id = p_run and f.day < v_today group by f.day, f.metric),
    j as (select g.d::date as day from generate_series(r.period_start, least(r.period_end, v_today - 1), interval '1 day') g(d)),
    p as (
      select j.day,
        coalesce((select v from t where t.day = j.day and t.metric = 'parcels_delivered'), 0) as livres,
        coalesce((select v from t where t.day = j.day and t.metric = 'transit_count'), 0) as livres_mesures,
        coalesce((select v from t where t.day = j.day and t.metric = 'payments_usd'), 0) as paye,
        coalesce((select v from t where t.day = j.day and t.metric = 'revenue_net_usd'), 0) as revenu,
        coalesce((select v from t where t.day = j.day and t.metric = 'expenses_usd'), 0) as depense,
        coalesce((select v from t where t.day = j.day and t.metric = 'shipments_arrived'), 0) as arrivees,
        coalesce((select v from t where t.day = j.day and t.metric = 'shipments_arrived_planned'), 0) as arrivees_prevues,
        coalesce((select v_vide from t where t.day = j.day and t.metric = 'deliveries_completed_driver'), 0) as sans_chauffeur
      from j)
    select * from p
  loop
    if x.livres > 0 and x.livres_mesures = 0 then
      v_n := v_n + analytics.raise_alert('KPI_IMPOSSIBLE', 'WARN', 'ops', 'avg_transit_hours', x.day, jsonb_build_object('delivered', x.livres), p_run, 'KPI_IMPOSSIBLE|avg_transit_hours|' || x.day)::int;
    elsif x.livres > x.livres_mesures then
      v_n := v_n + analytics.raise_alert('DATA_MISSING', 'WARN', 'ops', 'delivered_without_reception', x.day, jsonb_build_object('count', x.livres - x.livres_mesures), p_run, 'DATA_MISSING|delivered_without_reception|' || x.day)::int;
    end if;
    if x.paye > 0 and x.revenu = 0 then
      v_n := v_n + analytics.raise_alert('KPI_IMPOSSIBLE', 'WARN', 'finance', 'collection_pct', x.day, jsonb_build_object('payments_usd', x.paye), p_run, 'KPI_IMPOSSIBLE|collection_pct|' || x.day)::int;
    end if;
    if x.depense > 0 and x.revenu = 0 then
      v_n := v_n + analytics.raise_alert('KPI_IMPOSSIBLE', 'WARN', 'finance', 'margin_pct', x.day, jsonb_build_object('expenses_usd', x.depense), p_run, 'KPI_IMPOSSIBLE|margin_pct|' || x.day)::int;
    end if;
    if x.arrivees > 0 and x.arrivees_prevues = 0 then
      v_n := v_n + analytics.raise_alert('KPI_IMPOSSIBLE', 'WARN', 'ops', 'shipment_on_time_pct', x.day, jsonb_build_object('arrived', x.arrivees), p_run, 'KPI_IMPOSSIBLE|shipment_on_time_pct|' || x.day)::int;
    end if;
    if x.sans_chauffeur > 0 then
      v_n := v_n + analytics.raise_alert('DATA_MISSING', 'WARN', 'ops', 'deliveries_without_driver', x.day, jsonb_build_object('count', x.sans_chauffeur), p_run, 'DATA_MISSING|deliveries_without_driver|' || x.day)::int;
    end if;
  end loop;
  -- les anomalies : chaque jour clos de l'exécution comparé aux 28 jours calculés qui le précèdent
  for x in
    with serie as (
      select g.d::date as day, analytics.current_run_of(g.d::date) as run_id
        from generate_series(r.period_start - 28, least(r.period_end, v_today - 1), interval '1 day') g(d)),
    mesures as (select code, unit, domain from analytics.metric
                 where code in ('parcels_received', 'parcels_delivered', 'parcels_damaged', 'parcels_lost', 'tasks_failed', 'scans_rejected', 'incidents_opened',
                                'payments_usd', 'revenue_net_usd', 'refunds_usd', 'expenses_usd')),
    v as (
      select s.day, m.code, m.unit, m.domain,
             case when s.run_id is null then null else coalesce((select sum(f.value) from analytics.daily_fact f where f.run_id = s.run_id and f.day = s.day and f.metric = m.code), 0) end as val
        from serie s cross join mesures m),
    w as (
      select v.*, avg(val) over fen as moyenne, stddev_pop(val) over fen as ecart, count(val) over fen as n
        from v window fen as (partition by code order by day rows between 28 preceding and 1 preceding))
    select * from w
     where day between r.period_start and least(r.period_end, v_today - 1) and val is not null and n >= 14
       and abs(val - moyenne) > greatest(3 * coalesce(ecart, 0), analytics.anomaly_floor(unit))
  loop
    v_n := v_n + analytics.raise_alert('ANOMALY', 'WARN', x.domain, x.code, x.day,
                                       jsonb_build_object('value', x.val, 'mean', round(x.moyenne, 2), 'stddev', round(coalesce(x.ecart, 0), 2), 'days', x.n),
                                       p_run, 'ANOMALY|' || x.code || '|' || x.day)::int;
  end loop;
  return v_n;
end;
$$;

-- 5. Enregistrer un calcul : tracé (source, version, empreinte du code), puis ce qu'il révèle --------------------------------------------
create or replace function analytics.refresh_as(p_actor uuid, p_from date, p_to date, p_label text, p_source text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_t timestamptz := clock_timestamp(); v_rows jsonb; v_run bigint; v_n int; v_today date := logistics.today(); v_alertes int;
begin
  if p_source is null or p_source not in ('manual', 'scheduler', 'worker') then raise exception 'Source inconnue.' using errcode = 'LG005'; end if;
  if p_actor is not null then perform logistics.require_right(p_actor, 'direction'); end if;
  if p_from is null or p_to is null or p_to < p_from then raise exception 'Période invalide.' using errcode = 'LG005'; end if;
  if p_to > v_today then raise exception 'On ne calcule pas l''avenir : au plus tard aujourd''hui (%).', v_today using errcode = 'LG005'; end if;
  if p_to - p_from > 366 then raise exception 'Au plus 367 jours par calcul.' using errcode = 'LG005'; end if;
  select coalesce(jsonb_agg(jsonb_build_object('day', f.day, 'metric', f.metric, 'dimension', f.dimension, 'value', f.value)), '[]'::jsonb), count(*)
    into v_rows, v_n from analytics.compute_facts(p_from, p_to) f;
  insert into analytics.report_run (period_start, period_end, generated_by, generated_label, partial, row_count, checksum, source_watermark, duration_ms,
                                    calc_version, calc_fingerprint, source)
  values (p_from, p_to, p_actor, left(coalesce(p_label, ''), 120), p_to >= v_today, v_n, analytics.checksum(v_rows), analytics.source_watermark(p_from, p_to),
          (extract(epoch from clock_timestamp() - v_t) * 1000)::int, analytics.calc_version(), analytics.calc_fingerprint(), p_source)
  returning id into v_run;
  insert into analytics.daily_fact (run_id, day, metric, dimension, value)
  select v_run, (x ->> 'day')::date, x ->> 'metric', x ->> 'dimension', (x ->> 'value')::numeric from jsonb_array_elements(v_rows) x;
  v_alertes := analytics.detect(v_run);
  return (select jsonb_build_object('run_id', r.id, 'period_start', r.period_start, 'period_end', r.period_end, 'rows', r.row_count, 'checksum', r.checksum,
                                    'partial', r.partial, 'duration_ms', r.duration_ms, 'calc_version', r.calc_version, 'source', r.source,
                                    'status', case when r.partial then 'PROVISIONAL' else 'COMPLETE' end, 'alerts_raised', v_alertes)
            from analytics.report_run r where r.id = v_run);
end;
$$;

-- La porte de 012 garde sa signature (ops.schema_level la cherche) : la direction (« à la main ») ou le travailleur.
create or replace function analytics.refresh(p_actor uuid, p_from date, p_to date, p_label text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$
  select analytics.refresh_as(p_actor, p_from, p_to, p_label, case when p_actor is null then 'worker' else 'manual' end)
$$;

-- Les métadonnées d'une exécution, lisibles même pour celles d'avant 029 (colonnes nulles : version « 012 », source déduite).
create or replace function analytics.run_meta(r analytics.report_run) returns jsonb language sql stable set search_path = '' as $$
  select jsonb_build_object('run_id', r.id, 'period_start', r.period_start, 'period_end', r.period_end, 'generated_at', r.generated_at,
    'source', coalesce(r.source, case when r.generated_by is null then 'worker' else 'manual' end),
    'calc_version', coalesce(r.calc_version, '012'), 'calc_fingerprint', coalesce(r.calc_fingerprint, ''),
    'current_version', coalesce(r.calc_version, '012') = analytics.calc_version(),
    'checksum', r.checksum, 'partial', r.partial, 'status', case when r.partial then 'PROVISIONAL' else 'COMPLETE' end,
    'rows', r.row_count, 'duration_ms', r.duration_ms)
$$;

-- Recalculer une exécution passée et comparer — en disant aussi si la version du calcul a changé depuis.
create or replace function analytics.verify_run(p_actor uuid, p_run bigint)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare r analytics.report_run; v_rows jsonb; v_sum text; v_wm jsonb; v_meme_code boolean;
begin
  perform logistics.require_right(p_actor, 'direction');
  select * into r from analytics.report_run where id = p_run;
  if not found then raise exception 'Exécution inconnue.' using errcode = 'LG002'; end if;
  select coalesce(jsonb_agg(jsonb_build_object('day', f.day, 'metric', f.metric, 'dimension', f.dimension, 'value', f.value)), '[]'::jsonb)
    into v_rows from analytics.compute_facts(r.period_start, r.period_end) f;
  v_sum := analytics.checksum(v_rows);
  v_wm := analytics.source_watermark(r.period_start, r.period_end);
  v_meme_code := r.calc_fingerprint is not null and r.calc_fingerprint = analytics.calc_fingerprint();
  return jsonb_build_object('run_id', r.id, 'period_start', r.period_start, 'period_end', r.period_end, 'partial', r.partial,
    'checksum_then', r.checksum, 'checksum_now', v_sum, 'reproducible', v_sum = r.checksum,
    'stored_intact', r.checksum = analytics.checksum((select coalesce(jsonb_agg(jsonb_build_object('day', d.day, 'metric', d.metric, 'dimension', d.dimension, 'value', d.value)), '[]'::jsonb)
                                                       from analytics.daily_fact d where d.run_id = r.id)),
    'sources_changed', v_wm <> r.source_watermark,
    'calc_version_then', coalesce(r.calc_version, '012'), 'calc_version_now', analytics.calc_version(), 'same_code', v_meme_code,
    'verdict', case when v_sum = r.checksum then 'REPRODUCIBLE'
                    when not v_meme_code then 'VERSION_CHANGED'
                    when v_wm <> r.source_watermark then 'SOURCES_CHANGED'
                    else 'COMPUTATION_CHANGED' end);
end;
$$;

-- 6. La lecture : agréger selon la nature de chaque mesure ---------------------------------------------------------------------------------
-- Le chiffre en vigueur d'un jour : celui de la dernière exécution qui le couvre (inchangé ; les échecs ne sont pas des exécutions).
-- Les périodes d'un rapport : le grain calendaire (semaine ISO, mois, trimestre, année), ou « all » = toute la période d'un coup.
create or replace function analytics.aggregate(p_grain text, p_from date, p_to date, p_dom text[])
returns table (period date, metric text, dimension text, value numeric)
language sql stable set search_path = '' as $$
  with jours as (
    select g.d::date as day, analytics.current_run_of(g.d::date) as run_id,
           case when p_grain = 'all' then p_from else date_trunc(p_grain, g.d)::date end as period
      from generate_series(p_from, p_to, interval '1 day') g(d)),
  derniers as (select j.period, max(j.day) as dernier from jours j group by j.period),
  f as (
    select j.period, j.day, x.metric, x.dimension, x.value, m.aggregation
      from jours j join analytics.daily_fact x on x.run_id = j.run_id and x.day = j.day
      join analytics.metric m on m.code = x.metric and m.domain = any (p_dom))
  select f.period, f.metric, f.dimension, sum(f.value) from f where f.aggregation = 'sum' group by 1, 2, 3
  union all
  select f.period, f.metric, f.dimension, sum(f.value) from f join derniers d on d.period = f.period and d.dernier = f.day where f.aggregation = 'end' group by 1, 2, 3
  union all
  select f.period, f.metric, '', count(distinct f.dimension)::numeric from f where f.aggregation = 'distinct' group by 1, 2
$$;

-- La somme des valeurs d'une mesure « distinct » (les colis reçus des clients), pour la fréquence : jamais montrée par client.
create or replace function analytics.distinct_sums(p_grain text, p_from date, p_to date, p_dom text[])
returns table (period date, metric text, value numeric)
language sql stable set search_path = '' as $$
  select case when p_grain = 'all' then p_from else date_trunc(p_grain, g.d)::date end, x.metric, sum(x.value)
    from generate_series(p_from, p_to, interval '1 day') g(d)
    join analytics.daily_fact x on x.day = g.d::date and x.run_id = analytics.current_run_of(g.d::date)
    join analytics.metric m on m.code = x.metric and m.aggregation = 'distinct' and m.domain = any (p_dom)
   group by 1, 2
$$;

-- Les indicateurs dérivés d'une période, à partir de ses totaux (et de quelques détails par dimension) : seulement ceux dont les termes sont
-- visibles. null = impossible à calculer (division par zéro, ou stock inconnu) — jamais 0 en silence.
create or replace function analytics.pct(p_num numeric, p_den numeric) returns numeric language sql immutable set search_path = '' as $$
  select case when coalesce(p_den, 0) = 0 then null else round(100.0 * coalesce(p_num, 0) / p_den, 1) end
$$;
create or replace function analytics.ratio(p_num numeric, p_den numeric, p_digits int default 1) returns numeric language sql immutable set search_path = '' as $$
  select case when coalesce(p_den, 0) = 0 then null else round(coalesce(p_num, 0) / p_den, p_digits) end
$$;
create or replace function analytics.derive(p jsonb, p_dom text[]) returns jsonb language plpgsql immutable set search_path = '' as $$
declare r jsonb := '{}'::jsonb;
  n jsonb := coalesce(p, '{}'::jsonb);
begin
  if 'ops' = any (p_dom) then
    r := r || jsonb_build_object(
      'delivery_success_pct', analytics.pct((n ->> 'tasks_completed:DELIVERY')::numeric, coalesce((n ->> 'tasks_completed:DELIVERY')::numeric, 0) + coalesce((n ->> 'tasks_failed:DELIVERY')::numeric, 0)),
      'avg_transit_hours', analytics.ratio((n ->> 'transit_hours_sum')::numeric, (n ->> 'transit_count')::numeric),
      'scan_rejection_pct', analytics.pct((n ->> 'scans_rejected')::numeric, (n ->> 'scans_total')::numeric),
      'delivery_on_time_pct', analytics.pct((n ->> 'deliveries_on_time')::numeric, (n ->> 'tasks_completed:DELIVERY')::numeric),
      'shipment_on_time_pct', analytics.pct((n ->> 'shipments_arrived_on_time')::numeric, (n ->> 'shipments_arrived_planned')::numeric),
      'avg_shipment_transit_hours', analytics.ratio((n ->> 'shipment_transit_hours_sum')::numeric, (n ->> 'shipment_transit_count')::numeric));
  end if;
  if 'finance' = any (p_dom) then
    r := r || jsonb_build_object(
      'collection_pct', analytics.pct((n ->> 'payments_usd')::numeric, (n ->> 'revenue_net_usd')::numeric),
      'invoiced_usd', round(coalesce((n ->> 'revenue_net_usd')::numeric, 0) + coalesce((n ->> 'revenue_tax_usd')::numeric, 0), 2),
      'net_collected_usd', round(coalesce((n ->> 'payments_usd')::numeric, 0) - coalesce((n ->> 'refunds_usd')::numeric, 0), 2),
      'margin_usd', round(coalesce((n ->> 'revenue_net_usd')::numeric, 0) - coalesce((n ->> 'expenses_usd')::numeric, 0), 2),
      'margin_pct', analytics.pct(coalesce((n ->> 'revenue_net_usd')::numeric, 0) - coalesce((n ->> 'expenses_usd')::numeric, 0), (n ->> 'revenue_net_usd')::numeric));
  end if;
  if 'customers' = any (p_dom) then
    r := r || jsonb_build_object('parcels_per_customer', analytics.ratio((n ->> 'customers_shipping:sum')::numeric, (n ->> 'customers_shipping')::numeric, 2));
  end if;
  return r;
end;
$$;

-- Les entrées de derive pour chaque période : les totaux de chaque mesure, deux détails par genre de mission, la somme des « distinct ».
create or replace function analytics.derive_inputs(p_grain text, p_from date, p_to date, p_dom text[])
returns table (period date, inputs jsonb)
language sql stable set search_path = '' as $$
  with a as (select * from analytics.aggregate(p_grain, p_from, p_to, p_dom)),
  k as (
    select a.period, a.metric as cle, sum(a.value) as v from a group by a.period, a.metric
    union all
    select a.period, a.metric || ':' || a.dimension, a.value from a where a.metric in ('tasks_completed', 'tasks_failed') and a.dimension = 'DELIVERY'
    union all
    select s.period, s.metric || ':sum', s.value from analytics.distinct_sums(p_grain, p_from, p_to, p_dom) s)
  select k.period, jsonb_object_agg(k.cle, k.v) from k group by k.period
$$;

-- Les étiquettes lisibles des dimensions (chauffeur, zone, tournée) : la base les donne, l'écran ne devine rien.
create or replace function analytics.dimension_labels(p_rows jsonb) returns jsonb language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'driver', coalesce((select jsonb_object_agg(d.id::text, d.full_name) from logistics.driver d
                         where d.id::text in (select x ->> 'dimension' from jsonb_array_elements(p_rows) x where x ->> 'metric' like 'deliveries\_%\_driver')), '{}'::jsonb),
    'zone', coalesce((select jsonb_object_agg(z.code, z.name) from logistics.delivery_zone z
                       where z.code in (select x ->> 'dimension' from jsonb_array_elements(p_rows) x where x ->> 'metric' like 'deliveries\_%\_zone')), '{}'::jsonb),
    'route', coalesce((select jsonb_object_agg(r.code, r.name) from logistics.route r
                        where r.code in (select x ->> 'dimension' from jsonb_array_elements(p_rows) x where x ->> 'metric' like 'deliveries\_%\_route')), '{}'::jsonb))
$$;

-- Le détail du dernier kilomètre sur toute la période : réussies, échouées, taux de réussite, par chauffeur, par zone, par tournée.
create or replace function analytics.last_mile_breakdown(p_from date, p_to date) returns jsonb language sql stable set search_path = '' as $$
  with a as (select * from analytics.aggregate('all', p_from, p_to, array['ops'])),
  g as (
    select axe, a.dimension,
           sum(a.value) filter (where a.metric like 'deliveries\_completed\_%') as reussies,
           sum(a.value) filter (where a.metric like 'deliveries\_failed\_%') as echouees
      from a cross join lateral (select case when a.metric like '%\_driver' then 'driver' when a.metric like '%\_zone' then 'zone' else 'route' end as axe) x
     where a.metric like 'deliveries\_completed\_%' or a.metric like 'deliveries\_failed\_%'
     group by axe, a.dimension)
  select jsonb_build_object(
    'driver', coalesce((select jsonb_agg(jsonb_build_object('key', g.dimension, 'label', coalesce((select d.full_name from logistics.driver d where d.id::text = g.dimension), ''),
                                                           'completed', coalesce(g.reussies, 0), 'failed', coalesce(g.echouees, 0),
                                                           'success_pct', analytics.pct(g.reussies, coalesce(g.reussies, 0) + coalesce(g.echouees, 0))) order by coalesce(g.reussies, 0) + coalesce(g.echouees, 0) desc, g.dimension)
                         from g where g.axe = 'driver'), '[]'::jsonb),
    'zone', coalesce((select jsonb_agg(jsonb_build_object('key', g.dimension, 'label', coalesce((select z.name from logistics.delivery_zone z where z.code = g.dimension), ''),
                                                         'completed', coalesce(g.reussies, 0), 'failed', coalesce(g.echouees, 0),
                                                         'success_pct', analytics.pct(g.reussies, coalesce(g.reussies, 0) + coalesce(g.echouees, 0))) order by coalesce(g.reussies, 0) + coalesce(g.echouees, 0) desc, g.dimension)
                       from g where g.axe = 'zone'), '[]'::jsonb),
    'route', coalesce((select jsonb_agg(jsonb_build_object('key', g.dimension, 'label', coalesce((select r.name from logistics.route r where r.code = g.dimension), ''),
                                                          'completed', coalesce(g.reussies, 0), 'failed', coalesce(g.echouees, 0),
                                                          'success_pct', analytics.pct(g.reussies, coalesce(g.reussies, 0) + coalesce(g.echouees, 0))) order by coalesce(g.reussies, 0) + coalesce(g.echouees, 0) desc, g.dimension)
                        from g where g.axe = 'route'), '[]'::jsonb))
$$;

-- Le rapport : périodes, lignes, totaux, indicateurs dérivés PAR PÉRIODE, détail du dernier kilomètre, et tout ce qui dit d'où il vient.
create or replace function analytics.report(p_actor uuid, p_grain text, p_from date, p_to date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_dom text[]; v_rows jsonb; v_totals jsonb; v_missing jsonb; v_runs jsonb; v_stale jsonb; v_out jsonb;
begin
  perform logistics.require_staff(p_actor);
  v_dom := analytics.allowed_domains(p_actor);
  if cardinality(v_dom) = 0 then raise exception 'Aucun droit de lecture sur les rapports.' using errcode = 'LG003'; end if;
  if p_grain is null or p_grain not in ('day', 'week', 'month', 'quarter', 'year') then raise exception 'Grain inconnu (day, week, month, quarter, year).' using errcode = 'LG005'; end if;
  if p_from is null or p_to is null or p_to < p_from or p_to - p_from > 3700 then raise exception 'Période invalide (dix ans au plus).' using errcode = 'LG005'; end if;

  with a as (select * from analytics.aggregate(p_grain, p_from, p_to, v_dom))
  -- les lignes par dimension ; jamais par client (une mesure « distinct » n'a qu'une ligne : le nombre de clients)
  select coalesce(jsonb_agg(jsonb_build_object('period', a.period, 'metric', a.metric, 'dimension', a.dimension, 'value', a.value) order by a.period, a.metric, a.dimension), '[]'::jsonb)
    into v_rows from a;
  with jours as (select g.d::date as day, analytics.current_run_of(g.d::date) as run_id,
                        date_trunc(p_grain, g.d)::date as period from generate_series(p_from, p_to, interval '1 day') g(d)),
  derniers as (select period, max(day) as dernier from jours group by period),
  inconnus as (select d.period from derniers d join jours j on j.day = d.dernier where j.run_id is null),
  t as (select x.period, x.metric, sum(x.value) as value from analytics.aggregate(p_grain, p_from, p_to, v_dom) x group by x.period, x.metric
        union all
        -- un stock dont le dernier jour de la période n'a jamais été calculé : inconnu (null), pas zéro
        select i.period, m.code, null from inconnus i cross join analytics.metric m where m.aggregation = 'end' and m.domain = any (v_dom))
  select coalesce(jsonb_agg(jsonb_build_object('period', t.period, 'metric', t.metric, 'value', t.value) order by t.period, t.metric), '[]'::jsonb) into v_totals from t;
  select coalesce(jsonb_agg(g.d::date order by g.d), '[]'::jsonb) into v_missing
    from generate_series(p_from, p_to, interval '1 day') g(d) where analytics.current_run_of(g.d::date) is null;
  -- les jours calculés par une version antérieure du calcul : lisibles, mais à recalculer (les nouvelles mesures y manquent)
  select coalesce(jsonb_agg(g.d::date order by g.d), '[]'::jsonb) into v_stale
    from generate_series(p_from, p_to, interval '1 day') g(d) join analytics.report_run r on r.id = analytics.current_run_of(g.d::date)
   where coalesce(r.calc_version, '012') <> analytics.calc_version();
  select coalesce(jsonb_agg(analytics.run_meta(r) order by r.id), '[]'::jsonb) into v_runs
    from analytics.report_run r where r.id in (select distinct analytics.current_run_of(g.d::date) from generate_series(p_from, p_to, interval '1 day') g(d));

  v_out := jsonb_build_object(
    'grain', p_grain, 'from', p_from, 'to', p_to, 'domains', to_jsonb(v_dom),
    'rows', v_rows, 'totals', v_totals,
    'periods', (select jsonb_agg(x.period order by x.period) from (select distinct date_trunc(p_grain, g.d)::date as period from generate_series(p_from, p_to, interval '1 day') g(d)) x),
    'derived', coalesce((select jsonb_agg(jsonb_build_object('period', d.period, 'values', analytics.derive(d.inputs, v_dom)) order by d.period)
                           from analytics.derive_inputs(p_grain, p_from, p_to, v_dom) d), '[]'::jsonb),
    'metrics', (select jsonb_agg(jsonb_build_object('code', m.code, 'domain', m.domain, 'family', m.family, 'unit', m.unit, 'aggregation', m.aggregation,
                                                    'dimension_kind', m.dimension_kind, 'definition', m.definition) order by m.domain, m.code)
                  from analytics.metric m where m.domain = any (v_dom)),
    'labels', analytics.dimension_labels(v_rows),
    'breakdown', case when 'ops' = any (v_dom) then analytics.last_mile_breakdown(p_from, p_to) else null end,
    'missing_days', v_missing, 'stale_days', v_stale,
    'partial', exists (select 1 from jsonb_array_elements(v_runs) x where (x ->> 'partial')::boolean),
    'runs', v_runs);
  -- l'en-tête du rapport : quand, quelle version, son empreinte (celle des lignes et des totaux), son statut, ses sources
  return v_out || jsonb_build_object(
    'generated_at', now(), 'calc_version', analytics.calc_version(),
    'report_checksum', md5(v_rows::text || '|' || v_totals::text),
    'status', case when jsonb_array_length(v_missing) > 0 then 'INCOMPLETE' when jsonb_array_length(v_stale) > 0 then 'OUTDATED'
                   when (v_out ->> 'partial')::boolean then 'PROVISIONAL' else 'COMPLETE' end,
    'sources', to_jsonb(array['logistics.tracking_event', 'logistics.shipment_status_history', 'logistics.task_status_history', 'logistics.scan', 'logistics.incident',
                              'logistics.revenue_entry', 'logistics.payment', 'logistics.refund', 'logistics.expense', 'logistics.proof_of_delivery',
                              'logistics.support_ticket', 'logistics.customer']));
end;
$$;

-- Les indicateurs : la période et la précédente de même longueur, chaque mesure agrégée selon sa nature, les dérivés par la base.
create or replace function analytics.kpis(p_actor uuid, p_from date, p_to date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_dom text[]; v_len int; v_cur jsonb; v_pre jsonb; v_ic jsonb; v_ip jsonb;
begin
  perform logistics.require_staff(p_actor);
  v_dom := analytics.allowed_domains(p_actor);
  if cardinality(v_dom) = 0 then raise exception 'Aucun droit de lecture sur les rapports.' using errcode = 'LG003'; end if;
  if p_from is null or p_to is null or p_to < p_from or p_to - p_from > 3700 then raise exception 'Période invalide (dix ans au plus).' using errcode = 'LG005'; end if;
  v_len := p_to - p_from + 1;
  -- chaque mesure visible : sa valeur sur la période (0 si aucune activité ; null si c'est un stock et que le dernier jour n'est pas calculé)
  with a as (select x.metric, sum(x.value) as v from analytics.aggregate('all', p_from, p_to, v_dom) x group by x.metric)
  select jsonb_object_agg(m.code, case when m.aggregation = 'end' and analytics.current_run_of(p_to) is null then null
                                       else coalesce((select a.v from a where a.metric = m.code), 0) end)
    into v_cur from analytics.metric m where m.domain = any (v_dom);
  with a as (select x.metric, sum(x.value) as v from analytics.aggregate('all', p_from - v_len, p_from - 1, v_dom) x group by x.metric)
  select jsonb_object_agg(m.code, case when m.aggregation = 'end' and analytics.current_run_of(p_from - 1) is null then null
                                       else coalesce((select a.v from a where a.metric = m.code), 0) end)
    into v_pre from analytics.metric m where m.domain = any (v_dom);
  select d.inputs into v_ic from analytics.derive_inputs('all', p_from, p_to, v_dom) d;
  select d.inputs into v_ip from analytics.derive_inputs('all', p_from - v_len, p_from - 1, v_dom) d;
  return jsonb_build_object('from', p_from, 'to', p_to, 'previous_from', p_from - v_len, 'previous_to', p_from - 1, 'domains', to_jsonb(v_dom),
    'current', v_cur, 'previous', v_pre,
    'ratios_current', analytics.derive(v_ic, v_dom), 'ratios_previous', analytics.derive(v_ip, v_dom),
    'missing_days', coalesce((select jsonb_agg(g.d::date order by g.d) from generate_series(p_from, p_to, interval '1 day') g(d) where analytics.current_run_of(g.d::date) is null), '[]'::jsonb),
    'generated_at', now(), 'calc_version', analytics.calc_version());
end;
$$;

create or replace function analytics.runs(p_actor uuid, p_limit int default 30)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_staff(p_actor);
  if cardinality(analytics.allowed_domains(p_actor)) = 0 then raise exception 'Aucun droit de lecture sur les rapports.' using errcode = 'LG003'; end if;
  return coalesce((select jsonb_agg(analytics.run_meta(r) || jsonb_build_object(
                     'generated_by', case when r.generated_by is null then 'system' else coalesce((select a.email from auth.users a where a.id = r.generated_by), '') end,
                     'label', r.generated_label, 'alerts', (select count(*) from analytics.alert x where x.run_id = r.id)) order by r.id desc)
                     from analytics.report_run r
                    where r.id in (select x.id from analytics.report_run x order by x.id desc limit greatest(1, least(coalesce(p_limit, 30), 200)))), '[]'::jsonb);
end;
$$;

-- 7. Les alertes, vues et acquittées -----------------------------------------------------------------------------------------------------
-- Visibles par domaine (une alerte « système » : par toute l'équipe qui lit des rapports) ; ouvertes = pas encore acquittées.
create or replace function analytics.alerts(p_actor uuid, p_all boolean default false)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_dom text[];
begin
  perform logistics.require_staff(p_actor);
  v_dom := analytics.allowed_domains(p_actor);
  if cardinality(v_dom) = 0 then raise exception 'Aucun droit de lecture sur les rapports.' using errcode = 'LG003'; end if;
  return jsonb_build_object(
    'open', (select count(*) from analytics.alert a where (a.domain = 'system' or a.domain = any (v_dom)) and not exists (select 1 from analytics.alert_ack k where k.alert_id = a.id)),
    'items', coalesce((select jsonb_agg(jsonb_build_object('id', a.id, 'raised_at', a.raised_at, 'code', a.code, 'severity', a.severity, 'domain', a.domain,
                                                         'subject', a.subject, 'day', a.day, 'detail', a.detail, 'run_id', a.run_id,
                                                         'acked_at', k.acked_at, 'note', k.note) order by a.id desc)
                         from (select * from analytics.alert a2 where (a2.domain = 'system' or a2.domain = any (v_dom))
                                  and (p_all or not exists (select 1 from analytics.alert_ack k2 where k2.alert_id = a2.id))
                                order by a2.id desc limit 200) a
                         left join analytics.alert_ack k on k.alert_id = a.id), '[]'::jsonb));
end;
$$;

create or replace function analytics.ack_alert(p_actor uuid, p_alert bigint, p_note text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'direction');
  if not exists (select 1 from analytics.alert where id = p_alert) then raise exception 'Alerte inconnue.' using errcode = 'LG002'; end if;
  if length(coalesce(p_note, '')) > 300 then raise exception 'Note trop longue (300 caractères au plus).' using errcode = 'LG005'; end if;
  insert into analytics.alert_ack (alert_id, acked_by, note) values (p_alert, p_actor, btrim(coalesce(p_note, ''))) on conflict (alert_id) do nothing;
  return (select jsonb_build_object('id', k.alert_id, 'acked_at', k.acked_at, 'note', k.note) from analytics.alert_ack k where k.alert_id = p_alert);
end;
$$;

-- 8. La veille et le recalcul planifié ----------------------------------------------------------------------------------------------------
-- La veille (chaque heure) : un recalcul qui n'a pas eu lieu, des jours clos jamais calculés ou calculés par une ancienne version.
create or replace function analytics.watch() returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_today date := logistics.today(); v_dernier timestamptz; v_h numeric; v_n int := 0; x record;
begin
  select max(generated_at) into v_dernier from analytics.report_run;
  v_h := case when v_dernier is null then null else round(extract(epoch from now() - v_dernier) / 3600, 1) end;
  if v_h is null or v_h >= 26 then
    v_n := v_n + analytics.raise_alert('REFRESH_NOT_RUN', case when v_h is null or v_h >= 72 then 'FAIL' else 'WARN' end, 'system', 'refresh', v_today,
                                       jsonb_build_object('hours_since_last', v_h), null, 'REFRESH_NOT_RUN|' || v_today)::int;
  end if;
  for x in select g.d::date as day, analytics.current_run_of(g.d::date) as run_id from generate_series(v_today - 7, v_today - 1, interval '1 day') g(d) loop
    if x.run_id is null then
      v_n := v_n + analytics.raise_alert('DATA_MISSING', 'WARN', 'system', 'day_not_computed', x.day, '{}'::jsonb, null, 'DATA_MISSING|day_not_computed|' || x.day)::int;
    elsif (select coalesce(r.calc_version, '012') from analytics.report_run r where r.id = x.run_id) <> analytics.calc_version() then
      v_n := v_n + analytics.raise_alert('DATA_MISSING', 'WARN', 'system', 'day_outdated', x.day, '{}'::jsonb, x.run_id, 'DATA_MISSING|day_outdated|' || x.day || '|' || analytics.calc_version())::int;
    end if;
  end loop;
  return jsonb_build_object('alerts_raised', v_n, 'hours_since_last', v_h);
end;
$$;

-- Le recalcul planifié (chaque nuit) : hier et aujourd'hui, et tout jour de l'année écoulée jamais calculé ou calculé par une version
-- antérieure (367 jours au plus par passage ; le reste au passage suivant). Un échec ne casse rien : il est journalisé, alerté, et signalé
-- par un battement de cœur « FAIL » (contrôle jobs_failed_24h de la santé du système).
create or replace function analytics.scheduled_refresh() returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_today date := logistics.today(); v_from date; v_res jsonb; v_veille jsonb; v_msg text; v_etat text; v_id bigint;
begin
  select min(g.d::date) into v_from from generate_series(v_today - 366, v_today - 2, interval '1 day') g(d)
   where analytics.current_run_of(g.d::date) is null
      or (select coalesce(r.calc_version, '012') from analytics.report_run r where r.id = analytics.current_run_of(g.d::date)) <> analytics.calc_version();
  v_from := least(coalesce(v_from, v_today - 1), v_today - 1);
  begin
    v_res := analytics.refresh_as(null, v_from, v_today, 'planifié', 'scheduler');
  exception when others then
    get stacked diagnostics v_msg = message_text, v_etat = returned_sqlstate;
    insert into analytics.run_failure (period_start, period_end, source, calc_version, sqlstate, message)
    values (v_from, v_today, 'scheduler', analytics.calc_version(), coalesce(v_etat, ''), left(coalesce(v_msg, ''), 300)) returning id into v_id;
    perform analytics.raise_alert('REFRESH_FAILED', 'FAIL', 'system', 'refresh', v_today, jsonb_build_object('sqlstate', v_etat, 'failure_id', v_id), null, 'REFRESH_FAILED|' || v_id);
    if to_regclass('ops.heartbeat') is not null then
      insert into ops.heartbeat (source, status, detail) values ('analytics_refresh', 'FAIL', jsonb_build_object('failure_id', v_id, 'sqlstate', v_etat));
    end if;
    return jsonb_build_object('status', 'FAILED', 'failure_id', v_id, 'sqlstate', v_etat, 'watch', analytics.watch());
  end;
  v_veille := analytics.watch();
  if to_regclass('ops.heartbeat') is not null then
    insert into ops.heartbeat (source, status, detail)
    values ('analytics_refresh', 'OK', jsonb_build_object('run_id', v_res -> 'run_id', 'from', v_from, 'to', v_today, 'rows', v_res -> 'rows', 'alerts', v_res -> 'alerts_raised'));
  end if;
  return v_res || jsonb_build_object('watch', v_veille);
end;
$$;

-- 9. Les façades -------------------------------------------------------------------------------------------------------------------------
create or replace function public.lg_an_alerts(p_all boolean default false)
returns jsonb language sql stable security definer set search_path = '' as $$ select analytics.alerts(auth.uid(), p_all) $$;
create or replace function public.lg_an_ack_alert(p_alert_id bigint, p_note text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$ select analytics.ack_alert(auth.uid(), p_alert_id, p_note) $$;
-- Le travailleur planifié (clé secrète) : désormais le même recalcul que la planification dans la base, veille comprise.
create or replace function public.ses_an_refresh(p_from date default null, p_to date default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
begin
  if p_from is null and p_to is null then return analytics.scheduled_refresh(); end if;
  return analytics.refresh(null, coalesce(p_from, logistics.today() - 1), coalesce(p_to, logistics.today()), 'travailleur');
end;
$$;

-- 10. La santé du système : deux contrôles de plus (alertes ouvertes, recalculs planifiés en échec) ------------------------------------------
-- Même corps que 013, avec l'analytique complétée.
create or replace function ops.status_checks()
returns table (code text, status text, value numeric, warn_at numeric, fail_at numeric, unit text, detail text)
language plpgsql stable security definer set search_path = '' as $$
#variable_conflict use_column
declare v numeric; v2 numeric; v_t timestamptz;
begin
  select count(*), coalesce(extract(epoch from now() - min(created_at)) / 60, 0) into v, v2 from logistics.event_delivery where status in ('PENDING', 'IN_PROGRESS');
  code := 'events_pending'; value := v; warn_at := 500; fail_at := 5000; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  code := 'events_oldest_minutes'; value := round(v2, 1); warn_at := 15; fail_at := 60; unit := 'minutes'; status := case when v2 >= fail_at then 'FAIL' when v2 >= warn_at then 'WARN' else 'OK' end; return next;
  select count(*) into v from logistics.dead_letter where resolved_at is null;
  code := 'dead_letters_open'; value := v; warn_at := 1; fail_at := 50; unit := 'count'; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  if to_regclass('logistics.notification') is not null then
    select count(*) filter (where status = 'FAILED' and created_at > now() - interval '24 hours'),
           coalesce(extract(epoch from now() - min(created_at) filter (where status = 'PENDING' and next_attempt_at <= now())) / 60, 0)
      into v, v2 from logistics.notification;
    code := 'notifications_failed_24h'; value := v; warn_at := 1; fail_at := 25; unit := 'count'; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
    code := 'notifications_oldest_due_minutes'; value := round(v2, 1); warn_at := 30; fail_at := 180; unit := 'minutes'; status := case when v2 >= fail_at then 'FAIL' when v2 >= warn_at then 'WARN' else 'OK' end; return next;
  end if;
  select max(reported_at) into v_t from ops.heartbeat where source = 'backup' and status = 'OK';
  v := case when v_t is null then null else round(extract(epoch from now() - v_t) / 3600, 1) end;
  code := 'backup_age_hours'; value := v; warn_at := 26; fail_at := 50; unit := 'hours'; detail := case when v_t is null then 'never' else '' end;
  status := case when v is null or v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  select max(reported_at) into v_t from ops.heartbeat where source = 'restore_check' and status = 'OK';
  v := case when v_t is null then null else round(extract(epoch from now() - v_t) / 86400, 1) end;
  code := 'restore_check_age_days'; value := v; warn_at := 8; fail_at := 32; unit := 'days'; detail := case when v_t is null then 'never' else '' end;
  status := case when v is null or v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  select count(*) into v from ops.heartbeat where status = 'FAIL' and reported_at > now() - interval '24 hours';
  code := 'jobs_failed_24h'; value := v; warn_at := 1; fail_at := 3; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  if to_regclass('analytics.report_run') is not null then
    select round(extract(epoch from now() - max(generated_at)) / 3600, 1) into v from analytics.report_run;
    code := 'analytics_age_hours'; value := v; warn_at := 26; fail_at := 72; unit := 'hours'; detail := case when v is null then 'never' else '' end;
    status := case when v is null then 'WARN' when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
    select count(*) into v from generate_series(logistics.today() - 7, logistics.today() - 1, interval '1 day') g(d)
     where not exists (select 1 from analytics.report_run r where g.d::date between r.period_start and r.period_end);
    code := 'analytics_missing_days_7'; value := v; warn_at := 1; fail_at := 7; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  end if;
  if to_regclass('analytics.alert') is not null then
    select count(*), count(*) filter (where a.severity = 'FAIL') into v, v2 from analytics.alert a where not exists (select 1 from analytics.alert_ack k where k.alert_id = a.id);
    code := 'analytics_open_alerts'; value := v; warn_at := 1; fail_at := null; unit := 'count'; detail := case when v2 > 0 then 'fail:' || v2 else '' end;
    status := case when v2 > 0 then 'FAIL' when v >= 1 then 'WARN' else 'OK' end; return next;
    select count(*) into v from analytics.run_failure where attempted_at > now() - interval '24 hours';
    code := 'analytics_failures_24h'; value := v; warn_at := 1; fail_at := 2; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  end if;
  select count(*), max(occurred_at) into v, v_t from logistics.audit_log where occurred_at > now() - interval '24 hours';
  code := 'audit_entries_24h'; value := v; warn_at := null; fail_at := null; unit := 'count'; detail := coalesce(to_char(v_t at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), ''); status := 'OK'; return next;
  select count(*) into v from ops.client_error where reported_at > now() - interval '24 hours';
  code := 'client_errors_24h'; value := v; warn_at := 10; fail_at := 100; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  select count(*) into v from ops.rate_counter where hits >= max_hits and window_start > now() - interval '24 hours';
  code := 'rate_limited_windows_24h'; value := v; warn_at := 1; fail_at := 50; unit := 'count'; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  v := round(pg_database_size(current_database()) / 1048576.0, 1);
  code := 'database_size_mb'; value := v; warn_at := 400; fail_at := 480; unit := 'MB'; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  v := ops.schema_level();
  code := 'schema_level'; value := v; warn_at := null; fail_at := null; unit := 'level'; status := case when v >= 13 then 'OK' else 'WARN' end; return next;
end;
$$;

-- 11. Tout fermé, sauf les façades ----------------------------------------------------------------------------------------------------------
revoke all on all tables in schema analytics from public, anon, authenticated;
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname in ('analytics', 'ops') loop
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

-- Planifier : PAS ici (une étape ne fait que poser le code). Par l'outil d'exploitation, qui vérifie la base puis inscrit dans pg_cron :
--   ses-analytique         '20 5 * * *'  select analytics.scheduled_refresh();   -- chaque nuit, 0 h 20 à Haïti (heure d'hiver)
--   ses-analytique-veille  '50 * * * *'  select analytics.watch();               -- chaque heure
-- Pour retirer SEULEMENT cette étape : retirer ces deux tâches (interrupteurs.py analytique-deplanifier) ; le reste peut demeurer.
