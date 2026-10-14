#!/usr/bin/env python3
"""Étape 027 — le centre de notifications (phase 11), éprouvé sur la RÉPLIQUE DE LA PRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-notifications-centre-essai.py

On exige :
 A. chaque notification porte son destinataire (les anciennes aussi) ; les règles nouvelles existent ; WhatsApp a son fournisseur, éteint ;
 B. l'INSCRIPTION : la bienvenue part une fois, après la confirmation de l'adresse ; jamais avant, jamais deux fois, jamais pour un compte
    ancien ; une panne de la bienvenue ne bloque JAMAIS une confirmation ;
 C. le DOCUMENT NÉCESSAIRE : une exception de douane « document manquant » prévient (sans sa description interne) et remplace le message
    « en attente » ; une autre exception garde le message « en attente » ;
 D. WHATSAPP : seulement si le canal est allumé ET que le client l'a demandé ; le travailleur reçoit modèle, langue, variables permises, pays ;
 E. IDEMPOTENCE : un même événement, rejoué, ne crée jamais une seconde notification ;
 F. les ACCUSÉS des fournisseurs : remis, lu, rebond (échec), en double, référence inconnue ; la clé secrète seulement ;
 G. la SURVEILLANCE : l'alerte au-delà du seuil ; la relance par la direction (même notification, motif, audit) ; la liste des échecs, masquée ;
 H. rien d'ouvert aux visiteurs ni aux clients ; 027 rejouée ne change rien.
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
    if isinstance(v, list):
        return "array[%s]::uuid[]" % ', '.join("'%s'" % x for x in v) if v else "'{}'::uuid[]"
    return "'%s'" % str(v).replace("'", "''")


def main():
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('027-centre-notifications.sql' in etapes, 'l\'étape 027 est dans le noyau')
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        ok(json.loads(q("select logistics.run_migration('notifications')"))['report']['ready'] is True, 'rattrapage prêt')

        def utilisateur(n, email, confirme=True, cree="now()"):
            q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, created_at, raw_user_meta_data) values "
              "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0027-%012d', 'authenticated', 'authenticated', '%s', 'x', %s, %s, '{}')"
              % (n, email, 'now()' if confirme else 'null', cree))
            return '00000000-0000-0000-0027-%012d' % n

        utilisateur(1, 'nt-emp@essai.test')
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.statut'] where email = 'nt-emp@essai.test'")
        q("select logistics.run_migration('notifications, employé')")
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        emp = q("select id from public.clients where email = 'nt-emp@essai.test'")
        client = q("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1")
        repartir = lambda: q("select logistics.dispatch_events(1000, 'notification_engine')")   # noqa: E731

        def appel(nom, acteur, kw):
            return cl.run('prod', 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items())), role='authenticated', claims=acteur, expect_error=True)

        def f(nom, acteur=emp, **kw):
            code, sortie = appel(nom, acteur, kw)
            if code != 0:
                raise AssertionError('%s refusée : %s' % (nom, sortie[-400:]))
            return json.loads(sortie)

        def refus(nom, attendu, msg, acteur=emp, **kw):
            code, sortie = appel(nom, acteur, kw)
            ok(code != 0 and attendu in sortie, '%s : attendu « %s », obtenu %s' % (msg, attendu, sortie[-240:]))

        def service(sql):
            code, sortie = cl.run('prod', 'set role service_role; ' + sql, expect_error=True)
            if code != 0:
                raise AssertionError('service_role refusé : %s' % sortie[-300:])
            return sortie.strip().splitlines()[-1] if sortie.strip() else ''

        # ============================================================ A. la forme
        ok(q("select count(*) from logistics.notification where recipient is null") == '0', 'toutes les notifications portent leur destinataire, les anciennes aussi')
        regles = {l.split('=')[0]: l.split('=')[1].split(',') for l in cl.lignes('prod', "select event_type || '=' || array_to_string(channels, ',') from logistics.notification_rule")}
        ok(regles.get('CustomerRegistered') == ['in_app', 'email'] and 'whatsapp' in regles.get('CustomsExceptionRaised', []), 'les deux règles nouvelles')
        wa = sorted(k for k, v in regles.items() if 'whatsapp' in v)
        ok(wa == sorted(['ParcelAtDestinationHub', 'OutForDelivery', 'DeliveryAssigned', 'Delivered', 'DeliveryFailed', 'InvoiceIssued', 'PaymentReceived', 'CustomsExceptionRaised']),
           'WhatsApp entre dans les règles qui comptent : %s' % wa)
        wa_modeles = json.load(open(os.path.join(P.RACINE, 'scripts/notifications/whatsapp-modeles.json'), encoding='utf-8'))
        modeles_wa = {m['name'] for m in wa_modeles['modeles']}
        tpl = {l.split('=')[0]: l.split('=')[1] for l in cl.lignes('prod', "select event_type || '=' || template from logistics.notification_rule")}
        for e in wa:
            nom = 'ses_' + re.sub(r'(?<!^)(?=[A-Z])', '_', tpl[e]).lower()
            ok(nom in modeles_wa, 'le modèle WhatsApp %s existe pour la règle %s' % (nom, e))
        ok(q("select enabled::text || '/' || provider from logistics.notification_channel where code = 'whatsapp'") == 'false/meta', 'WhatsApp : fournisseur Meta, canal ÉTEINT')
        ok(q("select count(*) from logistics.notification_template where code in ('Welcome', 'DocumentRequired')") == '8', 'deux modèles × quatre langues')
        ok(q("select count(*) from logistics.event_subscriber where code = 'notification_engine' and 'CustomerRegistered' = any (event_types) and 'CustomsExceptionRaised' = any (event_types)") == '1',
           'le moteur écoute les deux nouveaux événements')

        # ============================================================ B. l'inscription
        nouveau = utilisateur(2, 'nouvelle-cliente@essai.test', confirme=False)
        q("update public.clients set langue = 'ht' where id = '%s'" % nouveau)
        q("select logistics.run_migration('inscription')")
        cust = q("select id from logistics.customer where auth_user_id = '%s'" % nouveau)
        ok(cust, 'la nouvelle cliente est recopiée dans le noyau')
        bienvenues = lambda: q("select count(*) from logistics.domain_event where event_type = 'CustomerRegistered' and aggregate_id = '%s'" % cust)   # noqa: E731
        ok(bienvenues() == '0', 'pas de bienvenue tant que l\'adresse n\'est pas confirmée')
        q("update auth.users set email_confirmed_at = now() where id = '%s'" % nouveau)
        ok(bienvenues() == '1', 'adresse confirmée : la bienvenue est demandée')
        q("update auth.users set email_confirmed_at = null where id = '%s'" % nouveau)
        q("update auth.users set email_confirmed_at = now() where id = '%s'" % nouveau)
        q("update logistics.customer set auth_user_id = auth_user_id where id = '%s'" % cust)
        ok(bienvenues() == '1', 'jamais deux fois (confirmée de nouveau, recopiée de nouveau)')
        repartir()
        nb = cl.lignes('prod', "select channel || '|' || status || '|' || coalesce(recipient, '') || '|' || language || '|' || body from logistics.notification "
                               "where customer_id = '%s' and template = 'Welcome' order by channel" % cust)
        code_client = q("select code from logistics.customer where id = '%s'" % cust)
        ok(len(nb) == 2 and nb[0].startswith('email|PENDING|nouvelle-cliente@essai.test|ht|') and nb[1].startswith('in_app|SENT|portail|ht|'),
           'la bienvenue : portail (lue tout de suite) et e-mail (en attente du travailleur), en créole, destinataire écrit : %s' % nb)
        ok(all(code_client in x for x in nb), 'elle donne le code client (%s)' % code_client)
        # un compte ancien, confirmé aujourd'hui seulement : rien
        ancien = utilisateur(3, 'ancien-client@essai.test', confirme=False, cree="now() - interval '40 days'")
        q("select logistics.run_migration('ancien')")
        q("update auth.users set email_confirmed_at = now() where id = '%s'" % ancien)
        ok(q("select count(*) from logistics.domain_event e join logistics.customer c on c.id::text = e.aggregate_id where e.event_type = 'CustomerRegistered' and c.auth_user_id = '%s'" % ancien) == '0',
           'un compte ancien ne reçoit jamais de bienvenue')
        # confirmée AVANT d'être recopiée : la recopie la déclenche
        tot = utilisateur(4, 'confirmee-tot@essai.test')
        q("select logistics.run_migration('confirmée tôt')")
        ok(q("select count(*) from logistics.domain_event e join logistics.customer c on c.id::text = e.aggregate_id where e.event_type = 'CustomerRegistered' and c.auth_user_id = '%s'" % tot) == '1',
           'confirmée avant la recopie : la recopie demande la bienvenue')
        # une panne de la bienvenue ne bloque JAMAIS une confirmation
        q("create or replace function logistics.nt_welcome(p_auth_user uuid) returns void language plpgsql as $$ begin raise exception 'panne simulée'; end; $$")
        panne = utilisateur(5, 'panne@essai.test', confirme=False)
        code, sortie = cl.run('prod', "update auth.users set email_confirmed_at = now() where id = '%s'" % panne, expect_error=True)
        ok(code == 0 and q("select email_confirmed_at is not null from auth.users where id = '%s'" % panne) == 't', 'bienvenue en panne : la confirmation passe quand même')
        cl.run('prod', P.lire_sql('outils/logistique/027-centre-notifications.sql'))

        # ============================================================ C. le document nécessaire (un vrai passage en douane)
        mia = f('lg_create_branch', admin, p_code='MIA', p_name='Miami', p_kind='office', p_country='US', p_city='Doral')['branch_id']
        pap = f('lg_create_branch', admin, p_code='PAP-HUB', p_name='Hub Port-au-Prince', p_kind='hub', p_country='HT', p_city='Port-au-Prince')['branch_id']
        wm = f('lg_create_warehouse', admin, p_branch_id=mia, p_code='MIA-1', p_name='Doral')['warehouse_id']
        etagere = f('lg_create_location', admin, p_warehouse_id=wm, p_code='A-01', p_zone='A', p_kind='staging')['location_id']
        nums = cl.lignes('prod', "select p.tracking_number from logistics.parcel p join logistics.customer c on c.id = p.customer_id where p.status = 'CREATED' and p.service_mode = 'air' "
                                 "and p.destination_country = 'HT' and c.email <> '' and coalesce(p.verified_weight_lb, p.weight_lb) > 0 order by p.tracking_number limit 2")
        ok(len(nums) == 2, 'deux colis aériens pour Haïti, de clients joignables par e-mail')
        f('lg_prepare_parcels', p_tracking_numbers=R("array[%s, %s]::text[]" % (val(nums[0]), val(nums[1]))), p_warehouse_id=wm, p_location_id=etagere)
        ids = [q("select id from logistics.parcel where tracking_number = %s" % val(x)) for x in nums]
        sid = f('lg_create_shipment', p_code='EXP-NT-1', p_mode='air', p_origin_branch=mia, p_destination_branch=pap, p_parcel_ids=ids)['shipment_id']
        f('lg_generate_manifest', p_shipment_id=sid)
        f('lg_mark_shipment_ready', p_shipment_id=sid)
        t = f('lg_create_transport', p_mode='air', p_carrier='Sunrise', p_reference='AWB-NT', p_voyage_number='2Q-9', p_origin_branch=mia, p_destination_branch=pap,
              p_planned_departure=R("now() + interval '1 hour'"), p_planned_arrival=R("now() + interval '4 hours'"))['transport_id']
        f('lg_dispatch_shipment', p_shipment_id=sid, p_transport_id=t)
        f('lg_arrive_shipment', p_shipment_id=sid)
        f('lg_start_customs', p_shipment_id=sid, p_reference='DEC-NT', p_broker='Courtier')
        repartir()
        f('lg_customs_raise_exception', admin, p_shipment_id=sid, p_parcel_id=ids[0], p_kind='MISSING_DOCUMENT', p_description='Facture d\'achat illisible — NOTE INTERNE')
        f('lg_customs_raise_exception', admin, p_shipment_id=sid, p_parcel_id=ids[1], p_kind='UNDERVALUED', p_description='Valeur douteuse — NOTE INTERNE')
        repartir()
        doc = cl.lignes('prod', "select template || '|' || channel from logistics.notification where parcel_id = '%s' and template in ('DocumentRequired', 'ParcelOnHold') order by 1" % ids[0])
        ok(doc == ['DocumentRequired|email', 'DocumentRequired|in_app'] or doc == ['DocumentRequired|email', 'DocumentRequired|in_app', 'DocumentRequired|push'],
           'document manquant : « document demandé », et PAS un second message « en attente » : %s' % doc)
        ok(q("select count(*) from logistics.notification where parcel_id = '%s' and template = 'DocumentRequired' and (body like '%%NOTE INTERNE%%' or body like '%%illisible%%')" % ids[0]) == '0'
           and q("select count(*) from logistics.notification where parcel_id = '%s' and template = 'DocumentRequired' and body like '%%' || %s || '%%'" % (ids[0], val(nums[0]))) != '0',
           'le message donne le numéro du colis, jamais la note interne de la douane')
        autre = cl.lignes('prod', "select distinct template from logistics.notification where parcel_id = '%s' and template in ('DocumentRequired', 'ParcelOnHold')" % ids[1])
        ok(autre == ['ParcelOnHold'], 'une autre exception (sous-évaluation) garde le message « en attente », sans « document » : %s' % autre)

        # ============================================================ D. WhatsApp
        c_wa = q("select customer_id from logistics.parcel where id = '%s'" % ids[0])
        q("update logistics.customer set phone = '+509 3700 1234' where id = '%s'" % c_wa)
        avant = q("select count(*) from logistics.notification where channel = 'whatsapp'")
        q("update logistics.notification_channel set enabled = true where code = 'whatsapp'")
        # un événement « livré » simulé par la vraie machine : on rejoue le moteur sur un événement existant du colis, client SANS préférence
        ev = q("select id from logistics.domain_event where aggregate_id = '%s' and event_type = 'ParcelArrived' order by id limit 1" % ids[0])
        q("insert into logistics.notification_rule (event_type, template, channels) values ('ParcelArrived', 'ParcelArrived', array['in_app', 'push']) on conflict (event_type) do update set channels = array['in_app', 'push', 'whatsapp']")
        q("select logistics.handle_notification_engine(e) from logistics.domain_event e where e.id = %s" % ev)
        ok(q("select count(*) from logistics.notification where channel = 'whatsapp'") == avant, 'canal allumé mais client sans préférence WhatsApp : rien (il doit l\'avoir demandé)')
        auth_wa = q("select auth_user_id from logistics.customer where id = '%s'" % c_wa)
        code, sortie = appel('lg_set_notification_pref', auth_wa, {'p_channel': 'whatsapp', 'p_enabled': True})
        ok(code == 0, 'le client demande WhatsApp depuis son portail : %s' % sortie[-160:])
        ev2 = q("select id from logistics.domain_event where aggregate_id = '%s' and event_type = 'ParcelInTransit' order by id limit 1" % ids[0])
        q("insert into logistics.notification_rule (event_type, template, channels) values ('ParcelInTransit', 'ParcelInTransit', array['in_app']) on conflict (event_type) do update set channels = array['in_app', 'push', 'whatsapp']")
        q("select logistics.handle_notification_engine(e) from logistics.domain_event e where e.id = %s" % ev2)
        nw = q("select id || '|' || status || '|' || recipient || '|' || template from logistics.notification where event_row_id = %s and channel = 'whatsapp'" % ev2)
        ok(nw and nw.split('|')[1:] == ['PENDING', '+509 3700 1234', 'ParcelInTransit'], 'demandé : la notification WhatsApp attend le travailleur, vers le bon numéro : %s' % nw)
        donnees = json.loads(service("select public.ses_nt_template_data(array[%s]::bigint[])" % nw.split('|')[0]))[nw.split('|')[0]]
        ok(donnees['template'] == 'ParcelInTransit' and donnees['variables'].get('tracking_number') == nums[0] and set(donnees['variables']) <= {'tracking_number', 'stage'}
           and donnees['country'] in ('HT', 'US', 'DO', None) and donnees['language'] in ('fr', 'en', 'es', 'ht'),
           'le travailleur reçoit le modèle, la langue, les variables PERMISES et le pays (indicatif) : %s' % donnees)
        ok([q("select coalesce(logistics.nt_country_code(%s), '-')" % val(x)) for x in ('Haïti', 'haiti', 'HT', 'République dominicaine', 'Republica Dominicana', 'États-Unis', 'USA', 'France', '')]
           == ['HT', 'HT', 'HT', 'DO', 'DO', 'US', 'US', '-', '-'], 'le pays écrit en toutes lettres devient un code ; un pays inconnu, rien (le numéro doit alors porter son indicatif)')
        # ============================================================ E. idempotence
        q("select logistics.handle_notification_engine(e) from logistics.domain_event e where e.id = %s" % ev2)
        repartir()
        ok(q("select count(*) from logistics.notification where event_row_id = %s and channel = 'whatsapp'" % ev2) == '1', 'un même événement rejoué : une seule notification par canal')
        ok(q("select count(*) from (select event_row_id, channel from logistics.notification where event_row_id is not null group by 1, 2 having count(*) > 1) x") == '0',
           'nulle part deux notifications pour le même événement et le même canal')
        q("update logistics.notification_channel set enabled = false where code = 'whatsapp'")

        # ============================================================ F. les accusés des fournisseurs
        n_mail = q("select id from logistics.notification where customer_id = '%s' and template = 'Welcome' and channel = 'email'" % cust)
        q("update logistics.notification set status = 'SENT', sent_at = now(), provider_ref = '<msg-1@smtp-relay.brevo.test>' where id = %s" % n_mail)
        r = json.loads(service("select public.ses_nt_provider_event('brevo', '<msg-1@smtp-relay.brevo.test>', 'DELIVERED', null, now())"))
        ok(r['result'] == 'APPLIED' and q("select provider_status || '|' || (delivered_at is not null) from logistics.notification where id = %s" % n_mail) == 'DELIVERED|true', 'remis : noté, avec l\'heure')
        ok(json.loads(service("select public.ses_nt_provider_event('brevo', '<msg-1@smtp-relay.brevo.test>', 'DELIVERED')"))['result'] == 'DUPLICATE', 'le même accusé deux fois : rien de plus')
        ok(json.loads(service("select public.ses_nt_provider_event('meta', 'wamid.inconnu', 'READ')"))['result'] == 'UNKNOWN_REF', 'une référence inconnue est gardée sans rien toucher')
        r = json.loads(service("select public.ses_nt_provider_event('brevo', '<msg-1@smtp-relay.brevo.test>', 'BOUNCED', 'hard_bounce: boîte inexistante — clé sk_live_abcdef1234567890')"))
        ok(r['result'] == 'APPLIED' and q("select status from logistics.notification where id = %s" % n_mail) == 'FAILED', 'un rebond : la notification passe en échec')
        ok('sk_live_abcdef' not in q("select last_error from logistics.notification where id = %s" % n_mail), 'l\'erreur est nettoyée de tout ce qui ressemble à une clé')
        ok(q("select count(*) from logistics.notification_attempt where notification_id = %s and outcome = 'FAILED' and worker = 'brevo'" % n_mail) == '1', 'le rebond est au journal des essais')
        code, sortie = cl.run('prod', "update logistics.notification_provider_event set status = 'READ'", expect_error=True)
        ok(code != 0, 'les accusés sont en ajout seul')
        for role, claims in (('authenticated', emp), ('authenticated', client), ('anon', None)):
            code, sortie = cl.run('prod', "select public.ses_nt_provider_event('brevo', 'x', 'DELIVERED')", role=role, claims=claims, expect_error=True)
            ok(code != 0 and 'permission denied' in sortie, 'ses_nt_provider_event : %s refusé' % role)
            code, sortie = cl.run('prod', "select public.ses_nt_template_data(array[1]::bigint[])", role=role, claims=claims, expect_error=True)
            ok(code != 0 and 'permission denied' in sortie, 'ses_nt_template_data : %s refusé' % role)

        # ============================================================ G. la surveillance
        alerte = json.loads(service("select public.ses_nt_alert()"))
        ok(alerte['alert'] is False and any(c['channel'] == 'email' and c['failed_24h'] >= 1 for c in alerte['channels']), 'un échec isolé : pas d\'alerte, mais compté')
        q("update logistics.notification set status = 'FAILED', last_error = 'brevo 401 clé refusée' where id in (select id from logistics.notification where channel = 'email' "
          "and status in ('PENDING', 'SENT') order by id limit 12)")
        ok(json.loads(service("select public.ses_nt_alert()"))['alert'] is True, 'au-delà de 10 échecs en 24 h sur un canal allumé : ALERTE')
        echecs = f('lg_cc_notification_failures', admin)
        ok(echecs['can_retry'] is True and len(echecs['items']) >= 10, 'la direction voit les échecs et peut relancer')
        ok(all('@' not in (x['recipient'] or '') or '***@' in x['recipient'] for x in echecs['items']), 'le destinataire est masqué dans la liste')
        ok(f('lg_cc_notification_failures', emp)['can_retry'] is False, 'un employé voit, sans relancer')
        refus('lg_cc_notification_failures', 'LG003', 'un client ne voit rien', acteur=client)
        cible = echecs['items'][0]['notification_id']
        refus('lg_nt_retry', 'LG003', 'un employé ne relance pas', p_notification_id=R(str(cible)), p_reason='x')
        refus('lg_nt_retry', 'LG005', 'motif obligatoire', acteur=admin, p_notification_id=R(str(cible)), p_reason='  ')
        lignes_avant = q("select count(*) from logistics.notification")
        r = f('lg_nt_retry', admin, p_notification_id=R(str(cible)), p_reason='Clé Brevo remplacée')
        ok(r['status'] == 'PENDING' and q("select status || '|' || attempts from logistics.notification where id = %s" % cible) == 'PENDING|0'
           and q("select count(*) from logistics.notification") == lignes_avant, 'relancée : la MÊME notification repart, aucune nouvelle')
        ok(q("select count(*) from logistics.audit_log where action = 'notification.retry' and entity_id = '%s'" % cible) == '1', 'la relance est tracée')
        refus('lg_nt_retry', 'LG004', 'on ne relance qu\'un échec', acteur=admin, p_notification_id=R(str(cible)), p_reason='encore')

        # les signatures des fonctions que le site appelle, partagées avec notifications-contrat.cjs
        sig = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), "
                           "'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) "
                           "from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname in ('lg_cc_notification_failures', 'lg_nt_retry')"))
        ch = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'notifications-centre-rpc.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(sig, open(ch, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        ok(json.load(open(ch, encoding='utf-8')) == sig, 'les signatures sont celles du fichier partagé avec le contrat du site (sinon : SES_FORME_ECRIRE=1)')

        # ============================================================ H. fermé, rejouable
        avant = q("select count(*) || '/' || (select count(*) from logistics.domain_event) from logistics.notification")
        cl.run('prod', P.lire_sql('outils/logistique/027-centre-notifications.sql'))
        ok(q("select count(*) || '/' || (select count(*) from logistics.domain_event) from logistics.notification") == avant, '027 rejouée : rien ne change')
        ok(q('select count(*) from logistics.workflow_inconsistencies()') == '0', 'aucune incohérence')
        print('PASS centre de notifications (étape 027) : %d vérifications — destinataire écrit, bienvenue unique après confirmation, document demandé sans '
              'doublon ni note interne, WhatsApp sur demande du client, idempotence, accusés des fournisseurs, alerte et relance (PostgreSQL %s).'
              % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC centre de notifications (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
