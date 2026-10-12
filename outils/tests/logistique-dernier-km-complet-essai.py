#!/usr/bin/env python3
"""Phase 5 — le dernier kilomètre au complet (étape 017), éprouvé DEUX fois : sur la RÉPLIQUE DE LA PRODUCTION (noyau 001 → 017
par-dessus les données du 7 octobre) et sur une PRÉPRODUCTION montée comme la vraie (installation assemblée, données synthétiques).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-dernier-km-complet-essai.py

On exige :
 A. les quatre profils (chauffeur, agent de livraison, responsable de livraison, manager des opérations), décidés par la base, et les
    droits qui vont avec ;
 B. véhicules : statut avec motif (actif, maintenance, hors service), écarté par le moteur ; jamais retiré en pleine tournée ;
 C. zones : secteurs, zone trouvée par secteur puis par ville (accents et majuscules ignorés), ambiguïté laissée à l'équipe ;
    une livraison sans zone reçoit celle de sa ville ;
 D. chauffeurs : véhicule unique, fiche, statut avec motif, refusé tant que des missions sont ouvertes ;
 E. affectation automatique (zone, disponibilité, véhicule, capacité, charge, nombre d'arrêts) qui explique ses refus ; refus du
    chauffeur et réaffectation, motif obligatoire ;
 F. tournée : ordre des arrêts (équipe et chauffeur), ajout, retrait avec motif, annulation, démarrage ;
 G. preuve de livraison : code à usage unique, signature ou photo, nom, GPS, heure du téléphone ; en ajout seul ;
 H. incidents : client absent, adresse et téléphone incorrects, refus, dommage, colis manquant, livraison impossible ;
 I. le tableau du dernier kilomètre : missions du jour, en cours, chauffeurs actifs, échecs, incidents, SLA, preuves manquantes —
    chaque nombre recompté ici à la main, et le temps réel (un signal par changement) ; fermé aux clients et aux visiteurs ;
 J. l'application « Opérations » : la porte hors connexion (lg_mobile_command) rejoue une remise sans la refaire.
Jamais la production."""
import importlib.util
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


class R(str):
    """Fragment SQL brut (une date, une expression), jamais mis entre guillemets."""


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
        if not v:
            return "'{}'"
        return "array[%s]::%s[]" % (', '.join(val(x) for x in v), 'uuid' if re.match(r'^[0-9a-f-]{36}$', str(v[0])) else 'text')
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items()))


def parcours(cl, B, lieu):
    q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
    L = lambda sql: cl.lignes(B, sql)   # noqa: E731

    # ---------------------------------------------------------------- le décor : l'équipe de livraison
    comptes = {'resp': 'responsable', 'ch1': 'chauffeur un', 'ch2': 'chauffeur deux', 'ch3': 'chauffeur trois'}
    for i, (cle, nom) in enumerate(comptes.items()):
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0005-%012d', 'authenticated', 'authenticated', 'km-%s@essai.test', 'x', now(), '{\"nom_complet\": \"%s\"}')"
          % (i + 1, cle, nom))
        q("update public.clients set role = 'employe', droits = '{}', code = null where email = 'km-%s@essai.test'" % cle)
    q("update public.clients set droits = array['colis.lire', 'colis.statut', 'livraisons.gerer'] where email = 'km-resp@essai.test'")
    ok(json.loads(q("select logistics.run_migration('décor du dernier kilomètre')"))['report']['ready'] is True, '[%s] décor : rattrapage prêt' % lieu)
    uid = lambda email: q("select id from public.clients where email = '%s'" % email)   # noqa: E731
    equipe = lambda role: q("select id from public.clients where role = '%s' order by email limit 1" % role)   # noqa: E731
    admin, gerant = equipe('admin'), equipe('gerant')
    op = q("select id from public.clients where role = 'employe' and email not like 'km-%%' order by email limit 1")
    q("update logistics.app_user set rights = array['colis.lire', 'colis.statut'] where id = '%s'" % op)
    resp, ch1, ch2, ch3 = (uid('km-%s@essai.test' % k) for k in ('resp', 'ch1', 'ch2', 'ch3'))
    ok(q("select rights::text from logistics.app_user where id = '%s'" % resp) == '{colis.lire,colis.statut,livraisons.gerer}', '[%s] le droit « livraisons.gerer » passe du site au noyau' % lieu)
    clients = L("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1")
    client_compte = clients[0]
    cust = q("select id from logistics.customer where legacy_client_id = '%s'" % client_compte)
    org = q('select id from logistics.organization')
    q("insert into logistics.branch (organization_id, code, name, kind, country) select id, 'PAP', 'Hub Port-au-Prince', 'hub', 'HT' from logistics.organization")
    pap = q("select id from logistics.branch where code = 'PAP'")
    q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'PAP-1', 'Entrepôt Port-au-Prince')" % pap)
    wpap = q("select id from logistics.warehouse where code = 'PAP-1'")

    def f(nom, acteur=op, **kw):
        code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
        return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

    def fr(nom, etat, msg, acteur=op, **kw):
        code, texte = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
        ok(code != 0 and etat in texte, '[%s] %s : attendu %s, obtenu : %s' % (lieu, msg, etat, texte[-220:].replace('\n', ' ')))
        return texte

    n_colis = [0]

    def colis(ville='Pétion-Ville', poids=5, statut='AT_DESTINATION_HUB'):
        n_colis[0] += 1
        return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, destination_city, service_mode, status, "
                 "status_authority, source, weight_lb, declared_value, description, recipient_name, current_warehouse_id) values "
                 "('%s', 'SES-95%08d', 'jeton-k%d', '%s', 'HT', '%s', 'air', '%s', 'core', 'legacy_backfill', %s, 50, 'colis %d', 'Destinataire', '%s') returning id"
                 % (org, n_colis[0], n_colis[0], cust, ville.replace("'", "''"), statut, poids, n_colis[0], wpap))

    st = lambda pid: q("select status from logistics.parcel where id = '%s'" % pid)   # noqa: E731
    tst = lambda tid: q("select status from logistics.task where id = '%s'" % tid)   # noqa: E731

    def classement(tache):
        code, sortie = cl.run(B, "select json_agg(to_json(r)) from public.lg_rank_drivers('%s') r" % tache, role='authenticated', claims=op)
        return {x['driver_id']: x for x in json.loads(sortie)}

    def livraison(parcels, zone=None, **kw):
        a = dict(p_parcel_ids=parcels, p_hub_branch=pap, p_scheduled_for=R('current_date'), p_recipient_name='Marie', p_recipient_phone='+509 3000 0000',
                 p_address='12 rue Panaméricaine')
        if zone:
            a['p_zone_id'] = zone
        a.update(kw)
        return f('lg_create_delivery', **a)

    # ====================================================================== A. les quatre profils
    prof = lambda qui: f('lg_my_staff_profile', acteur=qui)   # noqa: E731
    ok('OPERATIONS_MANAGER' in prof(admin)['profiles'] and 'OPERATIONS_MANAGER' in prof(gerant)['profiles'], '[%s] A : gérant et administrateur : manager des opérations' % lieu)
    p_resp, p_op = prof(resp)['profiles'], prof(op)['profiles']
    ok('DELIVERY_MANAGER' in p_resp and 'DELIVERY_AGENT' in p_resp and 'OPERATIONS_MANAGER' not in p_resp, '[%s] A : responsable de livraison (et agent) : %s' % (lieu, p_resp))
    ok('DELIVERY_AGENT' in p_op and 'DELIVERY_MANAGER' not in p_op, '[%s] A : agent de livraison seulement : %s' % (lieu, p_op))
    ok(prof(client_compte)['staff'] is False, '[%s] A : un client n\'a aucun profil d\'équipe' % lieu)

    # ====================================================================== B. véhicules
    van1 = f('lg_create_vehicle', acteur=admin, p_plate='van-001', p_kind='VAN', p_capacity_lb=100, p_capacity_ft3=50, p_branch=pap)
    van2 = f('lg_create_vehicle', acteur=admin, p_plate='van-002', p_kind='VAN', p_capacity_lb=100, p_capacity_ft3=50, p_branch=pap)
    moto = f('lg_create_vehicle', acteur=admin, p_plate='moto-01', p_kind='MOTORCYCLE', p_capacity_lb=20, p_branch=pap)
    ok(q("select string_agg(status || '/' || active, ',' order by plate) from logistics.vehicle where plate in ('VAN-001', 'VAN-002', 'MOTO-01')") == 'ACTIVE/true,ACTIVE/true,ACTIVE/true',
       '[%s] B : trois véhicules actifs (agence : le hub)' % lieu)
    fr('lg_set_vehicle_status', 'LG003', 'un agent met un véhicule en maintenance', p_vehicle_id=van2, p_status='MAINTENANCE', p_reason='vidange')
    fr('lg_set_vehicle_status', 'motif', 'maintenance sans motif', acteur=resp, p_vehicle_id=van2, p_status='MAINTENANCE', p_reason=' ')
    v = f('lg_set_vehicle_status', acteur=resp, p_vehicle_id=van2, p_status='MAINTENANCE', p_reason='Vidange et freins')
    ok(v['status'] == 'MAINTENANCE' and q("select active from logistics.vehicle where id = '%s'" % van2) == 'f', '[%s] B : en maintenance : inactif pour le moteur' % lieu)
    code, texte = cl.run(B, "update logistics.vehicle set active = true where id = '%s'" % van2, expect_error=True)
    ok(code != 0, '[%s] B : statut et « actif » ne peuvent pas se contredire' % lieu)

    # ====================================================================== C. zones et secteurs
    zpv = f('lg_create_zone', acteur=admin, p_code='z-pv', p_name='Pétion-Ville', p_country='HT', p_cities=['Pétion-Ville'], p_branch=pap)
    zdel = f('lg_create_zone', acteur=admin, p_code='z-del', p_name='Delmas bas', p_country='HT', p_cities=['Delmas'], p_branch=pap)
    zdel2 = f('lg_create_zone', acteur=admin, p_code='z-del2', p_name='Delmas haut', p_country='HT', p_cities=['Delmas'], p_branch=pap)
    z = f('lg_update_zone', acteur=resp, p_zone_id=zdel, p_sectors=['Delmas 33', 'Delmas 19', ' '])
    ok(z['sectors'] == ['Delmas 19', 'Delmas 33'] and z['cities'] == ['Delmas'], '[%s] C : secteurs posés (triés, vides retirés), villes gardées' % lieu)
    f('lg_update_zone', acteur=resp, p_zone_id=zdel2, p_sectors=['Delmas 75'])
    fr('lg_update_zone', 'LG003', 'un agent modifie une zone', p_zone_id=zdel, p_name='x')
    r = f('lg_resolve_zone', p_country='HT', p_city='delmas', p_sector='DELMAS 75')
    ok(r['zone']['code'] == 'Z-DEL2' and r['matched_by'] == 'sector', '[%s] C : zone trouvée par le SECTEUR (majuscules ignorées)' % lieu)
    r = f('lg_resolve_zone', p_country='HT', p_city='Delmas')
    ok(r['zone'] is None and len(r['candidates']) == 2, '[%s] C : deux zones pour une ville : aucune choisie, les deux proposées' % lieu)
    r = f('lg_resolve_zone', p_country='HT', p_city='petion-ville')
    ok(r['zone']['code'] == 'Z-PV' and r['matched_by'] == 'city', '[%s] C : zone trouvée par la VILLE (accents ignorés)' % lieu)
    ok(f('lg_resolve_zone', p_country='DO', p_city='Pétion-Ville')['zone'] is None, '[%s] C : jamais dans un autre pays' % lieu)

    # ====================================================================== D. chauffeurs
    d1 = f('lg_create_driver', acteur=admin, p_user_id=ch1, p_full_name='Chauffeur Un', p_vehicle_id=van1, p_home_branch=pap, p_max_stops=3)
    d2 = f('lg_create_driver', acteur=admin, p_user_id=ch2, p_full_name='Chauffeur Deux', p_vehicle_id=moto, p_home_branch=pap)
    d3 = f('lg_create_driver', acteur=admin, p_user_id=ch3, p_full_name='Chauffeur Trois', p_home_branch=pap)
    ok('DRIVER' in prof(ch1)['profiles'] and prof(ch1)['driver']['vehicle'] == 'VAN-001', '[%s] D : le chauffeur se voit chauffeur, avec son véhicule' % lieu)
    fr('lg_set_driver_vehicle', 'déjà celui de', 'donner à un chauffeur le véhicule d\'un autre', acteur=resp, p_driver_id=d3, p_vehicle_id=van1)
    fr('lg_set_driver_vehicle', 'MAINTENANCE', 'donner un véhicule en maintenance', acteur=resp, p_driver_id=d3, p_vehicle_id=van2)
    f('lg_set_vehicle_status', acteur=resp, p_vehicle_id=van2, p_status='ACTIVE', p_reason='Révision faite')
    ok(f('lg_set_driver_vehicle', acteur=resp, p_driver_id=d3, p_vehicle_id=van2)['vehicle']['plate'] == 'VAN-002', '[%s] D : véhicule attribué' % lieu)
    u = f('lg_update_driver', acteur=resp, p_driver_id=d3, p_phone='+509 3700 0000', p_max_stops=5)
    ok(u['max_stops'] == 5 and u['phone'] == '+509 3700 0000' and u['name'] == 'Chauffeur Trois', '[%s] D : fiche mise à jour, le reste gardé' % lieu)
    fr('lg_update_driver', 'entre 1 et 200', 'un nombre d\'arrêts absurde', acteur=resp, p_driver_id=d3, p_max_stops=0)
    for d in (d1, d2, d3):
        f('lg_set_driver_zones', acteur=admin, p_driver=d, p_zone_ids=[zpv, zdel])
        f('lg_set_availability', p_driver=d, p_starts=R("now() - interval '6 hours'"), p_ends=R("now() + interval '10 hours'"))
    fr('lg_set_driver_status', 'motif', 'mettre un chauffeur en congé sans motif', acteur=resp, p_driver_id=d3, p_status='ON_LEAVE', p_reason='')
    f('lg_set_driver_status', acteur=resp, p_driver_id=d3, p_status='ON_LEAVE', p_reason='Congé annuel')
    ok(prof(ch3)['profiles'] == [] or 'DRIVER' not in prof(ch3)['profiles'], '[%s] D : en congé, il n\'est plus chauffeur pour l\'application' % lieu)

    # ====================================================================== E. affectation automatique
    lourd = colis(poids=30)
    t_lourd = livraison([lourd])['task_id']
    ok(q("select z.code from logistics.task t join logistics.delivery_zone z on z.id = t.zone_id where t.id = '%s'" % t_lourd) == 'Z-PV',
       '[%s] E : livraison sans zone donnée : celle de la ville du colis' % lieu)
    rang = classement(t_lourd)
    ok('CAPACITY_WEIGHT' in rang[d2]['reasons'] and rang[d1]['eligible'] and 'INACTIVE' in rang[d3]['reasons'],
       '[%s] E : la moto (20 lb) écartée pour 30 lb, le chauffeur en congé écarté, la camionnette retenue' % lieu)
    a = f('lg_auto_assign_task', p_task_id=t_lourd)
    ok(a['assigned'] and a['driver_id'] == d1, '[%s] E : proposée au chauffeur un' % lieu)
    fr('lg_refuse_task', 'motif', 'refuser sans motif', acteur=ch1, p_task_id=t_lourd, p_reason=' ')
    f('lg_refuse_task', acteur=ch1, p_task_id=t_lourd, p_reason='Pneu crevé')
    ok(tst(t_lourd) == 'CREATED' and 'REFUSED_BEFORE' in classement(t_lourd)[d1]['reasons'],
       '[%s] E : refusée : rendue au répartiteur, le moteur ne la lui repropose pas' % lieu)
    f('lg_set_driver_status', acteur=resp, p_driver_id=d3, p_status='ACTIVE', p_reason='Retour de congé')
    a = f('lg_auto_assign_task', p_task_id=t_lourd)
    ok(a['driver_id'] == d3, '[%s] E : reproposée au chauffeur trois (rentré de congé)' % lieu)
    fr('lg_assign_task', 'non éligible', 'reproposer la mission au chauffeur qui l\'a refusée, même à la main', p_task_id=t_lourd, p_driver_id=d1, p_reason='Il a réparé')
    f('lg_accept_task', acteur=ch3, p_task_id=t_lourd)
    ok(q("select string_agg(status, '>' order by offered_at, id) from logistics.assignment where task_id = '%s'" % t_lourd) == 'REFUSED>ACCEPTED',
       '[%s] E : historique des propositions : refusée par l\'un, acceptée par l\'autre' % lieu)
    # la journée : quatre petites livraisons, affectées d'un coup par le moteur
    petits = [livraison([colis()])['task_id'] for _ in range(4)]
    res = f('lg_auto_assign_day', p_date=R('current_date'))
    ok(res['assigned'] == 4, '[%s] E : la journée affectée d\'un coup (%s)' % (lieu, res))
    # réaffecter exige un motif
    actuel = q("select driver_id from logistics.task where id = '%s'" % petits[0])
    autre = d2 if actuel != d2 else d3
    fr('lg_assign_task', 'motif est obligatoire pour réaffecter', 'réaffecter sans motif', p_task_id=petits[0], p_driver_id=autre)
    r = f('lg_assign_task', p_task_id=petits[0], p_driver_id=autre, p_reason='Plus proche du client')
    ok(r['reassigned'] is True and q("select reason from logistics.assignment where task_id = '%s' and status = 'REASSIGNED'" % petits[0]) == 'Plus proche du client',
       '[%s] E : réaffectée avec motif, le motif gardé sur la proposition retirée' % lieu)
    # regrouper la journée sur le chauffeur un, jusqu'à son plafond de quatre arrêts
    f('lg_update_driver', acteur=resp, p_driver_id=d1, p_max_stops=4)
    for t in petits:
        if q("select driver_id from logistics.task where id = '%s'" % t) != d1:
            f('lg_assign_task', p_task_id=t, p_driver_id=d1, p_reason='Regrouper la tournée')
        f('lg_accept_task', acteur=ch1, p_task_id=t)
    charge = classement(livraison([colis()])['task_id'])
    ok('MAX_STOPS' in charge[d1]['reasons'] and not charge[d1]['eligible'],
       '[%s] E : quatre arrêts pour un plafond de quatre : le chauffeur un est écarté (MAX_STOPS) : %s' % (lieu, charge[d1]['reasons']))
    mes = petits

    # ====================================================================== D bis. statut refusé avec missions ouvertes
    fr('lg_set_driver_status', 'réaffectez-les', 'désactiver un chauffeur qui a des missions', acteur=resp, p_driver_id=d1, p_status='INACTIVE', p_reason='Fin de contrat')

    # ====================================================================== F. la tournée
    trip = f('lg_create_trip', p_driver_id=d1, p_trip_date=R('current_date'), p_task_ids=mes)['trip_id']
    det = f('lg_trip_detail', p_trip_id=trip)
    ok([s['task_id'] for s in det['stops']] == mes and det['vehicle']['plate'] == 'VAN-001', '[%s] F : tournée formée, arrêts dans l\'ordre donné' % lieu)
    ok(f('lg_trip_detail', acteur=ch1, p_trip_id=trip)['trip_id'] == trip, '[%s] F : le chauffeur voit SA tournée' % lieu)
    fr('lg_trip_detail', 'LG003', 'un autre chauffeur voit la tournée', acteur=ch2, p_trip_id=trip)
    fr('lg_reorder_trip', 'EXACTEMENT', 'un ordre qui oublie un arrêt', p_trip_id=trip, p_task_ids=mes[:-1])
    inverse = list(reversed(mes))
    det = f('lg_reorder_trip', p_trip_id=trip, p_task_ids=inverse)
    ok([s['task_id'] for s in det['stops']] == inverse and [s['sequence'] for s in det['stops']] == list(range(1, len(mes) + 1)), '[%s] F : arrêts réordonnés (1, 2, …)' % lieu)
    fr('lg_remove_task_from_trip', 'motif', 'retirer un arrêt sans motif', p_trip_id=trip, p_task_id=mes[0], p_reason='')
    det = f('lg_remove_task_from_trip', p_trip_id=trip, p_task_id=mes[0], p_reason='Client rappelle demain')
    ok(mes[0] not in [s['task_id'] for s in det['stops']] and q("select trip_id from logistics.task where id = '%s'" % mes[0]) == '', '[%s] F : arrêt retiré, la mission libre' % lieu)
    det = f('lg_add_task_to_trip', p_trip_id=trip, p_task_id=mes[0])
    ok(det['stops'][-1]['task_id'] == mes[0], '[%s] F : rajoutée, en dernier' % lieu)
    fr('lg_cancel_trip', 'LG003', 'un agent annule une tournée', p_trip_id=trip, p_reason='x')
    c = f('lg_cancel_trip', acteur=resp, p_trip_id=trip, p_reason='Camion bloqué')
    ok(c['status'] == 'CANCELLED' and c['tasks_released'] == len(mes), '[%s] F : tournée annulée, missions libérées' % lieu)
    trip = f('lg_create_trip', p_driver_id=d1, p_trip_date=R('current_date'), p_task_ids=mes)['trip_id']
    s = f('lg_start_trip', acteur=ch1, p_trip_id=trip)
    ok(s['tasks_started'] == len(mes) and all(tst(t) == 'STARTED' for t in mes), '[%s] F : tournée commencée : toutes les missions en cours' % lieu)
    fr('lg_set_vehicle_status', 'en tournée', 'mettre en maintenance un véhicule en tournée', acteur=resp, p_vehicle_id=van1, p_status='MAINTENANCE', p_reason='bruit')
    fr('lg_set_driver_vehicle', 'en tournée', 'changer le véhicule d\'un chauffeur en route', acteur=resp, p_driver_id=d1, p_vehicle_id=None)
    det = f('lg_reorder_trip', acteur=ch1, p_trip_id=trip, p_task_ids=list(reversed(mes)))
    ok([s_['task_id'] for s_ in det['stops']] == list(reversed(mes)), '[%s] F : en route, le chauffeur réordonne ses arrêts' % lieu)

    # ====================================================================== G. preuve de livraison
    t_otp, t_late, t_ok, t_fail = mes[0], mes[1], mes[2], mes[3]
    f('lg_issue_delivery_otp', p_task_id=t_otp)
    code_otp = q("select payload ->> 'code' from logistics.notification where template = 'DeliveryOtp' and payload ->> 'task_id' = '%s' order by created_at desc limit 1" % t_otp)
    ok(re.match(r'^\d{6}$', code_otp or '') is not None, '[%s] G : code à usage unique envoyé au DESTINATAIRE' % lieu)
    mauvais = '000000' if code_otp != '000000' else '111111'
    r = f('lg_complete_delivery', acteur=ch1, p_task_id=t_otp, p_recipient_name='Marie', p_latitude=18.51, p_longitude=-72.28, p_photo_path='pod/%s/photo.jpg' % t_otp, p_otp=mauvais)
    ok(r['completed'] is False and r['reason'] == 'OTP_INVALID', '[%s] G : mauvais code : remise refusée, essai compté' % lieu)
    fr('lg_complete_delivery', 'GPS', 'remettre sans position', acteur=ch1, p_task_id=t_otp, p_recipient_name='Marie', p_latitude=None, p_longitude=None, p_photo_path='pod/%s/p.jpg' % t_otp, p_otp=code_otp)
    fr('lg_complete_delivery', 'signature ou une photo', 'remettre sans signature ni photo', acteur=ch1, p_task_id=t_otp, p_recipient_name='Marie', p_latitude=18.5, p_longitude=-72.2, p_otp=code_otp)
    fr('lg_complete_delivery', 'destinataire', 'remettre sans nom', acteur=ch1, p_task_id=t_otp, p_recipient_name=' ', p_latitude=18.5, p_longitude=-72.2, p_photo_path='pod/%s/p.jpg' % t_otp, p_otp=code_otp)
    r = f('lg_complete_delivery', acteur=ch1, p_task_id=t_otp, p_recipient_name='Marie', p_latitude=18.51, p_longitude=-72.28,
          p_signature_path='pod/%s/signature.png' % t_otp, p_photo_path='pod/%s/photo.jpg' % t_otp, p_otp=code_otp)
    ok(r['completed'] is True and q("select otp_verified::text || '|' || (signature_path is not null)::text || '|' || (captured_at is not null)::text from logistics.proof_of_delivery where task_id = '%s'" % t_otp) == 'true|true|true',
       '[%s] G : remise avec code vérifié, signature, photo, nom, GPS, heure' % lieu)
    # l'application hors connexion : la remise faite il y a deux heures, envoyée maintenant, garde son heure ; rejouée, rien n'est refait
    args = {'task_id': t_late, 'recipient_name': 'Jean', 'latitude': 18.52, 'longitude': -72.29, 'photo_path': 'pod/%s/cle-1.jpg' % t_late,
            'recorded_at': q("select to_char((now() - interval '2 hours') at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"')")}
    m1 = f('lg_mobile_command', acteur=ch1, p_key='tel-ch1-remise-1', p_command='complete_delivery', p_args=args)
    m2 = f('lg_mobile_command', acteur=ch1, p_key='tel-ch1-remise-1', p_command='complete_delivery', p_args=args)
    ecart = float(q("select extract(epoch from (now() - captured_at)) / 60 from logistics.proof_of_delivery where task_id = '%s'" % t_late))
    ok(m1['completed'] is True and m2.get('replayed') is True and 115 <= ecart <= 125 and q("select count(*) from logistics.proof_of_delivery where task_id = '%s'" % t_late) == '1',
       '[%s] J : remise envoyée par l\'application après une coupure : heure du téléphone (il y a %.0f min), rejouée sans doublon' % (lieu, ecart))
    args2 = dict(args, task_id=t_ok, photo_path='pod/%s/cle-2.jpg' % t_ok, recorded_at='2001-01-01T00:00:00Z')
    f('lg_mobile_command', acteur=ch1, p_key='tel-ch1-remise-2', p_command='complete_delivery', p_args=args2)
    ok(float(q("select extract(epoch from (now() - captured_at)) from logistics.proof_of_delivery where task_id = '%s'" % t_ok)) < 120,
       '[%s] G : une heure de téléphone absurde (2001) n\'est pas crue : heure de la base' % lieu)
    for sql in ("update logistics.proof_of_delivery set recipient_name = 'X' where task_id = '%s'" % t_otp, "delete from logistics.proof_of_delivery where task_id = '%s'" % t_otp):
        code, texte = cl.run(B, sql, expect_error=True)
        ok(code != 0, '[%s] G : la preuve est en AJOUT SEUL (%s)' % (lieu, sql.split()[0]))

    # ====================================================================== H. incidents
    fr('lg_fail_task', 'inconnu', 'un genre d\'incident inconnu', acteur=ch1, p_task_id=t_fail, p_incident_type='EXTRATERRESTRE')
    f('lg_fail_task', acteur=ch1, p_task_id=t_fail, p_incident_type='MISSING_PARCEL', p_description='Le carton n\'est pas dans le camion')
    ok(q("select type || '/' || severity from logistics.incident where task_id = '%s'" % t_fail) == 'MISSING_PARCEL/HIGH' and tst(t_fail) == 'FAILED',
       '[%s] H : colis manquant : incident GRAVE, mission échouée' % lieu)
    f('lg_complete_trip', acteur=ch1, p_trip_id=trip)
    genres = []
    for genre in ('WRONG_PHONE', 'DELIVERY_IMPOSSIBLE', 'CUSTOMER_ABSENT', 'WRONG_ADDRESS', 'REFUSED', 'DAMAGED'):
        t = livraison([colis()], zone=zpv)['task_id']
        f('lg_assign_task', p_task_id=t, p_driver_id=d1)
        f('lg_accept_task', acteur=ch1, p_task_id=t)
        f('lg_start_task', acteur=ch1, p_task_id=t)
        if genre == 'DAMAGED':
            f('lg_mobile_command', acteur=ch1, p_key='tel-ch1-echec-1', p_command='fail_task', p_args={'task_id': t, 'incident_type': genre, 'description': 'écrasé'})
        else:
            f('lg_fail_task', acteur=ch1, p_task_id=t, p_incident_type=genre)
        genres.append((t, genre))
    ok(all(q("select type from logistics.incident where task_id = '%s'" % t) == g for t, g in genres), '[%s] H : les sept genres d\'incident d\'une livraison sont acceptés' % lieu)
    # une livraison replanifiée après un échec puis réussie : pas un « premier passage »
    t_re = genres[2][0]
    f('lg_reschedule_task', p_task_id=t_re, p_new_date=R('current_date'))
    f('lg_assign_task', p_task_id=t_re, p_driver_id=d1)
    f('lg_accept_task', acteur=ch1, p_task_id=t_re)
    f('lg_start_task', acteur=ch1, p_task_id=t_re)
    f('lg_complete_delivery', acteur=ch1, p_task_id=t_re, p_recipient_name='Paul', p_latitude=18.5, p_longitude=-72.3, p_photo_path='pod/%s/p.jpg' % t_re)
    # une livraison promise pour une fenêtre déjà passée, livrée maintenant : EN RETARD
    t_tard = livraison([colis()], zone=zpv, p_window_start=R("now() - interval '3 hours'"), p_window_end=R("now() - interval '1 hour'"))['task_id']
    f('lg_assign_task', p_task_id=t_tard, p_driver_id=d1)
    f('lg_accept_task', acteur=ch1, p_task_id=t_tard)
    f('lg_start_task', acteur=ch1, p_task_id=t_tard)
    f('lg_complete_delivery', acteur=ch1, p_task_id=t_tard, p_recipient_name='Luc', p_latitude=18.5, p_longitude=-72.3, p_photo_path='pod/%s/p.jpg' % t_tard)
    # une livraison en cours (pour « en cours »), une annulée par le responsable
    t_cours = livraison([colis()], zone=zpv)['task_id']
    f('lg_assign_task', p_task_id=t_cours, p_driver_id=d1)
    f('lg_accept_task', acteur=ch1, p_task_id=t_cours)
    f('lg_start_task', acteur=ch1, p_task_id=t_cours)
    t_ann = livraison([colis()], zone=zpv)['task_id']
    fr('lg_cancel_task', 'LG003', 'un agent annule une mission', p_task_id=t_ann, p_reason='doublon')
    f('lg_cancel_task', acteur=resp, p_task_id=t_ann, p_reason='Doublon de saisie')
    ok(tst(t_ann) == 'CANCELLED', '[%s] H : le responsable de livraison annule une mission (avec motif)' % lieu)
    # une dérogation de la direction : livré sans preuve (tracé)
    sans = colis(statut='OUT_FOR_DELIVERY')
    f('lg_deliver_without_proof', acteur=admin, p_parcel_id=sans, p_reason='Remis au gardien, application en panne')

    # ====================================================================== I. le tableau du dernier kilomètre
    signaux_avant = int(q("select count(*) from public.ses_signal where audience = 'staff'"))
    fr('lg_cc_last_mile', 'LG003', 'un client ouvre le tableau', acteur=client_compte)
    code, texte = cl.run(B, appel('lg_cc_last_mile'), role='anon', expect_error=True)
    ok(code != 0 and '42501' in texte, '[%s] I : un visiteur n\'appelle pas le tableau' % lieu)
    db = f('lg_cc_last_mile')
    # chaque nombre recompté ici, directement dans les tables
    attendu = {s_: int(q("select count(*) from logistics.task where scheduled_date = logistics.today() and status = '%s'" % s_)) for s_ in
               ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED', 'COMPLETED', 'FAILED', 'CANCELLED')}
    ok(db['tasks']['by_status'] == attendu and db['tasks']['total'] == sum(attendu.values()) - attendu['CANCELLED'],
       '[%s] I : missions du jour par état = le compte des tables : %s' % (lieu, db['tasks']['by_status']))
    ok({x['task_id'] for x in db['in_progress']} == set(L("select id from logistics.task where status = 'STARTED'")) and t_cours in {x['task_id'] for x in db['in_progress']},
       '[%s] I : livraisons en cours' % lieu)
    ok(db['drivers']['active'] == int(q("select count(*) from logistics.driver d join logistics.app_user u on u.id = d.user_id and u.active where d.status = 'ACTIVE'"))
       and db['drivers']['on_duty'] >= 1 and any(x['driver_id'] == d1 and x['on_duty'] for x in db['drivers']['items']),
       '[%s] I : chauffeurs actifs, et le chauffeur un en service' % lieu)
    echecs_jour = int(q("select count(*) from logistics.task_status_history h where h.to_status = 'FAILED' and h.occurred_at >= logistics.day_start(logistics.today())"))
    ok(db['failed']['count'] == echecs_jour == 7 and any(x['reason'] == 'MISSING_PARCEL' for x in db['failed']['items']),
       '[%s] I : échecs du jour, même replanifiés (7)' % lieu)
    ok(db['incidents']['by_type'].get('MISSING_PARCEL') == 1 and db['incidents']['by_type'].get('WRONG_PHONE') == 1 and db['incidents']['high'] >= 3,
       '[%s] I : incidents ouverts par genre : %s' % (lieu, db['incidents']['by_type']))
    sla = db['sla']
    livrees = int(q("select count(*) from logistics.task where kind = 'DELIVERY' and scheduled_date = logistics.today() and status = 'COMPLETED'"))
    ok(sla['completed'] == livrees and sla['late_completed'] == 1 and sla['on_time'] == livrees - 1 and sla['first_attempt'] == livrees - 1,
       '[%s] I : SLA : %d livrées, 1 en retard (fenêtre passée), 1 au second passage : %s' % (lieu, livrees, sla))
    ok(abs(sla['on_time_rate'] - round((livrees - 1) / livrees, 4)) < 1e-9 and sla['target'] == 0.95 and sla['met'] is (sla['on_time_rate'] >= 0.95),
       '[%s] I : taux à l\'heure et cible' % lieu)
    ok(sla['failed'] == int(q("select count(*) from logistics.task where kind = 'DELIVERY' and scheduled_date = logistics.today() and status = 'FAILED'")), '[%s] I : échecs restés échoués' % lieu)
    mp = db['missing_pod']
    ok(mp['derogations_today'] == 1 and mp['anomalies'] == 0 and mp['completed_tasks_without_proof'] == 0 and mp['items'][0]['reason'].startswith('Remis au gardien'),
       '[%s] I : preuves manquantes : une dérogation tracée, aucune anomalie : %s' % (lieu, {k: mp[k] for k in mp if k != 'items'}))
    # le temps réel : un changement produit un signal pour l'équipe, l'écran relit
    f('lg_update_driver', acteur=resp, p_driver_id=d2, p_phone='+509 3800 0000')
    ok(int(q("select count(*) from public.ses_signal where audience = 'staff'")) > signaux_avant and q("select topic from public.ses_signal where audience = 'staff' order by id desc limit 1") == 'driver',
       '[%s] I : temps réel : le changement émet un signal « driver » pour l\'équipe' % lieu)
    # le statut d'un chauffeur une fois ses missions closes
    ok(q("select count(*) from logistics.audit_log where action in ('driver.status', 'vehicle.status', 'driver.vehicle', 'driver.update', 'zone.update', 'trip.cancel')") != '0',
       '[%s] chaque geste de gestion est audité' % lieu)
    # La réponse réelle du tableau et les signatures des deux fonctions que le site appelle : figées pour le test du navigateur.
    return {'exemple': f('lg_cc_last_mile'),
            'signatures': json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), "
                                       "'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) "
                                       "from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname in ('lg_cc_last_mile', 'lg_auto_assign_day')"))}


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
        n = '|'.join(q("select count(*) from logistics.%s" % t) for t in ('event_type', 'task_transition', 'parcel_transition'))
        cl.run('prod', P.lire_sql('outils/logistique/017-dernier-kilometre-complet.sql'))
        ok('|'.join(q("select count(*) from logistics.%s" % t) for t in ('event_type', 'task_transition', 'parcel_transition')) == n, '017 rejouée : rien en double')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and "
             "(has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))") == '0',
           'aucune fonction du noyau n\'est ouverte à anon ou authenticated')
        facades = cl.lignes('prod', "select p.proname from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname in ('lg_set_driver_status', 'lg_set_driver_vehicle', "
                                    "'lg_update_driver', 'lg_set_vehicle_status', 'lg_update_zone', 'lg_resolve_zone', 'lg_reorder_trip', 'lg_add_task_to_trip', 'lg_remove_task_from_trip', "
                                    "'lg_cancel_trip', 'lg_trip_detail', 'lg_cc_last_mile') and has_function_privilege('authenticated', p.oid, 'execute') and not has_function_privilege('anon', p.oid, 'execute')")
        ok(len(facades) == 12, '12 façades nouvelles : comptes connectés seulement (%d)' % len(facades))
        ok(q("select count(*) from information_schema.role_table_grants where table_schema = 'logistics' and grantee in ('anon', 'authenticated', 'PUBLIC')") == '0', 'aucun droit direct sur les tables')
        contrat = parcours(cl, 'prod', 'réplique')
        ici = os.path.dirname(os.path.abspath(__file__))
        ch_ex, ch_rpc = os.path.join(ici, 'dernier-km-exemple.json'), os.path.join(ici, 'dernier-km-rpc.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(contrat['exemple'], open(ch_ex, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            json.dump(contrat['signatures'], open(ch_rpc, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        cles = lambda x, c='': ({c + '.' + k for k in x} | set().union(*[cles(v, c + '.' + k) for k, v in x.items()]) if isinstance(x, dict)
                                else set().union(*[cles(v, c + '[]') for v in x]) if isinstance(x, list) else set())
        ok(cles(json.load(open(ch_ex, encoding='utf-8'))) == cles(contrat['exemple']) and json.load(open(ch_rpc, encoding='utf-8')) == contrat['signatures'],
           'la forme du tableau et les signatures sont celles des fichiers partagés avec le test du navigateur (sinon : SES_FORME_ECRIRE=1, et relire)')
        ok(q('select count(*) from logistics.workflow_inconsistencies()') == '0', 'réplique : aucun colis incohérent après le dernier kilomètre')

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
        ok(cl.un('staging', "select nom from ses_meta.environnement") == 'staging', 'préproduction : marquée « staging »')
        parcours(cl, 'staging', 'préproduction')
        ok(cl.un('staging', 'select count(*) from logistics.workflow_inconsistencies()') == '0', 'préproduction : aucun colis incohérent')

        print('PASS dernier kilomètre complet (phase 5) : %d vérifications — sur la réplique ET la préproduction : quatre profils, véhicules et chauffeurs '
              '(statuts avec motif), zones et secteurs, affectation automatique expliquée, refus et réaffectation motivés, tournée (ordre, ajout, retrait, '
              'annulation), preuve de livraison en ajout seul avec l\'heure du téléphone, sept incidents, tableau temps réel recompté (SLA, échecs, preuves '
              'manquantes), porte de l\'application (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC dernier kilomètre complet (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
