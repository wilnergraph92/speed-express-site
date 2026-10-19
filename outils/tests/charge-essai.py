#!/usr/bin/env python3
"""Essai de charge du noyau — 100, 500 puis 1 000 utilisateurs SIMULTANÉS, sur un PostgreSQL jetable portant les étapes 001 à 029.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/charge-essai.py            # 100, 500, 1000 connexions, 20 s chacune
    SES_CHARGE_PALIERS=100,500 SES_CHARGE_DUREE=10 python3 outils/tests/charge-essai.py

Jamais la production : l'offre gratuite de Supabase sert de vrais clients, et sa limitation de débit (LG007) s'y déclencherait — c'est
voulu. Ce que l'essai mesure, c'est ce que la BASE tient : mêmes fonctions, mêmes droits, mêmes déclencheurs (limitation de débit, recopie,
événements, signal temps réel) qu'en production. Ce qu'il ne mesure PAS : le réseau, PostgREST, le pool de connexions de Supabase, la
diffusion temps réel (Realtime) ni l'envoi des notifications (travailleur non installé) — voir docs/production/GO-LIVE-CERTIFICATE.md.

Chaque utilisateur simulé est une connexion qui enchaîne, au hasard pondéré :
  · 60 % un SUIVI public (visiteur anonyme, numéro et jeton : public.suivre_colis) ;
  · 30 % un SCAN d'entrepôt (un employé distinct par connexion, clé d'idempotence unique : public.lg_scan_parcel), qui écrit un scan, son
    journal et le signal temps réel ;
  · 10 % une lecture du PORTAIL client (public.lg_my_parcels).
Puis l'essai vérifie : aucune transaction en échec, aucun interblocage, chaque scan réussi est écrit une fois et une seule (idempotence),
aucune limitation de débit déclenchée à tort (1 000 employés distincts), la santé et le rattrapage intacts.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]
PALIERS = [int(x) for x in os.environ.get('SES_CHARGE_PALIERS', '100,500,1000').split(',')]
DUREE = int(os.environ.get('SES_CHARGE_DUREE', '20'))


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


SUIVI = """\\set t random(1, :nsuivi)
SET ROLE anon;
SELECT public.suivre_colis(s.numero, s.jeton) FROM bench.suivi s WHERE s.i = :t;
RESET ROLE;
"""
SCAN = """\\set p random(1, 2000)
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', (SELECT id::text FROM bench.staff WHERE n = :client_id % 1000 + 1), false);
SELECT public.lg_scan_parcel('CH-' || lpad(:p::text, 5, '0'), 'lookup', (SELECT id FROM bench.wh), p_idempotency_key => 'charge-' || :client_id || '-' || md5(random()::text || clock_timestamp()::text));
RESET ROLE;
"""
PORTAIL = """\\set c random(1, :nclients)
SET ROLE authenticated;
SELECT set_config('request.jwt.claim.sub', (SELECT id::text FROM bench.clients WHERE n = :c), false);
SELECT public.lg_my_parcels();
RESET ROLE;
"""


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql: cl.un(B, sql)   # noqa: E731
        # assez de connexions pour 1 000 utilisateurs (et un peu de marge pour l'essai lui-même)
        subprocess.run([os.path.join(P.PG, 'pg_ctl'), '-D', cl.donnees, '-l', os.path.join(cl.tmp, 'pg.log'), '-w', '-m', 'fast', '-o',
                        "-p %s -c listen_addresses=127.0.0.1 -c unix_socket_directories='' -c fsync=off -c max_connections=%d -c shared_buffers=256MB"
                        % (cl.port, max(PALIERS) + 30), 'restart'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        P.monter_historique(cl, B)
        ok(int(q('show max_connections')) >= max(PALIERS), 'la base accepte %s connexions' % q('show max_connections'))
        for f_ in sorted(x for x in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', x)):
            cl.run(B, P.lire_sql('outils/logistique/' + f_))
        ok(q("select to_regprocedure('analytics.scheduled_refresh()') is not null") == 't', 'le noyau 001 → 029 est en place')
        # ---- le décor : 1 000 employés distincts, un entrepôt, 2 000 colis à scanner, les suivis publics, des clients du portail
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) "
          "select '00000000-0000-0000-0000-000000000000', ('00000000-0000-0000-0c00-' || lpad(i::text, 12, '0'))::uuid, 'authenticated', 'authenticated', "
          "'charge' || i || '@essai.test', 'x', now(), jsonb_build_object('nom_complet', 'Employé ' || i, 'pays', 'Haïti', 'ville', 'Delmas', 'adresse', 'x', 'telephone', '+509 3000', 'langue', 'fr') "
          "from generate_series(1, 1000) i")
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.statut'] where email like 'charge%@essai.test'")
        rap = json.loads(q("select logistics.run_migration('essai de charge')"))
        ok(rap['report']['ready'] is True, 'rattrapage prêt avec 1 000 employés')
        org = q('select id from logistics.organization')
        q("insert into logistics.branch (organization_id, code, name, kind, country, city) values ('%s', 'MIA', 'Miami', 'office', 'US', 'Miami')" % org)
        q("insert into logistics.warehouse (branch_id, code, name) select id, 'MIA-1', 'Entrepôt Miami' from logistics.branch where code = 'MIA'")
        q("insert into logistics.parcel (organization_id, tracking_number, public_token, destination_country, destination_city, service_mode, status, status_authority, source) "
          "select '%s', 'CH-' || lpad(i::text, 5, '0'), 'tch' || i, 'HT', 'Delmas', 'air', 'CREATED', 'core', 'native' from generate_series(1, 2000) i" % org)
        q("create schema bench; grant usage on schema bench to anon, authenticated;"
          "create table bench.staff as select row_number() over (order by c.email)::int as n, c.id from public.clients c join logistics.app_user u on u.id = c.id where c.email like 'charge%@essai.test';"
          "create table bench.wh as select id from logistics.warehouse where code = 'MIA-1';"
          "create table bench.suivi as select row_number() over (order by numero)::int as i, numero, jeton from public.colis;"
          "create table bench.clients as select row_number() over (order by c.id)::int as n, c.id from public.clients c join logistics.customer k on k.auth_user_id = c.id where c.role = 'client';"
          "grant select on all tables in schema bench to anon, authenticated;")
        nstaff, nsuivi, nclients = int(q('select count(*) from bench.staff')), int(q('select count(*) from bench.suivi')), int(q('select count(*) from bench.clients'))
        ok(nstaff == 1000 and nsuivi > 0 and nclients > 0, 'décor : %d employés, %d colis à suivre, %d clients du portail, 2 000 colis à scanner' % (nstaff, nsuivi, nclients))
        for nom, contenu in (('suivi.sql', SUIVI), ('scan.sql', SCAN), ('portail.sql', PORTAIL)):
            open(os.path.join(cl.tmp, nom), 'w').write(contenu)

        resultats = []
        for c in PALIERS:
            scans0 = int(q('select count(*) from logistics.scan'))
            r = subprocess.run([os.path.join(P.PG, 'pgbench'), '-h', '127.0.0.1', '-p', str(cl.port), '-U', 'postgres', '-n', '-c', str(c), '-j', str(min(c, 32)),
                                '-T', str(DUREE), '-D', 'nsuivi=%d' % nsuivi, '-D', 'nclients=%d' % nclients,
                                '-f', os.path.join(cl.tmp, 'suivi.sql') + '@6', '-f', os.path.join(cl.tmp, 'scan.sql') + '@3', '-f', os.path.join(cl.tmp, 'portail.sql') + '@1', B],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            sortie = r.stdout
            erreurs = [l for l in sortie.splitlines() if re.search(r'ERROR|aborted|FATAL|deadlock', l)]
            tps = float(re.search(r'tps = ([0-9.]+)', sortie).group(1)) if re.search(r'tps = ([0-9.]+)', sortie) else 0
            lat = float(re.search(r'latency average = ([0-9.]+) ms', sortie).group(1)) if re.search(r'latency average', sortie) else None
            faites = int(re.search(r'number of transactions actually processed: (\d+)', sortie).group(1)) if 'actually processed' in sortie else 0
            echecs = int(re.search(r'number of failed transactions: (\d+)', sortie).group(1)) if 'failed transactions' in sortie else 0
            scans_bench = sum(int(x) for x in re.findall(r'SQL script 2: .*?\n.*?- (\d+) transactions', sortie, re.S)[:1])
            scans = int(q('select count(*) from logistics.scan')) - scans0
            resultats.append({'utilisateurs': c, 'transactions': faites, 'tps': round(tps, 1), 'latence_moyenne_ms': lat, 'echecs': echecs,
                              'erreurs': len(erreurs), 'scans_ecrits': scans, 'scans_annonces': scans_bench})
            ok(r.returncode == 0 and not erreurs and echecs == 0, '%d utilisateurs : aucune erreur ni transaction en échec — %s' % (c, (erreurs or [sortie[-400:]])[:3]))
            # pgbench s'arrête à l'heure dite au milieu d'un script : un scan déjà validé peut ne pas compter comme transaction terminée
            # (au plus un par connexion). Les doublons, eux, se vérifient par les clés d'idempotence, plus bas.
            ok(faites > 0 and scans_bench > 0 and scans_bench <= scans <= scans_bench + c,
               '%d utilisateurs : chaque scan terminé est écrit (pgbench %d, base %d, au plus %d en vol à l\'arrêt)' % (c, scans_bench, scans, c))
            print('  %4d utilisateurs : %7.1f transactions/s, latence moyenne %s ms, %d transactions, %d scans écrits, %d échecs'
                  % (c, tps, lat, faites, scans, echecs), flush=True)
        # ---- après la charge : rien de cassé
        ok(q("select count(*) from (select idempotency_key from logistics.scan where idempotency_key like 'charge-%' group by 1 having count(*) > 1) d") == '0',
           'aucun scan en double (clés d\'idempotence uniques)')
        ok(q("select count(*) from ops.rate_counter where hits >= max_hits") == '0', 'aucune limitation de débit déclenchée pour 1 000 employés distincts')
        ok(json.loads(q('select public.ses_health()'))['status'] == 'ok', 'la sonde de santé répond « ok » après la charge')
        ok(json.loads(q("select logistics.run_migration('après la charge')"))['report']['ready'] is True, 'le rattrapage reste prêt après la charge')
        deadlocks = open(os.path.join(cl.tmp, 'pg.log'), encoding='utf-8', errors='replace').read().count('deadlock detected')
        ok(deadlocks == 0, 'aucun interblocage dans le journal de PostgreSQL (%d)' % deadlocks)
        # un employé seul qui scanne comme un robot : la limitation de débit le borne (elle protège, elle n'est pas un bug)
        un = q('select id from bench.staff where n = 1')
        code, texte = cl.run(B, "select count(*) from (select public.lg_scan_parcel('CH-00001', 'lookup', (select id from bench.wh), p_idempotency_key => 'robot-' || g) from generate_series(1, 1300) g) x",
                             role='authenticated', claims=un, expect_error=True)
        ok(code != 0 and 'LG007' in texte, 'un même employé au-delà de 1 200 scans en 10 minutes : refusé (LG007), comme en production')
        open(os.path.join(cl.tmp, 'resultats.json'), 'w').write(json.dumps(resultats))
        print('RESULTATS ' + json.dumps(resultats, ensure_ascii=False))
    print('%d vérifications — charge : %s utilisateurs simultanés tenus par la base, sans erreur, sans doublon, sans interblocage : OK'
          % (N[0], ' / '.join(str(x) for x in PALIERS)))


if __name__ == '__main__':
    main()
