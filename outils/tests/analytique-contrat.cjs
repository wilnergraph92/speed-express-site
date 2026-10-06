// L'analytique côté site (phase 16) : la couche de données et l'écran tiennent le contrat de la VRAIE base, sans réseau.
//
// Références écrites (et revérifiées) par outils/tests/logistique-analytique-essai.py sur un PostgreSQL jetable :
//   · analytique-rpc.json      : les signatures des cinq fonctions lg_an_* ;
//   · analytique-exemples.json : des réponses réelles (rapports, indicateurs, exécutions, vérifications).
// Ce qu'on éprouve : (1) trois implémentations, mêmes méthodes, ni démonstration ni site fermé ; (2) chaque appel respecte la signature, une
// période ou un grain invalide ne part pas ; (3) l'écran se dessine sur les réponses réelles sans lire une clé absente, sans « undefined » ni
// « NaN », en échappant tout ; n'additionne rien (les totaux viennent de la base) ; dit les jours manquants et le provisoire ; nomme chaque mesure,
// chaque rapport, chaque grain, chaque verdict ; (4) le CSV ne peut pas devenir une formule ; (5) la page charge le script.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const SIG = JSON.parse(fs.readFileSync('outils/tests/analytique-rpc.json', 'utf8'));
const EX = JSON.parse(fs.readFileSync('outils/tests/analytique-exemples.json', 'utf8'));
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };

function charger(config, hote, extra) {
  const bac = Object.assign({ window: { addEventListener: () => {}, SES_CONFIG: config }, location: { protocol: 'https:', hostname: hote, href: 'https://' + hote + '/x.html', pathname: '/x.html' },
    document: { documentElement: { lang: 'fr' }, currentScript: null }, console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder }, extra || {});
  vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), bac);
  return bac.window.SES_API;
}
const rejet = async (p) => { try { await p; } catch (e) { return e.code; } return 'aucune-erreur'; };

(async () => {
  // ============================================================ 1. trois implémentations
  const faux = { appels: [] };
  const cfg = { supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai' };
  const en = charger(cfg, 'exemple.fr', { window: { addEventListener: () => {}, SES_CONFIG: cfg, supabase: { createClient: () => ({ auth: {}, rpc: (nom, args) => { faux.appels.push({ nom, args }); return Promise.resolve({ data: {}, error: null }); } }) } } });
  const demo = charger({}, 'localhost'), off = charger({}, 'exemple.fr');
  const M = Array.from(en.METHODES_ANALYTIQUE).sort();
  ok(M.join() === 'executions,indicateurs,rapport,recalculer,verifier', 'cinq méthodes');
  for (const [nom, api] of [['en ligne', en], ['démonstration', demo], ['fermé', off]]) ok(JSON.stringify(Object.keys(api.analytique).sort()) === JSON.stringify(M), nom + ' : mêmes méthodes');
  for (const m of M) {
    ok(await rejet(demo.analytique[m]('month', '2026-01-01', '2026-01-31')) === 'non-autorise', 'démonstration : ' + m + ' fermé (aucun chiffre inventé)');
    ok(await rejet(off.analytique[m]('month', '2026-01-01', '2026-01-31')) === 'ferme', 'site fermé : ' + m);
  }

  // ============================================================ 2. les appels respectent les signatures
  const vus = new Set();
  for (const [m, args] of [['rapport', ['week', '2026-01-01', '2026-03-31']], ['indicateurs', ['2026-01-01', '2026-01-31']], ['executions', [10]], ['recalculer', ['2026-01-01', '2026-01-31']], ['verifier', [12]]]) {
    faux.appels.length = 0; await en.analytique[m].apply(null, args);
    const a = faux.appels[0], sig = SIG[a.nom];
    ok(sig, m + ' : « ' + a.nom + ' » existe dans la base');
    Object.keys(a.args).forEach((k) => ok(sig.some((p) => p.nom === k), m + ' : paramètre inconnu ' + k));
    sig.filter((p) => !p.defaut).forEach((p) => ok(Object.prototype.hasOwnProperty.call(a.args, p.nom), m + ' : oublie ' + p.nom));
    vus.add(a.nom);
  }
  ok([...vus].sort().join() === Object.keys(SIG).sort().join(), 'le site appelle exactement les cinq fonctions lg_an_*');
  faux.appels.length = 0;
  for (const [m, args, msg] of [['rapport', ['heure', '2026-01-01', '2026-01-02'], 'grain inconnu'], ['rapport', ['day', '01/01/2026', '2026-01-02'], 'date mal écrite'],
    ['indicateurs', ['2026-01-01', ''], 'date vide'], ['recalculer', [null, '2026-01-01'], 'sans début'], ['verifier', ['12; drop'], 'identifiant douteux'], ['verifier', [0], 'identifiant nul']]) {
    ok(await rejet(en.analytique[m].apply(null, args)) === 'donnee-invalide', 'refusé avant tout appel : ' + msg);
  }
  ok(faux.appels.length === 0, 'aucun de ces refus n\'a atteint la base');
  ok(JSON.stringify(Array.from(en.GRAINS_ANALYTIQUE)) === '["day","week","month","quarter","year"]', 'les cinq grains de la base');

  // ============================================================ 3. l'écran, sur les réponses réelles
  const html = fs.readFileSync('tableau-de-bord.html', 'utf8');
  const textes = {};
  for (const m of html.matchAll(/<span data-t="([^"]+)">([^<]*)<\/span>/g)) textes[m[1]] = m[2];
  const fautes = [];
  const T = (k, v) => {
    if (!(k in textes)) fautes.push('texte absent : ' + k);
    let s = textes[k] || '';
    Object.keys(v || {}).forEach((x) => { s = s.split('{' + x + '}').join(String(v[x])); });
    return s;
  };
  function garde(x, chemin) {
    if (!x || typeof x !== 'object') return x;
    return new Proxy(x, { get(cible, cle) {
      if (typeof cle === 'symbol' || cle === 'toJSON' || cle === 'length' || cle === 'constructor' || cle === 'then') return Reflect.get(cible, cle);
      if (Array.isArray(cible) && (/^\d+$/.test(cle) || cle in Array.prototype)) { const v = Reflect.get(cible, cle); return typeof v === 'function' ? v.bind(cible) : garde(v, chemin + '[]'); }
      if (!(cle in cible)) fautes.push('clé absente de la réponse réelle : ' + chemin + '.' + String(cle));
      return garde(Reflect.get(cible, cle), chemin + '.' + String(cle));
    } });
  }
  const echapper = (x) => String(x).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const defs = [];
  const C = { enregistrer: (d) => defs.push(d), t: T, e: echapper, montant: (v) => '$' + Number(v).toFixed(2), jour: (x) => String(x), date: (x) => String(x), acces: () => ({ direction: true, today: '2026-10-06' }), message: String, annoncer: () => {} };
  const fen = { SES_API: en, SES_CENTRE: C };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-analytique.js', 'utf8'), { window: fen, document: { documentElement: { lang: 'fr' } }, URL, Blob: class {}, setTimeout, Date, Math, JSON, String, Number, Promise });
  const A = C.analytique, def = defs[0];
  ok(def && def.id === 'analytique', 'la section s\'inscrit dans le centre');
  ok(def.ouvrir({ ops: true }) && def.ouvrir({ finance: true }) && def.ouvrir({ customers: true }) && !def.ouvrir({ direction: true }) && !def.ouvrir(null), 'ouverte dès qu\'un domaine est lisible, et seulement alors');
  const sorties = [];
  for (const [nom, rap] of [['rapport_mois', EX.rapport_mois], ['rapport_jour', EX.rapport_jour], ['rapport_trou', EX.rapport_trou]]) {
    const r = garde(JSON.parse(JSON.stringify(rap)), nom);
    sorties.push(A.notes(r, true), A.tableaux(r));
  }
  sorties.push(A.cartes(garde(JSON.parse(JSON.stringify(EX.indicateurs)), 'indicateurs')));
  sorties.push(A.journal(garde(JSON.parse(JSON.stringify(EX.executions)), 'executions'), true));
  A.etat.verdicts[EX.executions[0].run_id] = 'SOURCES_CHANGED';
  sorties.push(A.journal(garde(JSON.parse(JSON.stringify(EX.executions)), 'executions'), true));
  const tout = sorties.join('\n');
  ok(fautes.length === 0, 'aucune clé absente, aucun texte manquant : ' + fautes.slice(0, 5).join(' ; '));
  ok(!/undefined|NaN|\[object/.test(tout), 'ni « undefined », ni « NaN » à l\'écran');
  ok(tout.includes(textes['c-an-manquants'].split('{nombre}')[0].trim().slice(0, 10)) || EX.rapport_trou.missing_days.length === 0, 'des jours jamais calculés : signalés');
  ok(A.notes(EX.rapport_trou, true).includes('data-an-calculer') && !A.notes(EX.rapport_trou, false).includes('data-an-calculer'), '« Calculer ces jours » : pour la direction seulement');
  ok(A.notes({ missing_days: [], partial: true, runs: [] }, true).includes(echapper(textes['c-an-provisoire'])), 'une période provisoire le dit');
  ok(tout.includes(echapper(textes['c-an-v-SOURCES_CHANGED'])), 'le verdict d\'une vérification s\'affiche');
  // pas une addition : chaque cellule vient d'un total de la base
  const src = fs.readFileSync('assets/js/ses-analytique.js', 'utf8');
  ok(!/\+=\s*(Number|v\b|x\.value|r\.value)|reduce\(/.test(src), 'aucune addition dans le navigateur : les totaux viennent de la base (« totals »)');
  const t0 = EX.rapport_mois.totals[0];
  if (t0) ok(A.tableaux(EX.rapport_mois).includes(echapper(A.valeur(t0.value, EX.rapport_mois.metrics.find((m) => m.code === t0.metric).unit))), 'un total de la base apparaît tel quel dans le tableau');
  // un texte hostile venant de la base est échappé
  const hostile = JSON.parse(JSON.stringify(EX.executions)); hostile[0].generated_by = '<img src=x onerror=alert(1)>';
  ok(!A.journal(hostile, false).includes('<img') && A.journal(hostile, false).includes('&lt;img'), 'ce qui vient de la base est échappé');
  // les noms : chaque mesure, rapport, grain, domaine, verdict
  const mesures = EX.rapport_mois.metrics.map((m) => m.code);
  ok(mesures.length === 22, 'l\'administrateur voit les vingt-deux mesures');
  for (const m of mesures) ok(('c-an-m-' + m) in textes, 'mesure nommée : ' + m);
  for (const r of Object.keys(EX.indicateurs.ratios_current)) ok(('c-an-r-' + r) in textes, 'rapport nommé : ' + r);
  for (const g of en.GRAINS_ANALYTIQUE) ok(('c-an-g-' + g) in textes, 'grain nommé : ' + g);
  for (const d of ['ops', 'finance', 'customers']) ok(('c-an-d-' + d) in textes, 'domaine nommé : ' + d);
  for (const v of ['REPRODUCIBLE', 'SOURCES_CHANGED', 'COMPUTATION_CHANGED']) ok(('c-an-v-' + v) in textes, 'verdict nommé : ' + v);
  ok(EX.verification.verdict === 'REPRODUCIBLE' && EX.verification_sources.verdict === 'SOURCES_CHANGED', 'les exemples réels couvrent les verdicts');
  ok(Object.keys(A.CARTES).every((d) => A.CARTES[d].mesures.every((m) => mesures.includes(m)) && A.CARTES[d].ratios.every((r) => r in EX.indicateurs.ratios_current)), 'les cartes ne citent que des mesures et des rapports que la base rend');
  ok(A.ORDRE.length === 22 && mesures.every((m) => A.ORDRE.includes(m)), 'chaque mesure a sa place dans l\'ordre de lecture');
  const tab = A.tableaux(EX.rapport_mois);
  ok(tab.indexOf(echapper(textes['c-an-m-parcels_received'])) < tab.indexOf(echapper(textes['c-an-m-parcels_delivered'])), 'les lignes suivent l\'ordre de lecture (reçus avant livrés)');
  // les valeurs
  ok(A.valeur(null, 'pct') === '—' && A.valeur(undefined, 'count') === '—', 'une valeur que la base n\'a pas pu calculer s\'écrit « — », jamais « 0 »');
  ok(A.valeur(75, 'pct').includes('75') && A.valeur(12.5, 'hours').includes('12,5'), 'pourcentages et heures mis en forme dans la langue');
  ok(A.nomPeriode('2026-07-01', 'quarter') === 'T3 2026' && A.nomPeriode('2026-01-01', 'year') === '2026', 'trimestre et année nommés');
  // le CSV
  const c = A.csv({ metrics: [{ code: 'payments_usd', unit: 'usd' }], rows: [{ period: '2026-09-01', metric: 'payments_usd', dimension: '=HYPERLINK("x")', value: 50 }] });
  ok(c.charCodeAt(0) === 0xfeff && c.includes('"\'=HYPERLINK(""x"")"') && c.includes('"usd"'), 'CSV : BOM, aucune formule, guillemets doublés, unité');
  ok(/<script src="assets\/js\/ses-analytique\.js\?v=\d+" defer><\/script>/.test(html), 'la page charge l\'analytique');
  console.log('PASS analytique : ' + n + ' vérifications — trois implémentations, signatures réelles, écran sur réponses réelles sans addition ni trou, textes, CSV.');
})().catch((e) => { console.error('ÉCHEC analytique : ' + (e && e.message)); process.exit(1); });
