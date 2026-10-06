# Portail client web (phase 11)

> Sources : `outils/logistique/008-portail-client.sql` (l'API), `assets/js/ses-portail*.js` (l'interface), `outils/portail-textes.py` (les textes).
> Preuves : `logistique-portail-essai.py` (1 071 vérifications sur PostgreSQL, 58 altérations volontaires toutes détectées), `portail-contrat.cjs` (81), `portail-textes.cjs` (269).
> **Non appliqué en production** : l'interrupteur `portailNoyau` de `config.js` est éteint, et la migration 008 n'est pas passée.

## 1. Ce que c'est
Le site devient l'interface officielle du noyau logistique, **sans toucher au site public** (accueil, services, blog, suivi public…). L'espace client passe de trois onglets
(colis, factures, compte) à **quatorze sections** :

| Section | Ce que le client y fait | Fonction de la base |
|---|---|---|
| Tableau de bord | chiffres du jour, prochaines livraisons, derniers événements, actions rapides | `lg_my_dashboard` |
| Mes colis | liste filtrée (étape, recherche), pagination, fiche détaillée | `lg_my_parcels`, `lg_my_parcel` |
| Suivi | un numéro → le **vrai journal** du colis (`TrackingEvent`), du plus récent au plus ancien | `lg_my_parcel` |
| Mes expéditions | les vols et traversées qui portent **ses** colis | `lg_my_shipments` |
| Consolidations | les regroupements où figurent ses colis | `lg_my_consolidations` |
| Factures | liste, solde par devise, détail ligne par ligne, impression | `lg_my_invoices`, `lg_my_balance` |
| Paiements | paiements reçus, avoirs, remboursements | `lg_my_payments` |
| Documents | factures, avoirs, devis, reçus de livraison | `lg_my_documents` |
| Adresses | carnet d'adresses (20 au plus), adresse par défaut | `lg_my_addresses`, `lg_save_address`, `lg_delete_address` |
| Enlèvement | **demande** d'enlèvement, suivi des demandes, annulation | `lg_my_pickups`, `lg_request_pickup`, `lg_cancel_pickup_request` |
| Livraison | **demande** de livraison de ses colis au hub, suivi, preuve de remise | `lg_my_deliveries`, `lg_request_delivery`, `lg_cancel_delivery_request` |
| Notifications | liste, lues / non lues | `lg_my_notifications`, `lg_mark_notifications_read` |
| Support | tickets, fil de conversation, réponse, fermeture | `lg_my_tickets`, `lg_my_ticket`, `lg_open_ticket`, `lg_reply_ticket`, `lg_close_my_ticket` |
| Profil | le panneau « Mon compte » d'avant : informations, mot de passe | (ancien schéma, inchangé) |

Une **demande** n'est pas une commande : l'équipe la confirme (phase 12 : le tableau de commande). Tant qu'elle ne l'a pas fait, elle reste « demandée » et le client peut l'annuler.

## 2. Règle d'or : aucune règle métier dans le navigateur
Les étapes (`registered … delivered`), les statuts, les soldes, les droits, les plafonds viennent **de la base**. Le site les montre ; il ne les calcule pas. Un client qui modifierait la page
ne gagnerait aucun pouvoir : le serveur refuserait. La correspondance statut interne → étape visible par le client (`logistics.customer_stage`) vit **une seule fois**, dans la base.

## 3. Ce qu'un client ne peut jamais faire (éprouvé, pas supposé)
| Tentative | Résultat |
|---|---|
| changer son rôle ou ses droits (`clients.role`, `droits`), son code, son e-mail | refusé ; l'ancien schéma est **identique octet pour octet** après dix-huit attaques |
| changer le statut d'un colis, par n'importe quelle porte (`UPDATE`, `lg_transition_parcel`, `lg_scan_parcel`…) | refusé (`42501` ou `LG003`) |
| modifier une facture finalisée, inventer un paiement | refusé : aucune table du noyau n'est accessible, et aucune fonction du personnel ne répond |
| **falsifier un événement** (suivi, domaine, audit) | refusé : aucun accès direct ; les événements ne s'écrivent que dans une transaction du noyau |
| appeler une fonction du personnel | **les 74 fonctions du personnel sont appelées une à une par un client** : toutes refusent |
| lire le colis, la facture, le ticket, l'adresse d'un autre | « introuvable », **exactement** comme un identifiant inexistant : on ne peut pas deviner un numéro |
| voir l'auteur d'un message, un emplacement interne, un motif, un brouillon | jamais : la **forme de chaque réponse est figée** dans `portail-formes.json` ; une clé de plus fait échouer le test |

Deux fonctions du personnel validaient ou verrouillaient **avant** de contrôler le droit (`lg_scan_parcel`, `lg_transition_parcel`). Rien ne fuyait et rien n'était écrit, mais l'épreuve « un client les appelle »
l'a révélé : un contrôle « personnel actif » (`logistics.require_staff`) passe maintenant **en tout premier** (migrations 003 et 004).

## 4. Le suivi : le vrai journal
Chaque événement du journal du colis (`tracking_event`) filtré par `event_type.customer_visible` : les événements internes (rangement, mouvement, inspection) ne sont jamais montrés. Pour chaque événement le client reçoit
la date, l'événement, l'étape, le **lieu** (nom de la succursale — jamais le code d'emplacement) et, pour les colis hérités seulement, la note qu'il lisait déjà. **Jamais** l'auteur, le motif, le GPS.
Un colis mis en attente se montre « en attente » ; **pourquoi**, c'est l'affaire de l'équipe.

## 5. L'interrupteur et le repli : ne rien casser en publiant avant les migrations
`config.js` : `portailNoyau: false` (défaut). Le portail ne s'ouvre que si **trois** conditions tiennent, vérifiées à chaque ouverture (`SES_API.portail.disponible`) :
1. l'interrupteur est allumé ;
2. la base répond et la migration 008 est passée (sinon `noyau-absent`) ;
3. le noyau est **à jour pour ce client** (`in_sync`) : chacun de ses colis et chacune de ses factures de l'ancien schéma y a son pendant à jour.

Sinon, l'espace client d'avant s'affiche, tel quel. Publier le site avant les migrations, ou allumer l'interrupteur trop tôt, est donc **sans danger** : il y a un repli sûr.

### Pour allumer le portail (à vous de décider)
1. sauvegarde vérifiée (`docs/backup/`) ; projet **speed-express-site** ouvert dans Supabase ;
2. coller `outils/logistique/001` à `008` dans l'ordre (déjà éprouvées sur PostgreSQL jetable) ;
3. `select logistics.backfill_from_legacy();` puis `select * from logistics.reconcile_with_legacy();` (doit rendre 0 ligne) ;
4. **tant que le site et l'application écrivent encore dans l'ancien schéma, le noyau prend du retard** : rejouer le rattrapage régulièrement (ou passer à l'étape 3 de `MIGRATION-STRATEGY.md`, la double écriture). Un client dont le noyau est en retard retombe seul sur l'espace d'avant ;
5. mettre `portailNoyau: true` dans `config.js`, publier.
Retour arrière : remettre `false`.

## 6. Interface
- **Navigation** : une adresse par section et par fiche (`#/colis/SES-10001-HT`), donc « précédent », favoris et liens fonctionnent. Colonne à gauche sur ordinateur ; barre défilante sur téléphone, l'onglet ouvert reste visible.
- **Accessibilité** : onglets au clavier (flèches, Origine/Fin), titre de section qui reçoit le focus à l'arrivée, états annoncés (`role="status"` / `role="alert"`), champs reliés à leurs libellés, aide et erreurs reliées, la **couleur ne porte jamais seule** un état (le texte le dit), mouvement réduit respecté, tableaux qui deviennent des fiches sur petit écran.
- **États** : chaque écran a son chargement, son vide et son erreur (avec « Réessayer »). Une réponse tardive d'un chargement abandonné est ignorée.
- **Quatre langues** : tous les textes sont dans `outils/portail-textes.py` (français, anglais, espagnol, créole) ; le test `portail-textes.cjs` exige un texte et trois traductions pour **chaque** valeur que la base peut renvoyer (étapes, événements, statuts, modes de paiement…).
- **Aucun HTML venu du serveur n'est interprété** : tout est échappé (éprouvé avec des données hostiles sur toutes les sections).
- **Envoi de formulaire** : une clé d'idempotence est jointe ; rejouée après une panne réseau, elle empêche la base de créer deux demandes.
- **Dates** : un jour sans heure (`2026-10-06`) s'affiche **ce jour-là** à Port-au-Prince, Saint-Domingue et Miami (le navigateur le lisait en UTC et l'affichait la veille — défaut corrigé aussi pour l'ancien espace).

## 7. Mode démonstration
Hors ligne (fichier ouvert, `localhost`, sans clé Supabase), les quatorze sections fonctionnent : colis et factures de démonstration, adresses, demandes et tickets **enregistrés pour de bon dans le navigateur**. Il n'y a pas de personnel pour traiter une demande ni répondre à un ticket :
elles restent « en attente » — la démonstration n'invente rien. Expéditions, consolidations, notifications : vides. Le test de contrat compare la **forme** de chaque réponse de la démonstration à celle de la vraie base.

## 8. Limites assumées
- **Profil** : modifie toujours l'**ancien schéma** (colonnes autorisées, inchangées). Le profil du noyau est recopié par le rattrapage.
- **Paiement en ligne** : absent. Le portail montre le solde et explique comment régler (agence, virement, mobile money) ; l'encaissement reste saisi par l'équipe.
- **Temps réel** : la liste se rafraîchit quand l'onglet du navigateur redevient visible ; le temps réel arrive avec la phase 13.
- **Notifications** : la section lit les notifications « in_app » ; leur production (modèles, canaux, relances) est la phase 13. D'ici là, la liste est vide.
- **Documents** : ce sont des vues des enregistrements (facture, avoir, devis, reçu), imprimables par le navigateur ; aucun fichier PDF n'est stocké.
- **Les colis hérités** gardent leur historique d'avant : le suivi y montre l'étape et le lieu, pas d'événement de noyau.
