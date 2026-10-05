# Déploiement et exploitation — état réel au 5 octobre 2026

> Décrit l'existant. **[CODE]** workflows et scripts ; **[PROD]** mesuré ;
> **[GITHUB]** lu par l'API GitHub (réglages, noms de secrets — jamais leurs valeurs).

## 1. Environnements
| Environnement | Existe ? | Détail |
|---|---|---|
| **Production** | oui | site : GitHub Pages ; base : un projet Supabase |
| **Préproduction (staging)** | **non** | pas de second projet Supabase ni de site de test |
| Développement local | oui, **sans base** | mode `demo` (tout en `localStorage`) ; les tests SQL tournent sur PostgreSQL WASM jetable |
| Application mobile | Expo Go local | pas de build distribué |

Conséquence : une migration SQL s'exécute **directement en production** (SQL
Editor, copie-collée par le propriétaire), après vérification manuelle que le
projet ouvert est bien `speed-express-site` (et non celui de Goship).

## 2. Dépôts
| Dépôt | Visibilité | Contenu |
|---|---|---|
| `speed-express-site` | **public** | site, dashboard, SQL, outils, tests, documents |
| `speed-express-app` | **privé** | application Expo |
| `Goship-express-site`, `goship-express-app` | publics | projet **frère, à ne jamais modifier** |

Un seul propriétaire (`wilnergraph92`), aucun collaborateur **[GITHUB]**. Un agent
externe (`arena-ai-coding-agent[bot]`, GitHub App) a un droit d'écriture et ouvre
des **branches `arena/…` et des pull requests** ; le propriétaire les fusionne.
`main` **n'est pas protégée** **[GITHUB]** : envoi forcé et suppression possibles.
Site : 18 branches `arena/…`, PR n°17 ouverte (remplacée par la n°18, fusionnée).
Application : PR n°1 ouverte, en conflit. Protection des secrets : *secret
scanning* et *push protection* **actifs** sur le site ; alertes Dependabot
**désactivées**.

## 3. Construction du site (aucune compilation)
Les 28 pages à la racine sont **générées** par `python3 outils/mise-en-page.py`
depuis `outils/pages/`, `outils/communs/` et `outils/espace/` (5 pages de comptes
via `pages-espace.py`). Reproductible : relancée, elle annonce « déjà à jour ».
Autres générateurs : `sitemap.py`, `accessibilite.py`, `unification.py`.

**Numéro de version du cache (`?v=32`)** : quatre constantes + ~214 occurrences dans
`outils/pages/`. Une seule commande les met à jour : `python3 outils/versionner.py`.

## 4. Intégration continue
| Workflow | Déclencheur | Rôle |
|---|---|---|
| `qualite.yml` | PR, push hors `main`, appelé par le déploiement | `verifier.sh` (9 suites) + régénération reproductible (`git diff --exit-code`) |
| `deploy.yml` | push sur `main` | appelle la qualité, **construit** `_site/` par `rsync` avec exclusions, publie sur Pages |
| `recup-reference.yml` | push sur une branche `arena/…` précise | opération **ponctuelle** (copie d'une maquette), `contents: write`, **inactive sur `main`**, à supprimer |

Permissions par défaut des workflows : **lecture seule**. **Aucun secret** ni
variable d'Actions dans les deux dépôts **[GITHUB]**. Historique : 51 déploiements,
50 réussis ; le seul échec date du 21 septembre.

## 5. Ce qui est publié
GitHub Pages, source `main` / `/`, HTTPS forcé, **pas de domaine personnalisé**
(`wilnergraph92.github.io/speed-express-site/`). Le dépôt est copié dans `_site/`
**moins** : `.git`, `.github`, `.claude`, `outils`, `README.md`, `CLAUDE.md`
(plus, depuis la phase 1, `docs`, `scripts`, `SECURITY.md`, `ARCHITECTURE-BASELINE.md`).
**Tout autre fichier à la racine part en ligne.** Vérifié **[PROD]** : `CLAUDE.md`,
`README.md`, `outils/…` et `.github/…` renvoient 404 ; 28 pages sur 28 identiques au dépôt.

Les fichiers `_headers` et `_redirects` sont publiés comme des fichiers ordinaires
mais **GitHub Pages ne les lit pas**. En-têtes réellement servis : seulement
`strict-transport-security` ; **aucune** CSP, ni `X-Frame-Options`, ni
`Referrer-Policy` **[PROD]**. Le `_headers` décrit une CSP **périmée** (il bloquerait
Supabase et les photos Unsplash s'il était un jour appliqué).

## 6. Configuration et « variables d'environnement »
Il n'y a **aucune variable d'environnement** en production.
| Où | Quoi | Sensible ? |
|---|---|---|
| `assets/js/config.js` | URL et clé **publique** Supabase, téléphone, WhatsApp, e-mail, adresse et RNC de facturation, devise, fuseau | non (publiques par nature) |
| `App_SES/src/api/supabase.ts` | URL et clé publique | non |
| `SES_TEST_DEPS` (poste local) | dossier des dépendances de test (PGlite, Playwright) | non |
| Supabase (tableau de bord) | SMTP, Site URL, redirections, politique de mot de passe | **[?]** non lisible |
Aucune clé secrète (`service_role`, `sb_secret_…`), aucun `.env`, aucun
certificat : ni dans les fichiers, ni dans l'historique complet des deux dépôts.

## 7. Tests (état du jour)
| Suite | Lancée par `verifier.sh` | CI | Résultat |
|---|---|---|---|
| qualité, i18n, couverture des traductions, tableau de bord (statique), performances, SEO, accessibilité, API, rôles API | oui | oui | **PASS** |
| rôles SQL (PostgreSQL WASM, 498 contrôles) | si `SES_TEST_DEPS` | **non** | **PASS** |
| `dashboard-sql.cjs` (PostgreSQL WASM) | **non** | non | **ÉCHEC en fuseau local** (AST) ; **PASS avec `TZ=UTC`** — défaut du test (il compare des horodatages sérialisés dans le fuseau de la machine), pas du produit |
| 4 suites navigateur (`*.mjs`, Playwright + `@sparticuz/chromium`) | non | non | non exécutables sur ce poste (binaire Linux) |
Application : `tsc` 0 erreur ; `expo lint` 2 erreurs et 4 avertissements ; aucun test.

## 8. Sauvegardes et reprise
- **Code** : Git (GitHub) ; une sauvegarde locale du 1ᵉʳ octobre (`~/Desktop/SES-sauvegarde-2026-10-01/`, antérieure aux quatre rôles).
- **Données** (clients, colis, factures, historique, appareils) : **aucune sauvegarde démontrée** ; l'offre Supabase et ses sauvegardes automatiques ne sont pas lisibles de l'extérieur **[?]**. Voir phase 2 (`docs/backup/`).

## 9. Surveillance
Aucune : pas d'alerte de disponibilité, pas de journal centralisé, pas de suivi
d'erreurs côté navigateur ou application. Les erreurs ne sont vues que si un
utilisateur les signale.

## 10. Procédure de publication actuelle
1. `git pull` (l'autre agent écrit aussi).
2. Modifier les sources (`outils/…`), jamais les pages générées.
3. `python3 outils/mise-en-page.py`, puis `bash outils/tests/verifier.sh` (+ `SES_TEST_DEPS=… ` pour le SQL).
4. `python3 outils/versionner.py` si des fichiers servis ont changé.
5. Commit, puis `git push origin main` → la CI qualité s'exécute, puis le déploiement.
6. Vérifier le **run du bon commit** (pas seulement « success »), puis la page en ligne.
7. Migration SQL : collée à la main dans le SQL Editor du bon projet.
