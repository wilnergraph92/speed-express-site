#!/usr/bin/env python3
"""Étape 033 — l'historique et le profil du chauffeur (SES Opérations), éprouvés sur la RÉPLIQUE DE LA PRODUCTION (001 → 033).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-chauffeur-essai.py
    SES_FORME_ECRIRE=1 …   réécrit chauffeur-exemples.json (à recopier dans App_SES/tests/exemples-chauffeur.json)

Demande du propriétaire (21/10/2026) : un profil, l'historique des opérations du chauffeur, les options livraison et ramassage.
 A. une journée réelle de chauffeur, par la porte des téléphones : une livraison remise (preuve), une livraison en échec, un ramassage ;
 B. son historique : les trois, du plus récent au plus ancien, avec colis, preuve (sans les fichiers), motif d'échec et fil des statuts ; les
    totaux comptés par la base ; le filtre livraison / ramassage ; la pagination ; une période invalide refusée ;
 C. chacun le sien : un autre chauffeur ne voit rien, un agent sans fiche de chauffeur ni un client n'y ont pas accès ;
 D. la fiche du membre connecté : nom, rôle, agence, sa fiche de chauffeur et son véhicule, ses 30 derniers jours ; un client : refusé ;
 E. tout fermé, 033 rejouée sans effet ; le fichier partagé avec l'application.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


class R(str):
    pass


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def val(v):
    if v is None:
        return 'null'
    if isinstance(v, R):
        return str(v)
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return "'%s'::jsonb" % json.dumps(v).replace("'", "''")
    return "'%s'" % str(v).replace("'", "''")


def main():
    with P.Cluster() as cl:
        B = 'prod'
        if not P.monter_production(cl, B):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        etapes = sorted(f for f in os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')) if re.match(r'^\d{3}-.*\.sql$', f))
        ok('033-operations-chauffeur.sql' in etapes, 'l\'étape 033 est dans le noyau')
        for f_ in etapes:
            cl.run(B, P.lire_sql('outils/logistique/' + f_))
        q = lambda sql: cl.un(B, sql)   # noqa: E731
        comptes = {'chauf': [], 'chauf2': [], 'hub': ['colis.lire', 'colis.statut']}
        for i, (cle, droits) in enumerate(comptes.items()):
            q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
              "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0033-%012d', 'authenticated', 'authenticated', 'ch-%s@essai.test', 'x', now(), '{}')" % (i + 1, cle))
            q("update public.clients set role = 'employe', code = null, nom_complet = 'Membre %s', droits = %s where email = 'ch-%s@essai.test'"
              % (cle, ("array[%s]::text[]" % ', '.join("'%s'" % d for d in droits)) if droits else "'{}'", cle))
        ok(json.loads(q("select logistics.run_migration('décor du chauffeur')"))['report']['ready'] is True, 'décor prêt')
        uid = lambda e: q("select id from public.clients where email = '%s'" % e)   # noqa: E731
        admin = q("select id from public.clients where role = 'admin' order by email limit 1")
        chauf, chauf2, hub = uid('ch-chauf@essai.test'), uid('ch-chauf2@essai.test'), uid('ch-hub@essai.test')
        client = cl.lignes(B, "select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 1")[0]

        def appel(nom, acteur, kw):
            return cl.run(B, 'select public.%s(%s)' % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items())), role='authenticated', claims=acteur, expect_error=True)

        def f(nom, acteur=chauf, **kw):
            code, sortie = appel(nom, acteur, kw)
            if code != 0:
                raise AssertionError('%s refusée : %s' % (nom, sortie[-400:]))
            return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie   # certaines rendent un identifiant

        def refus(nom, code_attendu, msg, acteur=chauf, **kw):
            code, sortie = appel(nom, acteur, kw)
            ok(code != 0 and code_attendu in sortie, '%s : attendu %s, obtenu %s' % (msg, code_attendu, sortie[-220:]))

        def geste(cle, commande, args, acteur=chauf):
            return f('lg_mobile_command', acteur, p_key=cle, p_command=commande, p_args=args)

        # le décor : un hub, deux chauffeurs, un véhicule
        org = q('select id from logistics.organization')
        q("insert into logistics.branch (organization_id, code, name, kind, country, city) values ('%s', 'CH-PAP', 'Hub essai chauffeur', 'hub', 'HT', 'Port-au-Prince')" % org)
        pap = q("select id from logistics.branch where code = 'CH-PAP'")
        veh = f('lg_create_vehicle', admin, p_plate='ch-van', p_kind='VAN', p_capacity_lb=300, p_branch=pap)
        drv = f('lg_create_driver', admin, p_user_id=chauf, p_full_name='Jean Chauffeur', p_vehicle_id=veh)
        f('lg_create_driver', admin, p_user_id=chauf2, p_full_name='Paul Deux', p_vehicle_id=f('lg_create_vehicle', admin, p_plate='ch-moto', p_kind='MOTORCYCLE', p_capacity_lb=60, p_branch=pap))
        cust = q("select id from logistics.customer where legacy_client_id = '%s'" % client)
        n_p = [0]

        def colis(statut):
            n_p[0] += 1
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source, weight_lb) "
                     "values ('%s', 'SES-97%08d', 'jeton-ch%d', '%s', 'HT', 'air', '%s', 'core', 'legacy_backfill', 3) returning id" % (org, n_p[0], n_p[0], cust, statut))
        ici = {'latitude': 18.5392, 'longitude': -72.3364}
        # le jour de la BASE (Port-au-Prince), pas celui du serveur : vers 2 h UTC, ce n'est pas le même jour
        jour = q('select logistics.today()')

        # ============================================================ A. une journée réelle, par la porte des téléphones
        taches = []
        for i in range(2):
            liv = f('lg_create_delivery', hub, p_parcel_ids=R("array['%s']::uuid[]" % colis('AT_DESTINATION_HUB')), p_hub_branch=pap, p_scheduled_for=R("'%s'::date" % jour),
                    p_recipient_name='Marie %d' % i, p_address='%d rue Capois, Port-au-Prince' % (i + 1))
            f('lg_assign_task', admin, p_task_id=liv['task_id'], p_driver_id=drv, p_force=True, p_reason='Essai chauffeur')
            taches.append(liv['task_id'])
        t1, t2 = taches
        enl = f('lg_create_pickup_task', hub, p_customer_id=cust, p_address='5 rue Pavée, Port-au-Prince', p_scheduled_date=R("'%s'::date" % jour))
        t3 = enl['task_id']
        f('lg_assign_task', admin, p_task_id=t3, p_driver_id=drv, p_force=True, p_reason='Essai chauffeur')
        for t in (t1, t2, t3):
            geste('acc-' + t[:8], 'accept_task', {'task_id': t})
            geste('dem-' + t[:8], 'start_task', {'task_id': t})
        geste('pod-' + t1[:8], 'complete_delivery', dict(task_id=t1, recipient_name='Marie 0', photo_path='pod/%s/pod-%s.jpg' % (t1, t1[:8]), **ici))
        geste('ech-' + t2[:8], 'fail_task', {'task_id': t2, 'incident_type': 'CUSTOMER_ABSENT', 'description': 'personne au portail'})
        geste('enl-' + t3[:8], 'complete_pickup', {'task_id': t3, 'parcel_ids': [colis('CREATED')]})
        ok(q("select string_agg(status, ',' order by status) from logistics.task where id in ('%s', '%s', '%s')" % (t1, t2, t3)) == 'COMPLETED,COMPLETED,FAILED',
           'la journée : une livraison remise, une en échec, un ramassage fait')

        # ============================================================ B. son historique
        h = f('lg_my_task_history')
        ok(h['total'] == 3 and h['totals'] == {'delivered': 1, 'picked_up': 1, 'failed': 1, 'cancelled': 0, 'parcels': 2},
           'les totaux comptés par la base : %s' % h['totals'])
        ok(h['from'] < h['to'] and h['kind'] is None, 'par défaut : les 30 derniers jours, tous genres')
        par = {x['task_id']: x for x in h['items']}
        ok(par[t3]['kind'] == 'PICKUP' and par[t3]['status'] == 'COMPLETED' and len(par[t3]['parcels']) == 1 and par[t3]['contact'] and par[t3]['proof'] is None,
           'le ramassage : ses colis collectés, le client')
        ok(par[t1]['proof']['recipient_name'] == 'Marie 0' and par[t1]['proof']['has_photo'] is True and par[t1]['contact'] == 'Marie 0' and par[t1]['parcels'][0].startswith('SES-97'),
           'la livraison remise : sa preuve (qui, quand, photo), ses colis')
        ok('photo_path' not in json.dumps(h) and 'pod/' not in json.dumps(h), 'jamais le chemin des fichiers de preuve')
        ok(par[t2]['status'] == 'FAILED' and par[t2]['failed_reason'] and [s['status'] for s in par[t2]['steps']][-1] == 'FAILED'
           and [s['status'] for s in par[t2]['steps']][0] == 'CREATED', 'l\'échec : son motif, et le fil de ses statuts du début à la fin')
        fins = [x['finished_at'] for x in h['items']]
        ok(all(fins) and fins == sorted(fins, reverse=True), 'du plus récent au plus ancien, chacune avec son heure de fin')
        liv = f('lg_my_task_history', p_kind='DELIVERY')
        ok(liv['total'] == 2 and {x['kind'] for x in liv['items']} == {'DELIVERY'} and liv['totals']['picked_up'] == 0, 'l\'option « livraisons »')
        ram = f('lg_my_task_history', p_kind='PICKUP')
        ok(ram['total'] == 1 and ram['items'][0]['task_id'] == t3, 'l\'option « ramassages »')
        p1, p2 = f('lg_my_task_history', p_limit=1), f('lg_my_task_history', p_limit=1, p_offset=1)
        ok(len(p1['items']) == 1 and len(p2['items']) == 1 and p1['items'][0]['task_id'] != p2['items'][0]['task_id'] and p1['total'] == 3, 'page après page')
        ok(f('lg_my_task_history', p_from=R("'%s'::date - 400" % jour), p_to=R("'%s'::date - 370" % jour))['total'] == 0, 'une période sans mission : vide, sans erreur')
        refus('lg_my_task_history', 'LG005', 'une période à l\'envers', p_from=R("'%s'::date" % jour), p_to=R("'%s'::date - 1" % jour))
        refus('lg_my_task_history', 'LG005', 'une période de plus d\'un an', p_from=R("'%s'::date - 400" % jour))
        refus('lg_my_task_history', 'LG005', 'un genre inconnu', p_kind='VOL')

        # ============================================================ C. chacun le sien
        ok(f('lg_my_task_history', chauf2)['total'] == 0, 'un autre chauffeur ne voit rien des missions du premier')
        refus('lg_my_task_history', 'LG003', 'un agent sans fiche de chauffeur', acteur=hub)
        refus('lg_my_task_history', 'LG003', 'un client', acteur=client)
        q("update logistics.driver set status = 'ON_LEAVE' where user_id = '%s'" % chauf)
        ok(f('lg_my_task_history')['total'] == 3, 'un chauffeur en congé garde son historique')
        q("update logistics.driver set status = 'ACTIVE' where user_id = '%s'" % chauf)

        # ============================================================ D. la fiche
        carte = f('lg_my_staff_card')
        ok(carte['name'] == 'Membre chauf' and carte['role'] == 'employee' and carte['email'] == 'ch-chauf@essai.test' and carte['today'], 'la fiche : nom, rôle, e-mail')
        d = carte['driver']
        ok(d['name'] == 'Jean Chauffeur' and d['status'] == 'ACTIVE' and d['vehicle']['kind'] == 'VAN' and d['vehicle']['plate'].upper() == 'CH-VAN',
           'sa fiche de chauffeur et son véhicule')
        ok(d['last_30_days'] == {'delivered': 1, 'picked_up': 1, 'failed': 1} and d['open_today'] == 0, 'ses 30 derniers jours, comptés par la base')
        ok(f('lg_my_staff_card', hub)['driver'] is None, 'un agent sans fiche de chauffeur : sa fiche d\'équipe seulement')
        refus('lg_my_staff_card', 'LG003', 'un client n\'a pas de fiche d\'équipe', acteur=client)

        # ============================================================ E. tout fermé, rejeu, fichier partagé
        avant = q('select count(*) from logistics.task')
        cl.run(B, P.lire_sql('outils/logistique/033-operations-chauffeur.sql'))
        ok(q('select count(*) from logistics.task') == avant, '033 rejouée : rien ne change')
        code, sortie = cl.run(B, 'select public.lg_my_task_history()', role='anon', expect_error=True)
        ok(code != 0 and 'permission denied' in sortie, 'un visiteur : rien')
        for fn in ('logistics.my_task_history(uuid,date,date,text,integer,integer)', 'logistics.my_staff_card(uuid)'):
            ok(q("select has_function_privilege('authenticated', '%s', 'execute')::text || has_function_privilege('anon', '%s', 'execute')::text" % (fn, fn)) == 'falsefalse',
               '%s : jamais appelée en direct' % fn)
        for fn in ('public.lg_my_task_history(date,date,text,integer,integer)', 'public.lg_my_staff_card()'):
            ok(q("select has_function_privilege('authenticated', '%s', 'execute')::text || has_function_privilege('anon', '%s', 'execute')::text" % (fn, fn)) == 'truefalse',
               '%s : aux comptes connectés seulement' % fn)
        ICI = os.path.dirname(os.path.abspath(__file__))
        SIG = json.loads(q("select json_object_agg(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), "
                           "'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) "
                           "from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname in ('lg_my_task_history', 'lg_my_staff_card')"))
        EX = {'signatures': SIG, 'historique': h, 'historique_ramassages': ram, 'fiche': carte, 'fiche_sans_chauffeur': f('lg_my_staff_card', hub)}
        ch = os.path.join(ICI, 'chauffeur-exemples.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump(EX, open(ch, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        lus = json.load(open(ch, encoding='utf-8'))
        ok(lus['signatures'] == json.loads(json.dumps(SIG)), 'les signatures sont celles du fichier partagé avec l\'application (sinon : SES_FORME_ECRIRE=1)')

        def forme(x):
            if isinstance(x, dict):
                return {k: forme(v) for k, v in x.items() if v is not None}
            if isinstance(x, list):
                return [forme(x[0])] if x else []
            return type(x).__name__
        for k in EX:
            ok(forme(lus[k]) == forme(json.loads(json.dumps(EX[k]))), 'la réponse « %s » a la forme du fichier partagé' % k)
    print('%d vérifications — étape 033 (historique et profil du chauffeur) : OK' % N[0])


if __name__ == '__main__':
    try:
        sys.exit(main())
    except AssertionError as e:
        print('ÉCHEC historique et profil du chauffeur (après %d vérifications) : %s' % (N[0], e))
        sys.exit(1)
