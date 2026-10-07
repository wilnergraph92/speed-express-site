// Les fenêtres du tableau de bord (assets/js/ses-admin.js) : ce qui les rend sûres ne doit pas disparaître en silence.
//   node outils/tests/fenetres-tableau.cjs
// (1) Chaque geste qui touche aux données a un droit dans DROIT_ACTION, revérifié au clic ; (2) la liste des colis n'a plus de
// bouton : la ligne ouvre la fiche, et Statut / Modifier / Supprimer vivent dans la fiche, chacun derrière son droit ; (3) toute
// suppression exige de retaper le numéro ; (4) une seule fenêtre à la fois, et un formulaire commencé ne se ferme pas sur « Échap » ;
// (5) les textes existent sur la page (sinon des boutons vides).
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };
const js = fs.readFileSync('assets/js/ses-admin.js', 'utf8'), page = fs.readFileSync('tableau-de-bord.html', 'utf8');

// (1) la table des droits, lue telle quelle
const brut = /var DROIT_ACTION = (\{[\s\S]*?\});/.exec(js);
ok(brut, 'DROIT_ACTION existe');
const DROITS = vm.runInNewContext('(' + brut[1] + ')');
const ATTENDU = { statut: 'colis.statut', modifier: 'colis.modifier', supprimer: 'colis.supprimer', 'supprimer-facture': 'factures.supprimer',
  'modifier-facture': 'factures.modifier', 'basculer-facture': 'factures.modifier', paiement: 'factures.modifier', facturer: 'factures.creer',
  fiche: 'colis.lire', 'imprimer-fiche': 'colis.lire', profil: 'clients.lire' };
for (const [a, d] of Object.entries(ATTENDU)) ok(DROITS[a] === d, a + ' exige « ' + d + ' »');
const gestes = new Set([...js.matchAll(/data-action="([a-z-]+)"/g), ...js.matchAll(/bouton\('([a-z-]+)'/g)].map((m) => m[1]));
for (const g of gestes) ok(g in DROITS || g === 'role', 'geste « ' + g + ' » : un droit déclaré (ou une règle à part)');
ok(/if \(!autorise\(action, id\)\) return erreurGenerale\(\{ code: 'non-autorise' \}\);/.test(js), 'le droit est revérifié au clic, avant tout geste');
ok(/if \(action === 'role'\) \{[\s\S]{0,200}peutChangerRole\(compte\)/.test(js), 'changer un rôle : la règle de la hiérarchie');

// (2) la liste des colis et la fiche
const liste = /function listeColis\(\) \{([\s\S]*?)\n  \}\n/.exec(js)[1];
ok(!/bouton\(/.test(liste), 'la liste des colis n\'a plus de bouton d\'action');
ok(/data-fiche="/.test(liste) && /tabindex="0"/.test(liste) && /ouvrir-fiche/.test(liste), 'la ligne ouvre la fiche, au clavier aussi, avec un nom pour les lecteurs d\'écran');
const fiche = /function ouvrirFiche\(id\) \{([\s\S]*?)\n  \}\n/.exec(js)[1];
for (const [a, d] of [['statut', 'colis.statut'], ['modifier', 'colis.modifier'], ['supprimer', 'colis.supprimer']])
  ok(new RegExp("peut\\('" + d.replace('.', '\\.') + "'\\) \\? [\\s\\S]{0,80}?bouton\\('" + a + "'").test(fiche), 'fiche : « ' + a + ' » seulement avec « ' + d + ' »');
ok(/ses-actions-fiche/.test(fiche), 'fiche : la barre d\'actions');
ok(/if \(ev\.target\.closest\('input,button,a,label'\)\) return;/.test(js), 'cocher une case ne déclenche pas l\'ouverture');

// (2 bis) la liste des factures, même principe
const listeF = /function listeFactures\(\) \{([\s\S]*?)\n  \}\n/.exec(js)[1];
ok(!/data-action=/.test(listeF), 'la liste des factures n\'a plus de bouton d\'action');
ok(/data-facture="/.test(listeF) && /tabindex="0"/.test(listeF) && /ouvrir-facture/.test(listeF), 'la ligne d\'une facture ouvre sa fenêtre, au clavier aussi');
const apercu = /function apercuFacture\(fa, colis\) \{([\s\S]*?)\n  \}\n/.exec(js)[1];
ok(/peut\('factures\.modifier'\) \?[\s\S]{0,200}data-action="paiement"[\s\S]{0,300}data-action="basculer-facture"[\s\S]{0,400}data-action="modifier-facture"/.test(apercu), 'facture : paiement, payée/impayée, modifier seulement avec « factures.modifier »');
ok(/peut\('factures\.supprimer'\) \?[\s\S]{0,200}data-action="supprimer-facture"/.test(apercu), 'facture : supprimer seulement avec « factures.supprimer »');
ok(/function rouvrirFacture\(id\) \{\s*if \(!peut\('factures\.lire'\)\)/.test(js), 'ouvrir une facture exige « factures.lire »');

// (3) les suppressions
ok((js.match(/confirmer\(UI\.t\('confirmer-(colis|facture)'[\s\S]*?\}, [a-z]\.numero\);/g) || []).length === 2, 'colis et facture : le numéro à retaper');
ok(/\$\('#ses-confirmer-oui'\)\.disabled = !!aRetaper;/.test(js), 'le bouton de suppression reste éteint tant que le numéro n\'est pas retapé');
ok(/if \(aRetaper && String\(\$\('#ses-confirmer-champ'\)\.value\)\.trim\(\)\.toUpperCase\(\) !== aRetaper\.toUpperCase\(\)\) return;/.test(js), 'revérifié au clic');
ok(/'#ses-confirmer'\)\.addEventListener\('close', function \(\) \{ aConfirmer = null; \}\)/.test(js), 'fermée sans confirmer : l\'action en attente est oubliée');

// (4) une fenêtre à la fois, rien de perdu sur « Échap »
const ouvertures = (js.match(/\$\('#(ses-form-[a-z]+|ses-fiche)'\)\.showModal\(\);/g) || []).length;
const gardees = (js.match(/fermerFenetres\('(ses-form-[a-z]+|ses-fiche)'\);\n\s+\$\('#\1'\)\.showModal\(\);/g) || []).length;
ok(ouvertures > 0 && ouvertures === gardees, 'chaque fenêtre ferme les autres avant de s\'ouvrir (' + gardees + '/' + ouvertures + ')');
ok(/d\.addEventListener\('cancel', function \(ev\) \{\s*if \(!d\.dataset\.modifie\) return;\s*ev\.preventDefault\(\);/.test(js), 'un formulaire modifié ne se ferme pas sur « Échap »');

// (5) la page
for (const id of ['ses-confirmer-saisie', 'ses-confirmer-champ', 'ses-confirmer-consigne']) ok(page.includes('id="' + id + '"'), 'page : #' + id);
for (const k of ['ouvrir-fiche', 'ouvrir-facture', 'action-imprimer-fiche', 'confirmer-saisie', 'modifs-non-enregistrees', 'action-statut', 'action-modifier', 'action-supprimer'])
  ok(page.includes('data-t="' + k + '"'), 'page : texte « ' + k + ' »');

console.log('PASS fenêtres du tableau de bord : ' + n + ' vérifications — droits revérifiés au clic, actions dans la fiche, suppression au numéro retapé, une fenêtre à la fois, rien de perdu sur « Échap »');
