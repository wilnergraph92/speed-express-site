# La machine d'états du colis — workflow opérationnel

> Phase 3, 12 octobre 2026. Étapes du noyau : **003** (la machine), **004** (entrepôt et scan), **005** (expédition), **006** (dernier
> kilomètre), **015** (le workflow complet : `LOADED`, `FAILED_DELIVERY`, cohérence, sortie, inventaire). Éprouvé par
> `outils/tests/logistique-workflow-essai.py` sur la réplique de la production. **Non appliqué en production** : préproduction d'abord
> ([`MIGRATION-REPORT.md`](MIGRATION-REPORT.md) §7). L'historique de conception est dans [`STATE-MACHINE.md`](STATE-MACHINE.md).

## 1. Le workflow

```
CREATED → RECEIVED_AT_WAREHOUSE → INSPECTED → STORED → (CONSOLIDATION_PENDING) → CONSOLIDATED → READY_FOR_SHIPMENT → LOADED
        → IN_TRANSIT → ARRIVED_AT_HUB → CUSTOMS → CLEARED → READY_FOR_DELIVERY → DELIVERY_ASSIGNED → OUT_FOR_DELIVERY → DELIVERED

Exceptions : ON_HOLD · DAMAGED · LOST · RETURNED · FAILED_DELIVERY · CANCELLED
```

Chaque statut a un **code** (la clé, stable, déjà utilisée partout) et un **nom métier** (celui du workflow, `parcel_status.business_name`).
La façade `lg_transition_parcel` accepte l'un ou l'autre ; rien d'autre.

| Nom métier | Code | Qui y mène | Ce que voit le client |
|---|---|---|---|
| CREATED | `CREATED` | enregistrement | enregistré |
| RECEIVED_AT_WAREHOUSE | `RECEIVED` | scan **réception** | reçu |
| INSPECTED | `VERIFIED` | inspection (poids, mesures, état, photos) | reçu |
| STORED | `STORED` | scan **rangement** (emplacement obligatoire) | reçu |
| CONSOLIDATION_PENDING | `CONSOLIDATION_PENDING` | scan **consolidation** (étape intermédiaire) | reçu |
| CONSOLIDATED | `CONSOLIDATED` | consolidation fermée | reçu |
| READY_FOR_SHIPMENT | `READY_FOR_EXPORT` | expédition prête (manifeste) | reçu |
| LOADED | `LOADED` | scan de **sortie** (le colis monte dans son transport) | reçu |
| IN_TRANSIT | `IN_TRANSIT` | départ de l'expédition | en transit |
| ARRIVED_AT_HUB | `ARRIVED` | arrivée de l'expédition | à la douane |
| CUSTOMS | `CUSTOMS_PROCESSING` | dédouanement commencé | à la douane |
| CLEARED | `CUSTOMS_CLEARED` | dédouanement terminé | à la douane |
| READY_FOR_DELIVERY | `AT_DESTINATION_HUB` | réception au hub | au hub |
| DELIVERY_ASSIGNED | `DELIVERY_ASSIGNED` | livraison créée (mission) | en livraison |
| OUT_FOR_DELIVERY | `OUT_FOR_DELIVERY` | mission commencée par le chauffeur | en livraison |
| DELIVERED | `DELIVERED` | preuve de livraison (ou dérogation tracée de la direction) | livré |
| ON_HOLD | `ON_HOLD` | signalé par un opérateur (motif) ; reprise par la direction, **vers le statut d'avant seulement** | retenu |
| DAMAGED | `DAMAGED` | signalé (motif) | incident |
| LOST | `LOST` | décidé par la direction (motif) | perdu |
| RETURNED | `RETURNED` | décidé par la direction (motif) | retourné |
| FAILED_DELIVERY | `FAILED_DELIVERY` | mission échouée (chauffeur) ; puis replanifiée, ramenée au hub ou retournée | incident (« livraison manquée ») |
| CANCELLED | `CANCELLED` | décidé par la direction, seulement avant le départ (motif) | annulé |

## 2. Les règles

1. **Une seule porte.** Le statut ne change que par `logistics.transition_parcel` (ou la façade `lg_transition_parcel`). Une mise à
   jour directe est refusée (`LG001`), même par le propriétaire de la base ; un compte connecté n'a même pas accès à la table.
2. **Tout ce qui n'est pas déclaré est interdit.** Les 104 transitions vivent en données (`logistics.parcel_transition`, annexe) ; les
   358 autres paires sont refusées. Aucun retour arbitraire : les seuls retours en arrière sont légitimes et nommés (sortir un colis
   d'une consolidation ; décharger un colis avant le départ, avec motif ; reprendre après une attente, vers le statut d'avant).
3. **Chaque transition exige ses conditions** : un droit (`colis.statut`, `direction`, ou `livraison` pour le chauffeur de la mission),
   et selon le cas un motif, un entrepôt, un emplacement, un client.
4. **Chaque transition trace, dans la même transaction** : un événement de suivi (`tracking_event`), une ligne d'audit (`audit_log`), un
   événement de domaine (`domain_event`), tous trois de même **corrélation** ; le moteur de notifications en tire, selon ses règles, la
   notification du client (réception, transit, arrivée, dédouanement, hub, livraison, livraison manquée…). Le chargement, interne, ne
   dérange pas le client.
5. **Cohérence colis / livraison / mission / expédition**, vérifiée **à la validation de chaque transaction** (contrôle différé, quel que
   soit le chemin, même la façade directe) :

   | Statut du colis | Exige |
   |---|---|
   | `LOADED` | appartenir à une expédition **prête** |
   | `DELIVERY_ASSIGNED` | une mission de livraison en attente (`CREATED`, `ASSIGNED`, `ACCEPTED`) |
   | `OUT_FOR_DELIVERY` | une mission **commencée** |
   | `FAILED_DELIVERY` | une mission **échouée** |
   | `DELIVERED` | une mission **terminée**, ou la dérogation tracée de la direction (« livré sans preuve ») |

   Le même contrôle s'applique quand la **mission** change d'état. `logistics.workflow_inconsistencies()` liste en plus, pour la
   surveillance, les colis partis sans expédition partie et les colis rangés sans emplacement.
6. **Idempotence.** Une transition ou un scan rejoués avec la même clé rendent le résultat d'origine sans rien refaire ; la même clé pour
   une autre demande est refusée (`LG006`).

## 3. Ce que font les fonctions de l'entrepôt, de l'expédition et de la livraison

| Geste | Fonction | Effet sur le colis |
|---|---|---|
| scan réception | `lg_scan_parcel(…, 'receive')` | `CREATED → RECEIVED` ; colis sans client : incident |
| inspection | `lg_inspect_parcel` | `RECEIVED → VERIFIED` |
| scan rangement | `lg_scan_parcel(…, 'store', emplacement)` | `VERIFIED → STORED` + mouvement |
| scan déplacement | `lg_scan_parcel(…, 'move', emplacement)` | même statut, nouvel emplacement + mouvement + événement |
| scan consolidation | `lg_scan_parcel(…, 'consolidate')` | `STORED → CONSOLIDATION_PENDING` |
| fermer la consolidation | `lg_close_consolidation` | `→ CONSOLIDATED` |
| expédition prête | `lg_mark_shipment_ready` | `CONSOLIDATED → READY_FOR_EXPORT` |
| **scan de sortie** | `lg_scan_parcel(…, 'load')` | `READY_FOR_EXPORT → LOADED` (refusé si l'expédition n'est pas prête) |
| départ | `lg_dispatch_shipment` | `LOADED` **et** `READY_FOR_EXPORT` → `IN_TRANSIT` ; le résultat compte les colis **partis sans scan de sortie** |
| expédition rouverte / annulée | `lg_reopen_shipment`, `lg_cancel_shipment` | `LOADED → READY_FOR_EXPORT` (déchargé, motif) → `CONSOLIDATED` |
| arrivée, douane, hub | `lg_arrive_shipment`, `lg_start_customs`, `lg_clear_customs`, `lg_receive_at_hub` | `→ ARRIVED → CUSTOMS_PROCESSING → CUSTOMS_CLEARED → AT_DESTINATION_HUB` |
| livraison créée | `lg_create_delivery` | `AT_DESTINATION_HUB → DELIVERY_ASSIGNED` |
| mission commencée | `lg_start_task` | `→ OUT_FOR_DELIVERY` |
| livraison faite | `lg_complete_delivery` (preuve : photo ou signature, GPS, code si exigé) | `→ DELIVERED` |
| **mission échouée** | `lg_fail_task` | `OUT_FOR_DELIVERY → FAILED_DELIVERY` (+ incident, + notification au client) |
| mission replanifiée | `lg_reschedule_task` | `FAILED_DELIVERY` (ou hub) `→ DELIVERY_ASSIGNED` |
| mission annulée | `lg_cancel_task` (direction) | `DELIVERY_ASSIGNED` / `FAILED_DELIVERY` `→ AT_DESTINATION_HUB` |

Les colis retenus, abîmés ou perdus **ne suivent pas** leur expédition : ils sont sautés et nommés dans le résultat.

## 4. Le scan

**Un seul point d'entrée**, `lg_scan_parcel`, indifférent au lecteur : il reçoit un **texte**, une **intention**, un **entrepôt**.

| Lecteur | Tableau de bord (poste de scan) | Application « Opérations » |
|---|---|---|
| scanner USB « clavier » (Code 128 de l'étiquette) | ✅ partout dans la page, rafale reconnue | — |
| caméra (Code 128, QR) | ✅ par le détecteur du navigateur (`BarcodeDetector` : Chrome, Edge, Android) ; ailleurs, le poste le dit | ✅ |
| saisie au clavier | ✅ | ✅ |

Le code lu peut être le numéro (`SES-4821937065`), l'adresse de suivi d'un **QR** (`…suivi.html?colis=…&j=<jeton>`, le jeton est
vérifié : un jeton faux donne `INVALID_CODE` et un incident), ou une saisie en minuscules avec des espaces (normalisée).

Intentions : `receive`, `verify`, `store`, `move`, `consolidate`, **`load`** (sortie), `dispatch`, **`inventory`**, `lookup`.
Verdicts : `ACCEPTED`, `DUPLICATE`, `UNKNOWN_PARCEL`, `INVALID_CODE`, `WRONG_WAREHOUSE`, `ALREADY_DISPATCHED`, `DAMAGED`, `PROHIBITED`,
`NO_CUSTOMER`, `WRONG_STATE`. **Chaque lecture est enregistrée**, acceptée ou refusée.

| Cas | Comportement (éprouvé) |
|---|---|
| double scan, même clé | rejoué, rien de refait, une seule lecture |
| second scan, autre clé | `DUPLICATE`, le colis n'avance pas deux fois |
| hors ligne | le poste garde la lecture et sa clé ; renvoyée au retour du réseau avec son heure d'origine (`metadata.horodatage`) ; renvoyée deux fois : rejouée ; arrivée après qu'un autre poste a traité le colis : `DUPLICATE` |
| collision (deux postes, même colis, même instant) | le colis est **verrouillé** : un seul `ACCEPTED`, l'autre `DUPLICATE`, un seul événement |
| colis inexistant | `UNKNOWN_PARCEL`, un incident (un seul, même rescanné), lectures tracées |
| colis déjà livré | `ALREADY_DISPATCHED` (réception, sortie), `WRONG_STATE` (inventaire), `ACCEPTED` (consultation) ; il reste livré |

## 5. L'entrepôt

| Besoin | Où |
|---|---|
| entrepôts, zones (réception, stockage, quai, quarantaine…), emplacements | `warehouse`, `warehouse_zone`, `warehouse_location` (001, 004) |
| réception, entrée, déplacement, sortie | scans `receive`, `store`, `move`, `load` |
| **recherche d'emplacement** | `lg_locate_parcel(code)` → entrepôt, emplacement, zone, dernier scan, dernier inventaire |
| **inventaire** | scan `inventory` (constate la présence ; signale `LOCATION_MISMATCH` si trouvé ailleurs) ; `lg_warehouse_inventory(entrepôt[, emplacement][, depuis])` → attendus, vus, **à chercher** |
| exceptions | incidents (`lg_report_incident`), mises en attente, dommages, quarantaine |

Lecture réservée au personnel (`colis.lire`) ; refusée aux clients et aux visiteurs.

## 6. Ce qui reste à faire (hors de cette phase)

- Le **centre de commande** (009) ne compte pas encore `LOADED` parmi les colis « en entrepôt » ni `FAILED_DELIVERY` dans sa file
  « à traiter » ; l'écran d'**inventaire** et la **recherche d'emplacement** ont leurs fonctions mais pas encore leur page.
- L'application « Opérations » connaît les nouvelles intentions (contrat régénéré) mais ne propose pas encore le scan de sortie ni
  l'inventaire.
- La caméra du tableau de bord n'a pas été essayée sur un vrai poste avec une vraie caméra (pas de caméra sur la machine d'essai).

## 7. Retour en arrière

`015` ajoute (statuts, transitions, contrôles, fonctions) et redéfinit sept fonctions de façon compatible (mêmes signatures). **Ne jamais
repasser 004, 005, 006 ou 008 pour « retrouver » les anciennes versions** : rejouer une étape ancienne après une plus récente n'est pas
sûr (006 échoue).

| Besoin | Geste | Effet |
|---|---|---|
| le contrôle de cohérence bloque un geste légitime imprévu | `drop trigger parcel_workflow_coherence on logistics.parcel;` (et `task_workflow_coherence on logistics.task`) | la machine reste en place ; seule la vérification de fin de transaction s'arrête. La remettre : repasser **015** (rejouable) |
| ne plus proposer la sortie ou l'inventaire | retirer `load` / `inventory` de `INTENTIONS_POSTE` (`ses-api.js`), par PR | le poste ne les propose plus ; la base les accepte toujours |
| abandonner le noyau (tant que rien ne le lit) | [`MIGRATION-REPORT.md`](MIGRATION-REPORT.md) §8 | l'ancien schéma intact, le site continue |

Les statuts `LOADED` et `FAILED_DELIVERY` ne s'effacent pas une fois portés par un colis (l'historique les cite) : on cesse seulement
d'y mener.

## Annexe — les 104 transitions

Lu dans la base (001 → 015). Droit : `colis.statut` = un employé qui a ce droit ; `direction` = gérant ou administrateur ; `livraison` =
le chauffeur, pendant une fonction de mission (ou `colis.statut`). « système » : un événement interne peut la demander.

| De | Vers | Événement | Droit | Exige |
|---|---|---|---|---|
| `CREATED` | `RECEIVED` | ParcelReceived | colis.statut | entrepôt |
| `CREATED` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `CREATED` | `CANCELLED` | ParcelCancelled | direction | motif |
| `RECEIVED` | `VERIFIED` | ParcelVerified | colis.statut | entrepôt |
| `RECEIVED` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `RECEIVED` | `CANCELLED` | ParcelCancelled | direction | motif |
| `RECEIVED` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `RECEIVED` | `LOST` | ParcelLost | direction | motif |
| `VERIFIED` | `STORED` | ParcelStored | colis.statut | emplacement |
| `VERIFIED` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `VERIFIED` | `CANCELLED` | ParcelCancelled | direction | motif |
| `VERIFIED` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `VERIFIED` | `LOST` | ParcelLost | direction | motif |
| `STORED` | `CONSOLIDATION_PENDING` | ParcelConsolidationPending | colis.statut | client |
| `STORED` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `STORED` | `CANCELLED` | ParcelCancelled | direction | motif |
| `STORED` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `STORED` | `LOST` | ParcelLost | direction | motif |
| `CONSOLIDATION_PENDING` | `STORED` | ParcelStored | colis.statut | emplacement |
| `CONSOLIDATION_PENDING` | `CONSOLIDATED` | ParcelConsolidated | colis.statut | client, système |
| `CONSOLIDATION_PENDING` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `CONSOLIDATION_PENDING` | `CANCELLED` | ParcelCancelled | direction | motif |
| `CONSOLIDATION_PENDING` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `CONSOLIDATION_PENDING` | `LOST` | ParcelLost | direction | motif |
| `CONSOLIDATED` | `CONSOLIDATION_PENDING` | ParcelConsolidationPending | colis.statut | client |
| `CONSOLIDATED` | `READY_FOR_EXPORT` | ParcelReadyForExport | colis.statut | client, système |
| `CONSOLIDATED` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `CONSOLIDATED` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `CONSOLIDATED` | `LOST` | ParcelLost | direction | motif |
| `READY_FOR_EXPORT` | `CONSOLIDATED` | ParcelConsolidated | colis.statut | client, système |
| `READY_FOR_EXPORT` | `LOADED` | ParcelLoaded | colis.statut | client |
| `READY_FOR_EXPORT` | `IN_TRANSIT` | ParcelInTransit | colis.statut | client, système |
| `READY_FOR_EXPORT` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `READY_FOR_EXPORT` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `READY_FOR_EXPORT` | `LOST` | ParcelLost | direction | motif |
| `LOADED` | `READY_FOR_EXPORT` | ParcelUnloaded | colis.statut | motif, client |
| `LOADED` | `IN_TRANSIT` | ParcelInTransit | colis.statut | client, système |
| `LOADED` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `LOADED` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `LOADED` | `LOST` | ParcelLost | direction | motif |
| `IN_TRANSIT` | `ARRIVED` | ParcelArrived | colis.statut | client, système |
| `IN_TRANSIT` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `IN_TRANSIT` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `IN_TRANSIT` | `LOST` | ParcelLost | direction | motif |
| `ARRIVED` | `CUSTOMS_PROCESSING` | CustomsStarted | colis.statut | client, système |
| `ARRIVED` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `ARRIVED` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `ARRIVED` | `LOST` | ParcelLost | direction | motif |
| `CUSTOMS_PROCESSING` | `CUSTOMS_CLEARED` | CustomsCleared | colis.statut | client, système |
| `CUSTOMS_PROCESSING` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `CUSTOMS_PROCESSING` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `CUSTOMS_PROCESSING` | `LOST` | ParcelLost | direction | motif |
| `CUSTOMS_CLEARED` | `AT_DESTINATION_HUB` | ParcelAtDestinationHub | colis.statut | client, système |
| `CUSTOMS_CLEARED` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `CUSTOMS_CLEARED` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `CUSTOMS_CLEARED` | `LOST` | ParcelLost | direction | motif |
| `AT_DESTINATION_HUB` | `DELIVERY_ASSIGNED` | DeliveryAssigned | colis.statut | client, système |
| `AT_DESTINATION_HUB` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `AT_DESTINATION_HUB` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `AT_DESTINATION_HUB` | `LOST` | ParcelLost | direction | motif |
| `AT_DESTINATION_HUB` | `RETURNED` | ParcelReturned | direction | motif |
| `DELIVERY_ASSIGNED` | `AT_DESTINATION_HUB` | ParcelReturnedToHub | colis.statut | motif, client |
| `DELIVERY_ASSIGNED` | `OUT_FOR_DELIVERY` | OutForDelivery | livraison | client |
| `DELIVERY_ASSIGNED` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `DELIVERY_ASSIGNED` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `DELIVERY_ASSIGNED` | `LOST` | ParcelLost | direction | motif |
| `DELIVERY_ASSIGNED` | `RETURNED` | ParcelReturned | direction | motif |
| `OUT_FOR_DELIVERY` | `AT_DESTINATION_HUB` | ParcelReturnedToHub | livraison | motif, client |
| `OUT_FOR_DELIVERY` | `DELIVERED` | Delivered | livraison | client |
| `OUT_FOR_DELIVERY` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `OUT_FOR_DELIVERY` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `OUT_FOR_DELIVERY` | `LOST` | ParcelLost | direction | motif |
| `OUT_FOR_DELIVERY` | `RETURNED` | ParcelReturned | direction | motif |
| `OUT_FOR_DELIVERY` | `FAILED_DELIVERY` | DeliveryFailed | livraison | motif, client |
| `ON_HOLD` | `CREATED` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `RECEIVED` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `VERIFIED` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `STORED` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `CONSOLIDATION_PENDING` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `CONSOLIDATED` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `READY_FOR_EXPORT` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `LOADED` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `IN_TRANSIT` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `ARRIVED` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `CUSTOMS_PROCESSING` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `CUSTOMS_CLEARED` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `AT_DESTINATION_HUB` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `DELIVERY_ASSIGNED` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `OUT_FOR_DELIVERY` | ParcelResumed | direction | reprise |
| `ON_HOLD` | `CANCELLED` | ParcelCancelled | direction | motif |
| `ON_HOLD` | `DAMAGED` | ParcelDamaged | direction | motif |
| `ON_HOLD` | `LOST` | ParcelLost | direction | motif |
| `ON_HOLD` | `RETURNED` | ParcelReturned | direction | motif |
| `ON_HOLD` | `FAILED_DELIVERY` | ParcelResumed | direction | reprise |
| `DAMAGED` | `ON_HOLD` | ParcelOnHold | direction | motif |
| `DAMAGED` | `CANCELLED` | ParcelCancelled | direction | motif |
| `DAMAGED` | `LOST` | ParcelLost | direction | motif |
| `DAMAGED` | `RETURNED` | ParcelReturned | direction | motif |
| `FAILED_DELIVERY` | `AT_DESTINATION_HUB` | ParcelReturnedToHub | colis.statut | motif, client |
| `FAILED_DELIVERY` | `DELIVERY_ASSIGNED` | DeliveryAssigned | colis.statut | client |
| `FAILED_DELIVERY` | `ON_HOLD` | ParcelOnHold | colis.statut | motif |
| `FAILED_DELIVERY` | `DAMAGED` | ParcelDamaged | colis.statut | motif |
| `FAILED_DELIVERY` | `LOST` | ParcelLost | direction | motif |
| `FAILED_DELIVERY` | `RETURNED` | ParcelReturned | direction | motif |
