# Sauvegarde et reprise — Speed Express Shipping

> Le document de **décision et d'exploitation**. Le détail technique reste dans
> [`docs/backup/BACKUP-STRATEGY.md`](../backup/BACKUP-STRATEGY.md) (architecture, chiffrement, contenu d'une archive),
> [`RESTORE-PROCEDURE.md`](../backup/RESTORE-PROCEDURE.md) (gestes de restauration) et
> [`DISASTER-RECOVERY.md`](../backup/DISASTER-RECOVERY.md) (scénarios de sinistre). En cas d'écart, ce sont les scripts
> (`scripts/backup/`, `scripts/restore/`) et leurs essais qui font foi.

## 0. État au 8 octobre 2026 — à lire d'abord

| Élément | État |
|---|---|
| Scripts de sauvegarde, de vérification et de restauration | **écrits et éprouvés** : `sauvegarde-essai.py` (sauvegarde chiffrée → restauration → comparaison, sur PostgreSQL 16 réel), `sauvegarde-statique.py` |
| Sauvegarde quotidienne de la production | **NON INSTALLÉE** : il manque le dépôt privé, la clé `age`, le secret de connexion (§7) |
| Sauvegardes natives Supabase | **inconnues** : dépendent de l'offre (Free : aucune) ; à lire dans *Settings › Billing* et *Database › Backups* |
| Conséquence | **Aucune sauvegarde des données réelles n'est démontrée.** C'est le risque n° 1 de l'audit (F1). Aucune migration métier avant que §7 soit fait. |

## 1. Ce qui est sauvegardé, et ce qui ne l'est pas

| Sauvegardé (archive chiffrée) | Non sauvegardé (se reconstruit) |
|---|---|
| tout le schéma `public` : tables, données, fonctions, déclencheurs, sécurité par ligne, droits, vues, séquences — et, une fois installés, les schémas du noyau | réglages d'Auth du tableau de bord Supabase (à recopier depuis `docs/security/AUTH-HARDENING.md`) |
| les comptes : `auth.users`, `auth.identities` (mots de passe **hachés** : les clients gardent le leur) | l'extension `pg_net`, les clés d'API (régénérées par Supabase) |
| une copie CSV de chaque table, lisible sans PostgreSQL | le code du site et de l'application (dans Git) |
| un manifeste : lignes et empreinte de chaque table, séquences, squelette de sécurité | les secrets des travaux planifiés (dans les dépôts privés) |

## 2. Fréquence, rétention, responsable

| Copie | Fréquence | Rétention | Où | Responsable |
|---|---|---|---|---|
| **B. Sauvegarde quotidienne chiffrée** | tous les jours à 02 h 17 (Saint-Domingue) | 90 jours | artefacts du dépôt GitHub **privé** `speed-express-sauvegardes` | automatique ; le **propriétaire** lit le résumé chaque semaine |
| **B'. Sauvegarde avant migration** | avant **chaque** collage SQL en production (§3) | 90 jours (nommée `ses-avant-migration-…`) | idem | la personne qui colle la migration |
| **C. Copie hors ligne** | mensuelle (la dernière du mois) | 30 jours, 12 semaines, 12 mois, 5 ans (`rotation.py`) | disque ou clé USB du propriétaire, chiffrée | le **propriétaire** |
| A. Sauvegardes Supabase | quotidienne (offre Pro et plus) | 7 jours (Pro) | chez Supabase | le fournisseur — **jamais la seule copie** |

Clé de déchiffrement (`age`) : **deux copies hors ligne** dans deux lieux, jamais dans Git, jamais en secret d'Actions, jamais
envoyée par message. Sans elle, aucune sauvegarde n'est lisible par personne. Une seconde clé publique (personne de confiance)
peut être ajoutée à `SES_AGE_RECIPIENT`.

## 3. Avant chaque migration (règle sans exception)

1. Ouvrir le dépôt `speed-express-sauvegardes` › *Actions* › *Sauvegarde quotidienne* › **Run workflow**, motif
   `avant-migration-<nom-du-fichier>` (par exemple `avant-migration-supabase-maj-securite`).
2. Attendre la fin : le résumé doit dire **`verification: complete`** (l'archive a été restaurée dans une base jetable et
   comparée, table par table, à la base d'origine). Sinon : **on ne colle rien**.
3. Coller la migration d'abord en **préproduction** ([ENVIRONNEMENTS.md](ENVIRONNEMENTS.md) §5), puis en production, puis lancer la
   **requête de contrôle** de la PR.
4. Noter dans la PR : l'identifiant de l'archive « avant », l'heure du collage, le résultat de la requête de contrôle.

## 4. Vérification

| Quand | Quoi | Qui |
|---|---|---|
| à **chaque** sauvegarde | sommes de contrôle ; complétude ; **restauration de contrôle** dans un PostgreSQL 17 jetable, comparée au manifeste (lignes, empreintes, séquences, sécurité) ; une différence = échec, rien n'est gardé | automatique |
| à chaque échec | e-mail de GitHub (échec du workflow) ; une fois l'étape 013 installée, la page **Santé** passe en alerte (`backup_age_hours` > 26 h) | automatique → propriétaire |
| **silence** | pas de nouvelle ligne au journal depuis 36 h = la sauvegarde ne tourne plus : même gravité qu'un échec | propriétaire (lecture hebdomadaire) |
| **chaque trimestre** | **exercice de restauration** avec la clé hors ligne, dans un PostgreSQL jetable (§5), chronométré | propriétaire |

Ce que la vérification automatique ne prouve pas : qu'on sait **déchiffrer** (la CI n'a que la clé publique). Seul l'exercice
trimestriel le prouve.

## 5. Restauration

Toujours dans une base **vide** ; le script refuse sinon, refuse la base d'origine, et refuse la production ou Goship sans double clé
explicite. Par défaut il **n'affiche que son plan** ; il n'écrit qu'avec `--executer`.

| Besoin | Cible | Commande (détail : `RESTORE-PROCEDURE.md`) |
|---|---|---|
| exercice, contrôle, enquête | PostgreSQL local jetable | `restaurer.py --archive … --identite … --mode postgres-vide` puis `--executer` |
| copie de travail **anonymisée** | PostgreSQL local jetable, marqué d'abord (`outils/staging/marquer.sql`) | restauration comme ci-dessus, puis `outils/staging/anonymiser.sql` ([ENVIRONNEMENTS.md](ENVIRONNEMENTS.md) §6) — jamais vers un projet Supabase |
| reprise après sinistre | **nouveau** projet Supabase | `--mode supabase-vide`, puis bascule de `config.js` par PR : `DISASTER-RECOVERY.md` |

## 6. Objectifs de reprise

| Objectif | Valeur visée | Comment elle est tenue | Statut |
|---|---|---|---|
| **RPO** — perte de données maximale | **24 heures** (sauvegarde quotidienne) ; **0** pour une migration ratée (sauvegarde « avant migration ») | §2, §3 | **non tenu tant que §7 n'est pas fait** |
| **RTO** — remise en service | **4 heures** (nouveau projet Supabase + restauration + bascule de `config.js`) | `DISASTER-RECOVERY.md` | **à mesurer** au premier exercice trimestriel, puis à corriger ici |
| RTO du site seul (pages) | quelques minutes : republier un commit connu (`workflow_dispatch` de « Mettre le site en ligne », approbation) | GitHub Pages | éprouvé à chaque mise en ligne |

Pour descendre sous 24 h de RPO : l'option PITR de Supabase (offre Pro, payante) permet de revenir à la seconde près ; décision du
propriétaire, à noter ici si elle est prise.

## 7. Mise en service (gestes du propriétaire, dans l'ordre)

1. Lire l'offre Supabase et *Database › Backups* ; noter ici l'offre et la version de PostgreSQL (`select version();`).
2. `brew install age` puis `bash scripts/backup/generer-cle.sh ~/cles-ses/ses-sauvegarde.key` ; deux copies hors ligne de la clé privée.
3. Créer le dépôt **privé** `speed-express-sauvegardes` ; y copier `scripts/backup/modele-workflow-sauvegarde.yml` en
   `.github/workflows/sauvegarde.yml`.
4. Dans ce dépôt privé : secret `SES_DB_URL` (chaîne de connexion du pooleur, **jamais communiquée à personne, ni à l'assistant**) ;
   variables `SES_AGE_RECIPIENT` (clé publique `age1…`), `SES_SCRIPTS_REF` (commit relu des scripts), `PG_MAJEUR`.
5. *Run workflow* (motif `quotidienne`) ; lire le résumé : `verification: complete`.
6. Premier exercice de restauration (§4) ; noter sa durée en §6.
7. Cocher la ligne correspondante de [GO-LIVE-SECURITY-CHECKLIST.md](GO-LIVE-SECURITY-CHECKLIST.md).

## 8. Reprise après sinistre (résumé)

| Scénario | Premier geste | Référence |
|---|---|---|
| migration ratée (données intactes) | redéfinir la fonction précédente (`git show <commit>:fichier`) ; pas de restauration | `docs/production/ROLLBACK.md` |
| données effacées ou corrompues | figer : couper l'écriture (interrupteurs, message) ; restaurer la sauvegarde « avant » dans une base jetable ; comparer ; réinjecter ce qui manque | `DISASTER-RECOVERY.md` §3 |
| projet Supabase perdu / compromis | nouveau projet, restauration `supabase-vide`, réglages d'Auth, nouvelle clé publique dans `config.js` (PR), application : mise à jour OTA | `DISASTER-RECOVERY.md` |
| clé `age` perdue | nouvelle paire ; les archives anciennes deviennent illisibles : d'où les deux copies hors ligne | §2 |
| compte GitHub compromis | le site se republie depuis une copie locale ; la base n'est pas atteinte (aucun secret dans ce dépôt) | `INCIDENT-RESPONSE.md` |

Après tout sinistre : consigner l'heure de début et de fin, la fenêtre de données perdues, les décisions, et corriger ce document.
