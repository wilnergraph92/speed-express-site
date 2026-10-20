-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 30 : le noyau devient la source de vérité des colis
-- -----------------------------------------------------------------------------
-- À passer APRÈS 029, par l'outil de migration (scripts/migration/migrer.py), qui fait la sauvegarde vérifiée d'avant.
-- Vérifiez que le projet est bien « speed-express-site » (ou la préproduction) si vous la collez à la main.
--
-- Principe voulu par le propriétaire : le site, le portail, le tableau de bord, les deux applications mobiles et l'application de bureau sont
-- des CLIENTS qui parlent directement à Supabase, par les MÊMES fonctions. Jusqu'ici, un colis naissait dans l'ancien schéma (la table
-- public.colis, écrite par le tableau de bord) et le noyau n'en recevait qu'une copie, chaque minute ; le noyau ne prenait la main sur son
-- statut qu'à sa première transition, et l'ancien schéma, lui, ne voyait plus rien de ce que le noyau faisait ensuite.
--
-- Cette étape ferme la boucle, sans toucher à l'argent (la facturation reste celle de l'ancien schéma tant que la Finance n'a pas basculé,
-- décision du propriétaire du 19/10/2026) :
--   1. CRÉER : public.lg_create_parcel — le colis est enregistré dans l'ancien schéma (numéro, jeton, facture : les règles de toujours,
--      inchangées) ET dans le noyau, dans la même transaction (plus d'attente de la recopie) ;
--   2. MODIFIER : public.lg_update_parcel — les champs descriptifs et de prix (la facture suit, comme avant) ;
--   3. FAIRE AVANCER : public.lg_parcel_next_steps (les étapes permises au compte connecté) et public.lg_move_parcels (la machine d'états
--      du noyau, colis par colis, chaque refus avec sa raison) ; ANNULER : public.lg_cancel_parcel — un colis n'est jamais effacé ;
--   4. LE REFLET : chaque statut décidé par le noyau est recopié dans public.colis (statut et lieu, ramenés aux cinq statuts d'avant), pour
--      tout ce qui lit encore l'ancien schéma (onglet Colis, ancienne facturation, anciens écrans). Le reflet ne réécrit PAS l'historique
--      de l'ancien schéma et ne déclenche PAS l'ancienne notification push : le noyau a déjà son journal et ses notifications ; les
--      recopier ferait compter chaque étape deux fois (journal, Analytique) et prévenir le client deux fois. Un reflet en échec ne bloque
--      jamais une transition : il est journalisé (logistics.sync_failure) et la santé du système le voit (parcel_reflection_gaps) ;
--   5. LE SUIVI PUBLIC : public.ses_track (préfixe « ses_ » comme ses_health : rejouer les étapes 006 à 010 referme toutes les lg_* aux
--      visiteurs, et aucune lg_* ne doit leur être ouverte) — même règle que l'ancien suivi (le numéro ; le jeton du QR code, s'il est donné, doit
--      correspondre), mais le parcours vient du noyau ; rien de plus que ce que l'ancien suivi montrait (ni nom, ni transporteur) ;
--   6. LE PROFIL : public.lg_update_my_profile — l'application et le portail n'écrivent plus eux-mêmes dans la table des clients.
--
-- Rejouable sans risque ; aucune suppression de données.
-- =============================================================================

-- 1. Les statuts du noyau ramenés aux cinq de l'ancien schéma (le sens inverse de map_legacy_parcel_status) -------------------------------
create or replace function logistics.legacy_status_of(p_status text) returns text language sql immutable set search_path = '' as $$
  select case
    when p_status in ('CREATED', 'RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT') then 'confirme'
    when p_status in ('LOADED', 'IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED') then 'expedie'
    when p_status in ('AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY', 'FAILED_DELIVERY') then 'disponible'
    when p_status = 'DELIVERED' then 'livre'
    when p_status in ('ON_HOLD', 'DAMAGED', 'LOST', 'RETURNED', 'CANCELLED') then 'action'
  end
$$;

create or replace function logistics.legacy_service_of(p_mode text) returns text language sql immutable set search_path = '' as $$
  select case p_mode when 'air' then 'aerien' when 'sea' then 'maritime' when 'ground' then 'terrestre' end
$$;

-- 2. Recopier UN colis de l'ancien schéma vers le noyau, tout de suite (la même correspondance que le rattrapage, 002) -------------------
create or replace function logistics.sync_legacy_parcel(p_colis uuid) returns uuid
language plpgsql volatile security definer set search_path = '' as $$
declare v_org uuid; v_id uuid;
begin
  select id into v_org from logistics.organization order by created_at limit 1;
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
   where p.id = p_colis
  on conflict (legacy_parcel_id) do update set
    tracking_number = excluded.tracking_number, public_token = excluded.public_token, customer_id = excluded.customer_id,
    description = excluded.description, sender_name = excluded.sender_name, recipient_name = excluded.recipient_name,
    recipient_phone = excluded.recipient_phone, delivery_address = excluded.delivery_address,
    destination_country = excluded.destination_country, destination_city = excluded.destination_city,
    declared_value = excluded.declared_value, weight_lb = excluded.weight_lb, rate_per_lb = excluded.rate_per_lb,
    service_mode = excluded.service_mode, legacy_status = excluded.legacy_status,
    current_location = excluded.current_location, note = excluded.note,
    status = case when t.status_authority = 'legacy' then excluded.status else t.status end
  where (t.tracking_number, t.public_token, t.customer_id, t.description, t.sender_name, t.recipient_name,
         t.recipient_phone, t.delivery_address, t.destination_country, t.destination_city, t.declared_value,
         t.weight_lb, t.rate_per_lb, t.service_mode, t.legacy_status, t.current_location, t.note)
        is distinct from
        (excluded.tracking_number, excluded.public_token, excluded.customer_id, excluded.description, excluded.sender_name,
         excluded.recipient_name, excluded.recipient_phone, excluded.delivery_address, excluded.destination_country,
         excluded.destination_city, excluded.declared_value, excluded.weight_lb, excluded.rate_per_lb,
         excluded.service_mode, excluded.legacy_status, excluded.current_location, excluded.note)
     or (t.status_authority = 'legacy' and t.status <> excluded.status);
  select id into v_id from logistics.parcel where legacy_parcel_id = p_colis;
  return v_id;
end;
$$;

-- 3. Le reflet : le statut et le lieu décidés par le noyau, recopiés dans l'ancien schéma ------------------------------------------------
-- Pendant le reflet, « ses.reflet » vaut « on » (le temps de la transaction) : l'historique de l'ancien schéma et sa notification push se
-- taisent (leurs déclencheurs portent la condition, plus bas). La recopie vers le noyau, elle, peut passer : le rattrapage ne touche pas au
-- statut d'un colis sous l'autorité du noyau.
create or replace function logistics.reflect_parcel_to_legacy() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  begin
    perform set_config('ses.reflet', 'on', true);
    update public.colis c
       set statut = logistics.legacy_status_of(new.status),
           lieu = case when btrim(coalesce(new.current_location, '')) <> '' then left(new.current_location, 120) else c.lieu end
     where c.id = new.legacy_parcel_id
       and (c.statut is distinct from logistics.legacy_status_of(new.status)
            or (btrim(coalesce(new.current_location, '')) <> '' and c.lieu is distinct from left(new.current_location, 120)));
    perform set_config('ses.reflet', 'off', true);
  exception when others then
    perform set_config('ses.reflet', 'off', true);
    -- jamais bloquant : le noyau a décidé, l'écart se voit (santé : parcel_reflection_gaps) et se corrige par le reflet suivant
    insert into logistics.sync_failure (table_name, legacy_id, operation, error)
    values ('colis_reflet', new.legacy_parcel_id::text, 'REFLECT', left(sqlstate || ' ' || sqlerrm, 500));
  end;
  return null;
end;
$$;
drop trigger if exists reflet_ancien_schema on logistics.parcel;
create trigger reflet_ancien_schema after update of status, current_location, status_authority on logistics.parcel
  for each row when (new.status_authority = 'core' and new.legacy_parcel_id is not null)
  execute function logistics.reflect_parcel_to_legacy();

-- Les deux déclencheurs de l'ancien schéma qui se taisent pendant le reflet (mêmes définitions dans outils/supabase.sql et
-- outils/supabase-maj.sql : rejouer l'un ou l'autre ne change rien).
drop trigger if exists historiser_colis on public.colis;
create trigger historiser_colis
  after insert or update on public.colis
  for each row when (coalesce(current_setting('ses.reflet', true), '') <> 'on')
  execute function public.historiser_colis();
do $$
begin
  if to_regprocedure('public.prevenir_client()') is not null then
    drop trigger if exists prevenir_client on public.colis;
    create trigger prevenir_client
      after insert or update of statut on public.colis
      for each row when (coalesce(current_setting('ses.reflet', true), '') <> 'on')
      execute function public.prevenir_client();
  end if;
end
$$;

-- 4. Créer et modifier un colis : les règles de l'ancien schéma (numéro, jeton, facture), puis le noyau, dans la même transaction --------
create or replace function logistics.colis_champ(p jsonb, k text) returns text language sql immutable set search_path = '' as $$
  select nullif(btrim(p ->> k), '')
$$;

create or replace function logistics.create_parcel(p_actor uuid, p_colis jsonb) returns jsonb
language plpgsql volatile security definer set search_path = '' as $$
declare v_id uuid; v_parcel uuid; r public.colis;
begin
  perform logistics.require_right(p_actor, 'colis.creer');
  if p_colis is null or jsonb_typeof(p_colis) <> 'object' then raise exception 'Colis invalide.' using errcode = 'LG005'; end if;
  insert into public.colis (client_id, description, expediteur, destinataire, telephone_destinataire, poids_lb, tarif_lb, prix_manuel, service,
                            pays_destination, ville_destination, adresse_livraison, valeur_declaree, lieu, note)
  values ((logistics.colis_champ(p_colis, 'client_id'))::uuid,
          coalesce(left(p_colis ->> 'description', 400), ''), coalesce(left(p_colis ->> 'expediteur', 160), ''), coalesce(left(p_colis ->> 'destinataire', 160), ''),
          coalesce(left(p_colis ->> 'telephone_destinataire', 40), ''),
          (logistics.colis_champ(p_colis, 'poids_lb'))::numeric, coalesce((logistics.colis_champ(p_colis, 'tarif_lb'))::numeric, 0),
          (logistics.colis_champ(p_colis, 'prix_manuel'))::numeric, coalesce(logistics.colis_champ(p_colis, 'service'), 'aerien'),
          coalesce(logistics.colis_champ(p_colis, 'pays_destination'), 'DO'), coalesce(left(p_colis ->> 'ville_destination', 120), ''),
          coalesce(left(p_colis ->> 'adresse_livraison', 300), ''), (logistics.colis_champ(p_colis, 'valeur_declaree'))::numeric,
          coalesce(left(p_colis ->> 'lieu', 120), ''), coalesce(left(p_colis ->> 'note', 400), ''))
  returning id into v_id;
  v_parcel := logistics.sync_legacy_parcel(v_id);
  select * into r from public.colis where id = v_id;
  return to_jsonb(r) || jsonb_build_object('parcel_id', v_parcel);
exception when invalid_text_representation or numeric_value_out_of_range then
  raise exception 'Valeur invalide dans le colis.' using errcode = 'LG005';
end;
$$;

create or replace function logistics.update_parcel(p_actor uuid, p_colis_id uuid, p_champs jsonb) returns jsonb
language plpgsql volatile security definer set search_path = '' as $$
declare r public.colis; c jsonb := coalesce(p_champs, '{}'::jsonb);
begin
  perform logistics.require_right(p_actor, 'colis.modifier');
  if jsonb_typeof(c) <> 'object' then raise exception 'Champs invalides.' using errcode = 'LG005'; end if;
  if c ? 'statut' or c ? 'lieu' then raise exception 'Le statut et le lieu avancent par les étapes du noyau (lg_move_parcels).' using errcode = 'LG005'; end if;
  select * into r from public.colis where id = p_colis_id for update;
  if not found then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  -- Un colis sous l'autorité du noyau : son journal est celui du noyau. Une ligne de l'ancien historique (« confirmé » alors qu'il est
  -- rangé, en transit…) deviendrait à la recopie un faux événement au milieu de son parcours : la modification passe donc, elle aussi,
  -- en mode reflet (ni ancien historique, ni ancienne notification push).
  if exists (select 1 from logistics.parcel where legacy_parcel_id = p_colis_id and status_authority = 'core') then
    perform set_config('ses.reflet', 'on', true);
  end if;
  update public.colis set
    client_id = case when c ? 'client_id' then (logistics.colis_champ(c, 'client_id'))::uuid else client_id end,
    description = case when c ? 'description' then coalesce(left(c ->> 'description', 400), '') else description end,
    expediteur = case when c ? 'expediteur' then coalesce(left(c ->> 'expediteur', 160), '') else expediteur end,
    destinataire = case when c ? 'destinataire' then coalesce(left(c ->> 'destinataire', 160), '') else destinataire end,
    telephone_destinataire = case when c ? 'telephone_destinataire' then coalesce(left(c ->> 'telephone_destinataire', 40), '') else telephone_destinataire end,
    poids_lb = case when c ? 'poids_lb' then (logistics.colis_champ(c, 'poids_lb'))::numeric else poids_lb end,
    tarif_lb = case when c ? 'tarif_lb' then coalesce((logistics.colis_champ(c, 'tarif_lb'))::numeric, 0) else tarif_lb end,
    prix_manuel = case when c ? 'prix_manuel' then (logistics.colis_champ(c, 'prix_manuel'))::numeric else prix_manuel end,
    service = case when c ? 'service' then coalesce(logistics.colis_champ(c, 'service'), service) else service end,
    pays_destination = case when c ? 'pays_destination' then coalesce(logistics.colis_champ(c, 'pays_destination'), pays_destination) else pays_destination end,
    ville_destination = case when c ? 'ville_destination' then coalesce(left(c ->> 'ville_destination', 120), '') else ville_destination end,
    adresse_livraison = case when c ? 'adresse_livraison' then coalesce(left(c ->> 'adresse_livraison', 300), '') else adresse_livraison end,
    valeur_declaree = case when c ? 'valeur_declaree' then (logistics.colis_champ(c, 'valeur_declaree'))::numeric else valeur_declaree end,
    note = case when c ? 'note' then coalesce(left(c ->> 'note', 400), '') else note end
  where id = p_colis_id;
  perform set_config('ses.reflet', 'off', true);
  perform logistics.sync_legacy_parcel(p_colis_id);
  select * into r from public.colis where id = p_colis_id;
  return to_jsonb(r) || jsonb_build_object('parcel_id', (select id from logistics.parcel where legacy_parcel_id = p_colis_id));
exception when invalid_text_representation or numeric_value_out_of_range then
  raise exception 'Valeur invalide dans le colis.' using errcode = 'LG005';
end;
$$;

-- 5. Faire avancer un colis : les étapes permises, puis la machine d'états, colis par colis --------------------------------------------
-- Le colis se désigne par son identifiant de l'ancien schéma (celui de l'onglet Colis) ; s'il n'est pas encore dans le noyau, il y est
-- recopié sur-le-champ.
create or replace function logistics.parcel_of_colis(p_colis uuid) returns uuid language plpgsql volatile security definer set search_path = '' as $$
declare v uuid;
begin
  select id into v from logistics.parcel where legacy_parcel_id = p_colis;
  if v is null and exists (select 1 from public.colis where id = p_colis) then v := logistics.sync_legacy_parcel(p_colis); end if;
  if v is null then raise exception 'Colis introuvable.' using errcode = 'LG002'; end if;
  return v;
end;
$$;

create or replace function logistics.parcel_next_steps(p_actor uuid, p_colis uuid) returns jsonb
language plpgsql volatile security definer set search_path = '' as $$
declare v_p logistics.parcel;
begin
  perform logistics.require_right(p_actor, 'colis.statut');
  select * into v_p from logistics.parcel where id = logistics.parcel_of_colis(p_colis);
  -- needs_warehouse / needs_location : la machine exige un entrepôt ou un emplacement et le colis n'en a pas encore — l'écran les demande.
  return jsonb_build_object('colis_id', p_colis, 'parcel_id', v_p.id, 'tracking_number', v_p.tracking_number, 'status', v_p.status,
    'authority', v_p.status_authority, 'legacy_status', logistics.legacy_status_of(v_p.status),
    'current_warehouse_id', v_p.current_warehouse_id,
    'steps', coalesce((select jsonb_agg(jsonb_build_object('to_status', t.to_status, 'requires_reason', t.requires_reason,
                                                          'needs_warehouse', t.requires_warehouse and v_p.current_warehouse_id is null,
                                                          'needs_location', t.requires_location and v_p.current_location_id is null,
                                                          'direction_only', t.required_right = 'direction') order by s.sort_order, t.to_status)
                         from logistics.parcel_transition t join logistics.parcel_status s on s.code = t.to_status
                        where t.from_status = v_p.status and logistics.actor_can(p_actor, t.required_right)), '[]'::jsonb));
end;
$$;

create or replace function logistics.move_parcels(p_actor uuid, p_colis uuid[], p_to_status text, p_location_text text, p_reason text,
                                                   p_warehouse_id uuid default null, p_location_id uuid default null) returns jsonb
language plpgsql volatile security definer set search_path = '' as $$
declare v_c uuid; v_res jsonb := '[]'::jsonb; v_msg text; v_etat text; v_num text;
begin
  perform logistics.require_right(p_actor, 'colis.statut');
  if p_colis is null or cardinality(p_colis) = 0 or cardinality(p_colis) > 200 then raise exception 'Entre 1 et 200 colis.' using errcode = 'LG005'; end if;
  foreach v_c in array p_colis loop
    select numero into v_num from public.colis where id = v_c;
    begin
      perform logistics.transition_parcel(logistics.parcel_of_colis(v_c), coalesce(logistics.status_code(p_to_status), p_to_status), p_actor, null,
                                          null, p_warehouse_id, p_location_id, coalesce(left(p_location_text, 120), ''), null, nullif(btrim(coalesce(p_reason, '')), ''),
                                          '{}'::jsonb, 'api');
      v_res := v_res || jsonb_build_object('colis_id', v_c, 'numero', v_num, 'ok', true);
    exception when others then
      get stacked diagnostics v_msg = message_text, v_etat = returned_sqlstate;
      v_res := v_res || jsonb_build_object('colis_id', v_c, 'numero', v_num, 'ok', false, 'code', v_etat, 'message', left(v_msg, 200));
    end;
  end loop;
  return jsonb_build_object('to_status', p_to_status, 'done', (select count(*) from jsonb_array_elements(v_res) x where (x ->> 'ok')::boolean),
                            'results', v_res);
end;
$$;

-- Annuler : jamais effacer. La facture de l'ancien schéma, elle, se gère comme avant (onglet Factures) : l'argent n'a pas basculé.
create or replace function logistics.cancel_parcel(p_actor uuid, p_colis uuid, p_reason text) returns jsonb
language plpgsql volatile security definer set search_path = '' as $$
declare r jsonb;
begin
  if btrim(coalesce(p_reason, '')) = '' then raise exception 'Motif obligatoire pour annuler un colis.' using errcode = 'LG005'; end if;
  r := logistics.move_parcels(p_actor, array[p_colis], 'CANCELLED', '', p_reason);
  if not ((r -> 'results' -> 0 ->> 'ok')::boolean) then
    raise exception '%', coalesce(r -> 'results' -> 0 ->> 'message', 'Annulation refusée.') using errcode = coalesce(r -> 'results' -> 0 ->> 'code', 'LG001');
  end if;
  return r -> 'results' -> 0;
end;
$$;

-- 6. Le suivi public, depuis le noyau ---------------------------------------------------------------------------------------------------
-- Même règle que public.suivre_colis : le numéro (au moins 4 caractères) ; le jeton du QR code, s'il est donné, doit correspondre.
-- Rien de plus que ce que l'ancien suivi montrait : ni nom, ni téléphone, ni adresse, ni transporteur.
create or replace function logistics.public_track(p_numero text, p_jeton text) returns jsonb
language plpgsql stable security definer set search_path = '' as $$
declare v_p logistics.parcel; v_j jsonb;
begin
  if length(btrim(coalesce(p_numero, ''))) < 4 then return null; end if;
  select * into v_p from logistics.parcel where tracking_number = upper(btrim(p_numero)) and (p_jeton is null or public_token = p_jeton) limit 1;
  if not found then return null; end if;
  v_j := logistics.parcel_journey(v_p.id);
  return jsonb_build_object(
    'numero', v_p.tracking_number, 'status', v_p.status, 'stage', logistics.customer_stage(v_p.status),
    'service_mode', v_p.service_mode, 'destination_country', v_p.destination_country, 'updated_at', v_p.updated_at,
    'steps', coalesce((select jsonb_agg(jsonb_build_object('key', s ->> 'key', 'state', s ->> 'state', 'at', s -> 'at', 'place', s -> 'place'))
                         from jsonb_array_elements(coalesce(v_j -> 'steps', '[]'::jsonb)) s), '[]'::jsonb),
    'events', coalesce((select jsonb_agg(jsonb_build_object('status', e.to_status, 'at', e.occurred_at, 'place', nullif(e.location_text, ''))
                                         order by e.occurred_at, e.id)
                          from logistics.tracking_event e where e.parcel_id = v_p.id and e.to_status is not null), '[]'::jsonb),
    -- la forme de l'ancien suivi (public.suivre_colis), ramenée par la BASE aux cinq statuts d'avant : la page Suivi n'a rien à traduire
    'statut', logistics.legacy_status_of(v_p.status), 'pays_destination', v_p.destination_country,
    'service', logistics.legacy_service_of(v_p.service_mode), 'maj_le', v_p.updated_at,
    'historique', coalesce((select jsonb_agg(jsonb_build_object('statut', logistics.legacy_status_of(e.to_status), 'lieu', coalesce(e.location_text, ''), 'cree_le', e.occurred_at)
                                             order by e.occurred_at, e.id)
                              from logistics.tracking_event e where e.parcel_id = v_p.id and e.to_status is not null), '[]'::jsonb));
end;
$$;

-- 7. Le profil du client connecté : seulement ses champs à lui, jamais son rôle, ses droits ni son code -----------------------------------
create or replace function logistics.update_my_profile(p_user uuid, p_champs jsonb) returns jsonb
language plpgsql volatile security definer set search_path = '' as $$
declare c jsonb := coalesce(p_champs, '{}'::jsonb); r public.clients; k text;
begin
  if p_user is null then raise exception 'Connexion requise.' using errcode = '42501'; end if;
  if jsonb_typeof(c) <> 'object' then raise exception 'Champs invalides.' using errcode = 'LG005'; end if;
  for k in select jsonb_object_keys(c) loop
    if k not in ('nom_complet', 'telephone', 'pays', 'region', 'ville', 'adresse', 'langue') then
      raise exception 'Champ non modifiable : %.', k using errcode = 'LG005';
    end if;
  end loop;
  if c ? 'langue' and coalesce(c ->> 'langue', '') not in ('fr', 'en', 'es', 'ht') then raise exception 'Langue inconnue.' using errcode = 'LG005'; end if;
  update public.clients set
    nom_complet = case when c ? 'nom_complet' then coalesce(left(c ->> 'nom_complet', 160), '') else nom_complet end,
    telephone = case when c ? 'telephone' then coalesce(left(c ->> 'telephone', 40), '') else telephone end,
    pays = case when c ? 'pays' then coalesce(left(c ->> 'pays', 80), '') else pays end,
    region = case when c ? 'region' then coalesce(left(c ->> 'region', 120), '') else region end,
    ville = case when c ? 'ville' then coalesce(left(c ->> 'ville', 120), '') else ville end,
    adresse = case when c ? 'adresse' then coalesce(left(c ->> 'adresse', 300), '') else adresse end,
    langue = case when c ? 'langue' then c ->> 'langue' else langue end
  where id = p_user
  returning * into r;
  if not found then raise exception 'Profil introuvable.' using errcode = 'LG002'; end if;
  return jsonb_build_object('id', r.id, 'nom_complet', r.nom_complet, 'telephone', r.telephone, 'pays', r.pays, 'region', r.region,
                            'ville', r.ville, 'adresse', r.adresse, 'langue', r.langue);
end;
$$;

-- 8. Les façades : l'acteur est TOUJOURS le compte connecté --------------------------------------------------------------------------------
create or replace function public.lg_create_parcel(p_colis jsonb)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.create_parcel(auth.uid(), p_colis) $$;
create or replace function public.lg_update_parcel(p_colis_id uuid, p_champs jsonb)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.update_parcel(auth.uid(), p_colis_id, p_champs) $$;
create or replace function public.lg_parcel_next_steps(p_colis_id uuid)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.parcel_next_steps(auth.uid(), p_colis_id) $$;
create or replace function public.lg_move_parcels(p_colis_ids uuid[], p_to_status text, p_location_text text default '', p_reason text default null,
                                                   p_warehouse_id uuid default null, p_location_id uuid default null)
returns jsonb language sql volatile security definer set search_path = '' as $$
  select logistics.move_parcels(auth.uid(), p_colis_ids, p_to_status, p_location_text, p_reason, p_warehouse_id, p_location_id) $$;
create or replace function public.lg_cancel_parcel(p_colis_id uuid, p_reason text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.cancel_parcel(auth.uid(), p_colis_id, p_reason) $$;
create or replace function public.ses_track(p_numero text, p_jeton text default null)
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.public_track(p_numero, p_jeton) $$;
create or replace function public.lg_update_my_profile(p_champs jsonb)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.update_my_profile(auth.uid(), p_champs) $$;

-- 9. La santé du système : un contrôle de plus, les reflets en défaut ---------------------------------------------------------------------
-- Même corps que 029, avec « parcel_reflection_gaps » : un colis sous l'autorité du noyau dont l'ancien schéma montre un autre statut.
create or replace function ops.status_checks()
returns table (code text, status text, value numeric, warn_at numeric, fail_at numeric, unit text, detail text)
language plpgsql stable security definer set search_path = '' as $$
#variable_conflict use_column
declare v numeric; v2 numeric; v_t timestamptz;
begin
  select count(*), coalesce(extract(epoch from now() - min(created_at)) / 60, 0) into v, v2 from logistics.event_delivery where status in ('PENDING', 'IN_PROGRESS');
  code := 'events_pending'; value := v; warn_at := 500; fail_at := 5000; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  code := 'events_oldest_minutes'; value := round(v2, 1); warn_at := 15; fail_at := 60; unit := 'minutes'; status := case when v2 >= fail_at then 'FAIL' when v2 >= warn_at then 'WARN' else 'OK' end; return next;
  select count(*) into v from logistics.dead_letter where resolved_at is null;
  code := 'dead_letters_open'; value := v; warn_at := 1; fail_at := 50; unit := 'count'; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  if to_regclass('logistics.notification') is not null then
    select count(*) filter (where status = 'FAILED' and created_at > now() - interval '24 hours'),
           coalesce(extract(epoch from now() - min(created_at) filter (where status = 'PENDING' and next_attempt_at <= now())) / 60, 0)
      into v, v2 from logistics.notification;
    code := 'notifications_failed_24h'; value := v; warn_at := 1; fail_at := 25; unit := 'count'; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
    code := 'notifications_oldest_due_minutes'; value := round(v2, 1); warn_at := 30; fail_at := 180; unit := 'minutes'; status := case when v2 >= fail_at then 'FAIL' when v2 >= warn_at then 'WARN' else 'OK' end; return next;
  end if;
  select max(reported_at) into v_t from ops.heartbeat where source = 'backup' and status = 'OK';
  v := case when v_t is null then null else round(extract(epoch from now() - v_t) / 3600, 1) end;
  code := 'backup_age_hours'; value := v; warn_at := 26; fail_at := 50; unit := 'hours'; detail := case when v_t is null then 'never' else '' end;
  status := case when v is null or v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  select max(reported_at) into v_t from ops.heartbeat where source = 'restore_check' and status = 'OK';
  v := case when v_t is null then null else round(extract(epoch from now() - v_t) / 86400, 1) end;
  code := 'restore_check_age_days'; value := v; warn_at := 8; fail_at := 32; unit := 'days'; detail := case when v_t is null then 'never' else '' end;
  status := case when v is null or v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  select count(*) into v from ops.heartbeat where status = 'FAIL' and reported_at > now() - interval '24 hours';
  code := 'jobs_failed_24h'; value := v; warn_at := 1; fail_at := 3; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  if to_regclass('analytics.report_run') is not null then
    select round(extract(epoch from now() - max(generated_at)) / 3600, 1) into v from analytics.report_run;
    code := 'analytics_age_hours'; value := v; warn_at := 26; fail_at := 72; unit := 'hours'; detail := case when v is null then 'never' else '' end;
    status := case when v is null then 'WARN' when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
    select count(*) into v from generate_series(logistics.today() - 7, logistics.today() - 1, interval '1 day') g(d)
     where not exists (select 1 from analytics.report_run r where g.d::date between r.period_start and r.period_end);
    code := 'analytics_missing_days_7'; value := v; warn_at := 1; fail_at := 7; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  end if;
  if to_regclass('analytics.alert') is not null then
    select count(*), count(*) filter (where a.severity = 'FAIL') into v, v2 from analytics.alert a where not exists (select 1 from analytics.alert_ack k where k.alert_id = a.id);
    code := 'analytics_open_alerts'; value := v; warn_at := 1; fail_at := null; unit := 'count'; detail := case when v2 > 0 then 'fail:' || v2 else '' end;
    status := case when v2 > 0 then 'FAIL' when v >= 1 then 'WARN' else 'OK' end; return next;
    select count(*) into v from analytics.run_failure where attempted_at > now() - interval '24 hours';
    code := 'analytics_failures_24h'; value := v; warn_at := 1; fail_at := 2; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  end if;
  select count(*) into v from logistics.parcel p join public.colis c on c.id = p.legacy_parcel_id
   where p.status_authority = 'core' and c.statut is distinct from logistics.legacy_status_of(p.status);
  code := 'parcel_reflection_gaps'; value := v; warn_at := 1; fail_at := 10; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  select count(*), max(occurred_at) into v, v_t from logistics.audit_log where occurred_at > now() - interval '24 hours';
  code := 'audit_entries_24h'; value := v; warn_at := null; fail_at := null; unit := 'count'; detail := coalesce(to_char(v_t at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'), ''); status := 'OK'; return next;
  select count(*) into v from ops.client_error where reported_at > now() - interval '24 hours';
  code := 'client_errors_24h'; value := v; warn_at := 10; fail_at := 100; unit := 'count'; detail := ''; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  select count(*) into v from ops.rate_counter where hits >= max_hits and window_start > now() - interval '24 hours';
  code := 'rate_limited_windows_24h'; value := v; warn_at := 1; fail_at := 50; unit := 'count'; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  v := round(pg_database_size(current_database()) / 1048576.0, 1);
  code := 'database_size_mb'; value := v; warn_at := 400; fail_at := 480; unit := 'MB'; status := case when v >= fail_at then 'FAIL' when v >= warn_at then 'WARN' else 'OK' end; return next;
  v := ops.schema_level();
  code := 'schema_level'; value := v; warn_at := null; fail_at := null; unit := 'level'; status := case when v >= 13 then 'OK' else 'WARN' end; return next;
end;
$$;

-- 10. Tout fermé, sauf les façades -------------------------------------------------------------------------------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where (n.nspname = 'logistics' and p.proname in ('legacy_status_of', 'legacy_service_of', 'sync_legacy_parcel', 'reflect_parcel_to_legacy', 'colis_champ', 'create_parcel',
                     'update_parcel', 'parcel_of_colis', 'parcel_next_steps', 'move_parcels', 'cancel_parcel', 'public_track', 'update_my_profile'))
               or (n.nspname = 'ops' and p.proname = 'status_checks') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig, p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_create_parcel', 'lg_update_parcel', 'lg_parcel_next_steps', 'lg_move_parcels', 'lg_cancel_parcel',
                                                         'ses_track', 'lg_update_my_profile') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
    if r.proname = 'ses_track' then execute format('grant execute on function %s to anon', r.sig); end if;
  end loop;
end
$$;
