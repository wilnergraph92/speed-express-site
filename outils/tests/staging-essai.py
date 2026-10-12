#!/usr/bin/env python3
"""La préproduction (outils/staging/), éprouvée sur un vrai PostgreSQL jetable réglé comme Supabase — jamais la production.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/staging-essai.py

On exige :
1. l'installation assemblée pose le marqueur « staging » et donne EXACTEMENT le schéma d'une installation neuve ; rejouée,
   elle ne casse rien ;
2. les données synthétiques : comptes sans mot de passe, numéros posés par la base, factures, historique, pré-alertes,
   identifiants d'équipe ; une seconde fois, refusées ;
3. la réinitialisation efface l'activité et les comptes synthétiques, garde les comptes créés à la main et le registre
   protégé, et l'on peut ressemer ;
4. sur une base qui n'est pas marquée (la production rejouée) : marquer, installer, semer, réinitialiser, anonymiser
   sont TOUS refusés et AUCUNE donnée ne change — même avec psql lancé sans arrêt sur erreur ;
5. au-delà de 25 comptes réels, la réinitialisation refuse même une base marquée ;
6. l'anonymisation d'une copie restaurée ne laisse aucun nom, e-mail, téléphone, adresse, note ni mot de passe, et garde
   la forme de l'activité (comptes, colis, factures, montants, statuts, numéros)."""
import importlib.util
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]
ICI = os.path.dirname(os.path.abspath(__file__))


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


spec = importlib.util.spec_from_file_location('assembler', os.path.join(P.RACINE, 'outils', 'staging', 'assembler-installation.py'))
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
INSTALLATION = A.assembler()
STAGING = lambda f: P.lire_sql('outils/staging/' + f)   # noqa: E731


def socle(cl, base):
    cl.run('postgres', 'create database %s' % base)
    cl.run(base, P.lire_sql('scripts/restore/socle-postgres-vide.sql'))
    cl.run(base, P.AUTH)
    cl.run(base, P.SUPABASE_DEFAUTS)


def refuse(cl, base, sql, code, msg):
    r, texte = cl.run(base, sql, expect_error=True)
    ok(r != 0 and code in texte, '%s : attendu %s, obtenu : %s' % (msg, code, texte[-200:].replace('\n', ' ')))


def psql_sans_arret(cl, base, sql):
    """psql tel qu'un humain pressé le lancerait : sans ON_ERROR_STOP, il continue après une erreur."""
    return subprocess.run([os.path.join(P.PG, 'psql'), '-h', '127.0.0.1', '-p', str(cl.port), '-U', 'postgres', '-d', base, '-qAtX'],
                          input=sql, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)


def main():
    with P.Cluster() as cl:
        # ------------------------------------------------------------------ 1. installation
        socle(cl, 'neuve')
        for f in A.ordre():
            cl.run('neuve', P.lire_sql('outils/' + f))
        socle(cl, 'staging')
        cl.run('staging', INSTALLATION)
        q = lambda sql: cl.un('staging', sql)   # noqa: E731
        ok(q("select nom from ses_meta.environnement") == 'staging', 'l\'installation pose le marqueur « staging »')
        ok(set(cl.lignes('staging', P.CATALOGUE)) == set(cl.lignes('neuve', P.CATALOGUE)), 'la préproduction a EXACTEMENT le schéma public d\'une installation neuve')
        ok(q("select has_schema_privilege('anon', 'ses_meta', 'usage') or has_schema_privilege('authenticated', 'ses_meta', 'usage')") == 'f',
           'le marqueur est invisible de l\'API (ni visiteur ni compte connecté)')
        cl.run('staging', INSTALLATION)
        ok(set(cl.lignes('staging', P.CATALOGUE)) == set(cl.lignes('neuve', P.CATALOGUE)), 'réinstaller sur la préproduction ne change rien')

        # ------------------------------------------------------------------ 2. données synthétiques
        cl.run('staging', STAGING('donnees-synthetiques.sql'))
        ok(q("select count(*) from auth.users where email like '%@exemple.test'") == '15', '15 comptes synthétiques')
        ok(q("select count(*) from auth.users where encrypted_password <> ''") == '0', 'aucun ne peut se connecter (pas de mot de passe)')
        ok(q("select count(*) from public.clients where role = 'client' and code ~ '^SES-[0-9]{5}$'") == '12', '12 clients, chacun son code SES-#####')
        ok(q("select string_agg(split_part(matricule, '-', 1), ',' order by matricule) from public.clients where role <> 'client'") == 'ADM,EMP,GER'
           and q("select count(*) from public.clients where role <> 'client' and code is not null") == '0',
           'l\'équipe synthétique : ADM, GER, EMP, sans code client')
        ok(q("select count(*) from public.colis where numero ~ '^SES-[0-9]{10}$'") == '60', '60 colis, numérotés par la base (SES- et dix chiffres)')
        ok(q("select count(distinct statut) from public.colis") == '5', 'les cinq statuts sont représentés')
        ok(q("select count(*) from public.factures") == '60' and q("select count(*) from public.factures where statut = 'payee'") != '0',
           'une facture par colis, créée par la base, certaines payées')
        ok(q("select count(*) from public.factures f join public.colis c on c.id = f.colis_id where c.prix_manuel = 25 and f.montant = 35 and f.frais_service = 10") != '0',
           'des prix saisis à la main, repris par la facture (25 $ + 10 $ de frais)')
        ok(int(q("select count(*) from public.colis_historique")) > 60, 'l\'historique suit les changements de statut')
        ok(q("select count(*) from public.prealertes where statut = 'attendue'") == '12', '12 pré-alertes')
        refuse(cl, 'staging', STAGING('donnees-synthetiques.sql'), 'SE901', 'semer deux fois')
        ok(q("select count(*) from public.colis") == '60', 'le second semis n\'a rien ajouté')

        # ------------------------------------------------------------------ 3. réinitialisation
        q("insert into auth.users (id, aud, role, email, encrypted_password, raw_user_meta_data) values "
          "(gen_random_uuid(), 'authenticated', 'authenticated', 'moi@preproduction.example', 'x', '{\"nom_complet\": \"Moi\"}')")
        q("update public.clients set role = 'admin', code = null where email = 'moi@preproduction.example'")
        mon_matricule = q("select matricule from public.clients where email = 'moi@preproduction.example'")
        cl.run('staging', STAGING('reinitialiser.sql'))
        for t in ('colis', 'colis_historique', 'factures', 'prealertes', 'appareils'):
            ok(q('select count(*) from public.%s' % t) == '0', 'réinitialisé : %s vide' % t)
        ok(q("select count(*) from auth.users where email like '%@exemple.test'") == '0', 'réinitialisé : plus de compte synthétique')
        ok(q("select role || ' ' || matricule from public.clients where email = 'moi@preproduction.example'") == 'admin ' + mon_matricule,
           'réinitialisé : le compte créé à la main garde son rôle et son identifiant')
        ok(q("select count(*) from public.matricules_attribues") == '1', 'réinitialisé : le registre ne garde que le compte réel')
        ok(q("select tgenabled from pg_trigger where tgname = 'proteger_registre_matricules'") == 'O', 'la protection du registre est rétablie')
        refuse(cl, 'staging', 'delete from public.matricules_attribues', '42501', 'le registre redevient inviolable')
        cl.run('staging', STAGING('donnees-synthetiques.sql'))
        ok(q("select count(*) from public.colis") == '60', 'on peut ressemer après une réinitialisation')

        # ------------------------------------------------------------------ 5. plus de 25 comptes réels
        q("insert into auth.users (id, aud, role, email, raw_user_meta_data) select gen_random_uuid(), 'authenticated', 'authenticated', "
          "'reel' || i || '@client.example', '{}' from generate_series(1, 25) i")
        refuse(cl, 'staging', STAGING('reinitialiser.sql'), 'SE900', 'plus de 25 comptes réels : réinitialisation refusée')
        ok(q("select count(*) from public.colis") == '60', 'et rien n\'est effacé')

        # ------------------------------------------------------------------ 4. la production n'est jamais touchée
        P.monter_historique(cl, 'prod')
        donnees = P.empreintes_historiques(cl, 'prod')
        refuse(cl, 'prod', STAGING('marquer.sql'), 'SE900', 'marquer la production')
        ok(cl.un('prod', "select to_regclass('ses_meta.environnement') is null") == 't', 'aucun marqueur posé sur la production')
        refuse(cl, 'prod', INSTALLATION, 'SE900', 'installer la préproduction sur la production')
        for f in ('donnees-synthetiques.sql', 'reinitialiser.sql', 'anonymiser.sql'):
            refuse(cl, 'prod', STAGING(f), 'SE900', '%s sur la production' % f)
            r = psql_sans_arret(cl, 'prod', STAGING(f))
            ok('SE900' in r.stderr or 'préproduction' in r.stderr or 'staging' in r.stderr, '%s, psql sans arrêt sur erreur : le garde-fou parle' % f)
        ok(P.empreintes_historiques(cl, 'prod') == donnees, 'la production : AUCUNE donnée changée, même avec psql sans arrêt sur erreur')
        ok(cl.un('prod', "select to_regclass('ses_meta.environnement') is null") == 't', 'et toujours aucun marqueur')
        r = psql_sans_arret(cl, 'prod', INSTALLATION)
        ok(cl.un('prod', "select to_regclass('ses_meta.environnement') is null") == 't' and P.empreintes_historiques(cl, 'prod') == donnees,
           'l\'installation poursuivie sans arrêt sur erreur ne marque pas la production et n\'en change aucune donnée (le reste est rejouable)')

        # ------------------------------------------------------------------ 6. anonymiser une copie restaurée
        cl.run('postgres', 'create database copie')
        cl.run('copie', P.lire_sql('scripts/restore/socle-postgres-vide.sql'))
        cl.run('copie', P.AUTH)
        cl.run('copie', STAGING('marquer.sql'))          # AVANT la restauration
        for f in ('supabase.sql', 'supabase-maj-facture-groupee.sql', 'supabase-maj-jeton.sql', 'supabase-dashboard.sql', 'supabase-maj.sql',
                  'supabase-maj-prix-prealertes.sql', 'supabase-maj-equipe.sql'):
            cl.run('copie', P.lire_sql('outils/' + f))
        cl.run('copie', P.DONNEES % {'noms': "array[%s]" % ','.join("'%s'" % n.replace("'", "''") for n in P.NOMS)})
        c = lambda sql: cl.un('copie', sql)   # noqa: E731
        c("insert into public.prealertes (client_id, magasin, contenu, numero_suivi, valeur) select id, 'Amazon', 'Robe pour Marie-Ève Léger', "
          "'1Z999AA10123456784', 40 from public.clients where role = 'client' limit 3")
        c("set session_replication_role = replica; update public.colis set telephone_destinataire = '+509 3712 3456', adresse_livraison = '12 rue de l''Église, Delmas' where true")
        forme = "select (select count(*) from auth.users) || '/' || (select count(*) from public.clients) || '/' || (select count(*) from public.colis) || '/' || " \
                "(select count(*) from public.factures) || '/' || (select sum(montant) from public.factures) || '/' || (select sum(montant_paye) from public.factures) || '/' || " \
                "(select string_agg(statut, ',' order by id) from public.colis) || '/' || (select string_agg(numero, ',' order by numero) from public.colis) || '/' || " \
                "(select string_agg(coalesce(code, '-'), ',' order by id) from public.clients) || '/' || (select count(*) from public.prealertes)"
        avant = c(forme)
        cl.run('copie', STAGING('anonymiser.sql'))
        ok(c(forme) == avant, 'anonymisé : même nombre de comptes, colis, factures, mêmes montants, statuts, numéros et codes')
        tout = '\n'.join(cl.lignes('copie', "select row_to_json(t)::text from auth.users t union all select row_to_json(t)::text from public.clients t "
                                            "union all select row_to_json(t)::text from public.colis t union all select row_to_json(t)::text from public.colis_historique t "
                                            "union all select row_to_json(t)::text from public.factures t union all select row_to_json(t)::text from public.prealertes t"))
        for nom in P.NOMS:
            ok(nom.split()[0].replace('"', '') not in tout, 'anonymisé : plus de trace de « %s »' % nom)
        for trace in ('@essai.test', '+509 3', "rue de l", '1Z999AA', 'remis en main propre', 'Marie-Ève', '$2a$10$fictif', 'Regroupe : essai'):
            ok(trace not in tout, 'anonymisé : plus de trace de « %s »' % trace)
        ok(c("select count(*) from public.appareils") == '0' and c("select count(*) from auth.identities") == '0',
           'anonymisé : plus de téléphone enregistré ni d\'identité de connexion')
        ok(c("select count(*) from pg_trigger where tgname in ('preparer_prealerte', 'verifier_modification_colis', 'facturer_colis') and tgenabled = 'O'") == '3',
           'les protections des colis, des factures et des pré-alertes sont intactes après l\'anonymisation')

        print('PASS préproduction : %d vérifications — installation marquée au schéma identique à une installation neuve, données synthétiques sans '
              'mot de passe, réinitialisation qui garde les comptes réels et le registre, garde-fous sur la production (même psql sans arrêt), '
              'plafond de 25 comptes réels, anonymisation complète qui garde la forme de l\'activité (PostgreSQL %s).'
              % (N[0], cl.un('staging', 'show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC préproduction (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
