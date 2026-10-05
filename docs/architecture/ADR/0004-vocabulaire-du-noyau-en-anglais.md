# ADR 0004 — Noyau nommé en anglais, libellés en quatre langues
**Statut :** Proposée (5 octobre 2026)

## Contexte
Le projet nomme ses tables et fonctions en français (`clients`, `colis`) et affiche quatre langues. Le
cahier des charges du noyau emploie le vocabulaire logistique anglais (Parcel, Shipment, TrackingEvent…),
et des applications, des partenaires et des outils futurs le liront.

## Décision
- Tables, colonnes, fonctions et événements du **schéma `logistics`** : **anglais**, `snake_case`, singulier (`parcel`, `tracking_event`).
- **Commentaires SQL et documentation en français** (convention du projet).
- **Libellés affichés** : dictionnaires existants (fr, en, es, ht) ; les codes de statut sont stables (`IN_TRANSIT`), jamais traduits en base.
- Les **anciennes tables gardent leurs noms**. Le tableau de correspondance est `DATA-MIGRATION-MAP.md`.

## Conséquences
+ un langage unique avec les partenaires et les futures applications ; codes de statut indépendants de la langue ;
− deux vocabulaires cohabitent pendant la migration (limité par la table de correspondance).

## Alternatives écartées
Tout en français : illisible pour des intégrations ; tout renommer : détruit la compatibilité.

## Quand la réexaminer
À la fin de la migration (étape 6), pour décider s'il faut unifier.
