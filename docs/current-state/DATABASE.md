# Base de données — état réel au 5 octobre 2026

> **Ce document décrit ce qui existe, pas ce qui devrait exister.** Aucune
> table, aucune fonction, aucun comportement n'a été modifié pour l'écrire.
>
> Sources : **[CODE]** lu dans `outils/*.sql` ; **[PROD]** mesuré sur la base de
> production avec la clé publique (lecture seule) ; **[?]** impossible à
> vérifier de l'extérieur (tableau de bord Supabase, données réelles).

## 1. Vue d'ensemble

| | |
|---|---|
| Moteur | PostgreSQL géré par Supabase **[PROD]** (passerelle Cloudflare, API REST PostgREST, Auth, Realtime) |
| Projet | un seul, `speed-express-site`. Goship Express a son propre projet, distinct **[PROD]** |
| Offre, région, sauvegardes | **[?]** non lisibles de l'extérieur (voir `docs/backup/` en phase 2) |
| Schéma utilisé | `public` uniquement ; `auth` est géré par Supabase |
| Données réelles | **[?]** le contenu est masqué par la sécurité par ligne (voulu) |

## 2. Tables

### `public.clients` — un compte = une ligne (clients **et** équipe)
| Colonne | Type | Remarque |
|---|---|---|
| `id` | uuid PK | **= `auth.users.id`**, `on delete cascade` |
| `code` | text unique | identifiant `SES-#####` ; **nul pour l'équipe** |
| `nom_complet`, `pays`, `region`, `ville`, `adresse`, `telephone`, `email` | text | `email` est une **copie** posée à l'inscription ; rien ne la resynchronise si l'e-mail Auth change **[CODE]** |
| `langue` | text | `fr`, `en`, `es`, `ht` (valeur forcée à l'inscription) |
| `role` | text | `client`, `employe`, `gerant`, `admin` (contrainte `check`) |
| `droits` | text[] | liste des droits d'un employé ; sans effet pour les autres rôles |
| `cree_le` | timestamptz | |

### `public.colis`
| Colonne | Type | Remarque |
|---|---|---|
| `id` | uuid PK | identifiant **interne**, jamais montré au public |
| `numero` | text unique | `SES-<compteur>-<HT|DO|US>` ; posé par déclencheur, immuable |
| `jeton` | text | 16 caractères hexadécimaux aléatoires ; écrit dans le QR ; immuable |
| `client_id` | uuid → `clients` | **`on delete set null`** : supprimer un client détache ses colis |
| `description`, `expediteur`, `destinataire`, `telephone_destinataire`, `adresse_livraison`, `ville_destination` | text | |
| `poids_lb` | numeric(8,2) ≥ 0 | |
| `tarif_lb` | numeric(10,2) ≥ 0 | **propre à chaque colis**, défaut 0 |
| `service` | text | `aerien`, `maritime`, `terrestre` |
| `pays_destination` | text | `HT`, `DO`, `US` (défaut `DO`) |
| `valeur_declaree` | numeric(10,2) ≥ 0 | |
| `statut` | text | `confirme`, `expedie`, `disponible`, `livre`, `action` (défaut `confirme`) |
| `lieu`, `note` | text | `note` est visible par le client |
| `cree_le`, `maj_le` | timestamptz | posés par déclencheur |

Index : `client_id`, `maj_le desc`, `statut`. Séquence `numero_colis_seq`, départ 10000.

### `public.colis_historique` — un changement = une ligne
`id` (identité), `colis_id` → `colis` **`on delete cascade`**, `statut`, `lieu`, `note`, `auteur` (e-mail de qui a agi), `cree_le`. Alimentée **uniquement** par le déclencheur `historiser_colis` ; les utilisateurs authentifiés n'ont que le droit de lecture **[CODE]**.

### `public.factures`
| Colonne | Type | Remarque |
|---|---|---|
| `id` | uuid PK | |
| `numero` | text unique | `FAC-<année>-<n°>` sur une séquence **globale** (`numero_facture_seq`) : le n° **ne repart pas à 1** chaque année |
| `client_id` | uuid NOT NULL → `clients` | **`on delete cascade`** : supprimer un client supprime ses factures |
| `colis_id` | uuid → `colis` | `on delete set null` : la facture survit au colis |
| `montant` | numeric(10,2) | **grand total** = colis + frais de service |
| `frais_service` | numeric(10,2) | 10 pour une facture de colis |
| `montant_paye` | numeric(10,2) | |
| `devise` | text | défaut `USD` |
| `statut` | text | `impayee`, `payee` |
| `lignes` | jsonb | une ligne figée par colis (n°, description, poids, tarif, montant) |
| `groupee` | boolean | ajoutée par la migration « facture groupée » |
| `note`, `echeance_le`, `cree_le`, `payee_le` | | |

### `public.appareils` (créée par la migration de l'application mobile **[PROD]** : existe)
`jeton` text PK (jeton Expo), `client_id` → `clients` `on delete cascade`, `plateforme`, `vu_le`, `cree_le`. Un client peut avoir plusieurs appareils.

### Vues
`colis_details` et `factures_details` : jointure avec le client (code, nom, e-mail…). **`security_invoker = true`** : la vue obéit aux règles de celui qui la lit.

## 3. Fonctions

| Fonction | Rôle | Mode | Appelable par |
|---|---|---|---|
| `nouveau_code_client()` | tire un `SES-#####` libre (90 000 possibles, 400 essais) | invoker | personne (révoquée) |
| `creer_profil_client()` | crée la ligne `clients` à l'inscription, rôle forcé à `client` | **definer** | déclencheur seul |
| `preparer_colis()` | pose numéro, jeton, dates ; les rend immuables | definer | déclencheur seul |
| `historiser_colis()` | écrit l'historique | definer | déclencheur seul |
| `facturer_colis()` | crée/recalcule la facture du colis | definer | déclencheur seul |
| `preparer_facture()` | numéro, cohérence statut ↔ montant payé, `payee_le` | definer | déclencheur seul |
| `verifier_modification_colis()` | un employé sans `colis.modifier` ne touche que statut/lieu/note | definer | déclencheur seul |
| `verifier_client_rattache()` | refuse un colis/une facture rattaché à un compte d'équipe (`SE002`) | definer | déclencheur seul |
| `est_admin()`, `est_direction()`, `a_droit(p_droit)` | contrôles de rôle, base de toutes les règles | definer | voir `RLS.md` |
| `definir_role(p_id, p_role, p_droits)` | change un rôle selon la hiérarchie | definer | `authenticated` (contrôle interne : `roles.gerer`) |
| `definir_admin(p_email)` | désigne le premier administrateur (SQL Editor) | definer | personne (révoquée) |
| `suivre_colis(p_numero, p_jeton default null)` | **suivi public** | definer | **`anon`** et `authenticated` |
| `statistiques_ses()` | chiffres du tableau de bord (ancien) | invoker (voir §6) | `authenticated` |
| `dashboard_periode_ses`, `dashboard_colis_ses`, `dashboard_clients_ses` | rapports du tableau de bord | invoker | `authenticated` |
| `texte_notification(p_statut, p_langue)` | libellé de la notification, 4 langues | invoker, immuable | **tout le monde** **[PROD]** |
| `prevenir_client()` | envoie la notification Expo (via `pg_net`) | definer | déclencheur seul |

Toutes les fonctions `security definer` fixent `set search_path = ''` **[CODE]**.

## 4. Déclencheurs

| Déclencheur | Table | Moment | Fonction |
|---|---|---|---|
| `creer_profil_client` | `auth.users` | après insertion | `creer_profil_client` |
| `preparer_colis` | `colis` | avant insert/update | `preparer_colis` |
| `verifier_modification_colis` | `colis` | avant update | `verifier_modification_colis` |
| `verifier_client_colis` | `colis` | avant insert / update de `client_id` | `verifier_client_rattache` |
| `historiser_colis` | `colis` | après insert/update | `historiser_colis` |
| `facturer_colis` | `colis` | après insert/update | `facturer_colis` |
| `prevenir_client` | `colis` | après insert / update de `statut` | `prevenir_client` |
| `preparer_facture` | `factures` | avant insert/update | `preparer_facture` |
| `verifier_client_facture` | `factures` | avant insert / update de `client_id` | `verifier_client_rattache` |

## 5. Temps réel et extensions
- Publication `supabase_realtime` : `colis`, `colis_historique`, `factures` **[CODE]**. `appareils` n'y est pas.
- Extension `pg_net` (schéma `extensions`) pour l'envoi des notifications ; `pgcrypto` pour `gen_random_bytes` (jeton).

## 6. Migrations : ce qui a été appliqué, et le piège

| Fichier | Contenu | Appliquée en production ? |
|---|---|---|
| `outils/supabase.sql` | schéma complet | oui, dans une version plus ancienne **[?]** |
| `outils/supabase-maj.sql` | tarif par colis, facture auto, **4 rôles**, équipe ≠ clientèle (sections 1 à 8) | oui **[PROD]** (`est_direction()` existe) |
| `outils/supabase-maj-facture-groupee.sql` | colonne `groupee` | probable **[?]** (la colonne est utilisée par le site) |
| `outils/supabase-maj-jeton.sql` | `suivre_colis(text, text)` avec jeton | oui **[PROD]** (appel avec et sans jeton accepté) |
| `outils/supabase-dashboard.sql` | fonctions `dashboard_*`, `statistiques_ses` en `invoker` | **oui [PROD]**, bien que son en-tête dise « NON APPLIQUÉE » |
| `App_SES/base/supabase-maj-notifications.sql` | `appareils`, `prevenir_client`, `texte_notification` | **oui [PROD]** (la table existe) |

Il n'y a **pas de registre de migrations** : rien dans la base ne dit lesquelles ont été passées. L'état ci-dessus est déduit de sondes.

### ⚠ Dérive : `supabase.sql` n'est plus la référence de la production
L'en-tête de `supabase.sql` dit « Relancez-le après chaque mise à jour du site ». **Ne le faites pas.** Rejoué après les migrations ci-dessus, il :

1. recrée `suivre_colis(text)` **à côté** de `suivre_colis(text, text)` ; PostgreSQL répond alors `function public.suivre_colis(...) is not unique` à tout appel avec un seul argument — **le suivi public cesse de fonctionner** ;
2. remet `statistiques_ses()` en `security definer` (version antérieure au tableau de bord actuel).

Démonstration reproduite sur un vrai PostgreSQL (WASM) jetable, hors production : état « schéma + 4 migrations » = une seule `suivre_colis`, en `invoker` pour `statistiques_ses` ; après rejeu de `supabase.sql` = deux `suivre_colis` et l'erreur ci-dessus.

**Règle provisoire :** n'exécuter dans le SQL Editor que `supabase-maj.sql` (rejouable, vérifié sur 498 contrôles). La réconciliation de `supabase.sql` est une migration à approuver (phases suivantes).

## 7. Observations factuelles pour la suite (aucune n'est corrigée ici)

1. **Suppression en cascade.** Supprimer un compte dans Supabase Auth supprime sa ligne `clients`, ce qui supprime **ses factures** (pièces comptables) et ses appareils, et détache ses colis. Aucune interface ne le fait aujourd'hui (la fermeture de compte est manuelle, par le support), mais le tableau de bord Supabase le permet.
2. **Pas de journal d'audit.** Les changements de statut de colis sont historisés. Ne le sont pas : paiements et modifications de factures, suppressions de colis/factures, changements de rôle.
3. **Suppression de colis = perte de son historique** (`on delete cascade`), pour qui a le droit `colis.supprimer`.
4. **Aucune règle de transition de statut** : la base accepte n'importe quel statut valide depuis n'importe quel autre (un colis `livre` peut repasser à `confirme`).
5. **Frais de service codés en dur** (`v_frais := 10`) dans `facturer_colis()`, et dupliqués dans `SES_API.FRAIS_SERVICE` (site, mode démo).
6. **Numéro de colis séquentiel et déductible** (voir `SECURITY.md` et `docs/security/TRACKING-SECURITY.md`).
7. **Défaut latent dans `prevenir_client()` (notifications).** La fonction appelle `extensions.net.http_post(...)`, un nom à trois parties : PostgreSQL le lit « base.schéma.fonction » et répond *cross-database references are not implemented*. La fonction de `pg_net` s'appelle `net.http_post` (schéma `net`). **Reproduit sur PostgreSQL 16 réel.** Conséquence : dès qu'un client a un appareil dans `appareils`, tout enregistrement ou changement de statut d'un de ses colis **échoue** (l'erreur annule l'instruction). Aujourd'hui sans effet, parce qu'aucun appareil n'est enregistré (pas de build de développement) ; **à corriger avant la première activation des notifications**. Aucune erreur d'envoi ne devrait par ailleurs pouvoir bloquer une mise à jour de colis.
8. **Données héritées** : les colis créés avant la migration du tarif ont `tarif_lb = 0` **[?]** ; d'anciens comptes d'équipe peuvent encore porter des colis et un code `SES-#####` **[?]**.
