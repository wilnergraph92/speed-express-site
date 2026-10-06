# Sécurité par ligne (RLS) et droits d'accès — état réel au 5 octobre 2026

> Décrit l'existant, sans le modifier. **[CODE]** = `outils/supabase.sql` et
> `outils/supabase-maj.sql` ; **[PROD]** = sondes anonymes faites sur la base de
> production ; **[TEST]** = couvert par `outils/tests/roles-sql.cjs` (498
> contrôles sur un PostgreSQL réel, WASM).

## 1. Principe
Trois couches, dans cet ordre : (1) les **droits sur les tables** (`GRANT`) ;
(2) les **règles de ligne** (RLS) ; (3) les **déclencheurs** pour ce qu'une règle
de ligne ne sait pas dire (quelles colonnes changent). La page n'est jamais
une frontière de sécurité : un navigateur se contourne, la base non.

RLS est **activée sur les 5 tables** `clients`, `colis`, `colis_historique`,
`factures`, `appareils` **[CODE]**. Les vues sont en `security_invoker`.

## 2. Droits sur les tables

| Table / vue | `anon` | `authenticated` | `service_role` |
|---|---|---|---|
| `clients` | rien **[PROD]** | `select` ; `update` limité à **7 colonnes** : `nom_complet, pays, region, ville, adresse, telephone, langue` | tout |
| `colis` | rien **[PROD]** | `select, insert, update, delete` (filtrés par les règles) | tout |
| `colis_historique` | rien **[PROD]** | `select` seulement | tout |
| `factures` | rien **[PROD]** | `select, insert, update, delete` (filtrés) | tout |
| `appareils` | rien **[PROD]** | `select, insert, update, delete` sur ses lignes | — |
| `colis_details`, `factures_details` | rien **[PROD]** | `select` | `select` |

Conséquence : `role`, `droits`, `code`, `email`, `id`, `cree_le` ne sont **pas
modifiables** par un compte, quelle que soit la requête, parce qu'aucun `GRANT
update` ne les couvre **[CODE]**. Le rôle ne change que par `definir_role()`.
**[TEST]** pour `role` (refus `42501`) ; pour `droits`, `code` et `email`, le
refus découle du même mécanisme mais **n'est pas encore éprouvé par un test
dédié** (ajouté en phase 3).

## 3. Règles de ligne

| Table | Opération | Règle |
|---|---|---|
| `clients` | select | `id = auth.uid()` **ou** droit `clients.lire` |
| `clients` | update | `id = auth.uid()` **ou** `est_direction()` (en plus des 7 colonnes ci-dessus) |
| `colis` | select | `client_id = auth.uid()` **ou** `colis.lire` |
| `colis` | insert | `colis.creer` |
| `colis` | update | `colis.modifier` **ou** `colis.statut` ; le déclencheur `verifier_modification_colis` limite sans `colis.modifier` à statut/lieu/note |
| `colis` | delete | `colis.supprimer` |
| `colis_historique` | select | `colis.lire` **ou** propriétaire du colis |
| `factures` | select | `client_id = auth.uid()` **ou** `factures.lire` |
| `factures` | insert / update / delete | `factures.creer` / `factures.modifier` / `factures.supprimer` |
| `appareils` | tout | `client_id = auth.uid()` (lecture, ajout, modification, suppression) |

Aucune règle `insert` ni `delete` sur `clients` : un compte ne se crée que par
le déclencheur d'inscription et ne se supprime que depuis Supabase Auth.

## 4. Qui peut appeler quelles fonctions

| Fonction | `anon` | `authenticated` | Mesure |
|---|---|---|---|
| `suivre_colis(text, text)` | **oui (voulu)** | oui | **[PROD]** répond `null` pour un numéro inexistant |
| `est_direction()` | non | oui | **[PROD]** 42501 |
| `definir_role`, `definir_admin`, `nouveau_code_client` | non | `definir_role` oui ; les deux autres non | **[PROD]** 42501 |
| `statistiques_ses`, `dashboard_*` | non | oui (contrôle `a_droit` à l'intérieur) | **[PROD]** 42501 |
| **`est_admin()`** | **oui, par défaut** | oui | **[PROD]** renvoie `false`, sans effet |
| **`a_droit(text)`** | **oui, par défaut** | oui | **[PROD]** renvoie `false`, sans effet |
| **`texte_notification(text, text)`** | **oui, par défaut** | oui | **[PROD]** renvoie un libellé |
| fonctions de déclencheur | non (retournent `trigger`, non appelables en RPC) | non | **[PROD]** `facturer_colis` : introuvable |

Les trois lignes en gras sont une **incohérence de durcissement**, sans fuite
constatée (elles ne renvoient rien de sensible pour un anonyme) : les fonctions
sœurs (`est_direction`, `definir_role`) sont fermées à `anon`, celles-ci ne le
sont pas parce qu'aucun `revoke … from public` ne les vise. *Fermées à `anon` dans `supabase-maj.sql` §10 (testé) ; pas encore appliqué en production.*

L'API ne publie pas la description de son schéma à un anonyme **[PROD]**
(`/rest/v1/` ne liste aucune table ni fonction).

## 5. Ce qu'un simple client ne peut pas faire
- lire le profil, les colis, les factures ou l'historique d'un autre ;
- modifier son rôle (**[TEST]**), ses droits, son code ou son e-mail (**[CODE]**, test dédié à venir) ;
- appeler `definir_role` avec succès ; se donner un droit ; se promouvoir ;
- créer, modifier ou supprimer un colis ou une facture ;
- obtenir un accès au tableau de bord : même avec une colonne `droits` pleine, `a_droit()` ne donne rien à un client.

## 6. Limites et angles morts connus
1. Le **temps réel** applique les mêmes règles, mais `appareils` n'est pas dans la publication.
2. Les règles sont écrites pour des appels **authentifiés** ; l'appel anonyme est refusé au niveau des `GRANT` avant d'atteindre la RLS.
3. **Pas de limitation de débit** sur `suivre_colis` (ni côté base, ni côté site).
4. `service_role` contourne tout (par conception de Supabase) : sa clé ne doit exister nulle part dans ce dépôt, ni dans l'application **[CODE : absente]**.
5. Un employé à qui l'on a coché `roles.gerer` agit selon la hiérarchie de `definir_role()` (voir `ROLES.md`) : il ne peut ni nommer ni toucher un gérant ou un administrateur.
