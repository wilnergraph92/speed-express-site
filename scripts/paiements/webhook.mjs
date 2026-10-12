// =============================================================================
// Speed Express Shipping — la porte des webhooks de paiement (Edge Function Supabase, phase 6)
// -----------------------------------------------------------------------------
// MODÈLE, non déployé : à copier dans supabase/functions/paiement-webhook/ d'un projet (préproduction d'abord), avec prestataires.mjs.
// Adresse : https://<projet>.supabase.co/functions/v1/paiement-webhook/<PRESTATAIRE> (ex. …/CARD), donnée au prestataire.
//
// Environnement de la fonction (secrets de Supabase, JAMAIS dans le dépôt ni dans un navigateur) :
//   SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY   fournis par Supabase à toute Edge Function
//   SES_PAY_CARD, SES_PAY_AZUL, …             le secret de webhook de chaque prestataire (nom = payment_provider.credentials_env)
//
// La fonction ne décide rien : elle vérifie la signature (elle seule a le secret), normalise, et confie le tout à la base
// (public.ses_payment_event, ouverte au seul service_role), qui journalise, applique ou refuse, et reste idempotente.
// La vérification JWT de Supabase doit être DÉSACTIVÉE pour cette fonction (le prestataire n'a pas de compte) : la sécurité
// est la signature du prestataire, puis l'idempotence et les contrôles de la base.
// =============================================================================
import { traiterWebhook } from './prestataires.mjs';

const ENV = (k) => (globalThis.Deno ? globalThis.Deno.env.get(k) : process.env[k]);

async function appelerBase(args) {
  const r = await fetch(ENV('SUPABASE_URL') + '/rest/v1/rpc/ses_payment_event', {
    method: 'POST',
    headers: { apikey: ENV('SUPABASE_SERVICE_ROLE_KEY'), authorization: 'Bearer ' + ENV('SUPABASE_SERVICE_ROLE_KEY'), 'content-type': 'application/json' },
    body: JSON.stringify(args)
  });
  if (!r.ok) throw new Error('base : ' + r.status);
  return r.json();
}

export async function gerer(requete) {
  if (requete.method !== 'POST') return new Response('', { status: 405 });
  const prestataire = new URL(requete.url).pathname.split('/').filter(Boolean).pop();
  const corpsBrut = await requete.text();
  if (corpsBrut.length > 65536) return new Response(JSON.stringify({ erreur: 'trop grand' }), { status: 413 });
  const entetes = {};
  requete.headers.forEach((v, k) => { entetes[k] = v; });
  const r = await traiterWebhook({
    prestataire, corpsBrut, entetes, appelerBase,
    // le NOM de la variable vient de la convention SES_PAY_<CODE> (= payment_provider.credentials_env) ; la valeur ne quitte jamais ce processus
    lireSecret: (code) => ENV('SES_PAY_' + code) || null
  });
  // Le journal : le prestataire, le résultat. Jamais le corps, la signature, ni un secret.
  console.log(JSON.stringify({ quand: new Date().toISOString(), prestataire, statut: r.statut, resultat: r.corps.resultat || r.corps.erreur }));
  return new Response(JSON.stringify(r.corps), { status: r.statut, headers: { 'content-type': 'application/json' } });
}

if (globalThis.Deno && globalThis.Deno.serve) globalThis.Deno.serve(gerer);
