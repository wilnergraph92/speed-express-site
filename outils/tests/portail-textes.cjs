// Les textes du portail client : chaque valeur que la base peut renvoyer a un texte dans la page ET une traduction dans les trois autres langues.
//
// i18n.cjs vérifie les clés écrites en toutes lettres (t('p-nav-colis')) ; il ne voit pas celles que le code construit (t('stage-' + étape),
// t('inv-' + statut)…). Un nouveau statut de facture, une nouvelle étape, un nouveau mode de paiement ajoutés à la base laisseraient donc un
// texte VIDE à l'écran, sans erreur. Les valeurs viennent de la vraie base (outils/tests/portail-enums.json, écrit par logistique-portail-essai.py).
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const ENUMS = JSON.parse(fs.readFileSync('outils/tests/portail-enums.json', 'utf8'));
const html = fs.readFileSync('espace-client.html', 'utf8');
const gabarit = {};
Array.from(html.matchAll(/<span data-t="([^"]+)">([^<]*)<\/span>/g)).forEach((m) => { gabarit[m[1]] = m[2].replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim(); });
const bac = { window: {} }; bac.window.SES_DICT = {};
['lang-dict.js', 'lang-dict-11.js'].forEach((f) => vm.runInNewContext(fs.readFileSync('assets/js/' + f, 'utf8'), bac));
const dict = bac.window.SES_DICT;
let n = 0;

function exiger(cle) {
  assert.ok(Object.prototype.hasOwnProperty.call(gabarit, cle), 'espace-client.html : texte absent pour la clé « ' + cle + ' » (relancer outils/portail-textes.py après l\'avoir ajouté à sa table)'); n++;
  const fr = gabarit[cle].replace(/\s+/g, ' ');
  assert.ok(fr, 'texte vide pour « ' + cle + ' »');
  const tr = dict[fr.replace(/[‘’]/g, "'")];
  assert.ok(Array.isArray(tr) && tr.length === 3 && tr.every((x) => typeof x === 'string' && x.trim()), 'pas de traduction anglais/espagnol/créole pour « ' + fr + ' » (clé ' + cle + ')'); n++;
}

const FAMILLES = { stage: 'stage-', event: 'evt-', invoice_status: 'inv-', quote_status: 'quote-', consolidation_status: 'cons-', method: 'method-', line_kind: 'line-', window: 'win-',
  category: 'cat-', ticket_status: 'tk-', service_mode: 'mode-', incident: 'incident-', request_stage: 'req-', customs: 'customs-', document_kind: 'doc-' };
Object.keys(FAMILLES).forEach((f) => ENUMS[f].forEach((v) => exiger(FAMILLES[f] + v)));

// Les étapes qui ne sont PAS une progression (un arrêt) ont leur message.
['on_hold', 'incident', 'lost', 'cancelled', 'returned'].forEach((s) => { assert.ok(ENUMS.stage.indexOf(s) >= 0, s); exiger('p-arret-' + s); });
['CUSTOMER', 'STAFF'].forEach((a) => exiger('tk-author-' + a));
['DRAFT'].forEach(() => {});
// Les sept étapes du parcours, dans l'ordre d'affichage (le même que celui de ses-portail.js).
const src = fs.readFileSync('assets/js/ses-portail.js', 'utf8');
const parcours = /var PARCOURS = \[([^\]]+)\]/.exec(src)[1].split(',').map((x) => x.trim().replace(/'/g, ''));
assert.deepEqual(parcours, ['registered', 'received', 'in_transit', 'customs', 'at_hub', 'out_for_delivery', 'delivered']); n++;
parcours.forEach((p) => assert.ok(ENUMS.stage.indexOf(p) >= 0, 'étape inconnue de la base : ' + p));
// La base ne renvoie aucune étape que le portail ne sache pas dessiner (progression ou arrêt).
ENUMS.stage.forEach((s) => assert.ok(parcours.indexOf(s) >= 0 || ['on_hold', 'incident', 'lost', 'cancelled', 'returned', 'preparing', 'closed'].indexOf(s) >= 0, 'étape sans dessin : ' + s)); n++;

// Les onglets : chaque section enregistrée a son libellé de navigation.
const sections = [];
['ses-portail-suivi.js', 'ses-portail-finance.js', 'ses-portail-services.js'].forEach((f) => {
  Array.from(fs.readFileSync('assets/js/' + f, 'utf8').matchAll(/P\.enregistrer\(\{\s*id: '([a-z]+)', ordre: (\d+)/g)).forEach((m) => sections.push([Number(m[2]), m[1]]));
});
sections.sort((a, b) => a[0] - b[0]);
assert.deepEqual(sections.map((s) => s[1]), ['tableau', 'colis', 'expeditions', 'suivi', 'consolidations', 'factures', 'paiements', 'documents', 'adresses', 'enlevements', 'livraisons', 'notifications', 'support', 'profil']); n++;
sections.forEach((s) => exiger('p-nav-' + s[1]));
assert.equal(new Set(sections.map((s) => s[0])).size, sections.length, 'deux sections ont le même rang'); n++;

// Les codes d'erreur que la couche de données peut lever vers le portail ont leur phrase.
['introuvable', 'etat-incompatible', 'donnee-invalide', 'doublon', 'noyau-absent', 'non-autorise'].forEach((c) => {
  if (c !== 'non-autorise') exiger('erreur-' + c);
  else assert.ok(Object.prototype.hasOwnProperty.call(gabarit, 'erreur-non-autorise'), 'erreur-non-autorise'); n++;
});
// Les notifications connues du moteur ont leur texte ; un modèle inconnu retombe sur une phrase neutre (p-notif-autre).
['ParcelReceived', 'ShipmentArrived', 'CustomsCleared', 'OutForDelivery', 'Delivered', 'DeliveryOtp'].forEach((tpl) => exiger('notif-' + tpl)); exiger('p-notif-autre');
// Les variables {…} d'un texte sont les mêmes dans les quatre langues (sinon une valeur disparaît ou s'affiche entre accolades).
Object.keys(gabarit).forEach((cle) => {
  const fr = gabarit[cle], tr = dict[fr.replace(/[‘’]/g, "'")];
  if (!tr) return;
  const vars = (x) => (x.match(/\{[a-z_]+\}/g) || []).sort().join(',');
  tr.forEach((x) => assert.equal(vars(x), vars(fr), 'variables différentes dans la traduction de « ' + fr + ' »'));
}); n++;
console.log('PASS portail client (textes) : ' + n + ' vérifications — chaque valeur de la base a son texte et ses trois traductions, quatorze sections nommées, codes d\'erreur, variables.');
