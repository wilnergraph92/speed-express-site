# API et accès aux données — état réel au 5 octobre 2026

> Décrit l'existant. **Il n'y a pas d'API sur mesure** : ni serveur Node, ni
> couche intermédiaire. Le site et l'application parlent **directement** à
> Supabase (PostgREST pour les tables et fonctions, Auth, Realtime), et la base
> fait respecter les règles. Sources : **[CODE]** `assets/js/ses-api.js`,
> `App_SES/src/api/*` ; **[PROD]** sondes.

## 1. Les surfaces exposées par Supabase

| Surface | Adresse (projet `speed-express-site`) | Qui l'appelle |
|---|---|---|
| REST — tables et vues | `/rest/v1/<table>` | site, application |
| REST — fonctions | `/rest/v1/rpc/<fonction>` | site, application |
| Auth | `/auth/v1/*` (signup, token, recover, user) | site, application |
| Realtime (WebSocket) | `/realtime/v1` | site, application |

Clé utilisée partout : **`sb_publishable_…`** (publique par conception, présente
dans `config.js` et dans l'application). Aucune clé secrète n'existe dans les
dépôts ni dans l'historique. La description du schéma (`/rest/v1/`) n'est pas
publiée à un anonyme **[PROD]**.

### Ce qu'un visiteur **non connecté** peut faire **[PROD]**
- `rpc/suivre_colis` (suivi public) ;
- les appels Auth publics (inscription, connexion, récupération) ;
- `rpc/est_admin`, `rpc/a_droit`, `rpc/texte_notification` (réponse sans effet ni fuite : voir `RLS.md`).
Tout le reste est refusé (`42501`).

## 2. La façade `window.SES_API` (site)

Un **contrat unique, trois implémentations** choisies par `MODE` :

| Mode | Quand | Données |
|---|---|---|
| `supabase` | `config.js` contient URL **et** clé | la vraie base |
| `demo` | pas de clés **et** `file:`/localhost | tout en `localStorage` |
| `off` | pas de clés, en ligne | l'interface dit que l'espace est fermé |

Règle du projet : toute méthode existe dans `supabase` **et** `demo` (sauf
`admin.dashboard*`, réservées à `supabase`, pour ne jamais inventer de
chiffres). La bibliothèque `supabase-js` 2.116.0 est servie **depuis le dépôt**
(`assets/js/vendor/`), jamais depuis un CDN, et chargée seulement si besoin.

### Méthodes publiques et client
| Méthode | Appel Supabase |
|---|---|
| `session()`, `profil()` | `auth.getSession`, `from('clients')…eq('id', moi)` |
| `inscrire`, `connecter`, `deconnecter` | `auth.signUp`, `signInWithPassword`, `signOut` |
| `envoyerLienMotDePasse`, `attendreRecuperation`, `changerMotDePasse` | `resetPasswordForEmail`, session de récupération, `updateUser` |
| `modifierProfil(champs)` | `update clients` (7 colonnes seulement, filtrées côté client **et** par `GRANT`) |
| `mesColis()`, `mesFactures()` | `select colis (+historique)`, `select factures (+n° colis)` |
| `surveiller(rappel)` | Realtime `postgres_changes` sur `colis`, `colis_historique`, `factures` |
| `suivre(numero, jeton)` | `rpc('suivre_colis', {p_numero, p_jeton?})` ; **repli sans jeton** si la base n'a pas la migration |

### `SES_API.admin.*` (équipe)
| Méthode | Appel |
|---|---|
| `dashboard(domaine, filtres)` | `rpc('dashboard_<colis|clients>_ses')` |
| `dashboardRecents`, `dashboardActivite` | `select colis`, `select colis_historique` |
| `statistiques()` | `rpc('statistiques_ses')` |
| `colis(o)`, `colisParId`, `historique` | `colis_details`, `colis_historique` |
| `creerColis`, `modifierColis`, `changerStatut(ids, …)`, `supprimerColis` | `insert/update/delete colis` |
| `clients(o)` (`role:'equipe'` ou clients), `chercherClient(code)`, `resumeClients` | `clients`, `colis_details`, `factures_details` |
| `definirRole(id, role, droits)` | `rpc('definir_role')` |
| `factures(o)`, `creerFacture`, `modifierFacture`, `supprimerFacture` | `factures_details`, `insert/update/delete factures` |
| `baseAJour()` | sonde : colonnes `tarif_lb` et fonction `est_direction` présentes ? |

Les champs envoyés passent par des **listes blanches** (`CHAMPS_PROFIL`,
`CHAMPS_COLIS`, `CHAMPS_FACTURE`) et `normaliserNombres()` (un champ numérique
vide part en `null`, jamais en `''`).

### Traduction des erreurs (`erreurSupabase`)
`invalid_credentials` → `identifiants` · `user_already_exists` → `email-existe`
· `429` → `trop-de-demandes` · `401/403/42501` → `non-autorise` · `42703`/`PGRST204`/
`23514` sur `clients_role_check` → `base-a-mettre-a-jour` · **`SE001`** →
`compte-a-des-colis` · **`SE002`** → `client-invalide` · `22P02` → `champ-mal-rempli`.

## 3. Application mobile
Pas de façade : `src/api/donnees.ts` appelle `supabase.from(...)` directement
(`mesColis`, `unColis`, `parcours`, `mesFactures`, `uneFacture`,
`modifierProfil`, `surveiller`) et `notifications.ts` la table `appareils`.
Toutes les lectures ajoutent un filtre explicite `client_id = moi` : la sécurité
reste côté base, ce filtre sert à dire « mes colis » à un compte que la base
autoriserait à en voir davantage. La **logique de total de facture est
recopiée** dans l'application (`totaux()`), comme sur le site.

## 4. Services tiers appelés
| Service | Pour quoi | Données envoyées |
|---|---|---|
| Expo Push (`exp.host/--/api/v2/push/send`) | notifications, **appelé par la base** (`pg_net`) | jetons d'appareil, libellé, numéro du colis |
| WhatsApp (`wa.me`) | contact, formulaire de repli | texte préparé côté visiteur |
| Google Fonts | polices du site | adresse IP du visiteur |
| Unsplash | 11 photos d'illustration dans 18 pages | adresse IP du visiteur |
| Formspree | formulaire de contact : **désactivé** (`formEndpoint` vide) | — |

## 5. Constats
1. Aucune couche de service : toute évolution de règle métier passe par une **fonction SQL** ou par le navigateur. Les règles de facturation du regroupement et plusieurs calculs sont aujourd'hui **dans le navigateur** (voir `BILLING.md`).
2. Deux copies de la façade (site et application) ne partagent aucun code : le contrat n'est écrit nulle part en dehors de ce document.
3. L'accès anonyme à la base est volontairement limité à `suivre_colis` ; aucun accès par clé de service n'est utilisé par une application.
