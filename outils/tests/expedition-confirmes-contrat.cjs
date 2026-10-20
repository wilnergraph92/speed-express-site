// Expédier les colis confirmés (étape 031) côté site, sans réseau, contre la VRAIE base :
//   expedition-confirmes-exemples.json, écrit par outils/tests/logistique-expedition-confirmes-essai.py (signatures de
//   lg_create_shipment_prepared et une réponse réelle de la fenêtre, avec ses colis « confirmed »).
// Ce qu'on éprouve : l'appel et ses paramètres ; la fenêtre « Nouvelle expédition » montre les colis confirmés et ne demande le lieu de
// préparation que si l'un d'eux est coché ; les textes ; le refus SE005 (un colis qui suit son expédition) a son message.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const EX = JSON.parse(fs.readFileSync('outils/tests/expedition-confirmes-exemples.json', 'utf8'));
const SIG = EX.signatures.lg_create_shipment_prepared;
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };
(async () => {
  const appels = [];
  const cfg = { supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai', centreNoyau: true };
  const fen = { addEventListener: () => {}, SES_CONFIG: cfg, supabase: { createClient: () => ({ auth: {}, rpc: (nom, args) => { appels.push({ nom, args });
    return Promise.resolve(nom === 'x' ? {} : { data: null, error: { code: 'SE005', message: 'Le colis SES-1 suit son expédition' } }); } }) } };
  const bac = { window: fen, location: { protocol: 'https:', hostname: 'exemple.fr', href: 'https://exemple.fr/x.html', pathname: '/x.html' },
    document: { documentElement: { lang: 'fr' }, currentScript: null }, console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), bac);
  const API = fen.SES_API;
  let code = null;
  try { await API.tableau.creerExpeditionPreparee({ code: 'EXP-1', mode: 'air', origine: 'o', destination: 'd', confirmes: ['c1'], entrepot: 'w', emplacement: 'l', cle: 'k' }); } catch (e) { code = e.code; }
  const a = appels[0];
  ok(a && a.nom === 'lg_create_shipment_prepared', 'creerExpeditionPreparee → lg_create_shipment_prepared');
  Object.keys(a.args).forEach((k) => ok(SIG.some((p) => p.nom === k), 'paramètre connu de la base : ' + k));
  SIG.filter((p) => !p.defaut).forEach((p) => ok(Object.prototype.hasOwnProperty.call(a.args, p.nom), 'paramètre exigé : ' + p.nom));
  ok(JSON.stringify(a.args.p_confirmed_ids) === '["c1"]' && a.args.p_warehouse_id === 'w' && a.args.p_location_id === 'l' && a.args.p_idempotency_key === 'k', 'les colis confirmés, le lieu de préparation, la clé du double clic');
  ok(code === 'colis-suit-expedition', 'SE005 devient « colis-suit-expedition »');
  // la réponse réelle de la fenêtre
  const c = EX.fenetre.confirmed;
  ok(Array.isArray(c) && ['parcels', 'consolidations', 'load_units', 'confirmed'].every((k) => k in EX.fenetre), 'la fenêtre rend aussi « confirmed »');
  if (c.length) ok(['parcel_id', 'tracking_number', 'status', 'customer', 'weight_lb', 'destination_country', 'destination_city'].every((k) => k in c[0]), 'un colis confirmé porte ce que la fenêtre lit');
  // l'écran
  const js = fs.readFileSync('assets/js/ses-modules.js', 'utf8'), html = fs.readFileSync('tableau-de-bord.html', 'utf8');
  ok(/name="confirme" value="' \+ e\(x\.parcel_id\)/.test(js) && /data-tout-confirmes/.test(js), 'la fenêtre liste les colis confirmés, avec « tout cocher »');
  ok(/id="cc-exp-lieu-prep" hidden/.test(js) && /var besoin = !!zonePret\.querySelector\('input\[name=confirme\]:checked'\);/.test(js), 'le lieu de préparation n\'apparaît que si un colis confirmé est coché');
  ok(/if \(confirmes\.length\) \{\s*if \(!f\.elements\.entrepot\.value \|\| !f\.elements\.emplacement\.value\) return 'c-exp-prep-lieu';/.test(js), 'sans lieu de préparation, rien ne part');
  const textes = {};
  for (const m of html.matchAll(/<span data-t="([^"]+)">([^<]*)<\/span>/g)) textes[m[1]] = m[2];
  for (const k of ['c-exp-confirmes', 'c-exp-confirmes-lieu', 'c-exp-sans-poids', 'c-exp-prep-lieu', 'erreur-colis-suit-expedition']) ok(k in textes, 'texte présent : ' + k);
  console.log('PASS expédier les colis confirmés (site) : ' + n + ' vérifications — appel et paramètres réels, fenêtre, lieu de préparation, textes, refus SE005.');
})().catch((e) => { console.error('ÉCHEC expédier les colis confirmés (site) : ' + (e && e.message)); process.exit(1); });
