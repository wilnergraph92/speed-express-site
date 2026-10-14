// L'application de bureau « Speed Express Operations » (phase 10, ADR 0016) : le pont entre les pages et l'enveloppe Tauri, et
// l'étiquette 4 × 6 en ZPL. Sans Tauri ni imprimante : une fausse enveloppe enregistre les commandes demandées.
//
// On exige : (1) dans un navigateur, le pont ne fait RIEN (pas d'impression détournée, pas de section) ; (2) dans l'application, chaque
// commande demandée existe dans lib.rs (generate_handler!), et rien d'autre ; window.print passe par l'enveloppe, et revient à la boîte du
// navigateur quand l'enveloppe le dit (Windows) ; (3) les préférences sont revalidées (canal, mode, nom d'imprimante) ; (4) un lien externe
// part dans le navigateur du système, une page interne reste dans l'application ; (5) l'étiquette ZPL : bornée, en UTF-8, 4 × 6 à 203 ppp,
// le numéro en Code 128, le QR du suivi, et AUCUNE commande ZPL glissée par un texte saisi ; (6) l'étiquette suit le choix du poste
// (directe si une imprimante thermique est choisie, sinon la boîte du système, et la boîte du système si l'imprimante refuse) ; (7) chaque texte.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };

const SRC = fs.readFileSync('assets/js/ses-bureau.js', 'utf8');
const RUST = fs.readFileSync('bureau/src-tauri/src/lib.rs', 'utf8');
const commandesRust = new Set((/generate_handler!\[([\s\S]*?)\]/.exec(RUST) || [, ''])[1].split(',').map((x) => x.trim().split('::').pop()).filter(Boolean));

function stockage() { const m = {}; return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, m }; }
function monter(tauri, extra) {
  const ecoute = {}, defs = [], annonces = [], classes = [];
  const fen = Object.assign({ localStorage: stockage(), print: () => fen.__printNatif++, __printNatif: 0, __TAURI__: tauri,
    SES_CENTRE: { enregistrer: (d) => defs.push(d), t: (k, v) => k + (v ? JSON.stringify(v) : ''), e: (x) => String(x), annoncer: (m, g) => annonces.push([m, g]) } }, extra || {});
  const doc = { documentElement: { classList: { add: (c) => classes.push(c) } }, addEventListener: (ev, f) => { ecoute[ev] = f; } };
  vm.runInNewContext(SRC, { window: fen, document: doc, location: { href: 'https://tauri.localhost/tableau-de-bord.html', origin: 'https://tauri.localhost' }, URL, Promise, String, JSON });
  return { fen, B: fen.SES_BUREAU, ecoute, defs, annonces, classes };
}

(async () => {
  // ============================================================ 1. dans un navigateur
  const nav = monter(undefined);
  ok(nav.B && nav.B.actif === false, 'navigateur : le pont existe, inactif');
  ok(nav.defs.length === 0 && !nav.ecoute.click && nav.classes.length === 0, 'navigateur : ni section, ni écoute des liens, ni classe');
  nav.fen.print(); ok(nav.fen.__printNatif === 1, 'navigateur : window.print reste celui du navigateur');
  ok(nav.B.etiquetteDirecte() === false, 'navigateur : jamais d\'étiquette directe');
  ok(await nav.B.imprimantes().then(() => 'oui', (e) => e.message) === 'hors-bureau', 'navigateur : aucune commande de l\'enveloppe');

  // ============================================================ 2. dans l'application
  const appels = [];
  let reponses = { imprimer: 'systeme', imprimantes: ['Zebra ZD421', 'Brother A4'], infos: { version: '1.0.0', systeme: 'macos', architecture: 'aarch64', mises_a_jour: false } };
  const tauri = { core: { invoke: (cmd, args) => { appels.push([cmd, args]); return cmd in reponses ? Promise.resolve(reponses[cmd]) : Promise.resolve(null); } } };
  const app = monter(tauri);
  const B = app.B;
  ok(B.actif === true && app.classes.includes('ses-bureau'), 'application : le pont est actif');
  ok(app.defs.length === 1 && app.defs[0].id === 'bureau' && app.defs[0].ouvrir() === true, 'application : la section « Application de bureau » s\'inscrit');
  app.fen.print(); await new Promise((r) => setTimeout(r, 0));
  ok(appels.some((a) => a[0] === 'imprimer') && app.fen.__printNatif === 0, 'macOS : window.print passe par l\'enveloppe');
  reponses.imprimer = 'navigateur'; appels.length = 0;
  app.fen.print(); await new Promise((r) => setTimeout(r, 0));
  ok(app.fen.__printNatif === 1, 'Windows : l\'enveloppe rend la main, la boîte d\'impression de WebView2 s\'ouvre');
  // chaque commande demandée par la page existe dans lib.rs
  const demandees = new Set([...SRC.matchAll(/appeler\('([a-z_]+)'/g)].map((m) => m[1]));
  for (const c of demandees) ok(commandesRust.has(c), 'commande « ' + c + ' » déclarée dans lib.rs');
  ok(commandesRust.size === demandees.size, 'lib.rs n\'expose que ce que la page demande : ' + [...commandesRust].sort().join(', '));

  // ============================================================ 3. préférences revalidées
  const L = app.fen.localStorage;
  ok(B.canal() === 'stable' && B.modeEtiquette() === 'dialogue' && B.imprimante() === '', 'par défaut : stable, boîte du système, aucune imprimante');
  L.setItem('ses-bureau-canal', 'nightly'); L.setItem('ses-bureau-etiquette-mode', 'brut');
  ok(B.canal() === 'stable' && B.modeEtiquette() === 'dialogue', 'une valeur inconnue revient au défaut');
  L.setItem('ses-bureau-etiquette-imprimante', 'Zebra\u0000; rm -rf /');
  ok(B.imprimante() === '' && B.etiquetteDirecte() === false, 'un nom d\'imprimante avec caractère de contrôle est écarté');
  L.setItem('ses-bureau-canal', 'beta'); L.setItem('ses-bureau-etiquette-mode', 'zpl'); L.setItem('ses-bureau-etiquette-imprimante', 'Zebra ZD421');
  ok(B.canal() === 'beta' && B.etiquetteDirecte() === true, 'canal bêta, étiquette directe sur la Zebra');
  appels.length = 0; await B.verifierMaj();
  ok(appels[0][0] === 'verifier_mise_a_jour' && appels[0][1].canal === 'beta', 'la recherche de mise à jour passe le canal choisi');
  appels.length = 0; await B.imprimerBrut('^XA^XZ');
  ok(appels[0][0] === 'imprimer_brut' && appels[0][1].imprimante === 'Zebra ZD421' && appels[0][1].donnees === '^XA^XZ', 'l\'étiquette brute part vers l\'imprimante choisie');

  // ============================================================ 4. les liens
  const clic = (href) => { let empeche = false; app.ecoute.click({ target: { closest: () => ({ getAttribute: () => href }) }, preventDefault: () => { empeche = true; } }); return empeche; };
  appels.length = 0;
  ok(clic('https://wa.me/18292653727') === true && appels[0][0] === 'ouvrir_lien' && appels[0][1].url === 'https://wa.me/18292653727', 'un lien externe s\'ouvre dans le navigateur du système');
  appels.length = 0;
  ok(clic('suivi.html?colis=SES-1') === false && appels.length === 0, 'une page interne reste dans l\'application');
  ok(clic('javascript:alert(1)') === false && appels.length === 0, 'un lien « javascript: » n\'est jamais transmis');

  // ============================================================ 5. l'étiquette ZPL
  const ui = { window: { SES_CONFIG: { siteUrl: 'https://wilnergraph92.github.io/speed-express-site' }, addEventListener: () => {} },
    document: { documentElement: { lang: 'fr' }, addEventListener: () => {}, querySelector: () => null, querySelectorAll: () => [], getElementById: () => null, createElement: () => ({ style: {}, innerHTML: '', querySelectorAll: () => [] }), head: { appendChild: () => {} }, body: { appendChild: () => {} } },
    location: { href: 'https://tauri.localhost/' }, Promise, URL, Date, Math, JSON, String, Number, Intl, setTimeout, clearTimeout };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-ui.js', 'utf8'), ui);
  const UI = ui.window.SES_UI;
  const colis = { numero: 'SES-4821937065', jeton: 'K7P2', service: 'aerien', destinataire: 'Marie ^XZ^FO0,0^FDpirate~JA Léger', telephone_client: '+509 3700 0000',
    ville_destination: 'Pétion-Ville', pays_destination: 'HT', code_client: 'SES-43521', poids_lb: 8.5, cree_le: '2026-10-14', description: 'x'.repeat(400) };
  const z = UI.zplEtiquette(colis);
  const lignes = z.trim().split('\n');
  ok(lignes[0] === '^XA' && lignes[lignes.length - 1] === '^XZ' && (z.match(/\^XA/g) || []).length === 1 && (z.match(/\^XZ/g) || []).length === 1, 'une seule étiquette : un ^XA, un ^XZ');
  ok(z.includes('^CI28') && z.includes('^PW812') && z.includes('^LL1218'), 'UTF-8, 4 × 6 pouces à 203 ppp');
  ok(!/pirate\^|\^FO0,0|~JA/.test(z) && z.includes('Marie -XZ-FO0,0-FDpirate-JA Léger'), 'un texte saisi ne glisse aucune commande ZPL (^ et ~ neutralisés), les accents restent');
  ok(z.includes('^BCN,200,N,N,N^FDSES-4821937065^FS'), 'le numéro en Code 128, comme sur l\'étiquette imprimée');
  ok(z.includes('^BQN,2,6^FDLA,https://wilnergraph92.github.io/speed-express-site/suivi.html?colis=SES-4821937065&j=K7P2^FS'), 'le QR mène au suivi, jeton compris');
  ok(lignes.every((l) => l.length < 400), 'chaque champ est borné (une description de 400 caractères est coupée)');
  ok(UI.zplEtiquette({ numero: 'SES-1' }).includes('^FDSES-1^FS') && !UI.zplEtiquette({ numero: 'SES-1' }).includes('undefined'), 'un colis presque vide donne une étiquette propre');

  // ============================================================ 6. l'étiquette suit le choix du poste
  const imprimees = [];
  ui.window.print = () => imprimees.push('dialogue');
  ui.window.SES_BUREAU = { actif: true, etiquetteDirecte: () => true, imprimerBrut: (d) => { imprimees.push('zpl'); return Promise.resolve(); }, signaler: () => {} };
  await UI.imprimerEtiquette(colis);
  ok(imprimees.join() === 'zpl', 'imprimante thermique choisie : l\'étiquette part en ZPL, sans boîte');
  ui.window.SES_BUREAU.imprimerBrut = () => Promise.reject(new Error('imprimante éteinte'));
  let signale = null; ui.window.SES_BUREAU.signaler = (e) => { signale = e.message; };
  imprimees.length = 0; await UI.imprimerEtiquette(colis); await new Promise((r) => setTimeout(r, 30));
  ok(signale === 'imprimante éteinte', 'une imprimante qui refuse est signalée…');
  ui.window.SES_BUREAU.etiquetteDirecte = () => false;
  ok(imprimees.join() === 'dialogue', '… et la page 4 × 6 reprend par la boîte du système : ' + imprimees.join());
  imprimees.length = 0; await UI.imprimerEtiquette(colis); await new Promise((r) => setTimeout(r, 30));
  ok(imprimees.join() === 'dialogue', 'sans imprimante thermique choisie : la boîte du système, comme dans un navigateur');
  ok(!/UI\.imprimer\(UI\.etiquette\(/.test(fs.readFileSync('assets/js/ses-admin.js', 'utf8') + fs.readFileSync('assets/js/ses-poste.js', 'utf8')), 'partout, l\'étiquette passe par imprimerEtiquette (fiche du colis, poste de scan)');

  // ============================================================ 7. les textes et la page
  const html = fs.readFileSync('tableau-de-bord.html', 'utf8');
  const cles = new Set([...SRC.matchAll(/t\('(c-[a-z0-9-]+)'/g)].map((m) => m[1]));
  cles.add('c-sec-bureau');
  for (const k of cles) ok(html.includes('data-t="' + k + '"'), 'texte présent dans la page : ' + k);
  const ordre = ['ses-centre.js', 'ses-poste.js', 'ses-bureau.js', 'ses-modules.js'].map((f) => html.indexOf('assets/js/' + f));
  ok(ordre.every((i) => i > 0) && ordre[0] < ordre[1] && ordre[1] < ordre[2], 'la page charge le centre, le poste, puis le pont de bureau');
  ok(/data-module="scanner" data-sections="poste bureau"/.test(html), 'la section « Application de bureau » vit dans le module Scanner');
  console.log('PASS application de bureau (pont et étiquette ZPL) : ' + n + ' vérifications — inactive dans un navigateur, commandes = lib.rs, impression par le système, '
    + 'préférences revalidées, liens externes au navigateur du système, ZPL borné et sans injection, repli sur la boîte du système.');
})().catch((e) => { console.error('ÉCHEC application de bureau : ' + (e && e.message)); process.exit(1); });
