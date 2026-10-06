// Le poste de scan du bureau (phase 15) : la couche de données et l'écran tiennent le contrat de la VRAIE base, sans réseau.
//
// Références écrites (et revérifiées) par outils/tests/logistique-applications-essai.py sur un PostgreSQL jetable :
//   · poste-rpc.json           : les signatures de lg_my_staff_profile et lg_scan_parcel ;
//   · applications-formes.json : la forme du profil, les intentions de scan et les verdicts que la base connaît.
// Ce qu'on éprouve : (1) trois implémentations, mêmes méthodes, ni la démonstration ni le site fermé n'ouvrent le poste ; (2) chaque appel
// respecte la signature, l'intention et la clé d'idempotence sont exigées avant tout appel ; (3) les intentions proposées existent dans la base
// et n'exigent pas d'emplacement ; (4) les fichiers : CSV sans formule ni accent cassé, liste importée nettoyée, plafonnée, sans doublon ;
// (5) la section : ouverte sur le droit « opérations », jamais de relecture automatique, le lecteur s'arrête en partant ; une lecture part
// avec l'entrepôt et l'intention choisis, une clé neuve à chaque lecture, la même clé quand on réessaie ; (6) chaque texte existe.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const SIG = JSON.parse(fs.readFileSync('outils/tests/poste-rpc.json', 'utf8'));
const FORMES = JSON.parse(fs.readFileSync('outils/tests/applications-formes.json', 'utf8'));
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
  const faux = { appels: [], reponse: {} };
  const cfg = { supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai' };
  const en = charger(cfg, 'exemple.fr', { window: { addEventListener: () => {}, SES_CONFIG: cfg, supabase: { createClient: () => ({ auth: {}, rpc: (nom, args) => { faux.appels.push({ nom, args }); return Promise.resolve({ data: faux.reponse, error: null }); } }) } } });
  const demo = charger({}, 'localhost'), off = charger({}, 'exemple.fr');
  const M = Array.from(en.METHODES_POSTE);
  ok(JSON.stringify(M.slice().sort()) === '["profil","scanner"]', 'deux méthodes');
  for (const [nom, api] of [['en ligne', en], ['démonstration', demo], ['fermé', off]]) ok(JSON.stringify(Object.keys(api.poste).sort()) === JSON.stringify(M.slice().sort()), nom + ' : mêmes méthodes');
  for (const m of M) {
    ok(await rejet(demo.poste[m]({})) === 'non-autorise', 'démonstration : ' + m + ' fermé (pas de noyau, pas de faux verdict)');
    ok(await rejet(off.poste[m]({})) === 'ferme', 'site fermé : ' + m);
  }

  // ============================================================ 2. les appels en ligne
  const verifier = (a, m) => {
    const sig = SIG[a.nom]; ok(sig, m + ' : « ' + a.nom + ' » existe dans la base');
    Object.keys(a.args).forEach((k) => ok(sig.some((p) => p.nom === k), m + ' : paramètre inconnu ' + k));
    sig.filter((p) => !p.defaut).forEach((p) => ok(Object.prototype.hasOwnProperty.call(a.args, p.nom), m + ' : oublie ' + p.nom));
    Object.keys(a.args).forEach((k) => ok(a.args[k] !== undefined, m + ' : ' + k + ' vaut undefined'));
  };
  faux.appels.length = 0; await en.poste.profil();
  ok(faux.appels.length === 1 && faux.appels[0].nom === 'lg_my_staff_profile' && Object.keys(faux.appels[0].args).length === 0, 'le profil : sans paramètre (la base lit le compte connecté)');
  const W = '00000000-0000-0000-0000-0000000000aa';
  faux.appels.length = 0; await en.poste.scanner({ code: 'N-001', intention: 'receive', entrepot: W, genre: 'barcode', cle: 'poste-abc-1', horodatage: '2026-10-06T10:00:00.000Z' });
  const a = faux.appels[0]; verifier(a, 'scanner');
  assert.deepEqual(JSON.parse(JSON.stringify(a.args)), { p_code: 'N-001', p_purpose: 'receive', p_warehouse_id: W, p_code_kind: 'barcode', p_idempotency_key: 'poste-abc-1',
    p_metadata: { source: 'desktop', recorded_at: '2026-10-06T10:00:00.000Z' } }, 'un scan : le texte lu, l\'intention, l\'entrepôt, le lecteur, la clé, et « bureau » comme source'); n++;
  faux.appels.length = 0; await en.poste.scanner({ code: 'N-001', intention: 'verify', entrepot: W, genre: 'rfid-pirate', cle: 'k-1' });
  ok(faux.appels[0].args.p_code_kind === 'unknown', 'un genre inconnu part « unknown »');
  faux.appels.length = 0;
  for (const [l, msg] of [[{ code: 'N', intention: 'store', entrepot: W, cle: 'k' }, 'rangement (exige un emplacement)'], [{ code: 'N', intention: 'pirater', entrepot: W, cle: 'k' }, 'intention inconnue'],
    [{ code: 'N', intention: 'receive', cle: 'k' }, 'sans entrepôt'], [{ code: 'N', intention: 'receive', entrepot: W }, 'sans clé d\'idempotence'], [undefined, 'rien']]) {
    ok(await rejet(en.poste.scanner(l)) === 'donnee-invalide', 'refusé avant tout appel : ' + msg);
  }
  ok(faux.appels.length === 0, 'aucun de ces refus n\'a atteint la base');

  // ============================================================ 3. les intentions
  ok(en.INTENTIONS_POSTE.every((x) => FORMES.scan_purposes.includes(x)), 'les intentions proposées existent dans la base : ' + en.INTENTIONS_POSTE);
  ok(!en.INTENTIONS_POSTE.includes('store') && !en.INTENTIONS_POSTE.includes('move'), 'ni rangement ni déplacement : ils exigent un emplacement que le poste ne demande pas');
  ok(FORMES.lg_my_staff_profile.includes('warehouses[].warehouse_id') && FORMES.lg_my_staff_profile.includes('warehouses[].code') && FORMES.lg_my_staff_profile.includes('profiles'), 'le profil rend ce que le poste lit');
  ok(FORMES.scan_parcel.includes('result') && FORMES.scan_parcel.includes('tracking_number'), 'le scan rend le verdict et le numéro que le poste affiche');

  // ============================================================ 4 et 5. l'écran, avec une fausse page
  const defs = [], appelsPoste = [], ecoute = {};
  const API = { INTENTIONS_POSTE: en.INTENTIONS_POSTE, poste: { scanner: (l) => { appelsPoste.push(l); return Promise.resolve({ result: l.code === 'X-404' ? 'UNKNOWN_PARCEL' : 'ACCEPTED', tracking_number: l.code === 'X-404' ? null : l.code }); }, profil: () => Promise.resolve(null) },
    notifications: { surveiller: () => () => {} } };
  const fen = { addEventListener: (ev, f) => { ecoute[ev] = f; }, SES_API: API, SES_UI: {}, SES_SCANNER: require('../../assets/js/ses-scanner.js'),
    SES_CENTRE: { enregistrer: (d) => defs.push(d), t: (k) => k, e: (x) => String(x), message: (er) => String(er && er.message), pastille: (k) => k, annoncer: () => {}, etat: () => {}, erreur: () => {} },
    localStorage: (() => { const m = {}; return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); } }; })() };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-poste.js', 'utf8'), { window: fen, document: { hidden: false, documentElement: { lang: 'fr' } }, URL, Blob: class {}, Promise, setTimeout, Date, Math, JSON, String, Number });
  const P = fen.SES_CENTRE.poste, def = defs[0];
  ok(def && def.id === 'poste', 'la section s\'inscrit dans le centre');
  ok(def.ouvrir({ ops: true }) === true && def.ouvrir({ ops: false }) === false && def.ouvrir(null) === false, 'ouverte sur le droit « opérations » annoncé par la base, et seulement lui');
  ok(def.actualiser() === undefined && typeof def.quitter === 'function', 'jamais de relecture automatique ; un « quitter » qui arrête le lecteur');
  ok(typeof ecoute.beforeinstallprompt === 'function', 'la proposition d\'installation du navigateur est gardée pour un bouton');

  // le CSV
  const c = P.csv([{ horodatage: 'h1', code: '=CMD()', intention: 'receive', entrepotCode: 'MIA-1', verdictTexte: 'Accepté', verdict: 'ACCEPTED', genre: 'barcode' },
    { horodatage: 'h2', code: 'N-"2"', intention: 'verify', entrepotCode: '-1', etat: 'erreur', genre: 'manual' }], { heure: 'Heure', numero: 'Numéro' });
  ok(c.charCodeAt(0) === 0xfeff, 'CSV : en-tête UTF-8 (les accents restent lisibles dans Excel)');
  ok(c.includes('"\'=CMD()"') && c.includes('"\'-1"') && !/(^|,)"=/m.test(c), 'CSV : une valeur qui commence par = + - @ ne devient jamais une formule');
  ok(c.includes('"N-""2"""'), 'CSV : guillemets doublés');
  ok(c.split('\r\n').length === 4 && c.includes('"Heure","Numéro"'), 'CSV : un en-tête traduit, une ligne par lecture, fins de ligne Windows');
  ok(c.includes('"erreur"'), 'CSV : une lecture qui n\'est pas partie le dit');
  // la liste importée
  const liste = P.lireListe('﻿numero;client\nN-001;Marie\nn-001\n  N-002 , x\n=CMD()\n\nab\nN 003\n"N-004"\n' + Array.from({ length: 700 }, (_, i) => 'Z-' + i).join('\n'));
  ok(liste[0] === 'N-001', 'un en-tête (« numero ») ne part jamais : un code inconnu ouvrirait un incident dans la base');
  ok(liste.slice(0, 3).join('|') === 'N-001|N-002|N-004', 'liste : sans doublon (casse ignorée), sans formule, sans texte trop court ni avec espace, guillemets retirés');
  // un export de ce poste se réimporte : on y retrouve les numéros, pas l'heure ni l'en-tête ni le code d'entrepôt
  const reimport = P.lireListe(P.csv([{ horodatage: '2026-10-06T10:00:00.000Z', code: 'SES-10001-HT', intention: 'receive', entrepotCode: 'MIA-1', verdict: 'ACCEPTED', genre: 'barcode' },
    { horodatage: '2026-10-06T10:00:01.000Z', code: 'N-7', intention: 'receive', entrepotCode: 'MIA-1', verdict: 'ACCEPTED', genre: 'barcode' }], { heure: 'Heure', numero: 'Numéro' }));
  ok(reimport.join('|') === 'SES-10001-HT|N-7', 'un export du poste se réimporte : ' + reimport.join('|'));
  ok(liste.length === P.MAX_IMPORT, 'liste : plafonnée à ' + P.MAX_IMPORT + ' numéros');
  ok(P.lireListe('').length === 0 && P.lireListe(null).length === 0, 'liste vide');
  // les lectures
  ok(!P.aEntrepot(null) && !P.aEntrepot({ staff: true, profiles: ['DRIVER'], warehouses: [{}] }) && !P.aEntrepot({ staff: true, profiles: ['WAREHOUSE_AGENT'], warehouses: [] }) &&
     P.aEntrepot({ staff: true, profiles: ['WAREHOUSE_AGENT'], warehouses: [{ warehouse_id: W }] }), 'le poste ne s\'ouvre qu\'au profil entrepôt AVEC un entrepôt');
  P.etat.profil = { staff: true, profiles: ['WAREHOUSE_AGENT'], warehouses: [{ warehouse_id: W, code: 'MIA-1', name: 'Miami' }, { warehouse_id: 'w2', code: 'MIA-2', name: 'Annexe' }] };
  P.etat.entrepot = 'w2'; P.etat.intention = 'verify';
  await P.lire('N-001', 'barcode'); await P.lire('N-001', 'barcode'); await P.lire('X-404', 'manual');
  ok(appelsPoste.length === 3 && appelsPoste.every((l) => l.entrepot === 'w2' && l.intention === 'verify'), 'chaque lecture part avec l\'entrepôt et l\'intention choisis');
  ok(new Set(appelsPoste.map((l) => l.cle)).size === 3 && appelsPoste.every((l) => /^poste-[a-z0-9]{8,16}-[a-z0-9]+-\d+$/.test(l.cle) && l.cle.length <= 80), 'une clé neuve à chaque lecture, courte et lisible');
  ok(P.etat.lectures[0].verdict === 'UNKNOWN_PARCEL' && P.etat.lectures[1].verdict === 'ACCEPTED' && P.etat.lectures[1].numero === 'N-001', 'le verdict de la base, la plus récente en tête');
  ok(FORMES.scan_results.includes(P.etat.lectures[0].verdict), 'un verdict que la base connaît');
  // réessayer = la même clé
  const avant = appelsPoste.length;
  API.poste.scanner = (l) => { appelsPoste.push(l); return Promise.reject(Object.assign(new Error('réseau'), { code: 'reseau' })); };
  await P.lire('N-009', 'barcode');
  const ratee = P.etat.lectures[0];
  ok(ratee.etat === 'erreur' && ratee.verdict === null, 'une coupure : la lecture est marquée « pas partie », sans verdict inventé');
  ok(appelsPoste.length === avant + 1, 'un seul appel');
  // sans profil : rien ne part
  const total = appelsPoste.length; P.etat.profil = { staff: true, profiles: ['DRIVER'], warehouses: [] };
  await P.lire('N-010', 'barcode');
  ok(appelsPoste.length === total, 'sans le profil entrepôt, aucune lecture ne part');
  ok(/data-poste-reessayer="' \+ e\(l\.cle\)/.test(fs.readFileSync('assets/js/ses-poste.js', 'utf8')) && /if \(l\) envoyer\(l\);/.test(fs.readFileSync('assets/js/ses-poste.js', 'utf8')), '« Réessayer » renvoie la lecture avec SA clé (la base ne compte pas deux scans)');

  // ============================================================ 6. les textes
  const src = fs.readFileSync('assets/js/ses-poste.js', 'utf8');
  const html = fs.readFileSync('tableau-de-bord.html', 'utf8');
  const cles = new Set([...src.matchAll(/t\('(c-[a-z0-9-]+)'/g)].map((m) => m[1]).filter((k) => !k.endsWith('-')));
  ['barcode', 'qr', 'manual', 'unknown'].forEach((g) => cles.add('c-poste-genre-' + g));
  en.INTENTIONS_POSTE.forEach((x) => cles.add('c-but-' + x));
  FORMES.scan_results.forEach((x) => cles.add('c-scan-' + x));
  cles.add('c-sec-poste');
  for (const k of cles) ok(html.includes('data-t="' + k + '"'), 'texte présent dans la page : ' + k);
  ok(cles.size > 40, 'les textes du poste sont relus (' + cles.size + ')');
  // la page charge le lecteur avant le poste, après le centre
  const ordre = ['ses-centre.js', 'ses-scanner.js', 'ses-poste.js'].map((f) => html.indexOf('assets/js/' + f));
  ok(ordre.every((i) => i > 0) && ordre[0] < ordre[1] && ordre[1] < ordre[2], 'la page charge le centre, puis le lecteur, puis le poste');
  ok(/<link rel="manifest" href="tableau-de-bord\.webmanifest">/.test(html), 'la page déclare son manifeste d\'installation');
  const man = JSON.parse(fs.readFileSync('tableau-de-bord.webmanifest', 'utf8'));
  ok(man.display === 'standalone' && man.start_url === 'tableau-de-bord.html' && man.icons.some((i) => i.sizes === '512x512') && man.icons.some((i) => i.sizes === '192x192'), 'manifeste : fenêtre à part, départ au tableau de bord, icônes 192 et 512');
  ok(man.icons.every((i) => fs.existsSync(i.src)), 'manifeste : les icônes existent');
  console.log('PASS poste de scan : ' + n + ' vérifications — trois implémentations, signatures de la base, intentions, CSV sans formule, liste importée nettoyée, clés d\'idempotence, section, textes, installation.');
})().catch((e) => { console.error('ÉCHEC poste de scan : ' + (e && e.message)); process.exit(1); });
