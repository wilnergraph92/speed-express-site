# Notifications et temps réel (phases 13 et 11)

> Statut : le moteur (010, et le centre de notifications 027) est **dans la base de production** ; le portail lit les notifications « dans
> l'espace client » ; le **travailleur d'envoi n'est pas installé** : aucun e-mail, push ni WhatsApp ne part tant que le propriétaire ne l'a
> pas mis en service (§11).
> Source : `outils/logistique/010-notifications.sql`, `027-centre-notifications.sql`, `scripts/notifications/`. Décision :
> [ADR 0011](ADR/0011-notifications-moteur-dans-la-base-travailleur-planifie.md).

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
| `whatsapp` | **éteint** | Meta (WhatsApp Cloud API, 027) | 5 | 60 s | idem, au format international (indicatif du pays du client) |

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

## 10. Le centre de notifications (phase 11, étape 027)

### Ce que porte chaque notification
- l'événement (`event_row_id`, et par lui son `event_id`) ;
- le destinataire (`recipient`, figé à la création : e-mail, téléphone, « appareils:n », « portail ») ;
- le canal, la langue, le modèle ;
- le statut, les essais, la dernière erreur, la date d'envoi ;
- depuis 027, l'accusé du fournisseur (`provider_status`, `delivered_at`).

**Idempotence** : un événement ne crée jamais deux notifications pour le même canal (`unique (event_row_id, channel)`). Une bienvenue
est unique par client (index unique sur `domain_event`). Une relance reprend LA MÊME notification.

### Les événements demandés

| Événement | Règle (modèle) | Canaux |
|---|---|---|
| inscription | `CustomerRegistered` (`Welcome`) : une fois, APRÈS la confirmation de l'adresse, jamais pour un compte de plus de 7 jours ; un déclencheur sur `auth.users` qui avale toute erreur (une confirmation n'échoue jamais à cause d'elle) | portail, e-mail |
| confirmation de l'e-mail | Supabase Auth, par le crochet « Send Email Hook » (`scripts/notifications/courriels-compte.mjs`) : l'e-mail dans la langue choisie à l'inscription. Idem pour le mot de passe oublié, le lien de connexion, le changement d'adresse, l'invitation et le code de vérification | e-mail |
| colis reçu, départ, arrivée, douane, au HUB | `ParcelReceived`, `ParcelConsolidated`, `ParcelInTransit`, `ParcelArrived`, `CustomsStarted`, `CustomsCleared`, `ParcelAtDestinationHub` | portail, push, e-mail ; WhatsApp au HUB |
| changement de statut | chaque étape que le client voit a sa règle ; les étapes internes (vérifié, rangé…) ne préviennent personne | — |
| facture, paiement | `InvoiceIssued`, `InvoiceOverdue`, `PaymentReceived` | portail, e-mail ; WhatsApp (émise, payée) |
| livraison assignée, en cours, réussie, échouée | `DeliveryAssigned`, `OutForDelivery`, `Delivered`, `DeliveryFailed` | portail, push (e-mail, SMS selon la règle) ; WhatsApp |
| incident | par ses effets, sans doublon : colis abîmé (`ParcelDamaged`), perdu (`ParcelLost`), en attente (`ParcelOnHold`), livraison manquée (`DeliveryFailed`). Un incident n'envoie pas un second message ; sa description interne ne part jamais | — |
| document nécessaire | `CustomsExceptionRaised` de genre `MISSING_DOCUMENT` (`DocumentRequired`) : remplace le message « en attente » qu'elle provoque (même corrélation) ; la note de la douane ne part jamais | portail, push, e-mail, WhatsApp |

### WhatsApp
- **Les modèles et leur langue**
  - Meta n'envoie, hors d'une conversation ouverte par le client, que des **modèles approuvés**.
  - `outils/portail-textes.py` écrit `scripts/notifications/whatsapp-modeles.json` : les MÊMES textes que le portail, en paramètres nommés
    (`{{tracking_number}}`), catégorie « utility ».
  - Le créole haïtien n'est pas une langue de modèle WhatsApp : un client créolophone reçoit le modèle **français** ; ses autres canaux
    restent en créole.
- **Soumettre les modèles** : `scripts/notifications/whatsapp-modeles.mjs`, avec `SES_WHATSAPP_TOKEN` et `SES_WHATSAPP_WABA_ID`. Il soumet
  seulement ceux qui manquent.
- **Ce que le travailleur envoie**
  - Il envoie `ses_<modèle>` avec EXACTEMENT les paramètres du modèle approuvé.
  - Une variable manquante, un numéro sans indicatif ou un modèle pas encore approuvé (132001) : échec définitif, sans nouvel essai.
  - Débit dépassé : plus tard.
- **Le numéro** : il est mis au format international d'après le pays du client (Haïti : 8 chiffres → 509 ; République dominicaine et
  États-Unis : 10 chiffres → 1). Rien n'est deviné ailleurs.
- **Le consentement** : WhatsApp ne part que si le client l'a **demandé** (préférence, refusée par défaut), et si le canal est allumé.

### Les accusés des fournisseurs
`scripts/notifications/webhook-fournisseurs.mjs` est un modèle d'Edge Function.
- **Meta** : la signature `X-Hub-Signature-256` (secret de l'application) est vérifiée ; l'abonnement se fait par jeton.
- **Brevo** : un jeton secret dans l'adresse, comparé en temps constant.
- **La base** : chaque accusé passe par `ses_nt_provider_event` (clé secrète seulement), en ajout seul et sans doublon.
  - « remis » et « lu » sont notés ;
  - un rebond définitif ou une plainte fait passer la notification en échec ;
  - un rebond temporaire n'est pas un échec.

### La surveillance
- **Le seuil** : `ses_nt_alert` donne l'alerte au-delà de 10 échecs en 24 h sur un canal allumé, d'un cinquième des envois, ou d'une heure
  de retard.
- **L'alerte** : le travailleur l'écrit au journal (`ALERTE_NOTIFICATIONS`), et son workflow ouvre UN ticket `alerte-notifications` dans le
  dépôt privé. GitHub l'envoie par e-mail ; le ticket ne cite que les canaux et les nombres.
- **Dans le tableau de bord** : Notifications › « Envois en échec » donne le destinataire masqué et l'erreur nettoyée. La direction relance
  (`lg_nt_retry`, motif obligatoire, tracé) la même notification.

## 11. Mise en service (gestes du propriétaire)

Aucun de ces gestes ne demande de donner une clé à qui que ce soit : chaque secret se pose directement dans GitHub ou dans Supabase.

1. **E-mail et push**
   1. Brevo : vérifier l'expéditeur, et créer une clé d'API.
   2. Copier `scripts/notifications/modele-workflow-notifications.yml` dans le dépôt privé.
   3. Y poser les secrets `SES_SUPABASE_SERVICE_KEY` et `SES_BREVO_API_KEY`, puis les variables `SES_SUPABASE_URL`,
      `SES_EMAIL_EXPEDITEUR`, `SES_SCRIPTS_REF` et `NOTIFICATIONS_ACTIVES=true`.
   4. Lancer une fois à la main, lire le bilan, puis décommenter la planification.
2. **E-mails de compte en quatre langues**
   1. Déployer `courriels-compte.mjs`, avec `serveur.mjs` et `courriels-compte.json`, comme Edge Function `courriels-compte`.
   2. Dans Supabase : Authentication › Hooks › Send Email Hook vers cette fonction.
   3. Poser ses secrets : `SES_HOOK_EMAIL_SECRET`, `SES_BREVO_API_KEY`, `SES_EMAIL_EXPEDITEUR`, `SES_SITE_URL`.
3. **WhatsApp**
   1. Compte WhatsApp Business chez Meta, numéro vérifié, utilisateur système et jeton permanent.
   2. Soumettre les modèles (`whatsapp-modeles.mjs --soumettre`) et attendre leur approbation.
   3. Poser `SES_WHATSAPP_TOKEN` (secret) et `SES_WHATSAPP_PHONE_ID` (variable) dans le dépôt privé.
   4. Allumer le canal : `update logistics.notification_channel set enabled = true where code = 'whatsapp'` (une migration ou le
      propriétaire).
4. **Accusés**
   1. Déployer `webhook-fournisseurs.mjs` comme Edge Function `notifications-accuses`, avec la vérification JWT désactivée.
   2. Poser ses secrets : `SES_META_APP_SECRET`, `SES_META_JETON_ABONNEMENT`, `SES_BREVO_JETON_WEBHOOK`.
   3. Donner son adresse à Meta et à Brevo.

Essais :
- `logistique-notifications-centre-essai.py` (réplique de la production) ;
- `notifications-travailleur.cjs` (dont WhatsApp) ;
- `notifications-serveur.mjs` (signatures, accusés, e-mails de compte) ;
- `notifications-statique.py`.
