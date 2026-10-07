// Les réglages du tableau de bord (assets/js/ses-reglages.js), sans navigateur : un faux document et un faux stockage.
//   node outils/tests/reglages.cjs
// On exige : des valeurs par défaut sûres ; toute valeur relue est revalidée (un réglage inconnu ou trafiqué redevient celui
// par défaut) ; un stockage interdit ne casse rien ; le thème « système » suit l'appareil ; l'apparence et les animations se
// posent sur <html> ; chaque texte du module existe sur la page ; la page charge le module avant ses-admin.js.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };

function charger({ stockage, sombre, interdit }) {
  const attrs = {}, classes = new Set();
  const html = {
    setAttribute: (k, v) => { attrs[k] = v; }, getAttribute: (k) => attrs[k],
    classList: { toggle: (c, oui) => { if (oui) classes.add(c); else classes.delete(c); }, contains: (c) => classes.has(c) }
  };
  const store = stockage || {};
  const localStorage = {
    getItem: (k) => { if (interdit) throw new Error('interdit'); return k in store ? store[k] : null; },
    setItem: (k, v) => { if (interdit) throw new Error('interdit'); store[k] = String(v); },
    removeItem: (k) => { delete store[k]; }
  };
  const window = {
    matchMedia: (q) => ({ matches: q.indexOf('dark') >= 0 ? !!sombre : true, addEventListener: () => {} }),
    addEventListener: () => {}
  };
  const document = {
    readyState: 'loading', documentElement: html, addEventListener: () => {},
    querySelector: () => null, querySelectorAll: () => [], getElementById: () => null
  };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-reglages.js', 'utf8'), { window, document, localStorage, navigator: { onLine: true }, JSON, Number, Array });
  return { R: window.SES_REGLAGES, attrs, classes, store };
}

// valeurs par défaut
let x = charger({});
ok(JSON.stringify(x.R.lire()) === JSON.stringify({ theme: 'clair', animations: true, periode: '30j', lignes: 20, reduit: false }), 'défauts : clair, animations, 30 jours, 20 lignes, menu ouvert');
ok(x.attrs['data-theme'] === 'clair', 'le thème se pose sur <html> dès le chargement');

// une valeur trafiquée redevient celle par défaut
x = charger({ stockage: { 'ses-tdb-reglages': JSON.stringify({ theme: '<script>', animations: 'non', periode: 'toujours', lignes: 100000, reduit: 'oui' }) } });
const r = x.R.lire();
ok(r.theme === 'clair' && r.periode === '30j' && r.lignes === 20 && r.reduit === false, 'valeurs inconnues ou trafiquées : retour aux défauts');
x = charger({ stockage: { 'ses-tdb-reglages': '{pas du json' } });
ok(x.R.lire().theme === 'clair', 'stockage illisible : défauts, sans erreur');
x = charger({ interdit: true });
ok(x.R.lire().lignes === 20, 'stockage interdit (navigation privée) : défauts');
let erreur = null; try { x.R.ecrire('theme', 'sombre'); } catch (e) { erreur = e; }
ok(!erreur && x.attrs['data-theme'] === 'sombre', 'stockage interdit : le réglage s\'applique quand même à la page, sans erreur');

// écrire, appliquer, prévenir
x = charger({});
const vus = []; x.R.surChange((cle, v) => vus.push(cle + '=' + v[cle]));
x.R.ecrire('theme', 'sombre'); x.R.ecrire('lignes', 50); x.R.ecrire('animations', false);
ok(x.attrs['data-theme'] === 'sombre', 'sombre posé sur <html>');
ok(x.classes.has('rg-sans-animations'), 'animations coupées : la classe est posée');
ok(JSON.parse(x.store['ses-tdb-reglages']).lignes === 50, 'le réglage est gardé sur l\'appareil');
ok(vus.join() === 'theme=sombre,lignes=50,animations=false', 'chaque changement prévient les écrans (lignes par page…)');
x.R.ecrire('animations', true);
ok(!x.classes.has('rg-sans-animations'), 'animations rallumées');

// le thème « système » suit l'appareil
x = charger({ sombre: true, stockage: { 'ses-tdb-reglages': JSON.stringify({ theme: 'systeme' }) } });
ok(x.attrs['data-theme'] === 'sombre', 'système sur un appareil sombre : sombre');
x = charger({ sombre: false, stockage: { 'ses-tdb-reglages': JSON.stringify({ theme: 'systeme' }) } });
ok(x.attrs['data-theme'] === 'clair', 'système sur un appareil clair : clair');

// la page
const page = fs.readFileSync('tableau-de-bord.html', 'utf8'), js = fs.readFileSync('assets/js/ses-reglages.js', 'utf8');
for (const [, k] of js.matchAll(/\bt\('([\w-]*\w)'[,)]/g)) ok(page.includes('data-t="' + k + '"'), 'texte « ' + k + ' » présent sur la page');
for (const m of ['clair', 'sombre', 'systeme']) ok(page.includes('data-t="rg-mode-supabase"') && page.includes('data-theme-choix="' + m + '"'), 'apparence « ' + m + ' » proposée dans le menu');
ok(page.indexOf('assets/js/ses-reglages.js?v=') > 0 && page.indexOf('assets/js/ses-reglages.js?v=') < page.indexOf('assets/js/ses-admin.js?v='), 'le module se charge avant ses-admin.js (lignes par page lues au démarrage)');
ok(page.includes('assets/css/ses-reglages.css?v='), 'la feuille de style des réglages et du thème sombre est chargée');
for (const id of ['rg-menu', 'rg-menu-compte', 'rg-reglages', 'rg-theme', 'rg-animations', 'rg-periode', 'rg-lignes', 'rg-reduit', 'rg-defaut', 'rg-termine'])
  ok(page.includes('id="' + id + '"'), 'page : #' + id);
const css = fs.readFileSync('assets/css/ses-reglages.css', 'utf8');
ok(/:root\[data-theme="sombre"\] \.ses-admin-page \[style\*="background:#fff"\]:has\(\.ses-facture-page\)\{background:#fff!important/.test(css), 'en sombre, la facture reste un papier blanc');

console.log('PASS réglages : ' + n + ' vérifications — défauts sûrs, valeurs revalidées, stockage interdit sans casse, thème système suivi, apparence et animations posées, textes et chargement de la page');
