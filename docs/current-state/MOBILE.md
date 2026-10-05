# Application mobile — état réel au 5 octobre 2026

> Dépôt **privé** `wilnergraph92/speed-express-app`, commit `236bfcb`
> (état identique à GitHub). **[CODE]** sauf mention.

## 1. Stack
Expo **SDK 57**, React Native **0.86.3**, React 19.2.3, `expo-router` (routes par
fichiers), TypeScript 6, `@supabase/supabase-js` ^2.117.2, `expo-notifications`,
`expo-localization`, polices Saira / Manrope / IBM Plex Mono. ≈ 2 100 lignes
TypeScript, **aucun test automatisé**.

## 2. Écrans (`src/app/`)
| Route | Écran |
|---|---|
| `connexion` | connexion e-mail + mot de passe |
| `inscription` | création de compte (retour e-mail vers la page `espace-client.html` du site) |
| `(espace)/index` | liste des colis, recherche, colis en cours |
| `(espace)/factures` | factures, reste à payer, détail |
| `(espace)/profil` | identifiant client, coordonnées, langue, notifications, contact WhatsApp/téléphone, déconnexion |
| `colis/[id]` | détail, frise du parcours en 4 étapes |

## 3. Données et sécurité
- Même projet Supabase et même clé publique que le site. La clé est écrite dans `src/api/supabase.ts` (aucune variable d'environnement).
- **Session dans `AsyncStorage`, non chiffrée** (jeton d'accès et de renouvellement lisibles sur l'appareil).
- **Garde de rôle** (`session.tsx`) : seul un compte de rôle `client` est accepté ; un compte d'équipe est déconnecté aussitôt.
- Chaque lecture ajoute `.eq('client_id', moi)` en plus des règles de la base.
- **Temps réel** : abonnement `postgres_changes` sur `colis`, `colis_historique`, `factures`, comme le site.
- Écriture possible : `clients` (profil, colonnes autorisées par le `GRANT`) et `appareils` (jeton de notification).
- Pas de « mot de passe oublié » dans l'application (texte présent, aucun écran).

## 4. Notifications
Flux **[CODE]** + **[PROD]** (la table existe) :
1. Le client active l'option dans « Profil » → autorisation du système → jeton Expo → `upsert` dans `appareils`.
2. La base appelle Expo Push (`pg_net`) quand le statut d'un colis change.
3. Désactiver l'option, ou se déconnecter, supprime le jeton de l'appareil.
**Défaut latent côté base** : le déclencheur appelle `extensions.net.http_post` (nom invalide, la fonction est `net.http_post`) ; le premier appareil enregistré ferait échouer les mises à jour de colis de son client (voir `DATABASE.md` §7.7). À corriger **avant** toute activation.
Limites : Expo Go ne reçoit **plus** de notifications (depuis le SDK 53) → il faut une **version de développement**. Aucun `projectId` EAS n'est configuré, donc un jeton ne peut pas être obtenu aujourd'hui. Aucun écouteur de **tap** sur une notification (elle n'ouvre pas le colis).

## 5. État de publication
| Élément | État |
|---|---|
| Identifiants | `com.speedexpressshipping.app` (iOS et Android) |
| Version | 1.0.0 |
| **Icône** | **icône Expo par défaut** (chevron bleu) ; écran de démarrage = symbole Expo |
| EAS / builds | **absents** (`eas.json`, `projectId` : aucun) |
| Comptes développeur Apple / Google | **non créés** |
| Distribution actuelle | Expo Go, sur ordinateur local (`npx expo start`) |
| Signature, certificats | aucun dans le dépôt (ignorés par `.gitignore`) |

## 6. Qualité
- `tsc --noEmit` : **0 erreur**.
- `expo lint` : **2 erreurs** (règle `react-hooks/set-state-in-effect`, `factures.tsx:39` et `index.tsx:50`) et **4 avertissements**.
- `npm audit` : 30 alertes (19 élevées, 11 modérées), dans des **outils de build** d'Expo (`@expo/cli`, `config-plugins`) — chaînes tracées pour `uuid` et `node-forge` ; non embarquées dans l'application installée (paquet final non décompilé).

## 7. Branches et pull requests
- `main` à jour avec GitHub.
- **PR n°1 ouverte** par l'autre agent (`arena-ai-coding-agent`, 2 octobre) : refonte visuelle + build web dans `docs/` pour GitHub Pages. **Conflit** avec `main` (`connexion.tsx`) ; part d'avant les deux derniers commits. À analyser avant toute décision (règle 4).
- Le dépôt avait été trouvé **public** le 5 octobre, puis remis en privé ; l'auteur du changement n'est pas établi.

## 8. Duplications avec le site
Types TypeScript recopiés de la structure des tables ; calcul des totaux de facture (`totaux`) ; les statuts et leurs libellés ; les textes en 4 langues (82 clés propres à l'application). Rien n'est partagé avec le site : le contrat de données n'est écrit que dans la base.
