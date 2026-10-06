# Réponse aux incidents

> Une seule personne d'astreinte : le propriétaire. Le but de ce document est de ne pas avoir à réfléchir dans le stress.

## 1. Gravité

| Niveau | Exemple | Délai |
|---|---|---|
| **S1** | le site ou la base ne répond plus ; données d'un client visibles par un autre ; clé secrète exposée ; base qui n'est pas la bonne | tout de suite |
| **S2** | une fonction importante en panne (connexion, portail, factures, scan) ; sauvegarde absente depuis 2 jours | dans la journée |
| **S3** | gêne limitée (un texte, une page lente, une notification en retard) | à la prochaine mise en ligne |

## 2. Les quinze premières minutes

1. **Constater** : page Santé ; `ses_health` (MONITORING §1) ; status.supabase.com ; githubstatus.com.
2. **Limiter** : éteindre l'interrupteur concerné (`portailNoyau`, `centreNoyau`) — c'est un retour à l'existant, toujours sûr ; suspendre
   un travail planifié en panne (désactiver son workflow dans le dépôt privé).
3. **Prévenir** les clients si l'incident les touche (modèle ci-dessous), par WhatsApp et sur la page d'accueil si besoin.
4. **Ne pas** : supprimer de données, restaurer une sauvegarde par-dessus la production, rejouer une ancienne migration, partager une clé
   secrète pour « aller plus vite ».

## 3. Fiches

### Site inaccessible
GitHub Pages : githubstatus.com. Une mise en ligne cassée : [ROLLBACK](ROLLBACK.md) §1 (revenir au commit précédent).

### Base inaccessible ou lente
Supabase status ; Supabase > Reports (CPU, connexions). Le site public reste lisible ; l'espace client et le tableau de bord affichent leur
message d'erreur. Rien à faire côté site.

### Données visibles par la mauvaise personne (S1)
Éteindre l'interrupteur concerné ; noter le compte, l'heure, la page ; vérifier la règle de sécurité (`docs/current-state/RLS.md`) ou la
façade en cause ; corriger par une migration testée ; prévenir les personnes concernées.

### Clé secrète exposée (S1)
La faire tourner **immédiatement** ([RUNBOOK](RUNBOOK.md) §3.9) ; vérifier dans Supabase > Logs qu'elle n'a pas servi ; la retirer de
l'historique Git n'est pas suffisant (elle est publique dès qu'elle a été poussée).

### Mauvais projet Supabase (S1)
Une requête passée sur le projet de Goship : arrêter ; ne rien « défaire » à la main ; restaurer ce projet depuis sa propre sauvegarde ;
prévenir. Prévention : la première ligne de chaque fichier SQL rappelle de vérifier le nom du projet.

### Tempête de notifications ou d'e-mails
Désactiver le workflow du travailleur ; `update logistics.notification_channel set enabled = false where code = 'email';` ; chercher la
règle ou l'événement en cause ; rallumer après correction.

### Un client bloqué par « trop de demandes »
[RUNBOOK](RUNBOOK.md) §3.4. Ce n'est pas un incident tant qu'il ne s'agit pas de nombreux comptes.

## 4. Message aux clients (modèle)

> Bonjour, nous rencontrons un problème technique sur [l'espace client / le suivi]. Vos colis ne sont pas concernés et continuent leur
> route. Nous vous tenons informé(e) d'ici [heure]. — L'équipe Speed Express Shipping

## 5. Après l'incident (sous 48 h)

| Question | Réponse |
|---|---|
| Que s'est-il passé, quand, combien de temps ? | |
| Qui a été touché ? | |
| Comment l'a-t-on vu ? (page Santé, client, sonde) | |
| Cause | |
| Ce qui a été fait | |
| Ce qui empêchera la récidive (un test, un contrôle, un seuil) | |
