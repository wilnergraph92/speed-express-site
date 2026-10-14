// =============================================================================
// Speed Express Shipping — les e-mails de COMPTE, dans la langue du client (Edge Function Supabase, phase 11)
// -----------------------------------------------------------------------------
// MODÈLE, non déployé : à copier dans supabase/functions/courriels-compte/ avec serveur.mjs et courriels-compte.json, puis dans Supabase :
// Authentication › Hooks › « Send Email Hook » → HTTPS → cette fonction (Supabase donne alors le secret « v1,whsec_… »).
// Sans ce crochet, Supabase envoie ses propres e-mails (en une seule langue) : rien ne casse, le crochet ne fait qu'en améliorer le texte.
//
// Environnement (secrets de la fonction, JAMAIS dans le dépôt ni dans un navigateur) :
//   SUPABASE_URL                  fourni par Supabase
//   SES_HOOK_EMAIL_SECRET         le secret du crochet donné par Supabase (v1,whsec_…)
//   SES_BREVO_API_KEY             clé d'API Brevo (la même que le travailleur des notifications)
//   SES_EMAIL_EXPEDITEUR          adresse d'expédition vérifiée chez Brevo
//   SES_SITE_URL                  https://wilnergraph92.github.io/speed-express-site (les liens de retour n'iront que là)
// Ce que Supabase attend : 200 et {} si l'e-mail est parti ; sinon une erreur { error: { http_code, message } } — l'inscription en est alors
// informée (le client peut redemander l'e-mail).
// =============================================================================
import { verifierStandardWebhook, courrielCompte } from './serveur.mjs';
import textes from './courriels-compte.json' with { type: 'json' };

const ENV = (k) => (globalThis.Deno ? globalThis.Deno.env.get(k) : process.env[k]);
const erreur = (code, message) => new Response(JSON.stringify({ error: { http_code: code, message } }), { status: code, headers: { 'content-type': 'application/json' } });

async function envoyerBrevo(m) {
  const r = await fetch('https://api.brevo.com/v3/smtp/email', {
    method: 'POST', headers: { 'api-key': ENV('SES_BREVO_API_KEY'), 'content-type': 'application/json', accept: 'application/json' },
    body: JSON.stringify({ sender: { email: ENV('SES_EMAIL_EXPEDITEUR'), name: 'Speed Express Shipping' }, to: [{ email: m.a }], subject: m.sujet, textContent: m.texte, htmlContent: m.html,
                           headers: { 'X-SES-Courriel-Compte': m.action } })
  });
  return r.status === 201 || r.status === 200;
}

export async function gerer(requete, envoyer = envoyerBrevo) {
  if (requete.method !== 'POST') return erreur(405, 'méthode');
  const corpsBrut = await requete.text();
  if (corpsBrut.length > 65536) return erreur(413, 'trop grand');
  const ok = await verifierStandardWebhook({ id: requete.headers.get('webhook-id'), horodatage: requete.headers.get('webhook-timestamp'),
                                             signatures: requete.headers.get('webhook-signature'), corpsBrut, secret: ENV('SES_HOOK_EMAIL_SECRET') });
  if (!ok) return erreur(401, 'signature');
  let m;
  try { m = courrielCompte(JSON.parse(corpsBrut), textes, { supabaseUrl: ENV('SUPABASE_URL'), siteUrl: ENV('SES_SITE_URL') }); } catch (e) { return erreur(400, String(e.message).slice(0, 100)); }
  const parti = await envoyer(m);
  // Le journal : l'action et la langue. Jamais l'adresse, le lien, le jeton, ni un secret.
  console.log(JSON.stringify({ quand: new Date().toISOString(), action: m.action, langue: m.langue, envoye: parti }));
  return parti ? new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }) : erreur(502, 'envoi refusé par le fournisseur');
}

if (globalThis.Deno && globalThis.Deno.serve) globalThis.Deno.serve((r) => gerer(r));
