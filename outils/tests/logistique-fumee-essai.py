#!/usr/bin/env python3
"""Toutes les lectures du noyau, appelées une fois sur le noyau COMPLET — le filet que les essais par phase n'étendent pas.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-fumee-essai.py

Chaque essai de phase éprouve SES fonctions juste après SON étape. Une étape plus récente peut pourtant casser une fonction plus
ancienne sans qu'aucun essai ne la rappelle : le 13 octobre 2026, l'étape 016 a ajouté planned_arrival_at aux expéditions, et le flux
du centre de commande (009), qui prenait « s.* » ET la même colonne du transport, a répondu « column reference is ambiguous » en
production. Ici, sur la réplique de la production, avec 001 → la dernière étape et le rattrapage prêt :

  · chaque fonction publique lg_* dont tous les paramètres ont une valeur par défaut est appelée par un administrateur, un gérant,
    un employé (colis.lire) et un client ; elle doit répondre, ou refuser par un code MÉTIER (droit, état) — jamais une erreur de SQL
    (colonne ambiguë ou absente, type, fonction introuvable…) ;
  · l'administrateur, qui a tous les droits, doit obtenir une réponse de chacune des lectures de l'équipe.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]
# Les refus permis : droits (42501, LG003), règles métier du noyau (LG0xx), données de l'ancien schéma (SE0xx). Tout autre code est
# une faute de SQL : 42702 ambiguë, 42703 colonne absente, 42883 fonction absente, 42804 / 22P02 type, XX000…
REFUS_METIER = re.compile(r'ERROR:\s+(42501|LG\d{3}|SE\d{3}|P0001)\b')


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
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        ok(json.loads(q("select logistics.run_migration('fumée')"))['report']['ready'] is True, 'noyau complet (%s étapes), rattrapage prêt' % len(etapes))
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0009-000000000001', 'authenticated', 'authenticated', 'fumee-emp@essai.test', 'x', now(), "
          "'{\"nom_complet\": \"Employé fumée\"}')")
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire'] where email = 'fumee-emp@essai.test'")
        q("select logistics.run_migration('fumée, employé')")
        acteurs = {
            'administrateur': q("select id from public.clients where role = 'admin' order by email limit 1"),
            'gérant': q("select id from public.clients where role = 'gerant' order by email limit 1"),
            'employé': q("select id from public.clients where email = 'fumee-emp@essai.test'"),
            'client': q("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1"),
        }
        # Les lectures : tous paramètres par défaut, ouvertes aux comptes connectés. Les écritures (lg_scan_parcel, lg_mobile_command…) ont
        # des paramètres obligatoires : elles ne sont pas ici, leurs essais de phase les éprouvent.
        fonctions = cl.lignes('prod', "select p.proname from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname like 'lg\\_%' "
                                      "and p.pronargs = p.pronargdefaults and has_function_privilege('authenticated', p.oid, 'execute') order by 1")
        ok(len(fonctions) >= 40, '%d lectures du noyau à appeler' % len(fonctions))
        fautes, repondues = [], {}
        for nom in fonctions:
            for qui, uid in acteurs.items():
                code, sortie = cl.run('prod', 'select public.%s()' % nom, role='authenticated', claims=uid, expect_error=True)
                if code == 0:
                    repondues.setdefault(qui, set()).add(nom)
                elif not REFUS_METIER.search(sortie):
                    fautes.append('%s (%s) : %s' % (nom, qui, sortie.strip().splitlines()[0][:200]))
        ok(not fautes, '%d erreur(s) de SQL :\n  - %s' % (len(fautes), '\n  - '.join(fautes)))
        equipe = [f for f in fonctions if not f.startswith(('lg_my_', 'lg_register', 'lg_unregister', 'lg_mark_notifications', 'lg_chat_open_customer'))]   # celles-là sont du client (032 : sans paramètre, SA conversation)
        sans = sorted(set(equipe) - repondues.get('administrateur', set()))
        ok(not sans, 'l\'administrateur obtient une réponse de chaque lecture de l\'équipe (refusées : %s)' % sans)
        print('PASS lectures du noyau complet : %d vérifications — %d fonctions × 4 comptes sur la réplique, 001 → %s : aucune erreur de SQL, '
              'l\'administrateur lit tout (PostgreSQL %s).' % (N[0], len(fonctions), etapes[-1][:3], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC lectures du noyau complet (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
