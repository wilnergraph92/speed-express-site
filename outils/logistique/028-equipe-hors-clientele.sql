-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 28 : un client qui entre dans l'équipe
-- -----------------------------------------------------------------------------
-- À passer APRÈS 027, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Constaté en production le 14 octobre 2026 (contrôle d'après la migration 027, commande « rapport » de l'exploitation) : un compte client
-- est entré dans l'équipe (employé — par exemple pour devenir chauffeur). La règle « l'équipe n'est pas la clientèle » (definir_role) lui a
-- retiré son code client dans l'ancien schéma, ce qui est voulu. Mais le noyau gardait sa fiche CLIENT avec l'ancien code, que la recopie ne
-- touche plus (elle ne suit que les clients, et les comptes qui portent des colis ou des factures) : un écart « inexpliqué », qui empêche le
-- rattrapage d'être « prêt ». Ici, sans rien supprimer :
--   · l'écart est EXPLIQUÉ (« became_staff ») quand le compte est de l'équipe dans l'ancien schéma, sans colis ni facture : la fiche du noyau
--     reste, comme l'historique de ce qu'il était ;
--   · cette fiche est marquée compte d'équipe (source « legacy_staff_account ») : plus de notification de client, la marque « compte
--     d'équipe » dans la liste des clients ;
--   · la bienvenue (027) ignore un compte d'équipe.
-- Rejouable sans risque ; aucune donnée supprimée.
-- =============================================================================

-- 1. Le compte qui a quitté la clientèle pour l'équipe ----------------------------------------------------------------------------------------
create or replace function logistics.customer_turned_staff(p_legacy_client uuid)
returns boolean language sql stable security definer set search_path = '' as $$
  select exists (select 1 from public.clients c where c.id = p_legacy_client and c.role <> 'client')
     and not exists (select 1 from public.colis p where p.client_id = p_legacy_client)
     and not exists (select 1 from public.factures f where f.client_id = p_legacy_client)
$$;

update logistics.customer x set source = 'legacy_staff_account'
 where x.source = 'legacy_backfill' and x.legacy_client_id is not null and logistics.customer_turned_staff(x.legacy_client_id);


-- 2. Les écarts du rattrapage : ce cas est EXPLIQUÉ (redéfinie depuis l'étape 014) ---------------------------------------------------------
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
         (sup.legacy_id is not null or e.legacy_id is not null or equipe.legacy_id is not null) as explained,
         case when sup.legacy_id is not null then 'legacy_deleted'
              when e.legacy_id is not null then 'owner_reviewed: ' || e.reason
              when equipe.legacy_id is not null then 'became_staff' end as reason
    from brut b
    left join lateral (
      select b.legacy_id where b.kind = 'orphan_in_core' and (
           (b.entity = 'parcel'    and exists (select 1 from logistics.parcel x    where x.legacy_parcel_id::text = b.legacy_id    and x.legacy_deleted_at is not null))
        or (b.entity = 'invoice'   and exists (select 1 from logistics.invoice x   where x.legacy_invoice_id::text = b.legacy_id   and x.legacy_deleted_at is not null))
        or (b.entity = 'customer'  and exists (select 1 from logistics.customer x  where x.legacy_client_id::text = b.legacy_id    and x.legacy_deleted_at is not null))
        or (b.entity = 'pre_alert' and exists (select 1 from logistics.pre_alert x where x.legacy_pre_alert_id::text = b.legacy_id and x.legacy_deleted_at is not null)))
    ) sup on true
    left join logistics.migration_explanation e on e.kind = b.kind and e.entity = b.entity and e.legacy_id = b.legacy_id
    -- un client devenu membre de l'équipe, sans colis ni facture : sa fiche client du noyau garde l'historique, l'ancien schéma l'a retiré
    left join lateral (
      select b.legacy_id where b.kind = 'mismatch' and b.entity = 'customer' and logistics.customer_turned_staff(b.legacy_id::uuid)
    ) equipe on true
$$;


-- 3. La bienvenue ignore un compte d'équipe (redéfinie depuis l'étape 027) ----------------------------------------------------------------------
create or replace function logistics.nt_welcome(p_auth_user uuid)
returns void language plpgsql security definer set search_path = '' as $$
declare c logistics.customer; v_conf timestamptz; v_cree timestamptz;
begin
  if p_auth_user is null then return; end if;
  select u.email_confirmed_at, u.created_at into v_conf, v_cree from auth.users u where u.id = p_auth_user;
  -- confirmée, et récente : un compte ancien (déjà client avant ce centre) ne reçoit jamais de « bienvenue »
  if v_conf is null or v_cree is null or v_cree < now() - interval '7 days' then return; end if;
  -- l'équipe n'est pas la clientèle : un compte d'équipe n'est jamais accueilli comme un client
  if exists (select 1 from public.clients x where x.id = p_auth_user and x.role <> 'client') then return; end if;
  select * into c from logistics.customer where auth_user_id = p_auth_user;
  if not found or c.source = 'legacy_staff_account' then return; end if;   -- pas encore recopié : le déclencheur du client s'en chargera
  insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, actor_label, payload)
  values ('CustomerRegistered', 'customer', c.id::text, gen_random_uuid(), 'inscription', jsonb_build_object('customer_id', c.id))
  on conflict (aggregate_id) where event_type = 'CustomerRegistered' do nothing;
end;
$$;


-- 4. Tout fermé ------------------------------------------------------------------------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('customer_turned_staff', 'migration_differences', 'nt_welcome') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
end
$$;
