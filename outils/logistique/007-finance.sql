-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 7 : le moteur financier
-- -----------------------------------------------------------------------------
-- Phase 10. À coller dans Supabase > SQL Editor APRÈS 001 à 006, après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet ouvert est bien « speed-express-site ».
--
-- Devis, grilles de tarifs, frais de service, surcharges, remises, taxes, taux de change ; factures ; paiements, avoirs, remboursements ;
-- solde client ; dépenses ; revenus. TOUT SE CALCULE ICI, dans la base : le navigateur et l'application n'envoient que des faits
-- (poids, colis, montant encaissé) et ne calculent jamais un prix.
--
-- Principes
--   · Un montant est arrondi au centime, LIGNE PAR LIGNE ; le total d'une facture est la somme de ses lignes arrondies. Jamais l'inverse.
--   · Une facture émise est FIGÉE : ses montants, ses lignes, son numéro ne changent plus, par aucun chemin. On corrige par un AVOIR
--     (explicite, motivé, tracé), on annule, on rembourse. Les paiements, avoirs, remboursements et écritures de revenus sont en ajout seul.
--   · Le tarif est gelé avec le devis, puis avec la facture : changer une grille ne retouche jamais ce qui est déjà émis.
--   · Seules les factures NATIVES (nées d'un devis du noyau) passent par ce moteur. Les factures héritées de l'ancien schéma restent
--     lues, jamais modifiées ici (LG004) : leur reprise sera une étape à part, décidée par le propriétaire.
--
-- Ne touche à aucune ancienne table. Retour arrière au bas du fichier. Rejouable sans risque.
-- =============================================================================

-- 1. Catalogue d'événements --------------------------------------------------------------------------------------------
alter table logistics.event_type drop constraint if exists event_type_aggregate_type_check;
alter table logistics.event_type add constraint event_type_aggregate_type_check
  check (aggregate_type in ('parcel', 'shipment', 'consolidation', 'warehouse', 'delivery', 'pickup', 'trip', 'task', 'driver', 'incident',
                            'customs', 'invoice', 'payment', 'scan', 'quote', 'expense', 'pricing'));
insert into logistics.event_type (code, aggregate_type, description) values
  ('PricingConfigured',   'pricing', 'Tarif, taxe, frais, surcharge, règle ou taux de change posé ou désactivé'),
  ('QuoteCreated',        'quote',   'Devis calculé et figé'),
  ('QuoteCancelled',      'quote',   'Devis annulé'),
  ('InvoiceCreated',      'invoice', 'Facture créée en brouillon depuis un devis'),
  ('InvoiceIssued',       'invoice', 'Facture émise : montants figés'),
  ('InvoicePartiallyPaid','invoice', 'Facture partiellement payée'),
  ('InvoicePaid',         'invoice', 'Facture soldée'),
  ('InvoiceOverdue',      'invoice', 'Facture en retard'),
  ('InvoiceCancelled',    'invoice', 'Facture annulée'),
  ('InvoiceRefunded',     'invoice', 'Facture remboursée en totalité'),
  ('CreditIssued',        'invoice', 'Avoir émis sur une facture'),
  ('PaymentReceived',     'payment', 'Paiement encaissé'),
  ('RefundIssued',        'payment', 'Remboursement effectué'),
  ('ExpenseRecorded',     'expense', 'Dépense enregistrée'),
  ('ExpenseVoided',       'expense', 'Dépense annulée')
on conflict (code) do nothing;


-- 2. Configuration : taux de change, zones, grilles, frais, surcharges, règles, taxes -------------------------------------
-- Un taux ne se corrige pas : on en pose un NOUVEAU, à une date plus récente. La grille, les frais, les surcharges, les règles et les
-- taxes sont versionnés de la même façon : seuls « active » et « valid_to » peuvent changer (voir guard_config).
create table if not exists logistics.exchange_rate (
  id            bigint generated always as identity primary key,
  from_currency text not null check (from_currency in ('USD', 'DOP', 'HTG')),
  to_currency   text not null check (to_currency in ('USD', 'DOP', 'HTG')),
  rate          numeric(18, 8) not null check (rate > 0),
  valid_from    date not null,
  created_by    uuid references logistics.app_user (id) on delete restrict,
  created_at    timestamptz not null default now(),
  check (from_currency <> to_currency),
  unique (from_currency, to_currency, valid_from)
);
comment on table logistics.exchange_rate is '1 unité de from_currency = rate unités de to_currency. Le taux inverse est déduit ; aucune triangulation (DOP → HTG exige sa propre paire).';

create table if not exists logistics.pricing_zone (
  id      uuid primary key default gen_random_uuid(),
  code    text not null unique,
  name    text not null default '',
  country text not null check (country in ('HT', 'DO', 'US')),
  active  boolean not null default true
);
create unique index if not exists pricing_zone_one_active_per_country on logistics.pricing_zone (country) where active;
comment on table logistics.pricing_zone is 'Zone TARIFAIRE (une par pays de destination active). Ne pas confondre avec delivery_zone, le secteur de livraison du dernier kilomètre.';

create table if not exists logistics.rate_card (
  id              uuid primary key default gen_random_uuid(),
  code            text not null unique,
  name            text not null default '',
  service_mode    text not null check (service_mode in ('air', 'sea', 'ground')),
  pricing_zone_id uuid not null references logistics.pricing_zone (id) on delete restrict,
  currency        text not null check (currency in ('USD', 'DOP', 'HTG')),
  lb_per_ft3      numeric(8, 3) check (lb_per_ft3 is null or lb_per_ft3 > 0),
  valid_from      date not null,
  valid_to        date,
  active          boolean not null default true,
  created_by      uuid references logistics.app_user (id) on delete restrict,
  created_at      timestamptz not null default now(),
  check (valid_to is null or valid_to >= valid_from)
);
comment on column logistics.rate_card.lb_per_ft3 is 'Poids volumétrique : si renseigné, on facture le plus grand du poids réel et du volume × ce facteur.';

create table if not exists logistics.weight_bracket (
  id            bigint generated always as identity primary key,
  rate_card_id  uuid not null references logistics.rate_card (id) on delete restrict,
  min_lb        numeric(10, 2) not null check (min_lb >= 0),
  max_lb        numeric(10, 2),
  price_per_lb  numeric(12, 4) not null check (price_per_lb >= 0),
  flat_fee      numeric(12, 2) not null default 0 check (flat_fee >= 0),
  min_charge    numeric(12, 2) not null default 0 check (min_charge >= 0),
  check (max_lb is null or max_lb > min_lb)
);
comment on table logistics.weight_bracket is 'Tranche [min_lb, max_lb[ : fret = max(min_charge, flat_fee + poids facturé × price_per_lb). max_lb nul = sans limite.';

create table if not exists logistics.service_fee (
  id         uuid primary key default gen_random_uuid(),
  code       text not null,
  name       text not null default '',
  amount     numeric(12, 2) not null check (amount >= 0),
  currency   text not null check (currency in ('USD', 'DOP', 'HTG')),
  valid_from date not null,
  valid_to   date,
  active     boolean not null default true,
  created_by uuid references logistics.app_user (id) on delete restrict,
  unique (code, currency, valid_from),
  check (valid_to is null or valid_to >= valid_from)
);
comment on table logistics.service_fee is 'Frais de service : UNE fois par facture, même groupée (règle de l''entreprise : 10 $). Le code « SERVICE » est celui que le moteur applique.';

create table if not exists logistics.surcharge (
  id              uuid primary key default gen_random_uuid(),
  code            text not null unique,
  name            text not null default '',
  kind            text not null check (kind in ('PERCENT', 'FLAT', 'PER_LB')),
  value           numeric(12, 4) not null check (value >= 0),
  currency        text check (currency in ('USD', 'DOP', 'HTG')),
  trigger_flag    text,
  min_weight_lb   numeric(10, 2) check (min_weight_lb is null or min_weight_lb >= 0),
  min_volume_ft3  numeric(10, 3) check (min_volume_ft3 is null or min_volume_ft3 >= 0),
  service_mode    text check (service_mode in ('air', 'sea', 'ground')),
  pricing_zone_id uuid references logistics.pricing_zone (id) on delete restrict,
  taxable         boolean not null default true,
  valid_from      date not null,
  valid_to        date,
  active          boolean not null default true,
  created_by      uuid references logistics.app_user (id) on delete restrict,
  check ((kind = 'PERCENT') = (currency is null)),
  check (kind <> 'PERCENT' or value <= 1000),
  check (valid_to is null or valid_to >= valid_from)
);
comment on table logistics.surcharge is 'Surcharge : s''applique à un colis si toutes ses conditions tiennent (mode, zone, poids facturé minimal, volume minimal, drapeau demandé). PERCENT se calcule sur le fret après remises.';

create table if not exists logistics.pricing_rule (
  id              uuid primary key default gen_random_uuid(),
  code            text not null unique,
  name            text not null default '',
  kind            text not null check (kind in ('RATE_OVERRIDE', 'DISCOUNT_PERCENT', 'DISCOUNT_FLAT')),
  value           numeric(12, 4) not null check (value >= 0),
  currency        text check (currency in ('USD', 'DOP', 'HTG')),
  customer_id     uuid references logistics.customer (id) on delete restrict,
  service_mode    text check (service_mode in ('air', 'sea', 'ground')),
  pricing_zone_id uuid references logistics.pricing_zone (id) on delete restrict,
  min_weight_lb   numeric(10, 2) check (min_weight_lb is null or min_weight_lb >= 0),
  priority        int not null default 100,
  reason          text not null default '',
  valid_from      date not null,
  valid_to        date,
  active          boolean not null default true,
  created_by      uuid references logistics.app_user (id) on delete restrict,
  check ((kind = 'DISCOUNT_PERCENT') = (currency is null)),
  check (kind <> 'DISCOUNT_PERCENT' or value <= 100),
  check (valid_to is null or valid_to >= valid_from)
);
comment on table logistics.pricing_rule is 'RATE_OVERRIDE : tarif négocié par livre (le plus prioritaire gagne, doit être dans la devise de la grille). DISCOUNT_* : remises sur le fret, appliquées par priorité croissante.';

create table if not exists logistics.tax (
  id           uuid primary key default gen_random_uuid(),
  code         text not null unique,
  name         text not null default '',
  rate_percent numeric(7, 4) not null check (rate_percent >= 0 and rate_percent <= 100),
  applies_to   text not null check (applies_to in ('FREIGHT', 'SURCHARGE', 'SERVICE_FEE', 'ALL')),
  country      text check (country in ('HT', 'DO', 'US')),
  valid_from   date not null,
  valid_to     date,
  active       boolean not null default true,
  created_by   uuid references logistics.app_user (id) on delete restrict,
  check (valid_to is null or valid_to >= valid_from)
);
comment on table logistics.tax is 'Taxe en sus (jamais incluse). Pays nul = tous. Calculée par taxe sur la base des lignes concernées, arrondie une fois.';

-- Une grille ou un taux n'est jamais retouché ; seuls « active » et « valid_to » bougent. Rien ne se supprime.
create or replace function logistics.guard_config()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'La configuration tarifaire ne se supprime pas : désactivez-la.' using errcode = 'LG004';
  end if;
  if (to_jsonb(new) - 'active' - 'valid_to') is distinct from (to_jsonb(old) - 'active' - 'valid_to') then
    raise exception 'Une grille, un frais, une surcharge, une règle ou une taxe ne se modifie pas : posez-en une nouvelle (seuls « active » et « valid_to » changent).' using errcode = 'LG004';
  end if;
  return new;
end;
$$;
do $$
declare t text;
begin
  foreach t in array array['pricing_zone', 'rate_card', 'service_fee', 'surcharge', 'pricing_rule', 'tax'] loop
    execute format('drop trigger if exists guard_config on logistics.%I', t);
    execute format('create trigger guard_config before update or delete on logistics.%I for each row execute function logistics.guard_config()', t);
  end loop;
end
$$;
drop trigger if exists weight_bracket_append_only on logistics.weight_bracket;
create trigger weight_bracket_append_only before update or delete on logistics.weight_bracket for each row execute function logistics.forbid_mutation();
drop trigger if exists exchange_rate_append_only on logistics.exchange_rate;
create trigger exchange_rate_append_only before update or delete on logistics.exchange_rate for each row execute function logistics.forbid_mutation();

-- Pas deux grilles actives en même temps pour le même mode et la même zone ; pas deux tranches qui se recouvrent.
create or replace function logistics.guard_rate_card()
returns trigger language plpgsql set search_path = '' as $$
begin
  if new.active and exists (select 1 from logistics.rate_card c
                             where c.id <> new.id and c.active and c.service_mode = new.service_mode and c.pricing_zone_id = new.pricing_zone_id
                               and c.valid_from <= coalesce(new.valid_to, date '9999-12-31') and coalesce(c.valid_to, date '9999-12-31') >= new.valid_from) then
    raise exception 'Une grille active couvre déjà ce mode et cette zone sur cette période.' using errcode = 'LG005';
  end if;
  return new;
end;
$$;
drop trigger if exists guard_rate_card on logistics.rate_card;
create trigger guard_rate_card before insert on logistics.rate_card for each row execute function logistics.guard_rate_card();

create or replace function logistics.guard_weight_bracket()
returns trigger language plpgsql set search_path = '' as $$
begin
  if exists (select 1 from logistics.weight_bracket b
              where b.rate_card_id = new.rate_card_id and b.id <> new.id
                and b.min_lb < coalesce(new.max_lb, 1e12) and new.min_lb < coalesce(b.max_lb, 1e12)) then
    raise exception 'Deux tranches de poids ne peuvent pas se recouvrir.' using errcode = 'LG005';
  end if;
  return new;
end;
$$;
drop trigger if exists guard_weight_bracket on logistics.weight_bracket;
create trigger guard_weight_bracket before insert on logistics.weight_bracket for each row execute function logistics.guard_weight_bracket();

-- Le seul fait connu : 10 $ de frais de service par facture (règle de l'entreprise). Aucun tarif, aucune taxe, aucun taux n'est inventé.
insert into logistics.service_fee (code, name, amount, currency, valid_from)
values ('SERVICE', 'Frais de service', 10, 'USD', date '2000-01-01')
on conflict (code, currency, valid_from) do nothing;


-- 3. Numérotation sans trou ---------------------------------------------------------------------------------------------
create table if not exists logistics.finance_counter (
  kind       text not null,
  year       int  not null,
  last_value int  not null default 0,
  primary key (kind, year)
);
create or replace function logistics.next_number(p_kind text, p_prefix text)
returns text language plpgsql volatile set search_path = '' as $$
declare v_y int := extract(year from now())::int; v_n int;
begin
  insert into logistics.finance_counter as c (kind, year, last_value) values (p_kind, v_y, 1)
  on conflict (kind, year) do update set last_value = c.last_value + 1
  returning c.last_value into v_n;
  return p_prefix || '-' || v_y::text || '-' || lpad(v_n::text, 6, '0');
end;
$$;


-- 4. Devises ------------------------------------------------------------------------------------------------------------
create or replace function logistics.convert_amount(p_amount numeric, p_from text, p_to text, p_on date)
returns numeric language plpgsql stable set search_path = '' as $$
declare v numeric;
begin
  if p_from = p_to then return round(p_amount, 2); end if;
  select rate into v from logistics.exchange_rate where from_currency = p_from and to_currency = p_to and valid_from <= p_on order by valid_from desc limit 1;
  if found then return round(p_amount * v, 2); end if;
  select rate into v from logistics.exchange_rate where from_currency = p_to and to_currency = p_from and valid_from <= p_on order by valid_from desc limit 1;
  if found then return round(p_amount / v, 2); end if;
  raise exception 'Aucun taux de change % → % au %.', p_from, p_to, p_on using errcode = 'LG005';
end;
$$;
-- Le multiplicateur effectif, à titre d'information sur un paiement (le montant, lui, vient de convert_amount).
create or replace function logistics.effective_rate(p_from text, p_to text, p_on date)
returns numeric language plpgsql stable set search_path = '' as $$
declare v numeric;
begin
  if p_from = p_to then return 1; end if;
  select rate into v from logistics.exchange_rate where from_currency = p_from and to_currency = p_to and valid_from <= p_on order by valid_from desc limit 1;
  if found then return v; end if;
  select rate into v from logistics.exchange_rate where from_currency = p_to and to_currency = p_from and valid_from <= p_on order by valid_from desc limit 1;
  if found then return round(1 / v, 8); end if;
  raise exception 'Aucun taux de change % → % au %.', p_from, p_to, p_on using errcode = 'LG005';
end;
$$;


-- 5. LE calcul d'un prix ------------------------------------------------------------------------------------------------
-- Pure : rien n'est écrit. Pour chaque colis :
--   1. poids facturé = poids vérifié (sinon déclaré) ; si la grille a un facteur volumétrique : max(poids, volume × facteur)
--   2. tarif au livre, du plus prioritaire au moins prioritaire :
--        a. tarif imposé sur la ligne (direction seule, motif) ........ fret = poids × tarif
--        b. tarif enregistré sur le colis (ancien « tarif_lb », en USD)  fret = poids × tarif   (devis en USD seulement)
--        c. règle RATE_OVERRIDE (client négocié) ..................... fret = max(min, plat + poids facturé × tarif)
--        d. la tranche de la grille .................................... fret = max(min, plat + poids facturé × tarif)
--      (c) et (d) se calculent dans la devise de la grille puis se convertissent ligne par ligne ; (a) et (b) n'ont rien à convertir.
--   3. remises, par priorité croissante, sur le fret courant (jamais sous zéro)
--   4. surcharges applicables ; les pourcentages portent sur le fret après remises
--   5. UNE fois : les frais de service ; 6. taxes, une par taxe, sur la base des lignes qu'elle vise.
create or replace function logistics.compute_quote(p_customer uuid, p_currency text, p_items jsonb, p_on date, p_can_override boolean default false)
returns jsonb language plpgsql stable set search_path = '' as $$
declare
  v_item jsonb; v_ord int := 0;
  v_par logistics.parcel; v_card logistics.rate_card; v_br logistics.weight_bracket; v_rule record; v_sur record; v_tax record; v_feer logistics.service_fee;
  v_w numeric; v_vol numeric; v_mode text; v_zone uuid; v_country text; v_flags text[]; v_chg numeric; v_rate numeric; v_src text; v_code text; v_pid uuid;
  v_fc numeric; v_freight numeric; v_run numeric; v_amt numeric; v_ovr numeric; v_first_country text;
  v_lines jsonb := '[]'::jsonb; v_out jsonb := '[]'::jsonb; v_bases jsonb := '[]'::jsonb; v_taxes jsonb := '[]'::jsonb;
  v_ftot numeric := 0; v_dtot numeric := 0; v_stot numeric := 0; v_fee numeric := 0; v_ttot numeric := 0; v_surt numeric;
  v_bf numeric; v_bs numeric; v_base numeric; v_modefr text;
begin
  if p_currency is null or p_currency not in ('USD', 'DOP', 'HTG') then raise exception 'Devise inconnue : %.', coalesce(p_currency, '(vide)') using errcode = 'LG005'; end if;
  if p_items is null or jsonb_typeof(p_items) <> 'array' or jsonb_array_length(p_items) = 0 then raise exception 'Un devis contient au moins un colis.' using errcode = 'LG005'; end if;
  if p_on is null then raise exception 'La date du calcul est obligatoire.' using errcode = 'LG005'; end if;

  for v_item in select e from jsonb_array_elements(p_items) e loop
    v_ord := v_ord + 1; v_pid := null; v_par := null; v_ovr := null; v_src := null;
    v_flags := coalesce(array(select jsonb_array_elements_text(coalesce(v_item -> 'flags', '[]'::jsonb))), '{}');
    if nullif(v_item ->> 'parcel_id', '') is not null then
      v_pid := (v_item ->> 'parcel_id')::uuid;
      select * into v_par from logistics.parcel where id = v_pid;
      if not found then raise exception 'Colis introuvable (ligne %).', v_ord using errcode = 'LG002'; end if;
      if p_customer is not null and v_par.customer_id is distinct from p_customer then raise exception 'Le colis % n''appartient pas à ce client : une facture ne réunit que les colis d''un MÊME client.', v_par.tracking_number using errcode = 'LG005'; end if;
      v_w := coalesce(v_par.verified_weight_lb, v_par.weight_lb); v_vol := v_par.volume_ft3; v_mode := v_par.service_mode; v_country := v_par.destination_country;
    else
      v_w := nullif(v_item ->> 'weight_lb', '')::numeric; v_vol := nullif(v_item ->> 'volume_ft3', '')::numeric;
      v_mode := v_item ->> 'service_mode'; v_country := v_item ->> 'destination_country';
    end if;
    if v_w is null or v_w <= 0 then raise exception 'Poids invalide (ligne %) : il doit être supérieur à zéro.', v_ord using errcode = 'LG005'; end if;
    if v_vol is not null and v_vol < 0 then raise exception 'Volume invalide (ligne %).', v_ord using errcode = 'LG005'; end if;
    if v_mode is null or v_mode not in ('air', 'sea', 'ground') then raise exception 'Mode de service inconnu (ligne %).', v_ord using errcode = 'LG005'; end if;
    if v_country is null or v_country not in ('HT', 'DO', 'US') then raise exception 'Pays de destination inconnu (ligne %).', v_ord using errcode = 'LG005'; end if;
    v_first_country := coalesce(v_first_country, v_country);
    v_zone := coalesce(nullif(v_item ->> 'pricing_zone_id', '')::uuid, (select id from logistics.pricing_zone where country = v_country and active));
    if v_zone is null then raise exception 'Aucune zone tarifaire active pour %.', v_country using errcode = 'LG005'; end if;
    select * into v_card from logistics.rate_card
     where active and service_mode = v_mode and pricing_zone_id = v_zone and valid_from <= p_on and (valid_to is null or valid_to >= p_on)
     order by valid_from desc limit 1;
    if not found then raise exception 'Aucune grille tarifaire active (% / zone %) au %.', v_mode, v_country, p_on using errcode = 'LG005'; end if;
    v_chg := case when v_card.lb_per_ft3 is not null and v_vol is not null then greatest(v_w, round(v_vol * v_card.lb_per_ft3, 2)) else v_w end;
    v_modefr := case v_mode when 'air' then 'aérien' when 'sea' then 'maritime' else 'terrestre' end;

    -- a. tarif imposé : direction seule, avec un motif
    if nullif(v_item ->> 'rate_override', '') is not null then
      if not coalesce(p_can_override, false) then raise exception 'Imposer un tarif est réservé à la direction.' using errcode = 'LG003'; end if;
      if btrim(coalesce(v_item ->> 'override_reason', '')) = '' then raise exception 'Un motif est obligatoire pour imposer un tarif (ligne %).', v_ord using errcode = 'LG005'; end if;
      v_ovr := (v_item ->> 'rate_override')::numeric;
      if v_ovr < 0 then raise exception 'Un tarif ne peut pas être négatif.' using errcode = 'LG005'; end if;
      v_src := 'OVERRIDE'; v_rate := v_ovr; v_code := 'OVERRIDE';
    -- b. tarif enregistré sur le colis (ancien « tarif_lb » : USD)
    elsif v_par.id is not null and coalesce(v_par.rate_per_lb, 0) > 0 and p_currency = 'USD' then
      v_src := 'PARCEL'; v_rate := v_par.rate_per_lb; v_code := 'PARCEL';
    end if;

    select * into v_br from logistics.weight_bracket b where b.rate_card_id = v_card.id and b.min_lb <= v_chg and (b.max_lb is null or v_chg < b.max_lb);
    if v_src is null and not found then raise exception 'Aucune tranche de poids pour % lb dans la grille %.', v_chg, v_card.code using errcode = 'LG005'; end if;

    if v_src in ('OVERRIDE', 'PARCEL') then
      v_freight := round(v_w * v_rate, 2); v_chg := v_w;
    else
      -- c. règle de tarif négocié, d. tranche de la grille
      select * into v_rule from logistics.pricing_rule r
       where r.active and r.kind = 'RATE_OVERRIDE' and r.currency = v_card.currency and r.valid_from <= p_on and (r.valid_to is null or r.valid_to >= p_on)
         and (r.customer_id is null or r.customer_id = p_customer) and (r.service_mode is null or r.service_mode = v_mode)
         and (r.pricing_zone_id is null or r.pricing_zone_id = v_zone) and (r.min_weight_lb is null or v_chg >= r.min_weight_lb)
       order by r.priority, r.id limit 1;
      if found then v_src := 'RULE'; v_rate := v_rule.value; v_code := v_rule.code; else v_src := 'CARD'; v_rate := v_br.price_per_lb; v_code := v_card.code; end if;
      v_fc := greatest(v_br.min_charge, round(v_br.flat_fee + v_chg * v_rate, 2));
      v_freight := logistics.convert_amount(v_fc, v_card.currency, p_currency, p_on);
    end if;

    v_lines := v_lines || jsonb_build_object('kind', 'FREIGHT', 'code', v_code, 'parcel_id', v_pid, 'item', v_ord,
                 'description', 'Fret ' || v_modefr || ' ' || v_chg::text || ' lb', 'quantity', v_chg, 'unit_price', v_rate, 'amount', v_freight);
    v_ftot := v_ftot + v_freight; v_run := v_freight; v_bf := 0;

    -- 3. remises
    for v_rule in select * from logistics.pricing_rule r
                   where r.active and r.kind in ('DISCOUNT_PERCENT', 'DISCOUNT_FLAT') and r.valid_from <= p_on and (r.valid_to is null or r.valid_to >= p_on)
                     and (r.customer_id is null or r.customer_id = p_customer) and (r.service_mode is null or r.service_mode = v_mode)
                     and (r.pricing_zone_id is null or r.pricing_zone_id = v_zone) and (r.min_weight_lb is null or v_chg >= r.min_weight_lb)
                   order by r.priority, r.id loop
      v_amt := case v_rule.kind when 'DISCOUNT_PERCENT' then round(v_run * v_rule.value / 100, 2)
                                else least(v_run, logistics.convert_amount(v_rule.value, v_rule.currency, p_currency, p_on)) end;
      if v_amt > 0 then
        v_run := v_run - v_amt; v_dtot := v_dtot + v_amt;
        v_lines := v_lines || jsonb_build_object('kind', 'DISCOUNT', 'code', v_rule.code, 'parcel_id', v_pid, 'item', v_ord, 'description', v_rule.name, 'quantity', 1, 'unit_price', null, 'amount', -v_amt);
      end if;
    end loop;

    -- 4. surcharges
    v_surt := 0;
    for v_sur in select * from logistics.surcharge s
                  where s.active and s.valid_from <= p_on and (s.valid_to is null or s.valid_to >= p_on)
                    and (s.service_mode is null or s.service_mode = v_mode) and (s.pricing_zone_id is null or s.pricing_zone_id = v_zone)
                    and (s.min_weight_lb is null or v_chg >= s.min_weight_lb) and (s.min_volume_ft3 is null or coalesce(v_vol, 0) >= s.min_volume_ft3)
                    and (s.trigger_flag is null or s.trigger_flag = any (v_flags))
                  order by s.code loop
      v_amt := case v_sur.kind when 'PERCENT' then round(v_run * v_sur.value / 100, 2)
                               when 'FLAT' then logistics.convert_amount(v_sur.value, v_sur.currency, p_currency, p_on)
                               else logistics.convert_amount(round(v_chg * v_sur.value, 2), v_sur.currency, p_currency, p_on) end;
      if v_amt > 0 then
        v_stot := v_stot + v_amt; if v_sur.taxable then v_surt := v_surt + v_amt; end if;
        v_lines := v_lines || jsonb_build_object('kind', 'SURCHARGE', 'code', v_sur.code, 'parcel_id', v_pid, 'item', v_ord, 'description', v_sur.name, 'quantity', 1, 'unit_price', null, 'amount', v_amt);
      end if;
    end loop;
    v_bases := v_bases || jsonb_build_object('country', v_country, 'freight_net', v_run, 'surcharge_taxable', v_surt);
    v_out := v_out || jsonb_build_object('item', v_ord, 'parcel_id', v_pid, 'weight_lb', v_w, 'chargeable_lb', v_chg, 'rate_source', v_src, 'rate', v_rate,
                                         'rate_card', v_card.code, 'currency_of_card', v_card.currency, 'freight', v_freight, 'country', v_country);
  end loop;

  -- 5. les frais de service, UNE fois
  select * into v_feer from logistics.service_fee f where f.active and f.code = 'SERVICE' and f.valid_from <= p_on and (f.valid_to is null or f.valid_to >= p_on)
   order by (f.currency = p_currency) desc, f.valid_from desc limit 1;
  if found then
    v_fee := logistics.convert_amount(v_feer.amount, v_feer.currency, p_currency, p_on);
    if v_fee > 0 then v_lines := v_lines || jsonb_build_object('kind', 'SERVICE_FEE', 'code', v_feer.code, 'parcel_id', null, 'item', null, 'description', v_feer.name, 'quantity', 1, 'unit_price', v_fee, 'amount', v_fee); end if;
  end if;

  -- 6. les taxes
  for v_tax in select * from logistics.tax t where t.active and t.valid_from <= p_on and (t.valid_to is null or t.valid_to >= p_on) order by t.code loop
    select coalesce(sum((b ->> 'freight_net')::numeric), 0), coalesce(sum((b ->> 'surcharge_taxable')::numeric), 0) into v_bf, v_bs
      from jsonb_array_elements(v_bases) b where v_tax.country is null or b ->> 'country' = v_tax.country;
    v_base := case v_tax.applies_to when 'FREIGHT' then v_bf when 'SURCHARGE' then v_bs
                when 'SERVICE_FEE' then case when v_tax.country is null or v_tax.country = v_first_country then v_fee else 0 end
                else v_bf + v_bs + case when v_tax.country is null or v_tax.country = v_first_country then v_fee else 0 end end;
    v_amt := round(v_base * v_tax.rate_percent / 100, 2);
    if v_amt > 0 then
      v_ttot := v_ttot + v_amt;
      v_taxes := v_taxes || jsonb_build_object('code', v_tax.code, 'rate_percent', v_tax.rate_percent, 'base', v_base, 'amount', v_amt);
      v_lines := v_lines || jsonb_build_object('kind', 'TAX', 'code', v_tax.code, 'parcel_id', null, 'item', null, 'description', v_tax.name, 'quantity', 1, 'unit_price', v_tax.rate_percent, 'amount', v_amt);
    end if;
  end loop;

  return jsonb_build_object('currency', p_currency, 'customer_id', p_customer, 'on_date', p_on, 'items', v_out, 'lines', v_lines,
           'freight_total', v_ftot, 'discount_total', v_dtot, 'surcharge_total', v_stot, 'subtotal', v_ftot - v_dtot + v_stot,
           'service_fee', v_fee, 'taxes', v_taxes, 'tax_total', v_ttot, 'total', v_ftot - v_dtot + v_stot + v_fee + v_ttot);
end;
$$;


-- 6. Devis, factures, paiements, avoirs, remboursements, revenus, dépenses ----------------------------------------------
create table if not exists logistics.quote (
  id              uuid primary key default gen_random_uuid(),
  number          text not null unique,
  organization_id uuid not null references logistics.organization (id) on delete restrict,
  customer_id     uuid not null references logistics.customer (id) on delete restrict,
  currency        text not null check (currency in ('USD', 'DOP', 'HTG')),
  status          text not null default 'OFFERED' check (status in ('OFFERED', 'INVOICED', 'EXPIRED', 'CANCELLED')),
  on_date         date not null,
  valid_until     date not null,
  subtotal        numeric(14, 2) not null check (subtotal >= 0),
  service_fee     numeric(14, 2) not null check (service_fee >= 0),
  tax_total       numeric(14, 2) not null check (tax_total >= 0),
  total           numeric(14, 2) not null check (total >= 0),
  calculation     jsonb not null,
  cancel_reason   text,
  created_by      uuid references logistics.app_user (id) on delete restrict,
  correlation_id  uuid not null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
comment on column logistics.quote.calculation is 'Le calcul COMPLET, figé à la création : lignes, tarif utilisé, remises, surcharges, taxes. Une grille modifiée plus tard ne le retouche pas.';

alter table logistics.invoice add column if not exists subtotal         numeric(14, 2) not null default 0;
alter table logistics.invoice add column if not exists discount_total   numeric(14, 2) not null default 0;
alter table logistics.invoice add column if not exists surcharge_total  numeric(14, 2) not null default 0;
alter table logistics.invoice add column if not exists tax_total        numeric(14, 2) not null default 0;
alter table logistics.invoice add column if not exists credited_amount  numeric(14, 2) not null default 0 check (credited_amount >= 0);
alter table logistics.invoice add column if not exists refunded_amount  numeric(14, 2) not null default 0 check (refunded_amount >= 0);
alter table logistics.invoice add column if not exists quote_id         uuid references logistics.quote (id) on delete restrict;
alter table logistics.invoice add column if not exists cancelled_at     timestamptz;
alter table logistics.invoice add column if not exists cancel_reason    text;
create unique index if not exists invoice_one_per_quote on logistics.invoice (quote_id) where quote_id is not null;
comment on column logistics.invoice.credited_amount is 'Somme des avoirs. Net dû = total − avoirs ; net payé = payé − remboursé ; solde = net dû − net payé.';

alter table logistics.invoice_item add column if not exists kind text not null default 'FREIGHT' check (kind in ('FREIGHT', 'SURCHARGE', 'DISCOUNT', 'SERVICE_FEE', 'TAX', 'OTHER'));
alter table logistics.invoice_item add column if not exists code text;

create table if not exists logistics.invoice_transition (
  from_status text not null references logistics.invoice_status (code),
  to_status   text not null references logistics.invoice_status (code),
  event_type  text not null references logistics.event_type (code),
  primary key (from_status, to_status)
);
insert into logistics.invoice_transition (from_status, to_status, event_type) values
  ('DRAFT',          'ISSUED',         'InvoiceIssued'),
  ('DRAFT',          'CANCELLED',      'InvoiceCancelled'),
  ('ISSUED',         'PARTIALLY_PAID', 'InvoicePartiallyPaid'),
  ('ISSUED',         'PAID',           'InvoicePaid'),
  ('ISSUED',         'OVERDUE',        'InvoiceOverdue'),
  ('ISSUED',         'CANCELLED',      'InvoiceCancelled'),
  ('PARTIALLY_PAID', 'PAID',           'InvoicePaid'),
  ('PARTIALLY_PAID', 'OVERDUE',        'InvoiceOverdue'),
  ('OVERDUE',        'PAID',           'InvoicePaid'),
  ('OVERDUE',        'CANCELLED',      'InvoiceCancelled'),
  ('PAID',           'REFUNDED',       'InvoiceRefunded')
on conflict do nothing;

create table if not exists logistics.invoice_status_history (
  id             bigint generated always as identity primary key,
  invoice_id     uuid not null references logistics.invoice (id) on delete restrict,
  from_status    text references logistics.invoice_status (code),
  to_status      text not null references logistics.invoice_status (code),
  occurred_at    timestamptz not null default now(),
  actor_user_id  uuid references logistics.app_user (id) on delete restrict,
  actor_label    text not null default '',
  reason         text,
  correlation_id uuid not null
);
drop trigger if exists invoice_status_history_append_only on logistics.invoice_status_history;
create trigger invoice_status_history_append_only before update or delete on logistics.invoice_status_history for each row execute function logistics.forbid_mutation();

create table if not exists logistics.payment (
  id                uuid primary key default gen_random_uuid(),
  number            text not null unique,
  invoice_id        uuid not null references logistics.invoice (id) on delete restrict,
  customer_id       uuid not null references logistics.customer (id) on delete restrict,
  amount            numeric(14, 2) not null check (amount > 0),
  currency          text not null check (currency in ('USD', 'DOP', 'HTG')),
  base_amount_usd   numeric(14, 2) not null,
  tendered_amount   numeric(14, 2) not null check (tendered_amount > 0),
  tendered_currency text not null check (tendered_currency in ('USD', 'DOP', 'HTG')),
  rate_used         numeric(18, 8) not null,
  method            text not null check (method in ('CASH', 'CARD', 'TRANSFER', 'MOBILE_MONEY', 'CHECK', 'OTHER')),
  reference         text not null default '',
  paid_at           timestamptz not null default now(),
  received_by       uuid references logistics.app_user (id) on delete restrict,
  correlation_id    uuid not null,
  created_at        timestamptz not null default now()
);
create index if not exists payment_invoice_idx on logistics.payment (invoice_id);
comment on table logistics.payment is 'Argent reçu, en ajout seul. « amount » est dans la devise de la facture ; « tendered_* » est ce que le client a réellement remis.';

create table if not exists logistics.refund (
  id              uuid primary key default gen_random_uuid(),
  number          text not null unique,
  payment_id      uuid not null references logistics.payment (id) on delete restrict,
  invoice_id      uuid not null references logistics.invoice (id) on delete restrict,
  customer_id     uuid not null references logistics.customer (id) on delete restrict,
  amount          numeric(14, 2) not null check (amount > 0),
  currency        text not null check (currency in ('USD', 'DOP', 'HTG')),
  base_amount_usd numeric(14, 2) not null,
  method          text not null check (method in ('CASH', 'CARD', 'TRANSFER', 'MOBILE_MONEY', 'CHECK', 'OTHER')),
  reason          text not null check (btrim(reason) <> ''),
  refunded_by     uuid references logistics.app_user (id) on delete restrict,
  correlation_id  uuid not null,
  created_at      timestamptz not null default now()
);
comment on table logistics.refund is 'Argent rendu, en ajout seul. Plafonné à ce qui a été payé EN TROP par rapport à ce qui est dû : un avoir précède tout remboursement d''une facture valable.';

create table if not exists logistics.credit (
  id             uuid primary key default gen_random_uuid(),
  number         text not null unique,
  invoice_id     uuid not null references logistics.invoice (id) on delete restrict,
  customer_id    uuid not null references logistics.customer (id) on delete restrict,
  amount         numeric(14, 2) not null check (amount > 0),
  net_amount     numeric(14, 2) not null,
  tax_amount     numeric(14, 2) not null,
  currency       text not null check (currency in ('USD', 'DOP', 'HTG')),
  reason         text not null check (btrim(reason) <> ''),
  issued_by      uuid references logistics.app_user (id) on delete restrict,
  correlation_id uuid not null,
  created_at     timestamptz not null default now(),
  check (net_amount + tax_amount = amount)
);
comment on table logistics.credit is 'Avoir (note de crédit) : la SEULE façon de corriger une facture émise. Ajout seul, motif obligatoire, direction.';

create table if not exists logistics.revenue_entry (
  id             bigint generated always as identity primary key,
  invoice_id     uuid not null references logistics.invoice (id) on delete restrict,
  entry_date     date not null default current_date,
  category       text not null check (category in ('FREIGHT', 'SURCHARGE', 'SERVICE_FEE', 'TAX', 'CREDIT_NOTE', 'CANCELLATION')),
  net_amount     numeric(14, 2) not null default 0,
  tax_amount     numeric(14, 2) not null default 0,
  currency       text not null check (currency in ('USD', 'DOP', 'HTG')),
  net_base_usd   numeric(14, 2) not null default 0,
  tax_base_usd   numeric(14, 2) not null default 0,
  ref_id         text,
  correlation_id uuid not null,
  created_at     timestamptz not null default now()
);
create index if not exists revenue_entry_date_idx on logistics.revenue_entry (entry_date);
comment on table logistics.revenue_entry is 'Revenu reconnu À L''ÉMISSION (hors taxe) ; les avoirs et annulations l''inversent par des lignes négatives. La taxe est collectée pour l''État, pas un revenu : colonne à part.';

create table if not exists logistics.expense (
  id              uuid primary key default gen_random_uuid(),
  number          text not null unique,
  category        text not null check (category in ('TRANSPORT', 'CUSTOMS', 'FUEL', 'SALARY', 'RENT', 'UTILITIES', 'MAINTENANCE', 'PACKAGING', 'OTHER')),
  description     text not null default '',
  amount          numeric(14, 2) not null check (amount > 0),
  currency        text not null check (currency in ('USD', 'DOP', 'HTG')),
  base_amount_usd numeric(14, 2) not null,
  incurred_on     date not null,
  shipment_id     uuid references logistics.shipment (id) on delete restrict,
  supplier        text not null default '',
  status          text not null default 'RECORDED' check (status in ('RECORDED', 'VOIDED')),
  void_reason     text,
  voided_by       uuid references logistics.app_user (id) on delete restrict,
  voided_at       timestamptz,
  recorded_by     uuid references logistics.app_user (id) on delete restrict,
  correlation_id  uuid not null,
  created_at      timestamptz not null default now(),
  check ((status = 'VOIDED') = (voided_at is not null))
);
create index if not exists expense_date_idx on logistics.expense (incurred_on);

do $$
declare t text;
begin
  foreach t in array array['payment', 'refund', 'credit', 'revenue_entry'] loop
    execute format('drop trigger if exists %I on logistics.%I', t || '_append_only', t);
    execute format('create trigger %I before update or delete on logistics.%I for each row execute function logistics.forbid_mutation()', t || '_append_only', t);
  end loop;
end
$$;

-- Un devis ne change que de statut, dans un seul sens.
create or replace function logistics.guard_quote()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then raise exception 'Un devis ne se supprime pas : on l''annule.' using errcode = 'LG004'; end if;
  if (to_jsonb(new) - 'status' - 'cancel_reason' - 'updated_at') is distinct from (to_jsonb(old) - 'status' - 'cancel_reason' - 'updated_at') then
    raise exception 'Un devis est figé : seul son statut change.' using errcode = 'LG004';
  end if;
  if new.status is distinct from old.status and not (old.status = 'OFFERED' and new.status in ('INVOICED', 'EXPIRED', 'CANCELLED')) then
    raise exception 'Devis % : passage % → % interdit.', old.number, old.status, new.status using errcode = 'LG001';
  end if;
  return new;
end;
$$;
drop trigger if exists guard_quote on logistics.quote;
create trigger guard_quote before update or delete on logistics.quote for each row execute function logistics.guard_quote();

-- Une dépense ne se supprime pas et ne se corrige pas : on l'ANNULE, avec un motif.
create or replace function logistics.guard_expense()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then raise exception 'Une dépense ne se supprime pas : on l''annule.' using errcode = 'LG004'; end if;
  if (to_jsonb(new) - 'status' - 'void_reason' - 'voided_by' - 'voided_at') is distinct from (to_jsonb(old) - 'status' - 'void_reason' - 'voided_by' - 'voided_at') then
    raise exception 'Une dépense enregistrée est figée : annulez-la et saisissez-en une autre.' using errcode = 'LG004';
  end if;
  if new.status is distinct from old.status and not (old.status = 'RECORDED' and new.status = 'VOIDED') then
    raise exception 'Dépense % : passage % → % interdit.', old.number, old.status, new.status using errcode = 'LG001';
  end if;
  return new;
end;
$$;
drop trigger if exists guard_expense on logistics.expense;
create trigger guard_expense before update or delete on logistics.expense for each row execute function logistics.guard_expense();


-- 7. Une facture du moteur est figée ------------------------------------------------------------------------------------
create or replace function logistics.guard_invoice()
returns trigger language plpgsql set search_path = '' as $$
declare v_op boolean := coalesce(current_setting('logistics.finance_op', true), 'off') = 'on';
        v_mv boolean := coalesce(current_setting('logistics.invoice_move', true), 'off') = 'on';
begin
  if tg_op = 'DELETE' then
    if old.status_authority = 'core' or old.source = 'native' then raise exception 'Une facture ne se supprime jamais : on l''annule.' using errcode = 'LG004'; end if;
    return old;
  end if;
  if tg_op = 'INSERT' then
    if new.source = 'native' then
      if not v_op then raise exception 'Une facture native ne naît que d''un devis (logistics.invoice_from_quote).' using errcode = 'LG004'; end if;
      if new.status <> 'DRAFT' or new.status_authority <> 'core' then raise exception 'Une facture naît en brouillon, sous l''autorité du noyau.' using errcode = 'LG001'; end if;
    end if;
    return new;
  end if;
  if old.status_authority = 'core' then
    if new.status_authority <> 'core' then raise exception 'L''autorité d''une facture du noyau ne revient jamais à l''ancien schéma.' using errcode = 'LG004'; end if;
    if not v_op then raise exception 'Facture gérée par le moteur financier : modification directe refusée. Corrigez par un avoir, un paiement, un remboursement ou une annulation.' using errcode = 'LG004'; end if;
    if new.status is distinct from old.status and not v_mv then raise exception 'Le statut d''une facture ne change que par une transition autorisée.' using errcode = 'LG001'; end if;
    if old.status <> 'DRAFT'
       and (new.number, new.customer_id, new.currency, new.total, new.subtotal, new.discount_total, new.surcharge_total, new.tax_total, new.service_fee, new.is_grouped, new.organization_id, new.quote_id)
           is distinct from
           (old.number, old.customer_id, old.currency, old.total, old.subtotal, old.discount_total, old.surcharge_total, old.tax_total, old.service_fee, old.is_grouped, old.organization_id, old.quote_id) then
      raise exception 'Facture finalisée : montants, devise, client et numéro sont figés. Corrigez par un avoir.' using errcode = 'LG004';
    end if;
  elsif new.status_authority = 'core' then
    raise exception 'La reprise d''une facture héritée par le moteur financier n''est pas ouverte : elle reste gérée par l''ancien schéma.' using errcode = 'LG004';
  end if;
  return new;
end;
$$;
drop trigger if exists guard_invoice on logistics.invoice;
create trigger guard_invoice before insert or update or delete on logistics.invoice for each row execute function logistics.guard_invoice();

create or replace function logistics.guard_invoice_item()
returns trigger language plpgsql set search_path = '' as $$
declare v_op boolean := coalesce(current_setting('logistics.finance_op', true), 'off') = 'on'; v_inv logistics.invoice;
begin
  select * into v_inv from logistics.invoice where id = coalesce(new.invoice_id, old.invoice_id);
  if v_inv.status_authority is distinct from 'core' then return coalesce(new, old); end if;
  if tg_op = 'UPDATE' or not v_op or v_inv.status <> 'DRAFT' then
    raise exception 'Les lignes d''une facture du moteur sont figées : on ne les ajoute qu''à la création du brouillon.' using errcode = 'LG004';
  end if;
  return coalesce(new, old);
end;
$$;
drop trigger if exists guard_invoice_item on logistics.invoice_item;
create trigger guard_invoice_item before insert or update or delete on logistics.invoice_item for each row execute function logistics.guard_invoice_item();


-- 8. Outils internes -----------------------------------------------------------------------------------------------------
create or replace function logistics.fin_audit(p_actor uuid, p_action text, p_type text, p_id text, p_before jsonb, p_after jsonb, p_corr uuid, p_meta jsonb default '{}'::jsonb)
returns void language plpgsql volatile set search_path = '' as $$
begin
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, before, after, correlation_id, metadata)
  values (p_actor, coalesce((select email from auth.users where id = p_actor), 'system'), p_action, p_type, p_id, p_before, p_after, p_corr, coalesce(p_meta, '{}'::jsonb));
end;
$$;
create or replace function logistics.invoice_balance(p_inv logistics.invoice)
returns numeric language sql immutable set search_path = '' as $$
  select (p_inv.total - p_inv.credited_amount) - (p_inv.paid_amount - p_inv.refunded_amount)
$$;

-- Le statut qui DÉCOULE des montants. Brouillon, annulée et remboursée ne se déduisent pas.
create or replace function logistics.derive_invoice_status(p_inv logistics.invoice, p_today date)
returns text language plpgsql immutable set search_path = '' as $$
declare v_nt numeric := p_inv.total - p_inv.credited_amount; v_np numeric := p_inv.paid_amount - p_inv.refunded_amount;
begin
  if p_inv.status in ('DRAFT', 'CANCELLED', 'REFUNDED') then return p_inv.status; end if;
  if v_nt <= 0 then
    if p_inv.paid_amount = 0 then return 'CANCELLED'; end if;
    if v_np <= 0 then return 'REFUNDED'; end if;
    return 'PAID';
  end if;
  if v_nt - v_np <= 0 then return 'PAID'; end if;
  -- Un retard constaté ne s'efface que par le paiement du solde : un paiement partiel ne sort pas une facture du retard.
  if p_inv.status = 'OVERDUE' then return 'OVERDUE'; end if;
  if p_inv.due_date is not null and p_inv.due_date < p_today then return 'OVERDUE'; end if;
  if v_np > 0 then return 'PARTIALLY_PAID'; end if;
  return 'ISSUED';
end;
$$;

create or replace function logistics.move_invoice(p_invoice uuid, p_to text, p_actor uuid, p_corr uuid, p_reason text default null)
returns logistics.invoice language plpgsql volatile set search_path = '' as $$
declare v_i logistics.invoice; v_tr logistics.invoice_transition; v_prev text := coalesce(current_setting('logistics.finance_op', true), 'off');
begin
  select * into v_i from logistics.invoice where id = p_invoice for update;
  if not found then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  select * into v_tr from logistics.invoice_transition where from_status = v_i.status and to_status = p_to;
  if not found then raise exception 'Transition de facture non autorisée : % → %.', v_i.status, p_to using errcode = 'LG001'; end if;
  perform set_config('logistics.finance_op', 'on', true); perform set_config('logistics.invoice_move', 'on', true);
  update logistics.invoice set status = p_to,
         paid_at = case when p_to = 'PAID' then now() else paid_at end,
         cancelled_at = case when p_to = 'CANCELLED' then now() else cancelled_at end,
         cancel_reason = case when p_to = 'CANCELLED' then p_reason else cancel_reason end
   where id = p_invoice returning * into v_i;
  perform set_config('logistics.invoice_move', 'off', true); perform set_config('logistics.finance_op', v_prev, true);
  insert into logistics.invoice_status_history (invoice_id, from_status, to_status, actor_user_id, actor_label, reason, correlation_id)
  values (p_invoice, v_tr.from_status, p_to, p_actor, coalesce((select email from auth.users where id = p_actor), 'system'), p_reason, p_corr);
  perform logistics.fin_audit(p_actor, 'invoice.transition', 'invoice', p_invoice::text, jsonb_build_object('status', v_tr.from_status), jsonb_build_object('status', p_to), p_corr, jsonb_build_object('reason', p_reason));
  perform logistics.emit(v_tr.event_type, 'invoice', p_invoice::text, p_corr, p_actor, jsonb_build_object('invoice_id', p_invoice, 'number', v_i.number, 'from_status', v_tr.from_status, 'to_status', p_to, 'reason', p_reason));
  return v_i;
end;
$$;

-- Recalcule le statut d'après les montants et fait la transition si besoin. Rend le statut final.
create or replace function logistics.apply_invoice_status(p_invoice uuid, p_actor uuid, p_corr uuid, p_today date default current_date)
returns text language plpgsql volatile set search_path = '' as $$
declare v_i logistics.invoice; v_new text;
begin
  select * into v_i from logistics.invoice where id = p_invoice;
  v_new := logistics.derive_invoice_status(v_i, p_today);
  if v_new <> v_i.status then perform logistics.move_invoice(p_invoice, v_new, p_actor, p_corr); end if;
  return v_new;
end;
$$;

create or replace function logistics.base_amount(p_amount numeric, p_currency text, p_on date)
returns numeric language sql stable set search_path = '' as $$ select logistics.convert_amount(p_amount, p_currency, 'USD', p_on) $$;


-- 9. Configuration (direction seulement) ------------------------------------------------------------------------------------
create or replace function logistics.cfg_done(p_actor uuid, p_kind text, p_id text, p_code text, p_corr uuid)
returns void language plpgsql volatile set search_path = '' as $$
begin
  perform logistics.fin_audit(p_actor, 'pricing.configure', p_kind, p_id, null, jsonb_build_object('code', p_code), p_corr);
  perform logistics.emit('PricingConfigured', 'pricing', p_id, p_corr, p_actor, jsonb_build_object('kind', p_kind, 'id', p_id, 'code', p_code));
end;
$$;

create or replace function logistics.set_exchange_rate(p_actor uuid, p_from text, p_to text, p_rate numeric, p_valid_from date)
returns bigint language plpgsql volatile security definer set search_path = '' as $$
declare v_id bigint; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  insert into logistics.exchange_rate (from_currency, to_currency, rate, valid_from, created_by) values (p_from, p_to, p_rate, coalesce(p_valid_from, current_date), p_actor) returning id into v_id;
  perform logistics.cfg_done(p_actor, 'exchange_rate', v_id::text, p_from || '>' || p_to, v_corr);
  return v_id;
end;
$$;

create or replace function logistics.create_pricing_zone(p_actor uuid, p_code text, p_name text, p_country text)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  insert into logistics.pricing_zone (code, name, country) values (upper(btrim(p_code)), p_name, p_country) returning id into v_id;
  perform logistics.cfg_done(p_actor, 'pricing_zone', v_id::text, upper(btrim(p_code)), v_corr);
  return v_id;
end;
$$;

create or replace function logistics.create_rate_card(p_actor uuid, p_code text, p_name text, p_mode text, p_zone uuid, p_currency text, p_valid_from date, p_valid_to date, p_lb_per_ft3 numeric, p_brackets jsonb)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid := gen_random_uuid(); v_corr uuid := gen_random_uuid(); b jsonb;
begin
  perform logistics.require_right(p_actor, 'direction');
  if p_brackets is null or jsonb_typeof(p_brackets) <> 'array' or jsonb_array_length(p_brackets) = 0 then raise exception 'Une grille contient au moins une tranche de poids.' using errcode = 'LG005'; end if;
  insert into logistics.rate_card (id, code, name, service_mode, pricing_zone_id, currency, lb_per_ft3, valid_from, valid_to, created_by)
  values (v_id, upper(btrim(p_code)), p_name, p_mode, p_zone, p_currency, p_lb_per_ft3, coalesce(p_valid_from, current_date), p_valid_to, p_actor);
  for b in select e from jsonb_array_elements(p_brackets) e loop
    insert into logistics.weight_bracket (rate_card_id, min_lb, max_lb, price_per_lb, flat_fee, min_charge)
    values (v_id, (b ->> 'min_lb')::numeric, nullif(b ->> 'max_lb', '')::numeric, (b ->> 'price_per_lb')::numeric, coalesce((b ->> 'flat_fee')::numeric, 0), coalesce((b ->> 'min_charge')::numeric, 0));
  end loop;
  perform logistics.cfg_done(p_actor, 'rate_card', v_id::text, upper(btrim(p_code)), v_corr);
  return v_id;
end;
$$;

create or replace function logistics.create_service_fee(p_actor uuid, p_code text, p_name text, p_amount numeric, p_currency text, p_valid_from date)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  insert into logistics.service_fee (code, name, amount, currency, valid_from, created_by) values (upper(btrim(p_code)), p_name, p_amount, p_currency, coalesce(p_valid_from, current_date), p_actor) returning id into v_id;
  perform logistics.cfg_done(p_actor, 'service_fee', v_id::text, upper(btrim(p_code)), v_corr);
  return v_id;
end;
$$;

create or replace function logistics.create_surcharge(p_actor uuid, p_code text, p_name text, p_kind text, p_value numeric, p_currency text, p_trigger_flag text, p_min_weight_lb numeric,
                                                       p_min_volume_ft3 numeric, p_service_mode text, p_zone uuid, p_taxable boolean, p_valid_from date, p_valid_to date)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  insert into logistics.surcharge (code, name, kind, value, currency, trigger_flag, min_weight_lb, min_volume_ft3, service_mode, pricing_zone_id, taxable, valid_from, valid_to, created_by)
  values (upper(btrim(p_code)), p_name, p_kind, p_value, p_currency, p_trigger_flag, p_min_weight_lb, p_min_volume_ft3, p_service_mode, p_zone, coalesce(p_taxable, true), coalesce(p_valid_from, current_date), p_valid_to, p_actor) returning id into v_id;
  perform logistics.cfg_done(p_actor, 'surcharge', v_id::text, upper(btrim(p_code)), v_corr);
  return v_id;
end;
$$;

create or replace function logistics.create_pricing_rule(p_actor uuid, p_code text, p_name text, p_kind text, p_value numeric, p_currency text, p_customer uuid, p_service_mode text, p_zone uuid,
                                                          p_min_weight_lb numeric, p_priority int, p_reason text, p_valid_from date, p_valid_to date)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour poser une règle de prix.' using errcode = 'LG005'; end if;
  insert into logistics.pricing_rule (code, name, kind, value, currency, customer_id, service_mode, pricing_zone_id, min_weight_lb, priority, reason, valid_from, valid_to, created_by)
  values (upper(btrim(p_code)), p_name, p_kind, p_value, p_currency, p_customer, p_service_mode, p_zone, p_min_weight_lb, coalesce(p_priority, 100), p_reason, coalesce(p_valid_from, current_date), p_valid_to, p_actor) returning id into v_id;
  perform logistics.cfg_done(p_actor, 'pricing_rule', v_id::text, upper(btrim(p_code)), v_corr);
  return v_id;
end;
$$;

create or replace function logistics.create_tax(p_actor uuid, p_code text, p_name text, p_rate_percent numeric, p_applies_to text, p_country text, p_valid_from date, p_valid_to date)
returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  insert into logistics.tax (code, name, rate_percent, applies_to, country, valid_from, valid_to, created_by)
  values (upper(btrim(p_code)), p_name, p_rate_percent, p_applies_to, p_country, coalesce(p_valid_from, current_date), p_valid_to, p_actor) returning id into v_id;
  perform logistics.cfg_done(p_actor, 'tax', v_id::text, upper(btrim(p_code)), v_corr);
  return v_id;
end;
$$;

-- Désactiver (jamais supprimer) un élément de configuration.
create or replace function logistics.set_pricing_active(p_actor uuid, p_kind text, p_id uuid, p_active boolean)
returns void language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := gen_random_uuid(); v_n int;
begin
  perform logistics.require_right(p_actor, 'direction');
  if p_kind not in ('pricing_zone', 'rate_card', 'service_fee', 'surcharge', 'pricing_rule', 'tax') then raise exception 'Type de configuration inconnu : %.', p_kind using errcode = 'LG005'; end if;
  execute format('update logistics.%I set active = $1 where id = $2', p_kind) using p_active, p_id;
  get diagnostics v_n = row_count;
  if v_n = 0 then raise exception 'Élément introuvable.' using errcode = 'LG002'; end if;
  perform logistics.cfg_done(p_actor, p_kind, p_id::text, case when p_active then 'activate' else 'deactivate' end, v_corr);
end;
$$;


-- 10. Devis -------------------------------------------------------------------------------------------------------------------
-- Les tarifs au livre ont jusqu'à quatre décimales : la colonne de la phase 5 (deux décimales) les arrondissait.
alter table logistics.invoice_item alter column unit_price type numeric(12, 4);

create or replace function logistics.price_preview(p_actor uuid, p_customer uuid, p_currency text, p_items jsonb, p_on date default current_date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'factures.creer');
  return logistics.compute_quote(p_customer, p_currency, p_items, coalesce(p_on, current_date), logistics.actor_can(p_actor, 'direction'));
end;
$$;

create or replace function logistics.create_quote(p_actor uuid, p_customer uuid, p_currency text, p_items jsonb, p_valid_days int default 15, p_on date default current_date, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_calc jsonb; v_id uuid := gen_random_uuid(); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_num text; v_org uuid; v_on date := coalesce(p_on, current_date);
begin
  perform logistics.require_right(p_actor, 'factures.creer');
  select organization_id into v_org from logistics.customer where id = p_customer;
  if not found then raise exception 'Client introuvable.' using errcode = 'LG002'; end if;
  if p_valid_days is null or p_valid_days < 0 or p_valid_days > 365 then raise exception 'Durée de validité invalide (0 à 365 jours).' using errcode = 'LG005'; end if;
  v_calc := logistics.compute_quote(p_customer, p_currency, p_items, v_on, logistics.actor_can(p_actor, 'direction'));
  v_num := logistics.next_number('quote', 'QUO');
  insert into logistics.quote (id, number, organization_id, customer_id, currency, on_date, valid_until, subtotal, service_fee, tax_total, total, calculation, created_by, correlation_id)
  values (v_id, v_num, v_org, p_customer, p_currency, v_on, v_on + p_valid_days, (v_calc ->> 'subtotal')::numeric, (v_calc ->> 'service_fee')::numeric, (v_calc ->> 'tax_total')::numeric, (v_calc ->> 'total')::numeric, v_calc, p_actor, v_corr);
  perform logistics.fin_audit(p_actor, 'quote.create', 'quote', v_id::text, null, jsonb_build_object('number', v_num, 'total', v_calc -> 'total', 'currency', p_currency), v_corr);
  perform logistics.emit('QuoteCreated', 'quote', v_id::text, v_corr, p_actor, jsonb_build_object('quote_id', v_id, 'number', v_num, 'customer_id', p_customer, 'total', v_calc -> 'total', 'currency', p_currency));
  return jsonb_build_object('quote_id', v_id, 'number', v_num, 'status', 'OFFERED', 'valid_until', v_on + p_valid_days, 'total', v_calc -> 'total', 'currency', p_currency, 'calculation', v_calc, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.cancel_quote(p_actor uuid, p_quote uuid, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_q logistics.quote; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'factures.creer');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif d''annulation est obligatoire.' using errcode = 'LG005'; end if;
  select * into v_q from logistics.quote where id = p_quote for update;
  if not found then raise exception 'Devis introuvable.' using errcode = 'LG002'; end if;
  if v_q.status <> 'OFFERED' then raise exception 'Devis %, déjà %.', v_q.number, v_q.status using errcode = 'LG004'; end if;
  update logistics.quote set status = 'CANCELLED', cancel_reason = p_reason, updated_at = now() where id = p_quote;
  perform logistics.fin_audit(p_actor, 'quote.cancel', 'quote', p_quote::text, jsonb_build_object('status', 'OFFERED'), jsonb_build_object('status', 'CANCELLED'), v_corr, jsonb_build_object('reason', p_reason));
  perform logistics.emit('QuoteCancelled', 'quote', p_quote::text, v_corr, p_actor, jsonb_build_object('quote_id', p_quote, 'reason', p_reason));
  return jsonb_build_object('quote_id', p_quote, 'status', 'CANCELLED');
end;
$$;

create or replace function logistics.expire_quotes(p_actor uuid)
returns int language plpgsql volatile security definer set search_path = '' as $$
declare v_n int;
begin
  perform logistics.require_right(p_actor, 'factures.modifier');
  update logistics.quote set status = 'EXPIRED', updated_at = now() where status = 'OFFERED' and valid_until < current_date;
  get diagnostics v_n = row_count;
  return v_n;
end;
$$;


-- 11. Factures -----------------------------------------------------------------------------------------------------------------
create or replace function logistics.invoice_from_quote(p_actor uuid, p_quote uuid, p_due_days int default 30, p_issue boolean default false, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_q logistics.quote; v_id uuid := gen_random_uuid(); v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_calc jsonb; v_it jsonb; v_pid uuid; v_n int := 0; v_par logistics.parcel;
  v_grouped boolean; v_res jsonb;
begin
  perform logistics.require_right(p_actor, 'factures.creer');
  select * into v_q from logistics.quote where id = p_quote for update;
  if not found then raise exception 'Devis introuvable.' using errcode = 'LG002'; end if;
  if v_q.status <> 'OFFERED' then raise exception 'Devis %, déjà % : il ne se facture qu''une fois.', v_q.number, v_q.status using errcode = 'LG004'; end if;
  if v_q.valid_until < current_date then raise exception 'Devis % expiré le % : recalculez-le.', v_q.number, v_q.valid_until using errcode = 'LG004'; end if;
  v_calc := v_q.calculation;
  for v_it in select e from jsonb_array_elements(v_calc -> 'items') e loop
    v_pid := nullif(v_it ->> 'parcel_id', '')::uuid;
    if v_pid is not null then
      select * into v_par from logistics.parcel where id = v_pid;
      if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
      if v_par.customer_id is distinct from v_q.customer_id then raise exception 'Le colis % n''appartient pas au client du devis.', v_par.tracking_number using errcode = 'LG005'; end if;
      if exists (select 1 from logistics.invoice_item it join logistics.invoice i on i.id = it.invoice_id
                  where it.parcel_id = v_pid and it.kind = 'FREIGHT' and i.status not in ('CANCELLED', 'REFUNDED')) then
        raise exception 'Le colis % est déjà facturé.', v_par.tracking_number using errcode = 'LG005';
      end if;
    end if;
  end loop;
  v_grouped := (select count(distinct (e ->> 'parcel_id')) from jsonb_array_elements(v_calc -> 'items') e where e ->> 'parcel_id' is not null) > 1;
  perform set_config('logistics.finance_op', 'on', true);
  insert into logistics.invoice (id, organization_id, number, customer_id, currency, status, status_authority, total, service_fee, subtotal, discount_total, surcharge_total, tax_total, is_grouped, note, source, quote_id)
  values (v_id, v_q.organization_id, 'DRAFT-' || substr(replace(v_id::text, '-', ''), 1, 12), v_q.customer_id, v_q.currency, 'DRAFT', 'core', v_q.total, v_q.service_fee, v_q.subtotal,
          (v_calc ->> 'discount_total')::numeric, (v_calc ->> 'surcharge_total')::numeric, v_q.tax_total, v_grouped, 'Devis ' || v_q.number, 'native', v_q.id);
  for v_it in select e from jsonb_array_elements(v_calc -> 'lines') e loop
    v_n := v_n + 1;
    insert into logistics.invoice_item (invoice_id, parcel_id, kind, code, description, quantity, weight_lb, unit_price, amount, position)
    values (v_id, nullif(v_it ->> 'parcel_id', '')::uuid, v_it ->> 'kind', v_it ->> 'code', coalesce(v_it ->> 'description', ''), coalesce((v_it ->> 'quantity')::numeric, 1),
            case when v_it ->> 'kind' = 'FREIGHT' then (v_it ->> 'quantity')::numeric end, nullif(v_it ->> 'unit_price', '')::numeric, (v_it ->> 'amount')::numeric, v_n);
  end loop;
  perform set_config('logistics.finance_op', 'off', true);
  update logistics.quote set status = 'INVOICED', updated_at = now() where id = p_quote;
  perform logistics.fin_audit(p_actor, 'invoice.create', 'invoice', v_id::text, null, jsonb_build_object('quote', v_q.number, 'total', v_q.total, 'currency', v_q.currency, 'lines', v_n), v_corr);
  perform logistics.emit('InvoiceCreated', 'invoice', v_id::text, v_corr, p_actor, jsonb_build_object('invoice_id', v_id, 'quote_id', p_quote, 'customer_id', v_q.customer_id, 'total', v_q.total, 'currency', v_q.currency));
  v_res := jsonb_build_object('invoice_id', v_id, 'status', 'DRAFT', 'total', v_q.total, 'currency', v_q.currency, 'grouped', v_grouped, 'lines', v_n, 'correlation_id', v_corr);
  if p_issue then v_res := v_res || logistics.issue_invoice(p_actor, v_id, p_due_days, v_corr); end if;
  return v_res;
end;
$$;

create or replace function logistics.issue_invoice(p_actor uuid, p_invoice uuid, p_due_days int default 30, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_i logistics.invoice; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_sum numeric; v_num text; r record; v_taxes numeric;
begin
  perform logistics.require_right(p_actor, 'factures.creer');
  select * into v_i from logistics.invoice where id = p_invoice for update;
  if not found then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  if v_i.status_authority <> 'core' then raise exception 'Facture héritée : elle reste gérée par l''ancien schéma.' using errcode = 'LG004'; end if;
  if v_i.status <> 'DRAFT' then raise exception 'Seul un brouillon s''émet (la facture est %).', v_i.status using errcode = 'LG004'; end if;
  if p_due_days is null or p_due_days < 0 or p_due_days > 365 then raise exception 'Échéance invalide (0 à 365 jours).' using errcode = 'LG005'; end if;
  select coalesce(sum(amount), 0) into v_sum from logistics.invoice_item where invoice_id = p_invoice;
  if v_sum <> v_i.total or v_i.subtotal + v_i.service_fee + v_i.tax_total <> v_i.total then raise exception 'Les lignes ne totalisent pas la facture : émission refusée.' using errcode = 'LG005'; end if;
  perform set_config('logistics.finance_op', 'on', true);
  v_num := logistics.next_number('invoice', 'INV');
  update logistics.invoice set number = v_num, issued_at = now(), due_date = current_date + p_due_days where id = p_invoice;
  perform logistics.move_invoice(p_invoice, 'ISSUED', p_actor, v_corr);
  -- Le revenu est reconnu ICI, hors taxe, en devise de la facture et en dollars (taux du jour).
  for r in select case when kind in ('FREIGHT', 'DISCOUNT') then 'FREIGHT' else kind end as cat, sum(amount) as net
             from logistics.invoice_item where invoice_id = p_invoice and kind <> 'TAX' group by 1 order by 1 loop
    insert into logistics.revenue_entry (invoice_id, category, net_amount, currency, net_base_usd, ref_id, correlation_id)
    values (p_invoice, r.cat, r.net, v_i.currency, logistics.base_amount(r.net, v_i.currency, current_date), v_num, v_corr);
  end loop;
  select coalesce(sum(amount), 0) into v_taxes from logistics.invoice_item where invoice_id = p_invoice and kind = 'TAX';
  if v_taxes <> 0 then
    insert into logistics.revenue_entry (invoice_id, category, tax_amount, currency, tax_base_usd, ref_id, correlation_id)
    values (p_invoice, 'TAX', v_taxes, v_i.currency, logistics.base_amount(v_taxes, v_i.currency, current_date), v_num, v_corr);
  end if;
  perform set_config('logistics.finance_op', 'off', true);
  return jsonb_build_object('invoice_id', p_invoice, 'number', v_num, 'status', 'ISSUED', 'due_date', current_date + p_due_days, 'total', v_i.total, 'currency', v_i.currency, 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.cancel_invoice(p_actor uuid, p_invoice uuid, p_reason text, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_i logistics.invoice; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid());
begin
  perform logistics.require_right(p_actor, 'factures.creer');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif d''annulation est obligatoire.' using errcode = 'LG005'; end if;
  select * into v_i from logistics.invoice where id = p_invoice for update;
  if not found then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  if v_i.status_authority <> 'core' then raise exception 'Facture héritée : elle reste gérée par l''ancien schéma.' using errcode = 'LG004'; end if;
  if v_i.status in ('ISSUED', 'OVERDUE') then
    perform logistics.require_right(p_actor, 'direction');
    if v_i.paid_amount > 0 or v_i.credited_amount > 0 then raise exception 'La facture a reçu un paiement ou un avoir : émettez un avoir pour le solde, puis remboursez.' using errcode = 'LG004'; end if;
    perform set_config('logistics.finance_op', 'on', true);
    insert into logistics.revenue_entry (invoice_id, category, net_amount, tax_amount, currency, net_base_usd, tax_base_usd, ref_id, correlation_id)
    select p_invoice, 'CANCELLATION', -(v_i.subtotal + v_i.service_fee), -v_i.tax_total, v_i.currency,
           -sum(net_base_usd), -sum(tax_base_usd), v_i.number, v_corr from logistics.revenue_entry where invoice_id = p_invoice;
    perform set_config('logistics.finance_op', 'off', true);
  elsif v_i.status <> 'DRAFT' then
    raise exception 'Une facture % ne s''annule pas : émettez un avoir.', v_i.status using errcode = 'LG004';
  end if;
  perform logistics.move_invoice(p_invoice, 'CANCELLED', p_actor, v_corr, p_reason);
  return jsonb_build_object('invoice_id', p_invoice, 'status', 'CANCELLED', 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.mark_overdue(p_actor uuid, p_date date default current_date)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare r record; v_i logistics.invoice; v_corr uuid := gen_random_uuid(); v_ids jsonb := '[]'::jsonb;
begin
  perform logistics.require_right(p_actor, 'factures.modifier');
  for r in select id from logistics.invoice where status_authority = 'core' and status in ('ISSUED', 'PARTIALLY_PAID') and due_date < p_date order by id loop
    select * into v_i from logistics.invoice where id = r.id;
    if logistics.derive_invoice_status(v_i, p_date) = 'OVERDUE' then
      perform logistics.move_invoice(r.id, 'OVERDUE', p_actor, v_corr, 'échéance dépassée');
      v_ids := v_ids || to_jsonb(r.id);
    end if;
  end loop;
  return jsonb_build_object('marked', jsonb_array_length(v_ids), 'invoices', v_ids);
end;
$$;


-- 12. Argent : paiement, avoir, remboursement ------------------------------------------------------------------------------------
create or replace function logistics.record_payment(p_actor uuid, p_invoice uuid, p_amount numeric, p_method text, p_reference text default '', p_currency text default null,
                                                     p_idempotency_key text default null, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_i logistics.invoice; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_prior jsonb; v_hash text; v_tender text; v_amt numeric; v_bal numeric; v_id uuid := gen_random_uuid();
  v_num text; v_status text; v_res jsonb;
begin
  perform logistics.require_right(p_actor, 'factures.modifier');
  v_hash := md5(concat_ws('|', p_invoice, p_amount, p_method, p_reference, coalesce(p_currency, '')));
  v_prior := logistics.idem_begin(p_idempotency_key, 'record_payment', v_hash, p_invoice::text);
  if v_prior is not null then return v_prior; end if;
  if p_amount is null or p_amount <= 0 then raise exception 'Le montant encaissé doit être supérieur à zéro.' using errcode = 'LG005'; end if;
  if p_method is null or p_method not in ('CASH', 'CARD', 'TRANSFER', 'MOBILE_MONEY', 'CHECK', 'OTHER') then raise exception 'Mode de paiement inconnu.' using errcode = 'LG005'; end if;
  select * into v_i from logistics.invoice where id = p_invoice for update;
  if not found then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  if v_i.status_authority <> 'core' then raise exception 'Facture héritée : elle reste gérée par l''ancien schéma.' using errcode = 'LG004'; end if;
  if v_i.status not in ('ISSUED', 'PARTIALLY_PAID', 'OVERDUE') then raise exception 'On n''encaisse que sur une facture émise et non soldée (elle est %).', v_i.status using errcode = 'LG004'; end if;
  v_tender := coalesce(p_currency, v_i.currency);
  if v_tender not in ('USD', 'DOP', 'HTG') then raise exception 'Devise inconnue : %.', v_tender using errcode = 'LG005'; end if;
  v_amt := logistics.convert_amount(p_amount, v_tender, v_i.currency, current_date);
  if v_amt <= 0 then raise exception 'Montant trop faible une fois converti.' using errcode = 'LG005'; end if;
  v_bal := logistics.invoice_balance(v_i);
  if v_amt > v_bal then raise exception 'Le paiement (% %) dépasse le solde dû (% %).', v_amt, v_i.currency, v_bal, v_i.currency using errcode = 'LG005'; end if;
  v_num := logistics.next_number('payment', 'PAY');
  insert into logistics.payment (id, number, invoice_id, customer_id, amount, currency, base_amount_usd, tendered_amount, tendered_currency, rate_used, method, reference, received_by, correlation_id)
  values (v_id, v_num, p_invoice, v_i.customer_id, v_amt, v_i.currency, logistics.base_amount(v_amt, v_i.currency, current_date), round(p_amount, 2), v_tender,
          logistics.effective_rate(v_tender, v_i.currency, current_date), p_method, coalesce(p_reference, ''), p_actor, v_corr);
  perform set_config('logistics.finance_op', 'on', true);
  update logistics.invoice set paid_amount = paid_amount + v_amt where id = p_invoice;
  v_status := logistics.apply_invoice_status(p_invoice, p_actor, v_corr);
  perform set_config('logistics.finance_op', 'off', true);
  perform logistics.fin_audit(p_actor, 'payment.record', 'payment', v_id::text, jsonb_build_object('paid_amount', v_i.paid_amount), jsonb_build_object('paid_amount', v_i.paid_amount + v_amt),
                              v_corr, jsonb_build_object('invoice', v_i.number, 'method', p_method));
  perform logistics.emit('PaymentReceived', 'payment', v_id::text, v_corr, p_actor, jsonb_build_object('payment_id', v_id, 'number', v_num, 'invoice_id', p_invoice, 'amount', v_amt, 'currency', v_i.currency));
  v_res := jsonb_build_object('payment_id', v_id, 'number', v_num, 'amount', v_amt, 'currency', v_i.currency, 'invoice_status', v_status,
                              'balance', (select logistics.invoice_balance(i) from logistics.invoice i where i.id = p_invoice), 'correlation_id', v_corr);
  return logistics.idem_end(p_idempotency_key, v_res);
end;
$$;

create or replace function logistics.issue_credit_note(p_actor uuid, p_invoice uuid, p_amount numeric, p_reason text, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_i logistics.invoice; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_id uuid := gen_random_uuid(); v_num text; v_prev_tax numeric; v_tax numeric; v_net numeric; v_status text;
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour émettre un avoir.' using errcode = 'LG005'; end if;
  if p_amount is null or p_amount <= 0 then raise exception 'Le montant de l''avoir doit être supérieur à zéro.' using errcode = 'LG005'; end if;
  select * into v_i from logistics.invoice where id = p_invoice for update;
  if not found then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  if v_i.status_authority <> 'core' then raise exception 'Facture héritée : elle reste gérée par l''ancien schéma.' using errcode = 'LG004'; end if;
  if v_i.status not in ('ISSUED', 'PARTIALLY_PAID', 'OVERDUE', 'PAID') then raise exception 'On n''émet pas d''avoir sur une facture % .', v_i.status using errcode = 'LG004'; end if;
  if p_amount > v_i.total - v_i.credited_amount then raise exception 'L''avoir (%) dépasse ce qui reste à créditer (%).', p_amount, v_i.total - v_i.credited_amount using errcode = 'LG005'; end if;
  select coalesce(sum(tax_amount), 0) into v_prev_tax from logistics.credit where invoice_id = p_invoice;
  -- Le dernier avoir reprend EXACTEMENT la taxe restante : un renversement total ne laisse pas de centime.
  v_tax := case when v_i.credited_amount + p_amount = v_i.total then v_i.tax_total - v_prev_tax else round(p_amount * v_i.tax_total / v_i.total, 2) end;
  v_tax := greatest(0, least(p_amount, v_tax)); v_net := p_amount - v_tax;
  v_num := logistics.next_number('credit', 'CRN');
  insert into logistics.credit (id, number, invoice_id, customer_id, amount, net_amount, tax_amount, currency, reason, issued_by, correlation_id)
  values (v_id, v_num, p_invoice, v_i.customer_id, p_amount, v_net, v_tax, v_i.currency, p_reason, p_actor, v_corr);
  perform set_config('logistics.finance_op', 'on', true);
  update logistics.invoice set credited_amount = credited_amount + p_amount where id = p_invoice;
  insert into logistics.revenue_entry (invoice_id, category, net_amount, tax_amount, currency, net_base_usd, tax_base_usd, ref_id, correlation_id)
  values (p_invoice, 'CREDIT_NOTE', -v_net, -v_tax, v_i.currency, -logistics.base_amount(v_net, v_i.currency, current_date), -logistics.base_amount(v_tax, v_i.currency, current_date), v_num, v_corr);
  v_status := logistics.apply_invoice_status(p_invoice, p_actor, v_corr);
  perform set_config('logistics.finance_op', 'off', true);
  perform logistics.fin_audit(p_actor, 'invoice.credit', 'invoice', p_invoice::text, jsonb_build_object('credited_amount', v_i.credited_amount), jsonb_build_object('credited_amount', v_i.credited_amount + p_amount),
                              v_corr, jsonb_build_object('credit', v_num, 'reason', p_reason));
  perform logistics.emit('CreditIssued', 'invoice', p_invoice::text, v_corr, p_actor, jsonb_build_object('credit_id', v_id, 'number', v_num, 'invoice_id', p_invoice, 'amount', p_amount, 'reason', p_reason));
  return jsonb_build_object('credit_id', v_id, 'number', v_num, 'amount', p_amount, 'net_amount', v_net, 'tax_amount', v_tax, 'invoice_status', v_status,
                            'balance', (select logistics.invoice_balance(i) from logistics.invoice i where i.id = p_invoice), 'correlation_id', v_corr);
end;
$$;

create or replace function logistics.refund_payment(p_actor uuid, p_payment uuid, p_amount numeric, p_reason text, p_method text, p_correlation_id uuid default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare
  v_p logistics.payment; v_i logistics.invoice; v_corr uuid := coalesce(p_correlation_id, gen_random_uuid()); v_id uuid := gen_random_uuid(); v_num text; v_done numeric; v_excess numeric; v_status text;
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour rembourser.' using errcode = 'LG005'; end if;
  if p_amount is null or p_amount <= 0 then raise exception 'Le montant remboursé doit être supérieur à zéro.' using errcode = 'LG005'; end if;
  if p_method is null or p_method not in ('CASH', 'CARD', 'TRANSFER', 'MOBILE_MONEY', 'CHECK', 'OTHER') then raise exception 'Mode de remboursement inconnu.' using errcode = 'LG005'; end if;
  select * into v_p from logistics.payment where id = p_payment;
  if not found then raise exception 'Paiement introuvable.' using errcode = 'LG002'; end if;
  select * into v_i from logistics.invoice where id = v_p.invoice_id for update;
  select coalesce(sum(amount), 0) into v_done from logistics.refund where payment_id = p_payment;
  if p_amount > v_p.amount - v_done then raise exception 'Le remboursement (%) dépasse ce qui reste remboursable sur ce paiement (%).', p_amount, v_p.amount - v_done using errcode = 'LG005'; end if;
  v_excess := (v_i.paid_amount - v_i.refunded_amount) - (v_i.total - v_i.credited_amount);
  if p_amount > v_excess then raise exception 'Le remboursement (%) dépasse l''excédent payé (%) : émettez d''abord un avoir.', p_amount, greatest(v_excess, 0) using errcode = 'LG005'; end if;
  v_num := logistics.next_number('refund', 'REF');
  insert into logistics.refund (id, number, payment_id, invoice_id, customer_id, amount, currency, base_amount_usd, method, reason, refunded_by, correlation_id)
  values (v_id, v_num, p_payment, v_i.id, v_i.customer_id, p_amount, v_i.currency, logistics.base_amount(p_amount, v_i.currency, current_date), p_method, p_reason, p_actor, v_corr);
  perform set_config('logistics.finance_op', 'on', true);
  update logistics.invoice set refunded_amount = refunded_amount + p_amount where id = v_i.id;
  v_status := logistics.apply_invoice_status(v_i.id, p_actor, v_corr);
  perform set_config('logistics.finance_op', 'off', true);
  perform logistics.fin_audit(p_actor, 'payment.refund', 'payment', p_payment::text, jsonb_build_object('refunded_amount', v_i.refunded_amount), jsonb_build_object('refunded_amount', v_i.refunded_amount + p_amount),
                              v_corr, jsonb_build_object('refund', v_num, 'reason', p_reason));
  perform logistics.emit('RefundIssued', 'payment', p_payment::text, v_corr, p_actor, jsonb_build_object('refund_id', v_id, 'number', v_num, 'payment_id', p_payment, 'invoice_id', v_i.id, 'amount', p_amount, 'reason', p_reason));
  return jsonb_build_object('refund_id', v_id, 'number', v_num, 'amount', p_amount, 'invoice_status', v_status, 'correlation_id', v_corr);
end;
$$;


-- 13. Dépenses -------------------------------------------------------------------------------------------------------------------------
create or replace function logistics.record_expense(p_actor uuid, p_category text, p_description text, p_amount numeric, p_currency text, p_incurred_on date, p_shipment uuid default null, p_supplier text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid := gen_random_uuid(); v_corr uuid := gen_random_uuid(); v_num text; v_on date := coalesce(p_incurred_on, current_date);
begin
  perform logistics.require_right(p_actor, 'factures.creer');
  if p_amount is null or p_amount <= 0 then raise exception 'Le montant d''une dépense doit être supérieur à zéro.' using errcode = 'LG005'; end if;
  if p_category is null or p_category not in ('TRANSPORT', 'CUSTOMS', 'FUEL', 'SALARY', 'RENT', 'UTILITIES', 'MAINTENANCE', 'PACKAGING', 'OTHER') then raise exception 'Catégorie de dépense inconnue.' using errcode = 'LG005'; end if;
  if p_currency is null or p_currency not in ('USD', 'DOP', 'HTG') then raise exception 'Devise inconnue.' using errcode = 'LG005'; end if;
  if v_on > current_date then raise exception 'Une dépense ne peut pas être datée dans le futur.' using errcode = 'LG005'; end if;
  if p_shipment is not null and not exists (select 1 from logistics.shipment where id = p_shipment) then raise exception 'Expédition introuvable.' using errcode = 'LG002'; end if;
  v_num := logistics.next_number('expense', 'EXP');
  insert into logistics.expense (id, number, category, description, amount, currency, base_amount_usd, incurred_on, shipment_id, supplier, recorded_by, correlation_id)
  values (v_id, v_num, p_category, coalesce(p_description, ''), round(p_amount, 2), p_currency, logistics.base_amount(round(p_amount, 2), p_currency, v_on), v_on, p_shipment, coalesce(p_supplier, ''), p_actor, v_corr);
  perform logistics.fin_audit(p_actor, 'expense.record', 'expense', v_id::text, null, jsonb_build_object('number', v_num, 'amount', p_amount, 'currency', p_currency, 'category', p_category), v_corr);
  perform logistics.emit('ExpenseRecorded', 'expense', v_id::text, v_corr, p_actor, jsonb_build_object('expense_id', v_id, 'number', v_num, 'amount', p_amount, 'currency', p_currency, 'category', p_category));
  return jsonb_build_object('expense_id', v_id, 'number', v_num, 'status', 'RECORDED');
end;
$$;

create or replace function logistics.void_expense(p_actor uuid, p_expense uuid, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := gen_random_uuid(); v_e logistics.expense;
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif d''annulation est obligatoire.' using errcode = 'LG005'; end if;
  select * into v_e from logistics.expense where id = p_expense for update;
  if not found then raise exception 'Dépense introuvable.' using errcode = 'LG002'; end if;
  if v_e.status <> 'RECORDED' then raise exception 'Dépense déjà %.', v_e.status using errcode = 'LG004'; end if;
  update logistics.expense set status = 'VOIDED', void_reason = p_reason, voided_by = p_actor, voided_at = now() where id = p_expense;
  perform logistics.fin_audit(p_actor, 'expense.void', 'expense', p_expense::text, jsonb_build_object('status', 'RECORDED'), jsonb_build_object('status', 'VOIDED'), v_corr, jsonb_build_object('reason', p_reason));
  perform logistics.emit('ExpenseVoided', 'expense', p_expense::text, v_corr, p_actor, jsonb_build_object('expense_id', p_expense, 'reason', p_reason));
  return jsonb_build_object('expense_id', p_expense, 'status', 'VOIDED');
end;
$$;


-- 14. Lecture : soldes, détail, synthèse, contrôle --------------------------------------------------------------------------------------
create or replace view logistics.customer_balance with (security_invoker = true) as
  select i.customer_id, i.currency, count(*)::int as invoices, sum(i.total) as invoiced, sum(i.credited_amount) as credited, sum(i.paid_amount) as paid, sum(i.refunded_amount) as refunded,
         sum((i.total - i.credited_amount) - (i.paid_amount - i.refunded_amount)) as balance
    from logistics.invoice i where i.status not in ('DRAFT', 'CANCELLED') group by i.customer_id, i.currency;
comment on view logistics.customer_balance is 'Solde par client et par devise : positif = le client doit, négatif = nous devons (excédent à rembourser). Inclut les factures héritées.';

create or replace function logistics.customer_balance_of(p_actor uuid, p_customer uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'factures.lire');
  return coalesce((select jsonb_agg(jsonb_build_object('currency', b.currency, 'invoices', b.invoices, 'invoiced', b.invoiced, 'credited', b.credited, 'paid', b.paid, 'refunded', b.refunded, 'balance', b.balance) order by b.currency)
                     from logistics.customer_balance b where b.customer_id = p_customer), '[]'::jsonb);
end;
$$;

create or replace function logistics.invoice_detail(p_actor uuid, p_invoice uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_i logistics.invoice;
begin
  perform logistics.require_right(p_actor, 'factures.lire');
  select * into v_i from logistics.invoice where id = p_invoice;
  if not found then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  return jsonb_build_object('invoice', to_jsonb(v_i) - 'legacy_invoice_id', 'balance', logistics.invoice_balance(v_i),
    'items', coalesce((select jsonb_agg(to_jsonb(t) order by t.position) from logistics.invoice_item t where t.invoice_id = p_invoice), '[]'::jsonb),
    'payments', coalesce((select jsonb_agg(to_jsonb(p) order by p.created_at, p.number) from logistics.payment p where p.invoice_id = p_invoice), '[]'::jsonb),
    'credits', coalesce((select jsonb_agg(to_jsonb(c) order by c.created_at, c.number) from logistics.credit c where c.invoice_id = p_invoice), '[]'::jsonb),
    'refunds', coalesce((select jsonb_agg(to_jsonb(r) order by r.created_at, r.number) from logistics.refund r where r.invoice_id = p_invoice), '[]'::jsonb),
    'history', coalesce((select jsonb_agg(jsonb_build_object('from', h.from_status, 'to', h.to_status, 'at', h.occurred_at, 'by', h.actor_label, 'reason', h.reason) order by h.id) from logistics.invoice_status_history h where h.invoice_id = p_invoice), '[]'::jsonb));
end;
$$;

-- Le client ne voit QUE ses factures émises : jamais un brouillon, jamais celles d'un autre.
create or replace function logistics.my_invoices(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('number', i.number, 'status', i.status, 'currency', i.currency, 'total', i.total, 'paid', i.paid_amount, 'credited', i.credited_amount,
                      'refunded', i.refunded_amount, 'balance', logistics.invoice_balance(i), 'issued_at', i.issued_at, 'due_date', i.due_date,
                      'items', coalesce((select jsonb_agg(jsonb_build_object('kind', t.kind, 'description', t.description, 'quantity', t.quantity, 'unit_price', t.unit_price, 'amount', t.amount) order by t.position)
                                          from logistics.invoice_item t where t.invoice_id = i.id), '[]'::jsonb)) order by i.created_at, i.number)
                     from logistics.invoice i join logistics.customer c on c.id = i.customer_id
                    where c.auth_user_id = p_user and i.status <> 'DRAFT'), '[]'::jsonb);
end;
$$;
create or replace function logistics.my_balance(p_user uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  return coalesce((select jsonb_agg(jsonb_build_object('currency', b.currency, 'invoiced', b.invoiced, 'paid', b.paid, 'balance', b.balance) order by b.currency)
                     from logistics.customer_balance b join logistics.customer c on c.id = b.customer_id where c.auth_user_id = p_user), '[]'::jsonb);
end;
$$;

-- La synthèse, en dollars (devise de référence), à partir des écritures datées : un taux changé plus tard ne la retouche pas.
create or replace function logistics.finance_summary(p_actor uuid, p_from date, p_to date)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_rev numeric; v_tax numeric; v_exp numeric; v_col numeric; v_ref numeric; v_cat jsonb; v_ecat jsonb; v_recv jsonb; v_rc jsonb; v_ec jsonb;
begin
  perform logistics.require_right(p_actor, 'direction');
  if p_from is null or p_to is null or p_to < p_from then raise exception 'Période invalide.' using errcode = 'LG005'; end if;
  select coalesce(sum(net_base_usd), 0), coalesce(sum(tax_base_usd), 0) into v_rev, v_tax from logistics.revenue_entry where entry_date between p_from and p_to;
  v_cat := coalesce((select jsonb_object_agg(category, s) from (select category, sum(net_base_usd) s from logistics.revenue_entry where entry_date between p_from and p_to and category <> 'TAX' group by category) x), '{}'::jsonb);
  v_rc := coalesce((select jsonb_object_agg(currency, s) from (select currency, sum(net_amount) s from logistics.revenue_entry where entry_date between p_from and p_to group by currency) x), '{}'::jsonb);
  select coalesce(sum(base_amount_usd), 0) into v_exp from logistics.expense where status = 'RECORDED' and incurred_on between p_from and p_to;
  v_ecat := coalesce((select jsonb_object_agg(category, s) from (select category, sum(base_amount_usd) s from logistics.expense where status = 'RECORDED' and incurred_on between p_from and p_to group by category) x), '{}'::jsonb);
  v_ec := coalesce((select jsonb_object_agg(currency, s) from (select currency, sum(amount) s from logistics.expense where status = 'RECORDED' and incurred_on between p_from and p_to group by currency) x), '{}'::jsonb);
  select coalesce(sum(base_amount_usd), 0) into v_col from logistics.payment where paid_at::date between p_from and p_to;
  select coalesce(sum(base_amount_usd), 0) into v_ref from logistics.refund where created_at::date between p_from and p_to;
  v_recv := coalesce((select jsonb_object_agg(currency, s) from (select currency, sum(greatest(balance, 0)) s from logistics.customer_balance group by currency) x), '{}'::jsonb);
  return jsonb_build_object('from', p_from, 'to', p_to, 'base_currency', 'USD',
    'revenue_base', v_rev, 'revenue_by_category_base', v_cat, 'revenue_by_currency', v_rc, 'tax_collected_base', v_tax,
    'expenses_base', v_exp, 'expenses_by_category_base', v_ecat, 'expenses_by_currency', v_ec,
    'margin_base', v_rev - v_exp, 'collected_base', v_col, 'refunded_base', v_ref, 'net_collected_base', v_col - v_ref,
    'receivable_now_by_currency', v_recv);
end;
$$;

-- Le contrôle d'intégrité : rend UNE ligne par anomalie ; rien en base saine.
create or replace function logistics.reconcile_finance()
returns table (problem text, entity text, id text, detail text)
language plpgsql stable set search_path = '' as $$
begin
  return query select 'paid_mismatch', 'invoice', i.id::text, 'payé ' || i.paid_amount || ' ≠ paiements ' || coalesce(s.t, 0)
    from logistics.invoice i left join (select invoice_id, sum(amount) t from logistics.payment group by invoice_id) s on s.invoice_id = i.id
   where i.status_authority = 'core' and i.paid_amount <> coalesce(s.t, 0);
  return query select 'refunded_mismatch', 'invoice', i.id::text, 'remboursé ' || i.refunded_amount || ' ≠ remboursements ' || coalesce(s.t, 0)
    from logistics.invoice i left join (select invoice_id, sum(amount) t from logistics.refund group by invoice_id) s on s.invoice_id = i.id
   where i.status_authority = 'core' and i.refunded_amount <> coalesce(s.t, 0);
  return query select 'credited_mismatch', 'invoice', i.id::text, 'crédité ' || i.credited_amount || ' ≠ avoirs ' || coalesce(s.t, 0)
    from logistics.invoice i left join (select invoice_id, sum(amount) t from logistics.credit group by invoice_id) s on s.invoice_id = i.id
   where i.status_authority = 'core' and i.credited_amount <> coalesce(s.t, 0);
  return query select 'items_mismatch', 'invoice', i.id::text, 'total ' || i.total || ' ≠ lignes ' || coalesce(s.t, 0)
    from logistics.invoice i left join (select invoice_id, sum(amount) t from logistics.invoice_item group by invoice_id) s on s.invoice_id = i.id
   where i.status_authority = 'core' and i.status <> 'DRAFT' and i.total <> coalesce(s.t, 0);
  return query select 'total_mismatch', 'invoice', i.id::text, 'total ' || i.total || ' ≠ sous-total + frais + taxes'
    from logistics.invoice i where i.status_authority = 'core' and i.total <> i.subtotal + i.service_fee + i.tax_total;
  return query select 'status_mismatch', 'invoice', i.id::text, 'statut ' || i.status || ' ≠ ' || logistics.derive_invoice_status(i, current_date)
    from logistics.invoice i where i.status_authority = 'core' and i.status <> 'DRAFT'
     and logistics.derive_invoice_status(i, current_date) <> i.status and not (logistics.derive_invoice_status(i, current_date) = 'OVERDUE' and i.status in ('ISSUED', 'PARTIALLY_PAID'));
  return query select 'overdue_not_marked', 'invoice', i.id::text, 'échéance ' || i.due_date || ' dépassée, statut ' || i.status
    from logistics.invoice i where i.status_authority = 'core' and i.status in ('ISSUED', 'PARTIALLY_PAID') and logistics.derive_invoice_status(i, current_date) = 'OVERDUE';
  return query select 'revenue_mismatch', 'invoice', i.id::text,
      'revenu ' || coalesce(e.net, 0) || '/' || coalesce(e.tax, 0) || ' attendu ' ||
      (case when i.status in ('DRAFT', 'CANCELLED') then 0 else i.subtotal + i.service_fee - coalesce(c.net, 0) end) || '/' ||
      (case when i.status in ('DRAFT', 'CANCELLED') then 0 else i.tax_total - coalesce(c.tax, 0) end)
    from logistics.invoice i
    left join (select invoice_id, sum(net_amount) net, sum(tax_amount) tax from logistics.revenue_entry group by invoice_id) e on e.invoice_id = i.id
    left join (select invoice_id, sum(net_amount) net, sum(tax_amount) tax from logistics.credit group by invoice_id) c on c.invoice_id = i.id
   where i.status_authority = 'core'
     and (coalesce(e.net, 0), coalesce(e.tax, 0)) is distinct from
         (case when i.status in ('DRAFT', 'CANCELLED') then 0 else i.subtotal + i.service_fee - coalesce(c.net, 0) end,
          case when i.status in ('DRAFT', 'CANCELLED') then 0 else i.tax_total - coalesce(c.tax, 0) end);
  return query select 'refund_exceeds_payment', 'payment', p.id::text, 'remboursé ' || s.t || ' > payé ' || p.amount
    from logistics.payment p join (select payment_id, sum(amount) t from logistics.refund group by payment_id) s on s.payment_id = p.id where s.t > p.amount;
  return query select 'customer_mismatch', 'payment', p.id::text, 'le client du paiement n''est pas celui de la facture'
    from logistics.payment p join logistics.invoice i on i.id = p.invoice_id where p.customer_id <> i.customer_id;
end;
$$;


-- 15. Façade (acteur = auth.uid(), jamais en paramètre) -----------------------------------------------------------------------------------
create or replace function public.lg_set_exchange_rate(p_from text, p_to text, p_rate numeric, p_valid_from date default null)
returns bigint language sql volatile security definer set search_path = '' as $$ select logistics.set_exchange_rate(auth.uid(), p_from, p_to, p_rate, p_valid_from) $$;
create or replace function public.lg_create_pricing_zone(p_code text, p_name text, p_country text)
returns uuid language sql volatile security definer set search_path = '' as $$ select logistics.create_pricing_zone(auth.uid(), p_code, p_name, p_country) $$;
create or replace function public.lg_create_rate_card(p_code text, p_name text, p_mode text, p_zone uuid, p_currency text, p_brackets jsonb, p_valid_from date default null, p_valid_to date default null, p_lb_per_ft3 numeric default null)
returns uuid language sql volatile security definer set search_path = '' as $$ select logistics.create_rate_card(auth.uid(), p_code, p_name, p_mode, p_zone, p_currency, p_valid_from, p_valid_to, p_lb_per_ft3, p_brackets) $$;
create or replace function public.lg_create_service_fee(p_code text, p_name text, p_amount numeric, p_currency text, p_valid_from date default null)
returns uuid language sql volatile security definer set search_path = '' as $$ select logistics.create_service_fee(auth.uid(), p_code, p_name, p_amount, p_currency, p_valid_from) $$;
create or replace function public.lg_create_surcharge(p_code text, p_name text, p_kind text, p_value numeric, p_currency text default null, p_trigger_flag text default null, p_min_weight_lb numeric default null,
  p_min_volume_ft3 numeric default null, p_service_mode text default null, p_zone uuid default null, p_taxable boolean default true, p_valid_from date default null, p_valid_to date default null)
returns uuid language sql volatile security definer set search_path = '' as $$ select logistics.create_surcharge(auth.uid(), p_code, p_name, p_kind, p_value, p_currency, p_trigger_flag, p_min_weight_lb, p_min_volume_ft3, p_service_mode, p_zone, p_taxable, p_valid_from, p_valid_to) $$;
create or replace function public.lg_create_pricing_rule(p_code text, p_name text, p_kind text, p_value numeric, p_reason text, p_currency text default null, p_customer uuid default null, p_service_mode text default null,
  p_zone uuid default null, p_min_weight_lb numeric default null, p_priority int default 100, p_valid_from date default null, p_valid_to date default null)
returns uuid language sql volatile security definer set search_path = '' as $$ select logistics.create_pricing_rule(auth.uid(), p_code, p_name, p_kind, p_value, p_currency, p_customer, p_service_mode, p_zone, p_min_weight_lb, p_priority, p_reason, p_valid_from, p_valid_to) $$;
create or replace function public.lg_create_tax(p_code text, p_name text, p_rate_percent numeric, p_applies_to text, p_country text default null, p_valid_from date default null, p_valid_to date default null)
returns uuid language sql volatile security definer set search_path = '' as $$ select logistics.create_tax(auth.uid(), p_code, p_name, p_rate_percent, p_applies_to, p_country, p_valid_from, p_valid_to) $$;
create or replace function public.lg_set_pricing_active(p_kind text, p_id uuid, p_active boolean)
returns void language sql volatile security definer set search_path = '' as $$ select logistics.set_pricing_active(auth.uid(), p_kind, p_id, p_active) $$;

create or replace function public.lg_price_preview(p_customer uuid, p_currency text, p_items jsonb, p_on date default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.price_preview(auth.uid(), p_customer, p_currency, p_items, coalesce(p_on, current_date)) $$;
create or replace function public.lg_create_quote(p_customer uuid, p_currency text, p_items jsonb, p_valid_days int default 15, p_on date default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_quote(auth.uid(), p_customer, p_currency, p_items, p_valid_days, coalesce(p_on, current_date), null) $$;
create or replace function public.lg_cancel_quote(p_quote uuid, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cancel_quote(auth.uid(), p_quote, p_reason) $$;
create or replace function public.lg_expire_quotes()
returns int language sql volatile security definer set search_path = '' as $$ select logistics.expire_quotes(auth.uid()) $$;
create or replace function public.lg_invoice_from_quote(p_quote uuid, p_due_days int default 30, p_issue boolean default false)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.invoice_from_quote(auth.uid(), p_quote, p_due_days, p_issue, null) $$;
create or replace function public.lg_issue_invoice(p_invoice uuid, p_due_days int default 30)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.issue_invoice(auth.uid(), p_invoice, p_due_days, null) $$;
create or replace function public.lg_cancel_invoice(p_invoice uuid, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cancel_invoice(auth.uid(), p_invoice, p_reason, null) $$;
create or replace function public.lg_mark_overdue(p_date date default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.mark_overdue(auth.uid(), coalesce(p_date, current_date)) $$;
create or replace function public.lg_record_payment(p_invoice uuid, p_amount numeric, p_method text, p_reference text default '', p_currency text default null, p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.record_payment(auth.uid(), p_invoice, p_amount, p_method, p_reference, p_currency, p_idempotency_key, null) $$;
create or replace function public.lg_issue_credit_note(p_invoice uuid, p_amount numeric, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.issue_credit_note(auth.uid(), p_invoice, p_amount, p_reason, null) $$;
create or replace function public.lg_refund_payment(p_payment uuid, p_amount numeric, p_reason text, p_method text default 'CASH')
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.refund_payment(auth.uid(), p_payment, p_amount, p_reason, p_method, null) $$;
create or replace function public.lg_record_expense(p_category text, p_amount numeric, p_currency text, p_description text default '', p_incurred_on date default null, p_shipment uuid default null, p_supplier text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.record_expense(auth.uid(), p_category, p_description, p_amount, p_currency, p_incurred_on, p_shipment, p_supplier) $$;
create or replace function public.lg_void_expense(p_expense uuid, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.void_expense(auth.uid(), p_expense, p_reason) $$;
create or replace function public.lg_finance_summary(p_from date, p_to date)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.finance_summary(auth.uid(), p_from, p_to) $$;
create or replace function public.lg_customer_balance(p_customer uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.customer_balance_of(auth.uid(), p_customer) $$;
create or replace function public.lg_invoice_detail(p_invoice uuid)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.invoice_detail(auth.uid(), p_invoice) $$;
create or replace function public.lg_my_invoices()
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_invoices(auth.uid()) $$;
create or replace function public.lg_my_balance()
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_balance(auth.uid()) $$;
create or replace function public.lg_reconcile_finance()
returns table (problem text, entity text, id text, detail text) language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(auth.uid(), 'direction');
  return query select * from logistics.reconcile_finance();
end;
$$;


-- 16. Tout fermé, sauf la façade -----------------------------------------------------------------------------------------------------------
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

-- Pour retirer SEULEMENT cette étape : supprimer les fonctions public.lg_* de la section 15, puis
--   drop view if exists logistics.customer_balance;
--   drop table if exists logistics.expense, logistics.revenue_entry, logistics.credit, logistics.refund, logistics.payment, logistics.invoice_status_history, logistics.invoice_transition,
--        logistics.quote, logistics.finance_counter, logistics.tax, logistics.pricing_rule, logistics.surcharge, logistics.service_fee, logistics.weight_bracket, logistics.rate_card,
--        logistics.pricing_zone, logistics.exchange_rate cascade;
--   (après avoir retiré les déclencheurs guard_invoice et guard_invoice_item et les colonnes ajoutées à logistics.invoice et logistics.invoice_item). Aucune donnée de l'ancien schéma n'est en jeu.
