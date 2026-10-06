# ADR 0009 — Le portail client lit le noyau derrière un interrupteur, avec repli sûr
**Statut :** Proposée (5 octobre 2026)

## Contexte
Le site en ligne lit l'ancien schéma (clients, colis, factures). Le noyau logistique est prêt et éprouvé mais **pas appliqué** en production, et tant que le site écrit dans l'ancien schéma le noyau prend du retard
(`MIGRATION-STRATEGY.md`, §7). Le portail client doit devenir l'interface officielle du noyau **sans** qu'un client voie un jour des données périmées ni que la publication du site casse quoi que ce soit.

## Décision
1. **Un interrupteur dans `config.js`** (`portailNoyau`, éteint par défaut) décide si le portail est même tenté.
2. **Un repli automatique** : même allumé, le portail ne s'ouvre que si la base répond, si la migration est passée, **et** si le noyau est à jour pour CE client (`in_sync`, calculé par la base en comparant statuts et soldes de l'ancien schéma). Au moindre doute : l'espace d'avant.
3. **La base est la seule source de règles** : étapes visibles, soldes, droits, plafonds. Le site ne calcule rien ; un client qui modifierait la page ne gagne aucun pouvoir.
4. **Une couche de données à trois implémentations** (en ligne, démonstration, fermé) qui tiennent le **même contrat**, vérifié contre les signatures et les formes de réponse de la vraie base.
5. **Les réponses sont minimales et figées** : une clé de plus est un changement à relire, pas un détail.
6. **Les demandes du client ne sont pas des ordres** : enlèvement et livraison sont déposés « demandés » ; le personnel les approuve (phase 12).

## Conséquences
+ publier le site avant (ou sans) les migrations est sans danger ; retour arrière = remettre l'interrupteur à `false` ;
+ un client dont le noyau est en retard ne voit jamais de données périmées ;
− deux interfaces coexistent jusqu'à la bascule complète (l'espace d'avant et le portail) ;
− tant que la double écriture n'est pas posée, le rattrapage doit être rejoué pour que le portail s'ouvre.

## Alternatives écartées
Remplacer l'espace client d'un coup : casse la production si les migrations ne sont pas passées ; détecter le noyau seul, sans interrupteur : une migration passée trop tôt exposerait un portail incomplet ; calculer les soldes dans le navigateur : exactement ce que le noyau veut éviter.

## Quand la réexaminer
À la mise en place de la double écriture (le repli `in_sync` deviendra rare) ; au retrait des anciennes tables (étape 6).
