# Mise en production — liste de contrôle

> Pour le propriétaire. Chaque case est un **geste explicite** : rien ici ne se fait tout seul.
> Ordre impératif. Une case qui échoue arrête la suite : on corrige, ou l'on revient en arrière ([ROLLBACK](ROLLBACK.md)).
> État au 6 octobre 2026 : **rien de ce qui suit n'a été fait en production** (migrations 001 à 013 non appliquées, interrupteurs éteints).

## 0. Les environnements

| Environnement | Site | Base | Usage |
|---|---|---|---|
| **Développement** | dossier servi en local (`file:` ou `localhost`) | aucune : mode `demo` (tout dans le navigateur) | écrire, essayer l'interface |
| **Essais** | — | PostgreSQL **jetable**, créé et détruit par chaque test (`SES_PG_BIN`) ; aussi dans la CI | prouver chaque migration avant la production |
| **Préproduction** | `node outils/staging/servir.cjs` (http://localhost:8792) | un second projet Supabase, `speed-express-staging`, données synthétiques | **outillée le 8 octobre 2026** : [ENVIRONNEMENTS.md](ENVIRONNEMENTS.md) ; le projet reste à créer |
| **Production** | GitHub Pages (`main`) | le projet Supabase `speed-express-site` | les clients |

Le site choisit sa base par `assets/js/config.js` (`supabaseUrl`, `supabaseKey`) : une préproduction se fait avec une **copie locale** du
site dont `config.js` pointe vers le projet de préproduction — jamais en changeant le `config.js` publié.

## 1. Avant tout

- [ ] [GO-LIVE-SECURITY-CHECKLIST.md](GO-LIVE-SECURITY-CHECKLIST.md) déroulée (sauvegarde, remède de sécurité, réglages d'Auth).

- [ ] `git pull` ; la CI de `main` est **verte** (Actions > « Mettre le site en ligne »), y compris les essais PostgreSQL.
- [ ] Localement : `SES_TEST_DEPS=… SES_PG_BIN=… bash outils/tests/verifier.sh` → code 0.
- [ ] Une **sauvegarde chiffrée vérifiée par restauration** de moins de 24 h (workflow de sauvegarde, résumé « vérification complete »).
- [ ] La clé privée `age` de déchiffrement est hors de l'ordinateur et de GitHub, et **testée** (une restauration à blanc : [docs/backup/RESTORE-PROCEDURE.md](../backup/RESTORE-PROCEDURE.md)).

## 2. GitHub (réglages, une fois)

- [x] Protéger `main` : PR obligatoire, CI `valider` exigée, aussi pour l'administrateur (8 octobre 2026).
- [x] Settings > Environments > `github-pages` : **Required reviewers** = vous (8 octobre 2026).
- [x] Alertes Dependabot actives (8 octobre 2026).
- [x] Workflow ponctuel `recup-reference.yml` retiré (PR de la phase 1).

## 3. Supabase

- [ ] **Vérifier en haut de la page que le projet ouvert est `speed-express-site`** (jamais celui de Goship). À refaire avant CHAQUE requête.
- [ ] Authentication > SMTP : Brevo branché (la clé SMTP ne quitte pas Supabase) ; un e-mail de test reçu, pas en indésirable.
- [ ] Authentication > Rate limits : laisser les valeurs par défaut (ou les baisser) ; ne jamais désactiver.
- [ ] (Recommandé) Un projet de **préproduction** : y passer 001 → 013 d'abord, avec les mêmes contrôles qu'en §4.

## 4. Les migrations du noyau, une par une

Dans SQL Editor, **dans l'ordre**, chacune après la précédente vérifiée. Ne jamais rejouer une étape ancienne après une plus récente
(006 notamment ne le supporte pas) ; rejouer la DERNIÈRE est sans risque.

| Étape | Fichier | Vérification après coup (SQL Editor) |
|---|---|---|
| 001 → 002 | modèle, rétroremplissage | `select logistics.backfill_from_legacy();` puis comparer les comptes (docs/architecture/DATA-MIGRATION-MAP.md) |
| 003 → 007 | états, entrepôt, transport, dernier kilomètre, finance | `select count(*) from logistics.event_type;` ; aucune erreur |
| 008 → 011 | portail, centre, notifications, applications | `select count(*) from pg_proc where proname like 'lg\_%';` augmente à chaque étape ; aucune erreur |
| 012 | analytique | `select public.ses_an_refresh(date_trunc('year', current_date)::date, current_date);` → une exécution, `partial: true` |
| 013 | exploitation | `select public.ses_health();` → `{"status": "ok", "schema_level": 13, …}` |

- [ ] Après 013 : Centre de commande > **Santé** → seuls « sauvegarde » et « restauration » en échec (aucun signal encore) : c'est attendu.

## 5. Les travaux planifiés (dépôt **privé**, jamais ce dépôt public)

- [ ] Sauvegarde : copier `scripts/backup/modele-workflow-sauvegarde.yml`, secrets posés ; lancer **à la main** une fois ; résumé « complete ».
  Pour que le signal arrive dans la page Santé, le rôle de `SES_DB_URL` doit pouvoir exécuter la fonction :
  `grant execute on function public.ses_ops_heartbeat(text, text, jsonb) to <rôle_de_sauvegarde>;`
- [ ] Notifications : `scripts/notifications/modele-workflow-notifications.yml`, `NOTIFICATIONS_ACTIVES = true`, un passage manuel, lire le
  bilan ; seulement ensuite décommenter la planification.
- [ ] Analytique : planifier `select public.ses_an_refresh();` chaque nuit (pg_cron, ou le travailleur).
- [ ] Santé : tous les contrôles **OK** (ou alertes comprises et acceptées).

## 6. Les interrupteurs (`assets/js/config.js`, une PR, puis « pousse »)

| Interrupteur | Rôle | Allumer quand |
|---|---|---|
| `portailNoyau` | portail client du noyau (14 sections) | 001 → 008 passées, rattrapage vérifié sur 3 comptes réels |
| `centreNoyau` | centre de commande de l'équipe (dont Poste de scan, Analytique, Santé) | 001 → 009 passées (013 pour la Santé, 012 pour l'Analytique) |

Éteindre un interrupteur est le **premier** geste de retour en arrière : le site retombe sur l'espace et le tableau de bord d'avant.

- [ ] Monter le cache : `python3 outils/versionner.py` ; `bash outils/tests/verifier.sh` ; PR ; relecture ; **« pousse »** ; approuver le
  déploiement dans l'environnement `github-pages`.
- [ ] Après mise en ligne : un compte client réel ouvre son portail ; un membre de l'équipe ouvre le centre ; la page Santé est OK.

## 7. Applications mobiles

- [ ] Essais sur **un Android et un iPhone réels** (docs/architecture/MOBILE-OPERATIONS.md §5) ; jamais publié sans.
- [x] Remplacer l'icône de l'application par celle de la marque (fait le 7 octobre 2026, application `6b6e113`).
- [ ] « SES Opérations » en distribution privée (TestFlight, test interne Google Play).

## 8. Signature

| Date | Étape franchie | Par | Sauvegarde de référence |
|---|---|---|---|
| | | | |
