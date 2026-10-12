#!/usr/bin/env python3
"""Phase 6 — la finance professionnelle (étape 018), éprouvée DEUX fois : sur la RÉPLIQUE DE LA PRODUCTION (noyau 001 → 018 par-dessus
les données du 7 octobre et leurs 200 factures héritées) et sur une PRÉPRODUCTION montée comme la vraie.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-finance-pro-essai.py

On exige :
 A. la PARITÉ avec l'ancien schéma : les règles de l'ancienne facturation (poids × tarif du colis, prix saisi à la main, 10 $ de frais
    une seule fois, facture groupée) rejouées par le NOYAU donnent les mêmes montants ; chaque écart est classé (colis changé après
    le paiement, colis sans tarif, facture sans colis…) ; aucun écart inexpliqué sur les données réelles ;
 B. les PRESTATAIRES : aucun secret dans la base (refusé même en écriture directe) ; le client ne voit que les prestataires actifs,
    sans référence de secret ; la demande de paiement porte le solde calculé par la base ;
 C. les WEBHOOKS (ouverts au seul serveur) : idempotents, vérifiés, journalisés, rattachés à la facture, au client et au prestataire ;
    non vérifié, montant faux, sans demande, déjà payé, argent arrivé sur une facture déjà soldée : rien d'appliqué, tout classé ;
 D. la RÉCONCILIATION : relevés du prestataire, écarts bloquants et informatifs, examen tracé par la direction ;
 E. les CORRECTIONS : avoir, remboursement, AJUSTEMENT (facture complémentaire liée) ; facture GROUPÉE en une seule transaction ;
    une facture émise ne se détruit jamais ; chaque geste audité (qui, quand, avant, après) ;
 F. la BASCULE : refusée tant que la réconciliation n'est pas propre, acceptée ensuite (direction, motif), réversible.
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
    """Fragment SQL brut, jamais mis entre guillemets."""


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
    q = lambda sql: cl.un(B, sql)   # noqa: E731
    L = lambda sql: cl.lignes(B, sql)   # noqa: E731

    # ---------------------------------------------------------------- le décor
    q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
      "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0006-000000000001', 'authenticated', 'authenticated', 'fi-comptable@essai.test', 'x', now(), '{\"nom_complet\": \"Comptable\"}')")
    q("update public.clients set role = 'employe', code = null, droits = array['factures.lire', 'factures.creer', 'factures.modifier', 'colis.lire'] where email = 'fi-comptable@essai.test'")
    clients = L("select id from public.clients where role = 'client' order by email limit 2")
    ca, cb = clients
    # L'ANCIENNE facturation, par l'ancien schéma lui-même (déclencheur facturer_colis) : poids × tarif, prix saisi, sans tarif, groupée.
    q("insert into public.colis (client_id, description, poids_lb, tarif_lb, pays_destination, service) values ('%s', 'fi-tarif', 5, 3.5, 'HT', 'aerien')" % ca)
    q("insert into public.colis (client_id, description, poids_lb, tarif_lb, prix_manuel, pays_destination, service) values ('%s', 'fi-forfait', 12, 3.5, 25, 'HT', 'aerien')" % ca)
    q("insert into public.colis (client_id, description, poids_lb, tarif_lb, pays_destination, service) values ('%s', 'fi-sans-tarif', 4, 0, 'HT', 'aerien')" % ca)
    q("insert into public.colis (client_id, description, poids_lb, tarif_lb, pays_destination, service) values ('%s', 'fi-paye', 10, 2, 'HT', 'aerien')" % ca)
    g1 = q("insert into public.colis (client_id, description, poids_lb, tarif_lb, pays_destination, service) values ('%s', 'fi-g1', 2, 4, 'HT', 'aerien') returning id" % ca)
    g2 = q("insert into public.colis (client_id, description, poids_lb, tarif_lb, prix_manuel, pays_destination, service) values ('%s', 'fi-g2', 3, 4, 15, 'HT', 'aerien') returning id" % ca)
    q("insert into public.factures (client_id, montant, frais_service, groupee, lignes) select '%s', 8 + 15 + 10, 10, true, jsonb_agg(jsonb_build_object('colis_id', c.id, 'numero', c.numero, "
      "'poids_lb', c.poids_lb, 'tarif_lb', c.tarif_lb, 'prix_manuel', c.prix_manuel is not null, 'montant', coalesce(c.prix_manuel, round(c.poids_lb * c.tarif_lb, 2)))) "
      "from public.colis c where c.id in ('%s', '%s')" % (ca, g1, g2))
    # payée, puis le colis change : l'ancienne facture reste figée
    admin_ancien = q("select id from public.clients where role = 'admin' order by email limit 1")
    cl.run(B, "update public.factures set montant_paye = montant, statut = 'payee' where colis_id = (select id from public.colis where description = 'fi-paye')", claims=admin_ancien)
    cl.run(B, "update public.colis set tarif_lb = 3 where description = 'fi-paye'", claims=admin_ancien)   # comme depuis le tableau de bord
    ok(json.loads(q("select logistics.run_migration('décor de la finance')"))['report']['ready'] is True, '[%s] décor : rattrapage prêt' % lieu)
    uid = lambda email: q("select id from public.clients where email = '%s'" % email)   # noqa: E731
    admin = q("select id from public.clients where role = 'admin' order by email limit 1")
    compta = uid('fi-comptable@essai.test')
    custa = q("select id from logistics.customer where legacy_client_id = '%s'" % ca)
    org = q('select id from logistics.organization')

    def f(nom, acteur=compta, **kw):
        code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
        return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

    def fr(nom, etat, msg, acteur=compta, role='authenticated', **kw):
        code, texte = cl.run(B, appel(nom, **kw), role=role, claims=acteur, expect_error=True)
        ok(code != 0 and etat in texte, '[%s] %s : attendu %s, obtenu : %s' % (lieu, msg, etat, texte[-220:].replace('\n', ' ')))
        return texte

    def srv(nom, **kw):
        code, sortie = cl.run(B, appel(nom, **kw), role='service_role')
        return json.loads(sortie)

    # la tarification du noyau : zones, grilles (4 $/lb), 10 $ de frais de service
    for pays in ('HT', 'DO', 'US'):
        z = f('lg_create_pricing_zone', acteur=admin, p_code='FZ-' + pays, p_name='Zone ' + pays, p_country=pays)
        for mode in ('air', 'sea', 'ground'):
            f('lg_create_rate_card', acteur=admin, p_code='FG-%s-%s' % (pays, mode), p_name='Grille', p_mode=mode, p_zone=z, p_currency='USD',
              p_brackets=R("'[{\"min_lb\": 0, \"price_per_lb\": 4}]'::jsonb"), p_valid_from='2020-01-01')
    f('lg_create_service_fee', acteur=admin, p_code='FRAIS', p_name='Frais de service', p_amount=10, p_currency='USD', p_valid_from='2020-01-01')

    # ====================================================================== A. la parité avec l'ancien schéma
    par = {r.split('|')[0]: r.split('|')[1:] for r in L(
        "select c.description || '|' || p.verdict || '|' || p.legacy_total || '|' || coalesce(p.core_total::text, '-') from logistics.legacy_finance_parity() p "
        "join public.factures f on f.id = p.legacy_invoice_id join public.colis c on c.id = f.colis_id where c.description like 'fi-%'")}
    ok(par['fi-tarif'][:3] == ['EQUAL', '27.50', '27.50'], '[%s] A : poids × tarif + 10 $ : même montant dans les deux moteurs (%s)' % (lieu, par['fi-tarif']))
    ok(par['fi-forfait'][:3] == ['EQUAL', '35.00', '35.00'], '[%s] A : PRIX SAISI à la main + 10 $ : même montant (le noyau connaît maintenant le forfait)' % lieu)
    ok(par['fi-sans-tarif'][0] == 'ZERO_RATE', '[%s] A : colis sans tarif : écart EXPLIQUÉ (l\'ancien schéma facture 0, le noyau la grille)' % lieu)
    ok(par['fi-paye'][0] == 'PARCEL_CHANGED' and par['fi-paye'][1] == '30.00', '[%s] A : facture payée puis colis modifié : écart EXPLIQUÉ, la facture reste figée' % lieu)
    groupee = q("select p.verdict || '|' || p.legacy_total || '|' || p.core_total from logistics.legacy_finance_parity() p join public.factures f on f.id = p.legacy_invoice_id "
                "where f.groupee and f.lignes @> '[{\"colis_id\": \"%s\"}]'" % g1)
    ok(groupee == 'EQUAL|33.00|33.00', '[%s] A : facture GROUPÉE (deux colis, frais une seule fois) : même montant (%s)' % (lieu, groupee))
    verdicts = dict(r.split('|') for r in L("select verdict || '|' || count(*) from logistics.legacy_finance_parity() group by verdict"))
    ok('UNEXPLAINED' not in verdicts and 'NO_PRICING' not in verdicts and 'SERVICE_FEE' not in verdicts,
       '[%s] A : sur TOUTES les factures héritées, aucun écart inexpliqué : %s' % (lieu, verdicts))

    # ====================================================================== B. les prestataires, sans secret
    fr('lg_configure_payment_provider', 'LG003', 'un comptable active un prestataire', p_code='CARD', p_active=True)
    fr('lg_configure_payment_provider', 'AUCUN secret', 'une clé secrète dans la configuration publique', acteur=admin, p_code='CARD', p_public_config={'checkout': {'secret_key': 'sk_live_x'}})
    code, t = cl.run(B, "update logistics.payment_provider set public_config = '{\"webhook_secret\": \"x\"}' where code = 'CARD'", expect_error=True)
    ok(code != 0 and 'check' in t.lower(), '[%s] B : même en écriture directe, la base refuse un secret' % lieu)
    p = f('lg_configure_payment_provider', acteur=admin, p_code='CARD', p_active=True, p_environment='test', p_public_config={'checkout_url': 'https://paiement.exemple.test'})
    ok(p['active'] is True and 'credentials_env' not in p, '[%s] B : carte Visa / Mastercard activée (test), sans référence de secret dans la réponse' % lieu)
    vus = f('lg_payment_providers', acteur=ca, p_currency='USD', p_country='HT')
    ok([x['code'] for x in vus] == ['CARD'] and all('secret' not in json.dumps(x).lower() for x in vus), '[%s] B : le client ne voit que les prestataires actifs, sans secret' % lieu)
    ok(q("select string_agg(code || ':' || active, ',' order by code) from logistics.payment_provider") == 'AZUL:false,CARD:true,MONCASH:false,NATCASH:false',
       '[%s] B : Azul, MonCash, NatCash prévus, éteints' % lieu)

    # ====================================================================== E1. facture groupée en une transaction
    n_p = [0]

    def colis_noyau(poids=5):
        n_p[0] += 1
        return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source, "
                 "weight_lb, description) values ('%s', 'SES-96%08d', 'jeton-f%d', '%s', 'HT', 'air', 'CREATED', 'core', 'native', %s, 'colis %d') returning id"
                 % (org, n_p[0], n_p[0], custa, poids, n_p[0]))
    p1, p2, p3 = colis_noyau(), colis_noyau(), colis_noyau()
    n_q, n_i = q('select count(*) from logistics.quote'), q('select count(*) from logistics.invoice')
    g = f('lg_create_grouped_invoice', p_customer=custa, p_currency='USD', p_parcel_ids=[p1, p2], p_idempotency_key='grp-1')
    ok(g['status'] == 'ISSUED' and float(g['total']) == 50 and g['grouped'] is True and g['number'].startswith('INV-'),
       '[%s] E : facture GROUPÉE émise d\'un coup : 2 × 20 $ + 10 $ de frais UNE fois = 50 $' % lieu)
    ok(f('lg_create_grouped_invoice', p_customer=custa, p_currency='USD', p_parcel_ids=[p1, p2], p_idempotency_key='grp-1')['invoice_id'] == g['invoice_id'],
       '[%s] E : rejouée avec la même clé : la même facture' % lieu)
    n_q2, n_i2 = q('select count(*) from logistics.quote'), q('select count(*) from logistics.invoice')
    fr('lg_create_grouped_invoice', 'déjà facturé', 'grouper un colis déjà facturé', p_customer=custa, p_currency='USD', p_parcel_ids=[p3, p1])
    ok(q('select count(*) from logistics.quote') == n_q2 and q('select count(*) from logistics.invoice') == n_i2 and int(n_q2) == int(n_q) + 1,
       '[%s] E : refusée : RIEN n\'est créé (ni devis, ni brouillon) — une seule transaction' % lieu)
    inv1, num1 = g['invoice_id'], g['number']

    # ====================================================================== C. la demande de paiement et les webhooks
    fr('lg_my_create_payment_intent', 'introuvable', 'payer la facture d\'un autre client', acteur=cb, p_invoice_number=num1, p_provider='CARD')
    fr('lg_my_create_payment_intent', 'indisponible', 'payer par un prestataire éteint', acteur=ca, p_invoice_number=num1, p_provider='AZUL')
    it = f('lg_my_create_payment_intent', acteur=ca, p_invoice_number=num1, p_provider='CARD', p_idempotency_key='cli-1')
    ok(float(it['amount']) == 50 and it['currency'] == 'USD' and it['status'] == 'CREATED' and 'secret' not in json.dumps(it).lower(),
       '[%s] C : demande de paiement : le montant est le SOLDE calculé par la base (50 $), sans secret' % lieu)
    ok(f('lg_my_create_payment_intent', acteur=ca, p_invoice_number=num1, p_provider='CARD', p_idempotency_key='cli-1')['intent_id'] == it['intent_id'], '[%s] C : demande rejouée : la même' % lieu)
    for role, claims in (('authenticated', ca), ('authenticated', admin), ('anon', None)):
        code, t = cl.run(B, appel('ses_payment_event', p_provider='CARD', p_event_key='x', p_external_id='x', p_amount=1, p_currency='USD', p_status='SUCCEEDED', p_verified=True),
                         role=role, claims=claims, expect_error=True)
        ok(code != 0 and '42501' in t, '[%s] C : un %s ne peut PAS déclarer un paiement (porte du serveur seulement)' % (lieu, 'visiteur' if role == 'anon' else 'compte connecté'))
    a = srv('ses_payment_attach', p_intent_id=it['intent_id'], p_provider='CARD', p_external_id='ord_1')
    ok(a['status'] == 'PENDING', '[%s] C : le serveur rattache la référence du prestataire' % lieu)
    ev = lambda key, ext, amount, status='SUCCEEDED', verified=True, cur='USD': srv('ses_payment_event', p_provider='CARD', p_event_key=key, p_external_id=ext, p_amount=amount,   # noqa: E731
                                                                                  p_currency=cur, p_status=status, p_verified=verified, p_raw_reference='sha256:essai')
    r = ev('evt_faux', 'ord_1', 50, verified=False)
    ok(r['outcome'] == 'REJECTED_UNVERIFIED' and q("select status from logistics.invoice where id = '%s'" % inv1) == 'ISSUED', '[%s] C : signature NON vérifiée : journalisé, rien d\'appliqué' % lieu)
    r = ev('evt_49', 'ord_1', 49)
    ok(r['outcome'] == 'MISMATCH' and q("select paid_amount from logistics.invoice where id = '%s'" % inv1) == '0.00', '[%s] C : montant différent (49 au lieu de 50) : rien d\'appliqué' % lieu)
    r = ev('evt_ok', 'ord_1', 50)
    ok(r['outcome'] == 'APPLIED' and q("select status || '|' || paid_amount from logistics.invoice where id = '%s'" % inv1) == 'PAID|50.00', '[%s] C : vérifié et juste : facture SOLDÉE' % lieu)
    pay = q("select provider_code || '|' || external_id || '|' || method || '|' || customer_id from logistics.payment where invoice_id = '%s'" % inv1)
    ok(pay == 'CARD|ord_1|CARD|%s' % custa, '[%s] C : le paiement est rattaché au prestataire, à sa référence, au client, à la facture' % lieu)
    r2 = ev('evt_ok', 'ord_1', 50)
    ok(r2['replayed'] is True and r2['outcome'] == 'APPLIED' and q("select count(*) from logistics.payment where invoice_id = '%s'" % inv1) == '1', '[%s] C : le même événement rejoué : rien ne se refait' % lieu)
    ok(ev('evt_ok_bis', 'ord_1', 50)['outcome'] == 'ALREADY_PAID' and q("select count(*) from logistics.payment where invoice_id = '%s'" % inv1) == '1',
       '[%s] C : un second « réussi » pour la même transaction : déjà payé, pas de double paiement' % lieu)
    ok(ev('evt_inconnu', 'ord_inconnu', 12)['outcome'] == 'NO_INTENT', '[%s] C : une référence que rien ne porte : mise de côté' % lieu)
    ok(f('lg_my_payment_intent', acteur=ca, p_number=it['number'])['status'] == 'SUCCEEDED', '[%s] C : le client voit sa demande payée' % lieu)
    ok(q("select count(*) from logistics.audit_log where action = 'payment.record' and after ->> 'paid_amount' = '50.00' and before ->> 'paid_amount' = '0.00'") == '1',
       '[%s] C : paiement audité : avant 0, après 50' % lieu)
    # une seconde facture : échec chez le prestataire, puis encaissement au guichet, puis le prestataire confirme quand même
    i2 = f('lg_invoice_from_quote', p_quote=f('lg_create_quote', p_customer=custa, p_currency='USD', p_items=R("jsonb_build_array(jsonb_build_object('parcel_id', '%s'::uuid))" % p3))['quote_id'], p_issue=True)
    num2 = i2['number']
    it2 = f('lg_my_create_payment_intent', acteur=ca, p_invoice_number=num2, p_provider='CARD')
    srv('ses_payment_attach', p_intent_id=it2['intent_id'], p_provider='CARD', p_external_id='ord_2')
    ok(ev('evt_2_echec', 'ord_2', 30, status='FAILED')['outcome'] == 'STATUS_UPDATED' and f('lg_my_payment_intent', acteur=ca, p_number=it2['number'])['status'] == 'FAILED',
       '[%s] C : refus de la carte : la demande échoue, sans argent' % lieu)
    it3 = f('lg_my_create_payment_intent', acteur=ca, p_invoice_number=num2, p_provider='CARD')
    srv('ses_payment_attach', p_intent_id=it3['intent_id'], p_provider='CARD', p_external_id='ord_3')
    f('lg_record_payment', p_invoice=i2['invoice_id'], p_amount=30, p_method='CASH', p_reference='guichet')
    ok(ev('evt_3_ok', 'ord_3', 30)['outcome'] == 'UNAPPLIED' and q("select paid_amount from logistics.invoice where id = '%s'" % i2['invoice_id']) == '30.00',
       '[%s] C : argent arrivé sur une facture déjà soldée au guichet : NON imputé, mis de côté' % lieu)

    # ====================================================================== D. la réconciliation
    for ext, mt in (('ord_1', 50), ('ord_9', 99)):
        srv('ses_payment_settlement', p_provider='CARD', p_external_id=ext, p_amount=mt, p_currency='USD', p_settled_on=R('current_date'), p_fee_amount=1.5, p_batch_ref='RELEVE-1')
    ok(srv('ses_payment_settlement', p_provider='CARD', p_external_id='ord_1', p_amount=50, p_currency='USD', p_settled_on=R('current_date'))['replayed'] is True, '[%s] D : relevé rejoué : ignoré' % lieu)
    rec = L("select problem || '|' || blocking from logistics.payment_reconciliation() order by 1")
    for attendu in ('event_mismatch|true', 'event_no_intent|true', 'event_unapplied|true', 'settlement_without_payment|true', 'event_unverified|false'):
        ok(attendu in rec, '[%s] D : réconciliation : %s (vu : %s)' % (lieu, attendu, rec))
    ok(not any(x.startswith('payment_without_event') or x.startswith('settlement_amount_mismatch') for x in rec), '[%s] D : le paiement en ligne est porté par son événement et par le relevé' % lieu)

    # ====================================================================== F1. la bascule refusée
    rap = f('lg_finance_cutover_report', acteur=admin)
    ok(rap['ready'] is False and rap['payments']['blocking'] >= 4 and rap['mode'] == 'legacy', '[%s] F : rapport de bascule : PAS prêt (%s écarts de paiement bloquants)' % (lieu, rap['payments']['blocking']))
    fr('lg_set_finance_mode', 'LG010', 'basculer avec une réconciliation sale', acteur=admin, p_mode='core', p_reason='essai')
    fr('lg_finance_cutover_report', 'LG003', 'un comptable lit le rapport de bascule (direction seulement)')

    # ====================================================================== E2. corrections, et rien ne se détruit
    fr('lg_issue_adjustment', 'LG003', 'un comptable ajuste une facture', p_invoice=inv1, p_net_amount=5, p_reason='emballage')
    adj = f('lg_issue_adjustment', acteur=admin, p_invoice=inv1, p_net_amount=5, p_reason='Emballage renforcé oublié')
    ok(adj['status'] == 'ISSUED' and float(adj['total']) == 5 and adj['adjustment_of'] == num1 and
       q("select kind || '|' || (corrects_invoice_id = '%s')::text from logistics.invoice where id = '%s'" % (inv1, adj['invoice_id'])) == 'ADJUSTMENT|true',
       '[%s] E : AJUSTEMENT : facture complémentaire émise, liée à la facture corrigée' % lieu)
    cr = f('lg_issue_credit_note', acteur=admin, p_invoice=i2['invoice_id'], p_amount=10, p_reason='Geste commercial')
    pid = q("select id from logistics.payment where invoice_id = '%s'" % i2['invoice_id'])
    rf = f('lg_refund_payment', acteur=admin, p_payment=pid, p_amount=10, p_reason='Trop-perçu après l\'avoir', p_method='CASH')
    ok(cr['number'].startswith('CRN-') and rf['number'].startswith('REF-'), '[%s] E : avoir puis remboursement' % lieu)
    for act in ('invoice.create', 'invoice.transition', 'payment.record', 'invoice.credit', 'payment.refund', 'invoice.adjust', 'provider.configure', 'payment_intent.create'):
        ok(q("select count(*) from logistics.audit_log where action = '%s'" % act) != '0', '[%s] E : audité : %s' % (lieu, act))
    ok(q("select count(*) from logistics.audit_log where action in ('invoice.credit', 'payment.refund') and before is not null and after is not null and actor_user_id = '%s'" % admin) == '2',
       '[%s] E : avoir et remboursement : qui, avant, après' % lieu)
    for sql, msg in (("delete from logistics.invoice where id = '%s'" % inv1, 'une facture émise'), ("delete from logistics.payment where invoice_id = '%s'" % inv1, 'un paiement'),
                     ("update logistics.invoice set total = 1 where id = '%s'" % inv1, 'le montant d\'une facture émise'),
                     ("delete from logistics.payment_event where event_key = 'evt_ok'", 'un événement de paiement'),
                     ("update logistics.payment_event set outcome = 'APPLIED' where event_key = 'evt_49'", 'le résultat d\'un événement traité'),
                     ("update logistics.payment_intent set amount = 1 where id = '%s'" % it['intent_id'], 'le montant d\'une demande')):
        code, t = cl.run(B, sql, expect_error=True)
        ok(code != 0, '[%s] E : jamais modifié ni détruit : %s' % (lieu, msg))
    ok(L('select problem from logistics.reconcile_finance()') == [], '[%s] E : le moteur est cohérent avec lui-même (factures, lignes, paiements, avoirs, revenus)' % lieu)

    # ====================================================================== F2. l'examen des écarts, puis la bascule
    for evid in L("select id from logistics.payment_event where outcome in ('MISMATCH', 'UNAPPLIED') or (outcome = 'NO_INTENT' and status = 'SUCCEEDED')"):
        fr('lg_review_payment_event', 'LG003', 'un comptable examine un écart', p_event_id=int(evid), p_note='x') if evid == L("select min(id)::text from logistics.payment_event where outcome = 'MISMATCH'")[0] else None
        f('lg_review_payment_event', acteur=admin, p_event_id=int(evid), p_note='Examiné : remboursé chez le prestataire, ou référence d\'essai')
    for lid in L("select id from logistics.provider_settlement_line where external_id = 'ord_9'"):
        f('lg_review_settlement_line', acteur=admin, p_line_id=int(lid), p_note='Versement d\'essai, contesté auprès du prestataire')
    for leg in L("select p.legacy_invoice_id from logistics.legacy_finance_parity() p where p.verdict in ('NO_PARCEL', 'UNEXPLAINED', 'NO_PRICING', 'SERVICE_FEE', 'CURRENCY')"):
        f('lg_review_legacy_parity', acteur=admin, p_legacy_invoice_id=leg, p_note='Facture héritée examinée : reste telle quelle dans l\'ancien schéma')
    rap = f('lg_finance_cutover_report', acteur=admin)
    ok(rap['ready'] is True and rap['payments']['blocking'] == 0 and rap['parity_blocking'] == 0 and rap['core']['problems'] == 0,
       '[%s] F : après examen tracé de chaque écart : PRÊT (%s)' % (lieu, {k: rap[k] for k in ('parity_blocking', 'copy_differences')}))
    ok(rap['payments']['informative'] >= 1, '[%s] F : les informations restent visibles (événement non vérifié)' % lieu)
    fr('lg_set_finance_mode', 'motif', 'basculer sans motif', acteur=admin, p_mode='core', p_reason=' ')
    ok(f('lg_set_finance_mode', acteur=admin, p_mode='core', p_reason='Réconciliation propre, validée par la direction')['mode'] == 'core', '[%s] F : BASCULE vers le noyau acceptée' % lieu)
    ok(f('lg_set_finance_mode', acteur=admin, p_mode='legacy', p_reason='Retour arrière d\'essai')['mode'] == 'legacy', '[%s] F : retour à l\'ancien schéma, toujours possible' % lieu)
    ok(q("select count(*) from logistics.audit_log where action = 'finance.mode'") == '2', '[%s] F : chaque bascule auditée' % lieu)


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
        n = '|'.join(q("select count(*) from logistics.%s" % t) for t in ('event_type', 'payment_provider', 'finance_setting'))
        cl.run('prod', P.lire_sql('outils/logistique/018-finance-professionnelle.sql'))
        ok('|'.join(q("select count(*) from logistics.%s" % t) for t in ('event_type', 'payment_provider', 'finance_setting')) == n, '018 rejouée : rien en double')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and "
             "(has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))") == '0',
           'aucune fonction du noyau n\'est ouverte à anon ou authenticated')
        serveur = cl.lignes('prod', "select p.proname || ':' || has_function_privilege('anon', p.oid, 'execute') || has_function_privilege('authenticated', p.oid, 'execute') || "
                                    "has_function_privilege('service_role', p.oid, 'execute') from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname like 'ses_payment_%' order by 1")
        ok(serveur == ['ses_payment_attach:falsefalsetrue', 'ses_payment_event:falsefalsetrue', 'ses_payment_settlement:falsefalsetrue'], 'les portes du serveur : service_role seulement (%s)' % serveur)
        ok(q("select count(*) from information_schema.role_table_grants where table_schema = 'logistics' and grantee in ('anon', 'authenticated', 'PUBLIC')") == '0', 'aucun droit direct sur les tables')
        ok(q("select count(*) from information_schema.columns where table_schema = 'logistics' and table_name = 'payment_provider' and column_name ~ 'secret_(key|value)|password|private'") == '0',
           'aucune colonne de secret dans la table des prestataires')
        parcours(cl, 'prod', 'réplique')

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

        print('PASS finance professionnelle (phase 6) : %d vérifications — sur la réplique ET la préproduction : parité avec l\'ancienne facturation '
              '(tarif, prix saisi, groupée, écarts classés), prestataires sans secret, webhooks idempotents vérifiés journalisés (serveur seul), '
              'réconciliation avec les relevés, ajustement, facture groupée atomique, rien ne se détruit, audit avant/après, bascule gardée '
              '(PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC finance professionnelle (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
