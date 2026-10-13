#!/usr/bin/env python3
"""Étape 024 — les écrans des expéditions et des transports, éprouvés de bout en bout sur la RÉPLIQUE DE LA PRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-expeditions-essai.py

Exactement les appels que fait le tableau de bord (ses-expeditions.js), dans l'ordre d'une vraie journée, sur des colis REPRIS de
l'ancien schéma (pas des colis fabriqués) :
 A. la direction crée Miami et le HUB de Port-au-Prince, un entrepôt à chacun (étape 023) ; un employé reçoit puis marque
    « à consolider » deux colis aériens pour Haïti au poste de scan ;
 B. lg_ready_for_shipment ne propose QUE ce que create_shipment acceptera (le mode, le statut, un client, hors consolidation) ;
 C. créer l'expédition (clé d'idempotence : un double clic ne crée rien de plus), la relire dans la liste avec son IDENTIFIANT,
    lire ses colis ; planifier ; créer le transport et le relire avec le sien, sa capacité et sa charge ;
 D. manifeste → prête → partie sur le transport → en transit → arrivée → douane (droits, payés, libérée) → reçue au HUB (la clôture attend
    que ses colis aient quitté le HUB) ;
    à chaque pas, le statut de l'expédition et celui de ses colis sont ceux de la base ; un geste hors d'ordre est refusé ;
 E. rien d'ouvert aux visiteurs ni aux clients ; 024 rejouée ne change rien.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


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
    if isinstance(v, list):
        return "array[%s]::uuid[]" % ', '.join("'%s'" % x for x in v) if v else "'{}'::uuid[]"
    return "'%s'" % str(v).replace("'", "''")


def main():
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('024-ecrans-expeditions.sql' in etapes, 'l\'étape 024 est dans le noyau')
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        ok(json.loads(q("select logistics.run_migration('expéditions')"))['report']['ready'] is True, 'rattrapage prêt')
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0024-000000000001', 'authenticated', 'authenticated', 'exp-emp@essai.test', 'x', now(), '{}')")
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.statut'] where email = 'exp-emp@essai.test'")
        q("select logistics.run_migration('expéditions, employé')")
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        emp = q("select id from public.clients where email = 'exp-emp@essai.test'")
        client = q("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1")

        def appel(nom, acteur, kw):
            return cl.run('prod', 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items())),
                          role='authenticated', claims=acteur, expect_error=True)

        def f(nom, acteur=emp, **kw):
            code, sortie = appel(nom, acteur, kw)
            if code != 0:
                raise AssertionError('%s refusée : %s' % (nom, sortie[-400:]))
            return json.loads(sortie)

        def refus(nom, code_attendu, msg, acteur=emp, **kw):
            code, sortie = appel(nom, acteur, kw)
            ok(code != 0 and code_attendu in sortie, '%s : attendu %s, obtenu %s' % (msg, code_attendu, sortie[-200:]))

        def statut(sid):
            return q("select status from logistics.shipment where id = '%s'" % sid)

        # ============================================================ A. les lieux, deux colis prêts
        mia = f('lg_create_branch', admin, p_code='MIA', p_name='Miami', p_kind='office', p_country='US', p_city='Doral')
        pap = f('lg_create_branch', admin, p_code='PAP-HUB', p_name='Hub Port-au-Prince', p_kind='hub', p_country='HT', p_city='Port-au-Prince')
        wm = f('lg_create_warehouse', admin, p_branch_id=mia['branch_id'], p_code='MIA-1', p_name='Doral')
        wp = f('lg_create_warehouse', admin, p_branch_id=pap['branch_id'], p_code='PAP-1', p_name='Hub PAP')
        numeros = cl.lignes('prod', "select tracking_number from logistics.parcel where status = 'CREATED' and service_mode = 'air' and destination_country = 'HT' "
                                    "and customer_id is not null order by tracking_number limit 3")
        ok(len(numeros) == 3, 'trois colis aériens pour Haïti, repris de l\'ancien schéma')
        etagere = f('lg_create_location', admin, p_warehouse_id=wm['warehouse_id'], p_code='A-01', p_zone='A', p_kind='staging')
        # « Préparer au départ » : reçu → vérifié (poids connu) → rangé → à consolider, par les gestes officiels du poste de scan
        sans_poids = q("select tracking_number from logistics.parcel where status = 'CREATED' and service_mode = 'air' and destination_country = 'HT' "
                       "and customer_id is not null and tracking_number not in (%s) order by tracking_number limit 1" % ','.join(val(n) for n in numeros))
        q("update logistics.parcel set weight_lb = null where tracking_number = %s" % val(sans_poids))
        prep = f('lg_prepare_parcels', p_tracking_numbers=R("array[%s, %s, %s, 'SES-0000000000']::text[]" % (val(numeros[0]), val(numeros[1].lower()), val(sans_poids))),
                 p_warehouse_id=wm['warehouse_id'], p_location_id=etagere['location_id'])
        res = {r['code']: r for r in prep['results']}
        ok(prep['prepared'] == 2 and res[numeros[0]]['ready'] and res[numeros[1]]['ready'], 'deux colis préparés (numéro en minuscules compris) : %s' % prep)
        ok(res[sans_poids]['reason'] == 'NO_WEIGHT' and res[sans_poids]['status'] == 'RECEIVED', 'sans poids : reçu, puis arrêté — à peser')
        ok(res['SES-0000000000']['reason'] == 'NOT_FOUND', 'un numéro inconnu est signalé, sans bloquer les autres')
        ok(q("select string_agg(purpose || ':' || result, ',' order by purpose) from logistics.scan where parcel_id = (select id from logistics.parcel where tracking_number = %s)"
             % val(numeros[0])) == 'consolidate:ACCEPTED,receive:ACCEPTED,store:ACCEPTED,verify:ACCEPTED'
           and q("select count(*) from logistics.parcel_inspection where parcel_id = (select id from logistics.parcel where tracking_number = %s)" % val(numeros[0])) == '1',
           'chaque geste est tracé comme au poste de scan (quatre scans, dont celui de la pesée, et une pesée)')
        refus('lg_prepare_parcels', 'LG005', 'l\'emplacement doit être de cet entrepôt', p_tracking_numbers=R("array['X']::text[]"), p_warehouse_id=wm['warehouse_id'],
              p_location_id=f('lg_create_location', admin, p_warehouse_id=wp['warehouse_id'], p_code='B-01')['location_id'])
        refus('lg_prepare_parcels', 'LG003', 'un client ne prépare rien', acteur=client, p_tracking_numbers=R("array['X']::text[]"), p_warehouse_id=wm['warehouse_id'],
              p_location_id=etagere['location_id'])
        f('lg_scan_parcel', p_code=numeros[2], p_purpose='receive', p_warehouse_id=wm['warehouse_id'], p_idempotency_key='exp-receive-3')

        # ============================================================ B. ce qui peut partir
        pret = f('lg_ready_for_shipment', p_mode='air')
        ok(sorted(p['tracking_number'] for p in pret['parcels']) == sorted(numeros[:2]), 'seuls les deux colis « à consolider » sont proposés (pas le reçu)')
        ok(all(p['parcel_id'] and p['customer']['code'] and p['destination_country'] == 'HT' and p['warehouse'] == 'MIA-1' for p in pret['parcels']),
           'chaque colis proposé : identifiant, client, destination, entrepôt')
        ok(f('lg_ready_for_shipment', p_mode='sea')['parcels'] == [], 'rien en maritime')
        ids = [p['parcel_id'] for p in pret['parcels']]

        # ============================================================ C. créer, relire, planifier ; le transport
        exp = f('lg_create_shipment', p_code='EXP-ESSAI-1', p_mode='air', p_origin_branch=mia['branch_id'], p_destination_branch=pap['branch_id'],
                p_parcel_ids=ids, p_idempotency_key='exp-creer-1')
        bis = f('lg_create_shipment', p_code='EXP-ESSAI-1', p_mode='air', p_origin_branch=mia['branch_id'], p_destination_branch=pap['branch_id'],
                p_parcel_ids=ids, p_idempotency_key='exp-creer-1')
        ok(bis['shipment_id'] == exp['shipment_id'] and q("select count(*) from logistics.shipment") == '1', 'un double clic ne crée pas une seconde expédition')
        sid = exp['shipment_id']
        liste = f('lg_cc_shipments')
        ok(liste['items'][0]['shipment_id'] == sid and liste['items'][0]['code'] == 'EXP-ESSAI-1' and liste['items'][0]['status'] == 'DRAFT',
           'la liste rend l\'expédition AVEC son identifiant')
        ok(f('lg_ready_for_shipment', p_mode='air')['parcels'] == [], 'partis dans l\'expédition, les colis ne sont plus proposés')
        colis = f('lg_shipment_parcels', p_shipment_id=sid)
        ok(sorted(c['tracking_number'] for c in colis) == sorted(numeros[:2]) and all(c['status'] == 'CONSOLIDATED' for c in colis),
           'les colis de l\'expédition : numéros, statut CONSOLIDATED')
        f('lg_plan_shipment', p_shipment_id=sid, p_planned_departure=R("now() + interval '1 hour'"), p_planned_arrival=R("now() + interval '5 hours'"),
          p_hub_warehouse_id=wp['warehouse_id'])
        t = f('lg_create_transport', p_mode='air', p_carrier='Sunrise Airways', p_reference='AWB-123-45678901', p_voyage_number='2Q-101',
              p_origin_branch=mia['branch_id'], p_destination_branch=pap['branch_id'], p_planned_departure=R("now() + interval '1 hour'"),
              p_planned_arrival=R("now() + interval '4 hours'"), p_capacity_weight_lb=500)
        tid = t['transport_id']
        lt = f('lg_cc_transports')['items'][0]
        ok(lt['transport_id'] == tid and lt['voyage_number'] == '2Q-101' and float(lt['capacity_weight_lb']) == 500 and float(lt['load_weight_lb']) == 0,
           'la liste des transports : identifiant, numéro de voyage, capacité, charge')
        f('lg_schedule_transport', p_transport_id=tid, p_planned_departure=R("now() + interval '2 hours'"), p_planned_arrival=R("now() + interval '6 hours'"))
        refus('lg_create_transport', 'LG005', 'un camion ne relie pas Miami', p_mode='ground', p_carrier='X', p_reference='T1', p_voyage_number='',
              p_origin_branch=mia['branch_id'], p_destination_branch=pap['branch_id'], p_planned_departure=R('now()'), p_planned_arrival=R("now() + interval '1 day'"))

        # ============================================================ D. le voyage
        refus('lg_dispatch_shipment', 'LG001', 'une expédition en brouillon ne part pas', p_shipment_id=sid, p_transport_id=tid)
        f('lg_generate_manifest', p_shipment_id=sid)
        f('lg_mark_shipment_ready', p_shipment_id=sid)
        ok(statut(sid) == 'READY', 'manifeste puis PRÊTE')
        f('lg_dispatch_shipment', p_shipment_id=sid, p_transport_id=tid, p_idempotency_key='exp-partir-1')
        ok(statut(sid) == 'DISPATCHED' and float(f('lg_cc_transports')['items'][0]['load_weight_lb']) > 0, 'PARTIE sur le transport, dont la charge monte')
        f('lg_mark_shipment_in_transit', p_shipment_id=sid)
        f('lg_arrive_shipment', p_shipment_id=sid)
        ok(statut(sid) == 'ARRIVED' and all(c['status'] == 'ARRIVED' for c in f('lg_shipment_parcels', p_shipment_id=sid)), 'ARRIVÉE ; ses colis aussi')
        refus('lg_receive_at_hub', 'LG', 'pas de réception au HUB avant la douane', p_shipment_id=sid)
        f('lg_start_customs', p_shipment_id=sid, p_reference='DEC-2026-001', p_broker='Courtier Port-au-Prince')
        f('lg_customs_assess_duties', p_shipment_id=sid, p_amount=125.5, p_currency='USD')
        refus('lg_clear_customs', 'LG005', 'droits impayés : pas de libération', p_shipment_id=sid)
        f('lg_customs_mark_duties_paid', p_shipment_id=sid)
        f('lg_clear_customs', p_shipment_id=sid, p_reference='MAINLEVEE-1')
        ok(statut(sid) == 'CUSTOMS_CLEARED', 'droits payés, LIBÉRÉE')
        f('lg_receive_at_hub', p_shipment_id=sid, p_hub_warehouse_id=wp['warehouse_id'])
        ok(statut(sid) == 'AT_HUB' and all(c['status'] == 'AT_DESTINATION_HUB' for c in f('lg_shipment_parcels', p_shipment_id=sid)),
           'reçue au HUB ; ses colis sont au HUB de destination')
        refus('lg_close_shipment', 'LG005', 'tant que ses colis attendent au HUB, l\'expédition ne se clôture pas (ils partent en livraison d\'abord)', p_shipment_id=sid)
        fiche = f('lg_shipment_summary', p_shipment_id=sid)
        ok(fiche['transport']['voyage_number'] == '2Q-101' and fiche['customs']['duties_paid'] is True, 'la fiche relit le transport et la douane')

        # ============================================================ E. fermé, rejouable
        refus('lg_ready_for_shipment', 'LG003', 'un client ne lit pas ce qui peut partir', acteur=client, p_mode='air')
        refus('lg_shipment_parcels', 'LG003', 'un client ne lit pas les colis d\'une expédition', acteur=client, p_shipment_id=sid)
        code, sortie = cl.run('prod', "select public.lg_ready_for_shipment('air')", role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in sortie, 'un visiteur ne lit rien')
        avant = q("select count(*) from logistics.shipment")
        cl.run('prod', P.lire_sql('outils/logistique/024-ecrans-expeditions.sql'))
        ok(q("select count(*) from logistics.shipment") == avant and f('lg_cc_shipments')['items'][0]['shipment_id'] == sid, '024 rejouée : rien ne change')
        print('PASS expéditions et transports (étape 024) : %d vérifications — de bout en bout sur des colis repris de l\'ancien schéma : scan, ce qui peut '
              'partir, création sans doublon, identifiants dans les listes, transport et capacité, manifeste, départ, arrivée, douane, HUB '
              '(PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC expéditions et transports (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
