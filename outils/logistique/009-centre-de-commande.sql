-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 9 : le centre de commande des opérations
-- -----------------------------------------------------------------------------
-- Phase 12. À coller dans Supabase > SQL Editor APRÈS 001 à 008, après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet ouvert est bien « speed-express-site ».
--
-- Ce que le tableau de bord de l'ÉQUIPE appelle : indicateurs du jour, file « à traiter », vue Expédition → transport → hub → livraison → chauffeur,
-- et une vue filtrée par domaine (colis, expéditions, entrepôt, consolidations, transport, chauffeurs, enlèvements, livraisons, clients, douane,
-- facturation, paiements, incidents, notifications, support, utilisateurs, journal d'audit, réglages) ; plus le traitement des demandes des clients
-- (approuver ou refuser un enlèvement ou une livraison) et des tickets de support.
--
-- Règles tenues ici, dans la base :
--   · AUCUNE statistique critique n'est calculée par le navigateur : chaque chiffre vient d'une fonction d'ici ;
--   · l'acteur est TOUJOURS le compte connecté (auth.uid()) ; chaque fonction contrôle d'abord son droit (colis.lire, factures.lire, clients.lire, direction) ;
--   · des filtres communs (période, pays, ville, entrepôt, statut, service, client), validés ici — un filtre inconnu est une erreur, pas un oubli silencieux ;
--   · des pages bornées (200 lignes au plus) ; rien ne se supprime ni ne se modifie par ces lectures.
-- « Aujourd'hui » s'entend à l'heure d'Haïti (logistics.day_start).
--
-- Ne touche à aucune ancienne table. Retour arrière au bas du fichier. Rejouable sans risque.
-- =============================================================================

-- 1. Catalogue d'événements --------------------------------------------------------------------------------------------------
insert into logistics.event_type (code, aggregate_type, description, customer_visible) values
  ('PickupRequestApproved',   'request', 'Demande d''enlèvement approuvée par l''équipe', false),
  ('PickupRequestRejected',   'request', 'Demande d''enlèvement refusée par l''équipe', false),
  ('DeliveryRequestApproved', 'request', 'Demande de livraison approuvée par l''équipe', false),
  ('DeliveryRequestRejected', 'request', 'Demande de livraison refusée par l''équipe', false),
  ('SupportTicketAnswered',   'ticket',  'Réponse de l''équipe à un ticket de support', false),
  ('SupportTicketClosedByStaff', 'ticket', 'Ticket de support fermé par l''équipe', false)
on conflict (code) do nothing;


-- 2. Outils ------------------------------------------------------------------------------------------------------------------------
create or replace function logistics.today()
returns date language sql stable set search_path = '' as $$ select (now() at time zone 'America/Port-au-Prince')::date $$;

-- Les filtres communs, validés une fois. Rend un objet normalisé (dates en « AAAA-MM-JJ »), ou lève LG005.
create or replace function logistics.cc_f(p_filters jsonb)
returns jsonb language plpgsql stable set search_path = '' as $$
declare v jsonb := coalesce(p_filters, '{}'::jsonb); k text; x text; o jsonb := '{}'::jsonb; v_max int;
begin
  if jsonb_typeof(v) <> 'object' then raise exception 'Les filtres doivent être un objet.' using errcode = 'LG005'; end if;
  for k in select jsonb_object_keys(v) loop
    if k not in ('from', 'to', 'country', 'city', 'warehouse_id', 'status', 'service', 'customer') then raise exception 'Filtre inconnu : %.', left(k, 40) using errcode = 'LG005'; end if;
  end loop;
  foreach k in array array['from', 'to'] loop
    x := nullif(btrim(v ->> k), '');
    if x is not null then
      begin o := o || jsonb_build_object(k, x::date);
      exception when others then raise exception 'Date invalide pour le filtre « % ».', k using errcode = 'LG005'; end;
    end if;
  end loop;
  if o ? 'from' and o ? 'to' and (o ->> 'to')::date < (o ->> 'from')::date then raise exception 'La fin de la période précède son début.' using errcode = 'LG005'; end if;
  x := nullif(btrim(v ->> 'country'), '');
  if x is not null then
    if x not in ('HT', 'DO', 'US') then raise exception 'Pays inconnu (HT, DO ou US).' using errcode = 'LG005'; end if;
    o := o || jsonb_build_object('country', x);
  end if;
  x := nullif(btrim(v ->> 'service'), '');
  if x is not null then
    if not exists (select 1 from logistics.transport_mode m where m.code = x) then raise exception 'Service inconnu.' using errcode = 'LG005'; end if;
    o := o || jsonb_build_object('service', x);
  end if;
  x := nullif(btrim(v ->> 'warehouse_id'), '');
  if x is not null then
    begin o := o || jsonb_build_object('warehouse_id', x::uuid);
    exception when others then raise exception 'Identifiant d''entrepôt invalide.' using errcode = 'LG005'; end;
  end if;
  foreach k in array array['city', 'status', 'customer'] loop
    x := nullif(btrim(v ->> k), '');
    if x is not null then
      v_max := case k when 'status' then 40 else 80 end;
      if char_length(x) > v_max then raise exception 'Le filtre « % » est trop long.', k using errcode = 'LG005'; end if;
      o := o || jsonb_build_object(k, x);
    end if;
  end loop;
  return o;
end;
$$;

create or replace function logistics.cc_lim(p int) returns int language sql immutable set search_path = '' as $$ select least(greatest(coalesce(p, 50), 1), 200) $$;
create or replace function logistics.cc_off(p int) returns int language sql immutable set search_path = '' as $$ select greatest(coalesce(p, 0), 0) $$;
-- Début et fin (exclue) de la période, en instants ; nuls si le filtre est absent.
create or replace function logistics.cc_from(p_f jsonb) returns timestamptz language sql stable set search_path = '' as $$ select case when p_f ? 'from' then logistics.day_start((p_f ->> 'from')::date) end $$;
create or replace function logistics.cc_to(p_f jsonb) returns timestamptz language sql stable set search_path = '' as $$ select case when p_f ? 'to' then logistics.day_start((p_f ->> 'to')::date + 1) end $$;
-- Un client reconnu par son code (SES-10001), son e-mail ou un morceau de son nom.
create or replace function logistics.cc_cust(p_f jsonb, c logistics.customer) returns boolean language sql stable set search_path = '' as $$
  select not (p_f ? 'customer') or c.code = upper(p_f ->> 'customer') or lower(c.email) = lower(p_f ->> 'customer') or position(lower(p_f ->> 'customer') in lower(c.full_name)) > 0
$$;

-- Une facture « impayée » : émise, non annulée, avec un solde à payer (une facture remboursée a toujours un solde nul). Une seule définition, pour les indicateurs, la liste des
-- factures et la fiche des clients (le solde d'un CLIENT, lui, peut compenser une facture par l'excédent d'une autre : ce n'est pas ce qu'on compte ici).
create or replace function logistics.cc_unpaid(p_inv logistics.invoice)
returns boolean language sql immutable set search_path = '' as $$
  select p_inv.status not in ('DRAFT', 'CANCELLED') and logistics.invoice_balance(p_inv) > 0
$$;

-- Ce que l'acteur a le droit d'ouvrir : le tableau de bord ne dessine que ces sections.
create or replace function logistics.cc_access(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_ops boolean := logistics.actor_can(p_actor, 'colis.lire'); v_fin boolean := logistics.actor_can(p_actor, 'factures.lire'); v_cli boolean := logistics.actor_can(p_actor, 'clients.lire');
        v_dir boolean := logistics.actor_can(p_actor, 'direction'); v_s jsonb := '[]'::jsonb; v_role text;
begin
  perform logistics.require_staff(p_actor);
  if not (v_ops or v_fin or v_cli or v_dir) then raise exception 'Aucun droit de lecture : le centre de commande reste fermé.' using errcode = 'LG003'; end if;
  v_s := v_s || '["commande"]'::jsonb;
  if v_ops then v_s := v_s || '["flux", "colis", "expeditions", "entrepot", "consolidations", "transport", "chauffeurs", "enlevements", "livraisons", "douane", "incidents", "notifications"]'::jsonb; end if;
  if v_cli then v_s := v_s || '["clients", "support"]'::jsonb; end if;
  if v_fin then v_s := v_s || '["facturation", "paiements"]'::jsonb; end if;
  if v_dir then v_s := v_s || '["utilisateurs", "audit", "parametres"]'::jsonb; end if;
  select u.role into v_role from logistics.app_user u where u.id = p_actor;
  return jsonb_build_object('sections', v_s, 'role', v_role, 'direction', v_dir, 'ops', v_ops, 'finance', v_fin, 'customers', v_cli, 'today', logistics.today());
end;
$$;


-- 3. Indicateurs et file « à traiter » -------------------------------------------------------------------------------------------
create or replace function logistics.cc_kpis(p_actor uuid, p_filters jsonb default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  v_f jsonb; v_ops boolean := logistics.actor_can(p_actor, 'colis.lire'); v_fin boolean := logistics.actor_can(p_actor, 'factures.lire'); v_cli boolean := logistics.actor_can(p_actor, 'clients.lire');
  v_t0 timestamptz := logistics.day_start(logistics.today()); v_day date := logistics.today(); v_has boolean;
  v_o jsonb := '{}'::jsonb; v_m jsonb;
begin
  perform logistics.cc_access(p_actor);
  v_f := logistics.cc_f(p_filters);
  v_has := v_f ? 'country' or v_f ? 'city' or v_f ? 'service' or v_f ? 'warehouse_id' or v_f ? 'customer';
  if v_ops then
    with fp as (
      select p.* from logistics.parcel p left join logistics.customer c on c.id = p.customer_id
       where (not v_f ? 'country' or p.destination_country = v_f ->> 'country') and (not v_f ? 'service' or p.service_mode = v_f ->> 'service')
         and (not v_f ? 'city' or position(lower(v_f ->> 'city') in lower(p.destination_city)) > 0)
         and (not v_f ? 'warehouse_id' or p.current_warehouse_id = (v_f ->> 'warehouse_id')::uuid) and (not v_f ? 'customer' or (c.id is not null and logistics.cc_cust(v_f, c)))),
    sh as (
      select s.* from logistics.shipment s left join logistics.branch b on b.id = s.destination_branch_id
       where (not v_f ? 'country' or b.country = v_f ->> 'country') and (not v_f ? 'service' or s.mode = v_f ->> 'service')
         and (not (v_f ? 'warehouse_id' or v_f ? 'customer' or v_f ? 'city') or exists (
               select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id left join logistics.customer c on c.id = p.customer_id
                where (not v_f ? 'warehouse_id' or p.current_warehouse_id = (v_f ->> 'warehouse_id')::uuid) and (not v_f ? 'customer' or (c.id is not null and logistics.cc_cust(v_f, c)))
                  and (not v_f ? 'city' or position(lower(v_f ->> 'city') in lower(p.destination_city)) > 0)))),
    tk as (
      select t.* from logistics.task t where t.kind = 'DELIVERY'
         and (not v_has or exists (select 1 from logistics.delivery_parcel dp join fp on fp.id = dp.parcel_id where dp.delivery_id = t.delivery_id)))
    select jsonb_build_object(
      'parcels_received_today', (select count(*) from logistics.tracking_event e join fp on fp.id = e.parcel_id where e.event_type = 'ParcelReceived' and e.occurred_at >= v_t0),
      'parcels_in_warehouse',   (select count(*) from fp where fp.status in ('RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT')),
      'parcels_at_hub',         (select count(*) from fp where fp.status = 'AT_DESTINATION_HUB'),
      'parcels_on_hold',        (select count(*) from fp where fp.status = 'ON_HOLD'),
      'consolidations_open',    (select count(*) from logistics.consolidation c where c.status = 'OPEN'
                                   and (not v_f ? 'country' or c.destination_country = v_f ->> 'country') and (not v_f ? 'service' or c.mode = v_f ->> 'service')
                                   and (not v_f ? 'warehouse_id' or c.warehouse_id = (v_f ->> 'warehouse_id')::uuid)
                                   and (not (v_f ? 'customer' or v_f ? 'city') or exists (
                                         select 1 from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id left join logistics.customer cu on cu.id = p.customer_id
                                          where cp.consolidation_id = c.id and cp.removed_at is null and (not v_f ? 'customer' or (cu.id is not null and logistics.cc_cust(v_f, cu)))
                                            and (not v_f ? 'city' or position(lower(v_f ->> 'city') in lower(p.destination_city)) > 0)))),
      'shipments_ready',        (select count(*) from sh where sh.status = 'READY'),
      'shipments_in_transit',   (select count(*) from sh where sh.status in ('DISPATCHED', 'IN_TRANSIT')),
      'shipments_customs',      (select count(*) from sh where sh.status in ('ARRIVED', 'CUSTOMS_PROCESSING')),
      'deliveries_today',       (select count(*) from tk where tk.scheduled_date = v_day and tk.status <> 'CANCELLED'),
      'deliveries_in_progress', (select count(*) from tk where tk.status = 'STARTED'),
      'deliveries_delayed',     (select count(*) from tk where tk.status in ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED') and (tk.scheduled_date < v_day or (tk.window_end is not null and tk.window_end < now()))),
      'incidents_open',         (select count(*) from logistics.incident i where i.status in ('OPEN', 'IN_PROGRESS') and (not v_has or i.parcel_id in (select id from fp))),
      'incidents_high',         (select count(*) from logistics.incident i where i.status in ('OPEN', 'IN_PROGRESS') and i.severity = 'HIGH' and (not v_has or i.parcel_id in (select id from fp))),
      'pickup_requests_pending', (select count(*) from logistics.pickup_request r join logistics.customer c on c.id = r.customer_id where r.status = 'REQUESTED' and logistics.cc_cust(v_f, c)
                                    and (not v_f ? 'country' or r.country = v_f ->> 'country') and (not v_f ? 'city' or position(lower(v_f ->> 'city') in lower(r.city)) > 0)),
      'delivery_requests_pending', (select count(*) from logistics.delivery_request r join logistics.customer c on c.id = r.customer_id where r.status = 'REQUESTED' and logistics.cc_cust(v_f, c)
                                      and (not v_f ? 'country' or r.country = v_f ->> 'country') and (not v_f ? 'city' or position(lower(v_f ->> 'city') in lower(r.city)) > 0))) into v_o;
  end if;
  if v_fin then
    v_m := jsonb_build_object('revenue_date', current_date,
      'revenue_today_usd', (select coalesce(sum(r.net_base_usd), 0) from logistics.revenue_entry r where r.entry_date = current_date),
      'revenue_month_usd', (select coalesce(sum(r.net_base_usd), 0) from logistics.revenue_entry r where r.entry_date >= date_trunc('month', current_date)::date and r.entry_date <= current_date),
      'unpaid', coalesce((select jsonb_agg(jsonb_build_object('currency', x.currency, 'invoices', x.n, 'customers', x.c, 'balance', x.s) order by x.currency)
                            from (select i.currency, count(*) as n, count(distinct i.customer_id) as c, sum(logistics.invoice_balance(i)) as s from logistics.invoice i where logistics.cc_unpaid(i) group by i.currency) x), '[]'::jsonb),
      'overdue_invoices', (select count(*) from logistics.invoice i where i.status = 'OVERDUE'));
    if v_f ? 'from' or v_f ? 'to' then
      v_m := v_m || jsonb_build_object('revenue_period_usd', (select coalesce(sum(r.net_base_usd), 0) from logistics.revenue_entry r
                                         where (not v_f ? 'from' or r.entry_date >= (v_f ->> 'from')::date) and (not v_f ? 'to' or r.entry_date <= (v_f ->> 'to')::date)));
    end if;
  end if;
  return jsonb_build_object('as_of', now(), 'today', v_day, 'filters', v_f, 'operations', case when v_ops then v_o end, 'money', v_m,
    'support', case when v_cli then jsonb_build_object('tickets_open', (select count(*) from logistics.support_ticket t where t.status <> 'CLOSED'),
                                                         'tickets_waiting_staff', (select count(*) from logistics.support_ticket t where t.status = 'OPEN')) end);
end;
$$;

-- La file de travail : ce qui attend l'équipe, du plus ancien. Rend le nombre et le plus ancien de chaque genre.
create or replace function logistics.cc_attention(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_ops boolean := logistics.actor_can(p_actor, 'colis.lire'); v_fin boolean := logistics.actor_can(p_actor, 'factures.lire'); v_cli boolean := logistics.actor_can(p_actor, 'clients.lire');
        v_a jsonb := '[]'::jsonb; v_day date := logistics.today();
begin
  perform logistics.cc_access(p_actor);
  if v_ops then
    v_a := v_a || coalesce((select jsonb_build_array(
      jsonb_build_object('kind', 'pickup_requests', 'count', count(*), 'oldest_at', min(created_at))) from logistics.pickup_request where status = 'REQUESTED' having count(*) > 0), '[]'::jsonb)
         || coalesce((select jsonb_build_array(jsonb_build_object('kind', 'delivery_requests', 'count', count(*), 'oldest_at', min(created_at))) from logistics.delivery_request where status = 'REQUESTED' having count(*) > 0), '[]'::jsonb)
         || coalesce((select jsonb_build_array(jsonb_build_object('kind', 'deliveries_delayed', 'count', count(*), 'oldest_at', min(coalesce(window_end, scheduled_date::timestamptz))))
                        from logistics.task where kind = 'DELIVERY' and status in ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED') and (scheduled_date < v_day or (window_end is not null and window_end < now())) having count(*) > 0), '[]'::jsonb)
         || coalesce((select jsonb_build_array(jsonb_build_object('kind', 'incidents_high', 'count', count(*), 'oldest_at', min(created_at))) from logistics.incident where status in ('OPEN', 'IN_PROGRESS') and severity = 'HIGH' having count(*) > 0), '[]'::jsonb)
         || coalesce((select jsonb_build_array(jsonb_build_object('kind', 'parcels_on_hold', 'count', count(*), 'oldest_at', min(updated_at))) from logistics.parcel where status = 'ON_HOLD' having count(*) > 0), '[]'::jsonb)
         || coalesce((select jsonb_build_array(jsonb_build_object('kind', 'shipments_late', 'count', count(*), 'oldest_at', min(t.planned_arrival_at)))
                        from logistics.shipment s join logistics.transport t on t.id = s.transport_id where s.status in ('DISPATCHED', 'IN_TRANSIT') and t.planned_arrival_at < now() having count(*) > 0), '[]'::jsonb);
  end if;
  if v_cli then
    v_a := v_a || coalesce((select jsonb_build_array(jsonb_build_object('kind', 'tickets_waiting', 'count', count(*), 'oldest_at', min(updated_at))) from logistics.support_ticket where status = 'OPEN' having count(*) > 0), '[]'::jsonb);
  end if;
  if v_fin then
    v_a := v_a || coalesce((select jsonb_build_array(jsonb_build_object('kind', 'invoices_overdue', 'count', count(*), 'oldest_at', min(due_date::timestamptz))) from logistics.invoice where status = 'OVERDUE' having count(*) > 0), '[]'::jsonb);
  end if;
  return jsonb_build_object('as_of', now(), 'items', v_a);
end;
$$;


-- 4. La vue Expédition → transport → hub → livraison → chauffeur ---------------------------------------------------------------------------
create or replace function logistics.cc_flow(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select s.*, t.carrier, t.reference as transport_ref, t.status as transport_status, t.planned_arrival_at, t.actual_departure_at, t.actual_arrival_at, b.country as dest_country
        from logistics.shipment s left join logistics.transport t on t.id = s.transport_id left join logistics.branch b on b.id = s.destination_branch_id
       where s.status not in ('DRAFT', 'CANCELLED')
         and (not v_f ? 'status' or s.status = v_f ->> 'status' or (v_f ->> 'status' = 'ACTIVE' and s.status <> 'CLOSED'))
         and (not v_f ? 'country' or b.country = v_f ->> 'country') and (not v_f ? 'service' or s.mode = v_f ->> 'service')
         and (logistics.cc_from(v_f) is null or s.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or s.created_at < logistics.cc_to(v_f))
         and (not v_f ? 'warehouse_id' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id where p.current_warehouse_id = (v_f ->> 'warehouse_id')::uuid))
         and (not v_f ? 'customer' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id join logistics.customer c on c.id = p.customer_id where logistics.cc_cust(v_f, c)))
         and (not v_f ? 'city' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id where position(lower(v_f ->> 'city') in lower(p.destination_city)) > 0)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f, 'items', coalesce((select jsonb_agg(jsonb_build_object(
        'shipment', x.code, 'mode', x.mode, 'status', x.status, 'created_at', x.created_at,
        'transport', case when x.transport_ref is not null then jsonb_build_object('reference', x.transport_ref, 'carrier', x.carrier, 'status', x.transport_status,
                           'departed_at', x.actual_departure_at, 'planned_arrival_at', x.planned_arrival_at, 'arrived_at', x.actual_arrival_at) end,
        'hub', logistics.branch_label(x.destination_branch_id), 'country', x.dest_country,
        'parcels', jsonb_build_object('total', (select count(*) from logistics.shipment_parcels(x.id)),
                      'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select p.status, count(*) as n from logistics.shipment_parcels(x.id) sp join logistics.parcel p on p.id = sp.parcel_id group by p.status) g), '{}'::jsonb)),
        'deliveries', coalesce((select jsonb_agg(jsonb_build_object('status', d.status, 'scheduled_date', d.scheduled_date, 'driver', d.driver_name, 'parcels', d.n) order by d.scheduled_date, d.driver_name)
                                  from (select tk.id, tk.status, tk.scheduled_date, dr.full_name as driver_name, count(distinct dp.parcel_id) as n
                                          from logistics.shipment_parcels(x.id) sp join logistics.delivery_parcel dp on dp.parcel_id = sp.parcel_id
                                          join logistics.task tk on tk.delivery_id = dp.delivery_id and tk.kind = 'DELIVERY' left join logistics.driver dr on dr.id = tk.driver_id
                                         group by tk.id, tk.status, tk.scheduled_date, dr.full_name) d), '[]'::jsonb)) order by x.created_at desc, x.code)
                                from (select * from f order by created_at desc, code limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;


-- 5. Les vues par domaine (opérations : droit « colis.lire ») ----------------------------------------------------------------------------------
create or replace function logistics.cc_parcels(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select p.*, c.code as customer_code, c.full_name as customer_name from logistics.parcel p left join logistics.customer c on c.id = p.customer_id
       where (not v_f ? 'country' or p.destination_country = v_f ->> 'country') and (not v_f ? 'service' or p.service_mode = v_f ->> 'service')
         and (not v_f ? 'status' or p.status = v_f ->> 'status') and (not v_f ? 'warehouse_id' or p.current_warehouse_id = (v_f ->> 'warehouse_id')::uuid)
         and (not v_f ? 'city' or position(lower(v_f ->> 'city') in lower(p.destination_city)) > 0)
         and (not v_f ? 'customer' or (c.id is not null and logistics.cc_cust(v_f, c)))
         and (logistics.cc_from(v_f) is null or p.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or p.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select status, count(*) as n from f group by status) g), '{}'::jsonb),
      'items', coalesce((select jsonb_agg(jsonb_build_object('tracking_number', x.tracking_number, 'status', x.status, 'service_mode', x.service_mode, 'customer_code', x.customer_code, 'customer_name', x.customer_name,
          'destination_country', x.destination_country, 'destination_city', x.destination_city, 'weight_lb', coalesce(x.verified_weight_lb, x.weight_lb), 'warehouse', (select logistics.branch_label(w.branch_id) from logistics.warehouse w where w.id = x.current_warehouse_id),
          'location', (select l.code from logistics.warehouse_location l where l.id = x.current_location_id), 'condition', x.condition, 'prohibited', x.is_prohibited, 'authority', x.status_authority,
          'created_at', x.created_at, 'updated_at', x.updated_at) order by x.updated_at desc, x.tracking_number) from (select * from f order by updated_at desc, tracking_number limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

-- La fiche complète d'un colis, POUR L'ÉQUIPE : tout le journal (événements internes compris), les auteurs, les scans, les incidents.
create or replace function logistics.cc_parcel_detail(p_actor uuid, p_tracking text)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare p logistics.parcel;
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  select * into p from logistics.parcel x where x.tracking_number = upper(btrim(coalesce(p_tracking, '')));
  if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  return jsonb_build_object(
    'parcel', (logistics.parcel_card(p) - 'public_token') || jsonb_build_object('customer_code', (select code from logistics.customer where id = p.customer_id), 'customer_name', (select full_name from logistics.customer where id = p.customer_id),
        'authority', p.status_authority, 'condition', p.condition, 'prohibited', p.is_prohibited, 'warehouse', (select logistics.branch_label(w.branch_id) from logistics.warehouse w where w.id = p.current_warehouse_id),
        'location', (select l.code from logistics.warehouse_location l where l.id = p.current_location_id)),
    'timeline', coalesce((select jsonb_agg(jsonb_build_object('at', e.occurred_at, 'event', e.event_type, 'from', e.from_status, 'to', e.to_status, 'actor', e.actor_label, 'source', e.source,
                              'location', nullif(e.location_text, ''), 'reason', e.metadata ->> 'reason', 'correlation_id', e.correlation_id) order by e.occurred_at, e.id)
                            from logistics.tracking_event e where e.parcel_id = p.id), '[]'::jsonb),
    'scans', coalesce((select jsonb_agg(jsonb_build_object('at', s.scanned_at, 'purpose', s.purpose, 'result', s.result, 'code_kind', s.code_kind) order by s.scanned_at desc) from (select * from logistics.scan where parcel_id = p.id order by scanned_at desc limit 20) s), '[]'::jsonb),
    'incidents', coalesce((select jsonb_agg(jsonb_build_object('type', i.type, 'severity', i.severity, 'status', i.status, 'description', i.description, 'at', i.created_at) order by i.created_at desc) from logistics.incident i where i.parcel_id = p.id), '[]'::jsonb),
    'shipments', coalesce((select jsonb_agg(jsonb_build_object('code', s.code, 'status', s.status, 'mode', s.mode)) from logistics.shipment s where s.id in (select sp.shipment_id from logistics.shipments_of_parcel(p.id) sp)), '[]'::jsonb),
    'deliveries', coalesce((select jsonb_agg(jsonb_build_object('status', t.status, 'scheduled_date', t.scheduled_date, 'driver', dr.full_name) order by t.created_at desc)
                              from logistics.delivery_parcel dp join logistics.task t on t.delivery_id = dp.delivery_id and t.kind = 'DELIVERY' left join logistics.driver dr on dr.id = t.driver_id where dp.parcel_id = p.id), '[]'::jsonb));
end;
$$;

create or replace function logistics.cc_shipments(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select s.*, b.country as dest_country from logistics.shipment s left join logistics.branch b on b.id = s.destination_branch_id
       where (not v_f ? 'status' or s.status = v_f ->> 'status') and (not v_f ? 'country' or b.country = v_f ->> 'country') and (not v_f ? 'service' or s.mode = v_f ->> 'service')
         and (not v_f ? 'warehouse_id' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id where p.current_warehouse_id = (v_f ->> 'warehouse_id')::uuid))
         and (not v_f ? 'customer' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id join logistics.customer c on c.id = p.customer_id where logistics.cc_cust(v_f, c)))
         and (not v_f ? 'city' or exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id where position(lower(v_f ->> 'city') in lower(p.destination_city)) > 0))
         and (logistics.cc_from(v_f) is null or s.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or s.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select status, count(*) as n from f group by status) g), '{}'::jsonb),
      'items', coalesce((select jsonb_agg(jsonb_build_object('code', x.code, 'mode', x.mode, 'status', x.status, 'origin', logistics.branch_label(x.origin_branch_id), 'destination', logistics.branch_label(x.destination_branch_id),
          'transport', (select t.reference from logistics.transport t where t.id = x.transport_id), 'parcels', (select count(*) from logistics.shipment_parcels(x.id)),
          'weight_lb', (select coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb)), 0) from logistics.shipment_parcels(x.id) sp join logistics.parcel p on p.id = sp.parcel_id),
          'dispatched_at', x.dispatched_at, 'arrived_at', x.arrived_at, 'created_at', x.created_at) order by x.created_at desc, x.code)
                           from (select * from f order by created_at desc, code limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_warehouse(p_actor uuid, p_filters jsonb default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_t0 timestamptz := logistics.day_start(logistics.today());
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return jsonb_build_object('filters', v_f,
    'warehouses', coalesce((select jsonb_agg(jsonb_build_object('warehouse_id', w.id, 'code', w.code, 'name', w.name, 'branch', logistics.branch_label(w.branch_id),
        'parcels', (select count(*) from logistics.parcel p where p.current_warehouse_id = w.id),
        'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select p.status, count(*) as n from logistics.parcel p where p.current_warehouse_id = w.id group by p.status) g), '{}'::jsonb),
        'locations', (select count(*) from logistics.warehouse_location l where l.warehouse_id = w.id and l.active),
        'received_today', (select count(*) from logistics.tracking_event e where e.warehouse_id = w.id and e.event_type = 'ParcelReceived' and e.occurred_at >= v_t0),
        'scans_today', (select count(*) from logistics.scan s where s.warehouse_id = w.id and s.scanned_at >= v_t0),
        'scans_rejected_today', (select count(*) from logistics.scan s where s.warehouse_id = w.id and s.scanned_at >= v_t0 and s.result <> 'ACCEPTED'),
        'open_incidents', (select count(*) from logistics.incident i where i.warehouse_id = w.id and i.status in ('OPEN', 'IN_PROGRESS'))) order by w.code)
        from logistics.warehouse w where w.active and (not v_f ? 'warehouse_id' or w.id = (v_f ->> 'warehouse_id')::uuid)
         and (not v_f ? 'country' or exists (select 1 from logistics.branch b where b.id = w.branch_id and b.country = v_f ->> 'country'))), '[]'::jsonb),
    'recent_scans', coalesce((select jsonb_agg(jsonb_build_object('at', x.scanned_at, 'code', x.scanned_code, 'purpose', x.purpose, 'result', x.result, 'warehouse', x.wcode) order by x.scanned_at desc)
                                from (select s.*, w.code as wcode from logistics.scan s join logistics.warehouse w on w.id = s.warehouse_id
                                       where (not v_f ? 'warehouse_id' or s.warehouse_id = (v_f ->> 'warehouse_id')::uuid) order by s.scanned_at desc limit 20) x), '[]'::jsonb));
end;
$$;

create or replace function logistics.cc_consolidations(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select c.* from logistics.consolidation c
       where (not v_f ? 'status' or c.status = v_f ->> 'status') and (not v_f ? 'country' or c.destination_country = v_f ->> 'country') and (not v_f ? 'service' or c.mode = v_f ->> 'service')
         and (not v_f ? 'warehouse_id' or c.warehouse_id = (v_f ->> 'warehouse_id')::uuid)
         and (not v_f ? 'customer' or exists (select 1 from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id join logistics.customer cu on cu.id = p.customer_id where cp.consolidation_id = c.id and cp.removed_at is null and logistics.cc_cust(v_f, cu)))
         and (logistics.cc_from(v_f) is null or c.opened_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or c.opened_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'items', coalesce((select jsonb_agg(jsonb_build_object('code', x.code, 'status', x.status, 'mode', x.mode, 'destination_country', x.destination_country,
          'warehouse', (select logistics.branch_label(w.branch_id) from logistics.warehouse w where w.id = x.warehouse_id),
          'parcels', (select count(*) from logistics.consolidation_parcel cp where cp.consolidation_id = x.id and cp.removed_at is null),
          'customers', (select count(distinct p.customer_id) from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id where cp.consolidation_id = x.id and cp.removed_at is null),
          'weight_lb', (select coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb)), 0) from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id where cp.consolidation_id = x.id and cp.removed_at is null),
          'shipment', (select s.code from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id where i.consolidation_id = x.id and s.status <> 'CANCELLED' order by s.created_at desc limit 1),
          'opened_at', x.opened_at, 'closed_at', x.closed_at) order by x.opened_at desc, x.code) from (select * from f order by opened_at desc, code limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_transports(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select t.* from logistics.transport t
       where (not v_f ? 'status' or t.status = v_f ->> 'status') and (not v_f ? 'service' or t.mode = v_f ->> 'service')
         and (not v_f ? 'country' or exists (select 1 from logistics.branch b where b.id = t.destination_branch_id and b.country = v_f ->> 'country'))
         and (logistics.cc_from(v_f) is null or coalesce(t.planned_departure_at, t.created_at) >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or coalesce(t.planned_departure_at, t.created_at) < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'items', coalesce((select jsonb_agg(jsonb_build_object('reference', x.reference, 'carrier', x.carrier, 'mode', x.mode, 'status', x.status, 'origin', logistics.branch_label(x.origin_branch_id), 'destination', logistics.branch_label(x.destination_branch_id),
          'planned_departure_at', x.planned_departure_at, 'actual_departure_at', x.actual_departure_at, 'planned_arrival_at', x.planned_arrival_at, 'actual_arrival_at', x.actual_arrival_at,
          'late', x.status in ('PLANNED', 'DEPARTED') and x.planned_arrival_at is not null and x.planned_arrival_at < now(),
          'shipments', (select count(*) from logistics.shipment s where s.transport_id = x.id and s.status <> 'CANCELLED')) order by coalesce(x.planned_departure_at, x.created_at) desc, x.reference)
          from (select * from f order by coalesce(planned_departure_at, created_at) desc, reference limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_drivers(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset); v_day date := logistics.today();
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select d.* from logistics.driver d
       where (not v_f ? 'status' or d.status = v_f ->> 'status')
         and (not v_f ? 'country' or exists (select 1 from logistics.driver_zone z join logistics.delivery_zone dz on dz.id = z.zone_id where z.driver_id = d.id and dz.country = v_f ->> 'country'))
         and (not v_f ? 'city' or exists (select 1 from logistics.driver_zone z join logistics.delivery_zone dz on dz.id = z.zone_id where z.driver_id = d.id and exists (select 1 from unnest(dz.cities) c where position(lower(v_f ->> 'city') in lower(c)) > 0))))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'items', coalesce((select jsonb_agg(jsonb_build_object('driver_id', x.id, 'name', x.full_name, 'phone', x.phone, 'status', x.status,
          'vehicle', (select concat(v.plate, ' (', v.kind, ')') from logistics.vehicle v where v.id = x.default_vehicle_id),
          'zones', coalesce((select jsonb_agg(dz.code order by dz.code) from logistics.driver_zone z join logistics.delivery_zone dz on dz.id = z.zone_id where z.driver_id = x.id), '[]'::jsonb),
          'tasks_today', (select count(*) from logistics.task t where t.driver_id = x.id and t.scheduled_date = v_day and t.status not in ('CANCELLED')),
          'tasks_open', (select count(*) from logistics.task t where t.driver_id = x.id and t.status in ('ASSIGNED', 'ACCEPTED', 'STARTED')),
          'completed_today', (select count(*) from logistics.task t where t.driver_id = x.id and t.scheduled_date = v_day and t.status = 'COMPLETED'),
          'failed_today', (select count(*) from logistics.task t where t.driver_id = x.id and t.scheduled_date = v_day and t.status = 'FAILED'),
          'position_age_min', case when x.last_position_at is null then null else round(extract(epoch from (now() - x.last_position_at)) / 60)::int end,
          'available_today', exists (select 1 from logistics.driver_availability a where a.driver_id = x.id and a.available and a.starts_at < logistics.day_start(v_day + 1) and a.ends_at > logistics.day_start(v_day))) order by x.full_name, x.id)
          from (select * from f order by full_name, id limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_pickups(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select r.id as request_id, r.number, 'REQUEST'::text as source, c.code as customer_code, c.full_name as customer_name, r.country, r.city, r.address, r.preferred_date as date, r.preferred_window as window,
             r.parcels_expected, r.notes, r.status as request_status, t.status as task_status, logistics.pickup_stage(r.status, t.status) as stage, dr.full_name as driver, r.created_at, r.review_message
        from logistics.pickup_request r join logistics.customer c on c.id = r.customer_id left join logistics.task t on t.id = r.task_id left join logistics.driver dr on dr.id = t.driver_id
       where (not v_f ? 'country' or r.country = v_f ->> 'country') and (not v_f ? 'city' or position(lower(v_f ->> 'city') in lower(r.city)) > 0) and logistics.cc_cust(v_f, c)
         and (not v_f ? 'status' or logistics.pickup_stage(r.status, t.status) = v_f ->> 'status')
         and (logistics.cc_from(v_f) is null or r.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or r.created_at < logistics.cc_to(v_f))
      union all
      select t.id, 'PKT-' || upper(substr(replace(t.id::text, '-', ''), 1, 8)), 'STAFF', c.code, c.full_name, null, '', t.address, t.scheduled_date, 'ANY', t.parcels_expected, '', null, t.status,
             logistics.pickup_stage('APPROVED', t.status), dr.full_name, t.created_at, null
        from logistics.task t join logistics.customer c on c.id = t.customer_id left join logistics.driver dr on dr.id = t.driver_id
       where t.kind = 'PICKUP' and not exists (select 1 from logistics.pickup_request r where r.task_id = t.id) and logistics.cc_cust(v_f, c) and not v_f ? 'country' and not v_f ? 'city'
         and (not v_f ? 'status' or logistics.pickup_stage('APPROVED', t.status) = v_f ->> 'status')
         and (logistics.cc_from(v_f) is null or t.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or t.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'by_stage', coalesce((select jsonb_object_agg(g.stage, g.n) from (select stage, count(*) as n from f group by stage) g), '{}'::jsonb),
      'items', coalesce((select jsonb_agg(to_jsonb(x) order by (x.stage = 'requested') desc, x.date, x.created_at, x.request_id)
                           from (select * from f order by (stage = 'requested') desc, date, created_at, request_id limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_deliveries(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset); v_day date := logistics.today();
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select 'TASK'::text as kind, t.id as ref_id, 'DEL-' || upper(substr(replace(t.id::text, '-', ''), 1, 8)) as number, c.code as customer_code, c.full_name as customer_name, t.address, t.scheduled_date as date, t.window_start, t.window_end,
             t.status as task_status, null::text as request_status, logistics.delivery_stage('APPROVED', t.status) as stage, dr.full_name as driver, t.priority,
             (t.status in ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED') and (t.scheduled_date < v_day or (t.window_end is not null and t.window_end < now()))) as delayed,
             (select count(*) from logistics.delivery_parcel dp where dp.delivery_id = t.delivery_id) as parcels, t.created_at
        from logistics.task t join logistics.delivery d on d.id = t.delivery_id left join logistics.customer c on c.id = d.customer_id left join logistics.driver dr on dr.id = t.driver_id
       where t.kind = 'DELIVERY' and (not v_f ? 'status' or logistics.delivery_stage('APPROVED', t.status) = v_f ->> 'status')
         and (not v_f ? 'customer' or (c.id is not null and logistics.cc_cust(v_f, c)))
         and (not v_f ? 'country' or exists (select 1 from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = d.id and p.destination_country = v_f ->> 'country'))
         and (not v_f ? 'city' or exists (select 1 from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = d.id and position(lower(v_f ->> 'city') in lower(p.destination_city)) > 0))
         and (not v_f ? 'warehouse_id' or exists (select 1 from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = d.id and p.current_warehouse_id = (v_f ->> 'warehouse_id')::uuid))
         and (logistics.cc_from(v_f) is null or t.scheduled_date >= (v_f ->> 'from')::date) and (logistics.cc_to(v_f) is null or t.scheduled_date <= (v_f ->> 'to')::date)
      union all
      select 'REQUEST', r.id, r.number, c.code, c.full_name, r.address, r.preferred_date, null::timestamptz, null::timestamptz, null, r.status, logistics.delivery_stage(r.status, null), null, 3, false,
             (select count(*) from logistics.delivery_request_parcel rp where rp.request_id = r.id), r.created_at
        from logistics.delivery_request r join logistics.customer c on c.id = r.customer_id
       where r.status in ('REQUESTED', 'REJECTED') and (not v_f ? 'status' or logistics.delivery_stage(r.status, null) = v_f ->> 'status') and logistics.cc_cust(v_f, c)
         and (not v_f ? 'country' or r.country = v_f ->> 'country') and (not v_f ? 'city' or position(lower(v_f ->> 'city') in lower(r.city)) > 0) and not v_f ? 'warehouse_id'
         and (logistics.cc_from(v_f) is null or r.preferred_date >= (v_f ->> 'from')::date) and (logistics.cc_to(v_f) is null or r.preferred_date <= (v_f ->> 'to')::date))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f, 'delayed', (select count(*) from f where delayed),
      'by_stage', coalesce((select jsonb_object_agg(g.stage, g.n) from (select stage, count(*) as n from f group by stage) g), '{}'::jsonb),
      'items', coalesce((select jsonb_agg(to_jsonb(x) order by (x.stage = 'requested') desc, x.delayed desc, x.date, x.created_at, x.ref_id)
                           from (select * from f order by (stage = 'requested') desc, delayed desc, date, created_at, ref_id limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_customs(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select d.*, s.code as shipment_code, s.mode as shipment_mode from logistics.customs_declaration d join logistics.shipment s on s.id = d.shipment_id
       where (not v_f ? 'status' or d.status = v_f ->> 'status') and (not v_f ? 'country' or d.destination_country = v_f ->> 'country') and (not v_f ? 'service' or s.mode = v_f ->> 'service')
         and (logistics.cc_from(v_f) is null or d.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or d.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select status, count(*) as n from f group by status) g), '{}'::jsonb),
      'items', coalesce((select jsonb_agg(jsonb_build_object('shipment', x.shipment_code, 'mode', x.shipment_mode, 'reference', x.reference, 'status', x.status, 'broker', x.broker_name,
          'origin_country', x.origin_country, 'destination_country', x.destination_country, 'declared_value', x.declared_value, 'currency', x.currency,
          'parcels', jsonb_array_length(x.snapshot), 'submitted_at', x.submitted_at, 'cleared_at', x.cleared_at, 'rejected_reason', x.rejected_reason,
          'waiting_days', case when x.status in ('SUBMITTED', 'UNDER_REVIEW') then (logistics.today() - (x.submitted_at at time zone 'America/Port-au-Prince')::date) end) order by x.created_at desc)
          from (select * from f order by created_at desc limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_incidents(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select i.*, p.tracking_number, p.destination_country, p.service_mode, c.code as customer_code, w.code as warehouse_code from logistics.incident i left join logistics.parcel p on p.id = i.parcel_id
        left join logistics.customer c on c.id = p.customer_id left join logistics.warehouse w on w.id = i.warehouse_id
       where (not v_f ? 'status' or i.status = v_f ->> 'status' or (v_f ->> 'status' = 'ACTIVE' and i.status in ('OPEN', 'IN_PROGRESS')))
         and (not v_f ? 'country' or p.destination_country = v_f ->> 'country') and (not v_f ? 'service' or p.service_mode = v_f ->> 'service')
         and (not v_f ? 'warehouse_id' or i.warehouse_id = (v_f ->> 'warehouse_id')::uuid) and (not v_f ? 'customer' or (c.id is not null and logistics.cc_cust(v_f, c)))
         and (logistics.cc_from(v_f) is null or i.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or i.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select status, count(*) as n from f group by status) g), '{}'::jsonb),
      'items', coalesce((select jsonb_agg(jsonb_build_object('incident_id', x.id, 'type', x.type, 'severity', x.severity, 'status', x.status, 'description', x.description, 'tracking_number', x.tracking_number,
          'customer_code', x.customer_code, 'warehouse', x.warehouse_code, 'task', x.task_id is not null, 'created_at', x.created_at, 'resolved_at', x.resolved_at, 'resolution', x.resolution)
          order by (x.status in ('OPEN', 'IN_PROGRESS')) desc, (x.severity = 'HIGH') desc, x.created_at desc, x.id) from (select * from f order by (status in ('OPEN', 'IN_PROGRESS')) desc, (severity = 'HIGH') desc, created_at desc, id limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_notifications(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select n.*, c.code as customer_code, c.full_name as customer_name from logistics.notification n left join logistics.customer c on c.id = n.customer_id
       where (not v_f ? 'status' or n.status = v_f ->> 'status') and (not v_f ? 'customer' or (c.id is not null and logistics.cc_cust(v_f, c)))
         and (logistics.cc_from(v_f) is null or n.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or n.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select status, count(*) as n from f group by status) g), '{}'::jsonb),
      'items', coalesce((select jsonb_agg(jsonb_build_object('id', x.id, 'channel', x.channel, 'template', x.template, 'status', x.status, 'customer_code', x.customer_code, 'customer_name', x.customer_name,
          'created_at', x.created_at, 'sent_at', x.sent_at) order by x.created_at desc, x.id desc) from (select * from f order by created_at desc, id desc limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;


-- 6. Clients, facturation, paiements, support (droits « clients.lire » et « factures.lire ») ---------------------------------------------------------
create or replace function logistics.cc_customers(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset); v_fin boolean := logistics.actor_can(p_actor, 'factures.lire');
begin
  perform logistics.require_right(p_actor, 'clients.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select c.* from logistics.customer c
       where logistics.cc_cust(v_f, c) and (not v_f ? 'country' or lower(c.country) in (lower(v_f ->> 'country'), case v_f ->> 'country' when 'HT' then 'haïti' when 'DO' then 'république dominicaine' else 'états-unis' end))
         and (not v_f ? 'city' or position(lower(v_f ->> 'city') in lower(c.city)) > 0)
         and (logistics.cc_from(v_f) is null or c.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or c.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'items', coalesce((select jsonb_agg(jsonb_build_object('customer_code', x.code, 'name', x.full_name, 'email', x.email, 'phone', x.phone, 'country', x.country, 'city', x.city, 'language', x.language,
          'parcels', (select count(*) from logistics.parcel p where p.customer_id = x.id),
          'parcels_open', (select count(*) from logistics.parcel p where p.customer_id = x.id and p.status not in ('DELIVERED', 'CANCELLED', 'LOST', 'RETURNED')),
          'unpaid', case when v_fin then coalesce((select jsonb_agg(jsonb_build_object('currency', u.currency, 'invoices', u.n, 'balance', u.s) order by u.currency)
                                                    from (select i.currency, count(*) as n, sum(logistics.invoice_balance(i)) as s from logistics.invoice i where i.customer_id = x.id and logistics.cc_unpaid(i) group by i.currency) u), '[]'::jsonb) end,
          'tickets_open', (select count(*) from logistics.support_ticket t where t.customer_id = x.id and t.status <> 'CLOSED'),
          'staff_account', x.source = 'legacy_staff_account', 'created_at', x.created_at, 'last_parcel_at', (select max(p.updated_at) from logistics.parcel p where p.customer_id = x.id)) order by x.created_at desc, x.code)
          from (select * from f order by created_at desc, code limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_invoices(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'factures.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select i.*, c.code as customer_code, c.full_name as customer_name, logistics.invoice_balance(i) as balance, logistics.cc_unpaid(i) as unpaid from logistics.invoice i join logistics.customer c on c.id = i.customer_id
       where i.status <> 'DRAFT' and logistics.cc_cust(v_f, c)
         and (not v_f ? 'status' or i.status = v_f ->> 'status' or (v_f ->> 'status' = 'UNPAID' and logistics.cc_unpaid(i)))
         and (logistics.cc_from(v_f) is null or i.issued_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or i.issued_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select status, count(*) as n from f group by status) g), '{}'::jsonb),
      'totals', coalesce((select jsonb_agg(jsonb_build_object('currency', g.currency, 'invoiced', g.t, 'unpaid_invoices', g.n, 'balance', g.b) order by g.currency) from (select currency, sum(total) as t, coalesce(sum(balance) filter (where unpaid), 0) as b, count(*) filter (where unpaid) as n from f group by currency) g), '[]'::jsonb),
      'items', coalesce((select jsonb_agg(jsonb_build_object('number', x.number, 'customer_code', x.customer_code, 'customer_name', x.customer_name, 'status', x.status, 'currency', x.currency, 'total', x.total, 'paid', x.paid_amount,
          'credited', x.credited_amount, 'refunded', x.refunded_amount, 'balance', x.balance, 'issued_at', x.issued_at, 'due_date', x.due_date, 'source', x.source, 'grouped', x.is_grouped) order by x.issued_at desc, x.number)
          from (select * from f order by issued_at desc, number limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_payments(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'factures.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select 'PAYMENT'::text as kind, p.number, p.paid_at as at, c.code as customer_code, c.full_name as customer_name, i.number as invoice, p.amount, p.currency, p.base_amount_usd, p.method, null::text as reason
        from logistics.payment p join logistics.invoice i on i.id = p.invoice_id join logistics.customer c on c.id = p.customer_id where logistics.cc_cust(v_f, c)
         and (not v_f ? 'status' or v_f ->> 'status' = 'PAYMENT')
      union all
      select 'REFUND', r.number, r.created_at, c.code, c.full_name, i.number, -r.amount, r.currency, -r.base_amount_usd, r.method, r.reason
        from logistics.refund r join logistics.invoice i on i.id = r.invoice_id join logistics.customer c on c.id = r.customer_id where logistics.cc_cust(v_f, c) and (not v_f ? 'status' or v_f ->> 'status' = 'REFUND')
      union all
      select 'CREDIT', k.number, k.created_at, c.code, c.full_name, i.number, k.amount, k.currency, null, null, k.reason
        from logistics.credit k join logistics.invoice i on i.id = k.invoice_id join logistics.customer c on c.id = k.customer_id where logistics.cc_cust(v_f, c) and (not v_f ? 'status' or v_f ->> 'status' = 'CREDIT'))
    select jsonb_build_object('total', (select count(*) from (select * from f where (logistics.cc_from(v_f) is null or at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or at < logistics.cc_to(v_f))) a), 'filters', v_f,
      'collected_usd', (select coalesce(sum(base_amount_usd) filter (where kind = 'PAYMENT'), 0) from f where (logistics.cc_from(v_f) is null or at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or at < logistics.cc_to(v_f))),
      'refunded_usd', (select coalesce(-sum(base_amount_usd) filter (where kind = 'REFUND'), 0) from f where (logistics.cc_from(v_f) is null or at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or at < logistics.cc_to(v_f))),
      'items', coalesce((select jsonb_agg(to_jsonb(x) order by x.at desc, x.number) from (select * from f where (logistics.cc_from(v_f) is null or at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or at < logistics.cc_to(v_f)) order by at desc, number limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_tickets(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'clients.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select t.*, c.code as customer_code, c.full_name as customer_name, (select m.author_kind from logistics.support_message m where m.ticket_id = t.id order by m.id desc limit 1) as last_author
        from logistics.support_ticket t join logistics.customer c on c.id = t.customer_id
       where logistics.cc_cust(v_f, c) and (not v_f ? 'status' or t.status = v_f ->> 'status' or (v_f ->> 'status' = 'ACTIVE' and t.status <> 'CLOSED'))
         and (logistics.cc_from(v_f) is null or t.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or t.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'by_status', coalesce((select jsonb_object_agg(g.status, g.n) from (select status, count(*) as n from f group by status) g), '{}'::jsonb),
      'items', coalesce((select jsonb_agg(jsonb_build_object('ticket_id', x.id, 'number', x.number, 'subject', x.subject, 'category', x.category, 'status', x.status, 'customer_code', x.customer_code, 'customer_name', x.customer_name,
          'last_author', x.last_author, 'waiting_hours', case when x.status = 'OPEN' then round(extract(epoch from (now() - x.updated_at)) / 3600)::int end, 'created_at', x.created_at, 'updated_at', x.updated_at,
          'messages', (select count(*) from logistics.support_message m where m.ticket_id = x.id)) order by (x.status = 'OPEN') desc, x.updated_at)
          from (select * from f order by (status = 'OPEN') desc, updated_at limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_ticket(p_actor uuid, p_id uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare t logistics.support_ticket;
begin
  perform logistics.require_right(p_actor, 'clients.lire');
  select * into t from logistics.support_ticket x where x.id = p_id;
  if not found then raise exception 'Ticket introuvable.' using errcode = 'LG002'; end if;
  return jsonb_build_object('ticket_id', t.id, 'number', t.number, 'subject', t.subject, 'category', t.category, 'status', t.status, 'created_at', t.created_at, 'closed_at', t.closed_at,
    'customer', (select jsonb_build_object('code', c.code, 'name', c.full_name, 'email', c.email, 'phone', c.phone) from logistics.customer c where c.id = t.customer_id),
    'parcel', (select p.tracking_number from logistics.parcel p where p.id = t.parcel_id), 'invoice', (select i.number from logistics.invoice i where i.id = t.invoice_id),
    'messages', coalesce((select jsonb_agg(jsonb_build_object('author', m.author_kind, 'staff', (select a.email from auth.users a where a.id = m.author_user_id), 'body', m.body, 'at', m.created_at) order by m.id)
                            from logistics.support_message m where m.ticket_id = t.id), '[]'::jsonb));
end;
$$;


-- 7. Direction : utilisateurs, journal d'audit, réglages ---------------------------------------------------------------------------------------------------
create or replace function logistics.cc_users(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'direction');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select u.*, a.email, a.last_sign_in_at from logistics.app_user u join auth.users a on a.id = u.id
       where (not v_f ? 'status' or u.role = v_f ->> 'status' or (v_f ->> 'status' = 'INACTIVE' and not u.active))
         and (not v_f ? 'customer' or position(lower(v_f ->> 'customer') in lower(a.email)) > 0))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'items', coalesce((select jsonb_agg(jsonb_build_object('user_id', x.id, 'email', x.email, 'role', x.role, 'rights', x.rights, 'active', x.active, 'branch', logistics.branch_label(x.branch_id),
          'driver', exists (select 1 from logistics.driver d where d.user_id = x.id), 'last_sign_in_at', x.last_sign_in_at, 'created_at', x.created_at) order by x.role desc, x.email)
          from (select * from f order by role desc, email limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

create or replace function logistics.cc_audit(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'direction');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select a.* from logistics.audit_log a
       where (not v_f ? 'status' or starts_with(a.action, v_f ->> 'status'))
         and (not v_f ? 'customer' or position(lower(v_f ->> 'customer') in lower(a.actor_label)) > 0)
         and (logistics.cc_from(v_f) is null or a.occurred_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or a.occurred_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'items', coalesce((select jsonb_agg(jsonb_build_object('id', x.id, 'at', x.occurred_at, 'actor', x.actor_label, 'action', x.action, 'entity_type', x.entity_type, 'entity_id', x.entity_id,
          'before', x.before, 'after', x.after, 'metadata', x.metadata, 'correlation_id', x.correlation_id) order by x.occurred_at desc, x.id desc) from (select * from f order by occurred_at desc, id desc limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

-- Les réglages : lecture seule d'un coup d'œil (les modifier passe par les fonctions de la phase 10, direction seulement).
create or replace function logistics.cc_settings(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'direction');
  return jsonb_build_object(
    'organization', (select jsonb_build_object('name', o.name, 'default_currency', o.default_currency) from logistics.organization o order by o.created_at limit 1),
    'branches', coalesce((select jsonb_agg(jsonb_build_object('code', b.code, 'name', b.name, 'kind', b.kind, 'country', b.country, 'city', b.city, 'active', b.active) order by b.code) from logistics.branch b), '[]'::jsonb),
    'warehouses', coalesce((select jsonb_agg(jsonb_build_object('code', w.code, 'name', w.name, 'branch', logistics.branch_label(w.branch_id), 'active', w.active) order by w.code) from logistics.warehouse w), '[]'::jsonb),
    'transport_modes', coalesce((select jsonb_agg(jsonb_build_object('code', m.code, 'active', m.active) order by m.code) from logistics.transport_mode m), '[]'::jsonb),
    'pricing', jsonb_build_object('rate_cards_active', (select count(*) from logistics.rate_card where active), 'zones_active', (select count(*) from logistics.pricing_zone where active),
        'surcharges_active', (select count(*) from logistics.surcharge where active), 'rules_active', (select count(*) from logistics.pricing_rule where active), 'taxes_active', (select count(*) from logistics.tax where active),
        'service_fee', (select coalesce(jsonb_agg(jsonb_build_object('code', f.code, 'amount', f.amount, 'currency', f.currency) order by f.code), '[]'::jsonb) from logistics.service_fee f where f.active),
        'exchange_rates', coalesce((select jsonb_agg(jsonb_build_object('from', x.from_currency, 'to', x.to_currency, 'rate', x.rate, 'valid_from', x.valid_from) order by x.from_currency, x.to_currency)
                                      from (select distinct on (from_currency, to_currency) * from logistics.exchange_rate order by from_currency, to_currency, valid_from desc) x), '[]'::jsonb)),
    'delivery', jsonb_build_object('zones', (select count(*) from logistics.delivery_zone where active), 'vehicles', (select count(*) from logistics.vehicle where active), 'drivers', (select count(*) from logistics.driver where status = 'ACTIVE')),
    'events', jsonb_build_object('pending', (select count(*) from logistics.event_delivery where status = 'PENDING'), 'dead', (select count(*) from logistics.dead_letter)));
end;
$$;


-- 8. L'équipe traite les demandes et le support --------------------------------------------------------------------------------------------------------------
create or replace function logistics.cc_review_pickup(p_actor uuid, p_id uuid, p_approve boolean, p_message text default null, p_date date default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare r logistics.pickup_request; v_corr uuid := gen_random_uuid(); v_task uuid; v_date date;
begin
  perform logistics.require_right(p_actor, 'colis.statut');
  select * into r from logistics.pickup_request x where x.id = p_id for update;
  if not found then raise exception 'Demande introuvable.' using errcode = 'LG002'; end if;
  if r.status <> 'REQUESTED' then raise exception 'La demande % est déjà traitée (%).', r.number, r.status using errcode = 'LG004'; end if;
  if char_length(coalesce(p_message, '')) > 500 then raise exception 'Le message au client est trop long (500 caractères).' using errcode = 'LG005'; end if;
  if p_approve is null then raise exception 'Choisissez : approuver ou refuser.' using errcode = 'LG005'; end if;
  if not p_approve then
    if btrim(coalesce(p_message, '')) = '' then raise exception 'Un message au client est obligatoire pour refuser (il le lira dans son portail).' using errcode = 'LG005'; end if;
    update logistics.pickup_request set status = 'REJECTED', review_message = btrim(p_message), reviewed_by = p_actor, reviewed_at = now() where id = p_id;
    perform logistics.fin_audit(p_actor, 'pickup_request.reject', 'pickup_request', p_id::text, jsonb_build_object('status', 'REQUESTED'), jsonb_build_object('status', 'REJECTED'), v_corr, jsonb_build_object('number', r.number));
    perform logistics.emit('PickupRequestRejected', 'request', p_id::text, v_corr, p_actor, jsonb_build_object('request_id', p_id, 'number', r.number, 'customer_id', r.customer_id));
    return jsonb_build_object('request_id', p_id, 'status', 'REJECTED');
  end if;
  v_date := coalesce(p_date, r.preferred_date);
  if v_date < logistics.today() then raise exception 'La date souhaitée est passée : indiquez une nouvelle date, ou refusez la demande.' using errcode = 'LG005'; end if;
  v_task := (logistics.create_pickup_task(r.customer_id, r.address || case when r.city <> '' then ', ' || r.city else '' end, v_date, p_actor, null, null,
              case r.preferred_window when 'MORNING' then logistics.day_start(v_date) + interval '8 hours' when 'AFTERNOON' then logistics.day_start(v_date) + interval '12 hours' end,
              case r.preferred_window when 'MORNING' then logistics.day_start(v_date) + interval '12 hours' when 'AFTERNOON' then logistics.day_start(v_date) + interval '17 hours' end,
              r.parcels_expected, 0, null, 3, v_corr) ->> 'task_id')::uuid;
  update logistics.pickup_request set status = 'APPROVED', task_id = v_task, review_message = nullif(btrim(coalesce(p_message, '')), ''), reviewed_by = p_actor, reviewed_at = now() where id = p_id;
  perform logistics.fin_audit(p_actor, 'pickup_request.approve', 'pickup_request', p_id::text, jsonb_build_object('status', 'REQUESTED'), jsonb_build_object('status', 'APPROVED', 'task_id', v_task), v_corr, jsonb_build_object('number', r.number));
  perform logistics.emit('PickupRequestApproved', 'request', p_id::text, v_corr, p_actor, jsonb_build_object('request_id', p_id, 'number', r.number, 'customer_id', r.customer_id, 'task_id', v_task, 'date', v_date));
  return jsonb_build_object('request_id', p_id, 'status', 'APPROVED', 'task_id', v_task, 'date', v_date, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.cc_review_delivery(p_actor uuid, p_id uuid, p_approve boolean, p_message text default null, p_hub_branch uuid default null, p_date date default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare r logistics.delivery_request; v_corr uuid := gen_random_uuid(); v_hub uuid; v_date date; v_parcels uuid[]; v_res jsonb;
begin
  perform logistics.require_right(p_actor, 'colis.statut');
  select * into r from logistics.delivery_request x where x.id = p_id for update;
  if not found then raise exception 'Demande introuvable.' using errcode = 'LG002'; end if;
  if r.status <> 'REQUESTED' then raise exception 'La demande % est déjà traitée (%).', r.number, r.status using errcode = 'LG004'; end if;
  if char_length(coalesce(p_message, '')) > 500 then raise exception 'Le message au client est trop long (500 caractères).' using errcode = 'LG005'; end if;
  if p_approve is null then raise exception 'Choisissez : approuver ou refuser.' using errcode = 'LG005'; end if;
  if not p_approve then
    if btrim(coalesce(p_message, '')) = '' then raise exception 'Un message au client est obligatoire pour refuser (il le lira dans son portail).' using errcode = 'LG005'; end if;
    update logistics.delivery_request set status = 'REJECTED', review_message = btrim(p_message), reviewed_by = p_actor, reviewed_at = now() where id = p_id;
    perform logistics.fin_audit(p_actor, 'delivery_request.reject', 'delivery_request', p_id::text, jsonb_build_object('status', 'REQUESTED'), jsonb_build_object('status', 'REJECTED'), v_corr, jsonb_build_object('number', r.number));
    perform logistics.emit('DeliveryRequestRejected', 'request', p_id::text, v_corr, p_actor, jsonb_build_object('request_id', p_id, 'number', r.number, 'customer_id', r.customer_id));
    return jsonb_build_object('request_id', p_id, 'status', 'REJECTED');
  end if;
  v_date := coalesce(p_date, r.preferred_date);
  if v_date < logistics.today() then raise exception 'La date souhaitée est passée : indiquez une nouvelle date, ou refusez la demande.' using errcode = 'LG005'; end if;
  v_hub := coalesce(p_hub_branch, (select b.id from logistics.branch b where b.kind = 'hub' and b.active order by b.code limit 1));
  if v_hub is null then raise exception 'Aucune succursale « hub » active : choisissez le hub de départ.' using errcode = 'LG005'; end if;
  select array_agg(rp.parcel_id order by rp.parcel_id) into v_parcels from logistics.delivery_request_parcel rp where rp.request_id = p_id;
  v_res := logistics.create_delivery(v_parcels, v_hub, v_date, p_actor, r.contact_name, r.contact_phone, r.address || case when r.city <> '' then ', ' || r.city else '' end, null, null, null,
              case r.preferred_window when 'MORNING' then logistics.day_start(v_date) + interval '8 hours' when 'AFTERNOON' then logistics.day_start(v_date) + interval '12 hours' end,
              case r.preferred_window when 'MORNING' then logistics.day_start(v_date) + interval '12 hours' when 'AFTERNOON' then logistics.day_start(v_date) + interval '17 hours' end, 3, false, v_corr);
  update logistics.delivery_request set status = 'APPROVED', delivery_id = (v_res ->> 'delivery_id')::uuid, review_message = nullif(btrim(coalesce(p_message, '')), ''), reviewed_by = p_actor, reviewed_at = now() where id = p_id;
  perform logistics.fin_audit(p_actor, 'delivery_request.approve', 'delivery_request', p_id::text, jsonb_build_object('status', 'REQUESTED'), jsonb_build_object('status', 'APPROVED', 'delivery_id', v_res ->> 'delivery_id'), v_corr, jsonb_build_object('number', r.number));
  perform logistics.emit('DeliveryRequestApproved', 'request', p_id::text, v_corr, p_actor, jsonb_build_object('request_id', p_id, 'number', r.number, 'customer_id', r.customer_id, 'delivery_id', v_res ->> 'delivery_id', 'date', v_date));
  return jsonb_build_object('request_id', p_id, 'status', 'APPROVED', 'delivery_id', v_res ->> 'delivery_id', 'task_id', v_res ->> 'task_id', 'date', v_date, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.cc_reply_ticket(p_actor uuid, p_id uuid, p_body text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare t logistics.support_ticket; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'clients.lire');
  if char_length(btrim(coalesce(p_body, ''))) not between 1 and 4000 then raise exception 'Le message doit compter de 1 à 4000 caractères.' using errcode = 'LG005'; end if;
  select * into t from logistics.support_ticket x where x.id = p_id for update;
  if not found then raise exception 'Ticket introuvable.' using errcode = 'LG002'; end if;
  if t.status = 'CLOSED' then raise exception 'Ce ticket est fermé.' using errcode = 'LG004'; end if;
  if (select count(*) from logistics.support_message m where m.ticket_id = p_id) >= 100 then raise exception 'Ce ticket a atteint 100 messages.' using errcode = 'LG005'; end if;
  insert into logistics.support_message (ticket_id, author_kind, author_user_id, body) values (p_id, 'STAFF', p_actor, btrim(p_body));
  update logistics.support_ticket set status = 'ANSWERED' where id = p_id;
  perform logistics.fin_audit(p_actor, 'ticket.reply', 'support_ticket', p_id::text, jsonb_build_object('status', t.status), jsonb_build_object('status', 'ANSWERED'), v_corr, jsonb_build_object('number', t.number));
  perform logistics.emit('SupportTicketAnswered', 'ticket', p_id::text, v_corr, p_actor, jsonb_build_object('ticket_id', p_id, 'number', t.number, 'customer_id', t.customer_id));
  return jsonb_build_object('ticket_id', p_id, 'status', 'ANSWERED');
end;
$$;

create or replace function logistics.cc_close_ticket(p_actor uuid, p_id uuid)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare t logistics.support_ticket; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'clients.lire');
  select * into t from logistics.support_ticket x where x.id = p_id for update;
  if not found then raise exception 'Ticket introuvable.' using errcode = 'LG002'; end if;
  if t.status = 'CLOSED' then raise exception 'Ce ticket est déjà fermé.' using errcode = 'LG004'; end if;
  update logistics.support_ticket set status = 'CLOSED', closed_at = now() where id = p_id;
  perform logistics.fin_audit(p_actor, 'ticket.close', 'support_ticket', p_id::text, jsonb_build_object('status', t.status), jsonb_build_object('status', 'CLOSED'), v_corr, jsonb_build_object('number', t.number));
  perform logistics.emit('SupportTicketClosedByStaff', 'ticket', p_id::text, v_corr, p_actor, jsonb_build_object('ticket_id', p_id, 'number', t.number, 'customer_id', t.customer_id));
  return jsonb_build_object('ticket_id', p_id, 'status', 'CLOSED');
end;
$$;


-- 9. Façade (acteur = auth.uid(), jamais en paramètre) ---------------------------------------------------------------------------------------------------------
create or replace function public.lg_cc_access() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_access(auth.uid()) $$;
create or replace function public.lg_cc_kpis(p_filters jsonb default null) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_kpis(auth.uid(), p_filters) $$;
create or replace function public.lg_cc_attention() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_attention(auth.uid()) $$;
create or replace function public.lg_cc_flow(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_flow(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_parcels(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_parcels(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_parcel(p_tracking text) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_parcel_detail(auth.uid(), p_tracking) $$;
create or replace function public.lg_cc_shipments(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_shipments(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_warehouse(p_filters jsonb default null) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_warehouse(auth.uid(), p_filters) $$;
create or replace function public.lg_cc_consolidations(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_consolidations(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_transports(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_transports(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_drivers(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_drivers(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_pickups(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_pickups(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_deliveries(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_deliveries(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_customs(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_customs(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_incidents(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_incidents(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_notifications(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_notifications(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_customers(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_customers(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_invoices(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_invoices(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_payments(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_payments(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_tickets(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_tickets(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_ticket(p_id uuid) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_ticket(auth.uid(), p_id) $$;
create or replace function public.lg_cc_users(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_users(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_audit(p_filters jsonb default null, p_limit int default 50, p_offset int default 0) returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_audit(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_cc_settings() returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_settings(auth.uid()) $$;
create or replace function public.lg_cc_review_pickup(p_id uuid, p_approve boolean, p_message text default null, p_date date default null) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cc_review_pickup(auth.uid(), p_id, p_approve, p_message, p_date) $$;
create or replace function public.lg_cc_review_delivery(p_id uuid, p_approve boolean, p_message text default null, p_hub_branch uuid default null, p_date date default null) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cc_review_delivery(auth.uid(), p_id, p_approve, p_message, p_hub_branch, p_date) $$;
create or replace function public.lg_cc_reply_ticket(p_id uuid, p_body text) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cc_reply_ticket(auth.uid(), p_id, p_body) $$;
create or replace function public.lg_cc_close_ticket(p_id uuid) returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cc_close_ticket(auth.uid(), p_id) $$;


-- 10. Tout fermé, sauf la façade ------------------------------------------------------------------------------------------------------------------------------------
do $$
declare r record;
begin
  for r in select tablename from pg_tables where schemaname = 'logistics' loop
    execute format('alter table logistics.%I enable row level security', r.tablename);
    execute format('revoke all on logistics.%I from public, anon, authenticated', r.tablename);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\_%' loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
revoke all on logistics.event_health, logistics.pickup_task, logistics.delivery_task, logistics.customer_balance from public, anon, authenticated;
grant select on logistics.event_health to service_role;

-- Pour retirer SEULEMENT cette étape : supprimer les fonctions public.lg_cc_* et logistics.cc_*, logistics.today(). Aucune table n'est créée ici ; aucune donnée n'est en jeu.
