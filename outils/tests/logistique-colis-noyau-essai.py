#!/usr/bin/env python3
"""Étape 030 — le noyau devient la source de vérité des colis, éprouvé sur la RÉPLIQUE DE LA PRODUCTION (001 → 030, recopie allumée).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-colis-noyau-essai.py

 A. créer (lg_create_parcel) : numéro SES- à dix chiffres, jeton, facture de l'ancien schéma (poids × tarif + 10 $) ET colis du noyau, tout
    de suite ; droits (colis.creer) ; modifier (lg_update_parcel) : la facture suit, le noyau aussi ; statut et lieu refusés par ce chemin ;
 B. faire avancer (lg_parcel_next_steps, lg_move_parcels) : les étapes permises au compte, entrepôt et emplacement demandés quand il le faut ;
    le colis passe sous l'autorité du noyau ; LE REFLET : statut et lieu recopiés dans l'ancien schéma, SANS nouvelle ligne d'historique ;
    la recopie (rattrapage) ne crée aucun événement en double ; l'Analytique compte une réception, pas deux ; plusieurs colis d'un coup,
    chaque refus avec sa raison ;
 C. annuler (lg_cancel_parcel) : motif obligatoire, direction seulement, rien d'effacé, facture intacte ;
 D. un reflet en échec ne bloque jamais le noyau : journalisé, vu par la santé (parcel_reflection_gaps), résorbé au reflet suivant ;
 E. le suivi public (ses_track) : numéro seul ou numéro + bon jeton ; mauvais jeton = rien ; ni nom, ni téléphone, ni adresse ;
 F. le profil (lg_update_my_profile) : ses champs seulement, jamais le rôle ;
 G. rattrapage prêt, rejeu de 030 sans effet, portes fermées.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def lit(v):
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return "'%s'::jsonb" % json.dumps(v).replace("'", "''")
    if isinstance(v, list):
        return "array[%s]::uuid[]" % ', '.join("'%s'" % x for x in v)
    return "'%s'" % str(v).replace("'", "''")


def main():
    with P.Cluster() as cl:
        B = 'prod'
        if not P.monter_production(cl, B):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('030-colis-noyau.sql' in etapes, 'l\'étape 030 est dans le noyau')
        for f_ in etapes:
            cl.run(B, P.lire_sql('outils/logistique/' + f_))
        cl.run(B, P.lire_sql('outils/logistique/030-colis-noyau.sql'))
        ok(True, '030 chargée deux fois de suite')
        q = lambda sql: cl.un(B, sql)   # noqa: E731
        rapport = lambda: json.loads(q("select logistics.run_migration('colis noyau')"))['report']   # noqa: E731
        ok(rapport()['ready'] is True, 'au départ : rattrapage prêt')
        q('select logistics.set_double_write(true)')
        ok(q("select value from logistics.migration_setting where key = 'double_write'") == 'true', 'recopie allumée, comme en production')

        # les comptes : un employé qui crée et modifie, un autre qui ne fait que changer les statuts, l'administrateur, une cliente
        def compte(n, email):
            q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
              "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0030-%012d', 'authenticated', 'authenticated', '%s', 'x', now(), "
              "'{\"nom_complet\": \"Essai %d\", \"pays\": \"Haïti\", \"ville\": \"Delmas\", \"telephone\": \"+509 3700 0000\"}')" % (n, email, n))
            return '00000000-0000-0000-0030-%012d' % n
        saisie = compte(1, 'saisie@essai.test')
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.creer', 'colis.modifier', 'colis.statut'] where id = '%s'" % saisie)
        statuts = compte(2, 'statuts@essai.test')
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.statut'] where id = '%s'" % statuts)
        cliente = compte(3, 'cliente@essai.test')
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        ok(rapport()['ready'] is True, 'les nouveaux comptes recopiés')

        def f(nom, acteur, **kw):
            code, sortie = cl.run(B, 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, lit(v)) for k, v in kw.items())), role='authenticated', claims=acteur)
            return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

        def refuse(nom, etat, msg, acteur, role='authenticated', **kw):
            code, texte = cl.run(B, 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, lit(v)) for k, v in kw.items())), role=role, claims=acteur, expect_error=True)
            ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-220:].replace('\n', ' ')))

        # ============================================================ A. créer et modifier
        champs = {'client_id': cliente, 'description': 'Chaussures', 'expediteur': 'Boutique Miami', 'destinataire': 'Marie Essai', 'telephone_destinataire': '+509 3711 1111',
                  'poids_lb': '4.5', 'tarif_lb': '3', 'service': 'aerien', 'pays_destination': 'HT', 'ville_destination': 'Delmas', 'adresse_livraison': '12 rue Lamarre'}
        c1 = f('lg_create_parcel', saisie, p_colis=champs)
        ok(re.match(r'^SES-\d{10}$', c1['numero']) and len(c1['jeton']) >= 16 and c1['parcel_id'], 'créé : numéro SES- à dix chiffres, jeton, colis du noyau aussitôt : %s %s %s' % (c1['numero'], c1['jeton'], c1['parcel_id']))
        ok(q("select tracking_number || '|' || public_token || '|' || status || '|' || status_authority || '|' || weight_lb from logistics.parcel where id = '%s'" % c1['parcel_id'])
           == '%s|%s|CREATED|legacy|4.50' % (c1['numero'], c1['jeton']), 'le noyau a le même colis, sans attendre la recopie')
        ok(q("select montant || '|' || frais_service from public.factures where colis_id = '%s'" % c1['id']) == '23.50|10.00', 'la facture de toujours : 4,5 lb × 3 $ + 10 $ de frais = 23,50 $')
        ok(q("select customer_id is not null from logistics.parcel where id = '%s'" % c1['parcel_id']) == 't', 'rattaché à la fiche client du noyau')
        refuse('lg_create_parcel', 'LG003', 'créer sans le droit « colis.creer »', statuts, p_colis=champs)
        refuse('lg_create_parcel', 'LG003', 'une cliente ne crée pas de colis', cliente, p_colis=champs)
        refuse('lg_create_parcel', 'LG005', 'un poids illisible', saisie, p_colis=dict(champs, poids_lb='quatre'))
        code, texte = cl.run(B, 'select public.lg_create_parcel(%s)' % lit(champs), role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in texte, 'un visiteur : rien')
        m1 = f('lg_update_parcel', saisie, p_colis_id=c1['id'], p_champs={'poids_lb': '6', 'note': 'Fragile'})
        ok(m1['poids_lb'] == 6 and q("select montant from public.factures where colis_id = '%s'" % c1['id']) == '28.00'
           and q("select weight_lb || '|' || note from logistics.parcel where id = '%s'" % c1['parcel_id']) == '6.00|Fragile',
           'modifié : la facture suit (6 × 3 + 10 = 28 $), le noyau aussi, tout de suite')
        refuse('lg_update_parcel', 'LG005', 'le statut ne change pas par une modification', saisie, p_colis_id=c1['id'], p_champs={'statut': 'livre'})
        refuse('lg_update_parcel', 'LG003', 'modifier sans le droit « colis.modifier »', statuts, p_colis_id=c1['id'], p_champs={'poids_lb': '1'})
        histo0 = int(q("select count(*) from public.colis_historique where colis_id = '%s'" % c1['id']))
        ok(histo0 == 2, 'l\'ancien historique : la naissance du colis, puis la note (comme toujours)')

        # ============================================================ B. faire avancer, et le reflet
        org = q('select id from logistics.organization order by created_at limit 1')
        q("insert into logistics.branch (organization_id, code, name, kind, country, city) values ('%s', 'MIA', 'Miami', 'office', 'US', 'Miami')" % org)
        q("insert into logistics.warehouse (branch_id, code, name) select id, 'MIA-1', 'Entrepôt Miami' from logistics.branch where code = 'MIA'")
        wh = q("select id from logistics.warehouse where code = 'MIA-1'")
        loc = q("insert into logistics.warehouse_location (warehouse_id, code) values ('%s', 'A-01') returning id" % wh)
        s0 = f('lg_parcel_next_steps', statuts, p_colis_id=c1['id'])
        vers = {x['to_status']: x for x in s0['steps']}
        ok(s0['status'] == 'CREATED' and 'RECEIVED' in vers and vers['RECEIVED']['needs_warehouse'] is True and 'CANCELLED' not in vers,
           'étapes permises à un employé : réception (entrepôt demandé), pas l\'annulation (direction) : %s' % sorted(vers))
        ok('CANCELLED' in {x['to_status'] for x in f('lg_parcel_next_steps', admin, p_colis_id=c1['id'])['steps']}, 'la direction voit aussi l\'annulation')
        sans = f('lg_move_parcels', statuts, p_colis_ids=[c1['id']], p_to_status='RECEIVED')
        ok(sans['done'] == 0 and sans['results'][0]['ok'] is False, 'réception sans entrepôt : refusée par la machine, avec sa raison : %s' % sans['results'][0].get('message'))
        evts0 = int(q("select count(*) from logistics.tracking_event where parcel_id = '%s'" % c1['parcel_id']))
        r = f('lg_move_parcels', statuts, p_colis_ids=[c1['id']], p_to_status='RECEIVED', p_location_text='Entrepôt Miami', p_warehouse_id=wh)
        ok(r['done'] == 1, 'reçu au poste MIA-1')
        ok(q("select status || '|' || status_authority from logistics.parcel where id = '%s'" % c1['parcel_id']) == 'RECEIVED|core', 'le colis passe sous l\'autorité du noyau')
        ok(q("select statut || '|' || lieu from public.colis where id = '%s'" % c1['id']) == 'confirme|Entrepôt Miami', 'LE REFLET : l\'ancien schéma voit « confirmé », au bon lieu')
        ok(int(q("select count(*) from public.colis_historique where colis_id = '%s'" % c1['id'])) == histo0, 'le reflet n\'écrit pas d\'historique dans l\'ancien schéma')
        q('select logistics.process_sync_queue()')
        evts1 = int(q("select count(*) from logistics.tracking_event where parcel_id = '%s'" % c1['parcel_id']))
        ok(q("select count(*) from logistics.tracking_event where parcel_id = '%s' and to_status = 'RECEIVED'" % c1['parcel_id']) == '1',
           'après la recopie : UNE réception dans le journal du noyau (aucun doublon venu de l\'ancien schéma)')
        for vers_, extra in (('VERIFIED', {'p_warehouse_id': wh}), ('STORED', {'p_location_id': loc})):
            r = f('lg_move_parcels', statuts, p_colis_ids=[c1['id']], p_to_status=vers_, **extra)
            ok(r['done'] == 1, 'étape %s' % vers_)
        ok(q("select statut from public.colis where id = '%s'" % c1['id']) == 'confirme', 'rangé : toujours « confirmé » pour l\'ancien schéma')
        # une modification APRÈS la bascule : ni ancienne ligne d'historique, ni faux événement « Enregistré » au milieu du parcours
        h1 = q("select count(*) from public.colis_historique where colis_id = '%s'" % c1['id'])
        f('lg_update_parcel', saisie, p_colis_id=c1['id'], p_champs={'note': 'Fragile, côté haut'})
        q('select logistics.process_sync_queue()')
        ok(q("select count(*) from public.colis_historique where colis_id = '%s'" % c1['id']) == h1, 'une note changée après la bascule : pas d\'ancien historique')
        ok(q("select count(*) from logistics.tracking_event e where e.parcel_id = '%s' and e.to_status = 'CREATED' and e.occurred_at > "
             "(select min(x.occurred_at) from logistics.tracking_event x where x.parcel_id = e.parcel_id and x.to_status = 'RECEIVED')" % c1['parcel_id']) == '0',
           'aucun faux événement « Enregistré » après la réception')
        ok(q("select note from logistics.parcel where id = '%s'" % c1['parcel_id']) == 'Fragile, côté haut', 'la note arrive quand même dans le noyau')
        r = f('lg_move_parcels', statuts, p_colis_ids=[c1['id']], p_to_status='ON_HOLD', p_reason='Adresse à vérifier')
        ok(r['done'] == 1 and q("select statut from public.colis where id = '%s'" % c1['id']) == 'action', 'retenu (motif) : « action » dans l\'ancien schéma')
        hier = q('select (logistics.today())::text')
        q("select analytics.refresh(null, '%s'::date, '%s'::date, 'essai')" % (hier, hier))
        ok(q("select coalesce(sum(value), 0) from analytics.daily_fact f where f.run_id = (select max(id) from analytics.report_run) and f.metric = 'parcels_received'") == '1.0000',
           'l\'Analytique compte UNE réception (pas deux)')
        # plusieurs colis d'un coup : un réussit, l'autre est refusé avec sa raison
        c2 = f('lg_create_parcel', saisie, p_colis=dict(champs, description='Livres'))
        lot = f('lg_move_parcels', admin, p_colis_ids=[c2['id'], c1['id']], p_to_status='RECEIVED', p_warehouse_id=wh)
        res = {x['numero']: x for x in lot['results']}
        ok(lot['done'] == 1 and res[c2['numero']]['ok'] is True and res[c1['numero']]['ok'] is False and res[c1['numero']]['message'],
           'deux colis d\'un coup : l\'un passe, l\'autre (déjà retenu) est refusé avec sa raison')

        # ============================================================ C. annuler
        refuse('lg_cancel_parcel', 'LG005', 'annuler sans motif', admin, p_colis_id=c2['id'], p_reason='  ')
        refuse('lg_cancel_parcel', 'LG003', 'un employé n\'annule pas (direction)', statuts, p_colis_id=c2['id'], p_reason='doublon')
        an = f('lg_cancel_parcel', admin, p_colis_id=c2['id'], p_reason='Créé en double')
        ok(an['ok'] is True and q("select status from logistics.parcel where legacy_parcel_id = '%s'" % c2['id']) == 'CANCELLED'
           and q("select statut from public.colis where id = '%s'" % c2['id']) == 'action', 'annulé : CANCELLED dans le noyau, « action » dans l\'ancien schéma')
        ok(q("select count(*) from public.colis where id = '%s'" % c2['id']) == '1' and q("select count(*) from public.factures where colis_id = '%s'" % c2['id']) == '1',
           'rien n\'est effacé : le colis et sa facture restent (la facture se gère dans l\'onglet Factures, comme avant)')

        # ============================================================ D. un reflet en échec ne bloque jamais le noyau
        q("alter table public.colis add constraint essai_bloque_reflet check (statut <> 'confirme' or lieu <> 'Poste bloqué') not valid")
        c3 = f('lg_create_parcel', saisie, p_colis=dict(champs, description='Montre'))
        r = f('lg_move_parcels', statuts, p_colis_ids=[c3['id']], p_to_status='RECEIVED', p_location_text='Poste bloqué', p_warehouse_id=wh)
        ok(r['done'] == 1 and q("select status from logistics.parcel where legacy_parcel_id = '%s'" % c3['id']) == 'RECEIVED',
           'le reflet échoue (contrainte de l\'essai) : la réception est quand même faite dans le noyau')
        ok(q("select count(*) from logistics.sync_failure where table_name = 'colis_reflet' and legacy_id = '%s'" % c3['id']) == '1', 'l\'échec du reflet est journalisé')
        sante = {x['code']: x for x in json.loads(cl.run(B, 'select public.lg_ops_status()', role='authenticated', claims=admin)[1])['checks']}
        ok(sante['parcel_reflection_gaps']['value'] == 0, 'statut identique (« confirmé » dans les deux) : aucun écart à signaler')
        q("alter table public.colis drop constraint essai_bloque_reflet")
        q("alter table public.colis add constraint essai_bloque_reflet2 check (statut <> 'action' or note <> 'Bloquer') not valid")
        f('lg_update_parcel', saisie, p_colis_id=c3['id'], p_champs={'note': 'Bloquer'})
        f('lg_move_parcels', statuts, p_colis_ids=[c3['id']], p_to_status='ON_HOLD', p_reason='Essai')
        sante = {x['code']: x for x in json.loads(cl.run(B, 'select public.lg_ops_status()', role='authenticated', claims=admin)[1])['checks']}
        ok(sante['parcel_reflection_gaps']['value'] == 1 and sante['parcel_reflection_gaps']['status'] == 'WARN', 'un statut non reflété : la santé du système le voit')
        q("alter table public.colis drop constraint essai_bloque_reflet2")
        f('lg_move_parcels', admin, p_colis_ids=[c3['id']], p_to_status='RECEIVED', p_warehouse_id=wh)
        sante = {x['code']: x for x in json.loads(cl.run(B, 'select public.lg_ops_status()', role='authenticated', claims=admin)[1])['checks']}
        ok(sante['parcel_reflection_gaps']['value'] == 0 and q("select statut from public.colis where id = '%s'" % c3['id']) == 'confirme', 'le reflet suivant résorbe l\'écart')

        # ============================================================ E. le suivi public, depuis le noyau
        code, sortie = cl.run(B, "select public.ses_track('%s')" % c1['numero'].lower(), role='anon')
        t = json.loads(sortie)
        ok(t['numero'] == c1['numero'] and t['status'] == 'ON_HOLD' and t['stage'] and len(t['steps']) == 8, 'un visiteur suit le colis par son numéro : statut et huit étapes')
        ok(any(e['status'] == 'RECEIVED' and e['place'] == 'Entrepôt Miami' for e in t['events']), 'les étapes datées, avec leur lieu')
        ok(t['statut'] == 'action' and t['service'] == 'aerien' and t['pays_destination'] == 'HT' and any(h['statut'] == 'confirme' and h['lieu'] == 'Entrepôt Miami' for h in t['historique']),
           'et la forme de l\'ancien suivi (statut, service, historique), ramenée par la base : la page Suivi n\'a rien à traduire')
        ancien_format = json.loads(cl.run(B, "select public.suivre_colis('%s')" % c1['numero'], role='anon')[1])
        ok(set(ancien_format) <= set(t), 'ses_track rend au moins toutes les clés de l\'ancien suivi : %s' % sorted(set(ancien_format) - set(t)))
        texte = json.dumps(t, ensure_ascii=False)
        ok('Marie' not in texte and '3711' not in texte and 'Lamarre' not in texte and 'Boutique' not in texte, 'ni nom, ni téléphone, ni adresse, ni expéditeur')
        ok(json.loads(cl.run(B, "select public.ses_track('%s', '%s')" % (c1['numero'], c1['jeton']), role='anon')[1])['numero'] == c1['numero'], 'numéro + bon jeton (QR code) : suivi')
        ok(cl.run(B, "select public.ses_track('%s', 'faux')" % c1['numero'], role='anon')[1] in ('', 'null') and
           cl.run(B, "select public.ses_track('SES')", role='anon')[1] in ('', 'null'), 'mauvais jeton, numéro trop court : rien')
        ancien = q("select numero from public.colis where numero is not null and id not in ('%s', '%s', '%s') order by cree_le limit 1" % (c1['id'], c2['id'], c3['id']))
        ok(json.loads(cl.run(B, "select public.ses_track('%s')" % ancien, role='anon')[1])['numero'] == ancien, 'un colis d\'avant la bascule se suit aussi')

        # ============================================================ F. le profil
        p = f('lg_update_my_profile', cliente, p_champs={'nom_complet': 'Marie Essai', 'ville': 'Pétion-Ville', 'langue': 'ht'})
        ok(p['ville'] == 'Pétion-Ville' and q("select langue from public.clients where id = '%s'" % cliente) == 'ht', 'la cliente modifie son profil')
        refuse('lg_update_my_profile', 'LG005', 'jamais son rôle', cliente, p_champs={'role': 'admin'})
        refuse('lg_update_my_profile', 'LG005', 'jamais son code', cliente, p_champs={'code': 'SES-00001'})
        refuse('lg_update_my_profile', 'LG005', 'une langue inconnue', cliente, p_champs={'langue': 'de'})
        ok(q("select role from public.clients where id = '%s'" % cliente) == 'client', 'son rôle n\'a pas bougé')

        # ============================================================ G. rattrapage, rejeu, portes
        q('select logistics.process_sync_queue()')
        r = rapport()
        ok(r['ready'] is True and r['unexplained'] == 0, 'après tout cela : rattrapage prêt, zéro écart inexpliqué')
        avant = q("select md5(string_agg(statut || lieu, ',' order by id)) from public.colis")
        cl.run(B, P.lire_sql('outils/logistique/030-colis-noyau.sql'))
        ok(q("select md5(string_agg(statut || lieu, ',' order by id)) from public.colis") == avant, '030 rejouée : rien ne bouge')
        for trig in ('historiser_colis', 'prevenir_client'):
            d = q("select pg_get_triggerdef(oid) from pg_trigger where tgname = '%s'" % trig)
            ok("ses.reflet" in d, 'le déclencheur %s se tait pendant le reflet' % trig)
        portes = cl.lignes(B, "select p.proname || '|' || has_function_privilege('authenticated', p.oid, 'execute') || '|' || has_function_privilege('anon', p.oid, 'execute') "
                              "from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname in "
                              "('lg_create_parcel', 'lg_update_parcel', 'lg_parcel_next_steps', 'lg_move_parcels', 'lg_cancel_parcel', 'ses_track', 'lg_update_my_profile') order by 1")
        ok(len(portes) == 7, 'sept portes')
        for l_ in portes:
            nom_, au_, an_ = l_.split('|')
            ok(au_ == 'true' and an_ == ('true' if nom_ == 'ses_track' else 'false'), '%s : ouverte aux comptes%s' % (nom_, ', et aux visiteurs' if nom_ == 'ses_track' else ' seulement'))
        for fn in ('logistics.sync_legacy_parcel(uuid)', 'logistics.create_parcel(uuid,jsonb)', 'logistics.public_track(text,text)'):
            ok(q("select has_function_privilege('authenticated', '%s', 'execute')::text || has_function_privilege('anon', '%s', 'execute')::text" % (fn, fn)) == 'falsefalse',
               '%s : jamais appelée en direct' % fn)
        # ============================================================ H. les fichiers partagés avec le site (colis-noyau-contrat.cjs)
        NOMS = ('lg_create_parcel', 'lg_update_parcel', 'lg_parcel_next_steps', 'lg_move_parcels', 'lg_cancel_parcel', 'ses_track', 'lg_update_my_profile')
        SIG = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), 'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) "
                           "from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname in (%s)"
                           % ', '.join("'%s'" % x for x in NOMS)))
        c4 = f('lg_create_parcel', saisie, p_colis=dict(champs, description='Exemple'))
        EX = {'creation': c4, 'modification': f('lg_update_parcel', saisie, p_colis_id=c4['id'], p_champs={'note': 'Exemple'}),
              'etapes': f('lg_parcel_next_steps', statuts, p_colis_id=c4['id']), 'etapes_direction': f('lg_parcel_next_steps', admin, p_colis_id=c4['id']),
              'avancement': f('lg_move_parcels', statuts, p_colis_ids=[c4['id']], p_to_status='RECEIVED', p_location_text='Entrepôt Miami', p_warehouse_id=wh),
              'lot': lot, 'annulation': an, 'suivi': t, 'profil': p}
        ICI = os.path.dirname(os.path.abspath(__file__))
        for nom_, contenu in (('colis-noyau-rpc.json', SIG), ('colis-noyau-exemples.json', EX)):
            ch = os.path.join(ICI, nom_)
            if os.environ.get('SES_FORME_ECRIRE'):
                json.dump(contenu, open(ch, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            ok(os.path.exists(ch), '%s existe (sinon : SES_FORME_ECRIRE=1)' % nom_)
        ok(json.load(open(os.path.join(ICI, 'colis-noyau-rpc.json'), encoding='utf-8')) == json.loads(json.dumps(SIG)), 'les signatures sont celles du fichier partagé avec le site')

        def forme(x, ch=''):
            if isinstance(x, dict):
                return {ch + '.' + k_ for k_ in x} | set().union(*[forme(v_, ch + '.' + k_) for k_, v_ in x.items()]) if x else set()
            if isinstance(x, list):
                return set().union(*[forme(v_, ch + '[]') for v_ in x]) if x else set()
            return set()
        lus = json.load(open(os.path.join(ICI, 'colis-noyau-exemples.json'), encoding='utf-8'))
        ok(all(forme(lus[k_]) == forme(json.loads(json.dumps(v_))) for k_, v_ in EX.items()), 'les exemples ont la forme des réponses réelles (sinon : SES_FORME_ECRIRE=1)')
    print('%d vérifications — étape 030 (le noyau, source de vérité des colis) : OK' % N[0])


if __name__ == '__main__':
    sys.exit(main())
