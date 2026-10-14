-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 25 : la remise au comptoir, et les écrans du dernier kilomètre
-- -----------------------------------------------------------------------------
-- À passer APRÈS 024, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Le propriétaire l'a confirmé le 14 octobre 2026 : ses clients reçoivent leurs colis DE DEUX FAÇONS — livrés par un chauffeur, ou
-- RETIRÉS AU COMPTOIR du HUB (l'ancien statut « disponible »). Le noyau ne connaissait que la livraison : un colis au HUB ne devenait
-- « livré » qu'après une mission terminée avec sa preuve (photo ou signature, GPS). Ici :
--   · une transition AT_DESTINATION_HUB → DELIVERED (événement « Delivered », le même message au client que pour une livraison) ;
--   · logistics.counter_handover, en AJOUT SEUL : qui a retiré (nom, pièce d'identité), quel membre de l'équipe a remis, où, quand. C'est
--     la preuve de la remise au comptoir : la règle « livré exige une preuve » (guard_parcel_status) et le contrôle de cohérence de fin de
--     transaction (parcel_coherence_issue) l'acceptent au même titre que la preuve du chauffeur ; sans elle, la transition reste refusée
--     (un « livré » à la main, par lg_transition_parcel, répond toujours « il faut une PREUVE ») ;
--   · lg_hand_over_at_counter : les colis d'UN client, tous au HUB, aucun dans une livraison en cours ; droit « colis.statut » ;
--   · lg_ready_for_delivery : les colis au HUB qui attendent (ni remis, ni dans une livraison en cours), avec le client (code, nom,
--     téléphone, adresse) et leur HUB — de quoi créer une livraison ou faire une remise au comptoir.
-- Rejouable sans risque ; aucune donnée supprimée. Ne JAMAIS rejouer 015 après 025.
-- =============================================================================

-- 1. La transition, et le registre des remises ---------------------------------------------------------------------------------------------
insert into logistics.parcel_transition (from_status, to_status, event_type, required_right, requires_customer, requires_reason)
values ('AT_DESTINATION_HUB', 'DELIVERED', 'Delivered', 'colis.statut', true, false)
on conflict do nothing;

create table if not exists logistics.counter_handover (
  id             uuid primary key default gen_random_uuid(),
  parcel_id      uuid not null unique references logistics.parcel (id) on delete restrict,
  customer_id    uuid not null references logistics.customer (id) on delete restrict,
  recipient_name text not null check (btrim(recipient_name) <> ''),
  id_document    text not null default '',
  note           text not null default '',
  warehouse_id   uuid references logistics.warehouse (id) on delete restrict,
  handed_by      uuid not null references logistics.app_user (id) on delete restrict,
  handed_at      timestamptz not null default now(),
  correlation_id uuid not null
);
comment on table logistics.counter_handover is 'Remise d''un colis au comptoir du HUB : la preuve (qui a retiré, pièce, qui a remis, où, quand). Ajout seul.';
drop trigger if exists counter_handover_append_only on logistics.counter_handover;
create trigger counter_handover_append_only before update or delete on logistics.counter_handover for each row execute function logistics.forbid_mutation();
alter table logistics.counter_handover enable row level security;
revoke all on logistics.counter_handover from public, anon, authenticated;


-- 2. La cohérence de fin de transaction : la remise au comptoir est une fin légitime (redéfinie depuis l'étape 015) -----------------------
create or replace function logistics.parcel_coherence_issue(p_parcel_id uuid)
returns text language plpgsql stable set search_path = '' as $$
declare
  v_p logistics.parcel;
  v_missions text[];
begin
  select * into v_p from logistics.parcel where id = p_parcel_id;
  if not found or v_p.status_authority <> 'core' then return null; end if;
  select coalesce(array_agg(t.status), '{}') into v_missions
    from logistics.delivery_parcel dp join logistics.task t on t.delivery_id = dp.delivery_id and t.kind = 'DELIVERY'
   where dp.parcel_id = p_parcel_id;
  if v_p.status = 'LOADED' and logistics.parcel_open_shipment(p_parcel_id, array['READY']) is null then
    return 'chargé sans expédition prête';
  elsif v_p.status = 'DELIVERY_ASSIGNED' and not (v_missions && array['CREATED', 'ASSIGNED', 'ACCEPTED']) then
    return 'affecté à une livraison sans mission en attente';
  elsif v_p.status = 'OUT_FOR_DELIVERY' and not (v_missions && array['STARTED']) then
    return 'en livraison sans mission commencée';
  elsif v_p.status = 'FAILED_DELIVERY' and not (v_missions && array['FAILED']) then
    return 'livraison manquée sans mission échouée';
  elsif v_p.status = 'DELIVERED' and not (v_missions && array['COMPLETED'])
        and not exists (select 1 from logistics.audit_log a where a.action = 'parcel.delivered_without_proof' and a.entity_id = p_parcel_id::text)
        and not exists (select 1 from logistics.counter_handover h where h.parcel_id = p_parcel_id) then
    return 'livré sans mission terminée, sans remise au comptoir ni dérogation de la direction';
  end if;
  return null;
end;
$$;


-- 3. Remettre au comptoir ---------------------------------------------------------------------------------------------------------------------
create or replace function logistics.hand_over_at_counter(p_actor uuid, p_parcel_ids uuid[], p_recipient_name text, p_id_document text default '', p_note text default '')
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_corr uuid := gen_random_uuid(); v_x uuid; v_p logistics.parcel; v_cust uuid; v_out jsonb := '[]'::jsonb;
begin
  perform logistics.require_right(p_actor, 'colis.statut');
  if coalesce(cardinality(p_parcel_ids), 0) = 0 then raise exception 'Choisissez au moins un colis.' using errcode = 'LG005'; end if;
  if cardinality(p_parcel_ids) > 100 then raise exception 'Au plus 100 colis par remise.' using errcode = 'LG005'; end if;
  if btrim(coalesce(p_recipient_name, '')) = '' then raise exception 'Le nom de la personne qui retire est obligatoire.' using errcode = 'LG005'; end if;
  foreach v_x in array p_parcel_ids loop
    select * into v_p from logistics.parcel where id = v_x for update;
    if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
    if v_p.status <> 'AT_DESTINATION_HUB' then
      raise exception 'Le colis % est en % : seul un colis AU HUB se remet au comptoir.', v_p.tracking_number, v_p.status using errcode = 'LG001';
    end if;
    if v_p.customer_id is null then raise exception 'Le colis % n''a pas de client.', v_p.tracking_number using errcode = 'LG005'; end if;
    if v_cust is not null and v_p.customer_id <> v_cust then raise exception 'Une remise ne réunit que les colis d''un MÊME client.' using errcode = 'LG005'; end if;
    v_cust := v_p.customer_id;
    if exists (select 1 from logistics.delivery_parcel dp join logistics.task t on t.delivery_id = dp.delivery_id
                where dp.parcel_id = v_x and t.status not in ('COMPLETED', 'FAILED', 'CANCELLED', 'REFUSED')) then
      raise exception 'Le colis % est dans une livraison en cours : annulez-la d''abord.', v_p.tracking_number using errcode = 'LG004';
    end if;
    insert into logistics.counter_handover (parcel_id, customer_id, recipient_name, id_document, note, warehouse_id, handed_by, correlation_id)
    values (v_x, v_p.customer_id, left(btrim(p_recipient_name), 200), left(btrim(coalesce(p_id_document, '')), 120), left(btrim(coalesce(p_note, '')), 500),
            v_p.current_warehouse_id, p_actor, v_corr);
    -- la preuve vient d'être écrite : le garde « livré exige une preuve » la reconnaît par la dérogation locale, limitée à cette transaction
    perform set_config('logistics.pod_override', 'on', true);
    perform logistics.transition_parcel(v_x, 'DELIVERED', p_actor, null, v_corr, v_p.current_warehouse_id, null, '', null, 'Remis au comptoir',
                                        jsonb_build_object('counter_handover', true, 'recipient_name', left(btrim(p_recipient_name), 200)), 'api');
    perform set_config('logistics.pod_override', 'off', true);
    v_out := v_out || jsonb_build_array(v_p.tracking_number);
  end loop;
  insert into logistics.audit_log (actor_user_id, actor_label, action, entity_type, entity_id, after, correlation_id)
  values (p_actor, logistics.lm_label(p_actor), 'parcel.counter_handover', 'customer', v_cust::text,
          jsonb_build_object('parcels', v_out, 'recipient_name', left(btrim(p_recipient_name), 200), 'id_document', left(btrim(coalesce(p_id_document, '')), 120)), v_corr);
  return jsonb_build_object('handed_over', v_out, 'count', jsonb_array_length(v_out), 'correlation_id', v_corr);
end;
$$;


-- 4. Ce qui attend au HUB --------------------------------------------------------------------------------------------------------------------
create or replace function logistics.ready_for_delivery(p_actor uuid, p_hub_branch uuid default null)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  return coalesce((select jsonb_agg(jsonb_build_object('parcel_id', p.id, 'tracking_number', p.tracking_number, 'weight_lb', coalesce(p.verified_weight_lb, p.weight_lb),
      'destination_country', p.destination_country, 'destination_city', p.destination_city,
      'hub', case when b.id is not null then jsonb_build_object('branch_id', b.id, 'code', b.code) end, 'warehouse', w.code,
      'customer', jsonb_build_object('customer_id', c.id, 'code', c.code, 'name', c.full_name, 'phone', c.phone, 'address', c.address, 'city', c.city))
      order by c.full_name, c.code, p.tracking_number)
    from logistics.parcel p join logistics.customer c on c.id = p.customer_id
    left join logistics.warehouse w on w.id = p.current_warehouse_id left join logistics.branch b on b.id = w.branch_id
   where p.status = 'AT_DESTINATION_HUB' and (p_hub_branch is null or w.branch_id = p_hub_branch)
     and not exists (select 1 from logistics.delivery_parcel dp join logistics.task t on t.delivery_id = dp.delivery_id
                      where dp.parcel_id = p.id and t.status not in ('COMPLETED', 'FAILED', 'CANCELLED', 'REFUSED'))), '[]'::jsonb);
end;
$$;


-- 5. Les façades, et tout le reste fermé ------------------------------------------------------------------------------------------------------
create or replace function public.lg_ready_for_delivery(p_hub_branch uuid default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.ready_for_delivery(auth.uid(), p_hub_branch) $$;
create or replace function public.lg_hand_over_at_counter(p_parcel_ids uuid[], p_recipient_name text, p_id_document text default '', p_note text default '')
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.hand_over_at_counter(auth.uid(), p_parcel_ids, p_recipient_name, p_id_document, p_note) $$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('parcel_coherence_issue', 'hand_over_at_counter', 'ready_for_delivery') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_ready_for_delivery', 'lg_hand_over_at_counter') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
end
$$;
