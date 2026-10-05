#!/usr/bin/env bash
# Suite légère, reproductible localement et avant toute publication.
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 outils/tests/qualite-static.py
python3 outils/tests/publication.py
python3 outils/tests/sauvegarde-statique.py
node outils/tests/i18n.cjs
python3 outils/tests/traductions-couverture.py
python3 outils/tests/dashboard-static.py
python3 outils/tests/performance-static.py
python3 outils/tests/seo-static.py
python3 outils/tests/accessibilite-static.py
node outils/tests/dashboard-api.cjs
node outils/tests/roles-api.cjs
# Les tests sur un vrai PostgreSQL (WASM) ont besoin d'un dossier qui contient
# @electric-sql/pglite : SES_TEST_DEPS=/chemin/vers/ce/dossier bash outils/tests/verifier.sh
if [ -n "${SES_TEST_DEPS:-}" ]; then node outils/tests/roles-sql.cjs; fi
# La sauvegarde de bout en bout (chiffrement, restauration, validation, garde-fous) tourne sur un
# vrai PostgreSQL jetable : il faut un dossier de binaires (initdb, pg_ctl, postgres, psql, pg_dump,
# pg_restore) et `age` dans le PATH : SES_PG_BIN=/chemin/bin bash outils/tests/verifier.sh
if [ -n "${SES_PG_BIN:-}" ]; then python3 outils/tests/sauvegarde-essai.py; python3 outils/tests/logistique-essai.py; python3 outils/tests/logistique-machine-essai.py; fi
