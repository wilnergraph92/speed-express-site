# Phase 7 — Qualité du code et unification

Date : 2026-10-01. Périmètre : les **28 pages HTML** publiées.

## Résultats

| Contrôle | Avant mesuré | Après |
|---|---:|---:|
| Pages utilisant Archivo | 16 | 0 |
| Pages utilisant Saira | 12 | 28 |
| Liens vers une ancre inexistante | 85 | 0 |
| Attributs `style-hover` | 883 | 0 |
| Variables CSS utilisées sans définition ni fallback | — | 0 |
| Scripts externes chargés deux fois dans une page | — | 0 |
| Erreurs de structure détectées par la nouvelle suite | 1 balise option mal formée | 0 |

Les estimations initiales de 35 ancres et environ 850 survols ne correspondaient
pas au dépôt de départ. Les 85 occurrences mesurées se répartissaient en :

- 68 liens `nos-services.html#services` ; les liens nommés pointent maintenant
  vers `#consolidation`, `#maritime`, `#aerien`, `#dedouanement` ; une demande
  générale de services pointe vers la section existante `#transport` ;
- 16 liens `index.html#adresse` → `nos-services.html#adresse-usa` ;
- 1 lien `#top` de la 404, résolu par `id="top"` sur son `body`.

Aucune section fictive créée. Les 883 anciens attributs sont éliminés de la
sortie ; les effets utiles sont représentés par **10 classes CSS partagées**
avec `:hover` et `:focus-visible`, sans interpréteur JavaScript. Les composants
uniformisés réutilisent ces classes. `!important` est limité aux propriétés
qui doivent prendre le dessus sur les styles inline hérités.

## Sources et générateurs

Sources ajoutées ou modifiées :

- `outils/pages/*.html` : 28 sources versionnées (23 pages de contenu et
  5 enveloppes de comptes), issues des pages publiées avant cette phase ;
- `outils/communs/entete.html`, `outils/communs/pied.html` : composants Saira
  uniques, navigation dans le même ordre, page active calculée à la génération ;
- `outils/espace/tableau-de-bord.html` : correction de
  `</option value="aerien">` en `</option><option value="aerien">` ; les autres
  fragments métier restent inchangés ;
- `assets/css/ses-base.css`, `ses-design.css`, `ses-entete.css`, `ses-espace.css`,
  `ses-survols.css` : typographie, variables, styles communs et états interactifs ;
- `README.md`, `.gitignore` : documentation de la chaîne et exclusion des caches.

Générateurs :

- `outils/mise-en-page.py` : la commande par défaut régénère les sources,
  puis appelle le générateur des comptes. L'ancien lancement intégral des
  retouches obsolètes est supprimé. `--etapes` est refusé explicitement ;
- `outils/pages-espace.py` : simplifié ; ne copie plus Contacts ni ses metadata.
  Assemble les enveloppes SEO et les fragments métier dédiés ;
- `outils/unification.py` : développement des composants, sélection du menu
  actif, normalisation Saira, migration ciblée des ancres et des survols.

Les anciennes fonctions de migration de `mise-en-page.py` restent importables
pour les tests historiques ; elles ne sont pas rejouées sur les sorties.
Aucune bibliothèque, aucun bundler ni framework ajouté au site.

## Régénération et conservation

**28 pages régénérées**, dont 5 comptes. Second passage : sorties identiques.
Le contrôle qualité compare aussi chaque sortie à sa source assemblée.

Comparaison contre les fichiers sauvegardés avant intervention :

- textes du contenu principal identiques sur 28/28 pages ;
- URLs d'images du contenu principal identiques sur 28/28 pages ;
- titres, metadata, canonical et JSON-LD identiques sur 28/28 pages.

Résultat détaillé : `outils/tests/phase7-comparaison.json` (constat de migration,
non un audit navigateur). Les URLs de pages sont inchangées ; seules les
ancres erronées et les composants communs sont normalisés. Aucun fichier
SQL, configuration de service, stockage client ou donnée métier n'a été modifié.

## Tests

Commande légère, sans téléchargement ni réseau :

```sh
python3 outils/mise-en-page.py
bash outils/tests/verifier.sh
```

Suite exécutée avec succès :

- **nouveau** `qualite-static.py` : inventaire 28 pages et sources, fichiers et
  ressources internes, ancres, IDs uniques, références ARIA, attributs doublés,
  imbrication HTML, repères essentiels, scripts externes uniques, syntaxe des
  scripts inline, JSON-LD, metadata, variables CSS et synchronisation sources ;
- **nouveau** `i18n.cjs` : 11 dictionnaires, 1 580 entrées ayant chacune trois
  traductions non vides, unicité des clés `data-t` et présence des clés
  littérales utilisées par l'espace client et le dashboard ;
- `dashboard-static.py` adapté au nouveau générateur, syntaxe de tous les JS
  sous `assets/js` et des fichiers Python ;
- suites existantes performance statique, SEO, accessibilité statique, API
  dashboard : toutes passent ;
- `git diff --check` sans erreur.

Le contrôle CSS accepte les variables avec fallback. La référence ARIA
`ses-fiche-titre` du dashboard est explicitement reconnue comme dynamique,
avec vérification de sa présence dans le script qui remplit la fiche avant
son ouverture. Les headers internes au dashboard sont légitimes.

## CI avant publication

- **ajout** `.github/workflows/qualite.yml` : pull requests, branches de travail,
  lancement manuel et workflow réutilisable ; Python 3.12 et Node 22 ; suite
  légère et contrôle de régénération sans diff ;
- **modification** `.github/workflows/deploy.yml` : la préparation et la
  publication GitHub Pages dépendent désormais de la réussite du job qualité.

Aucun score esthétique, capture pixel-perfect, style de formatage ou score
Lighthouse ne bloque la publication. Les dépendances du navigateur ne sont
pas requises par cette CI légère. Le workflow est configuré et la même suite
passe localement ; aucune exécution GitHub distante n'est revendiquée.

## Limites et erreurs restantes

**Aucune erreur restante détectée par la suite statique et les tests API.**

Le smoke test optionnel `outils/tests/qualite-browser.mjs` a maintenant été
**exécuté avec succès sur les 28 pages, en 1440 px et 390 px** : header/footer
visibles, police calculée Saira, ouverture/fermeture du menu mobile et aucune
exception JavaScript non interceptée. Le réseau métier et les appels externes
étaient neutralisés : ce n'est pas un test de connexion Supabase en production.

Le blocage initial `libnspr4.so` a été résolu sans modifier le site : extraction
des bibliothèques fournies avec `@sparticuz/chromium`, hors dépôt, puis ajout
à `LD_LIBRARY_PATH` pour le processus de test. Commande utilisée :

```sh
LD_LIBRARY_PATH=/home/user/test-deps/lib \
SES_TEST_DEPS=/home/user/test-deps node outils/tests/qualite-browser.mjs
```

Ces dépendances optionnelles ne sont pas ajoutées au dépôt ni requises par la
CI légère. Le test ne constitue pas une comparaison visuelle pixel-perfect.

Les liens externes ne sont pas sondés ; les contrôles portent sur les liens
internes. Le contrôle i18n vérifie la structure et les clés explicites, pas
la qualité linguistique ni la couverture exhaustive de tout texte libre.
Les tests SQL d'intégration et les connexions Supabase réelles sont hors du
périmètre de cette suite sans dépendances ; aucune base n'a été contactée.
