# Modèle de domaine — noyau logistique

> Phase 5, 5 octobre 2026. **Réalisé** = tables créées par `outils/logistique/001-modele-de-domaine.sql`
> et éprouvées par `outils/tests/logistique-essai.py` sur PostgreSQL réel. **Prévu** = spécifié ici,
> créé à la phase indiquée. **Rien n'est appliqué en production** à ce jour (voir `MIGRATION-STRATEGY.md`).

## 1. Le récit du métier
Un **client** envoie des **colis**. Le colis arrive dans un **entrepôt**, y est reçu, vérifié, rangé.
Plusieurs colis sont groupés dans une **consolidation**. La consolidation entre dans une **expédition**,
qui voyage par un **transport** (vol, traversée) et arrive dans un **hub**. Là, la douane, puis les
colis sont affectés à des **livraisons**, portées par des **tournées** et des **chauffeurs**, jusqu'à la
**preuve de livraison**. Tout cela est **facturé** et **tracé**.

## 2. Les entités

| Entité | Table | Rôle | État |
|---|---|---|---|
| Organization | `organization` | l'entreprise (une aujourd'hui, multi-entreprise préparé) | **réalisé** |
| Branch | `branch` | succursale, agence, hub (pays HT/DO/US) | **réalisé** (vide) |
| User | `app_user` | personnel : employé, gérant, administrateur | **réalisé** |
| Customer | `customer` | qui expédie ; peut exister **sans compte** | **réalisé** |
| Device | `device` | téléphone à notifier ; scanners (phase 7) | **réalisé** |
| Warehouse | `warehouse` | entrepôt d'une succursale | **réalisé** (squelette → phase 7) |
| WarehouseLocation | `warehouse_location` | zone / emplacement | **réalisé** (squelette → phase 7) |
| Parcel | `parcel` | **un colis** | **réalisé** |
| TrackingEvent | `tracking_event` | journal du colis, **ajout seul** | **réalisé** |
| Consolidation | `consolidation` + `consolidation_parcel` | groupe de colis ; un colis dans **une seule** consolidation active | **réalisé** |
| Shipment | `shipment` | **une expédition**, statuts propres | **réalisé** |
| ShipmentItem | `shipment_item` | une consolidation **ou** un colis seul | **réalisé** |
| Transport | `transport` | vol, traversée, camion ; partagé par plusieurs expéditions | **réalisé** |
| Delivery | `delivery` + `delivery_parcel` | livraison de colis à un destinataire (adresse, fenêtre, priorité, code de livraison) | **réalisé** (phase 9, `LAST-MILE.md`) |
| Invoice | `invoice` + `invoice_item` | facture et ses lignes liées aux colis | **réalisé** (moteur : phase 10, `FINANCE-ENGINE.md`) |
| AuditLog | `audit_log` | qui, quoi, quand, avant/après ; **ajout seul** | **réalisé** (alimenté → phase 6) |
| *(listes)* | `parcel_status`, `shipment_status`, `invoice_status` | vocabulaires de statuts, **séparés** | **réalisé** |
| Route, Trip, Stop | `route`, `trip`, `stop` | tournées (transport, dernier kilomètre) | **réalisé** (phases 8 et 9) |
| Driver, Vehicle, DriverAvailability, DeliveryZone | `driver`, `driver_zone`, `vehicle`, `driver_availability`, `delivery_zone` | chauffeurs (membres de l'équipe), véhicules, créneaux, secteurs | **réalisé** (phase 9) |
| PickupTask, DeliveryTask, Assignment | `task` (+ vues `pickup_task`, `delivery_task`), `assignment`, `pickup_parcel` | missions, propositions, colis collectés | **réalisé** (phase 9) |
| ProofOfDelivery | `proof_of_delivery` | nom, signature **ou** photo, heure, GPS, code vérifié ; **ajout seul** | **réalisé** (phase 9) |
| Incident | `incident` | client absent, adresse fausse, dommage… | **réalisé** (phases 7 et 9) |
| CustomsDeclaration, CustomsDocument | `customs_declaration`, `customs_document` | douane | **réalisé** (phase 8) |
| LoadUnit | `load_unit` | conteneur / unité logistique | **réalisé** (phase 8) |
| Quote, PricingRule, RateCard, Zone, WeightBracket, ServiceFee, Surcharge, Tax | `quote`, `pricing_rule`, `rate_card`, `pricing_zone`, `weight_bracket`, `service_fee`, `surcharge`, `tax`, `exchange_rate` | tarification | **réalisé** (phase 10) |
| Payment, Refund, Credit, CustomerBalance, Expense, Revenue | `payment`, `refund`, `credit`, vue `customer_balance`, `expense`, `revenue_entry` | argent | **réalisé** (phase 10) |
| Notification | — | file d'envoi | prévu — phases 6 et 10 |
| DomainEvent | `domain_event`, `event_delivery`, `dead_letter` | boîte d'envoi des événements (ADR 0003) | **réalisé** (phase 6) |

## 3. Règles de modélisation (valables pour toutes les phases)
1. **Identifiant interne ≠ identifiant public.** `id` (uuid) ne sort jamais ; le public voit `tracking_number` (+ `public_token` dans le QR).
2. **On ne supprime rien qui porte de l'histoire** : toutes les clés étrangères métier sont `ON DELETE RESTRICT`. (L'ancien schéma, lui, supprime en cascade ses factures : c'est un des défauts que le noyau corrige.)
3. **Ajout seul** pour ce qui prouve : `tracking_event`, `audit_log` refusent `UPDATE` et `DELETE` (code `LG004`), y compris au propriétaire.
4. **Un statut = un vocabulaire** : colis, expédition et facture ont chacun leur liste, avec clé étrangère. Un statut d'un type n'entre pas dans l'autre.
5. **Pas de donnée inventée** : ce qui n'a jamais été enregistré reste vide.
6. **Fermé à l'API** : aucune table n'est accordée à `anon` ni `authenticated`.
7. **Traçabilité de l'origine** : `source` et `legacy_*_id` sur chaque ligne reprise de l'ancien schéma.
8. **Argent** : `numeric(14,2)` + devise (`USD`, `DOP`, `HTG`), jamais de flottant.
9. **Noms** : anglais, `snake_case`, singulier (ADR 0004).

## 4. Cardinalités essentielles
- Un **client** → **n colis** ; un colis → **0 ou 1 client** (colis sans client possible : cas d'entrepôt).
- Un **colis** → **n événements** de suivi ; **n lignes de facture** (via `invoice_item`).
- Une **consolidation** → **n colis** ; un colis → **au plus 1 consolidation active** (historique des retraits conservé).
- Une **expédition** → **n lignes** (chacune = 1 consolidation **ou** 1 colis) ; → **0 ou 1 transport** ; un transport → **n expéditions** ; une expédition → **1 hub** de destination.
- Une **livraison** → **n colis** ; un colis peut avoir plusieurs livraisons au fil du temps (échec puis nouvel essai).
- Une **facture** → **1 client**, **n lignes**, chaque ligne → **0 ou 1 colis**.

## 5. Ce que ce modèle rend possible (et que l'ancien interdisait)
Groupage de plusieurs clients dans une expédition ; suivi par entrepôt et emplacement ; plusieurs
expéditions sur un même vol ; livraison de plusieurs colis d'un même client en un arrêt ; facture
rattachée à ses colis ; client sans compte ; historique infalsifiable.
