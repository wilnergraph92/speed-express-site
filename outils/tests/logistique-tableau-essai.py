#!/usr/bin/env python3
"""Phase 7 — le tableau de bord (étape 019), éprouvé sur la RÉPLIQUE DE LA PRODUCTION et sur une PRÉPRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-tableau-essai.py

On exige :
 A. les MODULES décidés par la base : administrateur les 26 ; gérant les 26 (direction) ; employé ses seuls modules ; chauffeur ses
    missions, ses tournées, son pointage ; client rien ;
 B. la vue TEMPS RÉEL : une carte par sujet, seulement à qui peut la lire, chaque carte ouvre un module que ce compte peut ouvrir,
    et ses nombres sont ceux des tables (recomptés ici) ;
 C. les listes : véhicules, tournées (le chauffeur : les siennes), dépenses et leurs totaux ;
 D. le POINTAGE DES COLIS : liste attendue figée, pointé, doublon, en trop, inconnu, bilan à la clôture, plus rien après ;
 E. le POINTAGE DU PERSONNEL : arrivée, pause, reprise, départ dans l'ordre ; minutes travaillées et anomalies comptées par la base ;
    corrections motivées par la direction ; relevé ; ajout seul ; chaque geste émet un signal temps réel.
Jamais la production."""
import importlib.util
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]
TOUS = ['vue-generale', 'commande', 'colis', 'prealertes', 'scanner', 'entrepots', 'consolidations', 'expeditions', 'transport', 'douane', 'livraisons',
        'chauffeurs', 'vehicules', 'tournees', 'incidents', 'clients', 'factures', 'encaissements', 'depenses', 'rapports', 'analytique', 'notifications',
        'equipe', 'pointage', 'parametres', 'sante']


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


def parcours(cl, B, lieu):
    q = lambda sql: cl.un(B, sql)   # noqa: E731
    L = lambda sql: cl.lignes(B, sql)   # noqa: E731
    comptes = {'ops': ['colis.lire', 'colis.statut'], 'fin': ['factures.lire'], 'chauf': []}
    for i, (cle, droits) in enumerate(comptes.items()):
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0007-%012d', 'authenticated', 'authenticated', 'tb-%s@essai.test', 'x', now(), '{\"nom_complet\": \"Membre %s\"}')"
          % (i + 1, cle, cle))
        q("update public.clients set role = 'employe', code = null, droits = %s where email = 'tb-%s@essai.test'" % (val(droits) if droits else "'{}'", cle))
    ok(json.loads(q("select logistics.run_migration('décor du tableau')"))['report']['ready'] is True, '[%s] décor prêt' % lieu)
    uid = lambda e: q("select id from public.clients where email = '%s'" % e)   # noqa: E731
    admin = q("select id from public.clients where role = 'admin' order by email limit 1")
    gerant = q("select id from public.clients where role = 'gerant' order by email limit 1")
    ops, fin, chauf = uid('tb-ops@essai.test'), uid('tb-fin@essai.test'), uid('tb-chauf@essai.test')
    client = L("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1")[0]

    def f(nom, acteur=ops, **kw):
        code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
        return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

    def fr(nom, etat, msg, acteur=ops, **kw):
        code, texte = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
        ok(code != 0 and etat in texte, '[%s] %s : attendu %s, obtenu : %s' % (lieu, msg, etat, texte[-200:].replace('\n', ' ')))

    # un véhicule, un chauffeur, une tournée, un colis en attente, une dépense
    org = q('select id from logistics.organization')
    q("insert into logistics.branch (organization_id, code, name, kind, country) values ('%s', 'TB-PAP', 'Hub Port-au-Prince', 'hub', 'HT')" % org)
    pap = q("select id from logistics.branch where code = 'TB-PAP'")
    q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'TB-W1', 'Entrepôt essai')" % pap)
    wh = q("select id from logistics.warehouse where code = 'TB-W1'")
    veh = f('lg_create_vehicle', acteur=admin, p_plate='tb-van', p_kind='VAN', p_capacity_lb=200, p_branch=pap)
    drv = f('lg_create_driver', acteur=admin, p_user_id=chauf, p_full_name='Chauffeur Essai', p_vehicle_id=veh)
    cust = q("select id from logistics.customer where legacy_client_id = '%s'" % client)
    n_p = [0]

    def colis(statut, entrepot=True):
        n_p[0] += 1
        return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source, weight_lb, "
                 "current_warehouse_id) values ('%s', 'SES-97%08d', 'jeton-t%d', '%s', 'HT', 'air', '%s', 'core', 'legacy_backfill', 3, %s) returning id"
                 % (org, n_p[0], n_p[0], cust, statut, "'%s'" % wh if entrepot else 'null'))
    q("select logistics.set_exchange_rate('%s', 'USD', 'HTG', 132, current_date)" % admin)
    f('lg_record_expense', acteur=admin, p_category='FUEL', p_amount=50, p_currency='USD', p_description='Gazole', p_incurred_on=R('current_date'))
    f('lg_record_expense', acteur=admin, p_category='FUEL', p_amount=1320, p_currency='HTG', p_description='Gazole HTG', p_incurred_on=R('current_date'))

    # ====================================================================== A. les modules
    acc = {k: f('lg_dashboard_access', acteur=v) for k, v in (('admin', admin), ('gerant', gerant), ('ops', ops), ('fin', fin), ('chauf', chauf), ('client', client))}
    ok(acc['admin']['modules'] == TOUS and len(TOUS) == 26, '[%s] A : administrateur : les 26 modules, dans l\'ordre de la barre' % lieu)
    ok(acc['gerant']['modules'] == TOUS and acc['gerant']['role'] == 'manager', '[%s] A : gérant : les 26 (la base l\'empêche de toucher un administrateur, definir_role)' % lieu)
    ok(set(acc['ops']['modules']) == {'vue-generale', 'commande', 'colis', 'prealertes', 'scanner', 'entrepots', 'consolidations', 'expeditions', 'transport', 'douane',
                                      'livraisons', 'chauffeurs', 'vehicules', 'tournees', 'incidents', 'rapports', 'notifications', 'pointage', 'parametres'},
       '[%s] A : employé des opérations : ses modules seulement, ni facturation, ni clients, ni équipe, ni santé' % lieu)
    ok(set(acc['fin']['modules']) == {'vue-generale', 'commande', 'factures', 'encaissements', 'depenses', 'rapports', 'pointage', 'parametres'},
       '[%s] A : employé de la facturation : ses modules seulement : %s' % (lieu, acc['fin']['modules']))
    ok(acc['chauf']['modules'] == ['livraisons', 'tournees', 'pointage', 'parametres'] and acc['chauf']['driver_only'] is True,
       '[%s] A : chauffeur : ses missions, ses tournées, son pointage — rien d\'autre' % lieu)
    ok(acc['client'] == {'staff': False, 'modules': []}, '[%s] A : client : JAMAIS le tableau de bord opérationnel' % lieu)

    # ====================================================================== B. la vue temps réel
    attente = colis('RECEIVED')
    colis('ON_HOLD')
    q("insert into logistics.incident (type, severity, description, correlation_id) values ('OTHER', 'HIGH', 'essai', gen_random_uuid())")
    cartes = {k: f('lg_cc_command', acteur=v) for k, v in (('admin', admin), ('ops', ops), ('fin', fin), ('chauf', chauf))}
    cles = lambda x: [c['key'] for c in x['cards']]   # noqa: E731
    ok(cles(cartes['admin']) == ['to_process', 'scans', 'arrivals', 'departures', 'customs', 'deliveries_today', 'delays', 'incidents', 'payments_pending', 'tasks', 'alerts'],
       '[%s] B : onze cartes pour l\'administrateur, dans l\'ordre' % lieu)
    ok('payments_pending' not in cles(cartes['ops']) and 'to_process' in cles(cartes['ops']), '[%s] B : l\'employé des opérations ne voit pas l\'argent' % lieu)
    ok(cles(cartes['fin']) == ['payments_pending', 'tasks', 'alerts'], '[%s] B : la facturation ne voit que l\'argent, ses tâches, les alertes : %s' % (lieu, cles(cartes['fin'])))
    ok(cles(cartes['chauf']) == ['deliveries_today', 'delays', 'tasks', 'alerts'], '[%s] B : le chauffeur : ses livraisons, ses retards, ses tâches : %s' % (lieu, cles(cartes['chauf'])))
    for qui, x in cartes.items():
        ok(all(c['module'] in x['modules'] for c in x['cards']), '[%s] B : %s : chaque carte ouvre un module qu\'il peut ouvrir' % (lieu, qui))
        ok(all(c['severity'] in ('ok', 'info', 'warn', 'bad') and isinstance(c['count'], int) for c in x['cards']), '[%s] B : %s : chaque carte a un nombre et une gravité' % (lieu, qui))
    c = {k['key']: k for k in cartes['admin']['cards']}
    ok(c['to_process']['detail']['received'] == int(q("select count(*) from logistics.parcel where status = 'RECEIVED'")) and c['to_process']['detail']['on_hold'] >= 1
       and c['to_process']['severity'] == 'warn', '[%s] B : colis à traiter = le compte des tables' % lieu)
    ok(c['incidents']['detail']['high'] == int(q("select count(*) from logistics.incident where status in ('OPEN', 'IN_PROGRESS') and severity = 'HIGH'")) and c['incidents']['severity'] == 'bad',
       '[%s] B : incidents graves = le compte des tables, carte rouge' % lieu)
    fr('lg_cc_command', 'LG003', 'un client ouvre le centre de commande', acteur=client)

    # ====================================================================== C. les listes
    v = f('lg_cc_vehicles')
    ok(any(x['plate'] == 'TB-VAN' and x['drivers'] == ['Chauffeur Essai'] for x in v['items']), '[%s] C : véhicules, avec leur chauffeur' % lieu)
    fr('lg_cc_vehicles', 'LG003', 'la facturation lit les véhicules', acteur=fin)
    ok(f('lg_cc_trips', acteur=chauf)['mine_only'] is True and f('lg_cc_trips')['mine_only'] is False, '[%s] C : tournées : le chauffeur ne voit que les siennes' % lieu)
    fr('lg_cc_trips', 'LG003', 'un client lit les tournées', acteur=client)
    dep = f('lg_cc_expenses', acteur=fin)
    ok(float(dep['total_usd']) == 60 and dep['by_category'][0]['category'] == 'FUEL' and len(dep['by_currency']) == 2,
       '[%s] C : dépenses : 50 $ + 1 320 HTG (10 $) = 60 $, comptés par la base' % lieu)
    fr('lg_cc_expenses', 'LG003', 'les opérations lisent les dépenses', acteur=ops)

    # ====================================================================== D. le pointage des colis
    p1, p2, p3 = colis('STORED'), colis('STORED'), colis('STORED', entrepot=False)
    t = f('lg_open_tally', p_kind='INVENTORY', p_source_type='warehouse', p_source_id=wh)
    attendus = int(q("select count(*) from logistics.parcel where current_warehouse_id = '%s' and status in ('RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', "
                     "'CONSOLIDATED', 'READY_FOR_EXPORT', 'AT_DESTINATION_HUB', 'ON_HOLD')" % wh))
    ok(t['expected'] == attendus and t['checked'] == 0 and t['number'].startswith('PTG-'), '[%s] D : pointage d\'inventaire ouvert : %d colis attendus (liste figée)' % (lieu, attendus))
    num = lambda pid: q("select tracking_number from logistics.parcel where id = '%s'" % pid)   # noqa: E731
    tid = t['tally_id']
    ok(f('lg_tally_scan', p_tally_id=tid, p_code=num(p1), p_code_kind='barcode')['result'] == 'CHECKED', '[%s] D : attendu : pointé' % lieu)
    ok(f('lg_tally_scan', p_tally_id=tid, p_code=num(p1))['result'] == 'DUPLICATE', '[%s] D : pointé deux fois : doublon' % lieu)
    ok(f('lg_tally_scan', p_tally_id=tid, p_code=num(p3))['result'] == 'EXTRA', '[%s] D : un colis connu mais pas attendu : en trop' % lieu)
    ok(f('lg_tally_scan', p_tally_id=tid, p_code='SES-0000000000')['result'] == 'UNKNOWN', '[%s] D : un code inconnu : inconnu, gardé' % lieu)
    r1 = f('lg_tally_scan', p_tally_id=tid, p_code=num(p2), p_idempotency_key='ptg-k1')
    ok(f('lg_tally_scan', p_tally_id=tid, p_code=num(p2), p_idempotency_key='ptg-k1').get('replayed') is True and r1['checked'] == 2, '[%s] D : lecture rejouée : rien de refait' % lieu)
    fin_t = f('lg_close_tally', p_tally_id=tid, p_note='inventaire du soir')
    ok(fin_t['status'] == 'CLOSED' and fin_t['checked'] == 2 and len(fin_t['missing']) == attendus - 2 and fin_t['extra'] == [num(p3)] and fin_t['unknown'] == ['SES-0000000000'],
       '[%s] D : bilan : 2 pointés, %d manquants, 1 en trop, 1 inconnu' % (lieu, attendus - 2))
    fr('lg_tally_scan', 'clos', 'pointer après la clôture', p_tally_id=tid, p_code=num(p2))
    code, _ = cl.run(B, "update logistics.tally_line set checked_at = null where session_id = '%s'" % tid, expect_error=True)
    ok(code != 0, '[%s] D : un pointage clos ne se modifie pas' % lieu)
    fr('lg_open_tally', 'LG003', 'la facturation ouvre un pointage de colis', acteur=fin, p_kind='OTHER', p_source_type='list', p_tracking_numbers=['X1'])
    ok(f('lg_cc_tallies')[0]['tally_id'] == tid or any(x['tally_id'] == tid for x in f('lg_cc_tallies')), '[%s] D : la liste des pointages' % lieu)

    # ====================================================================== E. le pointage du personnel
    signaux = int(q("select count(*) from public.ses_signal where topic = 'staff'"))
    fr('lg_clock', 'impossible', 'pointer un départ sans arrivée', acteur=chauf, p_kind='OUT')
    j = f('lg_clock', acteur=chauf, p_kind='IN')
    ok(j['state'] == 'IN' and len(j['events']) == 1, '[%s] E : arrivée pointée (chauffeur)' % lieu)
    fr('lg_clock', 'impossible', 'pointer deux arrivées', acteur=chauf, p_kind='IN')
    for k in ('BREAK_START', 'BREAK_END', 'OUT'):
        j = f('lg_clock', acteur=chauf, p_kind=k)
    ok(j['state'] == 'OUT' and [e['kind'] for e in j['events']] == ['IN', 'BREAK_START', 'BREAK_END', 'OUT'] and j['anomalies'] == [], '[%s] E : pause, reprise, départ, dans l\'ordre' % lieu)
    ok(int(q("select count(*) from public.ses_signal where topic = 'staff'")) >= signaux + 4, '[%s] E : chaque pointage émet un signal temps réel' % lieu)
    # une journée passée, corrigée par la direction : 8 h – 17 h, pause de 30 min = 510 min ; une autre sans départ
    hier = q("select (logistics.today() - 1)::text")
    avant = q("select (logistics.today() - 2)::text")
    for kind, heure in (('IN', '08:00'), ('BREAK_START', '12:00'), ('BREAK_END', '12:30'), ('OUT', '17:00')):
        f('lg_clock_correct', acteur=admin, p_user_id=ops, p_kind=kind, p_at=R("(('%s %s')::timestamp at time zone 'America/Port-au-Prince')" % (hier, heure)), p_reason='Badge oublié')
    f('lg_clock_correct', acteur=admin, p_user_id=ops, p_kind='IN', p_at=R("(('%s 09:00')::timestamp at time zone 'America/Port-au-Prince')" % avant), p_reason='Arrivée déclarée au téléphone')
    fr('lg_clock_correct', 'motif', 'corriger sans motif', acteur=admin, p_user_id=ops, p_kind='IN', p_at=R('now()'), p_reason=' ')
    fr('lg_clock_correct', 'LG003', 'un employé corrige un pointage', acteur=ops, p_user_id=ops, p_kind='IN', p_at=R('now()'), p_reason='x')
    rap = f('lg_clock_report', acteur=admin, p_from=avant, p_to=hier, p_user_id=ops)
    jours = {r['date']: r for r in rap['rows']}
    ok(jours[hier]['worked_minutes'] == 510 and jours[hier]['break_minutes'] == 30 and jours[hier]['anomalies'] == [], '[%s] E : 8 h – 17 h, 30 min de pause : 510 min, calculées par la base' % lieu)
    ok(jours[avant]['anomalies'] == ['NO_OUT'] and rap['anomalies'] == 1, '[%s] E : une journée sans départ : anomalie' % lieu)
    fr('lg_clock_report', 'LG003', 'un employé lit le relevé', acteur=ops, p_from=avant, p_to=hier)
    ok(f('lg_my_clock', acteur=ops, p_date=hier)['worked_minutes'] == 510, '[%s] E : chacun voit sa journée' % lieu)
    code, _ = cl.run(B, "delete from logistics.staff_clock_event where user_id = '%s'" % ops, expect_error=True)
    ok(code != 0, '[%s] E : le pointage du personnel est en ajout seul' % lieu)
    code, t_ = cl.run(B, appel('lg_clock', p_kind='IN'), role='authenticated', claims=client, expect_error=True)
    ok(code != 0, '[%s] E : un client ne pointe pas' % lieu)
    # Une livraison confiée au chauffeur, acceptée, dans une tournée : pour que « mes missions » et « tournées » aient du contenu.
    p_liv = colis('AT_DESTINATION_HUB')
    liv = f('lg_create_delivery', acteur=admin, p_parcel_ids=R("array['%s']::uuid[]" % p_liv), p_hub_branch=pap, p_scheduled_for=R('current_date'), p_recipient_name='Marie',
            p_address='3 rue Capois, Port-au-Prince')
    f('lg_assign_task', acteur=admin, p_task_id=liv['task_id'], p_driver_id=drv, p_force=True, p_reason='Essai : chauffeur sans disponibilité déclarée')
    f('lg_accept_task', acteur=chauf, p_task_id=liv['task_id'])
    f('lg_create_trip', acteur=admin, p_driver_id=drv, p_trip_date=R('current_date'), p_task_ids=R("array['%s']::uuid[]" % liv['task_id']))
    # Des réponses RÉELLES et les signatures, pour le test du navigateur (tableau-contrat.cjs).
    t2 = f('lg_open_tally', p_kind='ARRIVAL', p_source_type='list', p_tracking_numbers=[num(p1), 'SES-1111111111'])
    f('lg_tally_scan', p_tally_id=t2['tally_id'], p_code=num(p1))
    f('lg_tally_scan', p_tally_id=t2['tally_id'], p_code=num(p3))
    noms = ['lg_dashboard_access', 'lg_cc_command', 'lg_cc_vehicles', 'lg_cc_trips', 'lg_cc_expenses', 'lg_cc_tallies', 'lg_open_tally', 'lg_tally_scan', 'lg_tally_detail',
            'lg_close_tally', 'lg_clock', 'lg_my_clock', 'lg_clock_report', 'lg_clock_correct', 'lg_my_tasks',
            # le parc et les chauffeurs, depuis le tableau de bord (ses-modules.js : ajouter, modifier, changer de statut)
            'lg_create_driver', 'lg_update_driver', 'lg_set_driver_status', 'lg_set_driver_vehicle', 'lg_create_vehicle', 'lg_set_vehicle_status',
            # les agences, entrepôts et emplacements (étape 023)
            'lg_sites', 'lg_create_branch', 'lg_update_branch', 'lg_create_warehouse', 'lg_update_warehouse', 'lg_create_location', 'lg_set_location_active',
            # les expéditions et les transports (005, 016, 024)
            'lg_ready_for_shipment', 'lg_prepare_parcels', 'lg_create_shipment', 'lg_shipment_parcels', 'lg_shipment_summary', 'lg_plan_shipment', 'lg_generate_manifest',
            'lg_mark_shipment_ready', 'lg_reopen_shipment', 'lg_dispatch_shipment', 'lg_mark_shipment_in_transit', 'lg_arrive_shipment', 'lg_start_customs',
            'lg_customs_assess_duties', 'lg_customs_mark_duties_paid', 'lg_clear_customs', 'lg_reject_customs', 'lg_receive_at_hub', 'lg_close_shipment',
            'lg_cancel_shipment', 'lg_create_transport', 'lg_schedule_transport']
    return {
        'exemples': {'acces': acc['admin'], 'acces_chauffeur': acc['chauf'], 'commande': f('lg_cc_command', acteur=admin), 'commande_chauffeur': cartes['chauf'],
                     'vehicules': f('lg_cc_vehicles'), 'tournees': f('lg_cc_trips'), 'depenses': f('lg_cc_expenses', acteur=admin), 'pointages': f('lg_cc_tallies'),
                     'pointage': f('lg_tally_detail', p_tally_id=t2['tally_id']), 'pointage_clos': f('lg_tally_detail', p_tally_id=tid),
                     'journee': f('lg_my_clock', acteur=ops, p_date=hier), 'releve': rap, 'missions': f('lg_my_tasks', acteur=chauf),
                     'sites': f('lg_sites', acteur=admin)},
        'signatures': json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), "
                                   "'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) "
                                   "from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = any (%s)" % val(noms)))}


def main():
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        cl.run('postgres', "alter database prod set timezone to 'America/Port-au-Prince'")
        etapes = sorted(os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')))
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        n = q("select count(*) from logistics.event_type")
        cl.run('prod', P.lire_sql('outils/logistique/019-tableau-de-bord.sql'))
        ok(q("select count(*) from logistics.event_type") == n, '019 rejouée : rien en double')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and "
             "(has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))") == '0', 'aucune fonction du noyau ouverte')
        ok(q("select count(*) from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname in ('lg_dashboard_access', 'lg_cc_command', 'lg_cc_vehicles', 'lg_cc_trips', "
             "'lg_cc_expenses', 'lg_cc_tallies', 'lg_open_tally', 'lg_tally_scan', 'lg_tally_detail', 'lg_close_tally', 'lg_clock', 'lg_my_clock', 'lg_clock_report', 'lg_clock_correct') "
             "and has_function_privilege('authenticated', p.oid, 'execute') and not has_function_privilege('anon', p.oid, 'execute')") == '14', '14 façades : comptes connectés seulement')
        contrat = parcours(cl, 'prod', 'réplique')
        ici = os.path.dirname(os.path.abspath(__file__))
        ch_ex, ch_rpc = os.path.join(ici, 'tableau-exemples.json'), os.path.join(ici, 'tableau-rpc.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(contrat['exemples'], open(ch_ex, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            json.dump(contrat['signatures'], open(ch_rpc, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        cles = lambda x, c='': ({c + '.' + k for k in x} | set().union(*[cles(v, c + '.' + k) for k, v in x.items()]) if isinstance(x, dict)
                                else set().union(*[cles(v, c + '[]') for v in x]) if isinstance(x, list) else set())
        ok(cles(json.load(open(ch_ex, encoding='utf-8'))) == cles(contrat['exemples']) and json.load(open(ch_rpc, encoding='utf-8')) == contrat['signatures'],
           'la forme des réponses et les signatures sont celles des fichiers partagés avec le test du navigateur (sinon : SES_FORME_ECRIRE=1, et relire)')
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
        print('PASS tableau de bord (phase 7) : %d vérifications — sur la réplique ET la préproduction : modules décidés par la base pour chaque rôle, '
              'vue temps réel recomptée et filtrée par droits, véhicules, tournées, dépenses, pointage des colis et du personnel (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC tableau de bord (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
