#!/usr/bin/env python3
"""Les fichiers SQL du projet se REJOUENT sans rien changer, dans n'importe quel ordre raisonnable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/schema-rejouable.py

Constat à l'origine de ce test (phase 1) : supabase.sql, présenté comme « à relancer après chaque
mise à jour », recréait une ancienne version de suivre_colis à côté de la nouvelle, et PostgreSQL
répondait « is not unique » : le suivi public cessait de fonctionner. Ici, on empreinte TOUT le
schéma public (fonctions, droits, règles, déclencheurs, vues, colonnes), puis on rejoue chaque fichier
et on exige que rien n'ait bougé. Sur un vrai PostgreSQL jetable, jamais la production."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

CATALOGUE = P.CATALOGUE

ORDRE = ['supabase.sql', 'supabase-maj-facture-groupee.sql', 'supabase-maj-jeton.sql', 'supabase-dashboard.sql', 'supabase-maj.sql', 'supabase-maj-numeros.sql', 'supabase-maj-prix-prealertes.sql', 'supabase-maj-equipe.sql', 'supabase-maj-securite.sql']


def empreinte(cl, base):
    return set(cl.lignes(base, CATALOGUE))


def main():
    with P.Cluster() as cl:
        cl.run('postgres', 'create database ses')
        cl.run('ses', P.lire_sql('scripts/restore/socle-postgres-vide.sql'))
        cl.run('ses', P.AUTH)
        cl.run('ses', P.SUPABASE_DEFAUTS)   # comme un vrai projet : tout objet nouveau est ouvert d'office
        for f in ORDRE:
            cl.run('ses', P.lire_sql('outils/' + f))
        base = empreinte(cl, 'ses')
        n = 0
        # 1. chaque fichier, rejoué APRÈS tous les autres : rien ne doit changer
        for f in ORDRE:
            cl.run('ses', P.lire_sql('outils/' + f))
            apres = empreinte(cl, 'ses')
            if apres != base:
                en_plus, en_moins = sorted(apres - base), sorted(base - apres)
                print('ÉCHEC rejeu de %s : le schéma a changé.' % f)
                for l in en_moins[:6]: print('   - avant :', l[:170])
                for l in en_plus[:6]: print('   + après :', l[:170])
                return 1
            n += 1
        # 2. le suivi public existe en UN exemplaire, appelable avec le seul numéro (le défaut d'origine)
        ok = cl.un('ses', "select count(*) from pg_proc where proname = 'suivre_colis' and pronamespace = 'public'::regnamespace")
        assert ok == '1', 'suivre_colis en %s exemplaires' % ok
        cl.un('ses', "select public.suivre_colis('SES-10001-HT')")
        cl.un('ses', "select public.suivre_colis(p_numero => 'SES-10001-HT')")
        cl.un('ses', "select public.suivre_colis(p_numero => 'SES-10001-HT', p_jeton => 'x')")
        n += 3
        # 3. le même chemin dans l'ordre inverse des migrations (production ancienne puis nouveau schéma)
        cl.run('postgres', 'create database ses2')
        cl.run('ses2', P.lire_sql('scripts/restore/socle-postgres-vide.sql')); cl.run('ses2', P.AUTH); cl.run('ses2', P.SUPABASE_DEFAUTS)
        for f in ['supabase.sql', 'supabase-maj-securite.sql', 'supabase-maj-equipe.sql', 'supabase-maj-prix-prealertes.sql', 'supabase-maj-numeros.sql', 'supabase-maj.sql', 'supabase-dashboard.sql', 'supabase-maj-jeton.sql', 'supabase-maj-facture-groupee.sql']:
            cl.run('ses2', P.lire_sql('outils/' + f))
        if empreinte(cl, 'ses2') != base:
            diff = sorted(empreinte(cl, 'ses2') ^ base)
            print('ÉCHEC : un autre ordre de passage donne un autre schéma (%d écarts) ; ex. %s' % (len(diff), diff[0][:160]))
            return 1
        n += 1
        print('PASS schéma rejouable : %d vérifications — chaque fichier SQL rejoué après tous les autres ne change RIEN (%d éléments empreints : fonctions, droits, règles, '
              'déclencheurs, vues, colonnes), un seul suivi public, deux ordres de passage équivalents.' % (n, len(base)))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC schéma rejouable :', e); sys.exit(1)
