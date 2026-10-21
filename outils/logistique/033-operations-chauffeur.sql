-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 33 : l'historique et le profil du chauffeur (SES Opérations)
-- -----------------------------------------------------------------------------
-- À passer APRÈS 032, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Demande du propriétaire (21/10/2026), pour l'application SES Opérations : un profil, l'historique des opérations du chauffeur, les
-- options livraison et ramassage. Deux lectures, rien d'autre :
--   1. my_task_history : les missions TERMINÉES d'un chauffeur (livrées, ramassées, en échec, annulées), sur une période, filtrées par genre
--      (livraison, ramassage), avec leurs colis, la preuve de remise (sans les fichiers), le motif d'un échec et le fil de leurs statuts ; et
--      les totaux de la période, comptés par la base. Le chauffeur ne voit que les siennes ;
--   2. my_staff_card : la fiche du membre connecté (nom, e-mail, identifiant d'équipe, rôle, agence, sa fiche de chauffeur et son véhicule),
--      et les chiffres de ses 30 derniers jours.
-- Aucune écriture, aucune table. Rejouable sans risque ; aucune suppression.
-- =============================================================================

-- 1. L'historique des missions d'un chauffeur ----------------------------------------------------------------------------------------
create or replace function logistics.my_task_history(p_actor uuid, p_from date default null, p_to date default null, p_kind text default null,
                                                     p_limit int default 30, p_offset int default 0)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_d uuid := logistics.driver_of(p_actor); v_to date := coalesce(p_to, logistics.today()); v_from date; v_lim int := least(greatest(coalesce(p_limit, 30), 1), 100);
        v_off int := greatest(coalesce(p_offset, 0), 0);
begin
  if v_d is null then
    -- un chauffeur en congé ou désactivé garde son historique : on le cherche aussi parmi les fiches non actives
    select d.id into v_d from logistics.driver d where d.user_id = p_actor;
  end if;
  if v_d is null then raise exception 'Réservé aux chauffeurs.' using errcode = 'LG003'; end if;
  v_from := coalesce(p_from, v_to - 29);
  if v_from > v_to then raise exception 'La période commence après sa fin.' using errcode = 'LG005'; end if;
  if v_to - v_from > 366 then raise exception 'Une période fait au plus un an.' using errcode = 'LG005'; end if;
  if p_kind is not null and p_kind not in ('DELIVERY', 'PICKUP') then raise exception 'Genre inconnu : % (DELIVERY ou PICKUP).', p_kind using errcode = 'LG005'; end if;
  return (
    with f as (
      select t.*, (select max(h.occurred_at) from logistics.task_status_history h where h.task_id = t.id and h.to_status = t.status) as finished_at
        from logistics.task t
       where t.driver_id = v_d and t.status in ('COMPLETED', 'FAILED', 'CANCELLED')
         and t.scheduled_date between v_from and v_to and (p_kind is null or t.kind = p_kind))
    select jsonb_build_object(
      'from', v_from, 'to', v_to, 'kind', p_kind, 'total', (select count(*) from f),
      'totals', jsonb_build_object(
        'delivered', (select count(*) from f where kind = 'DELIVERY' and status = 'COMPLETED'),
        'picked_up', (select count(*) from f where kind = 'PICKUP' and status = 'COMPLETED'),
        'failed', (select count(*) from f where status = 'FAILED'),
        'cancelled', (select count(*) from f where status = 'CANCELLED'),
        'parcels', (select count(*) from f join logistics.delivery_parcel dp on dp.delivery_id = f.delivery_id where f.status = 'COMPLETED')
                 + (select count(*) from f join logistics.pickup_parcel pp on pp.task_id = f.id where f.status = 'COMPLETED')),
      'items', coalesce((select jsonb_agg(jsonb_build_object(
          'task_id', x.id, 'kind', x.kind, 'status', x.status, 'scheduled_date', x.scheduled_date, 'finished_at', x.finished_at,
          'address', x.address, 'failed_reason', x.failed_reason,
          'contact', case when x.kind = 'DELIVERY' then (select d.recipient_name from logistics.delivery d where d.id = x.delivery_id)
                          else (select c.full_name from logistics.customer c where c.id = x.customer_id) end,
          'parcels', coalesce(case when x.kind = 'DELIVERY'
                            then (select jsonb_agg(p.tracking_number order by p.tracking_number) from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = x.delivery_id)
                            else (select jsonb_agg(p.tracking_number order by p.tracking_number) from logistics.pickup_parcel pp join logistics.parcel p on p.id = pp.parcel_id where pp.task_id = x.id) end, '[]'::jsonb),
          'proof', (select jsonb_build_object('recipient_name', pod.recipient_name, 'delivered_at', pod.delivered_at, 'has_photo', pod.photo_path is not null,
                                              'has_signature', pod.signature_path is not null, 'otp_verified', pod.otp_verified)
                      from logistics.proof_of_delivery pod where pod.task_id = x.id),
          'steps', coalesce((select jsonb_agg(jsonb_build_object('status', h.to_status, 'at', h.occurred_at, 'reason', h.reason) order by h.occurred_at, h.id)
                               from logistics.task_status_history h where h.task_id = x.id), '[]'::jsonb))
          order by coalesce(x.finished_at, x.updated_at) desc, x.id)
        from (select * from f order by coalesce(finished_at, updated_at) desc, id limit v_lim offset v_off) x), '[]'::jsonb))
  );
end;
$$;

-- 2. La fiche du membre connecté (le profil de l'application) ------------------------------------------------------------------------
create or replace function logistics.my_staff_card(p_actor uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare u logistics.app_user; v_d logistics.driver; v_today date := logistics.today();
begin
  if p_actor is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  select * into u from logistics.app_user x where x.id = p_actor and x.active;
  if not found then raise exception 'Réservé à l''équipe.' using errcode = 'LG003'; end if;
  select * into v_d from logistics.driver d where d.user_id = p_actor;
  return jsonb_build_object(
    'user_id', u.id, 'name', logistics.chat_name(u.id), 'email', (select a.email from auth.users a where a.id = u.id),
    'role', u.role, 'staff_code', u.staff_code, 'branch', logistics.branch_label(u.branch_id), 'since', u.created_at,
    'driver', case when v_d.id is null then null else jsonb_build_object(
        'driver_id', v_d.id, 'name', v_d.full_name, 'phone', v_d.phone, 'license_no', v_d.license_no, 'status', v_d.status,
        'home_branch', logistics.branch_label(v_d.home_branch_id),
        'vehicle', (select jsonb_build_object('plate', v.plate, 'kind', v.kind) from logistics.vehicle v where v.id = v_d.default_vehicle_id),
        'last_30_days', jsonb_build_object(
          'delivered', (select count(*) from logistics.task t where t.driver_id = v_d.id and t.kind = 'DELIVERY' and t.status = 'COMPLETED' and t.scheduled_date > v_today - 30),
          'picked_up', (select count(*) from logistics.task t where t.driver_id = v_d.id and t.kind = 'PICKUP' and t.status = 'COMPLETED' and t.scheduled_date > v_today - 30),
          'failed', (select count(*) from logistics.task t where t.driver_id = v_d.id and t.status = 'FAILED' and t.scheduled_date > v_today - 30)),
        'open_today', (select count(*) from logistics.task t where t.driver_id = v_d.id and t.status in ('ASSIGNED', 'ACCEPTED', 'STARTED') and t.scheduled_date = v_today)) end,
    'today', v_today);
end;
$$;

-- 3. Les façades ----------------------------------------------------------------------------------------------------------------------
create or replace function public.lg_my_task_history(p_from date default null, p_to date default null, p_kind text default null, p_limit int default 30, p_offset int default 0)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_task_history(auth.uid(), p_from, p_to, p_kind, p_limit, p_offset) $$;
create or replace function public.lg_my_staff_card()
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.my_staff_card(auth.uid()) $$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('my_task_history', 'my_staff_card') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_my_task_history', 'lg_my_staff_card') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;

-- Pour retirer SEULEMENT cette étape : supprimer public.lg_my_task_history, public.lg_my_staff_card, logistics.my_task_history,
-- logistics.my_staff_card. Aucune table n'est créée ici.
