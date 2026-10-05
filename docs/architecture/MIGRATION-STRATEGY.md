# Stratégie de migration : de `public` au noyau `logistics`

**Principe : on étrangle l'ancien, on ne le remplace pas d'un coup.** Chaque étape est
réversible, testée sur PostgreSQL jetable, et **ne s'applique en production qu'après
sauvegarde vérifiée et accord du propriétaire.** Aucune table existante n'est supprimée ni
modifiée avant l'étape 6.

| Étape | Contenu | Effet sur le site et les applications | Retour arrière |
|---|---|---|---|
| **0** — aujourd'hui | seul `public` existe | — | — |
| **1** — *phase 5* | schéma `logistics` **ajouté** (vide, fermé à l'API) + **rattrapage** idempotent depuis `public` + comparaison automatique (`reconcile`) | **aucun** : personne ne lit encore le nouveau schéma | `drop schema logistics cascade` (rien d'autre n'en dépend) |
| **2** — *phase 6* | machine d'états, événements, audit sur le nouveau schéma, **écrits seulement par la façade** | aucun pour les clients actuels ; essais en parallèle | idem |
| **3** | **double écriture** : un déclencheur sur `colis`, `colis_historique`, `factures`, `clients`, `appareils` recopie vers `logistics` (jamais l'inverse) | invisible ; le risque d'un déclencheur défaillant est neutralisé par essais, journal d'écarts et possibilité de le retirer seul | retirer les déclencheurs ; relancer le rattrapage |
| **4** | l'écriture des **nouveaux** colis passe par la façade ; l'ancien schéma est alimenté par un déclencheur inverse | les interfaces migrent une à une | repasser l'écriture sur `public` |
| **5** | les interfaces lisent `logistics` ; `public.colis`… deviennent des **vues de compatibilité** | l'ancien site continue de fonctionner | rétablir les tables d'origine depuis la sauvegarde |
| **6** | retrait des anciennes tables | — | sauvegarde chiffrée de référence + accord écrit |

**Critères d'entrée de chaque étape** : (1) sauvegarde de la veille `verification: complete` ; (2) tests verts, dont `reconcile` sans écart ; (3) plan de retour arrière écrit ; (4) accord du propriétaire pour la production.

**Cohabitation des statuts** : le rattrapage traduit les cinq statuts actuels vers la machine d'états
(`confirme→CREATED`, `expedie→IN_TRANSIT`, `disponible→AT_DESTINATION_HUB`, `livre→DELIVERED`,
`action→ON_HOLD`) et **conserve le statut d'origine** à côté, pour ne jamais perdre l'information.

**Ce que la migration n'invente pas** : aucun paiement, aucune succursale, aucun entrepôt, aucune
position n'est fabriqué à partir de rien ; ce qui n'a jamais été enregistré reste vide.
