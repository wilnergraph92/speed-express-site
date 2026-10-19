#!/usr/bin/env python3
"""Étape 029 — l'analytique complète, ses alertes et son recalcul planifié, sur un vrai PostgreSQL jetable (001 à 029).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-analytique-complete-essai.py

Jamais la production. Ce qu'on éprouve :
  (A) le passage de 012 à 029 : les jours calculés par l'ancienne version restent lisibles, signalés « à recalculer » (rapport « OUTDATED »,
      vérification « VERSION_CHANGED », veille « day_outdated ») ; le recalcul planifié les reprend ;
  (B) les nouvelles mesures, sur une activité datée que l'essai maîtrise, comparées à un second chemin en Python : colis en transit et en
      retard À MINUIT (un événement à 00 h 00 pile compte pour le lendemain), expéditions créées, en retard, à l'heure, leur délai, livraisons
      par chauffeur, zone et tournée, ponctualité, dépenses (une annulée ne compte pas), reste dû facture par facture, clients actifs ;
  (C) les trois agrégations : un flux s'additionne, un stock vaut le DERNIER jour de la période, des clients se comptent DISTINCTS ; les
      indicateurs dérivés (taux, délais, facturé, marge, fréquence) sont calculés par la base, période par période ;
  (D) la traçabilité : source, version de calcul et empreinte du code, statut, empreinte du rapport, sources nommées ;
  (E) les alertes : KPI impossible, données manquantes, anomalie, recalcul non exécuté, recalcul en échec ; sans doublon ; en ajout seul ;
      vues selon les droits ; acquittées par la direction ; deux contrôles de plus dans la santé du système ;
  (F) les portes. Écrit analytique-complete-rpc.json et analytique-complete-exemples.json pour le test du site (analytique-contrat.cjs).
"""
import datetime as dt
import json
import os
import re
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]
HAITI = ZoneInfo('America/Port-au-Prince')
ICI = os.path.dirname(os.path.abspath(__file__))


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
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, lit(v)) for k, v in kw.items()))


def h(d, heure, mi=0):
    """Un instant à Haïti (le second chemin : Python)."""
    return dt.datetime(d.year, d.month, d.day, heure, mi, tzinfo=HAITI).isoformat()


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql: cl.un(B, sql)   # noqa: E731
        P.monter_historique(cl, B)
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('029-analytique-complete.sql' in etapes, 'l\'étape 029 est dans le noyau')
        for f_ in etapes:
            if f_ < '029':
                cl.run(B, P.lire_sql('outils/logistique/' + f_))
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) "
          "select '00000000-0000-0000-0000-000000000000', ('00000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid, 'authenticated', 'authenticated', "
          "'equipe' || i || '@essai.test', 'x', now(), jsonb_build_object('nom_complet', 'Équipe ' || i, 'pays', 'Haïti', 'ville', 'Delmas', 'adresse', 'x', 'telephone', '+509 3000', 'langue', 'fr') "
          "from generate_series(31, 32) i")
        q("update public.clients set role = 'employe', code = null, droits = array['factures.lire'] where email = 'equipe31@essai.test'")
        q("update public.clients set role = 'employe', code = null, droits = '{}' where email = 'equipe32@essai.test'")
        q("select logistics.run_migration('analytique 029')")
        uid = lambda e: q("select id from public.clients where email = '%s'" % e)   # noqa: E731
        admin, ops, fin, rien, client = uid('client1@essai.test'), uid('client3@essai.test'), uid('equipe31@essai.test'), uid('equipe32@essai.test'), uid('client9@essai.test')
        org = q('select id from logistics.organization')
        aujourdhui = dt.date.fromisoformat(q('select logistics.today()::text'))

        def f(nom, acteur, **kw):
            code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
            return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

        def refuse(nom, etat, msg, acteur, **kw):
            code, texte = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
            ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-200:].replace('\n', ' ')))

        # ============================================================== A. de 012 à 029
        recent0, recent1 = aujourdhui - dt.timedelta(days=9), aujourdhui
        ancien = f('lg_an_refresh', admin, p_from=str(recent0), p_to=str(recent1))
        ok('calc_version' not in ancien, 'avant 029 : une exécution de la version 012')
        cl.run(B, P.lire_sql('outils/logistique/029-analytique-complete.sql'))
        cl.run(B, P.lire_sql('outils/logistique/029-analytique-complete.sql'))
        ok(True, '029 chargée deux fois de suite')
        ok(q("select count(*) from analytics.metric") == '42' and q("select count(*) from analytics.metric where family is null or btrim(definition) = ''") == '0',
           'quarante-deux mesures, chacune avec sa famille et sa définition')
        ok(q("select string_agg(distinct family, ',' order by family) from analytics.metric") == 'customers,finance,last_mile,operations,transport', 'cinq familles')
        rep_ancien = f('lg_an_report', admin, p_grain='day', p_from=str(recent0), p_to=str(recent1))
        ok(rep_ancien['status'] == 'OUTDATED' and len(rep_ancien['stale_days']) == 10 and rep_ancien['runs'][0]['calc_version'] == '012' and rep_ancien['runs'][0]['current_version'] is False,
           'les jours de 012 restent lisibles, signalés « à recalculer » (rapport OUTDATED, version 012)')
        v_anc = f('lg_an_verify', admin, p_run_id=ancien['run_id'])
        ok(v_anc['verdict'] == 'VERSION_CHANGED' and v_anc['calc_version_then'] == '012' and v_anc['calc_version_now'] == '029', 'vérifier une exécution de 012 : « la version du calcul a changé »')
        veille = json.loads(q('select analytics.watch()'))
        ok(veille['alerts_raised'] == 7 and q("select count(*) from analytics.alert where code = 'DATA_MISSING' and subject = 'day_outdated'") == '7',
           'la veille : les sept derniers jours clos, calculés par une ancienne version, sont signalés')
        ok(json.loads(q('select analytics.watch()'))['alerts_raised'] == 0, 'la veille relancée : aucune alerte en double')
        code, t_ = cl.run(B, "select public.ses_an_refresh()", role='service_role')
        plan = json.loads(t_)
        ok(code == 0 and plan['source'] == 'scheduler' and plan['calc_version'] == '029' and plan['period_start'] == str(aujourdhui - dt.timedelta(days=366)) and plan['period_end'] == str(aujourdhui),
           'le recalcul planifié reprend toute l\'année écoulée (jours jamais calculés ou anciens) : %s → %s' % (plan.get('period_start'), plan.get('period_end')))
        ok(f('lg_an_report', admin, p_grain='day', p_from=str(recent0), p_to=str(recent1))['stale_days'] == [], 'après lui : plus aucun jour à recalculer')
        ok(q("select status || '|' || (detail ->> 'run_id') from ops.heartbeat where source = 'analytics_refresh' order by id desc limit 1") == 'OK|%s' % plan['run_id'],
           'le recalcul planifié laisse son battement de cœur (OK, n° d\'exécution)')

        # ============================================================== B. l'activité datée
        D1, D2, D3, D4, D7, D8 = (dt.date(2026, 9, d) for d in (1, 2, 3, 4, 7, 8))
        ok(D8 < aujourdhui, 'les jours du décor sont passés')
        avant = f('lg_an_report', admin, p_grain='day', p_from='2026-08-01', p_to=str(D8))
        ok(avant['rows'] == [], 'aucune activité dans la fenêtre du décor avant de la créer')
        ca = q("select id from logistics.customer where auth_user_id = '%s'" % client)
        cb = q("select id from logistics.customer where code is not null and id <> '%s' and source <> 'legacy_staff_account' order by code limit 1" % ca)

        def colis(n, mode, statut='CREATED', cust=None):
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, destination_city, service_mode, status, status_authority, source, weight_lb) "
                     "values ('%s', 'AC-%03d', 'tac%d', '%s', 'HT', 'Delmas', '%s', '%s', 'core', 'legacy_backfill', 3) returning id" % (org, n, n, cust or ca, mode, statut))

        def ev(p_, statut, quand):
            q("insert into logistics.tracking_event (parcel_id, event_type, to_status, occurred_at, source, correlation_id) values ('%s', 'Essai', '%s', '%s', 'manual', gen_random_uuid())" % (p_, statut, quand))

        # B1. colis en transit : p1 (air) chargé le 1er, arrivé le 2 à 23 h 30, livré le 3 ; p2 (mer) chargé le 2 à 0 h 30, toujours en route ;
        #     p3 (air) chargé le 3 à 23 h 59, livré le 4 à 0 h 00 PILE : à minuit du 3 il est encore en transit, et il est livré sans réception connue
        p1, p2, p3 = colis(1, 'air'), colis(2, 'sea'), colis(3, 'air')
        ev(p1, 'RECEIVED', h(D1, 10)); ev(p1, 'LOADED', h(D1, 15)); ev(p1, 'ARRIVED', h(D2, 23, 30)); ev(p1, 'DELIVERED', h(D3, 12))
        ev(p2, 'LOADED', h(D2, 0, 30))
        ev(p3, 'LOADED', h(D3, 23, 59)); ev(p3, 'DELIVERED', h(D4, 0))
        # B2. clients : ca reçoit p1 le 1er et p6 le 2 ; cb reçoit p4 le 2 et ouvre un ticket le 2
        p4, p6 = colis(4, 'air', cust=cb), colis(6, 'air')
        ev(p4, 'RECEIVED', h(D2, 9)); ev(p6, 'RECEIVED', h(D2, 11))
        q("insert into logistics.support_ticket (number, customer_id, subject, category, created_at) values ('TK-AC-1', '%s', 'Essai', 'OTHER', '%s')" % (cb, h(D2, 14)))
        # B3. le dernier kilomètre : un chauffeur, une zone, une tournée ; trois livraisons terminées le 3
        q("insert into logistics.branch (organization_id, code, name, kind, country, city) values ('%s', 'PAP', 'Hub', 'hub', 'HT', 'Port-au-Prince') on conflict do nothing" % org)
        pap = q("select id from logistics.branch where code = 'PAP'")
        chauffeur_user = q("select id from logistics.app_user order by id limit 1")
        drv = q("insert into logistics.driver (user_id, full_name) values ('%s', 'Jean Chauffeur') returning id" % chauffeur_user)
        zone = q("insert into logistics.delivery_zone (code, name, country) values ('Z-PAP', 'Port-au-Prince centre', 'HT') returning id")
        route = q("insert into logistics.route (code, kind, name) values ('R-PAP-1', 'LASTMILE', 'Tournée du matin') returning id")
        trip = q("insert into logistics.trip (route_id, kind) values ('%s', 'LASTMILE') returning id" % route)
        taches = []
        for n_ in (11, 12, 13):
            p_ = colis(n_, 'air', 'AT_DESTINATION_HUB')
            r_ = json.loads(cl.run(B, "select public.lg_create_delivery(array['%s']::uuid[], '%s', current_date, p_address => '5 rue')" % (p_, pap), role='authenticated', claims=admin)[1])
            taches.append((r_['task_id'], p_))
        (t1, pt1), (t2, pt2), (t3, pt3) = taches
        # t1 : prévue le 2, chauffeur, zone, tournée ; assignée le 1er, terminée le 3 à midi (en retard à minuit du 2) ; preuve le 3 à midi
        # t2 : prévue le 3, même chauffeur et zone, hors tournée ; échouée le 3
        # t3 : prévue le 3, SANS chauffeur ni zone ; terminée le 3 à midi, preuve à l'heure
        q("update logistics.task set scheduled_date = '%s', driver_id = '%s', zone_id = '%s', trip_id = '%s' where id = '%s'" % (D2, drv, zone, trip, t1))
        q("update logistics.task set scheduled_date = '%s', driver_id = '%s', zone_id = '%s' where id = '%s'" % (D3, drv, zone, t2))
        q("update logistics.task set scheduled_date = '%s' where id = '%s'" % (D3, t3))
        for t_, statut, quand in ((t1, 'ASSIGNED', h(D1, 10)), (t1, 'COMPLETED', h(D3, 12)), (t2, 'ASSIGNED', h(D3, 8)), (t2, 'FAILED', h(D3, 15)),
                                  (t3, 'ASSIGNED', h(D3, 8)), (t3, 'COMPLETED', h(D3, 12))):
            q("insert into logistics.task_status_history (task_id, to_status, occurred_at, correlation_id) values ('%s', '%s', '%s', gen_random_uuid())" % (t_, statut, quand))
        for t_ in (t1, t3):
            q("insert into logistics.proof_of_delivery (task_id, delivery_id, driver_id, recipient_name, photo_path, latitude, longitude, delivered_at, correlation_id) "
              "select id, delivery_id, '%s', 'Destinataire', 'pod/' || id || '/photo.jpg', 18.54, -72.33, '%s', gen_random_uuid() from logistics.task where id = '%s'" % (drv, h(D3, 12), t_))
        # B4. le transport : SHP-1 (air) prévu le 2 à midi, parti le 1er, arrivé le 3 (en retard) ; SHP-2 (mer) prévu le 7, parti le 2, arrivé le 3 (à l'heure)
        expeditions = []
        for code_, mode_, prevue, depart, arrivee in (('SHP-AC-1', 'air', h(D2, 12), h(D1, 12), h(D3, 12)), ('SHP-AC-2', 'sea', h(D7, 12), h(D2, 12), h(D3, 10))):
            tr = q("insert into logistics.transport (mode, planned_arrival_at) values ('%s', '%s') returning id" % (mode_, prevue))
            s_ = q("insert into logistics.shipment (code, mode, transport_id) values ('%s', '%s', '%s') returning id" % (code_, mode_, tr))
            for de, a_, quand in ((None, 'DRAFT', depart), ('DRAFT', 'DISPATCHED', depart), ('DISPATCHED', 'ARRIVED', arrivee)):
                q("insert into logistics.shipment_status_history (shipment_id, from_status, to_status, occurred_at, correlation_id) values ('%s', %s, '%s', '%s', gen_random_uuid())"
                  % (s_, lit(de), a_, quand))
            expeditions.append(s_)
        # B5. la finance : une facture neuve de ca ; 100 $ + 5 $ de taxe le 1er ; 60 $ payés le 2 ; 10 $ remboursés le 3 ; 25 $ payés le 7 (aucun revenu ce jour-là)
        inv = q("insert into logistics.invoice (organization_id, number, customer_id, status, total, source, legacy_invoice_id) values ('%s', 'INV-AC-1', '%s', 'ISSUED', 105, 'legacy_backfill', gen_random_uuid()) returning id" % (org, ca))
        q("insert into logistics.revenue_entry (invoice_id, entry_date, category, net_amount, tax_amount, currency, net_base_usd, tax_base_usd, correlation_id) "
          "values ('%s', '%s', 'FREIGHT', 100, 5, 'USD', 100, 5, gen_random_uuid())" % (inv, D1))
        pays = []
        for n_, quand, montant in ((1, h(D2, 12), 60), (2, h(D7, 12), 25)):
            pays.append(q("insert into logistics.payment (number, invoice_id, customer_id, amount, currency, base_amount_usd, tendered_amount, tendered_currency, rate_used, method, paid_at, correlation_id) "
                          "values ('PAY-AC-%d', '%s', '%s', %s, 'USD', %s, %s, 'USD', 1, 'CASH', '%s', gen_random_uuid()) returning id" % (n_, inv, ca, montant, montant, montant, quand)))
        q("insert into logistics.refund (number, payment_id, invoice_id, customer_id, amount, currency, base_amount_usd, method, reason, created_at, correlation_id) "
          "values ('RF-AC-1', '%s', '%s', '%s', 10, 'USD', 10, 'CASH', 'essai', '%s', gen_random_uuid())" % (pays[0], inv, ca, h(D3, 9)))
        q("insert into logistics.expense (number, category, amount, currency, base_amount_usd, incurred_on, correlation_id) values ('EXP-AC-1', 'FUEL', 20, 'USD', 20, '%s', gen_random_uuid())" % D1)
        q("insert into logistics.expense (number, category, amount, currency, base_amount_usd, incurred_on, status, void_reason, voided_at, correlation_id) "
          "values ('EXP-AC-2', 'RENT', 100, 'USD', 100, '%s', 'VOIDED', 'doublon', now(), gen_random_uuid())" % D1)
        # B6. une pointe : six colis reçus le 8 (les 28 jours d'avant en comptent trois : moyenne 0,11) → anomalie
        for n_ in range(21, 27):
            ev(colis(n_, 'ground'), 'RECEIVED', h(D8, 10))

        # ============================================================== C. le calcul, et le second chemin
        run = f('lg_an_refresh', admin, p_from='2026-08-01', p_to=str(D8))
        ok(run['source'] == 'manual' and run['status'] == 'COMPLETE' and run['calc_version'] == '029' and run['partial'] is False, 'un calcul à la main : source, version, statut')
        jour = f('lg_an_report', admin, p_grain='day', p_from=str(D1), p_to=str(D8))
        T = {(r['period'], r['metric'], r['dimension']): float(r['value']) for r in jour['rows']}

        def v(d_, m_, dim=''):
            return T.get((str(d_), m_, dim), 0)
        attendus = [
            (D1, 'parcels_in_transit', 'air', 1), (D2, 'parcels_in_transit', 'air', 1), (D2, 'parcels_in_transit', 'sea', 1),
            (D3, 'parcels_in_transit', 'air', 1), (D3, 'parcels_in_transit', 'sea', 1), (D4, 'parcels_in_transit', 'air', 0), (D4, 'parcels_in_transit', 'sea', 1),
            (D1, 'parcels_late', 'air', 0), (D2, 'parcels_late', 'air', 1), (D3, 'parcels_late', 'air', 0),
            (D1, 'shipments_created', 'air', 1), (D2, 'shipments_created', 'sea', 1),
            (D1, 'shipments_late', 'air', 0), (D2, 'shipments_late', 'air', 1), (D3, 'shipments_late', 'air', 0),
            (D3, 'shipments_arrived', 'air', 1), (D3, 'shipments_arrived', 'sea', 1),
            (D3, 'shipments_arrived_planned', 'air', 1), (D3, 'shipments_arrived_planned', 'sea', 1),
            (D3, 'shipments_arrived_on_time', 'air', 0), (D3, 'shipments_arrived_on_time', 'sea', 1),
            (D3, 'shipment_transit_hours_sum', 'air', 48), (D3, 'shipment_transit_hours_sum', 'sea', 22),
            (D3, 'deliveries_completed_driver', drv, 1), (D3, 'deliveries_failed_driver', drv, 1), (D3, 'deliveries_completed_driver', '', 1),
            (D3, 'deliveries_completed_zone', 'Z-PAP', 1), (D3, 'deliveries_failed_zone', 'Z-PAP', 1), (D3, 'deliveries_completed_zone', '', 1),
            (D3, 'deliveries_completed_route', 'R-PAP-1', 1), (D3, 'deliveries_failed_route', '', 1), (D3, 'deliveries_completed_route', '', 1),
            (D3, 'deliveries_on_time', '', 1), (D3, 'tasks_completed', 'DELIVERY', 2), (D3, 'tasks_failed', 'DELIVERY', 1),
            (D1, 'expenses_usd', 'FUEL', 20), (D1, 'expenses_usd', 'RENT', 0),
            (D1, 'receivables_usd', '', 105), (D2, 'receivables_usd', '', 45), (D3, 'receivables_usd', '', 55), (D7, 'receivables_usd', '', 30), (D8, 'receivables_usd', '', 30),
            (D4, 'parcels_delivered', 'air', 1), (D4, 'transit_count', 'air', 0),
        ]
        faux = [(str(d_), m_, dim, att, v(d_, m_, dim)) for d_, m_, dim, att in attendus if abs(v(d_, m_, dim) - att) > 1e-6]
        ok(not faux, 'chaque nouvelle mesure vaut ce que le second chemin attend — écarts : %s' % faux)
        ok(v(D3, 'parcels_in_transit', 'air') == 1, 'un colis livré à 0 h 00 PILE le 4 est encore en transit à minuit du 3 (le statut à minuit est le dernier AVANT minuit)')
        # les clients : aucune ligne par client, jamais
        ok(all(not re.match(r'^[0-9a-f-]{36}$', r['dimension']) for r in jour['rows'] if r['metric'] in ('customers_active', 'customers_shipping')),
           'les mesures de clientèle ne montrent aucun identifiant de client (seulement leur nombre)')
        ok(v(D2, 'customers_active') == 2 and v(D1, 'customers_active') == 1 and v(D2, 'customers_shipping') == 2, 'clients actifs par jour : 1 le 1er, 2 le 2')
        ok(jour['labels']['driver'].get(drv) == 'Jean Chauffeur' and jour['labels']['zone'].get('Z-PAP') == 'Port-au-Prince centre' and jour['labels']['route'].get('R-PAP-1') == 'Tournée du matin',
           'les dimensions arrivent avec leurs noms lisibles (chauffeur, zone, tournée), donnés par la base')

        # ============================================================== D. les trois agrégations, les dérivés par période
        sem = f('lg_an_report', admin, p_grain='week', p_from=str(D1), p_to=str(D3))
        tot = {(x['period'], x['metric']): x['value'] for x in sem['totals']}
        lundi = '2026-08-31'
        ok(float(tot[(lundi, 'parcels_in_transit')]) == 2, 'un STOCK sur la semaine (bornée au 3) = sa valeur du 3 (2), pas la somme des jours (5)')
        ok(float(tot[(lundi, 'customers_active')]) == 2, 'des clients actifs le 1er et le 2 = 2 clients DISTINCTS sur la semaine, pas 3')
        ok(float(tot[(lundi, 'receivables_usd')]) == 55 and float(tot[(lundi, 'expenses_usd')]) == 20, 'reste dû à la fin de la période (55 $), dépenses de la période (20 $, l\'annulée exclue)')
        der = {x['period']: x['values'] for x in sem['derived']}[lundi]
        ok(float(der['invoiced_usd']) == 105 and float(der['margin_usd']) == 80 and float(der['margin_pct']) == 80 and float(der['collection_pct']) == 60 and float(der['net_collected_usd']) == 50,
           'facturé 105 $, marge 80 $ (80 %%), encaissé 60 %%, encaissement net 50 $ — calculés par la base : %s' % der)
        ok(float(der['delivery_success_pct']) == round(100 * 2 / 3, 1) and float(der['delivery_on_time_pct']) == 50 and float(der['shipment_on_time_pct']) == 50
           and float(der['avg_shipment_transit_hours']) == 35 and float(der['parcels_per_customer']) == 1.5,
           'réussite des livraisons 66,7 %%, ponctualité 50 %%, expéditions à l\'heure 50 %%, délai moyen 35 h, 1,5 colis par client : %s' % der)
        bd = sem['breakdown']
        chauffeur = [x for x in bd['driver'] if x['key'] == drv][0]
        ok(chauffeur['completed'] == 1 and chauffeur['failed'] == 1 and float(chauffeur['success_pct']) == 50 and chauffeur['label'] == 'Jean Chauffeur',
           'le détail par chauffeur : 1 réussie, 1 échouée, 50 %')
        ok([x['key'] for x in bd['route']] == ['', 'R-PAP-1'] and [x for x in bd['zone'] if x['key'] == 'Z-PAP'][0]['success_pct'] is not None, 'par tournée et par zone aussi')
        k = f('lg_an_kpis', admin, p_from=str(D1), p_to=str(D3))
        ok(float(k['current']['parcels_in_transit']) == 2 and float(k['current']['customers_active']) == 2 and float(k['ratios_current']['margin_usd']) == 80,
           'les indicateurs suivent les mêmes règles (stock au dernier jour, clients distincts, marge)')
        ok(k['previous']['parcels_in_transit'] == 0 and k['ratios_previous']['margin_pct'] is None, 'la période précédente : un stock nul, une marge impossible à calculer (« — », jamais 0 %)')
        trou = f('lg_an_kpis', admin, p_from='2020-01-01', p_to='2020-01-03')
        ok(trou['current']['parcels_in_transit'] is None and trou['current']['parcels_received'] == 0, 'un stock dont le dernier jour n\'a jamais été calculé : inconnu, pas zéro')
        rep_trou = f('lg_an_report', admin, p_grain='month', p_from='2020-01-01', p_to='2020-01-03')
        ok(rep_trou['status'] == 'INCOMPLETE' and any(x['metric'] == 'parcels_in_transit' and x['value'] is None for x in rep_trou['totals']), 'idem dans le rapport, qui se dit INCOMPLET')

        # ============================================================== E. la traçabilité
        ok(sem['status'] == 'COMPLETE' and sem['calc_version'] == '029' and len(sem['report_checksum']) == 32 and 'logistics.tracking_event' in sem['sources'] and sem['generated_at'],
           'l\'en-tête du rapport : statut, version, empreinte, sources, horodatage')
        ok(f('lg_an_report', admin, p_grain='week', p_from=str(D1), p_to=str(D3))['report_checksum'] == sem['report_checksum'], 'la même demande rend la même empreinte de rapport')
        r0 = sem['runs'][0]
        ok(r0['source'] == 'manual' and r0['calc_version'] == '029' and r0['current_version'] is True and len(r0['calc_fingerprint']) == 32 and r0['status'] == 'COMPLETE',
           'chaque exécution : source, version, empreinte du code, statut')
        ok(f('lg_an_verify', admin, p_run_id=run['run_id'])['verdict'] == 'REPRODUCIBLE', 'le calcul de 029, refait : reproductible')
        journal = f('lg_an_runs', admin, p_limit=3)
        ok(journal[0]['run_id'] == run['run_id'] and journal[0]['generated_by'] == 'client1@essai.test' and journal[0]['alerts'] >= 1, 'le journal des exécutions : qui, et combien d\'alertes chacune a levées')

        # ============================================================== F. les alertes
        A = f('lg_an_alerts', admin, p_all=False)
        cles = {(x['code'], x['subject'], x['day']) for x in A['items']}
        for att in (('KPI_IMPOSSIBLE', 'avg_transit_hours', str(D4)), ('DATA_MISSING', 'deliveries_without_driver', str(D3)), ('KPI_IMPOSSIBLE', 'collection_pct', str(D7)),
                    ('ANOMALY', 'parcels_received', str(D8))):
            ok(att in cles, 'alerte levée : %s %s du %s' % att)
        ano = [x for x in A['items'] if x['code'] == 'ANOMALY' and x['day'] == str(D8)][0]
        ok(float(ano['detail']['value']) == 6 and float(ano['detail']['mean']) == round(3 / 28, 2) and ano['detail']['days'] == 28, 'l\'anomalie dit sa valeur, la moyenne et l\'historique : %s' % ano['detail'])
        ok(not any(x['code'] == 'ANOMALY' and x['subject'] == 'revenue_net_usd' for x in A['items']), 'un petit volume (100 $ un jour) ne crie pas au loup')
        nb = q("select count(*) from analytics.alert")
        f('lg_an_refresh', admin, p_from='2026-08-01', p_to=str(D8))
        ok(q("select count(*) from analytics.alert") == nb, 'le même calcul refait : aucune alerte en double')
        A_ops = f('lg_an_alerts', ops, p_all=True)
        ok(all(x['domain'] in ('ops', 'system') for x in A_ops['items']) and not any(x['subject'] == 'collection_pct' for x in A_ops['items']), 'l\'activité seule ne voit pas les alertes financières')
        A_fin = f('lg_an_alerts', fin, p_all=True)
        ok(any(x['subject'] == 'collection_pct' for x in A_fin['items']) and all(x['domain'] in ('finance', 'system') for x in A_fin['items']), 'la finance seule voit les siennes')
        refuse('lg_an_ack_alert', 'LG003', 'acquitter : la direction seulement', ops, p_alert_id=ano['id'])
        ack = f('lg_an_ack_alert', admin, p_alert_id=ano['id'], p_note='promotion du 8 septembre')
        ok(ack['note'] == 'promotion du 8 septembre' and f('lg_an_alerts', admin, p_all=False)['open'] == A['open'] - 1, 'acquittée : elle quitte les alertes ouvertes')
        ok(f('lg_an_ack_alert', admin, p_alert_id=ano['id'])['note'] == 'promotion du 8 septembre', 'acquitter deux fois ne change rien (la première note reste)')
        ok(any(x['id'] == ano['id'] and x['acked_at'] for x in f('lg_an_alerts', admin, p_all=True)['items']), 'elle reste dans l\'historique, acquittée')
        refuse('lg_an_ack_alert', 'LG002', 'une alerte inconnue', admin, p_alert_id=999999)
        refuse('lg_an_ack_alert', 'LG005', 'une note trop longue', admin, p_alert_id=ano['id'], p_note='x' * 301)
        for sql_, msg in (("update analytics.alert set severity = 'WARN'", 'changer une alerte'), ("delete from analytics.alert", 'effacer les alertes'),
                          ("delete from analytics.alert_ack", 'effacer un acquittement')):
            code, t_ = cl.run(B, sql_, expect_error=True)
            ok(code != 0 and 'LG004' in t_, 'en ajout seul : %s interdit' % msg)
        # un recalcul planifié en échec : journalisé, alerté, signalé ; rien d'écrit dans les faits
        corps = '\n'.join(cl.lignes(B, "select pg_get_functiondef('analytics.compute_facts(date,date)'::regprocedure)"))
        casse = corps.replace("select d, metric, dimension, round(value, 4) from faits", "select d, metric, dimension, round(value / 0, 4) from faits")
        ok(casse != corps, 'variante cassée du calcul préparée')
        cl.run(B, casse)
        runs_avant = q("select count(*) from analytics.report_run")
        code, t_ = cl.run(B, "select public.ses_an_refresh()", role='service_role')
        echec = json.loads(t_)
        ok(code == 0 and echec['status'] == 'FAILED' and echec['sqlstate'] == '22012' and q("select count(*) from analytics.report_run") == runs_avant,
           'un recalcul planifié qui échoue ne casse rien et n\'écrit aucun chiffre : %s' % echec.get('status'))
        ok(q("select count(*) from analytics.run_failure where source = 'scheduler'") == '1' and q("select count(*) from analytics.alert where code = 'REFRESH_FAILED'") == '1'
           and q("select status from ops.heartbeat where source = 'analytics_refresh' order by id desc limit 1") == 'FAIL', 'il est journalisé, alerté (REFRESH_FAILED) et signalé (battement FAIL)')
        code, t_ = cl.run(B, "delete from analytics.run_failure", expect_error=True)
        ok(code != 0 and 'LG004' in t_, 'en ajout seul : effacer un échec interdit')
        cl.run(B, P.lire_sql('outils/logistique/029-analytique-complete.sql'))
        ok(f('lg_an_verify', admin, p_run_id=run['run_id'])['verdict'] == 'REPRODUCIBLE', '029 rejouée : le calcul d\'origine, de nouveau reproductible')
        sante = {c['code']: c for c in json.loads(cl.run(B, 'select public.lg_ops_status()', role='authenticated', claims=admin)[1])['checks']}
        ok(sante['analytics_failures_24h']['status'] == 'WARN' and sante['analytics_open_alerts']['status'] == 'FAIL' and sante['analytics_open_alerts']['value'] >= 1,
           'la santé du système voit les alertes ouvertes (dont une grave) et l\'échec du recalcul')
        # un recalcul qui n'a pas eu lieu depuis 30 heures (l'essai vieillit les exécutions, en contournant l'ajout seul : seulement ici)
        q("alter table analytics.report_run disable trigger report_run_append_only")
        q("update analytics.report_run set generated_at = generated_at - interval '30 hours'")
        q("alter table analytics.report_run enable trigger report_run_append_only")
        w = json.loads(q('select analytics.watch()'))
        ok(w['hours_since_last'] >= 30 and q("select severity from analytics.alert where code = 'REFRESH_NOT_RUN'") == 'WARN', 'trente heures sans recalcul : alerte « recalcul non exécuté »')

        # ============================================================== G. les droits et les portes
        r_ops = f('lg_an_report', ops, p_grain='week', p_from=str(D1), p_to=str(D3))
        ok(r_ops['domains'] == ['ops'] and not any(x['metric'] in ('receivables_usd', 'expenses_usd', 'customers_active') for x in r_ops['rows'])
           and 'margin_usd' not in r_ops['derived'][0]['values'] and 'delivery_success_pct' in r_ops['derived'][0]['values'], 'activité seule : ni argent ni clientèle, même dans les dérivés')
        r_fin = f('lg_an_report', fin, p_grain='week', p_from=str(D1), p_to=str(D3))
        ok(r_fin['domains'] == ['finance'] and r_fin['breakdown'] is None and 'margin_usd' in r_fin['derived'][0]['values'], 'finance seule : l\'argent, sans le détail des livraisons')
        for u_, nom_ in ((rien, 'un membre sans droit'), (client, 'un client')):
            refuse('lg_an_alerts', 'LG003', '%s : pas d\'alertes' % nom_, u_)
        code, t_ = cl.run(B, appel('lg_an_alerts'), role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in t_, 'un visiteur : rien')
        for t_nom in ('alert', 'alert_ack', 'run_failure'):
            ok(q("select has_table_privilege('authenticated', 'analytics.%s', 'select')::text || has_table_privilege('anon', 'analytics.%s', 'select')::text" % (t_nom, t_nom)) == 'falsefalse',
               'analytics.%s : aucun accès direct' % t_nom)
        for fn in ('analytics.scheduled_refresh()', 'analytics.watch()', 'analytics.detect(bigint)'):
            ok(q("select has_function_privilege('authenticated', '%s', 'execute')::text || has_function_privilege('anon', '%s', 'execute')::text" % (fn, fn)) == 'falsefalse',
               '%s : jamais appelée de l\'extérieur' % fn)
        portes = cl.lignes(B, "select p.proname || '|' || has_function_privilege('authenticated', p.oid, 'execute') || '|' || has_function_privilege('anon', p.oid, 'execute') || '|' || p.prosecdef "
                              "from pg_proc p join pg_namespace n on n.oid = p.pronamespace where (n.nspname = 'public' and (p.proname like 'lg\\_an\\_%' or p.proname = 'ses_an_refresh')) order by 1")
        ok(len(portes) == 8, 'huit portes : sept pour l\'équipe, une pour le travailleur')
        for l_ in portes:
            nom_, au_, an_, sd_ = l_.split('|')
            ok(an_ == 'false' and sd_ == 'true' and au_ == ('false' if nom_ == 'ses_an_refresh' else 'true'), '%s : bien fermée' % nom_)

        # ============================================================== H. les fichiers partagés avec le site
        SIG = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), 'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) "
                           "from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\\_an\\_%'"))
        EX = {'rapport_semaine': sem, 'rapport_jour': f('lg_an_report', admin, p_grain='day', p_from=str(D1), p_to=str(D3)), 'rapport_trou': rep_trou,
              'rapport_ancien': rep_ancien, 'indicateurs': k, 'executions': f('lg_an_runs', admin, p_limit=5), 'recalcul': run,
              'verification': f('lg_an_verify', admin, p_run_id=run['run_id']), 'verification_version': v_anc,
              'alertes': f('lg_an_alerts', admin, p_all=True), 'acquittement': ack, 'rapport_activite': r_ops, 'rapport_finance': r_fin}
        for nom_, contenu in (('analytique-complete-rpc.json', SIG), ('analytique-complete-exemples.json', EX)):
            ch = os.path.join(ICI, nom_)
            if os.environ.get('SES_FORME_ECRIRE'):
                json.dump(contenu, open(ch, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            ok(os.path.exists(ch), '%s existe (sinon : SES_FORME_ECRIRE=1)' % nom_)
        ok(json.load(open(os.path.join(ICI, 'analytique-complete-rpc.json'), encoding='utf-8')) == json.loads(json.dumps(SIG)), 'les signatures sont celles du fichier partagé avec le site')

        def forme(x, ch=''):
            if isinstance(x, dict):
                return {ch + '.' + k_ for k_ in x} | set().union(*[forme(v_, ch + '.' + k_) for k_, v_ in x.items()]) if x else set()
            if isinstance(x, list):
                return set().union(*[forme(v_, ch + '[]') for v_ in x]) if x else set()
            return set()
        lus = json.load(open(os.path.join(ICI, 'analytique-complete-exemples.json'), encoding='utf-8'))
        # les clés des étiquettes (identifiants de chauffeur) changent d'un essai à l'autre : on compare la forme sans elles
        net = lambda s: {re.sub(r'\.[0-9a-f-]{36}', '.<id>', x) for x in s}   # noqa: E731
        ok(all(net(forme(lus[k_])) == net(forme(json.loads(json.dumps(v_)))) for k_, v_ in EX.items()), 'les exemples ont la forme des réponses réelles (sinon : SES_FORME_ECRIRE=1)')
    print('%d vérifications — étape 029 (analytique complète, alertes, recalcul planifié) : OK' % N[0])


if __name__ == '__main__':
    main()
