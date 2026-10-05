#!/usr/bin/env python3
"""Noyau logistique, phase 5 : le modèle, le rattrapage, les relations — sur un vrai PostgreSQL jetable.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-essai.py

Jamais la production. Le schéma historique réel est chargé avec des données fictives, puis :
  1. la migration 001 (modèle) et 002 (rattrapage) s'appliquent, deux fois, sans erreur ;
  2. les anciennes tables ne bougent pas d'un octet (empreintes avant / après) ;
  3. le rattrapage recopie tout fidèlement, est idempotent, et traite les cas limites ;
  4. la fonction de comparaison voit chaque dérive, et n'en voit plus après un nouveau rattrapage ;
  5. chaque relation du modèle est éprouvée : ce qui doit marcher marche, ce qui doit être refusé l'est ;
  6. le noyau est fermé à l'API (anon, authenticated).
"""
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


def refuse(cl, base, sql, sqlstate, msg, **kw):
    """Une instruction qui DOIT échouer, avec ce code précis."""
    code, texte = cl.run(base, sql, expect_error=True, **kw)
    ok(code != 0 and sqlstate in texte, '%s : attendu %s, obtenu : %s' % (msg, sqlstate, texte[-160:].replace('\n', ' ')))


def main():
    with P.Cluster() as cl:
        B = 'ses'
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        P.monter_historique(cl, B)

        # --- cas limites de l'ancien schéma, comme la production peut en contenir ---------------
        q("insert into public.colis (client_id, description, poids_lb, tarif_lb, pays_destination, service) "
          "values (null, 'colis sans client', 12, 2, 'HT', 'aerien')")
        q("update public.clients set role = 'employe', droits = '{}' where email = 'client5@essai.test'")   # compte d'équipe hérité qui garde ses colis
        staff = q("select id from public.clients where email = 'client3@essai.test'")
        q("update public.colis set statut = 'expedie', lieu = 'Miami — départ' where id = (select id from public.colis where statut = 'confirme' order by numero limit 1)",
          role='authenticated', claims=staff)   # un employé change un statut : l'auteur est enregistré
        n_clients_role_client = int(q("select count(*) from public.clients where role = 'client'"))
        n_staff = int(q("select count(*) from public.clients where role <> 'client'"))
        n_colis = int(q('select count(*) from public.colis'))
        n_hist = int(q('select count(*) from public.colis_historique'))
        n_fact = int(q('select count(*) from public.factures'))
        n_lignes = int(q("select coalesce(sum(jsonb_array_length(lignes)), 0) from public.factures"))
        n_app = int(q('select count(*) from public.appareils'))
        ok(n_colis > 200 and n_fact > 200 and n_app == 6, 'ancien schéma fictif prêt (%s colis, %s factures)' % (n_colis, n_fact))
        avant = P.empreintes_historiques(cl, B)

        # ---------------------------------------------------------------- 1. migrations rejouables
        for fichier in ('outils/logistique/001-modele-de-domaine.sql', 'outils/logistique/002-retroremplissage.sql'):
            sql = P.lire_sql(fichier)
            cl.run(B, sql)
            cl.run(B, sql)    # rejouée : aucune erreur
            ok(True, fichier + ' rejouée sans erreur')
        ok(q("select count(*) from logistics.parcel_status") == '20', '20 statuts de colis (15 du flux + 5 exceptionnels)')
        ok(q("select count(*) from logistics.shipment_status") == '10' and q("select count(*) from logistics.invoice_status") == '7',
           'statuts d\'expédition (10) et de facture (7), listes SÉPARÉES de celle du colis')
        ok(q("select count(*) from logistics.organization") == '1', 'une seule organisation, jamais dupliquée par un rejeu')
        ok(q("select count(*) from logistics.customer") == '0' and q("select count(*) from logistics.parcel") == '0',
           'après 001 et 002 : aucune donnée copiée (le rattrapage est un acte séparé)')
        ok(P.empreintes_historiques(cl, B) == avant, 'ANCIEN SCHÉMA INTACT après les migrations (empreinte de chaque table identique)')

        # ---------------------------------------------------------------- 2. comparaison AVANT rattrapage : tout manque
        manque = int(q("select count(*) from logistics.reconcile_with_legacy()"))
        ok(manque >= n_colis + n_fact + n_hist, 'avant rattrapage, la comparaison voit tout ce qui manque (%d écarts)' % manque)

        # ---------------------------------------------------------------- 3. rattrapage
        rap = json.loads(q('select logistics.backfill_from_legacy()'))
        ok(P.empreintes_historiques(cl, B) == avant, 'ANCIEN SCHÉMA INTACT après le rattrapage')
        n_customer = int(q('select count(*) from logistics.customer'))
        ok(n_customer == n_clients_role_client + 1, 'clients : %d = comptes « client » + le compte d\'équipe hérité qui porte des colis (%d)' % (n_customer, n_clients_role_client + 1))
        ok(int(q("select count(*) from logistics.customer where source = 'legacy_staff_account'")) == 1, 'le compte d\'équipe hérité est marqué comme tel')
        ok(int(q('select count(*) from logistics.app_user')) == n_staff, 'personnel : %d membres' % n_staff)
        ok(q("select string_agg(distinct role, ',' order by role) from logistics.app_user") == 'admin,employee,manager', 'rôles traduits (employe→employee, gerant→manager)')
        ok(int(q('select count(*) from logistics.parcel')) == n_colis, 'colis : %d = %d' % (n_colis, n_colis))
        ok(int(q('select count(*) from logistics.tracking_event')) == n_hist, 'événements : %d = lignes d\'historique' % n_hist)
        ok(int(q('select count(*) from logistics.invoice')) == n_fact, 'factures : %d' % n_fact)
        ok(int(q('select count(*) from logistics.invoice_item')) == n_lignes, 'lignes de facture : %d = éléments des JSON figés' % n_lignes)
        ok(int(q('select count(*) from logistics.device')) == n_app, 'appareils : %d' % n_app)
        ok(rap['parcel']['inserted'] == n_colis and rap['parcel']['updated'] == 0, 'le rapport annonce ce qui a été fait')

        # fidélité champ par champ
        ok(q("select count(*) from public.colis p join logistics.parcel x on x.legacy_parcel_id = p.id "
             "where x.tracking_number = p.numero and x.public_token = p.jeton and x.weight_lb is not distinct from p.poids_lb "
             "and x.rate_per_lb = p.tarif_lb and x.legacy_status = p.statut") == str(n_colis), 'numéro, jeton, poids, tarif et statut d\'origine recopiés à l\'identique')
        ok(q("select string_agg(distinct x.legacy_status || '>' || x.status, ' ' order by x.legacy_status || '>' || x.status) from logistics.parcel x")
           == 'confirme>CREATED disponible>AT_DESTINATION_HUB expedie>IN_TRANSIT livre>DELIVERED', 'les statuts historiques sont traduits, l\'original conservé')
        ok(q("select string_agg(distinct service_mode, ',' order by service_mode) from logistics.parcel") == 'air,ground,sea', 'services traduits (aerien/maritime/terrestre)')
        ok(q("select customer_id is null from logistics.parcel where description = 'colis sans client'") == 't', 'un colis SANS client reste sans client (rien d\'inventé)')
        ok(q("select count(*) from logistics.parcel p join logistics.customer c on c.id = p.customer_id where c.source = 'legacy_staff_account'") != '0',
           'les colis du compte d\'équipe hérité retrouvent leur propriétaire')
        ok(q("select count(*) from logistics.tracking_event where actor_user_id is not null") != '0', 'l\'auteur d\'un changement de statut est relié au membre du personnel')
        ok(q("select count(*) from logistics.tracking_event e join logistics.parcel p on p.id = e.parcel_id "
             "where e.from_status is null and e.legacy_history_id = (select min(h.id) from public.colis_historique h where h.colis_id = p.legacy_parcel_id)") == str(n_colis),
           'le premier événement de chaque colis n\'a pas de statut précédent ; les suivants le portent')
        ok(q("select count(*) from logistics.tracking_event where source <> 'legacy_backfill'") == '0', 'tout événement copié est marqué « legacy_backfill »')
        ok(q("select count(*) from logistics.invoice i join public.factures f on f.id = i.legacy_invoice_id "
             "where i.total = f.montant and i.paid_amount = f.montant_paye and i.number = f.numero") == str(n_fact), 'montants et numéros de facture identiques')
        ok(q("select string_agg(distinct status, ',' order by status) from logistics.invoice") == 'ISSUED,PAID,PARTIALLY_PAID', 'statuts de facture traduits, dont « partiellement payée »')
        ok(q("select count(*) from logistics.invoice where is_grouped") == '1', 'la facture groupée est reconnue')
        ok(int(q('select count(*) from logistics.invoice_item where parcel_id is not null')) > 0, 'les lignes de facture sont liées aux colis')
        ok(q("select to_regclass('logistics.payment') is null") == 't', 'aucun paiement fabriqué : la table payment n\'existe pas encore (phase 10)')
        ok(q("select count(*) from logistics.branch") == '0' and q("select count(*) from logistics.warehouse") == '0', 'aucune succursale ni aucun entrepôt inventés')

        # ---------------------------------------------------------------- 4. idempotence et comparaison
        total_avant = q("select (select count(*) from logistics.customer) + (select count(*) from logistics.parcel) + (select count(*) from logistics.tracking_event) "
                        "+ (select count(*) from logistics.invoice) + (select count(*) from logistics.invoice_item) + (select count(*) from logistics.device)")
        rap2 = json.loads(q('select logistics.backfill_from_legacy()'))
        ok(all(v['inserted'] == 0 and v['updated'] == 0 for v in rap2.values()), 'rattrapage REJOUÉ : 0 inséré, 0 modifié partout (%s)' % json.dumps(rap2))
        ok(q("select (select count(*) from logistics.customer) + (select count(*) from logistics.parcel) + (select count(*) from logistics.tracking_event) "
             "+ (select count(*) from logistics.invoice) + (select count(*) from logistics.invoice_item) + (select count(*) from logistics.device)") == total_avant,
           'aucun doublon après rejeu')
        ok(q('select count(*) from logistics.reconcile_with_legacy()') == '0', 'comparaison : AUCUN écart après rattrapage')

        # dérive : l'ancien schéma continue de vivre (le site écrit)
        q("insert into public.colis (client_id, description, poids_lb, tarif_lb, pays_destination, service) "
          "select id, 'colis arrivé après le rattrapage', 5, 3, 'DO', 'maritime' from public.clients where role = 'client' limit 1")
        gerant = q("select id from public.clients where email = 'client2@essai.test'")
        q("update public.colis set poids_lb = poids_lb + 1 where id = (select id from public.colis where description like 'Colis n°1 %' limit 1)",
          role='authenticated', claims=gerant)   # le gérant corrige un poids : la facture suit
        q("update public.factures set montant_paye = montant where statut = 'impayee' and id = (select id from public.factures where statut = 'impayee' limit 1)")
        q("update public.clients set telephone = '+509 9999 0000' where email = 'client7@essai.test'")
        lignes = cl.run(B, "select string_agg(kind || '/' || entity, ',' order by kind, entity) from logistics.reconcile_with_legacy()")[1]
        for attendu in ('missing_in_core/parcel', 'mismatch/parcel', 'mismatch/invoice', 'mismatch/customer', 'missing_in_core/tracking_event', 'missing_in_core/invoice'):
            ok(attendu in lignes, 'la comparaison voit la dérive « %s »' % attendu)
        rap3 = json.loads(q('select logistics.backfill_from_legacy()'))
        ok(rap3['parcel']['inserted'] >= 1 and rap3['parcel']['updated'] >= 1 and rap3['customer']['updated'] == 1, 'nouveau rattrapage : rattrape exactement les changements (%s)' % json.dumps(rap3['parcel']))
        ok(q('select count(*) from logistics.reconcile_with_legacy()') == '0', 'comparaison : plus aucun écart')

        # le noyau prend la main sur un statut : le rattrapage ne l'écrase plus
        un = q("select id from logistics.parcel where status = 'CREATED' limit 1")
        q("update logistics.parcel set status = 'RECEIVED', status_authority = 'core' where id = '%s'" % un)
        q("update public.colis set note = 'note modifiée côté ancien schéma' where id = (select legacy_parcel_id from logistics.parcel where id = '%s')" % un)
        q('select logistics.backfill_from_legacy()')
        ok(q("select status || '/' || status_authority || '/' || (note = 'note modifiée côté ancien schéma')::text from logistics.parcel where id = '%s'" % un) == 'RECEIVED/core/true',
           'statut « core » préservé, mais les autres champs continuent de suivre l\'ancien schéma')
        ok(q('select count(*) from logistics.reconcile_with_legacy()') == '0', 'la comparaison ne signale pas un statut volontairement pris en main par le noyau')

        # un ancien membre de l'équipe redevient client : désactivé, jamais supprimé
        q("update public.clients set role = 'client' where email = 'client4@essai.test'")
        rap4 = json.loads(q('select logistics.backfill_from_legacy()'))
        ok(q("select active::text from logistics.app_user where id = (select id from public.clients where email = 'client4@essai.test')") == 'false', 'ex-employé : désactivé')
        ok(rap4['app_user']['updated'] >= 1, 'le rapport le dit')

        # ---------------------------------------------------------------- 5. RELATIONS
        ids = cl.run(B, "select string_agg(id::text, ',') from (select id from logistics.parcel where customer_id is not null order by tracking_number limit 4) s")[1].split(',')
        p1, p2, p3, p4 = ids
        ok(int(q("select max(n) from (select count(*) n from logistics.parcel group by customer_id) s")) > 1, 'UN client a PLUSIEURS colis')
        q("insert into logistics.branch (organization_id, code, name, kind, country) select id, 'MIA', 'Miami', 'office', 'US' from logistics.organization")
        q("insert into logistics.branch (organization_id, code, name, kind, country) select id, 'PAP-HUB', 'Hub Port-au-Prince', 'hub', 'HT' from logistics.organization")
        q("insert into logistics.warehouse (branch_id, code, name) select id, 'MIA-1', 'Entrepôt Miami' from logistics.branch where code = 'MIA'")
        q("insert into logistics.consolidation (code, warehouse_id, destination_country, mode) select 'CONS-001', id, 'HT', 'air' from logistics.warehouse where code = 'MIA-1'")
        q("insert into logistics.consolidation (code, destination_country, mode) values ('CONS-002', 'HT', 'sea')")
        for p in (p1, p2, p3):
            q("insert into logistics.consolidation_parcel (consolidation_id, parcel_id) select id, '%s' from logistics.consolidation where code = 'CONS-001'" % p)
        ok(q("select count(*) from logistics.consolidation_parcel cp join logistics.consolidation c on c.id = cp.consolidation_id where c.code = 'CONS-001'") == '3',
           'PLUSIEURS colis dans UNE consolidation')
        refuse(cl, B, "insert into logistics.consolidation_parcel (consolidation_id, parcel_id) select id, '%s' from logistics.consolidation where code = 'CONS-002'" % p1,
               '23505', 'un colis ne peut pas être dans DEUX consolidations actives')
        q("update logistics.consolidation_parcel set removed_at = now() where parcel_id = '%s'" % p1)
        q("insert into logistics.consolidation_parcel (consolidation_id, parcel_id) select id, '%s' from logistics.consolidation where code = 'CONS-002'" % p1)
        ok(q("select count(*) from logistics.consolidation_parcel where parcel_id = '%s'" % p1) == '2', 'après retrait, le colis passe dans une autre consolidation ; l\'historique des deux reste')

        q("insert into logistics.transport (mode, carrier, reference, origin_branch_id, destination_branch_id) "
          "select 'air', 'Compagnie fictive', 'XX123', o.id, d.id from logistics.branch o, logistics.branch d where o.code = 'MIA' and d.code = 'PAP-HUB'")
        q("insert into logistics.shipment (code, mode, origin_branch_id, destination_branch_id, transport_id) "
          "select 'SHP-001', 'air', o.id, d.id, (select id from logistics.transport limit 1) from logistics.branch o, logistics.branch d where o.code = 'MIA' and d.code = 'PAP-HUB'")
        q("insert into logistics.shipment (code, mode, transport_id) select 'SHP-002', 'air', (select id from logistics.transport limit 1)")
        ok(q("select count(distinct id) from logistics.shipment where transport_id = (select id from logistics.transport limit 1)") == '2', 'PLUSIEURS expéditions peuvent partager UN transport')
        q("insert into logistics.shipment_item (shipment_id, consolidation_id) select s.id, c.id from logistics.shipment s, logistics.consolidation c where s.code = 'SHP-001' and c.code = 'CONS-001'")
        q("insert into logistics.shipment_item (shipment_id, parcel_id) select id, '%s' from logistics.shipment where code = 'SHP-001'" % p4)
        ok(q("select count(*) from logistics.shipment_item i join logistics.shipment s on s.id = i.shipment_id where s.code = 'SHP-001'") == '2',
           'une expédition contient une CONSOLIDATION et un colis seul')
        refuse(cl, B, "insert into logistics.shipment_item (shipment_id, consolidation_id) select s.id, c.id from logistics.shipment s, logistics.consolidation c where s.code = 'SHP-001' and c.code = 'CONS-001'",
               '23505', 'la même consolidation ne se met pas deux fois dans une expédition')
        refuse(cl, B, "insert into logistics.shipment_item (shipment_id) select id from logistics.shipment where code = 'SHP-001'", '23514', 'une ligne d\'expédition sans consolidation ni colis')
        refuse(cl, B, "insert into logistics.shipment_item (shipment_id, parcel_id, consolidation_id) select s.id, '%s', c.id from logistics.shipment s, logistics.consolidation c where s.code = 'SHP-002' and c.code = 'CONS-002'" % p2,
               '23514', 'une ligne ne peut pas être à la fois un colis ET une consolidation')
        ok(q("select b.kind from logistics.shipment s join logistics.branch b on b.id = s.destination_branch_id where s.code = 'SHP-001'") == 'hub', 'l\'expédition arrive dans un HUB')
        q("insert into logistics.delivery (destination_branch_id, scheduled_for) select id, current_date + 1 from logistics.branch where code = 'PAP-HUB'")
        for p in (p1, p2, p3):
            q("insert into logistics.delivery_parcel (delivery_id, parcel_id) select id, '%s' from logistics.delivery limit 1" % p)
        ok(q("select count(*) from logistics.delivery_parcel") == '3', 'les colis sont ensuite AFFECTÉS à une livraison')

        # Colis ≠ Expédition : deux vocabulaires de statuts
        refuse(cl, B, "update logistics.shipment set status = 'STORED' where code = 'SHP-001'", '23503', 'un statut de COLIS n\'est pas un statut d\'EXPÉDITION')
        refuse(cl, B, "update logistics.parcel set status = 'DISPATCHED' where id = '%s'" % p1, '23503', 'un statut d\'EXPÉDITION n\'est pas un statut de COLIS')
        refuse(cl, B, "update logistics.shipment set dispatched_at = now(), arrived_at = now() - interval '1 day' where code = 'SHP-001'", '23514', 'arrivée avant le départ')

        # Intégrité : on ne supprime jamais ce qui porte de l'histoire
        refuse(cl, B, "delete from logistics.customer where id = (select customer_id from logistics.parcel where id = '%s')" % p1, '23503', 'supprimer un client qui a des colis')
        refuse(cl, B, "delete from logistics.parcel where id = '%s'" % p1, '23503', 'supprimer un colis qui a un historique')
        refuse(cl, B, "delete from logistics.consolidation where code = 'CONS-001'", '23503', 'supprimer une consolidation qui contient des colis')
        refuse(cl, B, "delete from logistics.invoice where id = (select id from logistics.invoice limit 1)", '23503', 'supprimer une facture qui a des lignes')
        refuse(cl, B, "delete from auth.users where id = (select id from logistics.app_user limit 1)", '23503', 'supprimer le compte Auth d\'un membre du personnel')
        # …mais supprimer un compte Auth d'un client ne détruit ni ses colis ni ses factures du noyau
        # (la CASCADE de l'ANCIEN schéma — compte supprimé => factures supprimées — est documentée dans DATABASE.md §7 ; la rejouer détruirait des données fictives sans rien prouver de neuf)

        # Journal : ajout seul
        refuse(cl, B, "update logistics.tracking_event set location_text = 'trafiqué' where id = (select min(id) from logistics.tracking_event)", 'LG004', 'modifier un événement de suivi')
        refuse(cl, B, "delete from logistics.tracking_event where id = (select min(id) from logistics.tracking_event)", 'LG004', 'supprimer un événement de suivi')
        q("insert into logistics.audit_log (action, entity_type, entity_id, after) values ('essai', 'parcel', '%s', '{\"ok\": true}')" % p1)
        refuse(cl, B, "update logistics.audit_log set action = 'trafiqué'", 'LG004', 'modifier le journal d\'audit')
        refuse(cl, B, "delete from logistics.audit_log", 'LG004', 'supprimer du journal d\'audit')

        # Valeurs
        refuse(cl, B, "update logistics.parcel set service_mode = 'rail' where id = '%s'" % p1, '23514', 'mode de transport inconnu')
        refuse(cl, B, "update logistics.parcel set weight_lb = -1 where id = '%s'" % p1, '23514', 'poids négatif')
        refuse(cl, B, "update logistics.invoice set currency = 'EUR' where id = (select id from logistics.invoice limit 1)", '23514', 'devise inconnue')
        refuse(cl, B, "update logistics.invoice set status = 'PAYEE' where id = (select id from logistics.invoice limit 1)", '23503', 'statut de facture inconnu')
        ok(q("select count(*) from logistics.parcel where updated_at < created_at") == '0', 'updated_at tenu à jour par le déclencheur')

        # ---------------------------------------------------------------- 6. fermé à l'API
        for role in ('anon', 'authenticated'):
            refuse(cl, B, "select count(*) from logistics.parcel", '42501', 'le rôle « %s » lit une table du noyau' % role, role=role)
            refuse(cl, B, "select logistics.backfill_from_legacy()", '42501', 'le rôle « %s » lance le rattrapage' % role, role=role)
            refuse(cl, B, "select * from logistics.reconcile_with_legacy()", '42501', 'le rôle « %s » lance la comparaison' % role, role=role)
        ok(q("select count(*) from pg_tables t join pg_class c on c.relname = t.tablename and c.relnamespace = 'logistics'::regnamespace "
             "where t.schemaname = 'logistics' and not c.relrowsecurity") == '0', 'RLS activée sur TOUTES les tables du noyau')
        ok(q("select count(*) from information_schema.role_table_grants where table_schema = 'logistics' and grantee in ('anon', 'authenticated', 'PUBLIC')") == '0',
           'aucun droit sur les tables du noyau pour anon, authenticated, PUBLIC')
        ok(q("select count(*) from pg_policies where schemaname = 'logistics'") == '0', 'aucune politique : fermé par défaut')

        # l'ancien schéma continue de servir comme avant (le site n'est pas touché)
        ok(q("select count(*) from public.colis_details") != '0' and q("select (public.suivre_colis((select numero from public.colis limit 1)))->>'statut'") != '',
           'l\'ancien schéma fonctionne toujours : vue, suivi public')
        ok(q("select count(*) from pg_trigger t join pg_class c on c.oid = t.tgrelid where c.relnamespace = 'public'::regnamespace and not t.tgisinternal") != '0',
           'les déclencheurs historiques sont toujours en place')

        print('PASS noyau logistique (phase 5) : %d vérifications — migrations rejouables, ancien schéma intact, rattrapage fidèle et idempotent, '
              'comparaison des dérives, relations Client→Colis→Consolidation→Expédition→Transport→Hub→Livraison, intégrité, '
              'journaux en ajout seul, noyau fermé à l\'API (PostgreSQL %s).' % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC noyau logistique (après %d vérifications) : %s' % (N[0], e))
    sys.exit(1)
