#!/usr/bin/env python3
"""Étape 023 — les agences, les entrepôts et leurs emplacements, saisis par la direction, éprouvés sur la RÉPLIQUE DE LA PRODUCTION.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-sites-essai.py

La production n'a aucune agence ni aucun entrepôt (l'ancien schéma n'en a jamais eu, la migration n'en invente pas). On exige :
 A. la direction crée une agence, un entrepôt, un emplacement ; chacun est tracé (audit avant / après) et relu par lg_sites, avec ses
    identifiants ; un employé lit, mais ne crée rien (LG003) ; un client ne lit rien ;
 B. les données refusées : code illisible, code déjà pris, pays ou genre inconnu, nom vide, entrepôt dans une agence inactive ;
 C. les modifications : nom, genre, ville, actif — jamais le code ni le pays ; un HUB qui attend des expéditions reste un HUB ;
 D. ce qui en dépend fonctionne enfin : le poste de scan REÇOIT un colis dans l'entrepôt créé ; on ne désactive ni l'entrepôt ni
    l'emplacement qui gardent ce colis ;
 E. rien d'ouvert aux visiteurs ; 023 rejouée ne change rien.
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


def val(v):
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    return "'%s'" % str(v).replace("'", "''")


def main():
    with P.Cluster() as cl:
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('023-agences-entrepots.sql' in etapes, 'l\'étape 023 est dans le noyau')
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        ok(json.loads(q("select logistics.run_migration('agences')"))['report']['ready'] is True, 'rattrapage prêt')
        ok(q('select count(*) from logistics.branch') == '0' and q('select count(*) from logistics.warehouse') == '0', 'comme en production : aucune agence, aucun entrepôt')
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0023-000000000001', 'authenticated', 'authenticated', 'sites-emp@essai.test', 'x', now(), '{}')")
        q("update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.statut'] where email = 'sites-emp@essai.test'")
        q("select logistics.run_migration('agences, employé')")
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        emp = q("select id from public.clients where email = 'sites-emp@essai.test'")
        client = q("select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1")

        def f(nom, acteur=admin, **kw):
            code, sortie = cl.run('prod', 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items())),
                                  role='authenticated', claims=acteur, expect_error=True)
            if code != 0:
                raise AssertionError('%s refusée : %s' % (nom, sortie[-300:]))
            return json.loads(sortie)

        def refus(nom, code_attendu, msg, acteur=admin, **kw):
            code, sortie = cl.run('prod', 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items())),
                                  role='authenticated', claims=acteur, expect_error=True)
            ok(code != 0 and code_attendu in sortie, '%s : attendu %s, obtenu %s' % (msg, code_attendu, sortie[-200:]))

        # ============================================================ A. créer, tracer, relire
        mia = f('lg_create_branch', p_code=' mia ', p_name='Miami', p_kind='office', p_country='US', p_city='Miami')
        pap = f('lg_create_branch', p_code='PAP-HUB', p_name='Hub Port-au-Prince', p_kind='hub', p_country='HT', p_city='Port-au-Prince')
        ok(mia['code'] == 'MIA', 'le code est nettoyé et mis en majuscules (MIA)')
        w = f('lg_create_warehouse', p_branch_id=mia['branch_id'], p_code='MIA-1', p_name='Entrepôt Doral')
        loc = f('lg_create_location', p_warehouse_id=w['warehouse_id'], p_code='a-01', p_zone='A', p_kind='storage')
        ok(q("select string_agg(action, ',' order by id) from logistics.audit_log where action like 'branch.%' or action like 'warehouse.%' or action like 'location.%'")
           == 'branch.create,branch.create,warehouse.create,location.create', 'chaque création est tracée dans le journal d\'audit')
        s = f('lg_sites', acteur=emp)
        b = {x['code']: x for x in s['branches']}
        ok(set(b) == {'MIA', 'PAP-HUB'} and b['MIA']['warehouses'][0]['warehouse_id'] == w['warehouse_id']
           and b['MIA']['warehouses'][0]['locations'][0]['code'] == 'A-01' and s['can_manage'] is False,
           'un employé relit les agences, leurs entrepôts et emplacements, avec leurs identifiants ; il ne peut pas les gérer')
        ok(f('lg_sites')['can_manage'] is True, 'la direction peut les gérer')
        refus('lg_create_branch', 'LG003', 'un employé ne crée pas d\'agence', acteur=emp, p_code='X1', p_name='X', p_kind='office', p_country='US')
        refus('lg_create_warehouse', 'LG003', 'un employé ne crée pas d\'entrepôt', acteur=emp, p_branch_id=mia['branch_id'], p_code='X1', p_name='X')
        refus('lg_sites', 'LG003', 'un client ne lit pas les sites', acteur=client)

        # ============================================================ B. données refusées
        refus('lg_create_branch', 'LG005', 'code illisible', p_code='m', p_name='X', p_kind='office', p_country='US')
        refus('lg_create_branch', 'LG005', 'code avec espace', p_code='MI A', p_name='X', p_kind='office', p_country='US')
        refus('lg_create_branch', 'LG005', 'code déjà pris', p_code='MIA', p_name='Autre', p_kind='office', p_country='US')
        refus('lg_create_branch', 'LG005', 'pays inconnu', p_code='CUB', p_name='La Havane', p_kind='office', p_country='CU')
        refus('lg_create_branch', 'LG005', 'genre inconnu', p_code='SDQ', p_name='SDQ', p_kind='aeroport', p_country='DO')
        refus('lg_create_branch', 'LG005', 'nom vide', p_code='SDQ', p_name='  ', p_kind='hub', p_country='DO')
        refus('lg_create_warehouse', 'LG005', 'entrepôt au code déjà pris', p_branch_id=pap['branch_id'], p_code='MIA-1', p_name='Doublon')
        refus('lg_create_location', 'LG005', 'emplacement en double dans le même entrepôt', p_warehouse_id=w['warehouse_id'], p_code='A-01')
        refus('lg_create_location', 'LG005', 'genre d\'emplacement inconnu', p_warehouse_id=w['warehouse_id'], p_code='B-01', p_kind='toit')

        # ============================================================ C. modifier
        f('lg_update_branch', p_branch_id=mia['branch_id'], p_name='Miami — Doral', p_city='Doral')
        ok(q("select name || '|' || city || '|' || country || '|' || code from logistics.branch where id = '%s'" % mia['branch_id']) == 'Miami — Doral|Doral|US|MIA',
           'nom et ville modifiés ; le code et le pays ne bougent pas')
        ok(q("select before ->> 'name' || '→' || (after ->> 'name') from logistics.audit_log where action = 'branch.update'") == 'Miami→Miami — Doral', 'modification tracée, avant et après')
        dormante = f('lg_create_branch', p_code='JAC', p_name='Jacmel', p_kind='agency', p_country='HT', p_city='Jacmel')
        f('lg_update_branch', p_branch_id=dormante['branch_id'], p_active=False)
        refus('lg_create_warehouse', 'LG002', 'pas d\'entrepôt dans une agence inactive', p_branch_id=dormante['branch_id'], p_code='JAC-1', p_name='X')
        refus('lg_update_branch', 'LG005', 'genre inconnu à la modification', p_branch_id=pap['branch_id'], p_kind='aeroport')

        # ============================================================ D. ce qui en dépend : le scan reçoit dans l'entrepôt créé
        colis = q("select tracking_number from logistics.parcel where status = 'CREATED' and customer_id is not null order by tracking_number limit 1")
        code, sortie = cl.run('prod', "select public.lg_scan_parcel(p_code => %s, p_purpose => 'receive', p_warehouse_id => '%s', p_location_id => '%s', p_idempotency_key => 'sites-1')"
                              % (val(colis), w['warehouse_id'], loc['location_id']), role='authenticated', claims=emp, expect_error=True)
        ok(code == 0 and json.loads(sortie)['result'] == 'ACCEPTED', 'le poste de scan reçoit un colis dans l\'entrepôt créé : ' + sortie[-200:])
        ok(q("select status || '|' || (current_warehouse_id = '%s')::text from logistics.parcel where tracking_number = %s" % (w['warehouse_id'], val(colis))) == 'RECEIVED|true',
           'le colis est REÇU, dans cet entrepôt')
        refus('lg_update_warehouse', 'LG004', 'on ne désactive pas un entrepôt qui garde un colis', p_warehouse_id=w['warehouse_id'], p_active=False)
        q("update logistics.parcel set current_location_id = '%s' where tracking_number = %s" % (loc['location_id'], val(colis)))
        refus('lg_set_location_active', 'LG004', 'on ne désactive pas un emplacement qui garde un colis', p_location_id=loc['location_id'], p_active=False)
        vide = f('lg_create_location', p_warehouse_id=w['warehouse_id'], p_code='Q-01', p_zone='Q', p_kind='quarantine')
        ok(f('lg_set_location_active', p_location_id=vide['location_id'], p_active=False)['active'] is False, 'un emplacement vide se désactive (jamais supprimé)')
        ok(q("select count(*) from logistics.warehouse_location where id = '%s'" % vide['location_id']) == '1', 'il reste dans la base, inactif')

        # ============================================================ E. fermé, rejouable
        code, sortie = cl.run('prod', 'select public.lg_sites()', role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in sortie, 'un visiteur ne lit rien')
        ok(q("select count(*) from pg_proc p where p.pronamespace = 'logistics'::regnamespace and p.proname in ('sites', 'create_branch', 'update_branch', 'create_warehouse', "
             "'update_warehouse', 'create_location', 'set_location_active') and (has_function_privilege('authenticated', p.oid, 'execute') or has_function_privilege('anon', p.oid, 'execute'))") == '0',
           'les fonctions internes restent fermées')
        avant = q("select count(*) || '|' || (select count(*) from logistics.warehouse) || '|' || (select count(*) from logistics.warehouse_location) from logistics.branch")
        cl.run('prod', P.lire_sql('outils/logistique/023-agences-entrepots.sql'))
        ok(q("select count(*) || '|' || (select count(*) from logistics.warehouse) || '|' || (select count(*) from logistics.warehouse_location) from logistics.branch") == avant,
           '023 rejouée : rien ne change (%s)' % avant)
        print('PASS agences et entrepôts (étape 023) : %d vérifications — créés par la direction et tracés, relus par l\'équipe avec leurs identifiants, '
              'données refusées, code et pays figés, le scan reçoit dans l\'entrepôt créé, rien ne se désactive sous un colis (PostgreSQL %s).'
              % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC agences et entrepôts (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
