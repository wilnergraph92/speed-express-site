#!/usr/bin/env python3
"""Noyau logistique, phase 11 : l'API du portail client — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-portail-essai.py

Jamais la production. Ce qu'on éprouve : (1) chaque fonction que le client appelle rend exactement ce qu'elle doit, calculé ICI par un
second chemin ; (2) un client ne voit JAMAIS ce qui est à un autre ni ce qui est interne au personnel (la forme complète de chaque réponse
est figée : une clé de plus fait échouer le test) ; (3) un client ne peut RIEN modifier d'important : toutes les fonctions du personnel sont
appelées une à une par un client et doivent le refuser ; (4) les plafonds, la reprise sur double envoi et les gardes de la base."""
import json
import os
import re
import sys
from decimal import Decimal as D

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


class R(str):
    """Fragment SQL brut."""


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
    if isinstance(v, (int, float, D)):
        return str(v)
    if isinstance(v, (list, tuple)):
        if not v:
            return "'{}'"
        if all(isinstance(x, int) and not isinstance(x, bool) for x in v):
            return "array[%s]::bigint[]" % ', '.join(str(x) for x in v)
        return "array[%s]::%s[]" % (', '.join(val(x) for x in v), 'uuid' if re.match(r'^[0-9a-f-]{36}$', str(v[0])) else 'text')
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items()))


def cles(x, chemin=''):
    """Toutes les clés d'une réponse JSON, avec leur chemin (les tableaux comptent pour « [] »)."""
    sortie = set()
    if isinstance(x, dict):
        for k, v in x.items():
            sortie.add(chemin + '.' + k)
            sortie |= cles(v, chemin + '.' + k)
    elif isinstance(x, list):
        for v in x:
            sortie |= cles(v, chemin + '[]')
    return sortie


def texte(x):
    return json.dumps(x, ensure_ascii=False, default=str)


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        P.monter_historique(cl, B)
        for f_ in ('001-modele-de-domaine', '002-retroremplissage', '003-machine-d-etats', '004-entrepot', '005-transport-douane', '006-dernier-kilometre', '007-finance'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f_))
        # Des chauffeurs (équipe, sans aucun droit) : comptes ajoutés AVANT le rattrapage.
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) "
          "select '00000000-0000-0000-0000-000000000000', ('00000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid, 'authenticated', 'authenticated', "
          "'chauffeur' || i || '@essai.test', '$2a$10$fictif', now(), jsonb_build_object('nom_complet', 'Chauffeur ' || i, 'pays', 'Haïti', 'ville', 'Delmas', 'adresse', 'x', 'telephone', '+509 3000', 'langue', 'fr') "
          "from generate_series(21, 21) i")
        q("update public.clients set role = 'employe', droits = '{}' where email = 'chauffeur21@essai.test'")
        avant_legacy = P.empreintes_historiques(cl, B)
        cl.run(B, P.lire_sql('outils/logistique/008-portail-client.sql'))
        compte = lambda: tuple(q('select count(*) from logistics.%s' % t) for t in ('event_type',))   # noqa: E731
        c1 = compte()
        cl.run(B, P.lire_sql('outils/logistique/008-portail-client.sql'))
        ok(c1 == compte(), '008 rejouée : aucune ligne en double')
        ok(avant_legacy == P.empreintes_historiques(cl, B), 'les anciennes tables n\'ont pas bougé d\'un octet')
        q('select logistics.backfill_from_legacy()')
        ok(q("select count(*) from logistics.reconcile_with_legacy()") == '0', 'la réconciliation avec l\'ancien schéma est à 0 écart')

        uid = lambda n: q("select id from public.clients where email = 'client%d@essai.test'" % n)   # noqa: E731
        admin, gerant, op, ua, ub, uc = uid(1), uid(2), uid(3), uid(9), uid(10), uid(11)
        drv_u = q("select id from public.clients where email = 'chauffeur21@essai.test'")
        cid = lambda u: q("select id from logistics.customer where auth_user_id = '%s'" % u)   # noqa: E731
        ca, cb, cc = cid(ua), cid(ub), cid(uc)
        org = q('select id from logistics.organization')

        def f(nom, acteur, **kw):
            code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
            return json.loads(sortie, parse_float=D) if sortie.startswith(('{', '[')) else sortie

        def fr(nom, etat, msg, acteur, **kw):
            code, texte_ = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
            ok(code != 0 and etat in texte_, '%s : attendu %s, obtenu : %s' % (msg, etat, texte_[-220:].replace('\n', ' ')))

        def refuse(sql, etat, msg, **kw):
            code, texte_ = cl.run(B, sql, expect_error=True, **kw)
            ok(code != 0 and etat in texte_, '%s : attendu %s, obtenu : %s' % (msg, etat, texte_[-220:].replace('\n', ' ')))

        # ============================================================== A. le décor : branches, entrepôts, colis du noyau, expédition, livraison, factures
        q("insert into logistics.branch (organization_id, code, name, kind, country, city) values ('%s', 'MIA', 'Miami', 'office', 'US', 'Miami'), ('%s', 'PAP', 'Hub Port-au-Prince', 'hub', 'HT', 'Port-au-Prince')" % (org, org))
        mia, pap = q("select id from logistics.branch where code = 'MIA'"), q("select id from logistics.branch where code = 'PAP'")
        q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'MIA-1', 'Entrepôt Miami'), ('%s', 'PAP-1', 'Entrepôt hub')" % (mia, pap))
        wmia, wpap = q("select id from logistics.warehouse where code = 'MIA-1'"), q("select id from logistics.warehouse where code = 'PAP-1'")
        q("insert into logistics.warehouse_location (warehouse_id, code, kind) values ('%s', 'A-01-SECRET', 'storage')" % wmia)
        loc = q("select id from logistics.warehouse_location where code = 'A-01-SECRET'")
        q("insert into logistics.transport (mode, carrier, reference, planned_arrival_at) values ('air', 'Compagnie fictive', 'XX123', now() + interval '2 days')")
        vol = q("select id from logistics.transport where reference = 'XX123'")
        n_p = [0]

        def nat(cust, statut='CREATED', poids=4, desc='colis du noyau'):
            n_p[0] += 1
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, destination_city, service_mode, status, status_authority, source, weight_lb, declared_value, description, recipient_name, delivery_address) "
                     "values ('%s', 'N-%03d', 'tok%d', '%s', 'HT', 'Pétion-Ville', 'air', '%s', 'core', 'legacy_backfill', %s, 100, '%s', 'Destinataire %d', '12 rue des Fleurs') returning id" % (org, n_p[0], n_p[0], cust, statut, poids, desc, n_p[0]))
        trk = lambda pid: q("select tracking_number from logistics.parcel where id = '%s'" % pid)   # noqa: E731

        def tr(pid, to, **kw):
            args = dict(p_parcel_id=pid, p_to_status=to)
            args.update(kw)
            return f('lg_transition_parcel', admin, **args)

        a1 = nat(ca, poids=4, desc='bijoux fragiles pour Marie')
        tr(a1, 'RECEIVED', p_warehouse_id=wmia, p_location_text='QUAI-INTERNE-3'); tr(a1, 'VERIFIED', p_warehouse_id=wmia, p_location_text='ZONE-CONTROLE-9')
        tr(a1, 'STORED', p_warehouse_id=wmia, p_location_id=loc, p_location_text='A-01-SECRET'); tr(a1, 'CONSOLIDATION_PENDING')
        a2, a3 = nat(ca, 'CONSOLIDATION_PENDING', 6), nat(ca, 'CONSOLIDATION_PENDING', 7)
        b1, b2 = nat(cb, 'CONSOLIDATION_PENDING', 8, 'colis secret de B'), nat(cb, 'CONSOLIDATION_PENDING', 9)
        cons = f('lg_open_consolidation', admin, p_code='CONS-001', p_warehouse_id=wmia, p_destination_country='HT', p_mode='air')['consolidation_id']
        for p in (a1, a2, a3, b1):
            f('lg_add_parcel_to_consolidation', admin, p_consolidation_id=cons, p_parcel_id=p)
        f('lg_close_consolidation', admin, p_consolidation_id=cons)
        a5 = nat(ca, 'CONSOLIDATION_PENDING', 5)
        cons_open = f('lg_open_consolidation', admin, p_code='CONS-002', p_warehouse_id=wmia, p_destination_country='HT', p_mode='air')['consolidation_id']
        f('lg_add_parcel_to_consolidation', admin, p_consolidation_id=cons_open, p_parcel_id=a5)
        sh = f('lg_create_shipment', admin, p_code='SHP-001', p_mode='air', p_origin_branch=mia, p_destination_branch=pap, p_consolidation_ids=[cons], p_parcel_ids=[b2])['shipment_id']
        f('lg_generate_manifest', admin, p_shipment_id=sh); f('lg_mark_shipment_ready', admin, p_shipment_id=sh)
        a6 = nat(ca, 'CONSOLIDATION_PENDING', 2, 'colis dans une expédition en brouillon')
        sh_draft = f('lg_create_shipment', admin, p_code='SHP-DRAFT', p_mode='air', p_origin_branch=mia, p_destination_branch=pap, p_consolidation_ids=[], p_parcel_ids=[a6])['shipment_id']
        f('lg_dispatch_shipment', admin, p_shipment_id=sh, p_transport_id=vol, p_idempotency_key='d1'); f('lg_mark_shipment_in_transit', admin, p_shipment_id=sh)
        f('lg_arrive_shipment', admin, p_shipment_id=sh)
        f('lg_start_customs', admin, p_shipment_id=sh, p_reference='DEC-1', p_broker='Courtier')
        f('lg_clear_customs', admin, p_shipment_id=sh)
        f('lg_receive_at_hub', admin, p_shipment_id=sh, p_hub_warehouse_id=wpap)
        a4 = nat(ca, 'CONSOLIDATION_PENDING', 3, 'colis retenu')
        # a4 : mis en attente avec un motif INTERNE que le client ne doit jamais lire
        q("update logistics.parcel set status = 'STORED' where false")
        tr(a4, 'ON_HOLD', p_reason='contrôle douanier : soupçon de contrefaçon, dossier 4411')
        for _ in range(6):
            nat(ca, 'AT_DESTINATION_HUB', 2, 'colis du plafond')
        # --- la livraison de a1, de bout en bout, avec preuve
        f('lg_create_zone', admin, p_code='PV', p_name='Pétion-Ville', p_country='HT')
        veh = f('lg_create_vehicle', admin, p_plate='AA-100', p_kind='VAN', p_capacity_lb=500)
        drv = f('lg_create_driver', admin, p_user_id=drv_u, p_full_name='Chauffeur Un', p_vehicle_id=veh)
        dl = f('lg_create_delivery', admin, p_parcel_ids=[a1], p_hub_branch=pap, p_scheduled_for=R("current_date"), p_recipient_name='Marie Joseph', p_recipient_phone='+509 3111 1111',
               p_address='12 rue des Fleurs, Pétion-Ville', p_otp_required=True)
        f('lg_assign_task', admin, p_task_id=dl['task_id'], p_driver_id=drv, p_force=True, p_reason='essai')
        f('lg_accept_task', drv_u, p_task_id=dl['task_id']); f('lg_start_task', drv_u, p_task_id=dl['task_id'])
        f('lg_issue_delivery_otp', admin, p_task_id=dl['task_id'])
        otp = q("select payload->>'code' from logistics.notification where template = 'DeliveryOtp' order by id desc limit 1")
        f('lg_complete_delivery', drv_u, p_task_id=dl['task_id'], p_recipient_name='Marie Joseph', p_latitude=18.54, p_longitude=-72.33, p_signature_path='pod/%s/s.png' % dl['task_id'], p_otp=otp)
        # a2 reste au hub ; une deuxième livraison est en cours de planification pour a3 (non démarrée)
        dl3 = f('lg_create_delivery', admin, p_parcel_ids=[a3], p_hub_branch=pap, p_scheduled_for=R("current_date + 1"), p_recipient_name='Jean', p_address='5 rue du Code, Delmas')
        # --- la facturation
        zht = f('lg_create_pricing_zone', admin, p_code='Z-HT', p_name='Haïti', p_country='HT')
        f('lg_create_rate_card', admin, p_code='AIR-HT', p_name='Air Haïti', p_mode='air', p_zone=zht, p_currency='USD',
          p_brackets=R("'[{\"min_lb\": 0, \"price_per_lb\": 3.00, \"flat_fee\": 0, \"min_charge\": 5}]'::jsonb"))
        quote = lambda cust, items, who=admin: f('lg_create_quote', who, p_customer=cust, p_currency='USD', p_items=R("'%s'::jsonb" % json.dumps(items)))   # noqa: E731
        qa = quote(ca, [dict(parcel_id=a1)])
        inv_a = f('lg_invoice_from_quote', admin, p_quote=qa['quote_id'], p_issue=True)['invoice_id']
        pay = f('lg_record_payment', admin, p_invoice=inv_a, p_amount=22, p_method='CASH')
        f('lg_issue_credit_note', admin, p_invoice=inv_a, p_amount=5, p_reason='colis arrivé abîmé : remise de 5')
        f('lg_refund_payment', admin, p_payment=pay['payment_id'], p_amount=3, p_reason='geste commercial interne : client mécontent', p_method='CASH')
        qa2 = quote(ca, [dict(parcel_id=a2)])
        inv_draft = f('lg_invoice_from_quote', admin, p_quote=qa2['quote_id'], p_issue=False)['invoice_id']
        qa3 = quote(ca, [dict(parcel_id=a3)]); f('lg_cancel_quote', admin, p_quote=qa3['quote_id'], p_reason='annulé')
        qa4 = quote(ca, [dict(parcel_id=a5)])
        qb = quote(cb, [dict(parcel_id=b1)])
        inv_b = f('lg_invoice_from_quote', admin, p_quote=qb['quote_id'], p_issue=True)['invoice_id']
        f('lg_record_payment', admin, p_invoice=inv_b, p_amount=7, p_method='CARD')
        # --- notifications du portail et support (insérées comme le ferait le moteur de la phase 13)
        for cust, tpl, payload, lu in ((ca, 'ParcelReceived', {'tracking_number': 'N-001', 'stage': 'received', 'internal_key': 'SECRET', 'recipient_phone': '+509 0000'}, False),
                                       (ca, 'Delivered', {'tracking_number': 'N-001', 'stage': 'delivered'}, False), (ca, 'ShipmentArrived', {'shipment_code': 'SHP-001'}, True),
                                       (cb, 'ParcelReceived', {'tracking_number': 'N-004'}, False)):
            q("insert into logistics.notification (customer_id, channel, template, payload, status, read_at) values ('%s', 'in_app', '%s', '%s'::jsonb, 'SENT', %s)" % (
                cust, tpl, json.dumps(payload), 'now()' if lu else 'null'))
        q("insert into logistics.notification (customer_id, channel, template, payload, status) values ('%s', 'whatsapp', 'ParcelReceived', '{\"tracking_number\": \"N-001\"}', 'SENT')" % ca)

        # Le vocabulaire du client, écrit ICI une seconde fois pour que la base soit comparée à autre chose qu'à elle-même.
        ETAPE = {'CREATED': 'registered', 'RECEIVED': 'received', 'VERIFIED': 'received', 'STORED': 'received', 'CONSOLIDATION_PENDING': 'received', 'CONSOLIDATED': 'received',
                 'READY_FOR_EXPORT': 'received', 'IN_TRANSIT': 'in_transit', 'ARRIVED': 'customs', 'CUSTOMS_PROCESSING': 'customs', 'CUSTOMS_CLEARED': 'customs',
                 'AT_DESTINATION_HUB': 'at_hub', 'DELIVERY_ASSIGNED': 'out_for_delivery', 'OUT_FOR_DELIVERY': 'out_for_delivery', 'DELIVERED': 'delivered', 'ON_HOLD': 'on_hold',
                 'DAMAGED': 'incident', 'LOST': 'lost', 'CANCELLED': 'cancelled', 'RETURNED': 'returned'}
        ETAPE_EXP = {'DRAFT': 'preparing', 'READY': 'preparing', 'DISPATCHED': 'in_transit', 'IN_TRANSIT': 'in_transit', 'ARRIVED': 'customs', 'CUSTOMS_PROCESSING': 'customs',
                     'CUSTOMS_CLEARED': 'customs', 'AT_HUB': 'at_hub', 'CLOSED': 'closed', 'CANCELLED': 'cancelled'}

        # ============================================================== B. le vocabulaire : complet et identique
        ok(set(cl.lignes(B, "select code from logistics.parcel_status")) == set(ETAPE), 'les 20 statuts du colis sont tous connus du test')
        ok(all(q("select logistics.customer_stage('%s')" % st_) == e_ for st_, e_ in ETAPE.items()), 'chaque statut de colis a SON étape côté client, identique à la table du test')
        ok(q("select coalesce(logistics.customer_stage('INCONNU'), 'nul')") == 'nul', 'un statut inconnu ne reçoit aucune étape inventée')
        ok(set(cl.lignes(B, "select code from logistics.shipment_status")) == set(ETAPE_EXP) and all(q("select logistics.customer_shipment_stage('%s')" % st_) == e_ for st_, e_ in ETAPE_EXP.items()),
           'chaque statut d\'expédition a son étape côté client')
        ok(len(set(ETAPE.values())) == 12, 'douze étapes en tout : sept du parcours normal et cinq exceptions')

        # ============================================================== C. le tableau de bord
        dash = f('lg_my_dashboard', ua)
        ok(dash['linked'] is True and dash['in_sync'] is True, 'tableau de bord du client A : relié au noyau et à jour avec l\'ancien schéma')
        ok(dash['customer'] == {'code': q("select code from logistics.customer where id = '%s'" % ca), 'full_name': q("select full_name from logistics.customer where id = '%s'" % ca), 'language': q("select language from logistics.customer where id = '%s'" % ca)}, 'identité du client')
        statuts_a = cl.lignes(B, "select status from logistics.parcel where customer_id = '%s'" % ca)
        att = {}
        for st_ in statuts_a:
            att[ETAPE[st_]] = att.get(ETAPE[st_], 0) + 1
        ok(dash['parcels']['total'] == len(statuts_a) == 32 and dash['parcels']['by_stage'] == att, 'colis par étape : identiques à un décompte indépendant (%s)' % att)
        lignes_f = [l.split('|') for l in cl.lignes(B, "select status, total, credited_amount, paid_amount, refunded_amount, currency from logistics.invoice where customer_id = '%s'" % ca)]
        solde = {}
        impayees = 0
        for st_, tot, cre, pai, ref, cur in lignes_f:
            if st_ in ('DRAFT', 'CANCELLED'):
                continue
            b_ = (D(tot) - D(cre)) - (D(pai) - D(ref))
            solde[cur] = solde.get(cur, D(0)) + b_
            impayees += 1 if b_ > 0 else 0
        ok(dash['invoices']['unpaid'] == impayees > 0, 'factures impayées : %d, comme le décompte indépendant' % impayees)
        ok({b_['currency']: b_['balance'] for b_ in dash['invoices']['balances']} == solde, 'soldes par devise : identiques au calcul indépendant (%s)' % solde)
        ok(len(dash['deliveries']['upcoming']) == 1 and dash['deliveries']['upcoming'][0]['parcels'] == 1 and dash['deliveries']['upcoming'][0]['status'] == 'CREATED', 'une livraison à venir (celle de demain), la livrée n\'y est plus')
        ok(dash['pickups']['open'] == 0 and dash['notifications']['unread'] == 2 and dash['tickets']['open'] == 0, 'enlèvements 0, notifications non lues 2 (la lue et celle de WhatsApp ne comptent pas), tickets 0')
        ev = dash['recent_events']
        ok(0 < len(ev) <= 5 and [e_['at'] for e_ in ev] == sorted((e_['at'] for e_ in ev), reverse=True), 'derniers événements : au plus 5, du plus récent au plus ancien')
        ok(all(e_['tracking_number'] in cl.lignes(B, "select tracking_number from logistics.parcel where customer_id = '%s'" % ca) for e_ in ev), 'et seulement sur des colis de A')
        d_staff = f('lg_my_dashboard', admin)
        ok(d_staff == {'linked': False, 'in_sync': False}, 'un membre du personnel n\'a pas d\'espace client : « non relié », rien d\'autre')
        code, texte_ = cl.run(B, "select public.lg_my_dashboard()", role='anon', expect_error=True)
        ok(code != 0 and ('permission' in texte_.lower() or '42501' in texte_), 'un visiteur anonyme n\'appelle rien')
        code, texte_ = cl.run(B, "select public.lg_my_dashboard()", role='authenticated', expect_error=True)
        ok(code != 0 and '42501' in texte_, 'connecté mais sans jeton valide (aucun auth.uid()) : « connexion requise »')

        # ============================================================== D. la liste des colis
        tous = f('lg_my_parcels', ua, p_limit=200)
        ok(tous['total'] == 32 and len(tous['items']) == 32 and tous['by_stage'] == att, 'liste complète : 32 colis (20 hérités, 6 du noyau, 6 au hub), comptes par étape identiques')
        mes_numeros = set(cl.lignes(B, "select tracking_number from logistics.parcel where customer_id = '%s'" % ca))
        ok({i_['tracking_number'] for i_ in tous['items']} == mes_numeros, 'exactement les colis de A')
        ok([i_['updated_at'] for i_ in tous['items']] == sorted((i_['updated_at'] for i_ in tous['items']), reverse=True), 'du plus récemment mis à jour au plus ancien')
        pgs = [f('lg_my_parcels', ua, p_limit=10, p_offset=o_) for o_ in (0, 10, 20, 30)]
        pages = [i_['tracking_number'] for pg in pgs for i_ in pg['items']]
        ok([len(pg['items']) for pg in pgs] == [10, 10, 10, 2] and len(set(pages)) == 32 and pages == [i_['tracking_number'] for i_ in tous['items']] and pgs[0]['total'] == 32, 'pagination : 10 + 10 + 10 + 2, sans doublon ni trou, même ordre')
        ok(len(f('lg_my_parcels', ua, p_limit=0)['items']) == 1 and len(f('lg_my_parcels', ua, p_limit=-5)['items']) == 1 and len(f('lg_my_parcels', ua, p_limit=100000)['items']) == 32, 'plafonds : limite 0 ou négative → 1 ; limite énorme → plafonnée à 200')
        ok(len(f('lg_my_parcels', ua, p_offset=-3, p_limit=5)['items']) == 5, 'un décalage négatif vaut zéro')
        ok(f('lg_my_parcels', ua, p_offset=500)['items'] == [], 'au-delà de la fin : liste vide, total conservé')
        for etape in ('at_hub', 'delivered', 'on_hold', 'received', 'registered'):
            r_ = f('lg_my_parcels', ua, p_stage=etape, p_limit=200)
            ok(r_['total'] == att.get(etape, 0) and all(i_['stage'] == etape for i_ in r_['items']) and r_['by_stage'] == att, 'filtre « %s » : %d colis, tous de cette étape, les comptes par étape ne bougent pas' % (etape, att.get(etape, 0)))
        ok(f('lg_my_parcels', ua, p_stage='inexistante')['total'] == 0, 'une étape inconnue ne trouve rien (et n\'échoue pas)')
        r_ = f('lg_my_parcels', ua, p_search='n-001')
        ok(r_['total'] == 1 and r_['items'][0]['tracking_number'] == 'N-001', 'recherche par numéro, sans tenir compte de la casse')
        ok(f('lg_my_parcels', ua, p_search='fragiles')['total'] == 1 and f('lg_my_parcels', ua, p_search='BIJOUX')['total'] == 1 and f('lg_my_parcels', ua, p_search='  bijoux  ')['total'] == 1, 'recherche dans la description, sans tenir compte de la casse ni des espaces autour (la casse des lettres accentuées suit la langue de la base : non éprouvée ici)')
        ok(f('lg_my_parcels', ua, p_search='%')['total'] == 0 and f('lg_my_parcels', ua, p_search='_')['total'] == 0, 'les jokers « % » et « _ » sont des caractères, pas des motifs : aucun colis ne les contient')
        ok(f('lg_my_parcels', ua, p_search="x' or 1=1 --")['total'] == 0, 'une injection SQL ne trouve rien')
        ok(f('lg_my_parcels', ua, p_search='Destinataire 1')['total'] >= 1, 'recherche par destinataire')
        ok(f('lg_my_parcels', ua, p_search='n-001', p_stage='at_hub')['total'] == 0 and f('lg_my_parcels', ua, p_search='n-001', p_stage='delivered')['total'] == 1, 'recherche et étape se combinent')
        ok(f('lg_my_parcels', admin) == {'total': 0, 'by_stage': {}, 'items': []}, 'le personnel (non relié) obtient une liste vide')
        # --- isolation
        tb = set(cl.lignes(B, "select tracking_number from logistics.parcel where customer_id = '%s'" % cb))
        ok(not (tb & {i_['tracking_number'] for i_ in tous['items']}) and not any(t_ in texte(tous) for t_ in tb if len(t_) > 5), 'aucun numéro de colis de B dans la liste de A')
        ok(f('lg_my_parcels', ub, p_limit=200)['total'] == len(tb) and {i_['tracking_number'] for i_ in f('lg_my_parcels', ub, p_limit=200)['items']} == tb, 'B voit exactement ses colis')
        ok(f('lg_my_parcels', ua, p_search='secret de B')['total'] == 0, 'chercher le texte d\'un colis de B ne le trouve pas chez A')

        # ============================================================== E. le détail d'un colis et son suivi
        INTERDITS = ['A-01-SECRET', 'QUAI-INTERNE-3', 'ZONE-CONTROLE-9', 'chauffeur', 'client1@essai.test', 'client2@essai.test', 'client3@essai.test', 'dossier 4411', 'contrefaçon', 'actor', 'password', 'otp_hash', 'otp_salt',
                     'author_user_id', 'created_by', 'reviewed_by', 'legacy_', 'auth_user_id', 'organization_id', 'geo', 'latitude', 'longitude', 'metadata', 'correlation']
        d1 = f('lg_my_parcel', ua, p_tracking='N-001')
        ok(d1['tracking_number'] == 'N-001' and d1['stage'] == 'delivered' and d1['status'] == 'DELIVERED' and d1['description'] == 'bijoux fragiles pour Marie', 'fiche du colis N-001 : livré')
        ok(d1['place'] == 'Hub Port-au-Prince' and d1['weight_lb'] == D('4.00'), 'lieu actuel (nom de la succursale, sans « ville, ville ») et poids')
        VISIBLES = ['ParcelReceived', 'ParcelVerified', 'ParcelConsolidated', 'ParcelReadyForExport', 'ParcelInTransit', 'ParcelArrived', 'CustomsStarted', 'CustomsCleared',
                    'ParcelAtDestinationHub', 'DeliveryAssigned', 'OutForDelivery', 'Delivered']
        ok([t_['event'] for t_ in d1['timeline']] == VISIBLES, 'LE SUIVI : douze événements visibles, dans l\'ordre du parcours : %s' % [t_['event'] for t_ in d1['timeline']])
        brut = cl.lignes(B, "select event_type from logistics.tracking_event where parcel_id = '%s' order by id" % a1)
        ok(len(brut) == 14 and set(brut) - set(VISIBLES) == {'ParcelStored', 'ParcelConsolidationPending'}, 'le journal réel compte 14 événements : les deux événements internes (rangement, attente de consolidation) sont absents du suivi du client')
        ok([t_['at'] for t_ in d1['timeline']] == sorted(t_['at'] for t_ in d1['timeline']), 'du plus ancien au plus récent')
        ok([t_['stage'] for t_ in d1['timeline']] == [ETAPE[st_] for st_ in cl.lignes(B, "select to_status from logistics.tracking_event e where parcel_id = '%s' and event_type in (%s) order by id" % (a1, ','.join("'%s'" % v for v in VISIBLES)))], 'chaque événement porte l\'étape du client de son statut')
        lieux = {t_['event']: t_['place'] for t_ in d1['timeline']}
        ok(lieux['ParcelReceived'] == 'Miami' and lieux['ParcelVerified'] == 'Miami' and lieux['ParcelAtDestinationHub'] == 'Hub Port-au-Prince', 'les lieux sont des noms de succursale : « Miami » à la réception et à la vérification, « Hub Port-au-Prince » à l\'arrivée au hub : %s' % lieux)
        ok(all(v_ in ('Miami', 'Hub Port-au-Prince', None) for v_ in lieux.values()), 'et aucun autre lieu : jamais le code d\'emplacement interne')
        ok(all(set(t_) == {'at', 'event', 'status', 'stage', 'place', 'note'} for t_ in d1['timeline']) and all(t_['note'] is None for t_ in d1['timeline']), 'chaque ligne du suivi : date, événement, statut, étape, lieu, note — jamais l\'auteur ni le motif')
        ok(d1['shipment']['code'] == 'SHP-001' and d1['shipment']['stage'] == 'at_hub' and d1['shipment']['customs'] == 'cleared' and d1['shipment']['carrier'] == 'Compagnie fictive' and d1['shipment']['reference'] == 'XX123', 'l\'expédition du colis : code, étape, douane dédouanée, transporteur et référence du vol')
        ok(d1['shipment']['origin'] == 'Miami' and d1['shipment']['destination'] == 'Hub Port-au-Prince', 'de Miami au hub')
        ok(d1['shipment']['my_parcels'] == [{'tracking_number': t_, 'stage': ETAPE[q("select status from logistics.parcel where tracking_number = '%s'" % t_)]} for t_ in ('N-001', 'N-002', 'N-003')], 'l\'expédition ne montre QUE les colis de A (pas ceux de B qui voyagent avec lui)')
        ok(d1['consolidation']['code'] == 'CONS-001' and d1['consolidation']['status'] == 'CLOSED', 'sa consolidation')
        ok(d1['delivery']['stage'] == 'delivered' and d1['delivery']['otp_required'] is True and d1['delivery']['otp_issued'] is False and d1['delivery']['failure'] is None
           and d1['delivery']['proof']['recipient_name'] == 'Marie Joseph' and d1['delivery']['proof']['delivered_at'], 'la livraison : remise à Marie Joseph, preuve (nom et heure seulement), le code a été utilisé donc plus « émis »')
        ok([i_['number'] for i_ in d1['invoices']] == [q("select number from logistics.invoice where id = '%s'" % inv_a)] and d1['invoices'][0]['status'] == 'PAID' and d1['invoices'][0]['total'] == D('22.00'), 'sa facture')
        for mot in INTERDITS:
            ok(mot not in texte(d1), 'la fiche du colis ne contient jamais « %s »' % mot)
        # un colis retenu : le motif interne ne sort pas
        d4 = f('lg_my_parcel', ua, p_tracking='N-008')
        ok(d4['stage'] == 'on_hold' and [t_['event'] for t_ in d4['timeline']] == ['ParcelOnHold'] and d4['timeline'][0]['note'] is None, 'colis retenu : « en attente » est visible, le MOTIF ne l\'est pas')
        ok('contrefaçon' not in texte(d4) and '4411' not in texte(d4), 'ni le soupçon ni le numéro de dossier')
        ok(f('lg_my_parcel', ua, p_tracking='n-001')['tracking_number'] == 'N-001' and f('lg_my_parcel', ua, p_tracking='  n-001 ')['tracking_number'] == 'N-001', 'le numéro se lit sans tenir compte de la casse ni des espaces')
        d_h = f('lg_my_parcel', ua, p_tracking=q("select numero from public.colis where client_id = '%s' order by numero limit 1" % ua))
        hist = [l.split('|') for l in cl.lignes(B, "select h.statut, h.lieu, h.note from public.colis_historique h join public.colis c on c.id = h.colis_id where c.numero = '%s' order by h.cree_le, h.id" % d_h['tracking_number'])]
        ok(len(d_h['timeline']) == len(hist) > 0 and all(t_['event'] == 'ParcelStatusChanged' for t_ in d_h['timeline']), 'un colis hérité : son historique devient son suivi (%d étapes)' % len(hist))
        ok([(t_['place'] or '', t_['note'] or '') for t_ in d_h['timeline']] == [(l_[1], l_[2]) for l_ in hist], 'avec le lieu et la note de l\'ancien historique, à l\'identique')
        ok([t_['stage'] for t_ in d_h['timeline']] == [ETAPE[{'confirme': 'CREATED', 'expedie': 'IN_TRANSIT', 'disponible': 'AT_DESTINATION_HUB', 'livre': 'DELIVERED', 'action': 'ON_HOLD'}[l_[0]]] for l_ in hist], 'et l\'étape déduite du statut d\'origine')
        # isolation et erreurs identiques
        c1_, t1_ = cl.run(B, appel('lg_my_parcel', p_tracking='N-004'), role='authenticated', claims=ua, expect_error=True)
        c2_, t2_ = cl.run(B, appel('lg_my_parcel', p_tracking='ZZZ-INEXISTANT'), role='authenticated', claims=ua, expect_error=True)
        ok(c1_ != 0 and c2_ != 0 and 'LG002' in t1_ and re.sub(r'N-004|ZZZ-INEXISTANT', 'X', t1_.split('LOCATION')[0].replace(t1_.split("select public")[-1], '')) == re.sub(r'N-004|ZZZ-INEXISTANT', 'X', t2_.split('LOCATION')[0].replace(t2_.split("select public")[-1], '')),
           'le colis d\'un autre répond EXACTEMENT comme un colis qui n\'existe pas (LG002) : impossible de deviner un numéro')
        fr('lg_my_parcel', 'LG002', 'le personnel (non relié) n\'a pas de colis', admin, p_tracking='N-001')
        fr('lg_my_parcel', 'LG002', 'un numéro vide', ua, p_tracking='')
        db1 = f('lg_my_parcel', ub, p_tracking='N-004')
        ok(db1['consolidation']['code'] == 'CONS-001' and db1['shipment']['code'] == 'SHP-001' and [m_['tracking_number'] for m_ in db1['shipment']['my_parcels']] == ['N-004', 'N-005'], 'B voit sa fiche, la même expédition et SES deux colis (N-004 par la consolidation, N-005 en vrac)')
        ok(all(t_ not in texte(db1) for t_ in ('N-001', 'N-002', 'N-003')), 'et dans l\'expédition de B, aucun colis de A')

        # ============================================================== F. expéditions et consolidations
        shs = f('lg_my_shipments', ua)
        ok([x_['code'] for x_ in shs] == ['SHP-001'], 'A voit UNE expédition : celle qui porte ses colis. L\'expédition en brouillon (qui porte N-007) reste interne')
        ok(sorted(shs[0]) == sorted(d1['shipment']), 'la même forme que dans la fiche du colis')
        ok([x_['code'] for x_ in f('lg_my_shipments', ub)] == ['SHP-001'] and f('lg_my_shipments', uc) == [] and f('lg_my_shipments', admin) == [], 'B la voit aussi ; C n\'a rien ; le personnel non plus')
        cons_a = f('lg_my_consolidations', ua)
        ok(sorted(c_['code'] for c_ in cons_a) == ['CONS-001', 'CONS-002'], 'A voit deux consolidations : %s' % [c_['code'] for c_ in cons_a])
        c_cl = [c_ for c_ in cons_a if c_['code'] == 'CONS-001'][0]; c_op = [c_ for c_ in cons_a if c_['code'] == 'CONS-002'][0]
        ok(c_cl['status'] == 'CLOSED' and c_cl['my_count'] == 3 and c_cl['my_parcels'] == ['N-001', 'N-002', 'N-003'] and c_cl['shipment'] == 'SHP-001' and c_cl['origin'] == 'Miami', 'consolidation fermée : 3 colis à A (sur 4 dans la consolidation), partie dans SHP-001')
        ok(q("select count(*) from logistics.consolidation_parcel where consolidation_id = '%s' and removed_at is null" % cons) == '4' and c_cl['my_count'] == 3, 'la consolidation en compte 4 en tout : A n\'en voit que 3')
        ok(c_op['status'] == 'OPEN' and c_op['my_count'] == 1 and c_op['my_parcels'] == ['N-006'] and c_op['shipment'] is None, 'consolidation ouverte : 1 colis, pas encore d\'expédition')
        cb_ = f('lg_my_consolidations', ub)
        ok(len(cb_) == 1 and cb_[0]['my_count'] == 1 and cb_[0]['my_parcels'] == ['N-004'] and 'N-001' not in texte(cb_), 'B : un seul colis dans CONS-001, aucun colis de A')
        ok(f('lg_my_consolidations', uc) == [] and f('lg_my_consolidations', admin) == [], 'C et le personnel : rien')
        for mot in INTERDITS + ['N-004', 'N-005']:
            ok(mot not in texte(shs) + texte(cons_a), 'ni expéditions ni consolidations de A ne contiennent « %s »' % mot)

        # ============================================================== G. paiements et documents
        pays = f('lg_my_payments', ua)
        ok(len(pays['payments']) == 1 and pays['payments'][0]['amount'] == D('22.00') and pays['payments'][0]['method'] == 'CASH' and pays['payments'][0]['currency'] == 'USD'
           and pays['payments'][0]['invoice'] == q("select number from logistics.invoice where id = '%s'" % inv_a) and pays['payments'][0]['number'].startswith('PAY-'), 'un paiement de 22 USD en espèces sur sa facture')
        ok(len(pays['refunds']) == 1 and pays['refunds'][0]['amount'] == D('3.00') and 'reason' not in pays['refunds'][0] and 'mécontent' not in texte(pays), 'un remboursement de 3 USD : le MOTIF interne n\'est pas montré')
        ok(len(pays['credits']) == 1 and pays['credits'][0]['amount'] == D('5.00') and 'abîmé' in pays['credits'][0]['reason'], 'un avoir de 5 USD, avec son motif (il figure sur le document)')
        payb = f('lg_my_payments', ub)
        ok(len(payb['payments']) == 1 and payb['payments'][0]['amount'] == D('7.00') and payb['refunds'] == [] and payb['credits'] == [] and '22.00' not in texte(payb), 'B : son paiement de 7 USD, rien de A')
        ok(f('lg_my_payments', admin) == {'payments': [], 'refunds': [], 'credits': []}, 'le personnel (non relié) : rien')
        docs = f('lg_my_documents', ua)
        genres = [d_['kind'] for d_ in docs]
        n_fact = int(q("select count(*) from logistics.invoice where customer_id = '%s' and status <> 'DRAFT' and issued_at is not null" % ca))
        ok(genres.count('INVOICE') == n_fact and genres.count('CREDIT_NOTE') == 1 and genres.count('QUOTE') == 3 and genres.count('DELIVERY_RECEIPT') == 1, 'documents de A : %d factures, 1 avoir, 3 devis (l\'annulé n\'y est pas), 1 reçu de livraison' % n_fact)
        ok(q("select number from logistics.invoice where id = '%s'" % inv_draft) not in texte(docs), 'le brouillon de facture n\'est PAS un document du client')
        ok([d_['date'] for d_ in docs] == sorted((d_['date'] for d_ in docs), reverse=True), 'du plus récent au plus ancien')
        recu = [d_ for d_ in docs if d_['kind'] == 'DELIVERY_RECEIPT'][0]
        ok(recu['number'].startswith('POD-') and len(recu['number']) == 12 and recu['extra'] == {'recipient_name': 'Marie Joseph', 'parcels': ['N-001']}, 'le reçu de livraison : nom du destinataire et colis, numéro court')
        devis = [d_ for d_ in docs if d_['kind'] == 'QUOTE']
        ok(all(set(d_['extra']) == {'valid_until', 'lines'} and len(d_['extra']['lines']) >= 2 for d_ in devis) and {d_['status'] for d_ in devis} == {'INVOICED', 'OFFERED'}, 'les devis portent leurs lignes (fret, frais) et leur validité')
        avoir = [d_ for d_ in docs if d_['kind'] == 'CREDIT_NOTE'][0]
        ok(avoir['extra']['invoice'] == q("select number from logistics.invoice where id = '%s'" % inv_a) and avoir['amount'] == D('5.00'), 'l\'avoir renvoie à sa facture')
        docb = f('lg_my_documents', ub)
        ok(not any(d_['number'] in {x_['number'] for x_ in docs if x_['kind'] != 'DELIVERY_RECEIPT'} for d_ in docb if d_['kind'] != 'DELIVERY_RECEIPT'), 'les documents de B et de A ne partagent aucun numéro')
        ok(f('lg_my_documents', admin) == [], 'le personnel (non relié) : rien')
        ok(all(d_['kind'] in ('INVOICE',) for d_ in f('lg_my_documents', uc)), 'C n\'a que ses factures héritées : ni avoir, ni devis, ni reçu')
        for mot in INTERDITS + ['mécontent']:
            ok(mot not in texte(pays) + texte(docs), 'ni paiements ni documents ne contiennent « %s »' % mot)

        # Tout ce que le client NE DOIT PAS pouvoir changer, empreint une fois ici et comparée à la fin : colis, journal de suivi, factures, argent, droits.
        def noyau_critique():
            return q("select md5(concat_ws('|', "
                     "(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.parcel x), "
                     "(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.tracking_event x), "
                     "(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.invoice x), "
                     "(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.invoice_item x), "
                     "(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.payment x), "
                     "(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.refund x), "
                     "(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.credit x), "
                     "(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.revenue_entry x), "
                     "(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.app_user x), "
                     "(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.domain_event x where x.aggregate_type in ('parcel', 'shipment', 'invoice', 'payment'))))")
        fp0 = noyau_critique()
        legacy0 = P.empreintes_historiques(cl, B)

        # ============================================================== H. les adresses
        ANNEE = q("select extract(year from now())::int")
        ok(f('lg_my_addresses', ua) == [] and f('lg_my_addresses', admin) == [], 'au départ : aucune adresse')
        fr('lg_save_address', 'LG003', 'le personnel (sans profil client) n\'enregistre pas d\'adresse', admin, p_country='HT', p_address='x')
        code, texte_ = cl.run(B, appel('lg_save_address', p_country='HT', p_address='x'), role='authenticated', expect_error=True)
        ok(code != 0 and '42501' in texte_, 'sans connexion : refusé')
        ad1 = f('lg_save_address', ua, p_country='HT', p_address='  12 rue des Fleurs  ', p_city='Pétion-Ville', p_label='Maison', p_recipient_name='Marie Joseph', p_phone='+509 3111 1111', p_instructions='Portail bleu')
        ok(ad1['is_default'] is True, 'la première adresse devient l\'adresse par défaut')
        ad2 = f('lg_save_address', ua, p_country='DO', p_address='Calle El Conde 5', p_city='Saint-Domingue')
        ok(ad2['is_default'] is False, 'la deuxième ne l\'est pas')
        ad3 = f('lg_save_address', ua, p_country='US', p_address='100 Brickell Ave', p_city='Miami', p_label='Bureau', p_default=True)
        liste = f('lg_my_addresses', ua)
        ok([a_['address_id'] for a_ in liste][0] == ad3['address_id'] and sum(1 for a_ in liste if a_['is_default']) == 1 and len(liste) == 3, 'demander « par défaut » déplace le défaut : une seule adresse par défaut, elle passe en tête')
        ok(liste[-1]['address'] == '12 rue des Fleurs' or liste[1]['address'] == '12 rue des Fleurs', 'les espaces autour sont retirés')
        a1_ = [a_ for a_ in liste if a_['address_id'] == ad1['address_id']][0]
        ok(a1_['label'] == 'Maison' and a1_['recipient_name'] == 'Marie Joseph' and a1_['instructions'] == 'Portail bleu' and a1_['city'] == 'Pétion-Ville', 'tous les champs sont enregistrés')
        f('lg_save_address', ua, p_id=ad2['address_id'], p_country='DO', p_address='Calle El Conde 5', p_city='Santo Domingo', p_label='Famille')
        l2 = f('lg_my_addresses', ua)
        a2_ = [a_ for a_ in l2 if a_['address_id'] == ad2['address_id']][0]
        ok(a2_['city'] == 'Santo Domingo' and a2_['label'] == 'Famille' and [a_['is_default'] for a_ in l2].count(True) == 1 and l2[0]['address_id'] == ad3['address_id'], 'modifier une adresse ne touche pas au défaut quand on ne le demande pas')
        f('lg_save_address', ua, p_id=ad3['address_id'], p_country='US', p_address='100 Brickell Ave', p_city='Miami', p_default=False)
        ok(not any(a_['is_default'] for a_ in f('lg_my_addresses', ua)), 'on peut retirer le défaut : aucune adresse par défaut')
        f('lg_save_address', ua, p_id=ad1['address_id'], p_country='HT', p_address='12 rue des Fleurs', p_city='Pétion-Ville', p_default=True)
        for kw, msg in ((dict(p_country='FR', p_address='x'), 'pays inconnu'), (dict(p_country='HT', p_address='   '), 'adresse vide'), (dict(p_country='HT', p_address='x' * 201), 'adresse de 201 caractères'),
                        (dict(p_country='HT', p_address='x', p_label='l' * 41), 'étiquette de 41 caractères'), (dict(p_country='HT', p_address='x', p_city='c' * 81), 'ville de 81 caractères'),
                        (dict(p_country='HT', p_address='x', p_instructions='i' * 301), 'consignes de 301 caractères'), (dict(p_country='HT', p_address='x', p_phone='9' * 41), 'téléphone de 41 caractères')):
            fr('lg_save_address', 'LG005', msg, ua, **kw)
        ok(len(f('lg_my_addresses', ua)) == 3, 'les refus n\'ont rien créé')
        # l'adresse d'un autre
        adb = f('lg_save_address', ub, p_country='HT', p_address='Adresse secrète de B', p_city='Jacmel')
        fr('lg_save_address', 'LG002', 'modifier l\'adresse d\'un autre client', ua, p_id=adb['address_id'], p_country='HT', p_address='piratée')
        fr('lg_delete_address', 'LG002', 'supprimer l\'adresse d\'un autre client', ua, p_id=adb['address_id'])
        fr('lg_delete_address', 'LG002', 'supprimer une adresse qui n\'existe pas', ua, p_id=R("gen_random_uuid()"))
        ok(all('secrète' not in texte(x_) for x_ in (f('lg_my_addresses', ua),)) and f('lg_my_addresses', ub)[0]['address'] == 'Adresse secrète de B', 'l\'adresse de B est intacte et invisible de A')
        # suppression : le défaut passe à la plus récente restante
        f('lg_delete_address', ua, p_id=ad1['address_id'])
        l3 = f('lg_my_addresses', ua)
        ok(len(l3) == 2 and [a_['is_default'] for a_ in l3].count(True) == 1 and l3[0]['address_id'] == ad3['address_id'], 'supprimer le défaut : la plus récente des autres le devient')
        ok(q("select count(*) from logistics.customer_address where customer_id = '%s' and not active" % ca) == '1', 'la suppression est une désactivation : la ligne reste en base')
        fr('lg_delete_address', 'LG002', 'supprimer deux fois', ua, p_id=ad1['address_id'])
        fr('lg_save_address', 'LG002', 'modifier une adresse supprimée', ua, p_id=ad1['address_id'], p_country='HT', p_address='x')
        # plafond de 20
        for i in range(18):
            f('lg_save_address', ua, p_country='HT', p_address='Rue %d' % i)
        ok(len(f('lg_my_addresses', ua)) == 20, 'vingt adresses enregistrées')
        fr('lg_save_address', 'LG005', 'une 21e adresse', ua, p_country='HT', p_address='de trop')
        f('lg_save_address', ua, p_id=ad3['address_id'], p_country='US', p_address='100 Brickell Ave')
        ok(len(f('lg_my_addresses', ua)) == 20, 'modifier une adresse existante reste permis au plafond')
        for i, a_ in enumerate(f('lg_my_addresses', ua)):
            if i >= 3:
                f('lg_delete_address', ua, p_id=a_['address_id'])
        ok(len(f('lg_my_addresses', ua)) == 3, 'retour à trois adresses')
        ok(q("select count(*) from logistics.audit_log where action in ('address.create', 'address.update', 'address.delete') and actor_user_id is null and actor_label = 'customer:%s'" % q("select code from logistics.customer where id = '%s'" % ca)) == q("select count(*) from logistics.audit_log where action like 'address.%%' and metadata ->> 'customer_id' = '%s'" % ca),
           'chaque changement d\'adresse est tracé dans l\'audit, au nom « customer:<code> », sans acteur du personnel')
        ok(int(q("select count(*) from logistics.audit_log where action like 'address.%'")) >= 25, 'et il y en a beaucoup')

        # ============================================================== I. les demandes d'enlèvement
        DEMAIN, DANS3, DANS61 = q("select (current_date + 1)::text"), q("select (current_date + 3)::text"), q("select (current_date + 61)::text")
        HIER = q("select (current_date - 1)::text")
        adr_a = f('lg_my_addresses', ua)[0]
        fr('lg_request_pickup', 'LG003', 'le personnel ne demande pas d\'enlèvement', admin, p_preferred_date=DANS3, p_address='x', p_country='HT')
        for kw, msg in ((dict(p_preferred_date=HIER, p_address='x', p_country='HT'), 'date passée'), (dict(p_preferred_date=DANS61, p_address='x', p_country='HT'), 'date à plus de 60 jours'),
                        (dict(p_preferred_date=None, p_address='x', p_country='HT'), 'date absente'), (dict(p_preferred_date=DANS3, p_address='x', p_country='HT', p_window='NUIT'), 'créneau inconnu'),
                        (dict(p_preferred_date=DANS3, p_address='x', p_country='HT', p_parcels_expected=0), '0 colis'), (dict(p_preferred_date=DANS3, p_address='x', p_country='HT', p_parcels_expected=101), '101 colis'),
                        (dict(p_preferred_date=DANS3, p_address='x', p_country='HT', p_notes='n' * 501), 'notes de 501 caractères'), (dict(p_preferred_date=DANS3, p_country='HT'), 'sans adresse'),
                        (dict(p_preferred_date=DANS3, p_address='x', p_country='FR'), 'pays inconnu'), (dict(p_preferred_date=DANS3, p_address='x'), 'sans pays')):
            fr('lg_request_pickup', 'LG005', 'enlèvement : ' + msg, ua, **kw)
        fr('lg_request_pickup', 'LG002', 'enlèvement à l\'adresse d\'un autre client', ua, p_preferred_date=DANS3, p_address_id=adb['address_id'])
        fr('lg_request_pickup', 'LG002', 'enlèvement à une adresse qui n\'existe pas', ua, p_preferred_date=DANS3, p_address_id=R("gen_random_uuid()"))
        ok(f('lg_my_pickups', ua) == [], 'les refus n\'ont rien créé')
        pk1 = f('lg_request_pickup', ua, p_preferred_date=DANS3, p_parcels_expected=2, p_address_id=adr_a['address_id'], p_window='MORNING', p_notes='Sonner deux fois', p_idempotency_key='cle-1')
        ok(pk1['number'] == 'PKR-%s-000001' % ANNEE and pk1['stage'] == 'requested', 'demande déposée : numéro PKR-%s-000001, étape « demandée »' % ANNEE)
        pk1b = f('lg_request_pickup', ua, p_preferred_date=DANS3, p_parcels_expected=2, p_address_id=adr_a['address_id'], p_window='MORNING', p_notes='Sonner deux fois', p_idempotency_key='cle-1')
        ok(pk1b['pickup_id'] == pk1['pickup_id'] and pk1b['replayed'] is True and q("select count(*) from logistics.pickup_request where customer_id = '%s'" % ca) == '1', 'même clé rejouée (double clic) : une seule demande')
        fr('lg_request_pickup', 'LG006', 'la même clé pour une AUTRE demande', ua, p_preferred_date=DANS3, p_parcels_expected=9, p_address_id=adr_a['address_id'], p_idempotency_key='cle-1')
        pkb = f('lg_request_pickup', ub, p_preferred_date=DANS3, p_parcels_expected=1, p_address_id=adb['address_id'], p_idempotency_key='cle-1')
        ok(pkb['pickup_id'] != pk1['pickup_id'] and 'replayed' not in pkb, 'la clé d\'un autre client n\'est pas la même clé : B obtient SA demande, sans rien apprendre de celle de A')
        lp = f('lg_my_pickups', ua)
        ok(len(lp) == 1 and lp[0]['source'] == 'REQUEST' and lp[0]['stage'] == 'requested' and lp[0]['address'] == adr_a['address'] and lp[0]['city'] == adr_a['city'] and lp[0]['country'] == adr_a['country']
           and lp[0]['window'] == 'MORNING' and lp[0]['parcels_expected'] == 2 and lp[0]['notes'] == 'Sonner deux fois' and lp[0]['message'] is None and lp[0]['date'] == DANS3 and lp[0]['request_status'] == 'REQUESTED', 'ma demande, telle que déposée')
        f('lg_save_address', ua, p_id=adr_a['address_id'], p_country=adr_a['country'], p_address='Adresse changée après la demande', p_city=adr_a['city'])
        ok(f('lg_my_pickups', ua)[0]['address'] == adr_a['address'], 'la demande garde l\'adresse telle qu\'elle était (instantané) : la modifier ensuite ne la change pas')
        pk2 = f('lg_request_pickup', ua, p_preferred_date=DEMAIN, p_address='5 rue du Code', p_city='Delmas', p_country='HT')
        crd = cl.lignes(B, "select contact_name || '|' || contact_phone from logistics.pickup_request where id = '%s'" % pk2['pickup_id'])[0].split('|')
        ok(crd == [q("select full_name from logistics.customer where id = '%s'" % ca), q("select phone from logistics.customer where id = '%s'" % ca)], 'sans contact indiqué : le nom et le téléphone du client')
        ok(pk2['number'] == 'PKR-%s-000003' % ANNEE, 'numérotation continue (B a pris le 2) : %s' % pk2['number'])
        for i in range(3):
            f('lg_request_pickup', ua, p_preferred_date=DANS3, p_address='Adresse %d' % i, p_country='HT')
        fr('lg_request_pickup', 'LG005', 'une 6e demande en attente', ua, p_preferred_date=DANS3, p_address='de trop', p_country='HT')
        fr('lg_cancel_pickup_request', 'LG003', 'le personnel n\'annule pas pour un client', admin, p_id=pk1['pickup_id'])
        fr('lg_cancel_pickup_request', 'LG002', 'annuler la demande d\'un autre', ua, p_id=pkb['pickup_id'])
        fr('lg_cancel_pickup_request', 'LG002', 'annuler une demande inconnue', ua, p_id=R("gen_random_uuid()"))
        ok(f('lg_cancel_pickup_request', ua, p_id=pk2['pickup_id'])['stage'] == 'cancelled', 'annulation d\'une demande en attente')
        fr('lg_cancel_pickup_request', 'LG004', 'annuler deux fois', ua, p_id=pk2['pickup_id'])
        ok(f('lg_request_pickup', ua, p_preferred_date=DANS3, p_address='Après annulation', p_country='HT')['stage'] == 'requested', 'après une annulation, une place se libère : une nouvelle demande passe')
        refuse("update logistics.pickup_request set address = 'piraté' where id = '%s'" % pk1['pickup_id'], 'LG004', 'modifier les champs d\'une demande déposée')
        refuse("delete from logistics.pickup_request", 'LG004', 'supprimer une demande')
        refuse("update logistics.pickup_request set status = 'REQUESTED' where id = '%s'" % pk2['pickup_id'], 'LG001', 'rouvrir une demande annulée')
        refuse("update logistics.pickup_request set preferred_date = current_date where id = '%s'" % pk1['pickup_id'], 'LG004', 'changer la date d\'une demande déposée')
        # le personnel traite la demande (la phase 12 en fait des fonctions ; ici, ce que fera cette fonction)
        task_pk = f('lg_create_pickup_task', admin, p_customer_id=ca, p_address='Adresse', p_scheduled_date=DANS3)['task_id']
        q("update logistics.pickup_request set status = 'APPROVED', task_id = '%s' where id = '%s'" % (task_pk, pk1['pickup_id']))
        fr('lg_cancel_pickup_request', 'LG004', 'annuler une demande déjà approuvée', ua, p_id=pk1['pickup_id'])
        ok(f('lg_my_pickups', ua)[-1]['stage'] in ('scheduled', 'requested', 'cancelled') and [x_ for x_ in f('lg_my_pickups', ua) if x_['pickup_id'] == pk1['pickup_id']][0]['stage'] == 'scheduled', 'approuvée avec une mission créée : « planifiée »')
        f('lg_assign_task', admin, p_task_id=task_pk, p_driver_id=drv, p_force=True, p_reason='essai'); f('lg_accept_task', drv_u, p_task_id=task_pk); f('lg_start_task', drv_u, p_task_id=task_pk)
        ok([x_ for x_ in f('lg_my_pickups', ua) if x_['pickup_id'] == pk1['pickup_id']][0]['stage'] == 'on_the_way', 'mission commencée : « en route »')
        f('lg_fail_task', drv_u, p_task_id=task_pk, p_incident_type='CUSTOMER_ABSENT')
        ok([x_ for x_ in f('lg_my_pickups', ua) if x_['pickup_id'] == pk1['pickup_id']][0]['stage'] == 'missed', 'client absent : « manqué »')
        q("update logistics.pickup_request set status = 'REJECTED', review_message = 'Adresse hors de notre zone' where id = '%s'" % pkb['pickup_id'])
        ok(f('lg_my_pickups', ub)[0]['stage'] == 'rejected' and f('lg_my_pickups', ub)[0]['message'] == 'Adresse hors de notre zone', 'refusée : le client lit le message du personnel qui lui est destiné')
        PS = {('REQUESTED', None): 'requested', ('REJECTED', None): 'rejected', ('CANCELLED', None): 'cancelled', ('APPROVED', 'CREATED'): 'scheduled', ('APPROVED', 'ASSIGNED'): 'scheduled', ('APPROVED', 'ACCEPTED'): 'scheduled',
              ('APPROVED', 'STARTED'): 'on_the_way', ('APPROVED', 'COMPLETED'): 'completed', ('APPROVED', 'FAILED'): 'missed', ('APPROVED', 'CANCELLED'): 'cancelled', ('APPROVED', None): 'scheduled', ('REQUESTED', 'COMPLETED'): 'requested'}
        ok(all(q("select logistics.pickup_stage(%s, %s)" % (val(a_), val(b_))) == e_ for (a_, b_), e_ in PS.items()), 'toutes les combinaisons demande × mission donnent l\'étape attendue')
        # une mission créée par le personnel sans demande apparaît aussi
        task_staff = f('lg_create_pickup_task', admin, p_customer_id=ca, p_address='Enlèvement demandé par téléphone', p_scheduled_date=DEMAIN, p_parcels_expected=3)['task_id']
        staff_item = [x_ for x_ in f('lg_my_pickups', ua) if x_['source'] == 'STAFF']
        ok(len(staff_item) == 1 and staff_item[0]['stage'] == 'scheduled' and staff_item[0]['address'] == 'Enlèvement demandé par téléphone' and staff_item[0]['parcels_expected'] == 3 and staff_item[0]['number'].startswith('PKT-'), 'un enlèvement créé par le personnel apparaît aussi (source STAFF)')
        ok(f('lg_my_dashboard', ua)['pickups']['open'] == int(q("select count(*) from logistics.pickup_request r where r.customer_id = '%s' and r.status in ('REQUESTED','APPROVED') and (r.task_id is null or exists (select 1 from logistics.task t where t.id = r.task_id and t.status not in ('COMPLETED','CANCELLED','FAILED')))" % ca)), 'le tableau de bord compte les enlèvements ouverts comme le décompte direct')
        ok(q("select count(*) from logistics.domain_event where event_type = 'PickupRequestCreated'") == q("select count(*) from logistics.pickup_request") and q("select count(*) from logistics.domain_event where event_type = 'PickupRequestCancelled'") == '1', 'un événement par demande déposée (7), un par annulation (1)')
        ok(q("select count(*) from logistics.domain_event where event_type = 'PickupRequestCreated' and actor_user_id is null and actor_label like 'customer:%'") == q("select count(*) from logistics.pickup_request"), 'les événements sont au nom du client, sans acteur du personnel')

        # ============================================================== J. les livraisons
        def au_hub(cust):
            """Les colis du client au hub et libres de toute demande ou livraison en cours — calculés ici, autrement."""
            res = []
            for t_, pid in (l.split('|') for l in cl.lignes(B, "select tracking_number || '|' || id from logistics.parcel where customer_id = '%s' and status = 'AT_DESTINATION_HUB' order by tracking_number" % cust)):
                en_demande = q("select count(*) from logistics.delivery_request_parcel rp join logistics.delivery_request r on r.id = rp.request_id where rp.parcel_id = '%s' and r.status in ('REQUESTED', 'APPROVED')" % pid) != '0'
                en_tournee = q("select count(*) from logistics.delivery_parcel dp join logistics.task t on t.delivery_id = dp.delivery_id and t.kind = 'DELIVERY' where dp.parcel_id = '%s' and t.status not in ('COMPLETED', 'CANCELLED', 'FAILED')" % pid) != '0'
                if not en_demande and not en_tournee:
                    res.append(t_)
            return res
        dv = f('lg_my_deliveries', ua)
        ok([x_['tracking_number'] for x_ in dv['at_hub']] == au_hub(ca) and 'N-002' in au_hub(ca) and 'N-003' not in au_hub(ca), 'colis que A peut demander à se faire livrer : au hub et libres (N-002 oui, N-003 non : déjà dans une livraison)')
        ok(dv['requests'] == [] and len(dv['deliveries']) == 2, 'aucune demande ; deux livraisons : la remise de N-001 et la planifiée de N-003')
        liv_ok = [x_ for x_ in dv['deliveries'] if x_['stage'] == 'delivered'][0]; liv_prev = [x_ for x_ in dv['deliveries'] if x_['stage'] == 'scheduled'][0]
        ok(liv_ok['parcels'] == ['N-001'] and liv_ok['proof']['recipient_name'] == 'Marie Joseph' and liv_ok['otp_required'] is True and liv_ok['otp_issued'] is False, 'livraison faite : preuve (nom, heure), le code a servi')
        ok(liv_prev['parcels'] == ['N-003'] and liv_prev['address'] == '5 rue du Code, Delmas' and liv_prev['date'] == q("select (current_date + 1)::text") and liv_prev['proof'] is None and liv_prev['failure'] is None, 'livraison planifiée : adresse et date, pas de preuve')
        ok('otp_hash' not in texte(dv) and 'latitude' not in texte(dv) and 'driver' not in texte(dv).lower(), 'ni empreinte de code, ni position GPS, ni chauffeur')
        ok(f('lg_my_deliveries', admin) == {'requests': [], 'deliveries': [], 'at_hub': []}, 'le personnel (non relié) : rien')
        ok(f('lg_my_deliveries', ub)['requests'] == [] and 'N-001' not in texte(f('lg_my_deliveries', ub)), 'B ne voit rien de A')
        fr('lg_request_delivery', 'LG003', 'le personnel ne demande pas de livraison', admin, p_tracking_numbers=['N-002'], p_preferred_date=DANS3, p_address='x', p_country='HT')
        ad_l = f('lg_my_addresses', ua)[0]['address_id']
        for kw, msg, etat in ((dict(p_tracking_numbers=[]), 'aucun colis', 'LG005'), (dict(p_tracking_numbers=['N-%03d' % i for i in range(100, 151)]), '51 colis', 'LG005'),
                              (dict(p_tracking_numbers=['N-002'], p_preferred_date=HIER), 'date passée', 'LG005'), (dict(p_tracking_numbers=['N-002'], p_preferred_date=DANS61), 'date à plus de 60 jours', 'LG005'),
                              (dict(p_tracking_numbers=['N-002'], p_window='NUIT'), 'créneau inconnu', 'LG005'), (dict(p_tracking_numbers=['N-002'], p_notes='n' * 501), 'notes de 501 caractères', 'LG005'),
                              (dict(p_tracking_numbers=['N-001']), 'colis déjà livré (pas au hub)', 'LG005'), (dict(p_tracking_numbers=['N-003']), 'colis déjà dans une livraison', 'LG005'),
                              (dict(p_tracking_numbers=['N-008']), 'colis retenu (pas au hub)', 'LG005'), (dict(p_tracking_numbers=['N-004']), 'colis d\'un autre client', 'LG002'),
                              (dict(p_tracking_numbers=['ZZZ-1']), 'colis inexistant', 'LG002'), (dict(p_tracking_numbers=['N-002', 'N-004']), 'un colis à moi et un d\'un autre', 'LG002')):
            args = dict(p_preferred_date=DANS3, p_address_id=ad_l)
            args.update(kw)
            fr('lg_request_delivery', etat, 'livraison : ' + msg, ua, **args)
        ok(q("select count(*) from logistics.delivery_request") == '0', 'les refus n\'ont rien créé (tout ou rien)')
        c1_, t1_ = cl.run(B, appel('lg_request_delivery', p_tracking_numbers=['N-004'], p_preferred_date=DANS3, p_address_id=ad_l), role='authenticated', claims=ua, expect_error=True)
        c2_, t2_ = cl.run(B, appel('lg_request_delivery', p_tracking_numbers=['ZZZ-9'], p_preferred_date=DANS3, p_address_id=ad_l), role='authenticated', claims=ua, expect_error=True)
        ok('LG002' in t1_ and 'Colis introuvable' in t1_ and 'LG002' in t2_ and 'Colis introuvable' in t2_, 'le colis d\'un autre répond « introuvable », comme un colis inexistant')
        fr('lg_request_delivery', 'LG002', 'livraison à l\'adresse d\'un autre client', ua, p_tracking_numbers=['N-002'], p_preferred_date=DANS3, p_address_id=adb['address_id'])
        dr1 = f('lg_request_delivery', ua, p_tracking_numbers=['N-002', 'n-002', ' N-002 '], p_preferred_date=DANS3, p_address_id=ad_l, p_window='AFTERNOON', p_notes='Appeler avant', p_idempotency_key='liv-1')
        ok(dr1['number'] == 'DLR-%s-000001' % ANNEE and dr1['parcels'] == 1 and dr1['stage'] == 'requested', 'demande de livraison : numéro DLR-%s-000001 ; les trois écritures du même numéro ne font qu\'un colis' % ANNEE)
        dr1b = f('lg_request_delivery', ua, p_tracking_numbers=['N-002', 'n-002', ' N-002 '], p_preferred_date=DANS3, p_address_id=ad_l, p_window='AFTERNOON', p_notes='Appeler avant', p_idempotency_key='liv-1')
        ok(dr1b['request_id'] == dr1['request_id'] and dr1b['replayed'] is True and q("select count(*) from logistics.delivery_request") == '1', 'double envoi : une seule demande')
        fr('lg_request_delivery', 'LG006', 'même clé, autre demande', ua, p_tracking_numbers=['N-002'], p_preferred_date=DEMAIN, p_address_id=ad_l, p_idempotency_key='liv-1')
        fr('lg_request_delivery', 'LG005', 'le colis est maintenant dans une demande en attente', ua, p_tracking_numbers=['N-002'], p_preferred_date=DANS3, p_address_id=ad_l)
        dv2 = f('lg_my_deliveries', ua)
        ok('N-002' not in [x_['tracking_number'] for x_ in dv2['at_hub']] and [x_['tracking_number'] for x_ in dv2['at_hub']] == au_hub(ca), 'N-002 n\'est plus proposé : il est dans une demande')
        rq = dv2['requests'][0]
        ok(rq['number'] == dr1['number'] and rq['stage'] == 'requested' and rq['parcels'] == ['N-002'] and rq['window'] == 'AFTERNOON' and rq['notes'] == 'Appeler avant' and rq['request_status'] == 'REQUESTED' and rq['message'] is None, 'ma demande de livraison, telle que déposée')
        fr('lg_cancel_delivery_request', 'LG003', 'le personnel n\'annule pas pour un client', admin, p_id=dr1['request_id'])
        fr('lg_cancel_delivery_request', 'LG002', 'annuler la demande d\'un autre (B n\'en a pas : inconnue)', ub, p_id=dr1['request_id'])
        ok(f('lg_cancel_delivery_request', ua, p_id=dr1['request_id'])['stage'] == 'cancelled', 'annulation')
        fr('lg_cancel_delivery_request', 'LG004', 'annuler deux fois', ua, p_id=dr1['request_id'])
        ok('N-002' in [x_['tracking_number'] for x_ in f('lg_my_deliveries', ua)['at_hub']], 'annulée : N-002 est de nouveau proposé')
        dr2 = f('lg_request_delivery', ua, p_tracking_numbers=['N-002'], p_preferred_date=DANS3, p_address='1 rue Libre', p_city='Delmas', p_country='HT')
        ok(dr2['number'] == 'DLR-%s-000002' % ANNEE, 'on peut redemander après annulation, avec une adresse saisie')
        refuse("update logistics.delivery_request set address = 'piraté' where id = '%s'" % dr2['request_id'], 'LG004', 'modifier une demande de livraison déposée')
        refuse("delete from logistics.delivery_request", 'LG004', 'supprimer une demande de livraison')
        refuse("update logistics.delivery_request set status = 'REQUESTED' where id = '%s'" % dr1['request_id'], 'LG001', 'rouvrir une demande annulée')
        refuse("update logistics.delivery_request_parcel set parcel_id = parcel_id", 'LG004', 'modifier les colis d\'une demande')
        refuse("delete from logistics.delivery_request_parcel", 'LG004', 'retirer un colis d\'une demande')
        q("update logistics.delivery_request set status = 'APPROVED' where id = '%s'" % dr2['request_id'])
        fr('lg_cancel_delivery_request', 'LG004', 'annuler une demande approuvée', ua, p_id=dr2['request_id'])
        ok(f('lg_my_deliveries', ua)['requests'][0]['stage'] == 'scheduled', 'approuvée sans mission : « planifiée »')
        DS = {('REQUESTED', None): 'requested', ('REJECTED', None): 'rejected', ('CANCELLED', None): 'cancelled', ('APPROVED', 'CREATED'): 'scheduled', ('APPROVED', 'STARTED'): 'on_the_way', ('APPROVED', 'COMPLETED'): 'delivered',
              ('APPROVED', 'FAILED'): 'missed', ('APPROVED', 'CANCELLED'): 'cancelled', ('APPROVED', None): 'scheduled'}
        ok(all(q("select logistics.delivery_stage(%s, %s)" % (val(a_), val(b_))) == e_ for (a_, b_), e_ in DS.items()), 'toutes les combinaisons demande × mission donnent l\'étape attendue')
        ok(q("select count(*) from logistics.domain_event where event_type = 'DeliveryRequestCreated'") == '2' and q("select count(*) from logistics.domain_event where event_type = 'DeliveryRequestCancelled'") == '1', 'événements : 2 demandes déposées, 1 annulée')
        # plafond de 5 demandes en attente : on réutilise de vrais colis au hub (les colis hérités « disponibles »)
        libres = au_hub(ca)
        ok(len(libres) >= 6 and libres == [x_['tracking_number'] for x_ in f('lg_my_deliveries', ua)['at_hub']], 'six colis de plus au hub pour éprouver le plafond (%d libres)' % len(libres))
        for t_ in libres[:5]:
            f('lg_request_delivery', ua, p_tracking_numbers=[t_], p_preferred_date=DANS3, p_address_id=ad_l)
        fr('lg_request_delivery', 'LG005', 'une 6e demande de livraison en attente', ua, p_tracking_numbers=[libres[5]], p_preferred_date=DANS3, p_address_id=ad_l)

        # ============================================================== K. les notifications
        nt = f('lg_my_notifications', ua)
        ok(nt['unread'] == 2 and len(nt['items']) == 3 and [i_['template'] for i_ in nt['items']] == ['ShipmentArrived', 'Delivered', 'ParcelReceived'], 'trois notifications dans le portail (la WhatsApp n\'en est pas), la plus récente d\'abord, 2 non lues')
        ok(nt['items'][2]['payload'] == {'tracking_number': 'N-001', 'stage': 'received'}, 'la charge utile est filtrée par une LISTE BLANCHE : « internal_key » et « recipient_phone » ne sortent pas')
        ok(all(set(i_) == {'id', 'template', 'created_at', 'read_at', 'payload'} for i_ in nt['items']) and nt['items'][0]['read_at'] is not None, 'forme des notifications ; la plus récente est déjà lue')
        ok([i_['template'] for i_ in f('lg_my_notifications', ua, p_unread_only=True)['items']] == ['Delivered', 'ParcelReceived'], 'seulement les non lues')
        ok(len(f('lg_my_notifications', ua, p_limit=1)['items']) == 1 and f('lg_my_notifications', ua, p_limit=1)['unread'] == 2 and len(f('lg_my_notifications', ua, p_limit=0)['items']) == 1, 'limite : 1 ; le compteur n\'est pas limité ; limite 0 vaut 1')
        ok(f('lg_my_notifications', admin) == {'unread': 0, 'items': []}, 'le personnel (non relié) : rien')
        id_b = int(q("select id from logistics.notification where customer_id = '%s' and channel = 'in_app'" % cb))
        id_a1, id_a2 = (int(x_) for x_ in cl.lignes(B, "select id from logistics.notification where customer_id = '%s' and channel = 'in_app' and read_at is null order by id" % ca))
        ok(f('lg_mark_notifications_read', ua, p_ids=[id_b])['marked'] == 0 and q("select read_at is null from logistics.notification where id = %d" % id_b) == 't', 'marquer « lue » la notification de B : rien (elle reste non lue chez B)')
        ok(f('lg_mark_notifications_read', ua, p_ids=[id_a1])['marked'] == 1 and f('lg_my_dashboard', ua)['notifications']['unread'] == 1, 'marquer une notification : 1 ; le tableau de bord suit')
        ok(f('lg_mark_notifications_read', ua, p_ids=[id_a1])['marked'] == 0, 'la marquer deux fois : rien de plus')
        ok(f('lg_mark_notifications_read', ua)['marked'] == 1 and f('lg_my_notifications', ua)['unread'] == 0, 'tout marquer : la dernière non lue')
        wa = int(q("select id from logistics.notification where customer_id = '%s' and channel = 'whatsapp'" % ca))
        ok(f('lg_mark_notifications_read', ua, p_ids=[wa])['marked'] == 0 and q("select read_at is null from logistics.notification where id = %d" % wa) == 't', 'une notification WhatsApp n\'est pas du portail : intouchée')
        fr('lg_mark_notifications_read', 'LG003', 'le personnel ne marque rien', admin)
        ok(f('lg_my_notifications', ub)['unread'] == 1 and 'N-001' not in texte(f('lg_my_notifications', ub)), 'B garde sa notification non lue, et ne voit rien de A')

        # ============================================================== L. le support
        INV_A = q("select number from logistics.invoice where id = '%s'" % inv_a)
        for kw, msg, etat in ((dict(p_subject='ab', p_category='PARCEL', p_body='x'), 'sujet de 2 caractères', 'LG005'), (dict(p_subject='s' * 121, p_category='PARCEL', p_body='x'), 'sujet de 121 caractères', 'LG005'),
                              (dict(p_subject='Sujet', p_category='PARCEL', p_body='   '), 'message vide', 'LG005'), (dict(p_subject='Sujet', p_category='PARCEL', p_body='b' * 4001), 'message de 4001 caractères', 'LG005'),
                              (dict(p_subject='Sujet', p_category='VENTE', p_body='x'), 'catégorie inconnue', 'LG005'), (dict(p_subject='Sujet', p_category='PARCEL', p_body='x', p_tracking='N-004'), 'colis d\'un autre', 'LG002'),
                              (dict(p_subject='Sujet', p_category='INVOICE', p_body='x', p_invoice_number=q("select number from logistics.invoice where id = '%s'" % inv_b)), 'facture d\'un autre', 'LG002'),
                              (dict(p_subject='Sujet', p_category='INVOICE', p_body='x', p_invoice_number=q("select number from logistics.invoice where id = '%s'" % inv_draft)), 'brouillon de facture', 'LG002')):
            fr('lg_open_ticket', etat, 'ticket : ' + msg, ua, **kw)
        fr('lg_open_ticket', 'LG003', 'le personnel n\'ouvre pas de ticket client', admin, p_subject='Sujet', p_category='OTHER', p_body='x')
        ok(f('lg_my_tickets', ua) == [] and q("select count(*) from logistics.support_ticket") == '0', 'les refus n\'ont rien créé')
        t1 = f('lg_open_ticket', ua, p_subject='  Mon colis est abîmé  ', p_category='PARCEL', p_body='Le contenu est cassé.', p_tracking='n-001', p_invoice_number=INV_A, p_idempotency_key='t-1')
        ok(t1['number'] == 'SUP-%s-000001' % ANNEE and t1['status'] == 'OPEN', 'ticket ouvert : SUP-%s-000001' % ANNEE)
        t1b = f('lg_open_ticket', ua, p_subject='  Mon colis est abîmé  ', p_category='PARCEL', p_body='Le contenu est cassé.', p_tracking='n-001', p_invoice_number=INV_A, p_idempotency_key='t-1')
        ok(t1b['ticket_id'] == t1['ticket_id'] and t1b['replayed'] is True and q("select count(*) from logistics.support_ticket") == '1', 'double envoi : un seul ticket')
        fr('lg_open_ticket', 'LG006', 'même clé, autre ticket', ua, p_subject='Autre sujet', p_category='OTHER', p_body='autre', p_idempotency_key='t-1')
        lt = f('lg_my_tickets', ua)
        ok(len(lt) == 1 and lt[0]['subject'] == 'Mon colis est abîmé' and lt[0]['status'] == 'OPEN' and lt[0]['messages'] == 1 and lt[0]['last_author'] == 'CUSTOMER' and lt[0]['category'] == 'PARCEL', 'ma liste de tickets (sujet sans espaces autour)')
        tk = f('lg_my_ticket', ua, p_id=t1['ticket_id'])
        ok(tk['parcel'] == 'N-001' and tk['invoice'] == INV_A and len(tk['messages']) == 1 and tk['messages'][0]['author'] == 'CUSTOMER' and tk['messages'][0]['body'] == 'Le contenu est cassé.', 'détail : colis et facture liés, premier message')
        q("insert into logistics.support_message (ticket_id, author_kind, author_user_id, body) values ('%s', 'STAFF', '%s', 'Bonjour, nous ouvrons une enquête.')" % (t1['ticket_id'], admin))
        q("update logistics.support_ticket set status = 'ANSWERED' where id = '%s'" % t1['ticket_id'])
        tk = f('lg_my_ticket', ua, p_id=t1['ticket_id'])
        ok([m_['author'] for m_ in tk['messages']] == ['CUSTOMER', 'STAFF'] and tk['status'] == 'ANSWERED' and all(set(m_) == {'author', 'body', 'at'} for m_ in tk['messages']), 'la réponse du personnel est signée « STAFF » : sans nom, sans compte')
        ok('client1@essai.test' not in texte(tk) and admin not in texte(tk), 'ni l\'adresse ni l\'identifiant du membre du personnel')
        ok(f('lg_my_tickets', ua)[0]['last_author'] == 'STAFF' and f('lg_my_tickets', ua)[0]['messages'] == 2, 'la liste montre qui a écrit en dernier')
        ok(f('lg_reply_ticket', ua, p_id=t1['ticket_id'], p_body='Merci, voici des photos.')['status'] == 'OPEN' and f('lg_my_ticket', ua, p_id=t1['ticket_id'])['messages'][-1]['author'] == 'CUSTOMER', 'répondre rouvre le ticket (OPEN)')
        fr('lg_reply_ticket', 'LG005', 'réponse vide', ua, p_id=t1['ticket_id'], p_body=' ')
        fr('lg_reply_ticket', 'LG005', 'réponse de 4001 caractères', ua, p_id=t1['ticket_id'], p_body='r' * 4001)
        fr('lg_reply_ticket', 'LG003', 'le personnel ne répond pas par la porte du client', admin, p_id=t1['ticket_id'], p_body='x')
        c1_, t1x = cl.run(B, appel('lg_my_ticket', p_id=t1['ticket_id']), role='authenticated', claims=ub, expect_error=True)
        c2_, t2x = cl.run(B, appel('lg_my_ticket', p_id='11111111-1111-1111-1111-111111111111'), role='authenticated', claims=ub, expect_error=True)
        ok('LG002' in t1x and 'Ticket introuvable' in t1x and 'LG002' in t2x and 'Ticket introuvable' in t2x, 'le ticket d\'un autre répond « introuvable », comme un ticket inexistant')
        fr('lg_reply_ticket', 'LG002', 'répondre au ticket d\'un autre', ub, p_id=t1['ticket_id'], p_body='x')
        fr('lg_close_my_ticket', 'LG002', 'fermer le ticket d\'un autre', ub, p_id=t1['ticket_id'])
        fr('lg_close_my_ticket', 'LG003', 'le personnel ne ferme pas par la porte du client', admin, p_id=t1['ticket_id'])
        ok(f('lg_my_tickets', ub) == [] and 'cassé' not in texte(f('lg_my_tickets', ub)), 'B ne voit aucun ticket de A')
        ok(f('lg_close_my_ticket', ua, p_id=t1['ticket_id'])['status'] == 'CLOSED' and f('lg_my_ticket', ua, p_id=t1['ticket_id'])['closed_at'] is not None, 'ticket fermé')
        fr('lg_reply_ticket', 'LG004', 'répondre à un ticket fermé', ua, p_id=t1['ticket_id'], p_body='encore')
        fr('lg_close_my_ticket', 'LG004', 'fermer deux fois', ua, p_id=t1['ticket_id'])
        refuse("update logistics.support_ticket set status = 'OPEN', closed_at = null where id = '%s'" % t1['ticket_id'], 'LG001', 'rouvrir un ticket fermé')
        refuse("update logistics.support_ticket set subject = 'piraté' where id = '%s'" % t1['ticket_id'], 'LG004', 'modifier le sujet d\'un ticket')
        refuse("delete from logistics.support_ticket", 'LG004', 'supprimer un ticket')
        refuse("update logistics.support_message set body = 'piraté'", 'LG004', 'modifier un message')
        refuse("delete from logistics.support_message", 'LG004', 'supprimer un message')
        refuse("insert into logistics.support_message (ticket_id, author_kind, body) values ('%s', 'STAFF', 'faux message du personnel')" % t1['ticket_id'], '23514', 'un message « du personnel » sans auteur du personnel')
        # plafond de 5 tickets en 24 h
        for i in range(4):
            f('lg_open_ticket', ua, p_subject='Question %d' % i, p_category='OTHER', p_body='bonjour')
        fr('lg_open_ticket', 'LG005', 'un 6e ticket en 24 heures', ua, p_subject='De trop', p_category='OTHER', p_body='x')
        # plafond de 10 tickets ouverts : C en a dix, anciens
        for i in range(10):
            q("insert into logistics.support_ticket (number, customer_id, subject, category, created_at) values ('SUP-OLD-%d', '%s', 'Ancien ticket %d', 'OTHER', now() - interval '3 days')" % (i, cc, i))
        fr('lg_open_ticket', 'LG005', 'un 11e ticket ouvert', uc, p_subject='De trop', p_category='OTHER', p_body='x')
        ok(q("select count(*) from logistics.domain_event where event_type = 'SupportTicketOpened'") == '5' and q("select count(*) from logistics.domain_event where event_type = 'SupportTicketReplied'") == '1' and q("select count(*) from logistics.domain_event where event_type = 'SupportTicketClosed'") == '1',
           'événements : 5 tickets ouverts, 1 réponse, 1 fermeture')

        # ============================================================== M. ce qu'un client ne doit JAMAIS pouvoir faire
        ok(q("select role || '|' || coalesce(array_to_string(droits, ','), '') from public.clients where id = '%s'" % ua) == 'client|', 'A est un client, sans aucun droit')
        # 1. l'ancien schéma : rôle, droits, code, e-mail, colis, factures, historique
        attaques = ["update public.clients set role = 'admin' where id = '%s'" % ua, "update public.clients set role = 'gerant'", "update public.clients set droits = array['factures.modifier', 'roles.gerer'] where id = '%s'" % ua,
                    "update public.clients set code = 'SES-00001' where id = '%s'" % ua, "update public.clients set email = 'pirate@essai.test' where id = '%s'" % ua,
                    "update public.clients set role = 'admin' where id = '%s'" % ub, "select public.definir_role('%s', 'admin', array[]::text[])" % ua,
                    "update public.colis set statut = 'livre' where client_id = '%s'" % ua, "update public.colis set tarif_lb = 0 where client_id = '%s'" % ua, "update public.colis set poids_lb = 0.1 where client_id = '%s'" % ua,
                    "delete from public.colis where client_id = '%s'" % ua, "insert into public.colis (client_id, description, destinataire, poids_lb, tarif_lb, service, pays_destination, statut) values ('%s', 'faux', 'x', 1, 0, 'aerien', 'HT', 'livre')" % ua,
                    "update public.factures set montant_paye = montant where client_id = '%s'" % ua, "update public.factures set montant = 1 where client_id = '%s'" % ua, "delete from public.factures where client_id = '%s'" % ua,
                    "insert into public.colis_historique (colis_id, statut, lieu) select id, 'livre', 'faux' from public.colis where client_id = '%s' limit 1" % ua,
                    "update public.colis_historique set statut = 'livre'", "delete from public.colis_historique"]
        for a_ in attaques:
            cl.run(B, a_, role='authenticated', claims=ua, expect_error=True)
        ok(P.empreintes_historiques(cl, B) == legacy0, 'après dix-huit attaques sur l\'ancien schéma (rôle, droits, code, e-mail, colis, factures, historique) : TOUT est intact, octet pour octet')
        ok(q("select role || '|' || coalesce(array_to_string(droits, ','), '') from public.clients where id = '%s'" % ua) == 'client|', 'A est toujours un client sans droit')
        code, _ = cl.run(B, "update public.clients set telephone = '+509 0000 0000' where id = '%s'" % ua, role='authenticated', claims=ua, expect_error=True)
        ok(code == 0 and q("select telephone from public.clients where id = '%s'" % ua) == '+509 0000 0000', 'contre-épreuve : ce que le client PEUT changer (son téléphone) fonctionne : les refus ne viennent pas d\'un blocage général')
        # 2. le noyau : aucune table, aucune vue, aucune fonction interne n'est accessible
        ok(q("select count(*) from information_schema.table_privileges where table_schema = 'logistics' and grantee in ('anon', 'authenticated', 'PUBLIC')") == '0', 'aucun droit sur aucune table ni vue du schéma « logistics » pour un client, un visiteur ou le public')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and (has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute') or has_function_privilege('public', p.oid, 'execute'))") == '0',
           'aucune fonction interne du noyau (%s) n\'est exécutable par un client' % q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics'"))
        ok(q("select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace where n.nspname = 'logistics' and c.relkind = 'r' and not c.relrowsecurity") == '0', 'toutes les tables du noyau ont la sécurité par ligne active')
        for sql, msg in (("insert into logistics.tracking_event (parcel_id, event_type, to_status, occurred_at, source) values ('%s', 'Delivered', 'DELIVERED', now(), 'api')" % a2, 'FALSIFIER un événement de suivi'),
                         ("insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id) values ('Delivered', 'parcel', '%s', gen_random_uuid())" % a2, 'FALSIFIER un événement de domaine'),
                         ("update logistics.parcel set status = 'DELIVERED' where id = '%s'" % a2, 'changer le statut d\'un colis'),
                         ("update logistics.invoice set total = 0 where id = '%s'" % inv_a, 'modifier une facture finalisée'),
                         ("update logistics.invoice set status = 'PAID' where id = '%s'" % inv_draft, 'solder un brouillon'),
                         ("update logistics.app_user set role = 'admin'", 'changer un rôle du noyau'), ("update logistics.customer set auth_user_id = '%s' where id = '%s'" % (ua, cb), 'se rattacher au compte d\'un autre'),
                         ("delete from logistics.audit_log", 'effacer l\'audit'), ("select * from logistics.audit_log", 'LIRE l\'audit'), ("select * from logistics.payment", 'lire les paiements directement'),
                         ("insert into logistics.payment (number, invoice_id, customer_id, amount, currency, base_amount_usd, tendered_amount, tendered_currency, rate_used, method, correlation_id) values ('PAY-X', '%s', '%s', 1, 'USD', 1, 1, 'USD', 1, 'CASH', gen_random_uuid())" % (inv_draft, ca), 'inventer un paiement'),
                         ("update logistics.support_ticket set customer_id = '%s'" % cb, 'déplacer un ticket'), ("update logistics.notification set read_at = now()", 'modifier une notification directement')):
            code, texte_ = cl.run(B, sql, role='authenticated', claims=ua, expect_error=True)
            ok(code != 0 and ('permission denied' in texte_ or '42501' in texte_), 'un client ne peut pas %s (accès direct refusé) : %s' % (msg, texte_[-100:].replace('\n', ' ')))
        # 3. les fonctions : TOUTES celles du personnel, une par une, appelées par un client
        CLIENT = {'lg_my_dashboard', 'lg_my_parcels', 'lg_my_parcel', 'lg_my_shipments', 'lg_my_consolidations', 'lg_my_payments', 'lg_my_documents', 'lg_my_addresses', 'lg_save_address', 'lg_delete_address',
                  'lg_my_pickups', 'lg_request_pickup', 'lg_cancel_pickup_request', 'lg_my_deliveries', 'lg_request_delivery', 'lg_cancel_delivery_request', 'lg_my_notifications', 'lg_mark_notifications_read',
                  'lg_my_tickets', 'lg_my_ticket', 'lg_open_ticket', 'lg_reply_ticket', 'lg_close_my_ticket', 'lg_my_invoices', 'lg_my_balance'}
        LITT = {'uuid': 'gen_random_uuid()', 'text': "'x'", 'integer': '1', 'bigint': '1', 'smallint': '1', 'numeric': '1', 'date': 'current_date', 'boolean': 'false', 'jsonb': "'[]'::jsonb",
                'timestamp with time zone': 'now()', 'text[]': "array['x']", 'uuid[]': 'array[gen_random_uuid()]', 'bigint[]': 'array[1]::bigint[]'}
        fns = json.loads(q("select json_agg(json_build_object('name', p.proname, 'args', (select coalesce(json_agg(json_build_object('n', p.proargnames[u.ord], 't', format_type(u.t, null)) order by u.ord), '[]'::json) "
                           "from unnest(p.proargtypes::oid[]) with ordinality u(t, ord) where u.ord <= p.pronargs - p.pronargdefaults)) order by p.proname) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
                           "where n.nspname = 'public' and p.proname like 'lg\\_%'"))
        noms = {f_['name'] for f_ in fns}
        ok(CLIENT <= noms, 'toutes les fonctions du client existent bien')
        ok(len(fns) >= 95, 'le noyau expose %d fonctions lg_* : le test les appelle toutes' % len(fns))
        non_gerees = {t_ for f_ in fns for a_ in f_['args'] for t_ in [a_['t']] if t_ not in LITT}
        ok(not non_gerees, 'le test sait fabriquer un argument pour chaque type : %s' % non_gerees)
        refus = 0
        for f_ in fns:
            if f_['name'] in CLIENT:
                continue
            sql = "select public.%s(%s)" % (f_['name'], ', '.join('%s => %s' % (a_['n'], LITT[a_['t']]) for a_ in f_['args']))
            code, texte_ = cl.run(B, sql, role='authenticated', claims=ua, expect_error=True)
            ok(code != 0 and ('LG003' in texte_ or '42501' in texte_), 'UN CLIENT APPELLE %s : doit être refusé (LG003 ou 42501), obtenu : %s' % (f_['name'], texte_[-160:].replace('\n', ' ')))
            refus += 1
        ok(refus == len(fns) - len(CLIENT), 'les %d fonctions du personnel ont toutes refusé le client' % refus)
        # Et avec des paramètres VALIDES (un vrai colis, une vraie transition, une vraie intention) : le refus est le même, et il tombe avant tout le reste.
        fr('lg_scan_parcel', 'LG003', 'un client scanne un de SES colis (paramètres valides)', ua, p_code='N-001', p_purpose='lookup', p_warehouse_id=wmia)
        fr('lg_scan_parcel', 'LG003', 'un client scanne avec une intention invalide : le droit d\'abord, la validation ensuite', ua, p_code='N-001', p_purpose='piratage', p_warehouse_id=wmia)
        fr('lg_transition_parcel', 'LG003', 'un client fait avancer SON PROPRE colis vers « affecté à une livraison » (transition valide)', ua, p_parcel_id=a2, p_to_status='DELIVERY_ASSIGNED')
        fr('lg_transition_parcel', 'LG003', 'un client marque SON colis livré', ua, p_parcel_id=a2, p_to_status='DELIVERED', p_reason='reçu')
        fr('lg_transition_parcel', 'LG003', 'un client appelle avec une clé d\'idempotence déjà utilisée par le personnel', ua, p_parcel_id=a2, p_to_status='ON_HOLD', p_idempotency_key='d1', p_reason='x')
        fr('lg_transition_parcel', 'LG003', 'un client touche au colis d\'un autre', ua, p_parcel_id=b1, p_to_status='ON_HOLD', p_reason='x')
        fr('lg_transition_parcel', 'LG003', 'un client appelle avec un colis qui n\'existe pas : même refus (rien ne révèle si l\'identifiant existe)', ua, p_parcel_id=R("gen_random_uuid()"), p_to_status='ON_HOLD', p_reason='x')
        fr('lg_transition_parcel', 'LG003', 'un chauffeur n\'a pas le droit de faire avancer un colis par la porte générale', drv_u, p_parcel_id=a2, p_to_status='DELIVERY_ASSIGNED')
        ok(f('lg_task_board', admin, p_date=R("current_date")) is not None, 'contre-épreuve : la direction, elle, appelle une de ces fonctions sans refus')
        # 4. l'inverse : un membre du personnel ne passe pas par les portes du client, et un visiteur anonyme ne passe nulle part
        ecritures = [f_ for f_ in fns if f_['name'] in CLIENT and f_['name'] in ('lg_save_address', 'lg_delete_address', 'lg_request_pickup', 'lg_cancel_pickup_request', 'lg_request_delivery', 'lg_cancel_delivery_request',
                                                                                'lg_mark_notifications_read', 'lg_open_ticket', 'lg_reply_ticket', 'lg_close_my_ticket')]
        ok(len(ecritures) == 10, 'dix fonctions d\'écriture du client')
        for f_ in ecritures:
            sql = "select public.%s(%s)" % (f_['name'], ', '.join('%s => %s' % (a_['n'], LITT[a_['t']]) for a_ in f_['args']))
            code, texte_ = cl.run(B, sql, role='authenticated', claims=admin, expect_error=True)
            ok(code != 0 and 'LG003' in texte_, 'la direction appelle %s : refusé, elle n\'a pas de profil client' % f_['name'])
        for f_ in fns:
            sql = "select public.%s(%s)" % (f_['name'], ', '.join('%s => %s' % (a_['n'], LITT[a_['t']]) for a_ in f_['args']))
            code, texte_ = cl.run(B, sql, role='anon', expect_error=True)
            ok(code != 0 and ('permission denied' in texte_ or '42501' in texte_), 'un visiteur anonyme appelle %s : refusé' % f_['name'])
        # 5. à la fin de tout cela, rien de critique n'a bougé
        ok(noyau_critique() == fp0, 'colis, journal de suivi, factures, argent, droits : EMPREINTE IDENTIQUE à celle d\'avant les dizaines d\'actions et d\'attaques du client')

        # ============================================================== N. le noyau est-il à jour pour ce client ?
        sync = lambda u: f('lg_my_dashboard', u)['in_sync']   # noqa: E731
        ok(sync(ua) is True and sync(ub) is True and sync(uc) is True, 'après le rattrapage : à jour pour les trois clients')
        leg = q("select c.id from public.colis c join logistics.parcel p on p.legacy_parcel_id = c.id where c.client_id = '%s' and c.statut = 'confirme' and p.status_authority = 'legacy' limit 1" % ua)
        q("update public.colis set statut = 'expedie' where id = '%s'" % leg)
        ok(sync(ua) is False and sync(ub) is True, 'un colis de A change dans l\'ancien schéma : le noyau est en RETARD pour A (et seulement pour A)')
        q('select logistics.backfill_from_legacy()')
        ok(sync(ua) is True, 'le rattrapage rejoué : à jour')
        ok(sync(ua) is True, 'avant de toucher à une facture : A est bien à jour (sinon l\'essai suivant ne prouverait rien)')
        inv_leg = q("select f.id from public.factures f where f.client_id = '%s' and f.montant_paye = 0 limit 1" % ua)
        q("update public.factures set montant_paye = 1 where id = '%s'" % inv_leg)
        ok(sync(ua) is False, 'un paiement saisi dans l\'ancien schéma : en retard aussi')
        q('select logistics.backfill_from_legacy()')
        ok(sync(ua) is True, 'rattrapé')
        q("insert into public.colis (client_id, description, destinataire, poids_lb, tarif_lb, service, pays_destination, statut) values ('%s', 'colis arrivé après le rattrapage', 'x', 3, 2, 'aerien', 'HT', 'confirme')" % ua)
        ok(sync(ua) is False, 'un colis tout neuf dans l\'ancien schéma : en retard')
        q('select logistics.backfill_from_legacy()')
        ok(sync(ua) is True, 'rattrapé')
        pris = q("select p.id from logistics.parcel p where p.customer_id = '%s' and p.legacy_parcel_id is not null and p.status_authority = 'legacy' and p.status in ('CREATED', 'IN_TRANSIT', 'AT_DESTINATION_HUB') order by p.tracking_number limit 1" % ca)
        ok(pris != '', 'A a un colis hérité sur lequel le noyau peut prendre la main')
        f('lg_transition_parcel', admin, p_parcel_id=pris, p_to_status='ON_HOLD', p_reason='contrôle')
        q("update public.colis set statut = 'livre' where id = (select legacy_parcel_id from logistics.parcel where id = '%s')" % pris)
        ok(sync(ua) is True, 'un colis dont le NOYAU a pris la main n\'est plus comparé à l\'ancien statut (le noyau fait foi)')
        ok(f('lg_my_dashboard', admin)['in_sync'] is False, 'le personnel : jamais « à jour » (il n\'a pas d\'espace client)')

        # ============================================================== O. la FORME de chaque réponse est figée
        leg_num = q("select numero from public.colis where client_id = '%s' order by numero limit 1" % ua)
        REPONSES = {
            'tableau_de_bord': f('lg_my_dashboard', ua), 'colis': f('lg_my_parcels', ua, p_limit=3), 'colis_noyau': f('lg_my_parcel', ua, p_tracking='N-001'), 'colis_herite': f('lg_my_parcel', ua, p_tracking=leg_num),
            'expeditions': f('lg_my_shipments', ua), 'consolidations': f('lg_my_consolidations', ua), 'paiements': f('lg_my_payments', ua), 'documents': f('lg_my_documents', ua), 'adresses': f('lg_my_addresses', ua),
            'enlevements': f('lg_my_pickups', ua), 'livraisons': f('lg_my_deliveries', ua), 'notifications': f('lg_my_notifications', ua), 'tickets': f('lg_my_tickets', ua),
            'ticket': f('lg_my_ticket', ua, p_id=t1['ticket_id']), 'factures': f('lg_my_invoices', ua), 'solde': f('lg_my_balance', ua)}
        CHEMIN_FORMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portail-formes.json')
        CHEMIN_RPC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portail-rpc.json')
        # Les signatures des fonctions que le SITE appelle : le test du navigateur (portail-contrat.cjs) s'en sert pour vérifier que chaque appel
        # du site porte des noms de paramètres qui existent, et tous les obligatoires.
        SIGNATURES = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), 'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) "
                                  "from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname = any (array[%s])" % ','.join("'%s'" % c_ for c_ in sorted(CLIENT))))
        FORMES_VUES = {k_: sorted(cles(v_)) for k_, v_ in REPONSES.items()}
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(FORMES_VUES, open(CHEMIN_FORMES, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            json.dump(SIGNATURES, open(CHEMIN_RPC, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        FORME_ATTENDUE = json.load(open(CHEMIN_FORMES, encoding='utf-8'))
        ok(sorted(FORME_ATTENDUE) == sorted(REPONSES), 'le fichier des formes couvre exactement les seize réponses')
        ok(json.load(open(CHEMIN_RPC, encoding='utf-8')) == json.loads(json.dumps(SIGNATURES)), 'les signatures des 25 fonctions du client sont celles du fichier partagé avec le test du navigateur (sinon : relancer avec SES_FORME_ECRIRE=1 et relire le changement)')
        # Les valeurs que le site doit savoir NOMMER, relevées dans la vraie base : le test du navigateur (portail-textes.cjs) exige un texte traduit pour chacune.
        def valeurs_contrainte(table, colonne):
            defs = ' '.join(cl.lignes(B, "select pg_get_constraintdef(c.oid) from pg_constraint c where c.conrelid = 'logistics.%s'::regclass and c.contype = 'c'" % table))
            m_ = re.search(r"%s\s*=\s*ANY\s*\(\s*\(?ARRAY\[(.*?)\]" % colonne, defs) or re.search(r"\(%s\)::text\s*=\s*ANY\s*\(\s*\(?ARRAY\[(.*?)\]" % colonne, defs)
            return sorted(set(re.findall(r"'([A-Za-z_]+)'::text", m_.group(1)))) if m_ else []
        ENUMS = {
            'stage': sorted(set(ETAPE.values()) | set(ETAPE_EXP.values())),
            'event': cl.lignes(B, "select code from logistics.event_type where customer_visible and code <> 'ParcelStatusChanged' order by code"),
            'invoice_status': cl.lignes(B, "select code from logistics.invoice_status where code <> 'DRAFT' order by code"),
            'quote_status': [x_ for x_ in valeurs_contrainte('quote', 'status') if x_ != 'CANCELLED'],
            'consolidation_status': valeurs_contrainte('consolidation', 'status'),
            'method': valeurs_contrainte('payment', 'method'),
            'line_kind': valeurs_contrainte('invoice_item', 'kind'),
            'window': valeurs_contrainte('pickup_request', 'preferred_window'),
            'category': valeurs_contrainte('support_ticket', 'category'),
            'ticket_status': valeurs_contrainte('support_ticket', 'status'),
            'service_mode': cl.lignes(B, "select code from logistics.transport_mode order by code"),
            'incident': ['CUSTOMER_ABSENT', 'WRONG_ADDRESS', 'DAMAGED', 'REFUSED', 'VEHICLE_PROBLEM', 'PAYMENT_PROBLEM', 'OTHER'],
            'request_stage': sorted({q("select logistics.pickup_stage(%s, %s)" % (val(a_), val(b_))) for (a_, b_) in PS} | {q("select logistics.delivery_stage(%s, %s)" % (val(a_), val(b_))) for (a_, b_) in DS}),
            'customs': ['cleared', 'processing', 'rejected'],
            'document_kind': sorted({d_['kind'] for d_ in REPONSES['documents']} | {'INVOICE', 'CREDIT_NOTE', 'QUOTE', 'DELIVERY_RECEIPT'}),
        }
        ok(all(ENUMS[k_] for k_ in ENUMS), 'chaque famille de valeurs est relevée dans la base : %s' % {k_: len(v_) for k_, v_ in ENUMS.items()})
        CHEMIN_ENUMS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'portail-enums.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(ENUMS, open(CHEMIN_ENUMS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        ok(json.load(open(CHEMIN_ENUMS, encoding='utf-8')) == json.loads(json.dumps(ENUMS)), 'les valeurs que le site doit nommer sont celles du fichier partagé avec le test du navigateur (sinon : SES_FORME_ECRIRE=1)')
        for k_, attendu in FORME_ATTENDUE.items():
            vu = sorted(cles(REPONSES[k_]))
            ok(vu == attendu, 'LA FORME de « %s » a changé. En plus : %s. En moins : %s. (Une clé de plus peut être une fuite : à relire avant d\'accepter.)' % (k_, sorted(set(vu) - set(attendu)), sorted(set(attendu) - set(vu))))
        interdits_forme = ('actor', 'author_user', 'created_by', 'reviewed_by', 'organization', 'auth_user', 'otp_hash', 'otp_salt', 'legacy', 'email', 'password', 'latitude', 'longitude', 'metadata', 'correlation', 'location_text', 'warehouse', 'driver', 'internal')
        ok(not [c_ for v_ in FORME_ATTENDUE.values() for c_ in v_ if any(m_ in c_.lower() for m_ in interdits_forme)], 'aucune clé, dans aucune réponse, ne porte un nom interne (acteur, auteur, entrepôt, chauffeur, GPS, e-mail, empreinte…)')
        ok(not [c_ for v_ in FORME_ATTENDUE.values() for c_ in v_ if c_.split('.')[-1] in ('parcel_id', 'shipment_id', 'ref', 'invoice_id', 'message_id')], 'et aucun identifiant interne inutile (parcel_id, shipment_id, invoice_id, ref) : seuls les identifiants dont le client a besoin pour AGIR (adresse, demande, ticket, notification) sortent')
        for nom_, rep_ in REPONSES.items():
            for mot in INTERDITS + ['N-004', 'N-005', 'Adresse secrète de B', 'colis secret de B', 'client10@essai.test', 'client1@essai.test']:
                ok(mot not in texte(rep_), 'la réponse « %s » ne contient jamais « %s »' % (nom_, mot))

    print('%d vérifications — phase 11 (portail client) : OK' % N[0])


if __name__ == '__main__':
    main()
