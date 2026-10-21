#!/usr/bin/env python3
"""Étape 034 — le rapport d'une expédition, éprouvé sur la RÉPLIQUE DE LA PRODUCTION (001 → 034, recopie allumée).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-rapport-expedition-essai.py
    SES_FORME_ECRIRE=1 …   réécrit rapport-expedition-exemples.json (lu par outils/tests/rapport-expedition-contrat.cjs)

Demande du propriétaire (21/10/2026) : un rapport imprimable de l'expédition, ses colis classés par client, avec contenu, poids, pays et ville de
livraison, facture payée / impayée / payée en partie, totaux, l'arrivée (pays et ville) en tête, la date de création.
 A. une vraie expédition : trois colis de l'onglet Colis (deux clients, l'un en a deux), préparés et expédiés vers Port-au-Prince ;
 B. le rapport : classé par client, chaque colis avec son contenu, son poids, sa destination ; l'arrivée et la date en tête ; qui l'a préparé ;
 C. le paiement, tel que la facturation EN SERVICE le dit : payée, impayée, payée en partie ; une facture groupée retrouvée par ses lignes ; les
    montants comptés une seule fois par facture ;
 D. les montants seulement pour qui lit les factures ; le statut pour tous ceux qui lisent les colis ; un client : refusé ;
 E. tout fermé, 034 rejouée sans effet ; le fichier partagé avec le site.
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
        ok('034-rapport-expedition.sql' in etapes, 'l\'étape 034 est dans le noyau')
        for f_ in etapes:
            cl.run(B, P.lire_sql('outils/logistique/' + f_))
        q = lambda sql: cl.un(B, sql)   # noqa: E731
        rapport = lambda: json.loads(q("select logistics.run_migration('rapport d''expédition')"))['report']   # noqa: E731
        ok(rapport()['ready'] is True, 'rattrapage prêt')
        q('select logistics.set_double_write(true)')
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0034-000000000001', 'authenticated', 'authenticated', 'rap34@essai.test', 'x', now(), '{}')")
        q("update public.clients set role = 'employe', code = null, nom_complet = 'Lucie Préparatrice', droits = array['colis.lire', 'colis.statut', 'colis.creer', 'colis.modifier'] "
          "where email = 'rap34@essai.test'")
        rapport()
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        emp = q("select id from public.clients where email = 'rap34@essai.test'")
        clientes = cl.lignes(B, "select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 2")
        ca, cb = clientes

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
        loc = f('lg_create_location', admin, p_warehouse_id=wm['warehouse_id'], p_code='A-01', p_zone='A', p_kind='staging')

        # ============================================================ A. trois colis de l'onglet Colis, deux clients
        def colis_ancien(client, desc, poids):
            return q("insert into public.colis (client_id, description, poids_lb, tarif_lb, service, pays_destination, ville_destination) "
                     "values ('%s', '%s', %s, 4, 'aerien', 'HT', 'Port-au-Prince') returning id" % (client, desc, poids))
        c1, c2, c3 = colis_ancien(ca, 'Chaussures', 4), colis_ancien(ca, 'Livres', 2.5), colis_ancien(cb, 'Téléphone', 1)
        q('select logistics.process_sync_queue()')
        conf = {x['tracking_number']: x['parcel_id'] for x in f('lg_ready_for_shipment', p_mode='air')['confirmed']}
        num = {c: q("select numero from public.colis where id = '%s'" % c) for c in (c1, c2, c3)}
        exp = f('lg_create_shipment_prepared', p_code='EXP-34-1', p_mode='air', p_origin_branch=mia['branch_id'], p_destination_branch=pap['branch_id'],
                p_confirmed_ids=[conf[num[c]] for c in (c1, c2, c3)], p_warehouse_id=wm['warehouse_id'], p_location_id=loc['location_id'], p_idempotency_key='rap34')
        sid = exp['shipment_id']

        # la facturation EN SERVICE (ancien schéma) : c1 payée, c2 payée en partie, c3 impayée
        fac = lambda c: q("select id from public.factures where colis_id = '%s'" % c)   # noqa: E731
        q("update public.factures set statut = 'payee', payee_le = now(), montant_paye = montant where id = '%s'" % fac(c1))
        q("update public.factures set montant_paye = 5 where id = '%s'" % fac(c2))

        # ============================================================ B. le rapport
        r = f('lg_shipment_report', admin, p_shipment_id=sid)
        s = r['shipment']
        ok(s['code'] == 'EXP-34-1' and s['created_at'] and s['destination']['country'] == 'HT' and s['destination']['city'] == 'Port-au-Prince'
           and s['origin']['code'] == 'MIA' and s['mode'] == 'air', 'en tête : le code, la date de création, l\'arrivée (pays et ville), le départ, le mode')
        ok(s['prepared_by'] == 'Lucie Préparatrice', 'préparé par : %s' % s['prepared_by'])
        clients = r['customers']
        ok(len(clients) == 2 and sorted(x['count'] for x in clients) == [1, 2], 'classé par client : deux clients, l\'un avec deux colis')
        deux = [x for x in clients if x['count'] == 2][0]
        ok(deux['code'] and deux['name'] and sorted(p['tracking_number'] for p in deux['parcels']) == sorted([num[c1], num[c2]]), 'les deux colis du même client, ensemble')
        tous = {p['tracking_number']: p for x in clients for p in x['parcels']}
        ok(tous[num[c1]]['contents'] == 'Chaussures' and float(tous[num[c1]]['weight_lb']) == 4 and tous[num[c3]]['destination_city'] == 'Port-au-Prince'
           and tous[num[c3]]['destination_country'] == 'HT', 'chaque colis : contenu, poids, pays et ville de livraison')
        ok(r['totals']['parcels'] == 3 and r['totals']['customers'] == 2 and float(r['totals']['weight_lb']) == 7.5, 'les totaux, comptés par la base : %s' % r['totals'])

        # ============================================================ C. le paiement
        st = {n: tous[num[c]]['invoice']['status'] for c, n in ((c1, 'c1'), (c2, 'c2'), (c3, 'c3'))}
        ok(st == {'c1': 'PAID', 'c2': 'PARTIAL', 'c3': 'UNPAID'}, 'payée, payée en partie, impayée : %s' % st)
        ok(r['totals']['unpaid_parcels'] == 2, 'deux colis restent à encaisser')
        m1 = float(q("select montant from public.factures where id = '%s'" % fac(c1)))
        m2 = float(q("select montant from public.factures where id = '%s'" % fac(c2)))
        ok(float(deux['amount']) == m1 + m2 and float(deux['paid']) == m1 + 5, 'les montants du client : %s / %s' % (deux['amount'], deux['paid']))
        q('select logistics.process_sync_queue()')
        rr = rapport()
        ok(rr['ready'] is True and rr['unexplained'] == 0, 'rattrapage toujours prêt : %s' % rr.get('unexplained_by_entity'))
        # une facture groupée (une ligne par colis) : retrouvée par ses lignes, comptée une seule fois. (Fabriquée à la main, déclencheurs
        # coupés : le rattrapage ne la connaît pas, c'est pourquoi il est vérifié AVANT.)
        q("insert into public.factures (client_id, colis_id, montant, frais_service, lignes, groupee, statut) values ('%s', null, 99, 10, "
          "jsonb_build_array(jsonb_build_object('colis_id', '%s'), jsonb_build_object('colis_id', '%s')), true, 'impayee')" % (ca, c1, c2))
        q("alter table public.factures disable trigger user")
        q("update public.factures set colis_id = null, lignes = '[]'::jsonb where id in ('%s', '%s')" % (fac(c1), fac(c2)))
        q("alter table public.factures enable trigger user")
        g = f('lg_shipment_report', admin, p_shipment_id=sid)
        dg = [x for x in g['customers'] if x['count'] == 2][0]
        ok(all(p['invoice']['grouped'] is True and p['invoice']['status'] == 'UNPAID' for p in dg['parcels']), 'une facture groupée : retrouvée pour chacun de ses colis')
        ok(float(dg['amount']) == 99, 'et comptée UNE fois pour le client (%s)' % dg['amount'])

        # ============================================================ D. qui voit quoi
        r2 = f('lg_shipment_report', emp, p_shipment_id=sid)
        ok(r2['money'] is False and r2['totals']['amount'] is None and all(x.get('amount') is None for x in r2['customers'])
           and all(p['invoice'].get('amount') is None and p['invoice']['status'] for x in r2['customers'] for p in x['parcels']),
           'sans « factures.lire » : le statut de paiement, jamais les montants')
        refus('lg_shipment_report', 'LG003', 'un client', acteur=ca, p_shipment_id=sid)
        refus('lg_shipment_report', 'LG002', 'une expédition inconnue', p_shipment_id=R('gen_random_uuid()'))

        # ============================================================ E. tout fermé, rejeu, fichier partagé
        avant = q('select count(*) from logistics.shipment')
        cl.run(B, P.lire_sql('outils/logistique/034-rapport-expedition.sql'))
        ok(q('select count(*) from logistics.shipment') == avant, '034 rejouée : rien ne change')
        code, sortie = cl.run(B, "select public.lg_shipment_report('%s')" % sid, role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in sortie, 'un visiteur : rien')
        for fn in ('logistics.shipment_report(uuid,uuid)', 'logistics.report_invoice(uuid,boolean)'):
            ok(q("select has_function_privilege('authenticated', '%s', 'execute')::text || has_function_privilege('anon', '%s', 'execute')::text" % (fn, fn)) == 'falsefalse',
               '%s : jamais appelée en direct' % fn)
        ICI = os.path.dirname(os.path.abspath(__file__))
        SIG = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), "
                           "'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) "
                           "from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = 'lg_shipment_report'"))
        EX = {'signatures': SIG, 'rapport': r, 'rapport_sans_montants': r2}
        ch = os.path.join(ICI, 'rapport-expedition-exemples.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(EX, open(ch, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        lus = json.load(open(ch, encoding='utf-8'))
        ok(lus['signatures'] == json.loads(json.dumps(SIG)), 'les signatures sont celles du fichier partagé avec le site (sinon : SES_FORME_ECRIRE=1)')
    print('%d vérifications — étape 034 (rapport d\'expédition) : OK' % N[0])


if __name__ == '__main__':
    try:
        sys.exit(main())
    except AssertionError as e:
        print('ÉCHEC rapport d\'expédition (après %d vérifications) : %s' % (N[0], e))
        sys.exit(1)
