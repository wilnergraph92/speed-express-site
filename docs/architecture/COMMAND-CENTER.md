# Le centre de commande des opérations (phase 12)

> Statut : écrit et éprouvé sur PostgreSQL 16 jetable ; **non appliqué en production**. Décision : [ADR 0010](ADR/0010-centre-de-commande-dans-le-tableau-de-bord.md).

## Ce que c'est

Un onglet **« Centre de commande »** du tableau de bord de l'équipe (`tableau-de-bord.html`). Il s'ouvre sur :

1. **les chiffres du jour** — colis reçus aujourd'hui, en entrepôt, au hub, retenus ; consolidations ouvertes ; expéditions prêtes, en
   transit, en douane ; livraisons du jour, en cours, en retard ; incidents ouverts et graves ; demandes d'enlèvement et de livraison à
   traiter ; tickets ouverts et en attente de l'équipe ; revenu du jour et du mois, impayés par devise, factures en retard ;
2. **la file « à traiter »** — huit genres de tâches, avec leur nombre et depuis quand le plus ancien attend ;
3. **le flux** — chaque expédition active, son transport, son hub d'arrivée, ses colis par statut, ses livraisons et leurs chauffeurs.

Puis **dix-neuf sections**, chacune filtrable et paginée : flux, colis (avec une fiche complète : tout le journal, internes compris), expéditions,
entrepôt, consolidations, transport, chauffeurs, enlèvements, livraisons, douane, incidents, notifications, clients, support, facturation,
paiements, utilisateurs, journal d'audit, réglages — plus un lien vers les rapports par période de la vue d'ensemble.

Chaque chiffre est un **lien** vers la liste qu'il compte, déjà filtrée (`#centre/colis?statut=ON_HOLD`), en gardant les filtres de l'accueil
que cette liste sait appliquer.

## La règle : la base compte, le navigateur dessine

Tout vient de `outils/logistique/009-centre-de-commande.sql`, par la façade `public.lg_cc_*` (28 fonctions). Le navigateur
(`assets/js/ses-centre.js`, `ses-centre-vues.js`) n'additionne rien, ne trie rien, ne déduit aucun retard ni aucun solde.

| Fonction | Droit | Ce qu'elle rend |
|---|---|---|
| `lg_cc_access()` | personnel avec au moins un droit de lecture | les sections ouvertes, le rôle, la date du jour (Haïti) |
| `lg_cc_kpis(filtres)` | idem ; chaque bloc selon son droit | `operations` (15 chiffres), `money`, `support` ; un bloc sans droit vaut `null` |
| `lg_cc_attention()` | idem | la file « à traiter » |
| `lg_cc_flow`, `lg_cc_parcels`, `lg_cc_parcel`, `lg_cc_shipments`, `lg_cc_warehouse`, `lg_cc_consolidations`, `lg_cc_transports`, `lg_cc_drivers`, `lg_cc_pickups`, `lg_cc_deliveries`, `lg_cc_customs`, `lg_cc_incidents`, `lg_cc_notifications` | `colis.lire` | listes et fiches des opérations |
| `lg_cc_customers`, `lg_cc_tickets`, `lg_cc_ticket` | `clients.lire` | clients (le solde seulement avec `factures.lire`), support |
| `lg_cc_invoices`, `lg_cc_payments` | `factures.lire` | factures émises (jamais les brouillons) et leurs totaux, paiements, remboursements, avoirs |
| `lg_cc_users`, `lg_cc_audit`, `lg_cc_settings` | direction (gérant, administrateur) | comptes de l'équipe, journal d'audit, réglages en lecture |
| `lg_cc_review_pickup`, `lg_cc_review_delivery` | `colis.statut` | approuver (crée la mission ou la livraison) ou refuser (message obligatoire) |
| `lg_cc_reply_ticket`, `lg_cc_close_ticket` | `clients.lire` | répondre, fermer |

**Le droit se vérifie AVANT tout le reste** : un client, un visiteur ou un compte sans droit reçoit le même refus (`LG003` / `42501`), même
avec des filtres invalides ou un identifiant réel. Les fonctions internes `logistics.cc_*` ne sont exécutables par personne d'autre que la
façade ; toutes les tables du noyau restent fermées.

### Les filtres communs

`{ from, to, country, city, warehouse_id, status, service, customer }`, validés par la base : un filtre inconnu, une date invalide, une fin
avant le début, un pays hors HT/DO/US, un service inconnu, un texte trop long sont des **erreurs** (`LG005`), jamais un oubli silencieux.
Les recherches (ville, client, utilisateur, auteur d'audit) sont **littérales** : `%` et `_` sont des caractères, pas des jokers.
Un client se reconnaît par son code (sans tenir compte de la casse), son e-mail exact ou un morceau de son nom.

| Filtre | Colis | Expéditions | Consolidations | Demandes | Missions de livraison |
|---|---|---|---|---|---|
| pays | destination | pays du hub d'arrivée | destination | pays de la demande | par leurs colis |
| service | mode du colis | mode | mode | — | par leurs colis |
| entrepôt | entrepôt actuel | si un colis y est | entrepôt | — (exclut les demandes) | par leurs colis |
| ville, client | du colis | si un colis correspond | si un colis correspond | de la demande | par leurs colis |
| période | création | création | ouverture | création / date souhaitée | date prévue |

Dans les **indicateurs**, la période ne s'applique qu'au **revenu de la période** (`revenue_period_usd`, présent seulement si une période est
demandée) : les chiffres « du jour » restent ceux du jour. L'écran le dit.

### Ce que « en retard », « impayée », « aujourd'hui » veulent dire

- **Livraison en retard** : mission non terminée (créée, attribuée, acceptée, commencée) prévue avant aujourd'hui, ou dont la fenêtre de
  passage est dépassée. Une livraison faite n'est jamais en retard.
- **Expédition en retard** : partie ou en transit, dont l'arrivée prévue du transport est passée.
- **Facture impayée** : émise, non annulée, solde > 0 (`logistics.cc_unpaid`, une seule définition). Le nombre compte des **factures**, pas des
  clients (un client en a souvent plusieurs).
- **Aujourd'hui** : l'heure d'Haïti pour l'activité (`logistics.today()`) ; la date du serveur pour le revenu, parce que les écritures
  comptables de la phase 10 sont datées ainsi. La carte du revenu affiche la date comptable utilisée.

## Traiter les demandes des clients

| Action | Effet dans la base | Ce que le client voit |
|---|---|---|
| Approuver un enlèvement | mission d'enlèvement (créneau du matin 8 h–12 h, de l'après-midi 12 h–17 h, heure d'Haïti), demande liée | « planifié », et le message de l'équipe |
| Refuser un enlèvement | message obligatoire (500 caractères au plus) | « refusé » et le message |
| Approuver une livraison | livraison créée depuis le hub choisi (par défaut le premier hub actif), colis passés « affecté à une livraison » par la machine d'états | « planifiée » |
| Refuser une livraison | message obligatoire | « refusée » et le message |
| Répondre / fermer un ticket | message de l'équipe, ticket « répondu » / « fermé » | la réponse, sans l'e-mail de l'agent |

Chaque action : **tout ou rien** (un colis retenu entre-temps fait échouer l'approbation sans rien créer), **une ligne d'audit** au nom de
l'agent, **un événement** (`PickupRequestApproved`, `…Rejected`, `DeliveryRequestApproved`, `…Rejected`, `SupportTicketAnswered`,
`SupportTicketClosedByStaff`) qui porte le client concerné — la phase 13 en fera des notifications. Traiter deux fois est refusé (`LG004`).

## Ce qui ne sort jamais, même pour la direction

Le code de livraison à usage unique et son empreinte, le contenu des notifications (un code peut s'y trouver), le jeton public de suivi
d'un colis, les mots de passe et leurs empreintes, les clés d'idempotence, le chemin de la signature. Le test vérifie chaque réponse.

## Mise en service

1. Passer `001` à `009` dans Supabase > SQL Editor (projet `speed-express-site`), après une sauvegarde vérifiée.
2. Rejouer le rattrapage (`select logistics.backfill_from_legacy();`) et vérifier `logistics.reconcile_with_legacy()` à 0 écart.
3. Passer `centreNoyau: true` dans `assets/js/config.js`, publier.

Retour arrière : `centreNoyau: false`. La migration 009 ne crée aucune table : la retirer, c'est supprimer les fonctions `public.lg_cc_*`,
`logistics.cc_*` et `logistics.today()`.

## Tests

| Fichier | Ce qu'il prouve |
|---|---|
| `outils/tests/logistique-centre-essai.py` (PostgreSQL jetable, ~1 430 vérifications) | matrice des droits (6 rôles × 19 lectures, 4 actions), portes fermées avant toute validation, chaque indicateur et chaque liste recalculés par un second chemin sur les tables, 20 combinaisons de filtres, pagination et plafonds, file « à traiter » (nombre et plus ancien), traitement des demandes (tout ou rien, audit, événements, ce que le client voit), structure (droits d'exécution, chemin de recherche, sécurité par ligne), lecture sans écriture (empreinte de toutes les tables), formes figées |
| mutations (160, hors dépôt) | 160 défauts injectés dans 009, tous détectés |
| `outils/tests/centre-contrat.cjs` | trois implémentations, chaque appel conforme aux signatures réelles, interrupteur et repli, chaque section dessinée sur les réponses réelles sans clé inventée ni texte brut, échappement, formulaire de traitement |
| `outils/tests/centre-textes.cjs` | chaque valeur de la base, chaque colonne, chaque message a son texte et trois traductions ; filtres = statuts de la base |

Les fichiers partagés `outils/tests/centre-{formes,rpc,enums,exemples}.json` sont écrits par le test PostgreSQL (`SES_FORME_ECRIRE=1`) et
relus par les tests du navigateur.
