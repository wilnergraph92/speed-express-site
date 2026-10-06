# Moteur financier : devis, factures, paiements, avoirs, remboursements, soldes, dépenses, revenus

> Phase 10. Source : `outils/logistique/007-finance.sql` ; preuve : `outils/tests/logistique-finance-essai.py`
> (384 vérifications sur un vrai PostgreSQL jetable, dont une **grille de plus de 300 prix comparés à un modèle de référence indépendant**, plus 62 altérations volontaires de la migration, toutes détectées).
> **Non appliquée en production.** Elle suppose 001 à 006 déjà passées ; elle ne touche à aucune ancienne table et se rejoue sans risque.

## 1. Principe
**La base calcule, jamais le navigateur ni l'application.** Les écrans n'envoient que des faits (les colis, un poids, un montant encaissé) ; ils reçoivent des lignes,
un total, un statut. Aucun prix, aucune taxe, aucun solde n'est recalculé ailleurs.

1. **Arrondi** : au centime, **ligne par ligne** ; le total d'une facture est la somme de ses lignes arrondies, jamais l'inverse. Les montants sont `numeric(14,2)`, les tarifs au livre `numeric(12,4)`.
2. **Facture figée** : une fois émise, ses montants, ses lignes, son numéro, son client et sa devise ne changent plus, **par aucun chemin** (voir §8). On corrige par un **avoir**, on **annule**, on **rembourse**.
3. **Tarif gelé** : le devis garde son calcul complet ; la facture reprend ses lignes. Changer une grille, une taxe ou un taux plus tard ne retouche rien d'émis.
4. **Ajout seul** : paiements, avoirs, remboursements, écritures de revenu, historique des statuts, taux de change et tranches de poids ne se modifient ni ne se suppriment.
5. **Tout est tracé** : chaque opération d'argent produit une trace d'audit (avant/après, auteur), un événement de domaine et, pour une facture, une ligne d'historique, sous **une même corrélation**.
6. **Seules les factures natives** (nées d'un devis du noyau) passent par ce moteur. Les factures **héritées** de l'ancien schéma restent lues, jamais modifiées ici (`LG004`) : leur reprise est une étape à part, décidée par le propriétaire.

## 2. Les entités demandées, et où elles vivent
| Entité | Table | Remarque |
|---|---|---|
| Zone | `pricing_zone` | zone **tarifaire** (une active par pays) ; ne pas confondre avec `delivery_zone` (secteur du dernier kilomètre) |
| RateCard, WeightBracket | `rate_card`, `weight_bracket` | une grille par mode (air, mer, terre) et zone, dans **sa** devise ; tranches `[min, max[`, prix au livre, fixe, minimum |
| ServiceFee | `service_fee` | **10 $ par facture, comptés une seule fois, même groupée** (seule donnée posée par la migration : c'est la règle de l'entreprise) |
| Surcharge | `surcharge` | pourcentage, montant fixe ou au livre ; conditions : mode, zone, poids facturé, volume, drapeau demandé |
| PricingRule | `pricing_rule` | tarif négocié (`RATE_OVERRIDE`) ou remise (`DISCOUNT_PERCENT`, `DISCOUNT_FLAT`), par client, mode, zone, poids |
| Tax | `tax` | en sus, jamais incluse ; par pays ; vise le fret, les surcharges, les frais ou tout |
| (devises) | `exchange_rate` | USD, DOP, HTG ; ajout seul |
| Quote | `quote` | devis calculé et **figé** ; validité ; `OFFERED → INVOICED / EXPIRED / CANCELLED` |
| Invoice, InvoiceItem | `invoice`, `invoice_item` (étendues) | brouillon → émise ; lignes `FREIGHT`, `DISCOUNT`, `SURCHARGE`, `SERVICE_FEE`, `TAX` |
| Payment | `payment` | argent reçu ; garde ce qui a été **remis** (montant, devise), ce qui est **imputé**, l'équivalent en dollars et le taux |
| Credit | `credit` | **avoir** : la seule façon de corriger une facture émise ; réparti en net et taxe |
| Refund | `refund` | argent rendu ; plafonné à l'**excédent** payé |
| CustomerBalance | vue `customer_balance` | par client et par devise ; positif = le client doit, négatif = nous devons |
| Revenue | `revenue_entry` | reconnu **à l'émission**, hors taxe ; inversé par des lignes négatives (avoir, annulation) |
| Expense | `expense` | catégorie, devise, rattachable à une expédition ; **annulée**, jamais supprimée |

## 3. Le calcul d'un prix (`logistics.compute_quote`, pure : rien n'est écrit)
Pour **chaque colis** :
1. **Poids facturé** = poids vérifié à l'entrepôt (sinon déclaré). Si la grille a un facteur volumétrique : `max(poids, volume × facteur)`.
2. **Tarif au livre**, du plus prioritaire au moins prioritaire :
   a. **tarif imposé** sur la ligne — **direction seule**, **motif obligatoire** : fret = `poids × tarif` ;
   b. **tarif enregistré sur le colis** (l'ancien « tarif_lb », en **dollars** : devis en USD seulement) : fret = `poids × tarif` ;
   c. **règle `RATE_OVERRIDE`** (client négocié ; la plus prioritaire gagne ; dans la devise de la grille) : fret = `max(minimum, fixe + poids facturé × tarif négocié)` ;
   d. **la tranche de la grille** : fret = `max(minimum, fixe + poids facturé × prix de la tranche)`.
   (c) et (d) se calculent dans la devise de la grille, puis se **convertissent ligne par ligne** ; (a) et (b) n'ont rien à convertir. Une tranche est `[min, max[` : 5 lb est la borne **basse** de la tranche suivante.
3. **Remises**, par priorité croissante, sur le fret courant — **jamais sous zéro**.
4. **Surcharges** applicables ; les pourcentages portent sur le fret **après** remises.
5. **Une fois** : les frais de service. 6. **Taxes** : une par taxe, sur la base des lignes qu'elle vise, arrondie une fois ; une surcharge **non taxable** n'entre pas dans la base.

Exemple écrit à la main et vérifié par le test — **4 lb**, air, Haïti, en dollars, sans client négocié : fret `4 × 3,00 = 12,00` ; surcharge carburant 3 % = `0,36` ;
frais de service `10,00` ; taxes : `FEETAX` 2 % de 10,00 = `0,20`, `SURTAX` 5 % de 0,36 = `0,02`, `TCA` 10 % de (12,00 + 0,36 + 10,00) = `2,24` ; **total 24,82**.

## 4. Les devises : USD, DOP, HTG
- Un taux est `1 unité de A = r unités de B`, valable **à partir d'une date** ; on prend le plus récent **à la date du calcul**. Le taux inverse se déduit ; **aucune triangulation** (DOP → HTG exige sa propre paire, sinon `LG005`).
- **La devise de référence est le dollar** (revenus, encaissements, dépenses en base USD, convertis **à la date de l'écriture** : un taux changé plus tard ne retouche pas la synthèse).
- Un paiement peut être remis dans une autre devise que la facture : le montant imputé est converti au taux du jour ; le paiement garde le montant remis, sa devise et le taux.

## 5. Le cycle de vie de la facture
```
DRAFT ──émettre──▶ ISSUED ──┬─ paiement partiel ─▶ PARTIALLY_PAID ──┬─ solde payé ─▶ PAID ──remboursement total──▶ REFUNDED
   │                        ├─ solde payé ────────────────────────▶ PAID                (après avoir total)
   └─annuler─▶ CANCELLED    ├─ échéance dépassée ──▶ OVERDUE ─────────solde payé──────▶ PAID
                            └─ annuler / avoir total (impayée) ─▶ CANCELLED      OVERDUE ──annuler──▶ CANCELLED
```
**Onze transitions**, toutes éprouvées ; toute autre est refusée (`LG001`). Le statut **découle des montants** : `net dû = total − avoirs`, `net payé = payé − remboursé`, `solde = net dû − net payé`.
Solde ≤ 0 → payée ; sinon, partiellement payée si quelque chose est payé ; en retard si l'échéance est dépassée — **et un retard constaté ne s'efface que par le paiement du solde** (un paiement partiel ne sort pas une facture du retard).
Un avoir total sur une facture impayée l'**annule** ; sur une facture payée, l'argent reste « en attente de remboursement » jusqu'à ce qu'il soit rendu : alors **remboursée** (terminal).
`mark_overdue(date)` constate les retards ; le jour même de l'échéance, la facture n'est **pas** en retard.

## 6. Avoirs et remboursements
- **Avoir** : direction, motif obligatoire, au plus ce qui reste à créditer. Il est réparti en **net et taxe** au prorata ; **le dernier avoir reprend exactement la taxe restante** : un renversement total ne laisse aucun centime. Il inverse le revenu et la taxe par une écriture négative.
- **Remboursement** : direction, motif obligatoire. Plafonné à ce qui reste remboursable **sur ce paiement**, **et** à l'**excédent** payé par rapport à ce qui est dû. Conséquence voulue : **on ne rembourse pas une facture valable** ; il faut d'abord un avoir. Rembourser ne peut jamais créer une dette en silence.
- **Annulation** d'une facture émise : direction ; **impossible** si elle a reçu un paiement ou un avoir (on émet alors un avoir pour le solde, puis on rembourse). Le revenu est inversé. Un brouillon s'annule avec le seul droit de facturation.
- Un colis dont la facture est **annulée ou remboursée** peut être refacturé ; un colis déjà facturé (même en brouillon) ne l'est pas deux fois ; une facture ne réunit que les colis **d'un même client**.

## 7. Revenus, taxes, dépenses, synthèse
- **Revenu** reconnu **à l'émission**, hors taxe, par catégorie (fret net des remises, surcharges, frais) ; **la taxe n'est pas un revenu** : elle a sa colonne.
- **Dépenses** : catégorie (transport, douane, carburant, salaires, loyer, services, entretien, emballage, autre), devise, date (pas dans le futur), expédition facultative. **Annulables** avec un motif (direction), jamais supprimées.
- **`finance_summary(du, au)`** (direction) : revenu, taxe collectée, dépenses (par catégorie et par devise d'origine), marge, encaissé, remboursé, net encaissé, **à recevoir par devise** — en dollars de référence. Le test refait le même cumul **indépendamment**, à partir des lignes de chaque devis, et exige l'égalité au centime.

## 8. L'immuabilité, en détail
| Tentative | Résultat |
|---|---|
| `UPDATE` d'une facture du moteur hors des fonctions | refusé (`LG004`), brouillon compris |
| changer total, sous-total, taxes, frais, devise, client, numéro d'une facture **émise**, **même si le drapeau interne est actif** | refusé (`LG004`, « facture finalisée ») |
| changer le statut sans passer par la transition | refusé (`LG001`) |
| ajouter, modifier, supprimer une ligne d'une facture émise ; modifier une ligne de brouillon | refusé (`LG004`) |
| supprimer une facture, un devis, une dépense, une grille, une taxe, un taux, un paiement… | refusé (`LG004`) |
| créer une facture « native » sans devis | refusé (`LG004`) |
| faire reprendre une facture héritée par le moteur | refusé (`LG004`) |
| émettre un brouillon dont les lignes ne font plus le total | refusé (`LG005`) |

## 9. Droits
Les droits sont **ceux qui existent déjà** (`factures.lire`, `factures.creer`, `factures.modifier`) ; rien de nouveau n'est inventé.
| Qui | Peut |
|---|---|
| **direction** (gérant, administrateur) | tout ce qui suit **et** : poser les taux, zones, grilles, frais, surcharges, règles, taxes (et les désactiver) ; **imposer un tarif** (avec motif) ; **avoirs** ; **remboursements** ; **annuler une facture émise** ; **annuler une dépense** ; **synthèse** ; **contrôle d'intégrité** |
| employé avec `factures.creer` | aperçu de prix, devis, facture en brouillon, **émission**, annulation d'un **brouillon**, dépenses |
| employé avec `factures.modifier` | **encaisser**, constater les retards, expirer les devis |
| employé avec `factures.lire` | solde d'un client, détail d'une facture |
| **client** | **ses** factures émises (jamais un brouillon, jamais celles d'un autre) et **son** solde ; rien d'autre |
| anonyme | rien |

## 10. La façade (`public.lg_*`, `authenticated` seulement, acteur = `auth.uid()`)
Configuration : `lg_set_exchange_rate`, `lg_create_pricing_zone`, `lg_create_rate_card`, `lg_create_service_fee`, `lg_create_surcharge`, `lg_create_pricing_rule`, `lg_create_tax`, `lg_set_pricing_active`.
Devis et factures : `lg_price_preview`, `lg_create_quote`, `lg_cancel_quote`, `lg_expire_quotes`, `lg_invoice_from_quote`, `lg_issue_invoice`, `lg_cancel_invoice`, `lg_mark_overdue`.
Argent : `lg_record_payment` (clé d'idempotence facultative : même clé, même résultat ; même clé pour une autre demande : `LG006`), `lg_issue_credit_note`, `lg_refund_payment`.
Dépenses et lecture : `lg_record_expense`, `lg_void_expense`, `lg_finance_summary`, `lg_customer_balance`, `lg_invoice_detail`, `lg_my_invoices`, `lg_my_balance`, `lg_reconcile_finance`.
Les tables restent **fermées** (RLS active, aucun accès direct, y compris la vue `customer_balance`) ; aucune façade n'est ouverte à l'anonyme ; aucune fonction interne n'est appelable par un compte connecté.

## 11. Le contrôle d'intégrité (`reconcile_finance`)
Rend **une ligne par anomalie**, rien sur une base saine : `paid_mismatch`, `refunded_mismatch`, `credited_mismatch` (compteur ≠ somme des documents), `items_mismatch` (lignes ≠ total), `total_mismatch`,
`status_mismatch` (statut qui ne découle plus des montants), `overdue_not_marked`, `revenue_mismatch` (revenu ≠ facture − avoirs), `refund_exceeds_payment`, `customer_mismatch`.
Le test **corrompt volontairement** la base (dans une transaction annulée) pour chacune de ces anomalies et vérifie que le contrôle la voit, puis qu'après annulation la base est intacte.

## 12. Numérotation
`QUO-2026-000001`, `INV-…`, `PAY-…`, `CRN-…` (avoirs), `REF-…`, `EXP-…` : **sans trou** (un numéro pris dans une transaction annulée est rendu). Un brouillon porte un numéro **provisoire** (`DRAFT-…`) ; le numéro officiel est attribué **à l'émission**.

## 13. Cohabitation avec l'ancien schéma, et ce qui n'est PAS fait
- Les règles de l'entreprise sont reprises : tarif propre à chaque colis (le tarif enregistré sur le colis l'emporte), prix = poids × tarif, **10 $ de frais comptés une fois**, tarif gelé avec la facture, facture groupée = **un même client**.
- **Aucun tarif, aucune taxe, aucun taux n'est posé par la migration** : la direction doit les saisir avant tout usage. Sans grille, le moteur **refuse** de calculer (`LG005`) plutôt que d'inventer un prix.
- Les factures **héritées** (celles d'aujourd'hui) restent sous l'ancien schéma ; le solde client les **inclut** pour avoir une vue unique. Leur reprise (paiement d'ouverture, bascule d'autorité) reste à décider.
- **Pas encore fait** : génération du PDF depuis le moteur, envoi de la facture, paiement en ligne, rapprochement bancaire, arrondi différent par devise (tout est au centime), taxe incluse dans le prix, triangulation de devises, écran d'administration des tarifs.

## 14. Risques et limites
- **Reconnaissance du revenu à l'émission** (et non à la livraison ou à l'encaissement) : choix comptable à valider avec le comptable.
- **Un devis = une facture** : pour grouper plusieurs colis, on les met dans **le même devis** (les frais ne sont alors comptés qu'une fois). Réunir deux devis déjà faits n'est pas prévu.
- **Devise de référence fixe (USD)** ; `DOP ↔ HTG` sans paire = refus.
- **Aucune donnée n'est appliquée en production** : procédure habituelle (sauvegarde vérifiée, projet `speed-express-site` ouvert en haut du SQL Editor, 001 à 007 dans l'ordre).

## 15. Retour arrière
Au bas du fichier `007` : retirer les fonctions `public.lg_*` de la section 15, supprimer la vue `customer_balance` et les tables de l'étape, retirer les déclencheurs `guard_invoice` et `guard_invoice_item` et les colonnes ajoutées
à `invoice` et `invoice_item`. **Aucune donnée de l'ancien schéma n'est en jeu.**
