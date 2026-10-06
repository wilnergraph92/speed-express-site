#!/usr/bin/env python3
"""Sécurité de la base, éprouvée en tentant de l'attaquer — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/securite-sql.py

Chaque test est une TENTATIVE : un visiteur, un client, un employé sans droit essaient ce qu'ils
ne doivent pas pouvoir faire ; le test réussit quand la base refuse, avec le bon code.
Jamais la production."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def refuse(cl, sql, etat, msg, **kw):
    code, texte = cl.run('ses', sql, expect_error=True, **kw)
    ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-170:].replace('\n', ' ')))


def sans_effet(cl, dml, msg, **kw):
    """Une écriture que la sécurité par ligne vide de tout effet : 0 ligne touchée, sans erreur."""
    n = cl.un('ses', "with u as (%s returning 1) select count(*) from u" % dml, **kw)
    ok(n == '0', '%s : %s ligne(s) touchée(s) au lieu de 0' % (msg, n))


def main():
    with P.Cluster() as cl:
        q = lambda sql, **kw: cl.un('ses', sql, **kw)   # noqa: E731
        P.monter_historique(cl, 'ses')
        uid = lambda n: q("select id from public.clients where email = 'client%d@essai.test'" % n)   # noqa: E731
        admin, gerant, op, sansdroit, cli, autre = uid(1), uid(2), uid(3), uid(4), uid(9), uid(10)
        q("update public.clients set droits = '{}' where id = '%s'" % sansdroit)
        q("update public.clients set role = 'employe' where id = '%s'" % sansdroit)

        # ---------------------------------------------------------------- 1. le visiteur anonyme
        for fonction, args in [('est_direction', ''), ('definir_role', "'%s', 'admin'" % cli), ('definir_admin', "'a@b.c'"),
                               ('statistiques_ses', ''), ('dashboard_colis_ses', ''), ('dashboard_clients_ses', ''),
                               ('nouveau_code_client', ''), ('enregistrer_appareil', "'ExponentPushToken[abcdefghij1234567890]'"),
                               ('est_admin', ''), ('a_droit', "'colis.lire'"), ('texte_notification', "'livre', 'fr'")]:
            refuse(cl, 'select public.%s(%s)' % (fonction, args), '42501', 'anon exécute %s' % fonction, role='anon')
        ok(q("select (public.suivre_colis('ZZZZ-INEXISTANT')) is null", role='anon') == 't', 'anon : le suivi public reste ouvert (c\'est la seule fonction publique)')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public' and p.prokind = 'f' "
             "and has_function_privilege('anon', p.oid, 'execute') and p.prorettype <> 'trigger'::regtype") == '1',
           'UNE seule fonction publique est exécutable par un visiteur (suivre_colis)')
        for table in ('clients', 'colis', 'colis_historique', 'factures', 'appareils', 'colis_details', 'factures_details'):
            refuse(cl, 'select count(*) from public.%s' % table, '42501', 'anon lit %s' % table, role='anon')
        refuse(cl, "insert into public.colis (description) values ('x')", '42501', 'anon écrit dans colis', role='anon')
        refuse(cl, "update public.clients set role = 'admin'", '42501', 'anon modifie clients', role='anon')
        refuse(cl, "delete from public.factures", '42501', 'anon supprime des factures', role='anon')

        # ---------------------------------------------------------------- 2. un simple CLIENT
        c = dict(role='authenticated', claims=cli)
        ok(q('select count(*) from public.clients', **c) == '1', 'un client ne voit que SON profil')
        n_colis = int(q("select count(*) from public.colis where client_id = '%s'" % cli))
        ok(q('select count(*) from public.colis', **c) == str(n_colis) and q('select count(*) from public.factures', **c) == q("select count(*) from public.factures where client_id = '%s'" % cli),
           'un client ne voit que SES colis et SES factures')
        q("update public.clients set telephone = '+509 0000 1111', ville = 'Jacmel', langue = 'es' where id = '%s'" % cli, **c)
        ok(q("select telephone || '/' || ville || '/' || langue from public.clients where id = '%s'" % cli, **c) == '+509 0000 1111/Jacmel/es', 'il peut changer ses coordonnées (7 colonnes)')
        for colonne, valeur in [('role', "'admin'"), ('droits', "array['roles.gerer']"), ('code', "'SES-99999'"), ('email', "'pirate@evil.test'"),
                                ('id', "gen_random_uuid()"), ('cree_le', "now()")]:
            refuse(cl, "update public.clients set %s = %s where id = '%s'" % (colonne, valeur, cli), '42501', 'un client modifie sa colonne « %s »' % colonne, **c)
        refuse(cl, "update public.clients set nom_complet = 'x', role = 'admin' where id = '%s'" % cli, '42501', 'une colonne permise ne couvre pas une interdite dans la même requête', **c)
        ok(q("select role || '/' || coalesce(code, '') || '/' || email from public.clients where id = '%s'" % cli).startswith('client/SES-'), 'son rôle, son code et son e-mail sont intacts')
        ok(q("with u as (update public.clients set nom_complet = 'intrus' where id = '%s' returning 1) select count(*) from u" % autre, **c) == '0', 'il ne modifie pas le profil d\'un autre (0 ligne)')
        refuse(cl, "insert into public.clients (id, nom_complet) values (gen_random_uuid(), 'x')", '42501', 'un client crée un profil', **c)
        refuse(cl, "delete from public.clients where id = '%s'" % cli, '42501', 'un client supprime son profil', **c)
        refuse(cl, "select public.definir_role('%s', 'admin')" % cli, '42501', 'un client se promeut par definir_role', **c)
        refuse(cl, "select public.definir_role('%s', 'client')" % autre, '42501', 'un client modifie un autre compte par definir_role', **c)
        refuse(cl, "insert into public.colis (client_id, description) values ('%s', 'x')" % cli, '42501', 'un client crée un colis', **c)
        refuse(cl, "insert into public.factures (client_id, montant) values ('%s', 1)" % cli, '42501', 'un client crée une facture', **c)
        avant = q("select string_agg(montant_paye::text || '/' || statut, ',' order by id) from public.factures where client_id = '%s'" % cli)
        sans_effet(cl, "update public.factures set montant_paye = montant where client_id = '%s'" % cli, 'un client marque sa facture payée', **c)
        sans_effet(cl, "update public.factures set statut = 'payee' where client_id = '%s'" % cli, 'un client passe sa facture en « payée »', **c)
        sans_effet(cl, "update public.colis set tarif_lb = 0 where client_id = '%s'" % cli, 'un client baisse le tarif de son colis', **c)
        sans_effet(cl, "update public.colis set statut = 'livre' where client_id = '%s'" % cli, 'un client marque son colis livré', **c)
        sans_effet(cl, "delete from public.colis where client_id = '%s'" % cli, 'un client supprime son colis', **c)
        sans_effet(cl, "delete from public.factures where client_id = '%s'" % cli, 'un client supprime sa facture', **c)
        ok(q("select string_agg(montant_paye::text || '/' || statut, ',' order by id) from public.factures where client_id = '%s'" % cli) == avant, 'ses factures sont strictement inchangées')
        refuse(cl, "select public.statistiques_ses()", '42501', 'un client lit les statistiques', **c)
        ok(q("select public.est_admin()", **c) == 'f' and q("select public.a_droit('colis.lire')", **c) == 'f', 'un client n\'a aucun droit (même si la colonne droits est falsifiée en base)')
        q("update public.clients set droits = array['colis.lire','roles.gerer','factures.supprimer'] where id = '%s'" % cli)    # falsifié en superutilisateur
        ok(q("select count(*) from public.colis", **c) == str(n_colis), 'une colonne « droits » pleine ne donne AUCUN accès à un client')
        refuse(cl, "select public.definir_role('%s', 'admin')" % autre, '42501', 'ni la gestion des rôles', **c)
        q("update public.clients set droits = '{}' where id = '%s'" % cli)

        # ---------------------------------------------------------------- 3. un employé sans droit, un employé avec
        s = dict(role='authenticated', claims=sansdroit)
        ok(q('select count(*) from public.colis', **s) == '0', 'un employé SANS droit ne voit aucun colis')
        refuse(cl, "select public.definir_role('%s', 'employe')" % cli, '42501', 'un employé sans roles.gerer change un rôle', **s)
        o = dict(role='authenticated', claims=op)
        refuse(cl, "select public.definir_role('%s', 'gerant')" % cli, '42501', 'un employé (colis.statut seulement) nomme un gérant', **o)
        g = dict(role='authenticated', claims=gerant)
        refuse(cl, "select public.definir_role('%s', 'admin')" % cli, '42501', 'un gérant nomme un administrateur', **g)
        refuse(cl, "select public.definir_role('%s', 'client')" % gerant, '42501', 'un gérant modifie son propre rôle', **g)

        # ---------------------------------------------------------------- 4. les appareils (notifications)
        tok = 'ExponentPushToken[nouveau-telephone-0001]'
        q("select public.enregistrer_appareil('%s', 'ios')" % tok, **c)
        ok(q("select client_id::text from public.appareils where jeton = '%s'" % tok) == cli, 'un client enregistre son téléphone')
        q("select public.enregistrer_appareil('%s', 'android')" % tok, role='authenticated', claims=autre)
        ok(q("select client_id::text from public.appareils where jeton = '%s'" % tok) == autre, 'le même téléphone passe à un AUTRE compte : l\'ancien n\'en garde pas la trace')
        ok(q("select count(*) from public.appareils where jeton = '%s'" % tok, **c) == '0', 'et l\'ancien propriétaire ne le voit plus')
        refuse(cl, "select public.enregistrer_appareil('pas-un-jeton')", '22023', 'jeton de forme invalide', **c)
        refuse(cl, "select public.enregistrer_appareil('ExponentPushToken[%s]')" % ('x' * 300), '22023', 'jeton trop long', **c)
        refuse(cl, "select public.enregistrer_appareil('ExponentPushToken[</script>-0000000000000]')", '22023', 'jeton avec des caractères dangereux', **c)
        ok(q("with u as (update public.appareils set client_id = '%s' where jeton = '%s' returning 1) select count(*) from u" % (cli, tok), **c) == '0', 'prendre le téléphone d\'un autre par UPDATE direct : 0 ligne')
        ok(q("select has_table_privilege('authenticated', 'public.appareils', 'insert')") == 't' and q("select has_table_privilege('anon', 'public.appareils', 'select')") == 'f',
           'la table des appareils a ses droits (authenticated oui, anon non) — l\'enregistrement ne peut plus échouer en silence')

        # ---------------------------------------------------------------- 5. le déclencheur de notification ne peut plus bloquer un colis
        defn = '\n'.join(cl.lignes('ses', "select pg_get_functiondef('public.prevenir_client()'::regprocedure)"))
        ok('extensions.net.' not in defn and 'net.http_post' in defn, 'le nom d\'appel invalide « extensions.net.http_post » a disparu')
        ok('exception when others' in defn.lower(), 'l\'envoi est entouré d\'un bloc qui transforme toute erreur en avertissement')
        avec_appareil = q("select client_id::text from public.appareils where client_id <> '%s' limit 1" % cli)
        colis = q("select id from public.colis where client_id = '%s' limit 1" % avec_appareil)
        sans_appareil = q("select id from public.clients where role = 'client' and not exists (select 1 from public.appareils a where a.client_id = clients.id) limit 1")
        colis_sans = q("select id from public.colis where client_id = '%s' limit 1" % sans_appareil)
        g = dict(role='authenticated', claims=gerant)

        def statut(pid, nouveau):
            return q("update public.colis set statut = '%s' where id = '%s' returning statut" % (nouveau, pid), **g)

        # a) aucune extension pg_net (le cas de ce banc d'essai et d'un projet qui ne l'a pas activée)
        ok(q("select count(*) from pg_namespace where nspname = 'net'") == '0', 'point de départ : pg_net absent')
        ok(statut(colis, 'expedie') == 'expedie', 'SANS pg_net, le changement de statut d\'un colis qui a des appareils RÉUSSIT (avertissement seulement)')
        # b) pg_net présent : l'appel part, une fois, avec les bons arguments
        q("create schema net; create table public.essai_appels (n serial, corps jsonb, url text); "
          "create function net.http_post(url text, headers jsonb default '{}', body jsonb default '{}') returns bigint language plpgsql security definer as $$ "
          "begin insert into public.essai_appels (corps, url) values (body, url); return 1; end $$")
        ok(statut(colis, 'disponible') == 'disponible', 'avec pg_net, le statut change')
        ok(q('select count(*) from public.essai_appels') == '1', 'et UN appel d\'envoi est fait')
        ok(q("select (corps -> 'to') is not null and corps ->> 'body' = (select numero from public.colis where id = '%s') and url like 'https://exp.host/%%' from public.essai_appels" % colis) == 't',
           'avec les jetons du client, le numéro du colis, vers le service d\'Expo')
        langue = q("select langue from public.clients where id = '%s'" % avec_appareil)
        ok(q("select corps ->> 'title' = public.texte_notification('disponible', '%s') from public.essai_appels" % langue) == 't', 'dans la langue du client')
        # c) un colis dont le client n'a pas d'application : aucun appel
        statut(colis_sans, 'expedie')
        ok(q('select count(*) from public.essai_appels') == '1', 'un client sans application ne déclenche aucun appel')
        # d) un colis sans client
        q("insert into public.colis (description, poids_lb, tarif_lb, pays_destination, service) values ('sans client', 1, 1, 'HT', 'aerien')")
        ok(q("update public.colis set statut = 'expedie' where description = 'sans client' returning statut", **g) == 'expedie', 'un colis sans client change de statut sans erreur')
        # e) pg_net qui plante : le colis change quand même
        q("create or replace function net.http_post(url text, headers jsonb default '{}', body jsonb default '{}') returns bigint language plpgsql as $$ begin raise exception 'service Expo indisponible'; end $$")
        ok(statut(colis, 'livre') == 'livre', 'si le service d\'envoi PLANTE, le colis passe quand même à « livré »')
        ok(q("select statut from public.colis where id = '%s'" % colis) == 'livre', 'et la base l\'a bien enregistré')
        # f) à la création d'un colis aussi
        ok(q("insert into public.colis (client_id, description, poids_lb, tarif_lb, pays_destination, service) values ('%s', 'créé avec pg_net en panne', 2, 2, 'DO', 'maritime') returning 1" % avec_appareil) == '1',
           'la CRÉATION d\'un colis pour un client équipé réussit aussi pendant la panne')

        # ---------------------------------------------------------------- 6. les fonctions ouvertes, état final
        ok(q("select string_agg(p.proname, ',' order by p.proname) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
             "where n.nspname = 'public' and p.prorettype <> 'trigger'::regtype and has_function_privilege('authenticated', p.oid, 'execute')") ==
           'a_droit,dashboard_clients_ses,dashboard_colis_ses,dashboard_periode_ses,definir_role,enregistrer_appareil,est_admin,est_direction,statistiques_ses,suivre_colis,texte_notification',
           'fonctions ouvertes aux comptes connectés : exactement la liste attendue, ni plus ni moins')

        print('PASS sécurité SQL : %d vérifications — visiteur, client, employé et gérant tentent l\'interdit et sont refusés ; un client ne modifie ni son rôle, '
              'ni ses droits, ni son code, ni son e-mail ; téléphones réaffectés sans fuite ; une notification ne peut plus bloquer un colis (PostgreSQL %s).'
              % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC sécurité SQL (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
