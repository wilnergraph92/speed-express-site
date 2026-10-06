# Consolidation, expédition, transport et douane

> Phase 8. Source : `outils/logistique/005-transport-douane.sql` ; preuve : `outils/tests/logistique-transport-essai.py` (105 vérifications,
> dont 5 mutations détectées). **Non appliqué en production.**

## 1. Le flux
```
Colis (CONSOLIDATION_PENDING) ──▶ Consolidation ──fermer──▶ colis CONSOLIDATED ──▶ Expédition (DRAFT) ──manifeste──▶ READY ──partir──▶ DISPATCHED ──▶ IN_TRANSIT
   ──arrivée──▶ ARRIVED ──douane──▶ CUSTOMS_PROCESSING ──▶ CUSTOMS_CLEARED ──hub──▶ AT_HUB ──livraisons prises en charge──▶ CLOSED
```
**Deux machines d'états, deux vocabulaires** (cinq mots seulement sont communs). L'expédition ne change **jamais** un statut de colis directement : chaque service demande,
colis par colis, une transition à la machine du colis, qui la valide. **Un colis retenu (en attente, endommagé, perdu) est sauté et rapporté : il ne part pas avec le lot.**

## 2. Les services métier (tous derrière `public.lg_*`, acteur = compte connecté)
| Service | Ce qu'il fait | Refuse |
|---|---|---|
| `open_consolidation` | ouvre une consolidation (code, entrepôt, pays, mode) | mode ou pays inconnu |
| `add_parcel_to_consolidation` | y met un colis | statut ≠ « en attente de consolidation », **autre destination, autre mode, sans client**, consolidation close, colis déjà dans une autre (index unique) |
| **`close_consolidation`** | ferme : **tous** les colis passent « consolidés » dans une seule transaction | consolidation **vide**, colis pas en attente, déjà close ; **idempotent** |
| **`create_shipment`** | crée l'expédition (DRAFT) avec des **consolidations, des colis en vrac, des unités logistiques** | destination qui n'est pas un **hub**, mode différent, consolidation **ouverte** ou déjà dans une autre expédition, expédition vide ; **idempotent** |
| **`generate_manifest`** | fige le **manifeste** (colis, poids, valeur, retenus, totaux) en une **version** numérotée, empreinte md5 | expédition déjà partie, sans colis |
| `mark_shipment_ready` | DRAFT → READY ; colis → « prêts pour l'export » | **manifeste absent ou périmé** |
| **`dispatch_shipment`** | READY → DISPATCHED ; **transport** parti ; colis → « en transit » | pas prête, transport **annulé / d'un autre mode / inconnu**, **manifeste périmé** ; **idempotent** |
| `mark_shipment_in_transit` | DISPATCHED → IN_TRANSIT | — |
| **`arrive_shipment`** | → ARRIVED ; colis → « arrivés » ; le transport est « arrivé » quand **toutes** ses expéditions le sont | avant le départ |
| **`start_customs`** | → CUSTOMS_PROCESSING ; **déclaration** déposée (valeur déclarée, pays déduits des succursales, instantané des colis), documents | avant l'arrivée |
| **`clear_customs`** / `reject_customs` | acceptée → CUSTOMS_CLEARED ; **refusée → l'expédition reste en douane**, une nouvelle déclaration est possible | aucune déclaration en cours ; refus sans motif |
| `receive_at_hub` | → AT_HUB ; colis → « au hub » (rattachés à l'entrepôt du hub) | avant la douane, entrepôt d'un autre hub |
| `close_shipment` | AT_HUB → CLOSED | des colis attendent encore au hub |
| `cancel_shipment` / `reopen_shipment` | **direction** : annule (une expédition prête est d'abord rouverte : ses colis redeviennent « consolidés ») | sans motif ; après le départ |

Chaque opération produit ses **événements** (`ShipmentCreated`, `ManifestGenerated`, `ShipmentReady`, `ShipmentDispatched`, `ShipmentArrived`, `ShipmentCustomsStarted`, `ShipmentCustomsCleared`, `ShipmentAtHub`, `ShipmentClosed`,
`CustomsDeclarationSubmitted`…), une **trace d'audit** et une ligne d'**historique d'expédition** (ajout seul), avec **une corrélation** qui relie l'expédition et tous ses colis.

## 3. Le manifeste : figé, vérifié
Son contenu est **déterministe** (mêmes champs, même ordre) ; son empreinte est comparée au contenu **actuel** avant « prête » et avant le départ. Si un poids change ou qu'un colis est retenu **après** la génération,
le manifeste est **périmé** et le départ est refusé jusqu'à sa régénération (version suivante ; **toutes les versions sont conservées**, en ajout seul).

## 4. Modes de transport futurs
Les modes sont des **données** (`transport_mode`), plus une contrainte : ajouter le rail ou le fluvial est **une ligne**, utilisable aussitôt (testé avec « rail »). Un mode non déclaré est refusé.

## 5. Unités logistiques
Conteneur, palette, ULD, sac (`load_unit`) : contiennent des consolidations et entrent **telles quelles** dans une expédition. Un élément d'expédition est **une** chose : consolidation, colis, ou unité.

## 6. Douane
`customs_declaration` (une seule **vivante** par expédition : une refusée peut être remplacée, pas doublée), `customs_document` (chemin d'un fichier d'un compartiment **privé** : `customs/<déclaration>/<fichier>`).
Aucun taux, aucune taxe, aucun droit de douane n'est calculé ici : les droits de douane eux-mêmes ne sont **pas** modélisés ; le fret et les taxes sont dans le moteur financier (phase 10, `FINANCE-ENGINE.md`).

## 7. Limites assumées
- **Pas de tarifs** : le coût du fret et les frais de douane relèvent du moteur financier (phase 10, réalisé : `FINANCE-ENGINE.md`) ; les **frais de douane** peuvent s'y saisir comme **dépenses** rattachées à l'expédition.
- **Un colis retenu au départ** reste sur place ; sa réintégration dans une autre expédition suit le flux normal (reprise, nouvelle consolidation).
- **Pas de transfert partiel** d'une expédition (une partie arrive, l'autre non) : une expédition arrive en un bloc.
- **Itinéraires, voyages et arrêts** (`route`, `trip`, `stop`) existent comme structure ; leur planification pour le dernier kilomètre est réalisée en phase 9 (`LAST-MILE.md`).
