// La bascule des colis (étape 030) côté site : la couche de données et l'écran tiennent le contrat de la VRAIE base, sans réseau.
//
// Références écrites (et revérifiées) par outils/tests/logistique-colis-noyau-essai.py sur la réplique de la production :
//   · colis-noyau-rpc.json      : les signatures des sept fonctions (lg_create_parcel, lg_update_parcel, lg_parcel_next_steps, lg_move_parcels,
//                                 lg_cancel_parcel, ses_track, lg_update_my_profile) ;
//   · colis-noyau-exemples.json : des réponses réelles.
// Ce qu'on éprouve : (1) interrupteur « colisNoyau » ÉTEINT : rien ne change (anciennes tables, ancien suivi), les gestes du noyau refusés ;
// (2) ALLUMÉ : chaque geste appelle sa fonction avec ses paramètres réels, sans statut ni lieu glissés dans une création ou une modification ;
// un statut inconnu ou une annulation sans motif ne partent pas ; (3) la démonstration n'a pas de noyau ; (4) la réponse réelle du suivi a
// toutes les clés que la page Suivi lit ; (5) l'écran : formulaire (motif, entrepôt, emplacement), textes, « Annuler » au lieu de « Supprimer ».
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const SIG = JSON.parse(fs.readFileSync('outils/tests/colis-noyau-rpc.json', 'utf8'));
const EX = JSON.parse(fs.readFileSync('outils/tests/colis-noyau-exemples.json', 'utf8'));
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };

/* Un faux client Supabase : il note chaque appel (rpc ou table) et répond {} — la forme des réponses est éprouvée à part. */
function fauxClient(journal) {
  const chaine = (table) => {
    const c = { table, ops: [] };
    const f = (op) => (...args) => { c.ops.push([op, args]); return proxy; };
    const proxy = new Proxy({}, { get(_, k) {
      if (k === 'then') return (res) => { journal.push({ table, ops: c.ops }); return Promise.resolve({ data: k === 'then' && c.ops.some((o) => o[0] === 'single') ? { numero: 'SES-0000000001' } : [], error: null }).then(res); };
      return f(k);
    } });
    return proxy;
  };
  return { auth: { getUser: () => Promise.resolve({ data: { user: { id: 'moi' } } }), getSession: () => Promise.resolve({ data: { session: null } }) },
           rpc: (nom, args) => { journal.push({ rpc: nom, args }); return Promise.resolve({ data: nom === 'lg_cc_parcel' ? { timeline: [] } : {}, error: null }); },
           from: (t) => chaine(t), channel: () => ({ on() { return this; }, subscribe() { return this; } }), removeChannel() {} };
}
function charger(config, hote, journal) {
  const fenetre = { addEventListener: () => {}, SES_CONFIG: config, supabase: { createClient: () => fauxClient(journal) } };
  const bac = { window: fenetre, location: { protocol: 'https:', hostname: hote, href: 'https://' + hote + '/x.html', pathname: '/x.html', origin: 'https://' + hote },
    document: { documentElement: { lang: 'fr' }, currentScript: null }, console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), bac);
  return bac.window.SES_API;
}
const rejet = async (p) => { try { await p; } catch (e) { return e.code; } return 'aucune-erreur'; };
const cfg = (noyau) => ({ supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai', colisNoyau: noyau });
const colis = { client_id: 'c1', description: 'Chaussures', poids_lb: '4.5', tarif_lb: '3', statut: 'livre', lieu: 'Miami', note: 'Fragile' };

(async () => {
  // ============================================================ 1. interrupteur éteint : rien ne change
  const j0 = [];
  const eteint = charger(cfg(false), 'exemple.fr', j0);
  ok(eteint.colisNoyau === false, 'éteint par défaut');
  await eteint.admin.creerColis(colis); await eteint.admin.modifierColis('id1', { poids_lb: '5' }); await eteint.suivre('SES-1234567890');
  ok(!j0.some((x) => /^lg_/.test(x.rpc || '')), 'éteint : aucune fonction du noyau appelée');
  ok(j0.some((x) => x.table === 'colis' && x.ops.some((o) => o[0] === 'insert')) && j0.some((x) => x.rpc === 'suivre_colis'), 'éteint : l\'ancienne table et l\'ancien suivi, comme avant');
  for (const m of ['etapesColis', 'avancerColis', 'annulerColis']) ok(await rejet(eteint.admin[m]('id1', 'RECEIVED')) === 'non-autorise', 'éteint : ' + m + ' refusé');

  // ============================================================ 2. allumé : les fonctions du noyau, avec leurs paramètres réels
  const j = [];
  const api = charger(cfg(true), 'exemple.fr', j);
  ok(api.colisNoyau === true && JSON.stringify(Array.from(api.METHODES_COLIS_NOYAU)) === '["etapesColis","avancerColis","annulerColis"]', 'allumé : trois gestes du noyau');
  const appels = [
    ['creerColis', () => api.admin.creerColis(colis), 'lg_create_parcel'],
    ['modifierColis', () => api.admin.modifierColis('id1', { poids_lb: '5', statut: 'livre', lieu: 'X', note: 'n' }), 'lg_update_parcel'],
    ['etapesColis', () => api.admin.etapesColis('id1'), 'lg_parcel_next_steps'],
    ['avancerColis', () => api.admin.avancerColis(['id1', 'id2'], 'RECEIVED', { lieu: 'Miami', motif: 'm', entrepot: 'w1', emplacement: 'l1' }), 'lg_move_parcels'],
    ['annulerColis', () => api.admin.annulerColis('id1', 'Créé en double'), 'lg_cancel_parcel'],
    ['suivre', () => api.suivre('SES-1234567890', 'abc'), 'ses_track'],
    ['modifierProfil', () => api.modifierProfil({ nom_complet: 'Marie', role: 'admin', code: 'SES-1' }), 'lg_update_my_profile']];
  const vus = new Set();
  for (const [m, f, nom] of appels) {
    j.length = 0; await f();
    const a = j.find((x) => x.rpc === nom);
    ok(a, m + ' → ' + nom);
    const sig = SIG[nom];
    ok(sig, nom + ' existe dans la base');
    Object.keys(a.args).forEach((k) => ok(sig.some((p) => p.nom === k), m + ' : paramètre inconnu ' + k));
    sig.filter((p) => !p.defaut).forEach((p) => ok(Object.prototype.hasOwnProperty.call(a.args, p.nom), m + ' : oublie ' + p.nom));
    vus.add(nom);
  }
  ok([...vus].sort().join() === Object.keys(SIG).sort().join(), 'le site appelle exactement les sept fonctions de la bascule');
  j.length = 0; await api.admin.creerColis(colis);
  ok(!('statut' in j[0].args.p_colis) && j[0].args.p_colis.poids_lb === 4.5, 'création : jamais de statut (il vient du noyau), nombres normalisés');
  j.length = 0; await api.admin.modifierColis('id1', { poids_lb: '5', statut: 'livre', lieu: 'X', note: 'n' });
  ok(!('statut' in j[0].args.p_champs) && !('lieu' in j[0].args.p_champs) && j[0].args.p_champs.note === 'n', 'modification : ni statut ni lieu (ils avancent par les étapes)');
  j.length = 0; await api.modifierProfil({ nom_complet: 'Marie', role: 'admin', code: 'SES-1' });
  ok(JSON.stringify(Object.keys(j[0].args.p_champs)) === '["nom_complet"]', 'profil : seulement les champs du profil (jamais le rôle ni le code)');
  j.length = 0;
  ok(await rejet(api.admin.avancerColis(['id1'], 'livre; drop')) === 'statut-inconnu', 'un statut illisible ne part pas');
  ok(await rejet(api.admin.annulerColis('id1', '   ')) === 'donnee-invalide', 'une annulation sans motif ne part pas');
  ok(j.length === 0, 'aucun de ces refus n\'a atteint la base');
  j.length = 0; await api.admin.historique('id1');
  ok(j.some((x) => x.rpc === 'lg_cc_parcel'), 'la fiche lit le journal du noyau (lg_cc_parcel)');

  // ============================================================ 3. la démonstration n'a pas de noyau
  const demo = charger({}, 'localhost', []);
  ok(demo.colisNoyau === false, 'démonstration : interrupteur sans effet');
  for (const m of ['etapesColis', 'avancerColis', 'annulerColis']) ok(typeof demo.admin[m] === 'function' && await rejet(demo.admin[m]('id1')) === 'non-autorise', 'démonstration : ' + m + ' présent et refusé');

  // ============================================================ 4. les réponses réelles
  const ancienSuivi = ['numero', 'statut', 'service', 'pays_destination', 'maj_le', 'historique'];
  ok(ancienSuivi.every((k) => k in EX.suivi) && EX.suivi.historique.every((h) => 'statut' in h && 'lieu' in h && 'cree_le' in h), 'ses_track a toutes les clés que la page Suivi lit');
  ok(['confirme', 'expedie', 'disponible', 'livre', 'action'].includes(EX.suivi.statut), 'son statut est l\'un des cinq que la page sait nommer');
  ok(!/Marie|Lamarre|Boutique|3711/.test(JSON.stringify(EX.suivi)), 'le suivi public ne montre ni nom, ni adresse, ni téléphone');
  for (const s of EX.etapes.steps) ok(['to_status', 'requires_reason', 'needs_warehouse', 'needs_location', 'direction_only'].every((k) => k in s), 'une étape porte ce que l\'écran lit : ' + s.to_status);
  ok('current_warehouse_id' in EX.etapes && EX.etapes_direction.steps.some((s) => s.to_status === 'CANCELLED') && !EX.etapes.steps.some((s) => s.to_status === 'CANCELLED'),
     'l\'annulation n\'est proposée qu\'à la direction');
  ok(EX.avancement.results[0].ok === true && EX.lot.results.some((r) => r.ok === false && r.message), 'un refus revient avec sa raison');
  ok(EX.creation.numero && EX.creation.jeton && EX.creation.parcel_id && 'statut' in EX.creation, 'une création rend la ligne de l\'onglet Colis (numéro, jeton, statut) et le colis du noyau');

  // ============================================================ 5. l'écran
  const html = fs.readFileSync('tableau-de-bord.html', 'utf8'), admin = fs.readFileSync('assets/js/ses-admin.js', 'utf8');
  const textes = {};
  for (const m of html.matchAll(/<span data-t="([^"]+)">([^<]*)<\/span>/g)) textes[m[1]] = m[2];
  for (const k of ['action-annuler', 'c-cn-creer-entrepot', 'c-cn-aucune-etape', 'c-cn-annulation-impossible', 'c-cn-colis-annule', 'c-cn-refus']) ok(k in textes, 'texte présent : ' + k);
  const statuts = new Set([...EX.etapes.steps, ...EX.etapes_direction.steps].map((s) => s.to_status).concat([EX.etapes.status]));
  for (const s of statuts) ok(('c-colis-' + s) in textes, 'statut du noyau nommé : ' + s);
  for (const champ of ['motif', 'entrepot', 'emplacement']) ok(new RegExp('data-noyau="' + champ + '"[^>]*hidden').test(html), 'formulaire de statut : champ « ' + champ + ' », caché tant que l\'étape ne le demande pas');
  ok(/API\.colisNoyau \? \(peut\('colis\.statut'\) \? [^\n]*bouton\('annuler'/.test(admin) && /'annuler': 'colis\.statut'/.test(admin), 'allumé : « Annuler le colis » remplace « Supprimer »');
  ok(/if \(API\.colisNoyau\) return avancerNoyau\(/.test(admin), 'allumé : le formulaire de statut passe par les étapes du noyau');
  ok(/h\.statut_noyau \? \(t\('c-colis-' \+ h\.statut_noyau\)/.test(fs.readFileSync('assets/js/ses-ui.js', 'utf8')), 'l\'historique sait nommer une étape du noyau');
  ok(/colisNoyau: false,/.test(fs.readFileSync('assets/js/config.js', 'utf8')), 'config.js : l\'interrupteur existe, éteint (à allumer par le propriétaire)');
  console.log('PASS bascule des colis (site) : ' + n + ' vérifications — éteint rien ne change, allumé les sept fonctions avec leurs paramètres réels, démonstration sans noyau, réponses réelles, écran.');
})().catch((e) => { console.error('ÉCHEC bascule des colis (site) : ' + (e && e.message)); process.exit(1); });
