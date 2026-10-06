# ADR 0007 — Le moteur financier vit dans la base, au centime, avec des factures figées
**Statut :** Proposée (5 octobre 2026)

## Contexte
Aujourd'hui les frais, les totaux et le regroupement des factures sont calculés à **trois endroits** (SQL, site, application) : un écart d'arrondi ou une règle oubliée ici ou là donne une facture fausse,
et rien n'empêche de modifier une facture déjà émise. La phase 10 demande trois devises (USD, DOP, HTG), des tarifs par poids, des remises, des surcharges, des taxes, des avoirs et des remboursements.

## Décision
1. **Le calcul est unique et vit dans PostgreSQL** (`logistics.compute_quote`). Les interfaces n'envoient que des faits ; elles ne calculent jamais un prix, une taxe ni un solde.
2. **Arrondi au centime, ligne par ligne** ; le total est la somme des lignes arrondies.
3. **Une facture émise est figée** : montants, lignes, numéro, client, devise ne changent par aucun chemin (déclencheurs, même quand le drapeau interne est actif). On corrige par **avoir**, **annulation**, **remboursement**.
4. **Ajout seul** pour paiements, avoirs, remboursements, revenus, historique, taux et tranches.
5. **Le statut d'une facture découle de ses montants** (`net dû − net payé`) et ne change que par une transition autorisée.
6. **Un remboursement est plafonné à l'excédent payé** : on ne rembourse pas une facture valable sans avoir d'abord émis un avoir.
7. **Devise de référence : le dollar** ; chaque écriture garde son équivalent à la date de l'écriture. **Pas de triangulation** de devises.
8. **Revenu reconnu à l'émission**, hors taxe. **Un devis = une facture** (un groupage = un devis de plusieurs colis, frais comptés une fois).
9. **Rien n'est inventé** : aucun tarif, aucune taxe, aucun taux n'est posé par la migration (seule la règle des 10 $ de frais l'est). Sans grille, le moteur refuse de calculer.
10. **Les factures héritées ne passent pas par le moteur** tant que le propriétaire n'a pas décidé de leur reprise.

## Conséquences
+ un seul endroit à tester : un **modèle de référence indépendant** refait chaque prix et la base doit l'égaler au centime ;
+ aucune facture ne peut changer en silence ; tout est audité ;
− le site et l'application actuels gardent leur logique de facturation jusqu'à la bascule : **deux calculs coexistent** pendant la transition (la réconciliation les compare) ;
− la direction doit saisir les tarifs avant tout usage.

## Alternatives écartées
Calcul dans une application serveur : nouvelle pile, nouveau risque (ADR 0001) ; calcul dans le navigateur : exactement le défaut à corriger ; taxes incluses dans les prix : ambiguïté d'arrondi ; reconnaissance du revenu à l'encaissement :
masque les créances.

## Quand la réexaminer
Au premier besoin de comptabilité en partie double ou d'un autre pays fiscal ; à la décision de reprise des factures héritées ; si le comptable exige une autre reconnaissance du revenu.
