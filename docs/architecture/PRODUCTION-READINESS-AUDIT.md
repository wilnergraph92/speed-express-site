# Audit de préparation à la production — Speed Express Shipping

> **Date : 7 octobre 2026.** Site : commit `9641840` sur `main`, **identique au commit publié** (déploiement GitHub Pages du
> 7 octobre, 17 h 35 UTC), cache `?v=45`. Application : commit `1299f4f`, build Android `8578f819` (profil `preview`).
> Ce document **constate** ; il ne modifie ni la base, ni les données, ni le site publié. Il prolonge
> [`ARCHITECTURE-BASELINE.md`](../../ARCHITECTURE-BASELINE.md) (photographie du 5 octobre) sans le réécrire.

**Règle de lecture.** Une fonctionnalité n'est dite **opérationnelle** que si elle est vérifiable de bout en bout : code publié,
migration **confirmée en production par une requête** (pas seulement « Success »), et un test sur un vrai PostgreSQL ou un usage réel
observé. Une interface qui existe ne suffit pas.

Sources : **[CODE]** lu dans les dépôts · **[TEST]** suite exécutée le 7 octobre · **[PROD]** mesuré en production en lecture seule
(clé publique, aucun compte connecté) · **[PROP]** confirmé par le propriétaire (capture d'une requête de contrôle) · **[?]** invérifiable
d'ici.

**Suivi — phase 1 « sécuriser la production » (8 octobre 2026).** F2 levé (`main` protégée, PR et CI obligatoires, déploiement
approuvé par le propriétaire). F3 : remède écrit et **éprouvé sur une réplique de la production** (`securite-catalogue.py`), qui a
aussi trouvé `prefixe_matricule` ouverte aux visiteurs, `TRUNCATE` ouvert aux comptes connectés et la vue `factures_details` sans
`groupee` — à coller par le propriétaire (`GO-LIVE-SECURITY-CHECKLIST.md` §3). Préproduction outillée (`ENVIRONNEMENTS.md`),
surveillance planifiée, sauvegarde documentée (`BACKUP-AND-RECOVERY.md`) mais **F1 reste ouvert** tant que le dépôt privé n'existe pas.

---

## A. Architecture actuelle

```
 Visiteurs / clients               Équipe (employé · gérant · admin)            Clients mobiles (Android)
        │                                     │                                          │
 Site statique, 28 pages            tableau-de-bord.html (même site)            Application Expo SDK 57
 GitHub Pages, HTML/CSS/JS ES5      ses-admin.js · ses-dashboard.js ·           APK « preview » + mises à jour
 4 langues par dictionnaires        ses-reglages.js · ses-prealertes.js         OTA (canal preview)
        │                                     │                                          │
        └────────── window.SES_API (39 fichiers JS, ses-api.js ≈ 2 650 lignes) ── supabase-js ──┘
                                              │  aucun serveur applicatif
                                              ▼
 ┌──────────────────────────────── SUPABASE (un seul projet, production) ────────────────────────────────┐
 │ Auth (e-mail + mot de passe) · PostgREST · Realtime                                                    │
 │ schéma public : clients · colis · colis_historique · factures · prealertes · appareils ·             │
 │                 matricules_attribues + vues colis_details, factures_details                           │
 │ RLS + droits par colonne + déclencheurs + fonctions SECURITY DEFINER : la base décide                 │
 │ schémas logistics / analytics / ops (noyau 001 → 013) : ÉCRITS ET TESTÉS, NON INSTALLÉS               │
 └────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

| Couche | Réalité au 7 octobre | Source |
|---|---|---|
| Pages | 28 générées par `outils/mise-en-page.py` ; relancée : « 0 modifiées » | [TEST] |
| Données | double implémentation `supabase` / `demo` (+ `off`) de `SES_API` ; contrats éprouvés par suite | [TEST] |
| Base | ≈ 10 100 lignes SQL ; héritage `public` en production ; noyau 001-013 absent (`ses_health` introuvable) | [PROD] |
| Interrupteurs | `portailNoyau: false`, `centreNoyau: false` | [CODE] |
| CI/CD | `qualite.yml` (45 suites, dont PostgreSQL réel et WASM) → `deploy.yml` (rsync avec exclusions) → Pages | [CODE] |
| Mobile | dépôt privé ; une base de code, deux variantes (`client`, `operations`) ; seule la variante client a un build (Android) | [CODE] |

## B. Architecture cible

Celle de [`TARGET-ARCHITECTURE.md`](TARGET-ARCHITECTURE.md) et des ADR 0001 à 0015, **inchangée** : un noyau logistique dans PostgreSQL
(schéma `logistics`, machine d'états, événements en boîte d'envoi, audit, finance), exposé par une façade `public.lg_*`, et des
interfaces qui n'affichent et n'appellent que cette façade :

| Support visé | Brique prévue | État de la brique |
|---|---|---|
| Site public | site statique actuel | en ligne |
| Portail client | `ses-portail*.js` derrière `portailNoyau` (ADR 0009) | écrit, testé, **éteint** |
| Tableau de bord administratif | `tableau-de-bord.html` actuel | en ligne |
| Tableau de bord des opérations | centre de commande `ses-centre*.js` derrière `centreNoyau` (ADR 0010) | écrit, testé, **éteint** |
| Application mobile client | Expo, variante `client` | Android `preview` seulement |
| Application mobile opérations | Expo, variante `operations` (ADR 0012) | écrite, testée, **jamais construite** |
| Bureau Windows / macOS | tableau de bord installable (`tableau-de-bord.webmanifest`, ADR 0013), sans Electron | manifeste publié, installation **non éprouvée** |
| Notifications | moteur dans la base (010) + travailleur planifié `scripts/notifications/` (ADR 0011) | écrit, testé, **non installé** |
| Paiements | moteur financier (007, ADR 0007) ; aucun prestataire de paiement en ligne choisi | écrit, testé, **non installé** |
| Rapports | analytique séparée (012, ADR 0014) | écrite, testée, **non installée** |
| Suivi | `suivre_colis` (héritage) puis `tracking_event` du noyau | héritage en ligne |
| Entrepôt, transport, dernier kilomètre, preuve de livraison | 004, 005, 006 | écrits, testés, **non installés** |
| Audit | `logistics.audit_log` (002/003) | écrit, testé, **non installé** |
| Surveillance | `ops` (013, ADR 0015) | écrite, testée, **non installée** |

Aucune nouvelle pile n'est proposée par cet audit. Le chemin vers la cible est la stratégie d'étranglement de
[`MIGRATION-STRATEGY.md`](MIGRATION-STRATEGY.md).

## C. Fonctionnalités déjà opérationnelles (vérifiées de bout en bout)

| Fonctionnalité | Preuve |
|---|---|
| Site public, 28 pages, 4 langues | publié = `9641840` [PROD] ; 28 pages en 200 ; `CLAUDE.md`, `outils/`, `docs/` en 404 [PROD] ; qualité, SEO, traductions, navigateur [TEST] |
| Fermeture aux visiteurs anonymes | lecture de `clients`, `colis`, `factures`, `colis_historique`, `prealertes`, `matricules_attribues`, `appareils` et des deux vues : **refusée (42501)** [PROD] |
| Comptes, connexion, rôle relu en base | administrateur réel connecté et nommé [PROP] ; `roles-sql.cjs` 498 contrôles [TEST] |
| Rôles client / employé / gérant / admin | `definir_role` en production [PROP] ; grille complète [TEST] |
| Identifiants d'équipe ADM / GER / EMP | `supabase-maj-equipe.sql` collé ; l'administrateur a reçu **ADM-2279** [PROP] ; 50 contrôles [TEST] |
| Enregistrement d'un colis, facture créée par la base | `facturer_colis` en production ; prix saisi (`prix_manuel`) collé et vérifié [PROP] ; 62 contrôles [TEST] |
| Numéros `SES-` + 10 chiffres au hasard | `nouveau_format = true` [PROP] ; 1 611 contrôles [TEST] |
| Vue d'ensemble du tableau de bord, filtre Destination | `dashboard_colis_ses` à 8 paramètres collée [PROP] ; essais SQL et navigateur [TEST] |

## D. Fonctionnalités partiellement opérationnelles

| Fonctionnalité | Ce qui marche | Ce qui manque pour la dire opérationnelle |
|---|---|---|
| Inscription des clients | ouverte, confirmation obligatoire [PROD, baseline] | **SMTP propre non confirmé** : le service d'e-mail intégré de Supabase est limité à quelques messages par heure [?] ; modèles d'e-mail en anglais |
| Suivi public | `suivre_colis(numéro[, jeton])` ouvert aux visiteurs [CODE] | anciens numéros séquentiels acceptés **sans jeton**, aucune limite de débit (R7, décision A/B/C en attente : `docs/security/TRACKING-SECURITY.md`) |
| Facturation et paiements | facture automatique, tarif gelé, 10 $ de frais [TEST] | paiement **saisi à la main** ; aucun paiement en ligne ; regroupement **non transactionnel** fait par le navigateur (R4) |
| Pré-alertes | table, RLS, quotas (30 / 24 h) en production [PROP] ; écran de l'application ; onglet du tableau de bord [TEST] | **aucune pré-alerte réelle observée** de l'application jusqu'au tableau de bord |
| Application client Android | APK installé, mises à jour OTA publiées sur `preview` (empreinte `6cc2915…`) [PROD EAS] ; 6 suites, 2 255 contrôles, `tsc` et `lint` à 0 [TEST] | **pas d'iOS**, pas de build `production`, pas de fiche Play Store ; notifications impossibles (voir E) |
| Réglages, mode sombre, fenêtres sécurisées | publiés [PROD] ; 33 + 60 contrôles [TEST] | vus seulement sur des données d'essai (mode démo), jamais avec des données réelles |
| Bureau Windows / macOS | manifeste d'installation publié [CODE] | installation jamais éprouvée sur un poste Windows ou macOS ; aucun matériel (scanner, imprimante) essayé contre la production |

## E. Fonctionnalités non déployées

| Fonctionnalité | Où elle existe | Ce qui la bloque |
|---|---|---|
| **Notifications sur téléphone** | `prevenir_client`, `enregistrer_appareil` (section 9 de `supabase-maj.sql`) ; `src/api/notifications.ts` | section 9 **absente de la production** : `enregistrer_appareil` introuvable [PROD] ; Firebase (FCM) non configuré pour Android |
| Notifications par e-mail / moteur d'événements | 010 + `scripts/notifications/envoyer.mjs` | noyau non installé ; dépôt privé et secrets Brevo non posés |
| Noyau logistique (machine d'états, audit, événements) | 001-003 | non appliqué (décision du propriétaire, sauvegarde préalable) |
| Entrepôt, scanner, poste de scan | 004, `ses-scanner.js`, `ses-poste.js` | 004 et 009 non appliqués ; `centreNoyau` éteint |
| Transport, douane, dernier kilomètre, preuve de livraison | 005, 006 | non appliqués ; application « Opérations » jamais construite |
| Moteur financier | 007 | non appliqué ; reprise des factures héritées **refusée** (`LG004`) tant que le traitement de `montant_paye` n'est pas décidé |
| Portail client du noyau | 008, `ses-portail*.js` | non appliqué ; `portailNoyau` éteint |
| Centre de commande, analytique, santé | 009, 012, 013 | non appliqués ; `centreNoyau` éteint |
| Application « SES Opérations » | variante `operations` | aucun build (`preview-operations` jamais lancé) ; dépend de 011 |
| Sauvegarde chiffrée quotidienne | `scripts/backup/`, 57 contrôles [TEST] | workflow non installé : dépôt privé, clé `age`, offre et version de PostgreSQL de Supabase non fournies |
| Surveillance | `ops.status_checks()` (013) | 013 non appliqué ; aucune sonde externe |
| Paiement en ligne | — | aucun prestataire choisi ; nécessiterait un ADR |

## F. Risques critiques

| # | Risque | Constat | Conséquence | Remède |
|---|---|---|---|---|
| **F1** | **Aucune sauvegarde des données démontrée** (R1) | workflow non installé ; offre Supabase et sauvegardes natives [?] | une erreur de collage SQL, une suppression ou un incident chez le fournisseur = perte définitive des clients, colis et factures | installer `scripts/backup/` dans un dépôt privé, une restauration de contrôle réussie, **avant toute autre migration** |
| **F2** | **La production n'exige aucune validation dans GitHub** | `main` non protégée (404 « Branch not protected ») ; l'environnement `github-pages` n'a **aucun relecteur obligatoire** (seulement une règle de branche) ; un agent externe a le droit d'écriture | tout envoi sur `main` qui passe les tests part en ligne sans clic ; contraire à la règle « Production doit toujours nécessiter une validation explicite » | protéger `main` ; ajouter « Required reviewers » à `github-pages` (geste du propriétaire, `GO-LIVE-CHECKLIST.md` §2) |
| **F3** | **Les sections 9 et 10 de `supabase-maj.sql` ne sont pas en production** | `est_admin` s'exécute encore en anonyme (renvoie `false`), `enregistrer_appareil` est introuvable [PROD] | R9 (fonctions ouvertes aux visiteurs) ouvert ; R18 (`prevenir_client` appelle `extensions.net.http_post`, un nom invalide) **toujours en place** : il bloquera les changements de statut des colis d'un client le jour où son téléphone s'enregistre | ne **pas** brancher Firebase avant d'avoir passé ces sections, puis vérifier par requête (voir L) |

## G. Risques élevés

| # | Risque | Détail |
|---|---|---|
| G1 | Supprimer un compte Auth **supprime ses factures** (R3) | `clients.id → auth.users on delete cascade` puis `factures.client_id → clients on delete cascade` [CODE]. « Supprimer mon compte » n'envoie qu'une **demande** (application, site) : le risque se réalise quand l'équipe exécute la demande dans Supabase |
| G2 | **Pas de préproduction** (R10) | chaque migration est collée directement en production ; un premier collage de pré-alertes n'avait rien appliqué sans que « Success » le montre |
| G3 | **SMTP non confirmé** | sans envoi propre, une partie des nouveaux clients ne reçoit jamais son lien d'activation |
| G4 | **Aucun journal d'audit** sur l'héritage (R5) | paiements, suppressions, changements de rôle et de prix non tracés (seuls les identifiants d'équipe ont un registre) |
| G5 | Facture groupée **non transactionnelle** (R4) | le navigateur crée la groupée puis supprime les factures remplacées ; une coupure entre les deux laisse un double compte |
| G6 | Aucune surveillance | une panne de Supabase, une erreur JavaScript ou un quota dépassé ne se voient que si un client se plaint |

## H. Risques moyens

| # | Risque | Détail |
|---|---|---|
| H1 | Suivi public énumérable pour les **anciens** numéros (R7) | les nouveaux numéros (10 chiffres au hasard) réduisent le risque ; la décision A/B/C reste à prendre |
| H2 | PR n° 17 et 18 branches `arena/…` dormantes | PR n° 17 : 74 fichiers, 17 commits de retard ; une fusion par mégarde réécrirait le tableau de bord. Application : PR n° 1 ouverte, en conflit |
| H3 | `recup-reference.yml` encore présent | inactif sur `main`, mais `contents: write` ; la liste de mise en production demande sa suppression |
| H4 | Logique dupliquée site / application / base (R12) | frais, totaux, statuts recopiés en TypeScript ; corrigée dans le noyau seulement |
| H5 | `npm audit` de l'application : 30 alertes (19 élevées, 11 modérées) | dans la chaîne d'outils Expo (`@expo/cli`, `config-plugins`) ; non démontré dans l'APK |
| H6 | Dependabot désactivé sur le site | alertes de sécurité des actions GitHub non reçues |
| H7 | Quotas de l'offre gratuite [?] | base limitée à 500 Mo et pause après inactivité si l'offre est gratuite ; à confirmer |
| H8 | Le premier collage d'une migration peut échouer **en silence** | constaté le 7 octobre (pré-alertes) ; d'où la règle : toujours une requête de contrôle après « Success » |

## I. Dette technique

1. **Documentation en retard sur le code** (corrigé en partie par cet audit) :
   - `docs/current-state/MOBILE.md` décrit encore une application sans build, à l'icône Expo ;
   - `docs/current-state/DEPLOYMENT.md` compte 9 suites hors PostgreSQL en CI ;
   - `CLAUDE.md` donnait 1 616 lignes à `ses-api.js` et disait la base sans pré-alertes ;
   - la liste de mise en production demandait de remplacer l'icône, déjà fait.

   Un bandeau renvoie maintenant vers ce document ; `CLAUDE.md` et la liste sont corrigés.
2. **Les 4 suites navigateur ne tournent pas en CI**. Trois étaient périmées et l'audit les a réparées : la période « Personnalisée » passe désormais par le menu, la politique de contenu bloquait les sondes, et l'image de secours se testait sur un délai fixe. Elles demandent aussi un Chromium Linux ; `SES_CHROME` permet désormais de les lancer sur un poste.
3. `ses-admin.js` (≈ 1 900 lignes) et `ses-api.js` (≈ 2 650 lignes) concentrent la logique de l'interface : à découper par onglet le jour où le noyau prend le relais, pas avant.
4. Le cache se versionne à la main par commande (`versionner.py`, `?v=45`) : fiable mais à ne jamais oublier.
5. Application : aucune suite pour les écrans eux-mêmes (les tests portent sur la logique, les textes et le contrat).
6. Les essais « production » dépendent de l'historique Git complet (`git show <commit>:fichier`) : la CI le récupère (`fetch-depth: 0`).

## J. Dépendances

| Dépendance | Rôle | Risque si elle manque |
|---|---|---|
| Supabase (Auth, PostgREST, Realtime, PostgreSQL) | toute la donnée et toutes les règles | arrêt complet de l'espace client et du tableau de bord ; le site public reste lisible |
| GitHub (dépôt, Actions, Pages) | publication, CI | plus de mise en ligne ; le site publié reste servi |
| Expo / EAS (builds, mises à jour OTA) | application mobile | plus de nouvelle version ; l'application installée continue |
| Firebase Cloud Messaging | notifications Android | à configurer ; sans lui, aucune notification Android |
| Brevo (SMTP) | e-mails d'Auth et notifications | à confirmer ; sans lui, inscriptions perdues |
| `age` (chiffrement des sauvegardes) | sauvegarde | clé privée à garder hors de l'ordinateur et de GitHub |
| PGlite 0.5.8, PostgreSQL 16 (essais), Playwright 1.63 + axe-core 4.13 (navigateur) | tests seulement, hors dépôt | rien en production |
| Bibliothèques servies depuis `vendor/` (Supabase, QR, codes-barres) | site | aucune dépendance à un CDN tiers pour le code |

## K. Données à préserver

Toutes les tables de production sont des **données réelles** : `clients` (dont `code` `SES-#####` et `matricule`), `colis` (anciens
numéros `SES-10003-HT` et nouveaux numéros à 10 chiffres, imprimés sur des étiquettes déjà collées), `colis_historique`, `factures`
(montants **gelés**, `montant_paye`, factures groupées), `prealertes`, `appareils`, le registre **`matricules_attribues`** (jamais
réécrit, jamais effacé), et les comptes `auth.users`. À cela s'ajoutent les jetons de suivi des QR déjà imprimés.

Règles qui en découlent : aucune suppression, aucun `drop`, aucune réécriture de numéro ou de montant ; toute migration
`add … if not exists`, rejouable, testée sur PostgreSQL réel par deux chemins (production simulée et installation neuve) ; aucune
donnée inventée (ni paiement, ni succursale, ni position : `MIGRATION-STRATEGY.md`).

## L. Plan de migration

Chaque étape exige : une sauvegarde de moins de 24 h **vérifiée par restauration**, `verifier.sh` vert avec PostgreSQL, un retour
arrière écrit, et l'accord explicite du propriétaire. Le propriétaire colle lui-même le SQL, dans le projet `speed-express-site`.

| Étape | Contenu | Contrôle après coup |
|---|---|---|
| 0 | **Sauvegarde** opérationnelle (F1) et protection de `main` / `github-pages` (F2) | résumé « verification: complete » ; un envoi de test bloqué en attente d'approbation |
| 1 | Recoller **tout** `supabase-maj.sql` (rejouable) pour y ajouter les sections 9 et 10 (F3) — après un essai dédié du chemin « production réelle » : fichiers jusqu'à la section 8, puis les migrations du 7 octobre, puis `supabase-maj.sql` complet | `select has_function_privilege('anon','public.est_admin()','execute');` → `false` ; `select to_regprocedure('public.enregistrer_appareil(text,text)') is not null;` → `true` ; `prosrc` de `prevenir_client` sans `extensions.net` |
| 2 | Firebase (FCM), puis nouveau build Android | un téléphone enregistré ; un changement de statut réel passe **et** notifie |
| 3 | Noyau 001 → 002 (modèle, rattrapage) | comptes identiques (`DATA-MIGRATION-MAP.md`) |
| 4 | 003 → 007 (états, entrepôt, transport, dernier kilomètre, finance) | `GO-LIVE-CHECKLIST.md` §4 |
| 5 | 008 → 011 (portail, centre, notifications, applications) | nombre de fonctions `lg_%` croissant, aucune erreur |
| 6 | 012 → 013 (analytique, exploitation) | `ses_health()` → `"status": "ok"`, `schema_level: 13` |
| 7 | Interrupteurs `centreNoyau` puis `portailNoyau`, un par un | un membre de l'équipe ouvre le centre ; trois clients réels voient leur portail |
| 8 | Double écriture (étape 3 de `MIGRATION-STRATEGY.md`), puis bascule colis par colis | `reconcile` sans écart |

## M. Plan de rollback

| Élément | Premier geste | Ensuite |
|---|---|---|
| Site | `git revert` du commit fautif, « pousse » (la CI republie) | relancer le déploiement d'un commit connu (`workflow_dispatch`) |
| Interrupteur du noyau | le remettre à `false` (le site retombe sur l'ancien espace et l'ancien tableau de bord) | — |
| Migration héritée (`outils/*.sql`) | elles n'ajoutent que des colonnes, fonctions et déclencheurs : redéfinir la fonction précédente (`git show <commit>:fichier`) | restauration depuis la sauvegarde de référence si une donnée a changé |
| Noyau 001 → 013 | tant que rien ne lit le noyau : `drop schema logistics cascade` (et `analytics`, `ops`) — **seulement avec accord écrit et sauvegarde** | `docs/production/ROLLBACK.md` |
| Application | republier la mise à jour OTA précédente sur `preview` (`eas update:republish`) | réinstaller l'APK précédent |
| Données | `docs/backup/RESTORE-PROCEDURE.md` (restauration dans une base vide, validation, bascule) | **impossible tant que F1 n'est pas levé** |

## N. Plan de tests

| Niveau | Contenu | Où | État |
|---|---|---|---|
| Statique et contrats | 25 suites : pages, publication, sécurité, sauvegarde, traductions, tableau de bord, performances, SEO, accessibilité, API, rôles, scanner, portail, centre, notifications, poste, analytique, exploitation, pré-alertes, fenêtres, réglages | `verifier.sh`, CI | PASS |
| PostgreSQL WASM | 5 suites : rôles, tableau de bord, numéros, pré-alertes, identifiants d'équipe | `SES_TEST_DEPS`, CI | PASS |
| PostgreSQL 16 réel | 15 suites : rejeu du schéma, sécurité SQL, sauvegarde de bout en bout, noyau 001 → 013 | `SES_PG_BIN`, CI | PASS |
| Navigateur réel | 4 suites : qualité, tableau de bord, performances, accessibilité (axe-core, clavier) | `SES_TEST_DEPS` + Playwright (+ `SES_CHROME` sur un poste) ; **hors CI** | 3 PASS, accessibilité partielle (voir le rapport) |
| Application | 6 suites (stockage chiffré, opérations, contrat RPC, textes, variantes), `tsc`, `lint` | `npm run essai` (dépôt de l'application) ; **hors CI** | PASS |
| Production | contrôles en lecture seule après chaque collage ; sonde `ses_health` après 013 | SQL Editor, `curl` avec la clé publique | à faire à chaque étape |
| Manquants | parcours réel de bout en bout (inscription → colis → facture → paiement → notification) sur une **préproduction** ; essais sur iPhone ; suites navigateur en CI | — | à créer |

Commandes :

```bash
SES_TEST_DEPS=/dossier/pglite SES_PG_BIN=/dossier/bin bash outils/tests/verifier.sh
SES_TEST_DEPS=/dossier/playwright SES_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" node outils/tests/dashboard-browser.mjs
```

## O. Plan de mise en production

L'ordre est celui de [`docs/production/GO-LIVE-CHECKLIST.md`](../production/GO-LIVE-CHECKLIST.md), précédé des gestes que cet audit rend
prioritaires. Rien ne part sans un « pousse » du propriétaire, ni aucune migration sans son collage et une requête de contrôle.

1. **Protéger la production** : `main` protégée, relecteur obligatoire sur `github-pages`, Dependabot actif, `recup-reference.yml` retiré
   par PR, PR n° 17 et branches `arena/…` triées.
2. **Sauvegarde** quotidienne chiffrée, restauration de contrôle réussie, clé `age` testée hors de l'ordinateur.
3. **Préproduction** : un second projet Supabase gratuit ; chaque migration y passe d'abord.
4. **Héritage à jour** : sections 9 et 10 de `supabase-maj.sql` (F3), SMTP Brevo confirmé par un e-mail reçu.
5. **Notifications** : Firebase, build Android, essai réel ; puis iPhone (compte Apple).
6. **Noyau** 001 → 013, étape par étape (L), puis les travaux planifiés (sauvegarde, notifications, analytique).
7. **Interrupteurs** du centre puis du portail ; application « Opérations » en distribution privée.
8. **Signature** de chaque étape dans le tableau du §8 de la liste de mise en production.
