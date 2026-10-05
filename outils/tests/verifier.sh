#!/usr/bin/env bash
# Suite légère, reproductible localement et avant toute publication.
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 outils/tests/qualite-static.py
node outils/tests/i18n.cjs
python3 outils/tests/dashboard-static.py
python3 outils/tests/performance-static.py
python3 outils/tests/seo-static.py
python3 outils/tests/accessibilite-static.py
node outils/tests/dashboard-api.cjs
node outils/tests/roles-api.cjs
# Les tests sur un vrai PostgreSQL (WASM) ont besoin d'un dossier qui contient
# @electric-sql/pglite : SES_TEST_DEPS=/chemin/vers/ce/dossier bash outils/tests/verifier.sh
if [ -n "${SES_TEST_DEPS:-}" ]; then node outils/tests/roles-sql.cjs; fi
