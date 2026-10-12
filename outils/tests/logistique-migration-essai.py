#!/usr/bin/env python3
"""Phase 2 — la migration continue de l'ancien schéma vers le noyau (étape 014), sur la RÉPLIQUE DE LA PRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-migration-essai.py

La base de départ est celle de la production telle que sondée les 7 et 8 octobre 2026, remède de la phase 1 compris, avec
ce qu'elle a gagné depuis (prix saisis, pré-alertes, une facture groupée qui a remplacé des factures individuelles), et les
droits par défaut de Supabase. On y passe 001 → 014, puis on exige :
 1. installation : l'ancien schéma est intact ; rien n'est copié en collant ; la double écriture est ÉTEINTE ;
 2. rattrapage tracé : prêt, zéro écart, empreintes égales pour chaque entité, compteurs exacts ; rejoué : 0 / 0 partout ;
 3. dérive sans double écriture : visible dans le rapport, la double écriture refuse de s'allumer (LG010) ; un rattrapage
    la résorbe, les lignes disparues de l'ancien schéma sont MARQUÉES (jamais effacées) et comptées comme expliquées ;
 4. double écriture : chaque écriture de l'ancien schéma (y compris d'un client connecté, sous ses règles) arrive dans la
    file ; le traitement remet tout d'accord ; éteinte, plus rien n'est déposé ;
 5. échecs : une erreur du noyau ne bloque JAMAIS une écriture du site ; la file retente avec un délai, passe en « dead »
    après 8 échecs, repart après correction ; même le dépôt dans la file peut échouer sans rien bloquer ;
 6. écart examiné : une explication écrite le fait passer d'« inexpliqué » à « expliqué » ;
 7. sécurité : rien de tout cela n'est accessible à un visiteur ni à un compte connecté ;
 8. retour en arrière : éteindre, puis retirer le noyau ; l'ancien schéma reste intact et continue de fonctionner.
Jamais la production."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]
ETAPES = ['001-modele-de-domaine.sql', '002-retroremplissage.sql', '003-machine-d-etats.sql', '004-entrepot.sql', '005-transport-douane.sql',
          '006-dernier-kilometre.sql', '007-finance.sql', '008-portail-client.sql', '009-centre-de-commande.sql', '010-notifications.sql',
          '011-applications.sql', '012-analytique.sql', '013-exploitation.sql', '014-migration-continue.sql']


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def main():
    with P.Cluster() as cl:
        B = 'prod'
        if not P.monter_production(cl, B):
            print('ATTENTION : historique Git absent (clone superficiel) — réplique de la production impossible ; essai sauté.')
            return 0
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        js = lambda sql: json.loads(q(sql))   # noqa: E731
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        ok(q("select count(*) from public.prealertes") != '0' and q("select count(*) from public.factures where groupee") == '2'
           and q("select count(*) from public.colis where prix_manuel is not null") == '7',
           'réplique : pré-alertes, facture groupée et prix saisis présents, comme en production')
        avant = P.empreintes_historiques(cl, B)

        # ------------------------------------------------------------------ 1. installation
        for f in ETAPES:
            cl.run(B, P.lire_sql('outils/logistique/' + f))
        cl.run(B, P.lire_sql('outils/logistique/014-migration-continue.sql'))   # la dernière étape se rejoue sans risque
        ok(P.empreintes_historiques(cl, B) == avant, '001 → 014 : l\'ancien schéma est intact (empreinte de chaque table)')
        ok(q("select count(*) from logistics.parcel") == '0' and q("select count(*) from logistics.pre_alert") == '0', 'coller les étapes ne copie rien')
        ok(q("select value from logistics.migration_setting where key = 'double_write'") == 'false', 'la double écriture est ÉTEINTE à l\'installation')
        ok(q("select count(*) from pg_trigger where tgname = 'lg_double_ecriture'") == '6', 'six déclencheurs posés sur l\'ancien schéma (muets)')
        q("update public.colis set note = 'écrit avant le rattrapage' where id = (select id from public.colis order by numero limit 1)",
          role='authenticated', claims=admin)
        ok(q("select count(*) from logistics.sync_queue") == '0', 'éteinte, la double écriture ne dépose rien')
        r = js("select logistics.migration_report()")
        ok(r['ready'] is False and r['unexplained'] > 600, 'avant rattrapage : pas prêt, tout manque (%d écarts)' % r['unexplained'])

        # ------------------------------------------------------------------ 2. rattrapage tracé
        avant = P.empreintes_historiques(cl, B)   # après l'écriture d'essai ci-dessus : c'est l'état que le rattrapage doit laisser intact
        run = js("select logistics.run_migration('essai : premier rattrapage')")
        rap = run['report']
        ok(run['status'] == 'ok' and run['attempts'] == 1 and run['error'] is None, 'rattrapage réussi du premier coup')
        ok(rap['ready'] is True and rap['unexplained'] == 0 and rap['checksum_unexplained'] == [], 'PRÊT : zéro écart inexpliqué, aucune empreinte inexpliquée')
        ent = rap['checksums']
        ok(set(ent) == {'customer', 'app_user', 'parcel', 'tracking_event', 'invoice', 'pre_alert', 'device'}, 'sept entités empreintes')
        for e, v in ent.items():
            ok(v['equal'] and v['legacy'] == v['core'], '%s : %d lignes des deux côtés, même empreinte' % (e, v['legacy']))
        c = run['counters']
        ok(c['parcel']['inserted'] == int(q('select count(*) from public.colis')) and c['invoice']['inserted'] == int(q('select count(*) from public.factures'))
           and c['tracking_event']['inserted'] == int(q('select count(*) from public.colis_historique'))
           and c['pre_alert']['inserted'] == int(q('select count(*) from public.prealertes')),
           'compteurs exacts : colis, factures, historique, pré-alertes')
        ok(c['parcel_manual_price']['updated'] == 7 and c['app_user_staff_code']['updated'] == int(q("select count(*) from public.clients where role <> 'client'")),
           'compléments : 7 prix saisis, un identifiant d\'équipe par membre')
        ok(q("select count(*) from logistics.parcel where manual_price = 25") == '7'
           and q("select string_agg(split_part(staff_code, '-', 1), ',' order by staff_code) from logistics.app_user") ==
           q("select string_agg(split_part(matricule, '-', 1), ',' order by matricule) from public.clients where role <> 'client'"),
           'prix saisis et identifiants d\'équipe dans le noyau')
        ok(q("select count(*) from logistics.pre_alert where status = 'RECEIVED'") == '1' and q("select count(*) from logistics.pre_alert where status = 'CANCELLED'") == '1',
           'statuts des pré-alertes traduits')
        ok(q("select count(*) from logistics.invoice where is_grouped") == '2', 'les factures groupées sont copiées comme telles')
        ok(q("select count(*) from logistics.parcel where public_token is null or public_token = tracking_number") == '0',
           'chaque colis : un numéro public ET un jeton séparé')
        ok(q("select count(*) from logistics.parcel where currency <> 'USD'") == '0', 'devise explicite sur chaque colis (USD, celle du site)')
        ok(P.empreintes_historiques(cl, B) == avant, 'le rattrapage n\'a rien modifié dans l\'ancien schéma (lecture seule)')
        run2 = js("select logistics.run_migration('essai : rejeu')")
        ok(all(v['inserted'] == 0 and v['updated'] == 0 for v in run2['counters'].values()), 'rejoué : 0 inséré, 0 modifié, partout (idempotent)')
        ok(q("select count(*) || '/' || count(*) filter (where status = 'ok' and ready) from logistics.migration_run") == '2/2',
           'deux exécutions journalisées, prêtes')
        code, texte = cl.run(B, "update logistics.migration_run set status = 'ok'", expect_error=True)
        ok(code != 0, 'le journal des exécutions ne se réécrit pas')

        # ------------------------------------------------------------------ 3. dérive sans double écriture
        grp_client = q("select client_id from public.factures where groupee and note = 'Facture groupée (essai)'")
        q("set session_replication_role = default; "
          "select set_config('request.jwt.claim.sub', '%s', false); "
          "update public.colis set statut = 'expedie', lieu = 'Miami — départ' where id = (select id from public.colis where statut = 'confirme' order by numero limit 1); "
          "update public.factures set montant_paye = montant where id = (select id from public.factures where montant_paye = 0 and not groupee order by numero limit 1); "
          "delete from public.factures where id = (select id from public.factures where montant_paye = 0 and colis_id is not null and client_id <> '%s' order by numero limit 1);"
          % (admin, grp_client))
        q("insert into public.prealertes (client_id, magasin, contenu, valeur, service) select id, 'Walmart', 'Dérive', 10, 'aerien' "
          "from public.clients where role = 'client' order by email limit 1")
        r = js("select logistics.migration_report()")
        ok(r['ready'] is False and r['unexplained'] >= 4, 'sans double écriture, la dérive est VISIBLE (%d écarts : %s)' % (r['unexplained'], r['unexplained_by_entity']))
        code, texte = cl.run(B, "select logistics.set_double_write(true)", expect_error=True)
        ok(code != 0 and 'LG010' in texte, 'la double écriture REFUSE de s\'allumer sur une migration qui n\'est pas prête')
        rap = js("select logistics.run_migration('essai : rattraper la dérive')")['report']
        ok(rap['ready'] is True and rap['unexplained'] == 0, 'un rattrapage résorbe la dérive')
        ok(rap['explained_by_reason'].get('legacy_deleted', 0) == 1 and rap['checksums']['invoice']['core_legacy_deleted'] == 1,
           'la facture effacée de l\'ancien schéma est MARQUÉE dans le noyau (expliquée : legacy_deleted), jamais effacée')
        ok(q("select count(*) from logistics.invoice where legacy_deleted_at is not null") == '1', 'elle y est toujours')

        # ------------------------------------------------------------------ 4. double écriture
        ok(js("select logistics.set_double_write(true)")['double_write'] is True, 'migration prête : la double écriture s\'allume')
        q("insert into public.colis (client_id, description, poids_lb, tarif_lb, pays_destination, service) select id, 'double écriture', 3, 4, 'DO', 'maritime' "
          "from public.clients where role = 'client' order by email limit 1", role='authenticated', claims=admin)
        q("update public.colis set statut = 'disponible', lieu = 'Santo Domingo' where description = 'double écriture'", role='authenticated', claims=admin)
        q("update public.colis set prix_manuel = 30 where description = 'double écriture'", role='authenticated', claims=admin)
        client = q("select id from public.clients where role = 'client' order by email limit 1")
        q("insert into public.prealertes (client_id, magasin, contenu, service) values ('%s', 'Amazon', 'par le client lui-même', 'aerien')" % client,
          role='authenticated', claims=client)
        q("update public.clients set telephone = '+509 0000 0001' where id = '%s'" % client, role='authenticated', claims=client)
        ok(int(q("select count(*) from logistics.sync_queue where status = 'pending'")) >= 6,
           'chaque écriture, même d\'un client connecté sous ses propres règles, est déposée dans la file')
        ok(js("select logistics.migration_report()")['ready'] is False, 'tant que la file n\'est pas traitée, le rapport le dit')
        t = js("select logistics.process_sync_queue()")
        ok(t['status'] == 'ok' and t['processed'] >= 6 and t['ready'] is True, 'la file traitée : tout est d\'accord (%d lignes)' % t['processed'])
        ok(q("select manual_price || '/' || legacy_status from logistics.parcel where description = 'double écriture'") == '30.00/disponible',
           'le colis du site est dans le noyau, avec son prix saisi et son statut')
        ok(q("select count(*) from logistics.tracking_event e join logistics.parcel p on p.id = e.parcel_id where p.description = 'double écriture'") == '2',
           'et son historique')
        ok(js("select logistics.process_sync_queue()")['status'] == 'idle', 'file vide : rien à faire')

        # ------------------------------------------------------------------ 5. échecs, nouvelles tentatives, file des échecs
        q("alter table logistics.parcel add constraint essai_panne check (description <> 'PANNE')")   # une panne du noyau, simulée
        q("insert into public.colis (client_id, description, poids_lb, tarif_lb, pays_destination, service) select id, 'PANNE', 1, 1, 'HT', 'aerien' "
          "from public.clients where role = 'client' order by email limit 1", role='authenticated', claims=admin)
        ok(q("select count(*) from public.colis where description = 'PANNE'") == '1', 'le noyau en panne ne bloque PAS l\'écriture du site')
        t = js("select logistics.process_sync_queue()")
        ok(t['status'] == 'failed' and 'essai_panne' in t['error'], 'le traitement échoue et dit pourquoi')
        ok(q("select attempts || '/' || status || '/' || (next_try_at > clock_timestamp()) from logistics.sync_queue where status = 'pending' order by id desc limit 1") == '1/pending/true',
           'la ligne est replanifiée plus tard (1 tentative)')
        ok(q("select status from logistics.migration_run order by id desc limit 1") == 'failed', 'l\'échec est journalisé')
        ok(js("select logistics.process_sync_queue()")['status'] == 'idle', 'avant son heure, la ligne n\'est pas retentée')
        q("update logistics.sync_queue set attempts = 7, next_try_at = clock_timestamp() where status = 'pending'")
        js("select logistics.process_sync_queue()")
        ok(q("select count(*) from logistics.sync_queue where status = 'dead'") != '0', 'après 8 échecs : file des échecs (« dead »)')
        ok(js("select logistics.migration_report()")['sync_queue']['dead'] > 0, 'le rapport la montre')
        q("alter table logistics.parcel drop constraint essai_panne")   # la panne est réparée
        ok(int(q("select logistics.retry_dead_sync()")) > 0, 'une seconde chance après correction')
        t = js("select logistics.process_sync_queue()")
        ok(t['status'] == 'ok' and t['ready'] is True and q("select count(*) from logistics.parcel where description = 'PANNE'") == '1',
           'la ligne repart, le colis arrive, tout est d\'accord')
        # même le DÉPÔT dans la file peut échouer : le site n'en sait rien
        q("alter table logistics.sync_queue add constraint essai_depot check (table_name <> 'colis') not valid")
        q("update public.colis set note = 'dépôt en panne' where description = 'PANNE'", role='authenticated', claims=admin)
        ok(q("select note from public.colis where description = 'PANNE'") == 'dépôt en panne', 'la file elle-même en panne ne bloque pas le site')
        ok(q("select count(*) from logistics.sync_failure where table_name = 'colis'") == '1', 'l\'incident est consigné (sync_failure)')
        q("alter table logistics.sync_queue drop constraint essai_depot")
        ok(js("select logistics.run_migration('rattrapage après incident de dépôt')")['report']['ready'] is True,
           'un rattrapage complet rattrape ce que la file n\'a pas reçu')

        # ------------------------------------------------------------------ 6. écart examiné
        cible = q("select legacy_client_id from logistics.customer where legacy_client_id is not null order by legacy_client_id limit 1")
        q("update logistics.customer set full_name = 'Nom corrigé dans le noyau' where legacy_client_id = '%s'" % cible)
        r = js("select logistics.migration_report()")
        ok(r['ready'] is False and r['unexplained'] == 1 and r['unexplained_by_entity'] == {'mismatch/customer': 1} and r['checksum_unexplained'] == ['customer'],
           'un écart de champ : inexpliqué, nommé, et l\'empreinte des clients le confirme')
        code, texte = cl.run(B, "select logistics.explain_difference('mismatch', 'customer', '%s', 'court')" % cible, expect_error=True)
        ok(code != 0, 'une explication sans vraie raison est refusée')
        q("select logistics.explain_difference('mismatch', 'customer', '%s', 'Le client a demandé la correction de son nom ; reporter dans l''ancien schéma.')" % cible)
        r = js("select logistics.migration_report()")
        ok(r['ready'] is True and r['unexplained'] == 0 and r['checksum_unexplained'] == [] and r['explained_by_reason'].get('owner_reviewed') == 1,
           'expliqué par écrit : prêt, l\'écart reste visible avec sa raison')
        js("select logistics.run_migration('rétablir')")

        # ------------------------------------------------------------------ 7. sécurité
        for role in ('anon', 'authenticated'):
            for fn in ('run_migration(text)', 'migration_report()', 'process_sync_queue(integer)', 'set_double_write(boolean)', 'backfill_complements()',
                       'explain_difference(text,text,text,text)', 'retry_dead_sync()', 'migration_checksums()', 'enqueue_legacy_change()'):
                ok(q("select has_function_privilege('%s', 'logistics.%s', 'execute')" % (role, fn)) == 'f', '%s n\'exécute pas %s' % (role, fn))
            ok(q("select has_schema_privilege('%s', 'logistics', 'usage')" % role) == 'f', '%s n\'entre pas dans le schéma logistics' % role)

        # ------------------------------------------------------------------ 4bis. éteinte : plus rien
        js("select logistics.set_double_write(false)")
        n_file = q("select count(*) from logistics.sync_queue")
        q("update public.colis set note = 'après extinction' where description = 'PANNE'", role='authenticated', claims=admin)
        ok(q("select count(*) from logistics.sync_queue") == n_file, 'éteinte : plus aucun dépôt')

        # ------------------------------------------------------------------ 8. retour en arrière
        avant_retrait = P.empreintes_historiques(cl, B)
        cl.run(B, "drop schema analytics cascade; drop schema ops cascade; drop schema logistics cascade;")
        ok(q("select count(*) from pg_trigger where tgname = 'lg_double_ecriture'") == '0', 'retrait du noyau : ses déclencheurs partent avec lui')
        ok(P.empreintes_historiques(cl, B) == avant_retrait, 'retrait du noyau : l\'ancien schéma est intact')
        q("insert into public.colis (client_id, description, poids_lb, tarif_lb, pays_destination, service) select id, 'après retrait', 2, 3, 'HT', 'aerien' "
          "from public.clients where role = 'client' order by email limit 1", role='authenticated', claims=admin)
        ok(q("select count(*) from public.factures f join public.colis c on c.id = f.colis_id where c.description = 'après retrait'") == '1',
           'et le site continue de fonctionner (colis enregistré, facture créée par la base)')

        print('PASS migration continue (phase 2) : %d vérifications — réplique de la production, 001 → 014 sans toucher à l\'ancien schéma, rattrapage tracé '
              'prêt (zéro écart, sept empreintes égales) et idempotent, dérive visible puis résorbée, suppressions marquées jamais effacées, double écriture '
              'par file (y compris sous les règles d\'un client), pannes du noyau et de la file sans effet sur le site, nouvelles tentatives et file des '
              'échecs, écart expliqué par écrit, fermé aux visiteurs et aux comptes, retour en arrière sans dommage (PostgreSQL %s).'
              % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC migration continue (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
