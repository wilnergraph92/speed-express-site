# Rôles et permissions — état réel au 5 octobre 2026

> Décrit l'existant. Source : **[CODE]** `outils/supabase.sql`, `outils/supabase-maj.sql`,
> `assets/js/ses-api.js` ; **[TEST]** `roles-sql.cjs` (498) et `roles-api.cjs` (66).
> La règle vit dans la **base** ; le navigateur et l'application ne font que la refléter.

## 1. Les quatre rôles

| Rôle | Peut faire | Gère les rôles | Tableau de bord | Espace client / application |
|---|---|---|---|---|
| `client` | rien d'administratif ; lit **ses** colis et **ses** factures | non | **jamais** | oui |
| `employe` | exactement les droits cochés, un par un | seulement si `roles.gerer` lui est coché | selon ses droits de lecture | **non** (renvoyé au tableau de bord) |
| `gerant` | tous les droits d'activité (colis, factures, clients) | employés et clients seulement | oui | non |
| `admin` | tout | tout le monde, gérants et administrateurs compris | oui | non |

## 2. Les 11 droits (colonne `droits`, employés seulement)
`colis.lire`, `colis.creer`, `colis.modifier`, `colis.statut`, `colis.supprimer`,
`factures.lire`, `factures.creer`, `factures.modifier`, `factures.supprimer`,
`clients.lire`, `roles.gerer`.

- `colis.statut` est un droit réduit : statut, lieu et note, rien d'autre.
- Gérant et administrateur n'ont **pas** de liste : leur rôle donne tout (`a_droit()` répond « vrai »).
- La colonne `droits` d'un client ou d'un administrateur **n'ouvre jamais rien**.

## 3. Hiérarchie appliquée par `definir_role(p_id, p_role, p_droits)`
1. Appelant : droit `roles.gerer` obligatoire (`42501` sinon).
2. Rôle demandé : un des quatre (`22023` sinon).
3. **Personne ne modifie son propre rôle** (seule exception : un administrateur qui se « rend » administrateur ne change rien).
4. **Seul un administrateur** nomme, modifie ou retire un gérant ou un administrateur.
5. Le gérant et l'administrateur n'ont pas de droits à cocher : la liste est vidée.
6. **L'équipe n'est pas la clientèle** :
   - devenir membre de l'équipe **efface le code** `SES-#####` ; refusé si le compte a des colis ou des factures (`SE001`) ;
   - redevenir client en donne un nouveau ;
   - un compte d'équipe hérité qui porte encore des colis **garde** son code (on ne coupe pas ce lien en silence).
7. Le déclencheur `verifier_client_rattache` interdit de rattacher un colis ou une facture à un compte non client (`SE002`).

## 4. Où la règle est reflétée
| Lieu | Rôle |
|---|---|
| `SES_API.accesTableauDeBord(profil)` | **un seul endroit** décide qui entre dans le tableau de bord : être de l'équipe **et** pouvoir lire quelque chose ; fermé par défaut |
| `ses-admin.js` | garde d'entrée ; boutons selon les droits ; onglets **Clients** et **Équipe** séparés |
| `ses-espace.js` | un compte d'équipe est renvoyé au tableau de bord |
| `App_SES/src/api/session.tsx` | refuse tout compte non `client` et le déconnecte |
| Mode démo de `ses-api.js` | reproduit les mêmes règles (vérifié par `roles-api.cjs`) |

## 5. Comment on devient administrateur
Premier administrateur : `select public.definir_admin('adresse');` dans le SQL
Editor (fonction fermée à l'API). Ensuite, depuis le tableau de bord : un
compte d'équipe ne se **crée** pas depuis le navigateur (cela exigerait la clé
secrète) : la personne crée un compte normal, puis « Équipe › Ajouter un membre ».

## 6. Écarts et réserves
- Un compte d'équipe existant **avant** la règle « équipe ≠ clientèle » peut encore porter des colis et un code **[?]** (non lisible de l'extérieur).
- Il n'existe **pas de journal des changements de rôle** (qui a nommé qui, quand).
- Le rôle `chauffeur`/`entrepôt` n'existe pas : tout futur rôle opérationnel touche cinq endroits (contrainte SQL, fonctions SQL schéma **et** migration, `ROLES`/`droitsDe` dans `ses-api.js`, les deux implémentations de `definirRole`, gabarits et dictionnaires).
