#!/usr/bin/env python3
"""L'outil de migration (scripts/migration/migrer.py), éprouvé sur un vrai PostgreSQL jetable — jamais la production.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/migration-essai.py      (age et age-keygen dans le PATH)

On exige :
1. PRÉPRODUCTION : installation, données synthétiques, puis 001 → 021, par l'outil seul ; le journal dit ce qui est passé ;
   l'ordre est imposé (une étape sautée, une étape ancienne rejouée : refusées), la dernière se rejoue ; le plan n'écrit rien ;
2. PRODUCTION (la réplique) : refusée sans sa référence de projet, sans dossier de sauvegardes, en « préproduction », marquée
   « staging » ; puis 001 → 021 avec UNE SAUVEGARDE VÉRIFIÉE AVANT CHAQUE ÉTAPE, le rattrapage prêt à chaque étape dès la 014,
   et aucune donnée de l'espace client changée ;
3. la SAUVEGARDE couvre le noyau : après 021, elle emporte logistics, analytics, ops et le journal, se restaure dans une base
   vide et se valide (empreintes), déclencheurs de la double écriture et temps réel compris ; la base restaurée répond ;
4. un noyau présent sans journal (collé à la main) arrête tout ; Goship est refusé sans connexion ; aucun mot de passe ne sort.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]
MIGRER = os.path.join(P.RACINE, 'scripts', 'migration', 'migrer.py')
RESTAURER = os.path.join(P.RACINE, 'scripts', 'restore', 'restaurer.py')
INTER = os.path.join(P.RACINE, 'scripts', 'exploitation', 'interrupteurs.py')
MDP = 'Mdp-Essai-Migration-42'          # le serveur d'essai ne le demande pas ; il ne doit apparaître dans AUCUNE sortie
NOYAU = sorted(f[:3] for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def url(cl, base):
    return 'postgresql://postgres:%(mdp)s@127.0.0.1:%(port)s/%(base)s' % {'mdp': MDP, 'port': cl.port, 'base': base}


def migrer(cl, base, *args, env=None):
    e = dict(os.environ, SES_DB_URL=url(cl, base), SES_PG_BIN=P.PG, SES_MIGRATION_REF='essai-' + base)
    e.update(env or {})
    r = subprocess.run([sys.executable, MIGRER] + list(args), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, env=e)
    ok(MDP not in r.stdout, 'aucun mot de passe dans la sortie de migrer.py')
    return r.returncode, r.stdout


def refuse(code_texte, mot, msg):
    code, texte = code_texte
    ok(code != 0 and mot in texte, '%s : attendu un refus contenant « %s », obtenu (code %s) : %s' % (msg, mot, code, texte[-300:]))


def journal(cl, base):
    return cl.lignes(base, "select etape || ':' || passages from ses_meta.migration order by etape")


def main():
    if not (shutil.which('age') and shutil.which('age-keygen')):
        print('ÉCHEC : age et age-keygen doivent être dans le PATH.')
        return 1
    tmp = tempfile.mkdtemp(prefix='ses-essai-migration-')
    os.chmod(tmp, 0o700)
    try:
        with P.Cluster() as cl:
            if not P.monter_production(cl, 'prod'):
                print('ATTENTION : historique Git absent — essai sauté.')
                return 0
            # ============================================================ 1. PRÉPRODUCTION
            cl.run('postgres', 'create database stag')
            cl.run('stag', P.lire_sql('scripts/restore/socle-postgres-vide.sql'))
            cl.run('stag', P.AUTH)
            cl.run('stag', P.SUPABASE_DEFAUTS)
            code, texte = migrer(cl, 'stag', '--cible', 'preproduction', '--etape', 'installation')
            ok(code == 0 and 'Plan seulement' in texte and cl.un('stag', "select to_regclass('public.clients') is null") == 't',
               'le plan n\'écrit rien : ' + texte[-200:])
            refuse(migrer(cl, 'stag', '--cible', 'preproduction', '--etape', '001', '--executer'), 'staging', 'le noyau avant l\'installation')
            code, texte = migrer(cl, 'stag', '--cible', 'preproduction', '--etape', 'installation', '--jusqua', 'donnees-synthetiques', '--executer')
            ok(code == 0 and 'MIGRATION OK' in texte, 'installation et données synthétiques : ' + texte[-400:])
            ok(cl.un('stag', 'select nom from ses_meta.environnement') == 'staging' and cl.un('stag', 'select count(*) from public.colis') == '60',
               'préproduction marquée, 60 colis synthétiques')
            ok(journal(cl, 'stag') == ['donnees-synthetiques:1', 'installation:1'], 'le journal dit ce qui est passé : %s' % journal(cl, 'stag'))
            refuse(migrer(cl, 'stag', '--cible', 'preproduction', '--etape', '003', '--executer'), '001, 002', 'une étape sautée')
            ok(cl.un('stag', "select to_regnamespace('logistics') is null") == 't', 'refusée : rien du noyau n\'est passé')
            code, texte = migrer(cl, 'stag', '--cible', 'preproduction', '--etape', '001', '--jusqua', '013', '--executer')
            ok(code == 0 and '"sante": "ok"' in texte, '001 → 013 en préproduction, santé « ok » : ' + texte[-400:])
            code, texte = migrer(cl, 'stag', '--cible', 'preproduction', '--etape', '013', '--executer')
            ok(code == 0 and '013:2' in journal(cl, 'stag'), 'la DERNIÈRE étape se rejoue (013 : deux passages)')
            refuse(migrer(cl, 'stag', '--cible', 'preproduction', '--etape', '012', '--executer'), 'pas sûr', 'une étape ANCIENNE rejouée')
            refuse(migrer(cl, 'stag', '--cible', 'preproduction', '--etape', 'installation', '--executer'), 'déjà passé',
                   'réinstaller l\'espace client par-dessus le noyau')
            code, texte = migrer(cl, 'stag', '--cible', 'preproduction', '--etape', '014', '--jusqua', NOYAU[-1], '--executer')
            ok(code == 0 and '"pret": true' in texte and '"inexpliques": 0' in texte, '014 → %s : rattrapage prêt à chaque étape : %s' % (NOYAU[-1], texte[-500:]))
            ok(len([j for j in journal(cl, 'stag') if re.match(r'\d{3}:', j)]) == len(NOYAU), 'préproduction : les %d étapes au journal' % len(NOYAU))
            ok(cl.un('stag', 'select count(*) from logistics.parcel') == '60', 'les 60 colis synthétiques sont dans le noyau')
            refuse(migrer(cl, 'stag', '--cible', 'production', '--etape', '001', '--executer', '--sauvegardes', tmp, '--reference-projet', '127.0.0.1'),
                   'staging', 'la préproduction prise pour la production')
            # repartir propre (ENVIRONNEMENTS.md §5) : la réinitialisation retire le noyau ET ses lignes du journal ; tout se repasse
            cl.run('stag', P.lire_sql('outils/staging/reinitialiser.sql'))
            ok(journal(cl, 'stag') == ['installation:1'], 'réinitialisée : le journal ne garde que l\'installation (%s)' % journal(cl, 'stag'))
            code, texte = migrer(cl, 'stag', '--cible', 'preproduction', '--etape', 'donnees-synthetiques', '--jusqua', NOYAU[-1], '--executer')
            ok(code == 0 and cl.un('stag', 'select count(*) from logistics.parcel') == '60', 'ressemée et noyau repassé par l\'outil : ' + texte[-300:])

            # ============================================================ 2. PRODUCTION (la réplique)
            prod_ref = ['--reference-projet', '127.0.0.1']
            refuse(migrer(cl, 'prod', '--cible', 'production', '--etape', '001'), 'ne le nomme pas', 'production sans sa référence de projet')
            refuse(migrer(cl, 'prod', '--cible', 'preproduction', '--etape', '001', '--executer'), 'staging', 'la production prise pour la préproduction')
            refuse(migrer(cl, 'prod', '--cible', 'preproduction', '--etape', 'installation', '--executer'), 'production ?', 'installer la préproduction sur la production')
            refuse(migrer(cl, 'prod', '--cible', 'production', '--etape', 'donnees-synthetiques', *prod_ref), 'inconnue', 'des données synthétiques en production')
            refuse(migrer(cl, 'prod', '--cible', 'production', '--etape', '001', '--executer', *prod_ref), '--sauvegardes', 'production sans sauvegarde')
            avant = P.empreintes_historiques(cl, 'prod')
            n_comptes = cl.un('prod', 'select count(*) from auth.users')

            cle = os.path.join(tmp, 'sauvegarde.key')
            subprocess.run(['age-keygen', '-o', cle], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            os.chmod(cle, 0o600)
            publique = re.search(r'public key: (age1\w+)', open(cle).read()).group(1)
            sauvegardes = os.path.join(tmp, 'sauvegardes')
            env_sauv = {'SES_AGE_RECIPIENT': publique, 'SES_VERIF_DB_URL': url(cl, 'postgres')}
            # la base de contrôle doit être LOCALE : une adresse distante est refusée avant la première étape
            refuse(migrer(cl, 'prod', '--cible', 'production', '--etape', '001', '--executer', '--sauvegardes', sauvegardes, *prod_ref,
                          env=dict(env_sauv, SES_VERIF_DB_URL='postgresql://postgres:x@db.exemple.test:5432/postgres')),
                   'LOCAL', 'une base de contrôle distante')
            ok(cl.un('prod', "select to_regnamespace('logistics') is null") == 't', 'refusée : rien n\'est passé')
            code, texte = migrer(cl, 'prod', '--cible', 'production', '--etape', '001', '--jusqua', NOYAU[-1], '--executer', '--sauvegardes', sauvegardes,
                                 *prod_ref, env=env_sauv)
            ok(code == 0 and 'MIGRATION OK' in texte, 'production : 001 → %s par l\'outil : %s' % (NOYAU[-1], texte[-800:]))
            lignes = [json.loads(l) for l in open(os.path.join(sauvegardes, 'journal.jsonl'), encoding='utf-8')]
            ok(len(lignes) == len(NOYAU) and all(l['statut'] == 'ok' and l['verification'] == 'complete' for l in lignes),
               'une sauvegarde VÉRIFIÉE avant chacune des %d étapes (%d au journal)' % (len(NOYAU), len(lignes)))
            ok(lignes[-1]['tables'] > lignes[0]['tables'], 'les sauvegardes d\'après le noyau emportent ses tables (%s → %s tables)'
               % (lignes[0]['tables'], lignes[-1]['tables']))
            resultat = json.loads(texte.split('RESULTAT ', 1)[1].splitlines()[0])
            ok(all(e.get('sauvegarde') for e in resultat['etapes']) and all(e['controle'].get('rattrapage', {}).get('pret') for e in resultat['etapes'][13:]),
               'chaque étape nomme sa sauvegarde ; dès la 014, le rattrapage est prêt')
            ok(P.empreintes_historiques(cl, 'prod') == avant and cl.un('prod', 'select count(*) from auth.users') == n_comptes,
               'l\'espace client (colis, factures, historique, comptes) n\'a pas changé d\'une ligne')
            ok(cl.un('prod', "select count(*) from pg_trigger where tgname = 'lg_double_ecriture'") != '0'
               and cl.un('prod', "select count(*) from logistics.sync_queue") == '0',
               'la double écriture est posée, éteinte : rien n\'est mis en file')
            code, texte = migrer(cl, 'prod', '--cible', 'production', '--etape', '005', '--executer', '--sauvegardes', sauvegardes, *prod_ref, env=env_sauv)
            ok(code != 0 and 'pas sûr' in texte and len(open(os.path.join(sauvegardes, 'journal.jsonl')).readlines()) == len(NOYAU),
               'production : une étape ancienne est refusée AVANT toute sauvegarde ou écriture')

            # ============================================================ 3. la sauvegarde couvre le noyau
            cl.run('postgres', 'create database controle_final')
            r = subprocess.run([sys.executable, os.path.join(P.RACINE, 'scripts', 'backup', 'sauvegarder.py'), '--sortie', sauvegardes, '--exiger-verification'],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                               env=dict(os.environ, SES_DB_URL=url(cl, 'prod'), SES_PG_BIN=P.PG, SES_AGE_RECIPIENT=publique,
                                        SES_VERIF_DB_URL=url(cl, 'controle_final')))
            ok(r.returncode == 0 and 'vérification complete' in r.stdout and 'logistics' in r.stdout,
               'la sauvegarde quotidienne, après le noyau : vérifiée par restauration : ' + r.stdout[-500:])
            archive = sorted(f for f in os.listdir(sauvegardes) if f.endswith('.tar.gz.age'))[-1]
            cl.run('postgres', 'create database restauree')
            r = subprocess.run([sys.executable, RESTAURER, '--archive', os.path.join(sauvegardes, archive), '--identite', cle, '--executer'],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                               env=dict(os.environ, SES_RESTORE_DB_URL=url(cl, 'restauree'), SES_PG_BIN=P.PG))
            ok(r.returncode == 0 and 'VALIDATION OK' in r.stdout, 'restaurée dans une base vide et validée : ' + r.stdout[-500:])
            for t in ('logistics.parcel', 'logistics.domain_event', 'logistics.tracking_event', 'logistics.invoice', 'ses_meta.migration'):
                ok(cl.un('restauree', 'select count(*) from %s' % t) == cl.un('prod', 'select count(*) from %s' % t), 'restaurée : %s complète' % t)
            ok(cl.un('restauree', "select count(*) from pg_trigger where tgname = 'lg_double_ecriture'")
               == cl.un('prod', "select count(*) from pg_trigger where tgname = 'lg_double_ecriture'"), 'restaurée : les déclencheurs de la double écriture')
            ok(json.loads(cl.un('restauree', 'select public.ses_health()'))['status'] == 'ok', 'restaurée : la santé répond « ok »')
            ok(cl.un('restauree', "select count(*) from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'ses_signal'") == '1',
               'restaurée : le signal temps réel du noyau est publié')
            refuse((lambda r: (r.returncode, r.stdout))(subprocess.run(
                [sys.executable, RESTAURER, '--archive', os.path.join(sauvegardes, archive), '--identite', cle],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
                env=dict(os.environ, SES_RESTORE_DB_URL=url(cl, 'restauree'), SES_PG_BIN=P.PG))), 'pas vide', 'restaurer sur une base qui porte déjà le noyau')

            # ============================================================ 3 bis. la recopie (scripts/exploitation/interrupteurs.py)
            def inter(base, *args):
                r = subprocess.run([sys.executable, INTER] + list(args) + ['--reference-projet', '127.0.0.1'], stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, universal_newlines=True, env=dict(os.environ, SES_DB_URL=url(cl, base), SES_PG_BIN=P.PG))
                ok(MDP not in r.stdout, 'aucun mot de passe dans la sortie des interrupteurs')
                return r.returncode, r.stdout
            recopie = lambda: cl.un('prod', "select value from logistics.migration_setting where key = 'double_write'")   # noqa: E731
            refuse(inter('stag', 'etat'), 'production', 'les interrupteurs refusent une préproduction')
            refuse(inter('prod', 'recopie-allumer'), 'planificateur', 'sans planificateur (pg_cron), la recopie ne s\'allume pas')
            ok(recopie() == 'false', 'refusée : l\'interrupteur est resté éteint')
            # pg_cron n'existe pas ici : un planificateur de même forme (cron.job, cron.schedule, cron.unschedule)
            cl.run('prod', "create schema cron; create table cron.job (jobid bigserial primary key, jobname text unique, schedule text, command text, "
                           "active boolean not null default true); "
                           "create function cron.schedule(n text, s text, c text) returns bigint language sql as $f$ insert into cron.job (jobname, schedule, command) "
                           "values (n, s, c) on conflict (jobname) do update set schedule = excluded.schedule, command = excluded.command returning jobid $f$; "
                           "create function cron.unschedule(n text) returns boolean language sql as $f$ delete from cron.job where jobname = n returning true $f$;")
            # le site a écrit depuis la migration : l'allumage doit le rattraper d'abord
            cl.run('prod', "update public.colis set lieu = 'Entrepôt Miami (après migration)' where id = (select id from public.colis order by id limit 1)")
            code, texte = inter('prod', 'recopie-allumer')
            ok(code == 0 and '"recopie": true' in texte, 'recopie allumée : ' + texte[-400:])
            ok(cl.un('prod', "select schedule || ' | ' || command from cron.job where jobname = 'ses-recopie-noyau'") == '* * * * * | select logistics.process_sync_queue()',
               'planifiée chaque minute, dans la base')
            un = cl.un('prod', 'select id from public.colis order by id limit 1')
            cl.run('prod', "update public.colis set statut = 'livre', lieu = 'Livré (recopie)' where id = '%s'" % un)
            ok(cl.un('prod', "select count(*) from logistics.sync_queue where status = 'pending'") != '0', 'une écriture du site entre dans la file')
            ok(json.loads(cl.un('prod', cl.un('prod', "select command from cron.job where jobname = 'ses-recopie-noyau'")))['status'] == 'ok'
               and cl.un('prod', "select count(*) from logistics.sync_queue where status = 'pending'") == '0',
               'la tâche planifiée traite la file')
            ok(json.loads(cl.un('prod', 'select logistics.migration_report()'))['ready'] is True, 'après la recopie : toujours PRÊT (le noyau suit le site)')
            code, texte = inter('prod', 'recopie-eteindre')
            ok(code == 0 and recopie() == 'false' and cl.un('prod', "select count(*) from cron.job") == '0' and int(cl.un('prod', 'select count(*) from logistics.sync_queue')) > 0,
               'éteinte : interrupteur, puis planification retirée ; la file et ses journaux restent')
            # le rapport (lecture seule) : le détail d'un « pas prêt », sans donnée personnelle
            code, texte = inter('prod', 'rapport')
            ok(code == 0 and '"pret": true' in texte and '"ecarts": []' in texte, 'rapport : prêt, aucun écart : ' + texte[-300:])
            cible = cl.un('prod', "select id from public.clients where role = 'client' and coalesce(email, '') <> '' order by id limit 1")
            cl.run('prod', "update public.clients set email = 'nouvelle.adresse@essai.test', telephone = '+509 3700 9876' where id = '%s'" % cible)
            code, texte = inter('prod', 'rapport')
            ok(code == 0 and '"pret": false' in texte and cible in texte, 'rapport : l\'écart de la recopie éteinte, avec l\'identifiant de l\'ancien schéma : ' + texte[-400:])
            ok('nouvelle.adresse@essai.test' not in texte and '3700 9876' not in texte, 'rapport : ni e-mail ni numéro dans la sortie')
            ok('"champs": ["telephone", "email"]' in texte and '"role_ancien": "client"' in texte, 'rapport : quels champs diffèrent (sans leurs valeurs), et le rôle : ' + texte[-500:])
            ok(cl.un('prod', "select count(*) from public.clients where id = '%s' and email = 'nouvelle.adresse@essai.test'" % cible) == '1', 'rapport : rien n\'a été modifié')
            cl.un('prod', "select logistics.run_migration('après le rapport')")

            # ============================================================ 4. le reste des garde-fous
            cl.run('stag', 'drop table ses_meta.migration')
            refuse(migrer(cl, 'stag', '--cible', 'preproduction', '--etape', NOYAU[-1], '--executer'), 'collage à la main',
                   'un noyau présent sans journal')
            code, texte = (lambda r: (r.returncode, r.stdout))(subprocess.run(
                [sys.executable, MIGRER, '--cible', 'preproduction', '--etape', '001'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, env=dict(os.environ, SES_DB_URL='postgresql://postgres:' + MDP + '@db.gpfdyslysqjmojgzggib.supabase.co:5432/postgres')))
            ok(code != 0 and 'Goship' in texte and MDP not in texte, 'Goship refusé sans connexion, sans montrer le mot de passe')
            code, texte = (lambda r: (r.returncode, r.stdout))(subprocess.run(
                [sys.executable, MIGRER, '--cible', 'preproduction', '--etape', '001'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                universal_newlines=True, env=dict(os.environ, SES_DB_URL='postgresql://postgres:' + MDP + '@db.ltbqqchtyzlyakcsxxis.supabase.co:5432/postgres')))
            ok(code != 0 and 'PRODUCTION' in texte, 'la production visée comme préproduction : refusée sans connexion')

            print('PASS migration du noyau : %d vérifications — préproduction (installation, données, 001 → %s), production rejouée avec une '
                  'sauvegarde vérifiée avant chaque étape, ordre imposé, rattrapage prêt, espace client intact, sauvegarde et restauration '
                  'du noyau, garde-fous (PostgreSQL %s).' % (N[0], NOYAU[-1], cl.un('postgres', 'show server_version')))
            return 0
    except AssertionError as e:
        print('ÉCHEC migration du noyau (après %d vérifications) : %s' % (N[0], e))
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


sys.exit(main())
