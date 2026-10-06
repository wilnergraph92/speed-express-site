#!/usr/bin/env python3
"""Noyau logistique, phase 14 : ce que les applications mobiles demandent — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-applications-essai.py

Jamais la production. Ce qu'on éprouve : (1) le profil « Opérations » de chacun (chauffeur, agent d'entrepôt, agent de livraison) est
décidé par la base, d'après les droits, la fiche chauffeur et la succursale ; un client n'en a aucun ; (2) la porte des actions hors
connexion : exactement une fois par clé, même rejouée dix fois ; une clé pour une autre action est refusée ; une action refusée ne
consomme pas sa clé ; une position ancienne ne remplace jamais une plus récente ; (3) les portes et la forme figée des signatures, que
l'application relit (applications-rpc.json)."""
import json
import os
import re
import sys

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
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return "'%s'::jsonb" % json.dumps(v).replace("'", "''")
    if isinstance(v, (list, tuple)):
        return "array[%s]::%s[]" % (', '.join(val(x) for x in v), 'uuid' if v and re.match(r'^[0-9a-f-]{36}$', str(v[0])) else 'text') if v else "'{}'"
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items()))


# Les fonctions de la façade que l'application « Opérations » appelle (relu par le test de l'application).
APPLICATION = ['lg_my_staff_profile', 'lg_mobile_command', 'lg_my_tasks', 'lg_task_board', 'lg_assign_task', 'lg_auto_assign_task', 'lg_issue_delivery_otp', 'lg_rank_drivers']


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        n_ = lambda sql: int(q(sql))   # noqa: E731
        P.monter_historique(cl, B)
        for f_ in ('001-modele-de-domaine', '002-retroremplissage', '003-machine-d-etats', '004-entrepot', '005-transport-douane', '006-dernier-kilometre', '007-finance', '008-portail-client', '009-centre-de-commande', '010-notifications'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f_))
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) "
          "select '00000000-0000-0000-0000-000000000000', ('00000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid, 'authenticated', 'authenticated', "
          "'chauffeur' || i || '@essai.test', '$2a$10$fictif', now(), jsonb_build_object('nom_complet', 'Chauffeur ' || i, 'pays', 'Haïti', 'ville', 'Delmas', 'adresse', 'x', 'telephone', '+509 3000', 'langue', 'fr') "
          "from generate_series(21, 22) i")
        q("update public.clients set role = 'employe', droits = '{}' where email in ('chauffeur21@essai.test', 'chauffeur22@essai.test')")
        # Comme sur Supabase : toute fonction créée devient exécutable par anon et authenticated, sauf révocation explicite.
        # Sans cela, « fermé aux connectés » serait vrai par défaut ici et ne prouverait rien de la migration.
        q("alter default privileges in schema public grant execute on functions to anon, authenticated")
        q("alter default privileges in schema logistics grant execute on functions to anon, authenticated")
        cl.run(B, P.lire_sql('outils/logistique/011-applications.sql'))
        cl.run(B, P.lire_sql('outils/logistique/011-applications.sql'))
        q("alter default privileges in schema public revoke execute on functions from anon, authenticated")
        q("alter default privileges in schema logistics revoke execute on functions from anon, authenticated")
        ok(True, '011 chargée deux fois de suite')
        q('select logistics.backfill_from_legacy()')
        uid = lambda n: q("select id from public.clients where email = 'client%d@essai.test'" % n)   # noqa: E731
        admin, ent, hub_u, ua = uid(1), uid(3), uid(4), uid(9)
        drv_u, drv2_u = q("select id from public.clients where email = 'chauffeur21@essai.test'"), q("select id from public.clients where email = 'chauffeur22@essai.test'")
        ca = q("select id from logistics.customer where auth_user_id = '%s'" % ua)
        org = q('select id from logistics.organization')

        def f(nom, acteur, **kw):
            code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
            return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

        def fr(nom, etat, msg, acteur, **kw):
            code, texte_ = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
            ok(code != 0 and etat in texte_, '%s : attendu %s, obtenu : %s' % (msg, etat, texte_[-200:].replace('\n', ' ')))

        cmd = lambda acteur, cle, commande, args: f('lg_mobile_command', acteur, p_key=cle, p_command=commande, p_args=args)   # noqa: E731

        # ============================================================== A. le décor : succursales, entrepôts, chauffeurs
        q("insert into logistics.branch (organization_id, code, name, kind, country, city) values ('%s', 'MIA', 'Miami', 'office', 'US', 'Miami'), ('%s', 'PAP', 'Hub Port-au-Prince', 'hub', 'HT', 'Port-au-Prince')" % (org, org))
        mia, pap = q("select id from logistics.branch where code = 'MIA'"), q("select id from logistics.branch where code = 'PAP'")
        q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'MIA-1', 'Entrepôt Miami'), ('%s', 'PAP-1', 'Entrepôt hub')" % (mia, pap))
        q("insert into logistics.warehouse (branch_id, code, name, active) values ('%s', 'MIA-0', 'Ancien entrepôt Miami', false)" % mia)
        wmia, wpap = q("select id from logistics.warehouse where code = 'MIA-1'"), q("select id from logistics.warehouse where code = 'PAP-1'")
        q("update logistics.app_user set branch_id = '%s' where id = '%s'" % (mia, ent))
        q("update logistics.app_user set branch_id = '%s' where id = '%s'" % (pap, hub_u))
        veh = f('lg_create_vehicle', admin, p_plate='AA-100', p_kind='VAN', p_capacity_lb=500)
        drv = f('lg_create_driver', admin, p_user_id=drv_u, p_full_name='Chauffeur Un', p_vehicle_id=veh)
        drv2 = f('lg_create_driver', admin, p_user_id=drv2_u, p_full_name='Chauffeur Deux')
        q("update logistics.driver set status = 'ON_LEAVE' where id = '%s'" % drv2)

        # ============================================================== B. le profil « Opérations »
        pr = {nom: f('lg_my_staff_profile', u) for nom, u in (('admin', admin), ('entrepot', ent), ('hub', hub_u), ('chauffeur', drv_u), ('conge', drv2_u), ('client', ua))}
        ok(pr['admin']['staff'] is True and pr['admin']['profiles'] == ['WAREHOUSE_AGENT', 'DELIVERY_AGENT'] and pr['admin']['driver'] is None, 'l\'administrateur (sans succursale) : entrepôt et livraison, pas chauffeur')
        ok(pr['entrepot']['profiles'] == ['WAREHOUSE_AGENT'] and pr['entrepot']['branch'] == 'Miami', 'un employé qui fait avancer les colis, rattaché au bureau de Miami : entrepôt seulement')
        ok([w_['code'] for w_ in pr['entrepot']['warehouses']] == ['MIA-1'], 'ses entrepôts : ceux de sa succursale, jamais un entrepôt fermé')
        ok(pr['hub']['profiles'] == ['DELIVERY_AGENT'] and pr['hub']['warehouses'] == [], 'rattaché au hub : livraison seulement')
        ok(pr['chauffeur']['profiles'] == ['DRIVER'] and pr['chauffeur']['driver']['name'] == 'Chauffeur Un' and pr['chauffeur']['driver']['vehicle'] == 'AA-100', 'le chauffeur actif (sans aucun droit) : chauffeur, avec son véhicule')
        ok(pr['conge']['profiles'] == [] and pr['conge']['driver']['status'] == 'ON_LEAVE', 'un chauffeur en congé : aucun profil (sa fiche reste lisible)')
        ok(pr['client'] == {'staff': False, 'profiles': ['CUSTOMER']}, 'un client : rien pour l\'application « Opérations », seulement « CUSTOMER »')
        ok(pr['admin']['today'] == q("select logistics.today()::text"), 'la date du jour à l\'heure d\'Haïti')
        code, t_ = cl.run(B, appel('lg_my_staff_profile'), role='authenticated', expect_error=True)
        ok(code != 0 and '42501' in t_, 'sans jeton : connexion requise')
        q("update logistics.app_user set active = false where id = '%s'" % ent)
        ok(f('lg_my_staff_profile', ent) == {'staff': False, 'profiles': []}, 'un compte désactivé : plus membre de l\'équipe, aucun profil')
        q("update logistics.app_user set active = true where id = '%s'" % ent)

        # ============================================================== C. la porte des actions hors connexion
        n_p = [0]

        def nat(cust, statut):
            n_p[0] += 1
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, destination_city, service_mode, status, status_authority, source, weight_lb) "
                     "values ('%s', 'N-%03d', 'tok%d', '%s', 'HT', 'Delmas', 'air', '%s', 'core', 'legacy_backfill', 3) returning id" % (org, n_p[0], n_p[0], cust, statut))
        p1 = nat(ca, 'AT_DESTINATION_HUB')
        dl = f('lg_create_delivery', admin, p_parcel_ids=[p1], p_hub_branch=pap, p_scheduled_for=R('current_date'), p_recipient_name='Marie', p_address='1 rue', p_otp_required=True)
        t1 = dl['task_id']
        f('lg_assign_task', admin, p_task_id=t1, p_driver_id=drv, p_force=True, p_reason='essai')
        # les portes
        for u_, nom_ in ((ua, 'un client'), (None, 'un visiteur')):
            if u_:
                fr('lg_mobile_command', 'LG003', '%s : refusé, même avec une clé invalide et une action inconnue' % nom_, u_, p_key='x', p_command='pirater', p_args={})
                fr('lg_mobile_command', 'LG003', '%s : refusé, même pour une action valide' % nom_, u_, p_key='cle-valide-01', p_command='accept_task', p_args={'task_id': t1})
        code, t_ = cl.run(B, appel('lg_mobile_command', p_key='cle-valide-01', p_command='accept_task', p_args={'task_id': t1}), role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in t_, 'un visiteur ne passe pas')
        for kw, msg in ((dict(p_key='court', p_command='accept_task', p_args={'task_id': t1}), 'clé trop courte'), (dict(p_key='avec espace !!', p_command='accept_task', p_args={'task_id': t1}), 'clé avec des caractères interdits'),
                        (dict(p_key='cle-valide-02', p_command='drop_table', p_args={}), 'action inconnue'), (dict(p_key='cle-valide-06', p_command='pirater', p_args={}), 'action inconnue (bis)'),
                        (dict(p_key='cle-valide-07', p_command='accept_task', p_args={'task_id': t1, 'bourrage': 'x' * 20000}), 'arguments démesurés'), (dict(p_key='cle-valide-03', p_command='accept_task', p_args={}), 'mission manquante'),
                        (dict(p_key='cle-valide-04', p_command='accept_task', p_args={'task_id': 'pas-un-uuid'}), 'mission illisible'), (dict(p_key='cle-valide-05', p_command='accept_task', p_args=R("'[1]'::jsonb")), 'arguments qui ne sont pas un objet')):
            fr('lg_mobile_command', 'LG005', 'refusé : %s' % msg, drv_u, **kw)
        ok(n_("select count(*) from logistics.command_log where idempotency_key like 'mobile:%'") == 0, 'aucun refus n\'a consommé de clé')
        # accepter, rejouer dix fois
        hist = lambda: n_("select count(*) from logistics.task_status_history where task_id = '%s'" % t1)   # noqa: E731
        r1 = cmd(drv_u, 'tel1-0001', 'accept_task', {'task_id': t1})
        h1 = hist()
        ok(q("select status from logistics.task where id = '%s'" % t1) == 'ACCEPTED' and r1['command'] == 'accept_task', 'accepter : la mission est acceptée')
        for _ in range(10):
            rr = cmd(drv_u, 'tel1-0001', 'accept_task', {'task_id': t1})
        ok(rr.get('replayed') is True and rr['command'] == 'accept_task' and hist() == h1, 'rejouée dix fois (réseau capricieux) : le résultat d\'origine, rien de refait')
        fr('lg_mobile_command', 'LG006', 'la même clé pour une AUTRE action', drv_u, p_key='tel1-0001', p_command='start_task', p_args={'task_id': t1})
        # la clé d'un autre téléphone, d'un autre membre : une autre clé
        code, t_ = cl.run(B, appel('lg_mobile_command', p_key='tel1-0001', p_command='scan_parcel', p_args={'code': 'N-001', 'purpose': 'lookup', 'warehouse_id': wmia}), role='authenticated', claims=ent, expect_error=True)
        ok(code == 0 and json.loads(t_).get('replayed') is not True and json.loads(t_)['command'] == 'scan_parcel', 'la même clé chez un autre membre de l\'équipe : sa propre action, rien de celle du chauffeur')
        cmd(drv_u, 'tel1-0002', 'start_task', {'task_id': t1})
        ok(q("select status from logistics.task where id = '%s'" % t1) == 'STARTED', 'commencer')
        # une action refusée ne consomme pas sa clé
        f('lg_issue_delivery_otp', hub_u, p_task_id=t1)
        otp = q("select payload ->> 'code' from logistics.notification where template = 'DeliveryOtp' and payload ? 'code' order by id desc limit 1")
        mauvais = '000000' if otp != '000000' else '111111'
        # un mauvais code : la base compte l'essai (contre le devinage) et répond « code invalide » — c'est un RÉSULTAT, gardé sous sa clé ;
        # le chauffeur qui ressaisit le code fait une NOUVELLE action, avec une nouvelle clé.
        preuve = {'task_id': t1, 'recipient_name': 'Marie', 'latitude': 18.5, 'longitude': -72.3, 'signature_path': 'pod/%s/s.png' % t1, 'photo_path': 'pod/%s/m1a2b3c-0000abcd.jpg' % t1}
        rm = cmd(drv_u, 'tel1-0003', 'complete_delivery', dict(preuve, otp=mauvais))
        ok(rm['completed'] is False and rm['reason'] == 'OTP_INVALID' and q("select otp_attempts from logistics.delivery where id = (select delivery_id from logistics.task where id = '%s')" % t1) == '1', 'mauvais code : refus motivé, essai compté')
        ok(cmd(drv_u, 'tel1-0003', 'complete_delivery', dict(preuve, otp=mauvais)).get('replayed') is True and q("select otp_attempts from logistics.delivery where id = (select delivery_id from logistics.task where id = '%s')" % t1) == '1',
           'la même action rejouée : même réponse, l\'essai n\'est PAS recompté')
        fr('lg_mobile_command', 'LG006', 'le bon code sous l\'ancienne clé : refusé (une clé, une action)', drv_u, p_key='tel1-0003', p_command='complete_delivery', p_args=dict(preuve, otp=otp))
        rl = cmd(drv_u, 'tel1-0003b', 'complete_delivery', dict(preuve, otp=otp))
        ok(q("select status from logistics.task where id = '%s'" % t1) == 'COMPLETED' and q("select status from logistics.parcel where id = '%s'" % p1) == 'DELIVERED', 'avec le bon code, sous une nouvelle clé : livré, preuve enregistrée')
        ok(cmd(drv_u, 'tel1-0003b', 'complete_delivery', dict(preuve, otp=otp)).get('replayed') is True, 'rejouée après coup : « déjà fait », pas une erreur')
        ok(n_("select count(*) from logistics.proof_of_delivery where task_id = '%s'" % t1) == 1, 'une seule preuve')
        ok(q("select photo_path from logistics.proof_of_delivery where task_id = '%s'" % t1) == 'pod/%s/m1a2b3c-0000abcd.jpg' % t1, 'la photo déposée par l\'application est celle de la preuve')
        # échouer, refuser
        p2, p3 = nat(ca, 'AT_DESTINATION_HUB'), nat(ca, 'AT_DESTINATION_HUB')
        t2 = f('lg_create_delivery', admin, p_parcel_ids=[p2], p_hub_branch=pap, p_scheduled_for=R('current_date'), p_address='2 rue')['task_id']
        t3 = f('lg_create_delivery', admin, p_parcel_ids=[p3], p_hub_branch=pap, p_scheduled_for=R('current_date'), p_address='3 rue')['task_id']
        for t_x in (t2, t3):
            f('lg_assign_task', admin, p_task_id=t_x, p_driver_id=drv, p_force=True, p_reason='essai')
        cmd(drv_u, 'tel1-0004', 'refuse_task', {'task_id': t2, 'reason': 'véhicule en panne'})
        ok(q("select status from logistics.task where id = '%s'" % t2) in ('CREATED', 'REFUSED') or q("select driver_id is null from logistics.task where id = '%s'" % t2) == 't', 'refuser : la mission repart vers le répartiteur')
        cmd(drv_u, 'tel1-0005', 'accept_task', {'task_id': t3}); cmd(drv_u, 'tel1-0006', 'start_task', {'task_id': t3})
        cmd(drv_u, 'tel1-0007', 'fail_task', {'task_id': t3, 'incident_type': 'CUSTOMER_ABSENT', 'description': 'personne'})
        ok(q("select status from logistics.task where id = '%s'" % t3) == 'FAILED', 'échouer (client absent)')
        # la position : jamais en arrière
        maintenant = q("select now()::text")
        avant = q("select (now() - interval '10 minutes')::text")
        ok(cmd(drv_u, 'pos-0001', 'position', {'latitude': 18.54, 'longitude': -72.33, 'recorded_at': maintenant})['applied'] is True, 'position récente : enregistrée')
        ok(cmd(drv_u, 'pos-0002', 'position', {'latitude': 10, 'longitude': 10, 'recorded_at': avant})['applied'] is False, 'une position plus ancienne, rejouée après une coupure : ignorée')
        ok(q("select last_latitude::text from logistics.driver where id = '%s'" % drv) == '18.540000', 'la dernière position connue reste la plus récente')
        for args, msg in (({'latitude': 1, 'longitude': 1, 'recorded_at': q("select (now() + interval '1 hour')::text")}, 'une heure dans le futur'),
                          ({'latitude': 1, 'longitude': 1, 'recorded_at': q("select (now() - interval '2 days')::text")}, 'plus de 24 h'),
                          ({'latitude': 91, 'longitude': 1, 'recorded_at': maintenant}, 'latitude impossible'), ({'latitude': 1, 'longitude': 1}, 'sans heure'), ({'latitude': 'x', 'longitude': 1, 'recorded_at': maintenant}, 'illisible')):
            fr('lg_mobile_command', 'LG005', 'position refusée : %s' % msg, drv_u, p_key='pos-x%04d' % len(msg), p_command='position', p_args=args)
        fr('lg_mobile_command', 'LG003', 'position d\'un membre qui n\'est pas chauffeur', ent, p_key='pos-ent-001', p_command='position', p_args={'latitude': 1, 'longitude': 1, 'recorded_at': maintenant})
        fr('lg_mobile_command', 'LG003', 'un chauffeur ne fait pas les scans d\'entrepôt', drv_u, p_key='scan-drv-01', p_command='scan_parcel', p_args={'code': 'N-001', 'purpose': 'receive', 'warehouse_id': wmia})
        # l'entrepôt : scanner, signaler
        p4 = nat(ca, 'CREATED')
        n_scans = n_("select count(*) from logistics.scan")
        rs = cmd(ent, 'ent1-0001', 'scan_parcel', {'code': 'n-%03d' % n_p[0], 'purpose': 'receive', 'warehouse_id': wmia, 'code_kind': 'barcode', 'recorded_at': maintenant})
        ok(rs.get('result') == 'ACCEPTED' and q("select status from logistics.parcel where id = '%s'" % p4) == 'RECEIVED', 'scan de réception (numéro tapé en minuscules) : reçu à Miami')
        cmd(ent, 'ent1-0001', 'scan_parcel', {'code': 'n-%03d' % n_p[0], 'purpose': 'receive', 'warehouse_id': wmia, 'code_kind': 'barcode', 'recorded_at': maintenant})
        ok(n_("select count(*) from logistics.scan") == n_scans + 1, 'rejoué : un seul scan enregistré')
        ok(q("select metadata ->> 'source' from logistics.scan order by scanned_at desc limit 1") == 'mobile', 'le scan dit qu\'il vient de l\'application')
        ri = cmd(ent, 'ent1-0002', 'report_incident', {'type': 'DAMAGED', 'parcel_id': p4, 'description': 'carton écrasé', 'severity': 'HIGH', 'warehouse_id': wmia})
        ri2 = cmd(ent, 'ent1-0002', 'report_incident', {'type': 'DAMAGED', 'parcel_id': p4, 'description': 'carton écrasé', 'severity': 'HIGH', 'warehouse_id': wmia})
        ok(ri['incident_id'] == ri2['incident_id'] and n_("select count(*) from logistics.incident where parcel_id = '%s'" % p4) == 1, 'incident rejoué : un seul incident')
        # enlèvement
        tp = f('lg_create_pickup_task', admin, p_customer_id=ca, p_address='4 rue', p_scheduled_date=R('current_date'))['task_id']
        f('lg_assign_task', admin, p_task_id=tp, p_driver_id=drv, p_force=True, p_reason='essai')
        cmd(drv_u, 'tel1-0008', 'accept_task', {'task_id': tp}); cmd(drv_u, 'tel1-0009', 'start_task', {'task_id': tp})
        p5 = nat(ca, 'CREATED')
        cmd(drv_u, 'tel1-0010', 'complete_pickup', {'task_id': tp, 'parcel_ids': [p5]})
        ok(q("select status from logistics.task where id = '%s'" % tp) == 'COMPLETED', 'enlèvement terminé avec ses colis')
        # un chauffeur ne touche pas la mission d'un autre
        t6 = f('lg_create_delivery', admin, p_parcel_ids=[nat(ca, 'AT_DESTINATION_HUB')], p_hub_branch=pap, p_scheduled_for=R('current_date'), p_address='6 rue')['task_id']
        fr('lg_mobile_command', 'LG003', 'accepter une mission qui n\'est pas attribuée à ce chauffeur', drv_u, p_key='tel1-0011', p_command='accept_task', p_args={'task_id': t6})

        # ============================================================== D. les portes et les signatures
        portes = cl.lignes(B, "select p.proname || '|' || has_function_privilege('authenticated', p.oid, 'execute') || '|' || has_function_privilege('anon', p.oid, 'execute') || '|' || p.prosecdef || '|' || coalesce(array_to_string(p.proconfig, ','), '') "
                               "from pg_proc p join pg_namespace n on n.oid = p.pronamespace where (n.nspname = 'public' and p.proname in ('lg_my_staff_profile', 'lg_mobile_command', 'ses_peut_deposer_preuve')) "
                               "or (n.nspname = 'logistics' and p.proname in ('staff_profile', 'mobile_command')) order by 1")
        ok(len(portes) == 5, 'cinq fonctions')
        for l_ in portes:
            nom_, au_, an_, sd_, cf_ = l_.split('|')
            ok(an_ == 'false' and sd_ == 'true' and 'search_path=""' in cf_, '%s : jamais pour un visiteur ; définisseur ; chemin vidé' % nom_)
            ok(au_ == ('true' if nom_ in ('lg_my_staff_profile', 'lg_mobile_command', 'ses_peut_deposer_preuve') else 'false'), '%s : ouverte aux connectés seulement si c\'est la façade' % nom_)
        ok(f('ses_peut_deposer_preuve', drv_u) in ('t', 'true', True) and f('ses_peut_deposer_preuve', ent) in ('f', 'false', False), 'déposer une preuve : un chauffeur actif oui, un agent d\'entrepôt non')
        SIG = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), 'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) "
                           "from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname = any (array[%s])" % ','.join("'%s'" % x for x in APPLICATION)))
        ok(sorted(SIG) == sorted(APPLICATION), 'les huit fonctions que l\'application appelle existent')
        CH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'applications-rpc.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(SIG, open(CH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        ok(json.load(open(CH, encoding='utf-8')) == json.loads(json.dumps(SIG)), 'les signatures sont celles du fichier partagé avec l\'application (sinon : SES_FORME_ECRIRE=1, et recopier dans App_SES/tests/rpc-noyau.json)')

        # ============================================================== E. les FORMES de ce que l'application lit — ses types TypeScript s'y comparent
        # (App_SES/tests/contrat-rpc.cjs) : un champ renommé ici fait échouer l'application avant qu'un chauffeur voie un écran vide.
        f('lg_assign_task', admin, p_task_id=t6, p_driver_id=drv, p_force=True, p_reason='essai')
        q("update logistics.task set window_start = now(), window_end = now() + interval '2 hours' where id = '%s'" % t6)

        def forme(x):
            """Les clés de premier niveau d'un objet (ou du premier élément d'une liste), et celles de ses listes d'objets (« parcels[].x »)."""
            o = x[0] if isinstance(x, list) else x
            s = set()
            for k_, v_ in o.items():
                s.add(k_)
                if isinstance(v_, list) and v_ and isinstance(v_[0], dict):
                    s.update('%s[].%s' % (k_, k2) for k2 in v_[0])
                elif isinstance(v_, dict):
                    s.update('%s.%s' % (k_, k2) for k2 in v_)
            return sorted(s)
        missions = f('lg_my_tasks', drv_u, p_date=R('current_date'))
        ok(len(missions) == 1 and missions[0]['task_id'] == t6 and missions[0]['parcels'], 'la mission du chauffeur, avec ses colis')
        tableau = f('lg_task_board', hub_u, p_date=R('current_date'))
        code, sortie = cl.run(B, "select jsonb_agg(r) from public.lg_rank_drivers('%s') r" % t6, role='authenticated', claims=hub_u)
        classes = json.loads(sortie)
        profil_d = f('lg_my_staff_profile', drv_u)
        profil_e = f('lg_my_staff_profile', ent)
        # les arguments que la porte mobile LIT vraiment (a ->> 'x'), relus dans la fonction installée
        corps = '\n'.join(cl.lignes(B, "select pg_get_functiondef('logistics.mobile_command(uuid,text,text,jsonb)'::regprocedure)"))
        lus = sorted(set(re.findall(r"a ->>? '([a-z_]+)'", corps)))
        ok({'task_id', 'recipient_name', 'otp', 'photo_path', 'code', 'purpose', 'warehouse_id', 'latitude', 'recorded_at'} <= set(lus), 'la porte lit les arguments attendus')
        FORMES = {'lg_my_tasks': forme(missions), 'lg_task_board': forme(tableau), 'lg_rank_drivers': forme(classes),
                  'lg_my_staff_profile': sorted(set(forme(profil_d)) | set(forme(profil_e))), 'scan_parcel': forme(rs), 'mobile_args': lus,
                  # les actions admises par la porte, les intentions admises par la table des scans : relues dans la base installée
                  'fail_types': sorted(re.findall(r"'([A-Z_]+)'", re.search(r"p_incident_type not in \(([^)]*)\)", '\n'.join(cl.lignes(B, "select string_agg(pg_get_functiondef(p.oid), chr(10)) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and p.proname = 'fail_task'"))).group(1))),
                  'scan_results': sorted(re.findall(r"'([A-Z_]+)'", re.search(r"result = ANY \(ARRAY\[([^\]]*)\]", '\n'.join(cl.lignes(B, "select pg_get_constraintdef(c.oid) from pg_constraint c where c.conrelid = 'logistics.scan'::regclass and c.contype = 'c'"))).group(1))),
                  'task_statuses': sorted(cl.lignes(B, "select code from logistics.task_status")),
                  'mobile_commands': sorted(re.findall(r"'([a-z_]+)'", re.search(r"p_command not in \(([^)]*)\)", corps).group(1))),
                  'scan_purposes': sorted(re.findall(r"'([a-z]+)'", re.search(r"purpose = ANY \(ARRAY\[([^\]]*)\]", '\n'.join(cl.lignes(B, "select pg_get_constraintdef(c.oid) from pg_constraint c where c.conrelid = 'logistics.scan'::regclass and c.contype = 'c'"))).group(1)))}
        # le poste de scan du bureau (assets/js/ses-api.js, « poste ») appelle deux fonctions : leurs signatures, pour outils/tests/poste-contrat.cjs
        SIGP = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), 'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) "
                            "from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname in ('lg_my_staff_profile', 'lg_scan_parcel')"))
        ok(sorted(SIGP) == ['lg_my_staff_profile', 'lg_scan_parcel'], 'les deux fonctions du poste de scan existent')
        CP = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'poste-rpc.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(SIGP, open(CP, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        ok(json.load(open(CP, encoding='utf-8')) == json.loads(json.dumps(SIGP)), 'les signatures du poste sont celles du fichier partagé (sinon : SES_FORME_ECRIRE=1)')
        CF = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'applications-formes.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(FORMES, open(CF, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        ok(json.load(open(CF, encoding='utf-8')) == FORMES, 'les formes sont celles du fichier partagé avec l\'application (sinon : SES_FORME_ECRIRE=1, et recopier dans App_SES/tests/formes-noyau.json)')
    print('%d vérifications — phase 14 (applications mobiles, côté base) : OK' % N[0])


if __name__ == '__main__':
    main()
