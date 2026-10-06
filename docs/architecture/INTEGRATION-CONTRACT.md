# Contrat d'intégration

Ce que toute interface (site, applications, partenaires) peut compter recevoir et doit respecter.

## 1. Appels
- **Façade** : fonctions `public.lg_<verbe>_<nom>` appelées par `rpc/…`. Les tables du schéma `logistics` ne sont **jamais** lues ni écrites directement par un client.
- **Authentification** : jeton Supabase. Le rôle est relu en base à chaque appel.
- **Version** : les paramètres ajoutés ont une valeur par défaut. Un changement incompatible crée `lg_<…>_v2` ; l'ancienne reste appelable jusqu'à la fin de sa période annoncée.
- **Temps** : UTC (`timestamptz`), affichage local côté interface. **Argent** : `numeric(14,2)` + code devise (USD, DOP, HTG), jamais un nombre flottant.

## 2. Idempotence et corrélation
- Toute opération qui **écrit** accepte `p_idempotency_key text` : rejouée avec la même clé, elle renvoie le **résultat d'origine** sans rien refaire.
- Toute opération porte un `correlation_id` (créé si absent) qui **suit tous les événements et traces** qu'elle provoque.

## 3. Enveloppe d'un événement
```json
{ "id": "uuid", "type": "ParcelReceived", "version": 1,
  "occurred_at": "2026-10-05T14:03:11Z", "aggregate": {"type": "parcel", "id": "uuid"},
  "correlation_id": "uuid", "causation_id": "uuid|null", "idempotency_key": "text|null",
  "actor": {"user_id": "uuid|null", "label": "text"},
  "payload": { } }
```
Livraison **au moins une fois** : un consommateur doit être idempotent (clé = `id`).

## 4. Catalogue minimal d'événements
`ParcelReceived · ParcelVerified · ParcelStored · ParcelConsolidated · ShipmentCreated ·
ShipmentDispatched · ShipmentArrived · CustomsStarted · CustomsCleared · DeliveryAssigned ·
OutForDelivery · Delivered · ProofOfDeliveryCreated · IncidentCreated` (+ `ParcelCreated`,
`ParcelStatusChanged` pour les cas généraux).

## 5. Erreurs
Codes SQLSTATE personnalisés, stables, traduisibles par l'interface : `LG001` transition non
autorisée · `LG002` objet introuvable · `LG003` droit insuffisant · `LG004` état incompatible
(ex. colis déjà sorti) · `LG005` donnée invalide · `LG006` doublon · `42501` accès refusé.
Le message est destiné aux logs ; l'interface affiche **son propre texte** par code.

## 5 bis. API du portail client (phase 11)
25 fonctions pour le **client**, toutes `public.lg_my_*` ou d'action propre (`lg_save_address`, `lg_request_pickup`, `lg_open_ticket`…). Leur liste exacte, avec le nom et le caractère facultatif de chaque paramètre,
est dans `outils/tests/portail-rpc.json` (écrit et revérifié par `logistique-portail-essai.py`) ; la **forme de chaque réponse** est figée dans `portail-formes.json`. Règles communes : l'identité est `auth.uid()` (jamais un paramètre) ;
un identifiant qui n'est pas au client répond `LG002` comme un identifiant inexistant ; les écritures acceptent une clé d'idempotence **cloisonnée par client** ; plafonds (20 adresses, 5 demandes en attente par nature, 10 tickets ouverts, 5 tickets par jour).
Voir `CUSTOMER-PORTAL.md`.

## 5 ter. API du centre de commande (phase 12)
28 fonctions pour **l'équipe**, toutes `public.lg_cc_*` (liste exacte et paramètres : `outils/tests/centre-rpc.json` ; formes : `centre-formes.json`).
L'identité est `auth.uid()` ; chaque fonction vérifie son droit (`colis.lire`, `clients.lire`, `factures.lire`, direction, `colis.statut` pour
traiter une demande) **avant** de valider ses paramètres. Les listes prennent `p_filters` (objet : `from`, `to`, `country`, `city`,
`warehouse_id`, `status`, `service`, `customer` — tout autre nom est refusé `LG005`), `p_limit` (1 à 200) et `p_offset`, et rendent
`{ total, filters, items, … }`. Les actions renvoient `{ request_id | ticket_id, status, … }`, écrivent une ligne d'audit et émettent un
événement qui porte `customer_id`. Détail : [COMMAND-CENTER.md](COMMAND-CENTER.md).

## 6. Lecture
Listes paginées (`p_limit`, `p_after`), tri stable ; jamais de `select *` sur une table du noyau.
