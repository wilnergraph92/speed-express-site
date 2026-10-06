# Runbook — l'exploitation au quotidien

> Pour la personne qui fait tourner Speed Express. Chaque procédure dit **quoi regarder, quoi faire, quoi ne jamais faire**.
> Règles permanentes : ne jamais supprimer de données de production ; vérifier le projet Supabase (`speed-express-site`, jamais Goship)
> avant toute requête ; jamais de clé secrète dans le dépôt, dans un navigateur ou dans une conversation.

## 1. Chaque jour (2 minutes)

1. Tableau de bord > Centre de commande > **Santé** : état général OK ? Sinon, la ligne en alerte renvoie à la §3.
2. Sauvegarde de la nuit : contrôle `backup_age_hours` OK (ou, à défaut, le résumé du workflow dans le dépôt privé).
3. Centre > « À traiter » : demandes d'enlèvement et de livraison, tickets en attente.

## 2. Chaque semaine

- Restauration de contrôle récente (`restore_check_age_days` < 8 j).
- Analytique : aucun jour manquant ; un « Vérifier » sur une exécution de la semaine passée → « Reproductible ».
- Lire les dernières erreurs des navigateurs : une même erreur qui revient est un défaut du site à corriger.

## 3. Procédures

### 3.1 Les événements s'accumulent (`events_pending`, `events_oldest_minutes`)
Le moteur d'événements (étape 003) répartit les événements aux abonnés. Si la file grossit :
`select subscriber_code, status, count(*), min(created_at) from logistics.event_delivery where status in ('PENDING','IN_PROGRESS') group by 1, 2;`
Un abonné bloqué : lire `last_error` de ses lignes. Relancer une répartition : `select logistics.dispatch_events(500, '<abonné>');`
(les rejeux sont sans risque : un abonné ne reçoit jamais deux fois le même événement). **Ne jamais** supprimer de lignes.

### 3.2 Échecs définitifs (`dead_letters_open`)
`select id, subscriber_code, error, failed_at from logistics.dead_letter where resolved_at is null order by id;`
Corriger la cause, puis noter la résolution (la ligne reste, pour l'historique) :
`update logistics.dead_letter set resolved_at = now(), resolution_note = '<ce qui a été fait>' where id = <n>;`

### 3.3 La sauvegarde n'a pas tourné (`backup_age_hours` en échec)
Dépôt privé > Actions > « Sauvegarde quotidienne » : lire le résumé. « jamais » dans la page Santé alors que le workflow réussit : le rôle de
`SES_DB_URL` n'a pas le droit d'exécuter `ses_ops_heartbeat` (GO-LIVE §5). Restaurer : [docs/backup/RESTORE-PROCEDURE.md](../backup/RESTORE-PROCEDURE.md).

### 3.4 Un compte touche un plafond (`rate_limited_windows_24h`, erreur « trop de demandes »)
`select actor, bucket, window_start, hits, max_hits from ops.rate_counter where hits >= max_hits order by window_start desc;`
Un client réel : le plafond se libère seul à la fenêtre suivante (1 h au plus pour le portail, 10 min pour le terrain). Un robot : bloquer
le compte dans Supabase > Authentication. Les plafonds sont dans `ops.limit_of` (013) : les changer = une nouvelle migration, testée.

### 3.5 Recalculer les rapports
Centre > Analytique > « Recalculer la période » (direction ; 367 jours au plus par calcul ; jamais l'avenir). Chaque calcul est tracé ;
les anciens restent consultables.

### 3.6 Passer une migration
GO-LIVE §4 : sauvegarde vérifiée d'abord ; une étape à la fois ; **dans l'ordre** ; vérifier ; rejouer la dernière étape est sans risque,
rejouer une étape ancienne après une plus récente ne l'est pas (006 échoue).

### 3.7 Mettre en ligne une modification du site
`python3 outils/mise-en-page.py` (doit annoncer « 0 modifiées » au second passage) → `python3 outils/versionner.py` si des fichiers servis
ont changé → `bash outils/tests/verifier.sh` → PR → relecture → envoi sur `main` → approbation de l'environnement `github-pages`. La CI
refait tous les essais (PostgreSQL compris) : un échec bloque la mise en ligne.

### 3.8 Allumer / éteindre une fonction
Les interrupteurs de `assets/js/config.js` (`portailNoyau`, `centreNoyau`) : GO-LIVE §6. Éteindre est toujours sûr (repli sur l'existant).

### 3.9 Faire tourner une clé
| Clé | Où elle vit | Comment la changer |
|---|---|---|
| Clé publique Supabase (`sb_publishable_…`) | `assets/js/config.js` (publique par nature) | Supabase > API Keys : nouvelle clé, `config.js`, mise en ligne, puis révoquer l'ancienne |
| Clé secrète Supabase | secrets GitHub des dépôts **privés** seulement | Supabase > API Keys ; mettre à jour les secrets ; relancer un passage |
| Clé API Brevo (travailleur) et clé SMTP Brevo (Supabase) | secret du dépôt privé ; réglages SMTP de Supabase | Brevo > SMTP & API ; remplacer ; envoyer un e-mail de test |
| Jeton Expo | secret du dépôt privé | expo.dev > Access tokens |
| Clé `age` | publique : variable du workflow ; privée : hors ligne | générer une paire (`scripts/backup/generer-cle.sh`), garder l'ancienne privée tant que des sauvegardes l'utilisent |

## 4. Environnements et interrupteurs
Voir [GO-LIVE-CHECKLIST](GO-LIVE-CHECKLIST.md) §0 et §6. Il n'y a pas de préproduction aujourd'hui : chaque migration est d'abord
prouvée sur PostgreSQL jetable (localement et dans la CI).
