#!/usr/bin/env python3
"""Noyau logistique, phase 13 : notifications et temps réel — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-notifications-essai.py

Jamais la production. Ce qu'on éprouve : (1) chaque événement prévient le bon client, par les seuls canaux allumés, voulus et joignables,
dans sa langue, sans jamais de doublon ; (2) le travailleur réclame avec un bail, rend compte, relance avec une attente doublée, abandonne au
maximum d'essais, et chaque essai laisse sa ligne — erreurs nettoyées de tout secret ; (3) le code de livraison est relayé au client tant
que WhatsApp n'a pas de fournisseur ; (4) le signal temps réel ne porte aucune donnée, ne se lit que par ses destinataires, et ne bloque
jamais une opération ; (5) une panne du moteur ne bloque aucun colis ; (6) les portes : client, équipe, travailleur, visiteur."""
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
        return "array[%s]::%s[]" % (', '.join(val(x) for x in v), 'uuid' if re.match(r'^[0-9a-f-]{36}$', str(v[0])) else 'text')
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items()))


MODELES = ['ParcelReceived', 'ParcelInTransit', 'ParcelArrived', 'CustomsCleared', 'ParcelAtDestinationHub', 'OutForDelivery', 'Delivered', 'ParcelOnHold', 'ParcelDamaged',
           'ParcelLost', 'ParcelReturned', 'InvoiceIssued', 'InvoiceOverdue', 'PaymentReceived', 'PickupRequestApproved', 'PickupRequestRejected', 'DeliveryRequestApproved',
           'DeliveryRequestRejected', 'SupportTicketAnswered', 'DeliveryOtp']


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        n_ = lambda sql: int(q(sql))   # noqa: E731
        P.monter_historique(cl, B)
        for f_ in ('001-modele-de-domaine', '002-retroremplissage', '003-machine-d-etats', '004-entrepot', '005-transport-douane', '006-dernier-kilometre', '007-finance', '008-portail-client', '009-centre-de-commande'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f_))
        avant_legacy = P.empreintes_historiques(cl, B)
        cl.run(B, P.lire_sql('outils/logistique/010-notifications.sql'))
        compte = lambda: tuple(q('select count(*) from %s' % t) for t in ('logistics.notification_template', 'logistics.notification_rule', 'logistics.notification_channel', 'logistics.event_subscriber'))   # noqa: E731
        c1 = compte()
        cl.run(B, P.lire_sql('outils/logistique/010-notifications.sql'))
        ok(c1 == compte() and c1[:3] == ('80', '19', '5'), '010 rejouée : 80 modèles (20 × 4 langues), 19 règles, 5 canaux, rien en double : %s' % (c1,))
        ok(avant_legacy == P.empreintes_historiques(cl, B), 'les anciennes tables n\'ont pas bougé d\'un octet')
        q('select logistics.backfill_from_legacy()')

        uid = lambda n: q("select id from public.clients where email = 'client%d@essai.test'" % n)   # noqa: E731
        admin, op, ua, ub, uc = uid(1), uid(3), uid(9), uid(10), uid(11)
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

        def travailleur(sql):
            """Le travailleur parle avec la clé secrète (rôle service_role) : jamais un navigateur."""
            code, sortie = cl.run(B, sql, role='service_role')
            return sortie

        def reclamer(canaux=None, limite=20, bail=120):
            lignes = cl.lignes(B, "set role service_role; select row_to_json(x) from public.ses_nt_claim('essai', %s, %d, %d) x" % (val(canaux) if canaux else 'null', limite, bail))
            return [json.loads(l) for l in lignes if l.startswith('{')]

        repartir = lambda: q("select logistics.dispatch_events(1000, 'notification_engine')")   # noqa: E731

        # ============================================================== A. modèles, règles, canaux
        langues = cl.lignes(B, "select code || '|' || string_agg(language, ',' order by language) from logistics.notification_template group by code order by code")
        ok(sorted(l.split('|')[0] for l in langues) == sorted(MODELES) and all(l.split('|')[1] == 'en,es,fr,ht' for l in langues), 'chaque modèle existe dans les quatre langues')
        ok(set(cl.lignes(B, "select template from logistics.notification_rule")) <= set(MODELES), 'chaque règle a son modèle')
        ok(n_("select count(*) from logistics.notification_rule r where not exists (select 1 from logistics.event_type e where e.code = r.event_type)") == 0, 'chaque règle vise un événement déclaré')
        ok(cl.lignes(B, "select code || ':' || enabled from logistics.notification_channel order by code") == ['email:true', 'in_app:true', 'push:true', 'sms:false', 'whatsapp:false'],
           'canaux : portail, push et e-mail allumés ; SMS et WhatsApp déclarés mais éteints (pas de fournisseur)')
        ok(q("select active::text from logistics.event_subscriber where code = 'notification_planner'") == 'false' and q("select active::text from logistics.event_subscriber where code = 'notification_engine'") == 'true',
           'le moteur remplace l\'ancien planificateur')
        ok(set(q("select array_to_string(event_types, ',') from logistics.event_subscriber where code = 'notification_engine'").split(',')) == set(cl.lignes(B, "select event_type from logistics.notification_rule")),
           'le moteur écoute exactement les événements qui ont une règle')
        ok(n_("select count(*) from logistics.notification_template t, regexp_matches(t.title || ' ' || t.body, '\\{([a-z_]+)\\}', 'g') m where not (m[1] = any (logistics.nt_placeholders()))") == 0, 'aucun modèle ne cite une variable inconnue')
        refuse("insert into logistics.notification_template (code, language, title, body) values ('Essai', 'fr', 'Titre', 'Bonjour {password}')", 'LG005', 'un modèle qui cite une variable inconnue')
        refuse("update logistics.notification_template set body = body || ' {auth_user_id}' where code = 'Delivered' and language = 'fr'", 'LG005', 'une modification qui ajoute une variable inconnue')
        v0 = n_("select version from logistics.notification_template where code = 'Delivered' and language = 'fr'")
        q("update logistics.notification_template set body = body where code = 'Delivered' and language = 'fr'")
        ok(n_("select version from logistics.notification_template where code = 'Delivered' and language = 'fr'") == v0, 'réécrire le même texte ne change pas la version')
        q("update logistics.notification_template set body = body || ' ' where code = 'Delivered' and language = 'fr'")
        ok(n_("select version from logistics.notification_template where code = 'Delivered' and language = 'fr'") == v0 + 1, 'changer le texte monte la version')
        q("update logistics.notification_template set body = btrim(body) where code = 'Delivered' and language = 'fr'")
        ok(q("select logistics.nt_render('Colis {tracking_number} : {stage} {inconnu} {code}', '{\"tracking_number\": \"N-1\", \"stage\": \"received\", \"password\": \"x\"}')") == 'Colis N-1 : received {inconnu} ',
           'le rendu remplit les variables permises, vide les permises absentes, ne touche à rien d\'autre')

        # ============================================================== B. le décor
        q("insert into logistics.branch (organization_id, code, name, kind, country, city) values ('%s', 'MIA', 'Miami', 'office', 'US', 'Miami'), ('%s', 'PAP', 'Hub Port-au-Prince', 'hub', 'HT', 'Port-au-Prince')" % (org, org))
        mia, pap = q("select id from logistics.branch where code = 'MIA'"), q("select id from logistics.branch where code = 'PAP'")
        q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'MIA-1', 'Entrepôt Miami'), ('%s', 'PAP-1', 'Entrepôt hub')" % (mia, pap))
        wmia = q("select id from logistics.warehouse where code = 'MIA-1'")
        q("insert into logistics.warehouse_location (warehouse_id, code, kind) values ('%s', 'A-01', 'storage')" % wmia)
        loc = q("select id from logistics.warehouse_location where code = 'A-01'")
        n_p = [0]

        def nat(cust, statut='CREATED'):
            n_p[0] += 1
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, destination_city, service_mode, status, status_authority, source, weight_lb) "
                     "values ('%s', 'N-%03d', 'tok%d', '%s', 'HT', 'Delmas', 'air', '%s', 'core', 'legacy_backfill', 3) returning id" % (org, n_p[0], n_p[0], cust, statut))

        def tr(pid, to, **kw):
            args = dict(p_parcel_id=pid, p_to_status=to)
            args.update(kw)
            return f('lg_transition_parcel', admin, **args)

        langue = lambda c: q("select language from logistics.customer where id = '%s'" % c)   # noqa: E731
        appareils = lambda c: n_("select count(*) from logistics.device where owner_customer_id = '%s' and active and push_token is not null" % c)   # noqa: E731
        # A : un appareil (le rattrapage en a créé ou non) ; B : aucun appareil ; C : pas d'e-mail
        appareils_crees = not appareils(ca)
        if appareils_crees:
            q("insert into logistics.device (kind, platform, push_token, owner_customer_id) values ('customer_push', 'ios', 'ExponentPushToken[essai-A]', '%s')" % ca)
        q("update logistics.device set active = false where owner_customer_id = '%s'" % cb)
        q("update logistics.customer set email = '' where id = '%s'" % cc)
        ok(appareils(ca) >= 1 and appareils(cb) == 0, 'décor : A a un téléphone, B n\'en a pas')

        # ============================================================== C. le moteur : bon client, bons canaux, bonne langue, jamais deux fois
        def notifs(c, gabarit=None):
            return [l.split('|') for l in cl.lignes(B, "select channel || '|' || status || '|' || template || '|' || coalesce(language, '') || '|' || coalesce(title, '') || '|' || coalesce(body, '') "
                                                       "from logistics.notification where customer_id = '%s' %s order by id" % (c, "and template = '%s'" % gabarit if gabarit else ''))]

        def attendus(c, evenement):
            """Les canaux attendus, calculés ICI : règle ∩ canal allumé ∩ préférence ∩ joignable."""
            regle = q("select array_to_string(channels, ',') from logistics.notification_rule where event_type = '%s' and active" % evenement).split(',')
            res = []
            for ch in regle:
                allume = q("select enabled::text from logistics.notification_channel where code = '%s'" % ch) == 'true'
                pref = q("select coalesce((select enabled::text from logistics.notification_preference where customer_id = '%s' and channel = '%s'), '')" % (c, ch))
                voulu = True if ch == 'in_app' else (pref == 'true' if pref else ch in ('push', 'email'))
                joignable = {'in_app': q("select (auth_user_id is not null)::text from logistics.customer where id = '%s'" % c) == 'true',
                             'email': q("select (coalesce(btrim(email), '') <> '')::text from logistics.customer where id = '%s'" % c) == 'true',
                             'push': appareils(c) > 0}.get(ch, q("select (coalesce(btrim(phone), '') <> '')::text from logistics.customer where id = '%s'" % c) == 'true')
                if allume and voulu and joignable:
                    res.append(ch)
            return sorted(res)

        a1 = nat(ca)
        tr(a1, 'RECEIVED', p_warehouse_id=wmia, p_location_text='QUAI')
        ok(n_("select count(*) from logistics.notification where customer_id = '%s'" % ca) == 0, 'avant la répartition : aucune notification (le moteur ne travaille jamais dans la transaction du colis)')
        repartir()
        na = notifs(ca, 'ParcelReceived')
        ok(sorted(x[0] for x in na) == attendus(ca, 'ParcelReceived') == ['email', 'in_app', 'push'], 'colis reçu chez A : portail, téléphone et e-mail : %s' % [x[0] for x in na])
        ok({x[0]: x[1] for x in na} == {'in_app': 'SENT', 'push': 'PENDING', 'email': 'PENDING'}, 'le portail est servi tout de suite ; le téléphone et l\'e-mail attendent le travailleur')
        lg = langue(ca)
        ttl = q("select title from logistics.notification_template where code = 'ParcelReceived' and language = '%s'" % lg)
        ok(all(x[3] == lg and x[4] == ttl and 'N-001' in x[5] and '{' not in x[5] for x in na), 'dans la langue du client (%s), titre du modèle, numéro du colis dans le texte, plus aucune variable' % lg)
        ok(json.loads(q("select payload from logistics.notification where customer_id = '%s' and channel = 'in_app' and template = 'ParcelReceived'" % ca)) == {'tracking_number': 'N-001', 'stage': 'received'},
           'la charge utile : seulement les variables permises (numéro, étape)')
        ev = q("select id from logistics.domain_event where event_type = 'ParcelReceived' and aggregate_id = '%s'" % a1)
        q("select logistics.handle_notification_engine(e) from logistics.domain_event e where e.id = %s" % ev)
        q("select logistics.handle_notification_engine(e) from logistics.domain_event e where e.id = %s" % ev)
        ok(len(notifs(ca, 'ParcelReceived')) == 3, 'l\'événement rejoué deux fois : toujours trois notifications (une par canal)')
        # une règle désactivée ne prévient plus
        q("update logistics.notification_rule set active = false where event_type = 'ParcelReceived'")
        a0 = nat(ca); tr(a0, 'RECEIVED', p_warehouse_id=wmia); repartir()
        ok(len(notifs(ca, 'ParcelReceived')) == 3, 'règle « colis reçu » désactivée : aucune notification de plus')
        q("update logistics.notification_rule set active = true where event_type = 'ParcelReceived'")
        # B : sans téléphone ; C : sans e-mail
        b1, c1_ = nat(cb), nat(cc)
        tr(b1, 'RECEIVED', p_warehouse_id=wmia); tr(c1_, 'RECEIVED', p_warehouse_id=wmia)
        repartir()
        ok(sorted(x[0] for x in notifs(cb, 'ParcelReceived')) == attendus(cb, 'ParcelReceived') == ['email', 'in_app'], 'B, sans téléphone : portail et e-mail')
        ok(sorted(x[0] for x in notifs(cc, 'ParcelReceived')) == attendus(cc, 'ParcelReceived') and 'email' not in [x[0] for x in notifs(cc)], 'C, sans e-mail : pas d\'e-mail')
        ok(notifs(cb, 'ParcelReceived')[0][3] == langue(cb) != langue(ca), 'B reçoit dans SA langue (%s), pas dans celle de A' % langue(cb))
        # la préférence du client
        prefs = f('lg_my_notification_prefs', ua)
        ok([(p_['channel'], p_['available'], p_['enabled'], p_['locked']) for p_ in prefs] == [('email', True, True, False), ('in_app', True, True, True), ('push', True, True, False), ('sms', False, False, False), ('whatsapp', False, False, False)],
           'les préférences de A : tout ce qui est allumé, sauf SMS et WhatsApp (à demander) ; le portail ne se coupe pas')
        f('lg_set_notification_pref', ua, p_channel='email', p_enabled=False)
        ok(n_("select count(*) from logistics.audit_log where action = 'notification.preference' and entity_id = '%s'" % ca) == 1, 'le changement est tracé dans l\'audit')
        f('lg_set_notification_pref', ua, p_channel='email', p_enabled=False)
        ok(n_("select count(*) from logistics.audit_log where action = 'notification.preference' and entity_id = '%s'" % ca) == 1, 'redemander la même chose ne trace rien de plus')
        for kw, msg in ((dict(p_channel='in_app', p_enabled=False), 'couper le portail'), (dict(p_channel='fax', p_enabled=True), 'canal inconnu'), (dict(p_channel='email', p_enabled=None), 'ni oui ni non')):
            fr('lg_set_notification_pref', 'LG005', 'préférence refusée : %s' % msg, ua, **kw)
        fr('lg_set_notification_pref', 'LG003', 'l\'équipe n\'a pas de préférences de client', admin, p_channel='email', p_enabled=True)
        ok(f('lg_my_notification_prefs', admin) == [], 'l\'équipe (sans profil client) : aucune préférence')
        tr(a1, 'VERIFIED', p_warehouse_id=wmia); tr(a1, 'STORED', p_warehouse_id=wmia, p_location_id=loc, p_location_text='A-01'); tr(a1, 'CONSOLIDATION_PENDING'); tr(a1, 'ON_HOLD', p_reason='contrôle interne : dossier 77')
        repartir()
        oh = notifs(ca, 'ParcelOnHold')
        ok(sorted(x[0] for x in oh) == attendus(ca, 'ParcelOnHold') == ['in_app', 'push'], 'A a coupé l\'e-mail : la mise en attente arrive au portail et au téléphone seulement')
        ok(all('77' not in x[5] and 'contrôle interne' not in x[5] for x in oh), 'le MOTIF interne d\'une mise en attente ne part jamais chez le client')
        ok(n_("select count(*) from logistics.notification where customer_id = '%s' and template in ('ParcelVerified', 'ParcelStored', 'ParcelConsolidationPending')" % ca) == 0, 'les étapes internes (vérifié, rangé, attente de consolidation) ne préviennent personne')
        # un canal qu'on allume, une préférence qu'on donne
        f('lg_set_notification_pref', ua, p_channel='sms', p_enabled=True)
        wpap = q("select id from logistics.warehouse where code = 'PAP-1'")
        a2 = nat(ca, 'CUSTOMS_CLEARED')
        tr(a2, 'AT_DESTINATION_HUB', p_warehouse_id=wpap); repartir()
        ok('sms' not in [x[0] for x in notifs(ca, 'ParcelAtDestinationHub')] and notifs(ca, 'ParcelAtDestinationHub'), 'SMS voulu par A, mais le canal est éteint : pas de SMS (le reste part)')
        q("update logistics.notification_channel set enabled = true where code = 'sms'")
        a2b = nat(ca, 'CUSTOMS_CLEARED')
        tr(a2b, 'AT_DESTINATION_HUB', p_warehouse_id=wpap); repartir()
        hub = [x for x in notifs(ca, 'ParcelAtDestinationHub') if 'N-%03d' % n_p[0] in x[5]]
        ok(sorted(x[0] for x in hub) == attendus(ca, 'ParcelAtDestinationHub') and 'sms' in [x[0] for x in hub], 'canal SMS allumé et voulu : le colis disponible part aussi par SMS : %s' % [x[0] for x in hub])
        q("update logistics.notification_channel set enabled = false where code = 'sms'")
        # repli sur le français
        q("update logistics.notification_template set active = false where code = 'Delivered' and language = '%s'" % langue(cb))
        b2 = nat(cb, 'OUT_FOR_DELIVERY')
        ev_d = q("insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id, payload) values ('Delivered', 'parcel', '%s', gen_random_uuid(), '{\"to_status\": \"DELIVERED\"}') returning id" % b2)
        repartir()
        ok(langue(cb) == 'fr' or {x[3] for x in notifs(cb, 'Delivered')} == {'fr'}, 'modèle désactivé dans la langue de B : repli sur le français')
        q("update logistics.notification_template set active = true where code = 'Delivered'")
        # l'équipe n'est pas la clientèle
        q("update logistics.customer set source = 'legacy_staff_account' where id = '%s'" % cc)
        c2 = nat(cc); tr(c2, 'RECEIVED', p_warehouse_id=wmia); repartir()
        ok(len(notifs(cc, 'ParcelReceived')) == 1, 'un compte d\'équipe hérité qui porte un colis : aucune nouvelle notification (seule celle d\'avant reste)')
        q("update logistics.customer set source = 'legacy_backfill' where id = '%s'" % cc)

        # ============================================================== D. les notifications nées des actions de l'équipe et des finances
        DANS3 = q("select (current_date + 3)::text")
        adr = f('lg_save_address', ub, p_country='HT', p_address='1 rue Test', p_city='Delmas')
        pk = f('lg_request_pickup', ub, p_preferred_date=DANS3, p_address_id=adr['address_id'])
        f('lg_cc_review_pickup', admin, p_id=pk['pickup_id'], p_approve=True, p_message='Le chauffeur passe le matin.')
        tk = f('lg_open_ticket', ub, p_subject='Question', p_category='OTHER', p_body='Bonjour')
        f('lg_cc_reply_ticket', admin, p_id=tk['ticket_id'], p_body='Bonjour, voici la réponse.')
        repartir()
        pa = notifs(cb, 'PickupRequestApproved')
        ok(sorted(x[0] for x in pa) == attendus(cb, 'PickupRequestApproved') and any(DANS3 in x[5] and 'Le chauffeur passe le matin.' in x[5] for x in pa), 'enlèvement approuvé : B est prévenu avec la date et le message de l\'équipe')
        ok(sorted(x[0] for x in notifs(cb, 'SupportTicketAnswered')) == attendus(cb, 'SupportTicketAnswered'), 'réponse du support : B est prévenu')
        ok('voici la réponse' not in ' '.join(x[5] for x in notifs(cb, 'SupportTicketAnswered')), 'le texte de la réponse ne voyage pas dans la notification : le client le lit dans son portail')
        zht = f('lg_create_pricing_zone', admin, p_code='Z-HT', p_name='Haïti', p_country='HT')
        f('lg_create_rate_card', admin, p_code='AIR-HT', p_name='Air Haïti', p_mode='air', p_zone=zht, p_currency='USD', p_brackets=R("'[{\"min_lb\": 0, \"price_per_lb\": 3.00, \"flat_fee\": 0, \"min_charge\": 5}]'::jsonb"))
        qt = f('lg_create_quote', admin, p_customer=cb, p_currency='USD', p_items=R("'%s'::jsonb" % json.dumps([dict(parcel_id=b1)])))
        inv = f('lg_invoice_from_quote', admin, p_quote=qt['quote_id'], p_issue=True)
        f('lg_record_payment', admin, p_invoice=inv['invoice_id'], p_amount=5, p_method='CASH')
        repartir()
        ii = notifs(cb, 'InvoiceIssued')
        tot = q("select to_char(total, 'FM999999990.00') from logistics.invoice where id = '%s'" % inv['invoice_id'])
        ok(sorted(x[0] for x in ii) == attendus(cb, 'InvoiceIssued') and all(inv['number'] in x[5] and (tot + ' USD') in x[5] for x in ii), 'facture émise : numéro, montant (%s USD, le total à l\'émission), devise' % tot)
        pr = notifs(cb, 'PaymentReceived')
        ok(pr and all('5.00' in x[5] and inv['number'] in x[5] for x in pr), 'paiement reçu : 5.00 USD pour la facture')
        # ce que le portail montre
        mes = f('lg_my_notifications', ub, p_limit=100)
        tpl_b = set(cl.lignes(B, "select template from logistics.notification where customer_id = '%s' and channel = 'in_app'" % cb))
        ok({i_['template'] for i_ in mes['items']} == tpl_b and mes['unread'] == len(tpl_b) == len(mes['items']), 'le portail de B montre exactement ses notifications « in_app », non lues')
        ok(all(set(i_['payload']) <= {'tracking_number', 'status', 'stage', 'invoice_number', 'amount', 'currency', 'shipment_code', 'code', 'expires_hours', 'message', 'date'} for i_ in mes['items']), 'et seulement des variables permises')
        ok(all('N-001' not in json.dumps(i_) for i_ in mes['items']), 'aucune notification de A chez B')

        # ============================================================== E. le code de livraison : relayé tant que WhatsApp n'a pas de fournisseur
        a3 = nat(ca, 'AT_DESTINATION_HUB')
        dl = f('lg_create_delivery', admin, p_parcel_ids=[a3], p_hub_branch=pap, p_scheduled_for=R('current_date'), p_recipient_name='Marie', p_recipient_phone='+509 3111 1111', p_address='1 rue', p_otp_required=True)
        f('lg_issue_delivery_otp', admin, p_task_id=dl['task_id'])
        otp_lignes = [l.split('|') for l in cl.lignes(B, "select channel || '|' || status || '|' || coalesce(payload ->> 'code', '') || '|' || coalesce(body, '') || '|' || coalesce(last_error, '') from logistics.notification where template = 'DeliveryOtp' order by id")]
        code_otp = otp_lignes[0][2]
        ok(otp_lignes[0][0] == 'whatsapp' and otp_lignes[0][1] == 'SKIPPED' and 'sans fournisseur' in otp_lignes[0][4], 'l\'original (WhatsApp, vers le destinataire) est marqué « non envoyé », avec la raison')
        relais = {x[0]: x for x in otp_lignes[1:]}
        ok(set(relais) == {'in_app'}, 'relayé au portail du client — pas par e-mail : A l\'a coupé : %s' % sorted(relais))
        ok(relais['in_app'][1] == 'SENT' and code_otp in relais['in_app'][3] and len(code_otp) == 6, 'le portail affiche le code à 6 chiffres')
        ok(n_("select count(*) from logistics.notification_attempt a join logistics.notification n on n.id = a.notification_id where n.template = 'DeliveryOtp' and a.outcome = 'SKIPPED'") == 1, 'le saut est journalisé')
        q("update logistics.notification_channel set enabled = true where code = 'whatsapp'")
        f('lg_issue_delivery_otp', admin, p_task_id=dl['task_id'])
        dern = q("select channel || '|' || status from logistics.notification where template = 'DeliveryOtp' order by id desc limit 1")
        ok(dern == 'whatsapp|PENDING', 'WhatsApp allumé : le code part par WhatsApp vers le destinataire, sans relais')
        q("update logistics.notification_channel set enabled = false where code = 'whatsapp'")

        # ============================================================== F. le travailleur : bail, compte rendu, relance, abandon, journal
        en_attente = lambda: n_("select count(*) from logistics.notification n join logistics.notification_channel ch on ch.code = n.channel and ch.enabled where n.status = 'PENDING' and n.channel <> 'in_app'")   # noqa: E731
        avant = en_attente()
        lot = reclamer(['email', 'push'], 5)
        ok(0 < len(lot) <= 5 and all(x['channel'] in ('email', 'push') for x in lot), 'le travailleur réclame au plus 5 notifications, des canaux demandés : %d' % len(lot))
        ok(all(x['attempt'] == 1 and x['title'] and x['body'] and x['recipient'] for x in lot), 'chacune avec son essai, son texte et son destinataire')
        for x in lot:
            if x['channel'] == 'email':
                ok(set(x['recipient']) == {'email', 'name'} and '@' in x['recipient']['email'], 'e-mail : adresse et nom, rien d\'autre')
            else:
                ok(set(x['recipient']) == {'tokens'} and all(t_.startswith('ExponentPushToken') for t_ in x['recipient']['tokens']), 'téléphone : les jetons des appareils actifs')
        second = reclamer(['email', 'push'], 200)
        ok(not ({x['notification_id'] for x in lot} & {x['notification_id'] for x in second}), 'une notification sous bail n\'est pas réclamée deux fois')
        q("insert into logistics.notification (customer_id, channel, template, status) values ('%s', 'in_app', 'Essai', 'PENDING')" % ca)
        ok(not any(x['channel'] == 'in_app' for x in reclamer(None, 200)), 'le portail n\'est jamais réclamé (même une ligne « en attente » égarée)')
        # tout ce qui reste est maintenant sous bail ; on libère pour la suite
        q("update logistics.notification set locked_until = null, attempts = 0 where status = 'PENDING'")
        lot = reclamer(['email'], 3)
        n1, n2, n3 = lot[0]['notification_id'], lot[1]['notification_id'], lot[2]['notification_id']
        r_ok = json.loads(travailleur("select public.ses_nt_report(%d, true, 'brevo-123', null, 'essai')" % n1))
        ok(r_ok['status'] == 'SENT' and q("select status || '|' || provider_ref || '|' || (sent_at is not null) from logistics.notification where id = %d" % n1) == 'SENT|brevo-123|true', 'succès : envoyée, référence du fournisseur, heure d\'envoi')
        refuse("set role service_role; select public.ses_nt_report(%d, true)" % n1, 'LG004', 'rendre compte deux fois de la même notification')
        ok(cl.lignes(B, "select attempt || ':' || outcome || ':' || coalesce(provider_ref, '') from logistics.notification_attempt where notification_id = %d" % n1) == ['1:SENT:brevo-123'], 'le succès est journalisé, avec la référence')
        libre = q("select id from logistics.notification where status = 'PENDING' and locked_until is null and channel <> 'in_app' limit 1")
        refuse("set role service_role; select public.ses_nt_report(%s, true)" % libre, 'LG004', 'rendre compte d\'une notification que personne n\'a réclamée')
        r2 = json.loads(travailleur("select public.ses_nt_report(%d, false, null, 'Erreur 502 du fournisseur, clé xkeysib-abcdef0123456789 refusée pour ExponentPushToken[secret-42]', 'essai')" % n2))
        ok(r2['status'] == 'PENDING' and r2['retry_in_seconds'] == 120, 'premier échec : nouvel essai dans 120 s (attente du canal e-mail)')
        err = q("select last_error from logistics.notification where id = %d" % n2)
        ok('xkeysib-abcdef' not in err and 'secret-42' not in err and '[masqué]' in err and 'Erreur 502' in err, 'l\'erreur est gardée, mais nettoyée de la clé et du jeton : %s' % err)
        ok(q("select (next_attempt_at > now() + interval '110 seconds' and next_attempt_at < now() + interval '130 seconds')::text from logistics.notification where id = %d" % n2) == 'true', 'et l\'heure du prochain essai est fixée')
        ok(n2 not in [x['notification_id'] for x in reclamer(['email'], 200)], 'avant l\'heure : pas réclamée')
        q("update logistics.notification set locked_until = null where status = 'PENDING' and id <> %d" % n3)
        attentes = []
        for essai in range(2, 6):
            q("update logistics.notification set next_attempt_at = now() where id = %d" % n2)
            lot_ = [x for x in reclamer(['email'], 200) if x['notification_id'] == n2]
            ok(lot_ and lot_[0]['attempt'] == essai, 'essai n° %d réclamé' % essai)
            r_ = json.loads(travailleur("select public.ses_nt_report(%d, false, null, 'panne', 'essai')" % n2))
            attentes.append(r_.get('retry_in_seconds'))
            q("update logistics.notification set locked_until = null where status = 'PENDING' and id not in (%d, %d)" % (n2, n3))
        ok(attentes == [240, 480, 960, None] and q("select status from logistics.notification where id = %d" % n2) == 'FAILED', 'attente doublée à chaque essai (240, 480, 960 s), puis ÉCHEC au 5e essai (maximum du canal)')
        r3 = json.loads(travailleur("select public.ses_nt_report(%d, false, null, 'adresse e-mail invalide', 'essai', true)" % n3))
        ok(r3['status'] == 'FAILED', 'une erreur définitive (adresse invalide) : échec tout de suite, sans relance')
        journal = cl.lignes(B, "select attempt || ':' || outcome from logistics.notification_attempt where notification_id = %d order by id" % n2)
        ok(journal == ['1:RETRY', '2:RETRY', '3:RETRY', '4:RETRY', '5:FAILED'], 'le journal de livraison : une ligne par essai, dans l\'ordre : %s' % journal)
        refuse("update logistics.notification_attempt set outcome = 'SENT'", 'LG004', 'le journal ne se modifie pas')
        refuse("delete from logistics.notification_attempt", 'LG004', 'le journal ne se supprime pas')
        refuse("set role service_role; select public.ses_nt_report(%d, true)" % n2, 'LG004', 'rendre compte d\'une notification abandonnée')
        refuse("set role service_role; select public.ses_nt_report(999999, true)", 'LG002', 'une notification inconnue')
        refuse("set role service_role; select * from public.ses_nt_claim('', null)", 'LG005', 'un travailleur sans nom')
        # le destinataire a disparu
        q("update logistics.notification set locked_until = null, next_attempt_at = now() where status = 'PENDING'")
        pushs = n_("select count(*) from logistics.notification where status = 'PENDING' and channel = 'push' and customer_id = '%s'" % ca)
        q("update logistics.device set active = false where owner_customer_id = '%s'" % ca)
        rec = reclamer(['push'], 200)
        ok(pushs > 0 and all(x['recipient'] for x in rec) and n_("select count(*) from logistics.notification where status = 'SKIPPED' and channel = 'push' and customer_id = '%s' and last_error = 'Plus de destinataire pour ce canal.'" % ca) == pushs,
           'plus d\'appareil actif : les %d notifications « push » de A sont marquées non envoyées, sans être réclamées' % pushs)
        q("update logistics.device set active = true where owner_customer_id = '%s'" % ca)
        ok(int(travailleur("select public.ses_nt_disable_tokens(array['ExponentPushToken[essai-A]', 'inconnu'])")) <= 1, 'un jeton refusé par le service est désactivé (jamais supprimé)')
        ok(q("select active::text from logistics.device where push_token = 'ExponentPushToken[essai-A]'") in ('false', ''), 'le jeton refusé est désactivé…')
        ok(q("select count(*) from logistics.device where push_token = 'ExponentPushToken[essai-A]'") == ('1' if appareils_crees else '0'), '… et jamais supprimé')
        # un jeton posé pour CET essai (la fixture peut déjà avoir ses appareils) : refusé, il reste en base, inactif, avec ses voisins intacts
        q("insert into logistics.device (kind, platform, push_token, owner_customer_id) values ('customer_push', 'android', 'ExponentPushToken[essai-refus]', '%s')" % ca)
        voisins = appareils(ca)
        ok(travailleur("select public.ses_nt_disable_tokens(array['ExponentPushToken[essai-refus]'])") == '1', 'le jeton refusé : une ligne touchée')
        ok(q("select count(*) || '|' || bool_or(active)::text from logistics.device where push_token = 'ExponentPushToken[essai-refus]'") == '1|false', 'le jeton refusé reste en base (l\'historique de l\'appareil), seulement inactif')
        ok(appareils(ca) == voisins - 1, 'les autres appareils du client ne bougent pas')
        # une notification « portail » ne se réclame jamais, même restée en attente par accident : le portail la lit dans la base
        n_ia = q("select id from logistics.notification where channel = 'in_app' order by id limit 1")
        q("update logistics.notification set status = 'PENDING', next_attempt_at = now(), locked_until = null where id = %s" % n_ia)
        ok(all(str(x['notification_id']) != n_ia for x in reclamer(['in_app'], 500)), 'une notification « portail » en attente n\'est jamais confiée au travailleur')
        q("update logistics.notification set status = 'SENT' where id = %s" % n_ia)
        # un canal éteint n'est pas réclamé
        q("update logistics.notification set locked_until = null, next_attempt_at = now() where status = 'PENDING'")
        q("update logistics.notification_channel set enabled = false where code = 'email'")
        ok(not any(x['channel'] == 'email' for x in reclamer(None, 200)), 'canal e-mail éteint : ses notifications attendent, aucune n\'est réclamée')
        q("update logistics.notification_channel set enabled = true where code = 'email'")
        ok(avant > 0, 'il y avait bien du travail en attente')

        # ============================================================== G. le signal temps réel
        n_sig = lambda w: n_("select count(*) from public.ses_signal where %s" % w)   # noqa: E731
        ok(n_sig("audience = 'staff'") >= n_("select count(*) from logistics.domain_event"), 'un signal « équipe » par événement')
        ok(n_sig("audience = 'customer' and user_id = '%s'" % ua) > 0 and n_sig("audience = 'customer' and user_id = '%s'" % ub) > 0, 'des signaux « client » pour A et pour B')
        ok(set(cl.lignes(B, "select distinct topic from public.ses_signal")) <= {'parcel', 'shipment', 'invoice', 'payment', 'request', 'ticket', 'task', 'delivery', 'quote', 'pricing', 'address', 'customer', 'consolidation', 'incident', 'scan', 'customs', 'trip', 'pickup', 'expense'},
           'un sujet = un domaine, rien d\'autre')
        ok(set(cl.lignes(B, "select column_name from information_schema.columns where table_schema = 'public' and table_name = 'ses_signal'")) == {'id', 'audience', 'user_id', 'topic', 'created_at'}, 'le signal ne porte AUCUNE donnée métier')

        def vus(acteur, role='authenticated'):
            code, sortie = cl.run(B, "select coalesce(string_agg(audience || ':' || coalesce(user_id::text, '-'), ','), '') from public.ses_signal", role=role, claims=acteur, expect_error=True)
            return code, sortie
        code, s_a = vus(ua)
        ok(code == 0 and s_a and set(s_a.split(',')) == {'customer:' + ua}, 'A ne lit que SES signaux')
        code, s_op = vus(op)
        ok(code == 0 and s_op and set(s_op.split(',')) == {'staff:-'}, 'un employé qui lit les colis voit les signaux de l\'équipe, et aucun signal d\'un client')
        code, s_anon = vus(None, 'anon')
        ok(code != 0 and 'permission denied' in s_anon, 'un visiteur ne lit rien')
        refuse("insert into public.ses_signal (audience, topic) values ('staff', 'parcel')", 'permission denied', 'un client ne fabrique pas de signal', role='authenticated', claims=ua)
        # un signal manqué ne bloque jamais l'opération
        q("alter table public.ses_signal add constraint ses_signal_essai check (false) not valid")
        avant_sig = n_sig('true')
        a4 = nat(ca); tr(a4, 'RECEIVED', p_warehouse_id=wmia)
        ok(q("select status from logistics.parcel where id = '%s'" % a4) == 'RECEIVED' and n_sig('true') == avant_sig, 'le signal ne peut pas s\'écrire : le colis avance quand même, sans signal')
        q("alter table public.ses_signal drop constraint ses_signal_essai")
        refuse("select logistics.purge_signals(interval '10 minutes')", 'LG005', 'purger moins d\'une heure de signaux')
        q("update public.ses_signal set created_at = now() - interval '3 days' where id in (select id from public.ses_signal order by id limit 5)")
        ok(int(travailleur("select public.ses_nt_purge_signals()")) == 5, 'la purge retire seulement les signaux de plus de deux jours')

        # ============================================================== H. une panne du moteur ne bloque aucun colis
        q("alter table logistics.notification_template rename to notification_template_cache")
        a5 = nat(cb); tr(a5, 'RECEIVED', p_warehouse_id=wmia)
        ok(q("select status from logistics.parcel where id = '%s'" % a5) == 'RECEIVED', 'modèles indisponibles : le colis est reçu quand même')
        repartir()
        ev5 = q("select id from logistics.domain_event where event_type = 'ParcelReceived' and aggregate_id = '%s'" % a5)
        ok(q("select status from logistics.event_delivery where event_row_id = %s and subscriber_code = 'notification_engine'" % ev5) == 'FAILED', 'la livraison de l\'événement au moteur est en échec, et retentée plus tard')
        q("alter table logistics.notification_template_cache rename to notification_template")
        q("update logistics.event_delivery set next_attempt_at = now() where event_row_id = %s" % ev5)
        repartir()
        ok(q("select status from logistics.event_delivery where event_row_id = %s and subscriber_code = 'notification_engine'" % ev5) == 'DELIVERED' and len([x for x in notifs(cb, 'ParcelReceived')]) >= 2,
           'réparé : le moteur rattrape l\'événement, B est prévenu')

        # ============================================================== I. la santé des envois, pour l'équipe
        h = f('lg_cc_notification_health', op)
        ch_ = {c_['channel']: c_ for c_ in h['channels']}
        ok(sorted(ch_) == ['email', 'in_app', 'push', 'sms', 'whatsapp'], 'les cinq canaux')
        for c_ in ('email', 'push'):
            ok(ch_[c_]['pending'] + ch_[c_]['sending'] == n_("select count(*) from logistics.notification where channel = '%s' and status = 'PENDING'" % c_)
               and ch_[c_]['sent_24h'] == n_("select count(*) from logistics.notification where channel = '%s' and status = 'SENT' and sent_at >= now() - interval '24 hours'" % c_)
               and ch_[c_]['failed_24h'] == n_("select count(*) from logistics.notification_attempt a join logistics.notification n on n.id = a.notification_id where n.channel = '%s' and a.outcome = 'FAILED'" % c_),
               '%s : en attente, envoyées, échecs — identiques au décompte indépendant' % c_)
        ok(h['recent_errors'] and all('xkeysib-abc' not in json.dumps(e_) for e_ in h['recent_errors']) and set(h['recent_errors'][0]) == {'at', 'channel', 'template', 'outcome', 'error'}, 'les dernières erreurs, nettoyées, sans destinataire')
        ok('client' not in json.dumps(h) and '@' not in json.dumps(h), 'aucune adresse, aucun client dans la santé des envois')
        fr('lg_cc_notification_health', 'LG003', 'un client', ua)

        # ============================================================== J. les portes
        portes = cl.lignes(B, "select p.proname || '|' || has_function_privilege('authenticated', p.oid, 'execute') || '|' || has_function_privilege('anon', p.oid, 'execute') || '|' || has_function_privilege('service_role', p.oid, 'execute') || '|' || p.prosecdef || '|' || coalesce(array_to_string(p.proconfig, ','), '') "
                               "from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and (p.proname like 'ses\\_nt\\_%' or p.proname in ('lg_my_notification_prefs', 'lg_set_notification_pref', 'lg_cc_notification_health')) order by 1")
        ok(len(portes) == 8, 'huit fonctions de façade : %d' % len(portes))
        for l_ in portes:
            nom_, au_, an_, sr_, sd_, cf_ = l_.split('|')
            if nom_.startswith('ses_nt_'):
                ok(au_ == 'false' and an_ == 'false' and sr_ == 'true', '%s : réservée à la clé secrète (ni connecté, ni visiteur)' % nom_)
            else:
                ok(au_ == 'true' and an_ == 'false', '%s : connectés seulement' % nom_)
            ok(sd_ == 'true' and 'search_path=""' in cf_, '%s : définisseur, chemin de recherche vidé' % nom_)
        for sql_ in ("select * from public.ses_nt_claim('pirate', null)", "select public.ses_nt_report(1, true)", "select public.ses_nt_dispatch()", "select logistics.nt_claim('x', null)", "select * from logistics.notification", "select * from logistics.notification_attempt"):
            for qui_, kw_ in (('un client', dict(role='authenticated', claims=ua)), ('la direction connectée', dict(role='authenticated', claims=admin)), ('un visiteur', dict(role='anon'))):
                code, t_ = cl.run(B, sql_, expect_error=True, **kw_)
                ok(code != 0 and ('permission denied' in t_ or '42501' in t_), '%s ne peut pas « %s »' % (qui_, sql_[:50]))
        ok(n_("select count(*) from pg_tables where schemaname = 'logistics' and not rowsecurity") == 0 and n_("select count(*) from information_schema.role_table_grants where table_schema = 'logistics' and grantee in ('anon', 'authenticated', 'PUBLIC')") == 0,
           'les tables du noyau restent fermées')
        ok(cl.lignes(B, "select privilege_type from information_schema.role_table_grants where table_schema = 'public' and table_name = 'ses_signal' and grantee = 'authenticated'") == ['SELECT'] and
           q("select relrowsecurity::text from pg_class where oid = 'public.ses_signal'::regclass") == 'true', 'le signal : lecture seule pour les connectés, sous sécurité par ligne')
        # la façade du travailleur n'est pas rouverte par une migration rejouée après coup
        cl.run(B, P.lire_sql('outils/logistique/009-centre-de-commande.sql'))
        ok(q("select has_function_privilege('authenticated', 'public.ses_nt_claim(text, text[], int, int)', 'execute')::text") == 'false', '009 rejouée APRÈS 010 : la façade du travailleur reste fermée aux connectés')

        # ============================================================== K. les formes figées, partagées avec le test du navigateur (notifications-contrat.cjs)
        def cles(x, chemin=''):
            sortie = set()
            if isinstance(x, dict):
                for k, v in x.items():
                    sortie.add(chemin + '.' + k)
                    sortie |= cles(v, chemin + '.' + k)
            elif isinstance(x, list):
                for v in x:
                    sortie |= cles(v, chemin + '[]')
            return sortie
        REP = {'preferences': f('lg_my_notification_prefs', ua), 'sante': f('lg_cc_notification_health', op)}
        FORMES = {k_: sorted(cles(v_)) for k_, v_ in REP.items()}
        SIG = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), 'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) "
                           "from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname in ('lg_my_notification_prefs', 'lg_set_notification_pref', 'lg_cc_notification_health')"))
        DIR_ = os.path.dirname(os.path.abspath(__file__))
        CH_F, CH_R = os.path.join(DIR_, 'notifications-formes.json'), os.path.join(DIR_, 'notifications-rpc.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(FORMES, open(CH_F, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            json.dump(SIG, open(CH_R, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        ok(json.load(open(CH_F, encoding='utf-8')) == FORMES, 'la forme des préférences et de la santé des envois est celle du fichier partagé (sinon : SES_FORME_ECRIRE=1, et relire)')
        ok(json.load(open(CH_R, encoding='utf-8')) == json.loads(json.dumps(SIG)), 'les signatures des trois fonctions sont celles du fichier partagé')

    print('%d vérifications — phase 13 (notifications et temps réel) : OK' % N[0])


if __name__ == '__main__':
    main()
