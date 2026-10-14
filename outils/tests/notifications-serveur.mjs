// Les fonctions serveur des notifications (phase 11), sans réseau : les accusés de Meta et de Brevo, les e-mails de compte de Supabase Auth,
// la soumission des modèles WhatsApp. On exige : une signature fausse, absente, ou rejouée est refusée ; un jeton faux aussi ; chaque accusé
// devient le bon statut ; un rebond temporaire n'est pas un échec ; l'e-mail de compte est dans la langue du client, avec le lien de Supabase,
// et ne renvoie jamais hors du site ; le journal ne contient ni adresse, ni lien, ni jeton ; les textes sont complets dans les quatre langues.
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { readFileSync } from 'node:fs';

const S = await import('../../scripts/notifications/serveur.mjs');
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };

// ---------------------------------------------------------------------- 1. Meta
const SECRET_META = 'meta-app-secret-0123456789';
const corpsMeta = JSON.stringify({ object: 'whatsapp_business_account', entry: [{ changes: [{ field: 'messages', value: { statuses: [
  { id: 'wamid.A', status: 'delivered', timestamp: '1791900000', recipient_id: '50937001234' },
  { id: 'wamid.B', status: 'read', timestamp: '1791900100' },
  { id: 'wamid.C', status: 'failed', timestamp: '1791900200', errors: [{ code: 131026, title: 'Message undeliverable' }] },
  { id: 'wamid.D', status: 'deleted' }, { status: 'delivered' }] } }] }] });
const sigMeta = 'sha256=' + createHmac('sha256', SECRET_META).update(corpsMeta).digest('hex');
ok(await S.verifierMeta(corpsMeta, sigMeta, SECRET_META), 'Meta : la bonne signature passe');
ok(!(await S.verifierMeta(corpsMeta + ' ', sigMeta, SECRET_META)), 'Meta : un corps modifié est refusé');
ok(!(await S.verifierMeta(corpsMeta, sigMeta, 'autre-secret')) && !(await S.verifierMeta(corpsMeta, null, SECRET_META)) && !(await S.verifierMeta(corpsMeta, 'sha1=abc', SECRET_META))
   && !(await S.verifierMeta(corpsMeta, sigMeta, '')), 'Meta : autre secret, signature absente ou d\'un autre format, secret vide : refusé');
const acc = S.accusesMeta(JSON.parse(corpsMeta));
ok(acc.length === 3 && acc.map((a) => a.statut).join() === 'DELIVERED,READ,FAILED', 'Meta : remis, lu, échec ; un statut inconnu et un accusé sans identifiant sont ignorés');
ok(acc[2].erreur.startsWith('131026') && acc[0].quand === new Date(1791900000 * 1000).toISOString(), 'Meta : le code d\'erreur et l\'heure');
ok(!JSON.stringify(acc).includes('50937001234'), 'Meta : le numéro du destinataire ne passe pas à la base');
const p = (o) => new URLSearchParams(o);
ok(S.abonnementMeta(p({ 'hub.mode': 'subscribe', 'hub.verify_token': 'jeton-abonnement', 'hub.challenge': '1158201444' }), 'jeton-abonnement') === '1158201444', 'abonnement : le défi est rendu');
ok(S.abonnementMeta(p({ 'hub.mode': 'subscribe', 'hub.verify_token': 'faux', 'hub.challenge': '1' }), 'jeton-abonnement') === null
   && S.abonnementMeta(p({ 'hub.mode': 'subscribe', 'hub.verify_token': 'jeton-abonnement', 'hub.challenge': '<script>' }), 'jeton-abonnement') === null, 'abonnement : jeton faux, défi douteux : refusé');

// ---------------------------------------------------------------------- 2. Brevo
const JETON = 'brevo-jeton-webhook-0123456789abcdef';
ok(S.verifierBrevo(JETON, JETON) && !S.verifierBrevo('x', JETON) && !S.verifierBrevo(JETON, 'court') && !S.verifierBrevo(null, JETON), 'Brevo : le jeton, et un jeton trop court ne protège rien');
const ab = S.accusesBrevo([{ event: 'delivered', 'message-id': '<m1@relay>', ts_event: 1791900000 }, { event: 'hard_bounce', 'message-id': '<m2@relay>', reason: 'mailbox does not exist' },
  { event: 'soft_bounce', 'message-id': '<m3@relay>' }, { event: 'spam', 'message-id': '<m4@relay>' }, { event: 'click', 'message-id': '<m5@relay>' }, { event: 'delivered' }]);
ok(ab.map((a) => a.ref + ':' + a.statut).join() === '<m1@relay>:DELIVERED,<m2@relay>:BOUNCED,<m4@relay>:COMPLAINT', 'Brevo : remis, rebond définitif, plainte ; un rebond temporaire n\'est PAS un échec');
ok(S.accusesBrevo({ event: 'opened', 'message-id': '<m6@relay>' })[0].statut === 'READ', 'Brevo : un seul événement (pas une liste) aussi');

// ---------------------------------------------------------------------- 3. la fonction des accusés
process.env.SES_META_APP_SECRET = SECRET_META; process.env.SES_META_JETON_ABONNEMENT = 'jeton-abonnement'; process.env.SES_BREVO_JETON_WEBHOOK = JETON;
const W = await import('../../scripts/notifications/webhook-fournisseurs.mjs');
const recus = [];
const base = async (a) => { recus.push(a); return { result: 'APPLIED' }; };
const req = (url, o) => new Request('https://x.supabase.co/functions/v1/notifications-accuses' + url, o);
let r = await W.gerer(req('/meta', { method: 'POST', body: corpsMeta, headers: { 'x-hub-signature-256': sigMeta } }), base);
ok(r.status === 200 && recus.length === 3 && recus[0].fournisseur === 'meta', 'Meta signé : trois accusés confiés à la base');
recus.length = 0;
r = await W.gerer(req('/meta', { method: 'POST', body: corpsMeta, headers: { 'x-hub-signature-256': 'sha256=' + '0'.repeat(64) } }), base);
ok(r.status === 401 && recus.length === 0, 'Meta mal signé : 401, rien ne touche la base');
r = await W.gerer(req('/brevo?jeton=' + JETON, { method: 'POST', body: JSON.stringify({ event: 'hard_bounce', 'message-id': '<m2@relay>' }) }), base);
ok(r.status === 200 && recus.length === 1 && recus[0].statut === 'BOUNCED', 'Brevo avec son jeton : le rebond passe');
r = await W.gerer(req('/brevo?jeton=faux', { method: 'POST', body: '{}' }), base);
ok(r.status === 401, 'Brevo sans le bon jeton : 401');
ok((await W.gerer(req('/meta?hub.mode=subscribe&hub.verify_token=jeton-abonnement&hub.challenge=42', { method: 'GET' }), base)).status === 200, 'abonnement Meta');
ok((await W.gerer(req('/autre', { method: 'POST', body: '{}' }), base)).status === 404 && (await W.gerer(req('/brevo', { method: 'PUT', body: '{}' }), base)).status === 405, 'route inconnue, méthode refusée');

// ---------------------------------------------------------------------- 4. Standard Webhooks (Supabase Auth)
const cle = Buffer.from('cle-secrete-du-crochet-supabase-0123456789').toString('base64'), SECRET_HOOK = 'v1,whsec_' + cle;
const signer = (id, ts, corps) => 'v1,' + createHmac('sha256', Buffer.from(cle, 'base64')).update(id + '.' + ts + '.' + corps).digest('base64');
const maintenant = Date.now(), ts = String(Math.floor(maintenant / 1000));
const charge = { user: { id: 'u1', email: 'marie@essai.test', user_metadata: { langue: 'ht' } },
                 email_data: { token: '483920', token_hash: 'pkce_abc123', redirect_to: 'https://wilnergraph92.github.io/speed-express-site/espace-client.html', email_action_type: 'signup', site_url: 'x' } };
const corpsHook = JSON.stringify(charge);
const v = (o) => S.verifierStandardWebhook(Object.assign({ id: 'msg_1', horodatage: ts, signatures: signer('msg_1', ts, corpsHook), corpsBrut: corpsHook, secret: SECRET_HOOK, maintenant }, o));
ok(await v({}), 'crochet : la bonne signature passe');
ok(await v({ signatures: 'v1,faux ' + signer('msg_1', ts, corpsHook) }), 'crochet : plusieurs signatures, une bonne suffit');
ok(!(await v({ corpsBrut: corpsHook.replace('marie', 'pirate') })) && !(await v({ id: 'msg_2' })) && !(await v({ secret: 'v1,whsec_' + Buffer.from('autre').toString('base64') })),
   'crochet : corps, identifiant ou secret différents : refusé');
const vieux = String(Number(ts) - 600);
ok(!(await v({ horodatage: vieux, signatures: signer('msg_1', vieux, corpsHook) })), 'crochet : un message de plus de 5 minutes est refusé (rejeu)');
ok(!(await v({ signatures: null })) && !(await v({ secret: '' })), 'crochet : sans signature ou sans secret : refusé');

// ---------------------------------------------------------------------- 5. l'e-mail de compte
const textes = JSON.parse(readFileSync('scripts/notifications/courriels-compte.json', 'utf8'));
const OPT = { supabaseUrl: 'https://ltbqqchtyzlyakcsxxis.supabase.co', siteUrl: 'https://wilnergraph92.github.io/speed-express-site' };
const m = S.courrielCompte(charge, textes, OPT);
ok(m.a === 'marie@essai.test' && m.langue === 'ht' && m.sujet === textes.courriels.signup.ht.sujet, 'en créole, la langue choisie à l\'inscription');
ok(m.texte.includes('https://ltbqqchtyzlyakcsxxis.supabase.co/auth/v1/verify?token=pkce_abc123&type=signup&redirect_to=' + encodeURIComponent(charge.email_data.redirect_to)),
   'le lien de vérification de Supabase, qui renvoie à l\'espace client');
const ailleurs = S.courrielCompte({ user: charge.user, email_data: Object.assign({}, charge.email_data, { redirect_to: 'https://pirate.example/vol' }) }, textes, OPT);
ok(ailleurs.texte.includes(encodeURIComponent('https://wilnergraph92.github.io/speed-express-site/connexion.html')) && !ailleurs.texte.includes('pirate.example'), 'un retour hors du site devient la page de connexion');
const code = S.courrielCompte({ user: { email: 'a@b.c', user_metadata: {} }, email_data: { token: '771122', email_action_type: 'reauthentication' } }, textes, OPT);
ok(code.langue === 'fr' && code.texte.includes('771122') && !code.texte.includes('/auth/v1/verify'), 'le code de vérification, en français par défaut, sans lien');
const xss = S.courrielCompte({ user: { email: 'a@b.c', user_metadata: { langue: 'fr' } }, email_data: { token_hash: '"><script>', email_action_type: 'recovery', redirect_to: '' } }, textes, OPT);
ok(!xss.html.includes('<script>'), 'le lien est échappé dans la version HTML');
for (const [d, msg] of [[{ email_action_type: 'pirate', token_hash: 'x' }, 'action inconnue'], [{ email_action_type: 'signup' }, 'jeton absent']]) {
  assert.throws(() => S.courrielCompte({ user: { email: 'a@b.c' }, email_data: d }, textes, OPT), new RegExp(msg)); n++;
}
for (const action of ['signup', 'recovery', 'magiclink', 'email_change', 'invite', 'reauthentication']) {
  for (const lg of ['fr', 'en', 'es', 'ht']) ok(textes.courriels[action][lg].sujet && textes.courriels[action][lg].texte, 'texte ' + action + ' ' + lg);
}

// ---------------------------------------------------------------------- 6. la fonction des e-mails de compte
process.env.SES_HOOK_EMAIL_SECRET = SECRET_HOOK; process.env.SUPABASE_URL = OPT.supabaseUrl; process.env.SES_SITE_URL = OPT.siteUrl;
const C = await import('../../scripts/notifications/courriels-compte.mjs');
const envoyes = [], journal = [];
const log = console.log; console.log = (l) => journal.push(l);
const reqHook = (corps, sig, t = ts) => new Request('https://x.supabase.co/functions/v1/courriels-compte', { method: 'POST', body: corps, headers: { 'webhook-id': 'msg_1', 'webhook-timestamp': t, 'webhook-signature': sig } });
r = await C.gerer(reqHook(corpsHook, signer('msg_1', ts, corpsHook)), async (x) => { envoyes.push(x); return true; });
ok(r.status === 200 && (await r.text()) === '{}' && envoyes.length === 1, 'Supabase reçoit 200 et {} : l\'e-mail est parti');
r = await C.gerer(reqHook(corpsHook, signer('msg_1', ts, corpsHook)), async () => false);
ok(r.status === 502 && JSON.parse(await r.text()).error.http_code === 502, 'le fournisseur refuse : Supabase le sait (l\'utilisateur peut redemander)');
r = await C.gerer(reqHook(corpsHook, 'v1,faux'), async () => true);
ok(r.status === 401, 'signature fausse : 401, rien n\'est envoyé');
console.log = log;
const tout = journal.join('\n');
ok(!tout.includes('marie@essai.test') && !tout.includes('pkce_abc123') && !tout.includes('verify'), 'le journal : ni adresse, ni lien, ni jeton');

// ---------------------------------------------------------------------- 7. les modèles WhatsApp
const WM = await import('../../scripts/notifications/whatsapp-modeles.mjs');
const { modeles, langues } = JSON.parse(readFileSync('scripts/notifications/whatsapp-modeles.json', 'utf8'));
ok(langues.ht === 'fr' && langues.fr === 'fr' && langues.en === 'en' && langues.es === 'es', 'créole → modèle français (WhatsApp n\'a pas le créole)');
const PERMIS = ['tracking_number', 'stage', 'shipment_code', 'invoice_number', 'amount', 'currency', 'date', 'message', 'code', 'expires_hours'];
for (const x of modeles) {
  const corps = x.components.find((c) => c.type === 'BODY');
  const noms = [...new Set((corps.text.match(/\{\{([a-z_]+)\}\}/g) || []).map((y) => y.slice(2, -2)))];
  ok(/^ses_[a-z_]+$/.test(x.name) && x.category === 'UTILITY' && x.parameter_format === 'NAMED' && ['fr', 'en', 'es'].includes(x.language)
     && noms.every((y) => PERMIS.includes(y)) && (!noms.length || corps.example.body_text_named_params.length === noms.length)
     && !/^\s*\{\{/.test(corps.text) && !/\}\}\s*$/.test(corps.text), 'modèle conforme à Meta : ' + x.name + ' (' + x.language + ')');
}
ok(WM.aSoumettre(modeles, [{ name: modeles[0].name, language: modeles[0].language }]).length === modeles.length - 1, 'seuls les modèles absents chez Meta sont soumis');
console.log('PASS fonctions serveur des notifications : ' + n + ' vérifications — signatures Meta, jeton Brevo, Standard Webhooks (rejeu refusé), accusés, '
  + 'e-mails de compte en quatre langues sans retour hors du site, journal sans adresse ni jeton, modèles WhatsApp conformes.');
