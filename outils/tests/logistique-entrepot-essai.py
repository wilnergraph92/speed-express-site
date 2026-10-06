#!/usr/bin/env python3
"""Noyau logistique, phase 7 : l'entrepôt et les scanners — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-entrepot-essai.py

Jamais la production. Teste : la décision d'un scan sur 5 040 combinaisons, le flux réception →
vérification → rangement → déplacement, chaque cas limite (colis inconnu, étiquette falsifiée, doublon, mauvais
entrepôt, colis déjà sorti, endommagé, interdit, sans client), les droits, l'idempotence, la piste d'audit complète,
et que le résultat ne dépend pas du type de lecteur."""
import itertools
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


STATUTS = ['CREATED', 'RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT', 'IN_TRANSIT', 'ARRIVED',
           'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY', 'DELIVERED',
           'ON_HOLD', 'CANCELLED', 'DAMAGED', 'LOST', 'RETURNED']
INTENTIONS = ['receive', 'verify', 'store', 'move', 'consolidate', 'dispatch', 'lookup']
PARTIS = {'IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY', 'DELIVERED', 'RETURNED'}
EN_ENTREPOT = ['RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT']
W1, W2 = '11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222'
L1, L2 = '33333333-3333-4333-8333-333333333333', '44444444-4444-4444-8444-444444444444'


def attendu(statut, interdit, client, pw, pl, intention, w, l):
    """La spécification, écrite autrement que le SQL : des ensembles, pas une chaîne de « si »."""
    if intention == 'lookup': return 'ACCEPTED'
    if statut in PARTIS: return 'ALREADY_DISPATCHED'
    if statut in ('CANCELLED', 'LOST'): return 'WRONG_STATE'
    if interdit: return 'PROHIBITED'
    if statut == 'ON_HOLD': return 'WRONG_STATE'
    if statut == 'DAMAGED' and intention != 'move': return 'DAMAGED'
    if pw is not None and pw != w: return 'WRONG_ENTREPOT'.replace('ENTREPOT', 'WAREHOUSE')
    eligibles = {'receive': {'CREATED'}, 'verify': {'RECEIVED'}, 'store': {'VERIFIED'}, 'consolidate': {'STORED'}, 'dispatch': {'READY_FOR_EXPORT'},
                 'move': set(EN_ENTREPOT) | {'DAMAGED'}}
    doublons = {'receive': set(EN_ENTREPOT), 'verify': set(EN_ENTREPOT[1:]), 'consolidate': {'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT'}}
    if intention == 'move':
        if statut in eligibles['move'] and l is not None:
            return 'DUPLICATE' if pl == l else 'ACCEPTED'
        return 'WRONG_STATE'
    if statut in eligibles[intention]:
        if intention == 'consolidate' and not client: return 'NO_CUSTOMER'
        return 'ACCEPTED'
    if intention == 'store' and statut == 'STORED' and pl == l: return 'DUPLICATE'
    if statut in doublons.get(intention, set()): return 'DUPLICATE'
    return 'WRONG_STATE'


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        P.monter_historique(cl, B)
        for f in ('001-modele-de-domaine', '002-retroremplissage', '003-machine-d-etats', '004-entrepot'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f))
        avant = (q('select count(*) from logistics.parcel_transition'), q('select count(*) from logistics.event_type'))
        cl.run(B, P.lire_sql('outils/logistique/004-entrepot.sql'))
        ok(avant == (q('select count(*) from logistics.parcel_transition'), q('select count(*) from logistics.event_type')), '004 rejouée : aucune ligne en double')
        q('select logistics.backfill_from_legacy()')

        # ------------------------------------------------------------------ A. la décision, 5 040 combinaisons
        lignes = cl.lignes(B, """
          select s.code || '|' || p.i || '|' || x.b || '|' || c.b || '|' || coalesce(pw.v::text, '') || '|' || coalesce(pl.v::text, '') || '|' || wr.v || '|' || coalesce(lr.v::text, '') || '|' ||
                 logistics.assess_scan(s.code, x.b, c.b, pw.v, pl.v, p.i, wr.v, lr.v)
          from logistics.parcel_status s
          cross join unnest(array['receive','verify','store','move','consolidate','dispatch','lookup']) p(i)
          cross join (values (true), (false)) x(b) cross join (values (true), (false)) c(b)
          cross join (values (null::uuid), ('%s'::uuid), ('%s'::uuid)) pw(v)
          cross join (values (null::uuid), ('%s'::uuid)) pl(v)
          cross join (values ('%s'::uuid)) wr(v)
          cross join (values (null::uuid), ('%s'::uuid), ('%s'::uuid)) lr(v)""" % (W1, W2, L1, W1, L1, L2))
        ok(len(lignes) == 20 * 7 * 2 * 2 * 3 * 2 * 1 * 3, 'la décision est exercée sur %d combinaisons' % len(lignes))
        ecarts = []
        for l in lignes:
            st, it, pr, cu, pw, pl, w, lo, res = l.split('|')
            e = attendu(st, pr == 'true', cu == 'true', pw or None, pl or None, it, w, lo or None)
            if e != res: ecarts.append((st, it, pr, cu, pw[:2], pl[:2], lo[:2], 'attendu', e, 'obtenu', res))
        ok(not ecarts, 'la décision d\'un scan = la spécification sur toutes les combinaisons (%d écarts ; ex. %s)' % (len(ecarts), ecarts[:2]))
        ok(set(l.split('|')[-1] for l in lignes) == {'ACCEPTED', 'DUPLICATE', 'WRONG_STATE', 'ALREADY_DISPATCHED', 'WRONG_WAREHOUSE', 'DAMAGED', 'PROHIBITED', 'NO_CUSTOMER'},
           'chaque résultat possible est atteint au moins une fois')

        # ------------------------------------------------------------------ B. lecture d'un code, quel que soit le lecteur
        pc = lambda c: q("select logistics.parse_code('%s')" % c.replace("'", "''"))   # noqa: E731
        ok(json.loads(pc('SES-90001-HT')) == {'number': 'SES-90001-HT', 'token': None}, 'code-barres : le numéro')
        ok(json.loads(pc('  ses-90001-ht \t'))['number'] == 'SES-90001-HT', 'saisie manuelle : minuscules et espaces ignorés')
        ok(json.loads(pc('https://wilnergraph92.github.io/speed-express-site/suivi.html?colis=SES-90001-HT&j=ab12cd34')) == {'number': 'SES-90001-HT', 'token': 'ab12cd34'},
           'QR : le numéro ET le jeton extraits de l\'adresse')
        ok(json.loads(pc('https://x.test/suivi.html?colis=ses-90001-ht'))['token'] is None, 'adresse sans jeton')
        for mauvais in ('', '   ', '!!', 'a b ; drop table', 'x' * 600, '<script>'):
            refuse(cl, "select logistics.parse_code('%s')" % mauvais, 'LG005', 'code illisible « %s »' % mauvais[:12])

        # ------------------------------------------------------------------ C. décor
        uid = lambda n: q("select id from public.clients where email = 'client%d@essai.test'" % n)   # noqa: E731
        admin, gerant, op, op2, sansdroit, cli, inactif = uid(1), uid(2), uid(3), uid(4), uid(6), uid(9), uid(7)
        q("insert into logistics.app_user (id, organization_id, role, rights) select '%s', id, 'employee', '{}' from logistics.organization" % sansdroit)
        q("insert into logistics.app_user (id, organization_id, role, rights, active) select '%s', id, 'employee', array['colis.statut'], false from logistics.organization" % inactif)
        q("insert into logistics.branch (organization_id, code, name, kind, country) select id, 'MIA', 'Miami', 'office', 'US' from logistics.organization")
        q("insert into logistics.branch (organization_id, code, name, kind, country) select id, 'NYC', 'New York', 'office', 'US' from logistics.organization")
        q("insert into logistics.warehouse (branch_id, code, name) select id, 'MIA-1', 'Entrepôt Miami' from logistics.branch where code = 'MIA'")
        q("insert into logistics.warehouse (branch_id, code, name) select id, 'MIA-2', 'Entrepôt Miami 2' from logistics.branch where code = 'MIA'")
        q("insert into logistics.warehouse (branch_id, code, name) select id, 'NYC-1', 'Entrepôt New York' from logistics.branch where code = 'NYC'")
        w1, w2, w3 = (q("select id from logistics.warehouse where code = '%s'" % c) for c in ('MIA-1', 'MIA-2', 'NYC-1'))
        q("insert into logistics.warehouse_zone (warehouse_id, code, name, kind) values ('%s', 'Q', 'Quarantaine', 'quarantine'), ('%s', 'A', 'Rayons', 'storage')" % (w1, w1))
        q("insert into logistics.warehouse_location (warehouse_id, code, zone_id, kind) select '%s', 'A-01', id, 'storage' from logistics.warehouse_zone where code = 'A' and warehouse_id = '%s'" % (w1, w1))
        q("insert into logistics.warehouse_location (warehouse_id, code, zone_id, kind) select '%s', 'A-02', id, 'storage' from logistics.warehouse_zone where code = 'A' and warehouse_id = '%s'" % (w1, w1))
        q("insert into logistics.warehouse_location (warehouse_id, code, zone_id, kind) select '%s', 'Q-01', id, 'quarantine' from logistics.warehouse_zone where code = 'Q' and warehouse_id = '%s'" % (w1, w1))
        q("insert into logistics.warehouse_location (warehouse_id, code, kind) values ('%s', 'B-01', 'storage')" % w2)
        a1, a2, q1, b1 = (q("select id from logistics.warehouse_location where code = '%s'" % c) for c in ('A-01', 'A-02', 'Q-01', 'B-01'))
        q("update logistics.app_user set branch_id = (select id from logistics.branch where code = 'NYC') where id = '%s'" % op2)   # op2 ne travaille qu'à New York
        q("insert into logistics.device (kind, label) values ('usb_scanner', 'Scanner quai 1'), ('phone_camera', 'Téléphone Ana'), ('desktop_scanner', 'Poste bureau')")
        d_usb, d_cam = q("select id from logistics.device where label = 'Scanner quai 1'"), q("select id from logistics.device where label = 'Téléphone Ana'")
        d_push = q("select id from logistics.device where kind = 'customer_push' limit 1")
        org = q('select id from logistics.organization')
        customer = q("select id from logistics.customer where legacy_client_id = '%s'" % cli)
        compteur = [90000]

        def colis(statut='CREATED', client=True, wh=None, loc=None, interdit=False):
            compteur[0] += 1
            num = 'SES-%d-HT' % compteur[0]
            source = 'native' if statut == 'CREATED' else 'legacy_backfill'
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source, "
                     "current_warehouse_id, current_location_id, is_prohibited, weight_lb) values ('%s', '%s', 'jeton%d', %s, 'HT', 'air', '%s', 'core', '%s', %s, %s, %s, 20) returning id" % (
                         org, num, compteur[0], "'%s'" % customer if client else 'null', statut, source, "'%s'" % wh if wh else 'null', "'%s'" % loc if loc else 'null', 'true' if interdit else 'false')), num

        def scan(num, intention, acteur=op, wh=w1, loc=None, dev=None, kind='barcode', cle=None, **kw):
            sql = "select public.lg_scan_parcel('%s', '%s', '%s', %s, %s, '%s', %s)" % (
                num.replace("'", "''"), intention, wh, "'%s'" % loc if loc else 'null', "'%s'::uuid" % dev if dev else 'null', kind, "'%s'" % cle if cle else 'null')
            return json.loads(cl.run(B, sql, role='authenticated', claims=acteur, **kw)[1])

        # ------------------------------------------------------------------ D. le flux complet, et la piste d'audit de chaque pas
        pid, num = colis('CREATED')
        r = scan(num, 'receive', dev=d_usb, kind='barcode')
        ok(r['result'] == 'ACCEPTED' and r['status'] == 'RECEIVED' and r['warnings'] == [], 'RÉCEPTION : acceptée, colis reçu')
        ok(q("select received_at is not null from logistics.parcel where id = '%s'" % pid) == 't', 'la date de réception est posée')
        r = scan(num, 'verify', dev=d_usb)
        ok(r['result'] == 'ACCEPTED' and r['status'] == 'RECEIVED', 'VÉRIFICATION (scan) : le colis est identifié, l\'inspection suit')
        corr = 'beefcafe-0000-4000-8000-0000000000aa'
        insp = json.loads(cl.run(B, "select public.lg_inspect_parcel('%s', '%s', 22.5, 12, 10, 8, 'GOOD', false, null, 'carton propre', "
                                    "'[{\"path\": \"parcels/%s/avant.jpg\", \"kind\": \"RECEIVING\"}]'::jsonb, '%s', 'barcode', 'insp-1')" % (num, w1, pid, d_usb), role='authenticated', claims=op)[1])
        ok(insp['inspected'] is True and insp['status'] == 'VERIFIED' and insp['warnings'] == ['WEIGHT_DIFFERS'], 'INSPECTION : colis vérifié ; poids 22,5 lb contre 20 déclarés (écart > 10 %) signalé')
        ok(q("select verified_weight_lb::text || '/' || volume_ft3::text || '/' || condition from logistics.parcel where id = '%s'" % pid) == '22.50/0.556/GOOD',
           'poids vérifié, volume calculé (12×10×8 po = 0,556 pi³) et état enregistrés')
        ok(q("select count(*) from logistics.parcel_photo where parcel_id = '%s'" % pid) == '1' and q("select count(*) from logistics.parcel_inspection where parcel_id = '%s'" % pid) == '1', 'photo et inspection enregistrées')
        r = scan(num, 'store', loc=a1, dev=d_cam, kind='qr')
        ok(r['result'] == 'ACCEPTED' and r['status'] == 'STORED', 'RANGEMENT : le colis est rangé')
        ok(q("select current_location from logistics.parcel where id = '%s'" % pid) == 'A-01', 'sa position courante est A-01')
        r = scan(num, 'move', loc=a2)
        ok(r['result'] == 'ACCEPTED' and q("select current_location from logistics.parcel where id = '%s'" % pid) == 'A-02', 'MOUVEMENT : déplacé de A-01 à A-02')
        ok(q("select count(*) from logistics.parcel_movement where parcel_id = '%s'" % pid) == '2', 'deux mouvements enregistrés (rangement, déplacement)')
        ok(q("select count(*) from logistics.parcel_movement where parcel_id = '%s' and from_location_id = '%s' and to_location_id = '%s'" % (pid, a1, a2)) == '1', 'avec l\'origine et la destination')
        r = scan(num, 'consolidate')
        ok(r['result'] == 'ACCEPTED' and r['status'] == 'CONSOLIDATION_PENDING', 'CONSOLIDATION : le colis attend sa consolidation')

        # chaque scan accepté : colis, événement, utilisateur, entrepôt, emplacement, heure, appareil, métadonnées
        ok(q("select count(*) from logistics.scan where parcel_id = '%s' and result = 'ACCEPTED'" % pid) == '6', 'six scans acceptés enregistrés')
        ok(q("select count(*) from logistics.scan where parcel_id = '%s' and actor_user_id is not null and warehouse_id = '%s' and scanned_at is not null and correlation_id is not null" % (pid, w1)) == '6',
           'chaque scan porte l\'utilisateur, l\'entrepôt, l\'heure et la corrélation')
        ok(q("select count(*) from logistics.scan where parcel_id = '%s' and purpose in ('receive','store','consolidate') and tracking_event_id is not null" % pid) == '3', 'les scans qui changent un statut sont reliés à leur événement de suivi')
        ok(q("select count(*) from logistics.scan where parcel_id = '%s' and device_id = '%s'" % (pid, d_usb)) == '3' and q("select count(*) from logistics.scan where parcel_id = '%s' and location_id = '%s'" % (pid, a1)) == '1',
           'l\'appareil et l\'emplacement sont enregistrés')
        ok(int(q("select count(*) from logistics.tracking_event where parcel_id = '%s' and source = 'scan' and actor_user_id = '%s' and warehouse_id is not null" % (pid, op))) >= 5, 'les événements de suivi nomment l\'opérateur et l\'entrepôt')
        ok(int(q("select count(*) from logistics.audit_log where entity_id = '%s'" % pid)) >= 4, 'l\'audit garde chaque transition (avant / après)')
        ok(q("select count(distinct correlation_id) from (select correlation_id from logistics.scan where purpose = 'receive' and parcel_id = '%s' union all "
             "select correlation_id from logistics.tracking_event where parcel_id = '%s' and event_type = 'ParcelReceived' union all "
             "select correlation_id from logistics.domain_event where aggregate_id = '%s' and event_type = 'ParcelReceived') s" % (pid, pid, pid)) == '1',
           'le scan, l\'événement de suivi et l\'événement de domaine d\'une réception partagent UNE corrélation')

        # ------------------------------------------------------------------ E. les cas limites
        e0 = int(q('select count(*) from logistics.tracking_event'))
        # colis inconnu
        r = scan('SES-00000-ZZ', 'receive')
        ok(r['result'] == 'UNKNOWN_PARCEL' and r['parcel_id'] is None and r['incident_id'], 'COLIS INCONNU : refusé, scan tracé, incident ouvert')
        ok(q("select type || '/' || severity from logistics.incident where id = '%s'" % r['incident_id']) == 'UNKNOWN_PARCEL/MEDIUM', 'incident « colis inconnu »')
        r2 = scan('SES-00000-ZZ', 'receive')
        ok(r2['result'] == 'UNKNOWN_PARCEL' and r2['incident_id'] is None and q("select count(*) from logistics.incident where type = 'UNKNOWN_PARCEL'") == '1', 'le même code relu n\'ouvre pas un second incident')
        ok(q("select count(*) from logistics.domain_event where event_type = 'ScanRejected'") == '2', 'chaque refus émet « ScanRejected »')
        # étiquette falsifiée
        pf, nf = colis('CREATED')
        r = scan('https://x.test/suivi.html?colis=%s&j=FAUX' % nf, 'receive', kind='qr')
        ok(r['result'] == 'INVALID_CODE' and q("select status from logistics.parcel where id = '%s'" % pf) == 'CREATED', 'ÉTIQUETTE FALSIFIÉE (numéro connu, jeton faux) : refusée, colis intact')
        ok(q("select severity from logistics.incident where id = '%s'" % r['incident_id']) == 'HIGH', 'incident de gravité haute')
        r = scan('https://x.test/suivi.html?colis=%s&j=jeton%d' % (nf, compteur[0]), 'receive', kind='qr')
        ok(r['result'] == 'ACCEPTED', 'la MÊME étiquette avec le BON jeton est acceptée')
        # doublon
        r = scan(nf, 'receive')
        ok(r['result'] == 'DUPLICATE' and r['status'] == 'RECEIVED', 'DOUBLON : un colis déjà reçu n\'est pas reçu deux fois')
        # mauvais entrepôt
        r = scan(nf, 'verify', wh=w2)
        ok(r['result'] == 'WRONG_WAREHOUSE', 'MAUVAIS ENTREPÔT : le colis a été reçu ailleurs')
        # colis déjà sorti
        ps, ns = colis('IN_TRANSIT', wh=w1)
        ok(scan(ns, 'store', loc=a1)['result'] == 'ALREADY_DISPATCHED', 'COLIS DÉJÀ SORTI : refusé')
        ok(scan(ns, 'receive')['result'] == 'ALREADY_DISPATCHED', 'même en réception')
        # endommagé
        pd_, nd = colis('CREATED'); scan(nd, 'receive')
        r = json.loads(cl.run(B, "select public.lg_inspect_parcel('%s', '%s', 10, null, null, null, 'DAMAGED', false, null, 'carton écrasé', '[]')" % (nd, w1), role='authenticated', claims=op)[1])
        ok(r['status'] == 'DAMAGED' and r['incident_id'], 'ENDOMMAGÉ : l\'inspection met le colis en DAMAGED et ouvre un incident')
        ok(scan(nd, 'store', loc=a1)['result'] == 'DAMAGED', 'un colis endommagé ne se range pas')
        ok(scan(nd, 'consolidate')['result'] == 'DAMAGED', 'ni ne se consolide')
        ok(scan(nd, 'move', loc=q1)['result'] == 'ACCEPTED' and q("select reason from logistics.parcel_movement where parcel_id = '%s'" % pd_) == 'quarantine', 'mais il se déplace en QUARANTAINE')
        # dommage mineur
        pm, nm = colis('CREATED'); scan(nm, 'receive')
        r = json.loads(cl.run(B, "select public.lg_inspect_parcel('%s', '%s', 12, null, null, null, 'MINOR_DAMAGE', false, null, 'coin plié')" % (nm, w1), role='authenticated', claims=op)[1])
        ok(r['status'] == 'VERIFIED' and 'MINOR_DAMAGE' in r['warnings'] and q("select severity from logistics.incident where id = '%s'" % r['incident_id']) == 'LOW', 'DOMMAGE MINEUR : vérifié avec avertissement et incident de gravité basse')
        # interdit
        pi_, ni = colis('CREATED'); scan(ni, 'receive')
        r = json.loads(cl.run(B, "select public.lg_inspect_parcel('%s', '%s', 8, null, null, null, 'GOOD', true, 'batteries au lithium non déclarées')" % (ni, w1), role='authenticated', claims=op)[1])
        ok(r['status'] == 'ON_HOLD' and q("select is_prohibited::text from logistics.parcel where id = '%s'" % pi_) == 'true' and q("select severity from logistics.incident where id = '%s'" % r['incident_id']) == 'HIGH',
           'INTERDIT : colis mis en attente, marqué interdit, incident de gravité haute')
        for it in ('verify', 'store', 'consolidate', 'move'):
            ok(scan(ni, it, loc=a1)['result'] == 'PROHIBITED', 'un colis interdit est refusé pour « %s »' % it)
        ok(scan(ni, 'lookup')['result'] == 'ACCEPTED', 'mais on peut toujours le CONSULTER')
        refuse(cl, "select public.lg_inspect_parcel('%s', '%s', 8, null, null, null, 'GOOD', true, '')" % (ni, w1), 'LG005', 'objet interdit sans motif', role='authenticated', claims=op)
        # sans client
        pn, nn = colis('CREATED', client=False)
        r = scan(nn, 'receive')
        ok(r['result'] == 'ACCEPTED' and r['warnings'] == ['NO_CUSTOMER'] and r['incident_id'], 'SANS CLIENT : reçu avec avertissement et incident « à rattacher »')
        cl.run(B, "select public.lg_inspect_parcel('%s', '%s', 5)" % (nn, w1), role='authenticated', claims=op)
        scan(nn, 'store', loc=a1)
        ok(scan(nn, 'consolidate')['result'] == 'NO_CUSTOMER', '…mais il ne peut pas être consolidé (NO_CUSTOMER)')
        # refus : aucun statut ne bouge, aucun événement de suivi
        ok(q("select status from logistics.parcel where id = '%s'" % pn) == 'STORED', 'un scan refusé ne change JAMAIS le statut')

        # ------------------------------------------------------------------ F. droits
        refuse(cl, "select public.lg_scan_parcel('%s', 'lookup', '%s')" % (num, w1), '42501', 'visiteur anonyme', role='anon')
        for qui, nom in ((cli, 'un client'), (sansdroit, 'un employé sans droit'), (inactif, 'un compte désactivé')):
            refuse(cl, "select public.lg_scan_parcel('%s', 'lookup', '%s')" % (num, w1), 'LG003', nom, role='authenticated', claims=qui)
        refuse(cl, "select public.lg_scan_parcel('%s', 'lookup', '%s')" % (num, w1), 'LG003', 'opérateur d\'une AUTRE succursale', role='authenticated', claims=op2)
        refuse(cl, "select logistics.scan_parcel('%s', 'lookup', '%s', '%s')" % (num, op, w1), '42501', 'le noyau appelé directement', role='authenticated', claims=op)
        refuse(cl, "select public.lg_scan_parcel('%s', 'inventer', '%s')" % (num, w1), 'LG005', 'intention inconnue', role='authenticated', claims=op)
        refuse(cl, "select public.lg_scan_parcel('%s', 'store', '%s')" % (num, w1), 'LG005', 'rangement sans emplacement', role='authenticated', claims=op)
        refuse(cl, "select public.lg_scan_parcel('%s', 'store', '%s', '%s')" % (num, w1, b1), 'LG005', 'emplacement d\'un autre entrepôt', role='authenticated', claims=op)
        refuse(cl, "select public.lg_scan_parcel('%s', 'lookup', '00000000-0000-0000-0000-00000000dead')" % num, 'LG005', 'entrepôt inconnu', role='authenticated', claims=op)
        refuse(cl, "select public.lg_scan_parcel('%s', 'lookup', '%s', null, '%s')" % (num, w1, d_push), 'LG005', 'un téléphone de CLIENT n\'est pas un lecteur', role='authenticated', claims=op)
        refuse(cl, "select public.lg_scan_parcel('%s', 'lookup', '%s', null, null, 'laser')" % (num, w1), 'LG005', 'type de lecteur inconnu', role='authenticated', claims=op)
        ok(q("select count(*) from logistics.scan where actor_user_id in ('%s', '%s', '%s')" % (cli, sansdroit, inactif)) == '0', 'aucun scan n\'est enregistré pour un acteur refusé')
        # le gérant et l'administrateur scannent aussi
        ok(scan(num, 'lookup', acteur=gerant)['result'] == 'ACCEPTED' and scan(num, 'lookup', acteur=admin)['result'] == 'ACCEPTED', 'gérant et administrateur peuvent scanner')

        # ------------------------------------------------------------------ G. idempotence
        pk, nk = colis('CREATED')
        r1, r2 = scan(nk, 'receive', cle='scan-1'), scan(nk, 'receive', cle='scan-1')
        ok(r1['replayed'] is False and r2['replayed'] is True and r1['scan_id'] == r2['scan_id'], 'même clé rejouée (réseau coupé, double appui) : même scan')
        ok(q("select count(*) from logistics.scan where parcel_id = '%s'" % pk) == '1' and q("select count(*) from logistics.tracking_event where parcel_id = '%s'" % pk) == '1', 'UN scan et UN événement de suivi, pas deux')
        refuse(cl, "select public.lg_scan_parcel('%s', 'verify', '%s', null, null, 'barcode', 'scan-1')" % (nk, w1), 'LG006', 'même clé pour une autre demande', role='authenticated', claims=op)
        cl.run(B, "select public.lg_inspect_parcel('%s', '%s', 15, null, null, null, 'GOOD', false, null, '', '[]', null, 'barcode', 'insp-2')" % (nk, w1), role='authenticated', claims=op)
        cl.run(B, "select public.lg_inspect_parcel('%s', '%s', 15, null, null, null, 'GOOD', false, null, '', '[]', null, 'barcode', 'insp-2')" % (nk, w1), role='authenticated', claims=op)
        ok(q("select count(*) from logistics.parcel_inspection where parcel_id = '%s'" % pk) == '1', 'une inspection rejouée ne s\'enregistre qu\'une fois')

        # ------------------------------------------------------------------ H. le résultat ne dépend PAS du lecteur
        formes = [('SES-%d-HT', 'barcode'), ('ses-%d-ht', 'manual'), ('  SES-%d-HT  ', 'manual'), ('https://x.test/suivi.html?colis=SES-%d-HT&j=jeton%d', 'qr')]
        resultats = set()
        for forme, genre in formes:
            pz, nz = colis('CREATED')
            numero = compteur[0]
            code = (forme % (numero, numero)) if forme.count('%d') == 2 else (forme % numero)
            r = scan(code, 'receive', kind=genre, dev=d_cam if genre == 'qr' else d_usb)
            resultats.add((r['result'], r['status']))
        ok(resultats == {('ACCEPTED', 'RECEIVED')}, 'code-barres, QR, saisie manuelle (minuscules, espaces), caméra, USB : MÊME résultat')
        ok(q("select string_agg(distinct code_kind, ',' order by code_kind) from logistics.scan") == 'barcode,manual,qr,unknown', 'le type de lecteur est enregistré (y compris « inconnu » quand l\'application ne le précise pas), il ne change rien')

        # ------------------------------------------------------------------ I. photos, incidents, intégrité
        refuse(cl, "select public.lg_add_parcel_photo('%s', '../../etc/passwd', 'OTHER')" % pid, 'LG005', 'chemin de photo hors dossier', role='authenticated', claims=op)
        refuse(cl, "select public.lg_add_parcel_photo('%s', 'parcels/%s/x.jpg', 'OTHER')" % (pid, pk), 'LG005', 'photo rangée sous un AUTRE colis', role='authenticated', claims=op)
        ok(cl.run(B, "select public.lg_add_parcel_photo('%s', 'parcels/%s/apres.jpg', 'DAMAGE')" % (pid, pid), role='authenticated', claims=op)[0] == 0, 'photo ajoutée après coup, chemin valide')
        refuse(cl, "select public.lg_inspect_parcel('%s', '%s', 0)" % (num, w1), 'LG005', 'poids nul', role='authenticated', claims=op)
        refuse(cl, "select public.lg_inspect_parcel('%s', '%s', 10, 5, 5)" % (num, w1), 'LG005', 'deux dimensions sur trois', role='authenticated', claims=op)
        refuse(cl, "select public.lg_inspect_parcel('%s', '%s', 10, null, null, null, 'CASSE')" % (num, w1), 'LG005', 'état inconnu', role='authenticated', claims=op)
        for table in ('scan', 'parcel_inspection', 'parcel_movement'):
            refuse(cl, "update logistics.%s set id = id" % table if table != 'parcel_movement' else "update logistics.parcel_movement set reason = 'move'", 'LG004', '%s : modification' % table)
            refuse(cl, "delete from logistics.%s" % table, 'LG004', '%s : suppression' % table)
        inc = q("select id from logistics.incident where type = 'UNKNOWN_PARCEL'")
        refuse(cl, "select logistics.resolve_incident('%s', '%s', 'réglé')" % (inc, op), 'LG003', 'un opérateur résout un incident')
        refuse(cl, "select logistics.resolve_incident('%s', '%s', '  ')" % (inc, gerant), 'LG005', 'résolution sans note')
        q("select logistics.resolve_incident('%s', '%s', 'étiquette retrouvée, colis identifié')" % (inc, gerant))
        ok(q("select status from logistics.incident where id = '%s'" % inc) == 'RESOLVED', 'le gérant résout l\'incident, avec sa note')
        refuse(cl, "select logistics.resolve_incident('%s', '%s', 'encore')" % (inc, gerant), 'LG002', 'résoudre deux fois')
        ok(q("select count(*) from pg_tables t join pg_class c on c.relname = t.tablename and c.relnamespace = 'logistics'::regnamespace where t.schemaname = 'logistics' and not c.relrowsecurity") == '0', 'RLS sur toutes les tables du noyau')
        ok(q("select count(*) from information_schema.role_table_grants where table_schema = 'logistics' and grantee in ('anon', 'authenticated', 'PUBLIC')") == '0', 'aucun droit direct sur les tables du noyau')
        ok(q("select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace where n.nspname = 'logistics' and (has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))") == '0',
           'aucune fonction du noyau n\'est exécutable par anon ou authenticated : seule la façade l\'est')

        # ------------------------------------------------------------------ J. rien d'ancien n'a bougé
        ok(q('select count(*) from logistics.reconcile_with_legacy()') == '0', 'la comparaison avec l\'ancien schéma ne signale aucun écart')
        ok(q("select count(*) from logistics.parcel_transition") == '86', 'les 86 transitions de la phase 6 sont intactes')

        print('PASS entrepôt et scanners (phase 7) : %d vérifications — décision sur 5 040 combinaisons, réception → vérification → rangement → mouvement → consolidation, '
              'les 8 cas limites, droits et succursales, idempotence, piste d\'audit complète, indépendance du lecteur (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC entrepôt (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
