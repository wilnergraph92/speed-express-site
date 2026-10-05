# Moteur d'événements interne

> Phase 6. Source : `outils/logistique/003-machine-d-etats.sql` ; preuve : `logistique-machine-essai.py`. ADR 0003.
> **Non appliqué en production.**

## 1. Pourquoi
Faire réagir le système (notification, facture, tableau de bord) à ce qui arrive **sans jamais** que cette
réaction puisse bloquer ni corrompre l'opération métier. Le défaut des notifications actuelles (un appel HTTP
dans un déclencheur : si l'envoi échoue, la mise à jour du colis échoue aussi — voir `DATABASE.md` §7.7) est
**supprimé par construction** : l'envoi n'est plus dans la transaction du colis.

## 2. Le circuit
```
transition_parcel ──(même transaction)──▶ domain_event ──▶ event_delivery (une ligne par abonné) ──▶ abonné
        │                                  (ajout seul)        PENDING → IN_PROGRESS → DELIVERED
        ├─▶ tracking_event                                            ↘ FAILED (relance, attente ×2) ↘ DEAD → dead_letter
        └─▶ audit_log                                                                       (résolue à la main)
```

## 3. Garanties (toutes éprouvées)
| Garantie | Mécanisme |
|---|---|
| **Persistance** | l'événement est écrit **dans la même transaction** que le changement d'état : si la transaction échoue, il n'existe pas ; si elle réussit, il existe. Ajout seul (`LG004` sinon) |
| **Registre fermé** | un type d'événement inconnu est refusé (clé étrangère sur `event_type`) |
| **Idempotence** | `command_log` : la même clé rend le résultat d'origine ; une clé réutilisée pour une autre demande est refusée (`LG006`) ; une commande **en échec ne consomme pas** sa clé |
| **Corrélation** | `correlation_id` identique sur le suivi, l'audit et l'événement ; généré si absent ; `causation_id` prévu pour les chaînes |
| **Fan-out atomique** | un déclencheur crée la livraison de **chaque abonné actif** dans la même transaction : un événement qui existe a toujours ses livraisons |
| **Pas de doublon** | `unique (événement, abonné)` : un abonné ne reçoit jamais deux fois le même événement |
| **Relance** | à l'échec : `FAILED`, compteur +1, **attente × 2 à chaque essai** (`backoff_seconds × 2^(essai−1)`) ; pas de nouvel essai avant l'heure |
| **File des échecs** | au maximum d'essais : `DEAD` + ligne dans `dead_letter` (jamais supprimée) ; `requeue_dead_letter` la remet en circulation et la marque résolue avec une note |
| **Isolation** | chaque abonné interne s'exécute dans **sa propre sous-transaction** : sa panne n'arrête ni les autres ni le colis |
| **Livraison au moins une fois** | les abonnés sont idempotents (clé = `event_id`) |

## 4. Deux sortes d'abonnés
- **Interne** (`kind = 'internal'`) : une fonction SQL `f(ev domain_event)` appelée par `dispatch_events()`. Exemple fourni : `notification_planner` planifie une notification pour le client **qui a l'application**.
- **Externe** (`kind = 'external'`) : un travailleur (Edge Function) qui **réclame** (`claim_deliveries`, avec un **bail** : s'il tombe, l'événement revient), traite, puis `ack_delivery` ou `nack_delivery`. Rien d'autre n'est exposé : ces fonctions ne sont accordées qu'à `service_role`, **côté serveur seulement**.

## 5. Mise en service (à décider, après l'étape 2 de la stratégie)
1. Planifier `select logistics.dispatch_events();` toutes les minutes (extension `pg_cron` de Supabase, **à confirmer sur l'offre**) ou par une Edge Function planifiée.
2. L'envoi réel des notifications (Expo) est un abonné **externe** qui lit `notification` : à écrire quand la version de développement de l'application existera.
3. **Surveillance** : `logistics.event_health` donne, par abonné, les événements en attente, en échec, **morts**, et l'âge du plus ancien en attente. Alerte à prévoir : `dead > 0` ou `oldest_waiting_seconds` élevé.

## 6. Catalogue
26 types, dont les 14 demandés : `ParcelReceived, ParcelVerified, ParcelStored, ParcelConsolidated, ShipmentCreated, ShipmentDispatched,
ShipmentArrived, CustomsStarted, CustomsCleared, DeliveryAssigned, OutForDelivery, Delivered, ProofOfDeliveryCreated, IncidentCreated`.
Les événements d'expédition, de preuve de livraison et d'incident sont **déclarés** ici ; leurs producteurs arrivent aux phases 8 et 9.
Enveloppe : `INTEGRATION-CONTRACT.md` §3.

## 7. Limites assumées
- Pas de **messages différés précis** ni de **débit élevé** : seuils de réexamen dans `TARGET-ARCHITECTURE.md` §4.
- Le répartiteur interne est **déclenché**, pas continu : sans planification, les abonnés internes attendent.
- Un abonné externe doit **gérer sa propre idempotence** (la livraison est « au moins une fois »).
