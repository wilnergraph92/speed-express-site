// =============================================================================
// Speed Express Shipping — les accusés des fournisseurs (Edge Function Supabase, phase 11)
// -----------------------------------------------------------------------------
// MODÈLE, non déployé : à copier dans supabase/functions/notifications-accuses/ avec serveur.mjs. Adresses à donner aux fournisseurs :
//   Meta (WhatsApp) : https://<projet>.supabase.co/functions/v1/notifications-accuses/meta   (GET : abonnement ; POST : statuts)
//   Brevo (e-mail)  : https://<projet>.supabase.co/functions/v1/notifications-accuses/brevo?jeton=<SES_BREVO_JETON_WEBHOOK>
//
// Environnement (secrets de la fonction, JAMAIS dans le dépôt ni dans un navigateur) :
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   fournis par Supabase
//   SES_META_APP_SECRET        secret de l'application Meta (vérifie X-Hub-Signature-256)
//   SES_META_JETON_ABONNEMENT  jeton choisi à l'abonnement du webhook chez Meta
//   SES_BREVO_JETON_WEBHOOK    jeton tiré au hasard (au moins 24 caractères), écrit dans l'adresse donnée à Brevo
// La vérification JWT de Supabase doit être DÉSACTIVÉE pour cette fonction : la sécurité est la signature (Meta) ou le jeton (Brevo).
// La fonction ne décide rien : la base (public.ses_nt_provider_event, ouverte au seul service_role) journalise, en ajout seul, idempotente.
// =============================================================================
import { verifierMeta, abonnementMeta, accusesMeta, verifierBrevo, accusesBrevo } from './serveur.mjs';

const ENV = (k) => (globalThis.Deno ? globalThis.Deno.env.get(k) : process.env[k]);

async function appelerBase(a) {
  const r = await fetch(ENV('SUPABASE_URL') + '/rest/v1/rpc/ses_nt_provider_event', {
    method: 'POST',
    headers: { apikey: ENV('SUPABASE_SERVICE_ROLE_KEY'), authorization: 'Bearer ' + ENV('SUPABASE_SERVICE_ROLE_KEY'), 'content-type': 'application/json' },
    body: JSON.stringify({ p_provider: a.fournisseur, p_ref: a.ref, p_status: a.statut, p_error: a.erreur, p_occurred_at: a.quand })
  });
  if (!r.ok) throw new Error('base : ' + r.status);
  return r.json();
}

export async function gerer(requete, base = appelerBase) {
  const url = new URL(requete.url), quoi = url.pathname.split('/').filter(Boolean).pop();
  if (quoi === 'meta' && requete.method === 'GET') {
    const c = abonnementMeta(url.searchParams, ENV('SES_META_JETON_ABONNEMENT'));
    return c ? new Response(c, { status: 200 }) : new Response('', { status: 403 });
  }
  if (requete.method !== 'POST') return new Response('', { status: 405 });
  const corpsBrut = await requete.text();
  if (corpsBrut.length > 262144) return new Response('', { status: 413 });
  let accuses;
  if (quoi === 'meta') {
    if (!(await verifierMeta(corpsBrut, requete.headers.get('x-hub-signature-256'), ENV('SES_META_APP_SECRET')))) return new Response('', { status: 401 });
    accuses = accusesMeta(JSON.parse(corpsBrut));
  } else if (quoi === 'brevo') {
    if (!verifierBrevo(url.searchParams.get('jeton'), ENV('SES_BREVO_JETON_WEBHOOK'))) return new Response('', { status: 401 });
    accuses = accusesBrevo(JSON.parse(corpsBrut));
  } else {
    return new Response('', { status: 404 });
  }
  const resultats = [];
  for (const a of accuses) resultats.push((await base(a)).result);
  // Le journal : le fournisseur, combien, les résultats. Jamais le corps, une adresse, un numéro, ni un secret.
  console.log(JSON.stringify({ quand: new Date().toISOString(), fournisseur: quoi, accuses: accuses.length, resultats }));
  return new Response(JSON.stringify({ recus: accuses.length }), { status: 200, headers: { 'content-type': 'application/json' } });
}

if (globalThis.Deno && globalThis.Deno.serve) globalThis.Deno.serve((r) => gerer(r));
