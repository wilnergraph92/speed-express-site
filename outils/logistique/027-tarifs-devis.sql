-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 27 : les tarifs, les devis et la préparation de la bascule, depuis le tableau de bord
-- -----------------------------------------------------------------------------
-- À passer APRÈS 026, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Le moteur financier du noyau (007, 018) calcule tout, mais ne sait rien calculer tant que la direction n'a pas saisi SES tarifs : une zone
-- par pays, une grille par mode et par zone (même quand le colis porte son propre tarif à la livre, la grille doit exister). L'étape 007 n'a
-- posé que le seul fait connu, 10 $ de frais de service ; aucun prix n'est inventé ici non plus.
-- L'ancienne facturation reste la SEULE source de l'argent en production (finance_setting.mode = 'legacy') : cette étape n'émet aucune
-- facture, n'enregistre aucun paiement et ne bascule rien. Elle ajoute ce qu'il faut pour PRÉPARER la bascule, en lecture :
--   · lg_pricing_overview : toute la configuration des prix (zones, grilles et tranches, règles négociées, suppléments, frais de service,
--     taxes, taux de change) et la COUVERTURE — pour chaque mode et pays où des colis existent, la grille du jour, ou son absence ;
--   · lg_finance_parity_gaps : chaque facture héritée dont le noyau ne retrouve pas le montant, avec son verdict, si elle bloque la bascule,
--     et son examen éventuel (lg_finance_cutover_report n'en donnait que des exemples, sans l'identifiant pour les examiner) ;
--   · lg_cc_quotes : la liste des devis ; lg_quote_preview / lg_create_quote_for : un devis pour un client désigné par son CODE (SES-#####),
--     comme l'équipe le connaît (un devis n'est pas de l'argent : le client le voit dans son portail, rien n'est facturé).
-- Lectures des prix et des devis : « factures.lire » ; devis : « factures.creer » ; écarts de parité : direction. Rejouable sans risque ;
-- aucune donnée supprimée.
-- =============================================================================

-- 1. Toute la configuration des prix, et ce qui manque ---------------------------------------------------------------------------------------
create or replace function logistics.pricing_overview(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'factures.lire');
  return jsonb_build_object(
    'can_manage', logistics.actor_can(p_actor, 'direction'),
    'finance_mode', (select value from logistics.finance_setting where key = 'mode'),
    'zones', coalesce((select jsonb_agg(jsonb_build_object('zone_id', z.id, 'code', z.code, 'name', z.name, 'country', z.country, 'active', z.active) order by z.country, z.code)
                         from logistics.pricing_zone z), '[]'::jsonb),
    'rate_cards', coalesce((select jsonb_agg(jsonb_build_object('rate_card_id', r.id, 'code', r.code, 'name', r.name, 'mode', r.service_mode, 'currency', r.currency,
        'zone', jsonb_build_object('zone_id', z.id, 'code', z.code, 'country', z.country), 'lb_per_ft3', r.lb_per_ft3, 'valid_from', r.valid_from, 'valid_to', r.valid_to, 'active', r.active,
        'current', r.active and r.valid_from <= current_date and (r.valid_to is null or r.valid_to >= current_date),
        'brackets', coalesce((select jsonb_agg(jsonb_build_object('min_lb', b.min_lb, 'max_lb', b.max_lb, 'price_per_lb', b.price_per_lb, 'flat_fee', b.flat_fee, 'min_charge', b.min_charge) order by b.min_lb)
                                from logistics.weight_bracket b where b.rate_card_id = r.id), '[]'::jsonb)) order by z.country, r.service_mode, r.valid_from desc)
        from logistics.rate_card r join logistics.pricing_zone z on z.id = r.pricing_zone_id), '[]'::jsonb),
    'rules', coalesce((select jsonb_agg(jsonb_build_object('rule_id', u.id, 'code', u.code, 'name', u.name, 'kind', u.kind, 'value', u.value, 'currency', u.currency,
        'customer', case when c.id is not null then jsonb_build_object('code', c.code, 'name', c.full_name) end, 'mode', u.service_mode, 'zone', z.code, 'min_weight_lb', u.min_weight_lb,
        'priority', u.priority, 'reason', u.reason, 'valid_from', u.valid_from, 'valid_to', u.valid_to, 'active', u.active) order by u.priority, u.code)
        from logistics.pricing_rule u left join logistics.customer c on c.id = u.customer_id left join logistics.pricing_zone z on z.id = u.pricing_zone_id), '[]'::jsonb),
    'surcharges', coalesce((select jsonb_agg(jsonb_build_object('surcharge_id', s.id, 'code', s.code, 'name', s.name, 'kind', s.kind, 'value', s.value, 'currency', s.currency,
        'mode', s.service_mode, 'active', s.active, 'valid_from', s.valid_from, 'valid_to', s.valid_to) order by s.code) from logistics.surcharge s), '[]'::jsonb),
    'service_fees', coalesce((select jsonb_agg(jsonb_build_object('service_fee_id', f.id, 'code', f.code, 'name', f.name, 'amount', f.amount, 'currency', f.currency,
        'valid_from', f.valid_from, 'valid_to', f.valid_to, 'active', f.active) order by f.currency, f.valid_from desc) from logistics.service_fee f), '[]'::jsonb),
    'taxes', coalesce((select jsonb_agg(jsonb_build_object('tax_id', t.id, 'code', t.code, 'name', t.name, 'rate_percent', t.rate_percent, 'applies_to', t.applies_to, 'country', t.country,
        'valid_from', t.valid_from, 'valid_to', t.valid_to, 'active', t.active) order by t.code) from logistics.tax t), '[]'::jsonb),
    'exchange_rates', coalesce((select jsonb_agg(jsonb_build_object('from', x.from_currency, 'to', x.to_currency, 'rate', x.rate, 'valid_from', x.valid_from) order by x.from_currency, x.to_currency)
        from (select distinct on (from_currency, to_currency) * from logistics.exchange_rate where valid_from <= current_date order by from_currency, to_currency, valid_from desc) x), '[]'::jsonb),
    -- La couverture : là où il y a des colis, y a-t-il aujourd'hui une zone et une grille ? Sans elles, le noyau refuse de calculer.
    'coverage', coalesce((select jsonb_agg(jsonb_build_object('mode', k.service_mode, 'country', k.destination_country, 'parcels', k.n,
        'zone', (select z.code from logistics.pricing_zone z where z.country = k.destination_country and z.active limit 1),
        'rate_card', (select r.code from logistics.rate_card r join logistics.pricing_zone z on z.id = r.pricing_zone_id
                       where r.active and z.active and z.country = k.destination_country and r.service_mode = k.service_mode
                         and r.valid_from <= current_date and (r.valid_to is null or r.valid_to >= current_date) order by r.valid_from desc limit 1)) order by k.n desc)
        from (select service_mode, destination_country, count(*) as n from logistics.parcel group by 1, 2) k), '[]'::jsonb));
end;
$$;


-- 2. Les écarts de parité, un par un, avec de quoi les examiner -----------------------------------------------------------------------------
create or replace function logistics.finance_parity_gaps(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'direction');
  return coalesce((select jsonb_agg(jsonb_build_object('legacy_invoice_id', p.legacy_invoice_id, 'number', p.number, 'legacy_total', p.legacy_total, 'core_total', p.core_total,
      'verdict', p.verdict, 'detail', p.detail, 'blocking', p.verdict in ('UNEXPLAINED', 'NO_PRICING', 'SERVICE_FEE', 'NO_PARCEL', 'CURRENCY') and r.id is null,
      'review', case when r.id is not null then jsonb_build_object('note', r.note, 'at', r.reviewed_at, 'by', coalesce((select email from auth.users where id = r.reviewed_by), '')) end)
      order by (p.verdict in ('UNEXPLAINED', 'NO_PRICING', 'SERVICE_FEE', 'NO_PARCEL', 'CURRENCY') and r.id is null) desc, p.number)
    from logistics.legacy_finance_parity() p
    left join logistics.finance_review r on r.entity = 'legacy_invoice' and r.entity_id = p.legacy_invoice_id::text
   where p.verdict <> 'EQUAL'), '[]'::jsonb);
end;
$$;


-- 3. Les devis ---------------------------------------------------------------------------------------------------------------------------
create or replace function logistics.cc_quotes(p_actor uuid, p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_f jsonb; v_lim int := logistics.cc_lim(p_limit); v_off int := logistics.cc_off(p_offset);
begin
  perform logistics.require_right(p_actor, 'factures.lire');
  v_f := logistics.cc_f(p_filters);
  return (
    with f as (
      select q.*, c.code as c_code, c.full_name as c_name from logistics.quote q join logistics.customer c on c.id = q.customer_id
       where (not v_f ? 'status' or q.status = v_f ->> 'status') and (not v_f ? 'customer' or logistics.cc_cust(v_f, c))
         and (logistics.cc_from(v_f) is null or q.created_at >= logistics.cc_from(v_f)) and (logistics.cc_to(v_f) is null or q.created_at < logistics.cc_to(v_f)))
    select jsonb_build_object('total', (select count(*) from f), 'filters', v_f,
      'items', coalesce((select jsonb_agg(jsonb_build_object('quote_id', x.id, 'number', x.number, 'status',
          case when x.status = 'OFFERED' and x.valid_until < current_date then 'EXPIRED' else x.status end,
          'customer', jsonb_build_object('code', x.c_code, 'name', x.c_name), 'currency', x.currency, 'subtotal', x.subtotal, 'service_fee', x.service_fee,
          'tax_total', x.tax_total, 'total', x.total, 'items', jsonb_array_length(coalesce(x.calculation -> 'items', '[]'::jsonb)),
          'on_date', x.on_date, 'valid_until', x.valid_until, 'cancel_reason', x.cancel_reason, 'created_at', x.created_at) order by x.created_at desc, x.number)
          from (select * from f order by created_at desc, number limit v_lim offset v_off) x), '[]'::jsonb)));
end;
$$;

-- Le client désigné par son code, comme l'équipe le connaît ; sans code, un calcul « au comptoir » pour un visiteur (prix public, sans remise).
create or replace function logistics.customer_by_code(p_code text)
returns uuid language sql stable security definer set search_path = '' as $$
  select id from logistics.customer where upper(code) = upper(btrim(p_code)) limit 1
$$;

create or replace function logistics.quote_preview(p_actor uuid, p_customer_code text, p_currency text, p_items jsonb)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid;
begin
  perform logistics.require_right(p_actor, 'factures.creer');
  if nullif(btrim(coalesce(p_customer_code, '')), '') is not null then
    v_c := logistics.customer_by_code(p_customer_code);
    if v_c is null then raise exception 'Client inconnu : %.', left(btrim(p_customer_code), 40) using errcode = 'LG002'; end if;
  end if;
  return logistics.price_preview(p_actor, v_c, p_currency, p_items, current_date);
end;
$$;

create or replace function logistics.create_quote_for(p_actor uuid, p_customer_code text, p_currency text, p_items jsonb, p_valid_days int default 15)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid;
begin
  perform logistics.require_right(p_actor, 'factures.creer');
  v_c := logistics.customer_by_code(p_customer_code);
  if v_c is null then raise exception 'Client inconnu : %. Un devis s''adresse à un client inscrit (SES-#####).', left(btrim(coalesce(p_customer_code, '')), 40) using errcode = 'LG002'; end if;
  return logistics.create_quote(p_actor, v_c, p_currency, p_items, p_valid_days, current_date);
end;
$$;


-- 4. Les façades, et tout le reste fermé --------------------------------------------------------------------------------------------------
create or replace function public.lg_pricing_overview()
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.pricing_overview(auth.uid()) $$;
create or replace function public.lg_finance_parity_gaps()
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.finance_parity_gaps(auth.uid()) $$;
create or replace function public.lg_cc_quotes(p_filters jsonb default null, p_limit int default 50, p_offset int default 0)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.cc_quotes(auth.uid(), p_filters, p_limit, p_offset) $$;
create or replace function public.lg_quote_preview(p_currency text, p_items jsonb, p_customer_code text default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.quote_preview(auth.uid(), p_customer_code, p_currency, p_items) $$;
create or replace function public.lg_create_quote_for(p_customer_code text, p_currency text, p_items jsonb, p_valid_days int default 15)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_quote_for(auth.uid(), p_customer_code, p_currency, p_items, p_valid_days) $$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('pricing_overview', 'finance_parity_gaps', 'cc_quotes', 'customer_by_code', 'quote_preview', 'create_quote_for') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_pricing_overview', 'lg_finance_parity_gaps', 'lg_cc_quotes', 'lg_quote_preview', 'lg_create_quote_for') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
