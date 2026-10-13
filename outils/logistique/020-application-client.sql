-- =============================================================================
-- Speed Express Shipping — noyau logistique, étape 20 : l'application client (Android, iOS)
-- -----------------------------------------------------------------------------
-- Phase 8. À coller dans Supabase > SQL Editor APRÈS 019, d'abord en PRÉPRODUCTION,
-- puis en production après une sauvegarde « avant migration » vérifiée.
-- Vérifiez en haut de la page que le projet est bien « speed-express-site » (ou la préproduction).
--
-- Ce que l'application client attend de la base, et qui manquait :
--   1. une notification à CHAQUE événement important du colis — reçu, consolidé, départ, arrivée, douane (début et fin), disponible,
--      assigné à une livraison, en livraison, livré, incident. Il manquait « consolidé », « douane commencée », « assigné à une livraison »,
--      et le téléphone n'était pas prévenu d'un colis perdu ;
--   2. l'enregistrement d'un téléphone DIRECTEMENT dans le noyau (logistics.device), sans passer par l'ancienne table « appareils » :
--      l'application choisit l'une OU l'autre voie, jamais les deux (sinon deux envois pour un même événement) ;
--   3. ce qu'un push emporte pour que le toucher ouvre le bon colis : le numéro de suivi (jamais d'identifiant interne), lu par le travailleur
--      d'envoi (clé secrète seulement).
--
-- Rien n'est calculé par l'application : elle affiche ce que la base rend. Rejouable sans risque ; aucune donnée supprimée ;
-- aucune fonction existante redéfinie. Retour arrière : docs/architecture/APPLICATION-CLIENT.md §7.
-- =============================================================================

-- 1. Les règles de notification qui manquaient --------------------------------------------------------------------------------------------
insert into logistics.notification_rule (event_type, template, channels) values
  ('ParcelConsolidated', 'ParcelConsolidated', array['in_app', 'push']),
  ('CustomsStarted',     'CustomsStarted',     array['in_app', 'push']),
  ('DeliveryAssigned',   'DeliveryAssigned',   array['in_app', 'push'])
on conflict (event_type) do nothing;
-- Un colis perdu est un incident : le téléphone est prévenu, comme pour un colis endommagé (le canal s'ajoute, rien ne s'efface).
update logistics.notification_rule set channels = channels || array['push']
 where event_type = 'ParcelLost' and not ('push' = any (channels));

-- 2. Leurs textes, dans les quatre langues (les mêmes que le portail : écrits par outils/portail-textes.py, comme ceux de 010) -------------
-- Une étape écrite ne change plus : 010 garde ses 21 modèles, les trois nouveaux vivent ici (une base où 010 est déjà passée les reçoit par 020).
-- modeles:debut
-- Écrit par outils/portail-textes.py : ne pas modifier à la main.
insert into logistics.notification_template (code, language, title, body) values
  ('ParcelConsolidated', 'fr', 'Colis regroupé', 'Votre colis {tracking_number} est regroupé avec vos autres achats pour le départ.'),
  ('ParcelConsolidated', 'en', 'Parcel consolidated', 'Your parcel {tracking_number} has been consolidated with your other purchases for departure.'),
  ('ParcelConsolidated', 'es', 'Paquete consolidado', 'Su paquete {tracking_number} se ha consolidado con sus otras compras para la salida.'),
  ('ParcelConsolidated', 'ht', 'Kolis gwoupe', 'Kolis ou a {tracking_number} gwoupe ak lòt acha ou yo pou depa a.'),
  ('CustomsStarted', 'fr', 'Colis en douane', 'Votre colis {tracking_number} est en cours de dédouanement.'),
  ('CustomsStarted', 'en', 'Parcel in customs', 'Your parcel {tracking_number} is going through customs.'),
  ('CustomsStarted', 'es', 'Paquete en aduana', 'Su paquete {tracking_number} está en trámite de aduana.'),
  ('CustomsStarted', 'ht', 'Kolis nan dwàn', 'Kolis ou a {tracking_number} ap pase dwàn.'),
  ('DeliveryAssigned', 'fr', 'Livraison planifiée', 'Un livreur est affecté à votre colis {tracking_number} : la livraison est planifiée.'),
  ('DeliveryAssigned', 'en', 'Delivery scheduled', 'A courier has been assigned to your parcel {tracking_number}: delivery is scheduled.'),
  ('DeliveryAssigned', 'es', 'Entrega programada', 'Se asignó un repartidor a su paquete {tracking_number}: la entrega está programada.'),
  ('DeliveryAssigned', 'ht', 'Livrezon planifye', 'Yo bay yon livrè kolis ou a {tracking_number} : livrezon an planifye.')
on conflict (code, language) do update set title = excluded.title, body = excluded.body
  where (logistics.notification_template.title, logistics.notification_template.body) is distinct from (excluded.title, excluded.body);
-- modeles:fin

-- Le moteur n'écoute que les types d'événements qui ont une règle : on lui ajoute les trois nouveaux (même instruction que 015).
update logistics.event_subscriber
   set event_types = (select array_agg(event_type order by event_type) from logistics.notification_rule)
 where code = 'notification_engine'
   and event_types is distinct from (select array_agg(event_type order by event_type) from logistics.notification_rule);


-- 3. Le téléphone du client, enregistré dans le noyau ---------------------------------------------------------------------------------------
-- Un jeton Expo (ExponentPushToken[…]) et la plateforme. Le compte est TOUJOURS celui de la session : il ne se passe pas en paramètre.
-- Un téléphone qui a servi à un autre compte (prêté, revendu, reconnecté) lui est retiré et passe au compte connecté — sinon l'ancien
-- propriétaire continuerait de recevoir les notifications du nouveau. Au plus dix téléphones actifs par client : au-delà, le plus ancien
-- est désactivé (jamais supprimé). Le plafond d'appels est posé ICI, dans la fonction, et non par un déclencheur : la table des appareils
-- est aussi écrite par le rattrapage de l'ancien schéma (002, 014), qui ne doit jamais être freiné.
create or replace function logistics.register_customer_device(p_user uuid, p_token text, p_platform text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_client uuid; v_jeton text := btrim(coalesce(p_token, '')); v_id uuid; v_avant uuid;
begin
  v_client := logistics.require_customer(p_user);
  if v_jeton !~ '^Expo(nent)?PushToken\[[A-Za-z0-9_-]{8,200}\]$' then raise exception 'Jeton de notification illisible.' using errcode = 'LG005'; end if;
  if p_platform not in ('ios', 'android') then raise exception 'Plateforme inconnue : %.', p_platform using errcode = 'LG005'; end if;
  if to_regprocedure('ops.rate_limit(uuid,text,integer,integer)') is not null then perform ops.rate_limit(p_user, 'portal.device', 20, 3600); end if;
  select id, owner_customer_id into v_id, v_avant from logistics.device where push_token = v_jeton for update;
  if found then
    update logistics.device set owner_customer_id = v_client, owner_user_id = null, kind = 'customer_push', platform = p_platform, active = true,
                                last_seen_at = now(), updated_at = now()
     where id = v_id;
  else
    insert into logistics.device (kind, platform, push_token, owner_customer_id, label, active, last_seen_at, source)
    values ('customer_push', p_platform, v_jeton, v_client, 'Application client', true, now(), 'native')
    returning id into v_id;
  end if;
  update logistics.device set active = false, updated_at = now()
   where id in (select id from logistics.device where owner_customer_id = v_client and active and kind = 'customer_push'
                 order by last_seen_at desc nulls last, created_at desc offset 10);
  return jsonb_build_object('registered', true, 'platform', p_platform, 'reassigned', v_avant is not null and v_avant <> v_client);
end;
$$;

-- À la déconnexion : ce téléphone ne reçoit plus rien pour ce compte. Seul son propriétaire peut le retirer ; un jeton inconnu ou à un autre
-- compte répond pareil (rien à dire à qui essaierait des jetons au hasard).
create or replace function logistics.unregister_customer_device(p_user uuid, p_token text)
returns jsonb language plpgsql volatile security definer set search_path = '' as $$
declare v_client uuid; n int;
begin
  v_client := logistics.require_customer(p_user);
  update logistics.device set active = false, updated_at = now()
   where push_token = btrim(coalesce(p_token, '')) and owner_customer_id = v_client and active;
  get diagnostics n = row_count;
  return jsonb_build_object('unregistered', n > 0);
end;
$$;

-- 4. Ce qu'un push emporte : de quoi ouvrir le bon écran au toucher -------------------------------------------------------------------------
-- Pour le travailleur d'envoi seulement (clé secrète) : le modèle, et le numéro de suivi ou de facture. Le lien est celui de l'application
-- (speedexpress://colis/<numéro>) : un numéro public, jamais un identifiant interne de la base.
create or replace function logistics.nt_push_data(p_ids bigint[])
returns jsonb language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_object_agg(n.id::text, jsonb_strip_nulls(jsonb_build_object(
           'template', n.template,
           'tracking_number', n.payload ->> 'tracking_number',
           'invoice_number', n.payload ->> 'invoice_number',
           'url', case when n.payload ->> 'tracking_number' is not null then 'speedexpress://colis/' || (n.payload ->> 'tracking_number')
                       when n.payload ->> 'invoice_number' is not null then 'speedexpress://factures'
                       else 'speedexpress://notifications' end))), '{}'::jsonb)
    from logistics.notification n
   where n.id = any (coalesce(p_ids, '{}')) and n.channel = 'push'
$$;


-- 5. La façade ------------------------------------------------------------------------------------------------------------------------------
create or replace function public.lg_register_device(p_token text, p_platform text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.register_customer_device(auth.uid(), p_token, p_platform) $$;
create or replace function public.lg_unregister_device(p_token text)
returns jsonb language sql volatile security definer set search_path = '' as $$ select logistics.unregister_customer_device(auth.uid(), p_token) $$;
create or replace function public.ses_nt_push_data(p_ids bigint[])
returns jsonb language sql stable security definer set search_path = '' as $$ select logistics.nt_push_data(p_ids) $$;


-- 6. Tout fermé, sauf la façade : les comptes connectés pour le téléphone, la clé secrète pour le travailleur ---------------------------------
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'logistics' and p.proname in ('register_customer_device', 'unregister_customer_device', 'nt_push_data') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname in ('lg_register_device', 'lg_unregister_device') loop
    execute format('revoke all on function %s from public, anon', r.sig);
    execute format('grant execute on function %s to authenticated', r.sig);
  end loop;
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname = 'ses_nt_push_data' loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to service_role', r.sig);
  end loop;
end
$$;

-- 7. Retour arrière (docs/architecture/APPLICATION-CLIENT.md §7) : désactiver les trois règles (update … set active = false), retirer « push »
-- de ParcelLost, révoquer lg_register_device / lg_unregister_device / ses_nt_push_data. Les téléphones enregistrés restent (désactivables).
