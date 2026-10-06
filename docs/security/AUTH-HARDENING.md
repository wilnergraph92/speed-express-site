# Durcissement de l'authentification

> 5 octobre 2026. Ce que **le code** a corrigé (vérifié) et ce que **vous seul** pouvez régler dans le tableau de
> bord Supabase (je n'y ai pas accès : aucune de ces valeurs n'est lisible de l'extérieur, sauf mention).

## 1. Déjà corrigé dans le code
| Sujet | Correction | Preuve |
|---|---|---|
| Session de l'application | trousseau chiffré (`expo-secure-store`) au lieu d'un fichier en clair ; l'ancienne session est migrée puis effacée | `npm run essai:stockage` (21) |
| Rôle modifiable par un client ? | **non** : 7 colonnes seulement, le reste refusé (`42501`) | `securite-sql.py` |
| Fonctions ouvertes aux visiteurs | `est_admin`, `a_droit`, `texte_notification` fermées à `anon` ; une seule fonction publique reste | `securite-sql.py` |
| Téléphone passé d'un compte à l'autre | `enregistrer_appareil()` réaffecte, sans que l'ancien compte garde le téléphone | `securite-sql.py` |
| Scripts injectés / cadre d'un site tiers | politique de contenu + protection anti-cadre | `securite-statique.py` |
| API exposée | seuls `public` et `graphql_public` sont exposés ; GraphQL **désactivé** ; le schéma `logistics` **n'est pas** exposé | mesuré en production |

## 2. Mesuré en production (réglages publics)
Inscription ouverte, **confirmation d'e-mail obligatoire**, fournisseur e-mail seul, pas de connexion anonyme, pas de SMS,
pas de SAML ni de passkeys.

## 3. À régler dans Supabase — liste de contrôle
Ouvrez **Supabase › projet `speed-express-site`** (vérifiez le nom en haut de page : jamais celui de Goship), puis :

| # | Où | Quoi | Valeur recommandée | Pourquoi |
|---|---|---|---|---|
| 1 | *Authentication › URL Configuration* | **Site URL** | `https://wilnergraph92.github.io/speed-express-site/` | les liens des e-mails reviennent ici |
| 2 | idem | **Redirect URLs** | seulement `…/speed-express-site/espace-client.html` et `…/speed-express-site/nouveau-mot-de-passe.html` ; **aucun joker `*`** ; retirer `localhost` hors développement | un lien de réinitialisation ne doit pas pouvoir renvoyer vers un site tiers |
| 3 | *Authentication › SMTP Settings* | **SMTP personnalisé** (Brevo) activé, expéditeur de votre domaine | — | sans cela, quelques e-mails par heure seulement : les clients n'auraient pas leur confirmation |
| 4 | *Authentication › Sign In / Providers › Email* | **Minimum password length** | **8** (aligné sur le site) — ou 10 avec un changement coordonné du site | le site contrôle 8 ; un minimum serveur plus haut sans le site afficherait une erreur obscure |
| 5 | idem | **Confirm email** | activé (déjà le cas) | |
| 6 | idem | **Leaked password protection** | activée **si l'offre le permet** (offre Pro) | refuse les mots de passe connus des fuites |
| 7 | *Authentication › Rate Limits* | connexions, inscriptions, envois d'e-mail, renouvellements, par adresse IP | valeurs par défaut au minimum ; **ne pas les augmenter** | freine les essais de mots de passe et l'inscription en masse |
| 8 | *Authentication › Sessions* | **Detect and revoke potentially compromised refresh tokens** | activé | un jeton de renouvellement volé et rejoué invalide la session |
| 9 | *Authentication › Attack Protection* | **CAPTCHA** (Turnstile ou hCaptcha) à l'inscription | à activer **avec** le changement du formulaire (non fait) | arrête les inscriptions automatiques |
| 10 | *Authentication › Multi-Factor* | **TOTP** pour les administrateurs | activé ; l'interface du tableau de bord ne l'utilise pas encore (chantier à venir) | un mot de passe d'administrateur volé ne suffit plus |
| 11 | *Project Settings › Data API* | **Exposed schemas** | `public` seulement — **ne jamais ajouter `logistics`** | ADR 0002 : le noyau n'est atteint que par la façade `lg_*` |
| 12 | *Project Settings › Data API* | **Max rows** | 1000 (défaut) ou moins | limite ce qu'une requête peut extraire |
| 13 | *Project Settings › API Keys* | ne **pas** cliquer « Disable JWT-based API keys », ni *Pause / Restart / Transfer project* sans vous être assuré de l'effet | — | consignes déjà données |
| 14 | *Database › Backups* | noter l'offre et les sauvegardes disponibles | — | `docs/backup/BACKUP-STRATEGY.md` §2 |
| 15 | *Logs* | alertes e-mail sur échecs de connexion en rafale (si l'offre l'offre) | — | repérer une attaque |

**Après chaque changement** : tester un parcours complet (création de compte → e-mail → confirmation → connexion → oubli de mot de passe).

## 4. Côté GitHub
Activer la **double authentification** du compte ; protéger `main` (interdire l'envoi forcé et la suppression) ;
vérifier *Settings › Applications* (révoquer ce que vous n'utilisez plus). *Secret scanning* et *push protection* sont déjà actifs.

## 5. Ce qui n'est pas fait, et pourquoi
CAPTCHA et double authentification demandent un changement des pages (jeton, écran de second facteur) : ce sont des
chantiers distincts, à décider. Un minimum de mot de passe à 10 caractères demande de changer le site, le dictionnaire des 4
langues et le message d'erreur en même temps.
