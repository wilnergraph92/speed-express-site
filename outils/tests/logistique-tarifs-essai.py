#!/usr/bin/env python3
"""Étape 027 — les tarifs, les devis et la préparation de la bascule, éprouvés sur la RÉPLIQUE DE LA PRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-tarifs-essai.py

La réplique porte les vraies factures de l'ancien schéma (public.factures) et aucun tarif du noyau, comme la production. On exige :
 A. sans tarif, la couverture le dit (aucune zone, aucune grille là où il y a des colis) et un devis est refusé avec la raison ;
 B. la direction saisit une zone et une grille (valeurs d'ESSAI, jamais en production) : la vue d'ensemble les relit avec leurs tranches,
    la grille est « du jour », la couverture la trouve ; les 10 $ de frais de service sont là ; un employé lit sans pouvoir gérer ;
 C. un devis « au comptoir » (sans client) et un devis pour un client désigné par son CODE : le calcul est celui du noyau (poids × prix
    de la tranche + 10 $), le devis est numéroté, la liste le relit ; un code inconnu, un employé sans « factures.creer », un client : refusés ;
 D. les écarts de parité, un par un, avec l'identifiant de la facture héritée : bloquant tant qu'il n'est pas examiné, puis examiné avec sa
    note ; réservé à la direction ;
 E. RIEN n'a bougé dans l'argent (factures, paiements, mode « legacy ») ; fermé aux visiteurs ; 027 rejouée ne change rien.
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
    if isinstance(v, (list, dict)):
        return "'%s'::jsonb" % json.dumps(v).replace("'", "''")
    return "'%s'" % str(v).replace("'", "''")


def main():
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('027-tarifs-devis.sql' in etapes, 'l\'étape 027 est dans le noyau')
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        ok(json.loads(q("select logistics.run_migration('tarifs')"))['report']['ready'] is True, 'rattrapage prêt')
        for i, (mail, droits) in enumerate((('tar-fin@essai.test', "array['factures.lire', 'factures.creer']"), ('tar-lect@essai.test', "array['factures.lire']")), 1):
            q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
              "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0027-00000000000%d', 'authenticated', 'authenticated', '%s', 'x', now(), '{}')" % (i, mail))
            q("update public.clients set role = 'employe', code = null, droits = %s where email = '%s'" % (droits, mail))
        q("select logistics.run_migration('tarifs, employés')")
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        fin = q("select id from public.clients where email = 'tar-fin@essai.test'")
        lecteur = q("select id from public.clients where email = 'tar-lect@essai.test'")
        client = q("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1")
        code_client = q("select k.code from logistics.customer k join public.clients c on c.id = k.legacy_client_id where c.role = 'client' order by c.email limit 1")
        argent = "select (select count(*) from logistics.invoice) || '/' || (select count(*) from logistics.payment) || '/' || (select count(*) from public.factures) || '/' || " \
                 "(select value from logistics.finance_setting where key = 'mode')"
        argent_avant = q(argent)

        def appel(nom, acteur, kw):
            return cl.run('prod', 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items())),
                          role='authenticated', claims=acteur, expect_error=True)

        def f(nom, acteur=admin, **kw):
            code, sortie = appel(nom, acteur, kw)
            if code != 0:
                raise AssertionError('%s refusée : %s' % (nom, sortie[-400:]))
            return json.loads(sortie) if sortie.strip().startswith(('{', '[')) else sortie.strip()

        def refus(nom, attendu, msg, acteur=admin, **kw):
            code, sortie = appel(nom, acteur, kw)
            ok(code != 0 and attendu in sortie, '%s : attendu « %s », obtenu %s' % (msg, attendu, sortie[-240:]))

        ligne = [{'weight_lb': 10, 'service_mode': 'air', 'destination_country': 'HT'}]

        # ============================================================ A. sans tarif
        v = f('lg_pricing_overview')
        ok(v['zones'] == [] and v['rate_cards'] == [] and v['finance_mode'] == 'legacy' and v['can_manage'] is True, 'la production n\'a aucun tarif du noyau ; mode « legacy »')
        ok(v['coverage'] and all(c['zone'] is None and c['rate_card'] is None for c in v['coverage']) and sum(c['parcels'] for c in v['coverage']) > 0,
           'la couverture dit, pour chaque mode et pays où il y a des colis, qu\'il manque la zone et la grille : %s' % v['coverage'][:3])
        ok(any(s['code'] == 'SERVICE' and float(s['amount']) == 10 and s['currency'] == 'USD' for s in v['service_fees']), 'les 10 $ de frais de service (le seul fait connu)')
        refus('lg_quote_preview', 'zone tarifaire', 'sans zone, pas de devis (la raison est dite)', acteur=fin, p_currency='USD', p_items=ligne)

        # ============================================================ B. la direction saisit (valeurs d'essai)
        zone = f('lg_create_pricing_zone', p_code='ht', p_name='Haïti', p_country='HT')
        f('lg_create_rate_card', p_code='air-ht-essai', p_name='Aérien Haïti (essai)', p_mode='air', p_zone=R("'%s'::uuid" % zone), p_currency='USD',
          p_brackets=[{'min_lb': 0, 'max_lb': 50, 'price_per_lb': 4.5}, {'min_lb': 50, 'max_lb': None, 'price_per_lb': 4, 'min_charge': 0}])
        refus('lg_create_rate_card', 'LG003', 'un employé ne saisit pas de grille', acteur=fin, p_code='X', p_name='X', p_mode='air', p_zone=R("'%s'::uuid" % zone),
              p_currency='USD', p_brackets=[{'min_lb': 0, 'price_per_lb': 1}])
        v = f('lg_pricing_overview', acteur=lecteur)
        g = v['rate_cards'][0]
        ok(v['can_manage'] is False and v['zones'][0]['code'] == 'HT' and g['code'] == 'AIR-HT-ESSAI' and g['current'] is True and g['zone']['country'] == 'HT'
           and [float(b['price_per_lb']) for b in g['brackets']] == [4.5, 4.0] and g['brackets'][1]['max_lb'] is None,
           'un employé relit la zone et la grille (code en majuscules, du jour, deux tranches), sans pouvoir gérer')
        cov = {(c['mode'], c['country']): c for c in v['coverage']}
        ok(cov.get(('air', 'HT'), {}).get('rate_card') == 'AIR-HT-ESSAI' and cov[('air', 'HT')]['zone'] == 'HT', 'la couverture trouve la grille aérienne d\'Haïti')
        ok(all(c['rate_card'] is None for k, c in cov.items() if k != ('air', 'HT')), 'et dit encore ce qui manque ailleurs')
        refus('lg_pricing_overview', 'LG003', 'un client ne lit pas les tarifs', acteur=client)

        # ============================================================ C. les devis
        p = f('lg_quote_preview', acteur=fin, p_currency='USD', p_items=ligne)
        ok(float(p['freight_total']) == 45 and float(p['service_fee']) == 10 and float(p['total']) == 55 and p['customer_id'] is None,
           'au comptoir : 10 lb × 4,50 $ + 10 $ de frais = 55 $, calculé par le noyau : %s' % {k: p[k] for k in ('freight_total', 'service_fee', 'total')})
        refus('lg_quote_preview', 'LG002', 'un code client inconnu', acteur=fin, p_currency='USD', p_items=ligne, p_customer_code='SES-00000')
        refus('lg_quote_preview', 'LG003', 'un employé sans « factures.creer » ne fait pas de devis', acteur=lecteur, p_currency='USD', p_items=ligne)
        d = f('lg_create_quote_for', acteur=fin, p_customer_code=code_client.lower(), p_currency='USD', p_items=ligne + [{'weight_lb': 60, 'service_mode': 'air', 'destination_country': 'HT'}])
        ok(d['number'].startswith('QUO-') and d['status'] == 'OFFERED' and float(d['total']) == 45 + 240 + 10, 'un devis numéroté pour le client (code en minuscules) : 45 + 60 × 4 + 10 = 295 $')
        refus('lg_create_quote_for', 'LG002', 'un devis s\'adresse à un client inscrit', acteur=fin, p_customer_code='', p_currency='USD', p_items=ligne)
        refus('lg_create_quote_for', 'LG003', 'un client ne se fait pas de devis par l\'équipe', acteur=client, p_customer_code=code_client, p_currency='USD', p_items=ligne)
        lq = f('lg_cc_quotes', acteur=lecteur)
        ok(lq['total'] == 1 and lq['items'][0]['quote_id'] == d['quote_id'] and lq['items'][0]['customer']['code'] == code_client and lq['items'][0]['items'] == 2
           and float(lq['items'][0]['total']) == 295, 'la liste des devis : identifiant, client, deux colis, total')
        ok(f('lg_cc_quotes', acteur=lecteur, p_filters={'customer': code_client})['total'] == 1 and f('lg_cc_quotes', acteur=lecteur, p_filters={'status': 'CANCELLED'})['total'] == 0,
           'filtrée par client et par statut')
        f('lg_cancel_quote', acteur=fin, p_quote=R("'%s'::uuid" % d['quote_id']), p_reason='Client a changé d\'avis')
        ok(f('lg_cc_quotes', acteur=lecteur)['items'][0]['status'] == 'CANCELLED', 'annulé avec un motif, la liste le dit')

        # ============================================================ D. les écarts de parité
        e = f('lg_finance_parity_gaps')
        ok(len(e) > 0 and all(x['legacy_invoice_id'] and x['number'] and x['verdict'] != 'EQUAL' for x in e), '%d écart(s), chacun avec l\'identifiant de sa facture héritée' % len(e))
        bloquants = [x for x in e if x['blocking']]
        ok(bloquants and all(x['review'] is None for x in bloquants), 'des écarts BLOQUANTS (des colis sans grille : %s)' % sorted({x['verdict'] for x in bloquants}))
        rapport = f('lg_finance_cutover_report')
        ok(rapport['ready'] is False and rapport['parity_blocking'] == len(bloquants), 'le rapport de bascule compte les mêmes bloquants : pas prêt')
        x = bloquants[0]
        f('lg_review_legacy_parity', p_legacy_invoice_id=R("'%s'::uuid" % x['legacy_invoice_id']), p_note='Facture d\'essai, comprise')
        y = [z for z in f('lg_finance_parity_gaps') if z['legacy_invoice_id'] == x['legacy_invoice_id']][0]
        ok(y['blocking'] is False and y['review']['note'] == 'Facture d\'essai, comprise' and y['review']['by'], 'examiné : plus bloquant, la note et son auteur')
        ok(f('lg_finance_cutover_report')['parity_blocking'] == len(bloquants) - 1, 'le rapport compte un bloquant de moins')
        refus('lg_finance_parity_gaps', 'LG003', 'les écarts de parité sont réservés à la direction', acteur=fin)

        # ============================================================ E. rien n'a bougé dans l'argent ; fermé ; rejouable
        ok(q(argent) == argent_avant, 'aucune facture, aucun paiement, l\'ancienne facturation intacte, mode « legacy » : %s' % argent_avant)
        for nom in ('lg_pricing_overview()', 'lg_cc_quotes()', 'lg_finance_parity_gaps()'):
            code, sortie = cl.run('prod', 'select public.' + nom, role='anon', expect_error=True)
            ok(code != 0 and 'permission denied' in sortie, '%s : un visiteur ne lit rien' % nom)
        avant = q("select count(*) || '/' || (select count(*) from logistics.quote) from logistics.rate_card")
        cl.run('prod', P.lire_sql('outils/logistique/027-tarifs-devis.sql'))
        ok(q("select count(*) || '/' || (select count(*) from logistics.quote) from logistics.rate_card") == avant, '027 rejouée : rien ne change')
        print('PASS tarifs, devis et préparation de la bascule (étape 027) : %d vérifications — sur la réplique de la production : couverture des '
              'tarifs, grille saisie par la direction, devis calculés par le noyau, écarts de parité examinés un par un, AUCUN mouvement d\'argent '
              '(PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC tarifs et devis (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
