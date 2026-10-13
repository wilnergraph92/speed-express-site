#!/usr/bin/env python3
"""Phase 9 — « SES Opérations » sur le terrain (étape 021), éprouvée sur la RÉPLIQUE DE LA PRODUCTION et sur une PRÉPRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-terrain-essai.py
    SES_FORME_ECRIRE=1 …   réécrit terrain-rpc.json et terrain-formes.json (à recopier dans App_SES/tests/rpc-terrain.json, formes-terrain.json)

Les trois règles de la file hors connexion, sur les vrais gestes du terrain :
 A. MÊME commande rejouée (même clé, mêmes arguments) → le résultat d'ORIGINE, rien de fait deux fois ; même clé pour un autre geste → LG006 ;
 B. ORDRE incorrect → conflit (LG001) : arriver avant d'avoir commencé, livrer avant d'arriver n'est pas exigé mais terminer une tournée
    pas commencée l'est, replanifier une mission qui n'a pas échoué ;
 C. PERMISSION incorrecte → refus (LG003), et la clé n'est pas consommée : la mission d'un autre chauffeur, la tournée d'un autre, un chauffeur
    sans droit qui replanifie, un client à la porte ;
et :
 D. l'arrivée à l'arrêt : l'heure du TÉLÉPHONE (bornée), la position de ce moment seulement, une deuxième arrivée ne change rien ;
 E. la preuve d'une livraison lue par l'équipe et par son chauffeur, pas par un autre chauffeur ; la tournée démarrée et terminée par le téléphone ;
 F. tout fermé ; 021 rejouée sans doublon.
Jamais la production."""
import importlib.util
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]
TERRAIN = ['lg_trip_detail', 'lg_task_proof', 'lg_reorder_trip', 'lg_warehouse_locations']


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
    if isinstance(v, dict):
        return "'%s'::jsonb" % json.dumps(v).replace("'", "''")
    if isinstance(v, (list, tuple)):
        return "array[%s]::text[]" % ', '.join(val(x) for x in v) if v else "'{}'"
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items()))


def forme(x):
    o = x[0] if isinstance(x, list) else x
    s = set()
    for k_, v_ in o.items():
        s.add(k_)
        if isinstance(v_, list) and v_ and isinstance(v_[0], dict):
            s.update('%s[].%s' % (k_, k2) for k2 in v_[0])
        elif isinstance(v_, dict):
            s.update('%s.%s' % (k_, k2) for k2 in v_)
    return sorted(s)


def rejoue(r, origine):
    """Un rejeu rend le résultat d'origine, marqué « replayed » (la base ne refait rien)."""
    return r.get('replayed') is True and {k: v for k, v in r.items() if k != 'replayed'} == {k: v for k, v in origine.items() if k != 'replayed'}


def parcours(cl, B, lieu):
    q = lambda sql: cl.un(B, sql)   # noqa: E731
    L = lambda sql: cl.lignes(B, sql)   # noqa: E731
    comptes = {'chauf': [], 'chauf2': [], 'hub': ['colis.lire', 'colis.statut']}
    for i, (cle, droits) in enumerate(comptes.items()):
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0009-%012d', 'authenticated', 'authenticated', 'tr-%s@essai.test', 'x', now(), '{\"nom_complet\": \"Membre %s\"}')"
          % (i + 1, cle, cle))
        q("update public.clients set role = 'employe', code = null, droits = %s where email = 'tr-%s@essai.test'" % (val(droits) if droits else "'{}'", cle))
    ok(json.loads(q("select logistics.run_migration('décor du terrain')"))['report']['ready'] is True, '[%s] décor prêt' % lieu)
    uid = lambda e: q("select id from public.clients where email = '%s'" % e)   # noqa: E731
    admin = q("select id from public.clients where role = 'admin' order by email limit 1")
    chauf, chauf2, hub = uid('tr-chauf@essai.test'), uid('tr-chauf2@essai.test'), uid('tr-hub@essai.test')
    client = L("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1")[0]

    def f(nom, acteur=chauf, **kw):
        code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
        return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

    def fr(nom, etat, msg, acteur=chauf, **kw):
        code, texte = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
        ok(code != 0 and etat in texte, '[%s] %s : attendu %s, obtenu : %s' % (lieu, msg, etat, texte[-220:].replace('\n', ' ')))

    def geste(cle, commande, args, acteur=chauf):
        return f('lg_mobile_command', acteur=acteur, p_key=cle, p_command=commande, p_args=args)

    def geste_refuse(cle, commande, args, etat, msg, acteur=chauf):
        fr('lg_mobile_command', etat, msg, acteur=acteur, p_key=cle, p_command=commande, p_args=args)
        ok(q("select count(*) from logistics.command_log where idempotency_key = 'mobile:%s:%s'" % (acteur, cle)) == '0', '[%s] %s : la clé n\'est pas consommée' % (lieu, msg))

    # le décor : un hub, deux chauffeurs, deux livraisons sur la tournée du premier
    org = q('select id from logistics.organization')
    q("insert into logistics.branch (organization_id, code, name, kind, country) values ('%s', 'TR-PAP', 'Hub essai terrain', 'hub', 'HT')" % org)
    pap = q("select id from logistics.branch where code = 'TR-PAP'")
    veh = f('lg_create_vehicle', acteur=admin, p_plate='tr-van', p_kind='VAN', p_capacity_lb=300, p_branch=pap)
    veh2 = f('lg_create_vehicle', acteur=admin, p_plate='tr-moto', p_kind='MOTORCYCLE', p_capacity_lb=60, p_branch=pap)
    drv = f('lg_create_driver', acteur=admin, p_user_id=chauf, p_full_name='Chauffeur Terrain', p_vehicle_id=veh)
    f('lg_create_driver', acteur=admin, p_user_id=chauf2, p_full_name='Chauffeur Deux', p_vehicle_id=veh2)
    cust = q("select id from logistics.customer where legacy_client_id = '%s'" % client)
    n_p = [0]

    def colis():
        n_p[0] += 1
        return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source, weight_lb) "
                 "values ('%s', 'SES-96%08d', 'jeton-tr%d', '%s', 'HT', 'air', 'AT_DESTINATION_HUB', 'core', 'legacy_backfill', 3) returning id" % (org, n_p[0], n_p[0], cust))
    taches = []
    for i in range(2):
        liv = f('lg_create_delivery', acteur=hub, p_parcel_ids=R("array['%s']::uuid[]" % colis()), p_hub_branch=pap, p_scheduled_for=R('current_date'),
                p_recipient_name='Marie %d' % i, p_address='%d rue Capois, Port-au-Prince' % (i + 1))
        f('lg_assign_task', acteur=admin, p_task_id=liv['task_id'], p_driver_id=drv, p_force=True, p_reason='Essai terrain')
        taches.append(liv['task_id'])
    for t in taches:
        geste('acc-' + t[:8], 'accept_task', {'task_id': t})
    trip = f('lg_create_trip', acteur=hub, p_driver_id=drv, p_trip_date=R('current_date'), p_task_ids=R("array['%s', '%s']::uuid[]" % tuple(taches)))
    tid = trip['trip_id']
    t1, t2 = taches
    ici = {'latitude': 18.5392, 'longitude': -72.3364}

    # ====================================================================== B. l'ordre (avant le départ)
    geste_refuse('arr-avant-depart', 'arrive_stop', {'task_id': t1}, 'LG001', 'arriver avant d\'avoir commencé')
    geste_refuse('fin-avant-depart', 'complete_trip', {'trip_id': tid}, 'LG001', 'terminer une tournée pas commencée')
    # ====================================================================== C. la permission
    geste_refuse('dep-autre', 'start_trip', {'trip_id': tid}, 'LG003', 'démarrer la tournée d\'un autre chauffeur', acteur=chauf2)
    geste_refuse('arr-autre', 'arrive_stop', {'task_id': t1}, 'LG003', 'arriver à l\'arrêt de la mission d\'un autre', acteur=chauf2)
    fr('lg_mobile_command', 'LG003', 'un client à la porte des téléphones', acteur=client, p_key='client-essai', p_command='position', p_args={'latitude': 1, 'longitude': 1})

    # ====================================================================== E. la tournée démarrée par le téléphone
    dep = geste('dep-' + tid[:8], 'start_trip', {'trip_id': tid})
    ok(dep['status'] == 'STARTED' and dep['tasks_started'] == 2, '[%s] E : tournée démarrée depuis le téléphone, ses deux missions commencées' % lieu)
    # ====================================================================== A. le rejeu
    ok(rejoue(geste('dep-' + tid[:8], 'start_trip', {'trip_id': tid}), dep), '[%s] A : même geste rejoué → le résultat d\'origine (la tournée ne redémarre pas)' % lieu)
    fr('lg_mobile_command', 'LG006', 'même clé pour un AUTRE geste', p_key='dep-' + tid[:8], p_command='complete_trip', p_args={'trip_id': tid})

    # ====================================================================== D. l'arrivée à l'arrêt
    q("update logistics.driver set last_position_at = null, last_latitude = null, last_longitude = null where id = '%s'" % drv)
    heure = q("select to_char((now() - interval '20 minutes') at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')")
    geste_refuse('arr-futur', 'arrive_stop', {'task_id': t1, 'recorded_at': '2099-01-01T00:00:00Z'}, 'LG005', 'une heure d\'arrivée dans le futur')
    geste_refuse('arr-gps-moitie', 'arrive_stop', {'task_id': t1, 'latitude': 18.5}, 'LG005', 'une position à moitié')
    a1 = geste('arr-' + t1[:8], 'arrive_stop', dict(task_id=t1, recorded_at=heure, **ici))
    ok(a1['stop_status'] == 'ARRIVED' and a1['already'] is False and a1['sequence'] == 1, '[%s] D : arrivée au premier arrêt' % lieu)
    ok(q("select (abs(extract(epoch from actual_at - (now() - interval '20 minutes'))) < 5)::text from logistics.stop where task_id = '%s'" % t1) == 'true',
       '[%s] D : l\'heure du TÉLÉPHONE (envoyée vingt minutes plus tard, après une coupure)' % lieu)
    ok(q("select last_latitude || '|' || last_longitude from logistics.driver where id = '%s'" % drv) == '18.539200|-72.336400', '[%s] D : la position de l\'arrivée' % lieu)
    ok(rejoue(geste('arr-' + t1[:8], 'arrive_stop', dict(task_id=t1, recorded_at=heure, **ici)), a1), '[%s] A : arrivée rejouée → résultat d\'origine' % lieu)
    a1b = geste('arr2-' + t1[:8], 'arrive_stop', {'task_id': t1})
    ok(a1b['already'] is True and a1b['stop_status'] == 'ARRIVED', '[%s] D : une deuxième arrivée (autre geste) ne change rien, et le dit' % lieu)
    ok(q("select count(*) from logistics.domain_event where event_type = 'StopArrived' and payload ->> 'task_id' = '%s'" % t1) == '1', '[%s] D : un seul événement d\'arrivée' % lieu)

    # la remise, puis la preuve lue par l'équipe et par son chauffeur
    f('lg_issue_delivery_otp', acteur=hub, p_task_id=t1)
    # le code part AU CLIENT (notification « DeliveryOtp ») ; l'équipe ne le voit jamais : on le relit là où la base l'a déposé pour lui
    code = q("select payload ->> 'code' from logistics.notification where template = 'DeliveryOtp' order by id desc limit 1")
    remise = geste('pod-' + t1[:8], 'complete_delivery', dict(task_id=t1, recipient_name='Marie 0', photo_path='pod/%s/pod-%s.jpg' % (t1, t1[:8]),
                                                               signature_path='pod/%s/pod-%s-signature.svg' % (t1, t1[:8]), otp=code, recorded_at=heure, **ici))
    ok(remise.get('completed', True) is not False, '[%s] remise acceptée (code, photo, signature) : %s' % (lieu, remise))
    preuve = f('lg_task_proof', acteur=hub, p_task_id=t1)
    ok(preuve['status'] == 'COMPLETED' and preuve['proof']['recipient_name'] == 'Marie 0' and preuve['proof']['has_photo'] and preuve['proof']['has_signature']
       and preuve['proof']['otp_required'] and preuve['proof']['otp_verified'] and preuve['proof']['driver'] == 'Chauffeur Terrain', '[%s] E : la preuve, lue par l\'agent du hub' % lieu)
    ok(f('lg_task_proof', acteur=chauf, p_task_id=t1)['proof']['recipient_name'] == 'Marie 0', '[%s] E : et par son chauffeur' % lieu)
    fr('lg_task_proof', 'LG003', 'la preuve d\'une mission par un AUTRE chauffeur (sans droit de lecture)', acteur=chauf2, p_task_id=t1)
    ok('photo_path' not in json.dumps(preuve) and 'signature_path' not in json.dumps(preuve), '[%s] E : jamais le chemin des fichiers' % lieu)

    # ====================================================================== l'échec, puis la replanification
    geste('arr-' + t2[:8], 'arrive_stop', {'task_id': t2})
    geste_refuse('rep-trop-tot', 'reschedule_task', {'task_id': t2, 'new_date': q("select (current_date + 1)::text")}, 'LG001', 'replanifier une mission qui n\'a pas échoué', acteur=hub)
    geste('ech-' + t2[:8], 'fail_task', {'task_id': t2, 'incident_type': 'CUSTOMER_ABSENT', 'description': 'personne au portail'})
    demain = q("select (current_date + 1)::text")
    geste_refuse('rep-chauf', 'reschedule_task', {'task_id': t2, 'new_date': demain}, 'LG003', 'un chauffeur sans droit ne replanifie pas')
    geste_refuse('rep-passe', 'reschedule_task', {'task_id': t2, 'new_date': '2020-01-01'}, 'LG005', 'une date passée', acteur=hub)
    rep = geste('rep-' + t2[:8], 'reschedule_task', {'task_id': t2, 'new_date': demain}, acteur=hub)
    ok(rep['status'] == 'CREATED' and rep['scheduled_date'] == demain, '[%s] la replanification par l\'agent du hub, depuis le téléphone' % lieu)
    ok(f('lg_task_proof', acteur=hub, p_task_id=t2)['proof'] is None, '[%s] une mission sans remise : pas de preuve' % lieu)

    # ====================================================================== E. la tournée terminée par le téléphone
    fin = geste('fin-' + tid[:8], 'complete_trip', {'trip_id': tid})
    ok(fin.get('status') == 'COMPLETED', '[%s] E : tournée terminée depuis le téléphone (%s)' % (lieu, fin))
    detail = f('lg_trip_detail', acteur=chauf, p_trip_id=tid)

    # ====================================================================== les emplacements d'un entrepôt (ranger, transférer)
    q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'TR-W1', 'Entrepôt terrain')" % pap)
    wh = q("select id from logistics.warehouse where code = 'TR-W1'")
    q("insert into logistics.warehouse_location (warehouse_id, code, zone, kind) values ('%s', 'A-01', 'A', 'storage'), ('%s', 'B-02', 'B', 'storage'), ('%s', 'X-99', 'X', 'storage')" % (wh, wh, wh))
    q("update logistics.warehouse_location set active = false where code = 'X-99'")
    emp = f('lg_warehouse_locations', acteur=hub, p_warehouse_id=wh)
    ok([e['code'] for e in emp] == ['A-01', 'B-02'], '[%s] emplacements : les actifs, dans l\'ordre de l\'entrepôt (%s)' % (lieu, emp))
    fr('lg_warehouse_locations', 'LG003', 'un chauffeur sans droit ne lit pas les emplacements', acteur=chauf, p_warehouse_id=wh)
    fr('lg_warehouse_locations', 'LG002', 'un entrepôt inconnu', acteur=hub, p_warehouse_id=R("gen_random_uuid()"))

    # ====================================================================== F. tout fermé
    ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and "
         "(has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))") == '0', '[%s] F : aucune fonction du noyau ouverte' % lieu)
    for fn in ('public.lg_task_proof(uuid)', 'public.lg_warehouse_locations(uuid)'):
        ok(q("select has_function_privilege('authenticated', '%s', 'execute')::text || has_function_privilege('anon', '%s', 'execute')::text" % (fn, fn)) == 'truefalse',
           '[%s] F : %s aux comptes connectés seulement' % (lieu, fn))
    return {
        'formes': {'lg_trip_detail': forme(detail), 'lg_warehouse_locations': forme(emp), 'lg_task_proof': sorted(set(forme(preuve)) | set('proof.' + k for k in preuve['proof'])), 'arrive_stop': forme(a1),
                   # les gestes admis par la porte, relus dans la fonction installée
                   'mobile_commands': sorted(re.findall(r"'([a-z_]+)'", re.search(r"p_command not in \(([^)]*)\)",
                                                        '\n'.join(L("select pg_get_functiondef('logistics.mobile_command(uuid,text,text,jsonb)'::regprocedure)"))).group(1)))},
        'signatures': json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), "
                                   "'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) "
                                   "from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = any (%s)" % val(TERRAIN)))}


def main():
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        cl.run('postgres', "alter database prod set timezone to 'America/Port-au-Prince'")
        etapes = sorted(os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')))
        ok('021-operations-terrain.sql' in etapes, 'l\'étape 021 est dans le noyau')
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        compte = "select (select count(*) from logistics.event_type) || '|' || (select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname in ('logistics', 'public'))"
        n = q(compte)
        cl.run('prod', P.lire_sql('outils/logistique/021-operations-terrain.sql'))
        ok(q(compte) == n, '021 rejouée : rien en double (%s)' % n)
        contrat = parcours(cl, 'prod', 'réplique')
        ok(sorted(contrat['signatures']) == sorted(TERRAIN), 'chaque fonction de terrain de l\'application existe')
        ici = os.path.dirname(os.path.abspath(__file__))
        ch_f, ch_r = os.path.join(ici, 'terrain-formes.json'), os.path.join(ici, 'terrain-rpc.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(contrat['formes'], open(ch_f, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            json.dump(contrat['signatures'], open(ch_r, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        ok(json.load(open(ch_f, encoding='utf-8')) == contrat['formes'] and json.load(open(ch_r, encoding='utf-8')) == contrat['signatures'],
           'formes et signatures = fichiers partagés avec l\'application (sinon : SES_FORME_ECRIRE=1, recopier dans App_SES/tests/)')
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
        print('PASS opérations sur le terrain (phase 9) : %d vérifications — sur la réplique ET la préproduction : même geste rejoué = résultat d\'origine, '
              'ordre incorrect = conflit, permission incorrecte = refus sans clé consommée ; arrivée à l\'arrêt à l\'heure du téléphone, position du seul '
              'moment de l\'arrivée ; tournée démarrée et terminée ; replanification ; preuve lue par l\'équipe (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC opérations sur le terrain (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
