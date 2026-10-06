# Machine d'états du colis

> Phase 6. Source : `outils/logistique/003-machine-d-etats.sql` ; preuve : `outils/tests/logistique-machine-essai.py`
> (100 vérifications, dont les **400 paires** de statuts exercées une à une). **Non appliquée en production.**
> Ne pas l'utiliser sur les colis réels avant l'étape 4 de `MIGRATION-STRATEGY.md` : l'ancien tableau de bord écrit encore l'ancien statut.

## 1. Principe
**Un statut ne change jamais arbitrairement.** Un seul chemin existe : `logistics.transition_parcel()`. Tout
`UPDATE` direct du statut d'un colis est refusé (`LG001`). La machine est **en données** (`parcel_transition`) :
tout ce qui n'y figure pas est interdit.

## 2. Les 20 statuts
Flux nominal (15) : `CREATED → RECEIVED → VERIFIED → STORED → CONSOLIDATION_PENDING → CONSOLIDATED → READY_FOR_EXPORT →
IN_TRANSIT → ARRIVED → CUSTOMS_PROCESSING → CUSTOMS_CLEARED → AT_DESTINATION_HUB → DELIVERY_ASSIGNED → OUT_FOR_DELIVERY → DELIVERED`.
Exceptions (5) : `ON_HOLD`, `CANCELLED`, `DAMAGED`, `LOST`, `RETURNED`. **Terminaux** (rien n'en sort) : `DELIVERED`, `CANCELLED`, `LOST`, `RETURNED`.

## 3. Les 86 transitions autorisées (sur 400 paires)
> Les phases suivantes en ajoutent trois, **sans toucher aux autres** : `READY_FOR_EXPORT → CONSOLIDATED` (phase 8, rouvrir une expédition), puis
> `OUT_FOR_DELIVERY → AT_DESTINATION_HUB` et `DELIVERY_ASSIGNED → AT_DESTINATION_HUB` (phase 9, livraison manquée ou annulée : le colis revient au hub).
> **89 transitions au total** dans une base où les migrations 001 à 006 sont passées. Les 400 paires de la phase 6 s'éprouvent sur 003 seule.
| Famille | Transitions | Qui | Condition |
|---|---|---|---|
| **Flux** | chaque statut vers le suivant (14) | opérateur (`colis.statut`) ; le **système** pour 9 d'entre elles (consolidation → hub) | entrepôt pour `RECEIVED`, `VERIFIED` ; emplacement pour `STORED` ; **client** obligatoire dès `CONSOLIDATION_PENDING` |
| **Sortir d'une consolidation** | `CONSOLIDATED → CONSOLIDATION_PENDING`, `CONSOLIDATION_PENDING → STORED` | opérateur | emplacement pour `STORED` |
| **Mise en attente** | tout statut du flux (14) `→ ON_HOLD` ; `DAMAGED → ON_HOLD` | opérateur ; direction pour `DAMAGED → ON_HOLD` | **motif obligatoire** |
| **Reprise** | `ON_HOLD →` chaque statut du flux (14) | **direction** | **uniquement vers le statut d'avant l'attente** |
| **Dommage** | tout statut après `CREATED` (13) `→ DAMAGED` ; `ON_HOLD → DAMAGED` | opérateur (signaler) ; direction depuis `ON_HOLD` | motif |
| **Perte** | tout statut après `CREATED` (13), `ON_HOLD`, `DAMAGED` `→ LOST` | **direction** | motif |
| **Annulation** | `CREATED … CONSOLIDATION_PENDING`, `ON_HOLD`, `DAMAGED → CANCELLED` | **direction** | motif ; impossible une fois prêt pour l'export |
| **Retour** | `AT_DESTINATION_HUB`, `DELIVERY_ASSIGNED`, `OUT_FOR_DELIVERY`, `ON_HOLD`, `DAMAGED → RETURNED` | **direction** | motif |

Règle de partage : **tout opérateur peut signaler** (attente, dommage) ; **la direction décide** (reprise, annulation, perte, retour).
« Direction » = gérant ou administrateur ; « opérateur » = employé ayant le droit `colis.statut` (le droit existant), gérant, administrateur.

## 4. Ce que fait une transition (dans UNE transaction)
1. **Idempotence** : même clé = même résultat, rien n'est refait (`replayed: true`).
2. Verrouille le colis. 3. Identifie l'acteur (membre actif du personnel, ou « system »). 4. Vérifie que la transition existe.
5. Vérifie le **droit** (`colis.statut` ou `direction`). 6. Vérifie les **conditions** (motif, entrepôt, emplacement, client, reprise).
7. Met à jour le colis (statut, position, entrepôt) **et passe l'autorité du statut au noyau**.
8. Écrit **un événement de suivi** (`tracking_event`), **une trace d'audit** (avant/après) et **un événement de domaine** (`domain_event`), avec le **même `correlation_id`**.
Si une étape échoue, **rien n'est conservé** (prouvé en simulant une panne à la dernière écriture).

## 5. Qui peut l'appeler
- **Le personnel connecté**, par `public.lg_transition_parcel(...)`. **L'acteur est toujours le compte connecté** : la fonction n'a pas de paramètre « acteur ».
- **Le système interne** (`p_actor_user_id` nul, source `system`), seulement pour les transitions marquées `allow_system` (celles que déclenche une expédition ou la douane, phase 8).
- Un **client**, un compte **désactivé**, un employé **sans le droit**, un visiteur **anonyme** : refusés (`LG003`, `42501`).

## 6. Codes d'erreur (stables, `INTEGRATION-CONTRACT.md` §5)
`LG001` transition non autorisée · `LG002` introuvable · `LG003` droit insuffisant · `LG004` état incompatible / ajout seul · `LG005` donnée manquante (motif, entrepôt, emplacement, client) · `LG006` clé d'idempotence réutilisée pour une autre demande.

## 7. Cohabitation avec l'ancien schéma
`parcel.status_authority` vaut `legacy` (le rattrapage recopie le statut de l'ancien schéma) puis passe à `core` à la **première transition** ;
le rattrapage ne touche plus au statut ensuite, mais continue de suivre les autres champs. L'autorité ne revient **jamais** à l'ancien schéma.
Un colis **natif** naît obligatoirement en `CREATED`.

## 8. Conditions particulières
- **Colis sans client** : il peut être **reçu**, vérifié, rangé ; il ne peut pas être consolidé ni expédié (`LG005`).
- **Reprise** : si le statut d'avant l'attente est inconnu (colis hérité dont le premier événement est l'attente), la direction choisit ; sinon il est imposé.
- **Preuve de livraison** (phase 9) : un colis sous l'autorité du noyau ne passe `DELIVERED` **qu'avec une preuve** (`logistics.proof_of_delivery`). Le déclencheur
  de la base le garantit pour tout chemin ; seule la direction déroge (`deliver_without_proof`, motif obligatoire, tracé). Un colis encore sous l'autorité de l'ancien schéma n'est pas concerné.
- **Droit « livraison »** (phase 9) : `DELIVERY_ASSIGNED → OUT_FOR_DELIVERY`, `OUT_FOR_DELIVERY → DELIVERED` et `OUT_FOR_DELIVERY → AT_DESTINATION_HUB` exigent ce droit étroit.
  Un employé qui a `colis.statut` et la direction l'ont ; **un chauffeur actif l'a seulement pendant qu'une fonction de mission s'exécute** (jamais par `lg_transition_parcel`). Voir `LAST-MILE.md`.
