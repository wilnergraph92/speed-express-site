# ADR 0014 — L'analytique : un schéma séparé, des faits quotidiens tirés des journaux, chaque calcul tracé et vérifiable
**Statut :** Proposée (6 octobre 2026)

## Contexte
La phase 16 demande des rapports quotidiens, hebdomadaires, mensuels, trimestriels et annuels, des indicateurs, la séparation entre le
transactionnel et l'analytique, des agrégats ou vues matérialisées, et des rapports **reproductibles et traçables**. Contraintes : aucune
nouvelle pile sans ADR (pas d'entrepôt de données externe) ; la base reste la source de vérité ; les tables métier ne doivent pas être
ralenties ni modifiées par les rapports. Le noyau a déjà tout ce qu'il faut pour des chiffres reproductibles : ses journaux sont **en ajout
seul** (événements de suivi, historiques de statut, scans, écritures de revenu, paiements, remboursements), protégés par déclencheurs.

## Décision
1. **Deux schémas** : `logistics` (transactionnel, inchangé) et `analytics` (écrit seulement par `analytics.refresh`, lu seulement par la
   façade `public.lg_an_*`, tables et fonctions fermées à tout autre accès). 012 n'ajoute au transactionnel que des index de dates.
2. **Des faits quotidiens**, pas des vues matérialisées : (jour d'Haïti, mesure, dimension, valeur), 22 mesures enregistrées avec leur
   définition (`analytics.metric`). Une vue matérialisée se rafraîchit en bloc et ne garde ni l'historique de ses calculs ni leur empreinte ;
   une table de faits par exécution, si.
3. **Chaque calcul est une exécution** (`analytics.report_run`) : période, auteur (ou « système »), provisoire si elle touche aujourd'hui,
   nombre de lignes, empreinte md5 des faits, état des sources (lignes de chaque journal sur la période), durée. Faits et exécutions en
   **ajout seul**. Le chiffre en vigueur d'un jour est celui de sa dernière exécution.
4. **Les grains au-dessus du jour se calculent à la lecture** en additionnant les jours (semaine ISO, mois, trimestre, année) : aucun agrégat
   stocké ne peut diverger des jours. Les totaux par période et les rapports (taux de livraison, délai moyen, taux de scans refusés, taux
   d'encaissement, comparaison avec la période précédente) sont calculés **par la base** ; l'écran n'additionne rien.
5. **Vérifier** une exécution la recalcule et compare : *reproductible* ; *les sources ont changé* (un rattrapage dans un journal) ; *le
   calcul a changé* (même sources, autre résultat). Un jour jamais calculé est **signalé**, jamais compté zéro.
6. **Droits** : mesures d'activité = `colis.lire`, financières = `factures.lire`, clientèle = `clients.lire` ; recalculer et vérifier = la
   direction. Le recalcul planifié (`ses_an_refresh`, hier et aujourd'hui) n'est ouvert qu'à la clé secrète ; sa planification (pg_cron ou
   le travailleur) est un geste du propriétaire, pas de la migration.
7. Le jour est celui d'**Haïti** (`America/Port-au-Prince`, heure d'été comprise) ; l'argent est en dollars de base (`*_base_usd`), jamais
   dans la devise remise.

## Conséquences
+ un rapport passé se refait à l'identique, et l'on sait dire pourquoi s'il ne se refait pas ;
+ aucun rapport ne touche une table métier en écriture ; la lecture d'un an de jours reste légère (quelques dizaines de lignes par jour) ;
+ une nouvelle mesure = une ligne dans `analytics.metric` et une branche dans `analytics.compute_facts` ; les anciennes exécutions restent ;
− les chiffres d'aujourd'hui sont provisoires jusqu'au calcul suivant ; un rattrapage n'apparaît qu'après un nouveau calcul (voulu : le
  chiffre publié reste celui d'une exécution tracée) ;
− les faits s'accumulent à chaque recalcul (ajout seul) : quelques dizaines de lignes par jour et par calcul ; à purger un jour, par une
  migration explicite si le volume l'exige.

## Alternatives écartées
Vues matérialisées (pas de traçabilité par calcul) ; agrégats mensuels stockés (deux vérités possibles) ; calculs dans le navigateur (règle
du centre : aucun chiffre calculé côté client) ; entrepôt externe (nouvelle pile, données hors de la base).

## Quand la réexaminer
Si la lecture d'une année dépasse quelques secondes ; si un outil de BI externe doit lire ces faits (une réplique en lecture seule, ADR
dédiée) ; si une mesure exige un instantané d'état (stock d'impayés à une date) plutôt qu'un flux d'événements.
