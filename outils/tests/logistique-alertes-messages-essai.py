#!/usr/bin/env python3
"""Étape 035 — les alertes d'un nouveau message, éprouvées sur la RÉPLIQUE DE LA PRODUCTION (001 → 035, recopie allumée, canaux push et
e-mail allumés comme ils le seront quand le travailleur d'envoi sera installé).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-alertes-messages-essai.py
    SES_FORME_ECRIRE=1 …   réécrit alertes-messages-exemples.json (à recopier dans App_SES/tests/exemples-alertes.json)

 A. le client, quand l'équipe lui écrit : téléphone et e-mail, dans sa langue, le prénom de qui écrit et le début du message ; pas une
    alerte par ligne (dix minutes) ; rien quand c'est lui qui écrit ;
 B. l'équipe, sur son téléphone : qui lit les clients pour un client, les membres pour un direct ou un groupe ; jamais l'auteur, jamais
    sans téléphone enregistré, jamais qui ne lit pas les clients ; dix minutes ;
 C. les téléphones de l'équipe : enregistrer (un client ne le peut pas, un jeton illisible est refusé), reprendre un téléphone qui était à
    un client, retirer ;
 D. le travailleur : il trouve les téléphones d'un membre de l'équipe, et le lien d'une alerte ouvre la bonne messagerie ;
 E. une alerte ne bloque jamais un message (sans modèle actif : le message part, sans alerte) ;
 F. tout fermé, 035 rejouée sans effet, rattrapage prêt ; le fichier partagé avec l'application.
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
    return "'%s'" % str(v).replace("'", "''")


def main():
    with P.Cluster() as cl:
        B = 'prod'
        if not P.monter_production(cl, B):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('035-alertes-messages.sql' in etapes, 'l\'étape 035 est dans le noyau')
        for f_ in etapes:
            cl.run(B, P.lire_sql('outils/logistique/' + f_))
        cl.run(B, P.lire_sql('outils/logistique/035-alertes-messages.sql'))
        ok(True, '035 chargée deux fois de suite')
        q = lambda sql: cl.un(B, sql)   # noqa: E731
        rapport = lambda: json.loads(q("select logistics.run_migration('alertes')"))['report']   # noqa: E731
        ok(rapport()['ready'] is True, 'rattrapage prêt')
        q('select logistics.set_double_write(true)')
        q("update logistics.notification_channel set enabled = true where code in ('push', 'email')")

        def employe(n, email, nom, droits):
            q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
              "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0035-00000000000%d', 'authenticated', 'authenticated', '%s', 'x', now(), '{}')" % (n, email))
            q("update public.clients set role = 'employe', code = null, nom_complet = '%s', droits = array[%s]::text[] where email = '%s'"
              % (nom, ', '.join("'%s'" % d for d in droits), email))
            return q("select id from public.clients where email = '%s'" % email)
        emp_b = employe(1, 'al-b@essai.test', 'Rose Michel', ['colis.lire', 'clients.lire'])
        emp_c = employe(2, 'al-c@essai.test', 'Jean Baptiste', ['colis.lire'])
        rapport()
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        ca, ka = cl.lignes(B, "select c.id || '|' || k.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id "
                              "where c.role = 'client' and k.auth_user_id = c.id and coalesce(k.email, '') <> '' order by c.email limit 1")[0].split('|')

        def appel(nom, acteur, kw):
            return cl.run(B, 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items())), role='authenticated', claims=acteur, expect_error=True)

        def f(nom, acteur, **kw):
            code, sortie = appel(nom, acteur, kw)
            if code != 0:
                raise AssertionError('%s refusée : %s' % (nom, sortie[-400:]))
            return json.loads(sortie)

        def refus(nom, code_attendu, msg, acteur, **kw):
            code, sortie = appel(nom, acteur, kw)
            ok(code != 0 and code_attendu in sortie, '%s : attendu %s, obtenu %s' % (msg, code_attendu, sortie[-220:]))

        cle = iter('cle-%04d-alerte' % i for i in range(1, 9999))
        notifs = lambda cond: int(q("select count(*) from logistics.notification where template like 'ChatMessage%%' and " + cond))   # noqa: E731

        # le téléphone de la cliente (application client) et ceux de l'équipe (SES Opérations)
        f('lg_register_device', ca, p_token='ExponentPushToken[client-alerte-01]', p_platform='android')
        refus('lg_register_staff_device', 'LG003', 'un client n\'enregistre pas un téléphone de l\'équipe', ca, p_token='ExponentPushToken[client-alerte-02]', p_platform='android')
        refus('lg_register_staff_device', 'LG005', 'un jeton illisible', emp_b, p_token='n importe quoi', p_platform='android')
        reg = f('lg_register_staff_device', emp_b, p_token='ExponentPushToken[equipe-rose-01]', p_platform='ios')
        ok(reg['registered'] is True and q("select kind || '|' || (owner_user_id is not null)::text || '|' || (owner_customer_id is null)::text from logistics.device "
                                         "where push_token = 'ExponentPushToken[equipe-rose-01]'") == 'staff_push|true|true', 'le téléphone de Rose est celui d\'un membre de l\'équipe')
        f('lg_register_staff_device', admin, p_token='ExponentPushToken[equipe-dir-01]', p_platform='android')

        # ============================================================ A. le client, quand l'équipe lui écrit
        conv = f('lg_chat_open_customer', ca)['conversation_id']
        f('lg_chat_send', emp_b, p_conversation_id=conv, p_body='Votre colis   part demain.\nBonne journée', p_client_key=next(cle))
        ok(notifs("customer_id = '%s' and channel = 'push'" % ka) == 1 and notifs("customer_id = '%s' and channel = 'email'" % ka) == 1,
           'la cliente reçoit une alerte sur son téléphone et une par e-mail')
        corps = q("select body from logistics.notification where customer_id = '%s' and channel = 'push' and template = 'ChatMessage'" % ka)
        ok('Rose : Votre colis part demain. Bonne journée' in corps and 'Michel' not in corps, 'le prénom de qui écrit, le début du message, sans retour à la ligne : %s' % corps)
        ok(q("select recipient from logistics.notification where customer_id = '%s' and channel = 'email' and template = 'ChatMessage'" % ka) != '', 'son destinataire est figé')
        f('lg_chat_send', emp_b, p_conversation_id=conv, p_body='Et une seconde ligne', p_client_key=next(cle))
        ok(notifs("customer_id = '%s'" % ka) == 2, 'une seconde ligne dans les dix minutes : pas de nouvelle alerte')
        q("update logistics.notification set created_at = now() - interval '11 minutes' where customer_id = '%s' and template = 'ChatMessage'" % ka)
        f('lg_chat_send', emp_b, p_conversation_id=conv, p_body='Dix minutes plus tard', p_client_key=next(cle))
        ok(notifs("customer_id = '%s'" % ka) == 4, 'dix minutes plus tard : une nouvelle alerte (téléphone et e-mail)')

        # ============================================================ B. l'équipe, sur son téléphone
        ok(notifs('recipient_user_id is not null') == 0, 'quand un employé répond à un client, ses collègues ne sont pas alertés')
        avant = notifs('recipient_user_id is not null')
        f('lg_chat_send', ca, p_conversation_id=conv, p_body='Merci beaucoup !', p_client_key=next(cle))
        dest = set(cl.lignes(B, "select recipient_user_id from logistics.notification where template = 'ChatMessageStaff' and conversation_id = '%s'" % conv))
        ok(dest == {emp_b, admin}, 'la cliente écrit : Rose et la direction (téléphones enregistrés, lisent les clients) — pas Jean : %s' % dest)
        ok(q("select body from logistics.notification where recipient_user_id = '%s' and template = 'ChatMessageStaff'" % emp_b).endswith(': Merci beaucoup !'),
           'le nom de la cliente et son message')
        f('lg_chat_send', ca, p_conversation_id=conv, p_body='Encore merci', p_client_key=next(cle))
        ok(notifs('recipient_user_id is not null') == avant + 2, 'dix minutes : pas une alerte par ligne (%s)' % cl.lignes(B, "select recipient_user_id || ' ' || template || ' ' || created_at from logistics.notification where recipient_user_id is not null"))
        d1 = f('lg_chat_open_direct', emp_c, p_user_id=emp_b)['conversation_id']
        f('lg_chat_send', emp_c, p_conversation_id=d1, p_body='Le camion est chargé', p_client_key=next(cle))
        ok(notifs("recipient_user_id = '%s' and conversation_id = '%s'" % (emp_b, d1)) == 1 and notifs("recipient_user_id = '%s'" % emp_c) == 0,
           'un direct : le destinataire, jamais l\'auteur')
        f('lg_chat_send', emp_b, p_conversation_id=d1, p_body='Reçu', p_client_key=next(cle))
        ok(notifs("recipient_user_id = '%s'" % emp_c) == 0, 'sans téléphone enregistré : aucune alerte')
        g = f('lg_chat_create_group', admin, p_title='Entrepôt Miami', p_member_ids=R("array['%s', '%s']::uuid[]" % (emp_b, emp_c)))['conversation_id']
        f('lg_chat_send', admin, p_conversation_id=g, p_body='Inventaire à 14 h', p_client_key=next(cle))
        ok(q("select body from logistics.notification where recipient_user_id = '%s' and conversation_id = '%s'" % (emp_b, g)).find('(Entrepôt Miami)') > 0,
           'un groupe : son nom dans l\'alerte')
        ok(q("select language from logistics.notification where recipient_user_id = '%s' and conversation_id = '%s'" % (emp_b, g)) == 'fr', 'dans la langue du membre')

        # ============================================================ C. reprendre un téléphone, le retirer
        f('lg_register_staff_device', emp_c, p_token='ExponentPushToken[client-alerte-01]', p_platform='android')
        ok(q("select coalesce(owner_customer_id::text, 'aucun') || '|' || owner_user_id from logistics.device where push_token = 'ExponentPushToken[client-alerte-01]'")
           == 'aucun|' + emp_c, 'un téléphone passé de la cliente à Jean ne reçoit plus que pour Jean')
        ok(f('lg_unregister_staff_device', emp_c, p_token='ExponentPushToken[client-alerte-01]')['unregistered'] is True, 'retirer son téléphone')
        ok(f('lg_unregister_staff_device', emp_b, p_token='ExponentPushToken[equipe-dir-01]')['unregistered'] is False, 'on ne retire pas le téléphone d\'un autre')

        # ============================================================ D. le travailleur
        lot = cl.lignes(B, "select notification_id || '|' || coalesce(recipient::text, '') || '|' || template from logistics.nt_claim('essai', array['push'], 200)")
        staff = [x for x in lot if x.endswith('|ChatMessageStaff')]
        ok(staff and all('ExponentPushToken[equipe-' in x for x in staff), 'le travailleur trouve les téléphones des membres de l\'équipe')
        # (le téléphone de la cliente a été repris puis retiré plus haut : le travailleur saute son alerte ; le lien se lit quand même)
        ids = cl.lignes(B, "select id from logistics.notification where template like 'ChatMessage%%' and channel = 'push'")
        donnees = json.loads(q("select logistics.nt_push_data(array[%s]::bigint[])" % ','.join(ids)))
        urls = {v['template']: v['url'] for v in donnees.values()}
        ok(urls.get('ChatMessage') == 'speedexpress://messages' and urls.get('ChatMessageStaff', '').startswith('speedexpressops://conversation/'),
           'le lien de l\'alerte ouvre la messagerie de la bonne application : %s' % urls)

        # ============================================================ E. une alerte ne bloque jamais un message
        q("update logistics.notification_template set active = false where code like 'ChatMessage%'")
        q("update logistics.notification set created_at = now() - interval '11 minutes' where template like 'ChatMessage%'")
        n0 = notifs('true')
        envoi = f('lg_chat_send', emp_b, p_conversation_id=conv, p_body='Sans modèle', p_client_key=next(cle))
        ok(envoi['message_id'] and notifs('true') == n0, 'sans modèle actif : le message part, sans alerte')
        q("update logistics.notification_template set active = true where code like 'ChatMessage%'")
        q("update logistics.notification_channel set enabled = false where code in ('push', 'email')")
        f('lg_chat_send', emp_b, p_conversation_id=conv, p_body='Canaux éteints', p_client_key=next(cle))
        ok(notifs('true') == n0, 'canaux éteints (travailleur pas installé) : aucune alerte, le message part')

        # ============================================================ F. tout fermé, rejeu, rattrapage, fichier partagé
        n_dev = q('select count(*) from logistics.device')
        cl.run(B, P.lire_sql('outils/logistique/035-alertes-messages.sql'))
        ok(q('select count(*) from logistics.device') == n_dev and notifs('true') == n0, '035 rejouée : rien ne change')
        ok(q("select count(*) from logistics.notification_template where code like 'ChatMessage%'") == '8', 'deux modèles, quatre langues')
        code, sortie = cl.run(B, "select public.lg_register_staff_device('x', 'ios')", role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in sortie, 'un visiteur : rien')
        for fn in ('logistics.chat_alert(bigint)', 'logistics.register_staff_device(uuid,text,text)', 'logistics.nt_claim(text,text[],integer,integer)'):
            ok(q("select has_function_privilege('authenticated', '%s', 'execute')::text || has_function_privilege('anon', '%s', 'execute')::text" % (fn, fn)) == 'falsefalse',
               '%s : jamais appelée en direct' % fn)
        q('select logistics.process_sync_queue()')
        r = rapport()
        ok(r['ready'] is True and r['unexplained'] == 0, 'rattrapage prêt, zéro écart inexpliqué : %s' % r.get('unexplained_by_entity'))
        ICI = os.path.dirname(os.path.abspath(__file__))
        SIG = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), "
                           "'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) "
                           "from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname in ('lg_register_staff_device', 'lg_unregister_staff_device')"))
        EX = {'signatures': SIG, 'enregistrement': reg, 'urls': urls}
        ch = os.path.join(ICI, 'alertes-messages-exemples.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(EX, open(ch, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        lus = json.load(open(ch, encoding='utf-8'))
        ok(lus['signatures'] == json.loads(json.dumps(SIG)) and lus['urls'] == urls, 'signatures et liens = fichier partagé avec l\'application (sinon : SES_FORME_ECRIRE=1)')
    print('%d vérifications — étape 035 (alertes d\'un nouveau message) : OK' % N[0])


if __name__ == '__main__':
    try:
        sys.exit(main())
    except AssertionError as e:
        print('ÉCHEC alertes d\'un nouveau message (après %d vérifications) : %s' % (N[0], e))
        sys.exit(1)
