# Facturation — état réel au 5 octobre 2026

> Décrit l'existant. **[CODE]** = `outils/supabase.sql`, `supabase-maj.sql`,
> `supabase-maj-facture-groupee.sql`, `ses-api.js`, `ses-ui.js`, `ses-admin.js`.
> Aucune règle n'a été modifiée pour écrire ce document.

## 1. Le modèle en une phrase
Le prix **se calcule, il ne se saisit pas** : `poids_lb × tarif_lb`, auquel
s'ajoutent **10 $ de frais de service par facture**. Le tarif est **propre à
chaque colis**, choisi à l'enregistrement, et **gelé avec la facture**.

## 2. Naissance de la facture (dans la base)
Le déclencheur `facturer_colis` (après insertion d'un colis) :
- ne fait rien si le colis n'a **pas de client** (personne à facturer) ;
- calcule `total = round(poids × tarif, 2)` et `montant = total + 10` ;
- insère la facture : `client_id`, `colis_id`, `montant`, `frais_service = 10`, une ligne figée dans `lignes` (colis, description, quantité 1, poids, tarif, montant) ;
- numéro `FAC-<année>-<n°>` posé par `preparer_facture` (séquence **globale**).

Cas limites **[CODE]** : un colis sans poids donne `total = 0` donc une facture
de **10 $** (les frais seuls) ; un colis hérité d'avant la migration a
`tarif_lb = 0`, donc la même facture de 10 $ **[?]** sur les données réelles.

## 3. Recalcul et gel
- Tant que la facture est **impayée et sans aucun paiement**, toute modification du poids, du tarif, de la description ou du client du colis **recalcule** la facture (montant, ligne, client).
- Dès qu'un paiement est enregistré (`montant_paye > 0`) ou que la facture est `payee`, elle **ne bouge plus** : une facture ancienne reste telle qu'émise.
- Changer le tarif d'un colis suivant ne touche jamais une facture émise.

## 4. Paiement
Entièrement **manuel**, saisi dans le tableau de bord par quelqu'un ayant
`factures.modifier`. Il n'existe **aucune passerelle de paiement**, aucun
rapprochement bancaire, aucun reçu automatique.

`preparer_facture` garde le statut et le montant payé d'accord :
- insertion « payée » sans montant payé → `montant_paye = montant` ;
- `montant_paye ≥ montant` (et montant > 0) → `payee` ; sinon `impayee` ;
- basculer le statut à la main → `payee` = règlement complet, `impayee` = remise à zéro ;
- `payee_le` est posée à la première bascule en `payee`, effacée au retour en `impayee`.
Les paiements **partiels** passent par `montant_paye` (le client voit la balance).

## 5. Facture groupée
Plusieurs colis **d'un même client** réunis en une facture (`groupee = true`,
`colis_id = null`, une ligne figée par colis, **frais de service comptés une
seule fois**, valeur maximale des frais des factures absorbées).

**Le regroupement est orchestré par le navigateur** (`ses-admin.js`) :
1. refuse si une des factures est introuvable ou a déjà un paiement ;
2. calcule la facture groupée (`UI.regrouper`) ;
3. **crée** la facture groupée (`creerFacture`) ;
4. puis **supprime** une à une les factures individuelles impayées qu'elle remplace (`supprimerFacture`).

Ce n'est **pas une transaction**. Une coupure entre l'étape 3 et l'étape 4 laisse
**la facture groupée et les individuelles ensemble** (double facturation
apparente) ; une panne pendant l'étape 4 en supprime une partie seulement. Les
factures individuelles sont **supprimées définitivement** (pas d'annulation, pas
de note de crédit).

## 6. Devise et montants
`devise` par facture (défaut `USD`, réglage `devise` dans `config.js`). Les
rapports du tableau de bord séparent les soldes **par devise** (`soldes_par_devise`)
et n'additionnent jamais deux devises. Aucun taux de change n'existe.

## 7. Documents et mentions
Facture imprimable depuis le navigateur (`SES_UI.facture`). Les **lignes** viennent
du JSON gelé de la facture ; l'**adresse, le téléphone et le RNC** de
l'entreprise sont lus dans `config.js` **au moment de l'impression** : une
facture réimprimée après un changement de coordonnées affiche les nouvelles.
Aucun PDF n'est produit côté serveur et rien n'est archivé à l'émission.
**Le modèle ne gère ni taxe, ni numérotation fiscale** ; la conformité fiscale
n'est pas évaluée ici. Une facture peut aussi être **créée à la main** depuis le
tableau de bord (frais proposés : `SES_API.FRAIS_SERVICE`).

## 8. Droits
`factures.lire` / `creer` / `modifier` / `supprimer`. Un client ne lit que les
siennes. **Supprimer** une facture est un droit comme un autre : aucune trace de
qui a supprimé quoi (voir §10).

## 9. Duplication de logique métier (à connaître avant toute évolution)
| Règle | Emplacements |
|---|---|
| frais de service = 10 | `facturer_colis()` (SQL, **source de vérité**), `SES_API.FRAIS_SERVICE`, mode démo `facturerColis` |
| total = poids × tarif + frais | SQL ; démo `facturerColis` ; aperçu dans le formulaire du tableau de bord |
| regroupement | `UI.regrouper` (navigateur) ; **aucun équivalent SQL** |
| totaux / balance d'une facture | `ses-ui.js` (site), `totaux()` (application mobile) |

## 10. Traçabilité
- Historisé : les statuts des colis.
- **Non historisé** : création, modification, paiement, suppression d'une facture ; qui a enregistré un paiement et quand (seul `payee_le` existe) ; changements de tarif après coup.
- Conséquence : on ne peut pas aujourd'hui reconstituer l'historique d'un paiement ni justifier une suppression.
