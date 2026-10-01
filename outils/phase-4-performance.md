# Phase 4 — Performance

Date : 30 septembre 2026. Branche : `arena/01a0f433-speed-express-site`.

Périmètre demandé : E-14, M-01, M-23, M-24, F-01, F-02. Aucun changement de
contenu, de texte, de couleur ou de fonctionnalité. **Aucun déploiement, aucun
commit, aucune modification de Supabase.**

## 1. Mesures avant / après

Mesures reproductibles dans un Chromium local (390 × 844, DPR 2, réseau
externe bloqué), en servant l'état d'avant (`/home/user/.cache/perf-baseline`)
et l'état d'après depuis le même serveur. **Ce ne sont pas des mesures
Lighthouse ni des mesures sur Internet réel** : Lighthouse n'est pas exécutable
ici, et les domaines externes sont inaccessibles depuis la sandbox.

| Indicateur (accueil, mobile) | Avant | Après | Écart |
| --- | --- | --- | --- |
| Octets des fichiers locaux demandés | 1 146 471 | 746 127 | −400 344 (−34,9 %) |
| Requêtes locales | 17 | 14 | −3 |
| Dictionnaires chargés au premier écran (visite FR) | 3 fichiers (96 570 o) | 0 | −96 570 o |
| Images du carrousel (avion + navire) | JPEG natifs | WebP 800 px | −339 906 o |
| Image LCP observée | `ses-truck-800.jpg` (49 863 o) | `ses-truck-800.webp` (34 086 o) | −15 777 o (−31,6 %) |
| Parcours TreeWalker de traduction | 2 | 0 | −2 |
| Géométrie mobile (entête, hero, image, section Pourquoi) | — | identique | aucune régression visuelle |

Détail des fichiers modifiés par le serveur : `lang-dict.js`, `lang-dict-2.js`,
`lang-dict-3.js` et les JPEG du carrousel ne sont plus demandés du tout à
l'accueil en français ; ils sont remplacés par `ses-truck-800.webp`,
`hero-avion-800.webp`, `hero-navire-800.webp`.

Réserve importante : le double chargement de `ses-anim.js` décrit dans l'audit
n'est **pas reproductible dans ce checkout**. Contrôle sur les 28 pages : une
seule balise par page, aucun doublon d'aucun script. La correction demandée
(dédoublonnage dans le générateur) existe déjà (`animations()` +
`_unique_script`), et elle est désormais **testée** par injection d'une page
contenant deux balises. De même, `__bundler_thumbnail` est absent des 28 pages ;
la suppression à la source est testée sur un gabarit factice.

## 2. Fichiers modifiés

Générateurs (les pages sont régénérées à partir d'eux) :
- `outils/mise-en-page.py` : étapes **ciblées** ajoutées — `performance_images`,
  `dictionnaires_differe` ; règle `preconnect_images_externes` affinée ;
  `VERSION` 27 → **28**.
- `outils/pages-espace.py` : dédoublonnage de la liste de scripts,
  `lang-dict.js` retiré du chargement direct, `VERSION` 28.

Exécution : `python3 outils/mise-en-page.py --etapes=performance_images,preconnect_images_externes,version_scripts,dictionnaires_differe`,
puis relancée pour vérifier l'idempotence (0 page modifiée la seconde fois).
La liste complète des étapes n'est **pas** relancée : ses blocs CSS sont plus
anciens que ceux des pages et écraseraient le design actuel.

Code :
- `assets/js/lang-switcher.js` : dictionnaires chargés **à la demande**,
  visite française sans téléchargement, cache des parties déjà chargées,
  nouvelle tentative sur échec réseau, code de langue stocké validé,
  parcours de traduction limité aux nœuds ajoutés ou modifiés.
- `assets/img/` : 14 dérivées WebP générées (`ses-truck`, `hero-avion`,
  `hero-navire` en 480/800/1200/natif ; `ses-camion-colis` en 480 et 800) ;
  `favicon-180.png` réencodé sans perte (11 909 → 5 049 o) ;
  `favicon-32.png` conservé tel quel (déjà natif 32 × 32, sans perte possible).
- Les 28 pages : `<picture><source type="image/webp">` pour les trois photos du
  carrousel et l'accueil, `srcset`/`sizes` pour la camionnette, préchargement
  aligné sur la variante WebP réellement affichée, `preconnect` Unsplash
  uniquement là où une photo distante est visible sans `lazy`,
  `lang-dict.js` retiré du HTML.
- `assets/js/*.js` : versions `?v=28` (cache navigateur).

Outils et tests ajoutés :
- `outils/optimiser-images.cjs`, `outils/optimiser-favicons.cjs` (dépendance
  `sharp` externe, hors du dépôt ; aucune dépendance runtime pour le site).
- `outils/inventaire-images-phase4.csv` : inventaire complet (59 fichiers).
- `outils/tests/performance-static.py`, `outils/tests/performance-browser.mjs`.
- `outils/phase-4-performance.md`, `README.md`.

## 3. Ce qui a été corrigé, point par point

**E-14 / images.** Audit des 45 images d'origine (voir le CSV). Tout passe
aujourd'hui en WebP pour les navigateurs modernes, les JPEG/WebP d'origine
restant les replis : aucune image n'est supprimée, aucun cadrage changé.
- `ses-truck.jpg` (146 709 o, 1584 × 672) : variantes WebP 16 104 / 34 086 /
  61 080 / 90 384 o, `srcset` + `sizes="100vw"` conservés, préchargement
  `fetchpriority="high"` aligné sur la variante WebP. C'est bien l'image LCP
  observée avant comme après (vérifié par `PerformanceObserver`).
- `ses-camion-colis.webp` (224 738 o) : `srcset` 480/640/800/1280 et `sizes`.
  Cette photo est **visible sur mobile dans la version actuelle** ; la masquer
  serait une régression visuelle, elle est donc conservée. Aucun
  `<picture media>` qui cache une image visible n'a été ajouté sur l'accueil.
- Le camion décoratif de l'ancien hero (`outils/mise-en-page.py`, `CAMION`)
  reste, lui, protégé par `<source media="(min-width: 900px)">` et une image
  vide : un test de navigateur vérifie qu'à 390 px aucun octet de cette WebP
  n'est demandé, et qu'à 1280 px elle est bien chargée.

**M-01 / ses-anim.js.** Aucune page ne le charge deux fois (28/28 vérifiées) ;
la protection du générateur est testée sur une page fabriquée contenant un
doublon. Aucune correction manuelle de page n'a été nécessaire.

**M-23 / dictionnaires.** 405 848 o au total, répartis en 11 fichiers dont
seulement 1 à 3 par page. Le dictionnaire commun était chargé même en français.
Désormais : visite française = **0 octet** de dictionnaire ; changement de
langue = chargement parallèle dans l'ordre, uniquement les parties de la page ;
seule une partie en échec réseau est retentée. Le parcours de traduction ne
visite plus tout le document à chaque mutation : il se limite aux nœuds ajoutés
ou modifiés (1 parcours pour 1 sous-arbre ajouté, mesuré), et plus rien du tout
en français. FR/EN/ES/HT sont testés dans le navigateur, y compris la
restauration du français, le contenu ajouté dynamiquement et la traduction des
gabarits `[data-textes]` des pages de l'espace client.

**M-24 / ressources externes.** 18 pages utilisent `images.unsplash.com`.
Les 16 pages dont une photo distante est affichée sans `lazy` gardent le
`preconnect` (pertinent) ; l'accueil et le blog, où toutes les photos distantes
sont en `lazy`, ne le demandent plus. Toutes les images distantes portent
`referrerpolicy="no-referrer"` et un `data-fallback` local, appliqué une seule
fois en cas d'échec (testé réseau bloqué). Aucune photo officielle Speed Express
n'a été remplacée par une image distante, et aucune image distante n'a été
remplacée par une autre photo locale différente — cela aurait changé le rendu.

**F-01 / favicons.** `favicon-32.png` est bien un 32 × 32 natif (1 090 o),
`favicon-180.png` un 180 × 180 natif, déclarés avec les bons `sizes`. Une
512 × 512 n'est pas servie comme icône 32 : il n'y a ni manifeste ni usage
PWA, donc aucune 512 n'a été fabriquée (une icône de plus serait un octet
inutile). Le 180 a été réencodé sans perte.

**F-02 / `__bundler_thumbnail`.** Absent des 28 pages. La suppression reste
faite dans le générateur (`retirer_template_bundler`, présent aussi dans
`convertir-export.py` pour les réexports) et est vérifiée sur un gabarit
factice à chaque exécution des tests.

## 4. Tests exécutés (tous réussis)

1. `python3 outils/tests/performance-static.py` — les 28 pages : un seul
   `ses-anim.js`, aucun script dupliqué, aucune `__bundler_thumbnail`, toutes
   les ressources locales existent, `referrerpolicy` + repli local sur chaque
   image distante, étapes du générateur idempotentes, syntaxe JS/Python.
   Inclut des gabarits fabriqués (doublon de script, template résiduel,
   `<picture media>` du camion, preconnect sans/avec image visible).
2. `AWS_EXECUTION_ENV=AWS_Lambda_nodejs22.x SES_TEST_DEPS=… node outils/tests/performance-browser.mjs`
   — navigateur isolé, réseau externe bloqué :
   - accueil en français : 0 dictionnaire, 0 parcours de traduction ;
   - FR → EN → ES → HT → FR, chargement direct en EN/ES/HT, restauration du
     français, contenu ajouté dynamiquement traduit, attributs traduits,
     une seule partie retéléchargée après un échec simulé ;
   - image LCP et variantes réellement choisies (800 px en mobile DPR 2) ;
   - 320, 360, 390, 414, 768, 1024, 1280, 1440 px : aucun débordement, toutes
     les images du carrousel décodées ;
   - camionnette/colis visible et décodée, repli local appliqué une seule fois
     quand le CDN est injoignable, carrousel toujours fonctionnel ;
   - géométrie mobile identique à l'état d'avant (comparaison programme) ;
   - les 24 pages publiques : un seul `ses-anim.js`, zéro dictionnaire statique,
     zéro `__bundler_thumbnail`.
3. Non-régression des phases précédentes : `outils/tests/dashboard-static.py`,
   `dashboard-api.cjs`, `dashboard-sql.cjs` (PGlite) et `dashboard-browser.mjs`
   (8 largeurs, états vide/erreur/migration, navigation, permissions) — tous
   réussis après les changements de dictionnaires et d'images.

## 5. Régressions et limites connues

- **Lighthouse non exécuté** : impossible dans cette sandbox. Les chiffres
  ci-dessus sont des mesures de laboratoire sur serveur local, pas un audit
  Lighthouse ni une mesure d'utilisateurs réels.
- **Réseau externe inaccessible** : le comportement réel d'Unsplash et de
  Google Fonts (latence, `preconnect`, disponibilité des replis) est testé par
  interception, pas sur Internet.
- **Le dépôt grossit** : +14 dérivées WebP, `assets/img` passe de 3,59 Mo à
  4,51 Mo (+0,92 Mo). Le premier chargement mobile baisse, mais le poids du
  dépôt/déploiement augmente ; les JPEG d'origine sont conservés comme replis
  (suppression non destructive volontaire). Ces dérivées peuvent être
  regénérées avec `outils/optimiser-images.cjs`.
- **Camionnette « chargée puis masquée »** : signalée par l'audit, non
  reproductible ici sur les pages actuelles (image visible sur mobile). Une
  règle `media` générique n'a pas été appliquée sur l'accueil pour ne pas
  masquer une image affichée ; seule l'ancienne structure décorative est
  couverte et testée.
- **Dictionnaires** : une visite non française charge toujours les parties de
  sa page (comportement inchangé) ; sans JavaScript, la page reste en français
  (inchangé). `window.SES_DICT` n'est plus disponible avant le premier
  changement de langue — vérifié : aucun autre script du dépôt ne l'utilise.
- **Version 28** : les fichiers JS changent d'adresse une fois, ce qui
  invalide le cache des visiteurs (c'est le but), au prix d'un rechargement.
- Les polices Google restent externes (deux `preconnect` en tête de page) :
  hors périmètre de cette phase.

## 6. Arrêt

Aucun commit, push ou déploiement. Modification sauvegardée sur la branche de
session. La suite attend une validation explicite ; le module Rapports n'est
pas commencé.
