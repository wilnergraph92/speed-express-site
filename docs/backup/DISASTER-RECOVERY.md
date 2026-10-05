# Plan de reprise après sinistre — Speed Express Shipping

> Version du 5 octobre 2026. **Plan préparé, pas encore exercé en conditions réelles.**
> Objectifs **à confirmer par exercice** : perte de données maximale **24 h** (RPO) ;
> remise en service **4 h** (RTO). Les deux seront corrigés par la mesure du premier
> exercice (`BACKUP-STRATEGY.md` §8).

Ce document dit **quoi faire quand quelque chose est cassé**, dans l'ordre, sans
improviser. Principe : **d'abord arrêter l'hémorragie, ensuite comprendre, enfin
réparer.** Toute étape destructive est marquée ⛔ : on s'arrête, on relit, on confirme.

## 1. Les scénarios

| # | Scénario | Gravité | Chemin |
|---|---|---|---|
| S1 | **Erreur humaine** : lignes, factures ou table supprimées ; mauvaise requête dans le SQL Editor | élevée | §3.1 |
| S2 | **Migration SQL défectueuse** (comme `supabase.sql` rejoué, qui casse le suivi) | élevée | §3.2 |
| S3 | **Perte, suspension ou corruption du projet Supabase** | critique | §3.3 |
| S4 | **Fuite de la chaîne de connexion** (ou de toute clé) | critique | §3.4 |
| S5 | **Compte GitHub compromis** ou dépôt de sauvegardes perdu | élevée | §3.5 |
| S6 | **Clé privée de déchiffrement perdue** | critique | §3.6 |
| S7 | **Panne du fournisseur** (indisponibilité sans perte) | moyenne | §3.7 |

## 2. Avant de toucher à quoi que ce soit (tous scénarios)
1. **Ne pas aggraver.** Ne rien supprimer, ne rien « réessayer » en boucle, ne pas relancer `supabase.sql`.
2. **Noter l'heure** de la découverte et de la dernière chose connue bonne.
3. **Geler les écritures si les données sont en train de se corrompre.** Interrupteur du site : mettre `supabaseUrl` et `supabaseKey` à `''` dans `assets/js/config.js` et publier ; l'espace client affiche alors « fermé » au lieu de travailler sur de mauvaises données. (L'**application mobile** n'a pas d'interrupteur : elle continue de parler à la base.)
4. **Sauvegarder l'état cassé** avant de réparer (`sauvegarder.py`), pour pouvoir comparer et enquêter.
5. Choisir le scénario ci-dessous.

## 3. Les chemins

### 3.1 S1 — Erreur humaine (suppression, mauvaise requête)
1. Si le projet est en offre **Pro ou plus** : la restauration Supabase *Database › Backups* ramène **tout** le projet à un instant (⛔ le projet est inaccessible pendant l'opération, et tout ce qui a été écrit depuis est perdu) ; ne l'utiliser que si la perte est large.
2. **Sinon, ou pour récupérer peu de choses** : restaurer la dernière sauvegarde chiffrée dans une **base de répétition** (`RESTORE-PROCEDURE.md` §3), puis **recopier seulement les lignes manquantes** (§7 de la procédure). La production n'est jamais écrasée.
3. Valider (comptes, totaux de factures, séquences). 4. Consigner l'incident (§6).

### 3.2 S2 — Migration défectueuse
1. Ne pas empiler d'autres migrations. 2. Lire le message exact de l'erreur.
3. Si la migration est **rejouable et sans suppression** (c'est la règle du projet), la corriger puis la rejouer.
4. Sinon, restaurer dans un projet de répétition, **prouver le correctif** là-bas, puis l'appliquer en production. Jamais l'inverse.
5. Rappel connu : **ne rejouez pas `outils/supabase.sql`** (il recrée une seconde `suivre_colis`) ; seul `outils/supabase-maj.sql` se rejoue.

### 3.3 S3 — Projet Supabase perdu, suspendu ou corrompu : reconstruction
1. **Confirmer** auprès du fournisseur (état du projet, du compte, support). Ne pas reconstruire sur une simple alerte.
2. Récupérer la **dernière sauvegarde chiffrée** (artefact du dépôt de sauvegardes ; sinon la copie hors ligne la plus récente) et la **clé privée** hors ligne.
3. Créer un **projet Supabase neuf** (même version majeure de PostgreSQL ; région proche de Haïti/Saint-Domingue). Noter sa référence : ce sera la **nouvelle production**.
4. `python3 scripts/restore/restaurer.py … --mode supabase-vide` (plan), puis `--executer`. La cible neuve est vide : le script l'accepte. **Validation OK exigée** avant de continuer.
5. Refaire ce qu'une archive ne contient pas (`RESTORE-PROCEDURE.md` §6) : `pg_net`, SMTP, URL de redirection, politique de mot de passe.
6. Les clients gardent leur **mot de passe** (haché, restauré) ; leurs sessions sont invalidées : ils se reconnectent.
7. **Basculer** : mettre à jour `assets/js/config.js` (nouvelle URL, nouvelle clé publique `sb_publishable_…`), `python3 outils/versionner.py`, vérifier (`bash outils/tests/verifier.sh`), publier. Puis, côté **application**, `src/api/supabase.ts` et **une nouvelle version** à diffuser : tant qu'elle n'est pas installée, l'ancienne parle à l'ancienne adresse.
8. Contrôles (`RESTORE-PROCEDURE.md` §5), puis rouvrir.
9. **Perte de données = temps écoulé depuis la dernière sauvegarde (≤ 24 h)** : prévenir les clients concernés (colis enregistrés ce jour-là à ressaisir ; les étiquettes déjà imprimées d'après la base perdue ne résolvent plus).

> **Restauration dans le MÊME projet** (cas rare : la base est vide ou détruite mais le projet existe).
> ⛔ Le script refuse un projet protégé. La levée exige : `--autoriser-projet <référence>` **et**
> que la cible soit réellement vide. À ne faire qu'après avoir lu ce document en entier, et jamais seul.

### 3.4 S4 — Fuite d'une clé ou de la chaîne de connexion
1. **Changer le mot de passe de la base** (Supabase › *Database › Settings*) ; **changer** le secret `SES_DB_URL`.
2. Si la **clé de service** est en cause : la régénérer (⛔ ne pas toucher à *« Disable JWT-based API keys »* ni *Pause/Restart/Transfer project* sans être sûr). La clé **publique** (`sb_publishable_…`) n'est pas un secret : sa fuite ne change rien.
3. Auditer : *Logs* du projet (connexions inhabituelles) ; GitHub › *Security log*.
4. Si le dépôt de sauvegardes était concerné : les archives restent chiffrées, mais **changer la clé de chiffrement** par prudence (`BACKUP-STRATEGY.md` §6).

### 3.5 S5 — Compte GitHub compromis, dépôt perdu
1. Reprendre le compte (mot de passe, double authentification, révoquer les sessions et jetons). 2. Révoquer l'accès de **tout agent** (applications autorisées).
3. Vérifier `main` (historique, commits inconnus) ; **le site se reconstruit depuis n'importe quelle copie locale** (`git clone` ; la sauvegarde du dossier du projet existe sur l'ordinateur).
4. Les **données** ne sont pas dans GitHub (sauf les archives **chiffrées**) : elles sont intactes tant que Supabase l'est.
5. Re-créer le dépôt de sauvegardes si nécessaire, **rotation du secret `SES_DB_URL`** (§3.4).

### 3.6 S6 — Clé privée de déchiffrement perdue
**Les archives existantes sont illisibles, définitivement** — par conception. Que faire :
1. Chercher les **copies hors ligne** (coffre, papier, clé USB, seconde clé de secours).
2. Si aucune n'existe : la base de production, elle, est intacte ; **générer immédiatement une nouvelle paire** et lancer une sauvegarde ; l'historique chiffré est perdu, pas les données courantes.
3. **Ne jamais** attendre qu'un sinistre arrive pour découvrir que la clé manque : l'exercice trimestriel déchiffre *vraiment* une archive.

### 3.7 S7 — Panne du fournisseur
Pas de restauration : attendre ou communiquer. Le site public (statique, GitHub Pages) reste en ligne ; l'espace client et le suivi échouent. Préparer un message au support WhatsApp. **Ne pas reconstruire** sur une panne qui n'est pas une perte.

## 4. Matrice de décision rapide
| Les données… | Le projet… | Action |
|---|---|---|
| sont mal modifiées | existe | S1 / S2 : répétition + recopie ciblée |
| sont perdues en partie | existe | S1, Pro : restauration Supabase si la perte est large |
| sont perdues entièrement | n'existe plus | S3 : projet neuf + sauvegarde chiffrée |
| sont intactes | est injoignable | S7 : attendre |
| sont intactes | secret exposé | S4 : rotation, pas de restauration |

## 5. Exercice trimestriel (à dater, à signer)
- [ ] Récupérer la dernière sauvegarde (artefact) ; **noter l'heure de début**.
- [ ] La **déchiffrer avec la clé hors ligne** (preuve que la clé existe et fonctionne).
- [ ] Restaurer dans un environnement non productif (`--executer`) ; **VALIDATION OK**.
- [ ] Faire les 5 contrôles à la main (`RESTORE-PROCEDURE.md` §5).
- [ ] **Noter la durée totale** → comparer au RTO de 4 h ; ajuster ce document.
- [ ] Lire le journal : 90 jours de lignes `ok / complete`, tailles stables.
- [ ] Vérifier les **deux copies hors ligne** de la clé privée.
- [ ] Vérifier que `SES_SCRIPTS_REF` pointe sur une version relue.

## 6. Après tout sinistre
Consigner : heure de début/fin, cause, données perdues (fenêtre), décisions, ce qui a
marché, ce qui a manqué. **Une correction par leçon**, avec un test quand c'est possible.

## 7. Limites assumées (à connaître)
- **L'application mobile a l'adresse du serveur écrite en dur** : un changement de projet (S3) impose une nouvelle version. À traiter en phase 4 (adresse de service propre, réglage distant).
- Les sauvegardes sont **quotidiennes** : jusqu'à 24 h de saisies peuvent être perdues. Réduire exige l'offre PITR du fournisseur (payante) ou des sauvegardes plus fréquentes.
- Le **premier `pg_dump` réel** n'a pas encore tourné contre le vrai projet : la première exécution est la dernière pièce à valider.
- Pas de surveillance active : les alertes reposent sur l'e-mail d'échec de GitHub et sur la lecture mensuelle du journal.
