// =============================================================================
// Speed Express Shipping — la logique des fonctions serveur des notifications (phase 11)
// -----------------------------------------------------------------------------
// Ce module tourne dans une Edge Function de Supabase (Deno) ou dans Node (essais) : JAMAIS dans un navigateur. Il ne fait que vérifier et
// traduire ; la base décide (ses_nt_provider_event), et les clés n'arrivent que par l'environnement de la fonction. Trois usages :
//   1. les accusés de Meta (WhatsApp) : signature X-Hub-Signature-256 (HMAC-SHA256 du corps avec le secret de l'application Meta) ;
//   2. les accusés de Brevo (e-mail) : un jeton secret dans l'adresse du webhook (Brevo ne signe pas), comparé en temps constant ;
//   3. les e-mails de COMPTE de Supabase Auth (« Send Email Hook ») : signature « Standard Webhooks » (webhook-id, webhook-timestamp,
//      webhook-signature), puis l'e-mail écrit dans la langue choisie à l'inscription (textes : courriels-compte.json).
// =============================================================================

const enc = new TextEncoder();

/* Égalité en temps constant : la durée de la comparaison ne dit rien du secret. */
export function egaliteConstante(a, b) {
  const x = String(a || ''), y = String(b || '');
  let d = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) d |= (x.charCodeAt(i) || 0) ^ (y.charCodeAt(i) || 0);
  return d === 0 && x.length > 0;
}

async function hmac(cleOctets, message) {
  const k = await crypto.subtle.importKey('raw', cleOctets, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return new Uint8Array(await crypto.subtle.sign('HMAC', k, enc.encode(message)));
}
const hex = (o) => Array.from(o).map((b) => b.toString(16).padStart(2, '0')).join('');
const b64 = (o) => btoa(String.fromCharCode(...o));
const deB64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

// ---------------------------------------------------------------------------------------------------------------------- 1. Meta (WhatsApp)
export async function verifierMeta(corpsBrut, entete, secretApp) {
  if (!secretApp || !entete || !/^sha256=[0-9a-f]{64}$/.test(entete)) return false;
  return egaliteConstante(entete.slice(7), hex(await hmac(enc.encode(secretApp), corpsBrut)));
}
/* L'abonnement du webhook (GET) : Meta envoie hub.challenge, qu'on ne renvoie que si le jeton de vérification est le bon. */
export function abonnementMeta(params, jetonVerification) {
  if (params.get('hub.mode') === 'subscribe' && jetonVerification && egaliteConstante(params.get('hub.verify_token'), jetonVerification)) {
    const c = params.get('hub.challenge') || '';
    return /^[A-Za-z0-9_-]{1,100}$/.test(c) ? c : null;
  }
  return null;
}
const STATUTS_META = { sent: 'SENT', delivered: 'DELIVERED', read: 'READ', failed: 'FAILED' };
export function accusesMeta(j) {
  const sortie = [];
  for (const e of (j && j.entry) || []) for (const ch of e.changes || []) for (const s of (ch.value && ch.value.statuses) || []) {
    const statut = STATUTS_META[s.status];
    if (!statut || typeof s.id !== 'string' || !s.id) continue;
    const err = (s.errors || [])[0];
    sortie.push({ fournisseur: 'meta', ref: s.id.slice(0, 200), statut, erreur: err ? String(err.code || '') + ' ' + String(err.title || err.message || '').slice(0, 150) : null,
                  quand: /^[0-9]{9,11}$/.test(String(s.timestamp || '')) ? new Date(Number(s.timestamp) * 1000).toISOString() : null });
  }
  return sortie;
}

// ---------------------------------------------------------------------------------------------------------------------- 2. Brevo (e-mail)
export function verifierBrevo(jetonRecu, secret) { return !!secret && secret.length >= 24 && egaliteConstante(jetonRecu, secret); }
// Un rebond temporaire (soft_bounce, deferred) n'est pas un échec : Brevo réessaie lui-même. Le reste devient un accusé.
const STATUTS_BREVO = { delivered: 'DELIVERED', opened: 'READ', unique_opened: 'READ', hard_bounce: 'BOUNCED', invalid_email: 'BOUNCED', blocked: 'BOUNCED',
                        error: 'FAILED', spam: 'COMPLAINT', complaint: 'COMPLAINT' };
export function accusesBrevo(j) {
  const liste = Array.isArray(j) ? j : [j];
  const sortie = [];
  for (const e of liste) {
    const statut = e && STATUTS_BREVO[String(e.event || '').toLowerCase()];
    const ref = e && (e['message-id'] || e.messageId || e['message_id']);
    if (!statut || typeof ref !== 'string' || !ref) continue;
    sortie.push({ fournisseur: 'brevo', ref: ref.slice(0, 200), statut, erreur: statut === 'BOUNCED' || statut === 'FAILED' ? String(e.event) + (e.reason ? ' : ' + String(e.reason).slice(0, 150) : '') : null,
                  quand: e.ts_event ? new Date(Number(e.ts_event) * 1000).toISOString() : (e.date ? String(e.date).slice(0, 40) : null) });
  }
  return sortie;
}

// ---------------------------------------------------------------------------------------------------------------------- 3. Supabase Auth
/* « Standard Webhooks » : signature = base64(HMAC-SHA256(secret, id + '.' + horodatage + '.' + corps)) ; le secret s'écrit « v1,whsec_<base64> ».
   L'en-tête peut porter plusieurs signatures (« v1,xxx v1,yyy ») ; un horodatage de plus de 5 minutes est refusé (rejeu). */
export async function verifierStandardWebhook({ id, horodatage, signatures, corpsBrut, secret, maintenant }) {
  const s = String(secret || '').replace(/^v1,/, '').replace(/^whsec_/, '');
  if (!s || !id || !horodatage || !signatures || !/^[0-9]{9,11}$/.test(String(horodatage))) return false;
  const ecart = Math.abs((maintenant || Date.now()) / 1000 - Number(horodatage));
  if (ecart > 300) return false;
  let cle;
  try { cle = deB64(s); } catch (e) { return false; }
  const attendue = b64(await hmac(cle, id + '.' + horodatage + '.' + corpsBrut));
  return String(signatures).split(' ').some((x) => x.startsWith('v1,') && egaliteConstante(x.slice(3), attendue));
}

const ACTIONS = ['signup', 'recovery', 'magiclink', 'email_change', 'invite', 'reauthentication'];
function echapper(t) { return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

/* L'e-mail de compte, dans la langue du client. Le lien est celui de Supabase Auth (vérification du jeton), qui renvoie ensuite vers redirect_to,
   seulement s'il est sur le site (sinon : la page de connexion du site). */
export function courrielCompte(charge, textes, { supabaseUrl, siteUrl }) {
  const u = (charge && charge.user) || {}, d = (charge && charge.email_data) || {};
  const action = ACTIONS.includes(d.email_action_type) ? d.email_action_type : null;
  if (!action) throw new Error('action inconnue : ' + String(d.email_action_type).slice(0, 40));
  if (!u.email || !/@/.test(u.email)) throw new Error('adresse absente');
  const langue = ['fr', 'en', 'es', 'ht'].includes(u.user_metadata && u.user_metadata.langue) ? u.user_metadata.langue : 'fr';
  const t = textes.courriels[action][langue], pied = textes.pied[langue];
  const site = String(siteUrl || '').replace(/\/+$/, '');
  const retour = typeof d.redirect_to === 'string' && site && d.redirect_to.startsWith(site + '/') ? d.redirect_to : site + '/connexion.html';
  const lien = String(supabaseUrl).replace(/\/+$/, '') + '/auth/v1/verify?token=' + encodeURIComponent(d.token_hash || '') +
               '&type=' + encodeURIComponent(action === 'signup' ? 'signup' : action) + '&redirect_to=' + encodeURIComponent(retour);
  if (action !== 'reauthentication' && !d.token_hash) throw new Error('jeton absent');
  const texte = t.texte.replace('{lien}', lien).replace('{code}', String(d.token || ''));
  const html = '<p>' + echapper(t.texte).replace('{lien}', '<a href="' + echapper(lien) + '">' + echapper(lien) + '</a>').replace('{code}', '<strong>' + echapper(String(d.token || '')) + '</strong>') + '</p>' +
               '<p style="color:#626b78;font-size:13px">' + echapper(pied) + '</p>';
  return { a: u.email, sujet: t.sujet, texte: texte + '\n\n' + pied, html, langue, action };
}
