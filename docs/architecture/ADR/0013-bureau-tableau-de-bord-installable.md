# ADR 0013 — Le bureau Windows et macOS : le tableau de bord installable et un poste de scan, sans Tauri ni Electron
**Statut :** Proposée (6 octobre 2026). Applique l'[ADR 0005](0005-applications-operations-expo-et-bureau-web.md) §3, sans la remplacer.

## Contexte
La phase 15 demande une application de bureau Windows et macOS (« Tauri ou technologie validée dans l'architecture cible ») avec scanner
USB, imprimantes, fichiers et notifications, la logique restant dans le noyau. L'ADR 0005 a validé le **navigateur** pour le bureau et
écarté Electron et Tauri « tant qu'un besoin matériel ne l'impose ». Constat au 6 octobre 2026 :
- un scanner USB ou Bluetooth de codes-barres est un **clavier** (HID) : le navigateur le lit sans pilote (`ses-scanner.js`, phase 7) ;
- les imprimantes d'étiquettes vendues avec un pilote système (Zebra, Brother, Dymo, Rollo…) impriment ce que le navigateur leur envoie
  au format de la page ; le tableau de bord imprime déjà l'étiquette 4 × 6 avec son code QR et la facture (`ses-ui.js`) ;
- fichiers : le navigateur lit un fichier choisi et en télécharge un, sans accès au reste du disque ;
- notifications : l'API Notifications des navigateurs de bureau, sur permission explicite ;
- installation : Chrome et Edge (Windows, macOS) installent une page munie d'un manifeste dans sa propre fenêtre ; Safari 17+ (macOS) l'ajoute
  au Dock ;
- Rust n'est pas installé sur ce poste ; Tauri ajouterait une chaîne de compilation, une signature de code par système et des mises à jour
  à publier, pour ne rien faire de plus que ce qui précède.

## Décision
1. **L'application de bureau est le tableau de bord du site, installable** : un manifeste (`tableau-de-bord.webmanifest`, fenêtre à part,
   icônes faites des logos du site) et rien d'autre. **Pas de service worker** : il garderait en cache d'anciennes versions des scripts,
   alors que le numéro `?v=` doit toujours l'emporter ; un poste sans réseau ne peut de toute façon pas joindre la base, seule à décider.
2. **Le poste de scan** est une section du centre de commande (`assets/js/ses-poste.js`) : entrepôt et intention, scanner USB lu partout
   dans la page tant que le poste est affiché (et plus du tout ailleurs), saisie à la main, verdict de la base en grand et en couleur (plus un
   son, réglable, en cas de refus), étiquette du colis (le gabarit existant), bordereau de la session imprimé, export CSV (sans formule
   possible), import d'une liste de numéros (un en-tête ou un texte sans chiffre ne part jamais : un code inconnu ouvre un incident),
   notifications du système quand l'onglet est caché (une phrase sans donnée, au plus une par minute, sur le signal de la phase 13).
3. **La logique reste dans le noyau** : profil par `lg_my_staff_profile` (011), chaque lecture par `lg_scan_parcel` (004) avec une clé
   d'idempotence par lecture (« Réessayer » renvoie la même) et `source: desktop`. Aucune nouvelle fonction SQL.
4. Le poste s'ouvre sur le droit « opérations » que la base annonce déjà (`lg_cc_access`) ; il ne propose pas le rangement ni le
   déplacement, qui exigent un emplacement.
5. **Tauri reste la voie de sortie**, sans rien réécrire : il envelopperait ces mêmes pages le jour où un besoin le prouve (voir plus bas).

## Conséquences
+ rien à compiler, signer ni distribuer ; une seule version, mise à jour à chaque publication du site ;
+ Windows et macOS identiques ; un poste de scan qui marche aussi sur une tablette ;
+ le `ScannerService` est maintenant servi (`assets/js/ses-scanner.js`) : la même lecture au bureau et dans l'application mobile ;
− pas de travail hors connexion au bureau (une lecture « pas partie » se renvoie à la main, avec la même clé) ;
− impression : le navigateur passe par la boîte d'impression du système (un clic de plus) ; pas d'impression brute (ZPL) ;
− notifications : seulement tant que la fenêtre ou l'onglet est ouvert.

## Alternatives écartées
Tauri dès maintenant (chaîne Rust absente, signature et mises à jour à gérer, aucun besoin démontré) ; Electron (même coût, et un
navigateur entier embarqué) ; un service worker hors connexion (risque de servir de vieux scripts, alors que la base doit décider en direct).

## Quand la réexaminer
Une imprimante qui n'accepte que des commandes brutes (ZPL/EPL) ou une impression sans boîte de dialogue ; une balance ou un lecteur RFID
reliés en série ; un entrepôt qui doit scanner sans réseau pendant des heures. Alors : une enveloppe Tauri autour de ces pages, ses
adaptateurs branchés sur le même `ScannerService`, après une nouvelle ADR.
