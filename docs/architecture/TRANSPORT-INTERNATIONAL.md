# Le transport international (phase 4, étape 016)

Miami → Haïti et Miami → République dominicaine, en avion, en bateau ou en camion, **en direct ou avec transbordement**. Tout est
dans la base (`outils/logistique/016-transport-international.sql`, après 015) : les écrans affichent ce que les fonctions rendent et
ne recalculent ni un état, ni une étape, ni un total. Essai : `outils/tests/logistique-international-essai.py` (chaque parcours, sur la
réplique de la production **et** sur une préproduction montée comme la vraie).

État : **appliquée en production** le 13 octobre 2026 (outil de migration, journal `ses_meta.migration`).

## 1. Les parcours

| Parcours | Chemin d'une expédition | Douane |
|---|---|---|
| Direct aérien | Miami → hub Port-au-Prince (ou Saint-Domingue) | à l'arrivée |
| Direct maritime | Miami → hub Saint-Domingue (ou Port-au-Prince) | à l'arrivée |
| Transbordement | Miami → hub Saint-Domingue (bateau), puis **étape suivante** Saint-Domingue → Port-au-Prince (camion) | **une seule fois**, dans le pays du colis |
| Terrestre | à l'intérieur de l'île seulement (Haïti ↔ République dominicaine) ; un camion ne relie jamais Miami | à l'arrivée |

Une expédition peut porter des colis de **deux pays**. À l'arrivée (`arrive_shipment`), seuls les colis arrivés **dans leur pays**
passent `ARRIVED` puis en douane ; les autres restent `IN_TRANSIT` et reçoivent l'événement `ParcelTransitHubReached` (suivi, audit et
événement de domaine, même corrélation, statut inchangé). La douane locale ne déclare que les premiers. Une expédition dont **tous** les
colis continuent passe `ARRIVED → AT_HUB` sans douane (nouvelle transition) ; tant qu'un colis du pays attend sa douane, ce raccourci
est refusé.

L'**étape suivante** (`lg_create_onward_shipment`) part du hub où les colis sont arrivés, n'emmène que des colis `IN_TRANSIT` dont
l'expédition courante y est arrivée, et garde le lien (`shipment_item.from_shipment_id`). Au départ, ses colis sont **transbordés**
(`ParcelTransshipped`, statut inchangé). L'**expédition courante** d'un colis (`parcel_current_shipment`) est la plus récente qui le
porte, hors annulées et hors celles qu'une étape suivante a prolongées : l'expédition d'avant ne le déplace plus (la cascade le saute).
Annuler l'étape suivante rend le colis à sa première étape.

## 2. Les modules

| Module | Ce qui s'ajoute | Façades (`public`, comptes connectés) |
|---|---|---|
| Consolidation | responsable (`responsible_user_id`) ; fiche : colis, poids et volume totaux, valeur, entrepôt source, unité logistique | `lg_assign_consolidation_responsible`, `lg_consolidation_summary` (création, ajout, retrait, fermeture : étape 005) |
| Expédition | départ et arrivée **prévus**, hub de destination (entrepôt), fiche avec ses étapes avant et après, colis par pays | `lg_plan_shipment`, `lg_create_onward_shipment`, `lg_shipment_summary` |
| Transport | fournisseur, référence, **numéro de voyage**, dates prévues, **capacité** en poids et en volume, vérifiée au départ | `lg_create_transport`, `lg_schedule_transport` (tant que `PLANNED`) |
| Unité logistique | palette, sac, conteneur, ULD ; charge limitée (poids, volume) ; une seule destination et un seul mode ; **scellée** obligatoirement au départ ; ouverture tracée avec son motif | `lg_create_load_unit`, `lg_put_consolidation_in_load_unit`, `lg_seal_load_unit`, `lg_open_load_unit`, `lg_load_unit_summary` |
| Douane | montant des droits (USD, DOP, HTG), **payés avant la libération** ; inspections (ajout seul) ; **exceptions** par colis | `lg_customs_assess_duties`, `lg_customs_mark_duties_paid`, `lg_customs_inspect`, `lg_customs_raise_exception`, `lg_customs_resolve_exception` (direction) |
| Suivi | le parcours en huit étapes | `lg_my_parcel_journey` (le client, ses colis seulement), `lg_parcel_journey` (l'équipe, `colis.lire`) |

Fonctions de l'étape 5 redéfinies, mêmes signatures : `cascade_parcels` (expédition courante, transbordement, pays d'arrivée),
`arrive_shipment` (hubs de transit), `receive_at_hub` (pur transit, hub prévu par défaut), `dispatch_shipment` (scellés, capacité),
`clear_customs` (droits payés).

## 3. Les exceptions de douane

Une exception vise **un colis en douane** de l'expédition (`MISSING_DOCUMENT`, `UNDERVALUED`, `PROHIBITED_ITEM`, `DUTIES_UNPAID`,
`INSPECTION_HOLD`, `SEIZED`, `OTHER`) : le colis passe `ON_HOLD` (motif « Douane : … »), le reste de l'expédition suit son cours. Une
seule exception ouverte par colis. La direction la lève, avec une explication :

- **RELEASED** : le colis revient en douane, puis **rattrape** son expédition (libéré, puis au hub si elle y est déjà) ;
- **SEIZED** : le colis passe `LOST`.

## 4. Le parcours du client

`logistics.parcel_journey` rend huit étapes (`reception`, `warehouse`, `consolidation`, `departure`, `transit`, `arrival`, `customs`,
`delivery`), chacune avec `state` (`done`, `current`, `upcoming`, `stopped`), `at` et `place`, plus `current_step`, `completed`,
`exception` (`paused` : en attente, abîmé, livraison manquée ; `stopped` : perdu, retourné, annulé), `transport` (le dernier moyen :
mode, compagnie, numéro de voyage, trajet, arrivée prévue) et `transit_hubs`. Les dates viennent du journal du colis ; une étape
franchie sans trace propre (colis repris de l'ancien schéma) est « franchie » sans date. Un vol direct n'a pas de date de transit
propre. Aucune clé interne (acteur, entrepôt, GPS) : l'essai le vérifie.

Le portail (`ses-portail.js`, `P.parcoursColis`) le dessine tel quel à la place de la frise ; si la fonction n'existe pas encore (base
avant 016), il garde la frise d'avant. Contrat : `outils/tests/parcours-rpc.json` et `parcours-formes.json`, écrits par l'essai
(`SES_FORME_ECRIRE=1`) et lus par `portail-contrat.cjs` ; `portail-textes.cjs` exige un nom traduit pour chaque étape que la base
déclare. Seuls `ParcelTransitHubReached` et `ParcelTransshipped` deviennent visibles du client dans son suivi daté.

## 5. Erreurs

`LG002` introuvable, `LG003` droit insuffisant, `LG004` état incompatible (déjà scellée, déjà payé, transport parti, exception déjà
levée), `LG005` donnée refusée (capacité, scellé manquant, droits impayés, camion depuis Miami, colis pas au hub…).

## 6. Ce qui reste hors de cette phase

- ~~Les écrans de l'équipe~~ : faits (étape 024, 14 octobre 2026). Dans le tableau de bord, Expéditions : « Préparer des colis » (le chemin du
  poste de scan, `lg_prepare_parcels`), « Nouvelle expédition » (`lg_ready_for_shipment` : seulement ce que `create_shipment` acceptera), la fiche
  et les gestes de l'état présent (planifier, prête, partir, en transit, arrivée, douane, droits, libération, HUB, clôture, annulation motivée) ;
  Transport : « Nouveau transport », « Replanifier ». Éprouvés de bout en bout par `logistique-expeditions-essai.py`. Restent : l'étape suivante
  (transbordement), les unités logistiques et leurs scellés, les inspections et exceptions de douane.
- Les notifications des étapes de transit : aucune règle n'est ajoutée (le client les voit dans son suivi, sans message).
- Les droits et taxes ne créent pas de facture : le montant est tracé sur la déclaration.

## 7. Vérifier

```bash
SES_PG_BIN=/chemin/des/binaires python3 outils/tests/logistique-international-essai.py
node outils/tests/portail-contrat.cjs && node outils/tests/portail-textes.cjs
```

## 7 bis. Depuis le tableau de bord (étape 026)

L'équipe se sert de ces règles sans SQL :

| Écran | Geste | Fonction |
|---|---|---|
| Consolidations | Nouvelle consolidation (code, entrepôt, pays, mode) | `lg_open_consolidation` |
| Consolidations | Ajouter des colis : numéros scannés ou collés, ou colis « à consolider » cochés ; chaque numéro est jugé seul (`NOT_FOUND`, `WRONG_STATE`, `NO_CUSTOMER`, `OTHER_COUNTRY`, `OTHER_MODE`, `IN_CONSOLIDATION`, `REFUSED`) | `lg_fill_consolidation` |
| Consolidations | Voir les colis, en retirer un tant qu'elle est ouverte ; Fermer | `lg_consolidation_parcels`, `lg_remove_parcel_from_consolidation`, `lg_close_consolidation` |
| Consolidations | Charger dans une unité ; Retirer de l'unité (motif) | `lg_put_consolidation_in_load_unit`, `lg_remove_consolidation_from_load_unit` |
| Unités logistiques | Nouvelle unité (palette, conteneur, ULD, sac ; poids et volume maximaux facultatifs), Charger, Sceller, Ouvrir (motif), Sceller de nouveau | `lg_cc_load_units`, `lg_create_load_unit`, `lg_seal_load_unit`, `lg_open_load_unit` |
| Expéditions | Nouvelle expédition : les unités prêtes s'ajoutent aux consolidations et aux colis | `lg_ready_for_shipment` (`load_units`) |
| Expéditions | Transbordement : le hub de transit, ses colis qui attendent, la destination (le hub de leur pays d'abord), le mode | `lg_awaiting_onward`, `lg_create_onward_shipment` |

Trois trous fermés par 026 : une consolidation chargée dans une unité ne part plus seule (elle partait deux fois) ; une unité vide, ou d'un
autre mode que l'expédition, ne part pas ; une unité dont l'expédition est prête, partie ou au-delà ne change plus de contenu. Essai :
`outils/tests/logistique-unites-essai.py` (sur la réplique de la production).

## 8. Retour en arrière

`016` **ajoute** (colonnes, deux tables, événements, une transition, fonctions) et redéfinit cinq fonctions de l'étape 5 avec les mêmes
signatures. Rien n'est supprimé. **Ne jamais repasser 005 ou 015 pour « retrouver » les anciennes versions** : rejouer une étape
ancienne après une plus récente n'est pas sûr.

| Besoin | Geste | Effet |
|---|---|---|
| une capacité mal saisie bloque un départ légitime | créer un nouveau transport (`lg_create_transport`) avec la bonne capacité, ou sans capacité, et y faire partir l'expédition | le transport erroné reste `PLANNED`, inutilisé ; aucune donnée modifiée à la main |
| des droits fixés par erreur | `lg_customs_assess_duties(…, 0)` | droits à zéro, réputés payés ; la libération reprend |
| une unité ne peut pas être scellée | retirer sa consolidation de l'unité (`lg_remove_consolidation_from_load_unit`, motif obligatoire, étape 026) tant que l'expédition est en brouillon, puis l'expédier seule | aucune unité, aucun scellé exigé |
| abandonner le noyau (tant que rien ne le lit) | [`MIGRATION-REPORT.md`](MIGRATION-REPORT.md) §8 | l'ancien schéma intact, le site continue |
