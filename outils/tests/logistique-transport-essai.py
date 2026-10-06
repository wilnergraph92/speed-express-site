#!/usr/bin/env python3
"""Noyau logistique, phase 8 : consolidation, expédition, transport, douane — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-transport-essai.py

Jamais la production. Le flux Colis → Consolidation → Expédition → Transport → Arrivée → Douane → Hub, de bout en bout, avec
la preuve que les statuts de l'expédition et du colis sont SÉPARÉS, que chaque opération produit ses événements, et que
chaque règle d'entreprise refuse ce qu'elle doit refuser."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def refuse(cl, sql, etat, msg, **kw):
    code, texte = cl.run('ses', sql, expect_error=True, **kw)
    ok(code != 0 and etat in texte, '%s : attendu %s, obtenu : %s' % (msg, etat, texte[-170:].replace('\n', ' ')))


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        P.monter_historique(cl, B)
        for f in ('001-modele-de-domaine', '002-retroremplissage', '003-machine-d-etats', '004-entrepot', '005-transport-douane'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f))
        avant = tuple(q('select count(*) from logistics.%s' % t) for t in ('shipment_transition', 'event_type', 'transport_mode', 'parcel_transition'))
        cl.run(B, P.lire_sql('outils/logistique/005-transport-douane.sql'))
        ok(avant == tuple(q('select count(*) from logistics.%s' % t) for t in ('shipment_transition', 'event_type', 'transport_mode', 'parcel_transition')), '005 rejouée : aucune ligne en double')
        ok(q("select count(*) from logistics.parcel_transition") == '87', 'la phase 8 ajoute UNE transition de colis (READY_FOR_EXPORT → CONSOLIDATED) : 87')
        q('select logistics.backfill_from_legacy()')

        uid = lambda n: q("select id from public.clients where email = 'client%d@essai.test'" % n)   # noqa: E731
        admin, gerant, op, sansdroit, cli = uid(1), uid(2), uid(3), uid(6), uid(9)
        q("insert into logistics.app_user (id, organization_id, role, rights) select '%s', id, 'employee', '{}' from logistics.organization" % sansdroit)
        q("insert into logistics.branch (organization_id, code, name, kind, country) select id, c, n, k, p from logistics.organization, (values "
          "('MIA', 'Miami', 'office', 'US'), ('PAP', 'Hub Port-au-Prince', 'hub', 'HT'), ('SDQ', 'Saint-Domingue', 'office', 'DO')) v(c, n, k, p)")
        mia, pap, sdq = (q("select id from logistics.branch where code = '%s'" % c) for c in ('MIA', 'PAP', 'SDQ'))
        q("insert into logistics.warehouse (branch_id, code, name) values ('%s', 'MIA-1', 'Entrepôt Miami'), ('%s', 'PAP-1', 'Entrepôt hub')" % (mia, pap))
        wmia, wpap = q("select id from logistics.warehouse where code = 'MIA-1'"), q("select id from logistics.warehouse where code = 'PAP-1'")
        q("insert into logistics.transport (mode, carrier, reference) values ('air', 'Compagnie fictive', 'XX123'), ('sea', 'Armement fictif', 'NAVIRE-9'), ('air', 'Compagnie fictive', 'XX124'), ('air', 'Compagnie fictive', 'XX125')")
        vol1, navire, vol2, vol3 = (q("select id from logistics.transport where reference = '%s'" % r) for r in ('XX123', 'NAVIRE-9', 'XX124', 'XX125'))
        org = q('select id from logistics.organization')
        customers = cl.lignes(B, "select id from logistics.customer order by code limit 3")
        n_p = [0]

        def colis(statut='CONSOLIDATION_PENDING', pays='HT', mode='air', client=True, cust=None):
            n_p[0] += 1
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source, weight_lb, declared_value, description, recipient_name) "
                     "values ('%s', 'P-%d', 'tok', %s, '%s', '%s', '%s', 'core', 'legacy_backfill', %d, %d, 'colis %d', 'Destinataire %d') returning id" % (
                         org, n_p[0], "'%s'" % (cust or customers[n_p[0] % 3]) if client else 'null', pays, mode, statut, 10 + n_p[0], 100 + n_p[0], n_p[0], n_p[0]))

        def f(nom, *args, acteur=op, **kw):
            return json.loads(cl.run(B, "select public.%s(%s)" % (nom, ', '.join(args)), role='authenticated', claims=acteur, **kw)[1])

        def fr(nom, *args, etat, msg, acteur=op):
            refuse(cl, "select public.%s(%s)" % (nom, ', '.join(args)), etat, msg, role='authenticated', claims=acteur)

        st = lambda t, i: q("select status from logistics.%s where id = '%s'" % (t, i))   # noqa: E731
        qs = lambda s: "'%s'" % s   # noqa: E731

        # ============================================================== A. le flux complet
        ps = [colis() for _ in range(3)]; loose = colis()
        cons = f('lg_open_consolidation', "'CONS-001'", qs(wmia), "'HT'", "'air'")
        cid = cons['consolidation_id']
        ok(cons['status'] == 'OPEN', 'CONSOLIDATION ouverte')
        for p in ps: f('lg_add_parcel_to_consolidation', qs(cid), qs(p))
        ok(q("select count(*) from logistics.consolidation_parcel where consolidation_id = '%s' and removed_at is null" % cid) == '3', 'PLUSIEURS colis (de plusieurs clients) dans UNE consolidation')
        ok(q("select count(distinct customer_id) from logistics.parcel where id in (%s)" % ','.join(qs(p) for p in ps)) == '3', '…appartenant à trois clients différents')
        r = f('lg_close_consolidation', qs(cid))
        ok(r['status'] == 'CLOSED' and r['parcels'] == 3, 'consolidation FERMÉE avec 3 colis')
        ok(all(st('parcel', p) == 'CONSOLIDATED' for p in ps), 'chaque colis est passé « consolidé » (machine du colis)')
        ok(q("select count(*) from logistics.domain_event where event_type = 'ParcelConsolidated' and aggregate_id in (%s)" % ','.join(qs(p) for p in ps)) == '3', '3 événements « ParcelConsolidated »')
        ok(q("select count(*) from logistics.domain_event where event_type = 'ConsolidationClosed' and aggregate_id = '%s'" % cid) == '1', '1 événement « ConsolidationClosed »')
        ok(q("select count(distinct correlation_id) from logistics.domain_event where (aggregate_id in (%s) and event_type = 'ParcelConsolidated') or (aggregate_id = '%s' and event_type = 'ConsolidationClosed')" % (','.join(qs(p) for p in ps), cid)) == '1',
           'une seule corrélation relie la consolidation et ses colis')

        sh = f('lg_create_shipment', "'SHP-001'", "'air'", qs(mia), qs(pap), "array['%s']::uuid[]" % cid, "array['%s']::uuid[]" % loose)
        sid = sh['shipment_id']
        ok(sh['status'] == 'DRAFT' and sh['parcels'] == 4, 'EXPÉDITION créée : une consolidation (3 colis) + un colis en vrac = 4 colis')
        ok(st('parcel', loose) == 'CONSOLIDATED', 'le colis en vrac est passé « consolidé » à la création')
        ok(q("select count(*) from logistics.shipment_item where shipment_id = '%s'" % sid) == '2', 'une expédition contient plusieurs éléments')
        fr('lg_mark_shipment_ready', qs(sid), etat='LG005', msg='PRÊTE sans manifeste')
        m1 = f('lg_generate_manifest', qs(sid))
        ok(m1['version'] == 1 and m1['content']['totals']['parcels'] == 4 and len(m1['content']['parcels']) == 4, 'MANIFESTE généré : version 1, 4 colis')
        ok(m1['content']['totals']['weight_lb'] == sum(10 + i for i in range(1, 5)) and m1['content']['shipment']['destination'] == 'PAP', 'poids total et destination du manifeste')
        rdy = f('lg_mark_shipment_ready', qs(sid))
        ok(rdy['status'] == 'READY' and rdy['parcels']['moved'] == 4 and all(st('parcel', p) == 'READY_FOR_EXPORT' for p in ps + [loose]), 'expédition PRÊTE : ses 4 colis passent « prêts pour l\'export »')
        ok(st('shipment', sid) == 'READY', 'le statut de l\'EXPÉDITION est READY (vocabulaire propre)')

        d = f('lg_dispatch_shipment', qs(sid), qs(vol1), "'dsp-1'")
        ok(d['status'] == 'DISPATCHED' and all(st('parcel', p) == 'IN_TRANSIT' for p in ps + [loose]), 'DISPATCH : l\'expédition part, ses colis sont « en transit »')
        ok(q("select status || '/' || (actual_departure_at is not null)::text from logistics.transport where id = '%s'" % vol1) == 'DEPARTED/true', 'le TRANSPORT est parti')
        ok(q("select transport_id::text from logistics.shipment where id = '%s'" % sid) == vol1 and q("select dispatched_at is not null from logistics.shipment where id = '%s'" % sid) == 't', 'l\'expédition est liée à son transport, départ daté')
        d2 = f('lg_dispatch_shipment', qs(sid), qs(vol1), "'dsp-1'")
        ok(d2['replayed'] is True and q("select count(*) from logistics.shipment_status_history where shipment_id = '%s' and to_status = 'DISPATCHED'" % sid) == '1', 'dispatch rejoué (même clé) : une seule fois')
        ok(f('lg_mark_shipment_in_transit', qs(sid))['status'] == 'IN_TRANSIT', 'expédition « en transit »')
        a = f('lg_arrive_shipment', qs(sid))
        ok(a['status'] == 'ARRIVED' and all(st('parcel', p) == 'ARRIVED' for p in ps + [loose]), 'ARRIVÉE : expédition et colis « arrivés »')
        ok(q("select status from logistics.transport where id = '%s'" % vol1) == 'ARRIVED', 'tous les envois du transport sont arrivés : le TRANSPORT est arrivé')
        c = f('lg_start_customs', qs(sid), "'DEC-2026-77'", "'Courtier fictif'", "'[{\"type\": \"PACKING_LIST\", \"reference\": \"PL-1\", \"path\": \"customs/%s/pl.pdf\"}]'::jsonb" % sid)
        ok(c['status'] == 'CUSTOMS_PROCESSING' and c['declared_value'] == sum(100 + i for i in range(1, 5)) and all(st('parcel', p) == 'CUSTOMS_PROCESSING' for p in ps + [loose]), 'DOUANE : déclaration déposée (valeur déclarée totale), colis « en douane »')
        ok(q("select status || '/' || origin_country || '/' || destination_country from logistics.customs_declaration where shipment_id = '%s'" % sid) == 'SUBMITTED/US/HT', 'déclaration SUBMITTED, pays d\'origine et de destination déduits des succursales')
        ok(q("select count(*) from logistics.customs_document where declaration_id = '%s'" % c['declaration_id']) == '1', 'document de douane enregistré')
        cc = f('lg_clear_customs', qs(sid))
        ok(cc['status'] == 'CUSTOMS_CLEARED' and all(st('parcel', p) == 'CUSTOMS_CLEARED' for p in ps + [loose]) and q("select status from logistics.customs_declaration where id = '%s'" % c['declaration_id']) == 'CLEARED', 'DÉDOUANÉ')
        h = f('lg_receive_at_hub', qs(sid), qs(wpap))
        ok(h['status'] == 'AT_HUB' and all(st('parcel', p) == 'AT_DESTINATION_HUB' for p in ps + [loose]), 'HUB : l\'expédition arrive au hub, ses colis y sont')
        ok(q("select count(*) from logistics.parcel where id in (%s) and current_warehouse_id = '%s'" % (','.join(qs(p) for p in ps + [loose]), wpap)) == '4', 'les colis sont rattachés à l\'entrepôt du hub')
        fr('lg_close_shipment', qs(sid), etat='LG005', msg='fermer une expédition dont les colis attendent encore au hub')
        for p in ps + [loose]: q("select logistics.transition_parcel('%s', 'DELIVERY_ASSIGNED', '%s', null, null, null, null, '', null, null, '{}', 'api')" % (p, op))
        ok(f('lg_close_shipment', qs(sid))['status'] == 'CLOSED', 'expédition CLOSE quand tous ses colis sont pris en charge pour la livraison')

        # ------------------------------------------------------------------ statuts séparés, événements, historique
        ok(q("select string_agg(to_status, '>' order by id) from logistics.shipment_status_history where shipment_id = '%s'" % sid) == 'DRAFT>READY>DISPATCHED>IN_TRANSIT>ARRIVED>CUSTOMS_PROCESSING>CUSTOMS_CLEARED>AT_HUB>CLOSED',
           'l\'historique de l\'EXPÉDITION : 9 états, dans l\'ordre')
        ev = q("select string_agg(event_type, '>' order by id) from logistics.domain_event where aggregate_type = 'shipment' and aggregate_id = '%s'" % sid)
        ok(ev == 'ShipmentCreated>ManifestGenerated>ShipmentReady>ShipmentDispatched>ShipmentInTransit>ShipmentArrived>ShipmentCustomsStarted>ShipmentCustomsCleared>ShipmentAtHub>ShipmentClosed', 'événements de l\'expédition : %s' % ev)
        ok(q("select count(*) from logistics.domain_event where aggregate_type = 'customs'") == '2', 'événements de douane : dépôt et acceptation')
        ok(set(cl.lignes(B, "select code from logistics.shipment_status")) & set(cl.lignes(B, "select code from logistics.parcel_status")) == {'IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'CANCELLED'},
           'deux vocabulaires distincts : seuls cinq mots sont communs (le reste est propre à chaque objet)')
        refuse(cl, "update logistics.shipment set status = 'DISPATCHED' where id = '%s'" % sid, 'LG001', 'UPDATE direct du statut d\'une expédition')
        refuse(cl, "insert into logistics.shipment (code, mode, status) values ('X', 'air', 'READY')", 'LG001', 'une expédition naît ailleurs qu\'en DRAFT')
        refuse(cl, "update logistics.shipment_status_history set reason = 'x'", 'LG004', 'modifier l\'historique d\'expédition')
        ok(q("select count(*) from logistics.audit_log where entity_type = 'shipment' and entity_id = '%s'" % sid) == '9', 'audit : 1 création + 8 transitions')

        # ============================================================== B. la cascade respecte l'état de chaque colis
        pa, pb, pc, pd = colis(), colis(), colis(), colis()
        c2 = f('lg_open_consolidation', "'CONS-002'", qs(wmia), "'HT'", "'air'")['consolidation_id']
        for p in (pa, pb, pc, pd): f('lg_add_parcel_to_consolidation', qs(c2), qs(p))
        f('lg_close_consolidation', qs(c2))
        s2 = f('lg_create_shipment', "'SHP-002'", "'air'", qs(mia), qs(pap), "array['%s']::uuid[]" % c2)['shipment_id']
        f('lg_generate_manifest', qs(s2))
        q("select logistics.transition_parcel('%s', 'ON_HOLD', '%s', null, null, null, null, '', null, 'contrôle douanier', '{}', 'api')" % (pb, op))
        fr('lg_mark_shipment_ready', qs(s2), etat='LG005', msg='un colis est passé en attente APRÈS le manifeste : le manifeste est PÉRIMÉ')
        m2 = f('lg_generate_manifest', qs(s2))
        ok(m2['version'] == 2 and m2['content']['totals']['held'] == 1, 'manifeste régénéré (version 2) : il signale le colis retenu')
        r = f('lg_mark_shipment_ready', qs(s2))
        ok(r['parcels']['moved'] == 3 and len(r['parcels']['skipped']) == 1 and r['parcels']['skipped'][0]['status'] == 'ON_HOLD', 'seuls 3 colis sur 4 passent « prêts » : le colis EN ATTENTE est sauté et rapporté')
        f('lg_dispatch_shipment', qs(s2), qs(vol2))
        ok(st('parcel', pb) == 'ON_HOLD' and st('parcel', pa) == 'IN_TRANSIT', 'le colis retenu NE PART PAS avec le lot')
        ok(q("select count(*) from logistics.shipment_manifest where shipment_id = '%s'" % s2) == '2', 'les deux versions du manifeste sont conservées')
        refuse(cl, "update logistics.shipment_manifest set content_hash = 'x'", 'LG004', 'modifier un manifeste')
        refuse(cl, "delete from logistics.shipment_manifest", 'LG004', 'supprimer un manifeste')

        # ============================================================== C. refus de la douane
        f('lg_arrive_shipment', qs(s2)); c_ = f('lg_start_customs', qs(s2), "'DEC-1'")
        fr('lg_reject_customs', qs(s2), "' '", etat='LG005', msg='refus sans motif')
        rj = f('lg_reject_customs', qs(s2), "'valeur déclarée contestée'")
        ok(rj['status'] == 'REJECTED' and rj['shipment_status'] == 'CUSTOMS_PROCESSING', 'REFUS de la douane : l\'expédition RESTE en douane')
        ok(q("select count(*) from logistics.customs_declaration where shipment_id = '%s' and status <> 'REJECTED'" % s2) == '0', 'plus aucune déclaration vivante')
        refuse(cl, "insert into logistics.customs_declaration (shipment_id, status) values ('%s', 'SUBMITTED'), ('%s', 'SUBMITTED')" % (s2, s2), '23505', 'DEUX déclarations vivantes pour une expédition')
        q("insert into logistics.customs_declaration (shipment_id, status, reference) values ('%s', 'SUBMITTED', 'DEC-2')" % s2)
        ok(f('lg_clear_customs', qs(s2), "'DEC-2'")['status'] == 'CUSTOMS_CLEARED', 'une NOUVELLE déclaration est acceptée')

        # ============================================================== D. règles de consolidation
        pw = colis(statut='STORED'); pu = colis(pays='DO'); pm = colis(mode='sea'); pn = colis(client=False); ok_p = colis()
        c3 = f('lg_open_consolidation', "'CONS-003'", qs(wmia), "'HT'", "'air'")['consolidation_id']
        fr('lg_add_parcel_to_consolidation', qs(c3), qs(pw), etat='LG005', msg='un colis qui n\'est pas « en attente de consolidation »')
        fr('lg_add_parcel_to_consolidation', qs(c3), qs(pu), etat='LG005', msg='une AUTRE destination')
        fr('lg_add_parcel_to_consolidation', qs(c3), qs(pm), etat='LG005', msg='un AUTRE mode de transport')
        fr('lg_add_parcel_to_consolidation', qs(c3), qs(pn), etat='LG005', msg='un colis sans client')
        fr('lg_close_consolidation', qs(c3), etat='LG005', msg='fermer une consolidation VIDE')
        f('lg_add_parcel_to_consolidation', qs(c3), qs(ok_p))
        refuse(cl, "select public.lg_add_parcel_to_consolidation('%s', '%s')" % (c2, ok_p), 'LG004', 'ajouter à une consolidation CLOSE', role='authenticated', claims=op)
        c4 = f('lg_open_consolidation', "'CONS-004'", qs(wmia), "'HT'", "'air'")['consolidation_id']
        refuse(cl, "select public.lg_add_parcel_to_consolidation('%s', '%s')" % (c4, ok_p), '23505', 'un colis dans DEUX consolidations actives', role='authenticated', claims=op)
        cl.run(B, "select public.lg_remove_parcel_from_consolidation('%s', '%s')" % (c3, ok_p), role='authenticated', claims=op)   # ne renvoie rien
        f('lg_add_parcel_to_consolidation', qs(c4), qs(ok_p))
        ok(q("select count(*) from logistics.consolidation_parcel where parcel_id = '%s'" % ok_p) == '2', 'retiré d\'une consolidation, le colis entre dans une autre (l\'historique des deux reste)')
        fr('lg_create_shipment', "'SHP-X'", "'air'", qs(mia), qs(pap), "array['%s']::uuid[]" % c4, etat='LG005', msg='expédier une consolidation OUVERTE')
        f('lg_close_consolidation', qs(c4), "'close-1'"); r1 = f('lg_close_consolidation', qs(c4), "'close-1'")
        ok(r1['replayed'] is True, 'fermeture rejouée (même clé) : même résultat')
        fr('lg_close_consolidation', qs(c4), etat='LG004', msg='fermer deux fois')

        # ============================================================== E. règles d'expédition
        fr('lg_create_shipment', "'SHP-Y'", "'air'", qs(mia), qs(sdq), "array['%s']::uuid[]" % c4, etat='LG005', msg='la destination n\'est pas un HUB')
        fr('lg_create_shipment', "'SHP-Y'", "'sea'", qs(mia), qs(pap), "array['%s']::uuid[]" % c4, etat='LG005', msg='mode de l\'expédition ≠ mode de la consolidation')
        fr('lg_create_shipment', "'SHP-Y'", "'air'", qs(mia), qs(pap), etat='LG005', msg='expédition vide')
        fr('lg_create_shipment', "'SHP-Y'", "'teleport'", qs(mia), qs(pap), "array['%s']::uuid[]" % c4, etat='LG005', msg='mode inconnu')
        s3 = f('lg_create_shipment', "'SHP-003'", "'air'", qs(mia), qs(pap), "array['%s']::uuid[]" % c4)['shipment_id']
        fr('lg_create_shipment', "'SHP-004'", "'air'", qs(mia), qs(pap), "array['%s']::uuid[]" % c4, etat='LG005', msg='la MÊME consolidation dans deux expéditions actives')
        fr('lg_dispatch_shipment', qs(s3), qs(vol1), etat='LG001', msg='partir sans être PRÊTE')
        fr('lg_arrive_shipment', qs(s3), etat='LG001', msg='arriver avant d\'être partie')
        fr('lg_start_customs', qs(s3), etat='LG001', msg='douane avant l\'arrivée')
        fr('lg_clear_customs', qs(s3), etat='LG002', msg='accepter une déclaration qui n\'existe pas')
        fr('lg_receive_at_hub', qs(s3), etat='LG001', msg='hub avant la douane')
        f('lg_generate_manifest', qs(s3)); f('lg_mark_shipment_ready', qs(s3))
        fr('lg_dispatch_shipment', qs(s3), qs(navire), etat='mode', msg='transport d\'un AUTRE mode')
        q("update logistics.transport set status = 'CANCELLED' where id = '%s'" % vol2)
        fr('lg_dispatch_shipment', qs(s3), qs(vol2), etat='CANCELLED', msg='transport ANNULÉ')
        fr('lg_dispatch_shipment', qs(s3), "'00000000-0000-0000-0000-00000000dead'", etat='LG002', msg='transport inconnu')
        q("update logistics.parcel set verified_weight_lb = 99 where id = '%s'" % ok_p)       # le poids change après le manifeste
        # le transport vol3 est LIBRE et du bon mode : la SEULE raison possible du refus est le manifeste périmé
        fr('lg_dispatch_shipment', qs(s3), qs(vol3), etat='périmé', msg='partir avec un manifeste PÉRIMÉ (un poids a changé)')
        ok(q("select status from logistics.transport where id = '%s'" % vol3) == 'PLANNED', 'le transport libre n\'a pas bougé')
        f('lg_generate_manifest', qs(s3))
        fr('lg_cancel_shipment', qs(s3), "'erreur de saisie'", etat='LG003', msg='un employé annule une expédition (réservé à la direction)', acteur=op)
        fr('lg_cancel_shipment', qs(s3), "' '", etat='LG005', msg='annuler sans motif', acteur=gerant)
        cn = f('lg_cancel_shipment', qs(s3), "'erreur de saisie'", acteur=gerant)
        ok(cn['status'] == 'CANCELLED' and st('parcel', ok_p) == 'CONSOLIDATED', 'ANNULATION d\'une expédition PRÊTE (par le gérant) : rouverte, ses colis reviennent « consolidés »')
        ok(q("select string_agg(to_status, '>' order by id) from logistics.shipment_status_history where shipment_id = '%s'" % s3) == 'DRAFT>READY>DRAFT>CANCELLED', 'historique : DRAFT>READY>DRAFT>CANCELLED')
        s4 = f('lg_create_shipment', "'SHP-004'", "'air'", qs(mia), qs(pap), "array['%s']::uuid[]" % c4)
        ok(s4['status'] == 'DRAFT', 'la consolidation d\'une expédition ANNULÉE peut partir dans une autre')

        # ============================================================== F. unités logistiques et modes futurs
        lu = q("insert into logistics.load_unit (code, kind, max_weight_lb) values ('CONT-1', 'CONTAINER', 40000) returning id")
        pl1 = colis(mode='sea'); c5 = f('lg_open_consolidation', "'CONS-005'", qs(wmia), "'HT'", "'sea'")['consolidation_id']
        f('lg_add_parcel_to_consolidation', qs(c5), qs(pl1)); f('lg_close_consolidation', qs(c5))
        q("update logistics.consolidation set load_unit_id = '%s' where id = '%s'" % (lu, c5))
        s5 = f('lg_create_shipment', "'SHP-005'", "'sea'", qs(mia), qs(pap), "'{}'::uuid[]", "'{}'::uuid[]", "array['%s']::uuid[]" % lu)
        ok(s5['parcels'] == 1, 'UN CONTENEUR (unité logistique) entre dans une expédition avec les colis de ses consolidations')
        refuse(cl, "insert into logistics.shipment_item (shipment_id, parcel_id, load_unit_id) values ('%s', '%s', '%s')" % (s5['shipment_id'], pl1, lu), '23514', 'un élément à la fois colis ET unité')
        fr('lg_create_shipment', "'SHP-006'", "'sea'", qs(mia), qs(pap), "'{}'::uuid[]", "'{}'::uuid[]", "array['%s']::uuid[]" % lu, etat='LG005', msg='la même unité dans deux expéditions')
        q("insert into logistics.transport_mode (code, label_key) values ('rail', 'mode-rail')")
        q("insert into logistics.transport (mode, carrier, reference) values ('rail', 'Chemin de fer fictif', 'TRAIN-1')")
        ok(q("select count(*) from logistics.transport where mode = 'rail'") == '1', 'MODE FUTUR : ajouter « rail » est une ligne de données, pas une migration')
        c6 = f('lg_open_consolidation', "'CONS-006'", qs(wmia), "'HT'", "'rail'")
        ok(c6['status'] == 'OPEN', '…et il est aussitôt utilisable (consolidation en mode rail)')
        refuse(cl, "insert into logistics.transport (mode) values ('teleport')", '23503', 'un mode non déclaré')
        fr('lg_open_consolidation', "'CONS-007'", qs(wmia), "'HT'", "'teleport'", etat='LG005', msg='mode inconnu à l\'ouverture')

        # ============================================================== G. droits, façade, fermeture
        for fn, args in (('lg_open_consolidation', ["'C-X'", qs(wmia), "'HT'", "'air'"]), ('lg_generate_manifest', [qs(s2)]), ('lg_arrive_shipment', [qs(s2)])):
            refuse(cl, "select public.%s(%s)" % (fn, ', '.join(args)), '42501', '%s par un visiteur' % fn, role='anon')
            for qui, nom in ((cli, 'un client'), (sansdroit, 'un employé sans droit')):
                refuse(cl, "select public.%s(%s)" % (fn, ', '.join(args)), 'LG003', '%s par %s' % (fn, nom), role='authenticated', claims=qui)
        refuse(cl, "select logistics.dispatch_shipment('%s', '%s', '%s')" % (s2, vol1, op), '42501', 'le noyau appelé directement', role='authenticated', claims=op)
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and (has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))") == '0',
           'aucune fonction du noyau n\'est ouverte à anon ou authenticated')
        ok(q("select count(*) from pg_tables t join pg_class c on c.relname = t.tablename and c.relnamespace = 'logistics'::regnamespace where t.schemaname = 'logistics' and not c.relrowsecurity") == '0', 'RLS partout')
        ok(q("select count(*) from information_schema.role_table_grants where table_schema = 'logistics' and grantee in ('anon', 'authenticated', 'PUBLIC')") == '0', 'aucun droit direct sur les tables')
        ok(q('select count(*) from logistics.reconcile_with_legacy()') == '0', 'aucun écart avec l\'ancien schéma')

        print('PASS transport et douane (phase 8) : %d vérifications — flux complet Colis → Consolidation → Expédition → Transport → Arrivée → Douane → Hub, statuts de l\'expédition '
              'séparés de ceux du colis, cascade qui épargne les colis retenus, manifeste figé et vérifié, refus de douane, modes futurs et unités logistiques, droits (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC transport (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
