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
  dépôt moins quelques fichiers de travail : `.github`, `.claude`,
  `outils/` et `README.md` sont retirés par
  `.github/workflows/deploy.yml`. Tout le reste est servi tel quel — y
  compris ce fichier, lisible par n'importe qui à l'adresse
  `/CLAUDE.md`. N'y dépose jamais de secret.

## Architecture

```
index.html, …                    28 pages à la racine — GÉNÉRÉES
outils/pages/                    les 28 sources : c'est ici qu'on écrit
outils/communs/                  en-tête, pied, composants partagés
outils/espace/                   fragments des 5 pages de comptes
assets/js/                       toute la logique (27 fichiers)
outils/*.sql                     migrations Supabase
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
'supabase'`. Toute autre méthode sans jumelle est un bug, pas un choix.

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

## Base de données

Tables : `clients`, `colis`, `colis_historique`, `factures`, plus deux
vues, `colis_details` et `factures_details`. Moins fournie que Goship
(ni notifications, ni préalertes, ni lignes de facture séparées).

Une bonne part de la facturation vit dans la base, pas dans le
navigateur : `facturer_colis()` crée la facture du colis dès son
enregistrement, et `verifier_modification_colis()` empêche un client de
toucher au tarif ou aux montants de ses propres colis.

Les migrations sont dans `outils/*.sql`, à exécuter dans Supabase >
SQL Editor. Écris-les **rejouables sans risque** : `add column if not
exists`, valeurs par défaut neutres, aucune suppression.

Code client : préfixe **`SES-`**.

## Facturation

- Le tarif est **propre à chaque colis** (`colis.tarif_lb`), fixé à
  l'enregistrement. Jamais de tarif global appliqué à tous les colis.
- Le prix **se calcule, il ne se saisit pas** : `poids_lb × tarif_lb`.
- **10 $ de frais de service** par facture (`SES_API.FRAIS_SERVICE`),
  comptés une seule fois — y compris sur une facture groupée.
- Le tarif est **gelé avec la facture** : changer le tarif d'un colis ne
  retouche jamais une facture déjà émise.
- Une facture groupée réunit plusieurs colis **d'un même client**, jamais
  de clients différents.

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

Sept suites : qualité, traductions, tableau de bord, performances, SEO,
accessibilité, API. Elles ne modifient aucun fichier.

**Le numéro de version du cache se change à trois endroits à la fois** :
`VERSION` dans `outils/mise-en-page.py`, `VERSION` dans
`outils/pages-espace.py`, et `var V` dans `assets/js/lang-switcher.js`.
En oublier un sert de vieux scripts à un visiteur qui revient.

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
