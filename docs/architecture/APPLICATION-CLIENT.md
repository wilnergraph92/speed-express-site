# L'application client (phase 8, étape 020)

L'application client Speed Express (Android, iOS) vit dans le dépôt **privé** `~/Desktop/App_SES` (`wilnergraph92/speed-express-app`) :
Expo, React Native, TypeScript, expo-router, Supabase, temps réel. Ce document décrit ce que la **base** lui fournit (étape 020) et
comment les deux dépôts restent d'accord. La liste de contrôle de publication est dans `App_SES/docs/PUBLICATION.md`.

Essais :
- `outils/tests/logistique-application-essai.py` : 110 vérifications, sur la réplique de la production **et** sur une préproduction. Il
  enregistre `application-rpc.json` (signatures) et `application-exemples.json` (réponses réelles) avec `SES_FORME_ECRIRE=1` ;
- `outils/tests/notifications-travailleur.cjs` : ce qu'emporte chaque push ;
- dans `App_SES` (`npm run essai`) : 14 suites, dont le contrat (`contrat-application.cjs`) contre les fichiers ci-dessus.

État : **non appliquée**. L'application fonctionne aujourd'hui sur l'ancien schéma (production), et passe d'elle-même au noyau quand
il est en service pour le client.

## 1. Deux sources, un seul modèle

`App_SES/src/api/portail.ts` choisit la source **une fois par compte** :
- `lg_my_dashboard` répond et le client est rattaché (`linked`, `in_sync`) → **noyau** : colis (`lg_my_parcels`, `lg_my_parcel`), parcours en
  huit étapes (`lg_my_parcel_journey`), factures, soldes et paiements calculés par la base, notifications, support ;
- la fonction n'existe pas (`PGRST202`, `42883`) → **ancien schéma** (`colis`, `colis_historique`, `factures_details`). Une coupure réseau ou un
  refus n'est **jamais** pris pour une absence du noyau.

`App_SES/src/api/modele.ts` traduit les deux formes vers le même modèle, sans règle métier :
- les statuts de l'ancien schéma sont traduits **comme le rattrapage du noyau** (002 puis `customer_stage`) : `confirme → registered`,
  `expedie → in_transit`, `disponible → at_hub`, `livre → delivered`, `action → on_hold` ;
- côté noyau, **aucun montant n'est calculé** : total, payé, solde viennent de la base (l'essai `modele.cjs` le vérifie dans le code) ;
- côté ancien schéma, le reste à payer se déduit comme sur le site (inventorié dans `finance-navigateur.cjs`), **par devise** : jamais un total
  qui additionnerait des dollars et des gourdes.

Les libellés (étapes, parcours, événements, factures, paiements, support) sont **les mêmes que le portail web** : `App_SES/scripts/importer-textes-portail.py`
les recopie depuis `outils/portail-textes.py` dans `src/i18n/textesPortail.ts`. On change la table du site, puis on relance ce script.

## 2. Les notifications : chaque événement important du colis

| Événement | Règle | Push |
|---|---|---|
| colis reçu | `ParcelReceived` | ✓ (010) |
| colis consolidé | `ParcelConsolidated` | ✓ **020** |
| départ | `ParcelInTransit` | ✓ (010) |
| arrivée | `ParcelArrived` | ✓ (010) |
| douane | `CustomsStarted` (**020**), `CustomsCleared` (010) | ✓ |
| disponible | `ParcelAtDestinationHub` | ✓ (010) |
| assigné à une livraison | `DeliveryAssigned` | ✓ **020** |
| en livraison | `OutForDelivery` | ✓ (010) |
| livré | `Delivered` | ✓ (010) |
| incident | `ParcelDamaged`, `ParcelOnHold`, `DeliveryFailed` (015), `ParcelLost` (push ajouté par **020**) | ✓ |

Les textes des trois nouveaux modèles sont dans `outils/portail-textes.py` (`notif-…`, `notif-titre-…`). L'outil écrit chaque modèle dans
l'étape qui l'ajoute (`MODELES_PAR_ETAPE`) : 010 reste telle qu'elle a été écrite, les trois nouveaux vivent dans 020.

## 3. Le téléphone, enregistré dans le noyau

`lg_register_device(p_token, p_platform)` : le compte est **celui de la session** ; jeton Expo et plateforme vérifiés (`LG005`) ; un compte
d'équipe est refusé (`LG003`) ; un téléphone qui a servi à un autre compte lui est retiré ; dix téléphones actifs au plus par client (le plus
ancien s'éteint, rien n'est supprimé) ; 20 enregistrements par heure (`LG007`, plafond posé dans la fonction : la table des appareils est
aussi écrite par le rattrapage, qui ne doit jamais être freiné). `lg_unregister_device(p_token)` : seul le propriétaire, désactivé, jamais supprimé.

**Une seule voie à la fois.** L'application enregistre le téléphone dans le noyau quand il est sa source, sinon dans l'ancienne table
`appareils` (`enregistrer_appareil`, section 9 de `supabase-maj.sql`). Les deux à la fois enverraient deux notifications par événement.
**À la bascule** des notifications vers le noyau : éteindre l'ancien déclencheur `prevenir_client` (section 9), sinon les téléphones repris
de l'ancien schéma (`source = legacy_backfill`) recevraient chaque message deux fois.

## 4. Toucher une notification ouvre le colis

Le travailleur d'envoi (`scripts/notifications/envoyer.mjs`) lit, une fois par lot, `ses_nt_push_data(p_ids)` (clé secrète seulement) :
`{ template, tracking_number, url: "speedexpress://colis/<numéro>" }`. Seules ces clés partent vers le téléphone, et seul un lien
`speedexpress://(colis/<numéro>|factures|notifications)` est accepté. Sans 020, le push part avec son seul identifiant et l'application ouvre
la liste des notifications. Côté application, `src/api/liens.ts` décide (formes du noyau et de l'ancien schéma, `{ colis_id, numero }`) et
`src/api/ouverture.ts` branche l'application lancée par le toucher comme l'application déjà ouverte. Le canal Android est `colis` partout.

## 5. Temps réel, hors connexion, sécurité

- **Temps réel** : les tables de l'ancien schéma et `public.ses_signal` (étape 010, sans donnée, filtré par compte) ; plusieurs signaux
  rapprochés ne font qu'une relecture.
- **Hors connexion** : la dernière lecture réussie de chaque liste est gardée sous le compte, avec son heure, et affichée avec un bandeau.
  Jamais un secret (les noms de copie sont filtrés), effacée à la déconnexion. Tout se relit au retour du réseau.
- **Session** : dans le trousseau chiffré du téléphone (Keychain, Keystore — `expo-secure-store`, `AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY`),
  découpée sous la limite de 2 Ko, jamais en clair ; AsyncStorage ne la garde que sur le web. À la déconnexion : téléphone retiré des envois,
  copie effacée, source oubliée.

## 6. Le paiement

Le paiement en ligne n'est proposé que si la base a un prestataire actif pour la devise **et** si le serveur de paiement est configuré au
build (`EXPO_PUBLIC_PAIEMENT_URL`, https). La base crée la demande et fixe le montant (`lg_my_create_payment_intent`, le solde du moment) ;
le serveur ouvre la page du prestataire (`<serveur>/commencer?demande=PIN-…&retour=speedexpress://paiement`) ; au retour, l'application
relit l'état dans la base (`lg_my_payment_intent`) — jamais la page de retour. **Ce serveur n'existe pas encore** (la fonction Edge de la
phase 6 est un modèle) : tant qu'il manque, l'écran propose l'agence et WhatsApp.

## 7. Retour en arrière

`020` **ajoute** (trois règles, des modèles de texte, trois fonctions et leurs façades) et ajoute « push » à `ParcelLost`. Rien n'est supprimé.

| Besoin | Geste |
|---|---|
| ne plus prévenir des trois nouveaux événements | `update logistics.notification_rule set active = false where event_type in ('ParcelConsolidated', 'CustomsStarted', 'DeliveryAssigned');` |
| plus de push pour un colis perdu | `update logistics.notification_rule set channels = array_remove(channels, 'push') where event_type = 'ParcelLost';` |
| fermer l'enregistrement des téléphones dans le noyau | `revoke execute on function public.lg_register_device(text, text), public.lg_unregister_device(text) from authenticated;` — l'application retombe sur l'ancienne table |
| couper les données des push | `revoke execute on function public.ses_nt_push_data(bigint[]) from service_role;` — les push partent avec leur seul identifiant |
