// Le rapport d'une expédition et l'arrivée par pays et ville (étape 034) côté site, sans réseau, contre la VRAIE base :
//   rapport-expedition-exemples.json, écrit par outils/tests/logistique-rapport-expedition-essai.py (signature de lg_shipment_report, et deux
//   réponses réelles : la direction, qui lit les factures, et un employé, qui ne les lit pas).
// Ce qu'on éprouve : l'appel et ses paramètres ; le rapport se dessine sur les réponses réelles sans clé absente ni texte manquant ; il porte en
// tête le pays et la ville d'arrivée et la date de création, les colis classés par client (contenu, poids, livraison, paiement), le total et les
// deux signatures ; les montants n'apparaissent que si la base les a rendus ; tout ce qui vient de la base est échappé ; le formulaire choisit
// l'arrivée par pays puis par ville et refuse une ville sans HUB ; le rapport s'imprime dès la création, et depuis la fiche.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const EX = JSON.parse(fs.readFileSync('outils/tests/rapport-expedition-exemples.json', 'utf8'));
const SIG = EX.signatures.lg_shipment_report;
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };
(async () => {
  // ============================================================ 1. l'appel
  const appels = [];
  const fen = { addEventListener: () => {}, SES_CONFIG: { supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai' },
    supabase: { createClient: () => ({ auth: {}, rpc: (nom, args) => { appels.push({ nom, args }); return Promise.resolve({ data: {}, error: null }); } }) } };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), { window: fen, location: { protocol: 'https:', hostname: 'exemple.fr', href: 'https://exemple.fr/x.html', pathname: '/x.html' },
    document: { documentElement: { lang: 'fr' }, currentScript: null }, console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder });
  ok(fen.SES_API.METHODES_TABLEAU.includes('rapportExpedition'), 'la méthode est déclarée (trois implémentations)');
  await fen.SES_API.tableau.rapportExpedition('00000000-0000-0000-0000-000000000001');
  ok(appels[0].nom === 'lg_shipment_report' && JSON.stringify(Object.keys(appels[0].args)) === JSON.stringify(SIG.map((p) => p.nom)), 'rapportExpedition → lg_shipment_report(p_shipment_id)');

  // ============================================================ 2. le rapport, sur les réponses réelles
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
  const C = { enregistrer: () => {}, t: T, e: echapper, date: String, jour: String, nombre: (v) => String(v), montant: (v, d) => String(v) + ' ' + d, pays: (x) => ({ HT: 'Haïti', US: 'États-Unis', DO: 'République dominicaine' })[x] || x,
    pastille: (cle, code) => echapper(code), peutOuvrir: () => true, modules: () => [], accesTableau: () => ({ ops: true, direction: true }) };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-modules.js', 'utf8'), { window: { SES_API: fen.SES_API, SES_CENTRE: C, SES_UI: {} },
    document: { documentElement: { lang: 'fr' }, querySelector: () => null, addEventListener: () => {} }, Number, String, Object, Math, Date, JSON });
  const V = C.modulesVues;
  const r = EX.rapport, r2 = EX.rapport_sans_montants;
  const h = V.rapportHtml(garde(JSON.parse(JSON.stringify(r)), 'rapport'));
  const h2 = V.rapportHtml(garde(JSON.parse(JSON.stringify(r2)), 'rapport'));
  ok(!fautes.length, 'aucune clé absente, aucun texte manquant : ' + fautes.join(', '));
  ok(!/undefined|null|\[object/.test(h + h2), 'rien de « undefined » à l\'impression');
  const d = r.shipment.destination;
  const tete = h.slice(0, h.indexOf('<section'));
  ok(tete.includes('Haïti') && tete.includes(echapper(d.city)) && tete.includes(T('c-rap-destination')), 'en tête : le pays et la ville d\'arrivée');
  ok(tete.includes(echapper(r.shipment.code)) && tete.includes(T('c-rap-creee-le', { date: r.shipment.created_at })), 'en tête : le code et la date de création');
  ok((h.match(/<section/g) || []).length === r.customers.length && r.customers.every((c) => h.includes(echapper(c.name)) && (!c.code || h.includes(echapper(c.code)))),
     'une section par client, avec son nom et son code');
  for (const c of r.customers) {
    const sec = h.slice(h.indexOf(echapper(c.name)));
    ok(c.parcels.every((p) => sec.includes(echapper(p.tracking_number)) && sec.includes(echapper(p.contents))), 'les colis de ' + c.name + ' dans SA section, avec leur contenu');
  }
  for (const st of new Set(r.customers.flatMap((c) => c.parcels.map((p) => p.invoice.status)))) ok(h.includes(echapper(T('c-rap-pay-' + st))), 'le paiement « ' + st + ' » est écrit en clair');
  ok(h.includes(echapper(T('c-rap-total-expedie', { n: r.totals.parcels, poids: r.totals.weight_lb }))), 'le total des colis expédiés');
  ok(h.includes(echapper(T('c-rap-prepare-par'))) && h.includes(echapper(T('c-rap-chauffeur'))) && (h.match(new RegExp(echapper(T('c-rap-signature')), 'g')) || []).length === 2,
     'les deux signatures : l\'employé qui prépare, le chauffeur qui expédie');
  ok(r.shipment.prepared_by && h.includes(echapper(r.shipment.prepared_by)), 'le nom de qui a préparé, imprimé');
  ok(h.includes(echapper(T('c-rap-montant-total'))) && !h2.includes(echapper(T('c-rap-montant-total'))) && !h2.includes(echapper(T('c-rap-encaisse'))),
     'les montants seulement quand la base les rend (qui lit les factures)');
  const piege = JSON.parse(JSON.stringify(r));
  piege.customers[0].name = '<img src=x onerror=alert(1)>'; piege.customers[0].parcels[0].contents = '<script>x</script>';
  const hp = V.rapportHtml(piege);
  ok(!hp.includes('<img') && !hp.includes('<script>') && hp.includes('&lt;img'), 'tout ce qui vient de la base est échappé');

  // ============================================================ 3. le formulaire et l'impression
  const js = fs.readFileSync('assets/js/ses-modules.js', 'utf8');
  ok(/name="paysArrivee"/.test(js) && /c-exp-ville-arrivee/.test(js) && /b\.country === f\.elements\.paysArrivee\.value/.test(js), 'l\'arrivée se choisit par pays, puis par ville');
  ok(/if \(arrivee && arrivee\.kind !== 'hub'\) return 'c-exp-ville-pas-hub-bloque';/.test(js), 'une ville sans HUB : l\'écran dit quoi faire, rien ne part');
  ok(/ouvrirFiche\(rep\.shipment_id\); imprimerRapport\(rep\.shipment_id\);/.test(js), 'le rapport s\'imprime dès la création de l\'expédition');
  ok(/bouton\('exp-rapport', 'c-exp-rapport'/.test(js) && /C\.actions\['exp-rapport'\]/.test(js), 'et depuis la fiche, à tout moment');
  ok(/UI\.imprimer\(rapportHtml\(d\)\)/.test(js), 'par l\'impression A4 du site (PDF dans la fenêtre d\'impression, imprimante du système dans l\'application de bureau)');
  for (const k of ['c-exp-pays-arrivee', 'c-exp-ville-arrivee', 'c-exp-choisir-pays', 'c-exp-aucune-ville', 'c-exp-pas-hub-court', 'c-exp-ville-pas-hub', 'c-exp-ville-pas-hub-bloque', 'c-exp-rapport'])
    ok(k in textes, 'texte présent : ' + k);
  console.log('PASS rapport d\'expédition (site) : ' + n + ' vérifications — appel réel, rapport sur réponses réelles (arrivée en tête, classé par client, paiement, total, signatures, montants selon les droits, échappé), arrivée par pays et ville, impression à la création.');
})().catch((e) => { console.error('ÉCHEC rapport d\'expédition (site) : ' + (e && e.message)); process.exit(1); });
