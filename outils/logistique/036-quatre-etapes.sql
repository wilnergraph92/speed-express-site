-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 36 : le parcours du client en QUATRE étapes
-- -----------------------------------------------------------------------------
-- À passer APRÈS 035, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Demande du propriétaire (21/10/2026) : « je veux uniquement afficher les étapes colis reçu, expédié, disponible, livré », dans
-- l'application client, l'espace client du site et la page Suivi. Le parcours en huit étapes (016) reste calculé et rendu tel quel ;
-- la base y AJOUTE ses quatre étapes (simple_steps), regroupées exactement comme l'onglet Colis les voit (le reflet de 030) :
--     received  (Reçu)       : CREATED … READY_FOR_EXPORT
--     shipped   (Expédié)    : LOADED, IN_TRANSIT, ARRIVED, CUSTOMS_PROCESSING, CUSTOMS_CLEARED
--     available (Disponible) : AT_DESTINATION_HUB, DELIVERY_ASSIGNED, OUT_FOR_DELIVERY, FAILED_DELIVERY
--     delivered (Livré)      : DELIVERED
-- Chaque étape : son état (franchie, en cours, à venir, interrompue), la date et le lieu où le colis l'a ATTEINTE (son premier
-- événement dans le groupe ; « Reçu » : l'enregistrement du colis). Un colis arrêté (en attente, abîmé, perdu, retourné, annulé) garde la
-- dernière étape atteinte ; l'exception du parcours (016) le dit. Aucune écriture, aucune table. Rejouable sans risque ; aucune suppression.
-- =============================================================================

create or replace function logistics.simple_step_of(p_status text)
returns int language sql immutable set search_path = '' as $$
  select case
    when p_status in ('CREATED', 'RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT') then 1
    when p_status in ('LOADED', 'IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED') then 2
    when p_status in ('AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY', 'FAILED_DELIVERY') then 3
    when p_status = 'DELIVERED' then 4
  end
$$;

create or replace function logistics.parcel_simple_steps(p_parcel uuid)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  v_p logistics.parcel; v_cles text[] := array['received', 'shipped', 'available', 'delivered'];
  v_le timestamptz[] := array[null, null, null, null]::timestamptz[]; v_lieu text[] := array[null, null, null, null]::text[];
  v_rang int := 0; v_g int; v_arret boolean; v_fin boolean; r record; i int; v_out jsonb := '[]'::jsonb; v_etat text;
begin
  select * into v_p from logistics.parcel where id = p_parcel;
  if not found then return null; end if;
  -- « Reçu » : depuis l'enregistrement du colis
  v_le[1] := v_p.created_at; v_rang := 1;
  for r in select e.to_status, e.occurred_at,
                  coalesce(nullif(e.location_text, ''), (select logistics.branch_label(w.branch_id) from logistics.warehouse w where w.id = e.warehouse_id)) as lieu
             from logistics.tracking_event e where e.parcel_id = p_parcel order by e.occurred_at, e.id loop
    v_g := logistics.simple_step_of(r.to_status);
    continue when v_g is null;
    if v_lieu[v_g] is null then v_lieu[v_g] := r.lieu; end if;
    if v_g > 1 and v_le[v_g] is null then v_le[v_g] := r.occurred_at; end if;
    if v_g > v_rang then v_rang := v_g; end if;
  end loop;
  -- le statut présent fait foi (un colis repris de l'ancien schéma n'a pas tout son historique)
  v_g := logistics.simple_step_of(v_p.status);
  if v_g is not null and v_g > v_rang then v_rang := v_g; end if;
  -- l'expédition dit d'où le colis est parti, et où il est disponible, quand le journal ne porte pas de lieu
  if v_rang >= 2 and v_lieu[2] is null then
    v_lieu[2] := (select logistics.branch_label(s.origin_branch_id) from logistics.shipment s
                   where s.id in (select x.shipment_id from logistics.shipments_of_parcel(p_parcel) x) and s.status <> 'CANCELLED' order by s.created_at, s.id limit 1);
  end if;
  if v_rang >= 3 and v_lieu[3] is null then
    v_lieu[3] := (select logistics.branch_label(s.destination_branch_id) from logistics.shipment s where s.id = logistics.parcel_current_shipment(p_parcel));
  end if;
  v_fin := v_p.status = 'DELIVERED';
  v_arret := v_p.status in ('LOST', 'RETURNED', 'CANCELLED');
  for i in 1 .. 4 loop
    v_etat := case when i < v_rang or (i = v_rang and v_fin) then 'done'
                   when i = v_rang then 'current'
                   when v_arret then 'stopped'
                   else 'upcoming' end;
    v_out := v_out || jsonb_build_object('key', v_cles[i], 'state', v_etat, 'at', case when i <= v_rang then v_le[i] end, 'place', case when i <= v_rang then v_lieu[i] end);
  end loop;
  return v_out;
end;
$$;

-- Le parcours d'un colis du client (016) : le même, et ses quatre étapes en plus.
create or replace function logistics.my_parcel_journey(p_user uuid, p_tracking text)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_c uuid; v_id uuid;
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  v_c := logistics.my_customer(p_user);
  select id into v_id from logistics.parcel where customer_id = v_c and tracking_number = upper(btrim(coalesce(p_tracking, '')));
  if v_id is null then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  return logistics.parcel_journey(v_id) || jsonb_build_object('simple_steps', logistics.parcel_simple_steps(v_id));
end;
$$;

-- Le même parcours pour l'équipe (lg_parcel_journey) : l'équipe et le client voient exactement la même chose.
create or replace function logistics.staff_parcel_journey(p_actor uuid, p_code text)
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare v_id uuid;
begin
  perform logistics.require_right(p_actor, 'colis.lire');
  select id into v_id from logistics.parcel where tracking_number = (logistics.parse_code(p_code) ->> 'number');
  if v_id is null then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  return logistics.parcel_journey(v_id) || jsonb_build_object('simple_steps', logistics.parcel_simple_steps(v_id));
end;
$$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('simple_step_of', 'parcel_simple_steps', 'my_parcel_journey', 'staff_parcel_journey') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
end
$$;

-- Pour retirer SEULEMENT cette étape : remettre logistics.my_parcel_journey et logistics.staff_parcel_journey (016), supprimer logistics.parcel_simple_steps et
-- logistics.simple_step_of.
