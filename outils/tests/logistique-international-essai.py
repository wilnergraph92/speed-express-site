#!/usr/bin/env python3
"""Phase 4 — le transport international (étape 016), chaque parcours éprouvé DEUX fois : sur la RÉPLIQUE DE LA PRODUCTION
(noyau 001 → 016 par-dessus les données du 7 octobre) et sur une PRÉPRODUCTION montée comme la vraie (installation assemblée,
données synthétiques, noyau 001 → 016, rattrapage).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-international-essai.py

Les parcours :
 A. Miami → Port-au-Prince, en AVION, en direct : consolidation (responsable, poids, volume, entrepôt source), unité logistique
    (ULD) chargée dans sa limite, SCELLÉE obligatoirement avant le départ, ouverte pour inspection puis rescellée ; transport
    créé par la façade (compagnie, numéro de vol, dates prévues, capacité) ; droits de douane fixés, PAYÉS avant la libération ;
    hub de destination prévu à l'avance ;
 B. Miami → Saint-Domingue, en BATEAU, en direct : capacité du navire refusée puis respectée, inspection, deux EXCEPTIONS de
    douane (l'une levée : le colis rattrape son expédition jusqu'au hub ; l'autre saisie : colis perdu), le reste libéré ;
 C. Miami → Saint-Domingue en bateau, puis CAMION vers Port-au-Prince (TRANSBORDEMENT) : à Saint-Domingue, les colis pour la
    République dominicaine passent la douane, ceux pour Haïti restent « en transit » (événement de hub de transit, pas de douane) ;
    une ÉTAPE SUIVANTE les emmène ; ils ne passent la douane qu'à Port-au-Prince ; l'expédition d'avant ne les déplace plus ;
    une expédition de pur transit va au hub sans douane locale ; le camion ne relie pas Miami ;
 D. le SUIVI client : le parcours en huit étapes calculé par la base (Réception → Livraison), daté, avec les hubs de transit et
    l'exception ; le client ne voit que ses colis, le visiteur rien ; chaque étape tracée (suivi, audit, événement, même corrélation).
Jamais la production."""
import importlib.util
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]
ETAPES = ['reception', 'warehouse', 'consolidation', 'departure', 'transit', 'arrival', 'customs', 'delivery']


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
    if isinstance(v, (list, tuple)):
        if not v:
            return "'{}'"
        return "array[%s]::%s[]" % (', '.join(val(x) for x in v), 'uuid' if re.match(r'^[0-9a-f-]{36}$', str(v[0])) else 'text')
    return "'%s'" % str(v).replace("'", "''")


def appel(nom, **kw):
    return "select public.%s(%s)" % (nom, ', '.join('%s => %s' % (k, val(v)) for k, v in kw.items()))


def cles(x, chemin=''):
    """Toutes les clés d'une réponse JSON, avec leur chemin (les tableaux comptent pour « [] ») : comme le test du portail."""
    sortie = set()
    if isinstance(x, dict):
        for k, v in x.items():
            sortie.add(chemin + '.' + k)
            sortie |= cles(v, chemin + '.' + k)
    elif isinstance(x, list):
        for v in x:
            sortie |= cles(v, chemin + '[]')
    return sortie


def etats(j):
    return [s['state'] for s in j['steps']]


def parcours(cl, B, lieu):
    """Les quatre parcours sur la base B (« réplique » ou « préproduction »)."""
    q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
    equipe = lambda role: q("select id from public.clients where role = '%s' order by email limit 1" % role)   # noqa: E731
    admin, gerant, op = equipe('admin'), equipe('gerant'), equipe('employe')
    q("update logistics.app_user set rights = array['colis.lire', 'colis.statut'] where id = '%s'" % op)
    clients = cl.lignes(B, "select c.id from public.clients c join logistics.customer k on k.legacy_client_id = c.id where c.role = 'client' order by c.email limit 2")
    client_compte, autre_client = clients[0], clients[1]
    cust = q("select id from logistics.customer where legacy_client_id = '%s'" % client_compte)
    org = q('select id from logistics.organization')
    q("insert into logistics.branch (organization_id, code, name, kind, country) select id, c, n, k, p from logistics.organization, (values "
      "('MIA', 'Miami', 'office', 'US'), ('PAP', 'Hub Port-au-Prince', 'hub', 'HT'), ('SDQ', 'Hub Saint-Domingue', 'hub', 'DO')) v(c, n, k, p)")
    br = lambda c: q("select id from logistics.branch where code = '%s'" % c)   # noqa: E731
    mia, pap, sdq = br('MIA'), br('PAP'), br('SDQ')
    q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'MIA-1', 'Entrepôt Miami'), ('%s', 'PAP-1', 'Entrepôt Port-au-Prince'), "
      "('%s', 'SDQ-1', 'Entrepôt Saint-Domingue')" % (mia, pap, sdq))
    wh = lambda c: q("select id from logistics.warehouse where code = '%s'" % c)   # noqa: E731
    wmia, wpap, wsdq = wh('MIA-1'), wh('PAP-1'), wh('SDQ-1')
    q("insert into logistics.warehouse_location (warehouse_id, code) values ('%s', 'A-01')" % wmia)
    a01 = q("select id from logistics.warehouse_location where code = 'A-01'")

    def f(nom, acteur=op, **kw):
        code, sortie = cl.run(B, appel(nom, **kw), role='authenticated', claims=acteur)
        return json.loads(sortie) if sortie.startswith(('{', '[')) else sortie

    def fr(nom, etat, msg, acteur=op, role='authenticated', **kw):
        code, texte = cl.run(B, appel(nom, **kw), role=role, claims=acteur, expect_error=True)
        ok(code != 0 and etat in texte, '[%s] %s : attendu %s, obtenu : %s' % (lieu, msg, etat, texte[-220:].replace('\n', ' ')))
        return texte

    n_colis = [0]

    def colis(pays='HT', mode='air', poids=5, valeur=50, natif=False):
        """Un colis du noyau. Natif : il naît CREATED et passe par les vrais scans ; sinon il est posé « rangé » (décor)."""
        n_colis[0] += 1
        num = 'SES-91%08d' % n_colis[0]
        statut, source = ('CREATED', 'native') if natif else ('STORED', 'legacy_backfill')
        pid = q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, "
                "status_authority, source, weight_lb, declared_value, description, recipient_name, current_warehouse_id, current_location_id) values "
                "('%s', '%s', 'jeton-i%d', '%s', '%s', '%s', '%s', 'core', '%s', %s, %s, 'colis %d', 'Destinataire', %s, %s) returning id" % (
                    org, num, n_colis[0], cust, pays, mode, statut, source, poids, valeur, n_colis[0],
                    'null' if natif else "'%s'" % wmia, 'null' if natif else "'%s'" % a01))
        if natif:
            f('lg_scan_parcel', p_code=num, p_purpose='receive', p_warehouse_id=wmia, p_code_kind='barcode')
            f('lg_transition_parcel', p_parcel_id=pid, p_to_status='INSPECTED')
            f('lg_scan_parcel', p_code=num, p_purpose='store', p_warehouse_id=wmia, p_location_id=a01, p_code_kind='barcode')
        f('lg_scan_parcel', p_code=num, p_purpose='consolidate', p_warehouse_id=wmia, p_code_kind='barcode')
        return pid

    num = lambda pid: q("select tracking_number from logistics.parcel where id = '%s'" % pid)   # noqa: E731
    st = lambda pid: q("select status from logistics.parcel where id = '%s'" % pid)   # noqa: E731

    def consolider(code, pays, mode, parcels):
        c = f('lg_open_consolidation', p_code=code, p_warehouse_id=wmia, p_destination_country=pays, p_mode=mode)['consolidation_id']
        for p in parcels:
            f('lg_add_parcel_to_consolidation', p_consolidation_id=c, p_parcel_id=p)
        f('lg_close_consolidation', p_consolidation_id=c)
        return c

    def preparer(sh):
        f('lg_generate_manifest', p_shipment_id=sh)
        f('lg_mark_shipment_ready', p_shipment_id=sh)

    def transport(mode, carrier, voyage, de, vers, capacite=None, volume=None):
        return f('lg_create_transport', p_mode=mode, p_carrier=carrier, p_reference='REF-' + voyage, p_voyage_number=voyage, p_origin_branch=de,
                 p_destination_branch=vers, p_planned_departure=R("now() + interval '1 day'"), p_planned_arrival=R("now() + interval '3 days'"),
                 p_capacity_weight_lb=capacite, p_capacity_volume_ft3=volume)['transport_id']

    def journey(p, acteur=None):
        return f('lg_my_parcel_journey', acteur=acteur or client_compte, p_tracking_number=num(p))

    # ====================================================================== A. Miami → Port-au-Prince, avion, direct
    a1 = colis(natif=True)
    a2 = colis()
    ok(st(a1) == 'CONSOLIDATION_PENDING' and st(a2) == 'CONSOLIDATION_PENDING', '[%s] A : deux colis prêts à consolider (dont un natif, scanné de bout en bout)' % lieu)
    ca = f('lg_open_consolidation', p_code='INT-CA', p_warehouse_id=wmia, p_destination_country='HT', p_mode='air')['consolidation_id']
    for p in (a1, a2):
        f('lg_add_parcel_to_consolidation', p_consolidation_id=ca, p_parcel_id=p)
    fr('lg_assign_consolidation_responsible', 'LG005', 'un client comme responsable de consolidation', p_consolidation_id=ca, p_user_id=client_compte)
    s = f('lg_assign_consolidation_responsible', p_consolidation_id=ca, p_user_id=gerant)
    ok(s['parcels'] == 2 and float(s['total_weight_lb']) == 10 and float(s['declared_value']) == 100 and s['warehouse']['code'] == 'MIA-1'
       and s['responsible']['user_id'] == gerant and s['status'] == 'OPEN',
       '[%s] A : fiche de consolidation (2 colis, 10 lb, 100 $, entrepôt source, responsable) : %s' % (lieu, s))
    ok(q("select count(*) from logistics.domain_event where event_type = 'ConsolidationResponsibleAssigned' and aggregate_id = '%s'" % ca) == '1', '[%s] A : responsable : un événement' % lieu)
    petit = f('lg_create_load_unit', p_code='uld-petit', p_kind='ULD', p_max_weight_lb=7)['load_unit_id']
    uld = f('lg_create_load_unit', p_code='uld-1', p_kind='ULD', p_max_weight_lb=500, p_max_volume_ft3=150)
    ok(uld['code'] == 'ULD-1' and uld['status'] == 'OPEN', '[%s] A : unité logistique créée (code normalisé)' % lieu)
    uld = uld['load_unit_id']
    fr('lg_create_load_unit', 'LG005', 'un type d\'unité inconnu', p_code='X-1', p_kind='CAISSE')
    fr('lg_put_consolidation_in_load_unit', 'FERMER', 'charger une consolidation encore ouverte', p_consolidation_id=ca, p_load_unit_id=uld)
    f('lg_close_consolidation', p_consolidation_id=ca)
    fr('lg_put_consolidation_in_load_unit', 'Poids maximal', 'dépasser le poids maximal d\'une unité (10 lb > 7 lb)', p_consolidation_id=ca, p_load_unit_id=petit)
    fr('lg_seal_load_unit', 'vide', 'sceller une unité vide', p_load_unit_id=petit, p_seal_number='S-0')
    u = f('lg_put_consolidation_in_load_unit', p_consolidation_id=ca, p_load_unit_id=uld)
    ok(u['parcels'] == 2 and float(u['weight_lb']) == 10 and u['consolidations'] == 1, '[%s] A : consolidation chargée dans l\'ULD (2 colis, 10 lb)' % lieu)
    vol = transport('air', 'Compagnie fictive', 'xa101', mia, pap, capacite=100)
    ok(q("select voyage_number || '|' || status from logistics.transport where id = '%s'" % vol) == 'XA101|PLANNED', '[%s] A : vol créé (numéro normalisé, PRÉVU)' % lieu)
    fr('lg_create_transport', 'camion', 'un camion Miami → Port-au-Prince', p_mode='ground', p_carrier='Transporteur', p_reference='T', p_voyage_number='T1',
       p_origin_branch=mia, p_destination_branch=pap, p_planned_departure=R('now()'), p_planned_arrival=R("now() + interval '1 day'"))
    fr('lg_create_transport', 'arrivée avant', 'un transport qui arrive avant de partir', p_mode='air', p_carrier='C', p_reference='R', p_voyage_number='V',
       p_origin_branch=mia, p_destination_branch=pap, p_planned_departure=R("now() + interval '2 days'"), p_planned_arrival=R('now()'))
    fr('lg_create_transport', 'fournisseur', 'un transport sans fournisseur', p_mode='air', p_carrier=' ', p_reference='R', p_voyage_number='V',
       p_origin_branch=mia, p_destination_branch=pap, p_planned_departure=R('now()'), p_planned_arrival=R("now() + interval '1 day'"))
    sa = f('lg_create_shipment', p_code='INT-SA', p_mode='air', p_origin_branch=mia, p_destination_branch=pap, p_load_unit_ids=[uld])['shipment_id']
    fr('lg_plan_shipment', 'hub de destination', 'un hub de destination qui n\'est pas à Port-au-Prince', p_shipment_id=sa,
       p_planned_departure=R("now() + interval '1 day'"), p_planned_arrival=R("now() + interval '2 days'"), p_hub_warehouse_id=wsdq)
    pl = f('lg_plan_shipment', p_shipment_id=sa, p_planned_departure=R("now() + interval '1 day'"), p_planned_arrival=R("now() + interval '2 days'"), p_hub_warehouse_id=wpap)
    ok(pl['hub_warehouse']['code'] == 'PAP-1' and pl['planned_arrival_at'] and pl['parcels'] == 2 and pl['destination']['country'] == 'HT',
       '[%s] A : expédition planifiée (dates prévues, hub de destination)' % lieu)
    preparer(sa)
    fr('lg_dispatch_shipment', 'pas scellée', 'partir avec une unité NON scellée', p_shipment_id=sa, p_transport_id=vol)
    u = f('lg_seal_load_unit', p_load_unit_id=uld, p_seal_number='sl-0001')
    ok(u['status'] == 'SEALED' and u['seal_number'] == 'SL-0001' and u['sealed_at'], '[%s] A : ULD scellée' % lieu)
    fr('lg_put_consolidation_in_load_unit', 'LG004', 'charger dans une unité scellée', p_consolidation_id=ca, p_load_unit_id=uld)
    fr('lg_open_load_unit', 'motif', 'ouvrir un scellé sans motif', p_load_unit_id=uld, p_reason=' ')
    u = f('lg_open_load_unit', p_load_unit_id=uld, p_reason='Inspection de sûreté avant vol')
    ok(u['status'] == 'OPENED' and u['opened_reason'].startswith('Inspection'), '[%s] A : ouverture tracée (motif)' % lieu)
    fr('lg_dispatch_shipment', 'pas scellée', 'partir avec une unité ouverte', p_shipment_id=sa, p_transport_id=vol)
    f('lg_seal_load_unit', p_load_unit_id=uld, p_seal_number='SL-0002')
    ok(q("select string_agg(action, '>' order by id) from logistics.audit_log where entity_type = 'load_unit' and entity_id = '%s'" % uld) ==
       'load_unit.seal>load_unit.open>load_unit.seal', '[%s] A : scellé, ouvert, rescellé : trois audits' % lieu)
    d = f('lg_dispatch_shipment', p_shipment_id=sa, p_transport_id=vol, p_idempotency_key='int-a')
    ok(d['status'] == 'DISPATCHED' and st(a1) == 'IN_TRANSIT' and st(a2) == 'IN_TRANSIT', '[%s] A : départ (unité scellée, capacité respectée) : en transit' % lieu)
    j = journey(a1)
    ok(etats(j) == ['done'] * 4 + ['current'] + ['upcoming'] * 3 and j['current_step'] == 'transit',
       '[%s] A : suivi client en vol : quatre étapes franchies, « Transit » en cours : %s' % (lieu, etats(j)))
    ok(all(s['at'] for s in j['steps'][:4]) and j['transport']['mode'] == 'air' and j['transport']['voyage_number'] == 'XA101'
       and j['transport']['carrier'] == 'Compagnie fictive' and j['exception'] is None and j['transit_hubs'] == [],
       '[%s] A : chaque étape franchie est DATÉE ; le vol, sa compagnie, aucun hub de transit' % lieu)
    f('lg_arrive_shipment', p_shipment_id=sa)
    ok(st(a1) == 'ARRIVED', '[%s] A : arrivé à Port-au-Prince' % lieu)
    f('lg_start_customs', p_shipment_id=sa, p_reference='DEC-A', p_broker='Courtier fictif', p_documents=R('\'[{"type": "AIR_WAYBILL", "reference": "AWB-1"}]\'::jsonb'))
    c = f('lg_customs_assess_duties', p_shipment_id=sa, p_amount=25, p_currency='USD')
    ok(float(c['duties_amount']) == 25 and c['duties_paid'] is False and c['documents'] == 1, '[%s] A : droits fixés (25 $), non payés, un document' % lieu)
    fr('lg_customs_assess_duties', 'Devise', 'une devise inconnue', p_shipment_id=sa, p_amount=1, p_currency='EUR')
    fr('lg_clear_customs', 'pas payés', 'libérer avec des droits impayés', p_shipment_id=sa)
    c = f('lg_customs_mark_duties_paid', p_shipment_id=sa)
    ok(c['duties_paid'] is True, '[%s] A : droits payés' % lieu)
    fr('lg_customs_mark_duties_paid', 'LG004', 'payer deux fois', p_shipment_id=sa)
    f('lg_clear_customs', p_shipment_id=sa)
    f('lg_receive_at_hub', p_shipment_id=sa)
    ok(st(a1) == 'AT_DESTINATION_HUB' and q("select current_warehouse_id from logistics.parcel where id = '%s'" % a1) == wpap,
       '[%s] A : au hub, dans l\'entrepôt PRÉVU par le plan (sans le redonner)' % lieu)
    j = journey(a1)
    ok(etats(j) == ['done'] * 7 + ['current'] and j['current_step'] == 'delivery' and j['steps'][4]['at'] is None and j['steps'][6]['at'],
       '[%s] A : suivi : douane franchie, « Livraison » en cours ; un vol direct n\'a pas de date de transit propre' % lieu)
    sm = f('lg_shipment_summary', p_shipment_id=sa)
    ok(sm['status'] == 'AT_HUB' and sm['parcels'] == 2 and float(sm['weight_lb']) == 10 and sm['load_units'][0]['seal_number'] == 'SL-0002'
       and sm['transport']['voyage_number'] == 'XA101' and sm['customs']['duties_paid'] is True and sm['by_destination'] == {'HT': 2},
       '[%s] A : fiche d\'expédition complète : %s' % (lieu, sm))

    # ====================================================================== B. Miami → Saint-Domingue, bateau, direct, exceptions
    b = [colis('DO', 'sea') for _ in range(3)]
    cb = consolider('INT-CB', 'DO', 'sea', b)
    sb = f('lg_create_shipment', p_code='INT-SB', p_mode='sea', p_origin_branch=mia, p_destination_branch=sdq, p_consolidation_ids=[cb])['shipment_id']
    preparer(sb)
    navire_petit = transport('sea', 'Armateur fictif', 'V-12', mia, sdq, capacite=12)
    fr('lg_dispatch_shipment', 'Capacité du transport', 'dépasser la capacité du navire (15 lb > 12 lb)', p_shipment_id=sb, p_transport_id=navire_petit)
    ok(st(b[0]) == 'READY_FOR_EXPORT' and q("select status from logistics.transport where id = '%s'" % navire_petit) == 'PLANNED', '[%s] B : refusé, rien n\'a bougé' % lieu)
    f('lg_schedule_transport', p_transport_id=navire_petit, p_planned_departure=R("now() + interval '5 days'"), p_planned_arrival=R("now() + interval '9 days'"))
    ok(q("select count(*) from logistics.domain_event where event_type = 'TransportScheduled' and aggregate_id = '%s'" % navire_petit) == '1', '[%s] B : horaires replanifiés, tracés' % lieu)
    navire = transport('sea', 'Armateur fictif', 'V-221', mia, sdq, capacite=1000, volume=500)
    f('lg_dispatch_shipment', p_shipment_id=sb, p_transport_id=navire)
    fr('lg_schedule_transport', 'LG004', 'replanifier un navire parti', p_transport_id=navire, p_planned_departure=R('now()'), p_planned_arrival=R("now() + interval '1 day'"))
    f('lg_arrive_shipment', p_shipment_id=sb)
    ok(all(st(p) == 'ARRIVED' for p in b), '[%s] B : arrivés à Saint-Domingue (leur pays)' % lieu)
    f('lg_start_customs', p_shipment_id=sb, p_reference='DEC-B', p_broker='Courtier fictif', p_documents=R("'[]'::jsonb"))
    ins = f('lg_customs_inspect', p_shipment_id=sb, p_result='ISSUES_FOUND', p_notes='Valeur douteuse', p_tracking_numbers=[num(b[0])])
    ok(ins['declaration_status'] == 'UNDER_REVIEW', '[%s] B : inspection : déclaration en examen' % lieu)
    x1 = f('lg_customs_raise_exception', p_shipment_id=sb, p_parcel_id=b[0], p_kind='UNDERVALUED', p_description='Facture absente')
    x2 = f('lg_customs_raise_exception', p_shipment_id=sb, p_parcel_id=b[1], p_kind='PROHIBITED_ITEM', p_description='Article interdit')
    ok(st(b[0]) == 'ON_HOLD' and st(b[1]) == 'ON_HOLD' and st(b[2]) == 'CUSTOMS_PROCESSING', '[%s] B : deux colis RETENUS, le troisième suit' % lieu)
    fr('lg_customs_raise_exception', 'EN DOUANE', 'une seconde exception sur un colis déjà retenu', p_shipment_id=sb, p_parcel_id=b[0], p_kind='OTHER', p_description='x')
    fr('lg_customs_raise_exception', 'pas dans cette expédition', 'une exception sur le colis d\'une autre expédition', p_shipment_id=sb, p_parcel_id=a1, p_kind='OTHER', p_description='x')
    j = journey(b[0])
    ok(j['current_step'] == 'customs' and j['exception']['kind'] == 'paused' and j['exception']['status'] == 'ON_HOLD',
       '[%s] B : suivi client : « Douane » en cours, exception « en pause » : %s' % (lieu, j['exception']))
    f('lg_clear_customs', p_shipment_id=sb)
    f('lg_receive_at_hub', p_shipment_id=sb, p_hub_warehouse_id=wsdq)
    ok(st(b[2]) == 'AT_DESTINATION_HUB' and st(b[0]) == 'ON_HOLD', '[%s] B : l\'expédition continue sans les colis retenus' % lieu)
    fr('lg_customs_resolve_exception', 'LG003', 'un employé lève une exception (réservé à la direction)', p_exception_id=x1['exception_id'], p_outcome='RELEASED', p_resolution='ok')
    fr('lg_customs_resolve_exception', 'expliquée', 'lever sans explication', acteur=gerant, p_exception_id=x1['exception_id'], p_outcome='RELEASED', p_resolution=' ')
    r1 = f('lg_customs_resolve_exception', acteur=gerant, p_exception_id=x1['exception_id'], p_outcome='RELEASED', p_resolution='Facture fournie')
    ok(r1['parcel_status'] == 'AT_DESTINATION_HUB' and q("select current_warehouse_id from logistics.parcel where id = '%s'" % b[0]) == wsdq,
       '[%s] B : exception LEVÉE : le colis rattrape son expédition jusqu\'au hub' % lieu)
    ok(cl.lignes(B, "select to_status from logistics.tracking_event where parcel_id = '%s' and from_status is distinct from to_status order by id" % b[0])[-4:] ==
       ['ON_HOLD', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB'], '[%s] B : son chemin réel : retenu, repris, libéré, au hub' % lieu)
    r2 = f('lg_customs_resolve_exception', acteur=gerant, p_exception_id=x2['exception_id'], p_outcome='SEIZED', p_resolution='Saisi : article interdit')
    ok(r2['parcel_status'] == 'LOST', '[%s] B : exception SAISIE : colis perdu pour le client' % lieu)
    fr('lg_customs_resolve_exception', 'LG004', 'lever deux fois la même exception', acteur=gerant, p_exception_id=x2['exception_id'], p_outcome='RELEASED', p_resolution='x')
    j = journey(b[1])
    ok(j['exception']['kind'] == 'stopped' and etats(j)[-1] == 'stopped' and j['current_step'] == 'customs', '[%s] B : suivi d\'un colis saisi : arrêté à la douane' % lieu)
    sm = f('lg_shipment_summary', p_shipment_id=sb)
    ok(sm['customs']['inspections'] == 1 and sm['customs']['open_exceptions'] == 0 and sm['transport']['voyage_number'] == 'V-221', '[%s] B : fiche : 1 inspection, 0 exception ouverte' % lieu)
    code, texte = cl.run(B, "update logistics.customs_inspection set result = 'PASSED'", expect_error=True)
    ok(code != 0, '[%s] B : l\'inspection est en ajout seul' % lieu)

    # ====================================================================== C. Miami → Saint-Domingue (bateau) → Port-au-Prince (camion)
    h1, h2 = colis('HT', 'sea'), colis('HT', 'sea')
    d1 = colis('DO', 'sea')
    ch = consolider('INT-CH', 'HT', 'sea', [h1, h2])
    cd = consolider('INT-CD', 'DO', 'sea', [d1])
    s1 = f('lg_create_shipment', p_code='INT-T1', p_mode='sea', p_origin_branch=mia, p_destination_branch=sdq, p_consolidation_ids=[ch, cd])['shipment_id']
    ok(f('lg_shipment_summary', p_shipment_id=s1)['by_destination'] == {'DO': 1, 'HT': 2}, '[%s] C : une expédition, deux pays de destination' % lieu)
    preparer(s1)
    f('lg_dispatch_shipment', p_shipment_id=s1, p_transport_id=transport('sea', 'Armateur fictif', 'V-300', mia, sdq))
    ar = f('lg_arrive_shipment', p_shipment_id=s1)
    ok(ar['in_transit_here'] == 2 and st(d1) == 'ARRIVED' and st(h1) == 'IN_TRANSIT' and st(h2) == 'IN_TRANSIT',
       '[%s] C : à Saint-Domingue, le colis dominicain ARRIVE, les deux haïtiens restent EN TRANSIT' % lieu)
    ok(q("select count(*) from logistics.tracking_event where parcel_id = '%s' and event_type = 'ParcelTransitHubReached' and from_status = to_status" % h1) == '1',
       '[%s] C : hub de transit : un événement, sans changement de statut' % lieu)
    corr = q("select correlation_id from logistics.tracking_event where parcel_id = '%s' and event_type = 'ParcelTransitHubReached'" % h1)
    ok(q("select count(*) from logistics.audit_log where correlation_id = '%s' and entity_id = '%s' and action = 'parcel.milestone'" % (corr, h1)) == '1'
       and q("select count(*) from logistics.domain_event where correlation_id = '%s' and aggregate_id = '%s' and event_type = 'ParcelTransitHubReached'" % (corr, h1)) == '1',
       '[%s] C : l\'étape de transit a son audit et son événement, même corrélation' % lieu)
    j = journey(h1)
    ok(j['current_step'] == 'transit' and j['transit_hubs'][0]['event'] == 'ParcelTransitHubReached' and 'Saint-Domingue' in (j['steps'][4]['place'] or ''),
       '[%s] C : suivi client : « Transit » en cours, à Saint-Domingue : %s' % (lieu, j['steps'][4]))
    fr('lg_receive_at_hub', 'douane de ce pays', 'passer au hub avant la douane du colis dominicain', p_shipment_id=s1)
    dec = f('lg_start_customs', p_shipment_id=s1, p_reference='DEC-T1', p_broker='Courtier fictif', p_documents=R("'[]'::jsonb"))
    ok(float(dec['declared_value']) == 50 and st(h1) == 'IN_TRANSIT', '[%s] C : la douane dominicaine ne déclare QUE le colis dominicain (50 $)' % lieu)
    f('lg_clear_customs', p_shipment_id=s1)
    f('lg_receive_at_hub', p_shipment_id=s1, p_hub_warehouse_id=wsdq)
    ok(st(d1) == 'AT_DESTINATION_HUB' and st(h1) == 'IN_TRANSIT', '[%s] C : le colis dominicain au hub, les haïtiens toujours en transit' % lieu)
    fr('lg_create_onward_shipment', 'pas arrivé à ce hub', 'une étape suivante qui part d\'un autre hub', p_code='INT-X', p_mode='ground',
       p_origin_branch=pap, p_destination_branch=sdq, p_parcel_ids=[h1])
    fr('lg_create_onward_shipment', 'EN TRANSIT', 'emmener en étape suivante un colis arrivé à destination', p_code='INT-X', p_mode='ground',
       p_origin_branch=sdq, p_destination_branch=pap, p_parcel_ids=[d1])
    s2 = f('lg_create_onward_shipment', p_code='INT-T2', p_mode='ground', p_origin_branch=sdq, p_destination_branch=pap, p_parcel_ids=[h1, h2], p_idempotency_key='int-t2')
    ok(s2['status'] == 'DRAFT' and s2['parcels'] == 2, '[%s] C : ÉTAPE SUIVANTE créée (camion Saint-Domingue → Port-au-Prince)' % lieu)
    ok(f('lg_create_onward_shipment', p_code='INT-T2', p_mode='ground', p_origin_branch=sdq, p_destination_branch=pap, p_parcel_ids=[h1, h2],
         p_idempotency_key='int-t2')['shipment_id'] == s2['shipment_id'], '[%s] C : rejouée avec la même clé : la même étape' % lieu)
    s2 = s2['shipment_id']
    ok(q("select logistics.parcel_current_shipment('%s')" % h1) == s2, '[%s] C : l\'expédition courante du colis est l\'étape suivante' % lieu)
    sm1 = f('lg_shipment_summary', p_shipment_id=s1)
    ok(sm1['moved_on'] == 2 and sm1['parcels'] == 1 and sm1['onward_legs'] == ['INT-T2'], '[%s] C : la première étape : 2 colis partis plus loin, 1 resté' % lieu)
    camion = transport('ground', 'Transporteur fictif', 'TR-9', sdq, pap, capacite=500)
    preparer(s2)
    d = f('lg_dispatch_shipment', p_shipment_id=s2, p_transport_id=camion)
    ok(d['parcels']['transshipped'] == 2 and st(h1) == 'IN_TRANSIT', '[%s] C : départ du camion : 2 colis TRANSBORDÉS, toujours en transit' % lieu)
    ok(q("select count(*) from logistics.tracking_event where parcel_id = '%s' and event_type = 'ParcelTransshipped'" % h1) == '1', '[%s] C : transbordement tracé' % lieu)
    f('lg_arrive_shipment', p_shipment_id=s2)
    ok(st(h1) == 'ARRIVED' and st(h2) == 'ARRIVED', '[%s] C : arrivés à Port-au-Prince, LEUR pays' % lieu)
    f('lg_start_customs', p_shipment_id=s2, p_reference='DEC-T2', p_broker='Courtier fictif', p_documents=R("'[]'::jsonb"))
    f('lg_clear_customs', p_shipment_id=s2)
    f('lg_receive_at_hub', p_shipment_id=s2, p_hub_warehouse_id=wpap)
    ok(st(h1) == 'AT_DESTINATION_HUB' and q("select current_warehouse_id from logistics.parcel where id = '%s'" % h1) == wpap, '[%s] C : douane HAÏTIENNE, puis hub de Port-au-Prince' % lieu)
    chemin = cl.lignes(B, "select to_status from logistics.tracking_event where parcel_id = '%s' and from_status is distinct from to_status order by id" % h1)
    ok(chemin[-5:] == ['IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB'] and chemin.count('CUSTOMS_PROCESSING') == 1,
       '[%s] C : UNE seule douane, à l\'arrivée finale : %s' % (lieu, chemin))
    j = journey(h1)
    ok(etats(j) == ['done'] * 7 + ['current'] and [t['event'] for t in j['transit_hubs']] == ['ParcelTransitHubReached', 'ParcelTransshipped']
       and 'Port-au-Prince' in (j['steps'][5]['place'] or '') and j['steps'][3]['place'] == 'Miami' and j['transport']['mode'] == 'ground',
       '[%s] C : suivi client : deux étapes de transit (hub atteint, transbordé), arrivée à Port-au-Prince, dernier moyen : camion' % lieu)
    # Une expédition de PUR transit : arrivée au hub intermédiaire, sans douane locale
    h3 = colis('HT', 'sea')
    s3 = f('lg_create_shipment', p_code='INT-T3', p_mode='sea', p_origin_branch=mia, p_destination_branch=sdq, p_consolidation_ids=[consolider('INT-CH3', 'HT', 'sea', [h3])])['shipment_id']
    preparer(s3)
    f('lg_dispatch_shipment', p_shipment_id=s3, p_transport_id=transport('sea', 'Armateur fictif', 'V-301', mia, sdq))
    f('lg_arrive_shipment', p_shipment_id=s3)
    f('lg_receive_at_hub', p_shipment_id=s3, p_hub_warehouse_id=wsdq)
    ok(q("select status from logistics.shipment where id = '%s'" % s3) == 'AT_HUB' and st(h3) == 'IN_TRANSIT',
       '[%s] C : pur transit : l\'expédition passe au hub sans douane, le colis attend son étape suivante' % lieu)
    s4 = f('lg_create_onward_shipment', p_code='INT-T4', p_mode='ground', p_origin_branch=sdq, p_destination_branch=pap, p_parcel_ids=[h3])['shipment_id']
    f('lg_cancel_shipment', acteur=gerant, p_shipment_id=s4, p_reason='camion indisponible')
    ok(q("select logistics.parcel_current_shipment('%s')" % h3) == s3 and st(h3) == 'IN_TRANSIT', '[%s] C : étape suivante annulée : le colis retourne à sa première étape' % lieu)

    # ====================================================================== D. le suivi : confidentialité, cohérence
    fr('lg_my_parcel_journey', 'introuvable', 'le suivi du colis d\'un AUTRE client', acteur=autre_client, p_tracking_number=num(a1))
    code, texte = cl.run(B, appel('lg_my_parcel_journey', p_tracking_number=num(a1)), role='anon', expect_error=True)
    ok(code != 0 and '42501' in texte, '[%s] D : un visiteur n\'appelle pas le suivi' % lieu)
    fr('lg_parcel_journey', 'LG003', 'le suivi « équipe » par un client', acteur=client_compte, p_code=num(a1))
    ok(f('lg_parcel_journey', p_code=num(h1)) == journey(h1), '[%s] D : l\'équipe et le client voient le MÊME parcours' % lieu)
    fr('lg_shipment_summary', 'LG003', 'la fiche d\'expédition par un client', acteur=client_compte, p_shipment_id=sa)
    ok(q("select count(*) from logistics.workflow_inconsistencies()") == '0', '[%s] D : aucun colis incohérent après les trois parcours' % lieu)
    ok(q("select count(*) from logistics.tracking_event e where e.parcel_id in (select id from logistics.parcel where public_token like 'jeton-i%%') and not exists ("
         "select 1 from logistics.audit_log a where a.correlation_id = e.correlation_id and a.entity_id = e.parcel_id::text)") == '0',
       '[%s] D : chaque événement de suivi des parcours a son audit (même corrélation)' % lieu)
    # La FORME du parcours et la signature de sa fonction, figées pour le test du navigateur (portail-contrat.cjs) : un colis transbordé
    # (transport, hubs de transit) et un colis saisi (exception) couvrent toutes les clés.
    return {'forme': sorted(cles(journey(h1)) | cles(journey(b[1]))),
            'signature': json.loads(q("select json_build_object(p.proname, (select coalesce(json_agg(json_build_object('nom', p.proargnames[u.ord], 'type', format_type(u.t, null), "
                                      "'defaut', u.ord > p.pronargs - p.pronargdefaults) order by u.ord), '[]'::json) from unnest(p.proargtypes::oid[]) with ordinality u(t, ord))) "
                                      "from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = 'lg_my_parcel_journey'"))}


def main():
    with P.Cluster() as cl:
        # ------------------------------------------------------------------ la réplique de la production
        if not P.monter_production(cl, 'prod'):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        cl.run('postgres', "alter database prod set timezone to 'America/Port-au-Prince'")
        etapes = sorted(os.listdir(os.path.join(P.RACINE, 'outils', 'logistique')))
        for f in etapes:
            cl.run('prod', P.lire_sql('outils/logistique/' + f))
        q = lambda sql: cl.un('prod', sql)   # noqa: E731
        n = q("select count(*) from logistics.shipment_transition") + '|' + q("select count(*) from logistics.event_type")
        cl.run('prod', P.lire_sql('outils/logistique/016-transport-international.sql'))
        ok(q("select count(*) from logistics.shipment_transition") + '|' + q("select count(*) from logistics.event_type") == n, '016 rejouée : rien en double')
        ok(q("select count(*) from logistics.event_type where code in ('ParcelTransitHubReached', 'ParcelTransshipped') and customer_visible") == '2',
           'les étapes de transit sont visibles du client')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and "
             "(has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))") == '0',
           'aucune fonction du noyau n\'est ouverte à anon ou authenticated')
        facades = cl.lignes('prod', "select p.proname from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname in ("
                                    "'lg_create_transport', 'lg_schedule_transport', 'lg_plan_shipment', 'lg_create_onward_shipment', 'lg_shipment_summary', "
                                    "'lg_consolidation_summary', 'lg_assign_consolidation_responsible', 'lg_create_load_unit', 'lg_put_consolidation_in_load_unit', "
                                    "'lg_seal_load_unit', 'lg_open_load_unit', 'lg_load_unit_summary', 'lg_customs_assess_duties', 'lg_customs_mark_duties_paid', "
                                    "'lg_customs_inspect', 'lg_customs_raise_exception', 'lg_customs_resolve_exception', 'lg_my_parcel_journey', 'lg_parcel_journey') "
                                    "and has_function_privilege('authenticated', p.oid, 'execute') and not has_function_privilege('anon', p.oid, 'execute')")
        ok(len(facades) == 19, '19 façades nouvelles : comptes connectés seulement (%d)' % len(facades))
        ok(q("select count(*) from pg_tables t join pg_class c on c.relname = t.tablename and c.relnamespace = 'logistics'::regnamespace "
             "where t.schemaname = 'logistics' and not c.relrowsecurity") == '0', 'RLS partout (dont inspections et exceptions de douane)')
        ok(q("select count(*) from information_schema.role_table_grants where table_schema = 'logistics' and grantee in ('anon', 'authenticated', 'PUBLIC')") == '0',
           'aucun droit direct sur les tables du noyau')
        ok(json.loads(q("select logistics.run_migration('décor du transport international')"))['report']['ready'] is True, 'réplique : rattrapage prêt')
        contrat = parcours(cl, 'prod', 'réplique')
        ici = os.path.dirname(os.path.abspath(__file__))
        chemin_forme, chemin_rpc = os.path.join(ici, 'parcours-formes.json'), os.path.join(ici, 'parcours-rpc.json')
        if os.environ.get('SES_FORME_ECRIRE'):
            json.dump({'parcours': contrat['forme']}, open(chemin_forme, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
            json.dump(contrat['signature'], open(chemin_rpc, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
        ok(json.load(open(chemin_forme, encoding='utf-8')) == {'parcours': contrat['forme']} and json.load(open(chemin_rpc, encoding='utf-8')) == contrat['signature'],
           'la forme du parcours et la signature de lg_my_parcel_journey sont celles du fichier partagé avec le test du navigateur (sinon : SES_FORME_ECRIRE=1, et relire)')
        interdits = ('actor', 'email', 'latitude', 'longitude', 'metadata', 'correlation', 'warehouse', 'driver', 'legacy', 'internal')
        ok(not [c for c in contrat['forme'] if any(m in c.lower() for m in interdits)], 'le parcours ne porte aucune clé interne (acteur, entrepôt, GPS…)')
        ok(q('select count(*) from logistics.reconcile_with_legacy()') == '0', 'réplique : aucun écart avec l\'ancien schéma après les parcours')

        # ------------------------------------------------------------------ la préproduction, montée comme la vraie
        spec = importlib.util.spec_from_file_location('assembler', os.path.join(P.RACINE, 'outils', 'staging', 'assembler-installation.py'))
        A = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(A)
        cl.run('postgres', 'create database staging')
        cl.run('postgres', "alter database staging set timezone to 'America/Port-au-Prince'")
        cl.run('staging', P.lire_sql('scripts/restore/socle-postgres-vide.sql'))
        cl.run('staging', P.AUTH)
        cl.run('staging', P.SUPABASE_DEFAUTS)
        cl.run('staging', A.assembler())
        cl.run('staging', P.lire_sql('outils/staging/donnees-synthetiques.sql'))
        for f in etapes:
            cl.run('staging', P.lire_sql('outils/logistique/' + f))
        qs = lambda sql: cl.un('staging', sql)   # noqa: E731
        ok(qs("select nom from ses_meta.environnement") == 'staging', 'préproduction : marquée « staging »')
        ok(json.loads(qs("select logistics.run_migration('répétition du transport international')"))['report']['ready'] is True,
           'préproduction : noyau 001 → 016 installé, rattrapage prêt')
        parcours(cl, 'staging', 'préproduction')

        print('PASS transport international (phase 4) : %d vérifications — sur la réplique ET la préproduction : Miami → Port-au-Prince en avion '
              '(ULD scellée, capacité, droits payés), Miami → Saint-Domingue en bateau (exceptions de douane levée et saisie), Miami → Saint-Domingue '
              '→ Port-au-Prince (transbordement, douane à l\'arrivée finale, pur transit), suivi client en huit étapes, confidentialité (PostgreSQL %s).'
              % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC transport international (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
