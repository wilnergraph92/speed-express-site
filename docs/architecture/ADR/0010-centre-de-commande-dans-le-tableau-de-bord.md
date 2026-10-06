# ADR 0010 — Le centre de commande est un onglet du tableau de bord, nourri par la base seule, sans démonstration
**Statut :** Proposée (6 octobre 2026)

## Contexte
L'équipe pilote aujourd'hui l'activité depuis le tableau de bord d'avant (`tableau-de-bord.html`), qui lit l'ancien schéma. La phase 12
demande un **centre de commande** : chiffres du jour, file « à traiter », vue expédition → transport → hub → livraison → chauffeur, dix-neuf
sections filtrables, et le traitement des demandes des clients (enlèvement, livraison, support). Exigence ferme : **aucune statistique
critique calculée côté navigateur**. Le noyau n'est pas appliqué en production (migrations 001 à 009 en attente).

## Décision
1. **Un onglet de plus, pas une page de plus** : « Centre de commande » s'ajoute au tableau de bord existant (même connexion, même contrôle
   d'accès `accesTableauDeBord`, mêmes styles). Les onglets d'avant restent : ils portent encore les écritures sur l'ancien schéma.
2. **Toute donnée vient de `public.lg_cc_*`** (`outils/logistique/009-centre-de-commande.sql`) : la base compte, filtre, trie, pagine
   (200 lignes au plus) et contrôle le droit de **chaque** fonction **avant** de valider ses paramètres. L'acteur est toujours `auth.uid()`.
3. **Les sections suivent les droits que la base annonce** (`lg_cc_access`) : `colis.lire` ouvre les opérations, `clients.lire` les clients
   et le support, `factures.lire` la facturation, la direction (gérant, administrateur) les utilisateurs, l'audit et les réglages.
4. **Un interrupteur** (`centreNoyau` dans `config.js`, éteint) et **un repli** : l'onglet n'apparaît que si la base répond et que le compte
   a un droit de lecture. Sinon, rien ne change.
5. **Pas de mode démonstration** — deuxième exception assumée à la règle « toute méthode existe dans les deux implémentations », pour la
   même raison que `admin.dashboard*` : ces chiffres ne montrent que des données réelles. Les trois implémentations gardent les mêmes noms de
   méthodes (celles de la démonstration répondent « fermé »), vérifiés par `outils/tests/centre-contrat.cjs`.
6. **Traiter une demande est une action de la base** (`lg_cc_review_pickup`, `lg_cc_review_delivery`, `lg_cc_reply_ticket`,
   `lg_cc_close_ticket`) : tout ou rien, une trace d'audit et un événement par action, le message du refus obligatoire et lu par le client.

## Conséquences
+ publier le site avant les migrations est sans danger ; retour arrière = interrupteur à `false` ;
+ un chiffre faux ne peut venir que de la base, où il est recalculé par un second chemin à chaque essai (`logistique-centre-essai.py`) ;
+ chaque chiffre renvoie à sa liste filtrée (`#centre/colis?statut=ON_HOLD`) : le bouton « précédent » fonctionne ;
− impossible à essayer en local sans base : un serveur d'essai nourri par les réponses réelles de la base de test (`centre-exemples.json`) sert
  aux vérifications visuelles ;
− « aujourd'hui » s'entend à l'heure d'Haïti pour l'activité, mais à la date du serveur pour le revenu (les écritures comptables de la
  phase 10 sont datées ainsi) : la carte « revenu du jour » affiche la date comptable utilisée.

## Alternatives écartées
Une page séparée : une connexion et un contrôle d'accès de plus à maintenir, et vingt-neuf pages à générer ; calculer les indicateurs dans le
navigateur à partir des listes : interdit par la phase et faux dès la deuxième page ; une démonstration aux chiffres inventés : trompeuse.

## Quand la réexaminer
À la double écriture (les onglets d'avant pourront céder la place) ; à la phase 16 (rapports) ; si un jour une démonstration fondée sur des
données de test réalistes devenait utile à la formation.
