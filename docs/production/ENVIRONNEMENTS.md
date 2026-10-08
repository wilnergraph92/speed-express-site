# Environnements : développement → préproduction → production

> Mis en place le 8 octobre 2026 (phase 1 « sécuriser la production »). Rien de ce document ne touche la production : la
> préproduction est un **second projet Supabase**, séparé, avec ses propres clés, et uniquement des données synthétiques.

## 1. La chaîne

```
 DÉVELOPPEMENT                    PRÉPRODUCTION (staging)                       PRODUCTION
 poste local                      poste local + projet Supabase séparé          GitHub Pages + projet speed-express-site
 ───────────                      ─────────────────────────────────            ──────────────────────────────────────
 mode « demo » (localStorage)     node outils/staging/servir.cjs               https://wilnergraph92.github.io/speed-express-site
 PostgreSQL jetable des essais    http://localhost:8792                         https://ltbqqchtyzlyakcsxxis.supabase.co
 aucune donnée réelle             données SYNTHÉTIQUES seulement                données réelles
        │                                   │                                              ▲
        │ branche + PR                      │ migration collée ici D'ABORD,                │ fusion de la PR (CI « valider » verte)
        └── CI « valider » (tests) ────────►│ parcours essayés à la main ─────────────────►│ + VOTRE approbation du déploiement
                                            │                                              │ + migration collée à la main, après
                                            │                                              │   sauvegarde « avant migration »
```

| | Développement | Préproduction | Production |
|---|---|---|---|
| Site | dossier servi en local, mode démo | `servir.cjs` sur `127.0.0.1:8792`, bandeau « PRÉPRODUCTION » | GitHub Pages, branche `main` |
| Base | aucune (démo) ; PostgreSQL jetable pour les essais | projet Supabase **dédié** (ex. `speed-express-staging`) | projet `speed-express-site` |
| Clé | aucune | clé **publique** de préproduction, dans `outils/staging/config-staging.local.json` (non suivi) | clé **publique** de production, dans `assets/js/config.js` |
| Données | fictives, jetables | **synthétiques** (`donnees-synthetiques.sql`), jamais de copie de la production | réelles |
| Qui écrit | n'importe quelle branche | le propriétaire (collages) | `main` par PR uniquement ; migrations collées par le propriétaire |
| Application mobile | Expo en local | à venir : profil EAS « staging » (§7) | canal `preview` aujourd'hui |

## 2. Ce que GitHub impose désormais (réglé le 8 octobre 2026)

- **`main` protégée** : aucun envoi direct, même pour l'administrateur ; **PR obligatoire** ; le contrôle **`valider`** (toute la suite
  de `outils/tests/verifier.sh`, PostgreSQL compris, et la régénération des 28 pages) doit être **vert et à jour** avant la fusion ;
  ni envoi forcé, ni suppression de la branche.
- **Déploiement approuvé** : l'environnement `github-pages` exige **votre approbation** (Actions › exécution › *Review deployments* ›
  *Approve*). Une fusion lance la CI puis attend ce clic : rien ne part en ligne sans vous.
- **Alertes Dependabot** actives ; secret scanning et push protection actifs ; workflows en lecture seule par défaut ;
  le workflow ponctuel `recup-reference.yml` (droit d'écriture) est retiré.
- Une PR affiche dans son résumé la **nature** de ses fichiers (migrations / site / préproduction / outillage / documentation) ; une
  migration y est signalée : **la fusion ne l'applique pas**.

Retirer temporairement une protection (urgence) : *Settings › Branches* ou *Environments* ; la remettre aussitôt, et le noter dans
l'incident.

## 3. Créer la préproduction (une fois, propriétaire)

1. supabase.com › *New project* : nom **`speed-express-staging`**, mot de passe de base fort (gardé dans votre gestionnaire, jamais
   communiqué), même région que la production. Offre gratuite suffisante.
2. **Vérifiez en haut de la page que vous êtes dans `speed-express-staging`.** SQL Editor : coller le fichier produit par
   `python3 outils/staging/assembler-installation.py` (`outils/staging/sortie/installation-staging.sql`), *Run*.
   Il pose le marqueur `staging` puis installe l'espace client tel qu'en production (même schéma, éprouvé par `staging-essai.py`).
   Collé par erreur sur la production, il **refuse** et n'applique rien.
3. SQL Editor : `outils/staging/donnees-synthetiques.sql` (12 clients, équipe, 60 colis, factures, pré-alertes, tout inventé).
4. *Authentication › URL Configuration* : **Site URL** `http://localhost:8792` ; **Redirect URLs** `http://localhost:8792/**`.
   (La production garde les siennes : voir la liste de contrôle de sécurité.)
5. *Settings › API* : copier l'URL et la clé **publique** (`sb_publishable_…`) dans
   `outils/staging/config-staging.local.json` (modèle : `config-staging.exemple.json`). **Jamais la clé secrète.**
6. `node outils/staging/servir.cjs` → http://localhost:8792. Le serveur refuse de démarrer s'il reçoit l'adresse ou la clé de la
   production, une clé secrète, ou le projet Goship.

## 4. Se connecter à la préproduction

Les comptes synthétiques n'ont **pas de mot de passe** : personne ne peut s'y connecter. Créez votre compte sur
http://localhost:8792 (inscription normale ; l'e-mail de confirmation part par le service intégré de Supabase), puis, dans le SQL
Editor **de la préproduction** :

```sql
update public.clients set role = 'admin', code = null where email = 'votre-adresse@exemple.com';
```

Ce compte survit aux réinitialisations (§5) : seuls les comptes `@exemple.test` sont effacés.

## 5. Le cycle d'une migration

1. PR avec la migration et ses essais ; CI verte.
2. **Préproduction** : coller la migration, lancer la requête de contrôle, essayer les parcours touchés sur http://localhost:8792.
3. Si besoin de repartir propre : `reinitialiser.sql` puis `donnees-synthetiques.sql` (refusés hors préproduction, et au-delà de
   25 comptes réels).
4. **Production** : sauvegarde « avant migration » vérifiée ([BACKUP-AND-RECOVERY.md](BACKUP-AND-RECOVERY.md) §3), collage, requête
   de contrôle, mention dans la PR.
5. Le site : fusion de la PR, approbation du déploiement, contrôle en ligne.

## 6. Données de production : jamais en préproduction sans anonymisation

La préproduction Supabase ne reçoit **que** des données synthétiques. Quand un problème n'est reproductible qu'avec la forme des
données réelles :

1. sur **votre poste**, un PostgreSQL **vide et jetable** ; y passer `outils/staging/marquer.sql` (avant toute donnée) ;
2. y restaurer la dernière sauvegarde (`restaurer.py --mode postgres-vide`) ;
3. `outils/staging/anonymiser.sql` : noms, e-mails, téléphones, adresses, notes, descriptions, numéros de suivi des marchands,
   mots de passe, sessions, identités et téléphones enregistrés sont remplacés ou retirés ; les nombres, montants, statuts, numéros
   SES et codes clients restent (`staging-essai.py` le prouve) ;
4. travailler sur cette copie locale, puis la **détruire**. Elle ne remonte jamais vers un projet Supabase.

Les scripts refusent toute base sans marqueur ; le marqueur se pose seulement sur une base où l'espace client n'existe pas encore.

## 7. Application mobile (à faire, dépôt `speed-express-app`)

Aujourd'hui l'URL et la clé de la production sont écrites dans `src/api/supabase.ts`. Pour une préproduction mobile, sans nouvelle
brique :
- lire `EXPO_PUBLIC_SUPABASE_URL` / `EXPO_PUBLIC_SUPABASE_KEY` avec repli sur la production ;
- un profil EAS `staging` (canal `staging`, variables de préproduction, nom « SES Préprod », autre identifiant de paquet pour coexister
  avec l'application réelle sur le téléphone) ;
- un essai qui refuse un build `production` pointant ailleurs que la production, et un build `staging` pointant vers elle.
Ce changement touche l'empreinte de l'application (nouveau build) : il fera l'objet de sa propre PR dans le dépôt de l'application.

## 8. Fichiers

| Fichier | Rôle |
|---|---|
| `outils/staging/marquer.sql` | pose le marqueur `staging` ; refuse une base qui porte déjà l'espace client |
| `outils/staging/assembler-installation.py` | assemble marqueur + migrations, dans une seule transaction, en `outils/staging/sortie/` (non suivi) |
| `outils/staging/donnees-synthetiques.sql` | le jeu d'essai, sans mot de passe |
| `outils/staging/reinitialiser.sql` | efface l'activité et les comptes synthétiques ; garde les vôtres |
| `outils/staging/anonymiser.sql` | anonymise une copie **locale** restaurée |
| `outils/staging/servir.cjs`, `config-staging.exemple.json` | le site de préproduction sur ce poste |
| `outils/tests/staging-essai.py`, `staging-serveur.cjs` | la preuve : 66 + 24 vérifications |
