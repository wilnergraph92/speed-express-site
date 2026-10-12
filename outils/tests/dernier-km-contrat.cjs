// Le dernier kilomètre côté site (phase 5) : la couche de données et la section « Dernier kilomètre » du centre de commande, contre la VRAIE base.
//
// Références écrites (et revérifiées) par outils/tests/logistique-dernier-km-complet-essai.py : dernier-km-rpc.json (signatures des deux fonctions
// que le site appelle), dernier-km-exemple.json (une réponse réelle du tableau, après une journée de livraisons, d'échecs et d'incidents).
// Ce qu'on éprouve : (1) trois implémentations, mêmes méthodes ; ni la démonstration ni le site fermé n'inventent de chiffres ; (2) chaque appel vise
// une fonction et des paramètres qui existent ; (3) la section se dessine sur la réponse réelle sans lire une clé absente, sans texte manquant,
// sans « undefined » ni « NaN », et échappe tout ce qui vient de la base ; elle ne s'ouvre qu'avec le droit de lire les colis ; (4) le droit
// « livraisons.gerer » est proposé dans l'écran de l'équipe, et nommé ; (5) la page charge la section et la range dans la navigation.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const SIG = JSON.parse(fs.readFileSync('outils/tests/dernier-km-rpc.json', 'utf8'));
const EX = JSON.parse(fs.readFileSync('outils/tests/dernier-km-exemple.json', 'utf8'));
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };

function charger(config, hote, extra) {
  const bac = Object.assign({ window: { addEventListener: () => {}, SES_CONFIG: config }, location: { protocol: 'https:', hostname: hote, href: 'https://' + hote + '/x.html', pathname: '/x.html', origin: 'https://' + hote },
    document: { documentElement: { lang: 'fr' }, currentScript: null }, console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder }, extra || {});
  vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), bac);
  return bac.window.SES_API;
}
const rejet = async (p) => { try { await p; } catch (e) { return e.code; } return 'aucune-erreur'; };

(async () => {
  // ============================================================ 1 et 2. trois implémentations, signatures
  const faux = { appels: [] };
  const cfg = { supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai' };
  const client = { auth: {}, rpc: (nom, args) => { faux.appels.push({ nom, args }); return Promise.resolve({ data: { assigned: 0, unassigned: [] }, error: null }); } };
  const en = charger(cfg, 'exemple.fr', { window: { addEventListener: () => {}, SES_CONFIG: cfg, supabase: { createClient: () => client } } });
  const demo = charger({}, 'localhost'), off = charger({}, 'exemple.fr');
  const M = Array.from(en.METHODES_DERNIER_KM).sort();
  ok(M.join() === 'affecterJournee,tableau', 'deux méthodes');
  for (const [nom, api] of [['en ligne', en], ['démonstration', demo], ['fermé', off]]) ok(JSON.stringify(Object.keys(api.dernierKm).sort()) === JSON.stringify(M), nom + ' : mêmes méthodes');
  ok(await rejet(demo.dernierKm.tableau()) === 'non-autorise' && await rejet(demo.dernierKm.affecterJournee('2026-10-12')) === 'non-autorise', 'la démonstration n\'invente aucun chiffre');
  ok(await rejet(off.dernierKm.tableau()) === 'ferme' && await rejet(off.dernierKm.affecterJournee('2026-10-12')) === 'ferme', 'le site fermé : fermé');
  const vus = new Set();
  for (const [m, args] of [['tableau', []], ['tableau', ['2026-10-12']], ['affecterJournee', ['2026-10-12']]]) {
    faux.appels.length = 0; await en.dernierKm[m].apply(null, args);
    const a = faux.appels[0], sig = SIG[a.nom];
    ok(sig, m + ' : « ' + a.nom + ' » existe dans la base');
    Object.keys(a.args).forEach((k) => ok(sig.some((p) => p.nom === k), m + ' : paramètre inconnu ' + k));
    sig.filter((p) => !p.defaut).forEach((p) => ok(Object.prototype.hasOwnProperty.call(a.args, p.nom), m + ' : oublie ' + p.nom));
    vus.add(a.nom);
  }
  ok([...vus].sort().join() === Object.keys(SIG).sort().join(), 'le site appelle exactement les deux fonctions');
  faux.appels.length = 0; await en.dernierKm.tableau();
  ok(JSON.stringify(faux.appels[0].args) === '{}', 'sans date : la base prend le jour d\'Haïti (rien n\'est calculé ici)');

  // ============================================================ 3. la section, sur la réponse réelle
  const html = fs.readFileSync('tableau-de-bord.html', 'utf8');
  const textes = {};
  for (const m of html.matchAll(/<span data-t="([^"]+)">([^<]*)<\/span>/g)) textes[m[1]] = m[2];
  const fautes = [];
  const T = (k, v) => { if (!(k in textes)) fautes.push('texte absent : ' + k); let s = textes[k] || ''; Object.keys(v || {}).forEach((x) => { s = s.split('{' + x + '}').join(String(v[x])); }); return s; };
  function garde(x, chemin) {
    if (!x || typeof x !== 'object') return x;
    return new Proxy(x, { get(c, k) {
      if (typeof k === 'symbol' || ['toJSON', 'length', 'constructor', 'then'].includes(k)) return Reflect.get(c, k);
      if (Array.isArray(c) && (/^\d+$/.test(k) || k in Array.prototype)) { const v = Reflect.get(c, k); return typeof v === 'function' ? v.bind(c) : garde(v, chemin + '[]'); }
      if (!(k in c)) fautes.push('clé absente : ' + chemin + '.' + String(k));
      return garde(Reflect.get(c, k), chemin + '.' + String(k));
    } });
  }
  const echapper = (x) => String(x).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const defs = [], C = { enregistrer: (d) => defs.push(d), t: T, e: echapper, date: String, jour: String, pastille: (cle, code) => '<span>' + echapper(T(cle) || code) + '</span>' };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-dernier-km.js', 'utf8'), { window: { SES_API: en, SES_CENTRE: C }, document: { documentElement: { lang: 'fr' } }, Number, String, Object });
  const def = defs[0];
  ok(def && def.id === 'dernierkm' && def.ouvrir({ ops: true }) && !def.ouvrir({ finance: true, customers: true }) && !def.ouvrir(null), 'la section : pour qui lit les colis seulement');
  const zone = { innerHTML: '', querySelector: () => null };
  C.dernierKm.dessiner(zone, garde(JSON.parse(JSON.stringify(EX)), 'tableau'));
  ok(fautes.length === 0, 'sur la réponse réelle : aucune clé absente, aucun texte manquant — ' + fautes.slice(0, 4).join(' ; '));
  ok(!/undefined|NaN|\[object/.test(zone.innerHTML), 'ni « undefined » ni « NaN » ni objet affiché');
  ok(EX.in_progress.length > 0 && EX.failed.items.length > 0 && EX.drivers.items.length > 0 && EX.missing_pod.items.length > 0 && Object.keys(EX.incidents.by_type).length > 0,
     'l\'exemple réel remplit chaque partie de l\'écran (en cours, échecs, chauffeurs, dérogations, incidents)');
  for (const k of Object.keys(EX.incidents.by_type)) ok(('c-inc-' + k) in textes, 'genre d\'incident nommé : ' + k);
  for (const k of ['WRONG_PHONE', 'MISSING_PARCEL', 'DELIVERY_IMPOSSIBLE', 'CUSTOMER_ABSENT', 'WRONG_ADDRESS', 'REFUSED', 'DAMAGED']) ok(('c-inc-' + k) in textes, 'incident de livraison nommé : ' + k);
  for (const s of ['ACTIVE', 'MAINTENANCE', 'OUT_OF_SERVICE']) ok(('c-veh-' + s) in textes, 'statut de véhicule nommé : ' + s);
  ok(zone.innerHTML.includes(echapper(EX.drivers.items[0].name)) && zone.innerHTML.includes('80 %'), 'les chauffeurs et le taux à l\'heure (calculé par la base) s\'affichent');
  const hostile = JSON.parse(JSON.stringify(EX));
  hostile.in_progress[0].address = '<img src=x onerror=alert(1)>';
  hostile.drivers.items[0].name = '<script>x</script>';
  hostile.missing_pod.items[0].reason = '<b>gras</b>';
  C.dernierKm.dessiner(zone, hostile);
  ok(!zone.innerHTML.includes('<img') && !zone.innerHTML.includes('<script>') && !zone.innerHTML.includes('<b>') && zone.innerHTML.includes('&lt;img'), 'tout ce qui vient de la base est échappé');

  // ============================================================ 4. le droit du responsable de livraison
  ok(Array.from(en.DROITS).includes('livraisons.gerer') && Array.from(demo.DROITS).includes('livraisons.gerer'), 'le droit « livraisons.gerer » se coche dans l\'écran de l\'équipe');
  ok('droit-livraisons.gerer' in textes, 'et il est nommé');

  // le client voit, lui aussi, pourquoi sa livraison a échoué (portail : « incident-… »)
  const portail = fs.readFileSync('espace-client.html', 'utf8');
  for (const k of ['WRONG_PHONE', 'MISSING_PARCEL', 'DELIVERY_IMPOSSIBLE']) ok(portail.includes('data-t="incident-' + k + '"'), 'espace client : raison d\'échec nommée : ' + k);

  // ============================================================ 5. la page
  ok(/<script src="assets\/js\/ses-dernier-km\.js\?v=\d+" defer><\/script>/.test(html), 'la page charge la section');
  ok(/'livraisons', 'dernierkm'/.test(fs.readFileSync('assets/js/ses-centre.js', 'utf8')) && 'c-sec-dernierkm' in textes, 'la section est rangée dans « Opérations » et nommée');
  console.log('PASS dernier kilomètre (site) : ' + n + ' vérifications — trois implémentations, signatures réelles, section sur la réponse réelle (sans clé absente ni texte manquant, échappée), droit du responsable de livraison.');
})().catch((e) => { console.error('ÉCHEC dernier kilomètre (site) : ' + (e && e.message)); process.exit(1); });
