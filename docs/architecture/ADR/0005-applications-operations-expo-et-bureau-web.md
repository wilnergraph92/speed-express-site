# ADR 0005 — Deux applications Expo ; le bureau est un navigateur
**Statut :** Proposée (5 octobre 2026)

## Contexte
Entrepôt et chauffeurs ont besoin de scanner, photographier, signer et travailler hors connexion ; le
personnel de bureau a besoin d'écrans larges et de scanners USB. L'application client existante est en Expo.

## Décision
1. **Application client** : inchangée (suivi, factures, profil).
2. **Application « Opérations »** (nouvelle) : entrepôt **et** chauffeur, **rôle par rôle**, en Expo/React Native — même technologie, compétences communes. Séparée de l'application client : les fonctions du personnel ne partent pas dans une application que tout client installe.
3. **Bureau** : **export web** de l'application Opérations (navigateur). Un scanner USB envoie des touches comme un clavier : le navigateur suffit. **Pas d'Electron/Tauri** tant qu'un besoin matériel (imprimante d'étiquettes, périphérique) ne l'impose.
4. Les scanners sont masqués derrière une **abstraction** (`ScannerService`) : le métier reçoit un « code lu », jamais « la caméra » ou « l'USB ».

## Conséquences
+ une base de code pour mobile et bureau ; surface d'attaque client réduite ;
− deux fiches de magasin à gérer (Apple, Google) ; distribution privée possible pour l'application Opérations.

## Alternatives écartées
Un seul binaire pour tous (mélange clients et personnel) ; application native bureau d'emblée (coût sans besoin démontré).

## Quand la réexaminer
Si une imprimante ou un périphérique impose un pilote natif de bureau.
