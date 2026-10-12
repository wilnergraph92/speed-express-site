# La finance professionnelle (phase 6, étape 018)

Le moteur financier du noyau (`logistics`, étape 007) devient la source de vérité de l'argent. L'étape **018**
(`outils/logistique/018-finance-professionnelle.sql`, après 017) ajoute les prestataires de paiement, les webhooks, la réconciliation,
l'ajustement, la facture groupée en une transaction, le prix saisi à la main dans le calcul du noyau, la parité avec l'ancien schéma et une
bascule gardée.

Essais :
- `outils/tests/logistique-finance-pro-essai.py` : 150 vérifications, sur la réplique de la production **et** sur une préproduction montée
  comme la vraie ;
- `outils/tests/logistique-finance-essai.py` : les 385 scénarios de l'étape 7, rejoués maintenant sur le moteur de l'étape 18 ;
- `outils/tests/paiements-webhook.mjs` : le serveur des webhooks ;
- `outils/tests/finance-navigateur.cjs` : le navigateur ne calcule rien.

État : **non appliquée**. L'ancien schéma facture toujours en production (`finance_setting.mode = 'legacy'`).

## 1. Le principe

La base calcule ; le navigateur affiche. Total, taxe, remise, solde, paiement, remboursement, conversion : tout est rendu par une fonction
du noyau. Le navigateur envoie des faits (des colis, un montant encaissé au guichet, le choix d'un prestataire), jamais un prix.

## 2. Entités

| Entité | Où | Note |
|---|---|---|
| devis, grille, tranche, règle, surcharge, frais de service, taxe, taux de change | `quote`, `rate_card`, `weight_bracket`, `pricing_rule`, `surcharge`, `service_fee`, `tax`, `exchange_rate` (007) | le devis fige le calcul complet |
| facture, ligne | `invoice`, `invoice_item` (001, 007) ; `kind` = `STANDARD` ou `ADJUSTMENT`, `corrects_invoice_id` (018) | figée à l'émission |
| paiement, remboursement, avoir | `payment`, `refund`, `credit` (007) ; `payment.provider_code`, `external_id` (018) | ajout seul |
| dépense, revenu | `expense`, `revenue_entry` (007) ; catégorie `OTHER` (018) | revenu reconnu à l'émission, hors taxe |
| prestataire | `payment_provider` (018) | **aucun secret** |
| demande de paiement | `payment_intent` (018) | montant = solde calculé par la base |
| événement de paiement | `payment_event` (018) | voir §4 |
| relevé du prestataire | `provider_settlement_line` (018) | ajout seul |
| examen d'un écart | `finance_review` (018) | ajout seul, direction |
| moteur de référence | `finance_setting` (018) | `legacy` ou `core` |

## 3. Les prestataires

`CARD` (Visa / Mastercard), `AZUL`, `MONCASH`, `NATCASH` sont prévus, **éteints** ; on en ajoute un par une ligne. La table ne contient aucun
secret : `credentials_env` est le **nom** de la variable d'environnement du serveur qui porte la clé (`SES_PAY_CARD`…). La configuration publique
(`public_config`) refuse toute clé dont le nom trahit un secret (`secret`, `token`, `api_key`, `password`, `private`…), même en écriture
directe. Le client ne voit que les prestataires actifs (`lg_payment_providers`), sans `credentials_env`. On les allume avec
`lg_configure_payment_provider` (direction, audité).

## 4. Le parcours d'un paiement en ligne

1. Le client demande à payer sa facture avec `lg_my_create_payment_intent(numéro, prestataire)`. La base fixe le montant (le **solde**), la
   devise et l'expiration (2 h). La demande est idempotente avec une clé.
2. Le serveur, une Edge Function (`scripts/paiements/webhook.mjs`, modèle non déployé), crée l'ordre chez le prestataire avec la clé
   secrète. Il rattache ensuite sa référence avec `ses_payment_attach`. La demande passe `PENDING`.
3. Le prestataire appelle le webhook. Le serveur **vérifie la signature** (`prestataires.mjs` : HMAC en temps constant pour l'adaptateur
   générique), normalise l'événement et appelle `ses_payment_event`.
4. La base journalise **chaque** événement dans `payment_event`, idempotent par (prestataire, clé d'événement), puis décide :

| Résultat | Quand | Argent |
|---|---|---|
| `APPLIED` | vérifié, montant et devise de la demande, facture encore à payer | paiement enregistré, facture recalculée |
| `REJECTED_UNVERIFIED` | signature non vérifiée | rien |
| `MISMATCH` | montant ou devise différents | rien |
| `NO_INTENT` | aucune demande ne porte cette référence | rien |
| `ALREADY_PAID` | la demande est déjà payée | rien (pas de double paiement) |
| `UNAPPLIED` | argent arrivé sur une facture déjà soldée ou une demande close | rien : à rembourser ou à imputer |
| `REFUND_TO_RECONCILE` | remboursement fait chez le prestataire | rien : la direction émet l'avoir et enregistre le remboursement |
| `STATUS_UPDATED` | en attente, échoué, annulé | l'état de la demande suit |

Les trois portes `ses_payment_*` ne sont ouvertes qu'au rôle `service_role`, jamais à un visiteur ni à un compte connecté. Le serveur ne
transmet jamais le corps reçu (données personnelles) : seulement une empreinte (`raw_reference`).

**Brancher un vrai prestataire** :
1. écrire son adaptateur dans `prestataires.mjs` d'après **sa** documentation (signature, champs, états) ; ceux d'Azul, MonCash et NatCash
   sont des stubs qui refusent tout ;
2. le tester avec ses exemples officiels ;
3. déployer la fonction en préproduction avec la clé de **test**, dans les secrets de Supabase ;
4. activer le prestataire (`environment = 'test'`) ;
5. puis seulement passer en `live`.

## 5. Réconciliation

`logistics.payment_reconciliation()` liste les écarts.

**Bloquants**, tant que la direction ne les a pas examinés :
- un événement `MISMATCH`, `UNAPPLIED`, `REFUND_TO_RECONCILE`, ou `NO_INTENT` réussi ;
- un paiement de prestataire sans événement vérifié ;
- une ligne de relevé sans paiement, ou d'un autre montant.

**Informatifs** : un événement non vérifié, un paiement pas encore au relevé après 7 jours, une demande abandonnée.

On examine avec `lg_review_payment_event` et `lg_review_settlement_line` (direction, note obligatoire, ajout seul). Un écart examiné ne
bloque plus, mais reste visible. `logistics.reconcile_finance()` (007) contrôle la cohérence interne : factures, lignes, paiements, avoirs,
remboursements, revenus.

## 6. Corrections et facture groupée

- Une facture émise ne se supprime ni ne se modifie : tout passe par les déclencheurs. On corrige par :
  - un **avoir** (`lg_issue_credit_note`) ;
  - un **remboursement** (`lg_refund_payment`, plafonné à l'excédent payé) ;
  - un **ajustement** (`lg_issue_adjustment`, direction) : une facture complémentaire émise aussitôt et liée à la facture corrigée, avec la
    taxe au taux effectif de l'original.
- **Facture groupée** (`lg_create_grouped_invoice`) : plusieurs colis d'un même client, un devis, une facture, une émission, des frais de
  service **une** fois, dans **une** transaction. Un seul colis impossible à facturer, et rien n'est créé. La création est idempotente avec
  une clé.
- **Audit** : création, émission, transitions, paiement, remboursement, avoir, annulation, ajustement, configuration d'un prestataire,
  demande de paiement, examen, bascule. Chacun avec l'utilisateur, la date, l'avant et l'après (`logistics.audit_log`).

## 7. Parité avec l'ancien schéma

`logistics.legacy_finance_parity()` recalcule **chaque** facture héritée (`public.factures`) par le noyau, sur ses colis, puis classe :

| Verdict | Sens | Bloque la bascule |
|---|---|---|
| `EQUAL` | même montant | non |
| `PARCEL_CHANGED` | le colis a changé après le paiement : l'ancienne facture reste figée | non |
| `ZERO_RATE` | colis sans tarif ni prix saisi : l'ancien schéma facture 0, le noyau la grille | non |
| `NO_PARCEL`, `CURRENCY` | facture sans colis retrouvable, ou hors dollars | oui, sauf examen |
| `NO_PRICING`, `SERVICE_FEE` | le noyau n'est pas configuré (grille, frais de 10 $) | oui, sauf examen |
| `UNEXPLAINED` | tout autre écart | oui, sauf examen |

Pour que les deux moteurs disent le même prix, le noyau connaît désormais le **prix saisi à la main** (`parcel.manual_price`, ancien
`prix_manuel`).

**Mesure sur la réplique de la production** (données du 7 octobre, 202 factures héritées), avec une grille et 10 $ de frais :
- 196 à 198 `EQUAL` selon le tirage des données d'essai ;
- 2 à 4 `PARCEL_CHANGED` ;
- 2 `NO_PARCEL`, des factures groupées d'essai sans référence de colis ;
- **aucun** `UNEXPLAINED`.

On examine avec `lg_review_legacy_parity` (direction, note).

## 8. La bascule

`lg_finance_cutover_report` (direction) réunit la parité, la cohérence du noyau, les paiements et les écarts de copie avec l'ancien schéma.
`ready` n'est vrai que si **aucun** écart bloquant non examiné ne reste.

`lg_set_finance_mode('core', motif)` est refusé (`LG010`) tant que `ready` est faux. Le retour à `legacy` est toujours possible. Chaque
bascule est auditée.

**Ce que la bascule demandera au site** (non fait dans cette phase) : les écrans de l'ancienne facturation calculent encore dans le
navigateur, et `finance-navigateur.cjs` en fige la liste.
- `ses-ui.js` : `totauxFacture` (affichage d'une facture héritée) et `regrouper` (regroupement d'anciennes factures) ;
- `ses-admin.js` : `prixColis`, `calculerPrix`, `preparerFormFacture` et `totaliser`.

À la bascule, l'onglet Factures du tableau de bord passera par `lg_create_grouped_invoice`, `lg_record_payment` et `lg_invoice_detail`, et
ces calculs disparaîtront. Les écrans du moteur (portail client, centre de commande) n'en font déjà aucun.

## 9. Retour en arrière

`018` **ajoute** (tables, colonnes, contraintes élargies, fonctions) et redéfinit `compute_quote` avec la même signature. Rien n'est supprimé.

| Besoin | Geste |
|---|---|
| couper un prestataire | `lg_configure_payment_provider(code, false)` : plus de demande ; les événements reçus restent journalisés |
| revenir à l'ancienne facturation | `lg_set_finance_mode('legacy', motif)` |
| ne plus recevoir de webhooks | retirer la fonction Edge (ou sa clé) : la base ne reçoit plus rien, rien ne se perd |

Ne jamais repasser 007 pour retrouver l'ancien `compute_quote`.
