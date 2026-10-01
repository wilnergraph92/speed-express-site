# Phase 6 — Accessibilité WCAG

Date : **1er octobre 2026**. Branche : `arena/01a0f5b4-speed-express-site`.

Périmètre demandé : **E-08, E-09, M-14–M-21, F-13, F-15**. Les 28 pages,
les cinq fragments de l'espace client et leurs composants partagés ont été
contrôlés. Aucun déploiement ni modification de Supabase ; les appels métier
sont remplacés par des doubles de test, et le réseau externe est bloqué.

## 1. Résultat et portée

- **98 états audités, zéro violation détectée** par les règles axe-core
  sélectionnées : `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`, `wcag22aa` et
  `best-practice`.
- **15 groupes de tests clavier réussis**, dans un véritable Chromium piloté
  par Playwright, et **aucune exception JavaScript non interceptée**.
- 56 états correspondent aux **28 pages à 1440 et 390 px**, après utilisation
  du lien d'évitement ; 42 vérifient des états dynamiques : menus ouverts,
  panneaux, erreurs, résultats, suggestions, graphiques et dialogues.
- Contrôles statiques accessibilité, dashboard, performance et SEO : **PASS**.
  Non-régression navigateur dashboard/performance et contrat API : **PASS**.

Environnement : Chromium **153.0.8010.0** sans interface graphique,
Playwright **1.63.0**, axe-core **4.13.0**, `@sparticuz/chromium` **153.0.0**.

**Ce résultat n'est pas une certification WCAG AA complète.** Il signifie
qu'aucun échec n'a été détecté dans les contrôles concluants et les états
exercés. Les examens incomplets d'axe sont conservés, pas masqués ni assimilés
à des réussites ; les limites sont détaillées en section 6.

Résultats du passage complet :
[`tests/accessibilite-resultats.json`](tests/accessibilite-resultats.json).
Le fichier contient les 98 audits, leurs examens incomplets, les 15 groupes
clavier et le drapeau `succes: true`.

## 2. Problèmes corrigés

| Sujet | Correction |
| --- | --- |
| Material Symbols décoratifs | Les **85 occurrences** dans les HTML ont `aria-hidden="true"` ; 38 seulement l'avaient avant, soit **47 corrections**. Le contrôle ou le texte adjacent porte le sens. Le lien téléphonique de l'accueil, réduit à une icône sur mobile, reçoit un nom explicite. |
| Contrastes | Gris informatifs remplacés par une palette contextuelle claire/sombre. Rouge du logo, des fonds et des bordures conservé ; variantes de **texte** rouge adaptées aux surfaces. États gris futurs du suivi et texte de navigation au survol corrigés après les audits dynamiques. |
| Lien d'évitement | **28 liens « Aller au contenu »**, visibles au focus clavier, vers un unique `<main id="contenu" tabindex="-1">` par page. Il y avait six `main` et aucun lien d'évitement avant. Les cinq anciennes sections éditoriales nommées `contenu` sont renommées `contenu-page`, avec leurs liens internes adaptés. |
| Recherche de suivi | Véritable `<label>` « Numéro de suivi » associé au champ, sur l'accueil et la page de suivi ; le placeholder n'est plus sa seule source de nom. |
| Cartes d'articles | **Un lien titré par carte** : 11 sur le blog et quatre sur l'accueil. Image et « Lire la suite » gardent leur présentation, sans interaction redondante ; un lien étendu rend l'image cliquable. Sur le blog, 33 liens deviennent 11. |
| Onglets | Un seul arrêt Tab ; flèches circulaires, Home/End, liens entre onglets et panneaux, `aria-selected` et focus cohérents. Activation automatique des panneaux publics ; activation **manuelle** Enter/Espace côté client/gestion, pour ne pas charger des données à chaque flèche. Les onglets masqués par les droits sont exclus. |
| Deux combobox clients | Focus conservé dans l'input ; ArrowUp/Down, Enter, Escape et Tab ; `aria-expanded`, `aria-activedescendant`, options nommées avec IDs stables et `aria-selected`. La souris garde la sélection habituelle. Aucun résultat, erreur et réponse tardive ne rouvrent pas une liste fermée. |
| Menu de langue | Menu/menuitemradio dans le Shadow DOM, `aria-expanded`, flèches, Home/End, Enter/Espace, Escape et sortie Tab. Retour au bouton, y compris après reconstruction du composant lors d'une traduction. Le premier Escape ne ferme pas également la navigation mobile. |
| Formulaires | Erreurs réelles en `role="alert"`, `aria-invalid`, IDs uniques et association par `aria-describedby`. Aides existantes conservées et erreurs retirées lors de la correction. Les erreurs générales sont décrites au niveau du formulaire. Succès et informations ordinaires utilisent `status`/annonce polie, pas des alertes indiscriminées. |
| Téléphone et dates | La clé de message téléphonique manquante produisait une alerte vide dans inscription/profil/gestion : ajout aux fragments et pages. Une erreur de période du dashboard est associée au champ Fin, avec focus et message. Un repli traduit évite les messages de champ vides. |
| Focus et dialogues | Focus visible à double contour clair/sombre ; maintien du focus lors du remplacement des filtres et du rétablissement d'un bouton occupé. Les sept dialogues natifs gardent Tab/Shift+Tab à l'intérieur, conservent Escape comme sortie et rendent le focus à l'ouvreur. Repli onglet actif/main si l'ouvreur a disparu. |
| Autres défauts révélés par axe | En-tête Actions nommé dans le tableau des factures client, liens dans les paragraphes/listes soulignés indépendamment de leur couleur, hiérarchie de titres et repères sémantiques corrigés. |
| Mouvement réduit | Marquee et shimmer arrêtés, animations/transitions coupées, contenus d'apparition rendus visibles, parallax/lueur stoppés et défilement JS/CSS non animé. Carrousel sans défilement automatique sous `prefers-reduced-motion`; changement de préférence pris en compte à chaud. Bouton Pause/Reprendre accessible en mode normal. |

### Incident préexistant bloquant un parcours

La fiche client appelait `carte()` dans `ses-admin.js`, alors que ce helper
n'existait plus. L'ouverture échouait avec « carte is not defined » : le
parcours clavier client → facture → paiement était impossible à vérifier.
Le rendu minimal utilisant les styles existants a été rétabli, ses montants
rouges/verts ajustés au contraste, et le parcours testé sans enregistrement.
Le remplacement du contenu de l'aperçu ne laisse plus le focus sur `body`.

## 3. Contrastes vérifiés

Calcul de luminance relative sRGB et ratio WCAG, vérifié par le test statique.
Le seuil est **4,5:1** pour le texte courant et **3:1** pour le grand texte.
Les couleurs réelles des états ouverts sont également soumises à axe.

| Texte / fond | Ratio | Résultat / usage |
| --- | ---: | --- |
| Avant `#8d949f` / blanc | **3,06:1** | Échec pour le texte courant |
| Avant `#7a828e` / blanc | **3,88:1** | Échec pour le texte courant |
| `#626b78` / blanc | **5,39:1** | AA — gris informatif clair |
| `#626b78` / `#f8f8f8` | **5,08:1** | AA — surface smoke |
| `#626b78` / `#f6f6f6` | **4,99:1** | AA — état de survol ; l'ancien `#6b7280` était à 4,47:1 |
| `#a3abb8` / `#20242a` | **6,74:1** | AA — gris informatif sombre |
| `#b60d14` / blanc | **6,87:1** | AA — texte rouge clair |
| `#b60d14` / `#f6e1e2` | **5,49:1** | AA — texte rouge sur fond teinté |
| `#ff7278` / `#20242a` | **5,89:1** | AA — rouge sur anthracite |
| `#ff7278` / `#2e0d10` | **6,71:1** | AA — rouge sur fond sombre teinté |
| Blanc / marque `#e8121b` | **4,63:1** | AA — boutons et CTA ; fond de marque conservé |
| `#0b7a19` / blanc | **5,51:1** | AA — information verte |
| `#737c89` / `#f7f7f7` | **3,94:1** | AA **grand texte uniquement** — grands numéros d'étapes |

Le gris des étapes futures de l'espace client était à **2,57:1** sur blanc ;
il utilise désormais le gris informatif à **5,39:1**. La distinction entre
texte principal, aide, information secondaire et état actif est maintenue
par la typographie, les surfaces et les variantes contextuelles, sans
remplacer tous les gris par du noir.

## 4. Tests clavier réellement exécutés

Les assertions contrôlent l'élément actif, les états ARIA, la sélection,
les descriptions d'erreur, les IDs et l'absence de débordement. Elles ne
constituent pas une écoute de lecteur d'écran.

| Groupe | Parcours et assertions | Résultat |
| --- | --- | --- |
| 1 — Contenu | Premier Tab → lien d'évitement ; Enter → main ; Tab suivant contourne l'entête, sur les 28 pages à 1440/390 px. | PASS |
| 2 — Navigation mobile | Ouverture Enter, Tab vers la navigation, Escape, état replié et retour au bouton. | PASS |
| 3 — Langues | Flèches, Home/End, Enter/Espace, Escape, sortie Tab, souris, FR/EN/ES/HT et focus après traduction. | PASS |
| 4 — Onglets publics | Activation automatique, flèches circulaires, Home/End, Tab vers le panneau. | PASS |
| 5 — Cartes | Un lien par carte, Enter navigue vers l'article. Vérification géométrique du lien étendu sur le centre des 15 images : la zone est bien cliquable. | PASS |
| 6 — Espace client | Un arrêt Tab, activation manuelle, Enter/Espace, flèches, Home/End ; maintien du focus après filtrage. | PASS |
| 7 — Gestion | Onglets verticaux/manuels, panneau accessible par Tab, valeurs tabulaires du graphique ; tiroir mobile avec boucle Tab, Escape et retour au bouton. | PASS |
| 8 — Comptes | Erreurs locales et réseau simulé, liens erreur/champ ou formulaire, IDs uniques, aides conservées, correction, boutons de visibilité du mot de passe. Profil/mot de passe client également audités. | PASS |
| 9 — Pays | Sélecteur natif avec Home/ArrowDown ; choix « autre pays », champ libre nommé et focus transféré. Erreur de téléphone d'inscription auditée. | PASS |
| 10 — Suivi | Accueil et page dédiée : Enter depuis le champ, vide/inconnu/résultat, région d'annonce, nettoyage de l'erreur, bouton rétabli sans perdre le focus, défilement réduit. | PASS |
| 11 — Contact | Erreurs nom/email/téléphone, échec de service simulé, correction, succès simulé et remise à zéro au clavier. | PASS |
| 12 — Combobox | Les deux champs : flèches/Enter/Escape/Tab, options/IDs/activedescendant, focus input, souris, aucun résultat, réponse tardive, Escape consommé avant fermeture du dialogue. | PASS |
| 13 — Dialogues | Colis, facture, fiche, statut, rôle, confirmation, paiement : noms, Tab/Shift+Tab, Escape/fermeture et retour aux ouvreurs. Rôle employé/droits affichés ; parcours réel fiche client → aperçu facture → paiement, puis retour. Confirmation annulée, aucune suppression. | PASS |
| 14 — Droits/vides | Onglets non autorisés exclus du clavier ; interface et données vides auditées. | PASS |
| 15 — Mouvement | CSS et scrolling JS réduits, changement système à chaud, pas d'avancement du carrousel pendant un intervalle complet, pause explicite en mode normal et diapositives inactives retirées du parcours. | PASS |

La soumission de contact est interceptée et toutes les données sont
synthétiques (`example.invalid`, identifiants `*-test-*`). Aucun envoi réel,
appel WhatsApp, suppression ou écriture de facture/paiement n'a été exécuté.
La configuration réelle `assets/js/config.js` n'est pas copiée dans les doubles.

## 5. Sources, génération et non-régression

- **Nouveaux fichiers communs** : `assets/css/ses-accessibilite.css` et
  `assets/js/ses-accessibilite.js` (onglets, validation, descriptions,
  mouvement et dialogues). Pas de framework ni de build ; le code partagé
  reste en IIFE/`var`.
- **Transformateur idempotent** : `outils/accessibilite.py`, intégré à
  `outils/mise-en-page.py` et à l'assembleur `outils/pages-espace.py`.
  Les fragments `outils/espace/*.html` restent synchronisés.
- **Composants** : entête, langue, site, comptes, UI, espace client, gestion,
  dashboard, animation et hero. Nouvelles chaînes communes dans les
  dictionnaires ; chaînes de formulaire dans les templates traduisibles.
- **Ressources versionnées 29** sur les 28 pages. Position des preloads et
  preconnects préservée par les étapes de performance pour maintenir leur
  idempotence après insertion des ressources d'accessibilité.
- **Seule l'étape ciblée d'accessibilité a été appliquée**, pas le générateur
  historique complet. Sa dernière relance donne **0 page retouchée**.
- **Tests ajoutés** : `tests/accessibilite-static.py` et
  `tests/accessibilite-browser.mjs`. Les doubles des tests navigateur
  dashboard/performance sont également rendus indépendants de la
  configuration réelle.

Derniers contrôles exécutés, tous PASS :

```sh
PYTHONDONTWRITEBYTECODE=1 python3 outils/tests/accessibilite-static.py
PYTHONDONTWRITEBYTECODE=1 python3 outils/tests/dashboard-static.py
PYTHONDONTWRITEBYTECODE=1 python3 outils/tests/performance-static.py
PYTHONDONTWRITEBYTECODE=1 python3 outils/tests/seo-static.py
node outils/tests/dashboard-api.cjs
node --check outils/tests/accessibilite-browser.mjs
git diff --check
```

Les tests navigateur `dashboard-browser.mjs` et `performance-browser.mjs`
passent aussi : huit largeurs de **320 à 1440 px**, filtres, navigation,
permissions, états vides/erreurs, traduction différée dans les quatre langues,
images, carrousel et fallback. Il s'agit de non-régressions fonctionnelles,
pas d'une nouvelle mesure Lighthouse ou d'un nouveau benchmark avant/après.

### Rejouer la suite d'accessibilité

Depuis la racine du dépôt, dépendances **hors dépôt** :

```sh
export SES_TEST_DEPS="$HOME/.cache/ses-a11y"
npm install --prefix "$SES_TEST_DEPS" \
  playwright@1.63.0 @sparticuz/chromium@153.0.0 axe-core@4.13.0
```

Sur la sandbox Linux, les bibliothèques AL2023 fournies par Chromium ont été
extraites, sans installation système :

```sh
mkdir -p "$SES_TEST_DEPS/lib"
node -e 'const fs=require("node:fs"),z=require("node:zlib"),d=process.env.SES_TEST_DEPS;fs.writeFileSync(d+"/al2023.tar",z.brotliDecompressSync(fs.readFileSync(d+"/node_modules/@sparticuz/chromium/bin/al2023.tar.br")))'
tar -xf "$SES_TEST_DEPS/al2023.tar" -C "$SES_TEST_DEPS/lib"
rm "$SES_TEST_DEPS/al2023.tar"
export LD_LIBRARY_PATH="$SES_TEST_DEPS/lib/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
SES_A11Y_REPORT="$SES_TEST_DEPS/rapport-navigateur.json" \
  node outils/tests/accessibilite-browser.mjs
```

Le test ouvre son serveur temporaire sur le port **8127**, puis ferme serveur
et navigateur dans `finally`, même en cas d'échec. Les dépendances/cache ne
font pas partie du dépôt ; le résultat final utile est conservé séparément.

## 6. Contrôles incomplets et vérifications impossibles ici

1. **Contrastes sur photos, dégradés et pseudo-éléments** : axe laisse
   `color-contrast` incomplet dans **83 états**, soit **760 occurrences
   cumulées de nœuds**, souvent les mêmes éléments répétés selon les états.
   Cela inclut aussi des liens-images, glyphes non textuels, textes trop
   courts et zones superposées. Ce ne sont pas 760 violations établies,
   mais ce ne sont pas des passes non plus. Les palettes unies ci-dessus
   sont mesurées ; l'ensemble des positions/diapositives/fonds composés
   demande une vérification visuelle/pixel sur les rendus réels.
2. **Relations de popups fermés** : 63 occurrences incomplètes de
   `aria-valid-attr-value` : 57 pour `ses-lang-menu` dans le Shadow DOM et
   six pour les deux listes de combobox. Les cibles existent dans leur
   racine ; DOM/IDs, ouverture, `aria-expanded` et `aria-activedescendant`
   ont été contrôlés explicitement. L'outil n'établit pas la relation quand
   ces popups sont invisibles. Ces examens restent dans le JSON.
3. **NVDA, JAWS, VoiceOver, TalkBack et braille** : pas de dispositif réel
   disponible. Les noms, rôles, live regions, focus et descriptions sont
   testés dans le DOM ; la prononciation, le timing exact et l'absence de
   doubles annonces ne sont pas certifiés. À vérifier avec au moins
   NVDA/Firefox et VoiceOver/Safari, y compris les combobox et formulaires.
4. **Navigateurs et appareils réels** : pas de validation Firefox/WebKit,
   iOS/Android, clavier matériel mobile ou contraste forcé Windows. Les
   popups natifs de `select`/`datalist` varient selon le système. Le scénario
   de pays est exercé, pas toutes les suggestions natives de villes.
5. **Production et contenus futurs** : polices/images distantes bloquées
   durant les tests, backend authentifié et paiements non exercés. Les
   fixtures couvrent les cas avec données, vides et erreurs, pas toutes les
   réponses métier, mises à jour temps réel ou factures possibles. Toute
   nouvelle couleur, carte ou traduction doit repasser les tests.
6. **Critères nécessitant jugement humain** : pertinence des textes
   alternatifs, compréhension des messages, ordre de lecture perçu,
   reflow/zoom à 200–400 %, taille de cible en situation tactile et
   masquage de focus dans toutes les combinaisons de scroll restent à
   valider manuellement. Les contrôles automatiques et huit largeurs de
   non-régression ne couvrent pas ces expériences intégralement.

**Bilan : objectif de zéro violation atteint pour les contrôles automatiques
concluants du périmètre testé ; réserves explicites conservées pour les
examens incomplets et l'assistance technique réelle. Phase 6 arrêtée ici.**
