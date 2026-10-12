-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 18 : la finance professionnelle
-- -----------------------------------------------------------------------------
-- Phase 6. À coller dans Supabase > SQL Editor APRÈS 017, d'abord en PRÉPRODUCTION,
-- puis en production après une sauvegarde « avant migration » vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site » (ou la préproduction).
--
-- Le moteur financier de l'étape 7 (devis, grilles, frais, surcharges, remises, taxes, change, factures figées,
-- paiements, avoirs, remboursements, dépenses, revenus) devient la source de vérité de l'argent. Cette étape ajoute :
--   1. les PRESTATAIRES DE PAIEMENT (carte Visa / Mastercard, Azul, MonCash, NatCash, d'autres plus tard) : une table
--      sans aucun secret — la base ne connaît que le NOM de la variable d'environnement du serveur qui le porte ;
--   2. la DEMANDE de paiement en ligne : le client (ou l'équipe) demande à payer une facture ; la base fixe le montant
--      (le solde qu'ELLE calcule), la devise, le prestataire ; le serveur (Edge Function) y rattache la référence du prestataire ;
--   3. le JOURNAL des événements de paiement (payment_event) reçus des prestataires par le serveur : idempotent (un
--      événement rejoué ne paie pas deux fois), vérifié (signature contrôlée par le serveur, qui seul a le secret ; un
--      événement non vérifié est journalisé, jamais appliqué), rattaché à la facture, au client et au prestataire,
--      réconciliable (relevés de règlement du prestataire, écarts classés, examen tracé) ;
--   4. l'AJUSTEMENT : une facture complémentaire liée à la facture corrigée (l'avoir et le remboursement existaient) ;
--   5. la FACTURE GROUPÉE en une seule transaction (devis, facture, émission : tout ou rien) ;
--   6. le PRIX SAISI À LA MAIN (ancien « prix_manuel ») dans le calcul du noyau, pour que les deux moteurs disent le même prix ;
--   7. la PARITÉ avec l'ancien schéma (chaque facture héritée recalculée par le noyau, chaque écart classé) et la BASCULE,
--      refusée tant que la réconciliation financière n'est pas propre.
--
-- Rien n'est calculé par le navigateur : ni total, ni taxe, ni remise, ni solde, ni conversion. Rejouable sans risque ;
-- aucune donnée supprimée. Fonction redéfinie : compute_quote (copie de l'étape 7, une branche de plus).
-- Retour arrière : docs/architecture/FINANCE.md §9.
-- =============================================================================

-- 1. Le vocabulaire ------------------------------------------------------------------------------------------------
do $$
declare v_types text[]; v_def text;
begin
  select pg_get_constraintdef(c.oid) into v_def from pg_constraint c where c.conrelid = 'logistics.event_type'::regclass and c.conname = 'event_type_aggregate_type_check';
  select array_agg(distinct x order by x) into v_types
    from (select m[1] as x from regexp_matches(coalesce(v_def, ''), '''([a-z_]+)''', 'g') m
          union select btrim(y) from unnest(string_to_array(substring(coalesce(v_def, '') from '\{([^}]*)\}'), ',')) y
          union select aggregate_type from logistics.event_type union select 'finance') t;
  alter table logistics.event_type drop constraint if exists event_type_aggregate_type_check;
  execute format('alter table logistics.event_type add constraint event_type_aggregate_type_check check (aggregate_type = any (%L::text[]))', v_types);
end
$$;
insert into logistics.event_type (code, aggregate_type, description) values
  ('PaymentProviderConfigured', 'finance', 'Prestataire de paiement activé, désactivé ou configuré'),
  ('PaymentIntentCreated',      'payment', 'Demande de paiement en ligne créée (montant fixé par la base)'),
  ('PaymentIntentUpdated',      'payment', 'Demande de paiement en ligne : référence du prestataire ou nouvel état'),
  ('PaymentEventApplied',       'payment', 'Événement d''un prestataire appliqué : paiement enregistré'),
  ('PaymentEventRejected',      'payment', 'Événement d''un prestataire non appliqué (non vérifié, montant différent, sans demande…)'),
  ('PaymentEventReviewed',      'payment', 'Écart d''un événement de paiement examiné par la direction'),
  ('SettlementLineImported',    'finance', 'Ligne d''un relevé de règlement du prestataire importée'),
  ('InvoiceAdjusted',           'invoice', 'Ajustement : facture complémentaire liée à une facture émise'),
  ('GroupedInvoiceCreated',     'invoice', 'Facture groupée créée et émise en une seule transaction'),
  ('FinanceModeChanged',        'finance', 'Moteur de facturation de référence changé (ancien schéma ↔ noyau)')
on conflict (code) do nothing;


-- 2. Les prestataires : aucun secret dans la base --------------------------------------------------------------------
-- Vrai si un objet JSON contient, à n'importe quelle profondeur, une clé dont le nom trahit un secret.
create or replace function logistics.json_has_secret_key(p jsonb)
returns boolean language sql immutable set search_path = '' as $$
  select exists (
    with recursive t(v) as (select p union all
      select e.value from t, lateral jsonb_each(case when jsonb_typeof(t.v) = 'object' then t.v else '{}'::jsonb end) e)
    select 1 from t, lateral jsonb_object_keys(case when jsonb_typeof(t.v) = 'object' then t.v else '{}'::jsonb end) k
     where lower(k) ~ '(secret|password|passwd|private|token|api_?key|client_?secret|webhook_?key|signing)')
$$;

create table if not exists logistics.payment_provider (
  code          text primary key check (code ~ '^[A-Z][A-Z0-9_]{1,30}$'),
  name          text not null,
  kind          text not null check (kind in ('CARD', 'MOBILE_MONEY', 'BANK', 'OTHER')),
  method        text not null check (method in ('CARD', 'MOBILE_MONEY', 'TRANSFER', 'OTHER')),
  countries     text[] not null default '{}',
  currencies    text[] not null default '{USD}',
  environment   text not null default 'test' check (environment in ('test', 'live')),
  active        boolean not null default false,
  public_config jsonb not null default '{}'::jsonb check (jsonb_typeof(public_config) = 'object' and not logistics.json_has_secret_key(public_config)),
  credentials_env    text check (credentials_env is null or credentials_env ~ '^[A-Z][A-Z0-9_]{2,60}$'),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
comment on table logistics.payment_provider is 'Prestataires de paiement. Aucun secret : credentials_env est le NOM de la variable d''environnement du serveur (Edge Function) qui porte la clé.';
-- Les prestataires prévus, ÉTEINTS : on les allume un par un, quand le contrat et les clés de test sont là.
insert into logistics.payment_provider (code, name, kind, method, countries, currencies, credentials_env) values
  ('CARD',    'Carte Visa / Mastercard', 'CARD',         'CARD',         '{US,HT,DO}', '{USD}',      'SES_PAY_CARD'),
  ('AZUL',    'Azul',                    'CARD',         'CARD',         '{DO}',       '{DOP,USD}',  'SES_PAY_AZUL'),
  ('MONCASH', 'MonCash',                 'MOBILE_MONEY', 'MOBILE_MONEY', '{HT}',       '{HTG}',      'SES_PAY_MONCASH'),
  ('NATCASH', 'NatCash',                 'MOBILE_MONEY', 'MOBILE_MONEY', '{HT}',       '{HTG}',      'SES_PAY_NATCASH')
on conflict (code) do nothing;

-- Le paiement sait d'où il vient : du guichet (sans prestataire) ou d'un prestataire, avec SA référence (une seule fois).
alter table logistics.payment add column if not exists provider_code text references logistics.payment_provider (code) on delete restrict;
alter table logistics.payment add column if not exists external_id text;
create unique index if not exists payment_provider_external_once on logistics.payment (provider_code, external_id) where provider_code is not null;


-- 3. La demande de paiement en ligne ---------------------------------------------------------------------------------
create table if not exists logistics.payment_intent (
  id             uuid primary key default gen_random_uuid(),
  number         text not null unique,
  invoice_id     uuid not null references logistics.invoice (id) on delete restrict,
  customer_id    uuid not null references logistics.customer (id) on delete restrict,
  provider_code  text not null references logistics.payment_provider (code) on delete restrict,
  amount         numeric(14, 2) not null check (amount > 0),
  currency       text not null check (currency in ('USD', 'DOP', 'HTG')),
  status         text not null default 'CREATED' check (status in ('CREATED', 'PENDING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED')),
  external_id    text,
  requested_by   uuid,
  expires_at     timestamptz not null,
  payment_id     uuid references logistics.payment (id) on delete restrict,
  correlation_id uuid not null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  check ((status = 'SUCCEEDED') = (payment_id is not null))
);
create unique index if not exists payment_intent_external_once on logistics.payment_intent (provider_code, external_id) where external_id is not null;
create unique index if not exists payment_intent_one_live on logistics.payment_intent (invoice_id, provider_code) where status in ('CREATED', 'PENDING');
comment on table logistics.payment_intent is 'Demande de paiement en ligne. Le montant est le solde calculé par la base à la création ; le navigateur ne le fixe jamais.';

-- Le montant, la devise, la facture, le client, le prestataire d'une demande ne changent plus ; l'état ne revient pas en arrière.
create or replace function logistics.guard_payment_intent()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then raise exception 'Une demande de paiement ne se supprime pas.' using errcode = 'LG004'; end if;
  if (new.number, new.invoice_id, new.customer_id, new.provider_code, new.amount, new.currency, new.created_at)
     is distinct from (old.number, old.invoice_id, old.customer_id, old.provider_code, old.amount, old.currency, old.created_at) then
    raise exception 'Une demande de paiement est figée (montant, devise, facture, client, prestataire).' using errcode = 'LG004';
  end if;
  if old.external_id is not null and new.external_id is distinct from old.external_id then raise exception 'La référence du prestataire ne change plus.' using errcode = 'LG004'; end if;
  if old.status in ('SUCCEEDED', 'FAILED', 'CANCELLED', 'EXPIRED') and new.status <> old.status then
    raise exception 'Demande de paiement terminée (%) : elle ne change plus d''état.', old.status using errcode = 'LG004';
  end if;
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists guard_payment_intent on logistics.payment_intent;
create trigger guard_payment_intent before update or delete on logistics.payment_intent for each row execute function logistics.guard_payment_intent();


-- 4. Le journal des événements de paiement ----------------------------------------------------------------------------
-- Une ligne par événement reçu d'un prestataire (event_key : l'identifiant de l'événement chez lui ; à défaut, la référence de
-- la transaction et son état). Ajout seul : seul le RÉSULTAT du traitement se pose, une fois. Le contenu brut n'est pas gardé
-- (données personnelles) : raw_reference est la référence lisible ou l'empreinte de ce que le serveur a reçu.
create table if not exists logistics.payment_event (
  id             bigint generated always as identity primary key,
  provider_code  text not null references logistics.payment_provider (code) on delete restrict,
  event_key      text not null check (length(event_key) between 1 and 200),
  external_id    text not null check (length(external_id) between 1 and 200),
  intent_id      uuid references logistics.payment_intent (id) on delete restrict,
  invoice_id     uuid references logistics.invoice (id) on delete restrict,
  customer_id    uuid references logistics.customer (id) on delete restrict,
  amount         numeric(14, 2) not null check (amount >= 0),
  currency       text not null check (currency in ('USD', 'DOP', 'HTG')),
  status         text not null check (status in ('PENDING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'REFUNDED')),
  verified       boolean not null,
  received_at    timestamptz not null default now(),
  processed_at   timestamptz,
  outcome        text check (outcome in ('APPLIED', 'STATUS_UPDATED', 'REJECTED_UNVERIFIED', 'NO_INTENT', 'MISMATCH', 'ALREADY_PAID', 'UNAPPLIED', 'REFUND_TO_RECONCILE')),
  outcome_detail text,
  payment_id     uuid references logistics.payment (id) on delete restrict,
  raw_reference  text not null default '' check (length(raw_reference) <= 500),
  correlation_id uuid not null,
  unique (provider_code, event_key),
  check ((processed_at is null) = (outcome is null))
);
create index if not exists payment_event_external_idx on logistics.payment_event (provider_code, external_id);
comment on table logistics.payment_event is 'Événements de paiement reçus des prestataires : idempotents (prestataire + clé d''événement), vérifiés par le serveur, journalisés, réconciliables.';

create or replace function logistics.guard_payment_event()
returns trigger language plpgsql set search_path = '' as $$
begin
  if tg_op = 'DELETE' then raise exception 'Le journal des paiements est en ajout seul.' using errcode = 'LG004'; end if;
  if old.processed_at is not null
     or (new.provider_code, new.event_key, new.external_id, new.amount, new.currency, new.status, new.verified, new.received_at, new.raw_reference, new.correlation_id)
        is distinct from (old.provider_code, old.event_key, old.external_id, old.amount, old.currency, old.status, old.verified, old.received_at, old.raw_reference, old.correlation_id) then
    raise exception 'Le journal des paiements est en ajout seul : seul le résultat du traitement se pose, une fois.' using errcode = 'LG004';
  end if;
  return new;
end;
$$;
drop trigger if exists guard_payment_event on logistics.payment_event;
create trigger guard_payment_event before update or delete on logistics.payment_event for each row execute function logistics.guard_payment_event();

-- L'EXAMEN d'un écart par la direction (ajout seul) : il ne change pas l'argent, il dit que l'écart est compris et traité
-- (remboursé, imputé, contesté, facture héritée laissée telle quelle…). Un écart examiné ne bloque plus la bascule ; il reste visible.
create table if not exists logistics.finance_review (
  id             bigint generated always as identity primary key,
  entity         text not null check (entity in ('payment_event', 'legacy_invoice', 'settlement_line')),
  entity_id      text not null,
  verdict        text not null,
  note           text not null check (btrim(note) <> '' and length(note) <= 2000),
  reviewed_by    uuid references logistics.app_user (id) on delete restrict,
  reviewed_at    timestamptz not null default now(),
  correlation_id uuid not null,
  unique (entity, entity_id)
);

-- Les relevés de règlement des prestataires (ce qu'ils ont réellement versé), pour réconcilier argent annoncé et argent reçu.
create table if not exists logistics.provider_settlement_line (
  id             bigint generated always as identity primary key,
  provider_code  text not null references logistics.payment_provider (code) on delete restrict,
  external_id    text not null,
  amount         numeric(14, 2) not null,
  currency       text not null check (currency in ('USD', 'DOP', 'HTG')),
  fee_amount     numeric(14, 2) not null default 0 check (fee_amount >= 0),
  settled_on     date not null,
  batch_ref      text not null default '',
  imported_at    timestamptz not null default now(),
  unique (provider_code, external_id)
);

-- Le moteur de facturation de référence : l'ancien schéma tant que la réconciliation n'est pas propre.
create table if not exists logistics.finance_setting (
  key        text primary key check (key in ('mode')),
  value      text not null,
  reason     text,
  updated_by uuid references logistics.app_user (id) on delete restrict,
  updated_at timestamptz not null default now(),
  check (key <> 'mode' or value in ('legacy', 'core'))
);
insert into logistics.finance_setting (key, value, reason) values ('mode', 'legacy', 'état initial : l''ancien schéma facture') on conflict (key) do nothing;

-- L'ajustement : une facture complémentaire liée à celle qu'elle corrige.
alter table logistics.invoice add column if not exists kind text not null default 'STANDARD';
alter table logistics.invoice drop constraint if exists invoice_kind_check;
alter table logistics.invoice add constraint invoice_kind_check check (kind in ('STANDARD', 'ADJUSTMENT'));
alter table logistics.invoice add column if not exists corrects_invoice_id uuid references logistics.invoice (id) on delete restrict;
alter table logistics.invoice drop constraint if exists invoice_adjustment_link;
alter table logistics.invoice add constraint invoice_adjustment_link check ((kind = 'ADJUSTMENT') = (corrects_invoice_id is not null));
-- Le revenu d'une ligne « autre » (celle d'un ajustement) se reconnaît comme les autres : la catégorie s'ajoute à celles d'avant.
do $$
declare v_cats text[]; v_def text;
begin
  select pg_get_constraintdef(c.oid) into v_def from pg_constraint c where c.conrelid = 'logistics.revenue_entry'::regclass and c.conname = 'revenue_entry_category_check';
  select array_agg(distinct x order by x) into v_cats
    from (select m[1] as x from regexp_matches(coalesce(v_def, ''), '''([A-Z_]+)''', 'g') m
          union select btrim(y) from unnest(string_to_array(substring(coalesce(v_def, '') from '\{([^}]*)\}'), ',')) y
          union select unnest(array['FREIGHT', 'SURCHARGE', 'SERVICE_FEE', 'TAX', 'CREDIT_NOTE', 'CANCELLATION', 'OTHER'])) t;
  alter table logistics.revenue_entry drop constraint if exists revenue_entry_category_check;
  execute format('alter table logistics.revenue_entry add constraint revenue_entry_category_check check (category = any (%L::text[]))', v_cats);
end
$$;

do $$
declare t text;
begin
  foreach t in array array['payment_provider', 'payment_intent', 'payment_event', 'finance_review', 'provider_settlement_line', 'finance_setting'] loop
    execute format('revoke all on logistics.%I from public, anon, authenticated', t);
    execute format('alter table logistics.%I enable row level security', t);
  end loop;
  foreach t in array array['finance_review', 'provider_settlement_line'] loop
    execute format('drop trigger if exists %I on logistics.%I', t || '_append_only', t);
    execute format('create trigger %I before update or delete on logistics.%I for each row execute function logistics.forbid_mutation()', t || '_append_only', t);
  end loop;
end
$$;


-- 5. Le calcul du prix : le prix saisi à la main ---------------------------------------------------------------------
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
    -- b0. prix saisi à la main sur le colis (ancien « prix_manuel », USD — étape 18) : un forfait, il remplace poids × tarif
    elsif v_par.id is not null and v_par.manual_price is not null and p_currency = 'USD' then
      v_src := 'MANUAL'; v_rate := null; v_code := 'MANUAL';
    -- b. tarif enregistré sur le colis (ancien « tarif_lb » : USD)
    elsif v_par.id is not null and coalesce(v_par.rate_per_lb, 0) > 0 and p_currency = 'USD' then
      v_src := 'PARCEL'; v_rate := v_par.rate_per_lb; v_code := 'PARCEL';
    end if;

    select * into v_br from logistics.weight_bracket b where b.rate_card_id = v_card.id and b.min_lb <= v_chg and (b.max_lb is null or v_chg < b.max_lb);
    if v_src is null and not found then raise exception 'Aucune tranche de poids pour % lb dans la grille %.', v_chg, v_card.code using errcode = 'LG005'; end if;

    if v_src = 'MANUAL' then
      v_freight := round(v_par.manual_price, 2); v_chg := v_w;
    elsif v_src in ('OVERRIDE', 'PARCEL') then
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


-- 6. Les prestataires : configuration ---------------------------------------------------------------------------------
create or replace function logistics.configure_payment_provider(p_actor uuid, p_code text, p_active boolean, p_environment text default null, p_public_config jsonb default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_p logistics.payment_provider; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  select * into v_p from logistics.payment_provider where code = upper(btrim(coalesce(p_code, ''))) for update;
  if not found then raise exception 'Prestataire inconnu : %.', p_code using errcode = 'LG002'; end if;
  if p_environment is not null and p_environment not in ('test', 'live') then raise exception 'Environnement inconnu : % (test ou live).', p_environment using errcode = 'LG005'; end if;
  if p_public_config is not null and (jsonb_typeof(p_public_config) <> 'object' or logistics.json_has_secret_key(p_public_config)) then
    raise exception 'La configuration publique ne doit contenir AUCUN secret : la clé reste dans l''environnement du serveur.' using errcode = 'LG005';
  end if;
  update logistics.payment_provider set active = coalesce(p_active, active), environment = coalesce(p_environment, environment),
         public_config = coalesce(p_public_config, public_config), updated_at = now() where code = v_p.code;
  perform logistics.fin_audit(p_actor, 'provider.configure', 'payment_provider', v_p.code,
                              jsonb_build_object('active', v_p.active, 'environment', v_p.environment, 'public_config', v_p.public_config),
                              (select jsonb_build_object('active', x.active, 'environment', x.environment, 'public_config', x.public_config) from logistics.payment_provider x where x.code = v_p.code), v_corr);
  perform logistics.emit('PaymentProviderConfigured', 'finance', v_p.code, v_corr, p_actor, jsonb_build_object('provider', v_p.code, 'active', coalesce(p_active, v_p.active)));
  return (select jsonb_build_object('code', x.code, 'name', x.name, 'active', x.active, 'environment', x.environment, 'public_config', x.public_config) from logistics.payment_provider x where x.code = v_p.code);
end;
$$;

-- Ce que le site peut savoir d'un prestataire : jamais credentials_env, jamais un secret.
create or replace function logistics.payment_providers_for(p_currency text, p_country text)
returns jsonb language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(jsonb_build_object('code', p.code, 'name', p.name, 'kind', p.kind, 'environment', p.environment, 'public_config', p.public_config) order by p.code), '[]'::jsonb)
    from logistics.payment_provider p
   where p.active and (p_currency is null or p_currency = any (p.currencies)) and (p_country is null or cardinality(p.countries) = 0 or p_country = any (p.countries))
$$;


-- 7. La demande de paiement en ligne : par le client, ou par l'équipe ---------------------------------------------------
create or replace function logistics.create_payment_intent(p_actor uuid, p_invoice uuid, p_provider text, p_as_customer boolean, p_idempotency_key text default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_i logistics.invoice; v_p logistics.payment_provider; v_bal numeric; v_id uuid := gen_random_uuid(); v_num text; v_corr uuid := gen_random_uuid(); v_prior jsonb; v_res jsonb; v_pays text;
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  v_prior := logistics.idem_begin(p_idempotency_key, 'create_payment_intent', md5(concat_ws('|', p_invoice, p_provider)), coalesce(p_invoice::text, ''));
  if v_prior is not null then return v_prior; end if;
  select * into v_i from logistics.invoice where id = p_invoice for update;
  if not found then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  if p_as_customer then
    -- Un client ne paie que SES factures ; celle d'un autre répond « introuvable », comme une facture qui n'existe pas.
    if v_i.customer_id is distinct from logistics.my_customer(p_actor) then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  else
    perform logistics.require_right(p_actor, 'factures.modifier');
  end if;
  if v_i.status_authority <> 'core' then raise exception 'Facture de l''ancien schéma : le paiement en ligne n''est ouvert qu''aux factures du moteur financier.' using errcode = 'LG004'; end if;
  if v_i.status not in ('ISSUED', 'PARTIALLY_PAID', 'OVERDUE') then raise exception 'Cette facture n''est pas à payer (elle est %).', v_i.status using errcode = 'LG004'; end if;
  select * into v_p from logistics.payment_provider where code = upper(btrim(coalesce(p_provider, '')));
  if not found or not v_p.active then raise exception 'Moyen de paiement indisponible.' using errcode = 'LG005'; end if;
  if not (v_i.currency = any (v_p.currencies)) then raise exception '% n''accepte pas la devise % de cette facture.', v_p.name, v_i.currency using errcode = 'LG005'; end if;
  v_bal := logistics.invoice_balance(v_i);
  if v_bal <= 0 then raise exception 'Cette facture est déjà soldée.' using errcode = 'LG004'; end if;
  -- Une demande précédente encore ouverte pour ce prestataire se termine : la nouvelle porte le solde d'aujourd'hui.
  update logistics.payment_intent set status = 'CANCELLED' where invoice_id = p_invoice and provider_code = v_p.code and status in ('CREATED', 'PENDING') and external_id is null;
  if exists (select 1 from logistics.payment_intent where invoice_id = p_invoice and provider_code = v_p.code and status = 'PENDING') then
    raise exception 'Un paiement est déjà en cours chez % pour cette facture : attendez sa confirmation.', v_p.name using errcode = 'LG004';
  end if;
  v_num := logistics.next_number('payment_intent', 'PIN');
  insert into logistics.payment_intent (id, number, invoice_id, customer_id, provider_code, amount, currency, requested_by, expires_at, correlation_id)
  values (v_id, v_num, p_invoice, v_i.customer_id, v_p.code, v_bal, v_i.currency, p_actor, now() + interval '2 hours', v_corr);
  -- (un client n'est pas un compte d'équipe : l'audit le nomme dans « requested_by », pas comme acteur)
  perform logistics.fin_audit(case when p_as_customer then null else p_actor end, 'payment_intent.create', 'payment_intent', v_id::text, null,
                              jsonb_build_object('number', v_num, 'invoice', v_i.number, 'provider', v_p.code, 'amount', v_bal, 'currency', v_i.currency, 'requested_by', p_actor), v_corr);
  perform logistics.emit('PaymentIntentCreated', 'payment', v_id::text, v_corr, case when p_as_customer then null else p_actor end,
                         jsonb_build_object('intent_id', v_id, 'number', v_num, 'invoice_id', p_invoice, 'customer_id', v_i.customer_id, 'provider', v_p.code, 'amount', v_bal, 'currency', v_i.currency));
  v_res := jsonb_build_object('intent_id', v_id, 'number', v_num, 'invoice_number', v_i.number, 'amount', v_bal, 'currency', v_i.currency, 'provider', v_p.code,
                              'provider_name', v_p.name, 'environment', v_p.environment, 'public_config', v_p.public_config, 'status', 'CREATED', 'expires_at', now() + interval '2 hours');
  return logistics.idem_end(p_idempotency_key, v_res);
end;
$$;

create or replace function logistics.payment_intent_view(p_intent logistics.payment_intent)
returns jsonb language sql stable security definer set search_path = '' as $$
  select jsonb_build_object('intent_id', p_intent.id, 'number', p_intent.number, 'status', p_intent.status, 'amount', p_intent.amount, 'currency', p_intent.currency,
                            'provider', p_intent.provider_code, 'invoice_number', (select i.number from logistics.invoice i where i.id = p_intent.invoice_id),
                            'invoice_status', (select i.status from logistics.invoice i where i.id = p_intent.invoice_id),
                            'balance', (select logistics.invoice_balance(i) from logistics.invoice i where i.id = p_intent.invoice_id),
                            'payment_number', (select p.number from logistics.payment p where p.id = p_intent.payment_id), 'expires_at', p_intent.expires_at)
$$;

create or replace function logistics.my_payment_intent(p_user uuid, p_number text)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_x logistics.payment_intent;
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  select * into v_x from logistics.payment_intent where number = upper(btrim(coalesce(p_number, ''))) and customer_id = logistics.my_customer(p_user);
  if not found then raise exception 'Demande de paiement introuvable.' using errcode = 'LG002'; end if;
  return logistics.payment_intent_view(v_x);
end;
$$;


-- 8. Le serveur (Edge Function, clé secrète de Supabase) : rattacher, recevoir, relever ---------------------------------
-- Ces fonctions ne sont ouvertes qu'au rôle « service_role » : jamais à un visiteur ni à un compte connecté. Le serveur seul
-- connaît les secrets des prestataires ; il vérifie la signature de chaque webhook AVANT d'appeler la base, et dit ce qu'il a vu.

-- Le serveur a créé l'ordre chez le prestataire : il rattache sa référence à la demande.
create or replace function logistics.attach_payment_intent(p_intent uuid, p_provider text, p_external_id text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_x logistics.payment_intent; v_corr uuid;
begin
  select * into v_x from logistics.payment_intent where id = p_intent for update;
  if not found or v_x.provider_code <> upper(btrim(coalesce(p_provider, ''))) then raise exception 'Demande de paiement introuvable pour ce prestataire.' using errcode = 'LG002'; end if;
  if btrim(coalesce(p_external_id, '')) = '' or length(p_external_id) > 200 then raise exception 'Référence du prestataire invalide.' using errcode = 'LG005'; end if;
  if v_x.external_id = btrim(p_external_id) then return logistics.payment_intent_view(v_x) || jsonb_build_object('replayed', true); end if;
  if v_x.external_id is not null then raise exception 'Cette demande a déjà une référence du prestataire.' using errcode = 'LG004'; end if;
  if v_x.status <> 'CREATED' then raise exception 'Demande % : elle ne se rattache plus.', v_x.status using errcode = 'LG004'; end if;
  if v_x.expires_at < now() then
    update logistics.payment_intent set status = 'EXPIRED' where id = p_intent;
    raise exception 'Demande expirée : le client doit en créer une nouvelle.' using errcode = 'LG004';
  end if;
  update logistics.payment_intent set external_id = btrim(p_external_id), status = 'PENDING' where id = p_intent returning * into v_x;
  v_corr := v_x.correlation_id;
  perform logistics.fin_audit(null, 'payment_intent.attach', 'payment_intent', p_intent::text, jsonb_build_object('status', 'CREATED'),
                              jsonb_build_object('status', 'PENDING', 'external_id', v_x.external_id), v_corr);
  perform logistics.emit('PaymentIntentUpdated', 'payment', p_intent::text, v_corr, null, jsonb_build_object('intent_id', p_intent, 'status', 'PENDING', 'provider', v_x.provider_code));
  return logistics.payment_intent_view(v_x);
end;
$$;

-- Le paiement reçu d'un prestataire, enregistré comme tout paiement (montant dans la devise de la facture, facture mise à jour,
-- statut recalculé, audit, événement) — sans acteur humain : c'est le prestataire qui a encaissé.
create or replace function logistics.apply_provider_payment(p_x logistics.payment_intent, p_event bigint, p_corr uuid)
returns uuid language plpgsql volatile set search_path = '' as $$
declare v_i logistics.invoice; v_id uuid := gen_random_uuid(); v_num text; v_meth text;
begin
  select * into v_i from logistics.invoice where id = p_x.invoice_id for update;
  select method into v_meth from logistics.payment_provider where code = p_x.provider_code;
  v_num := logistics.next_number('payment', 'PAY');
  insert into logistics.payment (id, number, invoice_id, customer_id, amount, currency, base_amount_usd, tendered_amount, tendered_currency, rate_used, method, reference,
                                 received_by, correlation_id, provider_code, external_id)
  values (v_id, v_num, p_x.invoice_id, p_x.customer_id, p_x.amount, p_x.currency, logistics.base_amount(p_x.amount, p_x.currency, current_date), p_x.amount, p_x.currency, 1,
          v_meth, p_x.provider_code || ' ' || p_x.external_id, null, p_corr, p_x.provider_code, p_x.external_id);
  perform set_config('logistics.finance_op', 'on', true);
  update logistics.invoice set paid_amount = paid_amount + p_x.amount where id = p_x.invoice_id;
  perform logistics.apply_invoice_status(p_x.invoice_id, null, p_corr);
  perform set_config('logistics.finance_op', 'off', true);
  update logistics.payment_intent set status = 'SUCCEEDED', payment_id = v_id where id = p_x.id;
  perform logistics.fin_audit(null, 'payment.record', 'payment', v_id::text, jsonb_build_object('paid_amount', v_i.paid_amount), jsonb_build_object('paid_amount', v_i.paid_amount + p_x.amount),
                              p_corr, jsonb_build_object('invoice', v_i.number, 'provider', p_x.provider_code, 'external_id', p_x.external_id, 'payment_event_id', p_event));
  perform logistics.emit('PaymentReceived', 'payment', v_id::text, p_corr, null,
                         jsonb_build_object('payment_id', v_id, 'number', v_num, 'invoice_id', p_x.invoice_id, 'customer_id', p_x.customer_id, 'amount', p_x.amount, 'currency', p_x.currency, 'provider', p_x.provider_code));
  return v_id;
end;
$$;

-- Un événement du prestataire, après vérification par le serveur. Idempotent : le même événement, rejoué, rend la même réponse.
create or replace function logistics.ingest_payment_event(p_provider text, p_event_key text, p_external_id text, p_amount numeric, p_currency text, p_status text,
                                                          p_verified boolean, p_raw_reference text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_ev logistics.payment_event; v_x logistics.payment_intent; v_i logistics.invoice; v_corr uuid := gen_random_uuid(); v_id bigint; v_out text; v_det text; v_pay uuid;
        v_prov text := upper(btrim(coalesce(p_provider, '')));
begin
  if not exists (select 1 from logistics.payment_provider where code = v_prov) then raise exception 'Prestataire inconnu : %.', p_provider using errcode = 'LG002'; end if;
  if p_status is null or p_status not in ('PENDING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'REFUNDED') then raise exception 'État de paiement inconnu : %.', p_status using errcode = 'LG005'; end if;
  if p_currency is null or p_currency not in ('USD', 'DOP', 'HTG') then raise exception 'Devise inconnue : %.', p_currency using errcode = 'LG005'; end if;
  if p_amount is null or p_amount < 0 then raise exception 'Montant invalide.' using errcode = 'LG005'; end if;
  if btrim(coalesce(p_event_key, '')) = '' or btrim(coalesce(p_external_id, '')) = '' then raise exception 'Clé d''événement et référence obligatoires.' using errcode = 'LG005'; end if;
  insert into logistics.payment_event (provider_code, event_key, external_id, amount, currency, status, verified, raw_reference, correlation_id)
  values (v_prov, btrim(p_event_key), btrim(p_external_id), round(p_amount, 2), p_currency, p_status, coalesce(p_verified, false), left(coalesce(p_raw_reference, ''), 500), v_corr)
  on conflict (provider_code, event_key) do nothing returning id into v_id;
  if v_id is null then
    -- Le même événement, rejoué par le prestataire (ou par le serveur après une coupure) : rien n'est refait.
    select * into v_ev from logistics.payment_event where provider_code = v_prov and event_key = btrim(p_event_key);
    return jsonb_build_object('event_id', v_ev.id, 'outcome', v_ev.outcome, 'payment_id', v_ev.payment_id, 'replayed', true);
  end if;

  select * into v_x from logistics.payment_intent where provider_code = v_prov and external_id = btrim(p_external_id) for update;
  if not coalesce(p_verified, false) then
    v_out := 'REJECTED_UNVERIFIED'; v_det := 'signature non vérifiée par le serveur : rien n''est appliqué';
  elsif v_x.id is null then
    v_out := 'NO_INTENT'; v_det := 'aucune demande de paiement ne porte cette référence';
  elsif p_status = 'SUCCEEDED' then
    if round(p_amount, 2) <> v_x.amount or p_currency <> v_x.currency then
      v_out := 'MISMATCH'; v_det := format('reçu %s %s, attendu %s %s', round(p_amount, 2), p_currency, v_x.amount, v_x.currency);
    elsif v_x.status = 'SUCCEEDED' then
      v_out := 'ALREADY_PAID'; v_det := 'la demande est déjà payée (un autre événement l''a confirmée)'; v_pay := v_x.payment_id;
    elsif v_x.status not in ('CREATED', 'PENDING') then
      v_out := 'UNAPPLIED'; v_det := format('argent reçu sur une demande %s : à rembourser ou à imputer', v_x.status);
    else
      select * into v_i from logistics.invoice where id = v_x.invoice_id;
      if v_i.status not in ('ISSUED', 'PARTIALLY_PAID', 'OVERDUE') or logistics.invoice_balance(v_i) < v_x.amount then
        v_out := 'UNAPPLIED'; v_det := format('la facture (%s, solde %s) ne peut plus recevoir %s : à rembourser ou à imputer', v_i.status, logistics.invoice_balance(v_i), v_x.amount);
      else
        v_pay := logistics.apply_provider_payment(v_x, v_id, v_corr);
        v_out := 'APPLIED'; v_det := null;
      end if;
    end if;
  elsif p_status = 'REFUNDED' then
    v_out := 'REFUND_TO_RECONCILE'; v_det := 'remboursement fait chez le prestataire : la direction émet l''avoir et enregistre le remboursement';
  else
    -- PENDING, FAILED, CANCELLED : l'état de la demande suit, sans argent.
    if v_x.status in ('CREATED', 'PENDING') and p_status <> v_x.status then
      update logistics.payment_intent set status = p_status where id = v_x.id;
    end if;
    v_out := 'STATUS_UPDATED'; v_det := p_status;
  end if;

  update logistics.payment_event set processed_at = now(), outcome = v_out, outcome_detail = v_det, payment_id = v_pay,
         intent_id = v_x.id, invoice_id = v_x.invoice_id, customer_id = v_x.customer_id where id = v_id;
  perform logistics.fin_audit(null, 'payment_event.' || lower(v_out), 'payment_event', v_id::text, null,
                              jsonb_build_object('provider', v_prov, 'external_id', btrim(p_external_id), 'status', p_status, 'amount', round(p_amount, 2), 'currency', p_currency,
                                                 'verified', coalesce(p_verified, false), 'outcome', v_out, 'detail', v_det), v_corr);
  perform logistics.emit(case when v_out = 'APPLIED' then 'PaymentEventApplied' when v_out = 'STATUS_UPDATED' then 'PaymentIntentUpdated' else 'PaymentEventRejected' end,
                         'payment', v_id::text, v_corr, null,
                         jsonb_build_object('event_id', v_id, 'provider', v_prov, 'outcome', v_out, 'intent_id', v_x.id, 'invoice_id', v_x.invoice_id, 'customer_id', v_x.customer_id));
  return jsonb_build_object('event_id', v_id, 'outcome', v_out, 'detail', v_det, 'payment_id', v_pay, 'replayed', false);
end;
$$;

create or replace function logistics.import_settlement_line(p_provider text, p_external_id text, p_amount numeric, p_currency text, p_settled_on date,
                                                           p_fee_amount numeric default 0, p_batch_ref text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_id bigint; v_prov text := upper(btrim(coalesce(p_provider, '')));
begin
  if not exists (select 1 from logistics.payment_provider where code = v_prov) then raise exception 'Prestataire inconnu : %.', p_provider using errcode = 'LG002'; end if;
  if p_currency not in ('USD', 'DOP', 'HTG') or p_amount is null or p_settled_on is null or btrim(coalesce(p_external_id, '')) = '' then raise exception 'Ligne de relevé invalide.' using errcode = 'LG005'; end if;
  insert into logistics.provider_settlement_line (provider_code, external_id, amount, currency, fee_amount, settled_on, batch_ref)
  values (v_prov, btrim(p_external_id), round(p_amount, 2), p_currency, round(coalesce(p_fee_amount, 0), 2), p_settled_on, coalesce(p_batch_ref, ''))
  on conflict (provider_code, external_id) do nothing returning id into v_id;
  if v_id is null then return jsonb_build_object('imported', false, 'replayed', true); end if;
  perform logistics.emit('SettlementLineImported', 'finance', v_id::text, gen_random_uuid(), null, jsonb_build_object('provider', v_prov, 'external_id', btrim(p_external_id)));
  return jsonb_build_object('imported', true, 'line_id', v_id);
end;
$$;


-- 9. La réconciliation des paiements en ligne ------------------------------------------------------------------------------
-- Ce qui empêche la bascule (« blocking ») tant qu'un humain ne l'a pas examiné, et ce qui n'est qu'informatif.
create or replace function logistics.payment_reconciliation()
returns table (problem text, blocking boolean, entity text, id text, detail text)
language plpgsql stable set search_path = '' as $$
begin
  -- des événements qui ont vu de l'argent sans qu'il soit imputé, non examinés
  return query select 'event_' || lower(e.outcome), true, 'payment_event', e.id::text, coalesce(e.outcome_detail, '') || ' (' || e.provider_code || ' ' || e.external_id || ')'
    from logistics.payment_event e
   where (e.outcome in ('MISMATCH', 'UNAPPLIED', 'REFUND_TO_RECONCILE') or (e.outcome = 'NO_INTENT' and e.status = 'SUCCEEDED'))
     and not exists (select 1 from logistics.finance_review r where r.entity = 'payment_event' and r.entity_id = e.id::text);
  -- informatif : une « réussite » non vérifiée (tentative de fraude, ou secret du serveur mal réglé) — jamais appliquée
  return query select 'event_unverified', false, 'payment_event', e.id::text, e.provider_code || ' ' || e.external_id || ' ' || e.status
    from logistics.payment_event e where e.outcome = 'REJECTED_UNVERIFIED';
  -- un événement reçu et jamais traité (ne doit pas arriver : le traitement est dans la même transaction)
  return query select 'event_unprocessed', true, 'payment_event', e.id::text, e.provider_code || ' ' || e.external_id from logistics.payment_event e where e.processed_at is null;
  -- un paiement de prestataire sans événement vérifié appliqué qui le porte
  return query select 'payment_without_event', true, 'payment', p.id::text, p.number || ' ' || p.provider_code || ' ' || p.external_id
    from logistics.payment p where p.provider_code is not null
     and not exists (select 1 from logistics.payment_event e where e.payment_id = p.id and e.verified and e.outcome = 'APPLIED');
  -- une demande « payée » sans paiement (impossible : contrainte) ou un paiement de demande d'un autre montant
  return query select 'intent_amount_mismatch', true, 'payment_intent', x.id::text, x.number || ' : ' || x.amount || ' ≠ ' || p.amount
    from logistics.payment_intent x join logistics.payment p on p.id = x.payment_id where p.amount <> x.amount;
  -- le relevé du prestataire : argent versé sans paiement, montant ou devise différents
  return query select 'settlement_without_payment', true, 'settlement', s.id::text, s.provider_code || ' ' || s.external_id || ' : ' || s.amount || ' ' || s.currency
    from logistics.provider_settlement_line s
   where not exists (select 1 from logistics.payment p where p.provider_code = s.provider_code and p.external_id = s.external_id)
     and not exists (select 1 from logistics.finance_review r where r.entity = 'settlement_line' and r.entity_id = s.id::text);
  return query select 'settlement_amount_mismatch', true, 'settlement', s.id::text, s.provider_code || ' ' || s.external_id || ' : relevé ' || s.amount || ' ' || s.currency || ', paiement ' || p.amount || ' ' || p.currency
    from logistics.provider_settlement_line s join logistics.payment p on p.provider_code = s.provider_code and p.external_id = s.external_id
   where (s.amount, s.currency) is distinct from (p.amount, p.currency)
     and not exists (select 1 from logistics.finance_review r where r.entity = 'settlement_line' and r.entity_id = s.id::text);
  -- informatif : un paiement de prestataire de plus de 7 jours que le relevé ne cite pas encore
  return query select 'payment_not_settled', false, 'payment', p.id::text, p.number || ' ' || p.provider_code || ' ' || p.external_id || ' du ' || p.paid_at::date
    from logistics.payment p where p.provider_code is not null and p.paid_at < now() - interval '7 days'
     and not exists (select 1 from logistics.provider_settlement_line s where s.provider_code = p.provider_code and s.external_id = p.external_id);
  -- informatif : demandes abandonnées
  return query select 'intent_stale', false, 'payment_intent', x.id::text, x.number || ' ' || x.status from logistics.payment_intent x where x.status in ('CREATED', 'PENDING') and x.expires_at < now() - interval '1 day';
end;
$$;

create or replace function logistics.review_settlement_line(p_actor uuid, p_line bigint, p_note text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_s logistics.provider_settlement_line; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_note, '')) = '' then raise exception 'Une note est obligatoire : ce qui a été fait.' using errcode = 'LG005'; end if;
  select * into v_s from logistics.provider_settlement_line where id = p_line;
  if not found then raise exception 'Ligne de relevé introuvable.' using errcode = 'LG002'; end if;
  if not exists (select 1 from logistics.payment_reconciliation() x where x.entity = 'settlement' and x.id = p_line::text) then raise exception 'Cette ligne n''a pas d''écart.' using errcode = 'LG004'; end if;
  insert into logistics.finance_review (entity, entity_id, verdict, note, reviewed_by, correlation_id) values ('settlement_line', p_line::text, 'SETTLEMENT', left(btrim(p_note), 2000), p_actor, v_corr);
  perform logistics.fin_audit(p_actor, 'settlement.review', 'settlement_line', p_line::text, jsonb_build_object('external_id', v_s.external_id, 'amount', v_s.amount), jsonb_build_object('reviewed', true, 'note', left(btrim(p_note), 2000)), v_corr);
  return jsonb_build_object('line_id', p_line, 'reviewed', true);
end;
$$;

create or replace function logistics.review_payment_event(p_actor uuid, p_event bigint, p_note text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_e logistics.payment_event; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_note, '')) = '' then raise exception 'Une note est obligatoire : ce qui a été fait (remboursé, imputé, contesté…).' using errcode = 'LG005'; end if;
  select * into v_e from logistics.payment_event where id = p_event;
  if not found then raise exception 'Événement introuvable.' using errcode = 'LG002'; end if;
  if v_e.outcome in ('APPLIED', 'STATUS_UPDATED') then raise exception 'Cet événement n''a pas d''écart à examiner.' using errcode = 'LG004'; end if;
  if exists (select 1 from logistics.finance_review where entity = 'payment_event' and entity_id = p_event::text) then raise exception 'Écart déjà examiné.' using errcode = 'LG004'; end if;
  insert into logistics.finance_review (entity, entity_id, verdict, note, reviewed_by, correlation_id) values ('payment_event', p_event::text, v_e.outcome, left(btrim(p_note), 2000), p_actor, v_corr);
  perform logistics.fin_audit(p_actor, 'payment_event.review', 'payment_event', p_event::text, jsonb_build_object('outcome', v_e.outcome), jsonb_build_object('reviewed', true, 'note', left(btrim(p_note), 2000)), v_corr);
  perform logistics.emit('PaymentEventReviewed', 'payment', p_event::text, v_corr, p_actor, jsonb_build_object('event_id', p_event, 'outcome', v_e.outcome));
  return jsonb_build_object('event_id', p_event, 'reviewed', true);
end;
$$;


-- 10. Ajustement et facture groupée -------------------------------------------------------------------------------------------
-- L'AJUSTEMENT : une facture complémentaire (motif, direction), émise aussitôt, liée à la facture corrigée. La taxe suit le taux
-- effectif de la facture d'origine (taxe ÷ montant hors taxe), arrondie au centime ; le revenu se reconnaît à l'émission.
create or replace function logistics.issue_adjustment(p_actor uuid, p_invoice uuid, p_net_amount numeric, p_reason text, p_due_days int default 30)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_o logistics.invoice; v_id uuid := gen_random_uuid(); v_corr uuid := gen_random_uuid(); v_tax numeric; v_ht numeric; v_res jsonb;
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour un ajustement.' using errcode = 'LG005'; end if;
  if p_net_amount is null or p_net_amount <= 0 then raise exception 'Un ajustement ajoute un montant positif (pour retirer : un avoir).' using errcode = 'LG005'; end if;
  select * into v_o from logistics.invoice where id = p_invoice;
  if not found then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  if v_o.status_authority <> 'core' then raise exception 'Facture de l''ancien schéma : elle s''y corrige.' using errcode = 'LG004'; end if;
  if v_o.status in ('DRAFT', 'CANCELLED') then raise exception 'On n''ajuste qu''une facture émise (elle est %).', v_o.status using errcode = 'LG004'; end if;
  v_ht := v_o.total - v_o.tax_total;
  v_tax := case when v_ht > 0 and v_o.tax_total > 0 then round(round(p_net_amount, 2) * v_o.tax_total / v_ht, 2) else 0 end;
  perform set_config('logistics.finance_op', 'on', true);
  insert into logistics.invoice (id, organization_id, number, customer_id, currency, status, status_authority, total, service_fee, subtotal, discount_total, surcharge_total, tax_total,
                                 is_grouped, note, source, kind, corrects_invoice_id)
  values (v_id, v_o.organization_id, 'DRAFT-' || substr(replace(v_id::text, '-', ''), 1, 12), v_o.customer_id, v_o.currency, 'DRAFT', 'core', round(p_net_amount, 2) + v_tax, 0,
          round(p_net_amount, 2), 0, 0, v_tax, false, 'Ajustement de ' || v_o.number || ' : ' || left(btrim(p_reason), 200), 'native', 'ADJUSTMENT', p_invoice);
  insert into logistics.invoice_item (invoice_id, kind, code, description, quantity, unit_price, amount, position)
  values (v_id, 'OTHER', 'ADJUSTMENT', 'Ajustement de ' || v_o.number || ' : ' || left(btrim(p_reason), 200), 1, round(p_net_amount, 2), round(p_net_amount, 2), 1);
  if v_tax > 0 then
    insert into logistics.invoice_item (invoice_id, kind, code, description, quantity, unit_price, amount, position) values (v_id, 'TAX', 'ADJUSTMENT_TAX', 'Taxe', 1, v_tax, v_tax, 2);
  end if;
  perform set_config('logistics.finance_op', 'off', true);
  perform logistics.fin_audit(p_actor, 'invoice.adjust', 'invoice', p_invoice::text, null,
                              jsonb_build_object('adjustment_invoice', v_id, 'net', round(p_net_amount, 2), 'tax', v_tax, 'reason', left(btrim(p_reason), 500)), v_corr);
  v_res := logistics.issue_invoice(p_actor, v_id, p_due_days, v_corr);
  perform logistics.emit('InvoiceAdjusted', 'invoice', p_invoice::text, v_corr, p_actor,
                         jsonb_build_object('invoice_id', p_invoice, 'adjustment_invoice_id', v_id, 'number', v_res ->> 'number', 'net', round(p_net_amount, 2), 'tax', v_tax, 'reason', left(btrim(p_reason), 500)));
  return v_res || jsonb_build_object('adjustment_of', v_o.number, 'net', round(p_net_amount, 2), 'tax', v_tax);
end;
$$;

-- La FACTURE GROUPÉE : plusieurs colis d'un même client, un devis, une facture, une émission, des frais de service UNE fois —
-- dans UNE transaction : si un seul colis ne peut pas être facturé, rien n'est créé (ni devis, ni brouillon).
create or replace function logistics.create_grouped_invoice(p_actor uuid, p_customer uuid, p_currency text, p_parcel_ids uuid[], p_due_days int default 30,
                                                            p_idempotency_key text default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_prior jsonb; v_q jsonb; v_inv jsonb; v_res jsonb; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'factures.creer');
  v_prior := logistics.idem_begin(p_idempotency_key, 'create_grouped_invoice', md5(concat_ws('|', p_customer, p_currency, p_parcel_ids::text, p_due_days)), coalesce(p_customer::text, ''));
  if v_prior is not null then return v_prior; end if;
  if coalesce(cardinality(p_parcel_ids), 0) < 2 then raise exception 'Une facture groupée réunit au moins deux colis.' using errcode = 'LG005'; end if;
  if (select count(distinct x) from unnest(p_parcel_ids) x) <> cardinality(p_parcel_ids) then raise exception 'Un colis est cité deux fois.' using errcode = 'LG005'; end if;
  v_q := logistics.create_quote(p_actor, p_customer, p_currency, (select jsonb_agg(jsonb_build_object('parcel_id', x)) from unnest(p_parcel_ids) x), 0, current_date, v_corr);
  v_inv := logistics.invoice_from_quote(p_actor, (v_q ->> 'quote_id')::uuid, p_due_days, true, v_corr);
  perform logistics.emit('GroupedInvoiceCreated', 'invoice', v_inv ->> 'invoice_id', v_corr, p_actor,
                         jsonb_build_object('invoice_id', v_inv ->> 'invoice_id', 'quote_id', v_q ->> 'quote_id', 'parcels', cardinality(p_parcel_ids)));
  v_res := jsonb_build_object('invoice_id', v_inv ->> 'invoice_id', 'number', v_inv ->> 'number', 'quote_number', v_q ->> 'number', 'status', v_inv ->> 'status',
                              'total', (v_inv ->> 'total')::numeric, 'currency', p_currency, 'parcels', cardinality(p_parcel_ids), 'grouped', (v_inv ->> 'grouped')::boolean,
                              'correlation_id', v_corr, 'replayed', false);
  return logistics.idem_end(p_idempotency_key, v_res);
end;
$$;


-- 11. Parité avec l'ancien schéma, et bascule -----------------------------------------------------------------------------------
-- Chaque facture héritée (public.factures) recalculée par le NOYAU sur ses colis, au tarif du colis ou à son prix saisi : même
-- montant attendu. Les écarts sont CLASSÉS ; seuls les inexpliqués et les blocages de configuration empêchent la bascule.
create or replace function logistics.legacy_finance_parity()
returns table (legacy_invoice_id uuid, number text, legacy_total numeric, core_total numeric, verdict text, detail text)
language plpgsql stable security definer set search_path = '' as $$
declare r record; v_items jsonb; v_calc jsonb; v_n int; v_nul int; v_change int; v_err text;
begin
  if to_regclass('public.factures') is null then return; end if;
  for r in execute $q$
      select f.id, f.numero, f.montant, f.client_id, f.colis_id, coalesce(f.lignes, '[]'::jsonb) as lignes, f.devise, f.frais_service
        from public.factures f order by f.numero $q$ loop
    legacy_invoice_id := r.id; number := r.numero; legacy_total := r.montant; core_total := null; detail := null;
    -- Les colis de la facture : le sien, ou ceux de ses lignes (facture groupée), retrouvés dans le noyau.
    select coalesce(jsonb_agg(jsonb_build_object('parcel_id', p.id) order by p.tracking_number), '[]'::jsonb), count(*),
           count(*) filter (where p.manual_price is null and coalesce(p.rate_per_lb, 0) = 0),
           count(*) filter (where exists (select 1 from jsonb_array_elements(r.lignes) l where (l ->> 'colis_id')::uuid = p.legacy_parcel_id
                                            and ((l ->> 'poids_lb')::numeric is distinct from p.weight_lb or (l ->> 'tarif_lb')::numeric is distinct from p.rate_per_lb
                                                 or coalesce((l ->> 'prix_manuel')::boolean, false) <> (p.manual_price is not null))))
      into v_items, v_n, v_nul, v_change
      from logistics.parcel p
     where p.legacy_parcel_id = r.colis_id or p.legacy_parcel_id in (select (l ->> 'colis_id')::uuid from jsonb_array_elements(r.lignes) l where l ? 'colis_id');
    if v_n = 0 then verdict := 'NO_PARCEL'; detail := 'aucun colis du noyau pour cette facture'; return next; continue; end if;
    if r.devise <> 'USD' then verdict := 'CURRENCY'; detail := 'devise ' || r.devise || ' : hors parité (l''ancien schéma facture en USD)'; return next; continue; end if;
    begin
      v_calc := logistics.compute_quote((select c.id from logistics.customer c where c.legacy_client_id = r.client_id), 'USD', v_items, current_date, false);
      core_total := (v_calc ->> 'total')::numeric;
    exception when others then
      v_err := sqlerrm; core_total := null;
    end;
    if core_total is null then verdict := 'NO_PRICING'; detail := v_err;
    elsif core_total = r.montant then verdict := 'EQUAL';
    elsif (v_calc ->> 'service_fee')::numeric <> coalesce(r.frais_service, 10) then verdict := 'SERVICE_FEE'; detail := 'frais de service du noyau ' || (v_calc ->> 'service_fee') || ' ≠ ' || r.frais_service;
    elsif v_nul > 0 then verdict := 'ZERO_RATE'; detail := v_nul || ' colis sans tarif ni prix saisi : l''ancien schéma facture 0, le noyau applique la grille';
    elsif v_change > 0 then verdict := 'PARCEL_CHANGED'; detail := 'le colis a changé depuis l''émission : la facture héritée garde son prix figé';
    else verdict := 'UNEXPLAINED'; detail := 'écart ' || (core_total - r.montant)::text;
    end if;
    return next;
  end loop;
end;
$$;

create or replace function logistics.finance_cutover_report(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_par jsonb; v_core jsonb; v_pay jsonb; v_bloc int; v_ready boolean;
begin
  if p_actor is not null then perform logistics.require_right(p_actor, 'direction'); end if;
  select jsonb_build_object('total', count(*), 'by_verdict', coalesce(jsonb_object_agg(verdict, n), '{}'::jsonb)) into v_par
    from (select verdict, count(*) n from logistics.legacy_finance_parity() group by verdict) x;
  v_par := v_par || jsonb_build_object('total', coalesce((select sum(value::int) from jsonb_each_text(v_par -> 'by_verdict')), 0),
                                       'examples', coalesce((select jsonb_agg(jsonb_build_object('number', p.number, 'legacy', p.legacy_total, 'core', p.core_total, 'verdict', p.verdict, 'detail', p.detail))
                                                               from (select * from logistics.legacy_finance_parity() x where verdict in ('UNEXPLAINED', 'NO_PRICING', 'SERVICE_FEE', 'NO_PARCEL', 'CURRENCY')
                                                                 and not exists (select 1 from logistics.finance_review r where r.entity = 'legacy_invoice' and r.entity_id = x.legacy_invoice_id::text) limit 20) p), '[]'::jsonb));
  select jsonb_build_object('problems', count(*), 'items', coalesce(jsonb_agg(jsonb_build_object('problem', problem, 'entity', entity, 'id', id, 'detail', detail)) filter (where true), '[]'::jsonb))
    into v_core from (select * from logistics.reconcile_finance() limit 50) z;
  select jsonb_build_object('blocking', count(*) filter (where blocking), 'informative', count(*) filter (where not blocking),
                            'items', coalesce(jsonb_agg(jsonb_build_object('problem', problem, 'blocking', blocking, 'entity', entity, 'id', id, 'detail', detail)), '[]'::jsonb))
    into v_pay from logistics.payment_reconciliation();
  -- Bloquent : les écarts inexpliqués, les prix que le noyau ne sait pas calculer, les frais de service différents, les factures sans
  -- colis — sauf ceux qu'un membre de la direction a examinés (finance_review, motif tracé).
  select count(*) into v_bloc from logistics.legacy_finance_parity() p
   where p.verdict in ('UNEXPLAINED', 'NO_PRICING', 'SERVICE_FEE', 'NO_PARCEL', 'CURRENCY')
     and not exists (select 1 from logistics.finance_review r where r.entity = 'legacy_invoice' and r.entity_id = p.legacy_invoice_id::text);
  v_par := v_par || jsonb_build_object('reviewed', (select count(*) from logistics.finance_review where entity = 'legacy_invoice'));
  v_ready := v_bloc = 0 and (v_core ->> 'problems')::int = 0 and (v_pay ->> 'blocking')::int = 0
             and coalesce((select json_agg(1) from logistics.reconcile_with_legacy())::text, '[]') = '[]';
  return jsonb_build_object('as_of', now(), 'mode', (select value from logistics.finance_setting where key = 'mode'), 'ready', v_ready,
                            'parity', v_par, 'parity_blocking', v_bloc, 'core', v_core, 'payments', v_pay,
                            'copy_differences', (select count(*) from logistics.reconcile_with_legacy()));
end;
$$;

create or replace function logistics.review_legacy_parity(p_actor uuid, p_legacy_invoice uuid, p_note text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_p record; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  if btrim(coalesce(p_note, '')) = '' then raise exception 'Une note est obligatoire : pourquoi cet écart est compris.' using errcode = 'LG005'; end if;
  select * into v_p from logistics.legacy_finance_parity() x where x.legacy_invoice_id = p_legacy_invoice;
  if not found then raise exception 'Facture héritée introuvable.' using errcode = 'LG002'; end if;
  if v_p.verdict = 'EQUAL' then raise exception 'Cette facture n''a pas d''écart.' using errcode = 'LG004'; end if;
  if exists (select 1 from logistics.finance_review where entity = 'legacy_invoice' and entity_id = p_legacy_invoice::text) then raise exception 'Écart déjà examiné.' using errcode = 'LG004'; end if;
  insert into logistics.finance_review (entity, entity_id, verdict, note, reviewed_by, correlation_id) values ('legacy_invoice', p_legacy_invoice::text, v_p.verdict, left(btrim(p_note), 2000), p_actor, v_corr);
  perform logistics.fin_audit(p_actor, 'finance.parity_review', 'legacy_invoice', p_legacy_invoice::text, jsonb_build_object('verdict', v_p.verdict, 'legacy', v_p.legacy_total, 'core', v_p.core_total),
                              jsonb_build_object('reviewed', true, 'note', left(btrim(p_note), 2000)), v_corr);
  return jsonb_build_object('legacy_invoice_id', p_legacy_invoice, 'number', v_p.number, 'verdict', v_p.verdict, 'reviewed', true);
end;
$$;

-- La bascule : vers le noyau SEULEMENT si la réconciliation est propre (direction, motif) ; le retour à l'ancien schéma, toujours.
create or replace function logistics.set_finance_mode(p_actor uuid, p_mode text, p_reason text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_rap jsonb; v_avant text; v_corr uuid := gen_random_uuid();
begin
  perform logistics.require_right(p_actor, 'direction');
  if p_mode not in ('legacy', 'core') then raise exception 'Moteur inconnu : % (legacy ou core).', p_mode using errcode = 'LG005'; end if;
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Un motif est obligatoire pour changer de moteur de facturation.' using errcode = 'LG005'; end if;
  select value into v_avant from logistics.finance_setting where key = 'mode' for update;
  if v_avant = p_mode then raise exception 'Le moteur de facturation est déjà %.', p_mode using errcode = 'LG004'; end if;
  if p_mode = 'core' then
    v_rap := logistics.finance_cutover_report(null);
    if not (v_rap ->> 'ready')::boolean then
      raise exception 'Bascule refusée : la réconciliation financière n''est pas propre (parité : %, noyau : %, paiements : %).',
        v_rap ->> 'parity_blocking', v_rap -> 'core' ->> 'problems', v_rap -> 'payments' ->> 'blocking' using errcode = 'LG010';
    end if;
  end if;
  update logistics.finance_setting set value = p_mode, reason = left(btrim(p_reason), 500), updated_by = p_actor, updated_at = now() where key = 'mode';
  perform logistics.fin_audit(p_actor, 'finance.mode', 'finance_setting', 'mode', jsonb_build_object('mode', v_avant), jsonb_build_object('mode', p_mode, 'reason', left(btrim(p_reason), 500)), v_corr,
                              case when v_rap is null then '{}'::jsonb else jsonb_build_object('report', v_rap - 'parity' - 'core' - 'payments') end);
  perform logistics.emit('FinanceModeChanged', 'finance', 'mode', v_corr, p_actor, jsonb_build_object('from', v_avant, 'to', p_mode));
  return jsonb_build_object('mode', p_mode, 'previous', v_avant);
end;
$$;


-- 12. La façade ----------------------------------------------------------------------------------------------------------------
-- a. comptes connectés (l'acteur est TOUJOURS le compte connecté)
create or replace function public.lg_payment_providers(p_currency text default null, p_country text default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  return logistics.payment_providers_for(p_currency, p_country);
end;
$$;
create or replace function public.lg_my_create_payment_intent(p_invoice_number text, p_provider text, p_idempotency_key text default null)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid;
begin
  if auth.uid() is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  select i.id into v_id from logistics.invoice i where i.number = upper(btrim(coalesce(p_invoice_number, ''))) and i.customer_id = logistics.my_customer(auth.uid());
  if v_id is null then raise exception 'Facture introuvable.' using errcode = 'LG002'; end if;
  return logistics.create_payment_intent(auth.uid(), v_id, p_provider, true, case when p_idempotency_key is null then null else 'pin:' || auth.uid()::text || ':' || p_idempotency_key end);
end;
$$;
create or replace function public.lg_my_payment_intent(p_number text)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_payment_intent(auth.uid(), p_number) $$;
create or replace function public.lg_create_payment_intent(p_invoice_id uuid, p_provider text, p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_payment_intent(auth.uid(), p_invoice_id, p_provider, false, p_idempotency_key) $$;
create or replace function public.lg_configure_payment_provider(p_code text, p_active boolean default null, p_environment text default null, p_public_config jsonb default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.configure_payment_provider(auth.uid(), p_code, p_active, p_environment, p_public_config) $$;
create or replace function public.lg_review_payment_event(p_event_id bigint, p_note text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.review_payment_event(auth.uid(), p_event_id, p_note) $$;
create or replace function public.lg_review_settlement_line(p_line_id bigint, p_note text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.review_settlement_line(auth.uid(), p_line_id, p_note) $$;
create or replace function public.lg_issue_adjustment(p_invoice uuid, p_net_amount numeric, p_reason text, p_due_days int default 30)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.issue_adjustment(auth.uid(), p_invoice, p_net_amount, p_reason, p_due_days) $$;
create or replace function public.lg_create_grouped_invoice(p_customer uuid, p_currency text, p_parcel_ids uuid[], p_due_days int default 30, p_idempotency_key text default null)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_grouped_invoice(auth.uid(), p_customer, p_currency, p_parcel_ids, p_due_days, p_idempotency_key) $$;
create or replace function public.lg_finance_cutover_report()
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  if auth.uid() is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  return logistics.finance_cutover_report(auth.uid());
end;
$$;
create or replace function public.lg_review_legacy_parity(p_legacy_invoice_id uuid, p_note text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.review_legacy_parity(auth.uid(), p_legacy_invoice_id, p_note) $$;
create or replace function public.lg_set_finance_mode(p_mode text, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.set_finance_mode(auth.uid(), p_mode, p_reason) $$;

-- b. le SERVEUR seul (rôle service_role, celui de la clé secrète de Supabase, dans une Edge Function)
create or replace function public.ses_payment_attach(p_intent_id uuid, p_provider text, p_external_id text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.attach_payment_intent(p_intent_id, p_provider, p_external_id) $$;
create or replace function public.ses_payment_event(p_provider text, p_event_key text, p_external_id text, p_amount numeric, p_currency text, p_status text,
                                                    p_verified boolean, p_raw_reference text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$
  select logistics.ingest_payment_event(p_provider, p_event_key, p_external_id, p_amount, p_currency, p_status, p_verified, p_raw_reference) $$;
create or replace function public.ses_payment_settlement(p_provider text, p_external_id text, p_amount numeric, p_currency text, p_settled_on date,
                                                         p_fee_amount numeric default 0, p_batch_ref text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$
  select logistics.import_settlement_line(p_provider, p_external_id, p_amount, p_currency, p_settled_on, p_fee_amount, p_batch_ref) $$;


-- 13. Tout fermé, sauf la façade -------------------------------------------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('json_has_secret_key', 'guard_payment_intent', 'guard_payment_event', 'compute_quote', 'configure_payment_provider',
              'payment_providers_for', 'create_payment_intent', 'payment_intent_view', 'my_payment_intent', 'attach_payment_intent', 'apply_provider_payment', 'ingest_payment_event',
              'import_settlement_line', 'payment_reconciliation', 'review_payment_event', 'issue_adjustment', 'create_grouped_invoice', 'legacy_finance_parity',
              'finance_cutover_report', 'set_finance_mode', 'review_legacy_parity', 'review_settlement_line') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_payment_providers', 'lg_my_create_payment_intent', 'lg_my_payment_intent', 'lg_create_payment_intent',
              'lg_configure_payment_provider', 'lg_review_payment_event', 'lg_issue_adjustment', 'lg_create_grouped_invoice', 'lg_finance_cutover_report', 'lg_set_finance_mode', 'lg_review_legacy_parity', 'lg_review_settlement_line') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
  -- Les portes du serveur : ni visiteur, ni compte connecté. Seul « service_role » (la clé secrète, jamais dans un navigateur).
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('ses_payment_attach', 'ses_payment_event', 'ses_payment_settlement') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    if exists (select 1 from pg_roles where rolname = 'service_role') then execute format('grant execute on function %s to service_role', r.sig); end if;
  end loop;
end
$$;
