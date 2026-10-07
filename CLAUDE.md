# Speed Express Shipping — site et espace client

Site vitrine et espace client d'une entreprise de transport de colis.
Site statique, sans build : les fichiers du dépôt sont exactement ceux
qui sont servis.

Projet frère de **Goship Express** (`~/Desktop/Website_GSE`) : même ADN,
mais plusieurs choix diffèrent. Voir « Différences avec Goship » plus
bas avant de transposer quoi que ce soit d'un projet à l'autre.

## Avant de toucher au code

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
  `outils/`, `docs/`, `scripts/`, `README.md`, `CLAUDE.md`, `SECURITY.md` et
  `ARCHITECTURE-BASELINE.md`. Tout le reste est servi tel quel. Un nouveau
  fichier de travail à la racine s'ajoute à cette liste : le test
  `outils/tests/publication.py` échoue sinon. N'y dépose jamais de secret.

## Architecture

```
index.html, …                    28 pages à la racine — GÉNÉRÉES
outils/pages/                    les 28 sources : c'est ici qu'on écrit
outils/communs/                  en-tête, pied, composants partagés
outils/espace/                   fragments des 5 pages de comptes
assets/js/                       toute la logique (38 fichiers)
outils/*.sql                     migrations Supabase
docs/, ARCHITECTURE-BASELINE.md     l'existant décrit (docs/current-state/), la cible (docs/architecture/), l'exploitation (docs/production/), jamais publié
outils/securite.py               politique de contenu, référent, anti-cadre : posés dans chaque page à la génération
outils/logistique/               noyau logistique (schémas « logistics », « analytics » pour les rapports, « ops » pour l'exploitation), migrations 001 à 013, NON appliquées
outils/tests/                    la suite de vérification
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
| `ses-api.js` | Couche de données, `window.SES_API`. Le cœur (1616 lignes). |
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
| `ses-analytique.js` | L'analytique du centre de commande (phase 16, ADR 0014) : rapports du jour à l'année, indicateurs avec la période précédente, jours jamais calculés signalés, exécutions tracées et vérifiables. Aucun chiffre calculé ici, pas même une addition : tout vient de `SES_API.analytique` (`public.lg_an_*`) |
| `ses-prealertes.js` | L'onglet « Pré-alertes » du tableau de bord : les achats annoncés par les clients depuis l'application (table `public.prealertes`, `supabase-maj-prix-prealertes.sql`). Visible avec « colis.lire » et si la table existe ; traitement (reçue, annulée) avec « colis.statut » ou « colis.modifier ». Tout passe par `SES_API.prealertes` |
| `ses-sante.js` | La santé du système, dans le centre de commande (phase 17, ADR 0015), pour la direction : quinze contrôles avec seuils et verdict de la base, derniers signaux des travaux planifiés, dernières erreurs des navigateurs. Tout vient de `SES_API.exploitation` (`public.lg_ops_status`) |
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
fonctions qui contrôlent les droits. Détail : `docs/architecture/NOTIFICATIONS.md`.

L'**exploitation** (phase 17, étape 013, schéma `ops`) : `ses_health()` est la seule fonction ouverte aux visiteurs (« ok » et le niveau
de migration) ; la limitation de débit est faite par des **déclencheurs** sur les tables où écrivent les façades (erreur `LG007`, message
« trop de demandes ») — ne la déplace pas dans les façades, elle serait perdue au rejeu d'une étape antérieure ; `SES_API` signale à la base
les erreurs JavaScript d'un compte connecté (jamais sur une page publique). Les étapes se passent **dans l'ordre** ; rejouer une étape ancienne
après une plus récente n'est pas sûr (006 échoue). Procédures, seuils, retour en arrière : `docs/production/`.

L'**analytique** (phase 16) vit dans son propre schéma, `analytics`, séparé du transactionnel : des faits quotidiens calculés à partir des
seuls journaux en ajout seul du noyau, chaque calcul tracé (empreinte, état des sources) et vérifiable. Une nouvelle mesure se déclare dans
`analytics.metric` ET se calcule dans `analytics.compute_facts` (012), puis reçoit son texte `c-an-m-…` dans `outils/centre-textes.py` ;
`analytique-contrat.cjs` exige un nom pour chaque mesure. Détail : `docs/architecture/ANALYTIQUE.md`.

Les **applications mobiles** (phase 14) vivent dans le dépôt privé `~/Desktop/App_SES` : l'application client, et « SES Opérations »
pour l'équipe (chauffeur, entrepôt, livraison), construite avec `APP_VARIANT=operations` depuis une autre racine d'écrans. Elle ne parle
à la base que par `lg_my_staff_profile` et `lg_mobile_command` (migration 011) et quelques `lg_*` de lecture. Le test PostgreSQL
`logistique-applications-essai.py` écrit `outils/tests/applications-rpc.json` et `applications-formes.json` : **changer une de ces
fonctions** oblige à relancer ce test avec `SES_FORME_ECRIRE=1`, à recopier les deux fichiers dans `App_SES/tests/` (`rpc-noyau.json`,
`formes-noyau.json`) et à y lancer `npm run essai`. Détail : `docs/architecture/MOBILE-OPERATIONS.md`, ADR 0012.

## Base de données

Tables : `clients`, `colis`, `colis_historique`, `factures`, `prealertes`
(les achats annoncés par les clients, `supabase-maj-prix-prealertes.sql`), plus deux
vues, `colis_details` et `factures_details`. Moins fournie que Goship
(ni notifications, ni préalertes, ni lignes de facture séparées).

Une bonne part de la facturation vit dans la base, pas dans le
navigateur : `facturer_colis()` crée la facture du colis dès son
enregistrement, `verifier_modification_colis()` empêche un client de toucher au
tarif ou aux montants de ses propres colis, et `definir_role()` applique la
hiérarchie des rôles (voir plus bas).

Les migrations sont dans `outils/*.sql`, à exécuter dans Supabase >
SQL Editor. Écris-les **rejouables sans risque** : `add column if not
exists`, valeurs par défaut neutres, aucune suppression.

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
| Tables | 10 + vue `colis_details` | 4 + vues `colis_details` et `factures_details` |
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

Les suites statiques et de contrat (qualité, publication, traductions, tableau de bord, performances, SEO, accessibilité, API, rôles,
portail, centre, notifications, poste de scan, analytique, exploitation) ne modifient aucun fichier. Les rôles sur un vrai PostgreSQL
(WASM) demandent un dossier contenant `@electric-sql/pglite` ; le noyau 001 à 013 et la sauvegarde de bout en bout, des binaires
PostgreSQL (`SES_PG_BIN`) et `age`. La CI (`qualite.yml`) les fait tous tourner avant chaque mise en ligne :

```bash
SES_TEST_DEPS=/chemin/du/dossier SES_PG_BIN=/chemin/des/binaires bash outils/tests/verifier.sh
```

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
(`git@github.com:wilnergraph92/speed-express-site.git`). Un
`git push origin main` met le site en ligne.

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
