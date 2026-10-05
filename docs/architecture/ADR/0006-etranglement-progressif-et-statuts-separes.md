# ADR 0006 — Migration par étranglement ; Colis ≠ Expédition
**Statut :** Proposée (5 octobre 2026)

## Contexte
Le système vit : des clients, des colis et des factures réels existent, et le site et l'application
les lisent. Il ne s'arrête pas pour migrer. Par ailleurs, le modèle actuel confond le colis (un objet
d'un client) et le transport (un voyage qui en emporte beaucoup).

## Décision
1. **Étranglement progressif** en six étapes réversibles (`MIGRATION-STRATEGY.md`) : ajouter, remplir, comparer, double-écrire, basculer, retirer. **Aucune table existante n'est supprimée ni modifiée avant l'étape 6.**
2. **Rattrapage idempotent** : rejouable à volonté, sans doublon, avec **fonction de comparaison** (`reconcile`) qui liste tout écart.
3. **Colis ≠ Expédition** : `parcel` a **sa** machine d'états (cycle de vie de l'objet) ; `shipment` a **la sienne** (cycle du voyage). Un client a plusieurs colis ; plusieurs colis appartiennent à une consolidation ; une consolidation entre dans une expédition ; une expédition voyage par un transport et arrive à un hub ; les colis sont ensuite affectés à des livraisons. L'expédition ne change jamais le statut d'un colis directement : elle émet un événement, que le cycle de vie du colis traduit en transition.
4. **Rien d'inventé** : la migration ne fabrique ni paiement, ni succursale, ni position.

## Conséquences
+ aucun arrêt, aucun risque pour les données existantes, retour arrière à chaque étape ;
− une période de cohabitation (deux modèles) à surveiller par `reconcile`.

## Alternatives écartées
Migration d'un coup (« big bang ») : un échec arrête l'activité ; fusionner colis et expédition : interdit de modéliser le groupage, l'essentiel du métier.

## Quand la réexaminer
À chaque entrée d'étape (critères dans la stratégie).
