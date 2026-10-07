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

CATALOGUE = """
select 'fonction ' || p.oid::regprocedure::text || ' ' || md5(pg_get_functiondef(p.oid)) || ' ' || coalesce(p.proacl::text, '')
  from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'public'
union all select 'colonne ' || table_name || '.' || column_name || ' ' || data_type || ' ' || coalesce(column_default, '') || ' ' || is_nullable
  from information_schema.columns where table_schema = 'public'
union all select 'politique ' || tablename || '.' || policyname || ' ' || cmd || ' ' || coalesce(qual, '') || ' ' || coalesce(with_check, '') || ' ' || roles::text
  from pg_policies where schemaname = 'public'
union all select 'declencheur ' || pg_get_triggerdef(t.oid) from pg_trigger t join pg_class c on c.oid = t.tgrelid
  where c.relnamespace = 'public'::regnamespace and not t.tgisinternal
union all select 'declencheur auth ' || pg_get_triggerdef(t.oid) from pg_trigger t join pg_class c on c.oid = t.tgrelid
  where c.relnamespace = 'auth'::regnamespace and not t.tgisinternal
union all select 'vue ' || viewname || ' ' || md5(definition) from pg_views where schemaname = 'public'
union all select 'contrainte ' || conrelid::regclass::text || ' ' || conname || ' ' || pg_get_constraintdef(oid)
  from pg_constraint where connamespace = 'public'::regnamespace
union all select 'droit table ' || grantee || ' ' || table_name || ' ' || privilege_type
  from information_schema.role_table_grants where table_schema = 'public'
union all select 'droit colonne ' || grantee || ' ' || table_name || '.' || column_name || ' ' || privilege_type
  from information_schema.role_column_grants where table_schema = 'public' and grantee in ('anon', 'authenticated')
union all select 'rls ' || relname || ' ' || relrowsecurity::text from pg_class where relnamespace = 'public'::regnamespace and relkind = 'r'
order by 1
"""

ORDRE = ['supabase.sql', 'supabase-maj-facture-groupee.sql', 'supabase-maj-jeton.sql', 'supabase-dashboard.sql', 'supabase-maj.sql', 'supabase-maj-numeros.sql']


def empreinte(cl, base):
    return set(cl.lignes(base, CATALOGUE))


def main():
    with P.Cluster() as cl:
        cl.run('postgres', 'create database ses')
        cl.run('ses', P.lire_sql('scripts/restore/socle-postgres-vide.sql'))
        cl.run('ses', P.AUTH)
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
        cl.run('ses2', P.lire_sql('scripts/restore/socle-postgres-vide.sql')); cl.run('ses2', P.AUTH)
        for f in ['supabase.sql', 'supabase-maj-numeros.sql', 'supabase-maj.sql', 'supabase-dashboard.sql', 'supabase-maj-jeton.sql', 'supabase-maj-facture-groupee.sql']:
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
