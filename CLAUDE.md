# Speed Express Shipping — site et espace client

Site vitrine et espace client d'une entreprise de transport de colis.
Site statique, sans build : les fichiers du dépôt sont exactement ceux
qui sont servis.

Projet frère de **Goship Express** (`~/Desktop/Website_GSE`) : même ADN,
mais plusieurs choix diffèrent. Voir « Différences avec Goship » plus
bas avant de transposer quoi que ce soit d'un projet à l'autre.

## Avant de toucher au code

- **Tout est commenté en français**, avec les accents, dans un ton qui
  explique le pourquoi plutôt que le quoi. Les noms de variables et de
  fonctions sont en français.
- **Aucune étape de compilation.** Pas de bundler, pas de framework.
  JavaScript ES5 dans des IIFE, `var`, pas de modules.
- **La racine du dépôt est la racine du site déployé.** Tout fichier
  ajouté ici part en ligne. N'y dépose jamais de secret ni de fichier de
  travail.

## Architecture

```
index.html, …                    28 pages à la racine
tableau-de-bord.html             tableau de bord équipe
outils/espace/                   variantes de l'espace client
assets/js/                       toute la logique (22 fichiers)
outils/*.sql                     migrations Supabase
```

### Les fichiers JavaScript

Les fichiers propres au projet portent le préfixe **`ses-`** :

| Fichier | Rôle |
|---|---|
| `ses-api.js` | Couche de données, `window.SES_API`. Le cœur (1350 lignes). |
| `ses-admin.js` | Tableau de bord équipe |
| `ses-espace.js` | Espace client |
| `ses-compte.js` | Comptes, connexion |
| `ses-ui.js` | Affichage partagé : statuts, dates, montants, étiquette, facture |
| `ses-entete.js` | En-tête et navigation |
| `ses-anim.js` | Animations |
| `ses-villes.js` | Liste des villes de livraison |
| `lang-dict*.js` | 11 dictionnaires de traduction |
| `lang-switcher.js` | Sélecteur de langue — Web Component en Shadow DOM |
| `config.js` | Clés Supabase et réglages — **contient des secrets** |

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

Tables : `clients`, `colis`, `colis_historique`, `factures`. Moins
fournie que Goship (ni notifications, ni préalertes, ni lignes de
facture séparées).

Les migrations sont dans `outils/*.sql`, à exécuter dans Supabase >
SQL Editor. Écris-les **rejouables sans risque** : `add column if not
exists`, valeurs par défaut neutres, aucune suppression.

Code client : préfixe **`SES-`**.

## Différences avec Goship Express

| | Goship (GSE) | Speed Express (SES) |
|---|---|---|
| Interface globale | `window.GoshipAPI` | `window.SES_API` |
| Préfixe de fichiers | aucun (`api.js`) | `ses-` (`ses-api.js`) |
| Tableau de bord | `admin.html` | `tableau-de-bord.html` |
| Traductions | dossiers `en/ es/ ht/` | dictionnaires JS à l'exécution |
| Code client | `GSE-0000` | `SES-0000` |
| Tables | 8 + vue `colis_details` | 4 |
| Facturation | 5 $/lb + 10 $ de frais, tarifs gelés | pas de tarification automatique |

Ne copie jamais un fichier d'un projet vers l'autre sans adapter ces
sept points.

## Travailler et vérifier

Sers le dossier en local : le mode démo s'active tout seul, sans
configuration.

Déploiement : **GitHub Pages depuis `main`**
(`git@github.com:wilnergraph92/speed-express-site.git`). Un
`git push origin main` met le site en ligne.

Messages de commit : une phrase en français qui dit ce que ça change
pour l'utilisateur, pas un préfixe technique.

## Pièges

- Une chaîne ajoutée sans entrée de dictionnaire reste en français dans
  les trois autres langues, silencieusement.
- `config.js` contient la clé Supabase : ne la recopie pas dans un
  fichier d'essai qui serait ensuite commité.
- Le Shadow DOM du sélecteur de langue isole ses styles : une règle CSS
  globale ne l'atteindra pas.
