# Correspondance des données : de `public` au noyau `logistics`

> Phase 5. Source : `outils/logistique/002-retroremplissage.sql`. **État en production : non appliqué.**
> Le rattrapage est **lecture seule** sur l'ancien schéma, **idempotent**, sans suppression. Démontré sur
> PostgreSQL réel avec des données fictives : 88 vérifications (`outils/tests/logistique-essai.py`).

## 1. Vue d'ensemble

| Ancien (`public`) | Nouveau (`logistics`) | Clé de rapprochement | Remarque |
|---|---|---|---|
| `clients` (`role = 'client'`) | `customer` | `customer.legacy_client_id = clients.id` | |
| `clients` (rôle d'équipe **qui porte des colis/factures**) | `customer` (`source = legacy_staff_account`) **et** `app_user` | idem | cas hérité d'avant « équipe ≠ clientèle » |
| `clients` (rôle `employe`, `gerant`, `admin`) | `app_user` | `app_user.id = clients.id` | `employe→employee`, `gerant→manager` |
| `colis` | `parcel` | `parcel.legacy_parcel_id = colis.id` | |
| `colis_historique` | `tracking_event` | `tracking_event.legacy_history_id = colis_historique.id` | une ligne = un événement |
| `factures` | `invoice` | `invoice.legacy_invoice_id = factures.id` | |
| `factures.lignes` (JSON) | `invoice_item` | `invoice_item.legacy_line_key = <id>:<rang>` | une ligne par élément du JSON |
| `appareils` | `device` (`kind = customer_push`) | `device.push_token = appareils.jeton` | |
| — | `organization` | — | une ligne : l'entreprise |

## 2. Colonne par colonne

### `clients` → `customer`
`id→legacy_client_id` (et `auth_user_id`) · `code→code` · `nom_complet→full_name` · `pays→country` ·
`region→region` · `ville→city` · `adresse→address` · `telephone→phone` · `email→email` ·
`langue→language` (valeur inconnue → `fr`) · `cree_le→created_at`. Le **nouvel `id`** du client est
indépendant du compte Auth : un client peut exister sans compte.
*Non repris* : `role`, `droits` (→ `app_user` pour le personnel).
*Non normalisé* : `pays` reste du texte libre (« Haïti », « Haiti ») — la normalisation est une décision séparée.

### `clients` (équipe) → `app_user`
`id→id` · `role→role` · `droits→rights` · `cree_le→created_at`. Un membre redevenu client est **désactivé** (`active = false`), jamais supprimé.

### `colis` → `parcel`
| Ancien | Nouveau | Transformation |
|---|---|---|
| `numero` | `tracking_number` | identique |
| `jeton` | `public_token` | identique |
| `client_id` | `customer_id` | via `customer.legacy_client_id` ; **reste vide** si le colis n'a pas de client |
| `description`, `expediteur`, `destinataire` | `description`, `sender_name`, `recipient_name` | identiques |
| `telephone_destinataire`, `adresse_livraison` | `recipient_phone`, `delivery_address` | identiques |
| `pays_destination`, `ville_destination` | `destination_country`, `destination_city` | identiques |
| `valeur_declaree`, `poids_lb`, `tarif_lb` | `declared_value`, `weight_lb`, `rate_per_lb` | identiques |
| `service` | `service_mode` | `aerien→air`, `maritime→sea`, `terrestre→ground` |
| `statut` | `status` **et** `legacy_status` | voir §3 ; l'original est **toujours conservé** |
| `lieu`, `note` | `current_location`, `note` | identiques |
| `cree_le` | `created_at` | identique ; `updated_at` = date du dernier rattrapage |

### `colis_historique` → `tracking_event`
`colis_id→parcel_id` (via `legacy_parcel_id`) · `statut→to_status` (traduit) · statut de la ligne précédente
→ `from_status` · `cree_le→occurred_at` · `lieu→location_text` · `auteur→actor_label` **et**, si l'e-mail
correspond à un membre du personnel, `actor_user_id` · `note` et statut d'origine → `metadata` ·
`event_type = 'ParcelStatusChanged'` · `source = 'legacy_backfill'`.

### `factures` → `invoice`
`numero→number` · `client_id→customer_id` · `devise→currency` (USD/DOP/HTG ; autre → USD) · `montant→total` ·
`frais_service→service_fee` · `montant_paye→paid_amount` · `groupee→is_grouped` · `cree_le→issued_at` ·
`echeance_le→due_date` · `payee_le→paid_at` · `note→note`. **Statut** : `payee→PAID` ;
`impayee` avec `montant_paye > 0 → PARTIALLY_PAID` ; sinon `ISSUED`. (`OVERDUE` n'est pas déduit : c'est une règle de la phase 10.)
`factures.lignes` → `invoice_item` : `description`, `quantite→quantity`, `poids_lb→weight_lb`,
`tarif_lb→unit_price`, `montant→amount`, `colis_id→parcel_id` (via `legacy_parcel_id`).

### `appareils` → `device`
`jeton→push_token` · `plateforme→platform` · `vu_le→last_seen_at` · propriétaire → `owner_customer_id`
(ou `owner_user_id` si l'appareil est celui d'un membre du personnel).

## 3. Traduction des statuts de colis
| Ancien `statut` | Nouveau `status` | Pourquoi |
|---|---|---|
| `confirme` | `CREATED` | colis enregistré, pas encore reçu |
| `expedie` | `IN_TRANSIT` | parti |
| `disponible` | `AT_DESTINATION_HUB` | disponible à destination |
| `livre` | `DELIVERED` | |
| `action` | `ON_HOLD` | une action est requise |

Traduction **imparfaite par nature** : cinq valeurs pour vingt. Elle ne prétend pas savoir si un colis
« expédié » a franchi la douane. C'est pourquoi `legacy_status` est gardé, et pourquoi le statut n'est
repris qu'**une fois par colis** sous l'autorité de l'ancien schéma (`status_authority = 'legacy'`) ;
dès que la machine d'états du noyau prend la main (`'core'`, phase 6), le rattrapage **n'y touche plus**.

## 4. Ce qui n'est PAS migré (et pourquoi)
| Élément | Raison |
|---|---|
| Paiements individuels | l'ancien schéma ne garde que `montant_paye` agrégé ; **aucun paiement n'est fabriqué**. La table `payment` (phase 10) naîtra des paiements réellement saisis |
| Succursales, entrepôts, emplacements | jamais enregistrés ; ne sont pas inventés |
| Positions (GPS, entrepôt) des événements passés | inconnues : `location_text` seul |
| Mots de passe, sessions | restent dans Supabase Auth |
| Factures sans ligne dans le JSON | copiées sans ligne (la comparaison les signale comme `mismatch/invoice_item` si les nombres diffèrent) |

## 4bis. Cas limites traités (et testés)
Colis **sans client** · compte d'équipe **hérité** qui garde ses colis et factures · membre d'équipe **redevenu client** ·
facture **groupée** (sans colis unique) · facture **partiellement payée** · colis dont le statut a été
**pris en main par le noyau** · changement de l'ancien schéma **après** le rattrapage (dérive).

## 5. Exécution (jamais automatique)
Dans l'ordre, après une **sauvegarde vérifiée** (`docs/backup/`) et dans le projet `speed-express-site` :
1. `outils/logistique/001-modele-de-domaine.sql` — crée le schéma, ferme tout, ne copie rien ;
2. `outils/logistique/002-retroremplissage.sql` — crée deux fonctions, ne copie rien ;
3. `select * from logistics.reconcile_with_legacy();` — lecture seule : doit tout lister comme « manquant » ;
4. `select logistics.backfill_from_legacy();` — copie ; renvoie un rapport `{"parcel": {"inserted": N, "updated": 0}, …}` ;
5. `select * from logistics.reconcile_with_legacy();` — **doit renvoyer 0 ligne** ;
6. rejouer 4 : le rapport doit afficher **0 / 0** partout.

**Retour arrière** (à n'importe quel moment) : `drop schema logistics cascade;` — rien d'autre ne dépend du noyau.

## 6. Lire la comparaison
`reconcile_with_legacy()` rend `(kind, entity, legacy_id, detail)` :
`missing_in_core` (à rattraper) · `orphan_in_core` (le noyau a une ligne que l'ancien n'a plus : **à examiner, jamais supprimé
automatiquement**) · `mismatch` (champs différents, nommés dans `detail`). Aucune ligne = cohérents.

## 7. Entre le rattrapage et la bascule
Tant que l'ancien schéma reste la source de vérité, **le noyau prend du retard dès que le site écrit**. C'est
attendu : on relance le rattrapage, ou, à l'étape 3 de la stratégie (double écriture), un déclencheur le fait en continu.
