#!/usr/bin/env python3
"""Étape 026 — consolidations, unités logistiques et transbordement depuis le tableau de bord, éprouvés sur la RÉPLIQUE DE LA PRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-unites-essai.py

Les appels exacts du tableau de bord (ses-modules.js), sur des colis REPRIS de l'ancien schéma :
 A. Miami, le HUB de Saint-Domingue (transit) et celui de Port-au-Prince ; des colis aériens pour Haïti préparés au poste de scan ;
 B. consolidation : ouvrir, remplir d'une liste de numéros (chaque refus avec sa raison, les autres entrent), lire ses colis, en retirer un,
    fermer ; la liste rend son identifiant ;
 C. unité logistique : créer, charger, la relire (contenu, mode, pays) ; une consolidation chargée ne part plus seule ; une unité vide ne part
    pas ; retirer avec motif (tracé) ; ce qui peut partir propose l'unité ; l'expédition l'emporte ; on charge encore tant qu'elle est en
    brouillon, plus après ; le départ exige le scellé ;
 D. transbordement : des colis haïtiens arrivés à Saint-Domingue attendent leur étape suivante (lg_awaiting_onward), l'étape suivante les
    emmène, ils n'attendent plus ;
 E. fermé aux clients et aux visiteurs ; 026 rejouée ne change rien ; aucune incohérence.
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


def numeros(l):
    return R("array[%s]::text[]" % ', '.join(val(x) for x in l))


def main():
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('026-unites-transbordement.sql' in etapes, 'l\'étape 026 est dans le noyau')
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        ok(json.loads(q("select logistics.run_migration('unités')"))['report']['ready'] is True, 'rattrapage prêt')
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0026-000000000001', 'authenticated', 'authenticated', 'uni-emp@essai.test', 'x', now(), '{}')")
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.statut'] where email = 'uni-emp@essai.test'")
        q("select logistics.run_migration('unités, employé')")
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        emp = q("select id from public.clients where email = 'uni-emp@essai.test'")
        client = q("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1")

        def appel(nom, acteur, kw):
            return cl.run('prod', 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items())),
                          role='authenticated', claims=acteur, expect_error=True)

        def f(nom, acteur=emp, **kw):
            code, sortie = appel(nom, acteur, kw)
            if code != 0:
                raise AssertionError('%s refusée : %s' % (nom, sortie[-400:]))
            return json.loads(sortie) if sortie.strip() else None

        def refus(nom, attendu, msg, acteur=emp, **kw):
            code, sortie = appel(nom, acteur, kw)
            ok(code != 0 and attendu in sortie, '%s : attendu « %s », obtenu %s' % (msg, attendu, sortie[-240:]))

        def statut(table, i):
            return q("select status from logistics.%s where id = '%s'" % (table, i))

        # ============================================================ A. les lieux, des colis prêts
        mia = f('lg_create_branch', admin, p_code='MIA', p_name='Miami', p_kind='office', p_country='US', p_city='Doral')['branch_id']
        sdq = f('lg_create_branch', admin, p_code='SDQ-HUB', p_name='Hub Saint-Domingue', p_kind='hub', p_country='DO', p_city='Santo Domingo')['branch_id']
        pap = f('lg_create_branch', admin, p_code='PAP-HUB', p_name='Hub Port-au-Prince', p_kind='hub', p_country='HT', p_city='Port-au-Prince')['branch_id']
        wm = f('lg_create_warehouse', admin, p_branch_id=mia, p_code='MIA-1', p_name='Doral')['warehouse_id']
        wsdq = f('lg_create_warehouse', admin, p_branch_id=sdq, p_code='SDQ-1', p_name='Hub SDQ')['warehouse_id']
        etagere = f('lg_create_location', admin, p_warehouse_id=wm, p_code='A-01', p_zone='A', p_kind='staging')['location_id']
        cand = cl.lignes('prod', "select tracking_number from logistics.parcel where status = 'CREATED' and service_mode = 'air' and destination_country = 'HT' "
                                 "and customer_id is not null and coalesce(verified_weight_lb, weight_lb) > 0 order by tracking_number limit 5")
        ok(len(cand) == 5, 'cinq colis aériens pour Haïti, repris de l\'ancien schéma')
        n, pas_pret = cand[:4], cand[4]
        prep = f('lg_prepare_parcels', p_tracking_numbers=numeros(n), p_warehouse_id=wm, p_location_id=etagere)
        ok(prep['prepared'] == 4, 'quatre colis préparés au départ : %s' % prep)
        ident = {x: q("select id from logistics.parcel where tracking_number = %s" % val(x)) for x in cand}

        # ============================================================ B. la consolidation
        c1 = f('lg_open_consolidation', p_code='CONS-HT-1', p_warehouse_id=wm, p_destination_country='HT', p_mode='air')['consolidation_id']
        r = f('lg_fill_consolidation', p_consolidation_id=c1, p_tracking_numbers=numeros([n[0], n[1].lower(), n[0], pas_pret, 'SES-0000000000', ' ']))
        par = {x['code']: x for x in r['results']}
        ok(r['added'] == 2 and r['parcels'] == 2 and par[n[0]]['added'] and par[n[1]]['added'], 'deux colis entrent (numéro en minuscules compris) : %s' % r)
        ok(len(r['results']) == 4, 'un numéro répété ou vide ne compte qu\'une fois / pas du tout')
        ok(par[pas_pret]['reason'] == 'WRONG_STATE' and par[pas_pret]['status'] == 'CREATED', 'un colis pas encore préparé : WRONG_STATE, avec son statut')
        ok(par['SES-0000000000']['reason'] == 'NOT_FOUND', 'un numéro inconnu : NOT_FOUND, sans bloquer les autres')
        r = f('lg_fill_consolidation', p_consolidation_id=c1, p_tracking_numbers=numeros([n[0]]))
        ok(r['added'] == 0 and r['results'][0]['reason'] == 'IN_CONSOLIDATION', 'un colis déjà consolidé : IN_CONSOLIDATION')
        lc = f('lg_consolidation_parcels', p_consolidation_id=c1)
        ok(sorted(x['tracking_number'] for x in lc) == sorted(n[:2]) and all(x['customer']['code'] and x['parcel_id'] for x in lc), 'ses colis : numéro, client, identifiant')
        ok(appel('lg_remove_parcel_from_consolidation', emp, {'p_consolidation_id': c1, 'p_parcel_id': ident[n[1]]})[0] == 0, 'retirer un colis (la fonction ne rend rien)')
        ok(len(f('lg_consolidation_parcels', p_consolidation_id=c1)) == 1, 'un colis retiré')
        ok(f('lg_fill_consolidation', p_consolidation_id=c1, p_tracking_numbers=numeros([n[1]]))['added'] == 1, 'puis remis')
        f('lg_close_consolidation', p_consolidation_id=c1)
        ok(statut('consolidation', c1) == 'CLOSED' and statut('parcel', ident[n[0]]) == 'CONSOLIDATED', 'fermée : ses colis sont consolidés')
        refus('lg_fill_consolidation', 'LG004', 'une consolidation fermée ne se remplit plus', p_consolidation_id=c1, p_tracking_numbers=numeros([n[2]]))
        item = [x for x in f('lg_cc_consolidations')['items'] if x['code'] == 'CONS-HT-1'][0]
        ok(item['consolidation_id'] == c1 and item['load_unit'] is None and item['parcels'] == 2, 'la liste rend l\'identifiant et l\'unité (aucune)')

        # ============================================================ C. l'unité logistique
        u1 = f('lg_create_load_unit', p_code='pal-1', p_kind='PALLET', p_max_weight_lb=2000)['load_unit_id']
        vide = f('lg_create_load_unit', p_code='PAL-VIDE', p_kind='PALLET')['load_unit_id']
        lu = {x['code']: x for x in f('lg_cc_load_units')['items']}
        ok(lu['PAL-1']['load_unit_id'] == u1 and lu['PAL-1']['status'] == 'OPEN' and lu['PAL-1']['consolidations'] == [] and lu['PAL-1']['mode'] is None,
           'la liste des unités : identifiant, code en majuscules, ouverte, vide')
        ok(f('lg_ready_for_shipment', p_mode='air')['load_units'] == [], 'une unité vide n\'est pas proposée au départ')
        f('lg_put_consolidation_in_load_unit', p_consolidation_id=c1, p_load_unit_id=u1)
        lu = {x['code']: x for x in f('lg_cc_load_units')['items']}
        ok(lu['PAL-1']['mode'] == 'air' and lu['PAL-1']['destination_country'] == 'HT' and lu['PAL-1']['parcels'] == 2
           and lu['PAL-1']['consolidations'][0]['code'] == 'CONS-HT-1', 'chargée : son mode, son pays, ses colis, sa consolidation')
        ok([x for x in f('lg_cc_consolidations')['items'] if x['code'] == 'CONS-HT-1'][0]['load_unit']['code'] == 'PAL-1', 'la consolidation dit dans quelle unité elle est')
        pret = f('lg_ready_for_shipment', p_mode='air')
        ok([x['code'] for x in pret['consolidations']] == [] and [x['code'] for x in pret['load_units']] == ['PAL-1'] and pret['load_units'][0]['parcels'] == 2,
           'ce qui peut partir : l\'unité, plus sa consolidation seule')
        ok(f('lg_ready_for_shipment', p_mode='sea')['load_units'] == [], 'rien en maritime')
        refus('lg_create_shipment', 'expédiez l\'unité', 'une consolidation chargée ne part pas seule', p_code='EXP-X', p_mode='air', p_origin_branch=mia,
              p_destination_branch=pap, p_consolidation_ids=[c1])
        refus('lg_create_shipment', 'vide', 'une unité vide ne part pas', p_code='EXP-X', p_mode='air', p_origin_branch=mia, p_destination_branch=pap, p_load_unit_ids=[vide])
        refus('lg_create_shipment', 'mode', 'une unité aérienne ne part pas en bateau', p_code='EXP-X', p_mode='sea', p_origin_branch=mia, p_destination_branch=pap,
              p_load_unit_ids=[u1])
        refus('lg_remove_consolidation_from_load_unit', 'motif', 'retirer sans motif', p_consolidation_id=c1, p_reason='  ')
        f('lg_remove_consolidation_from_load_unit', p_consolidation_id=c1, p_reason='Mauvaise palette')
        ok(q("select load_unit_id is null from logistics.consolidation where id = '%s'" % c1) == 't'
           and q("select count(*) from logistics.audit_log where action = 'load_unit.unload' and entity_id = '%s' and after ->> 'reason' = 'Mauvaise palette'" % u1) == '1',
           'retirée, et tracé avec son motif')
        refus('lg_remove_consolidation_from_load_unit', 'aucune unité', 'retirer une consolidation qui n\'est dans aucune unité', p_consolidation_id=c1, p_reason='x')
        f('lg_put_consolidation_in_load_unit', p_consolidation_id=c1, p_load_unit_id=u1)
        exp = f('lg_create_shipment', p_code='EXP-PAL-1', p_mode='air', p_origin_branch=mia, p_destination_branch=pap, p_load_unit_ids=[u1], p_idempotency_key='uni-exp-1')
        sid = exp['shipment_id']
        ok(exp['parcels'] == 2, 'l\'expédition emporte l\'unité et ses deux colis')
        ok(f('lg_ready_for_shipment', p_mode='air')['load_units'] == [], 'partie dans une expédition, l\'unité n\'est plus proposée')
        lu = {x['code']: x for x in f('lg_cc_load_units')['items']}
        ok(lu['PAL-1']['shipment']['code'] == 'EXP-PAL-1' and lu['PAL-1']['shipment']['status'] == 'DRAFT', 'la liste des unités dit avec quelle expédition elle part')
        ok([x for x in f('lg_cc_consolidations')['items'] if x['code'] == 'CONS-HT-1'][0]['shipment'] == 'EXP-PAL-1', 'la consolidation aussi (par son unité)')
        # une seconde consolidation, chargée tant que l'expédition est en brouillon
        c2 = f('lg_open_consolidation', p_code='CONS-HT-2', p_warehouse_id=wm, p_destination_country='HT', p_mode='air')['consolidation_id']
        f('lg_fill_consolidation', p_consolidation_id=c2, p_tracking_numbers=numeros([n[2]]))
        f('lg_close_consolidation', p_consolidation_id=c2)
        f('lg_put_consolidation_in_load_unit', p_consolidation_id=c2, p_load_unit_id=u1)
        ok(len(f('lg_shipment_parcels', p_shipment_id=sid)) == 3, 'chargée pendant le brouillon : l\'expédition compte trois colis')
        f('lg_generate_manifest', p_shipment_id=sid)
        f('lg_mark_shipment_ready', p_shipment_id=sid)
        refus('lg_remove_consolidation_from_load_unit', 'LG004', 'rien ne se retire d\'une unité dont l\'expédition est prête', p_consolidation_id=c2, p_reason='x')
        c3 = f('lg_open_consolidation', p_code='CONS-HT-3', p_warehouse_id=wm, p_destination_country='HT', p_mode='air')['consolidation_id']
        refus('lg_put_consolidation_in_load_unit', 'FERMER', 'charger une consolidation ouverte', p_consolidation_id=c3, p_load_unit_id=u1)
        t1 = f('lg_create_transport', p_mode='air', p_carrier='Sunrise Airways', p_reference='AWB-1', p_voyage_number='2Q-1', p_origin_branch=mia, p_destination_branch=pap,
               p_planned_departure=R("now() + interval '1 hour'"), p_planned_arrival=R("now() + interval '4 hours'"))['transport_id']
        refus('lg_dispatch_shipment', 'scellée', 'pas de départ sans scellé', p_shipment_id=sid, p_transport_id=t1)
        f('lg_seal_load_unit', p_load_unit_id=u1, p_seal_number='sl-77')
        refus('lg_remove_consolidation_from_load_unit', 'scellée', 'rien ne se retire d\'une unité scellée', p_consolidation_id=c2, p_reason='x')
        f('lg_dispatch_shipment', p_shipment_id=sid, p_transport_id=t1)
        ok(statut('shipment', sid) == 'DISPATCHED' and {x['code']: x for x in f('lg_cc_load_units')['items']}['PAL-1']['seal_number'] == 'SL-77',
           'scellée (SL-77), l\'unité part avec son expédition')

        # ============================================================ D. le transbordement
        loose = f('lg_create_shipment', p_code='EXP-SDQ-1', p_mode='air', p_origin_branch=mia, p_destination_branch=sdq, p_parcel_ids=[ident[n[3]]])['shipment_id']
        f('lg_generate_manifest', p_shipment_id=loose)
        f('lg_mark_shipment_ready', p_shipment_id=loose)
        t2 = f('lg_create_transport', p_mode='air', p_carrier='Arajet', p_reference='AWB-2', p_voyage_number='DM-2', p_origin_branch=mia, p_destination_branch=sdq,
               p_planned_departure=R("now() + interval '1 hour'"), p_planned_arrival=R("now() + interval '4 hours'"))['transport_id']
        f('lg_dispatch_shipment', p_shipment_id=loose, p_transport_id=t2)
        f('lg_mark_shipment_in_transit', p_shipment_id=loose)
        ok(f('lg_awaiting_onward') == [], 'en vol, rien n\'attend encore à un hub')
        f('lg_arrive_shipment', p_shipment_id=loose)
        ok(statut('parcel', ident[n[3]]) == 'IN_TRANSIT', 'arrivé à Saint-Domingue, le colis haïtien reste EN TRANSIT')
        att = f('lg_awaiting_onward')
        ok(len(att) == 1 and att[0]['parcel_id'] == ident[n[3]] and att[0]['hub']['code'] == 'SDQ-HUB' and att[0]['from_shipment']['code'] == 'EXP-SDQ-1'
           and att[0]['destination_country'] == 'HT' and att[0]['customer']['code'] and att[0]['mode'] == 'air',
           'il attend son étape suivante : hub, expédition d\'arrivée, pays, client : %s' % att)
        ok(len(f('lg_awaiting_onward', p_hub_branch=sdq)) == 1 and f('lg_awaiting_onward', p_hub_branch=pap) == [], 'filtré par hub')
        s2 = f('lg_create_onward_shipment', p_code='EXP-SDQ-PAP', p_mode='ground', p_origin_branch=sdq, p_destination_branch=pap, p_parcel_ids=[ident[n[3]]],
               p_idempotency_key='uni-onward-1')
        ok(s2['status'] == 'DRAFT' and f('lg_awaiting_onward') == [], 'l\'étape suivante l\'emmène : il n\'attend plus')

        # ============================================================ E. fermé, cohérent, rejouable
        for nom, kw in (('lg_cc_load_units', {}), ('lg_awaiting_onward', {}), ('lg_consolidation_parcels', {'p_consolidation_id': c1})):
            refus(nom, 'LG003', '%s : un client ne lit rien' % nom, acteur=client, **kw)
        refus('lg_fill_consolidation', 'LG003', 'un client ne remplit rien', acteur=client, p_consolidation_id=c3, p_tracking_numbers=numeros([n[0]]))
        refus('lg_remove_consolidation_from_load_unit', 'LG003', 'un client ne retire rien', acteur=client, p_consolidation_id=c2, p_reason='x')
        code, sortie = cl.run('prod', 'select public.lg_cc_load_units()', role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in sortie, 'un visiteur ne lit rien')
        ok(q('select count(*) from logistics.workflow_inconsistencies()') == '0', 'aucune incohérence')
        avant = q("select count(*) || '/' || count(load_unit_id) from logistics.consolidation")
        cl.run('prod', P.lire_sql('outils/logistique/026-unites-transbordement.sql'))
        ok(q("select count(*) || '/' || count(load_unit_id) from logistics.consolidation") == avant and len(f('lg_cc_load_units')['items']) == 2, '026 rejouée : rien ne change')
        print('PASS consolidations, unités et transbordement (étape 026) : %d vérifications — sur des colis repris de l\'ancien schéma : remplir par numéros '
              'avec la raison de chaque refus, unité chargée / retirée avec motif / scellée, une consolidation ne part jamais deux fois, étape suivante '
              'depuis un hub de transit (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC unités et transbordement (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
