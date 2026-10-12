// =============================================================================
// Speed Express Shipping — les prestataires de paiement, côté SERVEUR (phase 6)
// -----------------------------------------------------------------------------
// Ce module tourne dans une Edge Function de Supabase (Deno) ou dans Node : jamais dans un navigateur. Il est le seul endroit qui
// touche aux SECRETS des prestataires (clé secrète, secret de webhook) — lus dans l'environnement par le NOM que la base donne
// (logistics.payment_provider.credentials_env). Aucun secret n'est écrit dans le dépôt, ni envoyé à la base, ni renvoyé au navigateur.
//
// Un prestataire = un adaptateur :
//   verifier(corpsBrut, entetes, secret) → true / false : la signature du webhook, contrôlée en temps constant ;
//   normaliser(corps)                     → { event_key, external_id, amount, currency, status, raw_reference } ;
// La base reçoit le résultat (vérifié ou non) et décide seule : appliquer, refuser, mettre de côté (logistics.ingest_payment_event).
//
// Brancher un vrai prestataire (Azul, MonCash, NatCash, une passerelle Visa / Mastercard) : écrire SON adaptateur d'après SA
// documentation (schéma de signature, noms des champs, états), le tester avec ses exemples officiels, puis l'activer dans la base
// (lg_configure_payment_provider). Tant qu'un adaptateur n'est pas écrit, il REFUSE tout : un événement non vérifié est
// journalisé par la base, jamais appliqué.
// =============================================================================

const ETATS = ['PENDING', 'SUCCEEDED', 'FAILED', 'CANCELLED', 'REFUNDED'];
const DEVISES = ['USD', 'DOP', 'HTG'];

/* Comparaison en temps constant de deux chaînes hexadécimales (la durée ne dit rien du nombre de caractères justes). */
export function egaliteConstante(a, b) {
  const x = String(a || ''), y = String(b || '');
  let d = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) d |= (x.charCodeAt(i) || 0) ^ (y.charCodeAt(i) || 0);
  return d === 0;
}

/* HMAC-SHA256 en hexadécimal, par Web Crypto (présent dans Deno, Node 18+ et les Edge Functions). */
export async function hmacHex(secret, message) {
  const cle = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign('HMAC', cle, new TextEncoder().encode(message));
  return Array.from(new Uint8Array(sig)).map((o) => o.toString(16).padStart(2, '0')).join('');
}

/* Empreinte courte de ce qui a été reçu : la base la garde (raw_reference) à la place du contenu, qui peut porter des données personnelles. */
export async function empreinte(corpsBrut) {
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(String(corpsBrut)));
  return 'sha256:' + Array.from(new Uint8Array(h)).slice(0, 16).map((o) => o.toString(16).padStart(2, '0')).join('');
}

/* Un événement normalisé est-il complet et dans le vocabulaire de la base ? */
export function valide(ev) {
  return !!ev && typeof ev.event_key === 'string' && ev.event_key.length > 0 && ev.event_key.length <= 200
    && typeof ev.external_id === 'string' && ev.external_id.length > 0 && ev.external_id.length <= 200
    && typeof ev.amount === 'number' && isFinite(ev.amount) && ev.amount >= 0
    && DEVISES.includes(ev.currency) && ETATS.includes(ev.status);
}

/* L'adaptateur GÉNÉRIQUE : une signature « HMAC-SHA256 du corps brut, en hexadécimal », dans l'en-tête X-SES-Signature, et un corps
   JSON { id, reference, amount, currency, status }. C'est le contrat des essais et d'une passerelle qu'on configure soi-même ; un
   prestataire réel a le sien. */
const generique = {
  async verifier(corpsBrut, entetes, secret) {
    if (!secret) return false;
    const recu = String(entetes['x-ses-signature'] || '').trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(recu)) return false;
    return egaliteConstante(recu, await hmacHex(secret, corpsBrut));
  },
  normaliser(corps) {
    const etat = { succeeded: 'SUCCEEDED', paid: 'SUCCEEDED', pending: 'PENDING', failed: 'FAILED', cancelled: 'CANCELLED', canceled: 'CANCELLED', refunded: 'REFUNDED' }[String(corps.status || '').toLowerCase()];
    return { event_key: String(corps.id || ''), external_id: String(corps.reference || ''), amount: Number(corps.amount), currency: String(corps.currency || '').toUpperCase(), status: etat };
  }
};

/* Un prestataire dont l'adaptateur n'est pas encore écrit : il refuse tout (la base journalise l'événement « non vérifié »). */
function aEcrire(nom) {
  return {
    async verifier() { return false; },
    normaliser(corps) { return generique.normaliser(corps); },
    aEcrire: 'Adaptateur ' + nom + ' à écrire d\'après la documentation officielle du prestataire (signature, champs, états) avant toute activation.'
  };
}

export const ADAPTATEURS = {
  CARD: generique,                 // passerelle carte (Visa / Mastercard) configurée avec le schéma générique
  AZUL: aEcrire('Azul'),
  MONCASH: aEcrire('MonCash'),
  NATCASH: aEcrire('NatCash')
};

/* Le traitement d'un webhook, indépendant de l'hébergement. « appelerBase » appelle public.ses_payment_event avec la clé du serveur.
   Rend { statut HTTP, corps } : 200 dès que la base a journalisé (même un événement refusé : le prestataire ne doit pas réessayer
   sans fin), 400 pour un corps illisible, 404 pour un prestataire inconnu, 503 si la base ne répond pas (le prestataire réessaiera :
   l'idempotence de la base rend ce nouvel essai sans danger). */
export async function traiterWebhook({ prestataire, corpsBrut, entetes, lireSecret, appelerBase }) {
  const code = String(prestataire || '').toUpperCase();
  const a = ADAPTATEURS[code];
  if (!a) return { statut: 404, corps: { erreur: 'prestataire inconnu' } };
  let corps;
  try { corps = JSON.parse(corpsBrut); } catch (e) { return { statut: 400, corps: { erreur: 'corps illisible' } }; }
  const ev = a.normaliser(corps || {});
  if (!valide(ev)) return { statut: 400, corps: { erreur: 'événement incomplet' } };
  const entetesMin = {};
  Object.keys(entetes || {}).forEach((k) => { entetesMin[k.toLowerCase()] = entetes[k]; });
  const verifie = await a.verifier(corpsBrut, entetesMin, lireSecret(code));
  let r;
  try {
    r = await appelerBase({ p_provider: code, p_event_key: ev.event_key, p_external_id: ev.external_id, p_amount: ev.amount, p_currency: ev.currency,
                            p_status: ev.status, p_verified: verifie, p_raw_reference: await empreinte(corpsBrut) });
  } catch (e) {
    return { statut: 503, corps: { erreur: 'base indisponible' } };
  }
  return { statut: 200, corps: { recu: true, resultat: r && r.outcome, rejoue: !!(r && r.replayed) } };
}
