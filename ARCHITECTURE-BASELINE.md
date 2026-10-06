# Speed Express Shipping — photographie technique (baseline)

**Date : 5 octobre 2026.** Site `v32` (commit `7954339`), application `236bfcb`.
Ce document est la **référence officielle de l'existant** avant toute
transformation. Il décrit ce qui **est**, pas ce qui devrait être : aucune
table, aucun comportement, aucune architecture n'a été modifié pour l'écrire.

Détail par sujet : [`docs/current-state/`](docs/current-state/) —
[DATABASE](docs/current-state/DATABASE.md) · [AUTH](docs/current-state/AUTH.md) ·
[RLS](docs/current-state/RLS.md) · [ROLES](docs/current-state/ROLES.md) ·
[API](docs/current-state/API.md) · [PARCEL-LIFECYCLE](docs/current-state/PARCEL-LIFECYCLE.md) ·
[BILLING](docs/current-state/BILLING.md) · [MOBILE](docs/current-state/MOBILE.md) ·
[DEPLOYMENT](docs/current-state/DEPLOYMENT.md).

Légende des sources : **[CODE]** lu dans le dépôt · **[PROD]** mesuré en
production (lecture seule, clé publique) · **[?]** impossible à vérifier de
l'extérieur.

## 1. Le système en une image

```
 Visiteurs / clients            Équipe (employé · gérant · admin)         Clients mobiles
        │                                  │                                   │
  Site statique (28 pages)        Tableau de bord (même site)          Application Expo
  GitHub Pages, HTML/CSS/JS ES5   ses-admin.js, ses-dashboard.js       React Native, expo-router
        │                                  │                                   │
        └──────────────── window.SES_API (site)        supabase-js (app) ──────┘
                                   │  (aucun serveur à nous : appels directs)
                                   ▼
        ┌────────────────────────── SUPABASE (projet unique) ──────────────────────────┐
        │  Auth (e-mail+mdp)  │  PostgREST (tables, vues, RPC)  │  Realtime             │
        │                                                                               │
        │  PostgreSQL : clients · colis · colis_historique · factures · appareils        │
        │  RLS + GRANT par colonne + déclencheurs + fonctions SECURITY DEFINER          │
        │  → la base est la source de vérité : numéros, facture, historique, rôles      │
        └───────────────────────────────┬───────────────────────────────────────────────┘
                                        │ pg_net (déclencheur prevenir_client)
                                        ▼
                                Expo Push → téléphones
```

Choix structurants **[CODE]** : pas de serveur applicatif, pas de compilation
côté site (pages générées par des scripts Python), une seule base, quatre
langues par dictionnaires à l'exécution, règles de sécurité **dans la base**.

## 2. Composants

| Composant | Technologie | Dépôt | État |
|---|---|---|---|
| Site public + espace client + tableau de bord | HTML/CSS/JS ES5, 28 pages générées, 4 langues | `speed-express-site` (public) | en ligne, v32 **[PROD]** |
| Base et backend | Supabase : PostgreSQL, Auth, PostgREST, Realtime | — (SQL dans `outils/`) | en ligne **[PROD]** |
| Application mobile | Expo SDK 57, React Native 0.86, expo-router | `speed-express-app` (privé) | Expo Go seulement ; ni build, ni icône, ni comptes de stores |
| Notifications | trigger SQL → `pg_net` → Expo Push | SQL de l'application | base prête **[PROD]**, inutilisable sans build de développement |
| Déploiement | GitHub Actions → GitHub Pages | `.github/workflows/` | 50/51 réussis |
| Tests | 9 suites en CI + PostgreSQL WASM (498 contrôles) | `outils/tests/` | **PASS** (voir §6) |

## 3. Flux principaux (résumé)
- **Client** : inscription → e-mail de confirmation → profil créé par déclencheur (rôle `client`, code `SES-#####`) → espace client / application.
- **Colis** : enregistré par l'équipe → numéro + jeton posés par la base → première ligne d'historique → **facture créée aussitôt** → notification. Détail : `PARCEL-LIFECYCLE.md`.
- **Facturation** : `poids × tarif + 10 $`, tarif gelé avec la facture, paiement saisi à la main, regroupement fait **par le navigateur**. Détail : `BILLING.md`.
- **Authentification** : Supabase Auth ; le rôle est relu en base à chaque requête. Détail : `AUTH.md`, `ROLES.md`.
- **Suivi public** : `suivre_colis(numéro[, jeton])`, ouvert sans connexion ; ne renvoie ni identité ni adresse.
- **Notifications** : changement de statut → base → Expo → appareils enregistrés dans `appareils`.

## 4. État de la production (mesuré le 5 octobre 2026)

| Élément | Constat | Source |
|---|---|---|
| Site | 28/28 pages identiques au dépôt ; 45 fichiers appelés en 200 ; un seul `?v=32` | **[PROD]** |
| Déploiement | commit `7954339` publié ; `CLAUDE.md`, `outils/`, `.github/` en 404 | **[PROD]** |
| Accès anonyme à la base | lecture et écriture de toutes les tables refusées ; fonctions sensibles refusées | **[PROD]** |
| Migrations passées | `supabase-maj.sql` (4 rôles), jeton du suivi, tableau de bord, notifications | **[PROD]** par sondes |
| Inscription | ouverte, confirmation e-mail obligatoire, e-mail seul | **[PROD]** |
| Offre / sauvegardes / SMTP / redirections Supabase | inconnus | **[?]** |
| Données réelles (volumes, qualité) | inconnues | **[?]** |

## 5. Registre des risques (faits, non corrigés)

| # | Risque | Gravité | Détail |
|---|---|---|---|
| R1 | **Aucune sauvegarde des données démontrée** | élevée | `DEPLOYMENT.md` §8 → phase 2 |
| R2 | **`supabase.sql` rejoué casse le suivi public** (surcharge de `suivre_colis`) | élevée | `DATABASE.md` §6, démontré |
| R3 | Supprimer un compte Auth supprime ses **factures** (cascade) | élevée | `DATABASE.md` §7.1 |
| R4 | Facture groupée **non transactionnelle** + suppression définitive des factures remplacées | moyenne | `BILLING.md` §5 |
| R5 | **Aucun journal d'audit** (paiements, suppressions, rôles) | moyenne | `BILLING.md` §10 |
| R6 | Session de l'application **non chiffrée** | moyenne | `MOBILE.md` §3 → phase 3 |
| R7 | **Suivi public énumérable** (numéro séquentiel, jeton facultatif, pas de limite de débit) | moyenne | `PARCEL-LIFECYCLE.md` §5 → phase 3 |
| R8 | **Aucun en-tête de sécurité** (CSP, anti-clic, référent) ; `_headers` périmé | moyenne | `DEPLOYMENT.md` §5 → phase 3 |
| R9 | `est_admin`, `a_droit`, `texte_notification` exécutables par `anon` (sans fuite) | faible | `RLS.md` §4 → phase 3 |
| R10 | **Pas de préproduction** : les migrations partent en production | moyenne | `DEPLOYMENT.md` §1 → phase 4 |
| R11 | **Aucune surveillance** (disponibilité, erreurs) | moyenne | `DEPLOYMENT.md` §9 |
| R12 | Logique métier **dupliquée** (frais, totaux, regroupement : SQL + site + application) | moyenne | `BILLING.md` §9 → phase 4 |
| R13 | `main` non protégée ; agent externe avec droit d'écriture ; PR n°1 de l'application en conflit | moyenne | `DEPLOYMENT.md` §2 |
| R14 | Application : icône Expo, pas d'EAS, pas de comptes de stores, notifications inutilisables | bloquante pour la publication | `MOBILE.md` §5 |
| R15 | Tests : `dashboard-sql.cjs` dépend du fuseau, suites SQL/navigateur hors CI | faible | `DEPLOYMENT.md` §7 |
| R16 | Réglages Auth (SMTP, redirections, mot de passe, débit) **inconnus** | moyenne | `AUTH.md` §2 → phase 3 |
| R17 | Aucun contrôle de **transition de statut** ; aucune preuve de livraison | faible | `PARCEL-LIFECYCLE.md` §1, §6 |
| R18 | **Notifications : `prevenir_client()` appelle `extensions.net.http_post` (nom invalide)** : bloquerait tout changement de colis d'un client dont l'appareil est enregistré. Latent (aucun appareil aujourd'hui), reproduit sur PostgreSQL réel | élevée (latente) | `DATABASE.md` §7.7 → phase 3 |

## 6. Vérifications du jour (aucune n'a modifié le système)

| Suite | Résultat |
|---|---|
| qualité · dictionnaires · couverture des traductions · tableau de bord · performances · SEO · accessibilité · API · rôles API | **PASS** (9/9, via `verifier.sh`) |
| rôles SQL sur PostgreSQL WASM | **PASS**, 498 contrôles |
| `dashboard-sql.cjs` | PASS avec `TZ=UTC` ; échec en fuseau local (défaut du test) |
| application : `tsc` / `expo lint` / `npm audit` | 0 erreur / 2 erreurs + 4 avertissements / 30 alertes (outils de build) |

Reproduire : `bash outils/tests/verifier.sh` ; avec PostgreSQL WASM :
`SES_TEST_DEPS=/dossier bash outils/tests/verifier.sh`.

## 7. Ce que ce document ne dit pas
Les données réelles (volumes, anomalies), l'offre et les sauvegardes Supabase,
les réglages d'authentification non publics, et le comportement de
l'application sur un vrai téléphone n'ont **pas** pu être vérifiés. Chaque
document de `docs/current-state/` marque ces points **[?]**.

## 8. Règle de mise à jour
Toute évolution qui change l'un de ces constats met à jour ces documents **dans
le même commit**. Les décisions d'architecture futures vivent dans
`docs/architecture/ADR/` (phase 4) et ne réécrivent jamais ce baseline : elles le
citent.

## 9. Suivi des corrections (mis à jour le 5 octobre 2026)
Les corrections sont **écrites et testées ; aucune n'est appliquée en production** tant que vous n'avez pas collé la migration
(`outils/supabase-maj.sql`, sections 9 et 10) et publié le site.

| # | Risque | État | Où |
|---|---|---|---|
| R2 | `supabase.sql` rejoué cassait le suivi public | **corrigé** : `supabase.sql` réconcilié ; test de rejeu de chaque fichier | `schema-rejouable.py` |
| R6 | session mobile non chiffrée | **corrigé** (trousseau, migration de l'ancienne session) — dépôt de l'application | `npm run essai:stockage` |
| R7 | suivi public énumérable | **décision à prendre** (A / B / C) | `docs/security/TRACKING-SECURITY.md` |
| R8 | aucun en-tête de sécurité | **corrigé** : politique de contenu, référent, anti-cadre (publication = déploiement du site) | `securite-statique.py` |
| R9 | fonctions ouvertes à `anon` | **corrigé** (migration, section 10) | `securite-sql.py` |
| R15 | `dashboard-sql.cjs` dépendait du fuseau | **corrigé** et branché dans `verifier.sh` | `dashboard-sql.cjs` |
| R16 | réglages d'authentification inconnus | **liste de contrôle** prête, à régler par vous | `docs/security/AUTH-HARDENING.md` |
| R18 | notifications : appel invalide, bloquait les colis | **corrigé** (migration, section 9) ; table `appareils` sans droits **corrigée** aussi | `securite-sql.py` |
| — | vue `factures_details` sans la colonne `groupee` | **corrigé** (migration facture groupée) | `schema-rejouable.py` |
| R12 | logique de facturation **dupliquée** (frais, totaux, regroupement) | **corrigé dans le noyau** : un seul moteur de calcul, dans la base, qui refait chaque prix et chaque total (phase 10). Le site et l'application **actuels** gardent leur logique tant que la bascule n'est pas décidée | `FINANCE-ENGINE.md` ; `logistique-finance-essai.py` |
| R1, R3, R4, R5, R10, R11, R13, R14, R17 | sauvegardes, cascade, audit… | voir `docs/backup/`, noyau logistique (phases 5 à 10) | — |
