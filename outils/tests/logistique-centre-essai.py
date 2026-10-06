#!/usr/bin/env python3
"""Noyau logistique, phase 12 : le centre de commande des opérations — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-centre-essai.py

Jamais la production. Ce qu'on éprouve : (1) chaque chiffre du tableau de bord est calculé ICI par un second chemin, sur les tables, et doit
être identique à celui que la base renvoie ; (2) chaque rôle ne voit que ce que ses droits ouvrent, et un client, un visiteur ou un compte sans
droit n'obtient JAMAIS rien — même avec des paramètres invalides, le droit se vérifie avant tout ; (3) les filtres (période, pays, ville, entrepôt,
statut, service, client) filtrent vraiment, se combinent, et un filtre inconnu est une erreur ; (4) l'équipe traite les demandes et le support, et
chaque action laisse sa trace dans l'audit et son événement ; (5) la FORME de chaque réponse est figée."""
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
        # Du personnel de plusieurs sortes, ajouté AVANT le rattrapage : un chauffeur (sans droit), une caissière (factures), un agent de support (clients),
        # un compte sans aucun droit, un lecteur (colis en lecture seule).
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) "
          "select '00000000-0000-0000-0000-000000000000', ('00000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid, 'authenticated', 'authenticated', "
          "(array['chauffeur', 'caisse', 'support', 'vide', 'lecteur'])[i - 20] || i || '@essai.test', '$2a$10$fictif', now(), jsonb_build_object('nom_complet', 'Personnel ' || i, 'pays', 'Haïti', 'ville', 'Delmas', 'adresse', 'x', 'telephone', '+509 3000', 'langue', 'fr') "
          "from generate_series(21, 25) i")
        q("update public.clients set role = 'employe', droits = '{}' where email in ('chauffeur21@essai.test', 'vide24@essai.test')")
        q("update public.clients set role = 'employe', droits = array['factures.lire'] where email = 'caisse22@essai.test'")
        q("update public.clients set role = 'employe', droits = array['clients.lire'] where email = 'support23@essai.test'")
        q("update public.clients set role = 'employe', droits = array['colis.lire'] where email = 'lecteur25@essai.test'")
        # (un compte d'équipe qui porte encore un colis, comme avant la règle « équipe ≠ clientèle » : le déclencheur est suspendu le temps de l'insertion)
        q("alter table public.colis disable trigger verifier_client_colis; alter table public.factures disable trigger verifier_client_facture")
        q("insert into public.colis (client_id, description, destinataire, poids_lb, tarif_lb, service, pays_destination, statut) "
          "select id, 'colis hérité d''un compte d''équipe', 'x', 3, 2, 'aerien', 'HT', 'confirme' from public.clients where email = 'client4@essai.test'")
        q("alter table public.colis enable trigger verifier_client_colis; alter table public.factures enable trigger verifier_client_facture")
        avant_legacy = P.empreintes_historiques(cl, B)
        for f_ in ('008-portail-client', '009-centre-de-commande'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f_))
        compte = lambda: tuple(q('select count(*) from logistics.%s' % t) for t in ('event_type',))   # noqa: E731
        c1 = compte()
        for f_ in ('008-portail-client', '009-centre-de-commande'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f_))
        ok(c1 == compte(), '008 et 009 rejouées : aucune ligne en double')
        ok(avant_legacy == P.empreintes_historiques(cl, B), 'les anciennes tables n\'ont pas bougé d\'un octet')
        q('select logistics.backfill_from_legacy()')
        ok(q("select count(*) from logistics.reconcile_with_legacy()") == '0', 'la réconciliation avec l\'ancien schéma est à 0 écart')

        uid = lambda n: q("select id from public.clients where email = 'client%d@essai.test'" % n)   # noqa: E731
        admin, gerant, op, ua, ub, uc = uid(1), uid(2), uid(3), uid(9), uid(10), uid(11)
        mail = lambda m: q("select id from public.clients where email = '%s@essai.test'" % m)   # noqa: E731
        drv_u, caisse, soutien, vide, lecteur = mail('chauffeur21'), mail('caisse22'), mail('support23'), mail('vide24'), mail('lecteur25')
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

        # ============================================================== A2. le décor propre au centre de commande
        # Un troisième site (Saint-Domingue) ; trois expéditions de plus : une en retard sur son vol, une en douane, une prête ; des livraisons du jour,
        # en cours et en retard ; un incident grave et un incident sans gravité ; des scans acceptés et refusés ; des demandes des clients ; du support.
        q("insert into logistics.branch (organization_id, code, name, kind, country, city) values ('%s', 'SDQ', 'Hub Saint-Domingue', 'hub', 'DO', 'Santo Domingo')" % org)
        sdq = q("select id from logistics.branch where code = 'SDQ'")
        q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'SDQ-1', 'Entrepôt Saint-Domingue')" % sdq)
        wsdq = q("select id from logistics.warehouse where code = 'SDQ-1'")
        q("insert into logistics.transport (mode, carrier, reference, origin_branch_id, destination_branch_id, planned_departure_at, planned_arrival_at) "
          "values ('air', 'Compagnie fictive', 'YY456', '%s', '%s', now() - interval '3 days', now() - interval '1 day'), "
          "('sea', 'Armateur fictif', 'ZZ789', '%s', '%s', now() - interval '5 days', now() + interval '4 days')" % (mia, sdq, mia, sdq))
        vol2, vol3 = q("select id from logistics.transport where reference = 'YY456'"), q("select id from logistics.transport where reference = 'ZZ789'")
        x1, x2, x3 = nat(cb, 'CONSOLIDATION_PENDING', 5, 'colis pour Saint-Domingue'), nat(ca, 'CONSOLIDATION_PENDING', 6, 'colis maritime pour Saint-Domingue'), nat(ca, 'CONSOLIDATION_PENDING', 2, 'colis prêt à partir')
        q("update logistics.parcel set destination_country = 'DO', destination_city = 'Santo Domingo', service_mode = 'air' where id = '%s'" % x1)
        q("update logistics.parcel set destination_country = 'DO', destination_city = 'Santiago', service_mode = 'sea' where id = '%s'" % x2)
        sh2 = f('lg_create_shipment', admin, p_code='SHP-002', p_mode='air', p_origin_branch=mia, p_destination_branch=sdq, p_consolidation_ids=[], p_parcel_ids=[x1])['shipment_id']
        sh3 = f('lg_create_shipment', admin, p_code='SHP-003', p_mode='sea', p_origin_branch=mia, p_destination_branch=sdq, p_consolidation_ids=[], p_parcel_ids=[x2])['shipment_id']
        sh4 = f('lg_create_shipment', admin, p_code='SHP-004', p_mode='air', p_origin_branch=mia, p_destination_branch=pap, p_consolidation_ids=[], p_parcel_ids=[x3])['shipment_id']
        for s_ in (sh2, sh3, sh4):
            f('lg_generate_manifest', admin, p_shipment_id=s_); f('lg_mark_shipment_ready', admin, p_shipment_id=s_)
        f('lg_dispatch_shipment', admin, p_shipment_id=sh2, p_transport_id=vol2, p_idempotency_key='d2'); f('lg_mark_shipment_in_transit', admin, p_shipment_id=sh2)
        f('lg_dispatch_shipment', admin, p_shipment_id=sh3, p_transport_id=vol3, p_idempotency_key='d3'); f('lg_mark_shipment_in_transit', admin, p_shipment_id=sh3)
        f('lg_arrive_shipment', admin, p_shipment_id=sh3); f('lg_start_customs', admin, p_shipment_id=sh3, p_reference='DEC-3', p_broker='Courtier DO')
        # une cinquième expédition, arrivée mais pas encore en douane (sur son propre transport, dans les temps)
        q("insert into logistics.transport (mode, carrier, reference, origin_branch_id, destination_branch_id, planned_departure_at, planned_arrival_at) "
          "values ('air', 'Compagnie fictive', 'WW000', '%s', '%s', now() - interval '1 day', now() + interval '1 day')" % (mia, pap))
        vol4 = q("select id from logistics.transport where reference = 'WW000'")
        x5 = nat(ca, 'CONSOLIDATION_PENDING', 2, 'colis arrivé sans dossier de douane')
        sh5 = f('lg_create_shipment', admin, p_code='SHP-005', p_mode='air', p_origin_branch=mia, p_destination_branch=pap, p_consolidation_ids=[], p_parcel_ids=[x5])['shipment_id']
        f('lg_generate_manifest', admin, p_shipment_id=sh5); f('lg_mark_shipment_ready', admin, p_shipment_id=sh5)
        f('lg_dispatch_shipment', admin, p_shipment_id=sh5, p_transport_id=vol4, p_idempotency_key='d5'); f('lg_mark_shipment_in_transit', admin, p_shipment_id=sh5)
        f('lg_arrive_shipment', admin, p_shipment_id=sh5)
        # les livraisons : une en retard (prévue il y a deux jours), une en cours, une du jour pas encore attribuée
        p_late, p_prog, p_today = (nat(ca, 'AT_DESTINATION_HUB', 2, 'colis %s' % n_) for n_ in ('en retard', 'en cours', 'du jour'))
        dl_late = f('lg_create_delivery', admin, p_parcel_ids=[p_late], p_hub_branch=pap, p_scheduled_for=R("current_date"), p_recipient_name='Retardataire', p_address='9 rue Lente, Delmas')
        q("update logistics.task set scheduled_date = current_date - 2 where id = '%s'" % dl_late['task_id'])
        dl_prog = f('lg_create_delivery', admin, p_parcel_ids=[p_prog], p_hub_branch=pap, p_scheduled_for=R("current_date"), p_recipient_name='En cours', p_address='3 rue Vive, Pétion-Ville')
        f('lg_assign_task', admin, p_task_id=dl_prog['task_id'], p_driver_id=drv, p_force=True, p_reason='essai'); f('lg_accept_task', drv_u, p_task_id=dl_prog['task_id']); f('lg_start_task', drv_u, p_task_id=dl_prog['task_id'])
        dl_today = f('lg_create_delivery', admin, p_parcel_ids=[p_today], p_hub_branch=pap, p_scheduled_for=R("current_date"), p_recipient_name='Du jour', p_address='1 rue Neuve, Delmas')
        f('lg_update_driver_position', drv_u, p_latitude=18.54, p_longitude=-72.33)
        f('lg_set_availability', admin, p_driver=drv, p_starts=R("now() - interval '1 hour'"), p_ends=R("now() + interval '5 hours'"), p_available=True)
        # des incidents et des scans
        inc_haut = f('lg_report_incident', admin, p_type='DAMAGED', p_parcel_id=a2, p_description='emballage éventré', p_severity='HIGH', p_warehouse_id=wmia)
        inc_bas = f('lg_report_incident', admin, p_type='OTHER', p_parcel_id=b2, p_description='étiquette décollée', p_severity='LOW', p_warehouse_id=wmia)
        q("update logistics.incident set status = 'RESOLVED', resolved_at = now(), resolution = 'réétiqueté' where id = '%s'" % inc_bas)
        f('lg_scan_parcel', admin, p_code='N-002', p_purpose='lookup', p_warehouse_id=wmia, p_code_kind='barcode')
        f('lg_scan_parcel', admin, p_code='INCONNU-1', p_purpose='lookup', p_warehouse_id=wmia, p_code_kind='manual')
        # les demandes des clients (par la vraie porte du portail) et le support
        DEMAIN, DANS3, DANS9 = q("select (current_date + 1)::text"), q("select (current_date + 3)::text"), q("select (current_date + 9)::text")
        adr_ht = f('lg_save_address', ua, p_country='HT', p_address='12 rue des Fleurs', p_city='Pétion-Ville', p_label='Maison')
        adr_do = f('lg_save_address', ub, p_country='DO', p_address='Calle El Conde 5', p_city='Santo Domingo')
        pk_a = f('lg_request_pickup', ua, p_preferred_date=DANS3, p_parcels_expected=2, p_address_id=adr_ht['address_id'], p_window='MORNING', p_notes='Sonner deux fois')
        pk_b = f('lg_request_pickup', ub, p_preferred_date=DEMAIN, p_parcels_expected=1, p_address_id=adr_do['address_id'])
        pk_c = f('lg_request_pickup', ua, p_preferred_date=DANS9, p_parcels_expected=4, p_address='5 rue du Code', p_city='Delmas', p_country='HT')
        hub_libres = cl.lignes(B, "select tracking_number from logistics.parcel p where customer_id = '%s' and status = 'AT_DESTINATION_HUB' and not exists (select 1 from logistics.delivery_parcel dp where dp.parcel_id = p.id) order by tracking_number" % ca)
        dr_a = f('lg_request_delivery', ua, p_tracking_numbers=hub_libres[:2], p_preferred_date=DANS3, p_address_id=adr_ht['address_id'], p_window='AFTERNOON')
        dr_b = f('lg_request_delivery', ua, p_tracking_numbers=hub_libres[2:3], p_preferred_date=DANS9, p_address='1 rue Libre', p_city='Jacmel', p_country='HT')
        tk_1 = f('lg_open_ticket', ua, p_subject='Mon colis N-001', p_category='PARCEL', p_body='Où est-il ?', p_tracking='N-001')
        tk_2 = f('lg_open_ticket', ub, p_subject='Facture inexacte', p_category='INVOICE', p_body='Le total ne correspond pas.')
        tk_3 = f('lg_open_ticket', ua, p_subject='Question générale', p_category='OTHER', p_body='Bonjour')
        # une zone avec ses villes, rattachée au chauffeur ; un deuxième chauffeur (en congé) ; un enlèvement créé par le personnel, sans demande
        zone_pv = q("select id from logistics.delivery_zone where code = 'PV'")
        q("update logistics.delivery_zone set cities = array['Pétion-Ville', 'Delmas'] where id = '%s'" % zone_pv)
        f('lg_set_driver_zones', admin, p_driver=drv, p_zone_ids=[zone_pv])
        drv2 = f('lg_create_driver', admin, p_user_id=vide, p_full_name='Chauffeur Deux', p_phone='+509 3222 2222')
        q("update logistics.driver set status = 'ON_LEAVE' where id = '%s'" % drv2)
        task_staff = f('lg_create_pickup_task', admin, p_customer_id=ca, p_address='Enlèvement demandé par téléphone', p_scheduled_date=R("current_date + 2"), p_parcels_expected=3)['task_id']
        # de quoi éprouver les cas limites des indicateurs
        p_canc, p_win, x4 = nat(ca, 'AT_DESTINATION_HUB', 2, 'colis dont la livraison est annulée'), nat(ca, 'AT_DESTINATION_HUB', 2, 'colis dont la fenêtre est passée'), nat(cb, 'CONSOLIDATION_PENDING', 1, 'colis retiré de la consolidation')
        dl_canc = f('lg_create_delivery', admin, p_parcel_ids=[p_canc], p_hub_branch=pap, p_scheduled_for=R("current_date"), p_recipient_name='Annulée', p_address='7 rue Close, Delmas')
        f('lg_assign_task', admin, p_task_id=dl_canc['task_id'], p_driver_id=drv, p_force=True, p_reason='essai'); f('lg_cancel_task', admin, p_task_id=dl_canc['task_id'], p_reason='le client a annulé')
        dl_win = f('lg_create_delivery', admin, p_parcel_ids=[p_win], p_hub_branch=pap, p_scheduled_for=R("current_date"), p_recipient_name='Fenêtre passée', p_address='8 rue Heure, Delmas',
                   p_window_start=R("now() - interval '3 hours'"), p_window_end=R("now() - interval '1 hour'"))
        f('lg_add_parcel_to_consolidation', admin, p_consolidation_id=cons_open, p_parcel_id=x4); f('lg_remove_parcel_from_consolidation', admin, p_consolidation_id=cons_open, p_parcel_id=x4)
        q("update logistics.transport set planned_arrival_at = now() - interval '1 day' where reference = 'XX123'")
        f('lg_set_availability', admin, p_driver=drv2, p_starts=R("now() - interval '1 hour'"), p_ends=R("now() + interval '5 hours'"), p_available=False)
        # du revenu d'autres jours : hier, le dernier jour du mois précédent, l'an dernier
        q("insert into logistics.revenue_entry (invoice_id, entry_date, category, net_amount, currency, net_base_usd, correlation_id) values "
          "('%s', current_date - 1, 'FREIGHT', 50, 'USD', 50, gen_random_uuid()), ('%s', (date_trunc('month', current_date) - interval '1 day')::date, 'FREIGHT', 100, 'USD', 100, gen_random_uuid()), "
          "('%s', (current_date - interval '1 year')::date, 'FREIGHT', 1000, 'USD', 1000, gen_random_uuid())" % (inv_a, inv_a, inv_a))
        # une facture payée puis remboursée en entier, une facture échue
        inv_c = f('lg_invoice_from_quote', admin, p_quote=qa4['quote_id'], p_issue=True)['invoice_id']
        pay_c = f('lg_record_payment', admin, p_invoice=inv_c, p_amount=q("select total from logistics.invoice where id = '%s'" % inv_c), p_method='CASH')
        f('lg_issue_credit_note', admin, p_invoice=inv_c, p_amount=q("select total from logistics.invoice where id = '%s'" % inv_c), p_reason='avoir intégral')
        f('lg_refund_payment', admin, p_payment=pay_c['payment_id'], p_amount=q("select total from logistics.invoice where id = '%s'" % inv_c), p_reason='remboursement intégral', p_method='CASH')
        f('lg_mark_overdue', admin, p_date=R("current_date + 60"))

        # ============================================================== B. QUI VOIT QUOI : la matrice des droits, écrite ICI une seconde fois
        COMMANDE = ['commande']
        OPS = ['flux', 'colis', 'expeditions', 'entrepot', 'consolidations', 'transport', 'chauffeurs', 'enlevements', 'livraisons', 'douane', 'incidents', 'notifications']
        CLI, FIN, DIR = ['clients', 'support'], ['facturation', 'paiements'], ['utilisateurs', 'audit', 'parametres']
        DROIT = {'lg_cc_flow': 'ops', 'lg_cc_parcels': 'ops', 'lg_cc_shipments': 'ops', 'lg_cc_warehouse': 'ops', 'lg_cc_consolidations': 'ops', 'lg_cc_transports': 'ops', 'lg_cc_drivers': 'ops',
                 'lg_cc_pickups': 'ops', 'lg_cc_deliveries': 'ops', 'lg_cc_customs': 'ops', 'lg_cc_incidents': 'ops', 'lg_cc_notifications': 'ops',
                 'lg_cc_customers': 'cli', 'lg_cc_tickets': 'cli', 'lg_cc_invoices': 'fin', 'lg_cc_payments': 'fin', 'lg_cc_users': 'dir', 'lg_cc_audit': 'dir', 'lg_cc_settings': 'dir'}
        ok(len(DROIT) == 19, 'dix-neuf lectures filtrables par un droit')
        PERSONNEL = {'admin': (admin, {'ops', 'cli', 'fin', 'dir', 'statut'}), 'gerant': (gerant, {'ops', 'cli', 'fin', 'dir', 'statut'}), 'employé colis (lire + statut)': (op, {'ops', 'statut'}),
                     'lecteur (colis en lecture)': (lecteur, {'ops'}), 'caisse (factures)': (caisse, {'fin'}), 'support (clients)': (soutien, {'cli'})}
        FERMES = {'compte sans aucun droit': vide, 'chauffeur': drv_u, 'client A': ua, 'client B': ub}

        def sections_de(dr):
            return COMMANDE + (OPS if 'ops' in dr else []) + (CLI if 'cli' in dr else []) + (FIN if 'fin' in dr else []) + (DIR if 'dir' in dr else [])

        for nom_, (u_, dr_) in PERSONNEL.items():
            acc = f('lg_cc_access', u_)
            ok(acc['sections'] == sections_de(dr_), '%s : voit exactement les sections %s' % (nom_, sections_de(dr_)))
            ok(acc['direction'] is ('dir' in dr_) and acc['ops'] is ('ops' in dr_) and acc['finance'] is ('fin' in dr_) and acc['customers'] is ('cli' in dr_), '%s : les quatre drapeaux d\'accès sont justes' % nom_)
            ok(acc['today'] == q("select (now() at time zone 'America/Port-au-Prince')::date::text"), '%s : « aujourd\'hui » est la date d\'Haïti' % nom_)
        ok(f('lg_cc_access', admin)['role'] == 'admin' and f('lg_cc_access', gerant)['role'] == 'manager' and f('lg_cc_access', op)['role'] == 'employee', 'le rôle est rendu tel que la base le tient')
        for nom_, u_ in FERMES.items():
            fr('lg_cc_access', 'LG003', '%s : le centre de commande reste fermé' % nom_, u_)
        code, texte_ = cl.run(B, appel('lg_cc_access'), role='authenticated', expect_error=True)
        ok(code != 0 and 'LG003' in texte_, 'connecté sans jeton valide (aucun auth.uid()) : fermé')
        code, texte_ = cl.run(B, appel('lg_cc_access'), role='anon', expect_error=True)
        ok(code != 0 and ('permission denied' in texte_ or '42501' in texte_), 'un visiteur anonyme n\'appelle rien')
        # « direction » ne se donne pas à un employé, même écrit dans ses droits
        q("update logistics.app_user set rights = array['colis.lire', 'direction'] where id = '%s'" % lecteur)
        ok(f('lg_cc_access', lecteur)['sections'] == COMMANDE + OPS and f('lg_cc_access', lecteur)['direction'] is False, 'un employé qui a « direction » dans ses droits ne l\'a pas pour autant : ni utilisateurs, ni audit, ni réglages')
        fr('lg_cc_audit', 'LG003', 'et le journal d\'audit lui reste fermé', lecteur)
        q("update logistics.app_user set rights = array['colis.lire'] where id = '%s'" % lecteur)
        # un compte désactivé ne passe plus nulle part
        q("update logistics.app_user set active = false where id = '%s'" % soutien)
        fr('lg_cc_access', 'LG003', 'un compte du personnel désactivé', soutien)
        fr('lg_cc_tickets', 'LG003', 'et ses tickets de support lui sont fermés', soutien)
        q("update logistics.app_user set active = true where id = '%s'" % soutien)
        ok(f('lg_cc_access', soutien)['sections'] == COMMANDE + CLI, 'réactivé : il retrouve ses sections')

        # --- chaque lecture, chaque rôle : ouverte si et seulement si le droit y est (et un refus est TOUJOURS LG003)
        LECTURES = {'lg_cc_flow': {}, 'lg_cc_parcels': {}, 'lg_cc_shipments': {}, 'lg_cc_warehouse': {}, 'lg_cc_consolidations': {}, 'lg_cc_transports': {}, 'lg_cc_drivers': {}, 'lg_cc_pickups': {},
                    'lg_cc_deliveries': {}, 'lg_cc_customs': {}, 'lg_cc_incidents': {}, 'lg_cc_notifications': {}, 'lg_cc_customers': {}, 'lg_cc_tickets': {}, 'lg_cc_invoices': {}, 'lg_cc_payments': {},
                    'lg_cc_users': {}, 'lg_cc_audit': {}, 'lg_cc_settings': {}}
        ok(sorted(LECTURES) == sorted(DROIT), 'la matrice couvre exactement les dix-neuf lectures')
        n_ouvertes = n_fermees = 0
        for nom_, (u_, dr_) in PERSONNEL.items():
            for fn_, kw_ in LECTURES.items():
                code, texte_ = cl.run(B, appel(fn_, **kw_), role='authenticated', claims=u_, expect_error=True)
                if DROIT[fn_] in dr_:
                    ok(code == 0, '%s ouvre %s (droit « %s ») : %s' % (nom_, fn_, DROIT[fn_], texte_[-160:].replace('\n', ' ')))
                    n_ouvertes += 1
                else:
                    ok(code != 0 and 'LG003' in texte_, '%s n\'ouvre PAS %s (droit « %s » exigé) : %s' % (nom_, fn_, DROIT[fn_], texte_[-160:].replace('\n', ' ')))
                    n_fermees += 1
        ok(n_ouvertes + n_fermees == 6 * 19 and n_ouvertes > 40 and n_fermees > 40, 'six rôles × dix-neuf lectures : %d ouvertes, %d refusées' % (n_ouvertes, n_fermees))
        # --- la porte se ferme AVANT tout : un client, un compte sans droit, un visiteur — même avec des filtres invalides ou un identifiant réel
        MAUVAIS = {'p_filters': R("'{\"pays\": \"x\"}'::jsonb")}
        pk_id, tk_id = pk_a['pickup_id'], tk_1['ticket_id']
        FERMEES = [(fn_, dict(MAUVAIS) if fn_ != 'lg_cc_settings' else {}) for fn_ in list(LECTURES) + ['lg_cc_kpis']] + [('lg_cc_kpis', {}), ('lg_cc_attention', {}), ('lg_cc_parcel', dict(p_tracking='N-001')), ('lg_cc_ticket', dict(p_id=tk_id)),
                   ('lg_cc_review_pickup', dict(p_id=pk_id, p_approve=True)), ('lg_cc_review_pickup', dict(p_id=pk_id, p_approve=False, p_message='non')), ('lg_cc_review_delivery', dict(p_id=dr_a['request_id'], p_approve=True)),
                   ('lg_cc_review_delivery', dict(p_id=dr_a['request_id'], p_approve=False, p_message='non')), ('lg_cc_reply_ticket', dict(p_id=tk_id, p_body='réponse')), ('lg_cc_close_ticket', dict(p_id=tk_id))]
        for nom_, u_ in FERMES.items():
            for fn_, kw_ in FERMEES:
                fr(fn_, 'LG003', '%s appelle %s : refusé, quels que soient les paramètres' % (nom_, fn_), u_, **kw_)
        for fn_, kw_ in FERMEES:
            code, texte_ = cl.run(B, appel(fn_, **kw_), role='anon', expect_error=True)
            ok(code != 0 and ('permission denied' in texte_ or '42501' in texte_), 'un visiteur anonyme appelle %s : refusé' % fn_)
        # les détails et les écritures, rôle par rôle
        for nom_, (u_, dr_) in PERSONNEL.items():
            for fn_, kw_, besoin, etat_ouvert in (('lg_cc_parcel', dict(p_tracking='ZZZ-INCONNU'), 'ops', 'LG002'), ('lg_cc_ticket', dict(p_id=R("gen_random_uuid()")), 'cli', 'LG002'),
                                                   ('lg_cc_review_pickup', dict(p_id=R("gen_random_uuid()"), p_approve=True), 'statut', 'LG002'), ('lg_cc_review_delivery', dict(p_id=R("gen_random_uuid()"), p_approve=True), 'statut', 'LG002'),
                                                   ('lg_cc_reply_ticket', dict(p_id=R("gen_random_uuid()"), p_body='x'), 'cli', 'LG002'), ('lg_cc_close_ticket', dict(p_id=R("gen_random_uuid()")), 'cli', 'LG002')):
                fr(fn_, etat_ouvert if besoin in dr_ else 'LG003', '%s appelle %s (droit « %s ») : %s' % (nom_, fn_, besoin, 'la porte s\'ouvre, la recherche échoue' if besoin in dr_ else 'refusé'), u_, **kw_)
        for nom_, (u_, dr_) in PERSONNEL.items():
            acc_k = f('lg_cc_kpis', u_)
            ok((acc_k['operations'] is not None) == ('ops' in dr_) and (acc_k['money'] is not None) == ('fin' in dr_) and (acc_k['support'] is not None) == ('cli' in dr_), '%s : les indicateurs ne contiennent que les blocs de ses droits' % nom_)
            att_k = {i_['kind'] for i_ in f('lg_cc_attention', u_)['items']}
            ATT_OPS = {'pickup_requests', 'delivery_requests', 'deliveries_delayed', 'incidents_high', 'parcels_on_hold', 'shipments_late'}
            ok(att_k <= ((ATT_OPS if 'ops' in dr_ else set()) | ({'tickets_waiting'} if 'cli' in dr_ else set()) | ({'invoices_overdue'} if 'fin' in dr_ else set())), '%s : la file « à traiter » ne contient que ses genres de tâches : %s' % (nom_, sorted(att_k)))

        # ============================================================== C. LES INDICATEURS : chaque chiffre, recalculé ICI sur les tables
        JOUR = "((now() at time zone 'America/Port-au-Prince')::date)"
        T0 = "(%s::timestamp at time zone 'America/Port-au-Prince')" % JOUR
        n_ = lambda sql: int(q(sql))   # noqa: E731

        def attendu(pays=None, service=None, entrepot=None, client=None, ville=None):
            """Les indicateurs de l'équipe d'après les tables, par un chemin sans aucune des fonctions du centre de commande."""
            pw, sw, cw, rw = ['true'], ['true'], ['true'], ['true']
            if pays:
                pw.append("p.destination_country = '%s'" % pays); sw.append("(select b.country from logistics.branch b where b.id = s.destination_branch_id) = '%s'" % pays); cw.append("c.destination_country = '%s'" % pays); rw.append("r.country = '%s'" % pays)
            if service:
                pw.append("p.service_mode = '%s'" % service); sw.append("s.mode = '%s'" % service); cw.append("c.mode = '%s'" % service)
            if entrepot:
                pw.append("p.current_warehouse_id = '%s'" % entrepot); cw.append("c.warehouse_id = '%s'" % entrepot)
            if client:
                pw.append("(cu.code = upper('%s') or lower(cu.email) = lower('%s') or lower(cu.full_name) like '%%' || lower('%s') || '%%')" % (client, client, client))
                rw.append("(cu.code = upper('%s') or lower(cu.email) = lower('%s') or lower(cu.full_name) like '%%' || lower('%s') || '%%')" % (client, client, client))
            if ville:
                pw.append("lower(p.destination_city) like '%%' || lower('%s') || '%%'" % ville); rw.append("lower(r.city) like '%%' || lower('%s') || '%%'" % ville)
            parcels = "select p.id from logistics.parcel p left join logistics.customer cu on cu.id = p.customer_id where " + ' and '.join(pw)
            filtre_colis = bool(entrepot or client or ville or pays or service)
            # les expéditions et les consolidations : par leur propre pays/mode, et par leurs colis pour l'entrepôt, le client et la ville
            sparc = ' and '.join(w_ for w_ in ["true"] + (["p.current_warehouse_id = '%s'" % entrepot] if entrepot else []) + (["(cu.code = upper('%s') or lower(cu.email) = lower('%s') or lower(cu.full_name) like '%%' || lower('%s') || '%%')" % (client, client, client)] if client else [])
                                    + (["lower(p.destination_city) like '%%' || lower('%s') || '%%'" % ville] if ville else []))
            par_colis = bool(entrepot or client or ville)
            shw = ' and '.join(sw) + (" and exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id left join logistics.customer cu on cu.id = p.customer_id where %s)" % sparc if par_colis else '')
            cow = ' and '.join(cw) + (" and exists (select 1 from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id left join logistics.customer cu on cu.id = p.customer_id where cp.consolidation_id = c.id and cp.removed_at is null and %s)" % sparc if (client or ville) else '')
            ship = lambda st: n_("select count(*) from logistics.shipment s where s.status in (%s) and %s" % (st, shw))   # noqa: E731
            tasks = "select t.id from logistics.task t where t.kind = 'DELIVERY' " + ("and exists (select 1 from logistics.delivery_parcel dp where dp.delivery_id = t.delivery_id and dp.parcel_id in (%s))" % parcels if filtre_colis else '')
            inc = "select i.id from logistics.incident i where i.status in ('OPEN', 'IN_PROGRESS') " + ("and i.parcel_id in (%s)" % parcels if filtre_colis else '')
            return {
                'parcels_received_today': n_("select count(*) from logistics.tracking_event e where e.event_type = 'ParcelReceived' and e.occurred_at >= %s and e.parcel_id in (%s)" % (T0, parcels)),
                'parcels_in_warehouse': n_("select count(*) from logistics.parcel p where p.id in (%s) and p.status in ('RECEIVED','VERIFIED','STORED','CONSOLIDATION_PENDING','CONSOLIDATED','READY_FOR_EXPORT')" % parcels),
                'parcels_at_hub': n_("select count(*) from logistics.parcel p where p.id in (%s) and p.status = 'AT_DESTINATION_HUB'" % parcels),
                'parcels_on_hold': n_("select count(*) from logistics.parcel p where p.id in (%s) and p.status = 'ON_HOLD'" % parcels),
                'consolidations_open': n_("select count(*) from logistics.consolidation c where c.status = 'OPEN' and %s" % cow),
                'shipments_ready': ship("'READY'"), 'shipments_in_transit': ship("'DISPATCHED','IN_TRANSIT'"), 'shipments_customs': ship("'ARRIVED','CUSTOMS_PROCESSING'"),
                'deliveries_today': n_("select count(*) from logistics.task t where t.id in (%s) and t.scheduled_date = %s and t.status <> 'CANCELLED'" % (tasks, JOUR)),
                'deliveries_in_progress': n_("select count(*) from logistics.task t where t.id in (%s) and t.status = 'STARTED'" % tasks),
                'deliveries_delayed': n_("select count(*) from logistics.task t where t.id in (%s) and t.status in ('CREATED','ASSIGNED','ACCEPTED','STARTED') and (t.scheduled_date < %s or t.window_end < now())" % (tasks, JOUR)),
                'incidents_open': n_("select count(*) from (%s) x" % inc), 'incidents_high': n_("select count(*) from logistics.incident i where i.id in (%s) and i.severity = 'HIGH'" % inc),
                'pickup_requests_pending': n_("select count(*) from logistics.pickup_request r join logistics.customer cu on cu.id = r.customer_id where r.status = 'REQUESTED' and %s" % ' and '.join(rw)),
                'delivery_requests_pending': n_("select count(*) from logistics.delivery_request r join logistics.customer cu on cu.id = r.customer_id where r.status = 'REQUESTED' and %s" % ' and '.join(rw)),
            }

        def filtres(pays=None, service=None, entrepot=None, client=None, ville=None, de=None, a=None):
            d_ = {k_: v_ for k_, v_ in (('country', pays), ('service', service), ('warehouse_id', entrepot), ('customer', client), ('city', ville), ('from', de), ('to', a)) if v_}
            return R("'%s'::jsonb" % json.dumps(d_).replace("'", "''")) if d_ else None

        def kpi_ops(**kw):
            r_ = f('lg_cc_kpis', admin, **({'p_filters': filtres(**kw)} if filtres(**kw) is not None else {}))
            return {k_: v_ for k_, v_ in r_['operations'].items()}, r_

        base, rep = kpi_ops()
        att0 = attendu()
        ok(base == att0, 'SANS filtre : les quinze indicateurs de l\'équipe sont identiques au décompte indépendant sur les tables. Écart : %s' % {k_: (base[k_], att0.get(k_)) for k_ in base if base[k_] != att0.get(k_)})
        ok(sorted(base) == sorted(att0) and len(base) == 15, 'quinze indicateurs, ni plus ni moins : %s' % sorted(base))
        ok(rep['filters'] == {} and rep['today'] == q("select %s::text" % JOUR), 'les filtres appliqués et la date du jour sont rendus avec les chiffres')
        # les chiffres que le décor impose, écrits en dur : le test ne se contente pas de comparer deux calculs
        ok(base['shipments_ready'] == 1 and base['shipments_in_transit'] == 1 and base['shipments_customs'] == 2, 'une expédition prête (SHP-004), une en transit (SHP-002), deux en douane : SHP-003 en cours de dédouanement, SHP-005 arrivée')
        ok(base['consolidations_open'] == 1 and base['deliveries_in_progress'] == 1 and base['deliveries_delayed'] == 2, 'une consolidation ouverte, une livraison en cours, deux livraisons en retard (prévue il y a deux jours ; fenêtre d\'aujourd\'hui déjà passée)')
        ok(base['deliveries_today'] == 4, 'quatre livraisons aujourd\'hui : la remise faite (a1), celle en cours, celle pas encore attribuée et celle dont la fenêtre est passée — pas celle qui est ANNULÉE, ni celle en retard (prévue il y a deux jours), ni celle de demain')
        ok(base['incidents_open'] == 2 and base['incidents_high'] == 1, 'deux incidents ouverts (le dommage grave, et celui né du scan d\'un code inconnu, sans colis) dont un grave ; l\'incident résolu ne compte pas : %s' % base)
        ok(base['pickup_requests_pending'] == 3 and base['delivery_requests_pending'] == 2, 'trois demandes d\'enlèvement et deux demandes de livraison attendent l\'équipe')
        ok(base['parcels_received_today'] >= 1 and base['parcels_on_hold'] >= 1 and base['parcels_at_hub'] >= 6, 'des colis reçus aujourd\'hui, des colis retenus, des colis au hub')
        # chaque filtre, seul puis combiné : toujours le décompte indépendant
        wd_ = {'MIA-1': wmia, 'SDQ-1': wsdq}
        CAS = [dict(pays='DO'), dict(pays='HT'), dict(pays='US'), dict(service='sea'), dict(service='air'), dict(service='ground'), dict(entrepot=wmia), dict(entrepot=wsdq), dict(client=q("select code from logistics.customer where id = '%s'" % ca)), dict(client=q("select lower(code) from logistics.customer where id = '%s'" % ca)),
               dict(client='CLIENT10@ESSAI.TEST'), dict(client='brien'), dict(ville='santiago'), dict(ville='PÉTION'), dict(pays='DO', service='sea'), dict(pays='DO', service='air'), dict(pays='HT', client='SES'),
               dict(pays='DO', ville='santo'), dict(service='sea', ville='santiago'), dict(entrepot=wmia, pays='HT'), dict(client=q("select code from logistics.customer where id = '%s'" % cb), pays='DO')]
        diffs = 0
        for cas in CAS:
            got, _ = kpi_ops(**cas)
            exp = attendu(**cas)
            ok(got == exp, 'filtre %s : identique au décompte indépendant. Écart : %s' % (cas, {k_: (got[k_], exp.get(k_)) for k_ in got if got[k_] != exp.get(k_)}))
            diffs += 1 if got != base else 0
        ok(diffs >= 14, 'les filtres changent vraiment les chiffres (%d cas sur %d diffèrent du chiffre sans filtre) : un filtre ignoré ferait échouer ce test' % (diffs, len(CAS)))
        do_, _ = kpi_ops(pays='DO')
        ok(do_['shipments_in_transit'] == 1 and do_['shipments_customs'] == 1 and do_['shipments_ready'] == 0 and do_['pickup_requests_pending'] == 1, 'en République dominicaine : SHP-002 en transit, SHP-003 en douane, aucune prête ; une demande d\'enlèvement (celle de B)')
        ok(kpi_ops(pays='US')[0]['parcels_in_warehouse'] == 0 and kpi_ops(pays='US')[0]['shipments_in_transit'] == 0, 'États-Unis : aucun colis n\'y va, aucune expédition non plus')
        # la période : le revenu de la période suit les dates, les chiffres « du jour » non
        ok('revenue_period_usd' not in rep['money'], 'sans période demandée, pas de revenu de période')
        rev_p = lambda de_, a_: D(q("select coalesce(sum(net_base_usd), 0) from logistics.revenue_entry where %s" % ' and '.join(["true"] + (["entry_date >= %s" % de_] if de_ else []) + (["entry_date <= %s" % a_] if a_ else []))))   # noqa: E731
        kp = lambda de_=None, a_=None: f('lg_cc_kpis', admin, p_filters=R("'%s'::jsonb" % json.dumps({k_: q("select (%s)::text" % v_) for k_, v_ in (('from', de_), ('to', a_)) if v_}).replace("'", "''")))['money']['revenue_period_usd']   # noqa: E731
        ok(rev_p(None, None) == D('1000') + D('100') + D('50') + rev_p('current_date', 'current_date') and rev_p('current_date', 'current_date') > 0, 'le décor : du revenu aujourd\'hui, 50 hier, 100 le dernier jour du mois précédent, 1 000 l\'an dernier')
        ok(kp("current_date - 30", "current_date") == rev_p("current_date - 30", "current_date"), 'la période des trente derniers jours : la somme des écritures de ces jours')
        ok(kp("current_date - 1", "current_date - 1") == D('50') and kp("current_date - 1 - interval '1 year'", "current_date - interval '1 year'") == D('1000'), 'un seul jour : hier 50 USD ; l\'an dernier 1 000 USD')
        ok(kp("current_date + 1", "current_date + 9") == 0 and kp("current_date", None) == rev_p('current_date', None) and kp(None, "current_date - 2") == rev_p(None, 'current_date - 2'), 'une période dans le futur : 0 ; sans fin : depuis le début demandé ; sans début : jusqu\'à la fin demandée')
        rp2 = f('lg_cc_kpis', admin, p_filters=filtres(de=q("select (current_date - 30)::text"), a=q("select (current_date - 1)::text")))
        ok(rp2['operations'] == base, 'une période close hier : les chiffres « du jour » ne bougent pas')
        # l'argent
        money = rep['money']
        ok(money['revenue_date'] == q("select current_date::text") and D(money['revenue_today_usd']) == D(q("select coalesce(sum(net_base_usd), 0) from logistics.revenue_entry where entry_date = current_date")), 'revenu du jour : le total des écritures du jour')
        ok(D(money['revenue_month_usd']) == D(q("select coalesce(sum(net_base_usd), 0) from logistics.revenue_entry where to_char(entry_date, 'YYYY-MM') = to_char(current_date, 'YYYY-MM')")), 'revenu du mois')
        impayes = {}
        for st_, cu_, tot, cre, pai, ref_, cur in (l_.split('|') for l_ in cl.lignes(B, "select status, customer_id, total, credited_amount, paid_amount, refunded_amount, currency from logistics.invoice")):
            if st_ in ('DRAFT', 'CANCELLED'):
                continue
            b_ = (D(tot) - D(cre)) - (D(pai) - D(ref_))
            if b_ > 0:
                n0, c0, s0 = impayes.get(cur, (0, set(), D(0)))
                impayes[cur] = (n0 + 1, c0 | {cu_}, s0 + b_)
        ok({u_['currency']: (u_['invoices'], u_['customers'], D(u_['balance'])) for u_ in money['unpaid']} == {k_: (v_[0], len(v_[1]), v_[2]) for k_, v_ in impayes.items()} and len(impayes) >= 1,
           'factures impayées, par devise : nombre de factures, de clients et solde identiques au calcul indépendant (%s)' % {k_: (v_[0], len(v_[1]), v_[2]) for k_, v_ in impayes.items()})
        ok(all(u_['invoices'] >= u_['customers'] >= 1 for u_ in money['unpaid']), 'et jamais moins de factures que de clients')
        ok(money['overdue_invoices'] == n_("select count(*) from logistics.invoice where status = 'OVERDUE'"), 'factures en retard de paiement')
        ok(rep['support'] == {'tickets_open': 3, 'tickets_waiting_staff': 3}, 'support : trois tickets ouverts, trois attendent l\'équipe')
        # filtres invalides : une erreur, jamais un oubli silencieux
        for fl_, msg in (({'pays': 'HT'}, 'filtre inconnu'), ({'country': 'FR'}, 'pays inconnu'), ({'country': 'ht'}, 'pays en minuscules'), ({'service': 'teleportation'}, 'service inconnu'), ({'warehouse_id': 'pas-un-uuid'}, 'identifiant d\'entrepôt invalide'),
                         ({'from': '2026-13-45'}, 'date invalide'), ({'from': 'demain'}, 'date en toutes lettres'), ({'from': '2026-10-05', 'to': '2026-10-01'}, 'fin avant le début'), ({'city': 'x' * 81}, 'ville de 81 caractères'),
                         ({'customer': 'x' * 81}, 'client de 81 caractères'), ({'status': 'x' * 41}, 'statut de 41 caractères')):
            fr('lg_cc_kpis', 'LG005', 'filtre invalide (%s)' % msg, admin, p_filters=R("'%s'::jsonb" % json.dumps(fl_).replace("'", "''")))
        fr('lg_cc_kpis', 'LG005', 'des filtres qui ne sont pas un objet', admin, p_filters=R("'[1, 2]'::jsonb"))
        ok(f('lg_cc_kpis', admin, p_filters=R("'{}'::jsonb"))['filters'] == {} and f('lg_cc_kpis', admin, p_filters=R("'{\"city\": \"  \", \"customer\": \"\"}'::jsonb"))['filters'] == {}, 'des filtres vides ou faits d\'espaces valent « pas de filtre »')
        ok(f('lg_cc_kpis', admin, p_filters=R("'{\"country\": \" DO \"}'::jsonb"))['filters'] == {'country': 'DO'}, 'les espaces autour d\'une valeur sont retirés')
        f_dates = f('lg_cc_kpis', admin, p_filters=R("'{\"from\": \"2026-10-01\", \"to\": \"2026-10-05\"}'::jsonb"))['filters']
        ok(f_dates == {'from': '2026-10-01', 'to': '2026-10-05'}, 'les dates sont rendues au format AAAA-MM-JJ')
        ok(f('lg_cc_kpis', admin, p_filters=R("'{\"from\": \"2026-10-05\", \"to\": \"2026-10-05\"}'::jsonb"))['filters'] == {'from': '2026-10-05', 'to': '2026-10-05'}, 'un seul jour (début = fin) est une période valide')
        # filtrer par un client qui n'existe pas ne trouve rien (et n'échoue pas)
        zero, _ = kpi_ops(client='personne-ne-porte-ce-nom')
        ok(zero == attendu(client='personne-ne-porte-ce-nom') and zero['parcels_in_warehouse'] == 0 and zero['shipments_in_transit'] == 0 and zero['pickup_requests_pending'] == 0, 'un client inconnu : tout à zéro')
        ok(kpi_ops(client='%')[0]['parcels_in_warehouse'] == 0 and kpi_ops(client='_')[0]['parcels_in_warehouse'] == 0, 'les jokers « % » et « _ » sont des caractères, pas des motifs')
        # la file « à traiter » : chaque genre, son nombre et son plus ancien, recalculés sur les tables
        from datetime import datetime
        att = f('lg_cc_attention', admin)

        def instant(iso):
            # Python 3.9 n'accepte que 3 ou 6 chiffres après la virgule : PostgreSQL en écrit de 1 à 6.
            m_ = re.match(r'^(.*T\d\d:\d\d:\d\d)(?:\.(\d+))?(.*)$', iso)
            return datetime.fromisoformat(m_.group(1) + '.' + (m_.group(2) or '0').ljust(6, '0')[:6] + m_.group(3)).timestamp()
        epoch = lambda sql: (float(q(sql)) if q(sql) not in ('', None) else None)   # noqa: E731
        TACHE = "t.kind = 'DELIVERY' and t.status in ('CREATED', 'ASSIGNED', 'ACCEPTED', 'STARTED') and (t.scheduled_date < %s or t.window_end < now())" % JOUR
        ATT = [('pickup_requests', "select count(*), extract(epoch from min(created_at)) from logistics.pickup_request where status = 'REQUESTED'"),
               ('delivery_requests', "select count(*), extract(epoch from min(created_at)) from logistics.delivery_request where status = 'REQUESTED'"),
               ('deliveries_delayed', "select count(*), extract(epoch from min(case when t.window_end is not null then t.window_end else t.scheduled_date::timestamp at time zone current_setting('TimeZone') end)) from logistics.task t where %s" % TACHE),
               ('incidents_high', "select count(*), extract(epoch from min(created_at)) from logistics.incident where status in ('OPEN', 'IN_PROGRESS') and severity = 'HIGH'"),
               ('parcels_on_hold', "select count(*), extract(epoch from min(updated_at)) from logistics.parcel where status = 'ON_HOLD'"),
               ('shipments_late', "select count(*), extract(epoch from min(t.planned_arrival_at)) from logistics.shipment s join logistics.transport t on t.id = s.transport_id where s.status in ('DISPATCHED', 'IN_TRANSIT') and t.planned_arrival_at < now()"),
               ('tickets_waiting', "select count(*), extract(epoch from min(updated_at)) from logistics.support_ticket where status = 'OPEN'"),
               ('invoices_overdue', "select count(*), extract(epoch from min(due_date::timestamp at time zone current_setting('TimeZone'))) from logistics.invoice where status = 'OVERDUE'")]
        attendu_att = []
        for genre, sql_ in ATT:
            n0, e0 = q(sql_).split('|')
            if int(n0) > 0:
                attendu_att.append((genre, int(n0), float(e0)))
        ok([i_['kind'] for i_ in att['items']] == [g_[0] for g_ in attendu_att] and len(attendu_att) == 8, 'la file « à traiter » : les huit genres de tâches, dans l\'ordre de leur gravité : %s' % [i_['kind'] for i_ in att['items']])
        for item_, (genre, n0, e0) in zip(att['items'], attendu_att):
            ok(item_['count'] == n0 and abs(instant(item_['oldest_at']) - e0) < 0.01 and set(item_) == {'kind', 'count', 'oldest_at'}, 'à traiter « %s » : %d, le plus ancien à la bonne heure' % (genre, n0))
        ok({i_['kind']: i_['count'] for i_ in att['items']} == {'pickup_requests': 3, 'delivery_requests': 2, 'deliveries_delayed': 2, 'incidents_high': 1, 'parcels_on_hold': 1, 'shipments_late': 1, 'tickets_waiting': 3, 'invoices_overdue': att_over} if (att_over := n_("select count(*) from logistics.invoice where status = 'OVERDUE'")) >= 0 else False,
           'les nombres que le décor impose : 3 enlèvements, 2 livraisons demandées, 2 livraisons en retard, 1 incident grave, 1 colis retenu, 1 expédition en retard, 3 tickets')
        ok(att_over >= 1, 'au moins une facture en retard de paiement (le décor a avancé la date)')


        # ============================================================== D. LES VUES PAR DOMAINE
        def L(nom, fl=None, lim=None, off=None, who=admin, **kw):
            if fl:
                kw['p_filters'] = R("'%s'::jsonb" % json.dumps(fl).replace("'", "''"))
            if lim is not None:
                kw['p_limit'] = lim
            if off is not None:
                kw['p_offset'] = off
            return f(nom, who, **kw)

        def jour_debut(d_):
            return "(%s::date::timestamp at time zone 'America/Port-au-Prince')" % val(d_)

        def periode(col, fl):
            """La période d'un filtre, en SQL, écrite ICI : début du jour de « from » (inclus), début du lendemain de « to » (exclu)."""
            c_ = []
            if fl.get('from'):
                c_.append("%s >= %s" % (col, jour_debut(fl['from'])))
            if fl.get('to'):
                c_.append("%s < (%s + interval '1 day')" % (col, jour_debut(fl['to'])))
            return ' and '.join(c_) or 'true'

        def client_sql(client, alias='cu'):
            v_ = val(client)
            return "(%s.code = upper(%s) or lower(%s.email) = lower(%s) or strpos(lower(%s.full_name), lower(%s)) > 0)" % (alias, v_, alias, v_, alias, v_)

        def pagination(nom, cle, fl=None, attendu_total=None, ordre_attendu=None):
            """Une liste, de toutes les façons de la lire : tout d'un coup, page par page, limites absurdes — mêmes éléments, même ordre, même total."""
            tout = L(nom, fl, lim=200)
            ok(len(tout['items']) == min(tout['total'], 200), '%s : %d éléments rendus pour un total de %d' % (nom, len(tout['items']), tout['total']))
            if attendu_total is not None:
                ok(tout['total'] == attendu_total, '%s : total %d, attendu %d' % (nom, tout['total'], attendu_total))
            ids = [i_[cle] for i_ in tout['items']]
            ok(len(set(ids)) == len(ids), '%s : aucun doublon' % nom)
            if ordre_attendu is not None:
                ok(ids == ordre_attendu[:len(ids)], '%s : ordre identique au tri indépendant. En premier : %s ≠ %s' % (nom, ids[:4], ordre_attendu[:4]))
            if tout['total'] >= 3:
                pas = 2 if tout['total'] < 12 else 7
                pages_, o_ = [], 0
                while o_ < min(tout['total'], 60):
                    pg_ = L(nom, fl, lim=pas, off=o_)
                    ok(pg_['total'] == tout['total'] and len(pg_['items']) <= pas, '%s : page à %d, total constant' % (nom, o_))
                    pages_ += [i_[cle] for i_ in pg_['items']]
                    o_ += pas
                ok(pages_ == ids[:len(pages_)] and len(pages_) == min(tout['total'], o_), '%s : les pages mises bout à bout redonnent la liste complète, sans trou ni doublon' % nom)
            ok(len(L(nom, fl, lim=0)['items']) == min(1, tout['total']) and len(L(nom, fl, lim=-7)['items']) == min(1, tout['total']), '%s : limite 0 ou négative → 1' % nom)
            ok(len(L(nom, fl, lim=10 ** 6)['items']) == min(tout['total'], 200), '%s : limite énorme → plafonnée à 200' % nom)
            ok(L(nom, fl, off=-5, lim=3)['items'] == tout['items'][:3] and L(nom, fl, off=10 ** 6)['items'] == [] and L(nom, fl, off=10 ** 6)['total'] == tout['total'], '%s : décalage négatif = 0 ; au-delà de la fin : liste vide, total conservé' % nom)
            return tout

        # ------------------------------------------------------------ colis
        def cond_colis(pays=None, service=None, entrepot=None, client=None, ville=None, statut=None, de=None, a=None):
            c_ = ['true']
            if pays: c_.append("p.destination_country = '%s'" % pays)
            if service: c_.append("p.service_mode = '%s'" % service)
            if entrepot: c_.append("p.current_warehouse_id = '%s'" % entrepot)
            if client: c_.append(client_sql(client))
            if ville: c_.append("strpos(lower(p.destination_city), lower(%s)) > 0" % val(ville))
            if statut: c_.append("p.status = '%s'" % statut)
            c_.append(periode('p.created_at', {'from': de, 'to': a}))
            return ' and '.join(c_)

        def fl_(pays=None, service=None, entrepot=None, client=None, ville=None, statut=None, de=None, a=None):
            return {k_: v_ for k_, v_ in (('country', pays), ('service', service), ('warehouse_id', entrepot), ('customer', client), ('city', ville), ('status', statut), ('from', de), ('to', a)) if v_}

        SQL_COLIS = "from logistics.parcel p left join logistics.customer cu on cu.id = p.customer_id where %s"
        n_colis = n_("select count(*) from logistics.parcel")
        ordre_colis = cl.lignes(B, "select tracking_number from logistics.parcel order by updated_at desc, tracking_number limit 200")
        pc = pagination('lg_cc_parcels', 'tracking_number', None, n_colis, ordre_colis)
        ok(n_colis > 200 and len(pc['items']) == 200, 'plus de 200 colis en base (%d) : la page est plafonnée à 200' % n_colis)
        ok(pc['by_status'] == {k_: int(v_) for k_, v_ in (l_.split('|') for l_ in cl.lignes(B, "select status, count(*) from logistics.parcel group by status"))}, 'colis par statut : identiques à un regroupement indépendant')
        ok(sum(pc['by_status'].values()) == n_colis and pc['filters'] == {}, 'et leur somme est le total')
        i1 = [i_ for i_ in L('lg_cc_parcels', lim=200, fl={'customer': q("select code from logistics.customer where id = '%s'" % ca)})['items'] if i_['tracking_number'] == 'N-001'][0]
        ok(i1['status'] == 'DELIVERED' and i1['customer_code'] == q("select code from logistics.customer where id = '%s'" % ca) and i1['service_mode'] == 'air' and i1['weight_lb'] == D('4.00') and i1['authority'] == 'core'
           and i1['destination_country'] == 'HT' and i1['destination_city'] == 'Pétion-Ville' and i1['warehouse'] == 'Hub Port-au-Prince', 'N-001 : livré, à Pétion-Ville, au hub, poids 4, autorité « noyau »')
        cas_c = [dict(statut='AT_DESTINATION_HUB'), dict(statut='ON_HOLD'), dict(statut='DELIVERED'), dict(statut='INEXISTANT'), dict(pays='DO'), dict(service='sea'), dict(entrepot=wpap), dict(entrepot=wmia),
                 dict(client=q("select code from logistics.customer where id = '%s'" % ca)), dict(client='brien'), dict(ville='santiago'), dict(ville='pétion'), dict(pays='HT', statut='AT_DESTINATION_HUB'),
                 dict(pays='DO', service='sea', ville='santiago'), dict(de=q("select %s::text" % JOUR), a=q("select %s::text" % JOUR)), dict(a=q("select (%s - 1)::text" % JOUR)), dict(de=q("select (%s + 1)::text" % JOUR))]
        n_diff = 0
        for cas in cas_c:
            r_ = L('lg_cc_parcels', fl_(**cas), lim=200)
            att_ = n_("select count(*) " + SQL_COLIS % cond_colis(**cas))
            ok(r_['total'] == att_ and len(r_['items']) == min(att_, 200), 'colis, filtre %s : %d (décompte indépendant : %d)' % (cas, r_['total'], att_))
            if r_['total'] != n_colis:
                n_diff += 1
            if cas.get('statut') in (None, 'INEXISTANT'):
                continue
            ok(all(i_['status'] == cas['statut'] for i_ in r_['items']), 'colis, filtre %s : tous au statut demandé' % cas)
        ok(n_diff >= 14, 'les filtres de la liste des colis changent le résultat (%d cas sur %d)' % (n_diff, len(cas_c)))
        ok(L('lg_cc_parcels', fl_(statut='ON_HOLD', de=q("select %s::text" % JOUR)), lim=200)['total'] == n_("select count(*) from logistics.parcel where status = 'ON_HOLD' and created_at >= %s" % T0), 'statut et période se combinent')
        ok(L('lg_cc_parcels', fl_(client='%'), lim=200)['total'] == 0 and L('lg_cc_parcels', fl_(ville='_'), lim=200)['total'] == 0, 'jokers « % » et « _ » : des caractères, pas des motifs')
        ok(L('lg_cc_parcels', {'customer': "x' or 1=1 --"})['total'] == 0, 'une injection SQL dans un filtre ne trouve rien')
        fr('lg_cc_parcels', 'LG005', 'filtre inconnu', admin, p_filters=R("'{\"order\": \"1\"}'::jsonb"))
        # la fiche du colis, pour l'équipe : TOUT le journal, les auteurs et les motifs
        d1 = f('lg_cc_parcel', admin, p_tracking='N-001')
        ok(d1['parcel']['tracking_number'] == 'N-001' and d1['parcel']['status'] == 'DELIVERED' and d1['parcel']['customer_code'] == q("select code from logistics.customer where id = '%s'" % ca) and d1['parcel']['authority'] == 'core', 'fiche du colis : identité, client, autorité')
        brut = cl.lignes(B, "select event_type from logistics.tracking_event where parcel_id = '%s' order by occurred_at, id" % a1)
        ok([t_['event'] for t_ in d1['timeline']] == brut and len(brut) == 14, 'le journal COMPLET du colis : les %d événements, internes compris (ParcelStored, ParcelConsolidationPending), dans l\'ordre' % len(brut))
        ok(any(t_['location'] == 'A-01-SECRET' for t_ in d1['timeline']) and any(t_['location'] == 'QUAI-INTERNE-3' for t_ in d1['timeline']), 'l\'équipe voit les emplacements internes que le client ne voit jamais')
        ok(all(t_['actor'] for t_ in d1['timeline'] if t_['event'] != 'ParcelStatusChanged') and all(set(t_) == {'at', 'event', 'from', 'to', 'actor', 'source', 'location', 'reason', 'correlation_id'} for t_ in d1['timeline']), 'chaque ligne : auteur, source, emplacement, motif, corrélation')
        ok([s_['code'] for s_ in d1['shipments']] == ['SHP-001'] and len(d1['deliveries']) == 1 and d1['deliveries'][0]['status'] == 'COMPLETED' and d1['deliveries'][0]['driver'] == 'Chauffeur Un', 'son expédition et sa livraison (chauffeur compris)')
        ok(d1['incidents'] == [] and d1['scans'] == [], 'sans incident ni scan')
        d2 = f('lg_cc_parcel', admin, p_tracking=' n-002 ')
        ok([i_['type'] for i_ in d2['incidents']] == ['DAMAGED'] and d2['incidents'][0]['severity'] == 'HIGH' and len(d2['scans']) == 1 and d2['scans'][0]['result'] == 'ACCEPTED' and d2['scans'][0]['purpose'] == 'lookup', 'N-002 : l\'incident grave et le scan, numéro lu sans tenir compte de la casse ni des espaces')
        d4 = f('lg_cc_parcel', admin, p_tracking='N-008')
        ok(any('contrefaçon' in (t_['reason'] or '') for t_ in d4['timeline']), 'le motif INTERNE d\'une mise en attente est visible de l\'équipe (il ne l\'est pas du client)')
        d_h = f('lg_cc_parcel', admin, p_tracking=q("select numero from public.colis order by numero limit 1"))
        ok(d_h['parcel']['authority'] == 'legacy' and d_h['parcel']['tracking_number'], 'un colis hérité s\'ouvre aussi')
        fr('lg_cc_parcel', 'LG002', 'colis introuvable', admin, p_tracking='ZZZ-INCONNU')
        fr('lg_cc_parcel', 'LG002', 'numéro vide', admin, p_tracking='')
        for mot in ('otp_hash', 'otp_salt', 'password', 'encrypted', 'auth_user_id', 'idempotency'):
            ok(mot not in texte(d1) + texte(d2) + texte(d4), 'la fiche du colis ne contient jamais « %s » (même pour l\'équipe)' % mot)

        # ------------------------------------------------------------ expéditions et vue de flux
        tout_f = L('lg_cc_flow', lim=200)
        ok([i_['shipment'] for i_ in tout_f['items']] == ['SHP-005', 'SHP-004', 'SHP-003', 'SHP-002', 'SHP-001'] and tout_f['total'] == 5, 'le flux : les cinq expéditions actives, de la plus récente à la plus ancienne (le brouillon et les annulées n\'y sont pas)')
        fl1 = {i_['shipment']: i_ for i_ in tout_f['items']}
        ok(fl1['SHP-001']['status'] == 'AT_HUB' and fl1['SHP-001']['hub'] == 'Hub Port-au-Prince' and fl1['SHP-001']['transport']['reference'] == 'XX123' and fl1['SHP-001']['transport']['carrier'] == 'Compagnie fictive', 'SHP-001 : au hub, sur le vol XX123')
        ok(fl1['SHP-001']['parcels']['total'] == int(q("select count(*) from logistics.shipment_parcels('%s')" % sh)) >= 5 and sum(fl1['SHP-001']['parcels']['by_status'].values()) == fl1['SHP-001']['parcels']['total'], 'ses colis : le total est celui des colis réellement embarqués, ventilés par statut')
        ok([(d_['status'], d_['parcels']) for d_ in fl1['SHP-001']['deliveries']] == [('COMPLETED', 1), ('CREATED', 1)] and fl1['SHP-001']['deliveries'][0]['driver'] == 'Chauffeur Un' and fl1['SHP-001']['deliveries'][1]['driver'] is None,
           'ses livraisons : celle de N-001 faite par Chauffeur Un, celle de N-003 pas encore attribuée')
        ok(fl1['SHP-002']['transport']['reference'] == 'YY456' and fl1['SHP-002']['country'] == 'DO' and fl1['SHP-002']['deliveries'] == [] and fl1['SHP-002']['status'] == 'IN_TRANSIT' and fl1['SHP-002']['transport']['departed_at'], 'SHP-002 : en transit vers la République dominicaine, aucune livraison encore')
        ok(fl1['SHP-004']['transport'] is None and fl1['SHP-004']['status'] == 'READY' and fl1['SHP-003']['status'] == 'CUSTOMS_PROCESSING', 'SHP-004 : prête, pas encore de transport ; SHP-003 : en douane')
        for cas, att_ in ((dict(statut='READY'), ['SHP-004']), (dict(statut='ACTIVE'), ['SHP-005', 'SHP-004', 'SHP-003', 'SHP-002', 'SHP-001']), (dict(statut='CLOSED'), []), (dict(statut='DRAFT'), []), (dict(pays='DO'), ['SHP-003', 'SHP-002']),
                          (dict(service='sea'), ['SHP-003']), (dict(pays='DO', service='air'), ['SHP-002']), (dict(ville='santiago'), ['SHP-003']),
                          (dict(client=q("select code from logistics.customer where id = '%s'" % cb)), ['SHP-002', 'SHP-001']), (dict(client=q("select code from logistics.customer where id = '%s'" % ca), pays='DO'), ['SHP-003']), (dict(statut='ARRIVED'), ['SHP-005']),
                          (dict(de=q("select %s::text" % JOUR), a=q("select %s::text" % JOUR)), ['SHP-005', 'SHP-004', 'SHP-003', 'SHP-002', 'SHP-001']), (dict(a=q("select (%s - 1)::text" % JOUR)), [])):
            ok([i_['shipment'] for i_ in L('lg_cc_flow', fl_(**cas), lim=200)['items']] == att_, 'flux, filtre %s : %s' % (cas, att_))
        pagination('lg_cc_flow', 'shipment', None, 5)
        tout_s = L('lg_cc_shipments', lim=200)
        ok([i_['code'] for i_ in tout_s['items']] == cl.lignes(B, "select code from logistics.shipment order by created_at desc, code") and tout_s['total'] == 6, 'les expéditions : six, dont le brouillon, de la plus récente à la plus ancienne')
        ok(tout_s['by_status'] == {k_: int(v_) for k_, v_ in (l_.split('|') for l_ in cl.lignes(B, "select status, count(*) from logistics.shipment group by status"))}, 'par statut : identique au regroupement indépendant')
        s_ = {i_['code']: i_ for i_ in tout_s['items']}
        ok(s_['SHP-004']['origin'] == 'Miami' and s_['SHP-004']['destination'] == 'Hub Port-au-Prince' and s_['SHP-004']['parcels'] == 1 and s_['SHP-004']['weight_lb'] == D('2.00') and s_['SHP-004']['transport'] is None and s_['SHP-002']['transport'] == 'YY456', 'SHP-004 : de Miami au hub, 1 colis de 2 lb ; SHP-002 sur YY456')
        ok(s_['SHP-DRAFT']['status'] == 'DRAFT' and s_['SHP-DRAFT']['parcels'] == 1, 'le brouillon est listé ici (et seulement ici)')
        for cas in (dict(statut='DRAFT'), dict(pays='DO'), dict(service='sea'), dict(ville='santiago'), dict(entrepot=wpap), dict(client=q("select code from logistics.customer where id = '%s'" % ca)), dict(de=q("select %s::text" % JOUR))):
            r_ = L('lg_cc_shipments', fl_(**cas), lim=200)
            sw_ = ['true']
            if cas.get('statut'): sw_.append("s.status = '%s'" % cas['statut'])
            if cas.get('pays'): sw_.append("(select b.country from logistics.branch b where b.id = s.destination_branch_id) = '%s'" % cas['pays'])
            if cas.get('service'): sw_.append("s.mode = '%s'" % cas['service'])
            if cas.get('ville') or cas.get('entrepot') or cas.get('client'):
                sw_.append("exists (select 1 from logistics.shipment_parcels(s.id) sp join logistics.parcel p on p.id = sp.parcel_id left join logistics.customer cu on cu.id = p.customer_id where %s)" % cond_colis(ville=cas.get('ville'), entrepot=cas.get('entrepot'), client=cas.get('client')))
            if cas.get('de'): sw_.append(periode('s.created_at', {'from': cas['de']}))
            ok(sorted(i_['code'] for i_ in r_['items']) == sorted(cl.lignes(B, "select code from logistics.shipment s where %s" % ' and '.join(sw_))), 'expéditions, filtre %s : les mêmes que le décompte indépendant' % cas)
        pagination('lg_cc_shipments', 'code', None, 6)

        # ------------------------------------------------------------ entrepôt
        wh = f('lg_cc_warehouse', admin)
        ok([w_['code'] for w_ in wh['warehouses']] == ['MIA-1', 'PAP-1', 'SDQ-1'], 'trois entrepôts, dans l\'ordre des codes')
        for w_ in wh['warehouses']:
            wid = q("select id from logistics.warehouse where code = '%s'" % w_['code'])
            ok(w_['parcels'] == n_("select count(*) from logistics.parcel where current_warehouse_id = '%s'" % wid) and sum(w_['by_status'].values()) == w_['parcels'], '%s : colis présents = décompte indépendant, ventilés par statut' % w_['code'])
            ok(w_['received_today'] == n_("select count(*) from logistics.tracking_event where warehouse_id = '%s' and event_type = 'ParcelReceived' and occurred_at >= %s" % (wid, T0)), '%s : reçus aujourd\'hui' % w_['code'])
            ok(w_['scans_today'] == n_("select count(*) from logistics.scan where warehouse_id = '%s' and scanned_at >= %s" % (wid, T0)) and w_['scans_rejected_today'] == n_("select count(*) from logistics.scan where warehouse_id = '%s' and scanned_at >= %s and result <> 'ACCEPTED'" % (wid, T0)), '%s : scans du jour, dont refusés' % w_['code'])
            ok(w_['open_incidents'] == n_("select count(*) from logistics.incident where warehouse_id = '%s' and status in ('OPEN', 'IN_PROGRESS')" % wid) and w_['locations'] == n_("select count(*) from logistics.warehouse_location where warehouse_id = '%s' and active" % wid), '%s : incidents ouverts, emplacements' % w_['code'])
        w0 = {w_['code']: w_ for w_ in wh['warehouses']}
        ok(w0['MIA-1']['scans_today'] == 2 and w0['MIA-1']['scans_rejected_today'] == 1 and w0['MIA-1']['open_incidents'] == 2 and w0['MIA-1']['locations'] == 1 and w0['MIA-1']['received_today'] == 1 and w0['SDQ-1']['scans_today'] == 0, 'Miami : deux scans dont un refusé, deux incidents ouverts, un colis reçu aujourd\'hui ; Saint-Domingue : rien')
        ok([s_['code'] for s_ in wh['recent_scans']] == ['INCONNU-1', 'N-002'] and wh['recent_scans'][0]['result'] == 'UNKNOWN_PARCEL' and wh['recent_scans'][1]['result'] == 'ACCEPTED' and wh['recent_scans'][0]['warehouse'] == 'MIA-1', 'derniers scans : du plus récent au plus ancien, avec leur résultat')
        ok([w_['code'] for w_ in f('lg_cc_warehouse', admin, p_filters=R("'{\"warehouse_id\": \"%s\"}'::jsonb" % wsdq))['warehouses']] == ['SDQ-1'] and f('lg_cc_warehouse', admin, p_filters=R("'{\"warehouse_id\": \"%s\"}'::jsonb" % wsdq))['recent_scans'] == [], 'filtre par entrepôt : un seul, et ses propres scans')
        ok([w_['code'] for w_ in f('lg_cc_warehouse', admin, p_filters=R("'{\"country\": \"DO\"}'::jsonb"))['warehouses']] == ['SDQ-1'] and [w_['code'] for w_ in f('lg_cc_warehouse', admin, p_filters=R("'{\"country\": \"HT\"}'::jsonb"))['warehouses']] == ['PAP-1'], 'filtre par pays : l\'entrepôt de la succursale de ce pays')
        # les entrepôts désactivés n'apparaissent pas
        q("update logistics.warehouse set active = false where id = '%s'" % wsdq)
        ok([w_['code'] for w_ in f('lg_cc_warehouse', admin)['warehouses']] == ['MIA-1', 'PAP-1'], 'un entrepôt désactivé disparaît de la vue')
        q("update logistics.warehouse set active = true where id = '%s'" % wsdq)

        # ------------------------------------------------------------ consolidations
        tc = pagination('lg_cc_consolidations', 'code', None, 2, cl.lignes(B, "select code from logistics.consolidation order by opened_at desc, code"))
        c1_ = {i_['code']: i_ for i_ in tc['items']}
        ok(c1_['CONS-001']['status'] == 'CLOSED' and c1_['CONS-001']['parcels'] == 4 and c1_['CONS-001']['customers'] == 2 and c1_['CONS-001']['shipment'] == 'SHP-001' and c1_['CONS-001']['warehouse'] == 'Miami', 'CONS-001 : fermée, 4 colis de 2 clients, dans SHP-001')
        ok(c1_['CONS-001']['weight_lb'] == D(q("select coalesce(sum(coalesce(p.verified_weight_lb, p.weight_lb)), 0) from logistics.consolidation_parcel cp join logistics.parcel p on p.id = cp.parcel_id where cp.consolidation_id = '%s' and cp.removed_at is null" % cons)), 'son poids : la somme des colis (poids vérifié quand il existe)')
        ok(c1_['CONS-002']['status'] == 'OPEN' and c1_['CONS-002']['parcels'] == 1 and c1_['CONS-002']['customers'] == 1 and c1_['CONS-002']['shipment'] is None and c1_['CONS-002']['closed_at'] is None, 'CONS-002 : ouverte, 1 colis, pas d\'expédition')
        for cas, att_ in ((dict(statut='OPEN'), ['CONS-002']), (dict(statut='CLOSED'), ['CONS-001']), (dict(pays='HT'), ['CONS-002', 'CONS-001']), (dict(pays='DO'), []), (dict(service='air'), ['CONS-002', 'CONS-001']), (dict(service='sea'), []),
                          (dict(entrepot=wmia), ['CONS-002', 'CONS-001']), (dict(entrepot=wpap), []), (dict(client=q("select code from logistics.customer where id = '%s'" % cb)), ['CONS-001']),
                          (dict(client=q("select code from logistics.customer where id = '%s'" % ca)), ['CONS-002', 'CONS-001']), (dict(de=q("select %s::text" % JOUR)), ['CONS-002', 'CONS-001']), (dict(a=q("select (%s - 1)::text" % JOUR)), [])):
            ok(sorted(i_['code'] for i_ in L('lg_cc_consolidations', fl_(**cas), lim=200)['items']) == sorted(att_), 'consolidations, filtre %s : %s' % (cas, att_))

        # ------------------------------------------------------------ transport
        tt = pagination('lg_cc_transports', 'reference', None, 4, cl.lignes(B, "select reference from logistics.transport order by coalesce(planned_departure_at, created_at) desc, reference"))
        t_ = {i_['reference']: i_ for i_ in tt['items']}
        ok(t_['YY456']['late'] is True and t_['XX123']['late'] is False and t_['ZZ789']['late'] is False, 'seul YY456 est en retard : parti, et son arrivée prévue est passée')
        ok(t_['XX123']['shipments'] == 1 and t_['YY456']['shipments'] == 1 and t_['ZZ789']['shipments'] == 1 and t_['YY456']['mode'] == 'air' and t_['ZZ789']['mode'] == 'sea' and t_['YY456']['destination'] == 'Hub Saint-Domingue, Santo Domingo' and t_['YY456']['origin'] == 'Miami', 'expéditions par transport, mode, origine et destination')
        for cas in (dict(statut='ARRIVED'), dict(statut='DEPARTED'), dict(statut='PLANNED'), dict(service='sea'), dict(service='air'), dict(pays='DO'), dict(de=q("select %s::text" % JOUR)), dict(a=q("select (%s - 1)::text" % JOUR)), dict(a=q("select (%s - 4)::text" % JOUR))):
            c_ = ['true']
            if cas.get('statut'): c_.append("t.status = '%s'" % cas['statut'])
            if cas.get('service'): c_.append("t.mode = '%s'" % cas['service'])
            if cas.get('pays'): c_.append("exists (select 1 from logistics.branch b where b.id = t.destination_branch_id and b.country = '%s')" % cas['pays'])
            c_.append(periode('coalesce(t.planned_departure_at, t.created_at)', {'from': cas.get('de'), 'to': cas.get('a')}))
            ok(sorted(i_['reference'] for i_ in L('lg_cc_transports', fl_(**cas), lim=200)['items']) == sorted(cl.lignes(B, "select reference from logistics.transport t where %s" % ' and '.join(c_))), 'transports, filtre %s : les mêmes que le décompte indépendant' % cas)

        # ------------------------------------------------------------ chauffeurs
        dv = pagination('lg_cc_drivers', 'name', None, 2, ['Chauffeur Deux', 'Chauffeur Un'])
        d_un = [i_ for i_ in dv['items'] if i_['name'] == 'Chauffeur Un'][0]; d_deux = [i_ for i_ in dv['items'] if i_['name'] == 'Chauffeur Deux'][0]
        tdr = lambda extra: n_("select count(*) from logistics.task where driver_id = '%s' and scheduled_date = %s and %s" % (drv, JOUR, extra))   # noqa: E731
        ok(d_un['tasks_today'] == tdr("status <> 'CANCELLED'") == 2 and d_un['completed_today'] == tdr("status = 'COMPLETED'") == 1 and d_un['failed_today'] == tdr("status = 'FAILED'") == 0, 'Chauffeur Un : deux missions aujourd\'hui, une faite, aucune échouée')
        ok(d_un['tasks_open'] == n_("select count(*) from logistics.task where driver_id = '%s' and status in ('ASSIGNED', 'ACCEPTED', 'STARTED')" % drv) == 1, 'une mission ouverte (en cours)')
        ok(d_un['vehicle'] == 'AA-100 (VAN)' and d_un['zones'] == ['PV'] and d_un['status'] == 'ACTIVE' and d_un['available_today'] is True and d_un['position_age_min'] in (0, 1), 'son véhicule, sa zone, son statut, sa disponibilité du jour, une position vieille de moins d\'une minute')
        ok(d_deux['status'] == 'ON_LEAVE' and d_deux['vehicle'] is None and d_deux['zones'] == [] and d_deux['available_today'] is False and d_deux['position_age_min'] is None and d_deux['tasks_today'] == 0, 'Chauffeur Deux : en congé, sans véhicule ni zone ni position, indisponible')
        for cas, att_ in ((dict(statut='ACTIVE'), ['Chauffeur Un']), (dict(statut='ON_LEAVE'), ['Chauffeur Deux']), (dict(statut='INACTIVE'), []), (dict(pays='HT'), ['Chauffeur Un']), (dict(pays='DO'), []),
                          (dict(ville='pétion'), ['Chauffeur Un']), (dict(ville='DELMAS'), ['Chauffeur Un']), (dict(ville='jacmel'), []), (dict(statut='ACTIVE', pays='HT'), ['Chauffeur Un']), (dict(statut='ON_LEAVE', pays='HT'), [])):
            ok([i_['name'] for i_ in L('lg_cc_drivers', fl_(**cas), lim=200)['items']] == att_, 'chauffeurs, filtre %s : %s' % (cas, att_))
        # un chauffeur sans position récente ni disponibilité
        q("update logistics.driver set last_position_at = now() - interval '90 minutes' where id = '%s'" % drv)
        ok([i_ for i_ in L('lg_cc_drivers', lim=200)['items'] if i_['name'] == 'Chauffeur Un'][0]['position_age_min'] in (90, 91), 'l\'âge de la position se lit en minutes')
        q("update logistics.driver set last_position_at = now() where id = '%s'" % drv)

        # ------------------------------------------------------------ enlèvements
        ORD_ENL = [pk_b['pickup_id'], pk_a['pickup_id'], pk_c['pickup_id'], task_staff]
        pe = pagination('lg_cc_pickups', 'request_id', None, 4, ORD_ENL)
        ok(pe['by_stage'] == {'requested': 3, 'scheduled': 1}, 'enlèvements par étape : trois demandés, un planifié (celui du personnel)')
        e_a = [i_ for i_ in pe['items'] if i_['request_id'] == pk_a['pickup_id']][0]
        ok(e_a['source'] == 'REQUEST' and e_a['number'] == pk_a['number'] and e_a['customer_code'] == q("select code from logistics.customer where id = '%s'" % ca) and e_a['address'] == '12 rue des Fleurs' and e_a['city'] == 'Pétion-Ville' and e_a['country'] == 'HT'
           and e_a['window'] == 'MORNING' and e_a['parcels_expected'] == 2 and e_a['notes'] == 'Sonner deux fois' and e_a['request_status'] == 'REQUESTED' and e_a['driver'] is None and e_a['review_message'] is None and e_a['date'] == DANS3, 'la demande de A : tout ce que le client a écrit, et rien d\'attribué')
        e_s = [i_ for i_ in pe['items'] if i_['request_id'] == task_staff][0]
        ok(e_s['source'] == 'STAFF' and e_s['number'].startswith('PKT-') and e_s['stage'] == 'scheduled' and e_s['address'] == 'Enlèvement demandé par téléphone' and e_s['parcels_expected'] == 3 and e_s['request_status'] is None and e_s['country'] is None, 'l\'enlèvement créé par le personnel : source « STAFF », sans demande derrière')
        ok('task_status' in e_s and e_s['task_status'] == 'CREATED', 'l\'état de la mission est rendu (créée, pas encore attribuée)')
        for cas, att_ in ((dict(pays='DO'), [pk_b['pickup_id']]), (dict(pays='HT'), [pk_a['pickup_id'], pk_c['pickup_id']]), (dict(ville='delmas'), [pk_c['pickup_id']]), (dict(statut='requested'), ORD_ENL[:3]), (dict(statut='scheduled'), [task_staff]),
                          (dict(statut='rejected'), []), (dict(client=q("select code from logistics.customer where id = '%s'" % cb)), [pk_b['pickup_id']]),
                          (dict(client=q("select code from logistics.customer where id = '%s'" % ca)), [pk_a['pickup_id'], pk_c['pickup_id'], task_staff]), (dict(de=q("select %s::text" % JOUR), a=q("select %s::text" % JOUR)), ORD_ENL),
                          (dict(a=q("select (%s - 1)::text" % JOUR)), []), (dict(statut='requested', client=q("select code from logistics.customer where id = '%s'" % ca)), [pk_a['pickup_id'], pk_c['pickup_id']])):
            ok([i_['request_id'] for i_ in L('lg_cc_pickups', fl_(**cas), lim=200)['items']] == att_, 'enlèvements, filtre %s : %d résultat(s)' % (cas, len(att_)))

        # ------------------------------------------------------------ livraisons
        ETAPE_T = {'COMPLETED': 'delivered', 'STARTED': 'on_the_way', 'FAILED': 'missed', 'CANCELLED': 'cancelled'}
        tl = L('lg_cc_deliveries', lim=200)
        ok(tl['total'] == 9 == n_("select count(*) from logistics.task where kind = 'DELIVERY'") + n_("select count(*) from logistics.delivery_request where status in ('REQUESTED', 'REJECTED')"), 'neuf lignes : sept missions de livraison (dont une annulée) et deux demandes en attente')
        ok(tl['delayed'] == 2 and tl['by_stage'] == {'requested': 2, 'delivered': 1, 'on_the_way': 1, 'scheduled': 4, 'cancelled': 1}, 'deux en retard ; par étape : 2 demandées, 1 livrée, 1 en route, 4 planifiées, 1 annulée : %s' % tl['by_stage'])
        ids_l = [i_['ref_id'] for i_ in tl['items']]
        ok(ids_l[:4] == [dr_a['request_id'], dr_b['request_id'], dl_late['task_id'], dl_win['task_id']] and ids_l[-1] == dl3['task_id'], 'ordre : les demandes d\'abord, puis les livraisons en retard (la plus ancienne en premier), puis par date : la plus lointaine (demain) en dernier')
        tl_ = {i_['ref_id']: i_ for i_ in tl['items']}
        ok(tl_[dl_late['task_id']]['delayed'] is True and tl_[dl_late['task_id']]['stage'] == 'scheduled' and tl_[dl_late['task_id']]['driver'] is None and tl_[dl_late['task_id']]['date'] == q("select (%s - 2)::text" % JOUR), 'la livraison en retard : prévue il y a deux jours, pas attribuée')
        ok(tl_[dl_prog['task_id']]['stage'] == 'on_the_way' and tl_[dl_prog['task_id']]['driver'] == 'Chauffeur Un' and tl_[dl_prog['task_id']]['task_status'] == 'STARTED' and tl_[dl_prog['task_id']]['delayed'] is False, 'la livraison en cours : en route, avec son chauffeur')
        ok(tl_[dl['task_id']]['stage'] == 'delivered' and tl_[dl['task_id']]['driver'] == 'Chauffeur Un' and tl_[dl['task_id']]['parcels'] == 1 and tl_[dl['task_id']]['delayed'] is False and tl_[dl['task_id']]['task_status'] == 'COMPLETED', 'la livraison faite : jamais « en retard », même si elle est du jour')
        ok(tl_[dr_a['request_id']]['kind'] == 'REQUEST' and tl_[dr_a['request_id']]['parcels'] == 2 and tl_[dr_a['request_id']]['task_status'] is None and tl_[dr_a['request_id']]['request_status'] == 'REQUESTED' and tl_[dl['task_id']]['request_status'] is None and tl_[dr_a['request_id']]['number'] == dr_a['number'] and tl_[dl['task_id']]['kind'] == 'TASK', 'une demande de 2 colis ; la mission porte « TASK »')
        ok(all(i_['stage'] == ETAPE_T.get(i_['task_status'], 'scheduled') for i_ in tl['items'] if i_['kind'] == 'TASK'), 'chaque mission : l\'étape déduite de son état (faite, en route, manquée, annulée, sinon planifiée)')
        pagination('lg_cc_deliveries', 'ref_id', None, 9, None)
        CAS_L = [dict(statut='requested'), dict(statut='delivered'), dict(statut='scheduled'), dict(statut='on_the_way'), dict(statut='rejected'), dict(pays='HT'), dict(pays='DO'), dict(ville='jacmel'), dict(ville='pétion'), dict(entrepot=wpap), dict(entrepot=wmia),
                 dict(client=q("select code from logistics.customer where id = '%s'" % ca)), dict(client=q("select code from logistics.customer where id = '%s'" % cb)), dict(de=q("select %s::text" % JOUR), a=q("select %s::text" % JOUR)),
                 dict(a=q("select (%s - 3)::text" % JOUR)), dict(de=q("select (%s + 5)::text" % JOUR))]
        for cas in CAS_L:
            c_t, c_r = ["t.kind = 'DELIVERY'"], ["r.status in ('REQUESTED', 'REJECTED')"]
            if cas.get('statut'):
                c_t.append("(case when t.status = 'COMPLETED' then 'delivered' when t.status = 'STARTED' then 'on_the_way' when t.status = 'FAILED' then 'missed' when t.status = 'CANCELLED' then 'cancelled' else 'scheduled' end) = '%s'" % cas['statut'])
                c_r.append("(case r.status when 'REQUESTED' then 'requested' when 'REJECTED' then 'rejected' end) = '%s'" % cas['statut'])
            if cas.get('pays') or cas.get('ville') or cas.get('entrepot'):
                c_t.append("exists (select 1 from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = d.id and %s)" % cond_colis(pays=cas.get('pays'), ville=cas.get('ville'), entrepot=cas.get('entrepot')))
                if cas.get('pays'): c_r.append("r.country = '%s'" % cas['pays'])
                if cas.get('ville'): c_r.append("strpos(lower(r.city), lower(%s)) > 0" % val(cas['ville']))
                if cas.get('entrepot'): c_r.append('false')
            if cas.get('client'):
                c_t.append(client_sql(cas['client'])); c_r.append(client_sql(cas['client']))
            if cas.get('de'): c_t.append("t.scheduled_date >= '%s'" % cas['de']); c_r.append("r.preferred_date >= '%s'" % cas['de'])
            if cas.get('a'): c_t.append("t.scheduled_date <= '%s'" % cas['a']); c_r.append("r.preferred_date <= '%s'" % cas['a'])
            att_ids = sorted(cl.lignes(B, "select t.id from logistics.task t join logistics.delivery d on d.id = t.delivery_id left join logistics.customer cu on cu.id = d.customer_id where %s" % ' and '.join(c_t))
                             + cl.lignes(B, "select r.id from logistics.delivery_request r join logistics.customer cu on cu.id = r.customer_id where %s" % ' and '.join(c_r)))
            ok(sorted(i_['ref_id'] for i_ in L('lg_cc_deliveries', fl_(**cas), lim=200)['items']) == att_ids, 'livraisons, filtre %s : %d résultat(s), identiques au décompte indépendant' % (cas, len(att_ids)))

        # ------------------------------------------------------------ douane
        cu_ = pagination('lg_cc_customs', 'reference', None, 2, ['DEC-3', 'DEC-1'])
        k3 = [i_ for i_ in cu_['items'] if i_['reference'] == 'DEC-3'][0]; k1 = [i_ for i_ in cu_['items'] if i_['reference'] == 'DEC-1'][0]
        ok(k3['shipment'] == 'SHP-003' and k3['status'] == 'SUBMITTED' and k3['broker'] == 'Courtier DO' and k3['parcels'] == 1 and k3['waiting_days'] == 0 and k3['cleared_at'] is None and k3['destination_country'] == 'DO' and k3['mode'] == 'sea', 'DEC-3 : déposée, en attente depuis 0 jour, 1 colis, vers la République dominicaine')
        ok(k1['shipment'] == 'SHP-001' and k1['status'] == 'CLEARED' and k1['cleared_at'] and k1['waiting_days'] is None and k1['parcels'] == int(q("select jsonb_array_length(snapshot) from logistics.customs_declaration where reference = 'DEC-1'")), 'DEC-1 : dédouanée, plus d\'attente, le nombre de colis du manifeste figé')
        ok(cu_['by_status'] == {'SUBMITTED': 1, 'CLEARED': 1}, 'par statut')
        q("update logistics.customs_declaration set submitted_at = logistics.day_start(logistics.today() - 3) + interval '12 hours' where reference = 'DEC-3'")
        ok([i_ for i_ in L('lg_cc_customs', lim=200)['items'] if i_['reference'] == 'DEC-3'][0]['waiting_days'] == 3, 'l\'attente se compte en jours entiers, à l\'heure d\'Haïti')
        for cas, att_ in ((dict(statut='SUBMITTED'), ['DEC-3']), (dict(statut='CLEARED'), ['DEC-1']), (dict(statut='REJECTED'), []), (dict(pays='DO'), ['DEC-3']), (dict(pays='HT'), ['DEC-1']), (dict(service='sea'), ['DEC-3']), (dict(service='air'), ['DEC-1']),
                          (dict(de=q("select %s::text" % JOUR)), ['DEC-3', 'DEC-1']), (dict(a=q("select (%s - 1)::text" % JOUR)), [])):
            ok([i_['reference'] for i_ in L('lg_cc_customs', fl_(**cas), lim=200)['items']] == att_, 'douane, filtre %s : %s' % (cas, att_))

        # ------------------------------------------------------------ incidents
        inc_ = pagination('lg_cc_incidents', 'incident_id', None, 3, None)
        ok([(i_['type'], i_['status']) for i_ in inc_['items']] == [('DAMAGED', 'OPEN'), ('UNKNOWN_PARCEL', 'OPEN'), ('OTHER', 'RESOLVED')], 'les ouverts d\'abord (le grave en tête), le résolu ensuite')
        ok(inc_['by_status'] == {'OPEN': 2, 'RESOLVED': 1}, 'par statut')
        i_d = inc_['items'][0]
        ok(i_d['tracking_number'] == 'N-002' and i_d['severity'] == 'HIGH' and i_d['warehouse'] == 'MIA-1' and i_d['description'] == 'emballage éventré' and i_d['customer_code'] == q("select code from logistics.customer where id = '%s'" % ca) and i_d['task'] is False and i_d['resolved_at'] is None, 'l\'incident grave : colis N-002, entrepôt de Miami, client A')
        ok(inc_['items'][1]['tracking_number'] is None and inc_['items'][1]['customer_code'] is None and inc_['items'][2]['resolution'] == 'réétiqueté', 'l\'incident sans colis (code inconnu) est listé aussi ; le résolu porte sa résolution')
        for cas, att_ in ((dict(statut='ACTIVE'), 2), (dict(statut='OPEN'), 2), (dict(statut='RESOLVED'), 1), (dict(statut='CANCELLED'), 0), (dict(entrepot=wmia), 3), (dict(entrepot=wpap), 0), (dict(pays='HT'), 2), (dict(pays='DO'), 0),
                          (dict(service='air'), 2), (dict(client=q("select code from logistics.customer where id = '%s'" % ca)), 1), (dict(client=q("select code from logistics.customer where id = '%s'" % cb)), 1), (dict(de=q("select %s::text" % JOUR)), 3), (dict(a=q("select (%s - 1)::text" % JOUR)), 0)):
            ok(L('lg_cc_incidents', fl_(**cas), lim=200)['total'] == att_, 'incidents, filtre %s : %d' % (cas, att_))

        # ------------------------------------------------------------ notifications
        nt = pagination('lg_cc_notifications', 'id', None, n_("select count(*) from logistics.notification"), [int(x_) for x_ in cl.lignes(B, "select id from logistics.notification order by created_at desc, id desc")])
        ok(nt['by_status'] == {k_: int(v_) for k_, v_ in (l_.split('|') for l_ in cl.lignes(B, "select status, count(*) from logistics.notification group by status"))}, 'notifications par statut')
        ok(set(nt['items'][0]) == {'id', 'channel', 'template', 'status', 'customer_code', 'customer_name', 'created_at', 'sent_at'}, 'une notification : canal, modèle, statut, client, dates — JAMAIS son contenu (le code de livraison y voyage)')
        for cas in (dict(statut='SENT'), dict(statut='PENDING'), dict(client=q("select code from logistics.customer where id = '%s'" % ca)), dict(client=q("select code from logistics.customer where id = '%s'" % cb)), dict(de=q("select %s::text" % JOUR))):
            c_ = ['true']
            if cas.get('statut'): c_.append("n.status = '%s'" % cas['statut'])
            if cas.get('client'): c_.append(client_sql(cas['client']))
            c_.append(periode('n.created_at', {'from': cas.get('de')}))
            ok(L('lg_cc_notifications', fl_(**cas), lim=200)['total'] == n_("select count(*) from logistics.notification n left join logistics.customer cu on cu.id = n.customer_id where %s" % ' and '.join(c_)), 'notifications, filtre %s : identique au décompte indépendant' % cas)

        # ------------------------------------------------------------ clients
        code_a, code_b = q("select code from logistics.customer where id = '%s'" % ca), q("select code from logistics.customer where id = '%s'" % cb)
        n_cli = n_("select count(*) from logistics.customer")
        cus = pagination('lg_cc_customers', 'customer_code', None, n_cli, cl.lignes(B, "select code from logistics.customer order by created_at desc, code limit 200"))
        c_a = [i_ for i_ in L('lg_cc_customers', {'customer': code_a})['items']][0]
        ok(c_a['customer_code'] == code_a and c_a['email'] == 'client9@essai.test' and c_a['parcels'] == n_("select count(*) from logistics.parcel where customer_id = '%s'" % ca) and c_a['parcels_open'] == n_("select count(*) from logistics.parcel where customer_id = '%s' and status not in ('DELIVERED', 'CANCELLED', 'LOST', 'RETURNED')" % ca)
           and c_a['tickets_open'] == 2 and c_a['staff_account'] is False and c_a['language'] in ('fr', 'en', 'es', 'ht'), 'le client A : coordonnées, colis (tous, puis ouverts), deux tickets ouverts')
        impa = {}
        for st_, tot, cre, pai, ref_, cur in (l_.split('|') for l_ in cl.lignes(B, "select status, total, credited_amount, paid_amount, refunded_amount, currency from logistics.invoice where customer_id = '%s'" % ca)):
            b_ = (D(tot) - D(cre)) - (D(pai) - D(ref_))
            if st_ not in ('DRAFT', 'CANCELLED') and b_ > 0:
                n0, s0 = impa.get(cur, (0, D(0)))
                impa[cur] = (n0 + 1, s0 + b_)
        ok({u_['currency']: (u_['invoices'], D(u_['balance'])) for u_ in c_a['unpaid']} == impa and len(impa) == 1, 'ses factures impayées, par devise : identiques au calcul indépendant (%s)' % impa)
        ok(all(i_['unpaid'] is not None for i_ in cus['items']), 'avec le droit « factures.lire », chaque client porte son solde')
        sans_fin = L('lg_cc_customers', {'customer': code_a}, who=soutien)['items'][0]
        ok(sans_fin['unpaid'] is None and sans_fin['customer_code'] == code_a, 'SANS « factures.lire » (le support) : le solde du client est null, pas absent ni zéro')
        sa_ = [i_ for i_ in cus['items'] if i_['staff_account']]
        ok(len(sa_) == 1 == n_("select count(*) from logistics.customer where source = 'legacy_staff_account'") and sa_[0]['email'] == 'client4@essai.test' and sa_[0]['parcels'] == 1, 'un compte d\'équipe qui porte encore un colis hérité est signalé comme tel (et il est le seul)')
        for cas in (dict(client=code_a), dict(client='CLIENT10@essai.test'), dict(client='brien'), dict(client='personne'), dict(pays='HT'), dict(pays='DO'), dict(ville='pétion'), dict(ville='delmas'), dict(de=q("select %s::text" % JOUR)), dict(a=q("select (%s - 1)::text" % JOUR))):
            c_ = ['true']
            if cas.get('client'): c_.append(client_sql(cas['client'], 'cu'))
            if cas.get('pays'): c_.append("lower(cu.country) in (lower('%s'), '%s')" % (cas['pays'], {'HT': 'haïti', 'DO': 'république dominicaine'}.get(cas['pays'], 'états-unis')))
            if cas.get('ville'): c_.append("strpos(lower(cu.city), lower(%s)) > 0" % val(cas['ville']))
            c_.append(periode('cu.created_at', {'from': cas.get('de'), 'to': cas.get('a')}))
            ok(L('lg_cc_customers', fl_(**cas), lim=200)['total'] == n_("select count(*) from logistics.customer cu where %s" % ' and '.join(c_)), 'clients, filtre %s : identique au décompte indépendant' % cas)
        ok(L('lg_cc_customers', fl_(pays='HT'))['total'] > 0 and L('lg_cc_customers', fl_(pays='DO'))['total'] == 0 and L('lg_cc_customers', fl_(ville='pétion'))['total'] > 0, 'et ces filtres trouvent bien quelque chose, ou rien')

        # ------------------------------------------------------------ factures
        n_fact = n_("select count(*) from logistics.invoice where status <> 'DRAFT'")
        ordre_f = cl.lignes(B, "select number from logistics.invoice where status <> 'DRAFT' order by issued_at desc, number limit 200")
        inv = pagination('lg_cc_invoices', 'number', None, n_fact, ordre_f)
        ok(inv['by_status'] == {k_: int(v_) for k_, v_ in (l_.split('|') for l_ in cl.lignes(B, "select status, count(*) from logistics.invoice where status <> 'DRAFT' group by status"))} and 'DRAFT' not in inv['by_status'], 'par statut : identique, et JAMAIS de brouillon')
        ok(q("select status from logistics.invoice where id = '%s'" % inv_draft) == 'DRAFT' and q("select number from logistics.invoice where id = '%s'" % inv_draft) not in [i_['number'] for i_ in L('lg_cc_invoices', lim=200)['items']], 'le brouillon de facture n\'est pas listé')
        ok({t_['currency']: (D(t_['invoiced']), t_['unpaid_invoices'], D(t_['balance'])) for t_ in inv['totals']} == {c_: (D(q("select sum(total) from logistics.invoice where status <> 'DRAFT' and currency = '%s'" % c_)), n_("select count(*) from logistics.invoice i where status not in ('DRAFT', 'CANCELLED') and (i.total - i.credited_amount) - (i.paid_amount - i.refunded_amount) > 0 and currency = '%s'" % c_),
                                                                                                          D(q("select coalesce(sum((i.total - i.credited_amount) - (i.paid_amount - i.refunded_amount)), 0) from logistics.invoice i where status not in ('DRAFT', 'CANCELLED') and (i.total - i.credited_amount) - (i.paid_amount - i.refunded_amount) > 0 and currency = '%s'" % c_))) for c_ in ('USD',)},
           'totaux par devise : facturé, nombre d\'impayées et solde impayé, identiques au calcul indépendant')
        i_a = [i_ for i_ in L('lg_cc_invoices', {'customer': code_a}, lim=200)['items'] if i_['number'] == q("select number from logistics.invoice where id = '%s'" % inv_a)][0]
        ok(i_a['status'] == 'PAID' and i_a['total'] == D('22.00') and i_a['paid'] == D('22.00') and i_a['credited'] == D('5.00') and i_a['refunded'] == D('3.00') and i_a['balance'] == D('-0.00') + (D('22.00') - D('5.00')) - (D('22.00') - D('3.00')) and i_a['customer_code'] == code_a and i_a['source'] == 'native' and i_a['grouped'] is False,
           'la facture de A : 22 payés, 5 d\'avoir, 3 remboursés : le solde est (22 − 5) − (22 − 3) = −2 (un excédent), et l\'ordre des montants est celui de la facture')
        for cas, att_ in ((dict(statut='PAID'), "status = 'PAID'"), (dict(statut='UNPAID'), "status not in ('DRAFT', 'CANCELLED') and (total - credited_amount) - (paid_amount - refunded_amount) > 0"), (dict(statut='OVERDUE'), "status = 'OVERDUE'"),
                          (dict(statut='PARTIALLY_PAID'), "status = 'PARTIALLY_PAID'"), (dict(statut='ISSUED'), "status = 'ISSUED'"), (dict(statut='CANCELLED'), "status = 'CANCELLED'")):
            ok(L('lg_cc_invoices', fl_(**cas), lim=200)['total'] == n_("select count(*) from logistics.invoice where status <> 'DRAFT' and %s" % att_), 'factures, filtre %s : identique au décompte indépendant' % cas)
        for cas in (dict(client=code_a), dict(client=code_b), dict(client='brien'), dict(de=q("select %s::text" % JOUR)), dict(a=q("select (%s - 1)::text" % JOUR)), dict(statut='UNPAID', client=code_a)):
            c_ = ["i.status <> 'DRAFT'"]
            if cas.get('client'): c_.append(client_sql(cas['client'], 'cu'))
            if cas.get('statut') == 'UNPAID': c_.append("i.status not in ('CANCELLED') and (i.total - i.credited_amount) - (i.paid_amount - i.refunded_amount) > 0")
            c_.append(periode('i.issued_at', {'from': cas.get('de'), 'to': cas.get('a')}))
            ok(L('lg_cc_invoices', fl_(**cas), lim=200)['total'] == n_("select count(*) from logistics.invoice i join logistics.customer cu on cu.id = i.customer_id where %s" % ' and '.join(c_)), 'factures, filtre %s : identique au décompte indépendant' % cas)

        # ------------------------------------------------------------ paiements
        pa = pagination('lg_cc_payments', 'number', None, n_("select (select count(*) from logistics.payment) + (select count(*) from logistics.refund) + (select count(*) from logistics.credit)"), None)
        ok(pa['total'] == 7 and sorted(i_['kind'] for i_ in pa['items']) == ['CREDIT', 'CREDIT', 'PAYMENT', 'PAYMENT', 'PAYMENT', 'REFUND', 'REFUND'], 'sept lignes : trois paiements, deux remboursements, deux avoirs')
        ok(pa['collected_usd'] == D('54.00') and pa['refunded_usd'] == D('28.00'), 'encaissé 54 USD (22 + 7 + 25), remboursé 28 USD (3 + 25)')
        rf = [i_ for i_ in pa['items'] if i_['kind'] == 'REFUND' and i_['amount'] == D('-3.00')][0]; cr_ = [i_ for i_ in pa['items'] if i_['kind'] == 'CREDIT' and i_['amount'] == D('5.00')][0]
        ok(rf['amount'] == D('-3.00') and rf['reason'] and 'mécontent' in rf['reason'] and cr_['amount'] == D('5.00') and cr_['reason'] and [i_['at'] for i_ in pa['items']] == sorted((i_['at'] for i_ in pa['items']), reverse=True), 'le remboursement est négatif et garde son motif INTERNE (l\'équipe le voit) ; l\'avoir est positif ; du plus récent au plus ancien')
        for cas, att_ in ((dict(statut='PAYMENT'), 3), (dict(statut='REFUND'), 2), (dict(statut='CREDIT'), 2), (dict(client=code_a), 6), (dict(client=code_b), 1), (dict(de=q("select %s::text" % JOUR)), 7), (dict(a=q("select (%s - 1)::text" % JOUR)), 0), (dict(statut='PAYMENT', client=code_b), 1)):
            r_ = L('lg_cc_payments', fl_(**cas), lim=200)
            ok(r_['total'] == att_ == len(r_['items']), 'paiements, filtre %s : %d' % (cas, att_))
        ok(L('lg_cc_payments', fl_(a=q("select (%s - 1)::text" % JOUR)))['collected_usd'] == 0 and L('lg_cc_payments', fl_(statut='REFUND'))['collected_usd'] == 0 and L('lg_cc_payments', fl_(client=code_b))['collected_usd'] == D('7.00'), 'les totaux suivent les filtres')

        # ------------------------------------------------------------ support
        tks = pagination('lg_cc_tickets', 'ticket_id', None, 3, [tk_1['ticket_id'], tk_2['ticket_id'], tk_3['ticket_id']])
        ok(tks['by_status'] == {'OPEN': 3} and all(i_['last_author'] == 'CUSTOMER' and i_['messages'] == 1 and i_['waiting_hours'] == 0 for i_ in tks['items']), 'trois tickets ouverts, chacun avec un seul message du client, en attente depuis 0 heure')
        t1_ = tks['items'][0]
        ok(t1_['number'] == tk_1['number'] and t1_['subject'] == 'Mon colis N-001' and t1_['category'] == 'PARCEL' and t1_['customer_code'] == code_a, 'le plus ancien en premier : sujet, catégorie, client')
        for cas, att_ in ((dict(statut='OPEN'), 3), (dict(statut='ACTIVE'), 3), (dict(statut='ANSWERED'), 0), (dict(statut='CLOSED'), 0), (dict(client=code_a), 2), (dict(client=code_b), 1), (dict(de=q("select %s::text" % JOUR)), 3), (dict(a=q("select (%s - 1)::text" % JOUR)), 0)):
            ok(L('lg_cc_tickets', fl_(**cas), lim=200)['total'] == att_, 'tickets, filtre %s : %d' % (cas, att_))
        td = f('lg_cc_ticket', admin, p_id=tk_1['ticket_id'])
        ok(td['number'] == tk_1['number'] and td['customer'] == {'code': code_a, 'name': q("select full_name from logistics.customer where id = '%s'" % ca), 'email': 'client9@essai.test', 'phone': q("select phone from logistics.customer where id = '%s'" % ca)} and td['parcel'] == 'N-001' and td['invoice'] is None
           and [(m_['author'], m_['body'], m_['staff']) for m_ in td['messages']] == [('CUSTOMER', 'Où est-il ?', None)] and td['status'] == 'OPEN', 'la fiche du ticket : le client (avec son e-mail), le colis lié, les messages, sans auteur du personnel pour le message du client')
        fr('lg_cc_ticket', 'LG002', 'ticket inconnu', admin, p_id=R("gen_random_uuid()"))
        ok(L('lg_cc_tickets', who=soutien)['total'] == 3 and f('lg_cc_ticket', soutien, p_id=tk_2['ticket_id'])['customer']['code'] == code_b, 'le support (droit « clients.lire » seul) lit les tickets et leurs fiches')

        # ------------------------------------------------------------ utilisateurs
        ordre_u = cl.lignes(B, "select a.email from logistics.app_user u join auth.users a on a.id = u.id order by u.role desc, a.email")
        us = pagination('lg_cc_users', 'email', None, n_("select count(*) from logistics.app_user"), ordre_u)
        u_ = {i_['email']: i_ for i_ in us['items']}
        ok(u_['client1@essai.test']['role'] == 'admin' and u_['client2@essai.test']['role'] == 'manager' and u_['client3@essai.test']['rights'] == ['colis.lire', 'colis.statut'] and u_['caisse22@essai.test']['rights'] == ['factures.lire'], 'rôles et droits tels que la base les tient')
        ok(u_['chauffeur21@essai.test']['driver'] is True and u_['client1@essai.test']['driver'] is False and all(i_['active'] for i_ in us['items']) and set(us['items'][0]) == {'user_id', 'email', 'role', 'rights', 'active', 'branch', 'driver', 'last_sign_in_at', 'created_at'}, 'qui est chauffeur ; tous actifs ; jamais de mot de passe ni de jeton')
        for cas, att_ in ((dict(statut='admin'), ['client1@essai.test']), (dict(statut='manager'), ['client2@essai.test']), (dict(statut='employee'), None), (dict(statut='INACTIVE'), []), (dict(client='CAISSE'), ['caisse22@essai.test']), (dict(client='%'), [])):
            r_ = [i_['email'] for i_ in L('lg_cc_users', fl_(**cas), lim=200)['items']]
            ok(r_ == att_ if att_ is not None else len(r_) == n_("select count(*) from logistics.app_user where role = 'employee'"), 'utilisateurs, filtre %s : %s' % (cas, att_ if att_ is not None else 'tous les employés'))
        q("update logistics.app_user set active = false where id = '%s'" % soutien)
        ok([i_['email'] for i_ in L('lg_cc_users', fl_(statut='INACTIVE'), lim=200)['items']] == ['support23@essai.test'], 'un compte désactivé se retrouve par « INACTIVE »')
        q("update logistics.app_user set active = true where id = '%s'" % soutien)

        # ------------------------------------------------------------ journal d'audit
        n_aud = n_("select count(*) from logistics.audit_log")
        au = pagination('lg_cc_audit', 'id', None, n_aud, [int(x_) for x_ in cl.lignes(B, "select id from logistics.audit_log order by occurred_at desc, id desc limit 200")])
        ok(set(au['items'][0]) == {'id', 'at', 'actor', 'action', 'entity_type', 'entity_id', 'before', 'after', 'metadata', 'correlation_id'}, 'une ligne d\'audit : qui, quand, quoi, avant, après, corrélation')
        ok(L('lg_cc_audit', fl_(statut='address.'), lim=200)['total'] == n_("select count(*) from logistics.audit_log where action like 'address.%'") > 0 and L('lg_cc_audit', fl_(statut='%'), lim=200)['total'] == 0, 'filtre par préfixe d\'action ; les jokers sont des caractères')
        ok(L('lg_cc_audit', fl_(client='customer:'), lim=200)['total'] == n_("select count(*) from logistics.audit_log where position('customer:' in lower(actor_label)) > 0") > 0, 'filtre par auteur (le libellé de l\'acteur)')
        ok(L('lg_cc_audit', fl_(de=q("select %s::text" % JOUR)), lim=200)['total'] == n_aud and L('lg_cc_audit', fl_(a=q("select (%s - 1)::text" % JOUR)), lim=200)['total'] == 0, 'filtre par période')
        ok(L('lg_cc_audit', who=gerant)['total'] == n_aud, 'le gérant lit aussi le journal d\'audit')

        # ------------------------------------------------------------ réglages
        st = f('lg_cc_settings', admin)
        ok([b_['code'] for b_ in st['branches']] == cl.lignes(B, "select code from logistics.branch order by code") and [w_['code'] for w_ in st['warehouses']] == ['MIA-1', 'PAP-1', 'SDQ-1'] and sorted(m_['code'] for m_ in st['transport_modes']) == ['air', 'ground', 'sea'], 'succursales, entrepôts, modes de transport')
        ok(st['pricing']['rate_cards_active'] == n_("select count(*) from logistics.rate_card where active") == 1 and st['pricing']['zones_active'] == 1 and st['pricing']['surcharges_active'] == 0 and st['pricing']['rules_active'] == 0 and st['pricing']['taxes_active'] == 0, 'tarification : une grille, une zone, ni surtaxe, ni règle, ni taxe')
        ok(st['pricing']['service_fee'] == [{'code': 'SERVICE', 'amount': D('10.00'), 'currency': 'USD'}] and all(set(e_) == {'from', 'to', 'rate', 'valid_from'} for e_ in st['pricing']['exchange_rates']), 'les 10 USD de frais de service ; les taux de change')
        ok(st['delivery'] == {'zones': 1, 'vehicles': 1, 'drivers': 1} and st['events'] == {'pending': n_("select count(*) from logistics.event_delivery where status = 'PENDING'"), 'dead': n_("select count(*) from logistics.dead_letter")}, 'livraison : une zone, un véhicule, un chauffeur actif ; file d\'événements')
        ok(st['organization']['default_currency'] == 'USD' and 'service_role' not in texte(st) and 'password' not in texte(st), 'organisation, devise ; aucun secret dans les réglages')

        # ============================================================== E. L'ÉQUIPE TRAITE LES DEMANDES ET LE SUPPORT
        def fin_fp():
            return q("select md5(concat_ws('|', " + ', '.join("(select coalesce(string_agg(md5(x::text), '' order by x.id), '') from logistics.%s x)" % t_ for t_ in ('invoice', 'invoice_item', 'payment', 'refund', 'credit', 'revenue_entry', 'app_user', 'customer')) + "))")
        fin0 = fin_fp()
        ev = lambda t_: n_("select count(*) from logistics.domain_event where event_type = '%s'" % t_)   # noqa: E731
        HIER = q("select (%s - 1)::text" % JOUR)
        # ---- enlèvements
        for nom_, u_ in (('un lecteur (sans « colis.statut »)', lecteur), ('un agent de support', soutien), ('la caisse', caisse)):
            fr('lg_cc_review_pickup', 'LG003', '%s ne traite pas les demandes' % nom_, u_, p_id=pk_a['pickup_id'], p_approve=True)
            fr('lg_cc_review_delivery', 'LG003', '%s ne traite pas les demandes de livraison' % nom_, u_, p_id=dr_a['request_id'], p_approve=True)
        n_aud0, n_task0 = n_("select count(*) from logistics.audit_log"), n_("select count(*) from logistics.task")
        fr('lg_cc_review_pickup', 'LG002', 'une demande inconnue', op, p_id=R("gen_random_uuid()"), p_approve=True)
        fr('lg_cc_review_pickup', 'LG005', 'ni approuvée ni refusée : il faut choisir', op, p_id=pk_a['pickup_id'], p_approve=R('null'))
        fr('lg_cc_review_pickup', 'LG005', 'un message de 501 caractères', op, p_id=pk_a['pickup_id'], p_approve=True, p_message='m' * 501)
        fr('lg_cc_review_pickup', 'LG005', 'refuser sans dire pourquoi', op, p_id=pk_a['pickup_id'], p_approve=False)
        fr('lg_cc_review_pickup', 'LG005', 'refuser avec un message fait d\'espaces', op, p_id=pk_a['pickup_id'], p_approve=False, p_message='   ')
        fr('lg_cc_review_pickup', 'LG005', 'approuver pour une date passée', op, p_id=pk_a['pickup_id'], p_approve=True, p_date=HIER)
        ok(q("select status from logistics.pickup_request where id = '%s'" % pk_a['pickup_id']) == 'REQUESTED' and n_("select count(*) from logistics.audit_log") == n_aud0 and n_("select count(*) from logistics.task") == n_task0 and ev('PickupRequestApproved') == 0,
           'tous ces refus : la demande est intacte, aucune mission, aucune trace dans l\'audit, aucun événement')
        r1 = f('lg_cc_review_pickup', op, p_id=pk_a['pickup_id'], p_approve=True, p_message='Nous passons le matin')
        ok(r1['status'] == 'APPROVED' and r1['date'] == DANS3 and r1['task_id'] and r1['correlation_id'], 'approbation : une mission d\'enlèvement est créée pour la date souhaitée')
        tsk = cl.lignes(B, "select kind || '|' || status || '|' || customer_id || '|' || address || '|' || scheduled_date || '|' || parcels_expected || '|' || (window_start = (('%s'::date + time '08:00') at time zone 'America/Port-au-Prince')) || '|' || (window_end = (('%s'::date + time '12:00') at time zone 'America/Port-au-Prince')) from logistics.task where id = '%s'" % (DANS3, DANS3, r1['task_id']))[0].split('|')
        ok(tsk == ['PICKUP', 'CREATED', ca, '12 rue des Fleurs, Pétion-Ville', DANS3, '2', 'true', 'true'], 'la mission : enlèvement chez A, à l\'adresse de la demande, créneau du matin (8 h – 12 h, heure d\'Haïti), 2 colis attendus. Obtenu : %s' % tsk)
        rq_ = cl.lignes(B, "select status || '|' || coalesce(task_id::text, '') || '|' || coalesce(review_message, '') || '|' || (reviewed_by = '%s') from logistics.pickup_request where id = '%s'" % (op, pk_a['pickup_id']))[0].split('|')
        ok(rq_ == ['APPROVED', r1['task_id'], 'Nous passons le matin', 'true'], 'la demande : approuvée, liée à sa mission, message conservé, relecteur = l\'employé')
        mp = [x_ for x_ in f('lg_my_pickups', ua) if x_['pickup_id'] == pk_a['pickup_id']][0]
        ok(mp['stage'] == 'scheduled' and mp['message'] == 'Nous passons le matin' and mp['request_status'] == 'APPROVED', 'LE CLIENT le voit dans son portail : planifié, avec le message de l\'équipe')
        fr('lg_cc_review_pickup', 'LG004', 'traiter deux fois la même demande', op, p_id=pk_a['pickup_id'], p_approve=True)
        fr('lg_cc_review_pickup', 'LG004', 'refuser une demande déjà approuvée', op, p_id=pk_a['pickup_id'], p_approve=False, p_message='non')
        ok(n_("select count(*) from logistics.task where kind = 'PICKUP' and customer_id = '%s'" % ca) == 2 and ev('PickupRequestApproved') == 1, 'et rien n\'a été créé en double (la mission de A : la sienne et celle du téléphone)')
        r1b = f('lg_cc_review_pickup', gerant, p_id=pk_b['pickup_id'], p_approve=False, p_message='Adresse hors de notre zone')
        ok(r1b['status'] == 'REJECTED' and q("select review_message from logistics.pickup_request where id = '%s'" % pk_b['pickup_id']) == 'Adresse hors de notre zone' and q("select task_id is null from logistics.pickup_request where id = '%s'" % pk_b['pickup_id']) == 't', 'refus par le gérant : motif enregistré, aucune mission')
        mpb = [x_ for x_ in f('lg_my_pickups', ub) if x_['pickup_id'] == pk_b['pickup_id']][0]
        ok(mpb['stage'] == 'rejected' and mpb['message'] == 'Adresse hors de notre zone', 'B lit le refus et son motif dans son portail')
        r1c = f('lg_cc_review_pickup', admin, p_id=pk_c['pickup_id'], p_approve=True, p_date=R("current_date + 12"))
        ok(r1c['date'] == q("select (current_date + 12)::text") and q("select scheduled_date::text from logistics.task where id = '%s'" % r1c['task_id']) == r1c['date'], 'approbation avec une AUTRE date que celle demandée : la mission suit la date de l\'équipe')
        ok(q("select (window_start is null and window_end is null)::text from logistics.task where id = '%s'" % r1c['task_id']) == 'true' and q("select preferred_date::text from logistics.pickup_request where id = '%s'" % pk_c['pickup_id']) == DANS9, 'sans créneau demandé : pas de fenêtre ; la date souhaitée du client reste ce qu\'il avait écrit')
        ok(L('lg_cc_pickups', fl_(statut='requested'))['total'] == 0 and L('lg_cc_pickups')['by_stage'] == {'rejected': 1, 'scheduled': 3}, 'la liste de l\'équipe : plus rien en attente — un refusé, trois planifiés')
        ok(L('lg_cc_kpis', admin)['operations']['pickup_requests_pending'] == 0 if False else f('lg_cc_kpis', admin)['operations']['pickup_requests_pending'] == 0, 'l\'indicateur des demandes d\'enlèvement en attente tombe à zéro')
        # ---- livraisons
        parc_a = cl.lignes(B, "select tracking_number from logistics.delivery_request_parcel rp join logistics.parcel p on p.id = rp.parcel_id where rp.request_id = '%s' order by 1" % dr_a['request_id'])
        parc_b = cl.lignes(B, "select p.id from logistics.delivery_request_parcel rp join logistics.parcel p on p.id = rp.parcel_id where rp.request_id = '%s'" % dr_b['request_id'])
        ok(len(parc_a) == 2 and len(parc_b) == 1, 'la demande de A porte 2 colis, celle de B 1 colis')
        fr('lg_cc_review_delivery', 'LG002', 'une demande de livraison inconnue', op, p_id=R("gen_random_uuid()"), p_approve=True)
        fr('lg_cc_review_delivery', 'LG005', 'ni approuvée ni refusée', op, p_id=dr_a['request_id'], p_approve=R('null'))
        fr('lg_cc_review_delivery', 'LG005', 'refuser sans motif', op, p_id=dr_a['request_id'], p_approve=False)
        fr('lg_cc_review_delivery', 'LG005', 'un message de 501 caractères', op, p_id=dr_a['request_id'], p_approve=True, p_message='m' * 501)
        fr('lg_cc_review_delivery', 'LG005', 'approuver pour une date passée', op, p_id=dr_a['request_id'], p_approve=True, p_date=HIER)
        ok(q("select status from logistics.delivery_request where id = '%s'" % dr_a['request_id']) == 'REQUESTED', 'la demande de livraison est intacte après ces refus')
        r2 = f('lg_cc_review_delivery', gerant, p_id=dr_a['request_id'], p_approve=True, p_message='Livraison confirmée', p_hub_branch=pap)
        ok(r2['status'] == 'APPROVED' and r2['delivery_id'] and r2['task_id'] and r2['date'] == DANS3, 'approbation : une livraison est créée avec sa mission')
        dtk = cl.lignes(B, "select t.kind || '|' || t.status || '|' || t.scheduled_date || '|' || t.address || '|' || (t.window_start = (('%s'::date + time '12:00') at time zone 'America/Port-au-Prince')) || '|' || (t.window_end = (('%s'::date + time '17:00') at time zone 'America/Port-au-Prince')) from logistics.task t where t.id = '%s'" % (DANS3, DANS3, r2['task_id']))[0].split('|')
        ok(dtk == ['DELIVERY', 'CREATED', DANS3, '12 rue des Fleurs, Pétion-Ville', 'true', 'true'], 'la mission de livraison : date, adresse de la demande, créneau de l\'après-midi (12 h – 17 h). Obtenu : %s' % dtk)
        ok(sorted(cl.lignes(B, "select p.tracking_number from logistics.delivery_parcel dp join logistics.parcel p on p.id = dp.parcel_id where dp.delivery_id = '%s'" % r2['delivery_id'])) == parc_a and
           all(q("select status from logistics.parcel where tracking_number = '%s'" % t_) == 'DELIVERY_ASSIGNED' for t_ in parc_a), 'les deux colis de la demande sont dans la livraison et passent à « affecté à une livraison » (par la machine d\'états, pas à la main)')
        mdl = [x_ for x_ in f('lg_my_deliveries', ua)['requests'] if x_['request_id'] == dr_a['request_id']][0]
        ok(mdl['stage'] == 'scheduled' and mdl['message'] == 'Livraison confirmée' and mdl['request_status'] == 'APPROVED', 'A le voit dans son portail : planifiée, avec le message de l\'équipe')
        fr('lg_cc_review_delivery', 'LG004', 'traiter deux fois', op, p_id=dr_a['request_id'], p_approve=True)
        ok(n_("select count(*) from logistics.delivery d where d.id = '%s'" % r2['delivery_id']) == 1 and n_("select count(*) from logistics.delivery_request where status = 'APPROVED'") == 1, 'une seule livraison créée')
        # atomicité : un colis de la demande de B change d'état avant l'approbation → l'approbation échoue ENTIÈREMENT
        q("select 1")
        f('lg_transition_parcel', admin, p_parcel_id=parc_b[0], p_to_status='ON_HOLD', p_reason='contrôle avant livraison')
        n_aud1, n_task1, n_dl1, n_ev1 = n_("select count(*) from logistics.audit_log"), n_("select count(*) from logistics.task"), n_("select count(*) from logistics.delivery"), n_("select count(*) from logistics.domain_event where event_type = 'DeliveryRequestApproved'")
        code, texte_ = cl.run(B, appel('lg_cc_review_delivery', p_id=dr_b['request_id'], p_approve=True), role='authenticated', claims=op, expect_error=True)
        ok(code != 0 and ('LG004' in texte_ or 'LG005' in texte_), 'un colis retenu empêche l\'approbation : %s' % texte_[-200:].replace('\n', ' '))
        ok(q("select status from logistics.delivery_request where id = '%s'" % dr_b['request_id']) == 'REQUESTED' and n_("select count(*) from logistics.task") == n_task1 and n_("select count(*) from logistics.delivery") == n_dl1
           and n_("select count(*) from logistics.audit_log") == n_aud1 and n_("select count(*) from logistics.domain_event where event_type = 'DeliveryRequestApproved'") == n_ev1, 'et RIEN n\'a changé : la demande reste en attente, ni mission, ni livraison, ni audit, ni événement (tout ou rien)')
        r2b = f('lg_cc_review_delivery', op, p_id=dr_b['request_id'], p_approve=False, p_message='Le colis est retenu pour contrôle')
        ok(r2b['status'] == 'REJECTED' and [x_ for x_ in f('lg_my_deliveries', ua)['requests'] if x_['request_id'] == dr_b['request_id']][0]['message'] == 'Le colis est retenu pour contrôle', 'refusée avec un message que le client lit')
        ok(q("select status from logistics.parcel where id = '%s'" % parc_b[0]) == 'ON_HOLD', 'refuser ne touche pas au colis')
        ok(f('lg_cc_kpis', admin)['operations']['delivery_requests_pending'] == 0 and L('lg_cc_deliveries', fl_(statut='requested'))['total'] == 0 and L('lg_cc_deliveries', fl_(statut='rejected'))['total'] == 1, 'indicateur à zéro ; la liste montre une demande refusée')
        # un hub par défaut quand l'équipe n'en choisit pas : le premier par code
        pk_x = f('lg_request_delivery', ua, p_tracking_numbers=cl.lignes(B, "select tracking_number from logistics.parcel p where customer_id = '%s' and status = 'AT_DESTINATION_HUB' and not exists (select 1 from logistics.delivery_parcel dp where dp.parcel_id = p.id) order by 1 limit 1" % ca), p_preferred_date=DANS3, p_address='1 rue Libre', p_city='Jacmel', p_country='HT')
        r2c = f('lg_cc_review_delivery', admin, p_id=pk_x['request_id'], p_approve=True, p_date=R("current_date + 5"))
        ok(r2c['date'] == q("select (current_date + 5)::text") and q("select scheduled_date::text from logistics.task where id = '%s'" % r2c['task_id']) == r2c['date'], 'approbation avec une AUTRE date que celle demandée : la mission suit la date de l\'équipe')
        ok(q("select h.code from logistics.delivery d join logistics.branch h on h.id = d.destination_branch_id where d.id = '%s'" % r2c['delivery_id']) == 'PAP', 'sans hub indiqué : le premier hub actif par code (PAP)')
        q("update logistics.branch set active = false where kind = 'hub'")
        pk_y = f('lg_request_delivery', ua, p_tracking_numbers=cl.lignes(B, "select tracking_number from logistics.parcel p where customer_id = '%s' and status = 'AT_DESTINATION_HUB' and not exists (select 1 from logistics.delivery_parcel dp where dp.parcel_id = p.id) order by 1 limit 1" % ca), p_preferred_date=DANS3, p_address='2 rue Libre', p_city='Jacmel', p_country='HT')
        fr('lg_cc_review_delivery', 'LG005', 'aucun hub actif : il faut en choisir un', admin, p_id=pk_y['request_id'], p_approve=True)
        q("update logistics.branch set active = true where kind = 'hub'")
        # ---- support
        n_msg = lambda t_: n_("select count(*) from logistics.support_message where ticket_id = '%s'" % t_)   # noqa: E731
        fr('lg_cc_reply_ticket', 'LG003', 'la caisse (sans « clients.lire ») ne répond pas aux tickets', caisse, p_id=tk_1['ticket_id'], p_body='x')
        fr('lg_cc_reply_ticket', 'LG005', 'une réponse vide', soutien, p_id=tk_1['ticket_id'], p_body='   ')
        fr('lg_cc_reply_ticket', 'LG005', 'une réponse de 4001 caractères', soutien, p_id=tk_1['ticket_id'], p_body='m' * 4001)
        fr('lg_cc_reply_ticket', 'LG002', 'un ticket inconnu', soutien, p_id=R("gen_random_uuid()"), p_body='x')
        ok(n_msg(tk_1['ticket_id']) == 1 and ev('SupportTicketAnswered') == 0, 'aucun de ces refus n\'a écrit quoi que ce soit')
        rr = f('lg_cc_reply_ticket', soutien, p_id=tk_1['ticket_id'], p_body='  Votre colis est au hub de Port-au-Prince.  ')
        ok(rr['status'] == 'ANSWERED' and n_msg(tk_1['ticket_id']) == 2 and q("select status from logistics.support_ticket where id = '%s'" % tk_1['ticket_id']) == 'ANSWERED', 'réponse : le ticket passe à « répondu », le message est enregistré')
        td2 = f('lg_cc_ticket', admin, p_id=tk_1['ticket_id'])
        ok([(m_['author'], m_['body'], m_['staff']) for m_ in td2['messages']] == [('CUSTOMER', 'Où est-il ?', None), ('STAFF', 'Votre colis est au hub de Port-au-Prince.', 'support23@essai.test')], 'la fiche : les deux messages, le texte sans espaces autour, l\'auteur du personnel (l\'e-mail n\'est visible que de l\'équipe)')
        mt = f('lg_my_ticket', ua, p_id=tk_1['ticket_id'])
        ok(mt['status'] == 'ANSWERED' and [m_['author'] for m_ in mt['messages']] == ['CUSTOMER', 'STAFF'] and 'support23' not in texte(mt) and 'essai.test' not in texte(mt), 'LE CLIENT lit la réponse dans son portail — sans l\'e-mail de l\'agent')
        ok(L('lg_cc_tickets', fl_(statut='ANSWERED'))['total'] == 1 and L('lg_cc_tickets', fl_(statut='ANSWERED'))['items'][0]['last_author'] == 'STAFF' and L('lg_cc_tickets', fl_(statut='ANSWERED'))['items'][0]['waiting_hours'] is None, 'dans la liste de l\'équipe : « répondu », dernier auteur = l\'équipe, plus d\'attente')
        ok(f('lg_cc_kpis', admin)['support'] == {'tickets_open': 3, 'tickets_waiting_staff': 2}, 'indicateurs de support : trois ouverts, deux attendent encore l\'équipe')
        f('lg_reply_ticket', ua, p_id=tk_1['ticket_id'], p_body='Merci, je passe le chercher.')
        ok(q("select status from logistics.support_ticket where id = '%s'" % tk_1['ticket_id']) == 'OPEN' and f('lg_cc_kpis', admin)['support']['tickets_waiting_staff'] == 3, 'le client répond : le ticket redevient « ouvert » et attend l\'équipe')
        rc = f('lg_cc_close_ticket', soutien, p_id=tk_1['ticket_id'])
        ok(rc['status'] == 'CLOSED' and q("select (closed_at is not null)::text from logistics.support_ticket where id = '%s'" % tk_1['ticket_id']) == 'true', 'fermeture par l\'équipe')
        fr('lg_cc_close_ticket', 'LG004', 'fermer deux fois', soutien, p_id=tk_1['ticket_id'])
        fr('lg_cc_reply_ticket', 'LG004', 'répondre à un ticket fermé', soutien, p_id=tk_1['ticket_id'], p_body='trop tard')
        fr('lg_reply_ticket', 'LG004', 'et le client non plus', ua, p_id=tk_1['ticket_id'], p_body='trop tard')
        fr('lg_cc_close_ticket', 'LG003', 'la caisse ne ferme pas de ticket', caisse, p_id=tk_2['ticket_id'])
        fr('lg_cc_close_ticket', 'LG002', 'un ticket inconnu', soutien, p_id=R("gen_random_uuid()"))
        # le plafond de 100 messages
        q("insert into logistics.support_message (ticket_id, author_kind, body) select '%s', 'CUSTOMER', 'm' || g from generate_series(1, 98) g" % tk_3['ticket_id'])
        ok(n_msg(tk_3['ticket_id']) == 99, 'un ticket à 99 messages')
        f('lg_cc_reply_ticket', soutien, p_id=tk_3['ticket_id'], p_body='cent')
        fr('lg_cc_reply_ticket', 'LG005', 'le 101e message', soutien, p_id=tk_3['ticket_id'], p_body='cent un')
        # ---- la trace : audit et événements, un par action, au nom de la bonne personne
        AUDITS = [('pickup_request.approve', 2, [op, admin]), ('pickup_request.reject', 1, [gerant]), ('delivery_request.approve', 2, [gerant, admin]), ('delivery_request.reject', 1, [op]), ('ticket.reply', 2, [soutien, soutien]), ('ticket.close', 1, [soutien])]
        for act_, n_att, auteurs in AUDITS:
            lignes_a = cl.lignes(B, "select actor_user_id || '|' || entity_id || '|' || (before ->> 'status') || '|' || (after ->> 'status') || '|' || coalesce(correlation_id::text, '') from logistics.audit_log where action = '%s' order by id" % act_)
            ok(len(lignes_a) == n_att and sorted(x_.split('|')[0] for x_ in lignes_a) == sorted(auteurs), 'audit « %s » : %d ligne(s), au nom de la bonne personne' % (act_, n_att))
            ok(all(x_.split('|')[4] for x_ in lignes_a), 'audit « %s » : chaque ligne porte son identifiant de corrélation' % act_)
        ok(cl.lignes(B, "select before ->> 'status' || '>' || (after ->> 'status') from logistics.audit_log where action = 'pickup_request.approve' order by id") == ['REQUESTED>APPROVED'] * 2 and
           cl.lignes(B, "select before ->> 'status' || '>' || (after ->> 'status') from logistics.audit_log where action = 'ticket.close'") == ['OPEN>CLOSED'], 'avant → après : le statut change comme annoncé')
        ok(r1['correlation_id'] in cl.lignes(B, "select correlation_id from logistics.audit_log where action = 'pickup_request.approve'") and r1['correlation_id'] in cl.lignes(B, "select correlation_id from logistics.domain_event where event_type = 'PickupRequestApproved'"), 'l\'audit et l\'événement partagent la corrélation de l\'action')
        for typ_, att_ in (('PickupRequestApproved', 2), ('PickupRequestRejected', 1), ('DeliveryRequestApproved', 2), ('DeliveryRequestRejected', 1), ('SupportTicketAnswered', 2), ('SupportTicketClosedByStaff', 1)):
            ok(ev(typ_) == att_ and n_("select count(*) from logistics.domain_event where event_type = '%s' and actor_user_id is not null and payload ? 'customer_id'" % typ_) == att_, 'événement %s : %d, au nom du membre de l\'équipe, avec le client concerné' % (typ_, att_))
        ok(all(q("select customer_visible::text from logistics.event_type where code = '%s'" % t_) == 'false' for t_ in ('PickupRequestApproved', 'PickupRequestRejected', 'DeliveryRequestApproved', 'DeliveryRequestRejected', 'SupportTicketAnswered', 'SupportTicketClosedByStaff')), 'ces six événements ne sont pas des étapes du suivi du colis')
        ok(fin_fp() == fin0, 'traiter les demandes et le support ne touche ni aux factures, ni aux paiements, ni au revenu, ni aux comptes')
        for t_ in (f('lg_cc_parcel', admin, p_tracking=parc_a[0]),):
            ok(any(e_['event'] in ('DeliveryAssigned', 'ParcelStatusChanged') for e_ in t_['timeline']), 'le colis affecté porte son événement dans le journal (la machine d\'états a travaillé)')

        # ============================================================== F. LA STRUCTURE : portes, droits d'exécution, rien d'ouvert par erreur
        facade = cl.lignes(B, "select p.proname || '|' || p.prosecdef || '|' || coalesce(array_to_string(p.proconfig, ','), '') || '|' || has_function_privilege('authenticated', p.oid, 'execute') || '|' || has_function_privilege('anon', p.oid, 'execute') || '|' || coalesce(array_to_string(p.proargnames, ','), '') "
                                   "from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\\_cc\\_%' order by 1")
        ok(len(facade) == 28, 'vingt-huit fonctions de façade pour le centre de commande : %d' % len(facade))
        for l_ in facade:
            nom_, sec_, conf_, auth_, anon_, args_ = l_.split('|')
            ok(sec_ == 'true' and 'search_path=""' in conf_ and auth_ == 'true' and anon_ == 'false', '%s : droits de définisseur, chemin de recherche vidé, ouverte aux connectés seulement' % nom_)
            ok(not any(m_ in args_ for m_ in ('actor', 'user', 'uid', 'auth')), '%s : aucun paramètre ne désigne l\'acteur (c\'est toujours le compte connecté) : %s' % (nom_, args_))
        internes = cl.lignes(B, "select p.proname || '|' || has_function_privilege('authenticated', p.oid, 'execute') || '|' || has_function_privilege('anon', p.oid, 'execute') || '|' || (p.proconfig is not null) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
                                "where n.nspname = 'logistics' and (p.proname like 'cc\\_%' or p.proname = 'today')")
        ok(len(internes) >= 30, 'les fonctions internes du centre : %d' % len(internes))
        ok(all(l_.split('|')[1:] == ['false', 'false', 'true'] for l_ in internes), 'aucune fonction interne du centre n\'est exécutable par un connecté ni par un visiteur, et toutes ont un chemin de recherche fixé')
        ok(n_("select count(*) from pg_tables where schemaname = 'logistics' and not rowsecurity") == 0 and n_("select count(*) from information_schema.role_table_grants where table_schema = 'logistics' and grantee in ('anon', 'authenticated', 'PUBLIC')") == 0, 'toutes les tables du noyau : sécurité par ligne activée, aucun droit pour les connectés ni les visiteurs')
        for sql_ in ("select * from logistics.pickup_request", "select * from logistics.audit_log", "select * from logistics.support_message", "update logistics.pickup_request set status = 'APPROVED'", "delete from logistics.audit_log",
                     "insert into logistics.support_message (ticket_id, author_kind, body) values (gen_random_uuid(), 'STAFF', 'piraté')", "select * from logistics.customer_balance", "select logistics.cc_kpis('%s')" % admin,
                     "select logistics.cc_review_pickup('%s', '%s', true)" % (admin, pk_c['pickup_id']), "select logistics.today()"):
            for qui_, kw_ in (('un client connecté', dict(role='authenticated', claims=ua)), ('le membre de la direction connecté', dict(role='authenticated', claims=admin)), ('un visiteur', dict(role='anon'))):
                code, texte_ = cl.run(B, sql_, expect_error=True, **kw_)
                ok(code != 0 and ('permission denied' in texte_ or '42501' in texte_), '%s ne peut pas exécuter « %s » : %s' % (qui_, sql_[:70], texte_[-120:].replace('\n', ' ')))

        # lire ne modifie RIEN : l'empreinte de TOUTES les tables du noyau avant et après avoir ouvert chaque vue, deux fois
        def empreinte_totale():
            return {t_: q("select count(*) || ':' || coalesce(md5(string_agg(md5(x::text), '' order by md5(x::text))), '') from logistics.\"%s\" x" % t_) for t_ in cl.lignes(B, "select tablename from pg_tables where schemaname = 'logistics' order by 1")}
        avant_lect = empreinte_totale()
        REPONSES = {}
        for _ in range(2):
            REPONSES = {'acces': f('lg_cc_access', admin), 'indicateurs': f('lg_cc_kpis', admin), 'a_traiter': f('lg_cc_attention', admin), 'flux': f('lg_cc_flow', admin), 'colis': f('lg_cc_parcels', admin, p_limit=3), 'fiche_colis': f('lg_cc_parcel', admin, p_tracking='N-001'),
                        'expeditions': f('lg_cc_shipments', admin), 'entrepot': f('lg_cc_warehouse', admin), 'consolidations': f('lg_cc_consolidations', admin), 'transport': f('lg_cc_transports', admin), 'chauffeurs': f('lg_cc_drivers', admin),
                        'enlevements': f('lg_cc_pickups', admin), 'livraisons': f('lg_cc_deliveries', admin), 'douane': f('lg_cc_customs', admin), 'incidents': f('lg_cc_incidents', admin), 'notifications': f('lg_cc_notifications', admin, p_limit=3),
                        'clients': f('lg_cc_customers', admin, p_limit=3), 'factures': f('lg_cc_invoices', admin, p_limit=3), 'paiements': f('lg_cc_payments', admin), 'tickets': f('lg_cc_tickets', admin), 'fiche_ticket': f('lg_cc_ticket', admin, p_id=tk_1['ticket_id']),
                        'utilisateurs': f('lg_cc_users', admin, p_limit=3), 'audit': f('lg_cc_audit', admin, p_limit=3), 'reglages': f('lg_cc_settings', admin)}
        ok(empreinte_totale() == avant_lect, 'AUCUNE des %d tables du noyau n\'a changé d\'un octet après avoir ouvert les vingt-quatre vues, deux fois' % len(avant_lect))
        # ce qui ne doit JAMAIS sortir, même pour la direction
        a_cacher = [str(otp), 'otp_hash', 'otp_salt', 'encrypted_password', '$2a$10$', 'service_role', 'secret_key', 'jwt', 'raw_user_meta_data', 'auth_user_id', 'idempotency_key', 'signature_path', 'password']
        for nom_, rep_ in REPONSES.items():
            for mot in a_cacher:
                if mot == str(otp):
                    ok(not re.search(r'(?<![0-9a-f-])%s(?![0-9a-f-])' % re.escape(mot), texte(rep_)), 'la vue « %s » ne contient pas le code de livraison à usage unique' % nom_)
                else:
                    ok(mot not in texte(rep_), 'la vue « %s » ne contient jamais « %s »' % (nom_, mot))
        # ce que seule la direction voit
        for nom_, fn_ in (('gerant', gerant), ('admin', admin)):
            ok(f('lg_cc_users', fn_, p_limit=1)['total'] == n_("select count(*) from logistics.app_user"), '%s : la liste des comptes de l\'équipe' % nom_)
        ok(REPONSES['indicateurs']['operations'] is not None and REPONSES['indicateurs']['money'] is not None and REPONSES['indicateurs']['support'] is not None, 'la direction reçoit les trois blocs d\'indicateurs')

        # ============================================================== G. LA FORME de chaque réponse est figée (partagée avec le test du navigateur)
        REPONSES_ACTIONS = {'approuver_enlevement': r1, 'refuser_enlevement': r1b, 'approuver_livraison': r2, 'refuser_livraison': r2b, 'repondre_ticket': rr, 'fermer_ticket': rc}
        TOUT = dict(REPONSES); TOUT.update(REPONSES_ACTIONS)
        DIR_ = os.path.dirname(os.path.abspath(__file__))
        CH_FORMES, CH_RPC, CH_ENUMS, CH_EXEMPLES = (os.path.join(DIR_, 'centre-%s.json' % n_) for n_ in ('formes', 'rpc', 'enums', 'exemples'))
        # Les tableaux de comptes (« par statut », « par étape ») ont pour clés des VALEURS : leur forme est « une table de nombres », pas la liste des valeurs du jour.
        forme = lambda x_: sorted({re.sub(r'(\.by_(?:status|stage))\.[^.\[]+', r'\1.*', c_) for c_ in cles(x_)})   # noqa: E731
        FORMES = {k_: forme(v_) for k_, v_ in TOUT.items()}
        SIGNATURES = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), 'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) "
                                  "from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\\_cc\\_%'"))

        def valeurs_contrainte(table, colonne):
            defs = ' '.join(cl.lignes(B, "select pg_get_constraintdef(c.oid) from pg_constraint c where c.conrelid = 'logistics.%s'::regclass and c.contype = 'c'" % table))
            # TOUTES les contraintes qui parlent de la colonne (une table peut en avoir plusieurs, dont une qui n'en cite qu'une partie des valeurs)
            trouvees = set()
            for m_ in list(re.finditer(r"%s\s*=\s*ANY\s*\(\s*\(?ARRAY\[(.*?)\]" % colonne, defs)) + list(re.finditer(r"\(%s\)::text\s*=\s*ANY\s*\(\s*\(?ARRAY\[(.*?)\]" % colonne, defs)):
                trouvees |= set(re.findall(r"'([A-Za-z_]+)'::text", m_.group(1)))
            return sorted(trouvees)
        ENUMS = {
            'section': sorted(set(REPONSES['acces']['sections']) | set(COMMANDE + OPS + CLI + FIN + DIR)),
            'indicateur_operations': sorted(REPONSES['indicateurs']['operations']), 'indicateur_argent': sorted(REPONSES['indicateurs']['money']), 'indicateur_support': sorted(REPONSES['indicateurs']['support']),
            'a_traiter': ['pickup_requests', 'delivery_requests', 'deliveries_delayed', 'incidents_high', 'parcels_on_hold', 'shipments_late', 'tickets_waiting', 'invoices_overdue'],
            'statut_colis': cl.lignes(B, "select code from logistics.parcel_status order by code"), 'statut_expedition': cl.lignes(B, "select code from logistics.shipment_status order by code"),
            'statut_transport': valeurs_contrainte('transport', 'status'), 'statut_mission': cl.lignes(B, "select code from logistics.task_status order by code"), 'statut_chauffeur': valeurs_contrainte('driver', 'status'),
            'statut_douane': valeurs_contrainte('customs_declaration', 'status'), 'type_incident': valeurs_contrainte('incident', 'type'), 'gravite_incident': valeurs_contrainte('incident', 'severity'), 'statut_incident': valeurs_contrainte('incident', 'status'),
            'statut_facture': cl.lignes(B, "select code from logistics.invoice_status where code <> 'DRAFT' order by code"), 'genre_paiement': ['CREDIT', 'PAYMENT', 'REFUND'], 'moyen_paiement': valeurs_contrainte('payment', 'method'),
            'statut_ticket': valeurs_contrainte('support_ticket', 'status'), 'categorie_ticket': valeurs_contrainte('support_ticket', 'category'), 'canal': sorted(set(cl.lignes(B, "select distinct channel from logistics.notification")) | {'in_app', 'email', 'push', 'sms', 'whatsapp'}),
            'statut_notification': valeurs_contrainte('notification', 'status'), 'role': ['admin', 'employee', 'manager'], 'statut_demande': ['APPROVED', 'CANCELLED', 'REJECTED', 'REQUESTED'],
            'etape_demande': sorted({q("select logistics.pickup_stage(%s, %s)" % (val(a_), val(b_))) for a_ in ('REQUESTED', 'REJECTED', 'CANCELLED', 'APPROVED') for b_ in (None, 'COMPLETED', 'STARTED', 'FAILED', 'CANCELLED', 'CREATED')}
                                    | {q("select logistics.delivery_stage(%s, %s)" % (val(a_), val(b_))) for a_ in ('REQUESTED', 'REJECTED', 'CANCELLED', 'APPROVED') for b_ in (None, 'COMPLETED', 'STARTED', 'FAILED', 'CANCELLED', 'CREATED')}),
            'resultat_scan': valeurs_contrainte('scan', 'result'), 'but_scan': valeurs_contrainte('scan', 'purpose'), 'service': cl.lignes(B, "select code from logistics.transport_mode order by code"), 'pays': ['DO', 'HT', 'US'],
            'type_succursale': valeurs_contrainte('branch', 'kind'), 'etat_colis': valeurs_contrainte('parcel', 'condition'),
        }
        ok(all(ENUMS[k_] for k_ in ENUMS), 'chaque famille de valeurs est relevée dans la base : %s' % {k_: len(v_) for k_, v_ in ENUMS.items()})
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(FORMES, open(CH_FORMES, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            json.dump(SIGNATURES, open(CH_RPC, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            json.dump(ENUMS, open(CH_ENUMS, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            json.dump(json.loads(json.dumps(TOUT, default=str)), open(CH_EXEMPLES, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        ok(sorted(json.load(open(CH_FORMES, encoding='utf-8'))) == sorted(TOUT), 'le fichier des formes couvre exactement les trente réponses')
        for k_, attendu_ in json.load(open(CH_FORMES, encoding='utf-8')).items():
            vu = forme(TOUT[k_])
            ok(vu == attendu_, 'LA FORME de « %s » a changé. En plus : %s. En moins : %s. (Une clé de plus peut être une fuite : à relire avant d\'accepter.)' % (k_, sorted(set(vu) - set(attendu_)), sorted(set(attendu_) - set(vu))))
        ok(json.load(open(CH_RPC, encoding='utf-8')) == json.loads(json.dumps(SIGNATURES)) and len(SIGNATURES) == 28, 'les signatures des 28 fonctions sont celles du fichier partagé avec le test du navigateur (sinon : SES_FORME_ECRIRE=1 et relire le changement)')
        ok(json.load(open(CH_ENUMS, encoding='utf-8')) == json.loads(json.dumps(ENUMS)), 'les valeurs que le site doit savoir nommer sont celles du fichier partagé avec le test du navigateur')
        interdit_cle = ('password', 'otp_hash', 'otp_salt', 'token', 'secret', 'auth_user', 'idempotency', 'encrypted', 'signature')
        ok(not [c_ for v_ in FORMES.values() for c_ in v_ if any(m_ in c_.lower() for m_ in interdit_cle)], 'aucune clé, dans aucune réponse, ne porte un nom de secret (mot de passe, empreinte de code, jeton, clé d\'idempotence, signature)')

    print('%d vérifications — phase 12 (centre de commande) : OK' % N[0])


if __name__ == '__main__':
    main()
