#!/usr/bin/env python3
"""Étape 028 — un client qui entre dans l'équipe, éprouvé sur la RÉPLIQUE DE LA PRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-equipe-essai.py

Le cas constaté en production le 14 octobre 2026 :
 A. avec les étapes 001 à 027 seulement, un client sans colis ni facture que la direction fait entrer dans l'équipe (definir_role) rend le
    rattrapage « pas prêt » : un écart client inexpliqué (son code retiré dans l'ancien schéma, gardé dans le noyau) ;
 B. l'étape 028 l'EXPLIQUE (« became_staff ») : prêt ; la fiche du noyau reste (rien n'est supprimé), marquée compte d'équipe ;
 C. un autre écart client (un vrai désaccord sur un client resté client) reste INEXPLIQUÉ : la 028 n'excuse que ce cas ;
 D. la bienvenue ignore un compte d'équipe ; 028 rejouée ne change rien.
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


def main():
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('028-equipe-hors-clientele.sql' in etapes, 'l\'étape 028 est dans le noyau')
        for f in etapes:
            if f < '028':
                cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        rapport = lambda: json.loads(q("select logistics.run_migration('équipe')"))['report']   # noqa: E731
        ok(rapport()['ready'] is True, 'au départ : prêt')
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")

        def compte(n, email, confirme='now()'):
            q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
              "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0028-%012d', 'authenticated', 'authenticated', '%s', 'x', %s, '{}')" % (n, email, confirme))
            return '00000000-0000-0000-0028-%012d' % n

        # ============================================================ A. le cas de la production, sans la 028
        futur = compte(1, 'futur-chauffeur@essai.test')
        ok(rapport()['ready'] is True and q("select code is not null from logistics.customer where legacy_client_id = '%s'" % futur) == 't',
           'une nouvelle cliente, recopiée dans le noyau avec son code')
        code, sortie = cl.run('prod', "select public.definir_role('%s', 'employe', array['colis.lire', 'colis.statut'])" % futur, role='authenticated', claims=admin, expect_error=True)
        ok(code == 0 and q("select role || '|' || coalesce(code, '∅') from public.clients where id = '%s'" % futur) == 'employe|∅',
           'la direction la fait entrer dans l\'équipe : l\'ancien schéma lui retire son code client (« l\'équipe n\'est pas la clientèle ») : ' + sortie[-200:])
        r = rapport()
        ok(r['ready'] is False and r['unexplained_by_entity'] == {'mismatch/customer': 1},
           'SANS la 028 : le rattrapage n\'est plus prêt, un écart client inexpliqué (le cas de la production) : %s' % r['unexplained_by_entity'])

        # ============================================================ B. la 028
        cl.run('prod', P.lire_sql('outils/logistique/028-equipe-hors-clientele.sql'))
        r = rapport()
        ok(r['ready'] is True and r['unexplained'] == 0 and r['explained_by_reason'].get('became_staff') == 1,
           'avec la 028 : prêt, l\'écart est expliqué « devenu membre de l\'équipe » : %s' % r['explained_by_reason'])
        ok(q("select source || '|' || (code is not null) from logistics.customer where legacy_client_id = '%s'" % futur) == 'legacy_staff_account|true',
           'la fiche du noyau reste (son ancien code en historique), marquée compte d\'équipe')
        ok(q("select count(*) from logistics.customer where legacy_client_id = '%s'" % futur) == '1', 'rien n\'est supprimé')

        # ============================================================ C. un vrai désaccord reste un écart
        reste = q("select c.id from public.clients c join logistics.customer x on x.legacy_client_id = c.id where c.role = 'client' order by c.id limit 1")
        q("alter table public.clients disable trigger user")
        q("update public.clients set ville = 'Ville changée sans recopie' where id = '%s'" % reste)
        q("alter table public.clients enable trigger user")
        d = cl.lignes('prod', "select kind || '/' || entity || '/' || explained::text from logistics.migration_differences() where legacy_id = '%s'" % reste)
        ok(d == ['mismatch/customer/false'], 'un client RESTÉ client qui diffère : toujours inexpliqué (la 028 n\'excuse que le passage dans l\'équipe) : %s' % d)
        ok(rapport()['ready'] is True, 'et le rattrapage le corrige aussitôt (le noyau suit l\'ancien schéma)')

        # ============================================================ D. bienvenue, rejeu
        equipier = compte(2, 'equipier@essai.test', 'null')
        cl.run('prod', "select public.definir_role('%s', 'employe', array['colis.lire'])" % equipier, role='authenticated', claims=admin)
        q("select logistics.run_migration('équipier')")
        q("update auth.users set email_confirmed_at = now() where id = '%s'" % equipier)
        ok(q("select count(*) from logistics.domain_event e join logistics.customer c on c.id::text = e.aggregate_id "
             "where e.event_type = 'CustomerRegistered' and c.auth_user_id = '%s'" % equipier) == '0', 'un compte d\'équipe n\'est jamais accueilli comme un client')
        avant = q("select count(*) || '/' || string_agg(source, ',' order by id) from logistics.customer")
        cl.run('prod', P.lire_sql('outils/logistique/028-equipe-hors-clientele.sql'))
        ok(q("select count(*) || '/' || string_agg(source, ',' order by id) from logistics.customer") == avant and rapport()['ready'] is True, '028 rejouée : rien ne change')
        print('PASS client devenu membre de l\'équipe (étape 028) : %d vérifications — le cas de la production reproduit puis expliqué, la fiche gardée '
              'et marquée, un vrai écart reste un écart, pas de bienvenue à l\'équipe (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC client devenu membre de l\'équipe (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
