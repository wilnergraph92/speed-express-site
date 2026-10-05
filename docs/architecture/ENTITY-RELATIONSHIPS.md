# Relations entre entités

> Les diagrammes se lisent sur GitHub (Mermaid). `||--o{` = « un à plusieurs ». Les colonnes
> montrées sont les clés et celles qui portent la règle, pas toutes les colonnes.

## 1. Ce qui existe (réalisé et testé)

```mermaid
erDiagram
  ORGANIZATION ||--o{ BRANCH : possede
  ORGANIZATION ||--o{ CUSTOMER : possede
  ORGANIZATION ||--o{ APP_USER : emploie
  BRANCH ||--o{ WAREHOUSE : abrite
  WAREHOUSE ||--o{ WAREHOUSE_LOCATION : contient
  CUSTOMER ||--o{ PARCEL : "envoie (0..1 client par colis)"
  CUSTOMER ||--o{ INVOICE : "est facture"
  CUSTOMER ||--o{ DEVICE : "recoit les notifications"
  PARCEL ||--o{ TRACKING_EVENT : "journal (ajout seul)"
  PARCEL ||--o{ INVOICE_ITEM : "est facture par"
  INVOICE ||--o{ INVOICE_ITEM : contient
  PARCEL_STATUS ||--o{ PARCEL : "statut du colis"
  PARCEL_STATUS ||--o{ TRACKING_EVENT : "de / vers"
  SHIPMENT_STATUS ||--o{ SHIPMENT : "statut de l'expedition"
  INVOICE_STATUS ||--o{ INVOICE : "statut de la facture"
  CONSOLIDATION ||--o{ CONSOLIDATION_PARCEL : "regroupe"
  PARCEL ||--o{ CONSOLIDATION_PARCEL : "1 seule active"
  SHIPMENT ||--o{ SHIPMENT_ITEM : "contient"
  CONSOLIDATION ||--o{ SHIPMENT_ITEM : "OU"
  PARCEL ||--o{ SHIPMENT_ITEM : "OU colis seul"
  TRANSPORT ||--o{ SHIPMENT : "porte plusieurs"
  BRANCH ||--o{ SHIPMENT : "arrive au hub"
  DELIVERY ||--o{ DELIVERY_PARCEL : "livre"
  PARCEL ||--o{ DELIVERY_PARCEL : "affecte a"
  APP_USER ||--o{ TRACKING_EVENT : "acteur"
  APP_USER ||--o{ AUDIT_LOG : "acteur"
```

## 2. La chaîne logistique (le fil du récit)

```mermaid
flowchart LR
  C[Customer] -->|1..n| P[Parcel]
  P -->|reçu, vérifié, rangé| W[Warehouse / Location]
  W -->|n colis| K[Consolidation]
  K -->|1 ou n| S[Shipment]
  S -->|0..1| T[Transport]
  S -->|arrive à| H[Hub]
  H --> D[Customs]
  D --> L[Delivery]
  L --> POD[ProofOfDelivery]
  P -.facturé par.-> I[Invoice]
  P -.journal.-> E[TrackingEvent]
```
Plein = réalisé en base ; les étapes douane et preuve de livraison viennent aux phases 8 et 9.

## 3. Ce qui est prévu (phases 7 à 10)

```mermaid
erDiagram
  WAREHOUSE ||--o{ SCAN : "recoit"
  PARCEL ||--o{ SCAN : "est scanne"
  DEVICE ||--o{ SCAN : "par"
  SHIPMENT ||--o{ CUSTOMS_DECLARATION : "declare"
  CUSTOMS_DECLARATION ||--o{ CUSTOMS_DOCUMENT : "pieces"
  DRIVER ||--o{ ASSIGNMENT : "accepte / refuse"
  VEHICLE ||--o{ TRIP : "effectue"
  ROUTE ||--o{ TRIP : "suit"
  TRIP ||--o{ STOP : "arrets"
  STOP ||--o{ DELIVERY_TASK : "livre"
  DELIVERY_TASK ||--o| PROOF_OF_DELIVERY : "prouve par"
  PARCEL ||--o{ INCIDENT : "signale"
  INVOICE ||--o{ PAYMENT : "est reglee par"
  PAYMENT ||--o{ REFUND : "peut etre remboursee"
  RATE_CARD ||--o{ PRICING_RULE : "regles"
  QUOTE ||--o| INVOICE : "devient"
```

## 4. Règles d'intégrité (toutes prouvées par `logistique-essai.py`)
| Règle | Mécanisme |
|---|---|
| Un colis n'est dans qu'**une** consolidation active | index unique partiel `where removed_at is null` |
| Une ligne d'expédition = **une** consolidation **ou** un colis | `check (num_nonnulls(…) = 1)` |
| Pas deux fois la même chose dans une expédition | `unique (shipment_id, consolidation_id)`, `unique (shipment_id, parcel_id)` |
| Statut de colis ≠ statut d'expédition ≠ statut de facture | trois listes, clés étrangères |
| Arrivée après départ | `check (arrived_at >= dispatched_at)` |
| On ne supprime pas ce qui a de l'histoire | `ON DELETE RESTRICT` partout |
| Journaux en ajout seul | déclencheur `forbid_mutation` (`LG004`) |
| Fermé à l'API | RLS sans politique, aucun `grant` (`42501`) |
