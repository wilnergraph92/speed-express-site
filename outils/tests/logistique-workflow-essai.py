#!/usr/bin/env python3
"""Phase 3 — le workflow opérationnel du colis (étape 015), sur la RÉPLIQUE DE LA PRODUCTION, noyau 001 → 015.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-workflow-essai.py

On exige :
 1. la machine, exhaustivement : pour CHACUNE des 22 × 22 paires de statuts, la transition réussit si elle est déclarée, et
    elle est REFUSÉE (LG001, « non autorisée ») sinon — 100 % des valides passent, 100 % des invalides sont refusées ;
 2. le flux nominal de bout en bout, par les vraies fonctions (scans, consolidation, expédition, douane, hub, livraison) :
    CREATED → RECEIVED_AT_WAREHOUSE → INSPECTED → STORED → CONSOLIDATED → READY_FOR_SHIPMENT → LOADED → IN_TRANSIT →
    ARRIVED_AT_HUB → CUSTOMS → CLEARED → READY_FOR_DELIVERY → DELIVERY_ASSIGNED → OUT_FOR_DELIVERY → DELIVERED ;
    chaque transition produit UN événement de suivi, UNE ligne d'audit, UN événement de domaine, de même corrélation ;
    les notifications prévues partent vers le client ;
 3. la livraison manquée : FAILED_DELIVERY, le client prévenu, replanifiée, annulée → retour au hub ;
 4. interdits : modification directe du statut, retour arbitraire, reprise vers un autre statut que celui d'avant l'attente,
    statut incohérent avec la mission ou l'expédition (refusé à la validation de la transaction, quel que soit le chemin) ;
 5. le scan : idempotent (double scan), hors ligne puis rejoué, collision de deux postes sur le même colis, colis inexistant,
    colis déjà livré, QR et code-barres (Code 128) et saisie, jeton falsifié, sortie sans expédition prête, inventaire ;
 6. l'entrepôt : recherche d'emplacement, inventaire attendu / vu / à chercher ; fermé aux clients et aux visiteurs.
Jamais la production."""
import json
import os
import re
import subprocess
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


class R(str):
    """Fragment SQL brut (une date, une expression), jamais mis entre guillemets."""


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
    if isinstance(v, (list, tuple)):
        if not v:
            return "'{}'"
        return "array[%s]::%s[]" % (', '.join(val(x) for x in v), 'uuid' if re.match(r'^[0-9a-f-]{36}$', str(v[0])) else 'text')
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items()))


FLUX = ['CREATED', 'RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'LOADED', 'IN_TRANSIT',
        'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY', 'DELIVERED']


def main():
    with P.Cluster() as cl:
        B = 'prod'
        if not P.monter_production(cl, B):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        cl.run('postgres', "alter database %s set timezone to 'America/Port-au-Prince'" % B)
        for f in sorted(os.listdir(os.path.join(P.RACINE, 'outils', 'logistique'))):
            cl.run(B, P.lire_sql('outils/logistique/' + f))
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        n_trans = q('select count(*) from logistics.parcel_transition')
        cl.run(B, P.lire_sql('outils/logistique/015-workflow-colis.sql'))
        ok(q('select count(*) from logistics.parcel_transition') == n_trans, '015 rejouée : aucune transition en double')
        ok(q("select count(*) from logistics.parcel_status") == '22', '22 statuts : 16 du flux (dont LOADED) et 6 exceptions (dont FAILED_DELIVERY)')
        ok(q("select string_agg(business_name, ',' order by sort_order) from logistics.parcel_status where not is_exception") ==
           'CREATED,RECEIVED_AT_WAREHOUSE,INSPECTED,STORED,CONSOLIDATION_PENDING,CONSOLIDATED,READY_FOR_SHIPMENT,LOADED,IN_TRANSIT,ARRIVED_AT_HUB,'
           'CUSTOMS,CLEARED,READY_FOR_DELIVERY,DELIVERY_ASSIGNED,OUT_FOR_DELIVERY,DELIVERED',
           'les noms métier du workflow cible, dans l\'ordre')

        # -------------------------------------------------------------- le décor
        rapport = json.loads(q("select logistics.run_migration('décor du workflow')"))
        ok(rapport['report']['ready'] is True, 'données copiées, migration prête')
        uid = lambda email: q("select id from public.clients where email = '%s'" % email)   # noqa: E731
        admin, gerant, op = uid('client1@essai.test'), uid('client2@essai.test'), uid('client3@essai.test')
        q("update logistics.app_user set rights = array['colis.lire', 'colis.statut'] where id = '%s'" % op)
        client_compte = q("select id from public.clients where role = 'client' order by email limit 1")
        q("insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, raw_user_meta_data) values "
          "('00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0000-000000000099', 'authenticated', 'authenticated', 'chauffeur99@essai.test', "
          "'x', now(), '{\"nom_complet\": \"Chauffeur Essai\"}')")
        q("update public.clients set role = 'employe', droits = '{}', code = null where email = 'chauffeur99@essai.test'")
        q("select logistics.run_migration('chauffeur')")
        chauffeur = uid('chauffeur99@essai.test')
        q("insert into logistics.branch (organization_id, code, name, kind, country) select id, c, n, k, p from logistics.organization, (values "
          "('MIA', 'Miami', 'office', 'US'), ('PAP', 'Hub Port-au-Prince', 'hub', 'HT')) v(c, n, k, p)")
        mia, pap = q("select id from logistics.branch where code = 'MIA'"), q("select id from logistics.branch where code = 'PAP'")
        q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'MIA-1', 'Entrepôt Miami'), ('%s', 'PAP-1', 'Entrepôt hub')" % (mia, pap))
        wmia, wpap = q("select id from logistics.warehouse where code = 'MIA-1'"), q("select id from logistics.warehouse where code = 'PAP-1'")
        q("insert into logistics.warehouse_location (warehouse_id, code) values ('%s', 'A-01'), ('%s', 'A-02'), ('%s', 'B-01')" % (wmia, wmia, wpap))
        a01, a02 = q("select id from logistics.warehouse_location where code = 'A-01'"), q("select id from logistics.warehouse_location where code = 'A-02'")
        q("insert into logistics.transport (mode, carrier, reference) values ('air', 'Compagnie fictive', 'WF-1')")
        vol = q("select id from logistics.transport where reference = 'WF-1'")
        org = q('select id from logistics.organization')
        cust = q("select id from logistics.customer where legacy_client_id = '%s'" % client_compte)

        def f(nom, acteur=op, **kw):
            code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
            return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

        def fr(nom, etat, msg, acteur=op, **kw):
            code, texte = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur, expect_error=True)
            ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-200:].replace('\n', ' ')))
            return texte

        n_colis = [0]

        def colis(statut='CREATED', client=True, entrepot=wmia, emplacement=None):
            """Un colis du noyau. Natif s'il naît CREATED ; sinon placé directement dans le statut voulu (décor d'essai)."""
            n_colis[0] += 1
            num = 'SES-90000%05d' % n_colis[0]
            if statut == 'CREATED':
                return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, "
                         "status_authority, source, weight_lb, declared_value, description, recipient_name) values ('%s', '%s', 'jeton%d', %s, 'HT', 'air', 'CREATED', "
                         "'core', 'native', 5, 50, 'colis %d', 'Destinataire') returning id" % (org, num, n_colis[0], "'%s'" % cust if client else 'null', n_colis[0]))
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, "
                     "status_authority, source, weight_lb, declared_value, description, recipient_name, current_warehouse_id, current_location_id) values "
                     "('%s', '%s', 'jeton%d', %s, 'HT', 'air', '%s', 'core', 'legacy_backfill', 5, 50, 'colis %d', 'Destinataire', %s, %s) returning id" % (
                         org, num, n_colis[0], "'%s'" % cust if client else 'null', statut, n_colis[0], "'%s'" % entrepot if entrepot else 'null',
                         "'%s'" % emplacement if emplacement else 'null'))

        num = lambda pid: q("select tracking_number from logistics.parcel where id = '%s'" % pid)   # noqa: E731
        st = lambda pid: q("select status from logistics.parcel where id = '%s'" % pid)   # noqa: E731

        # ============================================================== 1. la machine, paire par paire
        statuts = cl.lignes(B, "select code from logistics.parcel_status order by sort_order")
        aretes = set(tuple(l.split('|')) for l in cl.lignes(B, "select from_status || '|' || to_status from logistics.parcel_transition"))
        cl.run(B, "create table essai_matrice (de text, vers text, etat text, message text)")
        cl.run(B, """
          do $$
          declare a text; b text; v_id uuid; v_org uuid; v_cust uuid; v_wh uuid; v_loc uuid; v_admin uuid := '%s';
          begin
            select id into v_org from logistics.organization; v_cust := '%s'; v_wh := '%s'; v_loc := '%s';
            perform set_config('logistics.pod_override', 'on', true);   -- la règle « livré exige une preuve » est éprouvée ailleurs
            foreach a in array (select array_agg(code order by sort_order) from logistics.parcel_status) loop
              foreach b in array (select array_agg(code order by sort_order) from logistics.parcel_status) loop
                continue when a = b;
                begin
                  insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status,
                                                status_authority, source, current_warehouse_id, current_location_id)
                  values (v_org, 'MAT-' || a || '-' || b, 'j', v_cust, 'HT', 'air', a, 'core', 'legacy_backfill', v_wh, v_loc) returning id into v_id;
                  perform logistics.transition_parcel(v_id, b, v_admin, null, null, v_wh, v_loc, '', null, 'essai de la matrice', '{}', 'manual');
                  raise exception 'reussi' using errcode = 'ZZ001';      -- tout annuler : chaque paire part d'une base propre
                exception when others then
                  insert into essai_matrice values (a, b, sqlstate, sqlerrm);
                end;
              end loop;
            end loop;
          end $$""" % (admin, cust, wmia, a01))
        res = {(l.split('|')[0], l.split('|')[1]): (l.split('|')[2], l.split('|')[3]) for l in cl.lignes(B, "select de || '|' || vers || '|' || etat || '|' || message from essai_matrice")}
        ok(len(res) == 22 * 21, '%d paires essayées (22 × 21)' % len(res))
        valides = [k for k in res if k in aretes]
        invalides = [k for k in res if k not in aretes]
        mauvaises_valides = [(k, res[k]) for k in valides if res[k][0] != 'ZZ001']
        mauvaises_invalides = [(k, res[k]) for k in invalides if not (res[k][0] == 'LG001' and 'non autorisée' in res[k][1])]
        ok(not mauvaises_valides, '100 %% des transitions VALIDES passent (%d) ; en échec : %s' % (len(valides), mauvaises_valides[:4]))
        ok(not mauvaises_invalides, '100 %% des transitions INVALIDES refusées par la machine (%d) ; mal refusées : %s' % (len(invalides), mauvaises_invalides[:4]))
        ok(len(valides) == len(aretes) and len(valides) == 104, '104 transitions déclarées, toutes éprouvées')
        for de, vers in (('DELIVERED', 'OUT_FOR_DELIVERY'), ('IN_TRANSIT', 'STORED'), ('LOADED', 'STORED'), ('CUSTOMS_CLEARED', 'IN_TRANSIT'),
                         ('FAILED_DELIVERY', 'OUT_FOR_DELIVERY'), ('DELIVERED', 'FAILED_DELIVERY'), ('LOST', 'STORED'), ('CANCELLED', 'CREATED')):
            ok((de, vers) in invalides, 'retour arbitraire interdit : %s → %s' % (de, vers))

        # ============================================================== 2. le flux nominal, par les vraies fonctions
        p1, p2 = colis(), colis()
        for p in (p1, p2):
            r = f('lg_scan_parcel', p_code=num(p), p_purpose='receive', p_warehouse_id=wmia, p_code_kind='barcode', p_idempotency_key='rec-' + p)
            ok(r['result'] == 'ACCEPTED' and st(p) == 'RECEIVED', 'scan de réception : RECEIVED_AT_WAREHOUSE')
        f('lg_transition_parcel', p_parcel_id=p1, p_to_status='INSPECTED')   # le nom métier est accepté par la façade
        f('lg_transition_parcel', p_parcel_id=p2, p_to_status='VERIFIED')
        ok(st(p1) == 'VERIFIED' and st(p2) == 'VERIFIED', 'INSPECTED (nom métier) = VERIFIED (code)')
        fr('lg_transition_parcel', 'LG001', 'un nom de statut inconnu', p_parcel_id=p1, p_to_status='EN_ROUTE_VERS_LA_LUNE')
        for p, loc in ((p1, a01), (p2, a02)):
            f('lg_scan_parcel', p_code=num(p), p_purpose='store', p_warehouse_id=wmia, p_location_id=loc, p_code_kind='barcode')
            f('lg_scan_parcel', p_code=num(p), p_purpose='consolidate', p_warehouse_id=wmia, p_code_kind='barcode')
        ok(st(p1) == 'CONSOLIDATION_PENDING', 'rangé puis scanné pour consolidation')
        cons = f('lg_open_consolidation', p_code='WF-C1', p_warehouse_id=wmia, p_destination_country='HT', p_mode='air')['consolidation_id']
        for p in (p1, p2):
            f('lg_add_parcel_to_consolidation', p_consolidation_id=cons, p_parcel_id=p)
        f('lg_close_consolidation', p_consolidation_id=cons)
        ok(st(p1) == 'CONSOLIDATED', 'consolidation fermée : CONSOLIDATED')
        sh = f('lg_create_shipment', p_code='WF-S1', p_mode='air', p_origin_branch=mia, p_destination_branch=pap, p_consolidation_ids=[cons])['shipment_id']
        r = f('lg_scan_parcel', p_code=num(p1), p_purpose='load', p_warehouse_id=wmia, p_code_kind='barcode')
        ok(r['result'] == 'WRONG_STATE', 'scan de sortie AVANT que l\'expédition soit prête : refusé')
        f('lg_generate_manifest', p_shipment_id=sh)
        f('lg_mark_shipment_ready', p_shipment_id=sh)
        ok(st(p1) == 'READY_FOR_EXPORT', 'expédition prête : READY_FOR_SHIPMENT')
        r = f('lg_scan_parcel', p_code=num(p1), p_purpose='load', p_warehouse_id=wmia, p_code_kind='barcode', p_idempotency_key='load-p1')
        ok(r['result'] == 'ACCEPTED' and st(p1) == 'LOADED', 'scan de SORTIE : LOADED')
        ok(f('lg_scan_parcel', p_code=num(p1), p_purpose='load', p_warehouse_id=wmia, p_code_kind='barcode')['result'] == 'DUPLICATE', 'second scan de sortie : doublon')
        d = f('lg_dispatch_shipment', p_shipment_id=sh, p_transport_id=vol, p_idempotency_key='wf-dsp')
        ok(d['parcels']['loaded'] == 1 and d['parcels']['not_scanned_at_loading'] == 1 and st(p1) == 'IN_TRANSIT' and st(p2) == 'IN_TRANSIT',
           'départ : le colis chargé part, celui qui n\'a pas été scanné à la sortie aussi, mais il est COMPTÉ')
        f('lg_arrive_shipment', p_shipment_id=sh)
        ok(st(p1) == 'ARRIVED', 'ARRIVED_AT_HUB')
        f('lg_start_customs', p_shipment_id=sh, p_reference='DEC-WF', p_broker='Courtier fictif', p_documents=R("'[]'::jsonb"))
        ok(st(p1) == 'CUSTOMS_PROCESSING', 'CUSTOMS')
        f('lg_clear_customs', p_shipment_id=sh)
        ok(st(p1) == 'CUSTOMS_CLEARED', 'CLEARED')
        f('lg_receive_at_hub', p_shipment_id=sh, p_hub_warehouse_id=wpap)
        ok(st(p1) == 'AT_DESTINATION_HUB' and st(p2) == 'AT_DESTINATION_HUB', 'READY_FOR_DELIVERY')
        van = f('lg_create_vehicle', acteur=admin, p_plate='WF-1', p_kind='VAN', p_capacity_lb=500, p_capacity_ft3=100)
        drv = f('lg_create_driver', acteur=admin, p_user_id=chauffeur, p_full_name='Chauffeur Essai', p_vehicle_id=van)
        f('lg_set_availability', acteur=admin, p_driver=drv, p_starts=R("now() - interval '1 hour'"), p_ends=R("now() + interval '10 hours'"))
        dl = f('lg_create_delivery', p_parcel_ids=[p1], p_hub_branch=pap, p_scheduled_for=R('current_date'), p_recipient_name='Marie', p_address='1 rue Neuve, Delmas')
        tk = dl['task_id']
        ok(st(p1) == 'DELIVERY_ASSIGNED', 'livraison créée : DELIVERY_ASSIGNED')
        f('lg_assign_task', p_task_id=tk, p_driver_id=drv)
        f('lg_accept_task', acteur=chauffeur, p_task_id=tk)
        f('lg_start_task', acteur=chauffeur, p_task_id=tk)
        ok(st(p1) == 'OUT_FOR_DELIVERY', 'mission commencée : OUT_FOR_DELIVERY')
        f('lg_complete_delivery', acteur=chauffeur, p_task_id=tk, p_recipient_name='Marie', p_latitude=18.54, p_longitude=-72.33, p_photo_path='pod/%s/p.jpg' % tk)
        ok(st(p1) == 'DELIVERED', 'preuve déposée : DELIVERED')
        chemin = cl.lignes(B, "select to_status from logistics.tracking_event where parcel_id = '%s' and from_status is distinct from to_status order by id" % p1)
        ok(chemin == FLUX[1:], 'le colis a suivi EXACTEMENT le flux cible : %s' % chemin)
        # chaque transition : un suivi, un audit, un événement, même corrélation
        n_te = int(q("select count(*) from logistics.tracking_event where parcel_id = '%s' and from_status is distinct from to_status" % p1))
        n_au = int(q("select count(*) from logistics.audit_log where entity_type = 'parcel' and entity_id = '%s' and action = 'parcel.transition'" % p1))
        n_de = int(q("select count(*) from logistics.domain_event where aggregate_type = 'parcel' and aggregate_id = '%s' and event_type <> 'ParcelMoved'" % p1))
        ok(n_te == 15 and n_au == 15 and n_de == 15, '15 transitions : 15 événements de suivi, 15 lignes d\'audit, 15 événements de domaine (%d/%d/%d)' % (n_te, n_au, n_de))
        ok(q("select count(*) from logistics.tracking_event e where e.parcel_id = '%s' and e.from_status is distinct from e.to_status and not exists ("
             "select 1 from logistics.audit_log a where a.correlation_id = e.correlation_id and a.entity_id = e.parcel_id::text) " % p1) == '0'
           and q("select count(*) from logistics.tracking_event e where e.parcel_id = '%s' and e.from_status is distinct from e.to_status and not exists ("
                 "select 1 from logistics.domain_event d where d.correlation_id = e.correlation_id and d.aggregate_id = e.parcel_id::text)" % p1) == '0',
           'chaque événement de suivi a son audit et son événement de domaine, de même corrélation')
        q("select logistics.dispatch_events(1000, 'notification_engine')")
        modeles = set(cl.lignes(B, "select distinct template from logistics.notification where parcel_id = '%s'" % p1))
        ok({'ParcelReceived', 'ParcelInTransit', 'ParcelArrived', 'CustomsCleared', 'ParcelAtDestinationHub', 'OutForDelivery', 'Delivered'} <= modeles,
           'les notifications prévues partent vers le client (%s)' % sorted(modeles))
        ok('ParcelLoaded' not in modeles, 'le chargement, interne, ne dérange pas le client')

        # ============================================================== 3. la livraison manquée
        dl2 = f('lg_create_delivery', p_parcel_ids=[p2], p_hub_branch=pap, p_scheduled_for=R('current_date'), p_recipient_name='Jean', p_address='2 rue Basse')
        tk2 = dl2['task_id']
        f('lg_assign_task', p_task_id=tk2, p_driver_id=drv)
        f('lg_accept_task', acteur=chauffeur, p_task_id=tk2)
        f('lg_start_task', acteur=chauffeur, p_task_id=tk2)
        f('lg_fail_task', acteur=chauffeur, p_task_id=tk2, p_incident_type='CUSTOMER_ABSENT', p_description='personne')
        ok(st(p2) == 'FAILED_DELIVERY' and q("select status from logistics.task where id = '%s'" % tk2) == 'FAILED', 'mission échouée : colis FAILED_DELIVERY')
        q("select logistics.dispatch_events(1000, 'notification_engine')")
        ok(q("select count(*) from logistics.notification where parcel_id = '%s' and template = 'DeliveryFailed'" % p2) != '0', 'le client est prévenu de la livraison manquée')
        f('lg_reschedule_task', p_task_id=tk2, p_new_date=R('current_date'))
        ok(st(p2) == 'DELIVERY_ASSIGNED', 'replanifiée : de nouveau DELIVERY_ASSIGNED')
        f('lg_assign_task', p_task_id=tk2, p_driver_id=drv)
        f('lg_accept_task', acteur=chauffeur, p_task_id=tk2)
        f('lg_start_task', acteur=chauffeur, p_task_id=tk2)
        f('lg_fail_task', acteur=chauffeur, p_task_id=tk2, p_incident_type='WRONG_ADDRESS', p_description='adresse introuvable')
        f('lg_cancel_task', acteur=admin, p_task_id=tk2, p_reason='client injoignable')
        ok(st(p2) == 'AT_DESTINATION_HUB', 'annulée par la direction : retour au hub (READY_FOR_DELIVERY)')

        # ============================================================== 4. les interdits
        code, texte = cl.run(B, "update logistics.parcel set status = 'DELIVERED' where id = '%s'" % p2, expect_error=True)
        ok(code != 0 and 'LG001' in texte, 'modification DIRECTE du statut : refusée (LG001), même pour le propriétaire de la base')
        code, texte = cl.run(B, "update logistics.parcel set status = 'DELIVERED' where id = '%s'" % p2, role='authenticated', claims=admin, expect_error=True)
        ok(code != 0 and '42501' in texte, 'un compte connecté n\'a même pas accès à la table')
        fr('lg_transition_parcel', 'Statut incohérent', 'affecter à une livraison SANS livraison (colis / mission incohérents)', p_parcel_id=p2, p_to_status='DELIVERY_ASSIGNED')
        ok(st(p2) == 'AT_DESTINATION_HUB', 'et rien n\'a changé (transaction entière annulée)')
        p3 = colis('READY_FOR_EXPORT')
        fr('lg_transition_parcel', 'Statut incohérent', 'charger un colis qui n\'appartient à aucune expédition prête', p_parcel_id=p3, p_to_status='LOADED')
        p4 = colis('OUT_FOR_DELIVERY', entrepot=wpap)
        fr('lg_transition_parcel', 'Statut incohérent', 'déclarer une livraison manquée sans mission échouée', acteur=admin, p_parcel_id=p4, p_to_status='FAILED_DELIVERY', p_reason='x')
        r = f('lg_deliver_without_proof', acteur=admin, p_parcel_id=p4, p_reason='Remis au voisin, application en panne')
        ok(st(p4) == 'DELIVERED', 'la dérogation de la direction (tracée) reste possible, et cohérente')
        # reprise après attente : vers le statut d'avant, pas ailleurs
        p5 = colis('STORED', emplacement=a01)
        f('lg_transition_parcel', p_parcel_id=p5, p_to_status='ON_HOLD', p_reason='document manquant')
        fr('lg_transition_parcel', 'LG001', 'reprendre vers un AUTRE statut que celui d\'avant l\'attente', acteur=admin, p_parcel_id=p5, p_to_status='VERIFIED')
        f('lg_transition_parcel', acteur=admin, p_parcel_id=p5, p_to_status='STORED')
        ok(st(p5) == 'STORED', 'reprise vers le statut d\'avant : acceptée')
        ok(q("select count(*) from logistics.workflow_inconsistencies()") == '0', 'rapport de cohérence : aucun colis incohérent')

        # ============================================================== 5. le scan
        p6 = colis()
        k = 'poste-1:2026-10-12T10:00:00Z:1'
        r1 = f('lg_scan_parcel', p_code=num(p6), p_purpose='receive', p_warehouse_id=wmia, p_code_kind='barcode', p_idempotency_key=k)
        r2 = f('lg_scan_parcel', p_code=num(p6), p_purpose='receive', p_warehouse_id=wmia, p_code_kind='barcode', p_idempotency_key=k)
        ok(r1['result'] == 'ACCEPTED' and r2.get('replayed') is True and r2['scan_id'] == r1['scan_id'], 'DOUBLE SCAN, même clé : rejoué, rien de refait')
        ok(q("select count(*) from logistics.scan where parcel_id = '%s'" % p6) == '1' and
           q("select count(*) from logistics.tracking_event where parcel_id = '%s'" % p6) == '1', 'une seule lecture, un seul événement')
        r3 = f('lg_scan_parcel', p_code=num(p6), p_purpose='receive', p_warehouse_id=wmia, p_code_kind='barcode', p_idempotency_key=k + '-bis')
        ok(r3['result'] == 'DUPLICATE' and st(p6) == 'RECEIVED', 'second scan d\'une AUTRE lecture : DOUBLON, le colis n\'avance pas deux fois')
        fr('lg_scan_parcel', 'LG006', 'la même clé pour une AUTRE demande', p_code=num(p6), p_purpose='verify', p_warehouse_id=wmia, p_idempotency_key=k)
        # hors ligne : le poste garde la lecture, la renvoie plus tard avec sa clé et son heure d'origine
        p7 = colis()
        hl = {'horodatage': '2026-10-12T09:15:00Z', 'hors_ligne': True}
        r = f('lg_scan_parcel', p_code=num(p7), p_purpose='receive', p_warehouse_id=wmia, p_code_kind='barcode', p_idempotency_key='hl-1', p_metadata=hl)
        ok(r['result'] == 'ACCEPTED' and q("select metadata ->> 'horodatage' from logistics.scan where idempotency_key = 'hl-1'") == '2026-10-12T09:15:00Z',
           'scan HORS LIGNE envoyé au retour du réseau : accepté, heure d\'origine gardée')
        r = f('lg_scan_parcel', p_code=num(p7), p_purpose='receive', p_warehouse_id=wmia, p_code_kind='barcode', p_idempotency_key='hl-1', p_metadata=hl)
        ok(r.get('replayed') is True, 'le poste le renvoie une seconde fois (accusé perdu) : rejoué, sans effet')
        p7b = colis()
        f('lg_scan_parcel', p_code=num(p7b), p_purpose='receive', p_warehouse_id=wmia, p_code_kind='manual')
        r = f('lg_scan_parcel', p_code=num(p7b), p_purpose='receive', p_warehouse_id=wmia, p_code_kind='barcode', p_idempotency_key='hl-2', p_metadata=hl)
        ok(r['result'] == 'DUPLICATE', 'une lecture hors ligne arrivée APRÈS qu\'un autre poste a reçu le colis : doublon, rien d\'abîmé')
        # collision : deux postes scannent le même colis au même instant
        p8 = colis()
        nombre = num(p8)

        def poste(nom, sortie):
            script = ("set role authenticated; select set_config('request.jwt.claim.sub', '%s', false); begin; "
                      "select (public.lg_scan_parcel(p_code => '%s', p_purpose => 'receive', p_warehouse_id => '%s', p_code_kind => 'barcode', p_idempotency_key => '%s')) ->> 'result'; "
                      "select pg_sleep(1.5); commit;") % (op, nombre, wmia, nom)
            r = subprocess.run([os.path.join(P.PG, 'psql'), '-h', '127.0.0.1', '-p', str(cl.port), '-U', 'postgres', '-d', B, '-qAtX', '-v', 'ON_ERROR_STOP=1'],
                               input=script, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
                               env=dict(os.environ, PGOPTIONS='-c search_path=public,extensions'))
            sortie[nom] = (r.returncode, r.stdout.strip().splitlines()[:2], r.stderr[-200:])
        sorties = {}
        t1 = threading.Thread(target=poste, args=('col-A', sorties))
        t2 = threading.Thread(target=poste, args=('col-B', sorties))
        t1.start(); t2.start(); t1.join(); t2.join()
        # 1re ligne de sortie : l'identifiant renvoyé par set_config ; 2e : le verdict du scan
        verdicts = sorted(s[1][1] if len(s[1]) > 1 else 'ERREUR ' + s[2] for s in sorties.values())
        ok(verdicts == ['ACCEPTED', 'DUPLICATE'], 'COLLISION de deux postes : un seul accepté, l\'autre doublon (%s)' % verdicts)
        ok(q("select count(*) from logistics.tracking_event where parcel_id = '%s'" % p8) == '1', 'et un seul événement : le verrou a fait attendre le second')
        # colis inexistant
        r = f('lg_scan_parcel', p_code='SES-0000000001', p_purpose='receive', p_warehouse_id=wmia, p_code_kind='barcode')
        ok(r['result'] == 'UNKNOWN_PARCEL' and r['incident_id'] is not None, 'COLIS INEXISTANT : refusé, incident ouvert')
        r = f('lg_scan_parcel', p_code='SES-0000000001', p_purpose='receive', p_warehouse_id=wmia, p_code_kind='barcode')
        ok(r['result'] == 'UNKNOWN_PARCEL' and r['incident_id'] is None, 'rescanné : pas un second incident')
        ok(q("select count(*) from logistics.scan where scanned_code = 'SES-0000000001'") == '2', 'les deux lectures refusées restent tracées')
        # colis déjà livré
        for intention, attendu in (('receive', 'ALREADY_DISPATCHED'), ('load', 'ALREADY_DISPATCHED'), ('inventory', 'WRONG_STATE'), ('lookup', 'ACCEPTED')):
            r = f('lg_scan_parcel', p_code=num(p1), p_purpose=intention, p_warehouse_id=wmia, p_code_kind='barcode')
            ok(r['result'] == attendu and st(p1) == 'DELIVERED', 'COLIS DÉJÀ LIVRÉ, scan « %s » : %s, il reste livré' % (intention, attendu))
        # QR, Code 128, saisie
        p9 = colis()
        jeton = q("select public_token from logistics.parcel where id = '%s'" % p9)
        r = f('lg_scan_parcel', p_code='https://wilnergraph92.github.io/speed-express-site/suivi.html?colis=%s&j=%s' % (num(p9), jeton),
              p_purpose='receive', p_warehouse_id=wmia, p_code_kind='qr')
        ok(r['result'] == 'ACCEPTED', 'QR de l\'étiquette (adresse de suivi + jeton) : accepté')
        p10 = colis()
        r = f('lg_scan_parcel', p_code='https://wilnergraph92.github.io/speed-express-site/suivi.html?colis=%s&j=FAUX' % num(p10),
              p_purpose='receive', p_warehouse_id=wmia, p_code_kind='qr')
        ok(r['result'] == 'INVALID_CODE' and st(p10) == 'CREATED', 'QR au jeton FALSIFIÉ : refusé, incident')
        r = f('lg_scan_parcel', p_code='  ' + num(p10).lower() + '\t', p_purpose='receive', p_warehouse_id=wmia, p_code_kind='manual')
        ok(r['result'] == 'ACCEPTED', 'saisie au clavier en minuscules avec des espaces : normalisée, acceptée')
        fr('lg_scan_parcel', 'LG005', 'type de lecteur inconnu', p_code=num(p10), p_purpose='lookup', p_warehouse_id=wmia, p_code_kind='telepathie')

        # ============================================================== 6. l'entrepôt : emplacement, inventaire
        loc = f('lg_locate_parcel', p_code=num(p5))
        ok(loc['found'] and loc['location']['code'] == 'A-01' and loc['warehouse']['code'] == 'MIA-1' and loc['business_status'] == 'STORED',
           'RECHERCHE D\'EMPLACEMENT : entrepôt MIA-1, emplacement A-01')
        ok(f('lg_locate_parcel', p_code='SES-0000000002')['found'] is False, 'un numéro inconnu : « introuvable », sans erreur')
        r = f('lg_scan_parcel', p_code=num(p5), p_purpose='inventory', p_warehouse_id=wmia, p_location_id=a02, p_code_kind='barcode')
        ok(r['result'] == 'ACCEPTED' and 'LOCATION_MISMATCH' in r['warnings'], 'inventaire : colis trouvé AILLEURS que prévu, signalé')
        inv = f('lg_warehouse_inventory', p_warehouse_id=wmia)
        ok(inv['expected'] >= 4 and inv['seen'] == 1 and inv['missing'] == inv['expected'] - 1, 'inventaire : %d attendus, 1 vu, le reste à chercher' % inv['expected'])
        inv_a01 = f('lg_warehouse_inventory', p_warehouse_id=wmia, p_location_id=a01)
        ok(all(x['location'] == 'A-01' for x in inv_a01['parcels']), 'inventaire d\'un seul emplacement')
        for nom_, kw in (('lg_locate_parcel', {'p_code': num(p5)}), ('lg_warehouse_inventory', {'p_warehouse_id': wmia})):
            fr(nom_, 'LG003', '%s refusé à un CLIENT' % nom_, acteur=client_compte, **kw)
            code, texte = cl.run(B, appel(nom_, **kw), role='anon', expect_error=True)
            ok(code != 0 and '42501' in texte, '%s refusé à un visiteur' % nom_)

        print('PASS workflow du colis (phase 3) : %d vérifications — 462 paires de statuts (104 valides acceptées, 358 invalides refusées), flux cible '
              'de bout en bout par les vraies fonctions (suivi + audit + événement à chaque pas, notifications), livraison manquée / replanifiée / '
              'annulée, aucune modification directe ni retour arbitraire, cohérence colis–mission–expédition à la validation, double scan, hors ligne, '
              'collision, colis inconnu, colis livré, QR / Code 128 / saisie, recherche d\'emplacement et inventaire (PostgreSQL %s).'
              % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC workflow du colis (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
