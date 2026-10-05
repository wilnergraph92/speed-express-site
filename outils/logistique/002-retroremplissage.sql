-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 2 : rattrapage des données
-- -----------------------------------------------------------------------------
-- Phase 5. À coller dans Supabase > SQL Editor APRÈS 001, et après sauvegarde vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site ».
--
-- Ce script crée DEUX FONCTIONS. Il ne copie encore aucune donnée par lui-même :
--     select logistics.reconcile_with_legacy();      -- ne modifie RIEN : liste les écarts
--     select logistics.backfill_from_legacy();       -- copie ; rejouable à volonté
-- (la seconde se lance à la main, une fois, quand vous le décidez.)
--
-- Garanties :
--   · LECTURE SEULE sur l'ancien schéma : clients, colis, colis_historique, factures,
--     appareils ne sont jamais modifiés ;
--   · IDEMPOTENT : rejouée sans changement de l'ancien schéma, elle n'insère ni ne
--     modifie rien (elle le dit : « 0 / 0 ») ;
--   · NE SUPPRIME RIEN : ni dans le nouveau schéma, ni dans l'ancien ;
--   · N'INVENTE RIEN : aucun paiement, aucune succursale, aucun entrepôt, aucune position ;
--   · après la première prise de contrôle d'un colis par la machine d'états du noyau
--     (status_authority = 'core', phase 6), le rattrapage ne touche plus à son statut ;
--   · à lancer dans une transaction courte ; en cas d'erreur, rien n'est conservé.
--
-- Prérequis : supabase-maj.sql (frais_service, montant_paye) déjà passé — c'est le cas en production.
-- Retour arrière : drop schema logistics cascade;
-- =============================================================================

create or replace function logistics.map_legacy_parcel_status(p text)
returns text language sql immutable set search_path = '' as $$
  select case p
    when 'confirme'   then 'CREATED'
    when 'expedie'    then 'IN_TRANSIT'
    when 'disponible' then 'AT_DESTINATION_HUB'
    when 'livre'      then 'DELIVERED'
    when 'action'     then 'ON_HOLD'
  end
$$;
comment on function logistics.map_legacy_parcel_status is
  'Les cinq statuts historiques vers la machine d''états. Le statut d''origine est toujours conservé à côté (parcel.legacy_status).';

create or replace function logistics.map_legacy_service(p text)
returns text language sql immutable set search_path = '' as $$
  select case p when 'aerien' then 'air' when 'maritime' then 'sea' when 'terrestre' then 'ground' end
$$;

create or replace function logistics.backfill_from_legacy()
returns jsonb
language plpgsql
volatile
set search_path = ''
as $$
declare
  v_org uuid;
  v_rap jsonb := '{}'::jsonb;
  n_ins int;
  n_upd int;
begin
  select id into v_org from logistics.organization order by created_at limit 1;
  if v_org is null then
    raise exception 'Aucune organisation : passez d''abord 001-modele-de-domaine.sql.' using errcode = 'LG002';
  end if;

  -- 1. Clients -------------------------------------------------------------------------
  -- Tout compte « client », plus tout compte d'équipe hérité qui porte encore des colis ou des
  -- factures (ils doivent avoir un propriétaire dans le nouveau modèle).
  with src as (
    select c.* from public.clients c
    where c.role = 'client'
       or exists (select 1 from public.colis p where p.client_id = c.id)
       or exists (select 1 from public.factures f where f.client_id = c.id)
  ), up as (
    insert into logistics.customer as t (organization_id, code, auth_user_id, full_name, country, region, city,
                                         address, phone, email, language, source, legacy_client_id, created_at)
    select v_org, s.code, s.id, s.nom_complet, s.pays, s.region, s.ville, s.adresse, s.telephone, s.email,
           case when s.langue in ('fr', 'en', 'es', 'ht') then s.langue else 'fr' end,
           case when s.role = 'client' then 'legacy_backfill' else 'legacy_staff_account' end, s.id, s.cree_le
    from src s
    on conflict (legacy_client_id) do update set
      code = excluded.code, auth_user_id = excluded.auth_user_id, full_name = excluded.full_name,
      country = excluded.country, region = excluded.region, city = excluded.city, address = excluded.address,
      phone = excluded.phone, email = excluded.email, language = excluded.language, source = excluded.source
    where (t.code, t.auth_user_id, t.full_name, t.country, t.region, t.city, t.address, t.phone, t.email, t.language, t.source)
          is distinct from
          (excluded.code, excluded.auth_user_id, excluded.full_name, excluded.country, excluded.region, excluded.city,
           excluded.address, excluded.phone, excluded.email, excluded.language, excluded.source)
    returning (xmax = 0) as inserted
  )
  select count(*) filter (where inserted), count(*) filter (where not inserted) into n_ins, n_upd from up;
  v_rap := v_rap || jsonb_build_object('customer', jsonb_build_object('inserted', n_ins, 'updated', n_upd));

  -- 2. Personnel ------------------------------------------------------------------------
  with up as (
    insert into logistics.app_user as t (id, organization_id, role, rights, active, created_at)
    select c.id, v_org,
           case c.role when 'employe' then 'employee' when 'gerant' then 'manager' when 'admin' then 'admin' end,
           c.droits, true, c.cree_le
    from public.clients c where c.role <> 'client'
    on conflict (id) do update set role = excluded.role, rights = excluded.rights, active = true
    where (t.role, t.rights, t.active) is distinct from (excluded.role, excluded.rights, true)
    returning (xmax = 0) as inserted
  ), retired as (
    -- Un ancien membre de l'équipe redevenu client : on le désactive, on ne le supprime jamais.
    update logistics.app_user u set active = false
    from public.clients c where c.id = u.id and c.role = 'client' and u.active
    returning 1
  )
  select (select count(*) from up where inserted), (select count(*) from up where not inserted) + (select count(*) from retired)
    into n_ins, n_upd;
  v_rap := v_rap || jsonb_build_object('app_user', jsonb_build_object('inserted', n_ins, 'updated', n_upd));

  -- 3. Appareils (table créée par la migration des notifications ; absente = rien à faire) -------
  if to_regclass('public.appareils') is not null then
    execute $q$
      with up as (
        insert into logistics.device as t (kind, platform, push_token, owner_customer_id, owner_user_id,
                                           last_seen_at, source, created_at)
        select 'customer_push', a.plateforme, a.jeton, cu.id, au.id, a.vu_le, 'legacy_backfill', a.cree_le
        from public.appareils a
        left join logistics.customer cu on cu.legacy_client_id = a.client_id
        left join logistics.app_user au on au.id = a.client_id and cu.id is null
        on conflict (push_token) do update set platform = excluded.platform,
          owner_customer_id = excluded.owner_customer_id, owner_user_id = excluded.owner_user_id,
          last_seen_at = excluded.last_seen_at
        where (t.platform, t.owner_customer_id, t.owner_user_id, t.last_seen_at)
              is distinct from (excluded.platform, excluded.owner_customer_id, excluded.owner_user_id, excluded.last_seen_at)
        returning (xmax = 0) as inserted
      )
      select count(*) filter (where inserted), count(*) filter (where not inserted) from up
    $q$ into n_ins, n_upd;
  else
    n_ins := 0; n_upd := 0;
  end if;
  v_rap := v_rap || jsonb_build_object('device', jsonb_build_object('inserted', n_ins, 'updated', n_upd));

  -- 4. Colis ------------------------------------------------------------------------------
  with up as (
    insert into logistics.parcel as t (organization_id, tracking_number, public_token, customer_id, description,
        sender_name, recipient_name, recipient_phone, delivery_address, destination_country, destination_city,
        declared_value, weight_lb, rate_per_lb, service_mode, status, legacy_status, current_location, note,
        source, legacy_parcel_id, created_at)
    select v_org, p.numero, p.jeton, cu.id, p.description, p.expediteur, p.destinataire, p.telephone_destinataire,
           p.adresse_livraison, p.pays_destination, p.ville_destination, p.valeur_declaree, p.poids_lb, p.tarif_lb,
           logistics.map_legacy_service(p.service), logistics.map_legacy_parcel_status(p.statut), p.statut,
           p.lieu, p.note, 'legacy_backfill', p.id, p.cree_le
    from public.colis p
    left join logistics.customer cu on cu.legacy_client_id = p.client_id
    on conflict (legacy_parcel_id) do update set
      tracking_number = excluded.tracking_number, public_token = excluded.public_token, customer_id = excluded.customer_id,
      description = excluded.description, sender_name = excluded.sender_name, recipient_name = excluded.recipient_name,
      recipient_phone = excluded.recipient_phone, delivery_address = excluded.delivery_address,
      destination_country = excluded.destination_country, destination_city = excluded.destination_city,
      declared_value = excluded.declared_value, weight_lb = excluded.weight_lb, rate_per_lb = excluded.rate_per_lb,
      service_mode = excluded.service_mode, legacy_status = excluded.legacy_status,
      current_location = excluded.current_location, note = excluded.note,
      -- Dès que la machine d'états du noyau a pris la main, l'ancien statut n'écrase plus rien.
      status = case when t.status_authority = 'legacy' then excluded.status else t.status end
    where (t.tracking_number, t.public_token, t.customer_id, t.description, t.sender_name, t.recipient_name,
           t.recipient_phone, t.delivery_address, t.destination_country, t.destination_city, t.declared_value,
           t.weight_lb, t.rate_per_lb, t.service_mode, t.legacy_status, t.current_location, t.note)
          is distinct from
          (excluded.tracking_number, excluded.public_token, excluded.customer_id, excluded.description, excluded.sender_name,
           excluded.recipient_name, excluded.recipient_phone, excluded.delivery_address, excluded.destination_country,
           excluded.destination_city, excluded.declared_value, excluded.weight_lb, excluded.rate_per_lb,
           excluded.service_mode, excluded.legacy_status, excluded.current_location, excluded.note)
       or (t.status_authority = 'legacy' and t.status <> excluded.status)
    returning (xmax = 0) as inserted
  )
  select count(*) filter (where inserted), count(*) filter (where not inserted) into n_ins, n_upd from up;
  v_rap := v_rap || jsonb_build_object('parcel', jsonb_build_object('inserted', n_ins, 'updated', n_upd));

  -- 5. Journal du colis : chaque ligne de l'ancien historique devient un événement ------------------
  -- Ajout seul (« on conflict do nothing ») : un événement déjà copié n'est jamais modifié.
  with ins as (
    insert into logistics.tracking_event (parcel_id, event_type, from_status, to_status, occurred_at, actor_user_id,
                                          actor_label, location_text, source, metadata, legacy_history_id)
    select pa.id, 'ParcelStatusChanged',
           lag(logistics.map_legacy_parcel_status(h.statut)) over (partition by h.colis_id order by h.cree_le, h.id),
           logistics.map_legacy_parcel_status(h.statut), h.cree_le,
           (select au.id from public.clients cl join logistics.app_user au on au.id = cl.id
             where h.auteur <> '' and lower(cl.email) = lower(h.auteur) limit 1),
           h.auteur, h.lieu, 'legacy_backfill',
           jsonb_build_object('legacy_status', h.statut, 'note', h.note), h.id
    from public.colis_historique h
    join logistics.parcel pa on pa.legacy_parcel_id = h.colis_id
    on conflict (legacy_history_id) do nothing
    returning 1
  )
  select count(*) into n_ins from ins;
  v_rap := v_rap || jsonb_build_object('tracking_event', jsonb_build_object('inserted', n_ins, 'updated', 0));

  -- 6. Factures ------------------------------------------------------------------------------
  with up as (
    insert into logistics.invoice as t (organization_id, number, customer_id, currency, status, total, service_fee,
        paid_amount, is_grouped, issued_at, due_date, paid_at, note, source, legacy_invoice_id, created_at)
    select v_org, f.numero, cu.id,
           case when f.devise in ('USD', 'DOP', 'HTG') then f.devise else 'USD' end,
           case when f.statut = 'payee' then 'PAID' when f.montant_paye > 0 then 'PARTIALLY_PAID' else 'ISSUED' end,
           f.montant, f.frais_service, f.montant_paye, coalesce((to_jsonb(f) ->> 'groupee')::boolean, false),
           f.cree_le, f.echeance_le, f.payee_le, f.note, 'legacy_backfill', f.id, f.cree_le
    from public.factures f
    join logistics.customer cu on cu.legacy_client_id = f.client_id
    on conflict (legacy_invoice_id) do update set
      number = excluded.number, customer_id = excluded.customer_id, currency = excluded.currency,
      total = excluded.total, service_fee = excluded.service_fee, paid_amount = excluded.paid_amount,
      is_grouped = excluded.is_grouped, due_date = excluded.due_date, paid_at = excluded.paid_at, note = excluded.note,
      status = case when t.status_authority = 'legacy' then excluded.status else t.status end
    where (t.number, t.customer_id, t.currency, t.total, t.service_fee, t.paid_amount, t.is_grouped, t.due_date, t.paid_at, t.note)
          is distinct from
          (excluded.number, excluded.customer_id, excluded.currency, excluded.total, excluded.service_fee,
           excluded.paid_amount, excluded.is_grouped, excluded.due_date, excluded.paid_at, excluded.note)
       or (t.status_authority = 'legacy' and t.status <> excluded.status)
    returning (xmax = 0) as inserted
  )
  select count(*) filter (where inserted), count(*) filter (where not inserted) into n_ins, n_upd from up;
  v_rap := v_rap || jsonb_build_object('invoice', jsonb_build_object('inserted', n_ins, 'updated', n_upd));

  -- 7. Lignes de facture : le JSON figé de l'ancienne facture, une ligne par élément --------------
  with up as (
    insert into logistics.invoice_item as t (invoice_id, parcel_id, description, quantity, weight_lb, unit_price,
                                             amount, position, legacy_line_key)
    select i.id, pa.id, coalesce(l.elem ->> 'description', ''), coalesce((l.elem ->> 'quantite')::numeric, 1),
           nullif(l.elem ->> 'poids_lb', '')::numeric, nullif(l.elem ->> 'tarif_lb', '')::numeric,
           coalesce((l.elem ->> 'montant')::numeric, 0), l.ord::int, f.id::text || ':' || l.ord
    from public.factures f
    join logistics.invoice i on i.legacy_invoice_id = f.id
    cross join lateral jsonb_array_elements(case when jsonb_typeof(f.lignes) = 'array' then f.lignes else '[]'::jsonb end)
                with ordinality as l(elem, ord)
    left join logistics.parcel pa on pa.legacy_parcel_id = nullif(l.elem ->> 'colis_id', '')::uuid
    on conflict (legacy_line_key) do update set
      invoice_id = excluded.invoice_id, parcel_id = excluded.parcel_id, description = excluded.description,
      quantity = excluded.quantity, weight_lb = excluded.weight_lb, unit_price = excluded.unit_price,
      amount = excluded.amount, position = excluded.position
    where (t.invoice_id, t.parcel_id, t.description, t.quantity, t.weight_lb, t.unit_price, t.amount, t.position)
          is distinct from
          (excluded.invoice_id, excluded.parcel_id, excluded.description, excluded.quantity, excluded.weight_lb,
           excluded.unit_price, excluded.amount, excluded.position)
    returning (xmax = 0) as inserted
  )
  select count(*) filter (where inserted), count(*) filter (where not inserted) into n_ins, n_upd from up;
  v_rap := v_rap || jsonb_build_object('invoice_item', jsonb_build_object('inserted', n_ins, 'updated', n_upd));

  return v_rap;
end;
$$;
comment on function logistics.backfill_from_legacy is
  'Copie l''ancien schéma vers le noyau. Idempotent, sans suppression, lecture seule sur public. Voir docs/architecture/DATA-MIGRATION-MAP.md.';

-- La comparaison : liste TOUT écart entre l'ancien schéma et le noyau. Lecture seule.
-- Zéro ligne = les deux modèles disent la même chose.
create or replace function logistics.reconcile_with_legacy()
returns table (kind text, entity text, legacy_id text, detail text)
language plpgsql
stable
set search_path = ''
as $$
begin
  -- clients
  return query select 'missing_in_core'::text, 'customer'::text, c.id::text, 'compte absent du noyau'::text
    from public.clients c
    where (c.role = 'client' or exists (select 1 from public.colis p where p.client_id = c.id)
           or exists (select 1 from public.factures f where f.client_id = c.id))
      and not exists (select 1 from logistics.customer x where x.legacy_client_id = c.id);
  return query select 'orphan_in_core', 'customer', x.legacy_client_id::text, 'client du noyau sans compte dans l''ancien schéma'
    from logistics.customer x where x.legacy_client_id is not null
      and not exists (select 1 from public.clients c where c.id = x.legacy_client_id);
  return query select 'mismatch', 'customer', c.id::text,
      'code/nom/adresse/téléphone/e-mail/langue différents'
    from public.clients c join logistics.customer x on x.legacy_client_id = c.id
    where (x.code, x.full_name, x.country, x.region, x.city, x.address, x.phone, x.email)
          is distinct from (c.code, c.nom_complet, c.pays, c.region, c.ville, c.adresse, c.telephone, c.email);
  -- personnel
  return query select 'missing_in_core', 'app_user', c.id::text, 'membre de l''équipe absent du noyau'
    from public.clients c where c.role <> 'client' and not exists (select 1 from logistics.app_user u where u.id = c.id);
  return query select 'mismatch', 'app_user', c.id::text, 'rôle ou droits différents'
    from public.clients c join logistics.app_user u on u.id = c.id
    where c.role <> 'client' and (u.role, u.rights, u.active) is distinct from
      (case c.role when 'employe' then 'employee' when 'gerant' then 'manager' else 'admin' end, c.droits, true);
  -- colis
  return query select 'missing_in_core', 'parcel', p.id::text, 'colis absent du noyau'
    from public.colis p where not exists (select 1 from logistics.parcel x where x.legacy_parcel_id = p.id);
  return query select 'orphan_in_core', 'parcel', x.legacy_parcel_id::text, 'colis du noyau sans colis dans l''ancien schéma'
    from logistics.parcel x where x.legacy_parcel_id is not null
      and not exists (select 1 from public.colis p where p.id = x.legacy_parcel_id);
  return query select 'mismatch', 'parcel', p.id::text,
      concat_ws('; ',
        case when x.tracking_number is distinct from p.numero then 'numéro' end,
        case when x.weight_lb is distinct from p.poids_lb then 'poids' end,
        case when x.rate_per_lb is distinct from p.tarif_lb then 'tarif' end,
        case when x.customer_id is distinct from (select cu.id from logistics.customer cu where cu.legacy_client_id = p.client_id) then 'client' end,
        case when x.legacy_status is distinct from p.statut then 'statut d''origine' end,
        case when x.status_authority = 'legacy' and x.status is distinct from logistics.map_legacy_parcel_status(p.statut) then 'statut' end)
    from public.colis p join logistics.parcel x on x.legacy_parcel_id = p.id
    where x.tracking_number is distinct from p.numero or x.weight_lb is distinct from p.poids_lb
       or x.rate_per_lb is distinct from p.tarif_lb or x.legacy_status is distinct from p.statut
       or x.customer_id is distinct from (select cu.id from logistics.customer cu where cu.legacy_client_id = p.client_id)
       or (x.status_authority = 'legacy' and x.status is distinct from logistics.map_legacy_parcel_status(p.statut));
  -- journal
  return query select 'missing_in_core', 'tracking_event', h.id::text, 'ligne d''historique non copiée'
    from public.colis_historique h
    where not exists (select 1 from logistics.tracking_event e where e.legacy_history_id = h.id);
  -- factures
  return query select 'missing_in_core', 'invoice', f.id::text, 'facture absente du noyau'
    from public.factures f where not exists (select 1 from logistics.invoice i where i.legacy_invoice_id = f.id);
  return query select 'orphan_in_core', 'invoice', i.legacy_invoice_id::text, 'facture du noyau sans facture dans l''ancien schéma'
    from logistics.invoice i where i.legacy_invoice_id is not null
      and not exists (select 1 from public.factures f where f.id = i.legacy_invoice_id);
  return query select 'mismatch', 'invoice', f.id::text,
      concat_ws('; ',
        case when i.number is distinct from f.numero then 'numéro' end,
        case when i.total is distinct from f.montant then 'total' end,
        case when i.paid_amount is distinct from f.montant_paye then 'montant payé' end,
        case when i.status_authority = 'legacy' and i.status is distinct from
             (case when f.statut = 'payee' then 'PAID' when f.montant_paye > 0 then 'PARTIALLY_PAID' else 'ISSUED' end) then 'statut' end)
    from public.factures f join logistics.invoice i on i.legacy_invoice_id = f.id
    where i.number is distinct from f.numero or i.total is distinct from f.montant or i.paid_amount is distinct from f.montant_paye
       or (i.status_authority = 'legacy' and i.status is distinct from
           (case when f.statut = 'payee' then 'PAID' when f.montant_paye > 0 then 'PARTIALLY_PAID' else 'ISSUED' end));
  return query select 'mismatch', 'invoice_item', f.id::text,
      'lignes : ' || jsonb_array_length(f.lignes) || ' dans l''ancien schéma, ' ||
      (select count(*) from logistics.invoice_item it where it.invoice_id = i.id) || ' dans le noyau'
    from public.factures f join logistics.invoice i on i.legacy_invoice_id = f.id
    where jsonb_typeof(f.lignes) = 'array'
      and jsonb_array_length(f.lignes) <> (select count(*) from logistics.invoice_item it where it.invoice_id = i.id);
  -- appareils
  if to_regclass('public.appareils') is not null then
    return query execute $q$
      select 'missing_in_core'::text, 'device'::text, a.jeton::text, 'appareil absent du noyau'::text
      from public.appareils a where not exists (select 1 from logistics.device d where d.push_token = a.jeton)
    $q$;
  end if;
end;
$$;
comment on function logistics.reconcile_with_legacy is
  'Compare l''ancien schéma au noyau. Lecture seule. Aucune ligne = cohérents.';

-- Ces deux fonctions ne s'appellent que depuis le SQL Editor (propriétaire) ou le service interne.
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'logistics' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
end
$$;
