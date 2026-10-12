// Les webhooks de paiement côté serveur (phase 6, scripts/paiements/) : signature, normalisation, réponse au prestataire, secrets.
//
//   node outils/tests/paiements-webhook.mjs
//
// Ce qu'on éprouve : (1) la signature HMAC du corps BRUT, comparée en temps constant ; un corps retouché, une signature absente ou
// mal formée, un secret absent : non vérifié ; (2) un événement non vérifié est quand même confié à la base (qui le journalise sans
// l'appliquer), avec p_verified = false ; (3) un prestataire dont l'adaptateur n'est pas écrit (Azul, MonCash, NatCash) refuse tout ;
// (4) corps illisible ou incomplet : 400, prestataire inconnu : 404, base injoignable : 503 (le prestataire réessaiera, la base est
// idempotente) ; (5) la base ne reçoit jamais le corps ni un secret, seulement une empreinte ; le journal non plus ; (6) la porte
// HTTP (webhook.mjs) : POST seul, taille bornée, appel de ses_payment_event avec la clé du serveur.
import assert from 'node:assert/strict';
import { ADAPTATEURS, egaliteConstante, hmacHex, traiterWebhook, valide } from '../../scripts/paiements/prestataires.mjs';

let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };
const SECRET = 'whsec_essai_' + 'x'.repeat(20);
const corps = JSON.stringify({ id: 'evt_001', reference: 'ord_42', amount: 35, currency: 'USD', status: 'succeeded', client: { email: 'marie@exemple.test' } });

// 1. la signature
ok(egaliteConstante('abc', 'abc') && !egaliteConstante('abc', 'abd') && !egaliteConstante('abc', 'abcd'), 'comparaison constante');
const sig = await hmacHex(SECRET, corps);
ok(/^[0-9a-f]{64}$/.test(sig), 'HMAC-SHA256 hexadécimal');
ok(await ADAPTATEURS.CARD.verifier(corps, { 'x-ses-signature': sig }, SECRET), 'bonne signature : vérifié');
ok(!(await ADAPTATEURS.CARD.verifier(corps.replace('35', '3500'), { 'x-ses-signature': sig }, SECRET)), 'montant retouché : non vérifié');
ok(!(await ADAPTATEURS.CARD.verifier(corps, { 'x-ses-signature': sig }, 'autre-secret')), 'mauvais secret : non vérifié');
ok(!(await ADAPTATEURS.CARD.verifier(corps, {}, SECRET)) && !(await ADAPTATEURS.CARD.verifier(corps, { 'x-ses-signature': 'zz' }, SECRET)), 'signature absente ou mal formée');
ok(!(await ADAPTATEURS.CARD.verifier(corps, { 'x-ses-signature': sig }, null)), 'sans secret configuré : jamais vérifié');
for (const p of ['AZUL', 'MONCASH', 'NATCASH']) {
  ok(!(await ADAPTATEURS[p].verifier(corps, { 'x-ses-signature': sig }, SECRET)) && /documentation officielle/.test(ADAPTATEURS[p].aEcrire), p + ' : adaptateur à écrire, refuse tout');
}
// 2. la normalisation
const ev = ADAPTATEURS.CARD.normaliser(JSON.parse(corps));
ok(valide(ev) && ev.status === 'SUCCEEDED' && ev.external_id === 'ord_42' && ev.event_key === 'evt_001' && ev.currency === 'USD', 'événement normalisé dans le vocabulaire de la base');
ok(!valide({ ...ev, currency: 'EUR' }) && !valide({ ...ev, status: undefined }) && !valide({ ...ev, amount: -1 }) && !valide({ ...ev, event_key: '' }), 'hors vocabulaire : refusé');

// 3. le traitement complet, avec une fausse base
const appels = [];
const base = async (args) => { appels.push(args); return { outcome: args.p_verified ? 'APPLIED' : 'REJECTED_UNVERIFIED', replayed: false }; };
const lireSecret = (code) => (code === 'CARD' ? SECRET : null);
let r = await traiterWebhook({ prestataire: 'card', corpsBrut: corps, entetes: { 'X-SES-Signature': sig }, lireSecret, appelerBase: base });
ok(r.statut === 200 && r.corps.resultat === 'APPLIED' && appels[0].p_verified === true && appels[0].p_provider === 'CARD', 'vérifié : confié à la base, qui applique');
ok(appels[0].p_raw_reference.startsWith('sha256:') && !JSON.stringify(appels[0]).includes('marie@') && !JSON.stringify(appels[0]).includes(SECRET),
   'la base reçoit une empreinte, jamais le corps (données personnelles) ni le secret');
r = await traiterWebhook({ prestataire: 'CARD', corpsBrut: corps.replace('35', '3500'), entetes: { 'x-ses-signature': sig }, lireSecret, appelerBase: base });
ok(r.statut === 200 && appels[1].p_verified === false && appels[1].p_amount === 3500, 'retouché : journalisé NON vérifié (la base ne l\'applique pas), 200 pour que le prestataire n\'insiste pas');
r = await traiterWebhook({ prestataire: 'MONCASH', corpsBrut: corps, entetes: { 'x-ses-signature': sig }, lireSecret: () => SECRET, appelerBase: base });
ok(r.statut === 200 && appels[2].p_verified === false, 'MonCash sans adaptateur : non vérifié, jamais appliqué');
ok((await traiterWebhook({ prestataire: 'PAYPAL', corpsBrut: corps, entetes: {}, lireSecret, appelerBase: base })).statut === 404, 'prestataire inconnu : 404');
ok((await traiterWebhook({ prestataire: 'CARD', corpsBrut: '{pas du json', entetes: {}, lireSecret, appelerBase: base })).statut === 400, 'corps illisible : 400');
ok((await traiterWebhook({ prestataire: 'CARD', corpsBrut: JSON.stringify({ id: 'x' }), entetes: {}, lireSecret, appelerBase: base })).statut === 400, 'événement incomplet : 400');
const nAvant = appels.length;
r = await traiterWebhook({ prestataire: 'CARD', corpsBrut: corps, entetes: { 'x-ses-signature': sig }, lireSecret, appelerBase: async () => { throw new Error('réseau'); } });
ok(r.statut === 503 && appels.length === nAvant, 'base injoignable : 503, le prestataire réessaiera');

// 4. la porte HTTP
process.env.SUPABASE_URL = 'https://projet-essai.supabase.co';
process.env.SUPABASE_SERVICE_ROLE_KEY = 'cle-serveur-essai';
process.env.SES_PAY_CARD = SECRET;
const vus = [];
globalThis.fetch = async (url, init) => { vus.push({ url, init }); return { ok: true, json: async () => ({ outcome: 'APPLIED', replayed: false }) }; };
const journal = [];
const log = console.log; console.log = (x) => journal.push(String(x));
const { gerer } = await import('../../scripts/paiements/webhook.mjs');
let rep = await gerer(new Request('https://projet-essai.supabase.co/functions/v1/paiement-webhook/CARD', { method: 'POST', body: corps, headers: { 'x-ses-signature': sig } }));
const get = await gerer(new Request('https://projet-essai.supabase.co/functions/v1/paiement-webhook/CARD', { method: 'GET' }));
const gros = await gerer(new Request('https://projet-essai.supabase.co/functions/v1/paiement-webhook/CARD', { method: 'POST', body: 'x'.repeat(70000) }));
console.log = log;
ok(rep.status === 200 && vus[0].url === 'https://projet-essai.supabase.co/rest/v1/rpc/ses_payment_event' && vus[0].init.headers.apikey === 'cle-serveur-essai'
   && JSON.parse(vus[0].init.body).p_verified === true, 'la porte appelle ses_payment_event avec la clé du serveur');
ok(get.status === 405 && gros.status === 413 && vus.length === 1, 'POST seulement, taille bornée');
ok(journal.length >= 1 && journal.every((l) => !l.includes(SECRET) && !l.includes('marie@') && !l.includes(sig) && !l.includes('cle-serveur-essai')), 'le journal ne contient ni secret, ni signature, ni données du client');

console.log('PASS webhooks de paiement : ' + n + ' vérifications — signature HMAC en temps constant, non vérifié journalisé jamais appliqué, adaptateurs à écrire qui refusent tout, codes HTTP, ni corps ni secret vers la base ou le journal.');
