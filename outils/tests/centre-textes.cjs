// Les textes du centre de commande : chaque valeur que la base peut renvoyer a un texte dans la page ET une traduction dans les trois autres langues.
//
// i18n.cjs vérifie les clés écrites en toutes lettres dans un appel t('c-…') ; il ne voit ni celles que le code construit (t('c-colis-' + statut))
// ni celles que les définitions de sections portent ({ t: 'c-col-numero' }, intro: 'c-flux-intro'). Un nouveau statut ajouté à la base, une
// nouvelle colonne, laisseraient un texte VIDE à l'écran, sans erreur. Les valeurs viennent de la vraie base (outils/tests/centre-enums.json,
// écrit par logistique-centre-essai.py).
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const ENUMS = JSON.parse(fs.readFileSync('outils/tests/centre-enums.json', 'utf8'));
const html = fs.readFileSync('tableau-de-bord.html', 'utf8');
const gabarit = {};
Array.from(html.matchAll(/<span data-t="([^"]+)">([^<]*)<\/span>/g)).forEach((m) => { gabarit[m[1]] = m[2].replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim(); });
const bac = { window: {} }; bac.window.SES_DICT = {};
['lang-dict.js', 'lang-dict-11.js'].forEach((f) => vm.runInNewContext(fs.readFileSync('assets/js/' + f, 'utf8'), bac));
const dict = bac.window.SES_DICT;
let n = 0;

function exiger(cle) {
  assert.ok(Object.prototype.hasOwnProperty.call(gabarit, cle), 'tableau-de-bord.html : texte absent pour la clé « ' + cle + ' » (l\'ajouter à outils/centre-textes.py, puis relancer ce script et outils/mise-en-page.py)'); n++;
  const fr = gabarit[cle].replace(/\s+/g, ' ');
  assert.ok(fr, 'texte vide pour « ' + cle + ' »');
  const tr = dict[fr.replace(/[‘’]/g, "'")];
  assert.ok(Array.isArray(tr) && tr.length === 3 && tr.every((x) => typeof x === 'string' && x.trim()), 'pas de traduction anglais/espagnol/créole pour « ' + fr + ' » (clé ' + cle + ')'); n++;
}

// 1. Chaque valeur que la base connaît a son nom.
const FAMILLES = { statut_colis: 'c-colis-', statut_expedition: 'c-exp-', statut_transport: 'c-trans-', statut_mission: 'c-miss-', statut_chauffeur: 'c-chauf-', statut_douane: 'c-dou-',
  type_incident: 'c-inc-', gravite_incident: 'c-grav-', statut_incident: 'c-incst-', statut_facture: 'c-fact-', genre_paiement: 'c-paie-', moyen_paiement: 'c-moyen-', statut_ticket: 'c-tk-',
  categorie_ticket: 'c-tkcat-', canal: 'c-canal-', statut_notification: 'c-nst-', role: 'c-role-', etape_demande: 'c-etape-', resultat_scan: 'c-scan-', but_scan: 'c-but-', service: 'c-svc-',
  type_succursale: 'c-bk-', etat_colis: 'c-etat-', a_traiter: 'c-att-', indicateur_operations: 'c-kpi-', indicateur_support: 'c-kpi-', section: 'c-sec-' };
Object.keys(FAMILLES).forEach((f) => { assert.ok(ENUMS[f] && ENUMS[f].length, 'famille absente de centre-enums.json : ' + f); ENUMS[f].forEach((v) => exiger(FAMILLES[f] + v)); });
ENUMS.indicateur_argent.filter((k) => k !== 'revenue_date').forEach((k) => exiger('c-kpi-' + k));
['revenue_period_usd', 'unpaid-detail'].forEach((k) => exiger('c-kpi-' + k));
['OPEN', 'CLOSED', 'CANCELLED'].forEach((s) => exiger('c-cons-' + s));
['core', 'legacy'].forEach((s) => exiger('c-aut-' + s));
['MORNING', 'AFTERNOON'].forEach((s) => exiger('c-creneau-' + s));
// Les valeurs de filtre qui ne sont pas des statuts de la base, mais que la base comprend (ACTIVE, UNPAID, INACTIVE).
['c-exp-ACTIVE', 'c-incst-ACTIVE', 'c-tk-ACTIVE', 'c-fact-UNPAID', 'c-role-INACTIVE', 'c-sec-rapports'].forEach(exiger);

// 2. Chaque clé écrite dans le code (colonnes, introductions, messages) a son texte. Une clé qui finit par « - » est un préfixe de famille.
const src = ['ses-centre.js', 'ses-centre-vues.js'].map((f) => fs.readFileSync('assets/js/' + f, 'utf8')).join('\n');
const litterales = new Set(Array.from(src.matchAll(/'(c-[a-z0-9_-]*[a-z0-9_])'/g)).map((m) => m[1]));
assert.ok(litterales.size > 150, 'trop peu de clés trouvées : ' + litterales.size); n++;
litterales.forEach(exiger);

// 3. Les listes de statuts proposées en filtre sont exactement celles de la base (plus les valeurs de regroupement que la base comprend).
const vues = fs.readFileSync('assets/js/ses-centre-vues.js', 'utf8');
const liste = (nom) => JSON.parse('[' + new RegExp('var ' + nom + ' = \\[([^\\]]+)\\];').exec(vues)[1].replace(/'/g, '"') + ']');
const egal = (a, b, msg) => { assert.deepEqual(Array.from(a).sort(), Array.from(b).sort(), msg); n++; };
egal(liste('STATUTS_COLIS'), ENUMS.statut_colis, 'les statuts de colis du filtre = ceux de la base');
egal(liste('STATUTS_EXPEDITION'), ENUMS.statut_expedition, 'les statuts d\'expédition du filtre = ceux de la base');
egal(liste('STATUTS_TRANSPORT'), ENUMS.statut_transport, 'transport');
egal(liste('STATUTS_DOUANE'), ENUMS.statut_douane, 'douane');
egal(liste('STATUTS_INCIDENT'), ENUMS.statut_incident, 'incidents');
egal(liste('STATUTS_FACTURE'), ENUMS.statut_facture, 'factures (sans les brouillons, que la liste ne montre jamais)');
egal(liste('STATUTS_TICKET'), ENUMS.statut_ticket, 'tickets');
egal(liste('ROLES'), ENUMS.role, 'rôles');
egal(liste('STATUTS_NOTIF').concat(['SKIPPED']).filter((x, i, t) => t.indexOf(x) === i), ENUMS.statut_notification, 'notifications (SKIPPED se lit mais ne se filtre pas)');
liste('ETAPES_DEMANDE').concat(liste('ETAPES_LIVRAISON')).forEach((x) => assert.ok(ENUMS.etape_demande.indexOf(x) >= 0, 'étape inconnue de la base : ' + x)); n++;

// 4. Les variables {…} d'un texte sont les mêmes dans les quatre langues.
Object.keys(gabarit).filter((c) => /^c-/.test(c)).forEach((cle) => {
  const fr = gabarit[cle], tr = dict[fr.replace(/[‘’]/g, "'")];
  if (!tr) return;
  const vars = (x) => (x.match(/\{[a-z_]+\}/g) || []).sort().join(',');
  tr.forEach((x) => assert.equal(vars(x), vars(fr), 'variables différentes dans la traduction de « ' + fr + ' »'));
}); n++;
// 5. L'onglet lui-même (texte écrit dans la page, traduit par le moteur)
assert.ok(/<span>Centre de commande<\/span>/.test(html) && Array.isArray(dict['Centre de commande']), 'le libellé de l\'onglet est traduit'); n++;
console.log('PASS centre de commande (textes) : ' + n + ' vérifications — chaque valeur de la base, chaque colonne et chaque message a son texte et ses trois traductions ; filtres = statuts de la base.');
