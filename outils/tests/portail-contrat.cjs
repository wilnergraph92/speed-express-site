// Le portail client côté couche de données : les trois implémentations (en ligne, démonstration, fermé) tiennent le MÊME contrat.
//
// Aucun réseau : la version en ligne parle à un faux client Supabase qui note chaque appel ; la démonstration vit dans la mémoire du test.
// Les deux références viennent de la VRAIE base (outils/tests/logistique-portail-essai.py les écrit et les revérifie) :
//   · portail-rpc.json    : les 25 fonctions que le site appelle, avec le nom et le caractère facultatif de chaque paramètre ;
//   · portail-formes.json : la forme exacte de chaque réponse que le client reçoit.
// Un site qui appelle une fonction ou un paramètre qui n'existe pas, ou une démonstration qui invente une clé, échoue ici.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const SIGNATURES = JSON.parse(fs.readFileSync('outils/tests/portail-rpc.json', 'utf8'));
const FORMES = JSON.parse(fs.readFileSync('outils/tests/portail-formes.json', 'utf8'));
let n = 0; const ok = () => { n++; };

function charger(config, hote, extra) {
  const bac = Object.assign({ window: { addEventListener: () => {}, SES_CONFIG: config }, location: { protocol: 'https:', hostname: hote, href: 'https://' + hote + '/x.html', pathname: '/x.html' },
    document: { documentElement: { lang: 'fr' }, currentScript: null }, console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder }, extra || {});
  vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), bac);
  return bac.window.SES_API;
}
const rejet = async (p) => { try { await p; } catch (e) { return e.code; } return 'aucune-erreur'; };

// ---- les chemins de clés, comme dans le test de la base --------------------------------------------------
function cles(x, chemin) {
  chemin = chemin || '';
  const s = new Set();
  if (Array.isArray(x)) x.forEach((v) => cles(v, chemin + '[]').forEach((k) => s.add(k)));
  else if (x && typeof x === 'object') Object.keys(x).forEach((k) => { s.add(chemin + '.' + k); cles(x[k], chemin + '.' + k).forEach((c) => s.add(c)); });
  return s;
}
// Les clés qui dépendent des DONNÉES (une étape par colis, une clé par notification) ne se comparent pas une à une.
const dynamique = (p) => p.replace(/by_stage\.[a-z_]+/g, 'by_stage.*').replace(/payload\.[a-z_]+/g, 'payload.*');
const enfants = (chemins) => {
  const m = {};
  chemins.forEach((p) => { const i = Math.max(p.lastIndexOf('.'), 0); (m[p.slice(0, i)] = m[p.slice(0, i)] || new Set()).add(p.slice(i + 1)); });
  return m;
};
function memeForme(nom, vu) {
  const attendu = new Set(Array.from(FORMES[nom]).map(dynamique)), obtenu = new Set(Array.from(cles(vu)).map(dynamique));
  const ea = enfants(attendu), eo = enfants(obtenu);
  Object.keys(eo).forEach((parent) => {
    assert.ok(ea[parent], nom + ' : la démonstration invente la structure « ' + parent + ' »');
    // Un objet « extra » varie selon le genre du document : sous-ensemble seulement.
    if (/extra$/.test(parent)) { eo[parent].forEach((k) => assert.ok(ea[parent].has(k), nom + ' : clé inventée ' + parent + '.' + k)); return; }
    assert.deepEqual(Array.from(eo[parent]).sort(), Array.from(ea[parent]).sort(), nom + ' : les clés de « ' + parent + ' » diffèrent de celles de la base');
  });
  ok();
}

(async () => {
  // =============================================================== 1. les trois implémentations ont les mêmes méthodes
  const demo = charger({ portailNoyau: true }, 'localhost');
  const off = charger({}, 'exemple.fr');
  const fakeClient = { appels: [], reponses: {}, erreurs: {} };
  fakeClient.rpc = function (nom, args) {
    fakeClient.appels.push({ nom, args });
    if (fakeClient.erreurs[nom]) return Promise.resolve({ data: null, error: fakeClient.erreurs[nom] });
    return Promise.resolve({ data: fakeClient.reponses[nom] === undefined ? {} : fakeClient.reponses[nom], error: null });
  };
  const sbCfg = { supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai', portailNoyau: true };
  const en = charger(sbCfg, 'exemple.fr', { window: { addEventListener: () => {}, SES_CONFIG: sbCfg, supabase: { createClient: () => ({ auth: {}, rpc: fakeClient.rpc }) } } });
  assert.equal(demo.mode, 'demo'); assert.equal(off.mode, 'off'); assert.equal(en.mode, 'supabase'); ok();
  const METHODES = Array.from(demo.METHODES_PORTAIL);
  assert.equal(METHODES.length, 26); ok();
  for (const [nom, api] of [['demo', demo], ['off', off], ['en ligne', en]]) {
    assert.deepEqual(Object.keys(api.portail).sort(), METHODES.slice().sort(), nom + ' : mêmes méthodes'); ok();
    METHODES.forEach((m) => assert.equal(typeof api.portail[m], 'function', nom + '.' + m)); ok();
  }
  assert.deepEqual(Array.from(off.METHODES_PORTAIL), METHODES); ok();

  // =============================================================== 2. le site ferme : rien ne s'ouvre
  assert.deepEqual(JSON.parse(JSON.stringify(await off.portail.disponible())), { actif: false, raison: 'off' }); ok();
  for (const m of METHODES.filter((x) => x !== 'disponible')) assert.equal(await rejet(off.portail[m]({})), 'ferme', 'fermé : ' + m);
  ok();

  // =============================================================== 3. en ligne : chaque appel respecte la signature de la base
  const ENTREES = {
    tableau: [], colis: [{ etape: 'at_hub', recherche: 'x', limite: 10, decalage: 20 }], colisDetail: ['SES-1'], expeditions: [], consolidations: [], factures: [], solde: [], paiements: [], documents: [], adresses: [],
    enregistrerAdresse: [{ id: '00000000-0000-0000-0000-000000000001', pays: 'HT', adresse: '1 rue', etiquette: 'M', destinataire: 'D', telephone: '1', region: 'R', ville: 'V', consignes: 'C', parDefaut: true }],
    supprimerAdresse: ['00000000-0000-0000-0000-000000000001'], enlevements: [],
    demanderEnlevement: [{ date: '2026-12-01', colis: 2, adresseId: '00000000-0000-0000-0000-000000000001', creneau: 'MORNING', notes: 'n', contact: 'c', telephone: 't', cle: 'k' }],
    annulerEnlevement: ['00000000-0000-0000-0000-000000000001'], livraisons: [],
    demanderLivraison: [{ colis: ['A', 'B'], date: '2026-12-01', adresse: 'a', ville: 'v', pays: 'HT', creneau: 'ANY', notes: 'n', contact: 'c', telephone: 't', cle: 'k' }],
    annulerLivraison: ['00000000-0000-0000-0000-000000000001'], notifications: [{ nonLuesSeulement: true, limite: 5 }], lireNotifications: [[1, 2]], tickets: [],
    ticket: ['00000000-0000-0000-0000-000000000001'], ouvrirTicket: [{ sujet: 'S', categorie: 'PARCEL', message: 'M', colis: 'SES-1', facture: 'INV-1', cle: 'k' }],
    repondreTicket: ['00000000-0000-0000-0000-000000000001', 'M'], fermerTicket: ['00000000-0000-0000-0000-000000000001']
  };
  const FONCTION = { tableau: 'lg_my_dashboard', colis: 'lg_my_parcels', colisDetail: 'lg_my_parcel', expeditions: 'lg_my_shipments', consolidations: 'lg_my_consolidations', factures: 'lg_my_invoices', solde: 'lg_my_balance',
    paiements: 'lg_my_payments', documents: 'lg_my_documents', adresses: 'lg_my_addresses', enregistrerAdresse: 'lg_save_address', supprimerAdresse: 'lg_delete_address', enlevements: 'lg_my_pickups',
    demanderEnlevement: 'lg_request_pickup', annulerEnlevement: 'lg_cancel_pickup_request', livraisons: 'lg_my_deliveries', demanderLivraison: 'lg_request_delivery', annulerLivraison: 'lg_cancel_delivery_request',
    notifications: 'lg_my_notifications', lireNotifications: 'lg_mark_notifications_read', tickets: 'lg_my_tickets', ticket: 'lg_my_ticket', ouvrirTicket: 'lg_open_ticket', repondreTicket: 'lg_reply_ticket',
    fermerTicket: 'lg_close_my_ticket' };
  assert.deepEqual(Object.keys(FONCTION).sort(), METHODES.filter((m) => m !== 'disponible').sort()); ok();
  assert.deepEqual(Object.values(FONCTION).sort(), Object.keys(SIGNATURES).sort(), 'les 25 fonctions du site sont exactement celles du fichier de signatures'); ok();
  for (const m of Object.keys(FONCTION)) {
    fakeClient.appels.length = 0;
    await en.portail[m].apply(null, ENTREES[m]);
    assert.equal(fakeClient.appels.length, 1, m); const a = fakeClient.appels[0];
    assert.equal(a.nom, FONCTION[m], m);
    const sig = SIGNATURES[a.nom], noms = sig.map((p) => p.nom);
    Object.keys(a.args).forEach((k) => assert.ok(noms.indexOf(k) >= 0, m + ' envoie « ' + k + ' » : la fonction ' + a.nom + ' ne connaît pas ce paramètre'));
    sig.filter((p) => !p.defaut).forEach((p) => assert.ok(Object.prototype.hasOwnProperty.call(a.args, p.nom), m + ' oublie le paramètre obligatoire « ' + p.nom + ' »'));
    Object.keys(a.args).forEach((k) => assert.notEqual(a.args[k], undefined, m + ' : « ' + k + ' » vaut undefined'));
  }
  ok();
  // Ce qui n'est pas renseigné n'est PAS envoyé : la base applique ses valeurs par défaut.
  fakeClient.appels.length = 0; await en.portail.colis({});
  assert.deepEqual(Object.keys(fakeClient.appels[0].args).sort(), ['p_limit', 'p_offset']); ok();
  fakeClient.appels.length = 0; await en.portail.demanderEnlevement({ date: '2026-12-01', colis: 1, adresse: 'x', pays: 'HT', creneau: 'ANY', cle: 'k' });
  assert.deepEqual(Object.keys(fakeClient.appels[0].args).sort(), ['p_address', 'p_country', 'p_idempotency_key', 'p_parcels_expected', 'p_preferred_date', 'p_window']); ok();
  fakeClient.appels.length = 0; await en.portail.enregistrerAdresse({ pays: 'HT', adresse: 'x' });
  assert.deepEqual(Object.keys(fakeClient.appels[0].args).sort(), ['p_address', 'p_country'], 'une adresse sans « par défaut » ne l\'envoie pas : la base garde son choix'); ok();
  fakeClient.appels.length = 0; await en.portail.lireNotifications([]);
  assert.deepEqual(JSON.parse(JSON.stringify(fakeClient.appels[0].args)), {}, 'aucune liste = tout marquer lu'); ok();
  // La clé d'envoi
  assert.match(en.cleEnvoi(), /^w[a-z0-9]{10,}$/); assert.notEqual(en.cleEnvoi(), en.cleEnvoi()); ok();

  // =============================================================== 4. en ligne : l'interrupteur, et le repli sûr
  const dispo = async (cfg, rep, err) => {
    fakeClient.reponses = { lg_my_dashboard: rep }; fakeClient.erreurs = err ? { lg_my_dashboard: err } : {};
    const o = Object.assign({}, sbCfg, cfg);
    const api = charger(o, 'exemple.fr', { window: { addEventListener: () => {}, SES_CONFIG: o, supabase: { createClient: () => ({ auth: {}, rpc: fakeClient.rpc }) } } });
    fakeClient.appels.length = 0;
    const r = JSON.parse(JSON.stringify(await api.portail.disponible()));
    return { r, appels: fakeClient.appels.length };
  };
  let d = await dispo({ portailNoyau: false }, {});
  assert.deepEqual(d.r, { actif: false, raison: 'drapeau' }); assert.equal(d.appels, 0, 'interrupteur éteint : la base n\'est pas même interrogée'); ok();
  assert.deepEqual((await dispo({ portailNoyau: undefined }, { linked: true, in_sync: true })).r, { actif: false, raison: 'drapeau' }, 'interrupteur absent de config.js = éteint'); ok();
  d = await dispo({ portailNoyau: true }, { linked: true, in_sync: true, parcels: { total: 3 } });
  assert.equal(d.r.actif, true); assert.equal(d.r.tableau.parcels.total, 3); ok();
  assert.deepEqual((await dispo({ portailNoyau: true }, { linked: false, in_sync: false })).r, { actif: false, raison: 'non-relie' }); ok();
  assert.deepEqual((await dispo({ portailNoyau: true }, { linked: true, in_sync: false })).r, { actif: false, raison: 'en-retard' }); ok();
  assert.deepEqual((await dispo({ portailNoyau: true }, null)).r, { actif: false, raison: 'non-relie' }); ok();
  assert.deepEqual((await dispo({ portailNoyau: true }, null, { code: 'PGRST202', message: 'Could not find the function public.lg_my_dashboard' })).r, { actif: false, raison: 'absent' }); ok();
  assert.deepEqual((await dispo({ portailNoyau: true }, null, { message: 'Could not find the function public.lg_my_dashboard in the schema cache' })).r, { actif: false, raison: 'absent' }); ok();
  assert.deepEqual((await dispo({ portailNoyau: true }, null, { message: 'Failed to fetch' })).r, { actif: false, raison: 'erreur' }); ok();
  assert.deepEqual((await dispo({ portailNoyau: true }, null, { code: 'LG003', message: 'x' })).r, { actif: false, raison: 'erreur' }); ok();

  // =============================================================== 5. en ligne : les codes d'erreur de la base
  for (const [code, attendu] of [['LG002', 'introuvable'], ['LG003', 'non-autorise'], ['LG004', 'etat-incompatible'], ['LG005', 'donnee-invalide'], ['LG006', 'doublon'], ['42501', 'non-autorise'], ['PGRST202', 'noyau-absent']]) {
    fakeClient.erreurs = { lg_my_parcel: { code, message: 'message de la base' } };
    assert.equal(await rejet(en.portail.colisDetail('X')), attendu, code); ok();
  }
  fakeClient.erreurs = { lg_my_parcel: { code: 'LG005', message: 'La date souhaitée doit être comprise entre aujourd\'hui et dans 60 jours.' } };
  try { await en.portail.colisDetail('X'); } catch (e) { assert.match(e.message, /60 jours/, 'le message de la base est gardé'); } ok();
  fakeClient.erreurs = {};

  // =============================================================== 6. la démonstration : mêmes réponses, mêmes règles
  const ADMIN = demo.identifiantsAdmin, MDP = 'motdepasse1';
  const ins = async (nom) => { const r = await demo.inscrire({ email: nom + '@essai.test', motDePasse: MDP, nom_complet: 'Client ' + nom, telephone: '+509 3000 0000' }); await demo.deconnecter(); return r.profil; };
  const pa = await ins('a'), pb = await ins('b');
  await demo.connecter(ADMIN.email, ADMIN.motDePasse);
  const mk = (cl, desc, statut, extra) => demo.admin.creerColis(Object.assign({ client_id: cl.id, description: desc, expediteur: 'Miami', destinataire: 'Dest ' + desc, poids_lb: 4, tarif_lb: 3, service: 'aerien',
    pays_destination: 'HT', ville_destination: 'Pétion-Ville', adresse_livraison: '12 rue des Fleurs', statut: 'confirme' }, extra || {}));
  const c1 = await mk(pa, 'bijoux'), c2 = await mk(pa, 'vêtements'), c3 = await mk(pa, 'livres'), cB = await mk(pb, 'secret de B');
  await demo.admin.changerStatut([c2.id], 'disponible', 'Hub Port-au-Prince', ''); await demo.admin.changerStatut([c3.id], 'disponible', 'Hub Port-au-Prince', '');
  await demo.admin.changerStatut([c1.id], 'expedie', 'En vol', 'Départ confirmé');
  await demo.deconnecter();
  // le personnel n'a pas d'espace client
  await demo.connecter(ADMIN.email, ADMIN.motDePasse);
  for (const m of ['tableau', 'colis', 'adresses', 'tickets', 'documents']) assert.equal(await rejet(demo.portail[m]({})), 'non-autorise', 'personnel : ' + m);
  assert.deepEqual(JSON.parse(JSON.stringify(await demo.portail.disponible())), { actif: false, raison: 'non-relie' }); ok();
  await demo.deconnecter();
  assert.equal(await rejet(demo.portail.tableau()), 'non-autorise', 'visiteur'); ok();

  await demo.connecter('a@essai.test', MDP);
  const dsp = await demo.portail.disponible(); assert.equal(dsp.actif, true); ok();
  const dem = charger({}, 'localhost');
  assert.deepEqual(JSON.parse(JSON.stringify(await dem.portail.disponible())), { actif: false, raison: 'drapeau' }, 'démonstration, interrupteur éteint : l\'espace d\'avant'); ok();

  const tab = await demo.portail.tableau();
  assert.equal(tab.parcels.total, 3); assert.deepEqual(JSON.parse(JSON.stringify(tab.parcels.by_stage)), { in_transit: 1, at_hub: 2 }); assert.equal(tab.linked, true); assert.equal(tab.in_sync, true); ok();
  assert.ok(tab.recent_events.length > 0 && tab.recent_events.length <= 5); ok();
  memeForme('tableau_de_bord', tab);
  const liste = await demo.portail.colis({ limite: 2 });
  assert.equal(liste.total, 3); assert.equal(liste.items.length, 2); assert.ok(liste.items.every((i) => i.tracking_number)); memeForme('colis', liste);
  assert.equal((await demo.portail.colis({ etape: 'at_hub' })).total, 2); assert.equal((await demo.portail.colis({ recherche: 'BIJOUX' })).total, 1); assert.equal((await demo.portail.colis({ recherche: '%' })).total, 0); ok();
  assert.equal((await demo.portail.colis({ limite: 100000 })).items.length, 3); assert.equal((await demo.portail.colis({ limite: 0 })).items.length, 1); ok();
  assert.ok(!JSON.stringify(await demo.portail.colis({ limite: 50 })).includes(cB.numero), 'rien de B chez A'); ok();
  const det = await demo.portail.colisDetail(c1.numero.toLowerCase());
  assert.equal(det.tracking_number, c1.numero); assert.equal(det.stage, 'in_transit'); assert.equal(det.timeline.length, 2); assert.equal(det.timeline[1].note, 'Départ confirmé'); memeForme('colis_herite', det);
  assert.equal(await rejet(demo.portail.colisDetail(cB.numero)), 'introuvable', 'le colis de B répond « introuvable »'); assert.equal(await rejet(demo.portail.colisDetail('ZZZ-1')), 'introuvable'); ok();
  assert.deepEqual(JSON.parse(JSON.stringify(await demo.portail.expeditions())), []); assert.deepEqual(JSON.parse(JSON.stringify(await demo.portail.consolidations())), []); ok();

  // adresses
  assert.deepEqual(JSON.parse(JSON.stringify(await demo.portail.adresses())), []); ok();
  const a1 = await demo.portail.enregistrerAdresse({ pays: 'HT', adresse: '  12 rue des Fleurs ', ville: 'Pétion-Ville', etiquette: 'Maison', destinataire: 'Marie', telephone: '+509 1' });
  assert.equal(a1.is_default, true); ok();
  const a2 = await demo.portail.enregistrerAdresse({ pays: 'US', adresse: '100 Brickell Ave', ville: 'Miami' }); assert.equal(a2.is_default, false); ok();
  await demo.portail.enregistrerAdresse({ id: a2.address_id, pays: 'US', adresse: '100 Brickell Ave', ville: 'Miami', parDefaut: true });
  let ads = await demo.portail.adresses(); assert.equal(ads.length, 2); assert.equal(ads[0].address_id, a2.address_id); assert.equal(ads.filter((x) => x.is_default).length, 1); assert.equal(ads[1].address, '12 rue des Fleurs'); memeForme('adresses', ads);
  for (const [champs, msg] of [[{ pays: 'FR', adresse: 'x' }, 'pays'], [{ pays: 'HT', adresse: '  ' }, 'adresse vide'], [{ pays: 'HT', adresse: 'x'.repeat(201) }, '201'], [{ pays: 'HT', adresse: 'x', etiquette: 'l'.repeat(41) }, 'étiquette']])
    assert.equal(await rejet(demo.portail.enregistrerAdresse(champs)), 'donnee-invalide', msg);
  ok();
  for (let i = 0; i < 18; i++) await demo.portail.enregistrerAdresse({ pays: 'HT', adresse: 'Rue ' + i });
  assert.equal(await rejet(demo.portail.enregistrerAdresse({ pays: 'HT', adresse: 'de trop' })), 'donnee-invalide', 'vingt adresses au plus');
  for (const a of (await demo.portail.adresses()).slice(2)) await demo.portail.supprimerAdresse(a.address_id);
  ads = await demo.portail.adresses(); assert.equal(ads.length, 2); ok();
  await demo.portail.supprimerAdresse(a2.address_id); ads = await demo.portail.adresses(); assert.equal(ads.length, 1); assert.equal(ads[0].is_default, true, 'le défaut passe à l\'adresse restante');
  assert.equal(await rejet(demo.portail.supprimerAdresse(a2.address_id)), 'introuvable'); await demo.portail.enregistrerAdresse({ pays: 'US', adresse: '100 Brickell Ave', parDefaut: false }); ok();

  // enlèvements
  const plusJ = (j) => new Date(Date.now() + j * 86400000).toISOString().slice(0, 10);
  const ad = (await demo.portail.adresses())[0];
  for (const [e, msg] of [[{ date: plusJ(-1), colis: 1, adresse: 'x', pays: 'HT' }, 'passée'], [{ date: plusJ(61), colis: 1, adresse: 'x', pays: 'HT' }, '61 jours'], [{ date: plusJ(3), colis: 0, adresse: 'x', pays: 'HT' }, '0 colis'],
                           [{ date: plusJ(3), colis: 101, adresse: 'x', pays: 'HT' }, '101'], [{ date: plusJ(3), colis: 1, adresse: 'x', pays: 'HT', creneau: 'NUIT' }, 'créneau'], [{ date: plusJ(3), colis: 1, pays: 'HT' }, 'sans adresse'],
                           [{ date: plusJ(3), colis: 1, adresse: 'x', pays: 'FR' }, 'pays'], [{ date: plusJ(3), colis: 1, adresse: 'x', pays: 'HT', notes: 'n'.repeat(501) }, 'notes']])
    assert.equal(await rejet(demo.portail.demanderEnlevement(e)), 'donnee-invalide', 'enlèvement : ' + msg);
  assert.equal(await rejet(demo.portail.demanderEnlevement({ date: plusJ(3), colis: 1, adresseId: 'inconnue' })), 'introuvable'); ok();
  const p1 = await demo.portail.demanderEnlevement({ date: plusJ(3), colis: 2, adresseId: ad.address_id, creneau: 'MORNING', notes: 'Sonner' });
  assert.match(p1.number, /^PKR-\d{4}-000001$/); assert.equal(p1.stage, 'requested'); ok();
  let enl = await demo.portail.enlevements(); assert.equal(enl.length, 1); assert.equal(enl[0].window, 'MORNING'); assert.equal(enl[0].message, null); memeForme('enlevements', enl);
  for (let i = 0; i < 4; i++) await demo.portail.demanderEnlevement({ date: plusJ(3), colis: 1, adresse: 'A' + i, pays: 'HT' });
  assert.equal(await rejet(demo.portail.demanderEnlevement({ date: plusJ(3), colis: 1, adresse: 'de trop', pays: 'HT' })), 'donnee-invalide', 'cinq en attente au plus');
  assert.equal((await demo.portail.annulerEnlevement(p1.pickup_id)).stage, 'cancelled'); assert.equal(await rejet(demo.portail.annulerEnlevement(p1.pickup_id)), 'etat-incompatible'); assert.equal(await rejet(demo.portail.annulerEnlevement('inconnue')), 'introuvable');
  assert.equal((await demo.portail.tableau()).pickups.open, 4); ok();

  // livraisons
  let liv = await demo.portail.livraisons(); assert.deepEqual(Array.from(liv.at_hub.map((x) => x.tracking_number)).sort(), [c2.numero, c3.numero].sort()); assert.deepEqual(JSON.parse(JSON.stringify(liv.deliveries)), []); ok();
  for (const [l, etat, msg] of [[{ colis: [], date: plusJ(3), adresseId: ad.address_id }, 'donnee-invalide', 'aucun colis'], [{ colis: [c1.numero], date: plusJ(3), adresseId: ad.address_id }, 'donnee-invalide', 'pas au hub'],
                                [{ colis: [cB.numero], date: plusJ(3), adresseId: ad.address_id }, 'introuvable', 'colis de B'], [{ colis: [c2.numero], date: plusJ(-1), adresseId: ad.address_id }, 'donnee-invalide', 'date passée']])
    assert.equal(await rejet(demo.portail.demanderLivraison(l)), etat, 'livraison : ' + msg);
  const l1 = await demo.portail.demanderLivraison({ colis: [c2.numero, c2.numero.toLowerCase()], date: plusJ(3), adresseId: ad.address_id, creneau: 'AFTERNOON' });
  assert.match(l1.number, /^DLR-\d{4}-000006$/); assert.equal(l1.parcels, 1); ok();
  assert.equal(await rejet(demo.portail.demanderLivraison({ colis: [c2.numero], date: plusJ(3), adresseId: ad.address_id })), 'donnee-invalide', 'déjà dans une demande');
  liv = await demo.portail.livraisons(); assert.deepEqual(Array.from(liv.at_hub.map((x) => x.tracking_number)), [c3.numero]); assert.equal(liv.requests.length, 1); memeForme('livraisons', liv);
  assert.equal((await demo.portail.annulerLivraison(l1.request_id)).stage, 'cancelled'); assert.equal((await demo.portail.livraisons()).at_hub.length, 2); ok();

  // factures, paiements, documents
  await demo.connecter(ADMIN.email, ADMIN.motDePasse);
  // Chaque colis enregistré génère sa facture (comme la base) : on solde celle du deuxième.
  const toutes = (await demo.admin.factures({ parPage: 100 })).lignes.filter((f) => f.client_id === pa.id);
  assert.equal(toutes.length, 3); const f1 = toutes.filter((f) => f.colis_id === c1.id)[0], f2 = toutes.filter((f) => f.colis_id === c2.id)[0];
  await demo.admin.modifierFacture(f2.id, { statut: 'payee', montant_paye: f2.montant });
  await demo.deconnecter(); await demo.connecter('a@essai.test', MDP);
  const facs = await demo.portail.factures(); assert.equal(facs.length, 3); memeForme('factures', facs);
  const fp = facs.filter((x) => x.status === 'PAID')[0], fi = facs.filter((x) => x.status === 'ISSUED')[0];
  assert.equal(facs.filter((x) => x.status === 'ISSUED').length, 2);
  assert.equal(fp.balance, 0); assert.equal(fi.balance, fi.total); assert.ok(fi.items.some((i) => i.kind === 'SERVICE_FEE')); ok();
  memeForme('solde', await demo.portail.solde());
  const pay = await demo.portail.paiements(); assert.equal(pay.payments.length, 1); assert.deepEqual(JSON.parse(JSON.stringify(pay.refunds)), []); memeForme('paiements', pay);
  const docs = await demo.portail.documents(); assert.equal(docs.length, 3); assert.ok(docs.every((x) => x.kind === 'INVOICE')); memeForme('documents', docs);
  assert.equal((await demo.portail.tableau()).invoices.unpaid, 2); ok();

  // notifications (vides : rien n'est inventé), tickets
  const nt = await demo.portail.notifications(); assert.deepEqual(JSON.parse(JSON.stringify(nt)), { unread: 0, items: [] }); assert.equal((await demo.portail.lireNotifications()).marked, 0); ok();
  for (const [t, msg] of [[{ sujet: 'ab', categorie: 'PARCEL', message: 'x' }, 'sujet court'], [{ sujet: 'Sujet', categorie: 'PARCEL', message: ' ' }, 'message vide'], [{ sujet: 'Sujet', categorie: 'VENTE', message: 'x' }, 'catégorie'],
                          [{ sujet: 'Sujet', categorie: 'PARCEL', message: 'x'.repeat(4001) }, 'message long']]) assert.equal(await rejet(demo.portail.ouvrirTicket(t)), 'donnee-invalide', msg);
  assert.equal(await rejet(demo.portail.ouvrirTicket({ sujet: 'Sujet', categorie: 'PARCEL', message: 'x', colis: cB.numero })), 'introuvable', 'le colis de B dans un ticket');
  assert.equal(await rejet(demo.portail.ouvrirTicket({ sujet: 'Sujet', categorie: 'INVOICE', message: 'x', facture: 'INV-INCONNUE' })), 'introuvable'); ok();
  const t1 = await demo.portail.ouvrirTicket({ sujet: '  Mon colis est abîmé ', categorie: 'PARCEL', message: 'Le contenu est cassé.', colis: c1.numero.toLowerCase(), facture: f1.numero });
  assert.match(t1.number, /^SUP-\d{4}-/); assert.equal(t1.status, 'OPEN'); ok();
  let tks = await demo.portail.tickets(); assert.equal(tks.length, 1); assert.equal(tks[0].subject, 'Mon colis est abîmé'); assert.equal(tks[0].last_author, 'CUSTOMER'); memeForme('tickets', tks);
  let tk = await demo.portail.ticket(t1.ticket_id); assert.equal(tk.parcel, c1.numero); assert.equal(tk.invoice, f1.numero); assert.equal(tk.messages.length, 1); memeForme('ticket', tk);
  assert.equal((await demo.portail.repondreTicket(t1.ticket_id, 'Voici des photos.')).status, 'OPEN'); assert.equal((await demo.portail.ticket(t1.ticket_id)).messages.length, 2);
  assert.equal(await rejet(demo.portail.repondreTicket(t1.ticket_id, '  ')), 'donnee-invalide'); ok();
  assert.equal((await demo.portail.fermerTicket(t1.ticket_id)).status, 'CLOSED'); assert.equal(await rejet(demo.portail.repondreTicket(t1.ticket_id, 'encore')), 'etat-incompatible'); assert.equal(await rejet(demo.portail.fermerTicket(t1.ticket_id)), 'etat-incompatible'); ok();
  for (let i = 0; i < 4; i++) await demo.portail.ouvrirTicket({ sujet: 'Question ' + i, categorie: 'OTHER', message: 'bonjour' });
  assert.equal(await rejet(demo.portail.ouvrirTicket({ sujet: 'De trop', categorie: 'OTHER', message: 'x' })), 'donnee-invalide', 'cinq tickets en 24 heures au plus'); ok();

  // l'isolation : B ne voit rien de A, A ne voit rien de B
  await demo.deconnecter(); await demo.connecter('b@essai.test', MDP);
  assert.equal((await demo.portail.colis({ limite: 50 })).total, 1); assert.deepEqual(JSON.parse(JSON.stringify(await demo.portail.adresses())), []); assert.deepEqual(JSON.parse(JSON.stringify(await demo.portail.tickets())), []);
  assert.deepEqual(JSON.parse(JSON.stringify(await demo.portail.enlevements())), []); assert.equal((await demo.portail.livraisons()).requests.length, 0); const fb = await demo.portail.factures(); assert.equal(fb.length, 1, 'B a la facture de SON colis'); assert.ok(!facs.some((x) => x.number === fb[0].number), 'et aucune facture en commun avec A');
  assert.equal(await rejet(demo.portail.ticket(t1.ticket_id)), 'introuvable', 'le ticket de A répond « introuvable » chez B');
  assert.equal(await rejet(demo.portail.annulerEnlevement(p1.pickup_id)), 'introuvable'); assert.equal(await rejet(demo.portail.supprimerAdresse(a1.address_id)), 'introuvable'); ok();
  await demo.deconnecter();

  console.log('PASS portail client (contrat) : ' + n + ' vérifications — trois implémentations, 25 fonctions de la base, formes des réponses, interrupteur et repli, codes d\'erreur, isolation.');
})().catch((e) => { console.error(e); process.exit(1); });
