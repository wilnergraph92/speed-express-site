# Surveillance

> Source de vérité des seuils : `ops.status_checks()` dans `outils/logistique/013-exploitation.sql`. Ce tableau la recopie ; en cas d'écart,
> c'est le SQL qui fait foi (et ce document est à corriger). Décision : [ADR 0015](../architecture/ADR/0015-exploitation-dans-la-base-sans-nouvelle-pile.md).

## 0. Dès aujourd'hui, sans le noyau (8 octobre 2026)

La page Santé et ses quinze contrôles n'existent qu'avec l'étape 013. En attendant, et ensuite en complément :

| Quoi | Comment | Alerte |
|---|---|---|
| **Disponibilité** du site, de l'authentification et de la base ; **aucune table lisible sans connexion** ; fonctions internes fermées ; santé du noyau dès qu'il existe | `.github/workflows/surveillance.yml` toutes les 15 min → `scripts/surveillance/sonder.mjs` (lecture seule, clé publique, retenté deux fois) | panne : ticket **`alerte-production`** + e-mail de GitHub ; fermé automatiquement au retour. Alerte non critique (fonctions internes ouvertes) : seulement dans le résumé de l'exécution |
| Échecs de la CI, du déploiement, de la surveillance, de la sauvegarde | e-mails de GitHub Actions | propriétaire |
| Quotas Supabase (taille de base, bande passante) | *Settings › Usage* et e-mails de Supabase | propriétaire |
| Application mobile | aucun suivi d'erreurs (décision et ADR à prendre) ; les plantages Android sont visibles dans la console Google Play une fois publiée | — |

Une sonde qui échoue alors que le site répond pour vous : lire le résumé de l'exécution (Actions › Surveillance de la production), qui
dit quel contrôle a échoué et pourquoi. Le contrôle « aucune donnée lisible sans connexion » en échec est une **fuite de données** :
traiter comme un incident de sécurité (INCIDENT-RESPONSE.md), pas comme une panne.

## 1. Où regarder

| Quoi | Où | Qui |
|---|---|---|
| L'état de tout | Tableau de bord > Centre de commande > **Santé** (relu chaque minute) | direction |
| « La base répond-elle ? » | `POST https://<projet>.supabase.co/rest/v1/rpc/ses_health` avec l'en-tête `apikey: <clé publique>` | n'importe quelle sonde |
| Les rapports | Centre de commande > **Analytique** (et son journal des exécutions) | selon les droits |
| Les travaux planifiés | GitHub Actions des dépôts privés : résumé de chaque exécution, journal JSON | propriétaire |
| La base elle-même | Supabase > Reports, Logs | propriétaire |

Sonde externe (facultative, choix du propriétaire) : un service de surveillance gratuit appelle `ses_health` toutes les 5 minutes et
alerte si la réponse n'est pas `"status": "ok"`. La clé publique suffit ; aucune donnée n'est exposée.

## 2. Les quinze contrôles

| Code | Ce qu'il mesure | Alerte | Échec | Que faire |
|---|---|---|---|---|
| `events_pending` | livraisons d'événements en attente | 500 | 5 000 | le moteur d'événements ne suit plus : RUNBOOK §3.1 |
| `events_oldest_minutes` | âge de la plus vieille en attente | 15 min | 60 min | idem |
| `dead_letters_open` | échecs définitifs non résolus | 1 | 50 | lire l'erreur, corriger, marquer résolu : RUNBOOK §3.2 |
| `notifications_failed_24h` | notifications en échec sur 24 h | 1 | 25 | Centre > Notifications : santé des envois ; clé Brevo, expéditeur |
| `notifications_oldest_due_minutes` | plus vieille notification due | 30 min | 180 min | le travailleur ne tourne plus : workflow du dépôt privé |
| `backup_age_hours` | dernière sauvegarde **réussie** | 26 h | 50 h | workflow de sauvegarde ; « jamais » = aucun signal reçu |
| `restore_check_age_days` | dernière restauration de contrôle réussie | 8 j | 32 j | relancer la sauvegarde avec base de contrôle |
| `jobs_failed_24h` | signaux « échec » d'un travail planifié | 1 | 3 | lire le détail (page Santé > travaux planifiés) |
| `analytics_age_hours` | dernier calcul des rapports | 26 h | 72 h | planification de `ses_an_refresh` |
| `analytics_missing_days_7` | jours sans rapport sur 7 | 1 | 7 | Analytique > « Calculer ces jours » |
| `audit_entries_24h` | écritures du journal d'audit (information) | — | — | zéro un jour ouvré : vérifier que l'équipe travaille dans le noyau |
| `client_errors_24h` | erreurs JavaScript remontées | 10 | 100 | page Santé > dernières erreurs : page, source, référence |
| `rate_limited_windows_24h` | comptes ayant touché un plafond | 1 | 50 | un client qui insiste, ou un robot : RUNBOOK §3.4 |
| `database_size_mb` | taille de la base | 400 Mo | 480 Mo | offre gratuite : 500 Mo ; purger ou changer d'offre |
| `schema_level` | plus haute étape installée | < 13 | — | une étape manque |

L'état général est **Échec** si un contrôle l'est, **Alerte** si un contrôle l'est, **OK** sinon.

## 3. Les signaux des travaux planifiés

| Source | Émis par | Fréquence attendue |
|---|---|---|
| `backup` | `scripts/backup/sauvegarder.py --signaler` (OK, ou FAIL avec le message) | quotidienne |
| `restore_check` | le même, quand la restauration de contrôle a réussi | quotidienne |
| `notifications_worker` | `scripts/notifications/envoyer.mjs` en fin de passage (OK, ou WARN s'il y a eu des échecs) | toutes les 5 min une fois activé |
| `analytics_refresh` | (réservé : le contrôle `analytics_age_hours` lit directement les exécutions) | — |
| `deploy` | (réservé) | — |

## 4. Journaux et corrélation

| Journal | Forme | Contient |
|---|---|---|
| Travailleur des notifications | JSON, une ligne par fait, secrets masqués, adresses masquées | répartition, envois, bilan, battement |
| Sauvegarde | `journal.jsonl` (une ligne par exécution) + résumé GitHub | taille, tables, lignes, vérification, durée — jamais de mot de passe |
| Noyau | `logistics.audit_log`, `domain_event`, `command_log` | `correlation_id` commun à une opération et à ses événements ; clé d'idempotence d'un geste |
| Navigateurs | `ops.client_error` | page (sans paramètres), message nettoyé, source, **référence** = identifiant de la page ouverte |
| Analytique | `analytics.report_run` | chaque calcul : qui, quand, empreinte, état des sources |

Retrouver une erreur signalée par un client : lui demander l'heure et la page ; page Santé > dernières erreurs ; la colonne « Référence »
regroupe toutes les erreurs d'une même page ouverte.
