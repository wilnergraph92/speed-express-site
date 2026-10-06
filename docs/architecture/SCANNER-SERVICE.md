# ScannerService : une abstraction pour tous les lecteurs

> Phase 7. Source : `assets/js/ses-scanner.js` (ES5, sans dépendance, servi au poste de scan du bureau depuis la phase 15) ; preuve : `outils/tests/scanner.cjs` (28 vérifications).
> **Le moteur métier ne dépend pas du type de scanner** : il reçoit un texte, un genre et un appareil.

## 1. Pourquoi
Caméra du téléphone, QR, code-barres, scanner USB, poste de bureau, saisie à la main : cinq façons de lire, un seul métier. Si le métier connaissait le lecteur,
chaque nouveau matériel exigerait de modifier la base et les écrans. Ici, brancher un lecteur = écrire un **adaptateur** de trois lignes.

## 2. Le contrat
Un **adaptateur** : `{ nom, demarrer(emettre), arreter() }`. Quand il lit quelque chose : `emettre(texte, genre)`.
Le **service** (`creerService`) : nettoie le texte, **supprime les rebonds** (une caméra voit le même QR sur 20 images : une seule lecture, tous lecteurs confondus,
fenêtre de 1,5 s), isole les erreurs (un abonné ou un lecteur défaillant n'arrête pas les autres), et rend une **lecture** :
`{ code, genre, source, appareilId, horodatage }`.

## 3. Les adaptateurs fournis
| Adaptateur | Lecteur | Particularité |
|---|---|---|
| `adaptateurClavier(cible)` | scanner USB / Bluetooth (se comporte comme un **clavier**), poste de bureau | une **rafale** (≤ 50 ms entre touches) terminée par Entrée ou Tab = un scan ; une **frappe humaine** (≥ 80 ms) n'en est **jamais** un |
| `adaptateurCamera(detecteur)` | caméra du téléphone ou du navigateur | le « détecteur » (`BarcodeDetector`, caméra d'Expo) rend `{ rawValue, format }` ; `qr_code` → genre `qr`, le reste → `barcode` |
| `service.soumettre(texte)` | saisie à la main | même chemin, genre `manual` |
| `adaptateurProgrammable(nom, genre)` | RFID, futur matériel, tests | on le pilote par `lire(texte)` |

## 4. Du lecteur à la base
```js
var service = SES_SCANNER.creerService({ appareilId: monAppareil })      // appareilId : ligne de logistics.device
  .ajouterAdaptateur(SES_SCANNER.adaptateurClavier(document))
  .ajouterAdaptateur(SES_SCANNER.adaptateurCamera(new BarcodeDetector()));
service.surLecture(function (lecture) {
  var args = SES_SCANNER.argumentsRpc(lecture, { intention: 'receive', entrepotId: entrepot.id });
  supabase.rpc('lg_scan_parcel', args).then(afficherResultat);          // ACCEPTED, DUPLICATE, WRONG_WAREHOUSE…
});
service.demarrer();
```
`argumentsRpc` fabrique les paramètres de `public.lg_scan_parcel` **identiques quel que soit le lecteur**, avec une **clé d'idempotence déduite de la lecture** : si le réseau coupe et que l'application renvoie la même lecture, la base ne la compte pas deux fois.

## 5. Matériel : ce qui est vérifié, ce qui ne l'est pas
**Vérifié** (faux lecteurs, horloge simulée) : la logique de rafale, de rebond, de multiplexage, d'isolation d'erreur, de clé d'idempotence.
**Pas vérifié** : un vrai scanner (préfixe/suffixe configurés différemment, disposition AZERTY/QWERTY du clavier, vitesse réelle), une vraie caméra (éclairage, étiquettes
abîmées, `BarcodeDetector` absent de certains navigateurs). **À essayer avec le matériel acheté**, en réglant `delaiMaxMs` et `terminateurs` si besoin.
Conseils : choisir un scanner **configurable en mode « clavier US »** avec suffixe Entrée ; vérifier qu'il lit le **Code 128** (format des étiquettes).
