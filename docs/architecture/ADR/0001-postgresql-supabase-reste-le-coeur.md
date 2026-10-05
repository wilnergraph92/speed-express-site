# ADR 0001 — PostgreSQL / Supabase reste le cœur du backend
**Statut :** Proposée (5 octobre 2026)

## Contexte
Le système réel tourne sur Supabase (PostgreSQL, Auth, Realtime) sans serveur applicatif ; les règles
de sécurité, la facturation et l'historique y vivent déjà, et **498 contrôles** les éprouvent sur
PostgreSQL réel. Le périmètre visé (entrepôt, transport, douane, dernier kilomètre, finance) est
**transactionnel et relationnel** : un colis, ses événements, sa facture et son état doivent changer ensemble.

## Décision
PostgreSQL (Supabase) **reste le cœur**. Le noyau logistique est un **nouveau schéma `logistics`**
dans la même base ; l'ancien schéma `public` n'est ni modifié ni supprimé (ADR 0006).

## Conséquences
+ transactions ACID pour toute opération métier ; une seule source de vérité ; aucun nouveau serveur à héberger, patcher, surveiller ;
+ les tests existants (PostgreSQL jetable) s'étendent tels quels ;
− la montée en charge se règle par PostgreSQL (index, partitions) et non par ajout de services ;
− dépendance au fournisseur : atténuée par la sauvegarde indépendante (`docs/backup/`) et le fait que tout est du SQL standard.

## Alternatives écartées
Serveur Node + ORM (Prisma) : une seconde couche à maintenir pour répéter ce que la base fait déjà ; microservices : complexité sans besoin à cette échelle.

## Quand la réexaminer
Si un traitement dépasse quelques secondes, ou si la charge dépasse ce qu'une instance PostgreSQL gérée tient raisonnablement.
