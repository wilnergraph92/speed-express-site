#!/usr/bin/env bash
# Suite légère, reproductible localement et avant toute publication.
set -euo pipefail
cd "$(dirname "$0")/../.."
python3 outils/tests/qualite-static.py
python3 outils/tests/publication.py
python3 outils/tests/securite-statique.py
python3 outils/tests/sauvegarde-statique.py
node outils/tests/i18n.cjs
python3 outils/tests/traductions-couverture.py
python3 outils/tests/dashboard-static.py
python3 outils/tests/performance-static.py
python3 outils/tests/seo-static.py
python3 outils/tests/accessibilite-static.py
node outils/tests/dashboard-api.cjs
node outils/tests/roles-api.cjs
node outils/tests/scanner.cjs
node outils/tests/portail-contrat.cjs
node outils/tests/portail-textes.cjs
node outils/tests/centre-contrat.cjs
node outils/tests/centre-textes.cjs
node outils/tests/notifications-travailleur.cjs
node outils/tests/notifications-contrat.cjs
node outils/tests/poste-contrat.cjs
node outils/tests/analytique-contrat.cjs
node outils/tests/exploitation-contrat.cjs
node outils/tests/prealertes-contrat.cjs
node outils/tests/fenetres-tableau.cjs
node outils/tests/reglages.cjs
# Les tests sur un vrai PostgreSQL (WASM) ont besoin d'un dossier qui contient
# @electric-sql/pglite : SES_TEST_DEPS=/chemin/vers/ce/dossier bash outils/tests/verifier.sh
if [ -n "${SES_TEST_DEPS:-}" ]; then node outils/tests/roles-sql.cjs; node outils/tests/dashboard-sql.cjs; node outils/tests/numeros-colis.cjs; node outils/tests/prealertes-sql.cjs; node outils/tests/matricules-sql.cjs; fi
# La sauvegarde de bout en bout (chiffrement, restauration, validation, garde-fous) tourne sur un
# vrai PostgreSQL jetable : il faut un dossier de binaires (initdb, pg_ctl, postgres, psql, pg_dump,
# pg_restore) et `age` dans le PATH : SES_PG_BIN=/chemin/bin bash outils/tests/verifier.sh
if [ -n "${SES_PG_BIN:-}" ]; then python3 outils/tests/schema-rejouable.py; python3 outils/tests/securite-sql.py; python3 outils/tests/sauvegarde-essai.py; python3 outils/tests/logistique-essai.py; python3 outils/tests/logistique-machine-essai.py; python3 outils/tests/logistique-entrepot-essai.py; python3 outils/tests/logistique-transport-essai.py; python3 outils/tests/logistique-dernier-km-essai.py; python3 outils/tests/logistique-finance-essai.py; python3 outils/tests/logistique-portail-essai.py; python3 outils/tests/logistique-centre-essai.py; python3 outils/tests/logistique-notifications-essai.py; python3 outils/tests/logistique-applications-essai.py; python3 outils/tests/logistique-analytique-essai.py; python3 outils/tests/logistique-exploitation-essai.py; fi
