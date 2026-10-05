#!/usr/bin/env python3
"""Noyau logistique, phase 6 : machine d'états, suivi, audit et moteur d'événements.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-machine-essai.py

Sur un vrai PostgreSQL jetable (jamais la production). La spécification des transitions est écrite
ICI, indépendamment du SQL, puis comparée à la table, puis exercée sur les 400 paires de statuts."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]


def ok(cond, msg):
    if not cond:
        raise AssertionError(msg)
    N[0] += 1


def refuse(cl, B, sql, sqlstate, msg, **kw):
    code, texte = cl.run(B, sql, expect_error=True, **kw)
    ok(code != 0 and sqlstate in texte, '%s : attendu %s, obtenu : %s' % (msg, sqlstate, texte[-170:].replace('\n', ' ')))


# --- La spécification, indépendante du SQL ----------------------------------------------------------
FLUX = ['CREATED', 'RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'CONSOLIDATED', 'READY_FOR_EXPORT',
        'IN_TRANSIT', 'ARRIVED', 'CUSTOMS_PROCESSING', 'CUSTOMS_CLEARED', 'AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY']
TOUS = FLUX + ['DELIVERED', 'ON_HOLD', 'CANCELLED', 'DAMAGED', 'LOST', 'RETURNED']
TERMINAUX = {'DELIVERED', 'CANCELLED', 'LOST', 'RETURNED'}


def specification():
    s = set()
    s |= {(FLUX[i], FLUX[i + 1]) for i in range(len(FLUX) - 1)} | {('OUT_FOR_DELIVERY', 'DELIVERED')}          # le flux, un pas à la fois
    s |= {('CONSOLIDATED', 'CONSOLIDATION_PENDING'), ('CONSOLIDATION_PENDING', 'STORED')}                         # sortir d'une consolidation
    s |= {(x, 'ON_HOLD') for x in FLUX} | {('DAMAGED', 'ON_HOLD')}                                                # mise en attente
    s |= {('ON_HOLD', x) for x in FLUX}                                                                           # reprise
    s |= {(x, 'DAMAGED') for x in FLUX[1:]} | {('ON_HOLD', 'DAMAGED')}                                           # dommage
    s |= {(x, 'LOST') for x in FLUX[1:]} | {('ON_HOLD', 'LOST'), ('DAMAGED', 'LOST')}                             # perte
    s |= {(x, 'CANCELLED') for x in ['CREATED', 'RECEIVED', 'VERIFIED', 'STORED', 'CONSOLIDATION_PENDING', 'ON_HOLD', 'DAMAGED']}
    s |= {(x, 'RETURNED') for x in ['AT_DESTINATION_HUB', 'DELIVERY_ASSIGNED', 'OUT_FOR_DELIVERY', 'ON_HOLD', 'DAMAGED']}
    return s


EVENEMENT = {'RECEIVED': 'ParcelReceived', 'VERIFIED': 'ParcelVerified', 'STORED': 'ParcelStored',
             'CONSOLIDATION_PENDING': 'ParcelConsolidationPending', 'CONSOLIDATED': 'ParcelConsolidated',
             'READY_FOR_EXPORT': 'ParcelReadyForExport', 'IN_TRANSIT': 'ParcelInTransit', 'ARRIVED': 'ParcelArrived',
             'CUSTOMS_PROCESSING': 'CustomsStarted', 'CUSTOMS_CLEARED': 'CustomsCleared', 'AT_DESTINATION_HUB': 'ParcelAtDestinationHub',
             'DELIVERY_ASSIGNED': 'DeliveryAssigned', 'OUT_FOR_DELIVERY': 'OutForDelivery', 'DELIVERED': 'Delivered',
             'ON_HOLD': 'ParcelOnHold', 'CANCELLED': 'ParcelCancelled', 'DAMAGED': 'ParcelDamaged', 'LOST': 'ParcelLost', 'RETURNED': 'ParcelReturned'}


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        P.monter_historique(cl, B)
        for f in ('001-modele-de-domaine', '002-retroremplissage', '003-machine-d-etats'):
            cl.run(B, P.lire_sql('outils/logistique/%s.sql' % f))
        before = (q('select count(*) from logistics.parcel_transition'), q('select count(*) from logistics.event_type'), q('select count(*) from logistics.event_subscriber'))
        cl.run(B, P.lire_sql('outils/logistique/003-machine-d-etats.sql'))
        ok(before == (q('select count(*) from logistics.parcel_transition'), q('select count(*) from logistics.event_type'), q('select count(*) from logistics.event_subscriber')),
           '003 rejouée : aucune ligne en double')
        q('select logistics.backfill_from_legacy()')

        # --- acteurs et décor -----------------------------------------------------------------
        uid = lambda mail: q("select id from public.clients where email = '%s@essai.test'" % mail)   # noqa: E731
        admin, gerant, op, op2 = uid('client1'), uid('client2'), uid('client3'), uid('client4')
        sans_droit, inactif, cli = uid('client6'), uid('client7'), uid('client8')
        q("insert into logistics.app_user (id, organization_id, role, rights) select '%s', id, 'employee', '{}' from logistics.organization" % sans_droit)
        q("insert into logistics.app_user (id, organization_id, role, rights, active) select '%s', id, 'employee', array['colis.statut'], false from logistics.organization" % inactif)
        q("insert into logistics.branch (organization_id, code, name, kind, country) select id, 'MIA', 'Miami', 'office', 'US' from logistics.organization")
        q("insert into logistics.warehouse (branch_id, code, name) select id, 'MIA-1', 'Entrepôt Miami' from logistics.branch where code = 'MIA'")
        q("insert into logistics.warehouse (branch_id, code, name) select id, 'MIA-2', 'Entrepôt Miami 2' from logistics.branch where code = 'MIA'")
        q("insert into logistics.warehouse_location (warehouse_id, code, zone) select id, 'A-01', 'A' from logistics.warehouse where code = 'MIA-1'")
        q("insert into logistics.warehouse_location (warehouse_id, code, zone) select id, 'B-01', 'B' from logistics.warehouse where code = 'MIA-2'")
        wh1 = q("select id from logistics.warehouse where code = 'MIA-1'")
        wh2 = q("select id from logistics.warehouse where code = 'MIA-2'")
        loc1 = q("select id from logistics.warehouse_location where code = 'A-01'")
        loc2 = q("select id from logistics.warehouse_location where code = 'B-01'")
        customer = q("select id from logistics.customer where legacy_client_id = '%s'" % cli)
        org = q('select id from logistics.organization')
        n_parcel = [0]

        def nouveau(statut='CREATED', client=True, autorite='core', source='legacy_backfill', cust=None):
            n_parcel[0] += 1
            return q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source) "
                     "values ('%s', 'T-%d', 'tok', %s, 'HT', 'air', '%s', '%s', '%s') returning id" % (
                         org, n_parcel[0], "'%s'" % (cust or customer) if client else 'null', statut, autorite, source))

        def trans(pid, vers, acteur=admin, cle=None, corr=None, wh=None, loc=None, motif=None, source='api', texte=''):
            args = ["'%s'" % pid, "'%s'" % vers, "'%s'" % acteur if acteur else 'null', "'%s'" % cle if cle else 'null',
                    "'%s'::uuid" % corr if corr else 'null', "'%s'" % wh if wh else 'null', "'%s'" % loc if loc else 'null',
                    "'%s'" % texte, 'null', "'%s'" % motif if motif else 'null', "'{}'::jsonb", "'%s'" % source]
            return 'select logistics.transition_parcel(%s)' % ', '.join(args)

        # ---------------------------------------------------------------- A. spécification = table
        attendu = specification()
        reel = {tuple(l.split('|')) for l in cl.lignes(B, 'select from_status, to_status from logistics.parcel_transition')}
        ok(attendu == reel, 'la table des transitions = la spécification (%d paires ; écart : %s)' % (len(attendu), sorted(attendu ^ reel)[:4]))
        ok(not any(f in TERMINAUX for f, _ in reel), 'AUCUNE transition ne sort d\'un état terminal (DELIVERED, CANCELLED, LOST, RETURNED)')
        ok(all(f == 'ON_HOLD' for f, t in reel if t == 'CREATED'), 'on ne revient à CREATED que par une REPRISE après mise en attente')
        pairs_evt = {tuple(l.split('|')) for l in cl.lignes(B, 'select to_status, event_type from logistics.parcel_transition where event_type <> \'ParcelResumed\'')}
        ok(all(EVENEMENT[t] == e or e in ('ParcelConsolidationPending', 'ParcelStored') for t, e in pairs_evt), 'chaque transition émet l\'événement prévu pour son statut d\'arrivée')
        ok(q("select count(*) from logistics.event_type where code in ('ParcelReceived','ParcelVerified','ParcelStored','ParcelConsolidated','ShipmentCreated','ShipmentDispatched',"
             "'ShipmentArrived','CustomsStarted','CustomsCleared','DeliveryAssigned','OutForDelivery','Delivered','ProofOfDeliveryCreated','IncidentCreated')") == '14',
           'les 14 événements minimum demandés existent dans le catalogue')

        # ---------------------------------------------------------------- B. la matrice des 400 paires
        e0 = {t: int(q('select count(*) from logistics.%s' % t)) for t in ('tracking_event', 'audit_log', 'domain_event')}
        script = """
create temp table matrice (f text, t text, code text);
do $$
declare s record; pid uuid; begin
  for s in select a.code as f, b.code as t from logistics.parcel_status a cross join logistics.parcel_status b loop
    insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source)
    values ('%(org)s', 'M-' || s.f || '-' || s.t, 'tok', '%(cust)s', 'HT', 'air', s.f, 'core', 'legacy_backfill') returning id into pid;
    begin
      perform logistics.transition_parcel(pid, s.t, '%(adm)s', null, null, '%(wh)s', '%(loc)s', '', null, 'essai', '{}', 'api');
      insert into matrice values (s.f, s.t, 'OK');
    exception when others then insert into matrice values (s.f, s.t, sqlstate); end;
  end loop;
end $$;
select f || '|' || t || '|' || code from matrice;""" % dict(org=org, cust=customer, adm=admin, wh=wh1, loc=loc1)
        res = [tuple(l.split('|')) for l in cl.lignes(B, script)]
        ok(len(res) == 400, 'la matrice exerce les 400 paires de statuts')
        autorisees_ok = {(f, t) for f, t, c in res if c == 'OK'}
        refusees = {(f, t): c for f, t, c in res if c != 'OK'}
        ok(autorisees_ok == attendu, 'TOUTES les transitions autorisées passent, AUCUNE autre (%d acceptées)' % len(autorisees_ok))
        ok(set(refusees.values()) == {'LG001'}, 'toutes les autres sont refusées avec le code LG001 « transition non autorisée » (%d refusées)' % len(refusees))
        n_ok = len(autorisees_ok)
        e1 = {t: int(q('select count(*) from logistics.%s' % t)) for t in ('tracking_event', 'audit_log', 'domain_event')}
        ok(e1['tracking_event'] - e0['tracking_event'] == n_ok and e1['audit_log'] - e0['audit_log'] == n_ok and e1['domain_event'] - e0['domain_event'] == n_ok,
           'CHAQUE transition réussie = 1 événement de suivi + 1 trace d\'audit + 1 événement de domaine (%d de chaque), les refusées 0' % n_ok)

        # ---------------------------------------------------------------- C. conditions de chaque transition
        p = nouveau('CREATED')
        refuse(cl, B, trans(nouveau('CREATED'), 'RECEIVED'), 'LG005', 'réception sans entrepôt')
        refuse(cl, B, trans(nouveau('VERIFIED'), 'STORED', wh=wh1), 'LG005', 'rangement sans emplacement')
        refuse(cl, B, trans(nouveau('CREATED'), 'ON_HOLD'), 'LG005', 'mise en attente sans motif')
        refuse(cl, B, trans(nouveau('CREATED'), 'ON_HOLD', motif='   '), 'LG005', 'mise en attente avec motif vide')
        refuse(cl, B, trans(nouveau('STORED', client=False), 'CONSOLIDATION_PENDING'), 'LG005', 'colis SANS CLIENT : ne dépasse pas le rangement')
        r = json.loads(q(trans(nouveau('CREATED', client=False), 'RECEIVED', wh=wh1)))
        ok(r['to_status'] == 'RECEIVED', 'un colis sans client peut être RECU (cas d\'entrepôt) mais pas aller plus loin')
        refuse(cl, B, trans(nouveau('VERIFIED'), 'STORED', wh=wh1, loc=loc2), 'LG005', 'emplacement d\'un AUTRE entrepôt')
        refuse(cl, B, trans(nouveau('VERIFIED'), 'STORED', loc='00000000-0000-0000-0000-00000000dead'), 'LG005', 'emplacement inconnu')
        refuse(cl, B, trans('00000000-0000-0000-0000-00000000dead', 'RECEIVED', wh=wh1), 'LG002', 'colis introuvable')
        refuse(cl, B, trans(nouveau('CREATED'), 'DELIVERED'), 'LG001', 'sauter du début à la fin')
        refuse(cl, B, trans(nouveau('DELIVERED'), 'CREATED'), 'LG001', 'ressusciter un colis livré')
        refuse(cl, B, trans(nouveau('CREATED'), 'EN_VOL'), 'LG001', 'statut inexistant')
        # la reprise ramène là où le colis était
        ph = nouveau('VERIFIED')
        q(trans(ph, 'ON_HOLD', motif='contrôle'))
        refuse(cl, B, trans(ph, 'STORED'), 'LG001', 'reprise ailleurs que là où le colis était (VERIFIED)')
        refuse(cl, B, trans(ph, 'RECEIVED'), 'LG001', 'reprise en arrière')
        ok(json.loads(q(trans(ph, 'VERIFIED')))['to_status'] == 'VERIFIED', 'reprise vers le statut d\'avant : acceptée')
        ok(q("select count(*) from logistics.tracking_event where parcel_id = '%s'" % ph) == '2', 'attente et reprise sont dans le journal (2 événements)')

        # ---------------------------------------------------------------- D. qui a le droit
        pp = nouveau('CREATED')
        refuse(cl, B, trans(pp, 'RECEIVED', acteur=customer, wh=wh1), 'LG003', 'un CLIENT (pas du personnel) change un statut')
        refuse(cl, B, trans(pp, 'RECEIVED', acteur=inactif, wh=wh1), 'LG003', 'un compte désactivé')
        refuse(cl, B, trans(pp, 'RECEIVED', acteur=sans_droit, wh=wh1), 'LG003', 'un employé SANS le droit colis.statut')
        refuse(cl, B, trans(pp, 'RECEIVED', acteur=None, wh=wh1), 'LG003', 'sans acteur, par l\'API')
        refuse(cl, B, trans(pp, 'RECEIVED', acteur=None, wh=wh1, source='system'), 'LG003', 'le système seul ne reçoit pas un colis (transition réservée à une personne)')
        ok(json.loads(q(trans(pp, 'RECEIVED', acteur=op, wh=wh1)))['to_status'] == 'RECEIVED', 'un employé AVEC colis.statut : accepté')
        refuse(cl, B, trans(pp, 'CANCELLED', acteur=op, motif='x'), 'LG003', 'un employé n\'annule pas (réservé à la direction)')
        refuse(cl, B, trans(nouveau('OUT_FOR_DELIVERY'), 'LOST', acteur=op, motif='x'), 'LG003', 'un employé ne déclare pas une perte')
        ok(json.loads(q(trans(pp, 'DAMAGED', acteur=op, motif='carton éventré')))['to_status'] == 'DAMAGED', 'mais tout opérateur peut SIGNALER un dommage')
        ok(json.loads(q(trans(pp, 'CANCELLED', acteur=gerant, motif='demande du client')))['to_status'] == 'CANCELLED', 'le gérant annule')
        ok(json.loads(q(trans(nouveau('OUT_FOR_DELIVERY'), 'LOST', acteur=admin, motif='introuvable')))['to_status'] == 'LOST', 'l\'administrateur déclare la perte')
        ok(json.loads(q(trans(nouveau('CONSOLIDATION_PENDING'), 'CONSOLIDATED', acteur=None, source='system')))['to_status'] == 'CONSOLIDATED',
           'le SYSTÈME interne peut faire avancer une consolidation (événement d\'expédition)')
        ok(q("select actor_label from logistics.tracking_event order by id desc limit 1") == 'system', 'le système est nommé « system » dans le journal')

        # ---------------------------------------------------------------- E. impossible de contourner la machine
        pb = nouveau('CREATED')
        refuse(cl, B, "update logistics.parcel set status = 'DELIVERED' where id = '%s'" % pb, 'LG001', 'UPDATE direct du statut d\'un colis « core »')
        refuse(cl, B, "update logistics.parcel set status_authority = 'legacy' where id = '%s'" % pb, 'LG001', 'rendre l\'autorité à l\'ancien schéma')
        pl = nouveau('CREATED', autorite='legacy')
        refuse(cl, B, "update logistics.parcel set status_authority = 'core' where id = '%s'" % pl, 'LG001', 'prendre l\'autorité sans transition')
        q("update logistics.parcel set status = 'IN_TRANSIT' where id = '%s'" % pl)
        ok(q("select status from logistics.parcel where id = '%s'" % pl) == 'IN_TRANSIT', 'sous l\'autorité de l\'ancien schéma, le rattrapage garde la main (compatibilité)')
        refuse(cl, B, "insert into logistics.parcel (organization_id, tracking_number, public_token, destination_country, service_mode, status, source) "
                      "values ('%s', 'N-1', 't', 'HT', 'air', 'RECEIVED', 'native')" % org, 'LG001', 'un colis NATIF qui naît ailleurs qu\'en CREATED')
        q("insert into logistics.parcel (organization_id, tracking_number, public_token, destination_country, service_mode, status, source) "
          "values ('%s', 'N-2', 't', 'HT', 'air', 'CREATED', 'native')" % org)
        ok(q("select status from logistics.parcel where tracking_number = 'N-2'") == 'CREATED', 'un colis natif naît en CREATED')
        r = json.loads(q(trans(pl, 'ARRIVED')))
        ok(q("select status_authority from logistics.parcel where id = '%s'" % pl) == 'core', 'la première transition passe l\'autorité au noyau')
        q('select logistics.backfill_from_legacy()')
        ok(q("select status from logistics.parcel where id = '%s'" % pl) == 'ARRIVED', 'et le rattrapage ne l\'écrase plus')

        # ---------------------------------------------------------------- F. idempotence
        pi = nouveau('CREATED')
        n0 = int(q("select count(*) from logistics.tracking_event where parcel_id = '%s'" % pi))
        r1 = json.loads(q(trans(pi, 'RECEIVED', wh=wh1, cle='cmd-1')))
        r2 = json.loads(q(trans(pi, 'RECEIVED', wh=wh1, cle='cmd-1')))
        ok(r1['replayed'] is False and r2['replayed'] is True and r1['event_id'] == r2['event_id'], 'même clé rejouée : même résultat, marqué « replayed »')
        ok(int(q("select count(*) from logistics.tracking_event where parcel_id = '%s'" % pi)) == n0 + 1, 'UN seul événement de suivi malgré deux appels')
        ok(q("select count(*) from logistics.domain_event where idempotency_key = 'cmd-1'") == '1' and q("select count(*) from logistics.audit_log where entity_id = '%s' and action = 'parcel.transition'" % pi) == '1',
           'un seul événement de domaine et une seule trace d\'audit')
        refuse(cl, B, trans(pi, 'VERIFIED', wh=wh1, cle='cmd-1'), 'LG006', 'même clé pour une AUTRE demande')
        pf = nouveau('CREATED')
        refuse(cl, B, trans(pf, 'RECEIVED', cle='cmd-2'), 'LG005', 'commande en échec (pas d\'entrepôt)')
        ok(q("select count(*) from logistics.command_log where idempotency_key = 'cmd-2'") == '0', 'une commande en échec ne « consomme » pas sa clé')
        ok(json.loads(q(trans(pf, 'RECEIVED', wh=wh1, cle='cmd-2')))['to_status'] == 'RECEIVED', 'elle peut être réessayée avec la même clé une fois corrigée')

        # ---------------------------------------------------------------- G. corrélation et audit
        pc = nouveau('CREATED')
        corr = 'c0ffee00-0000-4000-8000-000000000001'
        json.loads(q(trans(pc, 'RECEIVED', wh=wh1, corr=corr, texte='Quai 3')))
        ok(q("select count(*) from (select correlation_id from logistics.tracking_event where parcel_id = '%s' union all select correlation_id from logistics.audit_log where entity_id = '%s' "
             "union all select correlation_id from logistics.domain_event where aggregate_id = '%s') s where correlation_id = '%s'" % (pc, pc, pc, corr)) == '3',
           'le MÊME correlation_id suit le suivi, l\'audit et l\'événement')
        ok(q("select count(*) from logistics.domain_event where aggregate_id = '%s' and correlation_id is null" % pc) == '0', 'jamais d\'événement sans correlation_id (généré si absent)')
        ok(q("select actor_label, location_text, warehouse_id = '%s' from logistics.tracking_event where parcel_id = '%s'" % (wh1, pc)).startswith('client1@essai.test|Quai 3|t'),
           'acteur, date, emplacement et entrepôt sont enregistrés')
        ok(q("select (after ->> 'location') || '/' || (before ->> 'status') || '>' || (after ->> 'status') from logistics.audit_log where entity_id = '%s'" % pc) == 'Quai 3/CREATED>RECEIVED',
           'l\'audit garde l\'avant et l\'après')
        ok(q("select current_location from logistics.parcel where id = '%s'" % pc) == 'Quai 3', 'la position courante du colis est tenue à jour')
        # atomicité : si la dernière étape échoue, RIEN n'est conservé
        pa = nouveau('CREATED')
        q("create or replace function public.essai_casse() returns trigger language plpgsql as $$ begin raise exception 'panne simulée' using errcode = 'XX999'; end $$; "
          "create trigger essai_casse before insert on logistics.domain_event for each row execute function public.essai_casse()")
        refuse(cl, B, trans(pa, 'RECEIVED', wh=wh1), 'XX999', 'panne au moment d\'écrire l\'événement de domaine')
        q('drop trigger essai_casse on logistics.domain_event')
        ok(q("select status || '/' || (select count(*) from logistics.tracking_event where parcel_id = '%s') || '/' || (select count(*) from logistics.audit_log where entity_id = '%s') from logistics.parcel where id = '%s'" % (pa, pa, pa)) == 'CREATED/0/0',
           'ATOMIQUE : après la panne, statut inchangé, aucun suivi, aucune trace')

        # ---------------------------------------------------------------- H. le moteur d'événements
        refuse(cl, B, "update logistics.domain_event set version = 2 where id = (select min(id) from logistics.domain_event)", 'LG004', 'modifier un événement de domaine')
        refuse(cl, B, "delete from logistics.domain_event where id = (select min(id) from logistics.domain_event)", 'LG004', 'supprimer un événement de domaine')
        refuse(cl, B, "insert into logistics.domain_event (event_type, aggregate_type, aggregate_id, correlation_id) values ('Inconnu', 'parcel', 'x', gen_random_uuid())", '23503', 'un type d\'événement inconnu')
        # fan-out + abonné interne réel (notifications)
        q("update logistics.event_delivery set status = 'DELIVERED' where status in ('PENDING','FAILED')")     # on repart d'une file vide
        ccli = q("select owner_customer_id from logistics.device where owner_customer_id is not null limit 1")
        pn = q("insert into logistics.parcel (organization_id, tracking_number, public_token, customer_id, destination_country, service_mode, status, status_authority, source) "
               "values ('%s', 'NOTIF-1', 't', '%s', 'HT', 'air', 'CREATED', 'core', 'legacy_backfill') returning id" % (org, ccli))
        q(trans(pn, 'RECEIVED', wh=wh1))
        ok(q("select count(*) from logistics.event_delivery where subscriber_code = 'notification_planner' and status = 'PENDING'") == '1', 'fan-out : l\'événement ParcelReceived a sa livraison')
        q(trans(pn, 'VERIFIED', wh=wh1))
        ok(q("select count(*) from logistics.event_delivery where status = 'PENDING'") == '1', 'ParcelVerified n\'intéresse aucun abonné : pas de livraison')
        refuse(cl, B, "select logistics.dispatch_events()", '42501', 'dispatch_events lancé par authenticated', role='authenticated')
        res = json.loads(q('select logistics.dispatch_events()'))
        ok(res == {'delivered': 1, 'failed': 0, 'dead': 0}, 'dispatch : 1 livré (%s)' % res)
        ok(q("select count(*) from logistics.notification where parcel_id = '%s' and template = 'ParcelReceived' and status = 'PENDING'" % pn) == '1', 'l\'abonné a planifié la notification du client qui a l\'application')
        ok(json.loads(q('select logistics.dispatch_events()'))['delivered'] == 0, 'rejouer le répartiteur ne redistribue rien (pas de double livraison)')
        sans_app = q("select id from logistics.customer c where not exists (select 1 from logistics.device d where d.owner_customer_id = c.id) limit 1")
        pnn = nouveau('CREATED', cust=sans_app)
        q(trans(pnn, 'RECEIVED', wh=wh1)); q('select logistics.dispatch_events()')
        ok(q("select count(*) from logistics.notification where parcel_id = '%s'" % pnn) == '0', 'un client sans application ne reçoit rien (et rien ne casse)')

        # relances avec attente croissante, puis file des échecs ; l'opération métier n'est JAMAIS touchée
        q("create or replace function public.essai_echoue(ev logistics.domain_event) returns void language plpgsql as $$ begin raise exception 'service de messagerie en panne'; end $$")
        q("insert into logistics.event_subscriber (code, kind, event_types, handler, max_attempts, backoff_seconds) values ('fragile', 'internal', array['ParcelStored'], 'public.essai_echoue'::regproc, 3, 10)")
        pr = nouveau('VERIFIED')
        q(trans(pr, 'STORED', wh=wh1, loc=loc1))
        ok(q("select status from logistics.parcel where id = '%s'" % pr) == 'STORED', 'le colis est rangé, que l\'abonné soit en panne ou non')
        res = json.loads(q('select logistics.dispatch_events()'))
        ok(res['failed'] == 1, 'essai 1 : échec enregistré')
        d = q("select status || '/' || attempts || '/' || (next_attempt_at > now() + interval '8 seconds')::text || '/' || last_error from logistics.event_delivery where subscriber_code = 'fragile'")
        ok(d == 'FAILED/1/true/service de messagerie en panne', 'FAILED, 1 essai, prochaine tentative dans ~10 s, erreur gardée (%s)' % d)
        ok(json.loads(q('select logistics.dispatch_events()')) == {'delivered': 0, 'failed': 0, 'dead': 0}, 'pas de nouvel essai AVANT l\'heure prévue')
        q("update logistics.event_delivery set next_attempt_at = now() - interval '1 second' where subscriber_code = 'fragile'")
        q('select logistics.dispatch_events()')
        ok(q("select attempts || '/' || (next_attempt_at > now() + interval '15 seconds')::text from logistics.event_delivery where subscriber_code = 'fragile'") == '2/true', 'essai 2 : l\'attente DOUBLE (~20 s)')
        q("update logistics.event_delivery set next_attempt_at = now() - interval '1 second' where subscriber_code = 'fragile'")
        res = json.loads(q('select logistics.dispatch_events()'))
        ok(res['dead'] == 1 and q("select status from logistics.event_delivery where subscriber_code = 'fragile'") == 'DEAD', 'essai 3 = le maximum : l\'événement passe en file des échecs')
        ok(q("select count(*) from logistics.dead_letter where subscriber_code = 'fragile' and resolved_at is null") == '1', 'une entrée dans la file des échecs, non résolue')
        ok(q("select count(*) from logistics.event_delivery where subscriber_code = 'notification_planner' and status = 'DELIVERED'") != '0', 'les AUTRES abonnés n\'ont pas été gênés par l\'abonné défaillant')
        ok(q("select count(*) from logistics.event_health where subscriber_code = 'fragile' and dead = 1") == '1', 'la vue de surveillance montre l\'événement mort')
        q("create or replace function public.essai_echoue(ev logistics.domain_event) returns void language plpgsql as $$ begin null; end $$")   # la panne est réparée
        dl = q("select id from logistics.dead_letter where subscriber_code = 'fragile'")
        q("select logistics.requeue_dead_letter(%s, 'service rétabli')" % dl)
        ok(q("select status || '/' || attempts from logistics.event_delivery where subscriber_code = 'fragile'") == 'PENDING/0', 'remise en circulation : PENDING, compteur remis à zéro')
        ok(q("select count(*) from logistics.dead_letter where id = %s and resolved_at is not null and resolution_note = 'service rétabli'" % dl) == '1', 'l\'entrée est marquée résolue, avec sa note (jamais supprimée)')
        ok(json.loads(q('select logistics.dispatch_events()'))['delivered'] == 1, 'après réparation, l\'événement est enfin livré')
        refuse(cl, B, "select logistics.requeue_dead_letter(%s, 'encore')" % dl, 'LG002', 'résoudre deux fois la même entrée')

        # abonné externe : réclamer, bail, confirmer, refuser
        q("insert into logistics.event_subscriber (code, kind, event_types, max_attempts, backoff_seconds) values ('push_sender', 'external', array['ParcelInTransit'], 2, 5)")
        px = nouveau('READY_FOR_EXPORT')
        q(trans(px, 'IN_TRANSIT', acteur=None, source='system'))
        refuse(cl, B, "select * from logistics.claim_deliveries('push_sender')", '42501', 'claim_deliveries par authenticated', role='authenticated')
        refuse(cl, B, "select * from logistics.claim_deliveries('inconnu')", 'LG002', 'abonné externe inconnu')
        env = json.loads(q("select envelope from logistics.claim_deliveries('push_sender')"))
        ok(env['type'] == 'ParcelInTransit' and env['aggregate'] == {'type': 'parcel', 'id': px} and env['payload']['to_status'] == 'IN_TRANSIT'
           and env['correlation_id'] and env['actor']['label'] == 'system' and env['version'] == 1,
           'l\'enveloppe porte type, version, agrégat, corrélation, acteur et contenu')
        ok(q("select count(*) from logistics.claim_deliveries('push_sender')") == '0', 'un événement réclamé n\'est pas donné à un second travailleur (bail)')
        q("update logistics.event_delivery set locked_until = now() - interval '1 second' where subscriber_code = 'push_sender'")
        did = q("select delivery_id || '/' || attempt from logistics.claim_deliveries('push_sender')")
        ok(did.endswith('/2'), 'travailleur tombé : le bail expire, l\'événement revient (essai 2)')
        delivery = did.split('/')[0]
        ok(q("select logistics.nack_delivery(%s, 'API Expo indisponible')" % delivery) == 'DEAD', 'refus au dernier essai (max 2) : file des échecs')
        pk = nouveau('READY_FOR_EXPORT'); q(trans(pk, 'IN_TRANSIT', acteur=None, source='system'))
        d2 = q("select delivery_id from logistics.claim_deliveries('push_sender')")
        q("select logistics.ack_delivery(%s)" % d2)
        ok(q("select status from logistics.event_delivery where id = %s" % d2) == 'DELIVERED', 'confirmation : DELIVERED')
        refuse(cl, B, "select logistics.ack_delivery(%s)" % d2, 'LG004', 'confirmer deux fois')

        # ---------------------------------------------------------------- I. la façade publique
        pg_ = nouveau('CREATED')
        refuse(cl, B, "select public.lg_transition_parcel('%s', 'RECEIVED', null, null, '%s')" % (pg_, wh1), '42501', 'un visiteur anonyme', role='anon')
        refuse(cl, B, "select logistics.transition_parcel('%s', 'RECEIVED')" % pg_, '42501', 'le noyau appelé directement par authenticated', role='authenticated', claims=op)
        refuse(cl, B, "select public.lg_transition_parcel('%s', 'RECEIVED', null, null, '%s')" % (pg_, wh1), 'LG003', 'un client connecté', role='authenticated', claims=cli)
        refuse(cl, B, "select public.lg_transition_parcel('%s', 'RECEIVED', null, null, '%s')" % (pg_, wh1), 'LG003', 'un employé sans le droit', role='authenticated', claims=sans_droit)
        out = json.loads(cl.run(B, "select public.lg_transition_parcel('%s', 'RECEIVED', 'fa-1', null, '%s')" % (pg_, wh1), role='authenticated', claims=op)[1])
        ok(out['to_status'] == 'RECEIVED', 'un employé autorisé, par la façade')
        ok(q("select actor_user_id::text from logistics.tracking_event where parcel_id = '%s'" % pg_) == op, 'l\'acteur enregistré est le COMPTE CONNECTÉ (il ne se passe pas en paramètre)')
        ok(q("select pg_get_function_arguments('public.lg_transition_parcel(uuid,text,text,uuid,uuid,uuid,text,text,jsonb)'::regprocedure) !~ 'actor'") == 't', 'la façade n\'a aucun paramètre « acteur »')

        # ---------------------------------------------------------------- J. rejeu et rattrapage après tout cela
        ok(q('select count(*) from logistics.reconcile_with_legacy()') == '0', 'après toutes les transitions, la comparaison avec l\'ancien schéma ne signale aucun écart')

        print('PASS machine d\'états et événements (phase 6) : %d vérifications — 86 transitions autorisées et 314 refusées sur 400 paires, '
              'droits, conditions, idempotence, corrélation, atomicité, relances, file des échecs, abonnés externes, façade (PostgreSQL %s).'
              % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC machine d\'états (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
