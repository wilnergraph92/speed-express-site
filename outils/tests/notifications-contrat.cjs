// Notifications côté couche de données : les trois implémentations (en ligne, démonstration, fermé) tiennent le MÊME contrat, celui de la
// vraie base (notifications-rpc.json et notifications-formes.json, écrits par logistique-notifications-essai.py).
// Et le temps réel : on n'écoute qu'une table, public.ses_signal, en insertion, filtrée par audience — jamais une table métier.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const SIGNATURES = JSON.parse(fs.readFileSync('outils/tests/notifications-rpc.json', 'utf8'));
const FORMES = JSON.parse(fs.readFileSync('outils/tests/notifications-formes.json', 'utf8'));
let n = 0; const ok = () => { n++; };

function charger(config, hote, extra) {
  const bac = Object.assign({ window: { addEventListener: () => {}, SES_CONFIG: config }, location: { protocol: 'https:', hostname: hote, href: 'https://' + hote + '/x.html', pathname: '/x.html' },
    document: { documentElement: { lang: 'fr' }, currentScript: null }, console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder,
    localStorage: (() => { const m = {}; return { getItem: (k) => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); }, removeItem: (k) => { delete m[k]; } }; })() }, extra || {});
  bac.window.localStorage = bac.localStorage;
  vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), bac);
  return bac.window.SES_API;
}
function cles(x, chemin) {
  chemin = chemin || '';
  const s = new Set();
  if (Array.isArray(x)) x.forEach((v) => cles(v, chemin + '[]').forEach((k) => s.add(k)));
  else if (x && typeof x === 'object') Object.keys(x).forEach((k) => { s.add(chemin + '.' + k); cles(x[k], chemin + '.' + k).forEach((c) => s.add(c)); });
  return s;
}
const rejet = async (p) => { try { await p; } catch (e) { return e.code; } return 'aucune-erreur'; };

(async () => {
  const faux = { appels: [], canaux: [] };
  faux.rpc = (nom, args) => { faux.appels.push({ nom, args }); return Promise.resolve({ data: nom === 'lg_my_notification_prefs' || nom === 'lg_set_notification_pref' ? [] : {}, error: null }); };
  faux.channel = (nom) => {
    const c = { nom, ecoutes: [], on(type, filtre, rappel) { c.ecoutes.push({ type, filtre, rappel }); return c; }, subscribe() { faux.canaux.push(c); return c; } };
    return c;
  };
  faux.removeChannel = (c) => { c.retire = true; };
  const cfg = { supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai' };
  const en = charger(cfg, 'exemple.fr', { window: { addEventListener: () => {}, SES_CONFIG: cfg, supabase: { createClient: () => ({ auth: {}, rpc: faux.rpc, channel: faux.channel, removeChannel: faux.removeChannel }) } } });
  const demo = charger({}, 'localhost');
  const off = charger({}, 'exemple.fr');
  const METHODES = Array.from(en.METHODES_NOTIFICATIONS);
  assert.deepEqual(METHODES.sort(), ['preferences', 'reglerPreference', 'sante', 'surveiller']); ok();
  for (const [nom, api] of [['en ligne', en], ['démonstration', demo], ['fermé', off]]) assert.deepEqual(Object.keys(api.notifications).sort(), METHODES, nom + ' : mêmes méthodes');
  ok();

  // en ligne : chaque appel respecte la signature
  for (const [m, args, fn] of [['preferences', [], 'lg_my_notification_prefs'], ['reglerPreference', ['email', false], 'lg_set_notification_pref'], ['sante', [], 'lg_cc_notification_health']]) {
    faux.appels.length = 0;
    await en.notifications[m].apply(null, args);
    const a = faux.appels[0], sig = SIGNATURES[fn];
    assert.equal(a.nom, fn); assert.ok(sig, fn + ' absente des signatures');
    Object.keys(a.args).forEach((k) => assert.ok(sig.some((p) => p.nom === k), m + ' envoie un paramètre inconnu : ' + k));
    sig.filter((p) => !p.defaut).forEach((p) => assert.ok(k(a.args, p.nom), m + ' oublie ' + p.nom));
  }
  function k(o, c) { return Object.prototype.hasOwnProperty.call(o, c); }
  ok();
  faux.appels.length = 0; await en.notifications.reglerPreference('sms', 'oui');
  assert.deepEqual(JSON.parse(JSON.stringify(faux.appels[0].args)), { p_channel: 'sms', p_enabled: true }, 'le choix part en vrai booléen'); ok();

  // le temps réel : une seule table, en insertion, filtrée par audience ; se désabonner retire le canal
  const recus = [];
  const arreter = en.notifications.surveiller('customer', (topic) => recus.push(topic));
  await new Promise((r) => setTimeout(r, 0));
  const c = faux.canaux[0];
  assert.equal(c.ecoutes.length, 1); assert.equal(c.ecoutes[0].type, 'postgres_changes');
  assert.deepEqual(JSON.parse(JSON.stringify(c.ecoutes[0].filtre)), { event: 'INSERT', schema: 'public', table: 'ses_signal', filter: 'audience=eq.customer' }, 'le client écoute ses signaux, rien d\'autre'); ok();
  c.ecoutes[0].rappel({ new: { topic: 'parcel', id: 1 } }); c.ecoutes[0].rappel({});
  assert.deepEqual(recus, ['parcel', ''], 'le rappel reçoit le seul domaine'); ok();
  arreter(); await new Promise((r) => setTimeout(r, 0));
  assert.equal(c.retire, true, 'se désabonner retire le canal'); ok();
  en.notifications.surveiller('staff', () => {}); await new Promise((r) => setTimeout(r, 0));
  assert.equal(faux.canaux[1].ecoutes[0].filtre.filter, 'audience=eq.staff'); ok();
  assert.equal(typeof en.notifications.surveiller('n-importe-quoi', () => {}), 'function'); await new Promise((r) => setTimeout(r, 0));
  assert.equal(faux.canaux[2].ecoutes[0].filtre.filter, 'audience=eq.customer', 'une audience inconnue retombe sur la plus étroite'); ok();
  // ancienne écoute (colis, factures) : toujours là pour le tableau de bord d'avant, et la nouvelle n'écoute aucune table métier
  const src = fs.readFileSync('assets/js/ses-api.js', 'utf8');
  const bloc = src.slice(src.indexOf('    notifications: {'), src.indexOf('    notifications: {') + 2500);
  assert.ok(!/table: '(colis|factures|clients|colis_historique)'/.test(bloc), 'le temps réel des notifications n\'écoute aucune table métier'); ok();

  // démonstration : préférences locales, même forme que la base ; fermé : rien
  assert.equal(await rejet(demo.notifications.preferences()), 'non-autorise', 'démonstration sans connexion : refusé'); ok();
  await demo.inscrire({ nom_complet: 'Essai Démo', email: 'demo-notif@essai.test', motDePasse: 'motdepasse-solide-1', telephone: '+509 3000 0000', pays: 'Haïti', ville: 'Delmas', adresse: '1 rue' }).catch(() => null);
  await demo.connecter('demo-notif@essai.test', 'motdepasse-solide-1').catch(() => null);
  const prefs = await demo.notifications.preferences().catch((e) => e.code);
  if (Array.isArray(prefs)) {
    assert.deepEqual(Array.from(cles(prefs)).sort(), FORMES.preferences.slice().sort(), 'démonstration : la forme des préférences est celle de la base'); ok();
    assert.deepEqual(JSON.parse(JSON.stringify(prefs.map((p) => p.channel))), ['email', 'in_app', 'push', 'sms', 'whatsapp']); ok();
    const apres = await demo.notifications.reglerPreference('email', false);
    assert.equal(apres.find((p) => p.channel === 'email').enabled, false); ok();
    assert.equal(await rejet(demo.notifications.reglerPreference('in_app', false)), 'donnee-invalide', 'le portail ne se coupe pas'); ok();
    assert.equal(await rejet(demo.notifications.reglerPreference('email', 'oui')), 'donnee-invalide', 'ni oui ni non'); ok();
  } else {
    assert.fail('la démonstration n\'a pas pu ouvrir de session pour l\'essai : ' + prefs);
  }
  assert.equal(await rejet(demo.notifications.sante()), 'non-autorise'); ok();
  assert.equal(await rejet(off.notifications.preferences()), 'ferme'); assert.equal(typeof off.notifications.surveiller('customer', () => {}), 'function'); ok();
  console.log('PASS notifications (contrat) : ' + n + ' vérifications — trois implémentations, signatures de la base, préférences de même forme, temps réel limité au signal sans donnée.');
})().catch((e) => { console.error('ÉCHEC notifications (contrat) : ' + (e && e.message)); process.exit(1); });
