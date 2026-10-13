# Applications mobiles : client et « SES Opérations » (phase 14)

> Statut : écrit et vérifié sans appareil ; **migration 011 non appliquée en production** ; **jamais essayé sur un téléphone réel**.
> Décision : [ADR 0012](ADR/0012-une-base-de-code-deux-applications.md) (précise l'ADR 0005). Code : dépôt privé `App_SES`.
> Base : `outils/logistique/011-applications.sql`.

## 1. Deux applications, un dépôt

| | Client | SES Opérations |
|---|---|---|
| Construite par | `npx expo …` | `APP_VARIANT=operations npx expo …` |
| Identifiants | `com.speedexpressshipping.app` | `com.speedexpressshipping.operations` |
| Racine des écrans | `src/app` | `src/app-operations` |
| Comptes acceptés | clients seulement | équipe seulement |
| Caméra, position | bloquées (Android), « n'utilise pas » (iOS) | caméra ; position pendant l'utilisation, jamais en arrière-plan |

Le paquet client ne contient aucun écran ni module de l'équipe : `tests/variantes.cjs` suit ses imports, et un empaquetage Metro réel des
deux variantes (6 octobre 2026) le confirme — `lg_mobile_command` et la caméra n'apparaissent que dans le paquet « Opérations ».

## 2. Profils → onglets

`lg_my_staff_profile()` décide ; l'application affiche.

| Profil | Condition (base) | Onglet |
|---|---|---|
| `DRIVER` | fiche chauffeur `ACTIVE` liée au compte | Missions |
| `WAREHOUSE_AGENT` | droit `colis.statut`, succursale qui n'est pas un hub (ou aucune) | Scanner |
| `DELIVERY_AGENT` | droit `colis.statut`, succursale hub ou agence (ou aucune) | Tournées |
| `CUSTOMER` | compte client | aucun : refusé, renvoyé vers l'application client |

Tout profil ouvre aussi « Synchro ». Un compte désactivé n'est plus membre de l'équipe.

## 3. Ce qui passe par où

| Geste | Chemin | Hors connexion |
|---|---|---|
| lire ses missions, le tableau des tournées, classer les chauffeurs | `lg_my_tasks`, `lg_task_board`, `lg_rank_drivers` | non (relu au retour) |
| attribuer, attribuer automatiquement, émettre le code | `lg_assign_task`, `lg_auto_assign_task`, `lg_issue_delivery_otp` | **non**, volontairement |
| accepter, refuser, commencer, livrer, échouer, enlever, scanner, signaler, position | `lg_mobile_command(clé, commande, arguments)` | **oui** : file chiffrée, clé par geste |

Rejeu : même clé → résultat d'origine (`replayed: true`) ; même clé pour un autre geste → `LG006` ; refus (`LG001`–`LG005`, `42501`) → la clé
n'est pas consommée, la file classe le geste « conflit » (la situation a changé) ou « refusé » (droit, donnée) et ne le rejoue jamais seule.
Un mauvais code de livraison est un **résultat** (`completed: false, reason: OTP_INVALID`), compté contre le devinage ; ressaisir le code
crée un nouveau geste.

Preuve : photo déposée dans le dossier privé `preuves` sous `pod/<mission>/<clé>.jpg` (règle `ses_preuves_depot` : dépôt par un chauffeur
actif seulement, aucune lecture ni suppression depuis un téléphone).

Temps réel : `public.ses_signal` (audience `staff`, sujets `task`, `delivery`, `parcel`, `scan`, `pickup`, `trip`) → l'application relit ;
aucune donnée ne voyage par le signal.

## 3 bis. Phase 9 : le terrain (étape 021)

**Les modules, par profil** (l'écran propose, la base permet — `src/operations/geste.ts` ne lit jamais un rôle) :

| Profil | Modules | Écrans |
|---|---|---|
| `DRIVER` | missions, tournée, carte, navigation, arrêt, appel client, code (OTP), signature, photo, incident, livraison | Missions, `tournee/[id]`, `mission/[id]` (remise) |
| `WAREHOUSE_AGENT` | scanner (codes-barres, QR, saisie), réception, vérification, emplacement, transfert, consolidation, sortie, départ, inventaire, consultation | Scanner |
| `DELIVERY_AGENT` (et responsables) | tournées, arrêts, colis, livraison (attribution, code), échec, replanification, preuve (POD) | Tournées, `tournee/[id]`, `preuve/[id]` |

Un agent de livraison qui remet lui-même un colis a une fiche chauffeur : c'est la base qui en décide (`complete_delivery` exige le
chauffeur de la mission, la règle de dépôt des preuves un chauffeur actif).

**Quatre gestes de plus par la porte unique**, tous en file hors connexion : `arrive_stop` (l'heure du téléphone, bornée ; la position de
CE moment ; une deuxième arrivée ne change rien), `start_trip`, `complete_trip`, `reschedule_task` (aujourd'hui à soixante jours, droit
`colis.statut`). **Deux lectures** : `lg_task_proof` (la preuve d'une livraison, sans jamais le chemin des fichiers) et
`lg_warehouse_locations` (les emplacements actifs, pour ranger et transférer — on choisit dans la liste ou on scanne l'étiquette de l'étagère).

**Les trois règles de la file**, éprouvées sur PostgreSQL (`logistique-terrain-essai.py`) et dans l'application (`tests/terrain.cjs`) :
même commande rejouée → résultat d'origine (`replayed: true`), rien de fait deux fois ; ordre incorrect → `LG001`, classé « conflit » ;
permission incorrecte → `LG003`, classé « refusé », clé non consommée. Ni un conflit ni un refus n'est rejoué tout seul.

**La file est chiffrée** (trousseau du téléphone, `AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY`) : elle peut contenir un code de livraison.

**Le GPS** n'est lu qu'au moment d'un geste du métier — arrivée, remise (exigée par la base), échec, incident (`src/operations/position.ts`,
une seule lecture). Le suivi continu pendant une mission (phase 14) est **retiré** : aucun `watchPositionAsync`, aucun mode arrière-plan.

**La signature** se dessine au doigt et part en SVG (`pod/<mission>/<clé>-signature.svg`), la photo en JPEG (`pod/<mission>/<clé>.jpg`) :
adresses liées à la clé du geste, un nouvel essai réécrit au même endroit.

**La carte** : l'application de cartes du téléphone (Plans, Google Maps) ouvre la tournée et chaque arrêt — aucune clé d'API. Une carte
DANS l'application demanderait une clé Google Maps pour Android : une décision à prendre, pas un manque.

**L'écran Synchro** : connexion, dernière synchronisation, opérations en attente, erreurs (refus), conflits, envoyées.

## 4. Vérifications

| Où | Fichier | Ce qu'il prouve |
|---|---|---|
| site | `outils/tests/logistique-applications-essai.py` (PostgreSQL jetable, 70) | profils, porte unique, idempotence, refus sans clé consommée, code invalide, position jamais en arrière, preuve et photo, droits avec les privilèges par défaut de Supabase ; écrit `applications-rpc.json` et `applications-formes.json` |
| site | mutations de 011 (27) | toutes détectées |
| app | `tests/operations.cjs` (30) | lecteur de codes, profils → onglets, file hors connexion |
| app | `tests/contrat-rpc.cjs` (77) | fonctions, paramètres, types TypeScript = formes réelles, gestes, intentions, motifs |
| app | `tests/textes-operations.cjs` (1240) | quatre langues complètes, chaque clé des écrans, chaque statut et verdict de la base |
| app | `tests/variantes.cjs` (22) | identifiants, permissions, racines, isolation du paquet client |
| app | `tsc --noEmit`, `expo lint` | types et règles React (aucune erreur dans le code de l'équipe) |

## 5. Ce qui reste à faire avant de s'en servir

(Phase 9 : voir aussi la liste d'essais sur appareils réels, `App_SES/docs/ESSAIS-APPAREILS.md`.)


1. Passer 001 à 011 en production, après sauvegarde vérifiée (geste du propriétaire).
2. Créer une fiche chauffeur pour chaque chauffeur (`lg_create_driver`), rattacher les membres à leur succursale.
3. **Essayer sur un Android et un iPhone réels** : connexion, scan d'une vraie étiquette, photo, refus de la caméra puis autorisation,
   mode avion pendant une livraison puis retour du réseau, deux téléphones sur la même mission.
4. Fiches de magasin : distribution privée recommandée pour « Opérations ».

## 7. Retour en arrière (étape 021)

Ne **jamais** rejouer 017 après 021 (une étape ancienne ne se rejoue pas après une plus récente). Les quatre gestes ajoutés ne servent qu'aux
téléphones de l'équipe : les laisser. Fermer les deux lectures : `revoke execute on function public.lg_task_proof(uuid),
public.lg_warehouse_locations(uuid) from authenticated;`. Côté application, une version précédente (EAS Update) n'envoie plus ces gestes.
