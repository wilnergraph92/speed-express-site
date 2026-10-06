// Le centre de commande côté navigateur : la couche de données et les sections tiennent le contrat de la VRAIE base.
//
// Aucun réseau. Trois références écrites (et revérifiées) par outils/tests/logistique-centre-essai.py sur un PostgreSQL jetable :
//   · centre-rpc.json      : les 28 fonctions de la façade, avec le nom et le caractère facultatif de chaque paramètre ;
//   · centre-exemples.json : une réponse réelle de chaque fonction ;
//   · centre-enums.json    : les valeurs que la base connaît.
// Ce qu'on éprouve : (1) les trois implémentations ont les mêmes méthodes, et ni la démonstration ni le site fermé n'ouvrent le centre ;
// (2) chaque appel de la version en ligne vise une fonction et des paramètres qui existent, sans oublier un obligatoire ; (3) l'interrupteur et
// le repli ; (4) chaque section se dessine sur la réponse réelle sans lire une seule clé que la base ne renvoie pas, sans « undefined » ni
// « NaN » à l'écran, et en échappant tout ce qui vient de la base.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const SIGNATURES = JSON.parse(fs.readFileSync('outils/tests/centre-rpc.json', 'utf8'));
const EXEMPLES = JSON.parse(fs.readFileSync('outils/tests/centre-exemples.json', 'utf8'));
let n = 0; const ok = () => { n++; };

function charger(config, hote, extra) {
  const bac = Object.assign({ window: { addEventListener: () => {}, SES_CONFIG: config }, location: { protocol: 'https:', hostname: hote, href: 'https://' + hote + '/x.html', pathname: '/x.html' },
    document: { documentElement: { lang: 'fr' }, currentScript: null }, console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder }, extra || {});
  vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), bac);
  return bac.window.SES_API;
}
const rejet = async (p) => { try { await p; } catch (e) { return e.code; } return 'aucune-erreur'; };

(async () => {
  // =============================================================== 1. les trois implémentations : mêmes méthodes, et seule la version en ligne ouvre le centre
  const demo = charger({ centreNoyau: true }, 'localhost');
  const off = charger({ centreNoyau: true }, 'exemple.fr');
  const faux = { appels: [], reponses: {}, erreurs: {} };
  faux.rpc = function (nom, args) {
    faux.appels.push({ nom, args });
    if (faux.erreurs[nom]) return Promise.resolve({ data: null, error: faux.erreurs[nom] });
    return Promise.resolve({ data: faux.reponses[nom] === undefined ? {} : faux.reponses[nom], error: null });
  };
  const cfg = { supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai', centreNoyau: true };
  const enLigne = (c) => charger(c, 'exemple.fr', { window: { addEventListener: () => {}, SES_CONFIG: c, supabase: { createClient: () => ({ auth: {}, rpc: faux.rpc }) } } });
  const en = enLigne(cfg);
  assert.equal(demo.mode, 'demo'); assert.equal(off.mode, 'off'); assert.equal(en.mode, 'supabase'); ok();
  const METHODES = Array.from(en.METHODES_CENTRE);
  assert.equal(METHODES.length, 13); ok();
  for (const [nom, api] of [['démonstration', demo], ['fermé', off], ['en ligne', en]]) {
    assert.deepEqual(Object.keys(api.centre).sort(), METHODES.slice().sort(), nom + ' : mêmes méthodes'); ok();
  }
  assert.deepEqual(JSON.parse(JSON.stringify(await demo.centre.disponible())), { actif: false, raison: 'demo' }, 'pas de centre de commande en démonstration : ses chiffres ne seraient pas réels'); ok();
  assert.deepEqual(JSON.parse(JSON.stringify(await off.centre.disponible())), { actif: false, raison: 'off' }); ok();
  for (const m of METHODES.filter((x) => x !== 'disponible')) {
    assert.equal(await rejet(demo.centre[m]('colis', {})), 'non-autorise', 'démonstration : ' + m);
    assert.equal(await rejet(off.centre[m]('colis', {})), 'ferme', 'fermé : ' + m);
  }
  ok();

  // =============================================================== 2. en ligne : chaque appel respecte la signature de la base
  const ID = '00000000-0000-0000-0000-000000000001';
  const FILTRES = { pays: 'HT', ville: 'Delmas', entrepot: ID, statut: 'ON_HOLD', service: 'air', client: 'SES-1', du: '2026-10-01', au: '2026-10-05' };
  const appels = [['acces', []], ['indicateurs', [FILTRES]], ['aTraiter', []], ['entrepot', [FILTRES]], ['colisDetail', ['N-1']], ['ticket', [ID]], ['reglages', []],
    ['traiterEnlevement', [ID, { approuver: true, message: 'm', date: '2026-12-01' }]], ['traiterEnlevement', [ID, { approuver: false, message: 'non' }]],
    ['traiterLivraison', [ID, { approuver: true, hub: ID, date: '2026-12-01' }]], ['repondreTicket', [ID, 'Bonjour']], ['fermerTicket', [ID]]]
    .concat(Object.keys(en.VUES_CENTRE).map((v) => ['liste', [v, FILTRES, { limite: 25, decalage: 50 }]]));
  const vues = new Set();
  for (const [m, args] of appels) {
    faux.appels.length = 0;
    await en.centre[m].apply(null, args);
    assert.equal(faux.appels.length, 1, m); const a = faux.appels[0];
    const sig = SIGNATURES[a.nom];
    assert.ok(sig, m + ' appelle « ' + a.nom + ' », que la base ne connaît pas');
    const noms = sig.map((p) => p.nom);
    Object.keys(a.args).forEach((k) => assert.ok(noms.indexOf(k) >= 0, m + ' envoie « ' + k + ' » : ' + a.nom + ' ne connaît pas ce paramètre'));
    sig.filter((p) => !p.defaut).forEach((p) => assert.ok(Object.prototype.hasOwnProperty.call(a.args, p.nom), m + ' oublie le paramètre obligatoire « ' + p.nom + ' » de ' + a.nom));
    Object.keys(a.args).forEach((k) => assert.notEqual(a.args[k], undefined, m + ' : « ' + k + ' » vaut undefined'));
    assert.ok(!noms.some((x) => /actor|user|uid/.test(x)), a.nom + ' : aucune fonction ne prend l\'acteur en paramètre');
    vues.add(a.nom);
  }
  ok();
  assert.deepEqual(Array.from(vues).sort(), Object.keys(SIGNATURES).sort(), 'le site appelle exactement les 28 fonctions de la façade, ni plus ni moins'); ok();
  // Les filtres partent sous les noms de la base, et un filtre vide ne part pas.
  faux.appels.length = 0; await en.centre.liste('colis', FILTRES, { limite: 25, decalage: 0 });
  assert.deepEqual(JSON.parse(JSON.stringify(faux.appels[0].args.p_filters)), { country: 'HT', city: 'Delmas', warehouse_id: ID, status: 'ON_HOLD', service: 'air', customer: 'SES-1', from: '2026-10-01', to: '2026-10-05' }); ok();
  faux.appels.length = 0; await en.centre.liste('colis', { pays: '', ville: '   ', client: null, statut: 'X' }, {});
  assert.deepEqual(JSON.parse(JSON.stringify(faux.appels[0].args)), { p_filters: { status: 'X' } }, 'vide, espaces, null : pas envoyés ; ni limite ni décalage non plus'); ok();
  // Les noms de filtres de la base sont exactement ceux que 009 accepte (un filtre inconnu y est une erreur).
  const sql = fs.readFileSync('outils/logistique/009-centre-de-commande.sql', 'utf8');
  const acceptes = /if k not in \(([^)]+)\) then raise exception 'Filtre inconnu/.exec(sql)[1].split(',').map((x) => x.trim().replace(/'/g, '')).sort();
  assert.deepEqual(Object.values(en.FILTRES_CENTRE).sort(), acceptes); ok();
  assert.equal(await rejet(en.centre.liste('inexistante', {})), 'donnee-invalide', 'une vue inconnue ne part pas vers la base'); ok();
  // Traiter une demande : refuser envoie p_approve = false, jamais « undefined »
  faux.appels.length = 0; await en.centre.traiterEnlevement(ID, {});
  assert.deepEqual(JSON.parse(JSON.stringify(faux.appels[0].args)), { p_id: ID, p_approve: false }); ok();

  // =============================================================== 3. l'interrupteur et le repli sûr
  const dispo = async (c, err) => {
    faux.reponses = { lg_cc_access: EXEMPLES.acces }; faux.erreurs = err ? { lg_cc_access: err } : {};
    return JSON.parse(JSON.stringify(await enLigne(Object.assign({}, cfg, c)).centre.disponible()));
  };
  assert.deepEqual(await dispo({ centreNoyau: false }), { actif: false, raison: 'drapeau' }, 'interrupteur éteint : l\'onglet reste caché'); ok();
  faux.appels.length = 0; await dispo({ centreNoyau: false });
  assert.equal(faux.appels.length, 0, 'interrupteur éteint : AUCUN appel à la base'); ok();
  assert.equal((await dispo({})).actif, true); assert.deepEqual((await dispo({})).acces, EXEMPLES.acces); ok();
  assert.deepEqual(await dispo({}, { code: 'PGRST202', message: 'Could not find the function public.lg_cc_access' }), { actif: false, raison: 'absent' }, 'migration 009 pas passée : repli'); ok();
  assert.deepEqual(await dispo({}, { code: 'LG003', message: 'Aucun droit' }), { actif: false, raison: 'refuse' }, 'compte sans droit : repli'); ok();
  assert.deepEqual(await dispo({}, { code: 'XX000', message: 'panne' }), { actif: false, raison: 'erreur' }); ok();
  faux.erreurs = {};

  // =============================================================== 4. chaque section se dessine sur la réponse réelle
  // Une réponse « gardée » : lire une clé qu'elle n'a pas est une faute (la section afficherait un trou, ou se trompe de nom de champ).
  const fautes = [];
  const FACULTATIVES = new Set(['revenue_period_usd']);    // présente seulement quand une période est demandée — le code la teste
  function garde(x, chemin) {
    if (!x || typeof x !== 'object') return x;
    return new Proxy(x, { get(cible, cle) {
      const v = Reflect.get(cible, cle);
      if (typeof cle === 'symbol' || Array.isArray(cible) || cle in Object.prototype || cle === 'toJSON' || cle === 'then') return typeof v === 'object' ? garde(v, chemin + '.' + String(cle)) : v;
      if (!Object.prototype.hasOwnProperty.call(cible, cle) && !FACULTATIVES.has(cle)) fautes.push(chemin + '.' + cle);
      return garde(v, chemin + '.' + cle);
    } });
  }
  const echapper = (v) => String(v === null || v === undefined ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  // Une petite zone d'écran factice : ce que la section y écrit est relu par le test.
  function Zone() { this.innerHTML = ''; this.enfants = {}; this.ecouteurs = {}; this.elements = { message: { value: '' }, date: { value: '' } }; }
  Zone.prototype.querySelector = function (s) { return (this.enfants[s] = this.enfants[s] || new Zone()); };
  Zone.prototype.querySelectorAll = function () { return []; };
  Zone.prototype.addEventListener = function (type, fn) { this.ecouteurs[type] = fn; };
  Zone.prototype.setAttribute = Zone.prototype.removeAttribute = function () {};
  const texteDe = (z) => z.innerHTML + Object.values(z.enfants).map(texteDe).join('');
  const reponse = (cle) => Promise.resolve(garde(JSON.parse(JSON.stringify(EXEMPLES[cle])), cle));
  const API = { centre: {
    indicateurs: () => reponse('indicateurs'), aTraiter: () => reponse('a_traiter'), entrepot: () => reponse('entrepot'), reglages: () => reponse('reglages'),
    colisDetail: () => reponse('fiche_colis'), ticket: () => reponse('fiche_ticket'),
    liste: (vue) => reponse({ tickets: 'tickets', factures: 'factures' }[vue] || vue)
  } };
  const C = { vues: [], actions: {}, t: (cle, v) => cle + (v ? JSON.stringify(v) : ''), e: echapper,
    enregistrer(def) { C.vues.push(def); }, peutOuvrir: () => true, acces: () => EXEMPLES.acces, lien: (id, f) => '#centre/' + id + '?' + JSON.stringify(f || {}),
    pastille: (cle, code) => '<span>' + echapper(cle) + echapper(code) + '</span>', pays: (c) => c || '', nombre: (x) => { assert.ok(x !== undefined && !Number.isNaN(Number(x)), 'nombre illisible : ' + x); return String(x); },
    date: (x) => (x ? String(x) : '—'), jour: (x) => (x ? String(x) : '—'), montant: (v, d) => { assert.ok(d, 'montant sans devise'); return String(v) + ' ' + d; }, age: (x) => 'âge(' + x + ')',
    tableau: (cols, lignes) => cols.map((c) => c.t + ':' + lignes.map((l, i) => c.rendre(l, i)).join('|')).join('\n'),
    barreFiltres: () => '', charger: (zone, appel, dessiner) => appel().then(dessiner), dialogue: () => new Zone(), fermerDialogue() {}, annoncer() {}, rafraichir() {}, message: () => 'erreur', etats: {} };
  const bac = { window: { SES_CENTRE: C, SES_API: API, SES_UI: { vide: (t) => '<p>' + echapper(t) + '</p>', occuper: () => () => {} } }, document: { addEventListener() {} }, console, Promise, JSON };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-centre-vues.js', 'utf8'), bac);
  const SECTIONS = ['commande', 'flux', 'colis', 'expeditions', 'entrepot', 'consolidations', 'transport', 'chauffeurs', 'enlevements', 'livraisons', 'douane', 'incidents', 'notifications',
    'clients', 'support', 'facturation', 'paiements', 'utilisateurs', 'audit', 'parametres', 'rapports'];
  assert.deepEqual(C.vues.map((v) => v.id).sort(), SECTIONS.slice().sort(), 'vingt et une sections enregistrées : le centre, ses dix-neuf domaines et le lien vers les rapports'); ok();
  // Chaque section que la base peut ouvrir a sa définition, et réciproquement (sauf « rapports », un lien vers la vue d'ensemble).
  assert.deepEqual(SECTIONS.filter((s) => s !== 'rapports').sort(), JSON.parse(fs.readFileSync('outils/tests/centre-enums.json', 'utf8')).section.slice().sort()); ok();
  const REPONSE_DE = { flux: 'flux', colis: 'colis', expeditions: 'expeditions', consolidations: 'consolidations', transport: 'transport', chauffeurs: 'chauffeurs', enlevements: 'enlevements',
    livraisons: 'livraisons', douane: 'douane', incidents: 'incidents', notifications: 'notifications', clients: 'clients', support: 'tickets', facturation: 'factures', paiements: 'paiements',
    utilisateurs: 'utilisateurs', audit: 'audit' };
  const propre = (nom, html) => {
    assert.ok(!/undefined|NaN|\[object Object\]/.test(html), nom + ' : « undefined », « NaN » ou un objet brut à l\'écran : ' + (html.match(/.{0,60}(undefined|NaN|\[object Object\]).{0,30}/) || [''])[0]);
  };
  for (const def of C.vues.filter((v) => v.colonnes)) {
    assert.equal(REPONSE_DE[def.id], def.vue === 'tickets' ? 'tickets' : (def.vue === 'factures' ? 'factures' : def.vue), def.id + ' : la vue appelée est celle de sa section');
    const d = garde(JSON.parse(JSON.stringify(EXEMPLES[REPONSE_DE[def.id]])), def.id);
    assert.ok(d.items.length > 0, def.id + ' : l\'exemple de la base a des lignes (sinon ce test ne prouverait rien)');
    let html = def.resume ? def.resume(d, {}) || '' : '';
    d.items.forEach((l, i) => def.colonnes.forEach((c) => { const h = c.rendre(l, i); assert.equal(typeof h, 'string', def.id + ' ' + c.t); html += h; }));
    def.colonnes.forEach((c) => assert.ok(/^c-col-/.test(c.t), def.id + ' : en-tête de colonne sans texte'));
    def.cle && d.items.forEach((l) => assert.ok(def.cle(l) !== undefined && def.cle(l) !== null && def.cle(l) !== '', def.id + ' : ligne sans clé'));
    propre(def.id, html);
    assert.ok(Array.isArray(def.filtres) && def.filtres.every((f) => ['statut', 'pays', 'service', 'ville', 'entrepot', 'client', 'du', 'au'].indexOf(f) >= 0), def.id + ' : filtres connus');
    if (def.filtres.indexOf('statut') >= 0) assert.ok(def.statutLibre || (def.statuts && def.statuts.length && def.prefixeStatut), def.id + ' : un filtre de statut a ses valeurs et leur famille de textes');
  }
  ok();
  // Les sections dessinées à la main : accueil, entrepôt, réglages
  for (const id of ['commande', 'entrepot', 'parametres']) {
    const z = new Zone();
    await C.vues.find((v) => v.id === id).rendre(z, { filtres: {}, page: 0 }, C);
    await new Promise((r) => setTimeout(r, 0));
    const html = texteDe(z);
    assert.ok(html.length > 200, id + ' : quelque chose a été dessiné');
    propre(id, html);
  }
  ok();
  // L'accueil : chaque indicateur de la base a sa carte, et la file « à traiter » ses lignes
  const z = new Zone(); await C.vues.find((v) => v.id === 'commande').rendre(z, { filtres: {}, page: 0 }, C); await new Promise((r) => setTimeout(r, 0));
  const accueil = texteDe(z);
  Object.keys(EXEMPLES.indicateurs.operations).concat(Object.keys(EXEMPLES.indicateurs.support)).forEach((k) => assert.ok(accueil.indexOf('c-kpi-' + k) >= 0, 'pas de carte pour l\'indicateur ' + k));
  EXEMPLES.a_traiter.items.forEach((i) => assert.ok(accueil.indexOf('c-att-' + i.kind) >= 0, 'pas de ligne pour « ' + i.kind + ' »'));
  (EXEMPLES.indicateurs.money.unpaid || []).forEach((u) => assert.ok(accueil.indexOf(u.balance + ' ' + u.currency) >= 0, 'impayés en ' + u.currency));
  ok();
  // Les fiches : colis et ticket
  for (const [action, cle] of [['colis', 'fiche_colis'], ['ticket', 'fiche_ticket']]) {
    let zoneFiche = null;
    C.dialogue = () => (zoneFiche = new Zone());
    C.actions[action]({ getAttribute: (a) => (a === 'data-numero' ? 'N-001' : 'id') });
    await new Promise((r) => setTimeout(r, 0));
    const html = texteDe(zoneFiche);
    assert.ok(html.length > 300, action + ' : fiche dessinée');
    propre(action, html);
    if (action === 'colis') EXEMPLES.fiche_colis.timeline.forEach((e) => assert.ok(html.indexOf(echapper(e.event)) >= 0, 'événement absent de la fiche : ' + e.event));
    if (action === 'ticket') EXEMPLES.fiche_ticket.messages.forEach((m) => assert.ok(html.indexOf(echapper(m.body)) >= 0, 'message absent de la fiche'));
  }
  ok();
  // Traiter une demande : refuser sans message ne part pas ; approuver et refuser appellent la bonne méthode avec la bonne intention.
  const envoyes = [];
  API.centre.traiterEnlevement = (id, o) => { envoyes.push(['enlevement', id, JSON.parse(JSON.stringify(o))]); return Promise.resolve({}); };
  API.centre.traiterLivraison = (id, o) => { envoyes.push(['livraison', id, JSON.parse(JSON.stringify(o))]); return Promise.resolve({}); };
  for (const genre of ['enlevement', 'livraison']) {
    let boite = null; const avant = envoyes.length;
    C.dialogue = (k, html) => { boite = new Zone(); boite.innerHTML = html; return boite; };
    C.actions.traiter({ getAttribute: (a) => (a === 'data-id' ? 'ID-1' : genre) });
    const form = boite.querySelector('#cc-traiter'), refuser = form.querySelector('[data-refuser]'), msg = boite.querySelector('#cc-form-msg');
    assert.ok(/c-trait-(enl|liv)-intro/.test(boite.innerHTML) && /c-approuver/.test(boite.innerHTML) && /c-refuser/.test(boite.innerHTML), genre + ' : le formulaire propose d\'approuver ou de refuser');
    refuser.ecouteurs.click({ currentTarget: new Zone() });
    assert.equal(envoyes.length, avant, genre + ' : refuser sans message ne part pas vers la base');
    assert.equal(msg.textContent, 'c-trait-motif-obligatoire');
    form.elements.message.value = '  Hors zone  '; form.elements.date.value = '';
    refuser.ecouteurs.click({ currentTarget: new Zone() });
    form.elements.message.value = ''; form.elements.date.value = '2026-12-01';
    form.ecouteurs.submit({ preventDefault() {} });
    await new Promise((r) => setTimeout(r, 0));
  }
  assert.deepEqual(envoyes, [['enlevement', 'ID-1', { approuver: false, message: 'Hors zone', date: '' }], ['enlevement', 'ID-1', { approuver: true, message: '', date: '2026-12-01' }],
    ['livraison', 'ID-1', { approuver: false, message: 'Hors zone', date: '' }], ['livraison', 'ID-1', { approuver: true, message: '', date: '2026-12-01' }]], 'chaque bouton envoie son intention, le message nettoyé, la date choisie'); ok();
  assert.deepEqual(fautes, [], 'des sections lisent des clés que la base ne renvoie pas : ' + fautes.slice(0, 8).join(', ')); ok();

  // Tout ce qui vient de la base est échappé : une réponse piégée ne s'exécute pas.
  const piege = '<img src=x onerror=alert(1)>';
  const piegee = JSON.parse(JSON.stringify(EXEMPLES.colis));
  // les textes seulement (un nombre ou une date de la base ne peut pas porter de balise)
  piegee.items.forEach((l) => { Object.keys(l).forEach((k) => { if (typeof l[k] === 'string' && isNaN(Number(l[k])) && !/^\d{4}-\d\d-\d\d/.test(l[k])) l[k] = piege; }); });
  const defColis = C.vues.find((v) => v.id === 'colis');
  const hp = piegee.items.map((l) => defColis.colonnes.map((c) => c.rendre(l)).join('')).join('');
  assert.ok(hp.indexOf('<img') < 0 && hp.indexOf('&lt;img') >= 0, 'les textes de la base sont échappés'); ok();

  // =============================================================== 5. la page : l'onglet existe, caché tant que la base n'a pas répondu, et charge ses fichiers
  const page = fs.readFileSync('tableau-de-bord.html', 'utf8');
  assert.match(page, /<button type="button" role="tab" id="ses-o-centre" aria-controls="ses-p-centre"[^>]* hidden>/, 'l\'onglet est caché par défaut'); ok();
  assert.match(page, /<section role="tabpanel" id="ses-p-centre" aria-labelledby="ses-o-centre" hidden/); ok();
  ['ses-centre.js', 'ses-centre-vues.js'].forEach((f) => assert.match(page, new RegExp('<script src="assets/js/' + f.replace('.', '\\.') + '\\?v=\\d+" defer></script>')));
  assert.ok(page.indexOf('ses-centre.js') > page.indexOf('ses-api.js') && page.indexOf('ses-centre-vues.js') > page.indexOf('ses-centre.js'), 'ordre de chargement'); ok();
  assert.match(page, /<link rel="stylesheet" href="assets\/css\/ses-centre\.css\?v=\d+">/); ok();
  assert.match(page, /<dialog id="cc-dialogue"/); ok();
  assert.equal(/centreNoyau:\s*false/.test(fs.readFileSync('assets/js/config.js', 'utf8')), true, 'l\'interrupteur reste éteint tant que les migrations ne sont pas passées en production'); ok();
  console.log('PASS centre de commande (contrat) : ' + n + ' vérifications — trois implémentations, 28 fonctions et leurs paramètres, interrupteur et repli, 21 sections dessinées sur les réponses réelles sans clé inventée ni texte brut.');
})().catch((e) => { console.error('ÉCHEC centre de commande (contrat) : ' + (e && e.message)); process.exit(1); });
