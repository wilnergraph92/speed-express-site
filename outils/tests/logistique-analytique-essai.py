#!/usr/bin/env python3
"""Noyau logistique, phase 16 : l'analytique et les rapports — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-analytique-essai.py

Jamais la production. Ce qu'on éprouve :
  (1) les faits quotidiens : une activité datée que le test maîtrise (dont une à 23 h 30 heure d'Haïti, qui est le lendemain en UTC) fait
      bouger EXACTEMENT les chiffres attendus, calculés ici par un second chemin, en Python (fuseau d'Haïti, heures de transit) ;
  (2) les grains : semaine (ISO), mois, trimestre, année = la somme des jours, recalculée ici avec le calendrier de Python ;
  (3) la traçabilité et la reproductibilité : chaque calcul est une exécution (empreinte, état des sources) ; recalculé, un jour passé donne
      la même empreinte ; un rattrapage dans un journal est détecté (« les sources ont changé ») ; un calcul modifié aussi (« le calcul a
      changé ») ; faits et exécutions en ajout seul ; le chiffre en vigueur est celui de la dernière exécution ;
  (4) les droits : activité, finance et clientèle séparées ; recalculer = direction ; jours jamais calculés signalés ; les indicateurs de la
      période et de la précédente, et leurs rapports, calculés par la base ;
  (5) la séparation : le schéma analytique n'est lisible que par la façade ; le travailleur seul a la clé du recalcul planifié.
Écrit analytique-rpc.json (signatures) et analytique-exemples.json (réponses réelles) pour le test du site (analytique-contrat.cjs)."""
import datetime as dt
import json
import os
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


def jour_haiti(d, h, mi=0):
    """Un instant à Haïti → ISO avec décalage (le second chemin : Python, pas la base)."""
    return dt.datetime(d.year, d.month, d.day, h, mi, tzinfo=HAITI)


def heures(a, b):
    """La VRAIE durée entre deux instants. Attention : en Python, a - b entre deux heures du MÊME fuseau ignore les changements d'heure
    (écart « à l'horloge ») ; il faut passer par UTC."""
    return (b.astimezone(dt.timezone.utc) - a.astimezone(dt.timezone.utc)).total_seconds() / 3600


def debut(grain, d):
    if grain == 'day':
        return d
    if grain == 'week':
        return d - dt.timedelta(days=d.weekday())
    if grain == 'month':
        return d.replace(day=1)
    if grain == 'quarter':
        return d.replace(month=3 * ((d.month - 1) // 3) + 1, day=1)
    return d.replace(month=1, day=1)


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        P.monter_historique(cl, B)
        for f_ in ('001-modele-de-domaine', '002-retroremplissage', '003-machine-d-etats', '004-entrepot', '005-transport-douane', '006-dernier-kilometre',
                   '007-finance', '008-portail-client', '009-centre-de-commande', '010-notifications', '011-applications'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f_))
        # trois membres de l'équipe de plus : finance seule, aucun droit, et (déjà dans la fixture) client3 = activité seule
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) "
          "select '00000000-0000-0000-0000-000000000000', ('00000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid, 'authenticated', 'authenticated', "
          "'equipe' || i || '@essai.test', '$2a$10$fictif', now(), jsonb_build_object('nom_complet', 'Équipe ' || i, 'pays', 'Haïti', 'ville', 'Delmas', 'adresse', 'x', 'telephone', '+509 3000', 'langue', 'fr') "
          "from generate_series(31, 32) i")
        q("update public.clients set role = 'employe', droits = array['factures.lire'] where email = 'equipe31@essai.test'")
        q("update public.clients set role = 'employe', droits = '{}' where email = 'equipe32@essai.test'")
        q('select logistics.backfill_from_legacy()')
        # Comme sur Supabase : toute fonction créée devient exécutable par anon et authenticated, sauf révocation explicite.
        q("alter default privileges in schema public grant execute on functions to anon, authenticated")
        cl.run(B, P.lire_sql('outils/logistique/012-analytique.sql'))
        cl.run(B, P.lire_sql('outils/logistique/012-analytique.sql'))
        q("alter default privileges in schema public revoke execute on functions from anon, authenticated")
        ok(True, '012 chargée deux fois de suite')
        uid = lambda e: q("select id from public.clients where email = '%s'" % e)   # noqa: E731
        admin, ops, fin, rien, client = uid('client1@essai.test'), uid('client3@essai.test'), uid('equipe31@essai.test'), uid('equipe32@essai.test'), uid('client9@essai.test')
        ca = q("select id from logistics.customer where auth_user_id = '%s'" % client)
        org = q('select id from logistics.organization')
        aujourdhui = dt.date.fromisoformat(q('select logistics.today()::text'))

        def f(nom, acteur, **kw):
            code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
            return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

        def refuse(nom, etat, msg, acteur, **kw):
            code, texte = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
            ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-200:].replace('\n', ' ')))

        # ============================================================== A. le décor : les jours choisis
        A, Bj, C, D, E = dt.date(2025, 12, 31), dt.date(2026, 9, 1), dt.date(2026, 9, 2), dt.date(2026, 9, 7), dt.date(2026, 10, 1)
        ok(E < aujourdhui, 'les jours du décor sont passés (aujourd\'hui : %s)' % aujourdhui)
        # la base et Python découpent les journées de la même façon (heure d'été comprise)
        for d_ in (A, Bj, E):
            ok(dt.datetime.fromisoformat(q("select to_char(logistics.day_start('%s') at time zone 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS')" % d_) + '+00:00') == jour_haiti(d_, 0).astimezone(dt.timezone.utc),
               'début du %s : même instant pour la base et pour Python' % d_)

        f('lg_an_refresh', admin, p_from=str(A), p_to=str(aujourdhui))
        avant = f('lg_an_report', admin, p_grain='day', p_from=str(A), p_to=str(aujourdhui))
        ok(avant['missing_days'] == [] and avant['domains'] == ['ops', 'finance', 'customers'], 'l\'administrateur voit tout ; aucun jour manquant après un calcul')

        # ============================================================== B. l'activité datée, et ce qu'elle doit faire aux chiffres
        attendu = {}

        def plus(d_, metrique, dim, v):
            k = (str(d_), metrique, dim)
            attendu[k] = round(attendu.get(k, 0) + v, 4)

        def colis(n, mode, statut='CREATED'):
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, destination_city, service_mode, status, status_authority, source, weight_lb) "
                     "values ('%s', 'AN-%03d', 'tan%d', '%s', 'HT', 'Delmas', '%s', '%s', 'core', 'legacy_backfill', 3) returning id" % (org, n, n, ca, mode, statut))

        def evenement(p_, statut, quand):
            q("insert into logistics.tracking_event (parcel_id, event_type, to_status, occurred_at, source, correlation_id) values ('%s', 'Essai', '%s', '%s', 'manual', gen_random_uuid())"
              % (p_, statut, quand.isoformat()))

        p1, p2, p3, p4 = colis(1, 'air'), colis(2, 'sea'), colis(3, 'air'), colis(4, 'air')
        evenement(p1, 'RECEIVED', jour_haiti(A, 12)); evenement(p1, 'RECEIVED', jour_haiti(A, 13))           # deux fois reçu : un colis
        evenement(p1, 'DELIVERED', jour_haiti(Bj, 23, 30))                                                   # 23 h 30 à Haïti = le lendemain en UTC
        evenement(p2, 'RECEIVED', jour_haiti(Bj, 0, 15)); evenement(p2, 'DELIVERED', jour_haiti(D, 12))
        evenement(p3, 'RECEIVED', jour_haiti(C, 12)); evenement(p3, 'ON_HOLD', jour_haiti(C, 13)); evenement(p3, 'DAMAGED', jour_haiti(E, 12))
        evenement(p4, 'DELIVERED', jour_haiti(E, 10))                                                        # livré sans réception connue
        p7 = colis(7, 'sea')
        evenement(p7, 'RECEIVED', jour_haiti(dt.date(2026, 8, 31), 12))                                      # le dernier jour de la période précédente
        plus(dt.date(2026, 8, 31), 'parcels_received', 'sea', 1)
        plus(A, 'parcels_received', 'air', 1); plus(Bj, 'parcels_delivered', 'air', 1)
        plus(Bj, 'transit_hours_sum', 'air', heures(jour_haiti(A, 12), jour_haiti(Bj, 23, 30))); plus(Bj, 'transit_count', 'air', 1)
        plus(Bj, 'parcels_received', 'sea', 1); plus(D, 'parcels_delivered', 'sea', 1)
        plus(D, 'transit_hours_sum', 'sea', heures(jour_haiti(Bj, 0, 15), jour_haiti(D, 12))); plus(D, 'transit_count', 'sea', 1)
        plus(C, 'parcels_received', 'air', 1); plus(C, 'parcels_on_hold', '', 1); plus(E, 'parcels_damaged', '', 1)
        plus(E, 'parcels_delivered', 'air', 1)
        ok(heures(jour_haiti(A, 12), jour_haiti(Bj, 23, 30)) == 5866.5 and (jour_haiti(Bj, 23, 30) - jour_haiti(A, 12)).total_seconds() / 3600 == 5867.5,
           'le transit de p1 traverse le passage à l\'heure d\'été : 5866,5 h réelles (5867,5 à l\'horloge)')

        # une expédition, deux missions, des scans, un incident, un ticket
        q("insert into logistics.branch (organization_id, code, name, kind, country, city) values ('%s', 'MIA', 'Miami', 'office', 'US', 'Miami'), ('%s', 'PAP', 'Hub', 'hub', 'HT', 'Port-au-Prince')" % (org, org))
        mia, pap = q("select id from logistics.branch where code = 'MIA'"), q("select id from logistics.branch where code = 'PAP'")
        q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'MIA-1', 'Entrepôt Miami')" % mia)
        w = q("select id from logistics.warehouse where code = 'MIA-1'")
        p6 = colis(6, 'air', 'CONSOLIDATION_PENDING')
        cl.run(B, "select public.lg_create_shipment('SHP-AN-1', 'air', '%s', '%s', p_parcel_ids => array['%s']::uuid[])" % (mia, pap, p6), role='authenticated', claims=admin)
        sh_id = q("select id from logistics.shipment where code = 'SHP-AN-1'")
        for statut, quand in (('DISPATCHED', jour_haiti(Bj, 12)), ('DISPATCHED', jour_haiti(Bj, 14)), ('ARRIVED', jour_haiti(D, 12))):
            q("insert into logistics.shipment_status_history (shipment_id, to_status, occurred_at, correlation_id) values ('%s', '%s', '%s', gen_random_uuid())" % (sh_id, statut, quand.isoformat()))
        plus(Bj, 'shipments_dispatched', '', 1); plus(D, 'shipments_arrived', '', 1)
        p5 = colis(5, 'air', 'AT_DESTINATION_HUB')
        t_liv = json.loads(cl.run(B, "select public.lg_create_delivery(array['%s']::uuid[], '%s', current_date, p_address => '5 rue')" % (p5, pap), role='authenticated', claims=admin)[1])['task_id']
        t_enl = f('lg_create_pickup_task', admin, p_customer_id=ca, p_address='4 rue', p_scheduled_date=str(aujourdhui))['task_id']
        for t_, statut, quand in ((t_liv, 'COMPLETED', jour_haiti(C, 12)), (t_enl, 'FAILED', jour_haiti(C, 12)), (t_enl, 'COMPLETED', jour_haiti(D, 12))):
            q("insert into logistics.task_status_history (task_id, to_status, occurred_at, correlation_id) values ('%s', '%s', '%s', gen_random_uuid())" % (t_, statut, quand.isoformat()))
        plus(C, 'tasks_completed', 'DELIVERY', 1); plus(C, 'tasks_failed', 'PICKUP', 1); plus(D, 'tasks_completed', 'PICKUP', 1)
        for resultat in ('ACCEPTED', 'ACCEPTED', 'UNKNOWN_PARCEL'):
            q("insert into logistics.scan (scanned_code, code_kind, purpose, result, actor_user_id, warehouse_id, scanned_at, correlation_id) values ('AN-X', 'barcode', 'receive', '%s', '%s', '%s', '%s', gen_random_uuid())"
              % (resultat, admin, w, jour_haiti(Bj, 12).isoformat()))
        plus(Bj, 'scans_total', 'MIA-1', 3); plus(Bj, 'scans_rejected', 'MIA-1', 1)
        q("insert into logistics.incident (type, correlation_id, created_at) values ('DAMAGED', gen_random_uuid(), '%s')" % jour_haiti(E, 12).isoformat())
        plus(E, 'incidents_opened', 'DAMAGED', 1)
        q("insert into logistics.support_ticket (number, customer_id, subject, category, created_at) values ('TK-AN-1', '%s', 'Essai analytique', 'OTHER', '%s')" % (ca, jour_haiti(C, 12).isoformat()))
        plus(C, 'tickets_opened', '', 1)
        # la finance : des écritures, deux paiements, un remboursement
        inv = q("select id from logistics.invoice where customer_id = '%s' order by id limit 1" % ca)
        for d_, cat, net, tax in ((A, 'FREIGHT', 100.50, 0), (A, 'SERVICE_FEE', 10, 0), (E, 'FREIGHT', 40, 2.5), (C, 'CREDIT_NOTE', 0, 0)):
            q("insert into logistics.revenue_entry (invoice_id, entry_date, category, net_amount, tax_amount, currency, net_base_usd, tax_base_usd, correlation_id) values ('%s', '%s', '%s', %s, %s, 'USD', %s, %s, gen_random_uuid())"
              % (inv, d_, cat, net, tax, net, tax))
            if net:
                plus(d_, 'revenue_net_usd', cat, net)
            if tax:
                plus(d_, 'revenue_tax_usd', '', tax)
        pays = []
        # le second est remis en gourdes : les chiffres comptent le montant en dollars de base, jamais la somme remise dans sa devise
        for n_, quand, montant, remis, devise, taux, moyen in ((1, jour_haiti(Bj, 12), 50, 50, 'USD', 1, 'CASH'), (2, jour_haiti(E, 12), 30, 3960, 'HTG', 132, 'TRANSFER')):
            pays.append(q("insert into logistics.payment (number, invoice_id, customer_id, amount, currency, base_amount_usd, tendered_amount, tendered_currency, rate_used, method, paid_at, correlation_id) "
                          "values ('PAY-AN-%d', '%s', '%s', %s, 'USD', %s, %s, '%s', %s, '%s', '%s', gen_random_uuid()) returning id" % (n_, inv, ca, montant, montant, remis, devise, taux, moyen, quand.isoformat())))
            plus(quand.date(), 'payments_usd', moyen, montant); plus(quand.date(), 'payments_count', moyen, 1)
        q("insert into logistics.refund (number, payment_id, invoice_id, customer_id, amount, currency, base_amount_usd, method, reason, created_at, correlation_id) "
          "values ('RF-AN-1', '%s', '%s', '%s', 5, 'USD', 5, 'CASH', 'essai', '%s', gen_random_uuid())" % (pays[1], inv, ca, jour_haiti(E, 15).isoformat()))
        plus(E, 'refunds_usd', '', 5)

        # ============================================================== C. les faits : exactement ce qui était attendu
        run_tout = f('lg_an_refresh', admin, p_from=str(A), p_to=str(aujourdhui))
        ok(run_tout['partial'] is True and run_tout['rows'] > 0 and len(run_tout['checksum']) == 32, 'une période qui touche aujourd\'hui : marquée provisoire, avec son empreinte')
        apres = f('lg_an_report', admin, p_grain='day', p_from=str(A), p_to=str(aujourdhui))

        def table(rep):
            return {(r['period'], r['metric'], r['dimension']): float(r['value']) for r in rep['rows']}
        t0, t1 = table(avant), table(apres)
        ecarts = {k: round(t1.get(k, 0) - t0.get(k, 0), 4) for k in set(t0) | set(t1) if round(t1.get(k, 0) - t0.get(k, 0), 4) != 0}
        ecarts = {k: v for k, v in ecarts.items() if k[1] != 'customers_new'}
        manquants = {k: v for k, v in attendu.items() if ecarts.get(k) != v}
        en_trop = {k: v for k, v in ecarts.items() if k not in attendu}
        ok(not manquants and not en_trop, 'les faits bougent EXACTEMENT comme prévu — manquants ou faux : %s ; en trop : %s' % (manquants, en_trop))
        ok(t1.get((str(Bj), 'parcels_delivered', 'air'), 0) - t0.get((str(Bj), 'parcels_delivered', 'air'), 0) == 1 and
           t1.get((str(Bj + dt.timedelta(days=1)), 'parcels_delivered', 'air'), 0) == t0.get((str(Bj + dt.timedelta(days=1)), 'parcels_delivered', 'air'), 0),
           'une livraison à 23 h 30 heure d\'Haïti compte pour CE jour-là, pas pour le lendemain (UTC)')
        ok(q("select count(*) from analytics.daily_fact where value = 0") == '0', 'aucun fait à zéro n\'est stocké (une écriture nulle ne crée pas de ligne)')
        nouveaux = int(q("select count(*) from logistics.customer where (created_at at time zone 'America/Port-au-Prince')::date = logistics.today()"))
        ok(int(t1.get((str(aujourdhui), 'customers_new', ''), 0)) == nouveaux, 'fiches client créées aujourd\'hui : %d, par un second chemin' % nouveaux)

        # ============================================================== D. les grains = la somme des jours
        for grain in ('week', 'month', 'quarter', 'year'):
            rep = f('lg_an_report', admin, p_grain=grain, p_from=str(A), p_to=str(aujourdhui))
            somme = {}
            for (jour_, m_, d_), v in t1.items():
                k = (str(debut(grain, dt.date.fromisoformat(jour_))), m_, d_)
                somme[k] = round(somme.get(k, 0) + v, 4)
            ok(table(rep) == somme, '%s : chaque période = la somme de ses jours (calendrier de Python)' % grain)
            tot = {}
            for (per_, m_, d_), v in somme.items():
                tot[(per_, m_)] = round(tot.get((per_, m_), 0) + v, 4)
            ok({(x['period'], x['metric']): float(x['value']) for x in rep['totals']} == tot, '%s : les totaux par mesure = la somme de ses dimensions' % grain)
            attendues = sorted({str(debut(grain, A + dt.timedelta(days=i))) for i in range((aujourdhui - A).days + 1)})
            ok(rep['periods'] == attendues, '%s : les périodes couvertes, dans l\'ordre (%d)' % (grain, len(attendues)))
        sem = f('lg_an_report', admin, p_grain='week', p_from=str(Bj), p_to=str(D))
        ok(sem['periods'] == ['2026-08-31', '2026-09-07'], 'semaine ISO : le lundi 31 août, puis le lundi 7 septembre')

        # ============================================================== E. traçabilité et reproductibilité
        r1 = f('lg_an_refresh', admin, p_from=str(A), p_to=str(E))
        r1b = f('lg_an_refresh', admin, p_from=str(A), p_to=str(E))
        ok(r1['partial'] is False and r1['checksum'] == r1b['checksum'] and r1b['run_id'] > r1['run_id'], 'une période passée, recalculée : même empreinte, nouvelle exécution tracée')
        v1 = f('lg_an_verify', admin, p_run_id=r1['run_id'])
        ok(v1['verdict'] == 'REPRODUCIBLE' and v1['reproducible'] is True and v1['stored_intact'] is True and v1['sources_changed'] is False, 'vérifiée : reproductible, faits enregistrés intacts')
        runs = f('lg_an_runs', admin, p_limit=5)
        ok(runs[0]['run_id'] == r1b['run_id'] and runs[0]['generated_by'] == 'client1@essai.test' and runs[0]['rows'] == r1b['rows'], 'le journal des exécutions : la plus récente d\'abord, avec qui l\'a lancée')
        # un rattrapage dans un journal, sur un jour déjà calculé
        evenement(p4, 'RECEIVED', jour_haiti(D, 9))
        v2 = f('lg_an_verify', admin, p_run_id=r1b['run_id'])
        ok(v2['verdict'] == 'SOURCES_CHANGED' and v2['reproducible'] is False and v2['sources_changed'] is True and v2['stored_intact'] is True, 'un rattrapage : « les sources ont changé », et les faits enregistrés restent intacts')
        avant_d = f('lg_an_report', admin, p_grain='day', p_from=str(D), p_to=str(D))
        ok(table(avant_d).get((str(D), 'parcels_received', 'air'), 0) == t1.get((str(D), 'parcels_received', 'air'), 0), 'tant qu\'on ne recalcule pas, le chiffre publié ne bouge pas (il reste celui d\'une exécution tracée)')
        r2 = f('lg_an_refresh', admin, p_from=str(D), p_to=str(D))
        apres_d = f('lg_an_report', admin, p_grain='day', p_from=str(Bj), p_to=str(D))
        ok(table(apres_d).get((str(D), 'parcels_received', 'air'), 0) == t1.get((str(D), 'parcels_received', 'air'), 0) + 1, 'recalculé : le jour rattrapé prend sa nouvelle valeur')
        ok(table(apres_d).get((str(Bj), 'scans_total', 'MIA-1'), 0) == t1.get((str(Bj), 'scans_total', 'MIA-1'), 0), 'les autres jours gardent l\'exécution précédente')
        ok(any(x['run_id'] == r2['run_id'] for x in apres_d['runs']) and any(x['run_id'] == r1b['run_id'] for x in apres_d['runs']), 'le rapport dit de quelles exécutions viennent ses chiffres')
        # un calcul modifié (même sources) : détecté
        corps = cl.lignes(B, "select pg_get_functiondef('analytics.compute_facts(date,date)'::regprocedure)")
        modifie = '\n'.join(corps).replace("round(value, 4) from faits", "round(value * 2, 4) from faits")
        ok(modifie != '\n'.join(corps), 'variante du calcul préparée')
        cl.run(B, modifie)
        v3 = f('lg_an_verify', admin, p_run_id=r2['run_id'])
        ok(v3['verdict'] == 'COMPUTATION_CHANGED' and v3['sources_changed'] is False, 'même sources, autre résultat : « le calcul a changé »')
        cl.run(B, P.lire_sql('outils/logistique/012-analytique.sql'))
        ok(f('lg_an_verify', admin, p_run_id=r2['run_id'])['verdict'] == 'REPRODUCIBLE', '012 rejouée : le calcul d\'origine, de nouveau reproductible')
        # en ajout seul
        for sql_, msg in (("update analytics.daily_fact set value = 0", 'changer un fait'), ("delete from analytics.daily_fact", 'effacer les faits'),
                          ("update analytics.report_run set checksum = 'x'", 'changer une empreinte'), ("delete from analytics.report_run", 'effacer une exécution')):
            code, t_ = cl.run(B, sql_, expect_error=True)
            ok(code != 0 and 'LG004' in t_, 'interdit, même au propriétaire de la base : %s' % msg)

        # ============================================================== F. les droits et les erreurs
        r_ops = f('lg_an_report', ops, p_grain='month', p_from=str(Bj), p_to=str(E))
        ok(r_ops['domains'] == ['ops'] and all(x['domain'] == 'ops' for x in r_ops['metrics']), 'activité seule : les mesures d\'activité seulement')
        ok(not any(x['metric'] in ('revenue_net_usd', 'payments_usd', 'refunds_usd', 'tickets_opened', 'customers_new') for x in r_ops['rows']), 'ni argent, ni clientèle dans ses lignes')
        r_fin = f('lg_an_report', fin, p_grain='month', p_from=str(A), p_to=str(E))
        ok(r_fin['domains'] == ['finance'] and r_fin['rows'] and all(x['metric'] in ('revenue_net_usd', 'revenue_tax_usd', 'payments_usd', 'payments_count', 'refunds_usd') for x in r_fin['rows']), 'finance seule : l\'argent seulement')
        for u_, nom_ in ((rien, 'un membre sans droit'), (client, 'un client')):
            refuse('lg_an_report', 'LG003', '%s : pas de rapport' % nom_, u_, p_grain='day', p_from=str(Bj), p_to=str(C))
            refuse('lg_an_kpis', 'LG003', '%s : pas d\'indicateurs' % nom_, u_, p_from=str(Bj), p_to=str(C))
            refuse('lg_an_runs', 'LG003', '%s : pas de journal' % nom_, u_)
        refuse('lg_an_refresh', 'LG003', 'recalculer : la direction seulement', ops, p_from=str(Bj), p_to=str(C))
        refuse('lg_an_verify', 'LG003', 'vérifier : la direction seulement', ops, p_run_id=r1['run_id'])
        refuse('lg_an_report', 'LG005', 'grain inconnu', admin, p_grain='hour', p_from=str(Bj), p_to=str(C))
        refuse('lg_an_report', 'LG005', 'période à l\'envers', admin, p_grain='day', p_from=str(C), p_to=str(Bj))
        refuse('lg_an_refresh', 'LG005', 'calculer l\'avenir', admin, p_from=str(aujourdhui), p_to=str(aujourdhui + dt.timedelta(days=1)))
        refuse('lg_an_refresh', 'LG005', 'plus de 367 jours d\'un coup', admin, p_from='2024-01-01', p_to='2025-06-01')
        refuse('lg_an_verify', 'LG002', 'une exécution inconnue', admin, p_run_id=999999)
        trou = f('lg_an_report', admin, p_grain='day', p_from='2025-12-01', p_to='2025-12-05')
        ok(trou['missing_days'] == ['2025-12-01', '2025-12-02', '2025-12-03', '2025-12-04', '2025-12-05'] and trou['rows'] == [] and trou['runs'] == [],
           'des jours jamais calculés : signalés un par un, jamais comptés zéro en silence')
        ok(f('lg_an_report', admin, p_grain='day', p_from=str(D), p_to=str(aujourdhui))['partial'] is True, 'un rapport qui inclut un jour provisoire le dit')
        ok(f('lg_an_report', admin, p_grain='day', p_from=str(Bj), p_to=str(D))['partial'] is False, 'un rapport sur des jours clos n\'est pas provisoire')

        # ============================================================== G. les indicateurs : période et précédente, rapports calculés par la base
        k = f('lg_an_kpis', admin, p_from=str(Bj), p_to=str(D))
        ok(k['previous_from'] == '2026-08-25' and k['previous_to'] == '2026-08-31', 'la période précédente a la même longueur (7 jours)')
        tk = table(f('lg_an_report', admin, p_grain='day', p_from='2026-08-25', p_to=str(D)))

        def somme(m_, d0, d1, dim=None):
            return round(sum(v for (j_, mm, dd), v in tk.items() if mm == m_ and d0 <= j_ <= d1 and (dim is None or dd == dim)), 4)
        for m_ in ('parcels_received', 'parcels_delivered', 'scans_total', 'payments_usd', 'tasks_completed'):
            ok(float(k['current'][m_]) == somme(m_, str(Bj), str(D)) and float(k['previous'][m_]) == somme(m_, '2026-08-25', '2026-08-31'), 'indicateur %s : période et précédente' % m_)
        fait, rate = somme('tasks_completed', str(Bj), str(D), 'DELIVERY'), somme('tasks_failed', str(Bj), str(D), 'DELIVERY')
        ok(k['ratios_current']['delivery_success_pct'] == (round(100.0 * fait / (fait + rate), 1) if fait + rate else None), 'taux de livraisons réussies : calculé par la base')
        h_tot, nb = somme('transit_hours_sum', str(Bj), str(D)), somme('transit_count', str(Bj), str(D))
        ok(abs(float(k['ratios_current']['avg_transit_hours']) - round(h_tot / nb, 1)) < 0.051, 'délai moyen de transit (h) : %s' % k['ratios_current']['avg_transit_hours'])
        ok(float(k['ratios_current']['scan_rejection_pct']) == round(100.0 * somme('scans_rejected', str(Bj), str(D)) / somme('scans_total', str(Bj), str(D)), 1), 'taux de scans refusés')
        k_ops = f('lg_an_kpis', ops, p_from=str(Bj), p_to=str(D))
        ok(k_ops['ratios_current']['collection_pct'] is None and 'payments_usd' not in k_ops['current'] and k_ops['ratios_current']['delivery_success_pct'] is not None,
           'activité seule : ni encaissement ni paiements dans ses indicateurs')
        k_fin = f('lg_an_kpis', fin, p_from=str(E), p_to=str(E))
        te_ = table(f('lg_an_report', admin, p_grain='day', p_from=str(E), p_to=str(E)))
        paye, gagne = sum(v for (j_, m_, d_), v in te_.items() if m_ == 'payments_usd'), sum(v for (j_, m_, d_), v in te_.items() if m_ == 'revenue_net_usd')
        ok(k_fin['ratios_current']['delivery_success_pct'] is None and float(k_fin['ratios_current']['collection_pct']) == round(100.0 * paye / gagne, 1),
           'finance seule : taux d\'encaissement du jour E (paiements / revenus) = %s %%, sans taux de livraison' % k_fin['ratios_current']['collection_pct'])

        # ============================================================== H. la séparation et les portes
        code, t_ = cl.run(B, "select count(*) from analytics.daily_fact", role='authenticated', claims=admin, expect_error=True)
        ok(code != 0 and 'permission denied' in t_, 'le schéma analytique ne se lit pas en direct, même par l\'administrateur connecté')
        for t_nom in ('daily_fact', 'report_run', 'metric'):
            ok(q("select has_table_privilege('authenticated', 'analytics.%s', 'select')::text || has_table_privilege('anon', 'analytics.%s', 'select')::text" % (t_nom, t_nom)) == 'falsefalse',
               'analytics.%s : aucun droit de lecture direct (même si le schéma s\'ouvrait un jour)' % t_nom)
        code, t_ = cl.run(B, "select analytics.refresh(null, current_date, current_date)", role='authenticated', claims=admin, expect_error=True)
        ok(code != 0 and 'permission denied' in t_, 'les fonctions du schéma ne s\'appellent pas en direct')
        code, t_ = cl.run(B, "select public.ses_an_refresh()", role='authenticated', claims=admin, expect_error=True)
        ok(code != 0 and 'permission denied' in t_, 'le recalcul planifié : jamais par un connecté')
        code, t_ = cl.run(B, appel('lg_an_report', p_grain='day', p_from=str(Bj), p_to=str(C)), role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in t_, 'un visiteur : rien')
        code, t_ = cl.run(B, "select public.ses_an_refresh()", role='service_role')
        ok(code == 0 and json.loads(t_)['period_start'] == str(aujourdhui - dt.timedelta(days=1)) and json.loads(t_)['partial'] is True, 'le travailleur (clé secrète) : hier et aujourd\'hui')
        ok(f('lg_an_runs', admin, p_limit=1)[0]['generated_by'] == 'system', 'son exécution est tracée comme « système »')
        portes = cl.lignes(B, "select p.proname || '|' || has_function_privilege('authenticated', p.oid, 'execute') || '|' || has_function_privilege('anon', p.oid, 'execute') || '|' || p.prosecdef "
                              "from pg_proc p join pg_namespace n on n.oid = p.pronamespace where (n.nspname = 'public' and (p.proname like 'lg\\_an\\_%' or p.proname = 'ses_an_refresh')) order by 1")
        ok(len(portes) == 6, 'six portes : cinq pour l\'équipe, une pour le travailleur')
        for l_ in portes:
            nom_, au_, an_, sd_ = l_.split('|')
            ok(an_ == 'false' and sd_ == 'true' and au_ == ('false' if nom_ == 'ses_an_refresh' else 'true'), '%s : bien fermée' % nom_)
        ok(q("select count(*) from analytics.metric") == '22' and q("select count(*) from analytics.metric where btrim(definition) = ''") == '0', 'vingt-deux mesures, chacune avec sa définition écrite')

        # ============================================================== I. les fichiers partagés avec le site
        SIG = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), 'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) "
                           "from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\\_an\\_%'"))
        EX = {'rapport_mois': f('lg_an_report', admin, p_grain='month', p_from=str(Bj), p_to=str(E)), 'rapport_jour': f('lg_an_report', admin, p_grain='day', p_from=str(Bj), p_to=str(D)),
              'rapport_trou': trou, 'indicateurs': k, 'executions': f('lg_an_runs', admin, p_limit=5), 'recalcul': r2, 'verification': v1, 'verification_sources': v2}
        for nom_, contenu in (('analytique-rpc.json', SIG), ('analytique-exemples.json', EX)):
            ch = os.path.join(ICI, nom_)
            if os.environ.get('SES_FORME_ECRIRE'):
                json.dump(contenu, open(ch, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            ok(os.path.exists(ch), '%s existe (sinon : SES_FORME_ECRIRE=1)' % nom_)
        ok(json.load(open(os.path.join(ICI, 'analytique-rpc.json'), encoding='utf-8')) == json.loads(json.dumps(SIG)), 'les signatures sont celles du fichier partagé avec le site')
        # les exemples changent avec la date du jour (identifiants, empreintes) : on compare leur FORME, pas leurs valeurs
        def forme(x, ch=''):
            if isinstance(x, dict):
                return {ch + '.' + k_ for k_ in x} | set().union(*[forme(v, ch + '.' + k_) for k_, v in x.items()]) if x else set()
            if isinstance(x, list):
                return set().union(*[forme(v, ch + '[]') for v in x]) if x else set()
            return set()
        lus = json.load(open(os.path.join(ICI, 'analytique-exemples.json'), encoding='utf-8'))
        ok(all(forme(lus[k_]) == forme(json.loads(json.dumps(v))) for k_, v in EX.items()), 'les exemples ont la forme des réponses réelles (sinon : SES_FORME_ECRIRE=1)')
    print('%d vérifications — phase 16 (analytique et rapports) : OK' % N[0])


if __name__ == '__main__':
    main()
