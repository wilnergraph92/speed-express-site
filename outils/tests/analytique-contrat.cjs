// L'analytique côté site (phase 16, complétée par l'étape 029) : la couche de données et l'écran tiennent le contrat de la VRAIE base, sans réseau.
//
// Références écrites (et revérifiées) par outils/tests/logistique-analytique-complete-essai.py sur un PostgreSQL jetable (001 à 029) :
//   · analytique-complete-rpc.json      : les signatures des sept fonctions lg_an_* ;
//   · analytique-complete-exemples.json : des réponses réelles (rapports par semaine et par jour, rapport incomplet, rapport d'avant 029,
//     indicateurs, exécutions, vérifications, alertes, acquittement, rapports vus par l'activité seule et par la finance seule).
// Ce qu'on éprouve : (1) trois implémentations, mêmes méthodes, ni démonstration ni site fermé ; (2) chaque appel respecte la signature, une
// période ou un grain invalide ne part pas ; (3) l'écran se dessine sur les réponses réelles sans lire une clé absente, sans « undefined » ni
// « NaN », en échappant tout ; ne calcule rien (totaux, stocks, clients distincts, dérivés viennent de la base) ; dit les jours manquants, anciens et le
// provisoire ; nomme chaque mesure, indicateur, famille, grain, verdict, statut, source, alerte ; (4) CSV sans formule possible et PDF avec la
// traçabilité ; (5) la page charge le script.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const SIG = JSON.parse(fs.readFileSync('outils/tests/analytique-complete-rpc.json', 'utf8'));
const EX = JSON.parse(fs.readFileSync('outils/tests/analytique-complete-exemples.json', 'utf8'));
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
  ok(M.join() === 'acquitter,alertes,executions,indicateurs,rapport,recalculer,verifier', 'sept méthodes');
  for (const [nom, api] of [['en ligne', en], ['démonstration', demo], ['fermé', off]]) ok(JSON.stringify(Object.keys(api.analytique).sort()) === JSON.stringify(M), nom + ' : mêmes méthodes');
  for (const m of M) {
    ok(await rejet(demo.analytique[m]('month', '2026-01-01', '2026-01-31')) === 'non-autorise', 'démonstration : ' + m + ' fermé (aucun chiffre inventé)');
    ok(await rejet(off.analytique[m]('month', '2026-01-01', '2026-01-31')) === 'ferme', 'site fermé : ' + m);
  }

  // ============================================================ 2. les appels respectent les signatures
  const vus = new Set();
  for (const [m, args] of [['rapport', ['week', '2026-01-01', '2026-03-31']], ['indicateurs', ['2026-01-01', '2026-01-31']], ['executions', [10]], ['recalculer', ['2026-01-01', '2026-01-31']], ['verifier', [12]],
    ['alertes', [true]], ['acquitter', [7, 'vu']]]) {
    faux.appels.length = 0; await en.analytique[m].apply(null, args);
    const a = faux.appels[0], sig = SIG[a.nom];
    ok(sig, m + ' : « ' + a.nom + ' » existe dans la base');
    Object.keys(a.args).forEach((k) => ok(sig.some((p) => p.nom === k), m + ' : paramètre inconnu ' + k));
    sig.filter((p) => !p.defaut).forEach((p) => ok(Object.prototype.hasOwnProperty.call(a.args, p.nom), m + ' : oublie ' + p.nom));
    vus.add(a.nom);
  }
  ok([...vus].sort().join() === Object.keys(SIG).sort().join(), 'le site appelle exactement les sept fonctions lg_an_*');
  faux.appels.length = 0;
  for (const [m, args, msg] of [['rapport', ['heure', '2026-01-01', '2026-01-02'], 'grain inconnu'], ['rapport', ['day', '01/01/2026', '2026-01-02'], 'date mal écrite'],
    ['indicateurs', ['2026-01-01', ''], 'date vide'], ['recalculer', [null, '2026-01-01'], 'sans début'], ['verifier', ['12; drop'], 'identifiant douteux'], ['verifier', [0], 'identifiant nul'],
    ['acquitter', ['3 or 1=1'], 'alerte douteuse'], ['acquitter', [-2], 'alerte négative']]) {
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
  const copie = (x, nom) => garde(JSON.parse(JSON.stringify(x)), nom);
  for (const nom of ['rapport_semaine', 'rapport_jour', 'rapport_trou', 'rapport_ancien', 'rapport_activite', 'rapport_finance']) {
    const r = copie(EX[nom], nom);
    sorties.push(A.entete(r), A.notes(r, true), A.tableaux(r), A.detail(r));
  }
  sorties.push(A.cartes(copie(EX.indicateurs, 'indicateurs')));
  sorties.push(A.journal(copie(EX.executions, 'executions'), true));
  for (const v of ['SOURCES_CHANGED', 'VERSION_CHANGED']) { A.etat.verdicts[EX.executions[0].run_id] = v; sorties.push(A.journal(copie(EX.executions, 'executions'), true)); }
  sorties.push(A.alertes(copie(EX.alertes, 'alertes'), true), A.alertes(copie(EX.alertes, 'alertes'), false));
  sorties.push(A.pdf(copie(EX.rapport_semaine, 'rapport_semaine'), copie(EX.indicateurs, 'indicateurs')));
  const tout = sorties.join('\n');
  ok(fautes.length === 0, 'aucune clé absente, aucun texte manquant : ' + fautes.slice(0, 5).join(' ; '));
  ok(!/undefined|NaN|\[object/.test(tout), 'ni « undefined », ni « NaN » à l\'écran');
  ok(EX.rapport_trou.missing_days.length > 0 && A.notes(EX.rapport_trou, true).includes('data-an-calculer') && !A.notes(EX.rapport_trou, false).includes('data-an-calculer'), 'des jours jamais calculés : signalés ; « Calculer ces jours » pour la direction seulement');
  ok(A.notes(EX.rapport_ancien, true).includes(echapper(textes['c-an-anciens'].split('{nombre}')[1].trim().slice(0, 20))) && EX.rapport_ancien.status === 'OUTDATED', 'des jours calculés par une ancienne version : signalés, à recalculer');
  ok(A.notes({ missing_days: [], stale_days: [], partial: true, runs: [] }, true).includes(echapper(textes['c-an-provisoire'])), 'une période provisoire le dit');
  ok(tout.includes(echapper(textes['c-an-v-SOURCES_CHANGED'])) && tout.includes(echapper(textes['c-an-v-VERSION_CHANGED'])), 'les verdicts d\'une vérification s\'affichent');
  // l'en-tête de traçabilité : statut, version, empreinte du rapport, exécutions
  const ent = A.entete(EX.rapport_semaine);
  ok(ent.includes(echapper(textes['c-an-st-COMPLETE'])) && ent.includes(EX.rapport_semaine.calc_version) && ent.includes(EX.rapport_semaine.report_checksum.slice(0, 16)) && ent.includes('n° ' + EX.rapport_semaine.runs[0].run_id),
     'l\'en-tête dit le statut, la version du calcul, l\'empreinte du rapport et ses exécutions');
  for (const st of ['COMPLETE', 'PROVISIONAL', 'INCOMPLETE', 'OUTDATED']) ok(('c-an-st-' + st) in textes, 'statut nommé : ' + st);
  ok(EX.rapport_trou.status === 'INCOMPLETE' && EX.rapport_semaine.status === 'COMPLETE', 'les exemples réels couvrent les statuts');
  for (const src of ['manual', 'scheduler', 'worker']) ok(('c-an-src-' + src) in textes, 'source nommée : ' + src);
  ok(A.journal(EX.executions, false).includes(echapper(textes['c-an-src-' + EX.executions[0].source])), 'le journal dit la source de chaque exécution');
  // pas une addition : chaque cellule vient d'un total ou d'un dérivé de la base
  const src = fs.readFileSync('assets/js/ses-analytique.js', 'utf8');
  ok(!/\+=\s*(Number|v\b|x\.value|r\.value)|reduce\(|Math\.(max|min)\(|\/\s*(Number|x\.|r\.|v\b)/.test(src), 'aucune addition ni division dans le navigateur : totaux, stocks, clients distincts et dérivés viennent de la base');
  const sem = EX.rapport_semaine, t0 = sem.totals.find((x) => x.metric === 'parcels_in_transit' && x.value !== null);
  ok(t0 && A.tableaux(sem).includes(echapper(A.valeur(t0.value, 'count'))), 'un stock de fin de période apparaît tel que la base le rend');
  const d0 = sem.derived[0];
  ok(d0 && A.tableaux(sem).includes(echapper(A.valeur(d0.values.margin_usd, 'usd'))) && A.tableaux(sem).includes(echapper(textes['c-an-r-margin_usd'])), 'la marge de la période : un dérivé de la base, affiché tel quel');
  ok(EX.rapport_trou.totals.some((x) => x.value === null) && A.tableaux(EX.rapport_trou).includes('—'), 'un stock inconnu s\'écrit « — »');
  // un texte hostile venant de la base est échappé
  const hostile = JSON.parse(JSON.stringify(EX.executions)); hostile[0].generated_by = '<img src=x onerror=alert(1)>';
  ok(!A.journal(hostile, false).includes('<img') && A.journal(hostile, false).includes('&lt;img'), 'ce qui vient de la base est échappé');
  const al = JSON.parse(JSON.stringify(EX.alertes)); al.items[0].note = '<script>x</script>'; al.items[0].acked_at = '2026-10-01T00:00:00Z';
  ok(!A.alertes(al, true).includes('<script>'), 'une note d\'alerte est échappée');
  // les noms : chaque mesure, indicateur, famille, grain, verdict, rapport type, alerte et sujet
  const mesures = sem.metrics.map((m) => m.code);
  ok(mesures.length === 42, 'l\'administrateur voit les quarante-deux mesures');
  for (const m of mesures) ok(('c-an-m-' + m) in textes, 'mesure nommée : ' + m);
  for (const r of Object.keys(EX.indicateurs.ratios_current)) ok(('c-an-r-' + r) in textes && r in A.RATIOS, 'indicateur nommé et rangé : ' + r);
  ok(Object.keys(A.RATIOS).sort().join() === Object.keys(EX.indicateurs.ratios_current).sort().join(), 'l\'écran connaît exactement les indicateurs que la base dérive');
  for (const f of A.FAMILLES) ok(('c-an-f-' + f) in textes, 'famille nommée : ' + f);
  ok([...new Set(sem.metrics.map((m) => m.family))].sort().join() === [...A.FAMILLES].sort().join(), 'les familles de l\'écran sont celles de la base');
  for (const g of en.GRAINS_ANALYTIQUE) ok(('c-an-g-' + g) in textes, 'grain nommé : ' + g);
  for (const v of ['REPRODUCIBLE', 'SOURCES_CHANGED', 'COMPUTATION_CHANGED', 'VERSION_CHANGED']) ok(('c-an-v-' + v) in textes, 'verdict nommé : ' + v);
  ok(EX.verification.verdict === 'REPRODUCIBLE' && EX.verification_version.verdict === 'VERSION_CHANGED', 'les exemples réels couvrent les verdicts');
  for (const r of A.RAPPORTS) ok(('c-an-type-' + r) in textes, 'rapport type nommé : ' + r);
  for (const c of ['KPI_IMPOSSIBLE', 'DATA_MISSING', 'REFRESH_NOT_RUN', 'REFRESH_FAILED', 'ANOMALY']) ok(('c-an-a-' + c) in textes, 'alerte nommée : ' + c);
  ok(new Set(EX.alertes.items.map((a) => a.code)).size >= 4, 'les exemples réels couvrent au moins quatre genres d\'alerte');
  const sujetsSql = fs.readFileSync('outils/logistique/029-analytique-complete.sql', 'utf8').match(/raise_alert\('[A-Z_]+', '[A-Z]+', '[a-z]+', '([a-z_]+)'/g).map((x) => x.split("', '")[3].replace("'", ''));
  for (const s_ of new Set(sujetsSql)) ok(!/^Sujet|^c-an-s-/.test(A.nomSujet(s_)) && (A.RATIOS[s_] || A.ORDRE.includes(s_) || ('c-an-s-' + s_) in textes), 'sujet d\'alerte nommé : ' + s_);
  ok(A.alertes(EX.alertes, true).includes('data-an-acquitter') && !A.alertes(EX.alertes, false).includes('data-an-acquitter'), '« Acquitter » : pour la direction seulement');
  ok(Object.keys(A.CARTES).every((f) => A.CARTES[f].mesures.every((m) => mesures.includes(m)) && A.CARTES[f].ratios.every((r) => r in EX.indicateurs.ratios_current)), 'les cartes ne citent que des mesures et des indicateurs que la base rend');
  ok(A.ORDRE.length === 42 && mesures.every((m) => A.ORDRE.includes(m)), 'chaque mesure a sa place dans l\'ordre de lecture');
  const tab = A.tableaux(sem);
  ok(tab.indexOf(echapper(textes['c-an-m-parcels_received'])) < tab.indexOf(echapper(textes['c-an-m-parcels_delivered'])), 'les lignes suivent l\'ordre de lecture (reçus avant livrés)');
  ok(!tab.includes(echapper(textes['c-an-m-deliveries_completed_zone'])) && A.detail(sem).includes(echapper(textes['c-an-detail-zone'])), 'les mesures par zone et par tournée vont dans le détail, pas dans le tableau de la famille');
  // les droits vus à l'écran : l'activité seule n'a ni argent ni clientèle ; la finance seule n'a pas le détail des livraisons
  const act = A.cartes({ domains: EX.rapport_activite.domains, current: {}, previous: {}, ratios_current: {}, ratios_previous: {} }) + A.tableaux(EX.rapport_activite);
  ok(!act.includes(echapper(textes['c-an-f-finance'])) && act.includes(echapper(textes['c-an-f-transport'])), 'activité seule : opérations, transport, dernier kilomètre ; pas de finance');
  ok(A.detail(EX.rapport_finance) === '' && A.tableaux(EX.rapport_finance).includes(echapper(textes['c-an-r-margin_usd'])), 'finance seule : la marge, pas le détail des livraisons');
  // le détail par chauffeur : le nom donné par la base, le taux de la base
  const ch = sem.breakdown.driver.find((x) => x.key !== '');
  ok(ch && A.detail(sem).includes(echapper(ch.label)) && A.detail(sem).includes(echapper(A.valeur(ch.success_pct, 'pct'))), 'le détail par chauffeur : son nom et son taux, tels que la base les rend');
  ok(A.detail(sem).includes(echapper(textes['c-an-sans-driver'])), 'une livraison sans chauffeur est dite « sans chauffeur »');
  // les rapports types : des bornes de dates, pas des chiffres
  const b = A.bornes;
  ok(b('daily', '2026-10-07').du === '2026-10-07' && b('weekly', '2026-10-07').du === '2026-10-05' && b('weekly', '2026-10-05').du === '2026-10-05' && b('monthly', '2026-10-07').du === '2026-10-01'
     && b('quarterly', '2026-10-07').du === '2026-10-01' && b('quarterly', '2026-08-15').du === '2026-07-01' && b('yearly', '2026-10-07').du === '2026-01-01' && b('yearly', '2026-10-07').au === '2026-10-07',
     'les bornes des rapports types : jour, semaine (lundi), mois, trimestre, année — jusqu\'à aujourd\'hui');
  // le PDF : le même rapport, avec sa traçabilité, sans rien d'exécutable
  const pdf = A.pdf(EX.rapport_semaine, EX.indicateurs);
  ok(pdf.includes(EX.rapport_semaine.report_checksum.slice(0, 16)) && pdf.includes(echapper(textes['c-an-pdf-pied'])) && !/<script|data-an-/.test(pdf), 'PDF : en-tête de traçabilité et pied de page, ni script ni bouton');
  // les valeurs
  ok(A.valeur(null, 'pct') === '—' && A.valeur(undefined, 'count') === '—', 'une valeur que la base n\'a pas pu calculer s\'écrit « — », jamais « 0 »');
  ok(A.valeur(75, 'pct').includes('75') && A.valeur(12.5, 'hours').includes('12,5'), 'pourcentages et heures mis en forme dans la langue');
  ok(A.nomPeriode('2026-07-01', 'quarter') === 'T3 2026' && A.nomPeriode('2026-01-01', 'year') === '2026', 'trimestre et année nommés');
  // le CSV
  const c = A.csv({ metrics: [{ code: 'payments_usd', unit: 'usd' }], rows: [{ period: '2026-09-01', metric: 'payments_usd', dimension: '=HYPERLINK("x")', value: 50 }], runs: [], derived: [] });
  ok(c.charCodeAt(0) === 0xfeff && c.includes('"\'=HYPERLINK(""x"")"') && c.includes('"usd"'), 'CSV : BOM, aucune formule, guillemets doublés, unité');
  const cs = A.csv(EX.rapport_semaine);
  ok(cs.includes(EX.rapport_semaine.report_checksum) && cs.includes(EX.rapport_semaine.calc_version) && cs.includes(echapper(textes['c-an-st-COMPLETE'])) && cs.includes('"margin_usd"') && cs.includes('"Jean Chauffeur"'),
     'CSV : la traçabilité en tête (empreinte, version, statut), les indicateurs dérivés, le nom des chauffeurs');
  ok(/<script src="assets\/js\/ses-analytique\.js\?v=\d+" defer><\/script>/.test(html), 'la page charge l\'analytique');
  console.log('PASS analytique : ' + n + ' vérifications — trois implémentations, signatures réelles, écran sur réponses réelles sans calcul ni trou, cinq familles, traçabilité, alertes, rapports types, CSV et PDF.');
})().catch((e) => { console.error('ÉCHEC analytique : ' + (e && e.message)); process.exit(1); });
