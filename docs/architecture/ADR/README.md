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

Modèle : *Contexte → Décision → Conséquences → Alternatives écartées → Quand la réexaminer.*
