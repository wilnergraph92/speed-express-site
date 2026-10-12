# Rapport de migration : de l'ancien schéma (`public`) au noyau (`logistics`)

> Phase 2 « activer le noyau logistique », 11 octobre 2026. Ce rapport dit **ce qui est prouvé**, **sur quoi**, et **ce qui
> reste à faire pour la production**. Rien de ce qui suit n'a été appliqué en production : aucune migration, aucune lecture
> basculée, aucune donnée touchée.

## 0. Verdict

| Critère de fin de phase | État | Preuve |
|---|---|---|
| Rattrapage validé | ✅ sur la **réplique de la production** et en **répétition de préproduction** | `logistique-migration-essai.py` (79), `staging-essai.py` (73) |
| Réconciliation = zéro différence inexpliquée | ✅ `ready: true`, `unexplained: 0`, **sept empreintes égales** | §5 |
| Essais PostgreSQL verts | ✅ suite complète (§9) | `verifier.sh` |
| Retour en arrière documenté | ✅ et **éprouvé** (§8) | `logistique-migration-essai.py` §8 |
| Préproduction validée | 🟡 **répétée** sur une base marquée « staging » avec les scripts réels ; le **projet Supabase de préproduction n'existe pas encore** (geste du propriétaire, `docs/production/ENVIRONNEMENTS.md` §3) | `staging-essai.py` |
| Production | ⬜ non appliquée ; prérequis : sauvegarde installée, remède de la phase 1 collé, préproduction passée | §7 |

**La lecture du noyau n'est pas activée** : `portailNoyau` et `centreNoyau` restent à `false` dans `config.js`, et la double écriture
est **éteinte** à l'installation.

## 1. Les étapes de la stratégie, où elles en sont

| # | Étape (`MIGRATION-STRATEGY.md`) | Où | État |
|---|---|---|---|
| 1 | schéma `logistics` | 001 | écrit, éprouvé |
| 2 | rattrapage (backfill) | 002 + **014** (compléments) | éprouvé sur la réplique de la production |
| 3 | réconciliation | 002 + **014** (empreintes, classement, rapport) | zéro écart inexpliqué |
| 4 | machine d'états | 003 | écrite, éprouvée (phase 6) |
| 5 | audit / événements | 001, 003 | journaux en ajout seul, éprouvés |
| 6 | double écriture | **014** | écrite, éprouvée, **éteinte** |
| 7 | façade `public.lg_*` | 008 → 013 | écrite, éprouvée, **non appelée** par les interfaces |
| 8 | migration des interfaces | interrupteurs `portailNoyau`, `centreNoyau` | **non commencée** (hors phase 2) |
| 9 | retrait de l'ancien chemin | — | **interdit** tant que 8 n'est pas validée et qu'une sauvegarde de référence n'est pas signée |

## 2. Le modèle cible : les 47 entités

Toutes présentes dans `logistics` (vérifié sur le catalogue réel par `logistique-contraintes-essai.py`) :

| Domaine | Entités | Étape |
|---|---|---|
| Organisation, comptes | organization, branch, app_user, customer, device | 001 |
| Entrepôt, suivi | warehouse, warehouse_location, parcel, tracking_event, incident | 001, 004 |
| Transport, douane | consolidation, shipment, shipment_item, transport, route, trip, stop, load_unit, customs_declaration, customs_document | 001, 005 |
| Dernier kilomètre | delivery, driver, vehicle, driver_availability, delivery_zone, pickup_task, delivery_task (vues typées de `task`), assignment, proof_of_delivery | 001, 006 |
| Finance | quote, pricing_rule, rate_card, weight_bracket, service_fee, surcharge, tax, exchange_rate, invoice, invoice_item, payment, refund, credit, customer_balance (vue), expense, revenue (vue de `revenue_entry`) | 001, 007, **014** |
| Événements, audit | audit_log, domain_event, event_delivery, dead_letter | 001, 003 |
| Ajouts de la phase 2 | **pre_alert** (pré-alertes), parcel.manual_price, parcel.currency, app_user.staff_code, marqueurs `legacy_deleted_at` | **014** |

### Contraintes du cahier des charges, vérifiées sur le catalogue

| Contrainte | Résultat |
|---|---|
| UUID interne | chaque entité désignable de l'extérieur a un UUID. **Exceptions justifiées et listées** dans l'essai : tables de référence à clé naturelle (statuts, types, canaux) ; journaux et lignes de détail en ajout seul à clé entière croissante (`tracking_event`, `audit_log`, `domain_event`, `invoice_item`, `shipment_item`, `weight_bracket`, `exchange_rate`…), toujours atteints par leur parent en UUID et dont l'ordre compte |
| `tracking_number` public, jeton public séparé | `parcel.tracking_number` unique, `parcel.public_token` distinct pour chaque colis |
| Aucun secret exposé | aucune colonne de mot de passe ou de clé ; le code de livraison n'existe que **haché et salé** ; ni visiteur ni compte connecté n'entre dans `logistics`, `analytics` ou `ops` ; sécurité par ligne sur chaque table du noyau |
| Audit et historique en ajout seul | `audit_log`, `tracking_event`, `domain_event`, paiements, avoirs, remboursements, journaux d'état… refusent modification et effacement, **même du propriétaire de la base** |
| Montants `numeric`, devise explicite | toutes les colonnes d'argent sont `numeric` ; chaque table qui en porte a sa devise, sauf `invoice_item` et `weight_bracket` qui la tiennent de leur parent (vérifié) ; le colis porte désormais `currency` |
| FK `restrict` quand l'histoire doit être conservée | **aucune** suppression en cascade dans le noyau ; une seule mise à vide (un compte de connexion supprimé laisse la fiche client) ; effacer un colis qui a un historique, une facture qui a des lignes, un client qui a des colis : refusé |
| Aucune suppression destructive | ce qui disparaît de l'ancien schéma est **marqué** (`legacy_deleted_at`), jamais effacé ; `migrations-garde-fou.py` refuse toute instruction destructive dans les étapes |

## 3. La correspondance (mapping)

Détail colonne par colonne : [`DATA-MIGRATION-MAP.md`](DATA-MIGRATION-MAP.md). Résumé :

| Ancien (`public`) | Noyau (`logistics`) | Clé |
|---|---|---|
| `clients` (clients, et équipe portant des colis) | `customer` | `legacy_client_id` |
| `clients` (équipe) + `matricule` | `app_user` + `staff_code` | `id` |
| `colis` + `prix_manuel` | `parcel` + `manual_price`, `currency` | `legacy_parcel_id` |
| `colis_historique` | `tracking_event` | `legacy_history_id` |
| `factures` / `factures.lignes` | `invoice` / `invoice_item` | `legacy_invoice_id` / `legacy_line_key` |
| `appareils` | `device` | `push_token` |
| `prealertes` | `pre_alert` | `legacy_pre_alert_id` |

Ce qui n'est **pas** migré, volontairement : paiements individuels (l'ancien schéma n'a que `montant_paye` agrégé ; aucun paiement
n'est fabriqué), succursales, entrepôts et positions (jamais enregistrés), mots de passe et sessions (restent dans Supabase Auth),
le registre `matricules_attribues` (reste dans `public`).

## 4. Le mécanisme (étape 014)

| Besoin | Réponse | Fonction |
|---|---|---|
| **Idempotence** | chaque copie est un `insert … on conflict … do update … where … is distinct from` : rejouée sans changement, **0 inséré, 0 modifié** | `backfill_from_legacy()`, `backfill_complements()` |
| **Compteurs** | inséré / modifié par entité, à chaque exécution | `run_migration()` → `counters` |
| **Réconciliation automatique** | écarts ligne à ligne : absent, orphelin, champ différent | `reconcile_with_legacy()`, `reconcile_complements()` |
| **Rapport des différences** | écarts classés : **expliqués** (`legacy_deleted`, ou `owner_reviewed` avec une raison écrite) / **inexpliqués** | `migration_differences()`, `migration_report()` |
| **Checksum** | pour chaque entité, une empreinte md5 des champs comparés, lus des deux côtés dans le même ordre (une valeur vide garde sa place) | `migration_checksums()` |
| **Verdict** | `ready` = zéro écart inexpliqué **et** aucune empreinte différente sans explication | `migration_report()` |
| **Retry** | erreurs passagères (verrou, sérialisation, délai) retentées 3 fois ; double écriture : délai croissant (1, 2, 4… min), « dead » après 8 échecs, `retry_dead_sync()` après correction | `run_migration()`, `process_sync_queue()` |
| **Traçabilité** | chaque exécution journalisée, réussie ou non (durée, essais, compteurs, verdict, erreur), en ajout seul | `logistics.migration_run` |
| **Double écriture** | déclencheurs `lg_double_ecriture` → file `sync_queue` → `process_sync_queue()` qui rejoue le **même** rattrapage (aucune seconde correspondance à maintenir) ; éteinte par défaut ; refuse de s'allumer si la migration n'est pas prête (`LG010`) | `set_double_write()` |
| **Sécurité du site** | le déclencheur avale toute erreur : une panne du noyau, ou même de la file, ne fait **jamais** échouer une écriture du site (éprouvé) | `enqueue_legacy_change()`, `sync_failure` |

Pourquoi une file plutôt qu'une copie immédiate dans le déclencheur : la copie immédiate dupliquerait la correspondance (risque de
dérive entre deux codes) et exposerait chaque écriture du site à une erreur du noyau. La file rend ces deux risques impossibles ;
le prix est un retard de l'ordre de la minute, sans importance tant que rien ne lit le noyau.

## 5. Résultats sur la réplique de la production

Base : la production telle que sondée les 7 et 8 octobre 2026 (fichiers du 5 octobre, SQL de notifications de l'application,
collages du 7 octobre), **remède de la phase 1 collé**, avec des données fictives de même forme : prix saisis, pré-alertes
(dont une reçue et une annulée), deux factures groupées dont une a remplacé trois factures individuelles, comptes d'équipe à
identifiant ADM/GER/EMP. Droits par défaut de Supabase reproduits.

| Entité | Ancien | Noyau | Marquées supprimées | Empreintes |
|---|---|---|---|---|
| customer | 10 | 10 | 0 | égales |
| app_user (+ identifiants d'équipe) | 4 | 4 | 0 | égales |
| parcel (+ 7 prix saisis) | 203 | 203 | 0 | égales |
| tracking_event | 286 | 286 | 0 | égales |
| invoice (+ 204 lignes) | 202 | 202 | 0 | égales |
| pre_alert | 10 | 10 | 0 | égales |
| device | 0 | 0 | 0 | égales (aucun téléphone enregistré, comme en production) |

Premier rattrapage : **0,17 s**, `ready: true`, `unexplained: 0`. Rejeu : **0,12 s**, 0 inséré, 0 modifié partout. L'ancien schéma
est identique, table par table, avant et après (empreinte de contenu).

Scénarios éprouvés ensuite :
- **dérive** sans double écriture (statut changé, facture payée, facture effacée, pré-alerte ajoutée) : visible (`ready: false`,
  écarts nommés), double écriture refusée, résorbée par un rattrapage ; la facture effacée est **marquée** et comptée comme
  expliquée (`legacy_deleted`) ;
- **double écriture** allumée : colis créé, changé de statut, prix saisi, pré-alerte déposée **par un client connecté sous ses
  propres règles**, coordonnées modifiées → tout arrive dans le noyau, historique compris ; éteinte : plus aucun dépôt ;
- **pannes** : le noyau refuse une ligne → le site écrit quand même, l'échec est journalisé et replanifié, passe en « dead »
  après 8 échecs, repart après correction ; la **file elle-même** en panne → le site écrit quand même, l'incident est consigné, un
  rattrapage complet comble le trou ;
- **écart examiné** : un champ corrigé dans le noyau reste inexpliqué (et l'empreinte le confirme) jusqu'à une explication écrite
  (`explain_difference`, raison d'au moins 10 caractères, conservée).

## 6. Préproduction (répétition)

Sur une base marquée « staging » installée par le script réel (`outils/staging/`), avec les **données synthétiques** :
001 → 014 passent, rattrapage prêt (60 colis, 12 pré-alertes, 4 identifiants d'équipe, empreintes égales), double écriture qui
suit une écriture du site. `reinitialiser.sql` retire désormais aussi le noyau de préproduction (ses journaux en ajout seul et ses
comptes protégés empêcheraient sinon d'effacer les comptes synthétiques) ; on le repasse ensuite — éprouvé.

**À faire par le propriétaire** pour que « préproduction validée » soit vrai au sens strict : créer le projet
`speed-express-staging` et y dérouler la procédure du §7, étapes 1 à 6.

## 7. Procédure (préproduction d'abord, puis production)

Chaque étape : vérifier le nom du projet en haut de la page ; en production, **sauvegarde « avant migration » vérifiée** juste avant.

1. Prérequis production : sauvegarde quotidienne installée ; remède de la phase 1 collé et contrôlé (`GO-LIVE-SECURITY-CHECKLIST.md` §3).
2. SQL Editor : 001 → 015 (015 : le workflow du colis, phase 3), **dans l'ordre**, un fichier à la fois (`GO-LIVE-CHECKLIST.md` §4). Aucune donnée n'est copiée.
3. `select logistics.run_migration('premier rattrapage');`
4. `select logistics.migration_report();` → exiger `"ready": true`, `"unexplained": 0`, `"checksum_unexplained": []`.
   Sinon : `select * from logistics.migration_differences() where not explained;` — corriger la source, ou consigner un écart
   examiné : `select logistics.explain_difference('mismatch', 'customer', '<id>', '<raison écrite>');`
5. Rejouer 3 : les compteurs doivent être à 0 partout.
6. (Facultatif, quand on prépare l'étape 8) `select logistics.set_double_write(true);` puis planifier chaque minute
   `select logistics.process_sync_queue();` (pg_cron ou le travailleur) ; surveiller `migration_report() -> 'sync_queue'`.
7. Consigner dans la PR : l'archive « avant », l'heure, le rapport (`ready`, empreintes).

## 8. Retour en arrière

| Situation | Geste | Effet |
|---|---|---|
| la double écriture dérange | `select logistics.set_double_write(false);` | les déclencheurs redeviennent muets immédiatement ; rien d'autre ne change |
| un rattrapage a écrit quelque chose de faux dans le noyau | corriger la cause, `run_migration()` : il réécrit le noyau depuis l'ancien schéma (source de vérité) | l'ancien schéma n'est jamais touché |
| abandonner le noyau (tant que rien ne le lit) | `drop schema analytics cascade; drop schema ops cascade; drop schema logistics cascade;` | ses déclencheurs sur l'ancien schéma partent avec lui ; **l'ancien schéma est intact et le site continue** (éprouvé : colis enregistré et facturé après le retrait) |
| données de l'ancien schéma abîmées | ce n'est pas une affaire de migration : restauration (`docs/production/BACKUP-AND-RECOVERY.md`) | — |

Le retrait du noyau est **destructif pour le noyau seul** : il demande une sauvegarde de référence et l'accord écrit du propriétaire
(`docs/production/ROLLBACK.md`). Il n'est sans perte que tant qu'aucune interface n'écrit dans le noyau.

## 9. Essais

| Suite | Vérifications | Ce qu'elle prouve |
|---|---|---|
| `logistique-migration-essai.py` | 79 | le mécanisme complet sur la réplique de la production (§5, §8) |
| `logistique-contraintes-essai.py` | 128 | les 47 entités et les contraintes du §2, sur le catalogue réel |
| `staging-essai.py` | 73 | la préproduction, dont la répétition générale du noyau (§6) |
| `logistique-*-essai.py` (phases 5 à 17) | plus de 3 900 | chaque étape 001 → 013 |
| `migrations-garde-fou.py` | — | 14 étapes sans instruction destructive ni création non rejouable |

## 10. Limites connues

- Le traitement de la file rejoue le rattrapage **complet** : 0,1 à 0,2 s aujourd'hui ; à réexaminer au-delà de ~100 000 colis
  (rattrapage par lots ciblés), seuil noté ici.
- La file n'est traitée que si `process_sync_queue()` est planifié : sans planification, le rapport montre l'âge de la plus vieille
  ligne en attente (`oldest_pending_minutes`).
- La réplique de la production repose sur la sonde anonyme et l'historique Git ; les **volumes réels** et la **qualité réelle** des
  données ne sont connus qu'au premier `migration_report()` en production : c'est précisément le rôle de l'étape 4 du §7.
