#!/usr/bin/env python3
"""Noyau logistique, phase 9 : chauffeurs, enlèvements, livraisons, preuve — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-dernier-km-essai.py

Jamais la production. On éprouve : la préparation (véhicules, zones, chauffeurs, disponibilités), le moteur d'affectation règle par
règle (et ses explications), le cycle d'une mission (créée, proposée, acceptée, refusée, réaffectée, commencée, terminée, échouée,
replanifiée, annulée), les tournées, la preuve de livraison (nom, signature, photo, heure, GPS, code à usage unique), les sept incidents,
et la règle de fond : un colis ne passe « livré » qu'avec une preuve."""
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
    if isinstance(v, (list, tuple)):
        if not v:
            return "'{}'"
        return "array[%s]::%s[]" % (', '.join(val(x) for x in v), 'uuid' if v and re.match(r'^[0-9a-f-]{36}$', str(v[0])) else 'text')
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items()))


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        P.monter_historique(cl, B)
        for f_ in ('001-modele-de-domaine', '002-retroremplissage', '003-machine-d-etats', '004-entrepot', '005-transport-douane'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f_))
        avant_legacy = P.empreintes_historiques(cl, B)
        cl.run(B, P.lire_sql('outils/logistique/006-dernier-kilometre.sql'))
        compte = lambda: tuple(q('select count(*) from logistics.%s' % t) for t in ('parcel_transition', 'task_transition', 'event_type', 'task_status'))   # noqa: E731
        c1 = compte()
        cl.run(B, P.lire_sql('outils/logistique/006-dernier-kilometre.sql'))
        ok(c1 == compte(), '006 rejouée : aucune ligne en double')
        ok(c1[0] == '89', 'la phase 9 ajoute DEUX transitions de colis (retour au hub) : 87 + 2 = 89, obtenu %s' % c1[0])
        ok(c1[1] == '13', '13 transitions de mission')
        ok(avant_legacy == P.empreintes_historiques(cl, B), 'les anciennes tables n\'ont pas bougé d\'un octet')

        # Les chauffeurs sont des membres de l'ÉQUIPE : employés dans l'ancien schéma, sans aucun droit coché, sans colis ni facture.
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) "
          "select '00000000-0000-0000-0000-000000000000', ('00000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid, 'authenticated', 'authenticated', "
          "'chauffeur' || i || '@essai.test', '$2a$10$fictif', now(), jsonb_build_object('nom_complet', 'Chauffeur ' || i, 'pays', 'Haïti', 'ville', 'Delmas', 'adresse', 'x', 'telephone', '+509 3000', 'langue', 'fr') "
          "from generate_series(21, 24) i")
        q("update public.clients set role = 'employe', droits = '{}' where email like 'chauffeur%@essai.test'")
        q('select logistics.backfill_from_legacy()')
        ok(q("select count(*) from logistics.reconcile_with_legacy()") == '0', 'la réconciliation avec l\'ancien schéma reste à 0 écart')

        uid = lambda n: q("select id from public.clients where email = 'client%d@essai.test'" % n)   # noqa: E731
        admin, gerant, op, sansdroit, cli = uid(1), uid(2), uid(3), uid(6), uid(9)
        q("insert into logistics.app_user (id, organization_id, role, rights) select '%s', id, 'employee', '{}' from logistics.organization" % sansdroit)
        u1, u2, u3, u4 = (q("select id from public.clients where email = 'chauffeur%d@essai.test'" % n) for n in (21, 22, 23, 24))
        q("insert into logistics.branch (organization_id, code, name, kind, country) select id, 'PAP', 'Hub Port-au-Prince', 'hub', 'HT' from logistics.organization")
        pap = q("select id from logistics.branch where code = 'PAP'")
        org = q('select id from logistics.organization')
        customers = cl.lignes(B, "select id from logistics.customer order by code limit 3")
        n_p = [0]

        def colis(statut='AT_DESTINATION_HUB', cust=None, poids=None):
            n_p[0] += 1
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source, weight_lb, declared_value, description, recipient_name) "
                     "values ('%s', 'D-%d', 'tok', '%s', 'HT', 'air', '%s', 'core', 'legacy_backfill', %s, 100, 'colis %d', 'Destinataire %d') returning id" % (
                         org, n_p[0], cust or customers[0], statut, poids or (10 + n_p[0]), n_p[0], n_p[0]))

        def f(nom, acteur=op, **kw):
            code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
            return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

        def fr(nom, etat, msg, acteur=op, **kw):
            code, texte = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
            ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-190:].replace('\n', ' ')))

        def refuse(sql, etat, msg):
            code, texte = cl.run(B, sql, expect_error=True)
            ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-190:].replace('\n', ' ')))

        st = lambda t, i: q("select status from logistics.%s where id = '%s'" % (t, i))   # noqa: E731
        pst = lambda i: q("select status from logistics.parcel where id = '%s'" % i)   # noqa: E731
        J = lambda s: json.loads(q(s))   # noqa: E731
        T = lambda h, j='2026-11-10': q("select (logistics.day_start(date '%s') + interval '%s')::text" % (j, h))   # noqa: E731
        JOUR = '2026-11-10'
        PAP_LAT, PAP_LON = 18.5392, -72.3350

        # ============================================================== A. la préparation : droits, véhicules, zones, chauffeurs
        fr('lg_create_vehicle', 'LG003', 'créer un véhicule sans être direction', acteur=op, p_plate='AA-1', p_kind='VAN', p_capacity_lb=500)
        fr('lg_create_zone', 'LG003', 'créer une zone sans être direction', acteur=op, p_code='PV', p_name='x', p_country='HT')
        van1, van2 = (f('lg_create_vehicle', acteur=admin, p_plate=pl, p_kind='VAN', p_capacity_lb=500, p_capacity_ft3=100) for pl in ('aa-100', 'AA-200'))
        moto = f('lg_create_vehicle', acteur=gerant, p_plate='MM-1', p_kind='MOTORCYCLE', p_capacity_lb=50, p_capacity_ft3=10)
        ok(q("select plate from logistics.vehicle where id = '%s'" % van1) == 'AA-100', 'la plaque est mise en majuscules')
        refuse("insert into logistics.vehicle (plate, kind, capacity_lb) values ('AA-100', 'VAN', 100)", '23505', 'plaque en double')
        refuse("insert into logistics.vehicle (plate, kind, capacity_lb) values ('ZZ-1', 'BATEAU', 100)", '23514', 'type de véhicule inconnu')
        refuse("insert into logistics.vehicle (plate, kind, capacity_lb) values ('ZZ-2', 'VAN', 0)", '23514', 'capacité nulle')
        z1 = f('lg_create_zone', acteur=admin, p_code='pv', p_name='Pétion-Ville', p_country='HT', p_cities=['Pétion-Ville', 'Delmas'])
        z2 = f('lg_create_zone', acteur=admin, p_code='CDM', p_name='Carrefour', p_country='HT')
        fr('lg_create_driver', 'LG003', 'créer un chauffeur sans être direction', acteur=op, p_user_id=u1, p_full_name='X')
        fr('lg_create_driver', 'LG002', 'chauffeur sans compte d\'équipe (un client)', acteur=admin, p_user_id=cli, p_full_name='X')
        d1 = f('lg_create_driver', acteur=admin, p_user_id=u1, p_full_name='Chauffeur Un', p_phone='+509 3000 0001', p_vehicle_id=van1)
        d2 = f('lg_create_driver', acteur=admin, p_user_id=u2, p_full_name='Chauffeur Deux', p_vehicle_id=van2)
        d3 = f('lg_create_driver', acteur=admin, p_user_id=u3, p_full_name='Chauffeur Trois', p_vehicle_id=moto)
        d4 = f('lg_create_driver', acteur=admin, p_user_id=u4, p_full_name='Chauffeur Quatre')
        ok(q("select role from logistics.app_user where id = '%s'" % u1) == 'employee', 'un chauffeur reste un EMPLOYÉ de l\'équipe : son rôle ne change pas')
        ok(q("select count(*) from logistics.customer where auth_user_id in ('%s','%s','%s','%s')" % (u1, u2, u3, u4)) == '0', 'et il n\'a pas de profil client (l\'équipe n\'est pas la clientèle)')
        fr('lg_create_driver', '23505', 'deux fiches pour le même compte', acteur=admin, p_user_id=u1, p_full_name='Doublon')
        for d, z in ((d1, [z1]), (d2, [z1, z2]), (d3, [z2]), (d4, [z1])):
            f('lg_set_driver_zones', acteur=admin, p_driver=d, p_zone_ids=z)
        ok(q("select count(*) from logistics.driver_zone") == '5', 'zones des chauffeurs enregistrées')
        fr('lg_set_driver_zones', 'LG003', 'attribuer des zones sans être direction', acteur=op, p_driver=d1, p_zone_ids=[z2])
        for d in (d1, d2, d4):
            f('lg_set_availability', acteur=op, p_driver=d, p_starts=T('8 hours'), p_ends=T('18 hours'))
        f('lg_set_availability', acteur=op, p_driver=d3, p_starts=T('8 hours'), p_ends=T('12 hours'))
        fr('lg_set_availability', 'LG005', 'créneau à l\'envers', acteur=op, p_driver=d1, p_starts=T('10 hours'), p_ends=T('9 hours'))
        fr('lg_set_availability', 'LG003', 'déclarer les disponibilités d\'un AUTRE chauffeur sans droit', acteur=u2, p_driver=d1, p_starts=T('8 hours'), p_ends=T('9 hours'))
        f('lg_set_availability', acteur=u1, p_driver=d1, p_starts=T('19 hours'), p_ends=T('20 hours'), p_note='heures sup')
        ok(q("select count(*) from logistics.driver_availability where driver_id = '%s'" % d1) == '2', 'un chauffeur déclare SES propres disponibilités')
        fr('lg_update_driver_position', 'LG003', 'position d\'un non-chauffeur', acteur=op, p_latitude=18.5, p_longitude=-72.3)
        fr('lg_update_driver_position', 'LG005', 'latitude hors du globe', acteur=u1, p_latitude=95, p_longitude=-72.3)
        f('lg_update_driver_position', acteur=u1, p_latitude=18.5400, p_longitude=-72.3340)
        f('lg_update_driver_position', acteur=u2, p_latitude=18.5800, p_longitude=-72.2900)
        f('lg_update_driver_position', acteur=u3, p_latitude=18.5400, p_longitude=-72.3300)
        ok(q("select last_position_at is not null from logistics.driver where id = '%s'" % d1) == 't', 'la position du chauffeur est datée')
        ok(q("select count(*) from logistics.domain_event where aggregate_type = 'driver'") == '0', 'la simple position GPS ne produit PAS d\'événement (trop bavard)')

        # ============================================================== B. l'enlèvement
        fr('lg_create_pickup_task', 'LG003', 'enlèvement sans droit', acteur=sansdroit, p_customer_id=customers[0], p_address='1 rue A', p_scheduled_date=JOUR)
        fr('lg_create_pickup_task', 'LG005', 'enlèvement sans adresse', p_customer_id=customers[0], p_address='  ', p_scheduled_date=JOUR)
        fr('lg_create_pickup_task', 'LG002', 'enlèvement pour un client inconnu', p_customer_id='11111111-1111-1111-1111-111111111111', p_address='1 rue A', p_scheduled_date=JOUR)
        pk = f('lg_create_pickup_task', p_customer_id=customers[0], p_address='12 rue des Rosiers, Pétion-Ville', p_scheduled_date=JOUR,
               p_latitude=PAP_LAT, p_longitude=PAP_LON, p_window_start=T('9 hours'), p_window_end=T('12 hours'), p_zone_id=z1, p_priority=2, p_parcels_expected=2, p_weight_lb=30)
        pkid = pk['task_id']
        ok(pk['status'] == 'CREATED' and pk['kind'] == 'PICKUP', 'ENLÈVEMENT créé en statut CREATED')
        ok(q("select count(*) from logistics.pickup_task where id = '%s'" % pkid) == '1' and q("select count(*) from logistics.delivery_task where id = '%s'" % pkid) == '0', 'la vue « pickup_task » le montre ; « delivery_task » non')
        r = f('lg_auto_assign_task', p_task_id=pkid)
        ok(r['assigned'] is True and r['driver_id'] == d1, 'le moteur propose l\'enlèvement au chauffeur le plus PROCHE (Un)')
        cand = {c['driver_id']: c for c in r['candidates']}
        ok('ZONE' in cand[d3]['reasons'] and not cand[d3]['eligible'], 'le chauffeur Trois est écarté : mauvaise ZONE')
        ok('NO_VEHICLE' in cand[d4]['reasons'], 'le chauffeur Quatre est écarté : PAS DE VÉHICULE')
        ok(cand[d2]['eligible'] and cand[d2]['score'] < cand[d1]['score'], 'le chauffeur Deux est éligible mais plus loin : note plus basse')
        ok(st('task', pkid) == 'ASSIGNED' and q("select status from logistics.assignment where task_id = '%s'" % pkid) == 'OFFERED', 'mission ASSIGNED, proposition OFFERED')
        fr('lg_accept_task', 'LG003', 'accepter la mission d\'un AUTRE chauffeur', acteur=u2, p_task_id=pkid)
        fr('lg_accept_task', 'LG003', 'accepter sans être chauffeur', acteur=op, p_task_id=pkid)
        f('lg_accept_task', acteur=u1, p_task_id=pkid)
        fr('lg_accept_task', 'LG004', 'accepter deux fois', acteur=u1, p_task_id=pkid)
        fr('lg_complete_pickup', 'LG001', 'terminer un enlèvement non commencé', acteur=u1, p_task_id=pkid, p_parcel_ids=[colis('CREATED', customers[0])])
        f('lg_start_task', acteur=u1, p_task_id=pkid)
        fr('lg_start_task', 'LG001', 'commencer deux fois', acteur=u1, p_task_id=pkid)
        a1, a2 = colis('CREATED', customers[0]), colis('CREATED', customers[0])
        autre, recu = colis('CREATED', customers[1]), colis('STORED', customers[0])
        fr('lg_complete_pickup', 'LG005', 'terminer sans aucun colis', acteur=u1, p_task_id=pkid, p_parcel_ids=[])
        fr('lg_complete_pickup', 'LG005', 'colis d\'un AUTRE client', acteur=u1, p_task_id=pkid, p_parcel_ids=[a1, autre])
        fr('lg_complete_pickup', 'LG005', 'colis déjà reçu en entrepôt', acteur=u1, p_task_id=pkid, p_parcel_ids=[a1, recu])
        ok(q("select count(*) from logistics.pickup_parcel") == '0', 'les refus n\'ont rien enregistré (tout ou rien)')
        r = f('lg_complete_pickup', acteur=u1, p_task_id=pkid, p_parcel_ids=[a1, a2])
        ok(r['status'] == 'COMPLETED' and r['collected'] == 2, 'ENLÈVEMENT terminé : 2 colis collectés')
        ok(q("select count(*) from logistics.pickup_parcel where task_id = '%s'" % pkid) == '2', 'les colis sont rattachés à l\'enlèvement')
        ok(q("select string_agg(to_status, '>' order by id) from logistics.task_status_history where task_id = '%s'" % pkid) == 'CREATED>ASSIGNED>ACCEPTED>STARTED>COMPLETED', 'historique de la mission : 5 états dans l\'ordre')
        evp = q("select string_agg(event_type, '>' order by id) from logistics.domain_event where aggregate_id = '%s'" % pkid)
        ok(evp == 'PickupRequested>TaskAssigned>TaskAccepted>TaskStarted>TaskCompleted>PickupCompleted', 'événements de l\'enlèvement dans l\'ordre : %s' % evp)
        ok(q("select status from logistics.assignment where task_id = '%s'" % pkid) == 'COMPLETED', 'la proposition est terminée avec la mission')
        sec = f('lg_create_pickup_task', p_customer_id=customers[0], p_address='12 rue des Rosiers', p_scheduled_date=JOUR)['task_id']
        f('lg_assign_task', p_task_id=sec, p_driver_id=d1)
        f('lg_accept_task', acteur=u1, p_task_id=sec)
        f('lg_start_task', acteur=u1, p_task_id=sec)
        fr('lg_complete_pickup', 'LG005', 'enlever deux fois le même colis', acteur=u1, p_task_id=sec, p_parcel_ids=[a1])
        f('lg_fail_task', acteur=u1, p_task_id=sec, p_incident_type='CUSTOMER_ABSENT', p_description='personne à l\'adresse')
        ok(st('task', sec) == 'FAILED' and q("select count(*) from logistics.incident where task_id = '%s' and parcel_id is null" % sec) == '1', 'enlèvement manqué : mission échouée, incident sans colis')

        # ============================================================== C. la livraison, du hub à la porte
        p1, p2, p3 = (colis(cust=customers[0]) for _ in range(3))
        fr('lg_create_delivery', 'LG003', 'livraison sans droit', acteur=sansdroit, p_parcel_ids=[p1], p_hub_branch=pap, p_scheduled_for=JOUR, p_address='x')
        fr('lg_create_delivery', 'LG005', 'livraison sans colis', p_parcel_ids=[], p_hub_branch=pap, p_scheduled_for=JOUR, p_address='x')
        fr('lg_create_delivery', 'LG005', 'livraison sans adresse', p_parcel_ids=[p1], p_hub_branch=pap, p_scheduled_for=JOUR, p_address='')
        fr('lg_create_delivery', 'LG005', 'livraison sans date', p_parcel_ids=[p1], p_hub_branch=pap, p_scheduled_for=None, p_address='x')
        fr('lg_create_delivery', 'LG005', 'colis qui n\'est pas AU HUB', p_parcel_ids=[colis('STORED', customers[0])], p_hub_branch=pap, p_scheduled_for=JOUR, p_address='x')
        fr('lg_create_delivery', 'LG005', 'colis de DEUX clients dans une même livraison', p_parcel_ids=[p1, colis(cust=customers[1])], p_hub_branch=pap, p_scheduled_for=JOUR, p_address='x')
        ok(pst(p1) == 'AT_DESTINATION_HUB', 'les refus n\'ont déplacé aucun colis')
        dl = f('lg_create_delivery', p_parcel_ids=[p1, p2, p3], p_hub_branch=pap, p_scheduled_for=JOUR, p_recipient_name='Marie Joseph', p_recipient_phone='+509 3111 1111',
               p_address='12 rue des Rosiers, Pétion-Ville', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_zone_id=z1, p_window_start=T('9 hours'), p_window_end=T('12 hours'), p_priority=2)
        tk, delid = dl['task_id'], dl['delivery_id']
        poids3 = float(q("select sum(weight_lb) from logistics.parcel where id in ('%s','%s','%s')" % (p1, p2, p3)))
        ok(dl['status'] == 'CREATED' and abs(dl['weight_lb'] - poids3) < 0.001 and poids3 > 0, 'LIVRAISON créée avec le poids total de ses colis (%s lb)' % poids3)
        ok(all(pst(p) == 'DELIVERY_ASSIGNED' for p in (p1, p2, p3)), 'ses trois colis sont « affectés à une livraison »')
        ok(q("select count(*) from logistics.delivery_task where id = '%s'" % tk) == '1', 'la vue « delivery_task » la montre')
        fr('lg_create_delivery', 'LG005', 'un colis déjà dans une livraison en cours', p_parcel_ids=[p1], p_hub_branch=pap, p_scheduled_for=JOUR, p_address='x')
        # -- le moteur, règle par règle
        def classement(task=None):
            return {c['d']: c for c in J("select jsonb_agg(jsonb_build_object('d', driver_id, 'e', eligible, 's', score, 'r', to_jsonb(reasons))) from logistics.rank_drivers('%s')" % (task or tk))}
        cl_ = json.loads(cl.run(B, "select jsonb_agg(jsonb_build_object('d', driver_id, 'e', eligible, 's', score, 'r', to_jsonb(reasons))) from public.lg_rank_drivers('%s')" % tk, role='authenticated', claims=op)[1])
        cl_ = {c['d']: c for c in cl_}
        km = lambda c: float([x for x in c['r'] if x.startswith('DISTANCE_KM:')][0].split(':')[1])   # noqa: E731
        ok(abs(cl_[d1]['s'] - (100 - min(60, 2 * km(cl_[d1])))) < 0.011 and 'LOAD:0' in cl_[d1]['r'], 'note = 100 − 2 × km (priorité haute) − 2 × missions déjà prévues')
        ok(km(cl_[d1]) < 1 < km(cl_[d2]) and cl_[d1]['s'] > cl_[d2]['s'], 'le chauffeur le plus PROCHE a la meilleure note')
        ok('ZONE' in cl_[d3]['r'] and cl_[d3]['s'] is None and not cl_[d3]['e'], 'Trois : écarté pour sa zone, sans note (raisons : %s)' % cl_[d3]['r'])
        ok(cl_[d4]['r'] == ['NO_VEHICLE'], 'Quatre : écarté, sans véhicule')
        fr('lg_rank_drivers', 'LG003', 'classement demandé par un chauffeur', acteur=u1, p_task_id=tk)
        # priorité : la distance pèse double pour une mission urgente
        q("update logistics.task set priority = 3 where id = '%s'" % tk)
        c3 = classement()
        ok(abs(c3[d2]['s'] - (100 - km(c3[d2]))) < 0.011, 'priorité normale : la distance pèse UNE fois')
        q("update logistics.task set priority = 2 where id = '%s'" % tk)
        # plafond de pénalité
        q("update logistics.driver set last_latitude = 0, last_longitude = 0 where id = '%s'" % d2)
        ok(classement()[d2]['s'] == 40, 'la pénalité de distance est PLAFONNÉE à 60 : un chauffeur très loin garde 40')
        q("update logistics.driver set last_latitude = 18.5800, last_longitude = -72.2900 where id = '%s'" % d2)
        # charge : une mission de plus ce jour-là, deux points de moins
        q("update logistics.driver set last_latitude = NULL, last_longitude = NULL where id = '%s'" % d1)
        c0 = classement()
        ok(c0[d1]['e'] and 'NO_POSITION' in c0[d1]['r'] and c0[d1]['s'] == 100 and 'LOAD:0' in c0[d1]['r'], 'position inconnue : éligible, sans pénalité de distance (note 100)')
        charge = f('lg_create_pickup_task', p_customer_id=customers[0], p_address='charge', p_scheduled_date=JOUR, p_zone_id=z1, p_weight_lb=1)['task_id']
        f('lg_assign_task', p_task_id=charge, p_driver_id=d1)
        c0 = classement()
        ok('LOAD:1' in c0[d1]['r'] and c0[d1]['s'] == 98, 'une mission déjà prévue ce jour-là coûte DEUX points')
        f('lg_cancel_task', acteur=admin, p_task_id=charge, p_reason='essai de charge')
        ok('LOAD:0' in classement()[d1]['r'] and classement()[d1]['s'] == 100, 'une mission annulée ne compte plus dans la charge')
        q("update logistics.driver set last_latitude = 18.5400, last_longitude = -72.3340 where id = '%s'" % d1)
        # capacité
        q("update logistics.task set weight_lb = 600 where id = '%s'" % tk)
        c = classement()
        ok('CAPACITY_WEIGHT' in c[d1]['r'] and 'CAPACITY_WEIGHT' in c[d2]['r'] and not c[d1]['e'], 'poids 600 lb > capacité du fourgon (500) : écartés')
        q("update logistics.task set weight_lb = 30, volume_ft3 = 150 where id = '%s'" % tk)
        c = classement()
        ok('CAPACITY_VOLUME' in c[d1]['r'] and 'CAPACITY_WEIGHT' not in c[d1]['r'], 'volume 150 pi³ > 100 : écartés pour le VOLUME seulement')
        q("update logistics.task set volume_ft3 = 0 where id = '%s'" % tk)
        # disponibilités
        q("update logistics.task set window_start = logistics.day_start(date '%s') + interval '14 hours', window_end = logistics.day_start(date '%s') + interval '16 hours' where id = '%s'" % (JOUR, JOUR, tk))
        c = classement()
        ok(c[d1]['e'] and 'UNAVAILABLE' not in c[d1]['r'], 'fenêtre 14-16 h : Un (8-18 h) est libre')
        q("insert into logistics.driver_availability (driver_id, starts_at, ends_at, available, note) values ('%s', logistics.day_start(date '%s') + interval '14 hours 30 minutes', logistics.day_start(date '%s') + interval '15 hours', false, 'rendez-vous médical')" % (d2, JOUR, JOUR))
        c = classement()
        ok('UNAVAILABLE' in c[d2]['r'], 'un blocage « indisponible » qui touche la fenêtre écarte le chauffeur')
        q("update logistics.task set window_start = null, window_end = null where id = '%s'" % tk)
        ok(classement()[d2]['e'], 'sans fenêtre, un blocage partiel de la journée n\'écarte personne')
        q("insert into logistics.driver_availability (driver_id, starts_at, ends_at, available) values ('%s', logistics.day_start(date '%s'), logistics.day_start(date '%s') + interval '1 day', false)" % (d2, JOUR, JOUR))
        ok('UNAVAILABLE' in classement()[d2]['r'], 'un blocage couvrant TOUTE la journée écarte le chauffeur')
        q("delete from logistics.driver_availability where driver_id = '%s' and not available" % d2)
        ok('ZONE' in classement()[d3]['r'], 'Trois reste écarté pour sa zone')
        # inactif
        q("update logistics.driver set status = 'ON_LEAVE' where id = '%s'" % d1)
        ok('INACTIVE' in classement()[d1]['r'] and not classement()[d1]['e'], 'un chauffeur en congé est écarté (INACTIVE)')
        fr('lg_accept_task', 'LG003', 'un chauffeur en congé ne peut rien accepter', acteur=u1, p_task_id=tk)
        q("update logistics.driver set status = 'ACTIVE' where id = '%s'" % d1)
        q("update logistics.task set window_start = logistics.day_start(date '%s') + interval '9 hours', window_end = logistics.day_start(date '%s') + interval '12 hours', weight_lb = %s where id = '%s'" % (JOUR, JOUR, dl['weight_lb'], tk))

        # -- proposition, refus, réaffectation
        r = f('lg_auto_assign_task', p_task_id=tk)
        ok(r['driver_id'] == d1 and st('task', tk) == 'ASSIGNED' and q("select status from logistics.delivery where id = '%s'" % delid) == 'ASSIGNED', 'proposée à Un ; la LIVRAISON passe « ASSIGNED »')
        fr('lg_refuse_task', 'LG005', 'refuser sans motif', acteur=u1, p_task_id=tk, p_reason='  ')
        fr('lg_refuse_task', 'LG003', 'refuser la mission d\'un autre', acteur=u2, p_task_id=tk, p_reason='non')
        f('lg_refuse_task', acteur=u1, p_task_id=tk, p_reason='véhicule en panne')
        ok(st('task', tk) == 'CREATED' and q("select driver_id is null from logistics.task where id = '%s'" % tk) == 't' and q("select status from logistics.assignment where task_id = '%s' and driver_id = '%s'" % (tk, d1)) == 'REFUSED', 'REFUS : la mission retourne à CREATED, la proposition est REFUSED')
        ok(q("select status from logistics.delivery where id = '%s'" % delid) == 'PLANNED', 'la livraison revient « PLANNED »')
        ok(q("select reason from logistics.assignment where task_id = '%s' and driver_id = '%s'" % (tk, d1)) == 'véhicule en panne', 'le motif du refus est conservé')
        c = classement()
        ok('REFUSED_BEFORE' in c[d1]['r'] and not c[d1]['e'], 'le moteur NE REPROPOSE PAS la mission à celui qui l\'a refusée')
        r = f('lg_auto_assign_task', p_task_id=tk)
        ok(r['driver_id'] == d2, 'elle est proposée à Deux')
        fr('lg_assign_task', 'LG005', 'affecter à un chauffeur non éligible (mauvaise zone)', p_task_id=tk, p_driver_id=d3)
        fr('lg_assign_task', 'LG003', 'forcer sans être direction', acteur=op, p_task_id=tk, p_driver_id=d3, p_force=True, p_reason='urgence')
        fr('lg_assign_task', 'LG005', 'forcer sans motif', acteur=admin, p_task_id=tk, p_driver_id=d3, p_force=True)
        r = f('lg_assign_task', acteur=admin, p_task_id=tk, p_driver_id=d3, p_force=True, p_reason='seul chauffeur disponible dans le secteur')
        ok(r['forced'] is True and r['reassigned'] is True, 'la direction FORCE l\'affectation, avec un motif : réaffectée')
        ok(q("select count(*) from logistics.audit_log where action = 'task.assign_forced' and entity_id = '%s'" % tk) == '1', 'le forçage est tracé, avec les règles écartées')
        ok(q("select count(*) from logistics.assignment where task_id = '%s' and status in ('OFFERED','ACCEPTED')" % tk) == '1' and q("select status from logistics.assignment where task_id = '%s' and driver_id = '%s'" % (tk, d2)) == 'REASSIGNED', 'une seule proposition vivante ; la précédente est REASSIGNED')
        r = f('lg_assign_task', p_task_id=tk, p_driver_id=d2, p_reason='retour au chauffeur de la zone')
        ok(r['forced'] is False and q("select driver_id from logistics.task where id = '%s'" % tk) == d2, 'réaffectée à Deux (éligible, sans forcer)')
        ok(q("select count(*) from logistics.domain_event where event_type = 'TaskReassigned' and aggregate_id = '%s'" % tk) == '2', 'deux événements « TaskReassigned »')
        f('lg_accept_task', acteur=u2, p_task_id=tk)
        fr('lg_refuse_task', 'LG004', 'refuser APRÈS avoir accepté', acteur=u2, p_task_id=tk, p_reason='finalement non')
        ok(st('task', tk) == 'ACCEPTED' and q("select status from logistics.assignment where task_id = '%s' and status = 'ACCEPTED'" % tk) == 'ACCEPTED', 'mission ACCEPTÉE')

        # -- la tournée
        fr('lg_create_trip', 'LG003', 'tournée sans droit', acteur=sansdroit, p_driver_id=d2, p_trip_date=JOUR, p_task_ids=[tk])
        fr('lg_create_trip', 'LG005', 'tournée sans mission', p_driver_id=d2, p_trip_date=JOUR, p_task_ids=[])
        fr('lg_create_trip', 'LG005', 'mission acceptée par UN AUTRE chauffeur', p_driver_id=d1, p_trip_date=JOUR, p_task_ids=[tk])
        fr('lg_create_trip', 'LG005', 'chauffeur sans véhicule', p_driver_id=d4, p_trip_date=JOUR, p_task_ids=[tk])
        fr('lg_create_trip', 'LG005', 'mission prévue un autre jour', p_driver_id=d2, p_trip_date='2026-11-11', p_task_ids=[tk])
        ok(q("select count(*) from logistics.trip where kind = 'LASTMILE'") == '0', 'les refus n\'ont créé aucune tournée')
        trip = f('lg_create_trip', p_driver_id=d2, p_trip_date=JOUR, p_task_ids=[tk])
        tid = trip['trip_id']
        ok(trip['stops'] == 1 and st('trip', tid) == 'PLANNED' and q("select trip_id::text from logistics.task where id = '%s'" % tk) == tid, 'TOURNÉE planifiée, un arrêt')
        ok(q("select status || '/' || kind || '/' || sequence from logistics.stop where trip_id = '%s'" % tid) == 'PLANNED/DELIVERY/1', 'l\'arrêt est planifié')
        fr('lg_create_trip', 'LG005', 'mission déjà dans une tournée', p_driver_id=d2, p_trip_date=JOUR, p_task_ids=[tk])
        fr('lg_start_trip', 'LG003', 'tournée d\'un autre chauffeur', acteur=u1, p_trip_id=tid)
        # -- avant de partir : pas de livraison sans preuve, pas d'accès direct au statut
        fr('lg_complete_delivery', 'LG001', 'livrer avant d\'être parti', acteur=u2, p_task_id=tk, p_recipient_name='X', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % tk)
        r = f('lg_start_trip', acteur=u2, p_trip_id=tid)
        ok(r['status'] == 'STARTED' and r['tasks_started'] == 1, 'la tournée PART : la mission est commencée')
        ok(all(pst(p) == 'OUT_FOR_DELIVERY' for p in (p1, p2, p3)) and q("select status from logistics.delivery where id = '%s'" % delid) == 'OUT_FOR_DELIVERY', 'les trois colis sont « en livraison » ; la livraison aussi')
        # -- la règle de fond
        def direct(p, acteur):
            return cl.run(B, "select public.lg_transition_parcel('%s', 'DELIVERED', null, null, null, null, '', 'essai')" % p, role='authenticated', claims=acteur, expect_error=True)
        code, txt = direct(p1, u2)
        ok(code != 0 and 'LG003' in txt, 'un chauffeur ne passe PAS un colis « livré » par la porte de service (droit insuffisant) : %s' % txt[-120:])
        code, txt = direct(p1, op)
        ok(code != 0 and 'LG005' in txt and 'PREUVE' in txt, 'même un employé autorisé ne peut pas livrer SANS PREUVE : %s' % txt[-140:])
        refuse("update logistics.parcel set status = 'DELIVERED' where id = '%s'" % p1, 'LG001', 'UPDATE direct du statut')
        fr('lg_complete_delivery', 'LG005', 'sans nom du destinataire', acteur=u2, p_task_id=tk, p_recipient_name=' ', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % tk)
        fr('lg_complete_delivery', 'LG005', 'sans GPS', acteur=u2, p_task_id=tk, p_recipient_name='Marie', p_latitude=None, p_longitude=None, p_photo_path='pod/%s/p.jpg' % tk)
        fr('lg_complete_delivery', 'LG005', 'ni signature ni photo', acteur=u2, p_task_id=tk, p_recipient_name='Marie', p_latitude=PAP_LAT, p_longitude=PAP_LON)
        fr('lg_complete_delivery', 'LG005', 'fichier de preuve d\'une AUTRE mission', acteur=u2, p_task_id=tk, p_recipient_name='Marie', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % pkid)
        fr('lg_complete_delivery', '23514', 'chemin de fichier hors du dossier de preuves', acteur=u2, p_task_id=tk, p_recipient_name='Marie', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/../../x.jpg' % tk)
        fr('lg_complete_delivery', 'LG003', 'livrer la mission d\'un autre', acteur=u1, p_task_id=tk, p_recipient_name='Marie', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % tk)
        ok(all(pst(p) == 'OUT_FOR_DELIVERY' for p in (p1, p2, p3)) and q("select count(*) from logistics.proof_of_delivery") == '0', 'les refus n\'ont rien livré, rien enregistré')
        r = f('lg_complete_delivery', acteur=u2, p_task_id=tk, p_recipient_name='Marie Joseph', p_latitude=PAP_LAT + 0.0001, p_longitude=PAP_LON, p_signature_path='pod/%s/signature.png' % tk, p_photo_path='pod/%s/porte.jpg' % tk)
        ok(r['completed'] is True and r['parcels_delivered'] == 3, 'LIVRAISON terminée : 3 colis livrés')
        ok(all(pst(p) == 'DELIVERED' for p in (p1, p2, p3)) and st('task', tk) == 'COMPLETED' and q("select status from logistics.delivery where id = '%s'" % delid) == 'COMPLETED', 'colis LIVRÉS, mission et livraison TERMINÉES')
        pod = J("select to_jsonb(x) from logistics.proof_of_delivery x where task_id = '%s'" % tk)
        ok(pod['recipient_name'] == 'Marie Joseph' and pod['signature_path'].endswith('signature.png') and pod['photo_path'].endswith('porte.jpg'), 'PREUVE : nom, signature et photo')
        ok(pod['delivered_at'] and abs(pod['latitude'] - (PAP_LAT + 0.0001)) < 1e-6 and pod['longitude'] == PAP_LON and pod['otp_required'] is False, 'PREUVE : heure et GPS')
        refuse("update logistics.proof_of_delivery set recipient_name = 'Autre' where task_id = '%s'" % tk, 'LG004', 'modifier une preuve de livraison')
        refuse("delete from logistics.proof_of_delivery", 'LG004', 'supprimer une preuve de livraison')
        fr('lg_complete_delivery', 'LG001', 'livrer deux fois', acteur=u2, p_task_id=tk, p_recipient_name='Marie', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % tk)
        ok(q("select status from logistics.stop where task_id = '%s'" % tk) == 'DEPARTED', 'l\'arrêt est marqué « parti »')
        ev = q("select string_agg(event_type, '>' order by id) from logistics.domain_event where correlation_id = (select correlation_id from logistics.proof_of_delivery where task_id = '%s')" % tk)
        ok(ev == 'ProofOfDeliveryCreated>Delivered>Delivered>Delivered>TaskCompleted', 'une seule corrélation relie la preuve, les trois livraisons et la fin de mission : %s' % ev)
        ok(q("select string_agg(to_status, '>' order by id) from logistics.tracking_event where parcel_id = '%s'" % p1).endswith('DELIVERY_ASSIGNED>OUT_FOR_DELIVERY>DELIVERED'), 'le suivi du colis : affecté, en livraison, livré')
        ok(q("select count(*) from logistics.audit_log where action = 'task.transition' and entity_id = '%s'" % tk) == q("select count(*) from logistics.task_status_history where task_id = '%s' and from_status is not null" % tk), 'chaque transition de mission est auditée')
        f('lg_complete_trip', acteur=u2, p_trip_id=tid)
        ok(st('trip', tid) == 'COMPLETED' and q("select actual_arrival_at is not null from logistics.trip where id = '%s'" % tid) == 't', 'TOURNÉE terminée')

        # ============================================================== D. le code à usage unique
        def livraison_prete(chauffeur_u, chauffeur_d, otp=False, cust=None, **kw):
            p = colis(cust=cust or customers[0])
            dd = f('lg_create_delivery', p_parcel_ids=[p], p_hub_branch=pap, p_scheduled_for=JOUR, p_recipient_name='Destinataire', p_recipient_phone='+509 3222 2222',
                   p_address='5 rue du Code', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_zone_id=z1, p_otp_required=otp, **kw)
            f('lg_assign_task', p_task_id=dd['task_id'], p_driver_id=chauffeur_d)
            f('lg_accept_task', acteur=chauffeur_u, p_task_id=dd['task_id'])
            f('lg_start_task', acteur=chauffeur_u, p_task_id=dd['task_id'])
            return p, dd['task_id'], dd['delivery_id']
        po, to, do_ = livraison_prete(u2, d2, otp=True)
        fr('lg_complete_delivery', 'LG005', 'un code est exigé mais n\'a pas été émis', acteur=u2, p_task_id=to, p_recipient_name='X', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % to)
        fr('lg_issue_delivery_otp', 'LG003', 'émettre un code sans droit', acteur=sansdroit, p_task_id=to)
        fr('lg_issue_delivery_otp', 'LG003', 'un chauffeur n\'émet pas le code', acteur=u2, p_task_id=to)
        r = f('lg_issue_delivery_otp', p_task_id=to, p_valid_hours=2)
        ok(set(r.keys()) == {'task_id', 'issued', 'valid_hours'}, 'l\'émission NE REND PAS le code à l\'appelant : %s' % sorted(r.keys()))
        code = q("select payload->>'code' from logistics.notification where template = 'DeliveryOtp' and (payload->>'task_id') = '%s'" % to)
        ok(re.match(r'^\d{6}$', code) is not None, 'le code (6 chiffres) part vers le DESTINATAIRE par une notification')
        ok(q("select payload->>'recipient_phone' from logistics.notification where template = 'DeliveryOtp' and (payload->>'task_id') = '%s'" % to) == '+509 3222 2222', 'à la bonne personne : le téléphone du destinataire')
        ok(q("select otp_hash <> '%s' and length(otp_hash) = 64 and otp_hash !~ '%s' from logistics.delivery where id = '%s'" % (code, code, do_)) == 't', 'seule l\'EMPREINTE salée du code est conservée dans la livraison')
        mes = f('lg_my_tasks', acteur=u2)
        ok(any(t['task_id'] == to and t['otp_required'] is True for t in mes) and code not in json.dumps(mes) and 'otp_hash' not in json.dumps(mes), 'le chauffeur sait qu\'un code est exigé, mais ne le voit JAMAIS')
        mauvais = '000000' if code != '000000' else '111111'
        r = f('lg_complete_delivery', acteur=u2, p_task_id=to, p_recipient_name='X', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % to, p_otp=mauvais)
        ok(r['completed'] is False and r['reason'] == 'OTP_INVALID' and r['attempts_left'] == 4, 'mauvais code : refusé, 4 essais restants')
        ok(pst(po) == 'OUT_FOR_DELIVERY' and q("select otp_attempts from logistics.delivery where id = '%s'" % do_) == '1', 'l\'essai raté est COMPTÉ (il survit au refus)')
        r = f('lg_complete_delivery', acteur=u2, p_task_id=to, p_recipient_name='X', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % to)
        ok(r['completed'] is False, 'sans code : refusé')
        for _ in range(3):
            f('lg_complete_delivery', acteur=u2, p_task_id=to, p_recipient_name='X', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % to, p_otp=mauvais)
        fr('lg_complete_delivery', 'LG004', 'après cinq essais, même le BON code est refusé', acteur=u2, p_task_id=to, p_recipient_name='X', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % to, p_otp=code)
        r = f('lg_issue_delivery_otp', p_task_id=to, p_valid_hours=2)
        ok(q("select otp_attempts from logistics.delivery where id = '%s'" % do_) == '0', 'un nouveau code remet le compteur à zéro')
        code = q("select payload->>'code' from logistics.notification where template = 'DeliveryOtp' and (payload->>'task_id') = '%s' order by id desc limit 1" % to)
        q("update logistics.delivery set otp_expires_at = now() - interval '1 minute' where id = '%s'" % do_)
        fr('lg_complete_delivery', 'LG004', 'code expiré', acteur=u2, p_task_id=to, p_recipient_name='X', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % to, p_otp=code)
        f('lg_issue_delivery_otp', p_task_id=to)
        code = q("select payload->>'code' from logistics.notification where template = 'DeliveryOtp' and (payload->>'task_id') = '%s' order by id desc limit 1" % to)
        r = f('lg_complete_delivery', acteur=u2, p_task_id=to, p_recipient_name='Jean Baptiste', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_signature_path='pod/%s/s.png' % to, p_otp=code)
        ok(r['completed'] is True and pst(po) == 'DELIVERED', 'bon code : livré')
        ok(q("select otp_required::text || otp_verified::text from logistics.proof_of_delivery where task_id = '%s'" % to) == 'truetrue', 'la preuve dit que le code a été vérifié')
        ok(q("select otp_hash is null and otp_salt is null from logistics.delivery where id = '%s'" % do_) == 't', 'le code est effacé une fois utilisé')
        ok(q("select count(*) from logistics.domain_event where event_type = 'DeliveryOtpIssued' and aggregate_id = '%s'" % to) == '3', 'chaque émission est un événement')
        ok(q("select count(*) from logistics.domain_event where event_type = 'DeliveryOtpIssued' and payload::text like '%%%s%%'" % code) == '0', 'le code n\'est dans AUCUN événement')
        refuse("insert into logistics.proof_of_delivery (task_id, delivery_id, driver_id, recipient_name, photo_path, latitude, longitude, otp_required, otp_verified, correlation_id) "
               "select id, delivery_id, driver_id, 'X', 'pod/%s/x.jpg', 1, 1, true, false, gen_random_uuid() from logistics.task where id = '%s'" % (to, tk), '23514', 'une preuve où le code est exigé mais non vérifié')

        # ============================================================== E. l'échec, les sept incidents, la replanification, l'annulation
        types = ['CUSTOMER_ABSENT', 'WRONG_ADDRESS', 'DAMAGED', 'REFUSED', 'VEHICLE_PROBLEM', 'PAYMENT_PROBLEM', 'OTHER']
        echoues = {}
        for t in types:
            pe, te, de = livraison_prete(u2, d2)
            fr('lg_fail_task', 'LG005', 'incident inconnu', acteur=u2, p_task_id=te, p_incident_type='VOL') if t == types[0] else None
            r = f('lg_fail_task', acteur=u2, p_task_id=te, p_incident_type=t, p_description='essai %s' % t)
            ok(r['status'] == 'FAILED', 'échec « %s »' % t)
            echoues[t] = (pe, te, de)
            ok(pst(pe) == 'AT_DESTINATION_HUB', '« %s » : le colis REVIENT au hub' % t)
            ok(q("select status from logistics.delivery where id = '%s'" % de) == 'FAILED' and q("select failed_reason from logistics.task where id = '%s'" % te) == t, '« %s » : livraison échouée, motif conservé' % t)
            ok(q("select type || '/' || severity || '/' || status from logistics.incident where task_id = '%s'" % te) == '%s/%s/OPEN' % (t, 'HIGH' if t in ('DAMAGED', 'REFUSED') else 'MEDIUM'), '« %s » : incident ouvert, gravité déduite' % t)
        ok(set(cl.lignes(B, "select distinct type from logistics.incident where task_id is not null")) == set(types), 'les SEPT types d\'incident du dernier kilomètre sont éprouvés')
        pe, te, de = echoues['CUSTOMER_ABSENT']
        ok(q("select string_agg(event_type, '>' order by id) from logistics.domain_event where correlation_id = (select correlation_id from logistics.task_status_history where task_id = '%s' and to_status = 'FAILED')" % te) == 'IncidentCreated>ParcelReturnedToHub>TaskFailed' or
           q("select count(*) from logistics.domain_event where event_type in ('IncidentCreated','ParcelReturnedToHub','TaskFailed') and correlation_id = (select correlation_id from logistics.task_status_history where task_id = '%s' and to_status = 'FAILED')" % te) == '3',
           'l\'échec produit l\'incident, le retour au hub et l\'événement de mission, sous une même corrélation')
        fr('lg_fail_task', 'LG001', 'échouer une mission déjà échouée', acteur=u2, p_task_id=te, p_incident_type='OTHER')
        fr('lg_create_delivery', 'LG005', 'un colis dont la livraison a ÉCHOUÉ n\'entre pas dans une autre : on replanifie ou on annule d\'abord', p_parcel_ids=[pe], p_hub_branch=pap, p_scheduled_for=JOUR, p_address='x')
        fr('lg_reschedule_task', 'LG003', 'replanifier sans droit', acteur=sansdroit, p_task_id=te, p_new_date='2026-11-12')
        fr('lg_reschedule_task', 'LG005', 'replanifier sans date', p_task_id=te, p_new_date=None)
        fr('lg_reschedule_task', 'LG001', 'replanifier une mission non échouée', p_task_id=tk, p_new_date='2026-11-12')
        r = f('lg_reschedule_task', p_task_id=te, p_new_date='2026-11-12')
        ok(r['status'] == 'CREATED' and q("select scheduled_date::text from logistics.task where id = '%s'" % te) == '2026-11-12' and q("select driver_id is null from logistics.task where id = '%s'" % te) == 't', 'REPLANIFIÉE : à créer de nouveau, nouvelle date, sans chauffeur')
        ok(pst(pe) == 'DELIVERY_ASSIGNED' and q("select status || '/' || scheduled_for from logistics.delivery where id = '%s'" % de) == 'PLANNED/2026-11-12', 'le colis est de nouveau « affecté », la livraison « planifiée »')
        ok(q("select count(*) from logistics.domain_event where event_type = 'TaskRescheduled' and aggregate_id = '%s'" % te) == '1', 'événement « TaskRescheduled »')
        # annulation
        pa_, ta_, da_ = echoues['WRONG_ADDRESS']
        fr('lg_cancel_task', 'LG003', 'annuler sans être direction', acteur=op, p_task_id=ta_, p_reason='client injoignable')
        fr('lg_cancel_task', 'LG005', 'annuler sans motif', acteur=admin, p_task_id=ta_, p_reason=' ')
        f('lg_reschedule_task', p_task_id=ta_, p_new_date='2026-11-12')
        ok(pst(pa_) == 'DELIVERY_ASSIGNED', 'avant annulation : le colis est affecté')
        r = f('lg_cancel_task', acteur=admin, p_task_id=ta_, p_reason='adresse introuvable, client prévenu')
        ok(r['status'] == 'CANCELLED' and pst(pa_) == 'AT_DESTINATION_HUB' and q("select status from logistics.delivery where id = '%s'" % da_) == 'CANCELLED', 'ANNULÉE : le colis retourne au hub, la livraison est annulée')
        pl, tl, dl2 = livraison_prete(u2, d2)
        fr('lg_cancel_task', 'LG001', 'annuler une mission COMMENCÉE', acteur=admin, p_task_id=tl, p_reason='trop tard')
        f('lg_fail_task', acteur=u2, p_task_id=tl, p_incident_type='OTHER')
        # livrer sans preuve : la direction seule, avec motif
        pn, tn, dn = livraison_prete(u2, d2)
        fr('lg_deliver_without_proof', 'LG003', 'livrer sans preuve sans être direction', acteur=op, p_parcel_id=pn, p_reason='client sur place')
        fr('lg_deliver_without_proof', 'LG005', 'livrer sans preuve sans motif', acteur=admin, p_parcel_id=pn, p_reason=' ')
        fr('lg_deliver_without_proof', 'LG001', 'livrer sans preuve un colis qui n\'est pas en livraison', acteur=admin, p_parcel_id=colis(), p_reason='x')
        f('lg_deliver_without_proof', acteur=admin, p_parcel_id=pn, p_reason='application en panne, colis remis au voisin devant témoin')
        ok(pst(pn) == 'DELIVERED' and q("select count(*) from logistics.proof_of_delivery where delivery_id = '%s'" % dn) == '0', 'dérogation de la direction : colis livré, SANS preuve')
        ok(q("select count(*) from logistics.audit_log where action = 'parcel.delivered_without_proof' and entity_id = '%s'" % pn) == '1', 'la dérogation est tracée, avec son motif')
        refuse("update logistics.parcel set status = 'DELIVERED' where id = '%s'" % colis('OUT_FOR_DELIVERY'), 'LG001', 'la dérogation ne reste pas ouverte après la transaction')
        # l'ancien schéma n'est pas gêné
        ok(q("update logistics.parcel set status = 'DELIVERED' where id = (select id from logistics.parcel where status_authority = 'legacy' and status <> 'DELIVERED' limit 1) returning 'ok'") == 'ok',
           'un colis encore sous l\'autorité de l\'ANCIEN schéma continue de se livrer comme avant')

        # ============================================================== F. le moteur sur la journée
        q("update logistics.task set status = status where false")
        ancien = q("select coalesce(max(id), 0) from logistics.domain_event")
        j2 = '2026-11-20'
        for u_, d_ in ((u1, d1), (u2, d2)):
            f('lg_set_availability', acteur=u_, p_driver=d_, p_starts=T('8 hours', j2), p_ends=T('18 hours', j2))
        bas = f('lg_create_pickup_task', p_customer_id=customers[0], p_address='a', p_scheduled_date=j2, p_priority=5, p_zone_id=z1)['task_id']
        haut = f('lg_create_pickup_task', p_customer_id=customers[0], p_address='b', p_scheduled_date=j2, p_priority=1, p_zone_id=z1)['task_id']
        impossible = f('lg_create_pickup_task', p_customer_id=customers[0], p_address='c', p_scheduled_date=j2, p_priority=3, p_zone_id=z1, p_weight_lb=9999)['task_id']
        q("update logistics.driver set max_stops = 1 where id = '%s'" % d1)
        r = f('lg_auto_assign_day', p_date=j2)
        ok(r['assigned'] == 2 and len(r['unassigned']) == 1 and r['unassigned'][0]['task_id'] == impossible, 'la journée : 2 missions affectées, 1 INCAPABLE (trop lourde), rapportée avec ses raisons')
        ordre = cl.lignes(B, "select aggregate_id from logistics.domain_event where event_type = 'TaskAssigned' and id > %s order by id" % ancien)
        ok(ordre == [haut, bas], 'les missions prioritaires sont traitées D\'ABORD : %s' % ordre)
        ok(q("select status from logistics.task where id = '%s'" % impossible) == 'CREATED' and q("select count(*) from logistics.assignment where task_id = '%s'" % impossible) == '0', 'la mission impossible reste CRÉÉE, sans proposition fantôme')
        ok('MAX_STOPS' in classement(impossible)[d1]['r'] and 'CAPACITY_WEIGHT' in classement(impossible)[d1]['r'], 'et on sait POURQUOI (nombre d\'arrêts, poids)')
        q("update logistics.driver set max_stops = 30 where id = '%s'" % d1)
        board = f('lg_task_board', p_date=j2)
        ok(len(board) == 3 and {b['status'] for b in board} == {'ASSIGNED', 'CREATED'}, 'le tableau des missions du jour (personnel)')
        fr('lg_task_board', 'LG003', 'tableau des missions demandé par un chauffeur', acteur=u1, p_date=j2)
        # une réaffectation retire la mission de la tournée de l'ancien chauffeur
        pr, tr, dr = livraison_prete(u1, d1)
        f('lg_complete_delivery', acteur=u1, p_task_id=tr, p_recipient_name='Z', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_photo_path='pod/%s/p.jpg' % tr)
        # tournées : capacité, arrêts
        lourds = []
        for _ in range(2):
            pl_ = colis(cust=customers[0], poids=100)
            dd = f('lg_create_delivery', p_parcel_ids=[pl_], p_hub_branch=pap, p_scheduled_for=JOUR, p_address='lourd', p_latitude=PAP_LAT, p_longitude=PAP_LON, p_zone_id=z1)
            f('lg_assign_task', p_task_id=dd['task_id'], p_driver_id=d1)
            f('lg_accept_task', acteur=u1, p_task_id=dd['task_id'])
            lourds.append(dd['task_id'])
        ok(classement(lourds[1])[d1]['e'] is True, 'deux missions de 100 lb tiennent dans un fourgon de 500 lb : le moteur les accepte')
        q("update logistics.driver set default_vehicle_id = '%s' where id = '%s'" % (moto, d1))
        fr('lg_create_trip', 'LG005', 'tournée plus lourde que le véhicule du jour (200 lb dans une moto de 50 lb)', p_driver_id=d1, p_trip_date=JOUR, p_task_ids=lourds)
        q("update logistics.driver set default_vehicle_id = '%s' where id = '%s'" % (van1, d1))
        q("update logistics.driver set max_stops = 1 where id = '%s'" % d1)
        fr('lg_create_trip', 'LG005', 'trop d\'arrêts pour ce chauffeur', p_driver_id=d1, p_trip_date=JOUR, p_task_ids=lourds)
        q("update logistics.driver set max_stops = 30 where id = '%s'" % d1)
        t1 = f('lg_create_trip', p_driver_id=d1, p_trip_date=JOUR, p_task_ids=[lourds[0]])['trip_id']
        f('lg_assign_task', p_task_id=lourds[0], p_driver_id=d2, p_reason='rééquilibrage')
        ok(q("select trip_id is null from logistics.task where id = '%s'" % lourds[0]) == 't' and q("select status from logistics.stop where task_id = '%s'" % lourds[0]) == 'SKIPPED', 'réaffectée : retirée de la tournée de l\'ancien chauffeur (arrêt « sauté »)')
        t1 = f('lg_create_trip', p_driver_id=d1, p_trip_date=JOUR, p_task_ids=[lourds[1]])['trip_id']
        f('lg_start_trip', acteur=u1, p_trip_id=t1)
        fr('lg_complete_trip', 'LG005', 'terminer une tournée dont une mission court encore', acteur=u1, p_trip_id=t1)
        f('lg_fail_task', acteur=u1, p_task_id=lourds[1], p_incident_type='VEHICLE_PROBLEM')
        f('lg_complete_trip', acteur=u1, p_trip_id=t1)
        ok(q("select status from logistics.stop where task_id = '%s'" % lourds[1]) == 'SKIPPED' and st('trip', t1) == 'COMPLETED', 'tournée terminée : l\'arrêt de la mission échouée est « sauté »')
        fr('lg_complete_trip', 'LG001', 'terminer deux fois', acteur=u1, p_trip_id=t1)

        # ============================================================== G. droits, portes fermées
        for fn, kw in (('lg_create_pickup_task', dict(p_customer_id=customers[0], p_address='x', p_scheduled_date=JOUR)), ('lg_auto_assign_task', dict(p_task_id=tk)),
                       ('lg_cancel_task', dict(p_task_id=tk, p_reason='x')), ('lg_deliver_without_proof', dict(p_parcel_id=p1, p_reason='x')),
                       ('lg_issue_delivery_otp', dict(p_task_id=tk)), ('lg_assign_task', dict(p_task_id=tk, p_driver_id=d1))):
            fr(fn, 'LG003', 'le chauffeur ne peut PAS appeler %s' % fn, acteur=u2, **kw)
        for fn, kw in (('lg_accept_task', dict(p_task_id=tk)), ('lg_start_task', dict(p_task_id=tk)), ('lg_start_trip', dict(p_trip_id=tid)), ('lg_my_tasks', dict())):
            fr(fn, 'LG003', 'l\'employé ne peut PAS appeler %s (réservé aux chauffeurs)' % fn, acteur=op, **kw)
        code, txt = cl.run(B, appel('lg_my_tasks'), role='anon', expect_error=True)
        ok(code != 0 and ('permission' in txt.lower() or '42501' in txt), 'anonyme : lg_my_tasks refusé')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\\_%' and (has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('public', p.oid, 'execute'))") == '0', 'AUCUNE façade lg_* n\'est ouverte à l\'anonyme')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\\_%' and not has_function_privilege('authenticated', p.oid, 'execute')") == '0', 'toutes les façades sont ouvertes aux comptes connectés (qui vérifient ensuite leur droit)')
        ok(q("select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'logistics' and c.relkind = 'r' and (not c.relrowsecurity or has_table_privilege('authenticated', c.oid, 'select') or has_table_privilege('anon', c.oid, 'select'))") == '0', 'toutes les tables du noyau : RLS active, aucun accès direct')
        ok(q("select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'logistics' and c.relkind = 'v' and (has_table_privilege('authenticated', c.oid, 'select') or has_table_privilege('anon', c.oid, 'select'))") == '0', 'les vues « pickup_task » et « delivery_task » ne sont lisibles ni par un client ni par un anonyme')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and (has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))") == '0', 'aucune fonction interne du noyau n\'est appelable par un compte connecté')
        # le droit « livraison »
        cn = lambda u, d, flag: q("select set_config('logistics.last_mile', '%s', false); select logistics.actor_can('%s', '%s')" % (flag, u, d))   # noqa: E731
        ok(cn(u2, 'livraison', 'off') == 'f', 'le chauffeur n\'a PAS le droit « livraison » en dehors d\'une fonction de mission')
        ok(cn(u2, 'livraison', 'on') == 't', '…il l\'a pendant qu\'une fonction de mission s\'exécute')
        ok(cn(u2, 'colis.statut', 'on') == 'f' and cn(u2, 'direction', 'on') == 'f', '…et il n\'a JAMAIS ni « colis.statut » ni « direction »')
        ok(cn(op, 'livraison', 'off') == 't' and cn(gerant, 'livraison', 'off') == 't' and cn(sansdroit, 'livraison', 'on') == 'f', 'un employé avec « colis.statut » et la direction gardent leurs droits ; un employé sans droit n\'en gagne pas')
        ok(q("select string_agg(from_status || '>' || to_status || ':' || required_right, ',' order by from_status, to_status) from logistics.parcel_transition where required_right = 'livraison'") ==
           'DELIVERY_ASSIGNED>OUT_FOR_DELIVERY:livraison,OUT_FOR_DELIVERY>AT_DESTINATION_HUB:livraison,OUT_FOR_DELIVERY>DELIVERED:livraison', 'le droit « livraison » n\'ouvre que TROIS transitions')
        # chauffeur inactif
        q("update logistics.driver set status = 'INACTIVE' where id = '%s'" % d3)
        ok(cn(u3, 'livraison', 'on') == 'f', 'un chauffeur désactivé n\'a plus aucun droit')
        ok(q("select count(*) from logistics.audit_log where action = 'task.transition'") == q("select count(*) from logistics.task_status_history where from_status is not null"), 'dans tout le noyau : chaque transition de mission a son historique ET son audit, sans exception')
        ok(P.empreintes_historiques(cl, B).keys() == avant_legacy.keys() and all(P.empreintes_historiques(cl, B)[t] == avant_legacy[t] for t in ('public.colis_historique', 'public.factures', 'public.appareils')), 'tout au long de la phase 9, les anciennes tables (colis, historique, factures, appareils) n\'ont pas bougé')

    print('%d vérifications — phase 9 (dernier kilomètre) : OK' % N[0])


if __name__ == '__main__':
    main()
