#!/usr/bin/env node
// =============================================================================
// Speed Express Shipping — le travailleur des notifications (phase 13)
// -----------------------------------------------------------------------------
// Il tourne CÔTÉ SERVEUR (GitHub Actions, voir modele-workflow-notifications.yml), jamais dans un navigateur : il parle à la base avec la
// clé SECRÈTE de Supabase, et aux fournisseurs avec leurs clés. Aucune de ces clés n'est écrite dans le dépôt : elles arrivent par
// l'environnement (secrets du dépôt GitHub).
//
//   SES_SUPABASE_URL            adresse du projet (https://….supabase.co)
//   SES_SUPABASE_SERVICE_KEY    clé secrète (service_role) — SECRET
//   SES_BREVO_API_KEY           clé d'API Brevo pour l'e-mail — SECRET (sans elle : pas d'e-mail réclamé)
//   SES_EMAIL_EXPEDITEUR        adresse d'expédition vérifiée chez Brevo (ex. notifications@…)
//   SES_EXPO_TOKEN              jeton d'accès Expo (facultatif : la sécurité renforcée des envois push)
//
// Un passage : (1) répartir les événements en attente (la base crée les notifications) ; (2) réclamer un lot, avec un bail ; (3) envoyer
// chacune par son fournisseur ; (4) rendre compte à la base, qui décide : envoyée, nouvel essai plus tard, ou échec définitif ; (5) purger
// les signaux temps réel de plus de deux jours. Un jeton de téléphone refusé par Expo (« DeviceNotRegistered ») est désactivé.
//
// Le journal est en JSON, une ligne par fait, sans aucun secret ni adresse complète (les e-mails sont masqués).
// =============================================================================

const CANAUX_CONNUS = ['email', 'push', 'sms', 'whatsapp'];
const FOURNISSEURS = { brevo: 'https://api.brevo.com/v3/smtp/email', expo: 'https://exp.host/--/api/v2/push/send' };

/* Une adresse masquée : assez pour reconnaître une ligne du journal, pas assez pour la réutiliser. */
export function masquerEmail(e) {
  const [nom, dom] = String(e || '').split('@');
  if (!dom) return '[masqué]';
  return (nom.slice(0, 1) || '?') + '***@' + dom;
}

function echapperHtml(t) {
  return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* La configuration vient de l'environnement ; une configuration incomplète s'arrête AVANT tout appel réseau. */
export function lireConfiguration(env) {
  const manque = ['SES_SUPABASE_URL', 'SES_SUPABASE_SERVICE_KEY'].filter((k) => !String(env[k] || '').trim());
  if (manque.length) throw new Error('Configuration incomplète : ' + manque.join(', '));
  const url = String(env.SES_SUPABASE_URL).trim().replace(/\/+$/, '');
  if (!/^https:\/\/[a-z0-9-]+\.supabase\.co$/.test(url)) throw new Error('SES_SUPABASE_URL doit être l\'adresse https://….supabase.co du projet');
  const canaux = ['push'];
  if (String(env.SES_BREVO_API_KEY || '').trim()) {
    if (!/@/.test(String(env.SES_EMAIL_EXPEDITEUR || ''))) throw new Error('SES_EMAIL_EXPEDITEUR est requis pour envoyer des e-mails');
    canaux.push('email');
  }
  return {
    url, cle: String(env.SES_SUPABASE_SERVICE_KEY).trim(), brevo: String(env.SES_BREVO_API_KEY || '').trim(), expediteur: String(env.SES_EMAIL_EXPEDITEUR || '').trim(),
    expo: String(env.SES_EXPO_TOKEN || '').trim(), canaux, travailleur: String(env.SES_TRAVAILLEUR || 'github-actions').slice(0, 60), lot: Math.min(Math.max(Number(env.SES_LOT || 50) || 50, 1), 200)
  };
}

/* Un appel à la base (PostgREST) avec la clé secrète. */
async function rpc(cfg, fetch, nom, args) {
  const r = await fetch(cfg.url + '/rest/v1/rpc/' + nom, {
    method: 'POST', headers: { apikey: cfg.cle, Authorization: 'Bearer ' + cfg.cle, 'Content-Type': 'application/json', Prefer: 'return=representation' }, body: JSON.stringify(args || {})
  });
  const texte = await r.text();
  if (!r.ok) throw new Error('base ' + nom + ' : ' + r.status + ' ' + texte.slice(0, 200));
  return texte ? JSON.parse(texte) : null;
}

/* Le pied de chaque e-mail : on ne répond pas à une notification, on écrit au support depuis son espace. */
const PIEDS = {
  fr: 'Speed Express Shipping — retrouvez le détail dans votre espace client. Ce message est automatique.',
  en: 'Speed Express Shipping — see the details in your customer area. This message is automatic.',
  es: 'Speed Express Shipping — consulte el detalle en su espacio de cliente. Este mensaje es automático.',
  ht: 'Speed Express Shipping — gade detay yo nan espas kliyan ou. Mesaj sa a otomatik.'
};

/* Envoyer un e-mail par Brevo. Rend { ok, ref?, erreur?, definitif? } : la base décide de la suite. */
async function envoyerEmail(cfg, fetch, n) {
  const pied = PIEDS[n.language] || PIEDS.fr;
  const r = await fetch(FOURNISSEURS.brevo, {
    method: 'POST', headers: { 'api-key': cfg.brevo, 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({
      sender: { email: cfg.expediteur, name: 'Speed Express Shipping' }, to: [{ email: n.recipient.email, name: n.recipient.name || undefined }],
      subject: n.title, textContent: n.body + '\n\n' + pied,
      htmlContent: '<p>' + echapperHtml(n.body) + '</p><p style="color:#626b78;font-size:13px">' + echapperHtml(pied) + '</p>',
      headers: { 'X-SES-Notification': String(n.notification_id) }
    })
  });
  const texte = await r.text();
  if (r.status === 201 || r.status === 200) {
    let ref = null; try { ref = JSON.parse(texte).messageId || null; } catch (e) { ref = null; }
    return { ok: true, ref };
  }
  // 400 (adresse invalide, contenu refusé), 401/403 (clé) : réessayer ne changera rien. 429 et 5xx : plus tard.
  return { ok: false, erreur: 'brevo ' + r.status + ' ' + texte.slice(0, 200), definitif: r.status >= 400 && r.status < 500 && r.status !== 429 };
}

/* Envoyer une notification sur les téléphones par Expo. Un jeton refusé « DeviceNotRegistered » est à désactiver. */
async function envoyerPush(cfg, fetch, n) {
  const jetons = (n.recipient.tokens || []).filter((t) => /^Expo(nent)?PushToken\[[^\]]+\]$/.test(t));
  if (!jetons.length) return { ok: false, erreur: 'aucun jeton valide', definitif: true, aDesactiver: [] };
  const entetes = { 'Content-Type': 'application/json', Accept: 'application/json' };
  if (cfg.expo) entetes.Authorization = 'Bearer ' + cfg.expo;
  const r = await fetch(FOURNISSEURS.expo, { method: 'POST', headers: entetes, body: JSON.stringify(jetons.map((to) => ({ to, title: n.title, body: n.body, sound: 'default', data: { notification_id: n.notification_id } }))) });
  const texte = await r.text();
  if (!r.ok) return { ok: false, erreur: 'expo ' + r.status + ' ' + texte.slice(0, 200), definitif: r.status >= 400 && r.status < 500 && r.status !== 429 };
  let tickets = [];
  try { tickets = JSON.parse(texte).data || []; } catch (e) { return { ok: false, erreur: 'expo : réponse illisible', definitif: false }; }
  const reussis = [], aDesactiver = [], erreurs = [];
  tickets.forEach((t, i) => {
    if (t && t.status === 'ok') reussis.push(t.id);
    else {
      if (t && t.details && t.details.error === 'DeviceNotRegistered') aDesactiver.push(jetons[i]);
      erreurs.push((t && t.details && t.details.error) || (t && t.message) || 'erreur');
    }
  });
  if (reussis.length) return { ok: true, ref: reussis.join(',').slice(0, 200), aDesactiver };
  return { ok: false, erreur: 'expo : ' + erreurs.join(', ').slice(0, 200), definitif: aDesactiver.length === jetons.length, aDesactiver };
}

/* Un passage complet. `fetch` et `journal` sont fournis (le test les remplace) ; rien d'autre ne sort de cette fonction. */
export async function executer({ cfg, fetch, journal }) {
  const bilan = { reclamees: 0, envoyees: 0, relances: 0, echecs: 0, jetons_desactives: 0 };
  const repartis = await rpc(cfg, fetch, 'ses_nt_dispatch', { p_limit: 500 });
  journal({ niveau: 'info', message: 'événements répartis', detail: repartis });
  const lot = await rpc(cfg, fetch, 'ses_nt_claim', { p_worker: cfg.travailleur, p_channels: cfg.canaux, p_limit: cfg.lot, p_lease_seconds: 120 }) || [];
  bilan.reclamees = lot.length;
  for (const n of lot) {
    let res;
    try {
      if (n.channel === 'email' && cfg.brevo) res = await envoyerEmail(cfg, fetch, n);
      else if (n.channel === 'push') res = await envoyerPush(cfg, fetch, n);
      else res = { ok: false, erreur: 'aucun fournisseur pour le canal ' + n.channel, definitif: false };
    } catch (e) {
      res = { ok: false, erreur: 'réseau : ' + String((e && e.message) || e).slice(0, 150), definitif: false };   // une coupure : on réessaiera
    }
    if (res.aDesactiver && res.aDesactiver.length) {
      bilan.jetons_desactives += await rpc(cfg, fetch, 'ses_nt_disable_tokens', { p_tokens: res.aDesactiver });
    }
    const compte = await rpc(cfg, fetch, 'ses_nt_report', { p_id: n.notification_id, p_ok: !!res.ok, p_provider_ref: res.ref || null, p_error: res.ok ? null : res.erreur, p_worker: cfg.travailleur, p_permanent: !!res.definitif });
    if (compte && compte.status === 'SENT') bilan.envoyees++; else if (compte && compte.status === 'FAILED') bilan.echecs++; else bilan.relances++;
    journal({ niveau: res.ok ? 'info' : 'avertissement', message: res.ok ? 'envoyée' : 'non envoyée', notification_id: n.notification_id, canal: n.channel, essai: n.attempt,
      destinataire: n.channel === 'email' ? masquerEmail(n.recipient && n.recipient.email) : undefined, suite: compte && compte.status, erreur: res.ok ? undefined : res.erreur });
  }
  bilan.signaux_purges = await rpc(cfg, fetch, 'ses_nt_purge_signals', {});
  journal({ niveau: 'info', message: 'bilan', bilan });
  // Le battement de cœur de ce passage (étape 013) : la page Santé du tableau de bord sait quand le travailleur a tourné pour la dernière
  // fois. Jamais bloquant : sans la 013 (fonction absente), on le note au journal et le passage garde son résultat.
  try {
    await rpc(cfg, fetch, 'ses_ops_heartbeat', { p_source: 'notifications_worker', p_status: bilan.echecs > 0 ? 'WARN' : 'OK', p_detail: bilan });
  } catch (e) {
    journal({ niveau: 'avertissement', message: 'battement de cœur non déposé', erreur: String((e && e.message) || e).slice(0, 150) });
  }
  return bilan;
}

/* Le journal : JSON, une ligne par fait. Tout texte y passe par le masque des secrets connus, au cas où un fournisseur les renverrait. */
export function journaliste(secrets, ecrire) {
  const masques = secrets.filter((s) => s && s.length >= 8);
  return (fait) => {
    let ligne = JSON.stringify(Object.assign({ at: new Date().toISOString() }, fait));
    masques.forEach((s) => { ligne = ligne.split(s).join('[masqué]'); });
    ecrire(ligne);
  };
}

// Lancé en ligne de commande (pas importé par le test)
if (import.meta.url === 'file://' + process.argv[1]) {
  let cfg;
  try { cfg = lireConfiguration(process.env); } catch (e) { console.error(JSON.stringify({ niveau: 'erreur', message: e.message })); process.exit(2); }
  const journal = journaliste([cfg.cle, cfg.brevo, cfg.expo], (l) => console.log(l));
  executer({ cfg, fetch: globalThis.fetch, journal }).then((b) => { process.exit(b.echecs > 0 && b.envoyees === 0 && b.reclamees > 0 ? 1 : 0); },
    (e) => { journal({ niveau: 'erreur', message: String((e && e.message) || e) }); process.exit(1); });
}
export { CANAUX_CONNUS, FOURNISSEURS };
