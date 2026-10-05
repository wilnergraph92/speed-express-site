# ADR 0003 — Événements : boîte d'envoi transactionnelle, relances, file des échecs
**Statut :** Proposée (5 octobre 2026)

## Contexte
Chaque opération doit produire un événement, une trace d'audit et parfois une notification, **sans
jamais perdre ni dupliquer** (cf. le défaut des notifications : un envoi qui échoue ne doit pas bloquer
une mise à jour de colis).

## Décision
1. **Boîte d'envoi** : la table `logistics.domain_event` reçoit l'événement **dans la même transaction** que le changement d'état. Si la transaction échoue, l'événement n'existe pas ; si elle réussit, il existe.
2. **Idempotence** : clé `idempotency_key` unique ; rejouer une commande renvoie le résultat d'origine.
3. **Corrélation** : `correlation_id` sur chaque événement et trace ; `causation_id` pour la chaîne.
4. **Distribution** : un répartiteur **réclame** les événements en attente (`FOR UPDATE SKIP LOCKED`), appelle les abonnés enregistrés, compte les tentatives, **temporise** (attente croissante), puis place en **file des échecs** (`dead_letter`) après le maximum de tentatives. Aucun événement n'est supprimé.
5. Livraison **au moins une fois** : les abonnés sont idempotents.
6. **Un abonné défaillant ne bloque jamais** l'opération métier ni les autres abonnés.

## Conséquences
+ exact (jamais d'événement fantôme), observable (profondeur de file, échecs), sans composant à ajouter ;
− un débit très élevé exigerait une vraie file (seuil dans `TARGET-ARCHITECTURE.md` §4).

## Alternatives écartées
Appels HTTP depuis des déclencheurs (c'est ce qui a produit le défaut des notifications) ; bus externe (Kafka, RabbitMQ) : surdimensionné.

## Quand la réexaminer
Au-delà de ~50 événements/s soutenus, ou si des messages **différés** précis deviennent nécessaires.
