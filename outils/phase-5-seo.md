# Phase 5 — SEO et indexation

Date : 30 septembre 2026. Branche : `arena/01a0f589-speed-express-site`.

Périmètre : métadonnées de recherche, données structurées et fichiers
d'indexation des 28 pages. Aucun changement de contenu visible, de couleur,
d'image ou de fonctionnalité. **Aucun déploiement, aucune modification de
Supabase.** Deuxième passe après celle de la PR #12 (sitemap, canonical,
JSON-LD, Open Graph absolu, noindex des pages privées) ; cette phase couvre
ce que la première passe n'avait pas traité.

## 1. Audit avant / après

Contrôles rejoués en continu par `outils/tests/seo-static.py` (sans réseau) ;

les chiffres « avant » viennent du même script lancé sur le commit de base.

| Indicateur (28 pages) | Avant | Après |
| --- | --- | --- |
| Titres > 65 caractères (troncature probable dans les résultats) | 6 | 0 |
| Descriptions de pages publiques hors 70-165 caractères | 3 (+1 page noindex) | 0 |
| Pages publiques sans aucune donnée structurée JSON-LD | 7 | 0 |
| Pages publiques déclarant un fil d'Ariane (`BreadcrumbList`) | 0 | 20 |
| Services déclarés aux moteurs (`Service` + ancre) | 0 | 7 |
| URL du sitemap avec `changefreq`, `priority` et image | 0 | 21 |
| Blocs JSON-LD invalides, liens internes cassés, images sans alt | 0 | 0 |

L'existant était déjà sain : un h1 par page, canonical et og:url cohérents,
JSON-LD valide partout où il existait (accueil, 11 articles, blog, contact),
og:image présents sur le disque, aucun lien interne cassé. La phase corrige
**des écarts d'affichage dans les résultats**, pas des erreurs bloquantes.

## 2. Fichiers modifiés

Générateurs (les pages sont régénérées à partir d'eux) :
- `outils/mise-en-page.py` : étapes **ciblées** ajoutées —
  `seo_phase5_meta` (titres et descriptions) et
  `seo_phase5_donnees_structurees` (fils d'Ariane et nœuds de page typés),
  toutes deux idempotentes.
- `outils/sitemap.py` : **nouveau** — régénère `sitemap.xml` depuis les
  pages (canonical + meta robots + og:image relues, jamais d'URL tapée à
  la main), conserve les `lastmod` existants, `--touches=` pour dater les
  pages effectivement modifiées.

Exécution : `python3 outils/mise-en-page.py --etapes=seo_phase5_meta,seo_phase5_donnees_structurees`,
relancée pour vérifier l'idempotence (0 page modifiée la seconde fois), puis
`python3 outils/sitemap.py` (21 URL), relancé à l'identique. La liste
complète des étapes n'est **pas** relancée : ses blocs CSS sont plus anciens
que ceux des pages (même réserve qu'en phase 4).

Pages (22 fichiers, balises `<head>` uniquement) :
- **6 titres resserrés** à 52-64 caractères, mot-clé en tête et marque
  raccourcie quand nécessaire : accueil et cinq articles
  (`boutiques-chinoises`, `impact-ecommerce`, `partenaire-colis-etranger`,
  `pourquoi-speed-express`, `service-de-messagerie`). `og:title` suit.
- **4 descriptions étoffées** à 126-141 caractères, sans aucune promesse
  absente de la page : `support`, `impact-ecommerce`, `tendances-2026`,
  `fermer-un-compte` (cette dernière est noindex ; alignée par cohérence).
  `og:description` suit.
- **Fils d'Ariane JSON-LD** sur les 20 pages publiques hors accueil :
  `Accueil > Blog > Article` pour les 11 articles, `Accueil > Page` pour
  les 9 autres. L'accueil est la racine du fil et ne se déclare pas.
- **Nœuds typés** sur les 7 pages qui n'avaient rien : `AboutPage` (à
  propos) et `WebPage` (services, suivi, support, marchandises dangereuses,
  termes, confidentialité), chacune raccordée par `@id` à l'organisation et
  au site déclarés dans `index.html`. `nos-services.html` reçoit en plus un
  `ItemList` des 7 services, pointant vers les ancres réelles de la page
  (`#maritime`, `#aerien`…), `areaServed` DO/HT/US.

Fichiers d'indexation :
- `sitemap.xml` régénéré : 21 URL indexables (les 7 pages noindex en restent
  exclues), `lastmod` ISO conservée à 2026-09-30, `changefreq` et
  `priority` sobres (accueil 1.0/weekly, piliers 0.8-0.9, articles 0.7,
  pages légales 0.3/yearly), et l'image `og:image` de chaque page déclarée
  via `xmlns:image` pour Google Images.
- `robots.txt` **inchangé** : déjà conforme (`Disallow: /outils/`, ligne
  `Sitemap:` absolue). Les pages privées n'y sont volontairement pas
  interdites : une page `noindex` doit rester explorable pour que la
  directive soit lue — la bloquer dans robots.txt la ferait apparaître
  dans les résultats *sans* son contenu.

Tests : `outils/tests/seo-static.py` (nouveau) rejoue l'audit complet ;
`outils/tests/dashboard-static.py` passe à l'identique.

## 3. Vérifications

- Idempotence démontrée des deux générateurs (relance = 0 modification).
- `git diff` relu : seules des balises `<title>`, `<meta>` et des blocs
  `<script type="application/ld+json">` changent ; **aucune chaîne visible
  du corps n'est touchée**, donc aucune entrée des dictionnaires
  `lang-dict*.js` (qui ne traduisent que `document.body` et jamais le
  `<head>`) n'est rendue caduque. Aucun changement de `VERSION` : aucun
  fichier JavaScript ou image n'a été modifié.
- Tous les blocs JSON-LD (existants et nouveaux) sont parsés à l'exécution
  par le test ; positions des fils d'Ariane continues, URL absolues,
  ancres des services vérifiées présentes dans `nos-services.html`.

## 4. Limites, honnêtement

- **Pas de hreflang** : les quatre langues sont servies par la même URL et
  traduites à l'exécution par dictionnaires JS ; déclarer des versions
  linguistiques exigerait des URL distinctes (`/en/…`), ce qui sort du
  périmètre d'un site statique sans build. Conséquence assumée : seules
  les métadonnées françaises du `<head>` sont indexées.
- **Validation rich results impossible ici** : les blocs sont
  structurellement valides (parsés, schémas respectés) mais le test
  officiel Google (search.google.com/test/rich-results) reste à lancer en
  ligne, de même que l'envoi effectif du sitemap dans Search Console — le
  site n'a pas de serveur accessible depuis la sandbox.
- `changefreq` et `priority` sont des indices ignorables par Google ; elles
  sont fournies cohérentes, sans 1.0 partout.
- GitHub Pages ne lit pas `_headers` (déjà documenté) : les en-têtes de
  sécurité n'entrent pas en compte dans l'indexation.
- Aucune mesure de positionnement : un rapport de recherche réel suppose
  plusieurs semaines après déploiement.
