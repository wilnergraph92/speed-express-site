#!/usr/bin/env python3
"""Audit du catalogue de sécurité, sur un vrai PostgreSQL jetable réglé COMME SUPABASE — jamais la production.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/securite-catalogue.py

Deux bases sont montées, toutes deux avec les droits par défaut de Supabase (tout objet nouveau de « public » ouvert à
anon et authenticated, sauf retrait explicite) :

1. une INSTALLATION NEUVE (les fichiers dans l'ordre de schema-rejouable.py) : on lit le catalogue et on exige
   - chaque fonction SECURITY DEFINER a un search_path figé (sinon un objet homonyme peut la détourner) ;
   - une SEULE fonction appelable par un visiteur : le suivi public ;
   - la liste exacte des fonctions appelables par un compte connecté ;
   - la sécurité par ligne sur chaque table, aucun droit d'aucune sorte pour un visiteur sur une table ou une vue,
     aucun TRUNCATE / TRIGGER / REFERENCES pour un compte connecté ;
   - chaque vue obéit aux règles de celui qui la lit (security_invoker).

2. une RÉPLIQUE DE LA PRODUCTION telle que sondée le 7 octobre 2026 (sonde anonyme, lecture seule) : les fichiers du
   5 octobre (commit 7954339, supabase-maj.sql sans ses sections 9 et 10), la migration de notifications de l'application
   (fixtures/production-notifications-106f266.sql), puis les collages du 7 octobre. On vérifie qu'elle montre bien les
   défauts observés en production, puis qu'en y collant le REMÈDE (supabase-maj-facture-groupee.sql, supabase-maj.sql et
   supabase-maj-securite.sql actuels) :
   - ils disparaissent tous ;
   - le schéma devient celui de l'installation neuve, sans reste de l'ancienne version ;
   - aucune donnée n'a changé (empreinte de chaque table).
   C'est la preuve à fournir avant de proposer ce collage."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

ORDRE = ['supabase.sql', 'supabase-maj-facture-groupee.sql', 'supabase-maj-jeton.sql', 'supabase-dashboard.sql', 'supabase-maj.sql',
         'supabase-maj-numeros.sql', 'supabase-maj-prix-prealertes.sql', 'supabase-maj-equipe.sql', 'supabase-maj-securite.sql']
# Ce qui était en production avant le 7 octobre : les fichiers de ce commit (supabase-maj.sql s'y arrête à la section 8).
AVANT = '7954339'
# supabase-maj-facture-groupee.sql y est la version du 30 septembre : sa vue factures_details ne montre pas « groupee ».
PRODUCTION_5_OCTOBRE = ['supabase.sql', 'supabase-maj-facture-groupee.sql', 'supabase-maj-jeton.sql', 'supabase-dashboard.sql']
# Le remède proposé, dans cet ordre : tous rejouables.
REMEDE = ['supabase-maj-facture-groupee.sql', 'supabase-maj.sql', 'supabase-maj-securite.sql']
COLLAGES_7_OCTOBRE = ['supabase-maj-numeros.sql', 'supabase-maj-prix-prealertes.sql', 'supabase-dashboard.sql', 'supabase-maj-equipe.sql']

PUBLIQUES = 'suivre_colis'
CONNECTES = ('a_droit,dashboard_clients_ses,dashboard_colis_ses,dashboard_periode_ses,definir_role,enregistrer_appareil,est_admin,'
             'est_direction,statistiques_ses,suivre_colis,texte_notification')

N = [0]


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def git_show(chemin):
    return subprocess.run(['git', 'show', '%s:%s' % (AVANT, chemin)], cwd=P.RACINE, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, universal_newlines=True).stdout or None


def socle(cl, base):
    cl.run('postgres', 'create database %s' % base)
    cl.run(base, P.lire_sql('scripts/restore/socle-postgres-vide.sql'))
    cl.run(base, P.AUTH)
    cl.run(base, P.SUPABASE_DEFAUTS)


def fonctions(cl, base, role):
    return cl.un(base, "select coalesce(string_agg(distinct p.proname, ',' order by p.proname), '') from pg_proc p "
                       "where p.pronamespace = 'public'::regnamespace and p.prorettype <> 'trigger'::regtype "
                       "and has_function_privilege('%s', p.oid, 'execute')" % role)


def auditer(cl, base, ou):
    q = lambda sql: cl.un(base, sql)   # noqa: E731
    sans_chemin = q("select coalesce(string_agg(p.proname, ',' order by p.proname), '') from pg_proc p "
                    "where p.pronamespace = 'public'::regnamespace and p.prosecdef "
                    "and not exists (select 1 from unnest(coalesce(p.proconfig, '{}')) c where c like 'search_path=%')")
    ok(sans_chemin == '', '%s : fonctions SECURITY DEFINER sans search_path figé : %s' % (ou, sans_chemin))
    ok(fonctions(cl, base, 'anon') == PUBLIQUES, '%s : fonctions appelables par un visiteur : %s (attendu : %s)' % (ou, fonctions(cl, base, 'anon'), PUBLIQUES))
    ok(fonctions(cl, base, 'authenticated') == CONNECTES,
       '%s : fonctions appelables par un compte connecté : %s (attendu : %s)' % (ou, fonctions(cl, base, 'authenticated'), CONNECTES))
    sans_rls = q("select coalesce(string_agg(relname, ',' order by relname), '') from pg_class "
                 "where relnamespace = 'public'::regnamespace and relkind = 'r' and not relrowsecurity")
    ok(sans_rls == '', '%s : tables sans sécurité par ligne : %s' % (ou, sans_rls))
    anon = q("select coalesce(string_agg(c.relname || ':' || p, ',' order by c.relname, p), '') from pg_class c "
             "cross join unnest(array['select','insert','update','delete','truncate','references','trigger']) p "
             "where c.relnamespace = 'public'::regnamespace and c.relkind in ('r','v','m') and has_table_privilege('anon', c.oid, p)")
    ok(anon == '', '%s : droits d\'un visiteur sur des tables ou vues : %s' % (ou, anon))
    connecte = q("select coalesce(string_agg(c.relname || ':' || p, ',' order by c.relname, p), '') from pg_class c "
                 "cross join unnest(array['truncate','references','trigger']) p "
                 "where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and has_table_privilege('authenticated', c.oid, p)")
    ok(connecte == '', '%s : droits superflus d\'un compte connecté (TRUNCATE, TRIGGER, REFERENCES) : %s' % (ou, connecte))
    vues = q("select coalesce(string_agg(c.relname, ',' order by c.relname), '') from pg_class c where c.relnamespace = 'public'::regnamespace "
             "and c.relkind = 'v' and not coalesce('security_invoker=true' = any(c.reloptions), false)")
    ok(vues == '', '%s : vues qui contournent la sécurité par ligne (sans security_invoker) : %s' % (ou, vues))
    sequences = q("select coalesce(string_agg(c.relname, ',' order by c.relname), '') from pg_class c "
                  "where c.relnamespace = 'public'::regnamespace and c.relkind = 'S' and case when c.relkind = 'S' then has_sequence_privilege('anon', c.oid, 'usage') end")
    ok(sequences == '', '%s : séquences utilisables par un visiteur : %s' % (ou, sequences))


def main():
    with P.Cluster() as cl:
        # ------------------------------------------------------------------ 1. installation neuve
        socle(cl, 'neuve')
        for f in ORDRE:
            cl.run('neuve', P.lire_sql('outils/' + f))
        auditer(cl, 'neuve', 'installation neuve')
        reference = set(cl.lignes('neuve', P.CATALOGUE))

        # ------------------------------------------------------------------ 2. réplique de la production
        anciens = [git_show('outils/' + f) for f in PRODUCTION_5_OCTOBRE]
        if not all(anciens):
            print('ATTENTION : commit %s introuvable (clone superficiel ?) — réplique de la production non éprouvée.' % AVANT)
        else:
            # dans l'ordre de la production : le schéma, les notifications de l'application, des données, puis supabase-maj.sql
            # (sections 1 à 8, dont 8b qui retire l'identifiant client des comptes d'équipe existants), puis les collages du 7 octobre
            socle(cl, 'prod')
            for texte in anciens:
                cl.run('prod', texte)
            cl.run('prod', P.lire_sql('outils/tests/fixtures/production-notifications-106f266.sql'))
            cl.run('prod', P.DONNEES % {'noms': "array[%s]" % ','.join("'%s'" % n.replace("'", "''") for n in P.NOMS)})
            cl.run('prod', git_show('outils/supabase-maj.sql'))
            for f in COLLAGES_7_OCTOBRE:
                cl.run('prod', P.lire_sql('outils/' + f))
            q = lambda sql: cl.un('prod', sql)   # noqa: E731
            # ce que la sonde anonyme du 7 octobre a constaté en production
            ok(q("select has_function_privilege('anon', 'public.est_admin()', 'execute')") == 't', 'réplique : est_admin exécutable par un visiteur (comme en production)')
            ok(q("select has_function_privilege('anon', 'public.texte_notification(text,text)', 'execute')") == 't', 'réplique : texte_notification aussi')
            ok(q("select to_regprocedure('public.enregistrer_appareil(text,text)') is null") == 't', 'réplique : enregistrer_appareil absente (comme en production)')
            ok(q("select position('extensions.net.' in pg_get_functiondef('public.prevenir_client()'::regprocedure)) > 0") == 't',
               'réplique : prevenir_client appelle encore « extensions.net.http_post » (R18)')
            ok(q("select count(*) from pg_attribute where attrelid = 'public.factures_details'::regclass and attname = 'groupee'") == '0',
               'réplique : la vue factures_details ne montre pas « groupee » (version du 30 septembre)')
            # R18 démontré : dès qu'un client a un téléphone enregistré, son colis ne peut plus changer de statut
            equipe = q("select id from public.colis where client_id in (select client_id from public.appareils) limit 1")
            code, texte = cl.run('prod', "update public.colis set statut = 'action' where id = '%s'" % equipe, expect_error=True)
            ok(code != 0, 'réplique : changer le statut du colis d\'un client qui a un téléphone ÉCHOUE (R18, latent en production)')
            donnees = P.empreintes_historiques(cl, 'prod')
            # le remède, passé deux fois (rejouable)
            for _ in range(2):
                for f in REMEDE:
                    cl.run('prod', P.lire_sql('outils/' + f))
            auditer(cl, 'prod', 'production après le remède')
            ok(q("select position('extensions.net.' in pg_get_functiondef('public.prevenir_client()'::regprocedure)) = 0") == 't',
               'après le remède : prevenir_client corrigé')
            ok(q("select count(*) from pg_attribute where attrelid = 'public.factures_details'::regclass and attname = 'groupee'") == '1',
               'après le remède : factures_details montre « groupee »')
            # Le texte d'une vue « select c.* » dépend de l'ordre physique des colonnes (une colonne ajoutée plus tard arrive en
            # fin de table) : on compare les colonnes des vues, pas leur texte.
            pareil = lambda lignes: {l for l in lignes if not l.startswith('vue ')}   # noqa: E731
            apres = pareil(cl.lignes('prod', P.CATALOGUE))
            en_trop, manquants = sorted(apres - pareil(reference)), sorted(pareil(reference) - apres)
            ok(not en_trop and not manquants, 'après le remède, la production diffère d\'une installation neuve :\n   + %s\n   - %s'
               % ('\n   + '.join(l[:170] for l in en_trop[:12]), '\n   - '.join(l[:170] for l in manquants[:12])))
            ok(P.empreintes_historiques(cl, 'prod') == donnees, 'après le remède : aucune donnée n\'a changé (clients, colis, historique, factures, appareils, comptes)')
            ok(q("update public.colis set statut = 'action' where id = '%s' returning statut" % equipe) == 'action',
               'après le remède : le même changement de statut réussit')

        print('PASS catalogue de sécurité : %d vérifications — droits par défaut de Supabase reproduits ; search_path figé, une seule fonction publique, '
              'liste exacte des fonctions des comptes connectés, RLS partout, aucun droit de visiteur, security_invoker ; réplique de la production : '
              'défauts du 7 octobre retrouvés (R18 démontré), puis corrigés par facture-groupee + maj + securite sans reste ni changement de donnée (PostgreSQL %s).'
              % (N[0], cl.un('neuve', 'show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC catalogue de sécurité (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
