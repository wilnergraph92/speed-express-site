# Entrepôt : réception, vérification, rangement, mouvements

> Phase 7. Source : `outils/logistique/004-entrepot.sql` ; preuve : `outils/tests/logistique-entrepot-essai.py` (100 vérifications)
> et `outils/tests/scanner.cjs` (28). **Non appliqué en production.**

## 1. Le flux
```
 CREATED ──scan « receive »──▶ RECEIVED ──inspection──▶ VERIFIED ──scan « store »──▶ STORED ──scan « consolidate »──▶ CONSOLIDATION_PENDING
                                  │                        (poids, dimensions, état, photos)     └──scan « move » : déplacement dans l'entrepôt
                                  ├── état « endommagé » ─▶ DAMAGED  (+ incident HAUT)  ──▶ « move » vers la quarantaine seulement
                                  └── objet interdit ──────▶ ON_HOLD  (+ incident HAUT, colis marqué interdit)
```
Zones et emplacements (`warehouse_zone`, `warehouse_location`) : réception, rayonnage, regroupement, expédition, quarantaine, endommagés.

## 2. Un seul point d'entrée : le scan
`public.lg_scan_parcel(code, intention, entrepôt, emplacement, appareil, genre, clé)`. **L'acteur est toujours le compte connecté.**
Le métier reçoit un **texte** : il ne sait pas si c'est une caméra, un QR, un code-barres, un scanner USB ou une saisie à la main.
`parse_code` lit tous les cas : `SES-10001-HT`, `ses-10001-ht ` (saisie), ou l'adresse d'un QR (`…suivi.html?colis=…&j=…`, qui donne le numéro **et** le jeton).

Intentions : `receive`, `verify`, `store`, `move`, `consolidate`, `dispatch`, `lookup` (consulter sans rien changer).

## 3. Les résultats d'un scan (un refus est un résultat, pas une panne)
| Résultat | Quand | Effet |
|---|---|---|
| `ACCEPTED` | l'intention est possible | la transition ou le mouvement a lieu |
| `UNKNOWN_PARCEL` | numéro inconnu | scan tracé ; **incident** (une seule fois par code et par entrepôt) |
| `INVALID_CODE` | numéro connu, **jeton faux** | **étiquette falsifiée** : incident de gravité HAUTE, colis intact |
| `DUPLICATE` | déjà fait (déjà reçu, déjà rangé là…) | rien |
| `WRONG_WAREHOUSE` | le colis est dans un autre entrepôt | rien |
| `ALREADY_DISPATCHED` | le colis est parti (transit, livré, retourné…) | rien |
| `DAMAGED` | colis endommagé : ni rangement, ni consolidation, ni expédition (il va en **quarantaine**) | rien |
| `PROHIBITED` | colis marqué interdit | rien ; **incident HAUT** ; on peut le **consulter** |
| `NO_CUSTOMER` | consolidation d'un colis **sans client** | refusé (il peut être **reçu**, avec incident « à rattacher ») |
| `WRONG_STATE` | statut incompatible avec l'intention (en attente, perdu, annulé, étape sautée) | rien |

Un scan **refusé ne change jamais le statut**. La décision est une fonction pure (`assess_scan`), éprouvée sur **5 040 combinaisons**
(statut × intention × interdit × client × entrepôt × emplacement) contre une spécification écrite à part.

## 4. L'inspection (vérification)
`public.lg_inspect_parcel(...)` : **poids** (obligatoire, 0–2000 lb), **dimensions** (les trois ou aucune), **état** (`GOOD`, `MINOR_DAMAGE`, `DAMAGED`),
**objet interdit** (avec motif), notes, **photos** (chemins). Elle enregistre le constat (en **ajout seul**), met à jour le colis (poids vérifié, **volume** calculé en pi³),
puis décide : `VERIFIED`, `DAMAGED` ou `ON_HOLD`. Un **écart de plus de 10 %** avec le poids déclaré est signalé (`WEIGHT_DIFFERS`) : la tarification (phase 10) **facture le poids vérifié** quand il existe (`FINANCE-ENGINE.md` §3).
**Photos** : on n'enregistre que le **chemin** d'un fichier d'un compartiment **privé** de Supabase Storage (`parcels/<colis>/<fichier>`), jamais une adresse publique ; un chemin qui sort du dossier du colis est refusé.

## 5. Ce que chaque scan enregistre
Le **colis**, l'**événement** de suivi (quand le statut change), l'**utilisateur**, l'**entrepôt**, l'**emplacement**, l'**heure**, l'**appareil**, le **genre de lecteur**, les **métadonnées** et la **corrélation**. En plus :
une trace d'audit (avant/après), un événement de domaine (`ParcelReceived`, `ParcelMoved`, `ParcelInspected`, `ScanRejected`, `IncidentCreated`…), et, pour les mouvements, une ligne `parcel_movement` (origine, destination, motif). Les tables `scan`, `parcel_inspection`, `parcel_movement` sont en **ajout seul**.

## 6. Droits et sécurité
- Il faut le droit **`colis.statut`** (employé), ou être gérant/administrateur. Un client, un compte désactivé, un employé sans droit : refusés (`LG003`) et **rien n'est enregistré**.
- **Succursale** : un employé rattaché à une succursale ne scanne que dans **ses** entrepôts.
- L'appareil doit être un **lecteur** (`phone_camera`, `usb_scanner`, `desktop_scanner`, `handheld_scanner`) : le téléphone d'un client n'en est pas un.
- **Idempotence** : même clé = même scan (réseau coupé, double appui) ; une clé réutilisée pour une autre demande est refusée (`LG006`).

## 7. Incidents
Types : dommage, objet interdit, colis inconnu, étiquette falsifiée, mauvais entrepôt, sans client, client absent, adresse incorrecte, refus, véhicule, paiement, autre.
Gravité basse / moyenne / haute ; statut ouvert → résolu ou annulé. **Jamais supprimé** ; **résolu par la direction**, avec une note obligatoire.

## 8. Limites assumées
- Le **transfert entre deux entrepôts** n'est pas modélisé (un colis ne change d'entrepôt qu'en quittant le circuit) ; à ajouter si le besoin apparaît.
- L'**expédition** (`dispatch`) n'identifie que le colis ; le départ est décidé par le service d'expédition (phase 8).
- Les **photos** : le téléversement vers Storage (compartiment privé, politique d'accès) est à créer avec l'application Opérations.
