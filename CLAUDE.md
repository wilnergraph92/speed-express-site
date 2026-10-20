# Speed Express Shipping — site et espace client

Site vitrine et espace client d'une entreprise de transport de colis.
Site statique, sans build : les fichiers du dépôt sont exactement ceux
qui sont servis.

Projet frère de **Goship Express** (`~/Desktop/Website_GSE`) : même ADN,
mais plusieurs choix diffèrent. Voir « Différences avec Goship » plus
bas avant de transposer quoi que ce soit d'un projet à l'autre.

## Avant de toucher au code

- **`main` est protégée** (depuis le 8 octobre 2026) : on travaille sur une branche, on ouvre une PR ; la fusion exige la CI
  `valider` verte et à jour, et la mise en ligne attend l'**approbation du propriétaire** (environnement `github-pages`). Aucun
  envoi direct sur `main`, même administrateur. Chaîne complète : `docs/production/ENVIRONNEMENTS.md`.
- **Commence par `git pull`.** Ce dépôt reçoit aussi des commits d'un
  autre agent. Une copie locale en retard qu'on régénère réécrit les 28
  pages dans leur ancienne version et efface le travail des autres.
- **Tout est commenté en français**, avec les accents, dans un ton qui
  explique le pourquoi plutôt que le quoi. Les noms de variables et de
  fonctions sont en français.
- **Aucune étape de compilation.** Pas de bundler, pas de framework.
  JavaScript ES5 dans des IIFE, `var`, pas de modules.
- **Ce qui est à la racine part en ligne.** Le déploiement publie le
  dépôt moins les fichiers de travail, retirés par
  `.github/workflows/deploy.yml` : `.github`, `.claude`, `.gitignore`,
  `outils/`, `docs/`, `scripts/`, `bureau/`, `README.md`, `CLAUDE.md`, `SECURITY.md` et
  `ARCHITECTURE-BASELINE.md`. Tout le reste est servi tel quel. Un nouveau
  fichier de travail à la racine s'ajoute à cette liste : le test
  `outils/tests/publication.py` échoue sinon. N'y dépose jamais de secret.

## Architecture

```
index.html, …                    28 pages à la racine — GÉNÉRÉES
outils/pages/                    les 28 sources : c'est ici qu'on écrit
outils/communs/                  en-tête, pied, composants partagés
outils/espace/                   fragments des 5 pages de comptes
assets/js/                       toute la logique (41 fichiers)
outils/*.sql                     migrations Supabase
docs/, ARCHITECTURE-BASELINE.md     l'existant décrit (docs/current-state/), la cible (docs/architecture/), l'exploitation (docs/production/), jamais publié
outils/securite.py               politique de contenu, référent, anti-cadre : posés dans chaque page à la génération
outils/logistique/               noyau logistique (schémas « logistics », « analytics » pour les rapports, « ops » pour l'exploitation), migrations 001 à 031, appliquées en production par l'outil de migration (journal ses_meta.migration)
outils/tests/                    la suite de vérification
bureau/                          Speed Express Operations, l'application de bureau Windows et macOS (Tauri 2, ADR 0016) — jamais publiée sur le site
```

**Les pages à la racine ne se modifient pas à la main** : elles sont
écrasées à la prochaine génération. On édite `outils/pages/`, puis :

```bash
python3 outils/mise-en-page.py
```

Cette seule commande fait tout : 23 pages publiques depuis
`outils/pages/` et `outils/communs/`, puis elle appelle elle-même
`pages-espace.py` pour les 5 pages de comptes. Relancée aussitôt, elle
doit annoncer « déjà à jour » et « 0 modifiées » — sinon la génération
n'est pas reproductible, et c'est un bug à corriger avant de publier.

### Les fichiers JavaScript

Les fichiers propres au projet portent le préfixe **`ses-`** :

| Fichier | Rôle |
|---|---|
| `ses-api.js` | Couche de données, `window.SES_API`. Le cœur (≈ 2 650 lignes). |
| `ses-admin.js` | Tableau de bord équipe : colis, clients, factures |
| `ses-dashboard.js` | Tableau de bord : chiffres et rapports, en lecture seule |
| `ses-espace.js` | Espace client |
| `ses-compte.js` | Comptes, connexion |
| `ses-ui.js` | Affichage partagé : statuts, dates, montants, étiquette, facture |
| `ses-entete.js` | En-tête et navigation |
| `ses-hero.js` | Bannière de l'accueil |
| `ses-anim.js` | Animations |
| `ses-accessibilite.js` | Repères clavier et annonces aux lecteurs d'écran |
| `ses-villes.js` | Liste des villes de livraison |
| `site.js` | Comportements communs des pages publiques |
| `ses-portail.js`, `ses-portail-suivi.js`, `ses-portail-finance.js`, `ses-portail-services.js` | Portail client du noyau (14 sections), ouvert par `ses-espace.js` seulement si l'interrupteur `portailNoyau` de `config.js` est allumé et que le noyau est à jour pour ce client. Aucune règle métier : tout vient de `SES_API.portail` |
| `ses-centre.js`, `ses-centre-vues.js` | Centre de commande de l'équipe : un onglet du tableau de bord (19 sections, chiffres du jour, file « à traiter », traitement des demandes), visible seulement si l'interrupteur `centreNoyau` de `config.js` est allumé et que la base répond. Aucun chiffre calculé ici : tout vient de `SES_API.centre` (`public.lg_cc_*`) |
| `ses-scanner.js`, `ses-poste.js` | Le poste de scan du bureau (phase 15, ADR 0013) : une section du centre de commande. `ses-scanner.js` lit tous les lecteurs (scanner USB « clavier », caméra, saisie) ; `ses-poste.js` envoie chaque lecture à `lg_scan_parcel` avec une clé d'idempotence, imprime l'étiquette et le bordereau, exporte et importe des listes. Le tableau de bord s'installe comme application de bureau par `tableau-de-bord.webmanifest` (sans service worker) |
| `ses-modules.js` | Les sections du tableau de bord de la phase 7 (`docs/architecture/TABLEAU-DE-BORD.md`) : la vue temps réel du centre de commande (onze cartes, chacune ouvre son module), véhicules, tournées, dépenses, Pointage Express (colis et personnel), missions du chauffeur. Aucun chiffre calculé ici : tout vient de `SES_API.tableau` (`public.lg_dashboard_access`, `lg_cc_command`…) |
| `ses-analytique.js` | L'analytique du centre de commande (phase 16, ADR 0014 ; étape 029) : rapports quotidien à annuel ou sur une période choisie, cinq familles (opérations, transport, dernier kilomètre, finance, clientèle), détail par chauffeur, zone et tournée, alertes à acquitter, export CSV et PDF avec la traçabilité (version de calcul, empreintes, statut), jours jamais calculés ou anciens signalés. Aucun chiffre calculé ici, pas même une addition : tout vient de `SES_API.analytique` (`public.lg_an_*`) |
| `ses-prealertes.js` | L'onglet « Pré-alertes » du tableau de bord : les achats annoncés par les clients depuis l'application (table `public.prealertes`, `supabase-maj-prix-prealertes.sql`). Visible avec « colis.lire » et si la table existe ; traitement (reçue, annulée) avec « colis.statut » ou « colis.modifier ». Tout passe par `SES_API.prealertes` |
| `ses-reglages.js` | Le menu ⚙ (apparence claire, sombre ou système ; personnaliser ; rétablir ; tous les réglages ; déconnexion), le menu du compte et la fenêtre « Réglages » (Affichage, Mon compte, Système). Préférences d'AFFICHAGE gardées sur l'appareil (`localStorage`, revalidées à chaque lecture), jamais des données. Le thème sombre se pose sur `<html data-theme>` et vit dans `assets/css/ses-reglages.css` : une couleur écrite en dur dans un gabarit doit y avoir sa variante sombre. Se charge AVANT `ses-admin.js` (lignes par page) |
| `ses-dernier-km.js` | Le dernier kilomètre, dans le centre de commande (phase 5) : missions du jour, livraisons en cours, chauffeurs actifs, échecs, incidents, SLA, preuves manquantes, et l'affectation automatique de la journée. Aucun chiffre calculé ici : tout vient de `SES_API.dernierKm` (`public.lg_cc_last_mile`) ; relu à chaque signal temps réel |
| `ses-sante.js` | La santé du système, dans le centre de commande (phase 17, ADR 0015), pour la direction : quinze contrôles (dix-sept avec l'analytique de 029) avec seuils et verdict de la base, derniers signaux des travaux planifiés, dernières erreurs des navigateurs. Tout vient de `SES_API.exploitation` (`public.lg_ops_status`) |
| `ses-bureau.js` | Le pont avec l'application de bureau « Speed Express Operations » (phase 10, ADR 0016, `bureau/`) : impression par le système, étiquette ZPL sur l'imprimante thermique choisie, liens externes au navigateur du système, mises à jour (canal stable ou bêta), section « Application de bureau » du module Scanner. **Inactif dans un navigateur.** Toute commande qu'il demande doit exister dans `bureau/src-tauri/src/lib.rs` (`bureau-contrat.cjs` le vérifie) |
| `lang-dict*.js` | 11 dictionnaires de traduction |
| `lang-switcher.js` | Sélecteur de langue — Web Component en Shadow DOM |
| `config.js` | Clés Supabase et réglages — **contient des secrets** |
| `vendor/` | Bibliothèques servies depuis le dépôt, jamais depuis un CDN : la bibliothèque Supabase, chargée seulement quand on en a besoin, et les générateurs de QR et de codes-barres écrits ici |

### Le double backend — à comprendre avant tout

`ses-api.js` expose **une seule interface** (`window.SES_API`) mais deux
implémentations :

```js
var MODE = CFG.supabaseUrl && CFG.supabaseKey ? 'supabase'
         : (LOCAL ? 'demo' : 'off');
```

- **`supabase`** — la vraie base, en production
- **`demo`** — tout en `localStorage`, si aucune clé n'est configurée et
  qu'on est en local (`file:` ou localhost)
- **`off`** — en ligne sans configuration : l'interface le dit

**Toute méthode ajoutée doit l'être dans les deux implémentations**,
sinon le mode démo casse silencieusement.

Une seule exception, assumée : les méthodes `admin.dashboard*` n'existent
qu'en mode `supabase`, parce que ces rapports ne montrent que des chiffres
réels et qu'inventer des données de démonstration y serait trompeur.
`ses-dashboard.js` ne les appelle qu'après un test `API.mode !==
'supabase'`. Même raison, même exception pour le **centre de commande**
(`SES_API.centre`, ADR 0010) : les trois implémentations en ont les mêmes
méthodes, mais celles de la démonstration répondent « fermé » et l'onglet
reste caché. Toute autre méthode sans jumelle est un bug, pas un choix.

## Traductions — dictionnaires, pas dossiers

C'est la différence la plus piégeuse avec Goship. Ici, **une seule
version de chaque page**, traduite à l'exécution :

- `lang-dict.js` et `lang-dict-2.js` … `lang-dict-11.js` remplissent tous
  le même objet global `window.SES_DICT`, par `Object.assign`. Une entrée
  par chaîne source française, dans l'ordre **anglais, espagnol,
  créole** :
  `"Identifiant SES, nom ou e-mail": ["SES ID, name or email", "…", "…"]`
  La clé doit être le texte français **exact**, tel qu'il s'affiche.
- `lang-switcher.js` est un Web Component en **Shadow DOM**, choisi pour
  rester invisible aux scripts tiers. La langue retenue est stockée sous
  la clé `ses-lang`.

Conséquence : **toute chaîne visible ajoutée à une page doit recevoir sa
traduction dans le dictionnaire**, sinon elle restera en français dans
les trois autres langues. Cherche la chaîne exacte dans
`assets/js/lang-dict*.js`.

**Trois règles du moteur que rien ne rappelle, et qui laissent un texte en
français sans erreur :**

1. **Chaque page ne charge que SON dictionnaire** : `lang-dict.js` plus sa ou
   ses parties (`PAGE_PARTS` dans `lang-switcher.js` ; le tableau de bord et
   les pages de compte : `lang-dict-11.js`). Un texte traduit dans
   `lang-dict-3.js` reste français sur le tableau de bord. Mets la traduction
   dans le fichier de la page qui l'affiche.
2. **La comparaison est exacte, nœud de texte par nœud de texte**, après
   avoir remplacé `’` par `'`. Une clé écrite avec `’` ne correspond donc
   **jamais** : écris toujours `'`. Un texte coupé par une balise
   (`<strong>Client</strong> — suite…`) en fait deux, à traduire séparément.
3. **Seuls `placeholder`, `title`, `aria-label`, `alt` et le `<title>` sont
   traduits comme attributs.** Un `<option>` sans `value` est traduit **et sa
   valeur avec** : donne-lui toujours un `value` explicite (la valeur française
   canonique), sinon ce qui s'enregistre dépend de la langue de l'écran.

Un texte composé par le JavaScript passe par `UI.t('clé')` : la clé doit exister
en `data-t` dans le `<template data-textes>` **de la page**, sinon le texte est
**vide**, sans erreur. Un contenu rendu par le JavaScript doit aussi être
reconstruit au changement de langue (`UI.surLangue`), sinon il garde la langue
du moment où il a été dessiné.

**Les textes du portail client ne s'écrivent pas à la main** : ils sont dans une seule table,
`outils/portail-textes.py` (français, anglais, espagnol, créole), qui écrit à la fois le gabarit
(`outils/espace/espace-client.html`), le dictionnaire (`lang-dict-11.js`) **et les modèles des notifications**
envoyées par e-mail et sur le téléphone (`outils/logistique/010-notifications.sql`) entre des repères. Ajouter
un texte : une ligne dans la table, puis `python3 outils/portail-textes.py` et
`python3 outils/mise-en-page.py`. `portail-textes.cjs` exige un texte et trois traductions pour
**chaque valeur que la base peut renvoyer** (étapes, statuts, événements…) : un nouveau statut ajouté à la
base sans texte fait échouer ce test, au lieu de s'afficher vide.

Même principe pour le **centre de commande** : `outils/centre-textes.py` écrit les textes du tableau de bord
(`outils/espace/tableau-de-bord.html`) et leurs traductions ; `centre-textes.cjs` exige un texte pour chaque valeur que la
base renvoie et pour chaque colonne déclarée dans `ses-centre-vues.js`.

`outils/tests/traductions-couverture.py` vérifie les trois règles pour les 28
pages ; `i18n.cjs` vérifie que chaque `t('clé')` a son `data-t`. Si tu ajoutes
du texte, lance-les : ils disent exactement ce qui manque.

Les **notifications** (phase 13) partent par un travailleur côté serveur, `scripts/notifications/envoyer.mjs`, lancé par un
workflow GitHub Actions qui n'est **pas** installé (`scripts/notifications/modele-workflow-notifications.yml`, à copier dans un
dépôt privé) : il lit la clé secrète de Supabase et la clé Brevo dans l'environnement, jamais dans le dépôt. Le site n'écoute en
temps réel qu'une table sans donnée, `public.ses_signal` (`SES_API.notifications.surveiller`) ; il relit ensuite par les
fonctions qui contrôlent les droits. Le **centre de notifications** (phase 11, étape 027) : chaque notification porte son destinataire ; bienvenue
à l'inscription (une fois, après confirmation de l'e-mail, déclencheur sur `auth.users` qui ne peut jamais faire échouer une confirmation) ; « document
nécessaire » (exception de douane `MISSING_DOCUMENT`, sans doublon avec « en attente ») ; **WhatsApp** (Cloud API de Meta, par le travailleur : modèles
approuvés `ses_<modèle>` écrits par `portail-textes.py` dans `scripts/notifications/whatsapp-modeles.json`, créole → modèle français, consentement du
client) — **un nouveau modèle sur une règle WhatsApp doit entrer dans `WHATSAPP_MODELES`** (`notifications-statique.py` le vérifie) ; accusés des
fournisseurs (`ses_nt_provider_event`, fonctions serveur modèles `webhook-fournisseurs.mjs`, `courriels-compte.mjs` pour les e-mails de compte en
quatre langues) ; alerte (`ses_nt_alert`, ticket dans le dépôt privé) et relance par la direction (`lg_nt_retry`). Détail : `docs/architecture/NOTIFICATIONS.md`.

Le **workflow du colis** (phase 3, étape 015) : 22 statuts (code + nom métier, `parcel_status.business_name`), 104 transitions (105 avec la remise au comptoir, 025) en
données, et un contrôle **différé** de cohérence colis / mission / expédition à la validation de chaque transaction (`LG001`
« Statut incohérent »). Une fonction qui fait avancer une mission et ses colis doit laisser l'ensemble cohérent avant le `commit`.
Ajouter un statut touche : `parcel_status`, `parcel_transition`, `customer_stage` (008), `assess_scan` (004), les textes
(`centre-textes.py`, `portail-textes.py`) et, si l'application le voit, le contrat partagé (`SES_FORME_ECRIRE=1`). Détail :
`docs/architecture/PARCEL-STATE-MACHINE.md`.

Le **transport international** (phase 4, étape 016) : Miami → Haïti / République dominicaine, en direct ou avec **transbordement**
(un colis arrivé à un hub qui n'est pas dans son pays y reste `IN_TRANSIT`, une étape suivante l'emmène ; il ne passe la douane qu'une
fois, dans son pays). L'expédition qui déplace un colis est **son expédition courante** (`parcel_current_shipment`), jamais une étape
qu'il a quittée. Le client voit un parcours en huit étapes **calculé par la base** (`lg_my_parcel_journey`) : le portail le dessine tel
quel. Changer cette fonction oblige à relancer `logistique-international-essai.py` avec `SES_FORME_ECRIRE=1`
(`parcours-rpc.json`, `parcours-formes.json`). Détail : `docs/architecture/TRANSPORT-INTERNATIONAL.md`.

Le **dernier kilomètre** (phase 5, étape 017) : quatre profils décidés par la base — chauffeur (fiche active), agent de livraison
(`colis.statut`), responsable de livraison (`colis.statut` + **`livraisons.gerer`**, un droit d'employé de `SES_API.DROITS`), manager des
opérations (gérant, administrateur). Statuts de chauffeur et de véhicule, réaffectation, retrait d'une tournée, annulation : **motif
obligatoire**. La preuve de livraison reste en ajout seul et garde l'heure du téléphone. Un nouveau motif d'échec touche la contrainte
`incident_type_check`, `fail_task`, `centre-textes.py` (`c-inc-`), `portail-textes.py` (`incident-`) et `App_SES` (`ECHECS`, exigé par son
contrat). Le tableau du dernier kilomètre est calculé dans `logistics.last_mile_dashboard`. Détail : `docs/architecture/DERNIER-KILOMETRE.md`.

La **finance professionnelle** (phase 6, étape 018) : le moteur financier du noyau est la source de vérité de l'argent ; **le navigateur
ne calcule aucun montant** (`finance-navigateur.cjs` fige la liste des calculs de l'ancienne facturation, à retirer à la bascule). Les
prestataires de paiement (`payment_provider` : carte, Azul, MonCash, NatCash) n'ont **aucun secret** en base — seulement le NOM de la variable
d'environnement du serveur ; les webhooks passent par une Edge Function (`scripts/paiements/`, modèle) puis `ses_payment_event`, ouverte au
seul `service_role` : idempotents, vérifiés, journalisés (`payment_event`), réconciliables. La bascule de l'ancienne facturation vers le noyau
(`lg_set_finance_mode`) est refusée tant que la réconciliation (parité avec chaque facture héritée, cohérence du noyau, paiements) n'est pas
propre. Détail : `docs/architecture/FINANCE.md`.

La **migration continue** (phase 2, étape 014) : `logistics.run_migration()` rattrape l'ancien schéma (journalisé, retenté,
idempotent) ; `logistics.migration_report()` rend compteurs, empreintes des deux côtés et écarts classés — **prêt** = zéro écart
inexpliqué. La double écriture (déclencheurs `lg_double_ecriture` → file `logistics.sync_queue` → `process_sync_queue()`) est
**éteinte** par défaut et ne s'allume que si la migration est prête ; elle ne peut jamais faire échouer une écriture du site.
Toute colonne ou table ajoutée à l'ancien schéma doit être reportée dans le rattrapage **et** dans les empreintes
(`backfill_complements`, `reconcile_complements`, `migration_checksums`) : aucun essai ne devine un oubli, il resterait hors du
noyau sans bruit. Détail :
`docs/architecture/MIGRATION-REPORT.md`.

L'**exploitation** (phase 17, étape 013, schéma `ops`) : `ses_health()` est la seule fonction ouverte aux visiteurs (« ok » et le niveau
de migration) ; la limitation de débit est faite par des **déclencheurs** sur les tables où écrivent les façades (erreur `LG007`, message
« trop de demandes ») — ne la déplace pas dans les façades, elle serait perdue au rejeu d'une étape antérieure ; `SES_API` signale à la base
les erreurs JavaScript d'un compte connecté (jamais sur une page publique). Les étapes se passent **dans l'ordre** ; rejouer une étape ancienne
après une plus récente n'est pas sûr (006 échoue). Procédures, seuils, retour en arrière : `docs/production/`.

Le **tableau de bord** (phase 7, étape 019) : une barre de **26 modules** (`<button role="tab" data-module>` dans
`outils/espace/tableau-de-bord.html`). Les modules du noyau partagent le panneau du centre (`aria-controls="ses-p-centre"`) et
nomment leurs sections (`data-sections`) ; l'adresse reste `#centre/<section>`. Qui voit quel module se décide dans la base
(`lg_dashboard_access`) ; un module n'apparaît que si la base l'ouvre et qu'une de ses sections est dessinable. **Sans le noyau**
(production actuelle), la barre s'affiche quand même d'après les droits de l'ancien schéma, et chaque module du noyau ouvre un écran
« Bientôt disponible » (`ses-p-attente`, textes `c-bientot-…`) — jamais un chiffre. Ajouter un module touche :
la barre, `dashboard_access` (019), le texte `c-mod-…` dans `outils/centre-textes.py` ; `tableau-contrat.cjs` vérifie l'ensemble.
Détail : `docs/architecture/TABLEAU-DE-BORD.md`.

L'**application client** (phase 8, étape 020) vit dans `~/Desktop/App_SES` : elle lit le **noyau** (`lg_my_*`) dès qu'il est en service pour
le client, sinon l'ancien schéma, et traduit les deux vers un seul modèle (`src/api/modele.ts`, sans calcul de montant côté noyau). L'étape 020
ajoute les notifications qui manquaient (colis consolidé, douane commencée, livraison assignée, push d'un colis perdu), l'enregistrement d'un
téléphone dans le noyau (`lg_register_device`, une seule voie à la fois avec l'ancienne table `appareils`) et les données d'un push
(`ses_nt_push_data` : numéro et lien `speedexpress://colis/<numéro>`, lus par le travailleur d'envoi). Changer une fonction appelée par
l'application oblige à relancer `logistique-application-essai.py` avec `SES_FORME_ECRIRE=1`, à recopier `application-rpc.json` et
`application-exemples.json` dans `App_SES/tests/` (`rpc-application.json`, `exemples-application.json`) et à y lancer `npm run essai`. Ses
libellés sont ceux du portail (`App_SES/scripts/importer-textes-portail.py`). Détail : `docs/architecture/APPLICATION-CLIENT.md` ; publication :
`App_SES/docs/PUBLICATION.md`.

**SES Opérations** (phase 9, étape 021) : la porte unique `lg_mobile_command` admet 13 gestes (dont `arrive_stop`, `start_trip`,
`complete_trip`, `reschedule_task`) ; `lg_task_proof` et `lg_warehouse_locations` pour l'équipe. Le GPS n'est lu qu'au moment d'un geste du
métier (jamais de suivi). Changer la porte ou ces lectures oblige à relancer `logistique-applications-essai.py` **et**
`logistique-terrain-essai.py` avec `SES_FORME_ECRIRE=1`, puis à recopier `applications-*.json` et `terrain-*.json` dans `App_SES/tests/`
(`rpc-noyau.json`, `formes-noyau.json`, `rpc-terrain.json`, `formes-terrain.json`). Détail : `docs/architecture/MOBILE-OPERATIONS.md` §3 bis.

**Appliquer le noyau** se fait par `scripts/migration/migrer.py` (workflow « Migration du noyau » du dépôt privé des sauvegardes, modèle
`scripts/migration/modele-workflow-migration.yml`), pas par collage : la bonne base (référence du projet, marqueur `staging`), l'ordre
(journal `ses_meta.migration`), une sauvegarde **vérifiée avant chaque étape** en production, une transaction par étape, les contrôles
(santé, rattrapage prêt dès la 014) ; aucun interrupteur allumé. La sauvegarde emporte aussi `logistics`, `analytics`, `ops` et `ses_meta`
(`SCHEMAS_NOYAU`, `scripts/backup/_commun.py`) : **un nouveau schéma du noyau s'y ajoute**, sinon `sauvegarde-statique.py` échoue.
Les **agences, entrepôts et emplacements** (étape 023) n'existaient pas en production (l'ancien schéma n'en avait pas) : la direction les saisit
dans le tableau de bord (module Entrepôts › « Agences et entrepôts », `lg_sites`, `lg_create_branch`…). Code et pays figés après création ;
rien ne se désactive sous un colis. Essai : `logistique-sites-essai.py`.
Les **expéditions et transports** (étape 024) se créent et avancent depuis le tableau de bord (Expéditions, Transport ; `ses-modules.js`) : la fiche
ne propose que les gestes de l'état présent ; « Préparer des colis » (`lg_prepare_parcels`) fait faire à chaque colis le chemin du poste de scan
(reçu, vérifié avec son poids, rangé, à consolider). Essai de bout en bout : `logistique-expeditions-essai.py`.
Le **dernier kilomètre** depuis le tableau de bord (étape 025) : Livraisons › « Nouvelle livraison », « Remise au comptoir », et sur chaque
mission les gestes de son état (affecter selon `lg_rank_drivers`, code de livraison, replanifier, annuler) ; Tournées › « Nouvelle tournée ».
La **remise au comptoir** (confirmée par le propriétaire : ses clients retirent aussi au HUB) est une transition `AT_DESTINATION_HUB →
DELIVERED` qui exige SA preuve, `logistics.counter_handover` (ajout seul : qui retire, pièce, qui remet) ; « livré » reste impossible sans
preuve. 105 transitions. Essai : `logistique-comptoir-essai.py`.
Les **consolidations, unités logistiques et le transbordement** depuis le tableau de bord (étape 026) : Consolidations › « Nouvelle
consolidation », « Ajouter des colis » (`lg_fill_consolidation` : chaque numéro jugé seul, avec la raison de chaque refus), « Fermer »,
« Charger dans une unité » ; Consolidations › « Unités logistiques » (`lg_cc_load_units` : créer, charger, sceller, ouvrir avec motif, retirer
une consolidation avec motif) ; Expéditions › « Transbordement » (`lg_awaiting_onward`, puis `lg_create_onward_shipment`). La base refuse
désormais qu'une consolidation chargée parte AUSSI seule (`create_shipment` redéfinie), qu'une unité vide ou d'un autre mode parte, et
qu'une unité dont l'expédition n'est plus en brouillon change de contenu. Essai : `logistique-unites-essai.py`.
Un **client qui entre dans l'équipe** (étape 028) : sans colis ni facture, l'ancien schéma lui retire son code ; l'écart du rattrapage est expliqué (`became_staff`), la fiche du noyau reste, marquée compte d'équipe. Essai : `logistique-equipe-essai.py`.
La **bascule des colis** (étape 030, interrupteur `colisNoyau` de `config.js`, éteint par défaut) : **principe du propriétaire — le site, le
portail, le tableau de bord, les deux applications mobiles et l'application de bureau sont des clients qui parlent directement à Supabase, par
les MÊMES fonctions `lg_*`** ; aucun serveur intermédiaire. Allumée, un colis se crée (`lg_create_parcel`), se modifie (`lg_update_parcel`),
avance (`lg_parcel_next_steps`, `lg_move_parcels`) et s'annule (`lg_cancel_parcel`, jamais effacé) par le noyau ; le suivi public
(`ses_track`) et le profil (`lg_update_my_profile`) aussi. Le noyau décide du statut ; `public.colis` en garde le **reflet** (cinq statuts
d'avant), écrit sous `ses.reflet = on`, qui fait taire `historiser_colis` et `prevenir_client` (condition `WHEN` sur leurs déclencheurs,
reportée dans `supabase.sql` et `supabase-maj.sql`) : sinon chaque étape serait comptée deux fois. **Ne jamais réécrire `public.colis`
directement pour un colis sous l'autorité du noyau.** La facturation reste celle de l'ancien schéma (Finance : 031). Détail :
`docs/architecture/COLIS-NOYAU.md`.
**Expédier les colis confirmés** (étape 031, demande du propriétaire du 20/10/2026 : l'onglet Colis garde l'ancien parcours confirmé →
expédié → disponible → livré, `colisNoyau` éteint) : la fenêtre « Nouvelle expédition » (`lg_ready_for_shipment`, clé `confirmed`) propose
TOUS les colis confirmés ; `lg_create_shipment_prepared` les prépare (reçu, vérifié, rangé, à consolider — `prepare_parcels`) à l'entrepôt et à
l'emplacement choisis PUIS crée l'expédition, tout ou rien. Dès lors le colis suit son expédition : le reflet (030) écrit « expédié » au départ,
« disponible » au HUB ; l'onglet Colis ne peut plus changer SON statut (déclencheur `garde_statut_noyau`, erreur **SE005**) ; sa livraison passe par
Livraisons. Les autres colis gardent l'ancien parcours. Essai : `logistique-expedition-confirmes-essai.py`. La Finance devient **032**.
La **recopie** (double écriture) s'allume et s'éteint par `scripts/exploitation/interrupteurs.py` (workflow « Interrupteurs du noyau ») :
rattrapage prêt, puis `process_sync_queue()` planifiée chaque minute **dans la base** (pg_cron), puis l'interrupteur ; `etat` et `rapport` (le détail des écarts, sans valeur personnelle) se lisent sans rien changer. Éprouvé par
`outils/tests/migration-essai.py`.

**Speed Express Operations** (phase 10, ADR 0016) : l'application de bureau Windows et macOS est une enveloppe Tauri 2 autour des pages du site,
EMBARQUÉES (`bureau/preparer.mjs` copie ce que `deploy.yml` publie, et arrête tout si un secret s'y trouve) ; mêmes écrans, mêmes `lg_*`. Rust
n'ajoute que sept commandes (`lib.rs` : impression, imprimantes, étiquette brute vers une imprimante déclarée, lien externe, infos, mises à jour) ;
une seule capacité (`core:default`), navigation limitée aux pages internes. L'étiquette thermique est `SES_UI.zplEtiquette` (mêmes informations que
`etiquette()`, `^` et `~` neutralisés) : **changer l'étiquette HTML, c'est changer aussi le ZPL**. Le poste de scan a une **file hors ligne**
(`ses-poste.js`) : seulement les gestes qui peuvent attendre, même clé d'idempotence au rejeu, liée au compte connecté. Construction, signature,
canaux stable/bêta et recette : `docs/production/BUREAU.md` (workflow public `bureau.yml` sans secret, pour construire et éprouver ; publication signée depuis un dépôt privé, modèle `scripts/bureau/modele-workflow-publication.yml`, étiquettes `bureau-vX.Y.Z` et `bureau-beta-vX.Y.Z`).
Essais : `bureau-statique.py`, `bureau-contrat.cjs`, `poste-contrat.cjs`.

`outils/apercu-tableau.cjs` sert le tableau de bord en local, en démonstration, nourri par les réponses réelles des essais (aucune base) :
`node outils/apercu-tableau.cjs`, puis http://localhost:8767/tableau-de-bord.html (`?noyau=absent` : la production d'aujourd'hui).

L'**analytique** (phase 16, complétée par l'étape 029 en phase 12) vit dans son propre schéma, `analytics`, séparé du transactionnel : des faits
quotidiens calculés à partir des seuls journaux en ajout seul du noyau, chaque calcul tracé (source, version de calcul et empreinte du code,
empreinte des faits, état des sources, statut) et vérifiable. 42 mesures en cinq familles ; chacune déclare son **agrégation** (`sum` : un flux ;
`end` : un stock, la période vaut son dernier jour ; `distinct` : des clients distincts) — la base agrège, jamais l'écran. Une nouvelle mesure se
déclare dans `analytics.metric` (famille, agrégation, genre de dimension) ET se calcule dans `analytics.compute_facts` (029), puis reçoit son
texte `c-an-m-…` dans `outils/centre-textes.py` ; **changer `compute_facts`, c'est monter `analytics.calc_version()`** (les jours calculés avant
sont alors signalés « à recalculer » et le recalcul planifié les reprend). `analytique-contrat.cjs` exige un nom pour chaque mesure, indicateur,
alerte et sujet d'alerte. Alertes (`analytics.alert`, en ajout seul) : KPI impossible, données manquantes, recalcul non exécuté ou en échec,
anomalie. Recalcul planifié : `interrupteurs.py analytique-planifier` (pg_cron, dans la base). Détail : `docs/architecture/ANALYTIQUE.md`.

Les **applications mobiles** (phase 14) vivent dans le dépôt privé `~/Desktop/App_SES` : l'application client, et « SES Opérations »
pour l'équipe (chauffeur, entrepôt, livraison), construite avec `APP_VARIANT=operations` depuis une autre racine d'écrans. Elle ne parle
à la base que par `lg_my_staff_profile` et `lg_mobile_command` (migration 011) et quelques `lg_*` de lecture. Le test PostgreSQL
`logistique-applications-essai.py` écrit `outils/tests/applications-rpc.json` et `applications-formes.json` : **changer une de ces
fonctions** oblige à relancer ce test avec `SES_FORME_ECRIRE=1`, à recopier les deux fichiers dans `App_SES/tests/` (`rpc-noyau.json`,
`formes-noyau.json`) et à y lancer `npm run essai`. Détail : `docs/architecture/MOBILE-OPERATIONS.md`, ADR 0012.

## Base de données

Tables : `clients`, `colis`, `colis_historique`, `factures`, `prealertes`
(les achats annoncés par les clients, `supabase-maj-prix-prealertes.sql`), `appareils`
(téléphones à prévenir, section 9 de `supabase-maj.sql`) et `matricules_attribues`
(registre des identifiants d'équipe), plus deux vues, `colis_details` et
`factures_details`. Moins fournie que Goship (pas de lignes de facture séparées).
Ce qui est réellement passé en production, et ce qui ne l'est pas :
`docs/architecture/PRODUCTION-READINESS-AUDIT.md`.

Une bonne part de la facturation vit dans la base, pas dans le
navigateur : `facturer_colis()` crée la facture du colis dès son
enregistrement, `verifier_modification_colis()` empêche un client de toucher au
tarif ou aux montants de ses propres colis, et `definir_role()` applique la
hiérarchie des rôles (voir plus bas).

Les migrations sont dans `outils/*.sql`, à exécuter dans Supabase >
SQL Editor. Écris-les **rejouables sans risque** : `add column if not
exists`, valeurs par défaut neutres, aucune suppression.

**Supabase ouvre d'office** à `anon` et `authenticated` tout ce qui naît dans `public` (vérifié en production pour les fonctions) :
chaque migration **retire** ce qu'elle n'accorde pas (fonction interne : `revoke execute … from public, anon, authenticated` ;
table : `revoke truncate, references, trigger … from anon, authenticated`). Les essais reproduisent ces droits par défaut
(`_pgjetable.SUPABASE_DEFAUTS`) : `securite-catalogue.py` échoue sur un oubli. Une nouvelle migration s'ajoute à `ORDRE` dans
`schema-rejouable.py` **et** `securite-catalogue.py` (`migrations-garde-fou.py` le vérifie, et refuse toute instruction destructive).
Elle passe d'abord en **préproduction** (`outils/staging/`), puis en production après une sauvegarde « avant migration ».

Code client : préfixe **`SES-`** et cinq chiffres (`SES-43521`). Numéro de colis : **`SES-` et dix chiffres
tirés au hasard** (`SES-4821937065`), jamais deux fois le même, attribué par `preparer_colis()` (`supabase.sql`,
et `supabase-maj-numeros.sql` pour une base existante) ; les colis plus anciens gardent leur `SES-10003-HT`,
imprimé sur leur étiquette. Rien ne doit lire le pays ou un rang dans un numéro de colis.

## Facturation

- Le tarif est **propre à chaque colis** (`colis.tarif_lb`), fixé à
  l'enregistrement. Jamais de tarif global appliqué à tous les colis.
- Le prix **se calcule** (`poids_lb × tarif_lb`), sauf si l'équipe le **saisit à la main** dans le formulaire du colis
  (`colis.prix_manuel`, forfait ou geste commercial) : la facture prend alors ce prix. Vide, retour au calcul.
  `facturer_colis()` applique la règle ; le site et la démonstration la reflètent (`prixColis`, `facturerColis`).
- **10 $ de frais de service** par facture (`SES_API.FRAIS_SERVICE`),
  comptés une seule fois — y compris sur une facture groupée.
- Le tarif est **gelé avec la facture** : changer le tarif d'un colis ne
  retouche jamais une facture déjà émise.
- Une facture groupée réunit plusieurs colis **d'un même client**, jamais
  de clients différents.

## Rôles et permissions

Quatre rôles, du moins au plus de pouvoir :

| Rôle | Droits | Gère les rôles |
|---|---|---|
| `client` | aucun — **jamais** d'accès au tableau de bord | non |
| `employe` | ceux qu'on lui coche, un par un | seulement si `roles.gerer` lui est coché |
| `gerant` | tous les droits d'activité (colis, factures, clients) | employés et clients seulement |
| `admin` | tous | tout le monde, gérants et administrateurs compris |

La règle vit dans la **base** : `a_droit()`, `est_direction()` et
`definir_role()` dans `outils/supabase.sql`. Le navigateur ne fait que la
refléter pour l'affichage. Qui entre dans le tableau de bord se décide à un
seul endroit, `SES_API.accesTableauDeBord()` : fermé par défaut, il exige
d'être de l'équipe **et** de pouvoir lire quelque chose. Le contenu de la
colonne `droits` d'un client n'ouvre jamais rien.

**Chaque membre de l'équipe a un identifiant d'équipe** (`clients.matricule` : `ADM-`, `GER-` ou `EMP-` selon le rôle, et
quatre chiffres), donné par la base au moment où le rôle est attribué (déclencheur `attribuer_matricule`,
`supabase-maj-equipe.sql`). Il ne change QU'AVEC le rôle (un employé promu gérant reçoit un `GER-` neuf), ne se fournit jamais
à la main, et n'est jamais réutilisé : le registre `matricules_attribues` garde chaque identifiant donné, sans réécriture.

**L'équipe n'est pas la clientèle.** Un employé, un gérant ou un administrateur
n'a **pas de profil client** : pas d'identifiant `SES-#####`, aucun colis ni
facture rattachés, pas d'espace client (`espace-client.html` le renvoie au
tableau de bord), pas d'accès à l'application mobile. Le tableau de bord a deux
onglets distincts : **Clients** (la clientèle inscrite) et **Équipe** (les
comptes de l'équipe et leurs rôles). La base le garantit : `definir_role()`
retire l'identifiant en entrant dans l'équipe (et refuse si le compte a déjà
des colis ou des factures — erreur `SE001`), et le déclencheur
`verifier_client_rattache()` interdit de rattacher un colis ou une facture à un
compte d'équipe (`SE002`). Un compte d'équipe ne se crée pas depuis le tableau
de bord (il faudrait la clé secrète, qui ne doit jamais approcher un
navigateur) : la personne crée un compte normal, puis on la retrouve dans
« Équipe > Ajouter un membre ».

Ajouter un rôle touche cinq endroits : la contrainte et les fonctions SQL
(schéma **et** `supabase-maj.sql`), `ROLES` et `droitsDe` dans `ses-api.js`,
les **deux** implémentations de `definirRole`, les gabarits, les dictionnaires.
`roles-sql.cjs` (vrai PostgreSQL) et `roles-api.cjs` éprouvent la grille
complète : passe-les avant de publier.

## Différences avec Goship Express

| | Goship (GSE) | Speed Express (SES) |
|---|---|---|
| Interface globale | `window.GoshipAPI` | `window.SES_API` |
| Préfixe de fichiers | aucun (`api.js`) | `ses-` (`ses-api.js`) |
| Tableau de bord | `admin.html` | `tableau-de-bord.html` |
| Traductions | dossiers `en/ es/ ht/` | dictionnaires JS à l'exécution |
| Code client | `GSE-0000` | `SES-0000` |
| Tables | 10 + vue `colis_details` | 7 + vues `colis_details` et `factures_details` |
| Facturation | 5 $/lb + 10 $ de frais, tarifs gelés | tarif par colis + 10 $ de frais, tarifs gelés |

Ne copie jamais un fichier d'un projet vers l'autre sans adapter ces
sept points.

Les deux sites sont publiés sur le même domaine
`wilnergraph92.github.io` : ils **partagent donc le même
`localStorage`**. Ne reconnais jamais une session sur la seule allure
d'une clé `sb-*-auth-token` — un visiteur connecté chez Goship
passerait pour connecté ici. `ses-entete.js` reconstruit le nom exact de
la clé à partir de l'URL Supabase du projet.

## Travailler et vérifier

Sers le dossier en local : le mode démo s'active tout seul, sans
configuration.

Avant de publier :

```bash
bash outils/tests/verifier.sh
```

Les suites statiques et de contrat (qualité, publication, secrets — fichiers et historique —, garde-fou des migrations, traductions,
tableau de bord, performances, SEO, accessibilité, API, rôles, portail, centre, notifications, poste de scan, analytique, exploitation,
préproduction, surveillance) ne modifient aucun fichier. Les rôles sur un vrai PostgreSQL
(WASM) demandent un dossier contenant `@electric-sql/pglite` ; le noyau 001 à 013 et la sauvegarde de bout en bout, des binaires
PostgreSQL (`SES_PG_BIN`) et `age`. La CI (`qualite.yml`) les fait tous tourner avant chaque mise en ligne :

```bash
SES_TEST_DEPS=/chemin/du/dossier SES_PG_BIN=/chemin/des/binaires bash outils/tests/verifier.sh
```

L'**essai de charge** (`outils/tests/charge-essai.py`, hors de `verifier.sh` : 1 000 connexions) se lance à la main avant une ouverture plus
large ; ses résultats et le verdict de mise en service sont dans `docs/production/GO-LIVE-CERTIFICATE.md`.

**Pour monter le numéro de version du cache, une seule commande** :

```bash
python3 outils/versionner.py
```

Ne le fais jamais à la main. Ce numéro (`?v=31`) force le navigateur d'un
visiteur de retour à recharger les fichiers modifiés ; il est écrit à quatre
endroits (`mise-en-page.py`, `pages-espace.py`, `accessibilite.py`,
`lang-switcher.js`) **et en dur, plus de deux cents fois, dans
`outils/pages/`**. En oublier un sert de vieux fichiers sans rien signaler :
`lang-switcher.js` était ainsi resté deux versions en arrière, et un
visiteur de retour n'aurait pas reçu les nouvelles traductions. L'outil les
met tous à jour, vérifie qu'il ne reste aucun ancien numéro, puis régénère.
Sans lui, un test local peut aussi mentir : le navigateur resserre le vieux
fichier tant que `?v=` ne change pas.

Déploiement : **GitHub Pages depuis `main`**
(`git@github.com:wilnergraph92/speed-express-site.git`), par PR : la fusion lance la CI, puis le déploiement attend
l'approbation du propriétaire. La production est surveillée toutes les 15 minutes (`.github/workflows/surveillance.yml`,
lecture seule) ; une panne ouvre un ticket `alerte-production`.

Messages de commit : une phrase en français qui dit ce que ça change
pour l'utilisateur, pas un préfixe technique.

## Pièges

- Une page retouchée à la racine est perdue à la génération suivante :
  la source est dans `outils/pages/`.
- Une chaîne ajoutée sans entrée de dictionnaire reste en français dans
  les trois autres langues, silencieusement.
- Un champ numérique laissé vide part en `''`, que Postgres refuse pour
  une colonne `numeric`. `normaliserNombres()` dans `ses-api.js` traduit
  le vide avant l'envoi : passe par lui pour tout nouveau champ chiffré.
- `config.js` contient la clé Supabase : ne la recopie pas dans un
  fichier d'essai qui serait ensuite commité.
- Le Shadow DOM du sélecteur de langue isole ses styles : une règle CSS
  globale ne l'atteindra pas.
- `_headers` n'est pas lu par GitHub Pages : les en-têtes de sécurité
  qu'il décrit ne s'appliquent pas aujourd'hui.
