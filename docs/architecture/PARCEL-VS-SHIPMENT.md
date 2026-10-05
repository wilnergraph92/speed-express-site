# Colis ≠ Expédition

C'est la distinction centrale du métier. Les confondre est ce qui rendait l'ancien modèle incapable de
représenter le groupage, un vol partagé, ou un colis qui attend dans un entrepôt.

## 1. Définitions
| | **Colis** (`parcel`) | **Expédition** (`shipment`) |
|---|---|---|
| Ce que c'est | un **objet** qu'un client envoie | un **envoi groupé** d'un point à un hub |
| Appartient à | un client (0 ou 1) | l'entreprise (plusieurs clients y sont mélangés) |
| Contient | rien | des **consolidations** et/ou des **colis seuls** |
| Voyage | **dans** une expédition | **par** un transport |
| Numéro public | `tracking_number` (SES-10001-HT), QR | `code` interne (SHP-001), jamais au public |
| Statuts | 20 (CREATED … DELIVERED, exceptions) | 10 (DRAFT … AT_HUB, CLOSED, CANCELLED) |
| Journal | `tracking_event`, visible du client | événements d'expédition (phase 8), internes |
| Facturé | oui (lignes de facture) | non (c'est le colis qui est facturé) |

## 2. La chaîne
```
Customer ──1..n──▶ Parcel ──▶ Warehouse ──n──▶ Consolidation ──1..n──▶ Shipment ──▶ Transport
                                                                          │
                                                                          ▼
                                            Parcel ◀── Delivery ◀── Customs ◀── Hub
```
- Un client a **plusieurs colis**.
- **Plusieurs colis** appartiennent à **une consolidation** (un colis dans une seule à la fois).
- **Une consolidation** entre dans **une expédition**.
- **Une expédition** voyage par **un transport** (qui peut en porter plusieurs) et **arrive dans un hub**.
- Les colis sont **ensuite affectés à des livraisons**.

## 3. Deux machines d'états, deux vocabulaires
Un statut de colis n'est pas un statut d'expédition : la base les sépare par deux listes distinctes
(`parcel_status`, `shipment_status`) avec clés étrangères. `shipment.status = 'STORED'` est **refusé** ;
`parcel.status = 'DISPATCHED'` aussi (testé).

| Moment | Statut de l'**expédition** | Statut du **colis** (traduit par un événement) |
|---|---|---|
| consolidation fermée | — | `CONSOLIDATED` |
| expédition créée | `DRAFT` → `READY` | `READY_FOR_EXPORT` |
| départ | `DISPATCHED` → `IN_TRANSIT` | `IN_TRANSIT` |
| arrivée au hub | `ARRIVED` | `ARRIVED` |
| douane | `CUSTOMS_PROCESSING` → `CUSTOMS_CLEARED` | `CUSTOMS_PROCESSING` → `CUSTOMS_CLEARED` |
| au hub | `AT_HUB` | `AT_DESTINATION_HUB` |
| livraison | `CLOSED` quand tout est livré | `DELIVERY_ASSIGNED` → `OUT_FOR_DELIVERY` → `DELIVERED` |

## 4. La règle de traduction (phases 6 et 8)
**L'expédition ne modifie jamais le statut d'un colis directement.** Quand elle change d'état, elle
émet un **événement** (`ShipmentDispatched`…). Le cycle de vie du colis **consomme** cet événement et,
pour chaque colis concerné, demande la **transition** correspondante à **sa** machine d'états — qui la
valide (ou la refuse). Un colis en `ON_HOLD` ou `DAMAGED` ne repart donc pas par accident avec le lot.

## 5. Exemple
Trois clients (A : 2 colis, B : 1, C : 3) déposent leurs colis à Miami. L'entrepôt en met 5 dans la
consolidation `CONS-001` (le sixième, endommagé, reste en `DAMAGED`). `CONS-001` entre dans `SHP-001`,
qui voyage sur le vol XX123, lequel porte aussi `SHP-002`. À Port-au-Prince (hub), la douane libère
l'expédition ; les 5 colis deviennent `AT_DESTINATION_HUB`, sont répartis en 3 livraisons (une par
client), puis `DELIVERED` chacun. Chaque client voit **son** suivi ; personne ne voit l'expédition.

## 6. Dans l'ancien modèle
Il n'y avait que `colis.statut` (5 valeurs) : « expédié » voulait dire à la fois « parti » et « en
transit », sans entrepôt, sans groupage, sans hub. Le rattrapage traduit ces 5 valeurs
(`DATA-MIGRATION-MAP.md` §3) sans rien perdre.
