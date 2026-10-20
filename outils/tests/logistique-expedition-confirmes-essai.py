#!/usr/bin/env python3
"""Étape 031 — expédier les colis confirmés, éprouvé sur la RÉPLIQUE DE LA PRODUCTION (001 → 031, recopie allumée, colisNoyau éteint).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-expedition-confirmes-essai.py

Demande du propriétaire : l'onglet Colis garde l'ancien parcours (confirmé, expédié, disponible, livré) ; la fenêtre « Nouvelle expédition »
propose TOUS les colis confirmés, à sélectionner.
 A. un colis enregistré dans l'onglet Colis (ancien schéma, « confirmé ») apparaît dans la fenêtre, avec ses colis déjà prêts ;
 B. créer l'expédition avec lui : la base le prépare (reçu, vérifié, rangé, à consolider) PUIS crée l'expédition, dans une transaction ;
 C. tout ou rien : un colis sans poids et rien n'est fait, avec la raison ; entrepôt et emplacement exigés ; droits ;
 D. le voyage : départ → « expédié » dans l'onglet Colis, arrivée au HUB → « disponible » (le reflet de 030), sans ancien historique en double ;
 E. l'onglet Colis ne peut plus changer à la main le statut d'un colis qui suit son expédition (SE005) ; les autres colis, si (ancien parcours) ;
 F. rattrapage prêt, rejeu sans effet, portes.
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
        B = 'prod'
        if not P.monter_production(cl, B):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('031-expedition-colis-confirmes.sql' in etapes, 'l\'étape 031 est dans le noyau')
        for f_ in etapes:
            cl.run(B, P.lire_sql('outils/logistique/' + f_))
        cl.run(B, P.lire_sql('outils/logistique/031-expedition-colis-confirmes.sql'))
        ok(True, '031 chargée deux fois de suite')
        q = lambda sql: cl.un(B, sql)   # noqa: E731
        rapport = lambda: json.loads(q("select logistics.run_migration('expédition des confirmés')"))['report']   # noqa: E731
        ok(rapport()['ready'] is True, 'rattrapage prêt')
        q('select logistics.set_double_write(true)')
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0031-000000000001', 'authenticated', 'authenticated', 'exp31@essai.test', 'x', now(), '{}')")
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.statut', 'colis.creer', 'colis.modifier'] where email = 'exp31@essai.test'")
        rapport()
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        emp = q("select id from public.clients where email = 'exp31@essai.test'")
        cliente = q("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1")

        def appel(nom, acteur, kw):
            return cl.run(B, 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items())), role='authenticated', claims=acteur, expect_error=True)

        def f(nom, acteur=emp, **kw):
            code, sortie = appel(nom, acteur, kw)
            if code != 0:
                raise AssertionError('%s refusée : %s' % (nom, sortie[-400:]))
            return json.loads(sortie)

        def refus(nom, code_attendu, msg, acteur=emp, **kw):
            code, sortie = appel(nom, acteur, kw)
            ok(code != 0 and code_attendu in sortie, '%s : attendu %s, obtenu %s' % (msg, code_attendu, sortie[-220:]))

        # le décor : Miami (entrepôt, emplacement), le HUB de Port-au-Prince
        mia = f('lg_create_branch', admin, p_code='MIA', p_name='Miami', p_kind='office', p_country='US', p_city='Doral')
        pap = f('lg_create_branch', admin, p_code='PAP-HUB', p_name='Hub Port-au-Prince', p_kind='hub', p_country='HT', p_city='Port-au-Prince')
        wm = f('lg_create_warehouse', admin, p_branch_id=mia['branch_id'], p_code='MIA-1', p_name='Doral')
        wp = f('lg_create_warehouse', admin, p_branch_id=pap['branch_id'], p_code='PAP-1', p_name='Hub PAP')
        loc = f('lg_create_location', admin, p_warehouse_id=wm['warehouse_id'], p_code='A-01', p_zone='A', p_kind='staging')

        # ============================================================ A. l'onglet Colis (ancien schéma) enregistre deux colis « confirmés »
        def colis_ancien(desc, poids):
            return q("insert into public.colis (client_id, description, poids_lb, tarif_lb, service, pays_destination, ville_destination) "
                     "values ('%s', '%s', %s, 3, 'aerien', 'HT', 'Delmas') returning id" % (cliente, desc, poids))
        c1, c2, c3 = colis_ancien('Chaussures', 4), colis_ancien('Livres', 2.5), colis_ancien('Sans poids', 'null')
        q('select logistics.process_sync_queue()')
        num = {c: q("select numero from public.colis where id = '%s'" % c) for c in (c1, c2, c3)}
        pret = f('lg_ready_for_shipment', p_mode='air')
        conf = {x['tracking_number']: x for x in pret['confirmed']}
        ok(all(num[c] in conf for c in (c1, c2, c3)), 'les colis confirmés de l\'onglet Colis apparaissent dans la fenêtre « Nouvelle expédition »')
        ok(all(conf[num[c]]['status'] == 'CREATED' and conf[num[c]]['parcel_id'] and conf[num[c]]['customer']['code'] for c in (c1, c2)),
           'chacun avec son identifiant, son client, son statut')
        ok(f('lg_ready_for_shipment', p_mode='sea')['confirmed'] == [] or all(x['mode'] == 'sea' for x in f('lg_ready_for_shipment', p_mode='sea')['confirmed']),
           'le mode filtre la liste')
        ids = [conf[num[c]]['parcel_id'] for c in (c1, c2)]

        # ============================================================ C. tout ou rien, et les exigences
        avec_sans_poids = [conf[num[c]]['parcel_id'] for c in (c1, c3)]
        refus('lg_create_shipment_prepared', 'LG005', 'un colis sans poids : rien n\'est fait', p_code='EXP-31-X', p_mode='air', p_origin_branch=mia['branch_id'],
              p_destination_branch=pap['branch_id'], p_confirmed_ids=avec_sans_poids, p_warehouse_id=wm['warehouse_id'], p_location_id=loc['location_id'])
        ok(q("select status from logistics.parcel where legacy_parcel_id = '%s'" % c1) == 'CREATED' and q("select count(*) from logistics.shipment") == '0',
           'tout ou rien : le colis qui pouvait être préparé ne l\'a pas été, aucune expédition')
        code, sortie = appel('lg_create_shipment_prepared', emp, {'p_code': 'EXP-31-X', 'p_mode': 'air', 'p_origin_branch': mia['branch_id'], 'p_destination_branch': pap['branch_id'],
                                                                   'p_confirmed_ids': avec_sans_poids, 'p_warehouse_id': wm['warehouse_id'], 'p_location_id': loc['location_id']})
        ok(num[c3] in sortie, 'la raison nomme le colis en cause : %s' % sortie[-160:])
        refus('lg_create_shipment_prepared', 'LG005', 'sans entrepôt ni emplacement', p_code='EXP-31-X', p_mode='air', p_origin_branch=mia['branch_id'],
              p_destination_branch=pap['branch_id'], p_confirmed_ids=ids)
        refus('lg_create_shipment_prepared', 'LG003', 'une cliente ne crée pas d\'expédition', acteur=cliente, p_code='EXP-31-X', p_mode='air', p_origin_branch=mia['branch_id'],
              p_destination_branch=pap['branch_id'], p_confirmed_ids=ids, p_warehouse_id=wm['warehouse_id'], p_location_id=loc['location_id'])

        # ============================================================ B. créer l'expédition avec les confirmés
        histo0 = int(q("select count(*) from public.colis_historique where colis_id in ('%s', '%s')" % (c1, c2)))
        exp = f('lg_create_shipment_prepared', p_code='EXP-31-1', p_mode='air', p_origin_branch=mia['branch_id'], p_destination_branch=pap['branch_id'],
                p_confirmed_ids=ids, p_warehouse_id=wm['warehouse_id'], p_location_id=loc['location_id'], p_idempotency_key='exp31-creer')
        sid = exp['shipment_id']
        ok(sid and sorted(c['tracking_number'] for c in f('lg_shipment_parcels', p_shipment_id=sid)) == sorted([num[c1], num[c2]]),
           'l\'expédition est créée avec les deux colis confirmés')
        ok(q("select string_agg(status_authority, ',') from logistics.parcel where legacy_parcel_id in ('%s', '%s')" % (c1, c2)) == 'core,core',
           'préparés par la base : ils suivent désormais leur expédition (autorité du noyau)')
        ok(q("select string_agg(statut, ',') from public.colis where id in ('%s', '%s')" % (c1, c2)) == 'confirme,confirme', 'l\'onglet Colis les montre toujours « confirmés »')
        bis = f('lg_create_shipment_prepared', p_code='EXP-31-1', p_mode='air', p_origin_branch=mia['branch_id'], p_destination_branch=pap['branch_id'],
                p_confirmed_ids=ids, p_warehouse_id=wm['warehouse_id'], p_location_id=loc['location_id'], p_idempotency_key='exp31-creer')
        ok(bis['shipment_id'] == sid and q("select count(*) from logistics.shipment") == '1', 'un double clic ne crée pas une seconde expédition')
        reste = {x['tracking_number'] for x in f('lg_ready_for_shipment', p_mode='air')['confirmed']}
        ok(num[c1] not in reste and num[c3] in reste, 'partis dans l\'expédition, ils ne sont plus proposés ; le colis sans poids, si')

        # ============================================================ D. le voyage, vu par l'onglet Colis
        t = f('lg_create_transport', p_mode='air', p_carrier='Sunrise Airways', p_reference='AWB-31', p_voyage_number='2Q-31',
              p_origin_branch=mia['branch_id'], p_destination_branch=pap['branch_id'], p_planned_departure=R("now() + interval '1 hour'"),
              p_planned_arrival=R("now() + interval '4 hours'"), p_capacity_weight_lb=500)
        f('lg_generate_manifest', p_shipment_id=sid)
        f('lg_mark_shipment_ready', p_shipment_id=sid)
        f('lg_dispatch_shipment', p_shipment_id=sid, p_transport_id=t['transport_id'], p_idempotency_key='exp31-partir')
        ok(q("select string_agg(statut, ',') from public.colis where id in ('%s', '%s')" % (c1, c2)) == 'expedie,expedie', 'parti : « expédié » dans l\'onglet Colis')
        f('lg_mark_shipment_in_transit', p_shipment_id=sid)
        f('lg_arrive_shipment', p_shipment_id=sid)
        f('lg_start_customs', p_shipment_id=sid, p_reference='DEC-31', p_broker='Courtier')
        f('lg_clear_customs', p_shipment_id=sid, p_reference='MAINLEVEE-31')
        f('lg_receive_at_hub', p_shipment_id=sid, p_hub_warehouse_id=wp['warehouse_id'])
        ok(q("select string_agg(statut, ',') from public.colis where id in ('%s', '%s')" % (c1, c2)) == 'disponible,disponible', 'au HUB : « disponible » dans l\'onglet Colis')
        q('select logistics.process_sync_queue()')
        ok(int(q("select count(*) from public.colis_historique where colis_id in ('%s', '%s')" % (c1, c2))) == histo0, 'le voyage n\'écrit pas d\'ancien historique en double')
        ok(q("select count(*) from logistics.tracking_event e join logistics.parcel p on p.id = e.parcel_id where p.legacy_parcel_id = '%s' and e.to_status = 'IN_TRANSIT'" % c1) == '1',
           'le journal du noyau : un départ, pas deux')

        # ============================================================ E. l'onglet Colis : ancien parcours pour les autres, garde-fou pour ceux-ci
        code, texte = cl.run(B, "update public.colis set statut = 'livre' where id = '%s'" % c1, role='authenticated', claims=admin, expect_error=True)
        ok(code != 0 and 'SE005' in texte and num[c1] in texte, 'un colis qui suit son expédition : son statut ne se change pas à la main (SE005, numéro nommé)')
        ok(q("select statut from public.colis where id = '%s'" % c1) == 'disponible', 'il reste « disponible »')
        q("update public.colis set note = 'Appeler avant' where id = '%s'" % c1)
        ok(q("select note from public.colis where id = '%s'" % c1) == 'Appeler avant', 'sa note, elle, se modifie')
        c4 = colis_ancien('Ancien parcours', 1)
        for s_ in ('expedie', 'disponible', 'livre'):
            q("update public.colis set statut = '%s' where id = '%s'" % (s_, c4))
        ok(q("select statut from public.colis where id = '%s'" % c4) == 'livre', 'un colis hors expédition : confirmé → expédié → disponible → livré, comme avant')
        sante = {x['code']: x for x in json.loads(cl.run(B, 'select public.lg_ops_status()', role='authenticated', claims=admin)[1])['checks']}
        ok(sante['parcel_reflection_gaps']['value'] == 0, 'aucun écart entre l\'onglet Colis et le noyau')

        # ============================================================ F. rattrapage, rejeu, portes
        q('select logistics.process_sync_queue()')
        r = rapport()
        ok(r['ready'] is True and r['unexplained'] == 0, 'rattrapage prêt, zéro écart inexpliqué : %s' % r.get('unexplained_by_entity'))
        avant = q("select count(*) from logistics.shipment")
        cl.run(B, P.lire_sql('outils/logistique/031-expedition-colis-confirmes.sql'))
        ok(q("select count(*) from logistics.shipment") == avant, '031 rejouée : rien ne change')
        code, sortie = cl.run(B, "select public.lg_create_shipment_prepared('X', 'air', null, null)", role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in sortie, 'un visiteur : rien')
        for fn in ('logistics.create_shipment_prepared(uuid,text,text,uuid,uuid,uuid[],uuid[],uuid[],uuid[],uuid,uuid,text)', 'logistics.guard_legacy_status()'):
            ok(q("select has_function_privilege('authenticated', '%s', 'execute')::text || has_function_privilege('anon', '%s', 'execute')::text" % (fn, fn)) == 'falsefalse',
               '%s : jamais appelée en direct' % fn)
        # le fichier partagé avec le site (les signatures de la nouvelle façade, et une réponse réelle de la fenêtre)
        ICI = os.path.dirname(os.path.abspath(__file__))
        SIG = json.loads(q("select json_build_object(p.proname, (select json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), 'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord) "
                           "from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname = 'lg_create_shipment_prepared'"))
        EX = {'signatures': SIG, 'fenetre': f('lg_ready_for_shipment', p_mode='air'), 'creation': exp}
        ch = os.path.join(ICI, 'expedition-confirmes-exemples.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(EX, open(ch, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        lus = json.load(open(ch, encoding='utf-8'))
        ok(lus['signatures'] == json.loads(json.dumps(SIG)), 'les signatures sont celles du fichier partagé avec le site (sinon : SES_FORME_ECRIRE=1)')
        ok(set(lus['fenetre']) == set(EX['fenetre']) and (not EX['fenetre']['confirmed'] or set(lus['fenetre']['confirmed'][0]) == set(EX['fenetre']['confirmed'][0])),
           'la réponse de la fenêtre a la forme du fichier partagé')
    print('%d vérifications — étape 031 (expédier les colis confirmés) : OK' % N[0])


if __name__ == '__main__':
    sys.exit(main())
