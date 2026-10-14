#!/usr/bin/env python3
"""Étape 025 — la remise au comptoir, éprouvée sur la RÉPLIQUE DE LA PRODUCTION (des colis « disponibles » de l'ancien schéma).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-comptoir-essai.py

Le propriétaire l'a confirmé : ses clients retirent aussi leurs colis au comptoir du HUB. On exige :
 A. lg_ready_for_delivery montre les colis qui attendent au HUB, avec le client (code, nom, téléphone, adresse) ;
 B. « livré » sans preuve reste impossible : la transition seule (lg_transition_parcel) est refusée ;
 C. la remise : nom obligatoire, un seul client, colis au HUB, pas dans une livraison en cours, droit « colis.statut » ; le colis passe
    LIVRÉ, la preuve est écrite en ajout seul (ni modifiée ni effacée), l'audit et le journal du colis la portent, le client est prévenu
    comme d'une livraison ; aucune incohérence ; une seconde remise du même colis est refusée ;
 D. 025 rejouée ne change rien ; 105 transitions.
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
    if isinstance(v, list):
        return "array[%s]::uuid[]" % ', '.join("'%s'" % x for x in v) if v else "'{}'::uuid[]"
    return "'%s'" % str(v).replace("'", "''")


def main():
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('025-remise-comptoir.sql' in etapes, 'l\'étape 025 est dans le noyau')
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        ok(json.loads(q("select logistics.run_migration('comptoir')"))['report']['ready'] is True, 'rattrapage prêt')
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0025-000000000001', 'authenticated', 'authenticated', 'cpt-emp@essai.test', 'x', now(), '{}')")
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.statut'] where email = 'cpt-emp@essai.test'")
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0025-000000000002', 'authenticated', 'authenticated', 'cpt-lect@essai.test', 'x', now(), '{}')")
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire'] where email = 'cpt-lect@essai.test'")
        q("select logistics.run_migration('comptoir, employés')")
        emp = q("select id from public.clients where email = 'cpt-emp@essai.test'")
        lecteur = q("select id from public.clients where email = 'cpt-lect@essai.test'")
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
            ok(code != 0 and code_attendu in sortie, '%s : attendu %s, obtenu %s' % (msg, code_attendu, sortie[:300]))

        # ============================================================ A. ce qui attend au HUB
        # des colis « disponibles » de l'ancien schéma : AT_DESTINATION_HUB, encore sous son autorité
        attente = f('lg_ready_for_delivery')
        ok(len(attente) >= 3, '%d colis attendent au HUB (repris de l\'ancien schéma)' % len(attente))
        ok(all(x['customer']['code'] and 'phone' in x['customer'] and 'address' in x['customer'] for x in attente), 'chacun avec son client : code, téléphone, adresse')
        par_client = {}
        for x in attente:
            par_client.setdefault(x['customer']['customer_id'], []).append(x)
        cust, siens = max(par_client.items(), key=lambda kv: len(kv[1]))
        autre = [x for k, l in par_client.items() if k != cust for x in l][0]
        un = siens[0]

        # ============================================================ B. jamais « livré » sans preuve
        code, sortie = cl.run('prod', "select public.lg_transition_parcel(p_parcel_id => '%s', p_to_status => 'DELIVERED')" % un['parcel_id'],
                              role='authenticated', claims=emp, expect_error=True)
        ok(code != 0 and ('PREUVE' in sortie or 'LG005' in sortie or 'LG0' in sortie), 'la transition seule, sans remise ni preuve, est refusée : ' + sortie[-160:])
        ok(q("select status from logistics.parcel where id = '%s'" % un['parcel_id']) == 'AT_DESTINATION_HUB', 'le colis est resté au HUB')

        # ============================================================ C. la remise
        refus('lg_hand_over_at_counter', 'LG005', 'nom de la personne obligatoire', p_parcel_ids=[un['parcel_id']], p_recipient_name='  ')
        refus('lg_hand_over_at_counter', 'LG005', 'un seul client par remise', p_parcel_ids=[un['parcel_id'], autre['parcel_id']], p_recipient_name='Marie')
        refus('lg_hand_over_at_counter', 'LG003', 'un client ne remet rien', acteur=client, p_parcel_ids=[un['parcel_id']], p_recipient_name='Marie')
        refus('lg_hand_over_at_counter', 'LG003', 'un employé sans « colis.statut » ne remet rien', acteur=lecteur, p_parcel_ids=[un['parcel_id']], p_recipient_name='Marie')
        # un colis dans une livraison en cours ne se remet pas au comptoir
        hub = q("select b.id from logistics.branch b limit 1") or None
        if not hub:
            org = q('select id from logistics.organization')
            hub = q("insert into logistics.branch (organization_id, code, name, kind, country) values ('%s', 'PAP-HUB', 'Hub', 'hub', 'HT') returning id" % org)
        liv = f('lg_create_delivery', p_parcel_ids=[autre['parcel_id']], p_hub_branch=hub, p_scheduled_for=R('current_date'), p_address='3 rue Capois')
        # créer la livraison l'a déjà fait passer « affecté à une livraison » : refusé dès le contrôle d'état (LG001)
        refus('lg_hand_over_at_counter', 'LG001', 'un colis dans une livraison en cours', p_parcel_ids=[autre['parcel_id']], p_recipient_name='Paul')
        ok(autre['parcel_id'] not in [x['parcel_id'] for x in f('lg_ready_for_delivery')], 'en livraison, il ne figure plus dans ce qui attend')
        notes_avant = int(q("select count(*) from logistics.notification"))
        ids = [x['parcel_id'] for x in siens[:2]]
        r = f('lg_hand_over_at_counter', p_parcel_ids=ids, p_recipient_name='Marie-Ève Léger', p_id_document='CIN 001-234-567-8', p_note='retirés pour sa mère')
        ok(r['count'] == len(ids), 'remise : %d colis' % r['count'])
        ok(all(q("select status || '|' || status_authority from logistics.parcel where id = '%s'" % x) == 'DELIVERED|core' for x in ids), 'LIVRÉS, sous l\'autorité du noyau')
        ok(q("select count(*) from logistics.counter_handover where parcel_id = any (%s) and recipient_name = 'Marie-Ève Léger' and id_document = 'CIN 001-234-567-8' "
             "and handed_by = '%s'" % (val(ids), emp)) == str(len(ids)), 'la preuve : qui a retiré, sa pièce, qui a remis')
        ok(q("select count(*) from logistics.audit_log where action = 'parcel.counter_handover'") == '1', 'tracé dans l\'audit')
        ok(q("select count(*) from logistics.tracking_event where parcel_id = '%s' and to_status = 'DELIVERED' and from_status = 'AT_DESTINATION_HUB'" % ids[0]) == '1', 'le journal du colis dit « livré »')
        q("select logistics.dispatch_events(1000, 'notification_engine')")   # le travail planifié des notifications
        ok(q("select count(*) from logistics.notification where template = 'Delivered' and customer_id = '%s'" % cust) != '0'
           and int(q("select count(*) from logistics.notification")) > notes_avant, 'le client est prévenu, comme d\'une livraison (modèle « Delivered »)')
        ok(q('select count(*) from logistics.workflow_inconsistencies()') == '0', 'aucune incohérence : la remise est une fin légitime')
        refus('lg_hand_over_at_counter', 'LG001', 'un colis déjà remis ne se remet pas deux fois', p_parcel_ids=[ids[0]], p_recipient_name='Marie')
        code, sortie = cl.run('prod', "update logistics.counter_handover set recipient_name = 'X'", expect_error=True)
        ok(code != 0, 'la preuve ne se modifie pas')
        code, sortie = cl.run('prod', "delete from logistics.counter_handover", expect_error=True)
        ok(code != 0 and q('select count(*) from logistics.counter_handover') == str(len(ids)), 'ni ne s\'efface')
        code, sortie = cl.run('prod', "select count(*) from logistics.counter_handover", role='authenticated', claims=emp, expect_error=True)
        ok(code != 0, 'la table n\'est pas lisible directement par un compte')

        # ============================================================ D. rejouable
        ok(q('select count(*) from logistics.parcel_transition') == '105', '105 transitions (104 + la remise au comptoir)')
        cl.run('prod', P.lire_sql('outils/logistique/025-remise-comptoir.sql'))
        ok(q('select count(*) from logistics.parcel_transition') == '105' and q('select count(*) from logistics.counter_handover') == str(len(ids)), '025 rejouée : rien ne change')
        ok(liv['status'] == 'CREATED', 'la livraison créée attend son chauffeur')
        print('PASS remise au comptoir (étape 025) : %d vérifications — colis au HUB repris de l\'ancien schéma, « livré » jamais sans preuve, remise tracée '
              'en ajout seul (personne, pièce, membre de l\'équipe), client prévenu, cohérence, refus attendus (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC remise au comptoir (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
