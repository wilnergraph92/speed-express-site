# ADR 0016 — Speed Express Operations : une enveloppe Tauri 2 autour du tableau de bord
**Statut :** Acceptée (14 octobre 2026), à la demande du propriétaire (phase 10). Remplace l'[ADR 0013](0013-bureau-tableau-de-bord-installable.md)
sur un point : l'application de bureau n'est plus SEULEMENT le tableau de bord installable par le navigateur. Le tableau de bord
installable reste valable et inchangé.

## Contexte
L'ADR 0013 avait écarté Tauri « tant qu'un besoin matériel ne l'impose », et listé ce qui la ferait réexaminer : une imprimante qui
n'accepte que des commandes brutes (ZPL) ou une impression sans boîte de dialogue, un entrepôt qui doit scanner sans réseau, une
application à installer, signer et mettre à jour. Le propriétaire demande maintenant exactement cela :
- une application « Speed Express Operations » installée sur Windows et macOS, avec installateur, DMG, signature, versions, mises à
  jour, canaux stable et bêta ;
- l'étiquette 4 × 6 sur une imprimante thermique, l'A4 et le PDF ;
- le scanner USB, la caméra, la saisie ;
- une file d'opérations quand le réseau manque ;
- les mêmes appels à la base que le site et les applications mobiles, et aucun secret dans l'application.

## Décision
1. **Une enveloppe Tauri 2 autour des pages existantes**, pas une nouvelle application. `bureau/preparer.mjs` copie dans l'application
   exactement ce que le site publie (les exclusions de `deploy.yml`), et la fenêtre s'ouvre sur `tableau-de-bord.html`. Ce sont donc les
   mêmes écrans, les mêmes scripts et les mêmes `lg_*` : rien n'est réécrit, et rien ne peut diverger.
2. **Les pages sont embarquées, pas chargées depuis le site.** L'application démarre sans réseau, ce qui est nécessaire à la file hors
   ligne. Une version de l'application correspond à une version du site, et les mises à jour la gardent à jour. Une adresse distante aurait
   donné à une page du web l'accès aux commandes de l'enveloppe ; ici, aucune page distante n'y a accès.
3. **Le pont est un seul fichier, `assets/js/ses-bureau.js`**, inactif dans un navigateur. Il reste dans les pages du site pour être
   éprouvé avec elles (`bureau-contrat.cjs`).
4. **Rust n'ajoute que sept commandes étroites** (`bureau/src-tauri/src/lib.rs`) :
   - `imprimer` : la boîte d'impression de macOS ; sous Windows, WebView2 ouvre la sienne ;
   - `imprimantes` : les imprimantes du poste ;
   - `imprimer_brut` : l'étiquette ZPL, vers une imprimante déclarée par le système seulement ;
   - `ouvrir_lien` : https, mailto ou tel, dans le navigateur du système ;
   - `infos` ;
   - les deux commandes de mise à jour.

   La fenêtre ne navigue que dans ses pages. Elle n'a qu'une capacité, `core:default` : ni shell, ni fichiers, ni réseau ouverts à la page.
5. **L'étiquette thermique est un gabarit ZPL** (`SES_UI.zplEtiquette`), écrit à côté de l'étiquette HTML. Il porte les mêmes informations,
   le même Code 128 et le même QR. `^` et `~` sont neutralisés : un texte saisi ne peut glisser aucune commande. L'A4 et le PDF passent par
   la boîte d'impression du système, comme avant (« Enregistrer en PDF » sur macOS, « Microsoft Print to PDF » sous Windows). Une
   imprimante thermique qui refuse l'étiquette laisse la main à la boîte du système.
6. **La file hors ligne vit dans le poste de scan** (`ses-poste.js`), pour le site comme pour l'application :
   - elle ne garde que les gestes qui peuvent attendre (réception, contrôle, consolidation, chargement, départ, inventaire), jamais
     « consulter » ;
   - chaque lecture garde SA clé d'idempotence et l'heure du poste (`recorded_at`, et `queued` au rejeu) ; la base ne la compte jamais
     deux fois ;
   - la file appartient au compte connecté : un autre compte ne la renvoie pas en son nom ;
   - un refus de la base au rejeu sort la lecture de la file et reste affiché.

   Les autres gestes (expédier, encaisser, livrer…) exigent la base en direct, qui seule décide.
7. **Aucun secret dans l'application.** Elle ne connaît que la clé PUBLIQUE de Supabase (`config.js`), comme le site.
   - `preparer.mjs` arrête la construction si un secret se trouvait dans les pages.
   - La clé privée des mises à jour et les certificats ne vivent que dans les secrets du dépôt.
   - Aucune clé de paiement n'approche le poste : les paiements passent par le serveur (FINANCE.md).
8. **Construction sur GitHub Actions**, Windows et macOS, essais Rust compris, en deux temps :
   - le dépôt PUBLIC (`.github/workflows/bureau.yml`) construit et éprouve, sans aucun secret ; il produit des installateurs d'essai
     non signés ;
   - un dépôt PRIVÉ (modèle `scripts/bureau/modele-workflow-publication.yml`) signe (Developer ID et notarisation, Authenticode),
     publie dans le dépôt du site et tient les deux canaux : `bureau-vX.Y.Z` pour le stable, `bureau-beta-vX.Y.Z` pour la bêta. Le
     manifeste de chaque canal est recopié dans une version fixe (`bureau-canal-stable`, `bureau-canal-beta`).

   La signature et les mises à jour signées s'activent d'elles-mêmes quand les secrets existent.

## Conséquences
+ un seul code pour le site et le bureau ; la base décide toujours ; les mêmes essais couvrent les deux ;
+ l'impression thermique sans boîte de dialogue ; la file hors ligne du poste de scan, au site aussi ;
+ une application qui se met à jour seule, avec une signature vérifiée avant toute installation ;
− une chaîne de construction de plus (Rust, sur GitHub Actions ; rien n'est installé sur le poste du propriétaire) ;
− des certificats à acheter et à renouveler : Apple Developer (99 $ par an, déjà utile pour iOS) et un certificat de signature de code
  Windows. Sans eux, l'application s'installe quand même, mais macOS et Windows avertissent l'utilisateur ;
− la caméra dans WebKit (macOS) dépend de la version du système : à vérifier à la recette, le scanner USB et la saisie restant là.

## Alternatives écartées
- **Charger le site distant dans la fenêtre** : pas de démarrage hors ligne, et une page du web aurait eu accès à l'enveloppe.
- **Electron** : un navigateur entier embarqué, pour le même résultat.
- **Une application native réécrite** : deux codes à tenir, alors que les écrans existent et sont éprouvés.
- **Le pilote d'imprimante seul** (ADR 0013) : il reste le repli. Il ne permet ni le ZPL ni l'impression sans boîte de dialogue.
