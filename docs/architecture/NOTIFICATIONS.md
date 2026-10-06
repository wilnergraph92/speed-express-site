# Notifications et temps réel (phase 13)

> Statut : écrit et éprouvé sur PostgreSQL 16 jetable ; **non appliqué en production** ; travailleur **non installé**.
> Source : `outils/logistique/010-notifications.sql`, `scripts/notifications/envoyer.mjs`. Décision : [ADR 0011](ADR/0011-notifications-moteur-dans-la-base-travailleur-planifie.md).

## 1. Le circuit

```
opération métier ──(même transaction)──▶ domain_event ──┬─▶ event_delivery ──▶ notification_engine (abonné interne, hors transaction)
                                                         │                         │  règle × modèle × préférence × canal × destinataire
                                                         │                         ▼
                                                         │                     notification ── in_app : SENT tout de suite (le portail la lit)
                                                         │                         │        └─ push / e-mail / SMS / WhatsApp : PENDING
                                                         │                         ▼
                                                         │        travailleur (GitHub Actions) : réclamer (bail) → envoyer → rendre compte
                                                         │                         │   SENT · nouvel essai (attente ×2) · FAILED au maximum d'essais
                                                         │                         ▼
                                                         │                   notification_attempt (une ligne par essai, ajout seul)
                                                         └─▶ public.ses_signal (audience, sujet — aucune donnée) ──▶ temps réel Supabase ──▶ l'écran relit
```

## 2. Canaux

| Canal | État | Fournisseur | Essais | Attente initiale | Destinataire |
|---|---|---|---|---|---|
| `in_app` | allumé | la base (portail) | — | — | le compte du client |
| `push` | allumé | Expo | 5 | 60 s | appareils actifs du client (`logistics.device`) |
| `email` | allumé | Brevo (API) | 5 | 120 s | e-mail du client |
| `sms` | **éteint** | à choisir | 5 | 60 s | téléphone du client (ou du destinataire pour le code de livraison) |
| `whatsapp` | **éteint** | à choisir | 5 | 60 s | idem |

Un canal éteint : **rien n'est créé**. L'allumer : `update logistics.notification_channel set enabled = true, provider = '…' where code = 'sms';`
— et écrire son adaptateur dans le travailleur (aujourd'hui, une notification SMS réclamée est rendue « aucun fournisseur » et relancée).

Attente avant l'essai n : `attente_initiale × 2^(n−1)` ; au maximum d'essais, ou sur une erreur définitive (adresse invalide, clé refusée,
jeton inconnu), la notification passe **FAILED**.

## 3. Règles (19) et modèles (20 × 4 langues)

Événements qui préviennent le client : colis reçu, en route, arrivé, dédouané, au hub, en livraison, livré, en attente, endommagé, perdu,
retourné ; facture émise, en retard ; paiement reçu ; demande d'enlèvement ou de livraison approuvée ou refusée ; réponse du support. Les
étapes internes (vérifié, rangé, attente de consolidation…) ne préviennent personne. Le **motif** interne d'une mise en attente ne part
jamais : les modèles ne peuvent citer que dix variables (`tracking_number`, `stage`, `shipment_code`, `invoice_number`, `amount`, `currency`,
`date`, `message`, `code`, `expires_hours`) — un modèle qui en cite une autre est refusé par la base.

Les textes sont ceux du portail : `outils/portail-textes.py` écrit le gabarit, le dictionnaire **et** l'insertion des modèles dans 010
(entre `-- modeles:debut` et `-- modeles:fin`). Modifier un texte : la table, puis `python3 outils/portail-textes.py`. Le texte d'une
notification est **figé** à sa création, dans la langue du client (repli sur le français si le modèle de sa langue est désactivé).

## 4. Le code de livraison

Émis par l'équipe (phase 9), il part vers le **destinataire** par WhatsApp. Tant que WhatsApp est éteint, la base le **relaie** au client,
dans son portail et par e-mail (s'il ne l'a pas coupé), et marque l'original « non envoyé » avec la raison.

## 5. Préférences du client

`lg_my_notification_prefs()` / `lg_set_notification_pref(canal, oui/non)`, dans le profil du portail. Par défaut : portail (ne se coupe
pas), téléphone et e-mail ; SMS et WhatsApp seulement si le client les demande (et que le canal est allumé). Chaque changement est tracé dans
l'audit.

## 6. Le travailleur

`node scripts/notifications/envoyer.mjs`, avec dans l'environnement : `SES_SUPABASE_URL`, `SES_SUPABASE_SERVICE_KEY` (secret),
`SES_BREVO_API_KEY` (secret), `SES_EMAIL_EXPEDITEUR`, `SES_EXPO_TOKEN` (facultatif). Un passage : répartir les événements, réclamer 50
notifications, envoyer, rendre compte, purger les signaux de plus de deux jours. Un jeton refusé par Expo (« DeviceNotRegistered ») est
désactivé. Il ne contacte que trois hôtes (le projet Supabase, `api.brevo.com`, `exp.host`). Son journal est en JSON, sans clé ni adresse
complète.

**Mise en service** (geste explicite du propriétaire) : passer 001 à 010 ; vérifier l'expéditeur chez Brevo ; copier
`scripts/notifications/modele-workflow-notifications.yml` dans un dépôt **privé** ; y poser les secrets ; `NOTIFICATIONS_ACTIVES = true` ;
lancer **une fois à la main** et lire le bilan ; seulement ensuite décommenter la planification (toutes les 5 minutes).

## 7. Temps réel

`public.ses_signal` reçoit, pour chaque événement, une ligne « équipe » et, si un client est concerné, une ligne « client » (son
identifiant de compte). **Aucune donnée** : le domaine seulement (`parcel`, `invoice`, `request`…). La sécurité par ligne ne laisse lire à
un client que ses lignes, à l'équipe (avec un droit de lecture) que les lignes d'équipe. Le site écoute ces insertions
(`SES_API.notifications.surveiller`) : le centre de commande relit la section ouverte, le portail ses compteurs et ses écrans de lecture,
jamais un formulaire en cours. Une erreur d'écriture du signal est avalée : elle n'annule jamais l'opération. La table s'ajoute
automatiquement à la publication `supabase_realtime` quand elle existe.

Pour le chauffeur et l'entrepôt (application mobile, phase 14) : le même signal (sujets `task`, `parcel`, `scan`) ; l'application relit ses
missions par `lg_my_tasks`.

## 8. Ce que l'équipe voit

Centre de commande > Notifications : la **santé des envois** par canal (en attente, en cours, envoyées, nouveaux essais et échecs sur 24 h,
plus ancienne attente), la file des événements, les dix dernières erreurs — nettoyées de toute clé ou jeton, sans destinataire.

## 9. Tests

| Fichier | Ce qu'il prouve |
|---|---|
| `outils/tests/logistique-notifications-essai.py` (PostgreSQL jetable, ~140 vérifications) | modèles complets et gardés, canaux attendus calculés par un second chemin, langue et repli, idempotence, préférences, notifications nées de l'équipe et des finances, ce que le portail montre, relais du code, bail, relances (120, 240, 480, 960 s) puis échec, journal en ajout seul, erreurs nettoyées, destinataire disparu, signal (lecture par audience, aucune donnée, panne avalée, purge), panne du moteur rattrapée, portes |
| `outils/tests/notifications-travailleur.cjs` | configuration, trois hôtes seulement, chaque réponse de fournisseur → le bon compte rendu, jetons refusés désactivés, coupure réseau, journal sans secret |
| `outils/tests/notifications-contrat.cjs` | trois implémentations, signatures réelles, préférences de même forme en démonstration, temps réel limité au signal |

« Tester sur appareils réels » : **non fait ici** (aucun appareil ni compte Expo/Brevo sur ce poste). À faire au premier passage manuel du
travailleur : une notification sur un iPhone et un Android réels, un e-mail reçu (et pas en indésirable), un jeton désinstallé désactivé.
