// La messagerie (étape 032) côté site, sans réseau, contre la VRAIE base : messagerie-exemples.json, écrit par
// outils/tests/logistique-messagerie-essai.py (signatures des dix façades lg_chat_* et leurs réponses réelles : boîte de l'équipe, de la
// direction, de la cliente, fils, annuaire, envoi…). Le même fichier sert aux deux applications (App_SES/tests/).
// Ce qu'on éprouve : (1) les trois implémentations de SES_API.messagerie ont les mêmes méthodes, et seule la version en ligne répond ;
// (2) chaque méthode appelle la bonne fonction avec des paramètres que la base connaît, et tous ceux qu'elle exige ; une photo part dans le
// dossier de SA conversation et ne s'ouvre que par une adresse signée ; (3) l'écran se dessine sur les réponses réelles, sans clé absente
// ni texte manquant, tout ce qui vient de la base échappé ; (4) le module dans la barre, la section, le script et les textes.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const EX = JSON.parse(fs.readFileSync('outils/tests/messagerie-exemples.json', 'utf8'));
const SIG = EX.signatures;
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };

function charger(cfg, local) {
  const appels = [], depots = [], signes = [], canaux = [];
  const client = {
    auth: { getSession: () => Promise.resolve({ data: { session: { user: { id: 'moi-1' } } } }) },
    rpc: (nom, args) => { appels.push({ nom, args }); return Promise.resolve({ data: { ok: true }, error: null }); },
    storage: { from: (b) => ({ upload: (chemin, f, o) => { depots.push({ b, chemin, o }); return Promise.resolve({ data: {}, error: null }); },
                               createSignedUrl: (chemin, s) => { signes.push({ b, chemin, s }); return Promise.resolve({ data: { signedUrl: 'https://signee/' + chemin }, error: null }); } }) },
    channel: (nom) => { const c = { nom, ons: [], on: (...a) => { c.ons.push(a); return c; }, subscribe: () => c }; canaux.push(c); return c; },
    removeChannel: () => {}
  };
  const fen = { addEventListener: () => {}, SES_CONFIG: cfg, supabase: { createClient: () => client } };
  const bac = { window: fen, location: { protocol: local ? 'http:' : 'https:', hostname: local ? 'localhost' : 'exemple.fr', href: 'https://exemple.fr/x.html', pathname: '/x.html' },
    document: { documentElement: { lang: 'fr' }, currentScript: null }, console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder,
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} } };
  vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), bac);
  return { API: fen.SES_API, appels, depots, signes, canaux };
}

(async () => {
  // ============================================================ 1. trois implémentations, mêmes méthodes
  const en = charger({ supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai' });
  const demo = charger({}, true), off = charger({});
  const M = en.API.METHODES_MESSAGERIE;
  ok(Array.isArray(M) && M.length === 13, 'treize méthodes déclarées');
  for (const x of [en, demo, off]) ok(JSON.stringify(Object.keys(x.API.messagerie).sort()) === JSON.stringify(M.slice().sort()), x.API.mode + ' : exactement les méthodes déclarées');
  ok(demo.API.mode === 'demo' && off.API.mode === 'off', 'les deux autres implémentations sont bien la démonstration et le site fermé');
  for (const x of [demo, off]) {
    let refuse = 0;
    for (const m of M.filter((k) => k !== 'surveiller')) { try { await x.API.messagerie[m]('a'); } catch (e) { refuse++; } }
    ok(refuse === M.length - 1 && typeof x.API.messagerie.surveiller(() => {}) === 'function', x.API.mode + ' : aucune conversation inventée, tout est refusé (surveiller ne fait rien)');
  }

  // ============================================================ 2. les appels, contre les signatures réelles
  const A = en.API.messagerie, conv = '00000000-0000-0000-0000-0000000000c1';
  const cas = [
    ['boite', [], 'lg_chat_inbox'], ['nonLus', [], 'lg_chat_unread'], ['messages', [conv], 'lg_chat_messages'], ['messages', [conv, 42], 'lg_chat_messages'],
    ['envoyer', [conv, ' Bonjour ', 'cle-0001-essai', 'ses-1234567890', conv + '/cle-0001-essai.jpg'], 'lg_chat_send'], ['envoyer', [conv, 'Seul', 'cle-0002-essai'], 'lg_chat_send'],
    ['marquerLu', [conv, '17'], 'lg_chat_mark_read'], ['annuaire', [], 'lg_chat_directory'], ['annuaire', ['ro'], 'lg_chat_directory'],
    ['ouvrirDirect', ['u2'], 'lg_chat_open_direct'], ['ouvrirClient', [], 'lg_chat_open_customer'], ['ouvrirClient', ['k1'], 'lg_chat_open_customer'],
    ['creerGroupe', [' Miami ', ['u2']], 'lg_chat_create_group'], ['modifierGroupe', [conv, { titre: 'X', ajouter: ['u3'], retirer: ['u2'], archive: true }], 'lg_chat_update_group'],
    ['modifierGroupe', [conv, {}], 'lg_chat_update_group']];
  for (const [m, args, fn] of cas) {
    en.appels.length = 0;
    await A[m](...args);
    const a = en.appels[0];
    ok(a && a.nom === fn, m + ' → ' + fn);
    ok(SIG[fn], fn + ' : la base la connaît');
    Object.keys(a.args).forEach((k) => ok(SIG[fn].some((p) => p.nom === k), fn + ' : paramètre connu de la base (' + k + ')'));
    SIG[fn].filter((p) => !p.defaut).forEach((p) => ok(Object.prototype.hasOwnProperty.call(a.args, p.nom), fn + ' : paramètre exigé (' + p.nom + ')'));
  }
  ok(Object.keys(SIG).sort().join() === [...new Set(cas.map((c) => c[2]))].sort().join(), 'le site appelle les dix façades, et seulement elles');
  en.appels.length = 0;
  await A.envoyer(conv, ' Bonjour ', 'cle-0001-essai', 'ses-1234567890', conv + '/cle-0001-essai.jpg');
  const env = en.appels[0].args;
  ok(env.p_body === 'Bonjour' && env.p_parcel === 'SES-1234567890' && env.p_client_key === 'cle-0001-essai' && env.p_photo_path === conv + '/cle-0001-essai.jpg', 'le texte nettoyé, le colis en majuscules, la clé et la photo');
  en.appels.length = 0;
  await A.envoyer(conv, 'Sans clé');
  ok(/^[A-Za-z0-9_-]{8,80}$/.test(en.appels[0].args.p_client_key), 'sans clé fournie, une clé valide pour la base est tirée');
  ok(en.API.cleMessage() !== en.API.cleMessage() && /^[A-Za-z0-9_-]{8,80}$/.test(en.API.cleMessage()), 'deux clés ne se ressemblent jamais');
  // la photo : le dossier privé, celui de la conversation ; une image, 5 Mo au plus
  const chemin = await A.deposerPhoto(conv, { type: 'image/jpeg', size: 1000 }, 'cle-0003-essai');
  ok(chemin === conv + '/cle-0003-essai.jpg' && en.depots[0].b === 'messagerie' && en.depots[0].o.upsert === false, 'une photo part dans le dossier « messagerie », sous sa conversation, sans écraser');
  let refus = [];
  for (const f of [{ type: 'application/pdf', size: 10 }, { type: 'image/png', size: 6 * 1024 * 1024 }]) { try { await A.deposerPhoto(conv, f); } catch (e) { refus.push(e.code); } }
  ok(refus.join() === 'photo-invalide,photo-trop-lourde' && en.depots.length === 1, 'un autre fichier, ou une photo trop lourde : refusés avant tout envoi');
  const url = await A.adressePhoto(chemin);
  ok(url === 'https://signee/' + chemin && en.signes[0].b === 'messagerie' && en.signes[0].s <= 600, 'une photo ne s\'ouvre que par une adresse signée de dix minutes au plus');
  const stop = A.surveiller(() => {});
  await new Promise((r) => setTimeout(r, 10));
  const c0 = en.canaux[0];
  ok(c0 && c0.ons[0][1].table === 'ses_chat_signal' && c0.ons[0][1].event === 'INSERT' && c0.ons[0][1].filter === 'user_id=eq.moi-1' && typeof stop === 'function',
     'le temps réel écoute ses_chat_signal, pour ce compte seulement');

  // ============================================================ 3. l'écran, sur les réponses réelles
  const html = fs.readFileSync('tableau-de-bord.html', 'utf8'), js = fs.readFileSync('assets/js/ses-messagerie.js', 'utf8');
  const textes = {};
  for (const m of html.matchAll(/<span data-t="([^"]+)">([^<]*)<\/span>/g)) textes[m[1]] = m[2];
  const manquants = new Set();
  const t = (k, v) => { if (!(k in textes)) manquants.add(k); let s = textes[k] || ''; Object.keys(v || {}).forEach((x) => { s = s.replace('{' + x + '}', v[x]); }); return s; };
  const esc = (x) => String(x).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  const defs = [];
  const C = { enregistrer: (d) => defs.push(d), t, e: esc, date: (x) => String(x || ''), modules: () => EX.inbox_direction ? ['messagerie'] : [], actions: {} };
  const zoneDe = () => { const el = {}; return { querySelector: (s) => { el[s] = el[s] || { innerHTML: '', value: '', removeAttribute: () => {}, setAttribute: () => {}, getAttribute: () => null,
    querySelectorAll: () => [], scrollHeight: 0, scrollTop: 0, clientHeight: 0 }; return el[s]; }, el }; };
  vm.runInNewContext(js, { window: { SES_CENTRE: C, SES_API: en.API, SES_UI: { surLangue: () => {}, occuper: () => () => {} } },
    document: { addEventListener: () => {}, getElementById: () => null, body: { contains: () => true } }, Date, Math, String, Number, JSON, Array, Object, Promise, setTimeout, clearTimeout });
  ok(defs.length === 1 && defs[0].id === 'messagerie' && typeof defs[0].rendre === 'function' && typeof defs[0].actualiser === 'function', 'la section « messagerie » est inscrite au centre');
  const V = C.messagerieVues;
  for (const k of ['inbox_direction', 'inbox_equipe', 'inbox_client']) {
    const z = zoneDe(); V.poser(EX[k], null); V.dessinerListe(z, EX[k].items[0] && EX[k].items[0].conversation_id);
    const h = z.el['#cc-msg-convs'].innerHTML;
    ok(h.includes('cc-msg-conv') && !/undefined|null|\[object/.test(h), k + ' : la liste se dessine sans clé absente (' + h.slice(0, 80) + ')');
    ok(EX[k].items.every((x) => h.includes(esc(x.title))), k + ' : chaque conversation porte son titre');
  }
  ok(EX.inbox_equipe.items.some((x) => x.kind === 'CUSTOMER' && x.customer) && EX.inbox_client.items.every((x) => x.customer === null || x.customer === undefined),
     'l\'équipe voit le client d\'une conversation ; la cliente, jamais sa propre fiche');
  for (const k of ['messages_equipe', 'messages_client', 'messages_groupe']) {
    const h = EX[k].items.map(V.message).join('');
    ok(EX[k].items.length && !/undefined|null|\[object/.test(h), k + ' : chaque message se dessine sans clé absente');
    ok(EX[k].items.filter((m) => m.parcel).every((m) => h.includes('data-numero="' + esc(m.parcel.tracking_number) + '"')), k + ' : un colis cité ouvre sa fiche');
    ok(EX[k].items.filter((m) => m.photo_path).every((m) => h.includes('data-photo="' + esc(m.photo_path) + '"') && !h.includes('src="' + m.photo_path)),
       k + ' : une photo attend son adresse signée (jamais le chemin brut en adresse)');
  }
  ok(EX.messages_client.items.filter((m) => m.author.kind === 'STAFF').every((m) => !/\s/.test(m.author.name)), 'la cliente ne voit que le prénom de qui lui répond');
  const piege = { id: 9, at: '2026-10-20T10:00:00Z', mine: false, body: '<img src=x onerror=alert(1)>\nligne 2', photo_path: null,
                  author: { kind: 'STAFF', name: '<b>Rose</b>' }, parcel: { tracking_number: '"><script>' } };
  const hp = V.message(piege);
  ok(!hp.includes('<img') && !hp.includes('<b>') && !hp.includes('<script>') && hp.includes('&lt;img') && hp.includes('<br>'), 'tout ce qui vient de la base est échappé (les retours à la ligne gardés)');
  ok(V.apercu({ mine: true, body: 'Ok' }) === t('c-msg-vous') + ' : Ok' && V.apercu({ mine: false, author: 'Rose', photo: true, body: '' }) === 'Rose : ' + t('c-msg-photo'), 'l\'aperçu dit qui et quoi');
  ok(manquants.size === 0, 'aucun texte manquant : ' + [...manquants].join(', '));
  // les clés de texte écrites dans le fichier existent toutes dans la page
  const cles = new Set([...js.matchAll(/t\('((?:c-msg|c-gst|c-envoi|c-chargement)[a-z0-9-]*)'/g)].map((m) => m[1]));
  for (const k of cles) ok(k in textes, 'texte présent : ' + k);
  for (const k of ['erreur-photo-invalide', 'erreur-photo-trop-lourde', 'c-mod-messagerie', 'c-sec-messagerie', 'c-bientot-messagerie']) ok(k in textes, 'texte présent : ' + k);

  // ============================================================ 4. la barre, le script, la base
  ok(/<button type="button" role="tab" id="ses-o-messagerie" aria-controls="ses-p-centre"[^>]*data-module="messagerie" data-sections="messagerie" hidden>/.test(html), 'le module « Messagerie » est dans la barre (caché tant que la base ne l\'ouvre pas)');
  ok(/<script src="assets\/js\/ses-messagerie\.js\?v=\d+" defer><\/script>/.test(html) && html.indexOf('ses-messagerie.js') > html.indexOf('ses-centre-vues.js'), 'la page charge la messagerie, après le centre');
  ok(/\.cc-msg-moi/.test(fs.readFileSync('assets/css/ses-centre.css', 'utf8')) && /\[data-theme="sombre"\] \.cc-msg-moi/.test(fs.readFileSync('assets/css/ses-reglages.css', 'utf8')), 'les bulles ont leur variante sombre');
  ok(!/innerHTML\s*=\s*[^;]*\b(?:m|x|c)\.(?:body|title|name)\b(?![^;]*\be\()/.test(js), 'aucun texte de la base posé sans échappement');
  const sql = fs.readFileSync('outils/logistique/032-messagerie.sql', 'utf8');
  ok(/m := m \|\| 'messagerie'::text;/.test(sql), 'la base ouvre le module à toute l\'équipe (dashboard_access, 032)');
  console.log('PASS messagerie (site) : ' + n + ' vérifications — trois implémentations, dix façades aux paramètres réels, photos privées et signées, temps réel par compte, écran sur réponses réelles (échappé, sans texte manquant), module, script, textes.');
})().catch((e) => { console.error('ÉCHEC messagerie (site) : ' + (e && e.message)); process.exit(1); });
