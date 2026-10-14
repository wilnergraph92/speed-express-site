# Le dernier kilomètre (phase 5, étape 017)

L'étape 6 a posé le dernier kilomètre : chauffeurs, véhicules, zones, missions et leurs sept états, moteur d'affectation qui explique ses
choix, tournées, preuve de livraison en ajout seul, incidents. L'étape **017** (`outils/logistique/017-dernier-kilometre-complet.sql`, après
016) le termine. Tout est dans la base : le centre de commande et l'application « Opérations » affichent ce que les fonctions rendent.

Essais : `outils/tests/logistique-dernier-km-complet-essai.py` (chaque parcours sur la réplique de la production **et** sur une préproduction
montée comme la vraie), `outils/tests/dernier-km-contrat.cjs` (le site), `App_SES/tests/` (l'application).

État : **non appliquée**, ni en préproduction ni en production. Ordre : 001 → 017, d'abord en préproduction, puis en production après une
sauvegarde « avant migration ».

## 1. Les quatre profils

| Profil | Qui | Ce qu'il fait |
|---|---|---|
| Chauffeur (`DRIVER`) | un membre de l'équipe avec une fiche chauffeur **active** | accepte ou refuse (motif), commence, livre (preuve), échoue (incident), réordonne SA tournée, déclare ses disponibilités |
| Agent de livraison (`DELIVERY_AGENT`) | droit `colis.statut`, rattaché à un hub (ou sans succursale) | crée les livraisons, affecte (à la main ou automatiquement), forme et modifie les tournées |
| Responsable de livraison (`DELIVERY_MANAGER`) | `colis.statut` **et** `livraisons.gerer` | en plus : statut des chauffeurs et des véhicules, véhicule et fiche d'un chauffeur, zones et secteurs, annulation d'une mission ou d'une tournée |
| Manager des opérations (`OPERATIONS_MANAGER`) | gérant ou administrateur | tout, dont : créer chauffeurs, véhicules et zones, forcer une affectation, livrer sans preuve (dérogation tracée) |

`livraisons.gerer` est un droit d'employé comme les autres : il se coche dans « Équipe » du tableau de bord (`SES_API.DROITS`) et passe dans
le noyau par le rattrapage (`logistics.app_user.rights`). La règle est `logistics.require_delivery_manager` ; le profil, `lg_my_staff_profile`.

## 2. Ce que l'étape ajoute

| Module | Ajout | Façades (comptes connectés) |
|---|---|---|
| Chauffeur | statut `ACTIVE` / `INACTIVE` / `ON_LEAVE` avec **motif**, refusé tant qu'il a des missions ouvertes ; véhicule (actif, à un seul chauffeur, jamais changé en tournée) ; fiche (téléphone, permis, succursale, nombre d'arrêts) | `lg_set_driver_status`, `lg_set_driver_vehicle`, `lg_update_driver` |
| Véhicule | statut `ACTIVE` / `MAINTENANCE` / `OUT_OF_SERVICE` avec motif (`active` en découle, contrainte en base) ; jamais retiré en pleine tournée | `lg_set_vehicle_status` |
| Zone | **secteurs** ; mise à jour ; zone d'une adresse : par secteur, sinon par ville (accents, majuscules et espaces ignorés), jamais devinée si deux zones répondent ; une livraison créée sans zone reçoit celle de la ville de son colis | `lg_update_zone`, `lg_resolve_zone` |
| Affectation | réaffecter exige un **motif** (gardé sur la proposition retirée) ; proposer, accepter, refuser (motif) existaient | `lg_assign_task` (même signature) |
| Tournée | ordre des arrêts (équipe, ou le chauffeur pour les siens encore à faire), ajout, retrait (motif), annulation (motif, missions libérées), fiche | `lg_reorder_trip`, `lg_add_task_to_trip`, `lg_remove_task_from_trip`, `lg_cancel_trip`, `lg_trip_detail` |
| Preuve de livraison | `captured_at` : l'heure de la remise relevée par le téléphone (transmise par `lg_mobile_command`, au plus 7 jours avant, jamais future ; sinon l'heure de la base) | — |
| Incidents | `WRONG_PHONE`, `MISSING_PARCEL` (grave), `DELIVERY_IMPOSSIBLE`, en plus de client absent, adresse incorrecte, refus, dommage | `lg_fail_task` |
| Tableau | voir §4 | `lg_cc_last_mile` |

Fonctions redéfinies, mêmes signatures : `report_incident_for_task`, `fail_task`, `cancel_task` (responsable de livraison), `assign_task`,
`complete_delivery`, `create_delivery`, `staff_profile`, `mobile_command`.

## 3. Ce qui existait et reste la règle

- Les sept états d'une mission (`CREATED`, `ASSIGNED`, `ACCEPTED`, `STARTED`, `COMPLETED`, `FAILED`, `CANCELLED`) et leurs transitions sont des
  données (`task_transition`) ; un statut ne change que par elles.
- L'affectation automatique (`lg_auto_assign_task`, `lg_auto_assign_day`) écarte un chauffeur, raison à l'appui, s'il est inactif, hors zone,
  indisponible, sans véhicule actif (un véhicule en maintenance compte comme absent), au-delà de la capacité en poids ou en volume, à son
  maximum d'arrêts, ou s'il a déjà refusé la mission ; puis note les autres (distance, charge).
- La preuve de livraison (nom, signature ou photo, GPS, heure, code à usage unique si exigé) est **en ajout seul** : ni modification ni
  suppression, même pour le propriétaire de la base. Un colis ne passe « livré » qu'avec elle, sauf dérogation tracée de la direction.

## 4. Le tableau du dernier kilomètre

`logistics.last_mile_dashboard` (façade `lg_cc_last_mile`, section « Dernier kilomètre » du centre de commande, `assets/js/ses-dernier-km.js`)
rend, pour un jour (celui d'Haïti par défaut) :

- **missions du jour** par état, sans chauffeur, en retard ;
- **livraisons en cours**, la plus en retard d'abord ;
- **chauffeurs actifs** : disponibles, en service, charge, arrêts, véhicule, âge de la dernière position ;
- **échecs du jour**, même replanifiés depuis, avec leur motif ;
- **incidents ouverts** des missions, par genre et par gravité ;
- **SLA** : à l'heure (remise avant la fin de la fenêtre promise, ou de la journée), réussite (livrées / tentées), premier passage, contre une
  cible de 95 % écrite dans la fonction ;
- **preuves manquantes** : livraisons par dérogation (jour, 30 jours, motifs), anomalies (livré sans preuve ni dérogation, mission terminée
  sans preuve : jamais attendu).

L'écran ne compte rien ; il se relit à chaque signal temps réel (`public.ses_signal`, émis pour chaque événement du noyau) et avec
l'actualisation automatique. Le bouton « Affecter automatiquement la journée » appelle `lg_auto_assign_day`. Pas de chiffres en démonstration.

## 5. L'application « Opérations »

`App_SES` : les motifs d'échec sont exactement ceux de la base (`tests/contrat-rpc.cjs` exige les deux sens) ; la remise envoie `recorded_at`
(heure prise à la validation, pas à l'envoi) ; les profils `DELIVERY_MANAGER` et `OPERATIONS_MANAGER` ouvrent l'onglet des tournées. Contrat :
`outils/tests/applications-formes.json` (écrit par `logistique-applications-essai.py`, qui installe maintenant jusqu'à 017) recopié dans
`App_SES/tests/formes-noyau.json`.

## 6. Erreurs

`LG002` introuvable, `LG003` droit insuffisant (dont `livraisons.gerer`), `LG004` état incompatible (déjà dans ce statut, tournée partie),
`LG005` donnée refusée (motif manquant, missions ouvertes, véhicule d'un autre, ordre incomplet, capacité, plafond d'arrêts…).

## 7. Vérifier

```bash
SES_PG_BIN=/chemin/des/binaires python3 outils/tests/logistique-dernier-km-complet-essai.py
node outils/tests/dernier-km-contrat.cjs
cd ~/Desktop/App_SES && npm run essai
```

## 8. Ce qui reste hors de cette phase

- Les gestes de gestion (statut d'un chauffeur, d'un véhicule, secteurs, ordre d'une tournée) ont leurs façades, testées ; le centre de
  commande n'en propose pas encore de formulaire (seule l'affectation automatique de la journée y est un bouton).
- L'optimisation de l'ordre des arrêts (itinéraire) : l'ordre est choisi par l'équipe ou le chauffeur ; la base le garde et le vérifie.

## 9. Retour en arrière

`017` **ajoute** (colonnes, contraintes élargies, événements, fonctions) et redéfinit huit fonctions avec les mêmes signatures. Rien n'est
supprimé. **Ne jamais repasser 006, 011 ou 015** pour retrouver les anciennes versions.

| Besoin | Geste | Effet |
|---|---|---|
| un motif bloque un geste urgent | écrire le motif : il n'y a pas d'autre chemin, c'est la règle | — |
| un véhicule est bloqué en maintenance par erreur | `lg_set_vehicle_status(…, 'ACTIVE', motif)` | il revient dans le moteur |
| retirer la section du centre | retirer le script `ses-dernier-km.js` de `outils/pages/tableau-de-bord.html`, par PR | la base reste ; l'écran ne l'affiche plus |
| abandonner le noyau (tant que rien ne le lit) | [`MIGRATION-REPORT.md`](MIGRATION-REPORT.md) §8 | l'ancien schéma intact, le site continue |


## Depuis le tableau de bord (étape 025, 14 octobre 2026)

- **Livraisons** : « Nouvelle livraison » (les colis d'un client qui attendent au HUB, `lg_ready_for_delivery` ; destinataire, téléphone, adresse
  préremplis depuis la fiche client ; code exigé ou non) ; sur chaque mission, les gestes de son état : affecter (chauffeurs classés par
  `lg_rank_drivers` ; un chauffeur non retenu exige un motif), affecter automatiquement, envoyer le code, replanifier (échouée), annuler (motif).
- **Remise au comptoir** : le client, ou quelqu'un pour lui, retire ses colis au HUB. `lg_hand_over_at_counter` écrit la preuve
  (`logistics.counter_handover`, ajout seul : qui retire, sa pièce d'identité, qui remet, où, quand), puis fait passer les colis
  `AT_DESTINATION_HUB → DELIVERED` (événement « Delivered » : le client est prévenu comme d'une livraison). La règle « livré exige une preuve »
  et le contrôle de cohérence acceptent cette preuve ; sans elle, la transition reste refusée.
- **Tournées** : « Nouvelle tournée » (un chauffeur, un jour, ses missions ACCEPTÉES dans l'application), « Annuler la tournée » (motif).
- Restent : les zones de livraison et la disponibilité des chauffeurs (l'affectation automatique s'en sert ; à la main, elle s'en passe).
