# Stratégie de sauvegarde — Speed Express Shipping

> Version du 5 octobre 2026. Sources : **[DOC]** documentation officielle Supabase lue
> ce jour ; **[ESSAI]** démontré sur un PostgreSQL réel jetable (jamais la production) ;
> **[?]** à confirmer par le propriétaire dans le tableau de bord Supabase.

## 1. Pourquoi une sauvegarde à part
Le dépôt Git sauvegarde le **code**. Les **données** — clients, comptes, colis,
historique, factures, appareils — vivent uniquement dans Supabase. Avant ce
document, rien ne démontrait qu'une copie existe ailleurs (constat R1 de
`ARCHITECTURE-BASELINE.md`).

Les sauvegardes du fournisseur ne suffisent pas, même quand elles existent :
elles restaurent **tout le projet** d'un bloc (le projet est inaccessible pendant
l'opération **[DOC]**), elles vivent dans le **même compte** que la base (suspension,
suppression, compromission), et elles ne permettent pas de récupérer *une seule
facture* effacée par erreur sans écraser tout le reste.

## 2. Ce que Supabase fournit **[DOC]**

| Offre | Sauvegardes automatiques | Rétention |
|---|---|---|
| Free | **aucune sauvegarde téléchargeable** ; la documentation recommande d'exporter soi-même | — |
| Pro | quotidiennes | 7 jours |
| Team | quotidiennes | 14 jours |
| Enterprise | quotidiennes | 30 jours |
| Option PITR (Pro et plus) | restauration à la seconde près | 7 / 14 / 28 jours (≈ 100 / 200 / 400 $ par mois d'après la page de tarification de la documentation) |

Les sauvegardes de base **n'incluent pas** les objets du Storage **[DOC]** (non utilisé
aujourd'hui). Elles ne contiennent pas non plus les **réglages** d'Auth (SMTP, modèles
d'e-mail, URL de redirection) ni les secrets : voir §6.

**Offre actuelle du projet : [?]** non lisible de l'extérieur. Pour la connaître :
Supabase › *Settings* › *Billing*, puis *Database* › *Backups*. **Si l'offre est Free,
la sauvegarde décrite ici est la seule qui existe.**

## 3. Architecture retenue : trois copies, deux supports, une hors du fournisseur

| Copie | Où | Fréquence | Rétention | Qui l'exploite |
|---|---|---|---|---|
| A. Sauvegardes Supabase | chez Supabase | quotidienne (Pro+) | 7 j (Pro) | le fournisseur ; **ne pas s'y fier seul** |
| B. **Sauvegarde logique chiffrée** | **artefacts d'un dépôt GitHub PRIVÉ** dédié | **quotidienne**, 02 h 17 heure de Saint-Domingue | 90 jours | GitHub Actions (`scripts/backup/`) |
| C. **Copie hors ligne** | disque dur / clé du propriétaire | **mensuelle** (la dernière du mois) | 12 mois + 5 ans (`rotation.py`) | le propriétaire, à la main |

La copie B est celle qui fait foi. Elle est **vérifiée à chaque exécution** (§5).
Objectifs à confirmer par exercice (§8) : **perte de données maximale 24 h** (RPO),
**remise en service en 4 h** (RTO).

> Pourquoi des artefacts d'un dépôt **privé** et surtout pas du dépôt du site : un
> dépôt public publie ses artefacts et ses journaux d'exécution. Le modèle de
> workflow (`scripts/backup/modele-workflow-sauvegarde.yml`) ne doit jamais être
> installé dans `speed-express-site`.

## 4. Contenu d'une sauvegarde **[ESSAI]**
Fichier `ses-AAAAMMJJTHHMMSSZ.tar.gz.age`, une fois déchiffré :

| Fichier | Contenu |
|---|---|
| `public.dump` | **tout** le schéma `public` : tables, données, fonctions, déclencheurs, règles de sécurité (RLS), droits, vues, séquences. Une table de logistique ajoutée demain y entre **sans modifier les scripts** (essai à l'appui) |
| `auth.dump` | les comptes : `auth.users` et `auth.identities` (e-mails, mots de passe **hachés**, métadonnées) — les clients gardent leur mot de passe |
| `csv/` | chaque table en CSV, lisible **sans PostgreSQL** (dernier recours) ; les comptes sans les mots de passe |
| `manifest.json` | pour chaque table : nombre de lignes et **empreinte du contenu** ; valeurs des séquences ; squelette de sécurité (nombre de règles, tables protégées, fonctions) |
| `SHA256SUMS` | somme de chaque fichier |

Tout est lu dans **une seule transaction figée, en lecture seule** : l'archive est
cohérente même si un client enregistre un colis pendant la sauvegarde.

**Ne sont pas dans l'archive** (à reconstruire, voir `RESTORE-PROCEDURE.md` §6) : les
réglages d'Auth du tableau de bord, l'extension `pg_net`, les clés d'API, les secrets
de la CI, le code (dans Git).

## 5. Vérification automatique (aucune sauvegarde n'est rendue sans)
1. **Somme de chaque fichier** contrôlée juste après l'écriture.
2. **Complétude** : le dump porte une entrée « données » pour chaque table du manifest.
3. **Restauration de contrôle** : l'archive est restaurée dans une base **vide et
   jetable** (un PostgreSQL 17 démarré pour l'occasion dans la CI), puis comparée au
   manifest : lignes, **empreinte du contenu de chaque table**, séquences, règles de
   sécurité, déclencheur d'inscription. **Une différence = la sauvegarde échoue** et
   rien n'est conservé.
4. **Journal** (`journal.jsonl`, une ligne par exécution) : date, fichier, taille,
   somme, nombre de tables et de lignes, niveau de vérification (`complete`), durée,
   version, hôte **sans mot de passe**, statut. Succès comme échec.

**Ce que cela prouve** : l'archive contient exactement ce que la base contenait, et se
restaure. **Ce que cela ne prouve pas** : qu'on saura la **déchiffrer** (la clé privée
est absente de la CI par conception) — c'est le rôle de l'exercice trimestriel (§8).

## 6. Chiffrement et clés
- Outil : **age** (chiffrement à clé publique). La CI ne connaît que la clé **publique**
  (`age1…`, variable `SES_AGE_RECIPIENT`) : elle peut chiffrer, elle ne peut pas
  déchiffrer. Même un accès au dépôt de sauvegardes ne livre que du chiffré.
- Création, **une fois, sur votre ordinateur** : `bash scripts/backup/generer-cle.sh ~/cles-ses/ses-sauvegarde.key`.
  Le script refuse de créer la clé dans le dépôt Git ou d'écraser une clé existante.
- **La clé privée n'est JAMAIS dans Git, ni en secret de CI, ni envoyée par message.**
  Le dépôt la refuse (test `sauvegarde-statique.py`, `.gitignore`, refus à l'exécution
  si le fichier est dans le dépôt ou lisible par d'autres comptes).
- **Sans la clé privée, aucune sauvegarde n'est lisible, par personne, jamais.**
  Faites-en **au moins deux copies hors ligne**, dans deux lieux (gestionnaire de mots
  de passe + papier ou clé USB). Vérifiez-les à chaque exercice.
- **Clé de secours** : `SES_AGE_RECIPIENT` accepte plusieurs clés publiques séparées par
  des virgules ; chaque sauvegarde est alors lisible par l'une ou l'autre. Recommandé :
  une seconde clé gardée par une personne de confiance.
- Clé perdue ou compromise : générer une nouvelle paire, changer la variable ; les
  anciennes archives restent lisibles seulement avec l'ancienne clé — **conservez-la**
  tant qu'elles ont une valeur.

## 7. Connexion à la base : le secret le plus sensible
La sauvegarde lit la base avec une **chaîne de connexion** (`SES_DB_URL`). Elle donne un
accès complet à la base : c'est **plus sensible que la clé publique** du site, et
comparable à la clé de service. Règles :
- elle se met **uniquement** dans un secret GitHub du dépôt privé de sauvegardes ; jamais
  dans un fichier, jamais dans le dépôt du site, jamais dans un message ;
- elle ne passe jamais en argument de commande (les scripts la transmettent par variables
  d'environnement) et n'est jamais écrite dans un journal (testé) ;
- si le mot de passe contient `@ / : ? # %`, il doit être **encodé** dans l'URL (`%40 %2F %3A %3F %23 %25`) ;
- **IPv4** : la connexion directe de Supabase est en IPv6 sur les offres sans l'option IPv4,
  que les exécuteurs GitHub n'ont pas. Utilisez le **pooleur en mode session** (port 5432,
  utilisateur `postgres.<référence-du-projet>`) **[DOC]** ; la documentation recommande la
  connexion directe pour `pg_dump` : **premier essai réel à valider** (§9) ;
- les scripts utilisés par la CI sont **épinglés sur un commit précis** (`SES_SCRIPTS_REF`),
  relu avant de l'avancer : une version modifiée à votre insu pourrait lire ce secret ;
- changez le mot de passe de la base si le secret a pu fuiter (Supabase › *Database* › *Settings*).

Un rôle dédié en lecture seule serait préférable, mais `pg_dump` doit lire à travers la
sécurité par ligne, ce qui exige l'attribut `BYPASSRLS` ; **à vérifier** s'il est
accordable sur Supabase avant d'y renoncer.

## 8. Rétention, exercices, surveillance
- **Rétention B** : 90 jours d'artefacts (réglage du dépôt : *Settings* › *Actions* ›
  *Artifact and log retention*). Limite à surveiller : le stockage des artefacts d'un
  dépôt privé gratuit est limité (≈ 500 Mo) : ne dépassez pas ≈ 5 Mo par sauvegarde × 90 ;
  la taille est dans le journal.
- **Rétention C** : `python3 scripts/backup/rotation.py --dossier ~/sauvegardes-ses`
  (30 jours, 12 semaines, 12 mois, 5 ans ; **plan seulement** tant qu'on n'ajoute pas
  `--appliquer` ; ne supprime jamais la plus récente).
- **Chaque mois** : télécharger la dernière sauvegarde (artefact), la copier hors ligne,
  lire le journal : chaque jour doit y figurer avec `statut: ok`, `verification: complete`.
- **Chaque trimestre — exercice de restauration** : déchiffrer avec la clé **hors ligne**,
  restaurer dans un environnement non productif (`RESTORE-PROCEDURE.md` §3), valider.
  Noter la **durée réelle** : c'est elle qui confirme ou corrige le RTO de 4 h.
- **Alerte** : GitHub envoie un e-mail à chaque échec du workflow (si les notifications
  du compte sont actives). **Un silence prolongé est aussi une alerte** : pas de nouvelle
  ligne au journal depuis 36 h = la sauvegarde ne tourne plus.

## 9. Mise en place — qui fait quoi
| # | Étape | Qui |
|---|---|---|
| 1 | Lire l'offre Supabase et *Database › Backups* ; noter le résultat | propriétaire |
| 2 | Installer `age` (`brew install age`), puis `bash scripts/backup/generer-cle.sh …` ; mettre la clé privée en lieu sûr (2 copies hors ligne) | propriétaire |
| 3 | Créer un dépôt GitHub **privé** `speed-express-sauvegardes` | propriétaire |
| 4 | Y copier `scripts/backup/modele-workflow-sauvegarde.yml` en `.github/workflows/sauvegarde.yml` | propriétaire (ou moi sur demande) |
| 5 | Secret `SES_DB_URL`, variables `SES_AGE_RECIPIENT`, `SES_SCRIPTS_REF`, `PG_MAJEUR` | propriétaire (la chaîne de connexion **ne m'est jamais communiquée**) |
| 6 | Première exécution manuelle (*Run workflow*), lire le résumé | propriétaire |
| 7 | Premier exercice de restauration (§8) | propriétaire, avec moi si besoin |

**Ce qui n'est pas encore démontré en réel** : le premier `pg_dump` contre la vraie base
Supabase (pooleur, structure réelle du schéma `auth`). Les essais ont tourné sur un
PostgreSQL 16 avec le **vrai schéma du projet** et des **données fictives**. La
restauration de contrôle quotidienne (§5.3) est justement le filet : si le schéma réel
diffère d'un détail, **la première exécution échouera bruyamment** plutôt que de produire une
fausse sauvegarde.

## 10. Outils
| Où | Outils |
|---|---|
| CI (Ubuntu) | Python 3, `postgresql-client-<majeur>` (même version majeure que le serveur), `age` — installés par le workflow |
| Poste du propriétaire | `age` ; pour les exercices : un PostgreSQL local (`brew install postgresql@17`) ou un projet Supabase de répétition vide |
