# Dernier kilomètre : chauffeurs, enlèvements, livraisons, preuve

> Phase 9. Source : `outils/logistique/006-dernier-kilometre.sql` ; preuve : `outils/tests/logistique-dernier-km-essai.py`
> (242 vérifications sur un vrai PostgreSQL jetable, plus 26 altérations volontaires de la migration, **toutes détectées**).
> **Non appliquée en production.** Elle suppose 001 à 005 déjà passées ; elle ne touche à aucune ancienne table et se rejoue sans risque.

## 1. Principe
Une **mission** (`task`) est une unité de travail confiée à **un** chauffeur pour **un** jour : aller chercher des colis chez un client (`PICKUP`)
ou les remettre à leur destinataire (`DELIVERY`). Les deux natures partagent la **même table, les mêmes états, les mêmes règles** ; les vues
`pickup_task` et `delivery_task` n'en sont que des filtres. La base est la source de vérité : l'application mobile et le tableau de bord ne
font qu'appeler les façades `public.lg_*`, qui contrôlent le droit et ne prennent **jamais l'acteur en paramètre** (c'est `auth.uid()`).

**Un chauffeur n'est pas un rôle de plus.** C'est un membre de l'équipe (`app_user`, rôle inchangé) qui a, en plus, une fiche `driver`. Il n'a
donc **ni profil client, ni identifiant `SES-#####`**, et l'ancien schéma (`clients.role`) n'a pas à changer : un chauffeur y est un employé sans
droit coché. Le rattrapage (`002`) n'est pas touché.

## 2. Les entités
| Table | Rôle |
|---|---|
| `vehicle` | plaque, type (moto, voiture, fourgon, camion), capacité en **lb** et en **pi³**, succursale |
| `delivery_zone` | secteur de livraison (code, pays, villes) |
| `driver`, `driver_zone` | fiche du chauffeur : véhicule par défaut, **nombre maximal d'arrêts**, dernière position GPS ; zones qu'il dessert |
| `driver_availability` | créneaux **disponibles** et **blocages** (`available = false`) |
| `task` | la mission ; `task_status`, `task_transition` (13 transitions), `task_status_history` (ajout seul) |
| `delivery` (étendue) | adresse, destinataire, fenêtre horaire, priorité, poids, volume, code de livraison (empreinte salée) |
| `pickup_parcel` | les colis effectivement collectés par un enlèvement (un colis ne s'enlève **qu'une fois**) |
| `assignment` | la proposition faite à un chauffeur : `OFFERED → ACCEPTED / REFUSED / REASSIGNED / CANCELLED / COMPLETED`, avec note et explication |
| `trip`, `stop` (étendues) | la tournée d'un chauffeur pour un jour, ses arrêts dans l'ordre |
| `proof_of_delivery` | **ajout seul** : nom, signature **ou** photo, heure, GPS, code vérifié |
| `incident` (étendue) | rattaché à la mission ; les 7 types du dernier kilomètre existaient déjà (phase 7) |

## 3. La mission
```
CREATED ──assigner──▶ ASSIGNED ──accepter──▶ ACCEPTED ──commencer──▶ STARTED ──┬─terminer──▶ COMPLETED
   ▲                     │  ▲                   │                              └─échouer───▶ FAILED ──replanifier──▶ CREATED
   └──────refuser────────┘  └──réaffecter───────┘
CREATED / ASSIGNED / ACCEPTED / FAILED ──annuler (direction)──▶ CANCELLED
```
Le statut de la mission ne change que par `logistics.move_task()` (déclencheur `guard_task_status`) : un `UPDATE` direct est refusé (`LG001`).
`move_task` écrit **dans la même transaction** l'historique, l'audit (avant/après), l'événement de domaine et, ensemble, **le statut de la
livraison et celui de l'arrêt** — jamais ailleurs.

| Étape | Qui | Effet sur les colis |
|---|---|---|
| créer un enlèvement / une livraison | personnel (`colis.statut`) | livraison : les colis passent `DELIVERY_ASSIGNED` |
| proposer, affecter, réaffecter | personnel ; **forcer** : direction, motif obligatoire | — |
| accepter, refuser (motif obligatoire, **tant que non accepté**) | **le chauffeur concerné seulement** | — |
| commencer | le chauffeur | livraison : `OUT_FOR_DELIVERY` |
| terminer un enlèvement | le chauffeur, avec la liste des colis collectés | colis du **client de l'enlèvement**, encore `CREATED`, jamais déjà enlevés |
| terminer une livraison | le chauffeur, **avec preuve** | `DELIVERED` |
| échouer | le chauffeur, avec un type d'incident | livraison : retour `AT_DESTINATION_HUB` ; incident ouvert |
| replanifier | personnel | colis de nouveau `DELIVERY_ASSIGNED`, mission `CREATED`, sans chauffeur |
| annuler | **direction**, motif | colis `DELIVERY_ASSIGNED` : retour au hub |

Un colis dont la livraison a **échoué** n'entre pas dans une autre livraison : on **replanifie ou on annule** d'abord.

## 4. Le moteur d'affectation : il décide et il explique
`logistics.rank_drivers(mission)` évalue **chaque** chauffeur. Il est **écarté** (avec la raison dans `reasons`) s'il est :

| Raison | Règle |
|---|---|
| `INACTIVE` | fiche non active (congé, désactivé) ou compte d'équipe inactif |
| `ZONE` | ne dessert pas la zone de la mission |
| `UNAVAILABLE` | **avec fenêtre horaire** : aucun créneau disponible ne la couvre, ou un blocage la touche. **Sans fenêtre** : aucun créneau disponible ce jour-là, ou un blocage couvre **toute** la journée |
| `NO_VEHICLE` | pas de véhicule actif |
| `REFUSED_BEFORE` | a déjà **refusé cette mission** : le moteur ne la lui repropose pas |
| `CAPACITY_WEIGHT`, `CAPACITY_VOLUME` | poids ou volume (avec ceux de ses missions déjà prévues ce jour-là) dépasse son véhicule |
| `MAX_STOPS` | a déjà son nombre maximal d'arrêts |

Les autres reçoivent une **note** : `100 − min(60, distance_km × k) − 2 × missions déjà prévues`, avec `k = 2` si la priorité est 1 ou 2, `k = 1` sinon.
La distance est celle **à vol d'oiseau** (haversine) depuis la **dernière position connue** du chauffeur ; sans position (`NO_POSITION`), pas de pénalité.
`auto_assign` propose la mission au meilleur ; **si personne n'est éligible, rien n'est créé** et on rend la liste complète avec les raisons.
`auto_assign_day` traite la journée **par priorité puis par heure d'ouverture de fenêtre** ; chaque affectation compte dans la charge de la suivante.
`assign_task` applique les mêmes contrôles ; **seule la direction force**, avec un motif, et le forçage est tracé (`task.assign_forced`) avec les règles écartées.
Une réaffectation retire la mission de la tournée de l'ancien chauffeur (arrêt « sauté »).

**Limites assumées.** Pas d'optimisation d'itinéraire (l'ordre des arrêts est celui de la saisie) ; distance en ligne droite, pas de temps de trajet ; la position
est celle du dernier relevé, pas de la dernière mission. Les journées s'entendent à l'**heure d'Haïti** (`logistics.day_start`, une seule définition à changer).

## 5. Les tournées
`create_trip` rassemble des missions **acceptées par ce chauffeur, prévues ce jour-là, hors de toute autre tournée** ; elle refuse si le total dépasse
le véhicule (poids, volume) ou le nombre d'arrêts. `start_trip` commence toutes les missions ; `complete_trip` **refuse tant qu'une mission court encore**.

## 6. La preuve de livraison
`complete_delivery` exige : **nom du destinataire**, **position GPS**, **signature ou photo** (chemins `pod/<id de la mission>/<fichier>` : le fichier d'une
autre mission, ou un chemin qui sort du dossier, est refusé), et, **si la livraison l'exige, le code**. Le tout est écrit en **ajout seul**
(`UPDATE`/`DELETE` refusés, `LG004`), puis les colis passent `DELIVERED`, sous **une seule corrélation** : preuve, livraisons, fin de mission.

**La règle de fond est dans la base**, pas dans l'application : un colis sous l'autorité du noyau ne passe `DELIVERED` que si une preuve existe
(`guard_parcel_status`), **quel que soit le chemin** — y compris `lg_transition_parcel` appelé par un employé. Seule la direction déroge
(`deliver_without_proof`, motif obligatoire, audit `parcel.delivered_without_proof`) ; la dérogation ne survit pas à sa transaction.
Les colis encore sous l'autorité de l'**ancien** schéma ne sont pas concernés : rien ne change pour eux.

### Le code à usage unique
`issue_delivery_otp` (personnel) tire un code à 6 chiffres, **n'en conserve que l'empreinte salée**, et l'envoie **au destinataire** par une notification
(`logistics.notification`, avec le téléphone du destinataire) : **le chauffeur ne le voit jamais** (ni dans `my_tasks`, ni dans un événement). Cinq essais, validité
paramétrable (24 h par défaut) ; un essai raté est **compté même si l'appel échoue** ; au cinquième, même le bon code est refusé jusqu'à une nouvelle émission ; le code
est **effacé une fois utilisé**. Une livraison qui exige un code et n'en a pas reçu est refusée.

## 7. Les incidents
Sept types, tous éprouvés : `CUSTOMER_ABSENT`, `WRONG_ADDRESS`, `DAMAGED`, `REFUSED`, `VEHICLE_PROBLEM`, `PAYMENT_PROBLEM`, `OTHER` (gravité `HIGH` pour `DAMAGED` et
`REFUSED`, `MEDIUM` sinon). Échouer une mission **ouvre l'incident, ramène les colis au hub et marque la mission** dans la même transaction. Le colis n'est **pas** déclaré
endommagé automatiquement : c'est la décision du personnel (`ParcelDamaged`).

## 8. Droits
| Qui | Peut |
|---|---|
| **direction** (gérant, administrateur) | créer véhicules, zones, chauffeurs ; attribuer les zones ; **forcer** une affectation ; **annuler** une mission ; **livrer sans preuve** |
| **personnel** (`colis.statut`) | créer enlèvements et livraisons ; classer, affecter, réaffecter ; replanifier ; émettre le code ; créer des tournées ; voir le tableau du jour ; saisir les disponibilités de n'importe qui |
| **chauffeur actif** | accepter/refuser/commencer/terminer/échouer **ses** missions ; démarrer/terminer **sa** tournée ; mettre à jour **sa** position et **ses** disponibilités ; lire **ses** missions |
| **client, visiteur** | rien (`42501`) |

**Le droit `livraison`.** Les transitions `DELIVERY_ASSIGNED → OUT_FOR_DELIVERY`, `OUT_FOR_DELIVERY → DELIVERED` et `OUT_FOR_DELIVERY → AT_DESTINATION_HUB` l'exigent.
Un employé avec `colis.statut` et la direction l'ont comme avant ; **un chauffeur actif ne l'a que pendant l'exécution d'une fonction de mission** (`actor_can`, drapeau local à la
transaction). Il n'a **jamais** `colis.statut` ni `direction` : il ne peut pas changer un statut par `lg_transition_parcel`.

## 9. La façade (27 fonctions, `authenticated` seulement)
`lg_create_vehicle`, `lg_create_zone`, `lg_create_driver`, `lg_set_driver_zones`, `lg_set_availability`, `lg_update_driver_position`, `lg_create_pickup_task`, `lg_create_delivery`,
`lg_rank_drivers`, `lg_auto_assign_task`, `lg_auto_assign_day`, `lg_assign_task`, `lg_accept_task`, `lg_refuse_task`, `lg_start_task`, `lg_complete_pickup`, `lg_complete_delivery`,
`lg_fail_task`, `lg_reschedule_task`, `lg_cancel_task`, `lg_issue_delivery_otp`, `lg_deliver_without_proof`, `lg_create_trip`, `lg_start_trip`, `lg_complete_trip`, `lg_my_tasks`, `lg_task_board`.
Toutes les tables du schéma `logistics` restent **fermées** (RLS active, aucun accès direct) ; aucune façade n'est ouverte à l'anonyme ; aucune fonction interne n'est appelable par un compte connecté.

## 10. Événements ajoutés
`PickupRequested`, `PickupCompleted`, `DeliveryCreated`, `TaskAssigned`, `TaskAccepted`, `TaskRefused`, `TaskReassigned`, `TaskStarted`, `TaskCompleted`, `TaskFailed`, `TaskCancelled`,
`TaskRescheduled`, `TripCreated`, `TripStarted`, `TripCompleted`, `DeliveryOtpIssued`, `ParcelReturnedToHub` — et ceux de la phase 6 (`DeliveryAssigned`, `OutForDelivery`, `Delivered`),
`ProofOfDeliveryCreated` et `IncidentCreated`. Ils passent par l'outbox transactionnel (`EVENT-ENGINE.md`) : nouvelle tentative, dead-letter, corrélation.
La simple position GPS **ne produit pas d'événement** (trop bavard).

## 11. Risques et points ouverts
- **Fichiers de preuve** : la base ne conserve que les **chemins** (`pod/<mission>/…`). Le stockage (bucket privé Supabase) et ses règles d'accès restent à créer ; tant qu'il n'existe
  pas, la signature et la photo ne sont pas téléversables depuis l'application.
- **Code de livraison** : l'empreinte est salée, mais le code **en clair** vit dans `notification.payload` jusqu'à l'envoi. Le service d'envoi doit le **purger une fois envoyé** (à écrire avec lui).
- **Messagerie** : aucun envoi n'est branché (WhatsApp, SMS) ; la notification est seulement **enregistrée**.
- **Application mobile** : aucun écran « chauffeur » n'existe encore ; les façades sont prêtes, l'écran reste à faire.
- **Fuseau** : les journées sont comptées à l'heure d'Haïti ; un chauffeur en République dominicaine ou en Floride verrait ses créneaux décalés d'une heure par endroits.
- **Rien n'est appliqué en production** : procédure habituelle (sauvegarde vérifiée, projet `speed-express-site` ouvert en haut du SQL Editor, 001 à 006 dans l'ordre).

## 12. Retour arrière
Au bas du fichier `006` : retirer les fonctions `public.lg_*` de l'étape, supprimer les tables de l'étape, rétablir `guard_parcel_status()` et `actor_can()` de la migration 003, retirer les trois
transitions ajoutées et remettre `required_right = 'colis.statut'` sur les deux transitions de livraison. **Aucune donnée de l'ancien schéma n'est en jeu.**
