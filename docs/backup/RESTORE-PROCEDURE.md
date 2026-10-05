# Procédure de restauration — Speed Express Shipping

> Version du 5 octobre 2026. Démontrée de bout en bout sur un PostgreSQL réel jetable
> (`outils/tests/sauvegarde-essai.py`, 54 vérifications) ; **jamais encore exercée sur
> le projet Supabase réel** (voir `BACKUP-STRATEGY.md` §9).

**Règle d'or : on ne restaure jamais par-dessus la production.** On restaure dans une
base **vide**, on **valide**, et seulement ensuite on bascule (`DISASTER-RECOVERY.md`).
Le script le garantit : il refuse une cible non vide, la base d'origine, et les projets
protégés (production et Goship).

## 1. Ce qu'il faut avoir
- l'archive `ses-….tar.gz.age` (artefact du dépôt de sauvegardes, ou copie hors ligne) ;
- la **clé privée** `.key` (hors ligne) — **jamais** dans le dépôt, droits `600` ;
- `age`, Python 3, et pour une base locale `postgresql@17` (même version majeure que le serveur) ;
- une **base cible vide** et sa chaîne de connexion :
  - répétition : un PostgreSQL local, ou un projet Supabase de répétition vide (mode `supabase-vide`) ;
  - sinistre : un projet Supabase **neuf** (mode `supabase-vide`).

```bash
export SES_PG_BIN="$(dirname "$(command -v pg_restore)")"   # si pg_restore n'est pas dans le PATH
export SES_RESTORE_DB_URL='postgresql://postgres:MOT_DE_PASSE_ENCODE@127.0.0.1:5432/restauration'
```
(Le mot de passe contenant `@ / : ? # %` doit être encodé : `%40 %2F %3A %3F %23 %25`.)

## 2. Le plan d'abord, toujours
Sans `--executer`, le script **déchiffre, contrôle les sommes, interroge la cible en
lecture, vérifie les garde-fous, affiche le plan, et s'arrête. Rien n'est écrit.**

```bash
python3 scripts/restore/restaurer.py \
  --archive ~/sauvegardes-ses/ses-20261005T061700Z.tar.gz.age \
  --identite ~/cles-ses/ses-sauvegarde.key \
  --mode postgres-vide
```
Lisez : nombre de tables et de lignes annoncé, cible affichée (sans mot de passe),
refus éventuels.

## 3. Restaurer pour de bon (répétition)
Même commande + `--executer`. Ordre exécuté — il compte :

| # | Étape | Pourquoi dans cet ordre |
|---|---|---|
| 1 | socle (`postgres-vide` seulement) : rôles, schéma `auth`, extensions | un projet Supabase neuf l'a déjà |
| 2 | comptes (`auth.users`, `auth.identities`) | `public.clients` pointe vers `auth.users` |
| 3 | schéma `public` et données, **en une seule transaction** | tout ou rien : jamais de restauration à moitié |
| 4 | déclencheur d'inscription + temps réel (`post-restauration.sql`) | le déclencheur vit sur `auth.users` : un dump de `public` ne l'emporte pas |
| 5 | **validation** | voir §4 |

Sortie attendue : `VALIDATION OK : N table(s), M ligne(s) identiques à la sauvegarde`.
Sur un PostgreSQL ordinaire, ajoutez `--mode postgres-vide` (par défaut) ; sur un projet
Supabase neuf, `--mode supabase-vide`.

## 4. La validation : ce qu'elle compare
Pour **chaque** table (y compris celles ajoutées depuis) : nombre de lignes **et
empreinte du contenu** (somme md5 de toutes les lignes) ; **séquences** (sinon le prochain
colis recevrait un numéro déjà pris) ; **squelette de sécurité** (nombre de règles RLS,
tables protégées, fonctions, déclencheurs) ; **déclencheur d'inscription** ; **absence de
table inattendue**. Toute différence = code de sortie 1 et liste des anomalies.

## 5. Contrôles à faire à la main après une restauration réelle
La validation prouve que les données sont identiques. Vérifiez aussi que **l'application
fonctionne** sur la base restaurée (c'est ce que l'essai automatique fait, à reproduire) :
1. un client connecté ne voit que **ses** colis ;
2. un visiteur anonyme est refusé sur toutes les tables ;
3. le suivi public d'un numéro connu répond ;
4. créer un compte de test crée bien son profil ;
5. le prochain numéro de colis est supérieur au plus grand existant.

## 6. Ce qu'une archive ne contient pas : à refaire sur un projet neuf
| Élément | Où | Remarque |
|---|---|---|
| Extension `pg_net` | *Database › Extensions* | indispensable aux notifications ; **voir le défaut R18 de la baseline** avant de les réactiver |
| SMTP personnalisé, modèles d'e-mail | *Authentication › Emails / SMTP* | sinon limite d'envoi du fournisseur |
| Site URL, Redirect URLs | *Authentication › URL Configuration* | sinon les liens de confirmation renvoient à l'ancien site |
| Politique de mot de passe, limites | *Authentication* | |
| Nouvelle URL et clé publique | `assets/js/config.js` **et** `App_SES/src/api/supabase.ts` | l'application a l'adresse **écrite en dur** : une nouvelle URL exige une **nouvelle version** de l'application |
| Jetons des appareils | table `appareils` (restaurée) | les jetons Expo restent valables tant que l'application n'est pas réinstallée |
| Sessions ouvertes | — | les jetons de session changent : **chacun doit se reconnecter** ; les mots de passe, eux, sont conservés (hachés) |

## 7. Récupérer une seule chose (erreur humaine)
Exemple : des factures supprimées par erreur. **On ne restaure jamais l'archive sur la
production.** On la restaure dans une base **de répétition**, puis on recopie seulement
les lignes voulues.

```bash
# 1. restaurer l'archive dans une base de répétition (§3), puis, dans cette base :
psql "$SES_RESTORE_DB_URL" -c "\copy (select * from public.factures where client_id = '<uuid>') to 'factures-a-recuperer.csv' csv header"
# 2. relire le CSV, puis, en production, réinsérer ligne par ligne via le SQL Editor (INSERT … ON CONFLICT DO NOTHING).
```
Sans PostgreSQL : le dossier `csv/` de l'archive contient la table en clair
(`csv/factures.csv`).

## 8. Erreurs rencontrées pendant la mise au point (et leur remède)
| Message | Cause | Remède |
|---|---|---|
| `Restauration REFUSÉE : la cible n'est pas vide` | du contenu existe déjà dans `public` ou `auth.users` | choisir une base **vide** ; on n'écrase rien |
| `… est le projet protégé …` | la cible est la production ou Goship | choisir une autre cible (`DISASTER-RECOVERY.md` §4 pour le sinistre) |
| `la clé privée est DANS le dépôt Git` | fichier de clé sous le dépôt | le déplacer **hors dépôt** ; si commité, **la considérer compromise** |
| `la clé privée est lisible par d'autres comptes` | droits trop larges | `chmod 600 <fichier>` |
| `Somme de contrôle fausse` | archive altérée ou corrompue | reprendre une autre sauvegarde ; **ne jamais forcer** |
| `pg_dump est plus ancien que le serveur` | client PostgreSQL trop vieux | installer le client de la **même version majeure** |
| `Chaîne de connexion illisible` | mot de passe non encodé | encoder `@ / : ? # %` |
| `failed to decrypt` / `no identity matched` | mauvaise clé ou archive altérée | utiliser la clé qui correspond à la clé publique du jour de la sauvegarde |
| `CREATE SCHEMA public … already exists` | (corrigé) ordre de création du schéma public | le script l'écarte désormais de lui-même |
