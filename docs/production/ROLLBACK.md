# Retour en arrière

> Principe : **revenir en arrière ne détruit rien**. Le site se remet à une version précédente ; une fonction s'éteint ; une étape SQL se
> retire seulement si elle n'a rien écrit d'utile. **Aucun retour en arrière n'est automatique** : chacun est un geste du propriétaire.

## 1. Le site

| Situation | Geste | Effet |
|---|---|---|
| Une nouvelle fonction pose problème | éteindre son interrupteur dans `assets/js/config.js` (`portailNoyau` / `centreNoyau` à `false`) → PR → envoi → approbation | le site retombe sur l'espace client et le tableau de bord d'avant, qui lisent l'ancien schéma |
| Une mise en ligne est cassée | `git revert <commit>` (jamais `reset` ni envoi forcé) → envoi sur `main` → approbation | la version précédente est republiée ; l'historique garde tout |
| Il faut republier un état connu | Actions > « Mettre le site en ligne » > *Run workflow* sur `main` après le `revert` | même chose, sans nouveau commit |

Après un retour en arrière du site, monter le numéro de cache (`python3 outils/versionner.py`) pour que les visiteurs rechargent les fichiers.

## 2. La base

Les étapes 001 à 013 sont **additives** : elles créent des schémas (`logistics`, `analytics`, `ops`), des tables, des fonctions et des
déclencheurs, sans toucher aux tables d'origine (`clients`, `colis`, `colis_historique`, `factures`) au-delà de ce que chaque fichier
décrit. Le site d'avant ne dépend d'aucune d'elles.

1. **D'abord** : éteindre les interrupteurs (§1). Le noyau reste installé mais n'est plus lu.
2. **Retirer une étape** n'est utile que si elle gêne (un déclencheur, par exemple). Chaque fichier se termine par « Pour retirer
   SEULEMENT cette étape » : suivre ces lignes, dans l'ordre inverse des étapes (013, puis 012…). Exemples :
   - 013 : supprimer les sept déclencheurs `ops_rate_limit`, puis les fonctions `ses_health`, `lg_ops_status`, `lg_report_client_error`,
     `ses_ops_heartbeat`, puis le schéma `ops` (compteurs et journal d'exploitation seulement) ;
   - 012 : supprimer les fonctions `lg_an_*`, `ses_an_refresh`, puis le schéma `analytics` (chiffres recalculables).
3. **Restaurer une sauvegarde** : seulement en dernier recours, **dans une base vide** (jamais par-dessus la production), selon
   [docs/backup/RESTORE-PROCEDURE.md](../backup/RESTORE-PROCEDURE.md), puis basculer après vérification. Toute écriture faite depuis la
   sauvegarde serait perdue : la décision est celle du propriétaire.

Interdits : `drop table` d'une table qui contient des données métier ; `delete` en masse ; rejouer une étape ancienne pour « réparer ».

## 3. Les travaux planifiés

Désactiver le workflow (dépôt privé > Actions > *Disable workflow*). Rien n'est perdu : le travailleur des notifications reprend là où il
s'était arrêté (les notifications attendent dans la base) ; l'analytique se recalcule.

## 4. Les applications mobiles

Un binaire publié ne se retire pas d'un téléphone : publier une version corrigée (ou republier la précédente) ; pour « SES Opérations »
en distribution privée, retirer la version de test fautive. Côté base, rien à faire : l'application ne décide d'aucune règle.
