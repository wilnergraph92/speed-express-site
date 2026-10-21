#!/usr/bin/env python3
"""Étape 038 — facturer en gourdes, en dollars ou en pesos, éprouvé sur la RÉPLIQUE DE LA PRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-devises-essai.py

 A. la 038 passe sur la production d'aujourd'hui (001 à 037) : chaque colis existant reste en dollars au taux 1, AUCUNE facture ne
    change d'un centime ; rattrapage prêt, empreinte « parcel_billing » égale ;
 B. un colis en gourdes : la facture naît en HTG, (poids × tarif + 10 $) × taux ; la ligne garde devise, taux et montant en dollars ;
    un prix saisi en pesos : (prix + 10 $) × taux ;
 C. changer le taux ou la devise d'un colis met à jour sa facture impayée ; une facture déjà payée (même en partie) ne bouge jamais ;
 D. la base refuse une devise inconnue, un taux nul, un taux autre que 1 en dollars ; sans « colis.modifier », un employé ne change
    ni la devise ni le taux ;
 E. une facture groupée ne mélange jamais les devises (SE006) ; dans une seule devise, elle passe ;
 F. le noyau reçoit devise et taux par le rattrapage ; un écart se voit, puis se corrige ; 038 rejouée ne change rien ; supabase.sql
    et supabase-maj.sql portent les mêmes fonctions que l'étape.
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


def fonction(texte, nom, dernier=False):
    i = (texte.rindex if dernier else texte.index)('create or replace function %s' % nom)
    return texte[i:texte.index('\n$$;', i) + 4]


def main():
    etape = P.lire_sql('outils/logistique/038-devises.sql')
    for f in ('public.facturer_colis()', 'public.verifier_modification_colis()', 'public.verifier_devise_facture()'):
        ok(fonction(P.lire_sql('outils/supabase.sql'), f) == fonction(etape, f), 'supabase.sql porte la même %s que l\'étape 038' % f)
        ok(fonction(P.lire_sql('outils/supabase-maj.sql'), f, dernier=True) == fonction(etape, f), 'supabase-maj.sql (section 12) aussi : %s' % f)
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('038-devises.sql' in etapes, 'l\'étape 038 est dans le noyau')
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        # La réplique reçoit le supabase-maj.sql d'AUJOURD'HUI (section 12 comprise) ; la vraie production, non : on lui rend son état
        # réel — sans les deux colonnes, avec les fonctions et sans le déclencheur d'avant 038 (dépôt au commit e81ec01).
        avant = P.git_show('outils/supabase.sql', 'e81ec017e537cb02ee6e72f6ba995cd4762d5ef0')
        ok(avant and 'taux_change' not in avant, 'les fonctions d\'avant 038 sont retrouvées dans l\'historique')
        q("drop trigger if exists verifier_devise_facture on public.factures")
        q("drop function if exists public.verifier_devise_facture()")
        q("alter table public.colis drop column if exists devise, drop column if exists taux_change")
        for f in ('public.facturer_colis()', 'public.verifier_modification_colis()'):
            cl.run('prod', fonction(avant, f))
        for f in etapes:
            if f < '038':
                cl.run('prod', P.lire_sql('outils/logistique/' + f))
        rapport = lambda: json.loads(q("select logistics.run_migration('devises')"))['report']   # noqa: E731
        empreinte = lambda: q("select legacy_count || '/' || core_count || '/' || equal from logistics.migration_checksums() where entity = 'parcel_billing'")   # noqa: E731
        factures = lambda: q("select count(*) || ':' || md5(string_agg(id::text || montant::text || frais_service::text || devise || montant_paye::text, ',' order by id)) from public.factures")   # noqa: E731
        ok(rapport()['ready'] is True, 'au départ (001 à 037) : prêt')
        factures_avant = factures()

        # ============================================================ A. la 038
        cl.run('prod', etape)
        ok(q("select count(*) from public.colis where devise <> 'USD' or taux_change <> 1") == '0', 'chaque colis existant : en dollars, au taux 1')
        ok(factures() == factures_avant, 'aucune facture existante ne change d\'un centime')
        r = rapport()
        ok(r['ready'] is True and r['unexplained'] == 0, 'après la 038 : prêt, aucun écart')
        ok(empreinte().endswith('/true'), 'l\'empreinte « parcel_billing » est égale : ' + empreinte())

        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        client = q("select id from public.clients where role = 'client' order by code limit 1")

        def comme(qui, sql, erreur=False):
            code, sortie = cl.run('prod', sql, role='authenticated', claims=qui, expect_error=True)
            ok((code != 0) == erreur, ('refus attendu' if erreur else 'accepté attendu') + ' : ' + sql[:90] + ' → ' + sortie[-220:])
            return sortie

        def colis(desc, poids, tarif, devise, taux, prix='null'):
            comme(admin, "insert into public.colis (client_id, description, poids_lb, tarif_lb, prix_manuel, devise, taux_change) "
                         "values ('%s', '%s', %s, %s, %s, '%s', %s)" % (client, desc, poids, tarif, prix, devise, taux))
            return q("select id from public.colis where description = '%s'" % desc)

        def facture(cid):
            return q("select devise || '|' || montant || '|' || frais_service from public.factures where colis_id = '%s'" % cid)

        # ============================================================ B. la facture dans la devise du colis
        htg = colis('Essai gourdes', 10, 5, 'HTG', 131)
        ok(facture(htg) == 'HTG|7860.00|1310.00', '10 lb × 5 $ = 50 $, + 10 $ de frais = 60 $ × 131 = 7 860 HTG (frais 1 310) : ' + facture(htg))
        ligne = json.loads(q("select lignes -> 0 from public.factures where colis_id = '%s'" % htg))
        ok(ligne['devise'] == 'HTG' and float(ligne['taux_change']) == 131 and float(ligne['montant_usd']) == 50 and float(ligne['montant']) == 6550,
           'la ligne garde devise, taux, montant en dollars et montant converti : %s' % ligne)
        dop = colis('Essai pesos', 3, 0, 'DOP', 58.5, prix=40)
        ok(facture(dop) == 'DOP|2925.00|585.00', 'prix saisi 40 $ + 10 $ = 50 $ × 58,5 = 2 925 DOP : ' + facture(dop))
        usd = colis('Essai dollars', 4, 5, 'USD', 1)
        ok(facture(usd) == 'USD|30.00|10.00', 'en dollars, rien ne change : 4 × 5 + 10 = 30 $')

        # ============================================================ C. la facture suit le colis tant qu'elle est impayée
        comme(admin, "update public.colis set taux_change = 132 where id = '%s'" % htg)
        ok(facture(htg) == 'HTG|7920.00|1320.00', 'nouveau taux : la facture impayée suit (60 × 132) : ' + facture(htg))
        comme(admin, "update public.colis set devise = 'USD', taux_change = 1 where id = '%s'" % dop)
        ok(facture(dop) == 'USD|50.00|10.00', 'le colis repasse en dollars : sa facture aussi : ' + facture(dop))
        comme(admin, "update public.factures set montant_paye = 1000 where colis_id = '%s'" % htg)
        comme(admin, "update public.colis set taux_change = 140 where id = '%s'" % htg)
        ok(facture(htg) == 'HTG|7920.00|1320.00', 'un paiement partiel gèle la facture : le nouveau taux ne la touche plus')

        # ============================================================ D. la base refuse ce qui n'a pas de sens
        comme(admin, "update public.colis set devise = 'EUR' where id = '%s'" % usd, erreur=True)
        sortie = comme(admin, "update public.colis set devise = 'HTG', taux_change = 0 where id = '%s'" % usd, erreur=True)
        ok('colis_taux_change_valide' in sortie, 'un taux nul : refusé par la contrainte')
        comme(admin, "update public.colis set taux_change = 2 where id = '%s'" % usd, erreur=True)
        ok(facture(usd) == 'USD|30.00|10.00', 'et rien n\'a bougé')
        employe = '00000000-0000-0000-0038-000000000001'
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '%s', 'authenticated', 'authenticated', 'employe038@essai.test', 'x', now(), '{}')" % employe)
        comme(admin, "select public.definir_role('%s', 'employe', array['colis.lire', 'colis.statut'])" % employe)
        sortie = comme(employe, "update public.colis set taux_change = 1 where id = '%s'" % htg, erreur=True)
        ok('colis.modifier' in sortie, 'sans « colis.modifier », le taux ne change pas')
        comme(employe, "update public.colis set devise = 'USD', taux_change = 1 where id = '%s'" % htg, erreur=True)

        # ============================================================ E. une facture ne mélange pas les devises
        dop2 = colis('Essai pesos 2', 2, 5, 'DOP', 59)
        htg2 = colis('Essai gourdes 2', 2, 5, 'HTG', 131)
        groupee = "insert into public.factures (client_id, montant, frais_service, devise, lignes, groupee) values ('%s', 1, 1, '%s', '%s'::jsonb, true)"
        sortie = comme(admin, groupee % (client, 'HTG', json.dumps([{'colis_id': htg2}, {'colis_id': dop2}])), erreur=True)
        ok('SE006' in sortie or 'mélange pas les devises' in sortie, 'gourdes et pesos dans une groupée : refusé (SE006)')
        htg3 = colis('Essai gourdes 3', 1, 5, 'HTG', 130)
        comme(admin, groupee % (client, 'HTG', json.dumps([{'colis_id': htg2}, {'colis_id': htg3}])))
        comme(admin, "update public.factures set devise = 'DOP' where groupee and lignes @> '[{\"colis_id\": \"%s\"}]'" % htg3, erreur=True)

        # ============================================================ F. le noyau, l'écart, le rejeu
        ok(rapport()['ready'] is True, 'rattrapage prêt avec des colis en trois devises')
        ok(q("select billing_currency || '|' || exchange_rate from logistics.parcel where legacy_parcel_id = '%s'" % htg) == 'HTG|140.0000',
           'le noyau reçoit la devise et le taux du colis')
        ok(empreinte().endswith('/true'), 'empreinte « parcel_billing » égale')
        q("alter table public.colis disable trigger user")
        q("update public.colis set taux_change = 145 where id = '%s'" % htg)
        q("alter table public.colis enable trigger user")
        d = cl.lignes('prod', "select kind || '/' || entity || '/' || detail from logistics.reconcile_complements() where legacy_id = '%s'" % htg)
        ok(d == ['mismatch/parcel/devise ou taux de facturation différent'], 'la comparaison voit l\'écart : %s' % d)
        ok(rapport()['ready'] is True and empreinte().endswith('/true'), 'le rattrapage le corrige aussitôt')
        etat = q("select md5(string_agg(id::text || devise || taux_change::text, ',' order by id)) from public.colis") + factures()
        cl.run('prod', etape)
        ok(q("select md5(string_agg(id::text || devise || taux_change::text, ',' order by id)) from public.colis") + factures() == etat
           and rapport()['ready'] is True, '038 rejouée : rien ne change')
        print('PASS facturation en trois devises (étape 038) : %d vérifications — colis existants en dollars et factures intactes, facture '
              'convertie au taux (frais compris), suit le colis tant qu\'impayée puis gelée, refus des valeurs sans sens et des droits manquants, '
              'groupée dans une seule devise, noyau tenu à jour, rejeu sans effet (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC facturation en trois devises (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
