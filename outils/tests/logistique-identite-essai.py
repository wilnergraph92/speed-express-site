#!/usr/bin/env python3
"""Étape 037 — la date de naissance et la pièce d'identité du client, éprouvées sur la RÉPLIQUE DE LA PRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-identite-essai.py

 A. la 037 passe sur la production d'aujourd'hui (001 à 036) : colonnes vides pour les clients déjà inscrits, rattrapage prêt, empreinte
    « customer_identity » égale des deux côtés ;
 B. une inscription avec date et document : le profil les garde (numéro nettoyé), le noyau les reçoit par le rattrapage ;
 C. des valeurs mal formées (date impossible, future, avant 1900, type inconnu, numéro trop long) n'empêchent JAMAIS l'inscription : elles
    sont laissées vides ou coupées ; une inscription sans ces champs (application mobile) reste possible ;
 D. un écart (ancien schéma changé sans recopie) se voit dans la comparaison, puis le rattrapage le corrige ;
 E. le client ne peut pas modifier lui-même sa date de naissance ni sa pièce ; il peut toujours modifier sa ville ;
 F. la 037 rejouée ne change rien ; supabase.sql porte la même fonction d'inscription.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def fonction(texte, nom):
    i = texte.index('create or replace function %s' % nom)
    return texte[i:texte.index('\n$$;', i) + 4]


def main():
    etape = P.lire_sql('outils/logistique/037-identite-client.sql')
    ok(fonction(P.lire_sql('outils/supabase.sql'), 'public.creer_profil_client()') == fonction(etape, 'public.creer_profil_client()'),
       'supabase.sql porte la même fonction d\'inscription que l\'étape 037')
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('037-identite-client.sql' in etapes, 'l\'étape 037 est dans le noyau')
        for f in etapes:
            if f < '037':
                cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        # La réplique reçoit le supabase-maj.sql d'AUJOURD'HUI (section 11 comprise) ; la vraie production, non : on lui rend son état
        # réel — sans les trois colonnes, avec la fonction d'inscription d'avant (celle du dépôt au commit 1a4533c, juste avant 037).
        avant_037 = P.git_show('outils/supabase.sql', '1a4533cbd019c45f9611b75c70c3e11e03bdeaf1')
        ok(avant_037 and 'date_naissance' not in avant_037, 'la fonction d\'inscription d\'avant 037 est retrouvée dans l\'historique')
        q("alter table public.clients drop column if exists date_naissance, drop column if exists document_type, drop column if exists document_numero")
        cl.run('prod', fonction(avant_037, 'public.creer_profil_client()'))
        rapport = lambda: json.loads(q("select logistics.run_migration('identité')"))['report']   # noqa: E731
        empreinte = lambda: q("select legacy_count || '/' || core_count || '/' || equal from logistics.migration_checksums() where entity = 'customer_identity'")   # noqa: E731
        ok(rapport()['ready'] is True, 'au départ (001 à 036) : prêt')
        ok(q("select count(*) from information_schema.columns where table_schema = 'public' and table_name = 'clients' and column_name = 'date_naissance'") == '0',
           'la production d\'aujourd\'hui n\'a pas encore la colonne')
        clients_avant = q("select count(*) from public.clients")

        # ============================================================ A. la 037
        cl.run('prod', etape)
        ok(q("select count(*) from public.clients where date_naissance is null and document_type = '' and document_numero = ''") == clients_avant,
           'les clients déjà inscrits : rien d\'inventé (date vide, aucun document)')
        r = rapport()
        ok(r['ready'] is True and r['unexplained'] == 0, 'après la 037 : prêt, aucun écart')
        n = q("select count(*) from public.clients c where c.role = 'client' or exists (select 1 from public.colis p where p.client_id = c.id) "
              "or exists (select 1 from public.factures f where f.client_id = c.id)")
        ok(empreinte() == '%s/%s/true' % (n, n), 'l\'empreinte « customer_identity » est égale des deux côtés : %s' % empreinte())

        def inscrire(i, meta):
            uid = '00000000-0000-0000-0037-%012d' % i
            q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
              "('00000000-0000-0000-0000-000000000000', '%s', 'authenticated', 'authenticated', 'identite%d@essai.test', 'x', now(), '%s'::jsonb)"
              % (uid, i, json.dumps(meta).replace("'", "''")))
            return uid

        def profil(uid):
            return q("select coalesce(date_naissance::text, '∅') || '|' || document_type || '|' || document_numero from public.clients where id = '%s'" % uid)

        def noyau(uid):
            return q("select coalesce(birth_date::text, '∅') || '|' || id_document_type || '|' || id_document_number from logistics.customer "
                     "where legacy_client_id = '%s'" % uid)

        # ============================================================ B. une inscription complète
        ana = inscrire(1, {'nom_complet': 'Ana Pérez', 'pays': 'République dominicaine', 'date_naissance': '1990-05-14',
                           'document_type': 'cedula', 'document_numero': '  001-1234567-8  '})
        ok(profil(ana) == '1990-05-14|cedula|001-1234567-8', 'le profil garde la date, le type et le numéro (espaces retirés) : ' + profil(ana))
        ok(rapport()['ready'] is True and noyau(ana) == '1990-05-14|cedula|001-1234567-8', 'le noyau les reçoit par le rattrapage : ' + noyau(ana))
        ok(empreinte().endswith('/true'), 'l\'empreinte reste égale avec une identité renseignée')
        jean = inscrire(2, {'nom_complet': 'Jean Pierre', 'date_naissance': '1985-12-01', 'document_type': 'passeport', 'document_numero': 'RD1234567'})
        ok(profil(jean) == '1985-12-01|passeport|RD1234567', 'un passeport aussi : ' + profil(jean))

        # ============================================================ C. des valeurs mal formées n'empêchent jamais l'inscription
        cas = [
            ({'date_naissance': '1990-02-30', 'document_type': 'passeport', 'document_numero': 'X1'}, '∅|passeport|X1', 'un 30 février'),
            ({'date_naissance': '2999-01-01'}, '∅||', 'une date future'),
            ({'date_naissance': '1850-06-01'}, '∅||', 'une date avant 1900'),
            ({'date_naissance': '14/05/1990', 'document_type': 'permis'}, '∅||', 'une date d\'un autre format, un type inconnu'),
            ({'date_naissance': "1990-01-01'; drop table public.clients; --"}, '∅||', 'une injection dans la date'),
            ({'document_type': 'cedula', 'document_numero': 'N' * 60}, '∅|cedula|' + 'N' * 40, 'un numéro trop long, coupé à 40'),
            ({}, '∅||', 'aucune identité (inscription par l\'application mobile)'),
        ]
        for i, (meta, attendu, quoi) in enumerate(cas, start=10):
            uid = inscrire(i, dict({'nom_complet': 'Essai %d' % i}, **meta))
            ok(profil(uid) == attendu, '%s : l\'inscription passe, la valeur est ignorée ou coupée (%s)' % (quoi, profil(uid)))
        ok(q("select count(*) from public.clients where id::text like '00000000-0000-0000-0037-%'") == str(2 + len(cas)), 'chaque inscription a son profil')
        ok(rapport()['ready'] is True, 'et le rattrapage reste prêt')

        # ============================================================ D. un écart se voit, puis se corrige
        q("alter table public.clients disable trigger user")
        q("update public.clients set document_numero = 'CHANGE-SANS-RECOPIE' where id = '%s'" % ana)
        q("alter table public.clients enable trigger user")
        d = cl.lignes('prod', "select kind || '/' || entity || '/' || detail from logistics.reconcile_complements() where legacy_id = '%s'" % ana)
        ok(d == ['mismatch/customer/date de naissance ou pièce d\'identité différente'], 'la comparaison voit l\'écart : %s' % d)
        ok(empreinte().endswith('/false'), 'et l\'empreinte diffère')
        ok(rapport()['ready'] is True and noyau(ana) == '1990-05-14|cedula|CHANGE-SANS-RECOPIE' and empreinte().endswith('/true'),
           'le rattrapage le corrige aussitôt (le noyau suit l\'ancien schéma)')

        # ============================================================ E. le client ne modifie pas son identité
        code, sortie = cl.run('prod', "update public.clients set document_numero = 'AUTRE' where id = '%s'" % jean, role='authenticated', claims=jean, expect_error=True)
        ok(code != 0 and 'permission denied' in sortie, 'le client ne peut pas changer son numéro de document : ' + sortie[-160:])
        code, sortie = cl.run('prod', "update public.clients set date_naissance = '2000-01-01' where id = '%s'" % jean, role='authenticated', claims=jean, expect_error=True)
        ok(code != 0 and 'permission denied' in sortie, 'ni sa date de naissance')
        code, sortie = cl.run('prod', "update public.clients set ville = 'Santiago' where id = '%s'" % jean, role='authenticated', claims=jean, expect_error=True)
        ok(code == 0 and profil(jean) == '1985-12-01|passeport|RD1234567', 'il modifie toujours sa ville, son identité ne bouge pas : ' + sortie[-160:])
        code, sortie = cl.run('prod', "update public.clients set document_type = 'permis' where id = '%s'" % jean, expect_error=True)
        ok(code != 0 and 'clients_document_type_valeurs' in sortie, 'la base refuse un type inconnu, même écrit directement')

        # ============================================================ F. rejeu
        avant = q("select md5(string_agg(id::text || coalesce(date_naissance::text, '') || document_type || document_numero, ',' order by id)) from public.clients")
        cl.run('prod', etape)
        ok(q("select md5(string_agg(id::text || coalesce(date_naissance::text, '') || document_type || document_numero, ',' order by id)) from public.clients") == avant
           and rapport()['ready'] is True, '037 rejouée : rien ne change')
        print('PASS identité du client (étape 037) : %d vérifications — colonnes vides pour les clients existants, inscription complète gardée et '
              'recopiée, valeurs mal formées ignorées sans jamais bloquer, écart vu puis corrigé, identité non modifiable par le client, '
              'rejeu sans effet (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC identité du client (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
