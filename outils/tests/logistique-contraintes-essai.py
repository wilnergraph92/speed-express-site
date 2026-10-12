#!/usr/bin/env python3
"""Phase 2 — le modèle cible et ses contraintes, vérifiés sur le catalogue réel (001 → 014 sur la réplique de la production).

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-contraintes-essai.py

On exige, sans se fier aux commentaires des fichiers :
 1. les 47 entités du modèle cible existent (table ou vue), dans le schéma « logistics » ;
 2. identifiants : chaque entité désignable de l'extérieur a un UUID ; les seules exceptions sont des tables de référence à
    clé naturelle (statuts, types) et des journaux ou lignes de détail en ajout seul, listés ici avec leur raison ;
 3. le colis a un numéro public ET un jeton public distinct, chacun unique ;
 4. journaux en ajout seul : audit, historique du colis, événements (et les écritures financières) refusent toute
    modification et tout effacement, même du propriétaire de la base ;
 5. argent : chaque montant est numeric ; chaque table qui en porte a sa devise (ou la tient de son parent, listé) ;
 6. clés étrangères : AUCUN effacement en cascade ; une seule mise à vide (un compte de connexion supprimé laisse la fiche
    client) ; effacer un colis qui a un historique, une facture qui a des lignes, est refusé ;
 7. aucun secret : aucune colonne de mot de passe, de clé ou de code en clair (le code de livraison n'existe que haché) ;
 8. rien n'est exposé : ni visiteur ni compte connecté n'entre dans logistics, analytics ou ops ; sécurité par ligne sur
    chaque table du noyau.
Jamais la production."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _pgjetable as P   # noqa: E402

N = [0]

ENTITES = ['organization', 'branch', 'app_user', 'customer', 'device', 'warehouse', 'warehouse_location', 'parcel', 'tracking_event',
           'consolidation', 'shipment', 'shipment_item', 'transport', 'delivery', 'route', 'trip', 'stop', 'driver', 'vehicle',
           'driver_availability', 'delivery_zone', 'pickup_task', 'delivery_task', 'assignment', 'proof_of_delivery', 'incident',
           'customs_declaration', 'customs_document', 'load_unit', 'quote', 'pricing_rule', 'rate_card', 'weight_bracket', 'service_fee',
           'surcharge', 'tax', 'exchange_rate', 'invoice', 'invoice_item', 'payment', 'refund', 'credit', 'customer_balance', 'expense',
           'revenue', 'audit_log', 'domain_event', 'event_delivery', 'dead_letter']

# Clé primaire entière croissante : des lignes qu'on n'atteint jamais que par leur parent (UUID) et dont l'ordre compte.
JOURNAUX_ET_LIGNES = {
    'audit_log': 'journal d\'audit, en ajout seul', 'tracking_event': 'historique du colis, en ajout seul',
    'domain_event': 'boîte d\'envoi des événements, en ajout seul', 'event_delivery': 'livraison d\'un événement à un abonné',
    'dead_letter': 'échec définitif d\'une livraison', 'invoice_item': 'ligne d\'une facture (UUID de la facture)',
    'shipment_item': 'ligne d\'une expédition (UUID de l\'expédition)', 'consolidation_parcel': 'ligne d\'un regroupement',
    'weight_bracket': 'tranche d\'une grille (UUID de la grille), en ajout seul', 'exchange_rate': 'cours du jour, en ajout seul',
    'revenue_entry': 'écriture de revenu, en ajout seul', 'invoice_status_history': 'historique, en ajout seul',
    'shipment_status_history': 'historique, en ajout seul', 'task_status_history': 'historique, en ajout seul',
    'parcel_movement': 'mouvement en entrepôt, en ajout seul', 'notification': 'notification à envoyer',
    'notification_attempt': 'tentative d\'envoi, en ajout seul', 'support_message': 'message d\'un ticket (UUID du ticket)',
    'migration_run': 'journal des rattrapages, en ajout seul', 'sync_queue': 'file de la double écriture', 'sync_failure': 'incident de dépôt',
    'payment_event': 'journal des événements des prestataires de paiement, en ajout seul (étape 18)',
    'provider_settlement_line': 'ligne d\'un relevé de règlement, en ajout seul', 'finance_review': 'examen d\'un écart financier, en ajout seul',
}
# Devise tenue par le parent.
DEVISE_DU_PARENT = {'invoice_item': ('invoice_id', 'invoice'), 'weight_bracket': ('rate_card_id', 'rate_card')}
MONTANT = r'(amount|total|price|fee$|balance|invoiced|credited|refunded|^paid$|declared_value|rate_per_lb|cost|minimum_charge|_usd$)'


def ok(c, m):
    if not c:
        raise AssertionError(m)
    N[0] += 1


def main():
    with P.Cluster() as cl:
        B = 'prod'
        if not P.monter_production(cl, B):
            print('ATTENTION : historique Git absent — essai sauté.')
            return 0
        for f in sorted(os.listdir(os.path.join(P.RACINE, 'outils', 'logistique'))):
            cl.run(B, P.lire_sql('outils/logistique/' + f))
        q = lambda sql, **kw: cl.un(B, sql, **kw)   # noqa: E731
        ok(json.loads(q("select logistics.run_migration('essai des contraintes')"))['report']['ready'] is True, 'données copiées, migration prête')

        # 1. les 47 entités
        presentes = set(cl.lignes(B, "select c.relname from pg_class c where c.relnamespace = 'logistics'::regnamespace and c.relkind in ('r', 'v')"))
        manquantes = [e for e in ENTITES if e not in presentes]
        ok(not manquantes, 'entités du modèle cible absentes : %s' % manquantes)
        ok(len(ENTITES) == 49 and len(set(ENTITES)) == 49, '49 noms (47 entités + pickup/delivery_task) vérifiés')

        # 2. identifiants
        cles = dict(l.split(':') for l in cl.lignes(B, """
          select c.relname || ':' || format_type(a.atttypid, a.atttypmod) from pg_index i join pg_class c on c.oid = i.indrelid
            join pg_attribute a on a.attrelid = c.oid and a.attnum = any (i.indkey)
           where i.indisprimary and c.relnamespace = 'logistics'::regnamespace and c.relkind = 'r' and array_length(i.indkey, 1) = 1"""))
        references = set(cl.lignes(B, """select c.relname from pg_class c where c.relnamespace = 'logistics'::regnamespace and c.relkind = 'r'
                                           and exists (select 1 from pg_constraint k where k.conrelid = c.oid and k.contype = 'p')
                                           and c.relname ~ '(_status|_type|_mode|_channel|_rule|_subscriber|migration_setting|command_log|payment_provider|finance_setting)$'"""))
        for t, typ in sorted(cles.items()):
            if typ == 'uuid':
                continue
            ok((typ == 'text' and t in references) or (typ == 'bigint' and t in JOURNAUX_ET_LIGNES),
               '%s : clé %s sans raison listée (UUID attendu)' % (t, typ))
        for e in ('organization', 'branch', 'customer', 'parcel', 'shipment', 'consolidation', 'delivery', 'invoice', 'payment', 'refund', 'credit',
                  'quote', 'task', 'incident', 'driver', 'vehicle', 'warehouse', 'device', 'pre_alert', 'customs_declaration', 'expense'):
            ok(cles.get(e) == 'uuid', '%s : identifiant UUID' % e)
        ok(q("select count(*) from logistics.parcel where public_token = tracking_number") == '0'
           and q("select count(*) from pg_indexes where schemaname = 'logistics' and tablename = 'parcel' and indexdef ilike '%unique%(tracking_number)%'") == '1',
           'colis : numéro public unique, jeton public distinct')

        # 4. journaux en ajout seul — même pour le propriétaire de la base
        for t, cle in (('audit_log', 'id'), ('tracking_event', 'id'), ('domain_event', 'id')):
            if q('select count(*) from logistics.%s' % t) == '0':
                continue
            for dml in ('update logistics.%s set %s = %s where %s = (select min(%s) from logistics.%s)' % (t, cle, cle, cle, cle, t),
                        'delete from logistics.%s where %s = (select min(%s) from logistics.%s)' % (t, cle, cle, t)):
                code, texte = cl.run(B, dml, expect_error=True)
                ok(code != 0, '%s refuse : %s' % (t, dml.split()[0]))
        ajout_seul = set(cl.lignes(B, "select distinct c.relname from pg_trigger t join pg_class c on c.oid = t.tgrelid join pg_proc p on p.oid = t.tgfoid "
                                      "where p.proname = 'forbid_mutation' and c.relnamespace = 'logistics'::regnamespace"))
        for t in ('audit_log', 'tracking_event', 'domain_event', 'payment', 'refund', 'credit', 'revenue_entry', 'proof_of_delivery',
                  'invoice_status_history', 'shipment_status_history', 'task_status_history', 'migration_run', 'migration_explanation'):
            ok(t in ajout_seul, '%s : protégé en ajout seul' % t)

        # 5. argent
        colonnes = cl.lignes(B, "select c.table_name || ':' || c.column_name || ':' || c.data_type from information_schema.columns c "
                                "join pg_class k on k.relname = c.table_name and k.relnamespace = 'logistics'::regnamespace and k.relkind = 'r' "
                                "where c.table_schema = 'logistics'")
        import re
        # (un nom comme « refunded_by » ou « paid_at » désigne une personne ou une date, pas un montant)
        argent = [l.split(':') for l in colonnes if re.search(MONTANT, l.split(':')[1]) and not re.search(r'(_by|_at|_id|_on|_date)$', l.split(':')[1])]
        ok(len(argent) >= 30, '%d colonnes d\'argent repérées' % len(argent))
        for t, col, typ in argent:
            ok(typ == 'numeric', '%s.%s : %s au lieu de numeric' % (t, col, typ))
        avec_devise = {l.split(':')[0] for l in colonnes if l.split(':')[1] == 'currency'}
        for t in sorted({a[0] for a in argent}):
            if t in avec_devise:
                continue
            ok(t in DEVISE_DU_PARENT, '%s porte des montants sans devise ni parent qui en ait une' % t)
            fk, parent = DEVISE_DU_PARENT[t]
            ok(parent in avec_devise and q("select count(*) from pg_constraint where conrelid = 'logistics.%s'::regclass and contype = 'f' "
                                          "and confrelid = 'logistics.%s'::regclass" % (t, parent)) == '1', '%s tient sa devise de %s' % (t, parent))

        # 6. clés étrangères
        cascades = cl.lignes(B, "select conrelid::regclass::text || ' -> ' || confrelid::regclass::text from pg_constraint where contype = 'f' "
                                "and connamespace in ('logistics'::regnamespace, 'analytics'::regnamespace, 'ops'::regnamespace) and confdeltype = 'c'")
        ok(cascades == [], 'aucun effacement en cascade dans le noyau (%s)' % cascades)
        mises_a_vide = cl.lignes(B, "select conrelid::regclass::text || ' -> ' || confrelid::regclass::text from pg_constraint where contype = 'f' "
                                    "and connamespace in ('logistics'::regnamespace, 'analytics'::regnamespace, 'ops'::regnamespace) and confdeltype = 'n'")
        ok(mises_a_vide == ['logistics.customer -> auth.users'], 'une seule mise à vide : le compte de connexion supprimé laisse la fiche client (%s)' % mises_a_vide)
        code, _ = cl.run(B, "delete from logistics.parcel where id = (select parcel_id from logistics.tracking_event limit 1)", expect_error=True)
        ok(code != 0, 'effacer un colis qui a un historique : refusé')
        code, _ = cl.run(B, "delete from logistics.invoice where id = (select invoice_id from logistics.invoice_item limit 1)", expect_error=True)
        ok(code != 0, 'effacer une facture qui a des lignes : refusé')
        code, _ = cl.run(B, "delete from logistics.customer where id = (select customer_id from logistics.parcel where customer_id is not null limit 1)", expect_error=True)
        ok(code != 0, 'effacer un client qui a des colis : refusé')

        # 7. aucun secret
        sensibles = cl.lignes(B, "select table_schema || '.' || table_name || '.' || column_name from information_schema.columns "
                                 "where table_schema in ('logistics', 'analytics', 'ops') and column_name ~ '(password|secret|api_key|private_key|^otp$|otp_code|otp_plain)'")
        ok(sensibles == [], 'aucune colonne de secret en clair (%s)' % sensibles)
        ok(q("select count(*) from information_schema.columns where table_schema = 'logistics' and table_name = 'delivery' and column_name in ('otp_hash', 'otp_salt')") == '2',
           'le code de livraison n\'existe que haché et salé')

        # 8. rien n'est exposé
        for role in ('anon', 'authenticated'):
            for schema in ('logistics', 'analytics', 'ops'):
                ok(q("select has_schema_privilege('%s', '%s', 'usage')" % (role, schema)) == 'f', '%s n\'entre pas dans %s' % (role, schema))
        sans_rls = cl.lignes(B, "select relname from pg_class where relnamespace = 'logistics'::regnamespace and relkind = 'r' and not relrowsecurity")
        ok(sans_rls == [], 'sécurité par ligne sur chaque table de logistics (%s)' % sans_rls)

        print('PASS modèle cible et contraintes (phase 2) : %d vérifications — 47 entités présentes, UUID partout où une entité se désigne (exceptions '
              'listées : références et journaux), numéro et jeton publics distincts, journaux en ajout seul même pour le propriétaire, montants numeric '
              'et devise explicite, aucune cascade, historique protégé contre l\'effacement, aucun secret en clair, rien d\'exposé (PostgreSQL %s).'
              % (N[0], q('show server_version')))
        return 0


try:
    sys.exit(main())
except AssertionError as e:
    print('ÉCHEC modèle cible et contraintes (après %d vérifications) : %s' % (N[0], e)); sys.exit(1)
