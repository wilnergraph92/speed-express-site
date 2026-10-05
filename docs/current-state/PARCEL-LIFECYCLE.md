# Cycle de vie d'un colis — état réel au 5 octobre 2026

> Décrit l'existant. **[CODE]** = schéma SQL, `ses-api.js`, `ses-admin.js`,
> `ses-ui.js`, application mobile.

## 1. Statuts
Cinq valeurs, imposées par une contrainte `check` :

| Statut | Libellé | Étape de la frise (client) |
|---|---|---|
| `confirme` | Confirmé | 1 |
| `expedie` | Expédié | 2 |
| `disponible` | Disponible | 3 |
| `livre` | Livré | 4 |
| `action` | Action requise | hors frise |

**La base n'impose aucun ordre** : tout statut valide peut succéder à tout
autre (un colis `livre` peut revenir à `confirme`). La progression est une
convention de l'interface.

## 2. Naissance
1. Une personne de l'équipe ayant `colis.creer` enregistre le colis (tableau de bord) : client (par code `SES-#####`), description, expéditeur, destinataire, téléphone, poids, **tarif au livre**, service, pays, ville, adresse, valeur.
2. Le déclencheur `preparer_colis` pose :
   - le **numéro** `SES-<compteur>-<pays>` (compteur séquentiel dès 10000) ;
   - le **jeton** (16 hex aléatoires, valeur par défaut de la colonne) ;
   - `cree_le`, `maj_le` ;
   et les **rend immuables** : une étiquette imprimée reste valable jusqu'à la livraison.
3. `verifier_client_colis` refuse un client qui n'est pas de rôle `client` (`SE002`).
4. `historiser_colis` écrit la première ligne d'historique (statut initial, auteur).
5. `facturer_colis` crée aussitôt la **facture** du colis (voir `BILLING.md`).
6. `prevenir_client` envoie la notification de création si le client a un appareil enregistré.

## 3. Vie
- **Changement de statut / lieu / note** : droit `colis.statut` (ou `colis.modifier`). Une ligne d'historique est écrite **à chaque changement de statut, de lieu ou de note**, avec l'e-mail de l'auteur. L'historique n'est jamais écrit par l'interface : seul le déclencheur le fait, et les utilisateurs n'ont pas le droit d'y écrire.
- **Modification de la fiche** (poids, tarif, client…) : droit `colis.modifier` ; sans lui, le déclencheur `verifier_modification_colis` refuse (`42501`) tout champ autre que statut/lieu/note. Tant que la facture n'est pas payée, elle suit le colis.
- **Changement en masse** : `changerStatut(ids, statut, lieu, note)` met à jour plusieurs colis (un `update … in (…)`).
- **Note** : visible par le client. Elle ne doit donc contenir rien d'interne.
- **Notification** : à chaque changement de **statut** (insert ou update du statut), message dans la langue du client vers tous ses appareils ; le contenu est le libellé du statut et le **numéro du colis**.
- **Temps réel** : tout changement de `colis`, `colis_historique` ou `factures` est poussé au site et à l'application des personnes autorisées à le lire.

## 4. Étiquette et code
Étiquette imprimable (navigateur) : numéro, code-barres Code 128, QR vers
`suivi.html?colis=<numéro>&j=<jeton>`, téléphone, destinataire, poids. Générateurs
**écrits dans le dépôt** (`ses-codes.js`), sans bibliothèque externe.

## 5. Suivi public
`suivi.html` (ou le QR) → `SES_API.suivre(numero, jeton)` → `rpc('suivre_colis')`.
Sans connexion, la fonction renvoie **uniquement** : numéro, statut, service,
pays de destination, date de mise à jour et l'historique (statut, lieu, date).
**Jamais** : client, adresse, téléphone, description, note, tarif, identifiant
interne. Un numéro d'au moins 4 caractères est exigé. **Le jeton est
facultatif** : sans lui, le numéro seul suffit (choix documenté dans le code).
Voir `SECURITY.md` et `docs/security/TRACKING-SECURITY.md`.

## 6. Fin de vie
- **Livraison** : le statut `livre` ; aucune preuve de livraison (signature, photo, horodatage de remise) n'existe.
- **Suppression** : droit `colis.supprimer` ; supprime aussi **tout l'historique** du colis (`on delete cascade`) ; la facture survit (`colis_id` mis à `null`).
- **Compte supprimé** : le colis est détaché (`client_id = null`) mais conservé.

## 7. Ce que le modèle ne connaît pas (utile pour la phase 4)
Aucune notion de : chauffeur, tournée, entrepôt, position, scan de colis, lot
ou conteneur, groupage maritime, douane, preuve de livraison, incident ou
retour. Le « lieu » est un texte libre ; l'équipe est un groupe de rôles sans
affectation opérationnelle.
