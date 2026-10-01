/* Dictionnaires exécutés sans navigateur : clés FR et trois traductions non vides.
   Les clés data-t sont vérifiées séparément car ce ne sont pas les clés SES_DICT. */
var fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert');
var contexte = {window: {}};
vm.createContext(contexte);
var fichiers = fs.readdirSync('assets/js').filter(function (n) { return /^lang-dict(?:-\d+)?\.js$/.test(n); });
var total = 0;
fichiers.forEach(function (nom) {
  contexte.window.SES_DICT = {};
  vm.runInContext(fs.readFileSync('assets/js/' + nom, 'utf8'), contexte, {filename: nom});
  Object.keys(contexte.window.SES_DICT).forEach(function (cle) {
    var valeurs = contexte.window.SES_DICT[cle];
    assert(cle.trim(), nom + ': clé vide');
    assert(Array.isArray(valeurs) && valeurs.length === 3, nom + ': ' + cle);
    valeurs.forEach(function (v) { assert(typeof v === 'string' && v.trim(), nom + ': traduction vide ' + cle); });
    total++;
  });
});
assert(fichiers.length === 11, '11 dictionnaires attendus');
['espace-client.html', 'tableau-de-bord.html'].forEach(function (nom) {
  var html = fs.readFileSync(nom, 'utf8');
  var cles = Array.from(html.matchAll(/data-t="([^"]+)"/g), function (m) { return m[1]; });
  assert(new Set(cles).size === cles.length, nom + ': clés data-t doublées');
});
[
  ['espace-client.html', 'ses-espace.js', ''],
  ['tableau-de-bord.html', 'ses-dashboard.js', 'dash-']
].forEach(function (ecran) {
  var html = fs.readFileSync(ecran[0], 'utf8');
  var js = fs.readFileSync('assets/js/' + ecran[1], 'utf8');
  Array.from(js.matchAll(/\bt\('([^']+)'\s*[,)]/g)).forEach(function (m) {
    assert(html.includes('data-t="' + ecran[2] + m[1] + '"'), ecran[0] + ': clé absente ' + m[1]);
  });
});
console.log('PASS i18n : ' + fichiers.length + ' dictionnaires, ' + total + ' entrées, clés data-t uniques.');
