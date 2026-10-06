# Décisions d'architecture (ADR)

Une décision = un fichier numéroté, jamais réécrit : on la **remplace** par une nouvelle
(statut « Remplacée par … »). Statuts : *Proposée* (applicable sauf objection du propriétaire),
*Acceptée*, *Remplacée*.

| N° | Décision | Statut |
|---|---|---|
| [0001](0001-postgresql-supabase-reste-le-coeur.md) | PostgreSQL / Supabase reste le cœur du backend | Proposée |
| [0002](0002-postgres-d-abord-et-facade-rpc.md) | Logique dans PostgreSQL, façade `public.lg_*`, tables du noyau fermées | Proposée |
| [0003](0003-evenements-par-boite-d-envoi.md) | Événements : boîte d'envoi transactionnelle, relances, file des échecs | Proposée |
| [0004](0004-vocabulaire-du-noyau-en-anglais.md) | Noyau nommé en anglais, libellés en 4 langues | Proposée |
| [0005](0005-applications-operations-expo-et-bureau-web.md) | Deux applications Expo ; bureau = navigateur | Proposée |
| [0006](0006-etranglement-progressif-et-statuts-separes.md) | Migration par étranglement ; Colis ≠ Expédition (statuts séparés) | Proposée |
| [0007](0007-moteur-financier-dans-la-base.md) | Moteur financier dans la base, au centime, factures figées | Proposée |
| [0008](0008-chauffeur-membre-de-l-equipe-et-preuve-dans-la-base.md) | Chauffeur = membre de l'équipe ; preuve de livraison exigée par la base | Proposée |
| [0009](0009-portail-par-interrupteur-et-repli.md) | Portail client derrière un interrupteur, avec repli sûr sur l'ancien espace | Proposée |
| [0010](0010-centre-de-commande-dans-le-tableau-de-bord.md) | Centre de commande : un onglet du tableau de bord, nourri par la base seule, sans démonstration | Proposée |
| [0011](0011-notifications-moteur-dans-la-base-travailleur-planifie.md) | Notifications : moteur dans la base, envoi par un travailleur planifié, temps réel par un signal sans donnée | Proposée |
| [0012](0012-une-base-de-code-deux-applications.md) | Une base de code, deux applications, deux racines de routes ; profil et gestes hors connexion décidés par la base | Proposée |
| [0013](0013-bureau-tableau-de-bord-installable.md) | Bureau Windows/macOS : le tableau de bord installable et un poste de scan, sans Tauri ni Electron | Proposée |
| [0014](0014-analytique-separee-faits-quotidiens-traces.md) | Analytique : schéma séparé, faits quotidiens tirés des journaux, chaque calcul tracé et vérifiable | Proposée |
| [0015](0015-exploitation-dans-la-base-sans-nouvelle-pile.md) | Exploitation : surveillance, erreurs et limites dans la base ; CI complète ; aucune mise en ligne sans geste explicite | Proposée |

Modèle : *Contexte → Décision → Conséquences → Alternatives écartées → Quand la réexaminer.*
