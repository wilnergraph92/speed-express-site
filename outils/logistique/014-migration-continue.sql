-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 14 : la migration continue
-- -----------------------------------------------------------------------------
-- Phase 2 (« activer le noyau »). À coller dans Supabase > SQL Editor APRÈS 013,
-- d'abord en PRÉPRODUCTION, puis en production après une sauvegarde « avant
-- migration » vérifiée. Vérifiez en haut de la page que le projet est bien
-- « speed-express-site » (ou la préproduction).
--
-- Ce que cette étape ajoute — et rien d'autre : aucune donnée n'est copiée en la
-- collant, aucune lecture n'est basculée vers le noyau, l'ancien schéma n'est
-- jamais modifié (seuls six déclencheurs y sont posés, muets tant que la double
-- écriture est éteinte) :
--
--   1. la dernière entité du modèle cible qui manquait : revenue (le journal des
--      revenus ; pickup_task, delivery_task et customer_balance existent depuis 006 et 007) ;
--   2. ce que l'ancien schéma a gagné le 7 octobre et que le noyau ne portait pas :
--      prix saisi à la main et devise du colis, identifiant d'équipe (ADM-/GER-/EMP-),
--      pré-alertes ; plus un marqueur « supprimé dans l'ancien schéma » (on marque,
--      on n'efface jamais) ;
--   3. le RAPPORT de migration : compteurs, EMPREINTES (sommes de contrôle) des deux
--      côtés, écarts classés « expliqués » ou « inexpliqués », verdict « prêt » ;
--   4. l'EXÉCUTION tracée : chaque rattrapage est journalisé (durée, rapport, erreur),
--      retenté sur les erreurs passagères, rejouable sans effet (idempotent) ;
--   5. la DOUBLE ÉCRITURE (étape 3 de MIGRATION-STRATEGY.md), ÉTEINTE à l'installation :
--      allumée, chaque écriture de l'ancien schéma dépose une ligne dans une file ;
--      process_sync_queue() la traite par le MÊME rattrapage (aucune seconde copie
--      de la correspondance, donc aucune dérive possible), avec nouvelles tentatives
--      et file des échecs. Une écriture de l'ancien schéma ne peut JAMAIS échouer
--      à cause du noyau : le déclencheur avale toute erreur et la consigne.
--
-- Lecture du noyau par les interfaces : NON (interrupteurs de config.js éteints).
-- Rejouable sans risque. Retour arrière : MIGRATION-REPORT.md §8.
-- =============================================================================

-- 1. La dernière entité du modèle cible ------------------------------------------------------------------------
-- Les autres existent déjà : pickup_task et delivery_task (vues typées de « task », étape 6), customer_balance (étape 7).
-- Le journal des revenus s'appelle revenue_entry (une ligne par fait comptable, en ajout seul) ; « revenue » le nomme
-- comme le modèle cible, sans le dupliquer.
create or replace view logistics.revenue with (security_invoker = true) as
  select * from logistics.revenue_entry;


-- 2. Ce que le noyau ne portait pas encore ----------------------------------------------------------------------
alter table logistics.parcel add column if not exists manual_price numeric(12, 2) check (manual_price is null or manual_price >= 0);
alter table logistics.parcel add column if not exists currency text not null default 'USD' check (currency in ('USD', 'DOP', 'HTG'));
comment on column logistics.parcel.manual_price is 'Prix total saisi à la main (forfait, geste commercial) ; vide = poids × tarif. Copié de colis.prix_manuel.';
comment on column logistics.parcel.currency is 'Devise du tarif, du prix saisi et de la valeur déclarée. L''ancien schéma ne la porte pas : USD, celle du site.';

alter table logistics.app_user add column if not exists staff_code text;
create unique index if not exists app_user_staff_code_idx on logistics.app_user (staff_code) where staff_code is not null;
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'app_user_staff_code_format') then
    alter table logistics.app_user add constraint app_user_staff_code_format
      check (staff_code is null or staff_code ~ '^(ADM|GER|EMP)-[1-9][0-9]{3}$');
  end if;
end
$$;
comment on column logistics.app_user.staff_code is 'Identifiant d''équipe donné par l''ancien schéma (clients.matricule) ; le registre reste public.matricules_attribues.';

-- On ne supprime jamais une ligne du noyau parce qu'elle a disparu de l'ancien schéma : on le note.
alter table logistics.customer add column if not exists legacy_deleted_at timestamptz;
alter table logistics.parcel   add column if not exists legacy_deleted_at timestamptz;
alter table logistics.invoice  add column if not exists legacy_deleted_at timestamptz;
alter table logistics.device   add column if not exists legacy_deleted_at timestamptz;

-- Les pré-alertes : un achat annoncé par le client avant qu'il n'arrive à l'entrepôt.
create table if not exists logistics.pre_alert (
  id                  uuid primary key default gen_random_uuid(),
  organization_id     uuid not null references logistics.organization (id) on delete restrict,
  customer_id         uuid not null references logistics.customer (id) on delete restrict,
  merchant            text not null check (length(btrim(merchant)) between 1 and 80),
  content             text not null check (length(btrim(content)) between 1 and 200),
  merchant_tracking   text not null default '' check (length(merchant_tracking) <= 60),
  declared_value      numeric(12, 2) check (declared_value is null or declared_value >= 0),
  currency            text not null default 'USD' check (currency in ('USD', 'DOP', 'HTG')),
  service_mode        text not null check (service_mode in ('air', 'sea')),
  status              text not null check (status in ('EXPECTED', 'RECEIVED', 'CANCELLED')),
  parcel_id           uuid references logistics.parcel (id) on delete restrict,
  note                text not null default '',
  source              text not null default 'native' check (source in ('native', 'legacy_backfill')),
  legacy_pre_alert_id uuid unique,
  legacy_deleted_at   timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
create index if not exists pre_alert_customer_idx on logistics.pre_alert (customer_id, created_at desc);
drop trigger if exists touch_updated_at on logistics.pre_alert;
create trigger touch_updated_at before update on logistics.pre_alert for each row execute function logistics.touch_updated_at();
alter table logistics.pre_alert enable row level security;


-- 3. Les réglages et journaux de la migration -------------------------------------------------------------------
create table if not exists logistics.migration_setting (
  key        text primary key check (key in ('double_write')),
  value      jsonb not null,
  updated_at timestamptz not null default now(),
  updated_by text not null default current_user
);
insert into logistics.migration_setting (key, value) values ('double_write', 'false'::jsonb) on conflict (key) do nothing;

-- Chaque exécution du rattrapage, réussie ou non : une ligne, jamais réécrite.
create table if not exists logistics.migration_run (
  id          bigint generated always as identity primary key,
  started_at  timestamptz not null,
  finished_at timestamptz not null default clock_timestamp(),
  reason      text not null,
  status      text not null check (status in ('ok', 'failed')),
  attempts    int not null check (attempts >= 1),
  counters    jsonb not null default '{}'::jsonb,
  ready       boolean,
  unexplained int,
  error       text
);
drop trigger if exists migration_run_append_only on logistics.migration_run;
create trigger migration_run_append_only before update or delete on logistics.migration_run
  for each row execute function logistics.forbid_mutation();

-- Un écart connu, examiné et accepté par le propriétaire (par exemple une donnée ancienne invalide). Il cesse de compter
-- comme « inexpliqué » ; il reste visible dans le rapport, avec sa raison. Jamais réécrit, jamais effacé.
create table if not exists logistics.migration_explanation (
  kind        text not null check (kind in ('missing_in_core', 'orphan_in_core', 'mismatch')),
  entity      text not null,
  legacy_id   text not null,
  reason      text not null check (length(btrim(reason)) >= 10),
  explained_by text not null default current_user,
  explained_at timestamptz not null default now(),
  primary key (kind, entity, legacy_id)
);
drop trigger if exists migration_explanation_append_only on logistics.migration_explanation;
create trigger migration_explanation_append_only before update or delete on logistics.migration_explanation
  for each row execute function logistics.forbid_mutation();

-- La file de la double écriture : (table, identifiant, opération), déposée par l'ancien schéma, traitée par le noyau.
create table if not exists logistics.sync_queue (
  id           bigint generated always as identity primary key,
  table_name   text not null check (table_name in ('clients', 'colis', 'colis_historique', 'factures', 'appareils', 'prealertes')),
  legacy_id    text not null,
  operation    text not null check (operation in ('INSERT', 'UPDATE', 'DELETE')),
  enqueued_at  timestamptz not null default clock_timestamp(),
  status       text not null default 'pending' check (status in ('pending', 'done', 'dead')),
  attempts     int not null default 0,
  next_try_at  timestamptz not null default clock_timestamp(),
  processed_at timestamptz,
  last_error   text
);
create index if not exists sync_queue_pending_idx on logistics.sync_queue (next_try_at) where status = 'pending';

-- Ce que le déclencheur n'a pas pu déposer (jamais vu en essai : c'est le filet du filet). Une ligne ici n'a bloqué
-- AUCUNE écriture de l'ancien schéma ; le prochain rattrapage complet la rattrape de toute façon.
create table if not exists logistics.sync_failure (
  id          bigint generated always as identity primary key,
  occurred_at timestamptz not null default clock_timestamp(),
  table_name  text not null,
  legacy_id   text,
  operation   text not null,
  error       text not null
);

-- Tout ce schéma reste fermé : seuls le propriétaire (SQL Editor) et le service interne y accèdent.
do $$
declare t text;
begin
  foreach t in array array['pre_alert', 'migration_setting', 'migration_run', 'migration_explanation', 'sync_queue', 'sync_failure'] loop
    execute format('revoke all on logistics.%I from public, anon, authenticated', t);
    -- Sécurité par ligne sans aucune règle : même un droit accordé par erreur ne laisserait rien lire. Le propriétaire et
    -- les fonctions du noyau (qui s'exécutent avec ses droits) n'y sont pas soumis.
    execute format('alter table logistics.%I enable row level security', t);
  end loop;
end
$$;
revoke all on logistics.revenue from public, anon, authenticated;


-- 4. Le rattrapage des compléments (même garanties que backfill_from_legacy : lecture seule sur public, idempotent,
--    sans suppression, sans invention) ------------------------------------------------------------------------------
create or replace function logistics.backfill_complements()
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

  -- Prix saisi (colonne présente depuis le 7 octobre ; absente = rien à copier).
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'colis' and column_name = 'prix_manuel') then
    execute $q$
      with up as (
        update logistics.parcel x set manual_price = p.prix_manuel
          from public.colis p
         where x.legacy_parcel_id = p.id and x.manual_price is distinct from p.prix_manuel
        returning 1
      ) select count(*) from up $q$ into n_upd;
  else
    n_upd := 0;
  end if;
  v_rap := v_rap || jsonb_build_object('parcel_manual_price', jsonb_build_object('inserted', 0, 'updated', n_upd));

  -- Identifiant d'équipe.
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'clients' and column_name = 'matricule') then
    execute $q$
      with up as (
        update logistics.app_user u set staff_code = c.matricule
          from public.clients c
         where u.id = c.id and u.staff_code is distinct from c.matricule
        returning 1
      ) select count(*) from up $q$ into n_upd;
  else
    n_upd := 0;
  end if;
  v_rap := v_rap || jsonb_build_object('app_user_staff_code', jsonb_build_object('inserted', 0, 'updated', n_upd));

  -- Pré-alertes.
  if to_regclass('public.prealertes') is not null then
    execute $q$
      with up as (
        insert into logistics.pre_alert as t (organization_id, customer_id, merchant, content, merchant_tracking, declared_value,
                                              service_mode, status, parcel_id, note, source, legacy_pre_alert_id, created_at)
        select $1, cu.id, a.magasin, a.contenu, a.numero_suivi, a.valeur,
               case a.service when 'maritime' then 'sea' else 'air' end,
               case a.statut when 'recue' then 'RECEIVED' when 'annulee' then 'CANCELLED' else 'EXPECTED' end,
               pa.id, a.note, 'legacy_backfill', a.id, a.cree_le
          from public.prealertes a
          join logistics.customer cu on cu.legacy_client_id = a.client_id
          left join logistics.parcel pa on pa.legacy_parcel_id = a.colis_id
        on conflict (legacy_pre_alert_id) do update set
          customer_id = excluded.customer_id, merchant = excluded.merchant, content = excluded.content,
          merchant_tracking = excluded.merchant_tracking, declared_value = excluded.declared_value,
          service_mode = excluded.service_mode, status = excluded.status, parcel_id = excluded.parcel_id, note = excluded.note
        where (t.customer_id, t.merchant, t.content, t.merchant_tracking, t.declared_value, t.service_mode, t.status, t.parcel_id, t.note)
              is distinct from
              (excluded.customer_id, excluded.merchant, excluded.content, excluded.merchant_tracking, excluded.declared_value,
               excluded.service_mode, excluded.status, excluded.parcel_id, excluded.note)
        returning (xmax = 0) as inserted
      ) select count(*) filter (where inserted), count(*) filter (where not inserted) from up $q$ into n_ins, n_upd using v_org;
  else
    n_ins := 0; n_upd := 0;
  end if;
  v_rap := v_rap || jsonb_build_object('pre_alert', jsonb_build_object('inserted', n_ins, 'updated', n_upd));

  -- Ce qui a disparu de l'ancien schéma : marqué, jamais effacé. (Une facture remplacée par une facture groupée, par
  -- exemple, est retirée de l'ancien schéma par le tableau de bord : le noyau en garde la trace.)
  with m as (
    update logistics.parcel x set legacy_deleted_at = now()
     where x.legacy_parcel_id is not null and x.legacy_deleted_at is null
       and not exists (select 1 from public.colis p where p.id = x.legacy_parcel_id)
    returning 1
  ) select count(*) into n_upd from m;
  v_rap := v_rap || jsonb_build_object('parcel_legacy_deleted', jsonb_build_object('inserted', 0, 'updated', n_upd));
  with m as (
    update logistics.invoice x set legacy_deleted_at = now()
     where x.legacy_invoice_id is not null and x.legacy_deleted_at is null
       and not exists (select 1 from public.factures f where f.id = x.legacy_invoice_id)
    returning 1
  ) select count(*) into n_upd from m;
  v_rap := v_rap || jsonb_build_object('invoice_legacy_deleted', jsonb_build_object('inserted', 0, 'updated', n_upd));
  with m as (
    update logistics.customer x set legacy_deleted_at = now()
     where x.legacy_client_id is not null and x.legacy_deleted_at is null
       and not exists (select 1 from public.clients c where c.id = x.legacy_client_id)
    returning 1
  ) select count(*) into n_upd from m;
  v_rap := v_rap || jsonb_build_object('customer_legacy_deleted', jsonb_build_object('inserted', 0, 'updated', n_upd));
  if to_regclass('public.appareils') is not null then
    execute $q$
      with m as (
        update logistics.device d set legacy_deleted_at = now(), active = false
         where d.source = 'legacy_backfill' and d.legacy_deleted_at is null
           and not exists (select 1 from public.appareils a where a.jeton = d.push_token)
        returning 1
      ) select count(*) from m $q$ into n_upd;
  else
    n_upd := 0;
  end if;
  v_rap := v_rap || jsonb_build_object('device_legacy_deleted', jsonb_build_object('inserted', 0, 'updated', n_upd));
  if to_regclass('public.prealertes') is not null then
    execute $q$
      with m as (
        update logistics.pre_alert x set legacy_deleted_at = now()
         where x.legacy_pre_alert_id is not null and x.legacy_deleted_at is null
           and not exists (select 1 from public.prealertes a where a.id = x.legacy_pre_alert_id)
        returning 1
      ) select count(*) from m $q$ into n_upd;
  else
    n_upd := 0;
  end if;
  v_rap := v_rap || jsonb_build_object('pre_alert_legacy_deleted', jsonb_build_object('inserted', 0, 'updated', n_upd));
  return v_rap;
end;
$$;

-- La comparaison des compléments : même forme que reconcile_with_legacy().
create or replace function logistics.reconcile_complements()
returns table (kind text, entity text, legacy_id text, detail text)
language plpgsql
stable
set search_path = ''
as $$
begin
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'colis' and column_name = 'prix_manuel') then
    return query execute $q$
      select 'mismatch'::text, 'parcel'::text, p.id::text, 'prix saisi différent'::text
        from public.colis p join logistics.parcel x on x.legacy_parcel_id = p.id
       where x.manual_price is distinct from p.prix_manuel $q$;
  end if;
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'clients' and column_name = 'matricule') then
    return query execute $q$
      select 'mismatch'::text, 'app_user'::text, c.id::text, 'identifiant d''équipe différent'::text
        from public.clients c join logistics.app_user u on u.id = c.id
       where u.staff_code is distinct from c.matricule $q$;
  end if;
  if to_regclass('public.prealertes') is not null then
    return query execute $q$
      select 'missing_in_core'::text, 'pre_alert'::text, a.id::text, 'pré-alerte absente du noyau'::text
        from public.prealertes a where not exists (select 1 from logistics.pre_alert x where x.legacy_pre_alert_id = a.id)
      union all
      select 'orphan_in_core', 'pre_alert', x.legacy_pre_alert_id::text, 'pré-alerte du noyau sans pré-alerte dans l''ancien schéma'
        from logistics.pre_alert x where x.legacy_pre_alert_id is not null
         and not exists (select 1 from public.prealertes a where a.id = x.legacy_pre_alert_id)
      union all
      select 'mismatch', 'pre_alert', a.id::text, 'statut, colis relié ou note différents'
        from public.prealertes a join logistics.pre_alert x on x.legacy_pre_alert_id = a.id
       where (x.status, x.parcel_id, x.note) is distinct from
             (case a.statut when 'recue' then 'RECEIVED' when 'annulee' then 'CANCELLED' else 'EXPECTED' end,
              (select pa.id from logistics.parcel pa where pa.legacy_parcel_id = a.colis_id), a.note) $q$;
  end if;
end;
$$;


-- 5. Les écarts, classés --------------------------------------------------------------------------------------
-- Un écart est EXPLIQUÉ quand une raison connue le justifie :
--   · legacy_deleted : la ligne a disparu de l'ancien schéma, le noyau en garde la trace (marquée, jamais effacée) ;
--   · owner_reviewed : le propriétaire l'a examiné et consigné dans migration_explanation (raison écrite).
-- Tout le reste est INEXPLIQUÉ : la migration n'est pas prête tant qu'il en reste un.
create or replace function logistics.migration_differences()
returns table (kind text, entity text, legacy_id text, detail text, explained boolean, reason text)
language sql
stable
set search_path = ''
as $$
  with brut as (
    select * from logistics.reconcile_with_legacy()
    union all
    select * from logistics.reconcile_complements()
  )
  select b.kind, b.entity, b.legacy_id, b.detail,
         (sup.legacy_id is not null or e.legacy_id is not null) as explained,
         case when sup.legacy_id is not null then 'legacy_deleted'
              when e.legacy_id is not null then 'owner_reviewed: ' || e.reason end as reason
    from brut b
    left join lateral (
      select b.legacy_id where b.kind = 'orphan_in_core' and (
           (b.entity = 'parcel'    and exists (select 1 from logistics.parcel x    where x.legacy_parcel_id::text = b.legacy_id    and x.legacy_deleted_at is not null))
        or (b.entity = 'invoice'   and exists (select 1 from logistics.invoice x   where x.legacy_invoice_id::text = b.legacy_id   and x.legacy_deleted_at is not null))
        or (b.entity = 'customer'  and exists (select 1 from logistics.customer x  where x.legacy_client_id::text = b.legacy_id    and x.legacy_deleted_at is not null))
        or (b.entity = 'pre_alert' and exists (select 1 from logistics.pre_alert x where x.legacy_pre_alert_id::text = b.legacy_id and x.legacy_deleted_at is not null)))
    ) sup on true
    left join logistics.migration_explanation e on e.kind = b.kind and e.entity = b.entity and e.legacy_id = b.legacy_id
$$;


-- 6. Les empreintes : la même donnée, lue des deux côtés, dans le même ordre, réduite à une somme ---------------------
-- Une empreinte égale prouve que chaque champ comparé de chaque ligne est identique ; elle porte sur les lignes encore
-- présentes dans l'ancien schéma (les lignes marquées « supprimées » sont comptées à part).
create or replace function logistics.migration_checksums()
returns table (entity text, legacy_count bigint, core_count bigint, core_legacy_deleted bigint, legacy_checksum text, core_checksum text, equal boolean)
language plpgsql
stable
set search_path = ''
as $$
begin
  -- array_to_string(…, '|', '∅') : une valeur vide reste à sa place (concat_ws la sauterait, et deux lignes différentes
  -- pourraient alors donner la même empreinte).
  return query
  with clients_concernes as (
    select c.* from public.clients c
     where c.role = 'client' or exists (select 1 from public.colis p where p.client_id = c.id)
        or exists (select 1 from public.factures f where f.client_id = c.id)
  ), l as (
    select 'customer'::text e, count(*) n, md5(coalesce(string_agg(array_to_string(array[c.id::text, c.code, c.nom_complet, c.pays, c.region,
             c.ville, c.adresse, c.telephone, c.email], '|', '∅'), E'\n' order by c.id), '')) h
      from clients_concernes c
    union all
    select 'parcel', count(*), md5(coalesce(string_agg(array_to_string(array[p.id::text, p.numero, p.jeton, p.client_id::text, p.poids_lb::text,
             p.tarif_lb::text, p.statut, p.pays_destination, p.ville_destination, p.valeur_declaree::text, to_jsonb(p) ->> 'prix_manuel'], '|', '∅'),
             E'\n' order by p.id), ''))
      from public.colis p
    union all
    select 'tracking_event', count(*), md5(coalesce(string_agg(array_to_string(array[h.id::text, h.colis_id::text, h.statut, h.cree_le::text], '|', '∅'),
             E'\n' order by h.id), ''))
      from public.colis_historique h
    union all
    select 'invoice', count(*), md5(coalesce(string_agg(array_to_string(array[f.id::text, f.numero, f.client_id::text, f.montant::text,
             f.frais_service::text, f.montant_paye::text, case when f.devise in ('USD', 'DOP', 'HTG') then f.devise else 'USD' end], '|', '∅'),
             E'\n' order by f.id), ''))
      from public.factures f
    union all
    select 'app_user', count(*), md5(coalesce(string_agg(array_to_string(array[c.id::text,
             case c.role when 'employe' then 'employee' when 'gerant' then 'manager' else 'admin' end, c.droits::text,
             to_jsonb(c) ->> 'matricule'], '|', '∅'), E'\n' order by c.id), ''))
      from public.clients c where c.role <> 'client'
  ), k as (
    select 'customer'::text e, count(*) n,
           (select count(*) from logistics.customer z where z.legacy_deleted_at is not null) d,
           md5(coalesce(string_agg(array_to_string(array[x.legacy_client_id::text, x.code, x.full_name, x.country, x.region, x.city, x.address,
             x.phone, x.email], '|', '∅'), E'\n' order by x.legacy_client_id), '')) h
      from logistics.customer x join clients_concernes c on c.id = x.legacy_client_id
    union all
    select 'parcel', count(*), count(*) filter (where x.legacy_deleted_at is not null),
           md5(coalesce(string_agg(array_to_string(array[x.legacy_parcel_id::text, x.tracking_number, x.public_token,
             (select cu.legacy_client_id::text from logistics.customer cu where cu.id = x.customer_id), x.weight_lb::text, x.rate_per_lb::text,
             x.legacy_status, x.destination_country, x.destination_city, x.declared_value::text, x.manual_price::text], '|', '∅'),
             E'\n' order by x.legacy_parcel_id) filter (where x.legacy_deleted_at is null), ''))
      from logistics.parcel x where x.legacy_parcel_id is not null
    union all
    select 'tracking_event', count(*), 0::bigint,
           md5(coalesce(string_agg(array_to_string(array[t.legacy_history_id::text, pa.legacy_parcel_id::text, t.metadata ->> 'legacy_status',
             t.occurred_at::text], '|', '∅'), E'\n' order by t.legacy_history_id)
             filter (where exists (select 1 from public.colis_historique h where h.id = t.legacy_history_id)), ''))
      from logistics.tracking_event t join logistics.parcel pa on pa.id = t.parcel_id where t.legacy_history_id is not null
    union all
    select 'invoice', count(*), count(*) filter (where x.legacy_deleted_at is not null),
           md5(coalesce(string_agg(array_to_string(array[x.legacy_invoice_id::text, x.number,
             (select cu.legacy_client_id::text from logistics.customer cu where cu.id = x.customer_id), x.total::text, x.service_fee::text,
             x.paid_amount::text, x.currency], '|', '∅'), E'\n' order by x.legacy_invoice_id) filter (where x.legacy_deleted_at is null), ''))
      from logistics.invoice x where x.legacy_invoice_id is not null
    union all
    select 'app_user', count(*), count(*) filter (where not u.active),
           md5(coalesce(string_agg(array_to_string(array[u.id::text, u.role, u.rights::text, u.staff_code], '|', '∅'), E'\n' order by u.id)
             filter (where u.active), ''))
      from logistics.app_user u
  )
  select l.e, l.n, k.n, k.d, l.h, k.h, l.h = k.h from l join k using (e);
  -- Pré-alertes et appareils : tables plus récentes, lues seulement si elles existent.
  if to_regclass('public.prealertes') is not null then
    return query execute $q$
      select e, ln, kn, kd, lh, kh, lh = kh from (select 'pre_alert'::text,
             (select count(*) from public.prealertes),
             (select count(*) from logistics.pre_alert where legacy_pre_alert_id is not null),
             (select count(*) from logistics.pre_alert where legacy_deleted_at is not null),
             (select md5(coalesce(string_agg(array_to_string(array[a.id::text, a.client_id::text, a.magasin, a.contenu, a.numero_suivi,
                a.valeur::text, a.service, a.statut, a.colis_id::text, a.note], '|', '∅'), E'\n' order by a.id), '')) from public.prealertes a),
             (select md5(coalesce(string_agg(array_to_string(array[x.legacy_pre_alert_id::text, cu.legacy_client_id::text, x.merchant, x.content,
                x.merchant_tracking, x.declared_value::text, case x.service_mode when 'sea' then 'maritime' else 'aerien' end,
                case x.status when 'RECEIVED' then 'recue' when 'CANCELLED' then 'annulee' else 'attendue' end,
                pa.legacy_parcel_id::text, x.note], '|', '∅'), E'\n' order by x.legacy_pre_alert_id), ''))
                from logistics.pre_alert x join logistics.customer cu on cu.id = x.customer_id
                left join logistics.parcel pa on pa.id = x.parcel_id
               where x.legacy_pre_alert_id is not null and x.legacy_deleted_at is null)
      ) s (e, ln, kn, kd, lh, kh)
    $q$;
  end if;
  if to_regclass('public.appareils') is not null then
    return query execute $q$
      select e, ln, kn, kd, lh, kh, lh = kh from (select 'device'::text,
             (select count(*) from public.appareils),
             (select count(*) from logistics.device where source = 'legacy_backfill'),
             (select count(*) from logistics.device where source = 'legacy_backfill' and legacy_deleted_at is not null),
             (select md5(coalesce(string_agg(array_to_string(array[a.jeton, a.client_id::text, a.plateforme], '|', '∅'), E'\n' order by a.jeton), ''))
                from public.appareils a),
             (select md5(coalesce(string_agg(array_to_string(array[d.push_token, coalesce(cu.legacy_client_id, d.owner_user_id)::text, d.platform], '|', '∅'),
                E'\n' order by d.push_token), ''))
                from logistics.device d left join logistics.customer cu on cu.id = d.owner_customer_id
               where d.source = 'legacy_backfill' and d.legacy_deleted_at is null)
      ) s (e, ln, kn, kd, lh, kh)
    $q$;
  end if;
end;
$$;


-- 7. Le rapport -------------------------------------------------------------------------------------------------
create or replace function logistics.migration_report()
returns jsonb
language sql
stable
set search_path = ''
as $$
  with d as (select * from logistics.migration_differences()),
       c as (select * from logistics.migration_checksums())
  , empreintes_inexpliquees as (
    -- Une empreinte différente sans aucun écart expliqué pour cette entité : un angle mort de la comparaison ligne à
    -- ligne. Elle bloque le verdict « prêt » comme un écart inexpliqué.
    select c.entity from c where not c.equal and not exists (select 1 from d where d.entity = c.entity and d.explained)
  )
  select jsonb_build_object(
    'generated_at', now(),
    'ready', (select count(*) from d where not explained) = 0 and not exists (select 1 from empreintes_inexpliquees),
    'checksum_unexplained', coalesce((select jsonb_agg(entity order by entity) from empreintes_inexpliquees), '[]'::jsonb),
    'unexplained', (select count(*) from d where not explained),
    'explained', (select count(*) from d where explained),
    'unexplained_by_entity', coalesce((select jsonb_object_agg(k, n) from (select kind || '/' || entity k, count(*) n from d where not explained group by 1) s), '{}'::jsonb),
    'explained_by_reason', coalesce((select jsonb_object_agg(r, n) from (select split_part(reason, ':', 1) r, count(*) n from d where explained group by 1) s), '{}'::jsonb),
    'checksums', coalesce((select jsonb_object_agg(entity, jsonb_build_object('legacy', legacy_count, 'core', core_count,
                                                   'core_legacy_deleted', core_legacy_deleted, 'equal', equal)) from c), '{}'::jsonb),
    'double_write', (select value from logistics.migration_setting where key = 'double_write'),
    'sync_queue', jsonb_build_object(
        'pending', (select count(*) from logistics.sync_queue where status = 'pending'),
        'dead', (select count(*) from logistics.sync_queue where status = 'dead'),
        'oldest_pending_minutes', (select round(extract(epoch from now() - min(enqueued_at)) / 60) from logistics.sync_queue where status = 'pending'),
        'trigger_failures', (select count(*) from logistics.sync_failure)),
    'last_run', (select jsonb_build_object('at', finished_at, 'status', status, 'reason', reason, 'attempts', attempts, 'error', error)
                   from logistics.migration_run order by id desc limit 1)
  )
$$;


-- 8. L'exécution tracée, avec nouvelles tentatives --------------------------------------------------------------
-- Le rattrapage complet (ancien schéma + compléments), dans une sous-transaction : s'il échoue, rien n'est conservé de
-- lui, mais l'échec, lui, est journalisé. Les erreurs PASSAGÈRES (conflit de verrou, sérialisation, délai) sont
-- retentées jusqu'à trois fois ; les autres sont rendues aussitôt, avec leur message.
create or replace function logistics.run_migration(p_reason text default 'manual')
returns jsonb
language plpgsql
volatile
set search_path = ''
as $$
declare
  v_debut timestamptz := clock_timestamp();
  v_essai int := 0;
  v_compteurs jsonb;
  v_erreur text;
  v_etat text;
  v_rapport jsonb;
begin
  loop
    v_essai := v_essai + 1;
    begin
      v_compteurs := logistics.backfill_from_legacy() || logistics.backfill_complements();
      v_etat := 'ok';
      v_erreur := null;
      exit;
    exception
      when serialization_failure or deadlock_detected or lock_not_available or query_canceled then
        v_erreur := sqlstate || ' ' || sqlerrm;
        v_etat := 'failed';
        if v_essai >= 3 then exit; end if;
        perform pg_sleep(0.2 * v_essai);
      when others then
        v_erreur := sqlstate || ' ' || sqlerrm;
        v_etat := 'failed';
        exit;
    end;
  end loop;
  v_rapport := logistics.migration_report();
  insert into logistics.migration_run (started_at, reason, status, attempts, counters, ready, unexplained, error)
  values (v_debut, coalesce(nullif(btrim(p_reason), ''), 'manual'), v_etat, v_essai, coalesce(v_compteurs, '{}'::jsonb),
          (v_rapport ->> 'ready')::boolean, (v_rapport ->> 'unexplained')::int, v_erreur);
  return jsonb_build_object('status', v_etat, 'attempts', v_essai, 'error', v_erreur, 'counters', coalesce(v_compteurs, '{}'::jsonb))
         || jsonb_build_object('report', v_rapport);
end;
$$;

-- Consigner un écart examiné (propriétaire, SQL Editor). La raison est obligatoire et reste visible dans le rapport.
create or replace function logistics.explain_difference(p_kind text, p_entity text, p_legacy_id text, p_reason text)
returns void
language sql
volatile
set search_path = ''
as $$
  insert into logistics.migration_explanation (kind, entity, legacy_id, reason) values (p_kind, p_entity, p_legacy_id, p_reason)
$$;


-- 9. La double écriture -------------------------------------------------------------------------------------------
-- Le déclencheur posé sur l'ancien schéma : s'il est éteint, il ne fait rien ; allumé, il dépose (table, id, opération)
-- dans la file. Il ne lit ni n'écrit le noyau lui-même : rien de ce que fait le noyau ne peut faire échouer une
-- écriture du site. Même son dépôt est protégé : une erreur est consignée dans sync_failure, jamais propagée.
create or replace function logistics.enqueue_legacy_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_id text;
begin
  begin
    if coalesce((select value from logistics.migration_setting where key = 'double_write'), 'false'::jsonb) <> 'true'::jsonb then
      return null;
    end if;
    -- L'identifiant de la ligne ; « appareils » n'a pas de colonne id : son jeton en tient lieu.
    v_id := case when tg_op = 'DELETE' then coalesce(to_jsonb(old) ->> 'id', to_jsonb(old) ->> 'jeton')
                 else coalesce(to_jsonb(new) ->> 'id', to_jsonb(new) ->> 'jeton') end;
    insert into logistics.sync_queue (table_name, legacy_id, operation) values (tg_table_name, v_id, tg_op);
  exception when others then
    begin
      insert into logistics.sync_failure (table_name, legacy_id, operation, error) values (tg_table_name, v_id, tg_op, sqlstate || ' ' || sqlerrm);
    exception when others then
      raise warning 'double écriture : % (%), rien n''a été bloqué', sqlerrm, tg_table_name;
    end;
  end;
  return null;   -- déclencheur AFTER : sa valeur de retour est ignorée
end;
$$;

do $$
declare t text;
begin
  foreach t in array array['clients', 'colis', 'colis_historique', 'factures', 'appareils', 'prealertes'] loop
    if to_regclass('public.' || t) is not null then
      execute format('drop trigger if exists lg_double_ecriture on public.%I', t);
      execute format('create trigger lg_double_ecriture after insert or update or delete on public.%I '
                     'for each row execute function logistics.enqueue_legacy_change()', t);
    end if;
  end loop;
end
$$;

-- Le traitement de la file : un rattrapage complet (le même code que backfill_from_legacy, donc la même correspondance,
-- les mêmes garanties) quand la file a du travail, puis les lignes traitées passent à « done ». En cas d'échec, chacune
-- est replanifiée avec un délai croissant (1, 2, 4… minutes) ; après 8 échecs, elle passe en « dead » et le rapport
-- le montre. À planifier chaque minute (pg_cron ou le travailleur) une fois la double écriture allumée.
create or replace function logistics.process_sync_queue(p_limit int default 5000)
returns jsonb
language plpgsql
volatile
set search_path = ''
as $$
declare
  v_ids bigint[];
  v_resultat jsonb;
begin
  select array_agg(id order by id) into v_ids from (
    select id from logistics.sync_queue
     where status = 'pending' and next_try_at <= clock_timestamp()
     order by id limit greatest(p_limit, 1)
     for update skip locked
  ) s;
  if v_ids is null then
    return jsonb_build_object('processed', 0, 'status', 'idle');
  end if;
  v_resultat := logistics.run_migration('double_write');
  if v_resultat ->> 'status' = 'ok' then
    update logistics.sync_queue set status = 'done', processed_at = clock_timestamp(), attempts = attempts + 1, last_error = null
     where id = any (v_ids);
    return jsonb_build_object('processed', cardinality(v_ids), 'status', 'ok', 'ready', v_resultat -> 'report' -> 'ready');
  end if;
  update logistics.sync_queue
     set attempts = attempts + 1,
         last_error = v_resultat ->> 'error',
         status = case when attempts + 1 >= 8 then 'dead' else 'pending' end,
         next_try_at = clock_timestamp() + make_interval(mins => power(2, least(attempts, 6))::int)
   where id = any (v_ids);
  return jsonb_build_object('processed', 0, 'status', 'failed', 'error', v_resultat ->> 'error', 'retried', cardinality(v_ids));
end;
$$;

-- Rendre une seconde chance aux lignes « dead », une fois la cause corrigée (propriétaire).
create or replace function logistics.retry_dead_sync()
returns int
language sql
volatile
set search_path = ''
as $$
  with r as (
    update logistics.sync_queue set status = 'pending', next_try_at = clock_timestamp(), attempts = 0
     where status = 'dead' returning 1
  ) select count(*)::int from r
$$;

-- Allumer ou éteindre la double écriture. On ne l'allume que si la migration est PRÊTE (zéro écart inexpliqué,
-- empreintes égales) : sinon la file traiterait des écarts que personne n'a examinés.
create or replace function logistics.set_double_write(p_on boolean)
returns jsonb
language plpgsql
volatile
set search_path = ''
as $$
declare
  v_rapport jsonb;
begin
  if p_on then
    v_rapport := logistics.migration_report();
    if not (v_rapport ->> 'ready')::boolean then
      raise exception 'Double écriture refusée : la migration n''est pas prête (% écart(s) inexpliqué(s) ou empreinte différente). Lancez run_migration() et lisez migration_report().',
        v_rapport ->> 'unexplained' using errcode = 'LG010';
    end if;
  end if;
  update logistics.migration_setting set value = to_jsonb(p_on), updated_at = now(), updated_by = current_user where key = 'double_write';
  return jsonb_build_object('double_write', p_on);
end;
$$;


-- 10. Tout reste fermé : seuls le propriétaire (SQL Editor) et le service interne appellent ces fonctions --------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('backfill_complements', 'reconcile_complements', 'migration_differences',
              'migration_checksums', 'migration_report', 'run_migration', 'explain_difference', 'enqueue_legacy_change',
              'process_sync_queue', 'retry_dead_sync', 'set_double_write') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
end
$$;
