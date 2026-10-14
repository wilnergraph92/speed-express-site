#!/usr/bin/env python3
"""Phase 8 — l'application client (étape 020), éprouvée sur la RÉPLIQUE DE LA PRODUCTION et sur une PRÉPRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-application-essai.py
    SES_FORME_ECRIRE=1 …   réécrit application-rpc.json et application-exemples.json (à recopier dans App_SES/tests/)

On exige :
 A. une notification sur le TÉLÉPHONE à chaque événement important du colis : reçu, consolidé, départ, arrivée, douane (début, fin),
    disponible, assigné à une livraison, en livraison, livré, et chaque incident (endommagé, en attente, livraison manquée, perdu) —
    une règle active avec « push », un modèle dans les quatre langues qui cite le numéro de suivi ;
 B. le téléphone du client enregistré dans le noyau : par le compte de la session seulement, jeton et plateforme vérifiés, réaffecté au
    compte connecté s'il a servi à un autre, dix téléphones actifs au plus, retiré par son seul propriétaire, plafond d'appels ;
 C. le parcours complet : chaque événement d'un colis → un push en attente, dans la langue du client, et ses données (numéro de suivi,
    lien speedexpress://colis/…) lisibles par le seul travailleur ;
 D. tout fermé : rien du noyau ouvert, la façade aux comptes connectés, les données du push à la seule clé secrète ; 020 rejouée sans doublon.
Jamais la production."""
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]
# Les dix événements que le cahier des charges nomme (douane : début ET fin), et les incidents.
IMPORTANTS = ['ParcelReceived', 'ParcelConsolidated', 'ParcelInTransit', 'ParcelArrived', 'CustomsStarted', 'CustomsCleared', 'ParcelAtDestinationHub',
              'DeliveryAssigned', 'OutForDelivery', 'Delivered']
INCIDENTS = ['ParcelDamaged', 'ParcelOnHold', 'DeliveryFailed', 'ParcelLost']
# Ce que l'application appelle : le portail (008), le parcours (016), la finance (018), les notifications (010) et l'étape 020.
APPLICATION = ['lg_my_dashboard', 'lg_my_parcels', 'lg_my_parcel', 'lg_my_parcel_journey', 'lg_my_invoices', 'lg_my_payments', 'lg_my_balance', 'lg_my_notifications',
               'lg_mark_notifications_read', 'lg_my_tickets', 'lg_my_ticket', 'lg_open_ticket', 'lg_reply_ticket', 'lg_my_notification_prefs', 'lg_set_notification_pref',
               'lg_payment_providers', 'lg_my_create_payment_intent', 'lg_my_payment_intent', 'lg_register_device', 'lg_unregister_device']


class R(str):
    pass


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def val(v):
    if v is None:
        return 'null'
    if isinstance(v, R):
        return str(v)
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "array[%s]::text[]" % ', '.join(val(x) for x in v) if v else "'{}'"
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items()))


def jeton(i):
    return 'ExponentPushToken[essai-app-%06d]' % i


def parcours(cl, B, lieu):
    q = lambda sql: cl.un(B, sql)   # noqa: E731
    L = lambda sql: cl.lignes(B, sql)   # noqa: E731
    ok(json.loads(q("select logistics.run_migration('décor de l''application')"))['report']['ready'] is True, '[%s] décor prêt' % lieu)
    admin = q("select id from public.clients where role = 'admin' order by email limit 1")
    clients = L("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id and k.auth_user_id = c.id "
                "where c.role = 'client' order by c.email limit 3")
    ok(len(clients) >= 2, '[%s] au moins deux clients avec un compte' % lieu)
    ca, cb = clients[0], clients[1]
    cust_a = q("select id from logistics.customer where auth_user_id = '%s'" % ca)

    def f(nom, acteur=ca, **kw):
        code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
        return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

    def fr(nom, etat, msg, acteur=ca, **kw):
        code, texte = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
        ok(code != 0 and etat in texte, '[%s] %s : attendu %s, obtenu : %s' % (lieu, msg, etat, texte[-200:].replace('\n', ' ')))

    # ====================================================================== A. les règles et leurs textes
    for ev in IMPORTANTS + INCIDENTS:
        ligne = q("select coalesce((select active::text || '|' || ('push' = any (channels))::text || '|' || ('in_app' = any (channels))::text "
                  "from logistics.notification_rule where event_type = '%s'), 'absente')" % ev)
        ok(ligne == 'true|true|true', '[%s] A : %s prévient le téléphone et l\'espace client (%s)' % (lieu, ev, ligne))
        langues = L("select language || '|' || (body like '%%{tracking_number}%%')::text || '|' || (length(btrim(title)) > 0)::text from logistics.notification_template "
                    "where code = (select template from logistics.notification_rule where event_type = '%s') and active order by language" % ev)
        ok(langues == ['en|true|true', 'es|true|true', 'fr|true|true', 'ht|true|true'], '[%s] A : %s : un texte dans les quatre langues, qui cite le numéro (%s)' % (lieu, ev, langues))
    ok(q("select (select array_agg(event_type order by event_type) from logistics.notification_rule) = event_types from logistics.event_subscriber "
         "where code = 'notification_engine'") == 't', '[%s] A : le moteur écoute chaque événement qui a une règle' % lieu)
    ok(q("select count(*) from logistics.notification_template where code = 'CustomsStarted' and language = 'ht' and body = "
         "'Kolis ou a {tracking_number} ap pase dwàn.'") == '1', '[%s] A : les textes viennent de la table du portail (créole)' % lieu)

    # ====================================================================== B. le téléphone
    r = f('lg_register_device', p_token=jeton(1), p_platform='ios')
    ok(r == {'registered': True, 'platform': 'ios', 'reassigned': False}, '[%s] B : téléphone enregistré (%s)' % (lieu, r))
    ok(q("select kind || '|' || platform || '|' || active::text || '|' || source || '|' || (owner_customer_id = '%s')::text from logistics.device where push_token = '%s'"
         % (cust_a, jeton(1))) == 'customer_push|ios|true|native|true', '[%s] B : au compte de la session, source « native »' % lieu)
    ok(f('lg_register_device', p_token=jeton(1), p_platform='ios')['reassigned'] is False and q("select count(*) from logistics.device where push_token = '%s'" % jeton(1)) == '1',
       '[%s] B : réenregistré : une seule ligne' % lieu)
    fr('lg_register_device', 'LG005', 'jeton illisible', p_token='pas-un-jeton', p_platform='ios')
    fr('lg_register_device', 'LG005', 'jeton vide', p_token='ExponentPushToken[]', p_platform='android')
    fr('lg_register_device', 'LG005', 'plateforme inconnue', p_token=jeton(2), p_platform='windows')
    fr('lg_register_device', 'LG003', 'un membre de l\'équipe n\'enregistre pas de téléphone client', acteur=admin, p_token=jeton(3), p_platform='android')
    code, texte = cl.run(B, appel('lg_register_device', p_token=jeton(4), p_platform='ios'), role='anon', expect_error=True)
    ok(code != 0 and 'permission denied' in texte, '[%s] B : un visiteur ne peut rien enregistrer' % lieu)
    # prêté à B : le téléphone passe au compte connecté, A ne reçoit plus rien dessus
    r = f('lg_register_device', acteur=cb, p_token=jeton(1), p_platform='ios')
    ok(r['reassigned'] is True and q("select (owner_customer_id = '%s')::text from logistics.device where push_token = '%s'" % (cust_a, jeton(1))) == 'false',
       '[%s] B : un téléphone qui change de compte passe au compte connecté' % lieu)
    ok(f('lg_unregister_device', acteur=ca, p_token=jeton(1)) == {'unregistered': False} and q("select active::text from logistics.device where push_token = '%s'" % jeton(1)) == 'true',
       '[%s] B : l\'ancien propriétaire ne peut plus le retirer' % lieu)
    ok(f('lg_unregister_device', acteur=cb, p_token=jeton(1)) == {'unregistered': True} and q("select active::text from logistics.device where push_token = '%s'" % jeton(1)) == 'false',
       '[%s] B : retiré par son propriétaire : désactivé, jamais supprimé' % lieu)
    for i in range(10, 22):
        f('lg_register_device', acteur=cb, p_token=jeton(i), p_platform='android')
    ok(q("select count(*) from logistics.device where owner_customer_id = (select id from logistics.customer where auth_user_id = '%s') and active" % cb) == '10',
       '[%s] B : dix téléphones actifs au plus : le plus ancien est désactivé' % lieu)
    ok(q("select active::text from logistics.device where push_token = '%s'" % jeton(10)) == 'false' and q("select active::text from logistics.device where push_token = '%s'" % jeton(21)) == 'true',
       '[%s] B : c\'est le plus ancien qui s\'éteint, le dernier reste' % lieu)
    # plafond : 20 enregistrements par heure (cb : 1 emprunt + 12 + 7 = 20 ; le retrait ne compte pas)
    for i in range(30, 37):
        f('lg_register_device', acteur=cb, p_token=jeton(i), p_platform='android')
    fr('lg_register_device', 'LG007', 'plafond d\'appels : au-delà de vingt enregistrements par heure', acteur=cb, p_token=jeton(40), p_platform='android')
    # A garde un téléphone, en créole : c'est lui qui recevra les envois du parcours
    f('lg_register_device', p_token=jeton(50), p_platform='android')
    q("update logistics.customer set language = 'ht' where id = '%s'" % cust_a)

    # ====================================================================== C. le parcours d'un colis, événement par événement
    org = q('select id from logistics.organization')
    parcel = q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source, weight_lb) "
               "values ('%s', 'SES-9800000001', 'jeton-app-1', '%s', 'HT', 'air', 'RECEIVED', 'core', 'legacy_backfill', 2) returning id" % (org, cust_a))
    avant = int(q("select coalesce(max(id), 0) from logistics.notification"))
    for ev in IMPORTANTS + INCIDENTS:
        q("select logistics.emit('%s', 'parcel', '%s', gen_random_uuid(), '%s', '{}'::jsonb)" % (ev, parcel, admin))
    q("select logistics.dispatch_events(1000, 'notification_engine')")
    pushs = L("select template || '|' || language || '|' || status || '|' || (body like '%%SES-9800000001%%')::text from logistics.notification "
              "where id > %d and channel = 'push' and customer_id = '%s' order by id" % (avant, cust_a))
    ok(pushs == [ev + '|ht|PENDING|true' for ev in IMPORTANTS + INCIDENTS],
       '[%s] C : un push en attente pour chacun des %d événements, en créole, avec le numéro (%s)' % (lieu, len(IMPORTANTS + INCIDENTS), pushs[:3]))
    # (hors bienvenue : depuis l'étape 027, un client nouvellement inscrit et confirmé reçoit aussi « Bienvenue » dans son espace)
    ok(q("select count(*) from logistics.notification where id > %d and channel = 'in_app' and customer_id = '%s' and template <> 'Welcome'" % (avant, cust_a)) == str(len(IMPORTANTS + INCIDENTS)),
       '[%s] C : et chacun dans l\'espace client (lg_my_notifications)' % lieu)
    ids = L("select id from logistics.notification where id > %d and channel = 'push' and customer_id = '%s' order by id" % (avant, cust_a))
    lot = cl.lignes(B, "set role service_role; select public.ses_nt_push_data(array[%s]::bigint[])" % ','.join(ids))
    donnees = json.loads(lot[-1])
    ok(len(donnees) == len(ids) and all(d == {'template': d['template'], 'tracking_number': 'SES-9800000001', 'url': 'speedexpress://colis/SES-9800000001'} for d in donnees.values()),
       '[%s] C : chaque push emporte le numéro et le lien de l\'application, rien d\'autre' % lieu)
    code, texte = cl.run(B, "select public.ses_nt_push_data(array[%s]::bigint[])" % ids[0], role='authenticated', claims=ca, expect_error=True)
    ok(code != 0 and 'permission denied' in texte, '[%s] C : un client ne lit pas les données d\'envoi' % lieu)
    notes = f('lg_my_notifications')
    ok(notes['unread'] >= len(IMPORTANTS + INCIDENTS) and {n['template'] for n in notes['items']} >= set(IMPORTANTS + INCIDENTS),
       '[%s] C : le client retrouve chaque événement dans ses notifications' % lieu)

    # ====================================================================== D. tout fermé
    ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and "
         "(has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))") == '0', '[%s] D : aucune fonction du noyau ouverte' % lieu)
    ok(q("select string_agg(p.proname || ':' || has_function_privilege('authenticated', p.oid, 'execute')::text || ':' || has_function_privilege('anon', p.oid, 'execute')::text || ':' "
         "|| has_function_privilege('service_role', p.oid, 'execute')::text, ',' order by p.proname) from pg_proc p where p.pronamespace = 'public'::regnamespace "
         "and p.proname in ('lg_register_device', 'lg_unregister_device', 'ses_nt_push_data')")
       == 'lg_register_device:true:false:true,lg_unregister_device:true:false:true,ses_nt_push_data:false:false:true', '[%s] D : la façade aux comptes connectés, les données du push à la clé secrète' % lieu)

    # Des réponses RÉELLES et les signatures, pour l'application (App_SES/tests/)
    # un choix STABLE (plusieurs colis naissent à la même heure) : sinon la forme de l'exemple changerait d'un passage à l'autre
    num = q("select tracking_number from logistics.parcel where customer_id = '%s' order by created_at, tracking_number limit 1" % cust_a)
    return {
        'exemples': {'tableau': f('lg_my_dashboard'), 'colis': f('lg_my_parcels'), 'colis_detail': f('lg_my_parcel', p_tracking=num), 'parcours': f('lg_my_parcel_journey', p_tracking_number=num),
                     'factures': f('lg_my_invoices'), 'paiements': f('lg_my_payments'), 'solde': f('lg_my_balance'), 'notifications': f('lg_my_notifications', p_limit=3),
                     'tickets': f('lg_my_tickets'), 'enregistrement': f('lg_register_device', p_token=jeton(60), p_platform='ios')},
        'signatures': json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), "
                                   "'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) "
                                   "from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = any (%s)" % val(APPLICATION)))}


def main():
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        cl.run('postgres', "alter database prod set timezone to 'America/Port-au-Prince'")
        etapes = sorted(os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')))
        ok('020-application-client.sql' in etapes, 'l\'étape 020 est dans le noyau')
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        compte = "select (select count(*) from logistics.notification_rule) || '|' || (select count(*) from logistics.notification_template) || '|' || (select count(*) from logistics.event_type)"
        n = q(compte)
        cl.run('prod', P.lire_sql('outils/logistique/020-application-client.sql'))
        ok(q(compte) == n, '020 rejouée : rien en double (%s)' % n)
        contrat = parcours(cl, 'prod', 'réplique')
        ok(set(contrat['signatures']) == set(APPLICATION), 'chaque fonction appelée par l\'application existe (%s)' % sorted(set(APPLICATION) - set(contrat['signatures'])))
        ici = os.path.dirname(os.path.abspath(__file__))
        ch_ex, ch_rpc = os.path.join(ici, 'application-exemples.json'), os.path.join(ici, 'application-rpc.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(contrat['exemples'], open(ch_ex, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            json.dump(contrat['signatures'], open(ch_rpc, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        # « by_stage » compte les colis PAR ÉTAPE : ses clés sont des données (une étape sans colis n'y est pas), pas des champs.
        # La réplique tire au hasard le statut de ses colis : « delivered » y manquait environ une fois sur quatre, et la CI échouait.
        cles = lambda x, c='': ({c + '.' + k for k in x} | set().union(*[cles(v, c + '.' + k) for k, v in x.items() if k != 'by_stage']) if isinstance(x, dict)
                                else set().union(*[cles(v, c + '[]') for v in x]) if isinstance(x, list) else set())
        partage = cles(json.load(open(ch_ex, encoding='utf-8')))
        ok(partage == cles(contrat['exemples']) and json.load(open(ch_rpc, encoding='utf-8')) == contrat['signatures'],
           'la forme des réponses et les signatures sont celles des fichiers partagés avec l\'application (sinon : SES_FORME_ECRIRE=1, recopier dans App_SES/tests/)'
           ' — en trop : %s ; manquantes : %s' % (sorted(cles(contrat['exemples']) - partage), sorted(partage - cles(contrat['exemples']))))
        spec = importlib.util.spec_from_file_location('assembler', os.path.join(P.RACINE, 'outils', 'staging', 'assembler-installation.py'))
        A = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(A)
        cl.run('postgres', 'create database staging')
        cl.run('postgres', "alter database staging set timezone to 'America/Port-au-Prince'")
        cl.run('staging', P.lire_sql('scripts/restore/socle-postgres-vide.sql'))
        cl.run('staging', P.AUTH)
        cl.run('staging', P.SUPABASE_DEFAUTS)
        cl.run('staging', A.assembler())
        cl.run('staging', P.lire_sql('outils/staging/donnees-synthetiques.sql'))
        for f in etapes:
            cl.run('staging', P.lire_sql('outils/logistique/' + f))
        parcours(cl, 'staging', 'préproduction')
        print('PASS application client (phase 8) : %d vérifications — sur la réplique ET la préproduction : un push à chacun des dix événements importants '
              'et à chaque incident, en quatre langues, avec le numéro et le lien du colis ; téléphone enregistré au compte de la session, réaffecté, '
              'plafonné ; tout fermé (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC application client (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
