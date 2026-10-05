# ADR 0002 — Logique dans PostgreSQL, façade `public.lg_*`, tables du noyau fermées
**Statut :** Proposée (5 octobre 2026)

## Contexte
Aujourd'hui, une partie des règles est **dans le navigateur** (regroupement de factures, calculs de
totaux, statut libre) et dupliquée entre site et application (baseline R4, R12). Le backend doit devenir
l'unique décideur : statut, prix, droit.

## Décision
1. Les règles s'écrivent en **fonctions SQL** du schéma `logistics` (PL/pgSQL, `search_path` verrouillé).
2. Seules des fonctions **`public.lg_<verbe>_<nom>`** sont exposées à l'API ; elles valident, appellent le noyau, renvoient un résultat.
3. Les **tables du noyau ne sont accordées à aucun rôle de l'API** (ni `anon`, ni `authenticated`) : RLS activée, aucune politique, aucun `grant`. Lire se fait par des fonctions ou des vues dédiées.
4. Les **Edge Functions** ne servent qu'aux échanges extérieurs (push, douane, PDF) ; elles lisent l'outbox par la façade.
5. Fichiers : Supabase Storage, compartiments privés, liens signés à durée courte.

## Conséquences
+ aucune écriture « sauvage » possible : même une clé publique volée n'atteint pas les tables ;
+ un seul endroit à tester et à auditer ;
− chaque cas d'usage demande une fonction (c'est voulu : c'est ce qui rend l'API explicite).

## Alternatives écartées
Ouvrir les tables en REST avec des politiques : refait le problème actuel (règles éclatées, validations côté client).

## Quand la réexaminer
Si le nombre de fonctions rend la façade ingérable : la découper en schémas exposés par domaine.
