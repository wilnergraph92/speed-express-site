# Speed Express Operations — construire, signer, publier, mettre à jour, recetter

L'application de bureau de l'équipe, pour Windows et macOS (phase 10, [ADR 0016](../architecture/ADR/0016-bureau-tauri-autour-du-tableau-de-bord.md)).
C'est le tableau de bord du site dans sa propre fenêtre, avec en plus :
- l'impression directe de l'étiquette sur une imprimante thermique ;
- la file hors ligne du poste de scan ;
- les mises à jour.

| Où | Quoi |
|---|---|
| `bureau/src-tauri/` | l'enveloppe Tauri 2 : `tauri.conf.json`, `capabilities/`, `src/lib.rs` (les sept commandes), `src/impression.rs` et `impression-windows.ps1`, `src/majs.rs` |
| `bureau/preparer.mjs` | copie les pages publiées par le site dans `bureau/site/` (embarquées dans l'application), arrête tout si un secret s'y trouvait |
| `assets/js/ses-bureau.js` | le pont entre les pages et l'enveloppe, inactif dans un navigateur ; la section « Application de bureau » (module Scanner) |
| `assets/js/ses-ui.js` | `zplEtiquette` (l'étiquette 4 × 6 en ZPL) et `imprimerEtiquette` (ZPL ou boîte du système) |
| `assets/js/ses-poste.js` | la file hors ligne du poste de scan |
| `.github/workflows/bureau.yml` | dépôt PUBLIC, aucun secret : construction Windows et macOS, essais Rust et du script d'impression Windows, installateurs d'essai non signés |
| `scripts/bureau/modele-workflow-publication.yml` | MODÈLE à installer dans un dépôt PRIVÉ : signature, publication des versions, canaux stable et bêta, mises à jour signées |
| essais | `outils/tests/bureau-statique.py`, `bureau-contrat.cjs`, `poste-contrat.cjs` (file hors ligne) ; essais Rust dans le workflow |

## 1. Construire

Rien à installer sur un poste : les machines Windows et macOS de GitHub construisent.

- **Pour un essai** : Actions › « Application de bureau (essai) » › *Run workflow*. Les installateurs restent 14 jours dans les artefacts du lancement :
  - Windows : `…_x64-setup.exe` et `…_x64_en-US.msi` ;
  - macOS : `…_universal.dmg`, pour Apple Silicon et Intel.

  Toute PR qui touche l'application les construit aussi.
- **Sur un poste de développement** (facultatif), il faut Rust et Node :

```bash
cd bureau && npm ci && node preparer.mjs && npx tauri icon ../assets/img/app-512.png && npx tauri dev
```

## 2. Publier une version

Le dépôt du site est public : aucun de ses workflows ne lit de secret. La publication signée se fait donc depuis un dépôt PRIVÉ, comme la
sauvegarde et la migration.

**Une fois** :
1. copier `scripts/bureau/modele-workflow-publication.yml` dans le dépôt privé, sous `.github/workflows/publication-bureau.yml` ;
2. poser ses secrets (§3) ;
3. au minimum, `SES_SITE_PUBLICATION` : un jeton GitHub « fine-grained », limité au dépôt `speed-express-site`, avec le seul droit
   Contents: Read and write.

**À chaque version** :
1. poser une étiquette sur `main` du site, après la fusion :

| Étiquette | Canal | Version GitHub |
|---|---|---|
| `bureau-v1.0.0` | stable | version normale, marquée « latest » |
| `bureau-beta-v1.0.1` | bêta | préversion ; ne touche jamais le canal stable |

```bash
git tag bureau-beta-v1.0.1 && git push origin bureau-beta-v1.0.1
```

2. dans le dépôt privé, lancer Actions › « Publier l'application de bureau » › *Run workflow* avec cette étiquette.

Le numéro reste purement numérique : l'installateur MSI de Windows refuse « 1.0.1-beta ». Une bêta prend donc le numéro suivant.

Le workflow construit le site à cette étiquette, signe, publie les installateurs dans une version GitHub du site, puis recopie
`latest.json` dans `bureau-canal-beta` ou `bureau-canal-stable`. Les applications installées interrogent ces deux versions fixes :
**ne jamais les supprimer**.

## 3. Signer — ce que seul le propriétaire peut fournir

Sans signature, l'application s'installe quand même, mais le système avertit :
- macOS : « développeur non identifié » ; ouvrir par clic droit › Ouvrir, une fois ;
- Windows : SmartScreen ; cliquer sur « Informations complémentaires » › « Exécuter quand même ».

Les secrets se posent dans le **dépôt privé** de publication, Settings › Secrets and variables › Actions. Ne les envoyez jamais par
message.

| Pour | Secrets | D'où |
|---|---|---|
| publier dans le dépôt du site | `SES_SITE_PUBLICATION` | jeton « fine-grained » : dépôt speed-express-site, Contents: Read and write |
| macOS (Developer ID + notarisation) | `APPLE_CERTIFICATE` (le .p12 en base64), `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY` (« Developer ID Application: … (ÉQUIPE) »), `APPLE_ID`, `APPLE_PASSWORD` (mot de passe d'application, appleid.apple.com), `APPLE_TEAM_ID` | compte Apple Developer (le même que pour l'application iOS) |
| Windows (Authenticode) | `WINDOWS_CERTIFICATE` (le .pfx en base64), `WINDOWS_CERTIFICATE_PASSWORD` | un certificat de signature de code (OV ou EV) d'une autorité reconnue |
| Mises à jour signées | variable **publique** `BUREAU_CLE_PUBLIQUE_MAJ` ; secrets `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | `npx tauri signer generate -w ~/.tauri/ses-operations.key` sur VOTRE poste |

Les secrets sont lus à chaque construction. Dès qu'ils existent, la signature et les mises à jour s'activent, sans changer de code.
Le résumé du lancement dit ce qui a été signé.

**La clé privée des mises à jour** :
- gardez-en une copie hors ligne ;
- perdue, aucune mise à jour ne pourra plus être installée sur les postes existants (il faudrait réinstaller à la main) ;
- volée, quelqu'un pourrait signer une fausse version.

Elle ne va **jamais** dans Git ni dans un message.

## 4. Mettre à jour

Dans l'application : Scanner › « Application de bureau » ›
1. choisir le canal (stable, ou bêta pour un poste d'essai) ;
2. « Rechercher une mise à jour », puis « Installer et redémarrer ».

La mise à jour est téléchargée puis **vérifiée par sa signature avant d'être installée** : une signature fausse arrête tout.

## 5. Imprimer

- **Étiquette 4 × 6, imprimante thermique** : dans « Application de bureau », mode « Imprimante thermique directe (ZPL) », choisir
  l'imprimante, puis « Imprimer une étiquette d'essai ».
  - Une Zebra, ou toute imprimante qui comprend le ZPL, sort l'étiquette sans boîte de dialogue.
  - Si l'imprimante refuse ou est éteinte, la boîte du système prend le relais.
  - Une imprimante qui ne parle pas ZPL (Rollo, Dymo, Brother en mode pilote) : rester en mode « boîte du système » ; la page fait
    4 × 6 pouces (101,6 × 152,4 mm).
- **A4** (facture, bordereau) : la boîte d'impression du système, comme dans un navigateur.
- **PDF** : dans la même boîte, « Enregistrer en PDF » (macOS) ou « Microsoft Print to PDF » (Windows).

## 6. Hors connexion

Le poste de scan garde les lectures qui peuvent attendre (réception, contrôle, consolidation, chargement, départ, inventaire) quand le
réseau manque, et les renvoie seules à son retour.
- Un bandeau dit combien attendent ; « Envoyer maintenant » force l'envoi.
- La base ne compte jamais deux fois une lecture (même clé) et garde l'heure du poste.
- « Consulter », les expéditions, les encaissements et les livraisons exigent le réseau : c'est la base qui décide.
- La file appartient au compte connecté ; elle est plafonnée à 500 lectures.

## 7. Recette — à faire sur de vrais postes avant la première version stable

Les machines de GitHub construisent et lancent les essais. Ce tableau-ci ne peut se faire que sur des postes réels, avec le matériel :

| # | Poste | Vérifier | ✓ |
|---|---|---|---|
| 1 | Windows 11 | installer `setup.exe` ; l'application s'ouvre sur la connexion puis le tableau de bord ; un second lancement ramène la même fenêtre | |
| 2 | macOS récent (Apple Silicon et, si possible, Intel) | ouvrir le DMG, glisser dans Applications, lancer | |
| 3 | 1080p, 1440p, 4K (mise à l'échelle 100 %, 150 %, 200 %) | tableau de bord lisible, aucune barre horizontale, la fenêtre retrouve sa taille au relancement | |
| 4 | les deux | connexion, déconnexion ; un compte client est renvoyé (pas d'accès) | |
| 5 | scanner USB | Scanner › poste : une lecture sans clic, verdict de la base ; la saisie à la main | |
| 6 | caméra | « Caméra » au poste : un QR d'étiquette est lu (sinon, noter le système : le scanner USB reste la voie) | |
| 7 | imprimante thermique ZPL | « Imprimer une étiquette d'essai » en mode ZPL : l'étiquette sort, code-barres et QR lisibles par le scanner | |
| 8 | imprimante thermique en mode pilote | mode « boîte du système », format 4 × 6 : l'étiquette sort entière, sans marge | |
| 9 | imprimante A4 | une facture et le bordereau du poste ; « Enregistrer en PDF » | |
| 10 | hors ligne | couper le Wi-Fi, scanner 3 colis (« En attente du réseau »), fermer et rouvrir l'application, rétablir le réseau : les 3 partent seuls, une seule fois chacun | |
| 11 | lien externe | WhatsApp ou une adresse e-mail du site s'ouvre dans le navigateur ou la messagerie du système, pas dans l'application | |
| 12 | mise à jour | sur le canal bêta, publier `bureau-beta-v…` supérieur : « Rechercher », « Installer et redémarrer » | |

## 8. Retour en arrière

| Besoin | Geste |
|---|---|
| une version publiée pose problème | publier aussitôt une version supérieure qui corrige (les postes la prennent) ; en attendant, le tableau de bord du site reste utilisable dans un navigateur |
| couper les mises à jour | supprimer `latest.json` de la version `bureau-canal-…` (les postes ne trouvent plus rien), sans supprimer la version elle-même |
| ne plus utiliser l'application | désinstaller ; rien n'est perdu : les données sont dans la base, la file hors ligne se renvoie depuis le site sur le même poste et le même compte |
