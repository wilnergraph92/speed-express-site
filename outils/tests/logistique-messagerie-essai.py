#!/usr/bin/env python3
"""Étape 032 — la messagerie, éprouvée sur la RÉPLIQUE DE LA PRODUCTION (001 → 032, recopie allumée), avec un stockage de Supabase réduit
à l'essentiel (le dossier privé « messagerie » et ses règles).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-messagerie-essai.py

Demande du propriétaire : un chat interne entre le tableau de bord et les deux applications, et un chat direct avec le client ; messages
directs, groupes, colis cités, photos. Ce que l'essai prouve, dans l'ordre :
 A. rien ne se lit en direct : tables fermées, façades seulement ;
 B. le client : SA conversation (une seule), qu'il ouvre et où il écrit ; il ne voit que le prénom de qui lui répond, jamais l'équipe ni
    une conversation interne ; il ne cite que ses colis ;
 C. l'équipe qui lit les clients : la boîte partagée, les non-lus, la réponse ; dans la conversation d'un client, seuls les colis de CE client ;
 D. un membre qui ne lit pas les clients : ni leurs conversations, ni l'annuaire des clients ;
 E. les messages directs : une conversation par paire, privée (même la direction ne la lit pas) ;
 F. les groupes : la direction les crée, ajoute, retire (l'historique reste), archive (on lit, on n'écrit plus) ;
 G. un envoi rejoué ne fait qu'un message ; message vide, trop long, clé invalide : refusés ;
 H. les photos : déposées et lues seulement par ceux qui lisent la conversation, dans SON dossier, par celui qui l'envoie ;
 I. le signal temps réel : une ligne par destinataire, sans donnée, chacun ne lit que les siens ;
 J. ajout seul, débit limité, module « Messagerie » ouvert à toute l'équipe, pagination ;
 K. rattrapage prêt, rejeu sans effet, portes ; le fichier partagé avec le site et les applications (signatures et réponses réelles).
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


# Le stockage de Supabase, réduit à ce que les règles de 011 et 032 touchent.
STOCKAGE = """
create schema if not exists storage;
create table if not exists storage.buckets (id text primary key, name text not null, public boolean default false, file_size_limit bigint, allowed_mime_types text[]);
create table if not exists storage.objects (id uuid primary key default gen_random_uuid(), bucket_id text references storage.buckets (id), name text not null,
                                            owner uuid, owner_id text default (nullif(current_setting('request.jwt.claim.sub', true), '')), created_at timestamptz default now(),
                                            unique (bucket_id, name));
create or replace function storage.foldername(name text) returns text[] language sql immutable as $$
  select (string_to_array(name, '/'))[1:greatest(array_length(string_to_array(name, '/'), 1) - 1, 0)] $$;
alter table storage.objects enable row level security;
grant usage on schema storage to authenticated;
grant select, insert on storage.objects to authenticated;
"""


def main():
    with P.Cluster() as cl:
        B = 'prod'
        if not P.monter_production(cl, B):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        cl.run(B, STOCKAGE)
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('032-messagerie.sql' in etapes, 'l\'étape 032 est dans le noyau')
        for f_ in etapes:
            cl.run(B, P.lire_sql('outils/logistique/' + f_))
        cl.run(B, P.lire_sql('outils/logistique/032-messagerie.sql'))
        ok(True, '032 chargée deux fois de suite')
        q = lambda sql: cl.un(B, sql)   # noqa: E731
        rapport = lambda: json.loads(q("select logistics.run_migration('messagerie')"))['report']   # noqa: E731
        ok(rapport()['ready'] is True, 'rattrapage prêt')
        q('select logistics.set_double_write(true)')

        # le décor : deux employés (l'un lit les clients, l'autre non), la direction, deux clientes avec un compte
        def employe(n, email, droits):
            q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
              "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0032-00000000000%d', 'authenticated', 'authenticated', '%s', 'x', now(), '{}')" % (n, email))
            q("update public.clients set role = 'employe', code = null, nom_complet = '%s', droits = array[%s]::text[] where email = '%s'"
              % ({1: 'Rose Michel', 2: 'Jean Baptiste'}[n], ', '.join("'%s'" % d for d in droits), email))
            return q("select id from public.clients where email = '%s'" % email)
        emp_b = employe(1, 'chat-b@essai.test', ['colis.lire', 'clients.lire'])
        emp_c = employe(2, 'chat-c@essai.test', ['colis.lire', 'colis.statut'])
        rapport()
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        clientes = cl.lignes(B, "select c.id || '|' || k.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id "
                                "where c.role = 'client' and k.auth_user_id = c.id order by c.email limit 2")
        (ca, ka), (cb, kb) = [x.split('|') for x in clientes]
        ok(q("select count(*) from logistics.app_user where id in ('%s', '%s')" % (emp_b, emp_c)) == '2', 'les deux employés sont dans le noyau')

        def colis(client, desc):
            cid = q("insert into public.colis (client_id, description, poids_lb, tarif_lb, service, pays_destination, ville_destination) "
                    "values ('%s', '%s', 2, 3, 'aerien', 'HT', 'Delmas') returning id" % (client, desc))
            q('select logistics.process_sync_queue()')
            return q("select numero from public.colis where id = '%s'" % cid)
        num_a, num_b = colis(ca, 'Robe'), colis(cb, 'Téléphone')

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

        cle = iter('cle-%04d-essai' % i for i in range(1, 9999))

        # ============================================================ A. rien ne se lit en direct
        for t in ('chat_conversation', 'chat_member', 'chat_message', 'chat_read'):
            code, sortie = cl.run(B, 'select count(*) from logistics.%s' % t, role='authenticated', claims=admin, expect_error=True)
            ok(code != 0 and 'permission denied' in sortie, 'logistics.%s : fermée, même à la direction' % t)
            ok(q("select relrowsecurity::text from pg_class where oid = 'logistics.%s'::regclass" % t) == 'true', 'logistics.%s : sécurité des lignes' % t)

        # ============================================================ B. le client : SA conversation
        o1 = f('lg_chat_open_customer', ca)
        o2 = f('lg_chat_open_customer', ca)
        conv_a = o1['conversation_id']
        ok(conv_a and o2['conversation_id'] == conv_a, 'la cliente ouvre SA conversation, toujours la même')
        refus('lg_chat_open_customer', 'LG003', 'une cliente n\'ouvre pas la conversation d\'une autre', ca, p_customer_id=kb)
        refus('lg_chat_directory', 'LG003', 'une cliente ne voit pas l\'annuaire de l\'équipe', ca)
        refus('lg_chat_open_direct', 'LG003', 'une cliente n\'écrit pas à un membre en direct', ca, p_user_id=emp_b)
        refus('lg_chat_create_group', 'LG003', 'une cliente ne crée pas de groupe', ca, p_title='Clientes', p_member_ids=[emp_b])
        m1 = f('lg_chat_send', ca, p_conversation_id=conv_a, p_body='Bonjour, où est ma robe ?', p_client_key=next(cle), p_parcel=num_a)
        ok(m1['message_id'] and m1['replayed'] is False, 'la cliente écrit, en citant son colis')
        refus('lg_chat_send', 'LG003', 'une cliente ne cite pas le colis d\'une autre', ca, p_conversation_id=conv_a, p_body='Et celui-ci ?', p_client_key=next(cle), p_parcel=num_b)
        refus('lg_chat_send', 'LG002', 'un numéro inconnu', ca, p_conversation_id=conv_a, p_body='?', p_client_key=next(cle), p_parcel='SES-0000000000')
        inbox_ca = f('lg_chat_inbox', ca)
        ok(inbox_ca['me']['kind'] == 'CUSTOMER' and len(inbox_ca['items']) == 1 and inbox_ca['items'][0]['title'] == 'Speed Express'
           and inbox_ca['items'][0]['customer'] is None and inbox_ca['can'] == {'direct': False, 'groups': False, 'customers': False},
           'la boîte de la cliente : une conversation, « Speed Express », aucun droit d\'équipe')
        conv_b = f('lg_chat_open_customer', cb)['conversation_id']
        refus('lg_chat_messages', 'LG002', 'une cliente ne lit pas la conversation d\'une autre', cb, p_conversation_id=conv_a)
        refus('lg_chat_send', 'LG002', 'ni n\'y écrit', cb, p_conversation_id=conv_a, p_body='Coucou', p_client_key=next(cle))

        # ============================================================ C. l'équipe qui lit les clients
        inbox_b = f('lg_chat_inbox', emp_b)
        it = [x for x in inbox_b['items'] if x['conversation_id'] == conv_a]
        ok(it and it[0]['kind'] == 'CUSTOMER' and it[0]['unread'] == 1 and it[0]['customer']['customer_id'] == ka and it[0]['last']['parcel'] == num_a,
           'la boîte partagée : la conversation de la cliente, un non-lu, son colis cité')
        ok(not any(x['conversation_id'] == conv_b for x in inbox_b['items']), 'une conversation de client encore vide n\'encombre pas la boîte')
        ok(inbox_b['can']['customers'] is True and inbox_b['can']['groups'] is False and inbox_b['unread'] >= 1, 'ses droits : les clients, pas les groupes')
        lus = f('lg_chat_messages', emp_b, p_conversation_id=conv_a)
        ok(lus['conversation']['customer']['customer_id'] == ka and lus['items'][0]['author']['kind'] == 'CUSTOMER' and lus['items'][0]['parcel']['tracking_number'] == num_a,
           'il lit le message, avec le client et le colis')
        f('lg_chat_mark_read', emp_b, p_conversation_id=conv_a, p_message_id=m1['message_id'])
        ok(f('lg_chat_unread', emp_b)['unread'] == 0, 'lu : plus de non-lu pour lui')
        ok([x for x in f('lg_chat_inbox', admin)['items'] if x['conversation_id'] == conv_a][0]['unread'] == 1, 'la direction, elle, ne l\'a pas encore lu (chacun le sien)')
        rep = f('lg_chat_send', emp_b, p_conversation_id=conv_a, p_body='Elle part demain, Madame.', p_client_key=next(cle), p_parcel=num_a)
        refus('lg_chat_send', 'LG003', 'dans la conversation d\'une cliente, l\'équipe ne cite pas le colis d\'une autre', emp_b,
              p_conversation_id=conv_a, p_body='Voyez aussi', p_client_key=next(cle), p_parcel=num_b)
        vu = f('lg_chat_messages', ca, p_conversation_id=conv_a)
        derniere = vu['items'][-1]
        ok(derniere['author'] == {'kind': 'STAFF', 'name': 'Rose'} and derniere['mine'] is False and derniere['parcel']['tracking_number'] == num_a,
           'la cliente voit la réponse : le prénom seulement, et son colis')
        ok(vu['conversation']['members'] is None and vu['conversation']['customer'] is None and vu['unread'] == 1,
           'la cliente ne voit ni l\'équipe, ni sa propre fiche ; un non-lu')
        ok(f('lg_chat_unread', ca)['unread'] == 1, 'sa pastille : 1')
        f('lg_chat_mark_read', ca, p_conversation_id=conv_a, p_message_id=rep['message_id'])
        ok(f('lg_chat_unread', ca)['unread'] == 0, 'lu : sa pastille s\'éteint')
        ok(f('lg_chat_mark_read', ca, p_conversation_id=conv_a, p_message_id=10 ** 12)['last_read_id'] == rep['message_id'],
           'on ne « lit » jamais plus loin que le dernier message qui existe')
        f('lg_chat_open_customer', emp_b, p_customer_id=kb)
        ok(f('lg_chat_open_customer', emp_b, p_customer_id=kb)['conversation_id'] == conv_b, 'l\'équipe ouvre la conversation d\'un client : la même que la sienne')
        rep_b = f('lg_chat_directory', emp_b, p_search=q("select substr(full_name, 1, 4) from logistics.customer where id = '%s'" % kb))
        ok(any(x['customer_id'] == kb for x in rep_b['customers']),
           'l\'annuaire propose les clients qui ont un compte, à qui lit les clients')
        equipe = f('lg_chat_directory', emp_b)
        ok(all(x['user_id'] != emp_b for x in equipe['staff']) and any(x['user_id'] == emp_c and x['name'] == 'Jean Baptiste' for x in equipe['staff']) and equipe['customers'] == [],
           'et l\'équipe, nom compris, sans soi-même')

        # ============================================================ D. un membre qui ne lit pas les clients
        ok(not any(x['kind'] == 'CUSTOMER' for x in f('lg_chat_inbox', emp_c)['items']), 'sans « clients.lire » : aucune conversation de client')
        refus('lg_chat_messages', 'LG002', 'ni la lire', emp_c, p_conversation_id=conv_a)
        refus('lg_chat_open_customer', 'LG003', 'ni l\'ouvrir', emp_c, p_customer_id=ka)
        ok(f('lg_chat_directory', emp_c, p_search='ab')['customers'] == [], 'ni l\'annuaire des clients')

        # ============================================================ E. les messages directs
        d1 = f('lg_chat_open_direct', emp_c, p_user_id=emp_b)['conversation_id']
        ok(f('lg_chat_open_direct', emp_b, p_user_id=emp_c)['conversation_id'] == d1, 'une seule conversation par paire, quel que soit celui qui l\'ouvre')
        refus('lg_chat_open_direct', 'LG005', 'pas de conversation avec soi-même', emp_c, p_user_id=emp_c)
        refus('lg_chat_open_direct', 'LG005', 'pas de message direct à une cliente', emp_c, p_user_id=ca)
        f('lg_chat_send', emp_c, p_conversation_id=d1, p_body='Le camion est chargé.', p_client_key=next(cle), p_parcel=num_b)
        ok([x for x in f('lg_chat_inbox', emp_b)['items'] if x['conversation_id'] == d1][0]['title'] == 'Jean Baptiste', 'un message direct porte le nom de l\'autre')
        refus('lg_chat_messages', 'LG002', 'un message direct est privé : la direction ne le lit pas', admin, p_conversation_id=d1)
        refus('lg_chat_messages', 'LG002', 'une cliente non plus', ca, p_conversation_id=d1)
        ok(f('lg_chat_messages', emp_b, p_conversation_id=d1)['items'][0]['parcel']['tracking_number'] == num_b, 'en interne, tout colis peut être cité')

        # ============================================================ F. les groupes
        refus('lg_chat_create_group', 'LG003', 'un employé ne crée pas de groupe', emp_b, p_title='Miami', p_member_ids=[emp_c])
        refus('lg_chat_create_group', 'LG005', 'un groupe sans nom', admin, p_title=' ', p_member_ids=[emp_c])
        refus('lg_chat_create_group', 'LG005', 'un groupe ne réunit que l\'équipe', admin, p_title='Mélange', p_member_ids=[emp_c, ca])
        g = f('lg_chat_create_group', admin, p_title='Entrepôt Miami', p_member_ids=[emp_b, emp_c])
        gid = g['conversation_id']
        ok(g['members'] == 3, 'la direction crée le groupe (elle en est)')
        f('lg_chat_send', admin, p_conversation_id=gid, p_body='Inventaire à 14 h.', p_client_key=next(cle))
        ok([x for x in f('lg_chat_inbox', emp_c)['items'] if x['conversation_id'] == gid][0]['unread'] == 1, 'chaque membre le voit, non lu')
        gm = f('lg_chat_messages', admin, p_conversation_id=gid)['conversation']
        ok(gm['can_manage'] is True and len(gm['members']) == 3 and f('lg_chat_messages', emp_b, p_conversation_id=gid)['conversation']['can_manage'] is False,
           'la direction gère, les membres non')
        refus('lg_chat_update_group', 'LG003', 'un membre ne gère pas le groupe', emp_b, p_conversation_id=gid, p_remove=[emp_c])
        u = f('lg_chat_update_group', admin, p_conversation_id=gid, p_remove=[emp_c], p_title='Entrepôt Miami (A-1)')
        ok(u['members'] == 2, 'retirer un membre')
        refus('lg_chat_messages', 'LG002', 'retiré, il ne lit plus le groupe', emp_c, p_conversation_id=gid)
        ok(q("select count(*) from logistics.chat_message where conversation_id = '%s'" % gid) == '1', 'l\'historique reste')
        f('lg_chat_update_group', admin, p_conversation_id=gid, p_add=[emp_c])
        ok(len(f('lg_chat_messages', emp_c, p_conversation_id=gid)['items']) == 1, 'ajouté de nouveau, il relit tout')
        ok(f('lg_chat_update_group', admin, p_conversation_id=gid, p_archived=True)['archived'] is True, 'archiver')
        refus('lg_chat_send', 'LG005', 'un groupe archivé ne reçoit plus de message', emp_b, p_conversation_id=gid, p_body='Encore ?', p_client_key=next(cle))
        ok(len(f('lg_chat_messages', emp_b, p_conversation_id=gid)['items']) == 1, 'mais il se lit toujours')
        f('lg_chat_update_group', admin, p_conversation_id=gid, p_archived=False)
        ok(q("select count(*) from logistics.audit_log where action like 'chat.group.%%'") == '5', 'chaque geste de la direction est au journal d\'audit')

        # ============================================================ G. rejeu et refus
        k = next(cle)
        a1 = f('lg_chat_send', emp_b, p_conversation_id=gid, p_body='Reçu.', p_client_key=k)
        a2 = f('lg_chat_send', emp_b, p_conversation_id=gid, p_body='Reçu.', p_client_key=k)
        ok(a2['message_id'] == a1['message_id'] and a2['replayed'] is True and q("select count(*) from logistics.chat_message where client_key = '%s'" % k) == '1',
           'un double appui : un seul message')
        refus('lg_chat_send', 'LG005', 'un message vide ne part pas', emp_b, p_conversation_id=gid, p_body='   ', p_client_key=next(cle))
        refus('lg_chat_send', 'LG005', 'un message trop long', emp_b, p_conversation_id=gid, p_body='x' * 4001, p_client_key=next(cle))
        refus('lg_chat_send', 'LG005', 'une clé d\'envoi invalide', emp_b, p_conversation_id=gid, p_body='Ok', p_client_key='court')

        # ============================================================ H. les photos
        ok(q("select public::text || ',' || file_size_limit || ',' || array_to_string(allowed_mime_types, ' ') from storage.buckets where id = 'messagerie'")
           == 'false,5242880,image/jpeg image/png image/webp', 'le dossier « messagerie » : privé, 5 Mo, des images')
        chemin = '%s/photo-0001-essai.jpg' % conv_a

        def deposer(acteur, nom):
            return cl.run(B, "insert into storage.objects (bucket_id, name) values ('messagerie', '%s')" % nom, role='authenticated', claims=acteur, expect_error=True)
        ok(deposer(cb, chemin)[0] != 0, 'une autre cliente ne dépose rien dans cette conversation')
        ok(deposer(emp_c, chemin)[0] != 0, 'un membre qui ne lit pas les clients non plus')
        ok(deposer(ca, '%s/../evil.jpg' % conv_a)[0] != 0 and deposer(ca, '%s/photo.exe' % conv_a)[0] != 0, 'un nom piégé ou une extension inconnue : refusés')
        refus('lg_chat_send', 'LG005', 'une photo pas encore déposée', ca, p_conversation_id=conv_a, p_body='', p_client_key=next(cle), p_photo_path=chemin)
        ok(deposer(ca, chemin)[0] == 0, 'la cliente dépose sa photo dans SA conversation')
        refus('lg_chat_send', 'LG005', 'une photo citée depuis une autre conversation', emp_b, p_conversation_id=d1, p_body='Regarde', p_client_key=next(cle), p_photo_path=chemin)
        refus('lg_chat_send', 'LG005', 'la photo d\'un autre, même dans la bonne conversation', emp_b, p_conversation_id=conv_a, p_body='', p_client_key=next(cle), p_photo_path=chemin)
        ph = f('lg_chat_send', ca, p_conversation_id=conv_a, p_body='', p_client_key=next(cle), p_photo_path=chemin)
        ok(ph['message_id'] and f('lg_chat_messages', emp_b, p_conversation_id=conv_a)['items'][-1]['photo_path'] == chemin, 'une photo seule part, et l\'équipe la voit')
        lire = lambda acteur: cl.run(B, "select count(*) from storage.objects where bucket_id = 'messagerie' and name = '%s'" % chemin, role='authenticated', claims=acteur)[1]   # noqa: E731
        ok(lire(ca) == '1' and lire(emp_b) == '1' and lire(cb) == '0' and lire(emp_c) == '0', 'la photo s\'ouvre pour la cliente et l\'équipe des clients, pour personne d\'autre')
        g_photo = '%s/photo-0002-essai.jpg' % gid
        f('lg_chat_update_group', admin, p_conversation_id=gid, p_archived=True)
        ok(deposer(emp_b, g_photo)[0] != 0, 'rien ne se dépose dans un groupe archivé')
        f('lg_chat_update_group', admin, p_conversation_id=gid, p_archived=False)

        # ============================================================ I. le signal temps réel
        avant = int(q('select coalesce(max(id), 0) from public.ses_chat_signal'))
        f('lg_chat_send', admin, p_conversation_id=gid, p_body='Signal ?', p_client_key=next(cle))
        dest = set(cl.lignes(B, 'select user_id from public.ses_chat_signal where id > %d' % avant))
        ok(dest == {admin, emp_b, emp_c}, 'un signal par membre du groupe, et à eux seuls : %s' % dest)
        avant = int(q('select coalesce(max(id), 0) from public.ses_chat_signal'))
        f('lg_chat_send', ca, p_conversation_id=conv_a, p_body='Merci !', p_client_key=next(cle))
        dest = set(cl.lignes(B, 'select user_id from public.ses_chat_signal where id > %d' % avant))
        ok(ca in dest and emp_b in dest and admin in dest and emp_c not in dest and cb not in dest, 'conversation de cliente : elle, et l\'équipe des clients')
        ok(q("select string_agg(column_name, ',' order by ordinal_position) from information_schema.columns where table_schema = 'public' and table_name = 'ses_chat_signal'")
           == 'id,user_id,created_at', 'le signal ne porte aucune donnée')
        vus = cl.run(B, 'select count(distinct user_id) from public.ses_chat_signal', role='authenticated', claims=emp_c)[1]
        ok(vus == '1', 'chacun ne lit que ses propres signaux')

        # ============================================================ J. ajout seul, débit, module, pagination
        code, sortie = cl.run(B, "update logistics.chat_message set body = 'réécrit' where conversation_id = '%s'" % conv_a, expect_error=True)
        ok(code != 0 and 'LG004' in sortie, 'un message ne se réécrit pas (LG004)')
        code, sortie = cl.run(B, "delete from logistics.chat_message where conversation_id = '%s'" % conv_a, expect_error=True)
        ok(code != 0 and 'LG004' in sortie, 'ni ne s\'efface')
        ok(q("select (ops.limit_of('chat.message'))::text || (ops.limit_of('chat.conversation'))::text || (ops.limit_of('portal.support_message'))::text || (ops.limit_of('mobile.command'))::text")
           == '{600,3600}{60,3600}{60,3600}{1200,600}', 'deux seaux de débit de plus, les anciens inchangés')
        ok(q("select count(*) from pg_trigger where tgname = 'ops_rate_limit' and tgrelid in ('logistics.chat_message'::regclass, 'logistics.chat_conversation'::regclass)") == '2',
           'le débit est limité sur les deux tables où écrivent les façades')
        q("insert into ops.rate_counter (actor, bucket, window_start, hits, max_hits) values ('%s', 'chat.message', to_timestamp(floor(extract(epoch from now()) / 3600) * 3600), 600, 600) "
          "on conflict (actor, bucket, window_start) do update set hits = 600" % emp_c)
        refus('lg_chat_send', 'LG007', 'au-delà du plafond : trop de demandes', emp_c, p_conversation_id=d1, p_body='Spam', p_client_key=next(cle))
        q("delete from ops.rate_counter where actor = '%s'" % emp_c)
        for acteur in (admin, emp_b, emp_c):
            ok('messagerie' in f('lg_dashboard_access', acteur)['modules'], 'le module « Messagerie » est ouvert à %s' % acteur)
        ok(len(f('lg_dashboard_access', admin)['modules']) == 27, 'la direction : 27 modules dans la base')
        for i in range(55):
            f('lg_chat_send', emp_c, p_conversation_id=d1, p_body='Ligne %d' % i, p_client_key=next(cle))
        p1 = f('lg_chat_messages', emp_b, p_conversation_id=d1)
        ok(len(p1['items']) == 50 and p1['has_more'] is True and p1['items'][0]['id'] < p1['items'][-1]['id'], 'cinquante à la fois, dans l\'ordre, et « plus anciens » proposés')
        p2 = f('lg_chat_messages', emp_b, p_conversation_id=d1, p_before=p1['items'][0]['id'])
        ok(len(p2['items']) == 6 and p2['has_more'] is False and p2['items'][-1]['id'] < p1['items'][0]['id'], 'puis les plus anciens, jusqu\'au premier')

        # ============================================================ K. rattrapage, rejeu, portes, fichier partagé
        q('select logistics.process_sync_queue()')
        r = rapport()
        ok(r['ready'] is True and r['unexplained'] == 0, 'rattrapage prêt, zéro écart inexpliqué : %s' % r.get('unexplained_by_entity'))
        n_msg = q('select count(*) from logistics.chat_message')
        cl.run(B, P.lire_sql('outils/logistique/032-messagerie.sql'))
        ok(q('select count(*) from logistics.chat_message') == n_msg and q("select count(*) from storage.buckets where id = 'messagerie'") == '1', '032 rejouée : rien ne change')
        code, sortie = cl.run(B, 'select public.lg_chat_inbox()', role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in sortie, 'un visiteur : rien')
        internes = cl.lignes(B, "select p.oid::regprocedure::text from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and p.proname like 'chat\\_%'")
        ok(len(internes) == 17, 'dix-sept fonctions internes : %d' % len(internes))
        for fn in internes + ['ops.limit_of(text)', 'logistics.dashboard_access(uuid)']:
            ok(q("select has_function_privilege('authenticated', '%s', 'execute')::text || has_function_privilege('anon', '%s', 'execute')::text" % (fn, fn)) == 'falsefalse',
               '%s : jamais appelée en direct' % fn)
        facades = cl.lignes(B, "select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\\_chat\\_%' order by 1")
        ok(len(facades) == 10, 'dix façades : %s' % facades)
        for fn in facades:
            ok(q("select bool_and(has_function_privilege('authenticated', p.oid, 'execute') and not has_function_privilege('anon', p.oid, 'execute'))::text from pg_proc p "
                 "join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname = '%s'" % fn) == 'true', '%s : aux comptes connectés seulement' % fn)

        ICI = os.path.dirname(os.path.abspath(__file__))
        SIG = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), "
                           "'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) "
                           "from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.proname like 'lg\\_chat\\_%'"))
        EX = {'signatures': SIG,
              'inbox_equipe': f('lg_chat_inbox', emp_b), 'inbox_client': f('lg_chat_inbox', ca), 'inbox_direction': f('lg_chat_inbox', admin),
              'messages_equipe': f('lg_chat_messages', emp_b, p_conversation_id=conv_a, p_limit=5), 'messages_client': f('lg_chat_messages', ca, p_conversation_id=conv_a, p_limit=5),
              'messages_groupe': f('lg_chat_messages', admin, p_conversation_id=gid), 'directory': equipe, 'directory_clients': rep_b, 'send': rep, 'unread': f('lg_chat_unread', emp_b),
              'open': o1, 'group_create': g, 'group_update': u, 'mark_read': f('lg_chat_mark_read', ca, p_conversation_id=conv_a, p_message_id=rep['message_id'])}
        ch = os.path.join(ICI, 'messagerie-exemples.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(EX, open(ch, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        lus = json.load(open(ch, encoding='utf-8'))
        ok(lus['signatures'] == json.loads(json.dumps(SIG)), 'les signatures sont celles du fichier partagé avec le site et les applications (sinon : SES_FORME_ECRIRE=1)')

        def forme(x):
            if isinstance(x, dict):
                return {k: forme(v) for k, v in x.items() if v is not None}
            if isinstance(x, list):
                return [forme(x[0])] if x else []
            return type(x).__name__
        for k in EX:
            ok(forme(lus[k]) == forme(json.loads(json.dumps(EX[k]))), 'la réponse « %s » a la forme du fichier partagé' % k)
    print('%d vérifications — étape 032 (la messagerie) : OK' % N[0])


if __name__ == '__main__':
    sys.exit(main())
