-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 37 : la date de naissance et la pièce d'identité du client
-- -----------------------------------------------------------------------------
-- À passer APRÈS 036, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Demande du propriétaire (21/10/2026) : le formulaire d'inscription demande la date de naissance et un document (passeport ou
-- cédula) avec son numéro. Cette étape :
--   1. ajoute à l'ancien schéma (public.clients) date_naissance, document_type ('', 'passeport', 'cedula') et document_numero ;
--      valeurs neutres pour les clients déjà inscrits (aucune n'est inventée) ; reporté dans supabase.sql ;
--   2. redéfinit public.creer_profil_client() pour les lire dans les données de l'inscription. Une valeur mal formée (date
--      impossible, avant 1900 ou dans le futur, type inconnu) est IGNORÉE, jamais bloquante : une inscription ne doit jamais échouer
--      à cause du profil (même règle que le déclencheur de bienvenue de 027) ;
--   3. ajoute les mêmes champs au noyau (logistics.customer : birth_date, id_document_type, id_document_number — mêmes valeurs) ;
--   4. les reporte dans le rattrapage, la comparaison et les empreintes (014) : la recopie les tient à jour, et un écart se voit.
-- Un client ne peut PAS les modifier lui-même ensuite (les droits de colonne de public.clients ne les ouvrent pas) ; l'équipe qui lit
-- les clients (clients.lire) les voit, comme le reste du profil. Les comptes créés par l'application mobile les laissent vides.
-- Rejouable sans risque ; aucune suppression.
-- =============================================================================

-- 1. L'ancien schéma ----------------------------------------------------------
alter table public.clients
  add column if not exists date_naissance  date,
  add column if not exists document_type   text not null default '',
  add column if not exists document_numero text not null default '';

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'clients_document_type_valeurs') then
    alter table public.clients add constraint clients_document_type_valeurs check (document_type in ('', 'passeport', 'cedula'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'clients_document_numero_longueur') then
    alter table public.clients add constraint clients_document_numero_longueur check (char_length(document_numero) <= 40);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'clients_date_naissance_bornes') then
    alter table public.clients add constraint clients_date_naissance_bornes check (date_naissance is null or date_naissance >= date '1900-01-01');
  end if;
end $$;

-- 2. Le profil créé à l'inscription -------------------------------------------
create or replace function public.creer_profil_client()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  m jsonb := coalesce(new.raw_user_meta_data, '{}'::jsonb);
  v_naissance date;
begin
  -- Une date mal formée ne bloque pas l'inscription : elle est simplement laissée vide.
  begin
    if coalesce(m ->> 'date_naissance', '') ~ '^\d{4}-\d{2}-\d{2}$' then
      v_naissance := (m ->> 'date_naissance')::date;
    end if;
  exception when others then
    v_naissance := null;
  end;
  if v_naissance < date '1900-01-01' or v_naissance > current_date then
    v_naissance := null;
  end if;

  insert into public.clients (id, code, nom_complet, pays, region, ville, adresse, telephone, email, langue,
                              date_naissance, document_type, document_numero)
  values (
    new.id,
    public.nouveau_code_client(),
    left(trim(coalesce(m ->> 'nom_complet', '')), 120),
    left(trim(coalesce(m ->> 'pays', '')), 60),
    left(trim(coalesce(m ->> 'region', '')), 80),
    left(trim(coalesce(m ->> 'ville', '')), 80),
    left(trim(coalesce(m ->> 'adresse', '')), 200),
    left(trim(coalesce(m ->> 'telephone', '')), 40),
    coalesce(new.email, ''),
    case when m ->> 'langue' in ('fr', 'en', 'es', 'ht') then m ->> 'langue' else 'fr' end,
    v_naissance,
    case when m ->> 'document_type' in ('passeport', 'cedula') then m ->> 'document_type' else '' end,
    left(trim(coalesce(m ->> 'document_numero', '')), 40)
  )
  on conflict (id) do nothing;
  return new;
end;
$$;
revoke execute on function public.creer_profil_client() from public, anon, authenticated;

-- 3. Le noyau ----------------------------------------------------------------
alter table logistics.customer
  add column if not exists birth_date         date,
  add column if not exists id_document_type   text not null default '',
  add column if not exists id_document_number text not null default '';

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'customer_id_document_type_check') then
    alter table logistics.customer add constraint customer_id_document_type_check check (id_document_type in ('', 'passeport', 'cedula'));
  end if;
end $$;
comment on column logistics.customer.id_document_type is 'Pièce donnée à l''inscription : passeport ou cedula (mêmes valeurs que public.clients.document_type).';

-- 4. Le rattrapage, la comparaison et les empreintes (014), complétés ----------
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

  -- Identité du client (037) : date de naissance et pièce d'identité, données à l'inscription.
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'clients' and column_name = 'date_naissance') then
    execute $q$
      with up as (
        update logistics.customer x
           set birth_date = c.date_naissance, id_document_type = c.document_type, id_document_number = c.document_numero
          from public.clients c
         where x.legacy_client_id = c.id
           and (x.birth_date, x.id_document_type, x.id_document_number) is distinct from (c.date_naissance, c.document_type, c.document_numero)
        returning 1
      ) select count(*) from up $q$ into n_upd;
  else
    n_upd := 0;
  end if;
  v_rap := v_rap || jsonb_build_object('customer_identity', jsonb_build_object('inserted', 0, 'updated', n_upd));

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
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'clients' and column_name = 'date_naissance') then
    return query execute $q$
      select 'mismatch'::text, 'customer'::text, c.id::text, 'date de naissance ou pièce d''identité différente'::text
        from public.clients c join logistics.customer x on x.legacy_client_id = c.id
       where (x.birth_date, x.id_document_type, x.id_document_number) is distinct from (c.date_naissance, c.document_type, c.document_numero) $q$;
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
  -- Identité du client (037) : les mêmes clients que l'empreinte « customer ».
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'clients' and column_name = 'date_naissance') then
    return query execute $q$
      with cc as (
        select c.* from public.clients c
         where c.role = 'client' or exists (select 1 from public.colis p where p.client_id = c.id)
            or exists (select 1 from public.factures f where f.client_id = c.id)
      )
      select e, ln, kn, kd, lh, kh, lh = kh from (select 'customer_identity'::text,
             (select count(*) from cc),
             (select count(*) from logistics.customer x join cc on cc.id = x.legacy_client_id),
             0::bigint,
             (select md5(coalesce(string_agg(array_to_string(array[c.id::text, c.date_naissance::text, c.document_type, c.document_numero], '|', '∅'),
                E'\n' order by c.id), '')) from cc c),
             (select md5(coalesce(string_agg(array_to_string(array[x.legacy_client_id::text, x.birth_date::text, x.id_document_type, x.id_document_number], '|', '∅'),
                E'\n' order by x.legacy_client_id), '')) from logistics.customer x join cc on cc.id = x.legacy_client_id)
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

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('backfill_complements', 'reconcile_complements', 'migration_checksums') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
end
$$;

-- Pour retirer SEULEMENT cette étape : remettre public.creer_profil_client (supabase.sql d'avant) et les trois fonctions de 014 ; les
-- colonnes ajoutées peuvent rester (vides, elles ne gênent rien).
