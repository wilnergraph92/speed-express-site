# Authentification — état réel au 5 octobre 2026

> Décrit l'existant, sans le modifier. Sources : **[CODE]**, **[PROD]** (réglages
> publics lus sur `/auth/v1/settings`), **[?]** non vérifiable sans le tableau
> de bord Supabase.

## 1. Principe
Les comptes vivent dans **Supabase Auth** (e-mail + mot de passe, hachés par
Supabase : ni le schéma ni le site ne les voient). Une ligne `public.clients`,
de même identifiant, porte le profil, le rôle et les droits. Le **rôle n'est
jamais dans le jeton** : la base le relit à chaque requête (`a_droit()`,
`est_direction()`), donc un changement de rôle prend effet immédiatement.

## 2. Réglages mesurés **[PROD]**
| Réglage | Valeur |
|---|---|
| Inscription ouverte | **oui** (`disable_signup: false`) |
| Confirmation d'e-mail obligatoire | **oui** (`mailer_autoconfirm: false`) |
| Fournisseurs actifs | e-mail seulement (aucun Google/Apple/Facebook…) |
| Connexions anonymes | non |
| Téléphone / SMS | désactivé |
| SAML, passkeys | désactivés |

Non lisibles de l'extérieur **[?]** : expéditeur SMTP (personnalisé ou celui de
Supabase), « Site URL » et « Redirect URLs », longueur minimale du mot de
passe côté serveur, protection contre les mots de passe compromis, limites de
débit, durée de vie des sessions, MFA.

## 3. Parcours

### Création de compte (site)
1. `creer-un-compte.html` → `SES_API.inscrire()` → `auth.signUp` avec les
   coordonnées dans `options.data` (nom, pays, région, ville, adresse,
   téléphone, langue). `emailRedirectTo` = `espace-client.html`.
2. Supabase envoie l'e-mail de confirmation ; sans session, le site affiche
   « confirmez votre adresse ».
3. À l'insertion dans `auth.users`, le déclencheur `creer_profil_client` crée la
   ligne `clients` : **rôle forcé à `client`**, code `SES-#####`, champs tronqués
   (120/60/80/80/200/40 caractères), langue limitée à fr/en/es/ht. Le rôle ne
   peut pas être demandé depuis le formulaire **[CODE]**.

### Connexion (site)
`connexion.html` → `signInWithPassword`. Le profil est lu ensuite :
- rôle d'équipe → redirection vers `tableau-de-bord.html` ;
- client → `espace-client.html`.
Le client Supabase du site utilise le flux **`implicit`** (jetons dans
l'adresse de la page, effacés ensuite par `nettoyerAdresse()`), la session est
persistée dans `localStorage` (`sb-<projet>-auth-token`) et renouvelée toute
seule.

### Mot de passe oublié / changement
- Oubli : `envoyerLienMotDePasse()` → `resetPasswordForEmail`, retour sur
  `nouveau-mot-de-passe.html`, qui lit la session de récupération puis appelle
  `updateUser({ password })`.
- Changement connecté : Réglages de l'espace client / du tableau de bord →
  `updateUser`. Minimum **8 caractères, contrôlé seulement dans le navigateur**
  (`MDP_MINIMUM`) ; la règle serveur est **[?]**.

### Fermeture de compte
**Manuelle.** La page `fermer-un-compte.html` renvoie vers le support (e-mail,
téléphone) ; l'identité est vérifiée par l'équipe. Aucune suppression en libre
service n'existe. (Attention à la cascade décrite dans `DATABASE.md` §7.)

### Premier administrateur
Après création d'un compte normal, exécuter dans le SQL Editor
`select public.definir_admin('adresse@exemple.com');` (fonction révoquée à tous
les rôles de l'API). Les autres rôles passent par `definir_role()` (voir
`ROLES.md`).

## 4. Application mobile
- Même projet Supabase, même clé publique (`sb_publishable_…`).
- Session stockée dans **`AsyncStorage` (non chiffré)**, renouvellement
  automatique, `detectSessionInUrl: false`.
- **Garde de rôle** : après connexion, le profil est lu ; si le rôle n'est pas
  `client`, la session est fermée aussitôt et l'écran de connexion l'explique.
  La garde est côté application : la base, elle, laisse un employé lire ses
  propres données comme tout compte, et lire ce que ses droits permettent.
- Inscription depuis l'application : `signUp` avec retour sur la page
  `espace-client.html` du site (pas de lien profond vers l'application).
- **Pas de « mot de passe oublié » dans l'application** : la clé de texte existe,
  aucun écran ne l'utilise ; l'oubli passe par le site.

## 5. Particularités à connaître
- Le site Speed Express et Goship Express sont servis depuis le même domaine
  (`wilnergraph92.github.io`) et **partagent le même `localStorage`**. Le site
  ne reconnaît donc une session que si la clé porte l'identifiant du projet
  Speed Express (`ses-entete.js`).
- Mode démonstration (local, sans clés) : comptes dans `localStorage` et un
  compte administrateur de démo codé dans `ses-api.js`. **Il est inactif en
  ligne** : le mode `demo` ne s'active que sur `file:` ou localhost sans clés.
- Rien d'autre ne crée de compte : aucune API d'administration d'Auth n'est
  appelée depuis un navigateur (la clé secrète ne doit jamais s'en approcher).
