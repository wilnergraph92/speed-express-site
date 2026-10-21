// Le tableau de bord côté site (phase 7) : la barre des 26 modules, la couche de données SES_API.tableau et les sections nouvelles, contre la VRAIE base.
//
// Références écrites (et revérifiées) par outils/tests/logistique-tableau-essai.py : tableau-rpc.json (signatures), tableau-exemples.json (réponses réelles :
// modules d'un administrateur et d'un chauffeur, cartes temps réel, véhicules, tournées, dépenses, pointages, journée, relevé, missions).
// Ce qu'on éprouve : (1) trois implémentations, mêmes méthodes, ni la démonstration ni le site fermé n'inventent rien ; (2) chaque appel vise une fonction et
// des paramètres qui existent ; (3) la barre : les 26 modules dans l'ordre que la base connaît, chaque module du centre a des sections que ce site sait
// dessiner, chaque carte ouvre un module de la barre ; (4) chaque section se dessine sur la réponse réelle sans clé absente, sans texte manquant, sans
// « undefined » ni « NaN », et échappe tout ce qui vient de la base.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const SIG = JSON.parse(fs.readFileSync('outils/tests/tableau-rpc.json', 'utf8'));
const EX = JSON.parse(fs.readFileSync('outils/tests/tableau-exemples.json', 'utf8'));
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
  const cfg = { supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai', centreNoyau: true };
  const client = { auth: {}, rpc: (nom, args) => { faux.appels.push({ nom, args }); return Promise.resolve({ data: {}, error: null }); } };
  const en = charger(cfg, 'exemple.fr', { window: { addEventListener: () => {}, SES_CONFIG: cfg, supabase: { createClient: () => client } } });
  const demo = charger({}, 'localhost'), off = charger({}, 'exemple.fr');
  const M = Array.from(en.METHODES_TABLEAU);
  ok(M.length === 75, 'soixante-quinze méthodes');
  for (const [nom, api] of [['en ligne', en], ['démonstration', demo], ['fermé', off]]) ok(JSON.stringify(Object.keys(api.tableau).sort()) === JSON.stringify(M.slice().sort()), nom + ' : mêmes méthodes');
  for (const m of M) {
    ok(await rejet(demo.tableau[m]()) === 'non-autorise', 'démonstration : ' + m + ' ne répond rien (aucune donnée inventée)');
    ok(await rejet(off.tableau[m]()) === 'ferme', 'site fermé : ' + m);
  }
  const E = '00000000-0000-0000-0000-00000000000a', MI = '00000000-0000-0000-0000-00000000000c';
  const ARGS = { acces: [], commande: [], vehicules: [], tournees: ['2026-10-12'], depenses: [{ du: '2026-10-01', au: '2026-10-12', categorie: 'FUEL' }], pointages: [],
    ouvrirPointage: [{ genre: 'ARRIVAL', source: 'list', numeros: ['SES-1'] }], pointer: ['00000000-0000-0000-0000-000000000001', 'SES-1', 'barcode', 'k1'],
    detailPointage: ['00000000-0000-0000-0000-000000000001'], clorePointage: ['00000000-0000-0000-0000-000000000001', 'note'], horloge: ['IN'], maJournee: ['2026-10-12'],
    releve: ['2026-10-01', '2026-10-12'], corrigerPointage: ['00000000-0000-0000-0000-000000000001', 'IN', '2026-10-12T08:00:00Z', 'oubli'], mesMissions: [],
    creerChauffeur: [{ membre: '00000000-0000-0000-0000-000000000002', nom: 'Jean Chauffeur', telephone: '+509 3000 0000', vehicule: '00000000-0000-0000-0000-000000000003', arretsMax: '25' }],
    modifierChauffeur: ['00000000-0000-0000-0000-000000000004', { nom: 'Jean', permis: 'P-1', arretsMax: '20' }], statutChauffeur: ['00000000-0000-0000-0000-000000000004', 'ON_LEAVE', 'congé'],
    vehiculeChauffeur: ['00000000-0000-0000-0000-000000000004', null], creerVehicule: [{ plaque: 'AA-123', type: 'VAN', capaciteLb: '800', volume: '' }],
    statutVehicule: ['00000000-0000-0000-0000-000000000003', 'MAINTENANCE', 'vidange'],
    sites: [], creerAgence: [{ code: 'MIA', nom: 'Miami', genre: 'office', pays: 'US', ville: 'Miami' }], modifierAgence: ['00000000-0000-0000-0000-000000000005', { nom: 'Miami — Doral', actif: false }],
    creerEntrepot: ['00000000-0000-0000-0000-000000000005', { code: 'MIA-1', nom: 'Doral' }], modifierEntrepot: ['00000000-0000-0000-0000-000000000006', { actif: true }],
    creerEmplacement: ['00000000-0000-0000-0000-000000000006', { code: 'A-01', zone: 'A', genre: 'storage' }], emplacementActif: ['00000000-0000-0000-0000-000000000007', false],
    pret: ['air'], preparer: ['SES-1\nSES-2, SES-3', '00000000-0000-0000-0000-000000000006', '00000000-0000-0000-0000-000000000007'],
    creerExpedition: [{ code: 'EXP-1', mode: 'air', origine: '00000000-0000-0000-0000-000000000005', destination: '00000000-0000-0000-0000-000000000008', colis: ['00000000-0000-0000-0000-000000000009'], cle: 'k' }],
    colisExpedition: [E], ficheExpedition: [E], planifierExpedition: [E, '2026-10-14T12:00:00Z', '2026-10-14T18:00:00Z', '00000000-0000-0000-0000-000000000006'], expeditionPrete: [E],
    rouvrirExpedition: [E], partir: [E, '00000000-0000-0000-0000-00000000000b', 'k2'], enTransit: [E], arrivee: [E], commencerDouane: [E, 'DEC-1', 'Courtier'],
    fixerDroits: [E, '125.5', 'USD'], droitsPayes: [E], libererDouane: [E, 'ML-1'], rejeterDouane: [E, 'document manquant'], recevoirHub: [E, '00000000-0000-0000-0000-000000000006'],
    cloturerExpedition: [E], annulerExpedition: [E, 'erreur'],
    creerTransport: [{ mode: 'air', compagnie: 'Sunrise', reference: 'AWB-1', voyage: '2Q-1', origine: '00000000-0000-0000-0000-000000000005', destination: '00000000-0000-0000-0000-000000000008',
                       depart: '2026-10-14T12:00:00Z', arrivee: '2026-10-14T16:00:00Z', capaciteLb: '500', volume: '', vehicule: '' }],
    replanifierTransport: ['00000000-0000-0000-0000-00000000000b', '2026-10-15T12:00:00Z', '2026-10-15T16:00:00Z'],
    attenteHub: [], creerLivraison: [{ colis: ['00000000-0000-0000-0000-000000000009'], hub: '00000000-0000-0000-0000-000000000008', jour: '2026-10-14', destinataire: 'Marie',
                                       telephone: '+509', adresse: '3 rue Capois', code: true }],
    remettre: [['00000000-0000-0000-0000-000000000009'], 'Marie', 'CIN 1', ''], classerChauffeurs: [MI], affecter: [MI, '00000000-0000-0000-0000-00000000000d', true, 'seul disponible'],
    affecterAuto: [MI], codeLivraison: [MI], replanifierMission: [MI, '2026-10-15'], annulerMission: [MI, 'client absent'], missionsDuJour: ['2026-10-14'],
    creerTournee: ['00000000-0000-0000-0000-00000000000d', '2026-10-14', [MI]], annulerTournee: ['00000000-0000-0000-0000-00000000000e', 'véhicule en panne'],
    ouvrirConsolidation: [{ code: 'CONS-1', entrepot: '00000000-0000-0000-0000-000000000006', pays: 'HT', mode: 'air' }], remplirConsolidation: ['00000000-0000-0000-0000-00000000000f', 'SES-1\nSES-2'],
    colisConsolidation: ['00000000-0000-0000-0000-00000000000f'], retirerDeConsolidation: ['00000000-0000-0000-0000-00000000000f', '00000000-0000-0000-0000-000000000009'],
    fermerConsolidation: ['00000000-0000-0000-0000-00000000000f', 'k3'], unites: [{ status: 'OPEN' }], creerUnite: [{ code: 'PAL-1', genre: 'PALLET', poidsMax: '2000', volumeMax: '' }],
    chargerUnite: ['00000000-0000-0000-0000-00000000000f', '00000000-0000-0000-0000-000000000010'], retirerDeUnite: ['00000000-0000-0000-0000-00000000000f', 'mauvaise palette'],
    scellerUnite: ['00000000-0000-0000-0000-000000000010', 'SL-1'], ouvrirUnite: ['00000000-0000-0000-0000-000000000010', 'inspection'], attenteTransbordement: ['00000000-0000-0000-0000-000000000011'],
    etapeSuivante: [{ code: 'EXP-2', mode: 'ground', origine: '00000000-0000-0000-0000-000000000011', destination: '00000000-0000-0000-0000-000000000008', colis: ['00000000-0000-0000-0000-000000000009'], cle: 'k4' }],
    creerExpeditionPreparee: [{ code: 'EXP-3', mode: 'air', origine: '00000000-0000-0000-0000-000000000005', destination: '00000000-0000-0000-0000-000000000008',
                                confirmes: ['00000000-0000-0000-0000-000000000009'], entrepot: '00000000-0000-0000-0000-000000000006', emplacement: '00000000-0000-0000-0000-000000000007', cle: 'k5' }] };
  const vus = new Set();
  for (const m of M) {
    faux.appels.length = 0; await en.tableau[m].apply(null, ARGS[m]);
    ok(faux.appels.length > 0, m + ' : appelle la base');
    // une méthode peut enchaîner deux gestes de la base (« prête » = manifeste puis prête) : chacun est vérifié
    for (const a of faux.appels) {
      const sig = SIG[a.nom];
      ok(sig, m + ' : « ' + a.nom + ' » existe dans la base');
      Object.keys(a.args).forEach((k) => ok(sig.some((p) => p.nom === k), m + ' : paramètre inconnu ' + k));
      sig.filter((p) => !p.defaut).forEach((p) => ok(Object.prototype.hasOwnProperty.call(a.args, p.nom), m + ' : oublie ' + p.nom));
      vus.add(a.nom);
    }
  }
  ok([...vus].sort().join() === Object.keys(SIG).sort().join(), 'le site appelle exactement les fonctions de la base');

  // ============================================================ 3. la barre : les 27 modules de la base, moins les cinq retirés
  // Retirés de la barre par le propriétaire (20/10/2026) : la base les ouvre toujours, rien n'est effacé ; le site ne les montre plus.
  const RETIRES = ['entrepots', 'consolidations', 'transport', 'douane', 'pointage'];
  const RELAIS = { transport: 'expeditions', douane: 'expeditions', consolidations: 'expeditions', entrepots: 'expeditions' };
  const html = fs.readFileSync('tableau-de-bord.html', 'utf8');
  const onglets = [...html.matchAll(/<button type="button" role="tab" id="(ses-o-[a-z-]+)" aria-controls="([a-z-]+)"[^>]*data-module="([a-z-]+)"(?: data-sections="([a-z -]+)")?[^>]*>/g)]
    .map((m) => ({ id: m[1], panneau: m[2], module: m[3], sections: m[4] ? m[4].split(' ') : null }));
  ok(EX.acces.modules.length === 27 && RETIRES.every((m) => EX.acces.modules.includes(m)) && EX.acces.modules.includes('messagerie'), 'la base connaît ses 27 modules (messagerie comprise, 032), les cinq retirés compris');
  ok(onglets.length === 22, '22 entrées dans la barre (' + onglets.length + ')');
  ok(JSON.stringify(onglets.map((o) => o.module)) === JSON.stringify(EX.acces.modules.filter((m) => !RETIRES.includes(m))),
     'la barre suit EXACTEMENT les modules et l\'ordre que la base connaît, moins les cinq retirés (administrateur)');
  const centreJs = fs.readFileSync('assets/js/ses-centre.js', 'utf8');
  const retirees = JSON.parse((/var SECTIONS_RETIREES = (\[[^\]]*\])/.exec(centreJs) || [, '[]'])[1].replace(/'/g, '"'));
  ok(retirees.sort().join() === ['consolidations', 'douane', 'entrepot', 'pointage', 'transport', 'unites'].join(), 'les sections des modules retirés ne se dessinent plus (' + retirees + ')');
  ok(!retirees.includes('sites') && /id="ses-reglages-sites"/.test(html) && /location\.hash = '#centre\/sites'/.test(centreJs), 'les agences et entrepôts restent ouverts, depuis Paramètres');
  const enregistrees = new Set();
  for (const f of ['ses-centre-vues.js', 'ses-modules.js', 'ses-poste.js', 'ses-bureau.js', 'ses-analytique.js', 'ses-sante.js', 'ses-dernier-km.js', 'ses-messagerie.js']) {
    for (const m of fs.readFileSync('assets/js/' + f, 'utf8').matchAll(/enregistrer\(\{\s*id: '([a-z-]+)'/g)) enregistrees.add(m[1]);
  }
  for (const o of onglets.filter((x) => x.sections)) {
    ok(o.panneau === 'ses-p-centre' && o.sections.every((s) => enregistrees.has(s)), o.module + ' : chaque section existe (' + o.sections.filter((s) => !enregistrees.has(s)) + ')');
  }
  for (const o of onglets.filter((x) => !x.sections)) ok(html.includes('id="' + o.panneau + '"'), o.module + ' : son panneau existe');
  ok(EX.acces_chauffeur.modules.filter((m) => !RETIRES.includes(m)).every((m) => onglets.some((o) => o.module === m)), 'chaque module du chauffeur a son entrée');
  // Une carte d'un module retiré sans relais (le Pointage Express) reste affichée, sans lien.
  for (const c of EX.commande.cards) ok(onglets.some((o) => o.module === (RELAIS[c.module] || c.module)) || (RETIRES.includes(c.module) && !RELAIS[c.module]),
                                       'la carte « ' + c.key + ' » ouvre un module de la barre (' + (RELAIS[c.module] || c.module) + ')');
  ok(/<script src="assets\/js\/ses-modules\.js\?v=\d+" defer><\/script>/.test(html), 'la page charge les sections nouvelles');

  // ============================================================ 4. les sections, sur les réponses réelles
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
  const fauxOnglets = onglets.map((o) => ({ id: o.id, hidden: false, hasAttribute: (a) => a === 'data-sections' ? !!o.sections : false, getAttribute: (a) => a === 'data-sections' ? (o.sections || []).join(' ') : (a === 'data-module' ? o.module : null) }));
  const doc = { documentElement: { lang: 'fr' }, querySelector: (s) => { const m = /data-module="([a-z-]+)"/.exec(s); return m ? fauxOnglets.find((o) => o.getAttribute('data-module') === m[1]) || null : null; },
    addEventListener: () => {} };
  const defs = [];
  const C = {
    enregistrer: (d) => defs.push(d), t: T, e: echapper, date: String, jour: String, nombre: (v) => String(v), montant: (v, d) => String(v) + ' ' + d, age: () => '1 h',
    pastille: (cle, code) => '<span>' + echapper(T(cle) || code) + '</span>', peutOuvrir: () => true, entrepots: () => [{ warehouse_id: 'w1', code: 'W1', name: 'Entrepôt' }],
    modules: () => EX.acces.modules, accesTableau: () => EX.acces,
    tableau: (colonnes, lignes, opts) => { T(opts.legende); return '<table>' + colonnes.map((c) => '<th>' + echapper(T(c.t)) + '</th>').join('') + lignes.map((l, i) => '<tr>' + colonnes.map((c) => '<td>' + c.rendre(l, i) + '</td>').join('') + '</tr>').join('') + '</table>'; }
  };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-modules.js', 'utf8'), { window: { SES_API: en, SES_CENTRE: C }, document: doc, Number, String, Object, Math, Date });
  ok(defs.map((d) => d.id).sort().join() === 'depenses,mes-missions,pointage,sites,temps-reel,tournees,unites,vehicules', 'huit sections nouvelles inscrites');
  const V = C.modulesVues;
  const zone = () => ({ innerHTML: '', querySelector: () => null });
  const essais = [
    ['cartes (administrateur)', (z) => V.dessinerCartes(z, garde(JSON.parse(JSON.stringify(EX.commande)), 'commande'))],
    ['cartes (chauffeur)', (z) => V.dessinerCartes(z, garde(JSON.parse(JSON.stringify(EX.commande_chauffeur)), 'commande'))],
    ['véhicules', (z) => V.dessinerVehicules(z, garde(JSON.parse(JSON.stringify(EX.vehicules)), 'vehicules'))],
    ['tournées', (z) => V.dessinerTournees(z, garde(JSON.parse(JSON.stringify(EX.tournees)), 'tournees'))],
    ['dépenses', (z) => V.dessinerDepenses(z, garde(JSON.parse(JSON.stringify(EX.depenses)), 'depenses'))],
    ['ma journée', (z) => V.dessinerPersonnel(z, garde(JSON.parse(JSON.stringify(EX.journee)), 'journee'), { du: '2026-10-01', au: '2026-10-12' })],
    ['relevé', (z) => V.dessinerReleve(z, garde(JSON.parse(JSON.stringify(EX.releve)), 'releve'))],
    ['pointages', (z) => V.dessinerColis(z, garde(JSON.parse(JSON.stringify(EX.pointages)), 'pointages'))],
    ['pointage ouvert', (z) => V.dessinerSession(z, garde(JSON.parse(JSON.stringify(EX.pointage)), 'pointage'), { result: 'CHECKED', tracking_number: 'SES-1' })],
    ['pointage clos', (z) => V.dessinerSession(z, garde(JSON.parse(JSON.stringify(EX.pointage_clos)), 'pointage_clos'), null)],
    ['mes missions', (z) => V.dessinerMissions(z, garde(JSON.parse(JSON.stringify(EX.missions)), 'missions'))],
    ['agences et entrepôts', (z) => V.dessinerSites(z, garde(JSON.parse(JSON.stringify(EX.sites)), 'sites'))],
    ['unités logistiques', (z) => V.dessinerUnites(z, garde(JSON.parse(JSON.stringify(EX.unites)), 'unites'))]
  ];
  for (const [nom, f] of essais) {
    const z = zone(); fautes.length = 0; f(z);
    ok(fautes.length === 0, nom + ' : aucune clé absente, aucun texte manquant — ' + fautes.slice(0, 4).join(' ; '));
    ok(!/undefined|NaN|\[object/.test(z.innerHTML) && z.innerHTML.length > 50, nom + ' : ni « undefined », ni « NaN », et quelque chose à l\'écran');
  }
  ok(EX.sites.branches.length > 0 && EX.sites.branches.some((b) => b.warehouses.length) && EX.sites.can_manage === true, 'les agences réelles de l\'essai, gérables par la direction');
  ok(EX.missions.length > 0 && EX.tournees.items.length > 0 && EX.pointage.extra.length > 0 && EX.releve.rows.length > 0, 'les exemples réels remplissent chaque écran');
  // ce qui vient de la base est échappé
  const h = JSON.parse(JSON.stringify(EX.vehicules)); h.items[0].plate = '<img src=x onerror=alert(1)>'; h.items[0].drivers = ['<b>x</b>'];
  const z = zone(); V.dessinerVehicules(z, h);
  ok(!z.innerHTML.includes('<img') && !z.innerHTML.includes('<b>') && z.innerHTML.includes('&lt;img'), 'tout ce qui vient de la base est échappé');
  // la carte ouvre son module
  const zc = zone(); V.dessinerCartes(zc, EX.commande);
  ok(/href="#centre\/livraisons"/.test(zc.innerHTML) && /href="#colis"/.test(zc.innerHTML), 'une carte ouvre son module (centre ou ancien schéma)');
  ok(!/#centre\/(douane|transport|consolidations|entrepot|pointage)\b/.test(zc.innerHTML) && (!EX.commande.cards.some((c) => RELAIS[c.module]) || /href="#centre\/expeditions"/.test(zc.innerHTML)),
     'une carte d\'un module retiré ouvre les Expéditions');
  console.log('PASS tableau de bord (site) : ' + n + ' vérifications — trois implémentations, signatures réelles, 22 modules dans l\'ordre de la base (5 retirés), sections et cartes sur réponses réelles (sans clé absente ni texte manquant, échappées).');
})().catch((e) => { console.error('ÉCHEC tableau de bord (site) : ' + (e && e.message)); process.exit(1); });
