## Ce que ça change pour l'utilisateur

<!-- Une ou deux phrases, en français, du point de vue d'un client ou de l'équipe. -->

## Nature (une seule par PR, autant que possible)

- [ ] **Migration SQL** (`outils/*.sql`, `outils/logistique/*.sql`) — la fusion ne l'applique PAS : collage à la main, après sauvegarde, d'abord en préproduction
- [ ] **Site** (pages, scripts, styles) — publié dès la fusion, après votre approbation du déploiement
- [ ] **Préproduction / surveillance / outillage** (`outils/staging`, `scripts/`, `outils/tests`)
- [ ] **Documentation**
- [ ] L'application mobile vit dans son propre dépôt (`speed-express-app`) : rien ici

## Preuves

- [ ] `SES_TEST_DEPS=… SES_PG_BIN=… bash outils/tests/verifier.sh` vert en local (la CI le refait)
- [ ] `python3 outils/mise-en-page.py` relancé : « 0 modifiées »
- [ ] Fichiers servis modifiés → `python3 outils/versionner.py`
- [ ] Texte visible ajouté → traductions (`lang-dict*.js`) et `traductions-couverture.py`

## Migration : à remplir seulement si la PR en contient une

- Fichier(s) et ordre de collage :
- Requête de contrôle à lancer après coup (elle lit le catalogue ou les données, pas seulement « Success ») :
- Retour en arrière :
- Passée en préproduction le :

## Risques et état de la production

<!-- Ce qui peut casser, pour qui ; ce qui est déjà en production et ce qui ne l'est pas. -->
