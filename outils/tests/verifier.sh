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
