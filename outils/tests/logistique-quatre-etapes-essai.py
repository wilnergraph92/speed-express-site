#!/usr/bin/env python3
"""Étape 036 — le parcours du client en quatre étapes (Reçu, Expédié, Disponible, Livré), éprouvé sur la RÉPLIQUE DE LA PRODUCTION
(001 → 036, recopie allumée), au fil d'un vrai voyage.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-quatre-etapes-essai.py
    SES_FORME_ECRIRE=1 …   réécrit quatre-etapes-exemples.json (lu par le portail et recopié dans App_SES/tests/exemples-quatre-etapes.json)

 A. un colis de l'onglet Colis : « Reçu » en cours, daté de son enregistrement, les trois autres à venir ;
 B. préparé et parti : « Reçu » franchi, « Expédié » en cours, daté du départ et du lieu de départ ;
 C. arrivé, dédouané, au HUB : « Disponible » en cours, au HUB ; remis au comptoir : tout franchi, « Livré » daté ;
 D. les mêmes regroupements que l'onglet Colis (le reflet de 030) : chaque statut du noyau a son étape, ou c'est un arrêt ;
 E. un arrêt (mis en attente) garde la dernière étape atteinte ; le parcours en huit étapes est toujours rendu, inchangé ;
 F. tout fermé, 036 rejouée sans effet.
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
        ok('036-quatre-etapes.sql' in etapes, 'l\'étape 036 est dans le noyau')
        for f_ in etapes:
            cl.run(B, P.lire_sql('outils/logistique/' + f_))
        q = lambda sql: cl.un(B, sql)   # noqa: E731
        ok(json.loads(q("select logistics.run_migration('quatre étapes')"))['report']['ready'] is True, 'rattrapage prêt')
        q('select logistics.set_double_write(true)')
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0036-000000000001', 'authenticated', 'authenticated', 'q36@essai.test', 'x', now(), '{}')")
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.statut', 'colis.creer', 'colis.modifier'] where email = 'q36@essai.test'")
        q("select logistics.run_migration('employé')")
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        emp = q("select id from public.clients where email = 'q36@essai.test'")
        cliente = cl.lignes(B, "select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' and k.auth_user_id = c.id order by c.email limit 1")[0]

        def appel(nom, acteur, kw):
            return cl.run(B, 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items())), role='authenticated', claims=acteur, expect_error=True)

        def f(nom, acteur=emp, **kw):
            code, sortie = appel(nom, acteur, kw)
            if code != 0:
                raise AssertionError('%s refusée : %s' % (nom, sortie[-400:]))
            return json.loads(sortie)

        mia = f('lg_create_branch', admin, p_code='MIA', p_name='Miami', p_kind='office', p_country='US', p_city='Doral')
        pap = f('lg_create_branch', admin, p_code='PAP-HUB', p_name='Hub Port-au-Prince', p_kind='hub', p_country='HT', p_city='Port-au-Prince')
        wm = f('lg_create_warehouse', admin, p_branch_id=mia['branch_id'], p_code='MIA-1', p_name='Doral')
        wp = f('lg_create_warehouse', admin, p_branch_id=pap['branch_id'], p_code='PAP-1', p_name='Hub PAP')
        loc = f('lg_create_location', admin, p_warehouse_id=wm['warehouse_id'], p_code='A-01', p_zone='A', p_kind='staging')

        c1 = q("insert into public.colis (client_id, description, poids_lb, tarif_lb, service, pays_destination, ville_destination) "
               "values ('%s', 'Sac à dos', 3, 4, 'aerien', 'HT', 'Port-au-Prince') returning id" % cliente)
        q('select logistics.process_sync_queue()')
        num = q("select numero from public.colis where id = '%s'" % c1)
        pid = q("select id from logistics.parcel where legacy_parcel_id = '%s'" % c1)
        voir = lambda: f('lg_my_parcel_journey', cliente, p_tracking_number=num)   # noqa: E731
        etats = lambda j: [(s['key'], s['state']) for s in j['simple_steps']]   # noqa: E731

        # ============================================================ A. enregistré
        j = voir()
        ok(etats(j) == [('received', 'current'), ('shipped', 'upcoming'), ('available', 'upcoming'), ('delivered', 'upcoming')],
           'un colis de l\'onglet Colis : « Reçu » en cours (%s)' % etats(j))
        ok(j['simple_steps'][0]['at'] and all(s['at'] is None for s in j['simple_steps'][1:]), '« Reçu » daté de son enregistrement, rien d\'autre')
        ok(len(j['steps']) == 8 and j['current_step'] is None, 'le parcours en huit étapes est toujours rendu, inchangé')

        # ============================================================ B. préparé et parti
        exp = f('lg_create_shipment_prepared', p_code='EXP-36', p_mode='air', p_origin_branch=mia['branch_id'], p_destination_branch=pap['branch_id'],
                p_confirmed_ids=[pid], p_warehouse_id=wm['warehouse_id'], p_location_id=loc['location_id'], p_idempotency_key='q36')
        sid = exp['shipment_id']
        ok(etats(voir())[0] == ('received', 'current') and voir()['simple_steps'][0]['place'], 'préparé à l\'entrepôt : toujours « Reçu », avec le lieu de réception')
        t = f('lg_create_transport', p_mode='air', p_carrier='Sunrise Airways', p_reference='AWB-36', p_voyage_number='2Q-36', p_origin_branch=mia['branch_id'],
              p_destination_branch=pap['branch_id'], p_planned_departure=R("now() + interval '1 hour'"), p_planned_arrival=R("now() + interval '4 hours'"), p_capacity_weight_lb=500)
        f('lg_generate_manifest', p_shipment_id=sid)
        f('lg_mark_shipment_ready', p_shipment_id=sid)
        f('lg_dispatch_shipment', p_shipment_id=sid, p_transport_id=t['transport_id'], p_idempotency_key='q36-partir')
        j = voir()
        ok(etats(j) == [('received', 'done'), ('shipped', 'current'), ('available', 'upcoming'), ('delivered', 'upcoming')], 'parti : « Expédié » en cours (%s)' % etats(j))
        ok(j['simple_steps'][1]['at'] and 'Miami' in (j['simple_steps'][1]['place'] or ''), '« Expédié » daté du départ, et d\'où (%s)' % j['simple_steps'][1]['place'])

        # ============================================================ C. arrivé, dédouané, au HUB, remis
        f('lg_mark_shipment_in_transit', p_shipment_id=sid)
        f('lg_arrive_shipment', p_shipment_id=sid)
        f('lg_start_customs', p_shipment_id=sid, p_reference='DEC-36', p_broker='Courtier')
        ok(etats(voir())[1] == ('shipped', 'current'), 'à la douane : encore « Expédié »')
        f('lg_clear_customs', p_shipment_id=sid, p_reference='MAINLEVEE-36')
        f('lg_receive_at_hub', p_shipment_id=sid, p_hub_warehouse_id=wp['warehouse_id'])
        j = voir()
        ok(etats(j) == [('received', 'done'), ('shipped', 'done'), ('available', 'current'), ('delivered', 'upcoming')], 'au HUB : « Disponible » en cours (%s)' % etats(j))
        ok(j['simple_steps'][2]['at'] and 'Port-au-Prince' in (j['simple_steps'][2]['place'] or ''), '« Disponible », daté, au HUB (%s)' % j['simple_steps'][2]['place'])
        ok(q("select statut from public.colis where id = '%s'" % c1) == 'disponible', 'l\'onglet Colis dit la même chose : disponible')
        f('lg_hand_over_at_counter', p_parcel_ids=[pid], p_recipient_name='Maëlle Désir', p_id_document='CIN 123')
        j = voir()
        ok(etats(j) == [('received', 'done'), ('shipped', 'done'), ('available', 'done'), ('delivered', 'done')] and j['simple_steps'][3]['at'],
           'remis au comptoir : tout franchi, « Livré » daté (%s)' % etats(j))
        ok(q("select statut from public.colis where id = '%s'" % c1) == 'livre', 'l\'onglet Colis : livré')

        # ============================================================ D. les mêmes regroupements que l'onglet Colis (030)
        statuts = cl.lignes(B, 'select code from logistics.parcel_status order by code')
        reflet = {'confirme': 1, 'expedie': 2, 'disponible': 3, 'livre': 4}
        for s in statuts:
            g = q("select coalesce(logistics.simple_step_of('%s')::text, 'arret')" % s)
            r = q("select coalesce(logistics.legacy_status_of('%s'), '?')" % s) if q("select to_regproc('logistics.legacy_status_of') is not null") == 't' else None
            if r and r != '?':
                ok((g == 'arret' and r == 'action') or (g != 'arret' and reflet.get(r) == int(g)), '%s : étape %s, onglet Colis « %s »' % (s, g, r))
            else:
                ok(g in ('1', '2', '3', '4', 'arret'), '%s : une étape ou un arrêt' % s)

        # ============================================================ E. un arrêt
        c2 = q("insert into public.colis (client_id, description, poids_lb, tarif_lb, service, pays_destination, ville_destination) "
               "values ('%s', 'Livres', 2, 4, 'aerien', 'HT', 'Port-au-Prince') returning id" % cliente)
        q('select logistics.process_sync_queue()')
        n2 = q("select numero from public.colis where id = '%s'" % c2)
        q("update logistics.parcel set status = 'ON_HOLD' where legacy_parcel_id = '%s'" % c2)
        j2 = f('lg_my_parcel_journey', cliente, p_tracking_number=n2)
        ok(etats(j2)[0] == ('received', 'current') and j2['exception'] and j2['exception']['kind'] == 'paused', 'mis en attente : la dernière étape atteinte, et l\'exception le dit')

        # ============================================================ F. tout fermé, rejeu, fichier partagé
        cl.run(B, P.lire_sql('outils/logistique/036-quatre-etapes.sql'))
        ok(etats(voir())[3] == ('delivered', 'done'), '036 rejouée : rien ne change')
        for fn in ('logistics.parcel_simple_steps(uuid)', 'logistics.simple_step_of(text)'):
            ok(q("select has_function_privilege('authenticated', '%s', 'execute')::text || has_function_privilege('anon', '%s', 'execute')::text" % (fn, fn)) == 'falsefalse',
               '%s : jamais appelée en direct' % fn)
        ICI = os.path.dirname(os.path.abspath(__file__))
        EX = {'parcours_livre': j, 'parcours_attente': j2}
        ch = os.path.join(ICI, 'quatre-etapes-exemples.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(EX, open(ch, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        lus = json.load(open(ch, encoding='utf-8'))
        ok([s['key'] for s in lus['parcours_livre']['simple_steps']] == ['received', 'shipped', 'available', 'delivered'] and set(lus['parcours_livre']) == set(j),
           'la forme du fichier partagé (sinon : SES_FORME_ECRIRE=1)')
    print('%d vérifications — étape 036 (quatre étapes) : OK' % N[0])


if __name__ == '__main__':
    try:
        sys.exit(main())
    except AssertionError as e:
        print('ÉCHEC quatre étapes (après %d vérifications) : %s' % (N[0], e))
        sys.exit(1)
