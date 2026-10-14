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
//   SES_WHATSAPP_TOKEN          jeton d'accès PERMANENT d'un utilisateur système Meta (WhatsApp Cloud API) — SECRET (sans lui : pas de WhatsApp)
//   SES_WHATSAPP_PHONE_ID       identifiant du numéro WhatsApp Business chez Meta (pas un secret, mais propre au compte)
//   SES_WHATSAPP_VERSION        version de l'API Graph (par défaut v23.0)
//
// Un passage : (1) répartir les événements en attente (la base crée les notifications) ; (2) réclamer un lot, avec un bail ; (3) envoyer
// chacune par son fournisseur ; (4) rendre compte à la base, qui décide : envoyée, nouvel essai plus tard, ou échec définitif ; (5) purger
// les signaux temps réel de plus de deux jours. Un jeton de téléphone refusé par Expo (« DeviceNotRegistered ») est désactivé.
//
// Le journal est en JSON, une ligne par fait, sans aucun secret ni adresse complète (les e-mails et les numéros sont masqués).
// =============================================================================

import { readFileSync } from 'node:fs';

const CANAUX_CONNUS = ['email', 'push', 'sms', 'whatsapp'];
const FOURNISSEURS = { brevo: 'https://api.brevo.com/v3/smtp/email', expo: 'https://exp.host/--/api/v2/push/send', meta: 'https://graph.facebook.com' };
/* WhatsApp n'accepte, hors d'une conversation ouverte par le client, que des modèles qu'il a approuvés : « ses_<modèle> », dans la langue la plus
   proche de celle du client (le créole haïtien n'est pas une langue de modèle WhatsApp : le modèle français). Mêmes noms et mêmes langues que
   scripts/notifications/whatsapp-modeles.json, écrit par outils/portail-textes.py. */
const LANGUE_WHATSAPP = { fr: 'fr', en: 'en', es: 'es', ht: 'fr' };
/* Les paramètres de chaque modèle APPROUVÉ (nom + langue → noms des variables), lus dans le fichier même qui est soumis à Meta : on n'envoie
   que ceux-là (un paramètre de plus ou de moins, et Meta refuse le message). */
let MODELES_WA = null;
export function parametresModele(nom, langue, fichier) {
  if (!MODELES_WA || fichier) {
    const j = JSON.parse(readFileSync(fichier || new URL('./whatsapp-modeles.json', import.meta.url), 'utf8'));
    MODELES_WA = {};
    for (const m of j.modeles) {
      const corps = m.components.find((c) => c.type === 'BODY');
      MODELES_WA[m.name + '|' + m.language] = [...new Set((corps.text.match(/\{\{([a-z_]+)\}\}/g) || []).map((x) => x.slice(2, -2)))].sort();
    }
  }
  return MODELES_WA[nom + '|' + langue] || null;
}
export function nomModeleWhatsapp(code) { return 'ses_' + String(code || '').replace(/(?<!^)(?=[A-Z])/g, '_').toLowerCase(); }

/* Un numéro au format international, chiffres seuls (ce que Meta attend) : l'indicatif du pays du client quand le numéro n'en porte pas.
   Haïti : 8 chiffres → 509 ; République dominicaine et États-Unis : 10 chiffres → 1. Sinon, on n'invente rien : null (non envoyé, et dit). */
export function numeroInternational(tel, pays) {
  const brut = String(tel || '').trim();
  if (!brut) return null;
  let d = brut.replace(/[^0-9]/g, '');
  if (brut.startsWith('+')) return d.length >= 8 && d.length <= 15 ? d : null;
  if (d.startsWith('00')) { d = d.slice(2); return d.length >= 8 && d.length <= 15 ? d : null; }
  if (pays === 'HT' && d.length === 8) return '509' + d;
  if (pays === 'HT' && d.length === 11 && d.startsWith('509')) return d;
  if ((pays === 'DO' || pays === 'US') && d.length === 10) return '1' + d;
  if ((pays === 'DO' || pays === 'US') && d.length === 11 && d.startsWith('1')) return d;
  return null;
}

/* Un numéro masqué : les trois derniers chiffres. */
export function masquerTelephone(t) {
  const d = String(t || '').replace(/[^0-9]/g, '');
  return d ? '***' + d.slice(-3) : '[masqué]';
}

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
  const whatsapp = String(env.SES_WHATSAPP_TOKEN || '').trim(), telId = String(env.SES_WHATSAPP_PHONE_ID || '').trim();
  if (whatsapp) {
    if (!/^[0-9]{6,30}$/.test(telId)) throw new Error('SES_WHATSAPP_PHONE_ID (identifiant numérique du numéro chez Meta) est requis pour WhatsApp');
    canaux.push('whatsapp');
  }
  const version = String(env.SES_WHATSAPP_VERSION || 'v23.0').trim();
  if (!/^v[0-9]{1,2}\.[0-9]$/.test(version)) throw new Error('SES_WHATSAPP_VERSION doit ressembler à v23.0');
  return {
    url, cle: String(env.SES_SUPABASE_SERVICE_KEY).trim(), brevo: String(env.SES_BREVO_API_KEY || '').trim(), expediteur: String(env.SES_EMAIL_EXPEDITEUR || '').trim(),
    expo: String(env.SES_EXPO_TOKEN || '').trim(), whatsapp, telId, version, canaux,
    travailleur: String(env.SES_TRAVAILLEUR || 'github-actions').slice(0, 60), lot: Math.min(Math.max(Number(env.SES_LOT || 50) || 50, 1), 200)
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

/* Ce qu'un push emporte, pour qu'un toucher ouvre le bon écran de l'application : le numéro de suivi et le lien speedexpress://colis/…
   (étape 020, ses_nt_push_data). Lu une seule fois par lot. Sans la 020 (fonction absente) ou si la base ne répond pas, le push part
   quand même, avec son seul identifiant : l'application ouvre alors la liste de ses notifications. */
async function donneesPush(cfg, fetch, lot, journal) {
  const ids = lot.filter((n) => n.channel === 'push').map((n) => n.notification_id);
  if (!ids.length) return {};
  try {
    return (await rpc(cfg, fetch, 'ses_nt_push_data', { p_ids: ids })) || {};
  } catch (e) {
    journal({ niveau: 'avertissement', message: 'données des push indisponibles (étape 020 pas encore passée ?)', erreur: String((e && e.message) || e).slice(0, 150) });
    return {};
  }
}

/* Seules les clés connues partent vers le téléphone : rien d'autre ne quitte la base par ce canal. */
export function dataPush(n, donnees) {
  const d = (donnees && donnees[String(n.notification_id)]) || {};
  const data = { notification_id: n.notification_id };
  for (const k of ['template', 'tracking_number', 'invoice_number']) if (typeof d[k] === 'string' && d[k]) data[k] = d[k];
  if (typeof d.url === 'string' && /^speedexpress:\/\/(colis\/[A-Za-z0-9-]{4,40}|factures|notifications)$/.test(d.url)) data.url = d.url;
  return data;
}

/* Envoyer une notification sur les téléphones par Expo. Un jeton refusé « DeviceNotRegistered » est à désactiver. */
async function envoyerPush(cfg, fetch, n, donnees) {
  const jetons = (n.recipient.tokens || []).filter((t) => /^Expo(nent)?PushToken\[[^\]]+\]$/.test(t));
  if (!jetons.length) return { ok: false, erreur: 'aucun jeton valide', definitif: true, aDesactiver: [] };
  const entetes = { 'Content-Type': 'application/json', Accept: 'application/json' };
  if (cfg.expo) entetes.Authorization = 'Bearer ' + cfg.expo;
  const r = await fetch(FOURNISSEURS.expo, { method: 'POST', headers: entetes, body: JSON.stringify(jetons.map((to) => ({ to, title: n.title, body: n.body, sound: 'default', channelId: 'colis', data: dataPush(n, donnees) }))) });
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

/* Ce que WhatsApp doit savoir de chaque notification (étape 027, ses_nt_template_data) : le modèle, la langue, les variables PERMISES, le pays. */
async function donneesModeles(cfg, fetch, lot, journal) {
  const ids = lot.filter((n) => n.channel === 'whatsapp').map((n) => n.notification_id);
  if (!ids.length) return {};
  try {
    return (await rpc(cfg, fetch, 'ses_nt_template_data', { p_ids: ids })) || {};
  } catch (e) {
    journal({ niveau: 'avertissement', message: 'données des modèles WhatsApp indisponibles (étape 027 pas encore passée ?)', erreur: String((e && e.message) || e).slice(0, 150) });
    return {};
  }
}

/* Envoyer un message WhatsApp (modèle approuvé, paramètres NOMMÉS) par l'API Cloud de Meta. */
export async function envoyerWhatsapp(cfg, fetch, n, donnees) {
  const d = (donnees && donnees[String(n.notification_id)]) || null;
  if (!d) return { ok: false, erreur: 'whatsapp : données du modèle absentes', definitif: false };
  const vers = numeroInternational(n.recipient && n.recipient.phone, d.country);
  if (!vers) return { ok: false, erreur: 'whatsapp : numéro sans indicatif ou invalide', definitif: true };
  const nom = nomModeleWhatsapp(d.template), langue = LANGUE_WHATSAPP[d.language] || 'fr';
  const attendus = parametresModele(nom, langue);
  if (!attendus) return { ok: false, erreur: 'whatsapp : aucun modèle ' + nom + ' (' + langue + ') dans whatsapp-modeles.json', definitif: true };
  const manque = attendus.filter((k) => d.variables == null || d.variables[k] == null || String(d.variables[k]) === '');
  if (manque.length) return { ok: false, erreur: 'whatsapp : variable absente pour ' + nom + ' : ' + manque.join(', '), definitif: true };
  const parametres = attendus.map((k) => ({ type: 'text', parameter_name: k, text: String(d.variables[k]).slice(0, 200) }));
  const corps = { messaging_product: 'whatsapp', to: vers, type: 'template',
    template: { name: nom, language: { code: langue }, components: parametres.length ? [{ type: 'body', parameters: parametres }] : [] } };
  const r = await fetch(FOURNISSEURS.meta + '/' + cfg.version + '/' + cfg.telId + '/messages', {
    method: 'POST', headers: { Authorization: 'Bearer ' + cfg.whatsapp, 'Content-Type': 'application/json' }, body: JSON.stringify(corps)
  });
  const texte = await r.text();
  let j = null; try { j = JSON.parse(texte); } catch (e) { j = null; }
  if (r.ok && j && j.messages && j.messages[0] && j.messages[0].id) return { ok: true, ref: String(j.messages[0].id).slice(0, 200) };
  const code = j && j.error ? Number(j.error.code) : 0;
  // Réessayer ne changera rien : jeton refusé (190), droits (10, 200), modèle inexistant ou non approuvé (132000-132015), paramètres (100, 131008,
  // 131009), numéro non WhatsApp ou injoignable (131026), hors de la fenêtre de 24 h sans modèle (131047). Le reste (131000, 130429 débit, 5xx) : plus tard.
  const definitifs = [10, 100, 190, 200, 131008, 131009, 131026, 131047, 131051];
  const definitif = r.status === 401 || definitifs.includes(code) || (code >= 132000 && code <= 132015);
  return { ok: false, erreur: 'whatsapp ' + r.status + ' ' + (code || '') + ' ' + ((j && j.error && (j.error.message || '').slice(0, 160)) || texte.slice(0, 160)), definitif };
}

/* Un passage complet. `fetch` et `journal` sont fournis (le test les remplace) ; rien d'autre ne sort de cette fonction. */
export async function executer({ cfg, fetch, journal }) {
  const bilan = { reclamees: 0, envoyees: 0, relances: 0, echecs: 0, jetons_desactives: 0 };
  const repartis = await rpc(cfg, fetch, 'ses_nt_dispatch', { p_limit: 500 });
  journal({ niveau: 'info', message: 'événements répartis', detail: repartis });
  const lot = await rpc(cfg, fetch, 'ses_nt_claim', { p_worker: cfg.travailleur, p_channels: cfg.canaux, p_limit: cfg.lot, p_lease_seconds: 120 }) || [];
  bilan.reclamees = lot.length;
  const donnees = await donneesPush(cfg, fetch, lot, journal);
  const modeles = await donneesModeles(cfg, fetch, lot, journal);
  for (const n of lot) {
    let res;
    try {
      if (n.channel === 'email' && cfg.brevo) res = await envoyerEmail(cfg, fetch, n);
      else if (n.channel === 'push') res = await envoyerPush(cfg, fetch, n, donnees);
      else if (n.channel === 'whatsapp' && cfg.whatsapp) res = await envoyerWhatsapp(cfg, fetch, n, modeles);
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
      destinataire: n.channel === 'email' ? masquerEmail(n.recipient && n.recipient.email) : (n.channel === 'whatsapp' || n.channel === 'sms') ? masquerTelephone(n.recipient && n.recipient.phone) : undefined,
      suite: compte && compte.status, erreur: res.ok ? undefined : res.erreur });
  }
  bilan.signaux_purges = await rpc(cfg, fetch, 'ses_nt_purge_signals', {});
  // La surveillance (étape 027) : au-delà du seuil d'échecs ou d'attente, le workflow ouvre une alerte (ALERTE_NOTIFICATIONS dans le journal).
  try {
    const alerte = await rpc(cfg, fetch, 'ses_nt_alert', {});
    bilan.alerte = !!(alerte && alerte.alert);
    if (bilan.alerte) journal({ niveau: 'erreur', message: 'ALERTE_NOTIFICATIONS', canaux: alerte.channels });
  } catch (e) {
    journal({ niveau: 'avertissement', message: 'surveillance indisponible (étape 027 pas encore passée ?)', erreur: String((e && e.message) || e).slice(0, 150) });
  }
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
  const journal = journaliste([cfg.cle, cfg.brevo, cfg.expo, cfg.whatsapp], (l) => console.log(l));
  executer({ cfg, fetch: globalThis.fetch, journal }).then((b) => { process.exit(b.echecs > 0 && b.envoyees === 0 && b.reclamees > 0 ? 1 : 0); },
    (e) => { journal({ niveau: 'erreur', message: String((e && e.message) || e) }); process.exit(1); });
}
export { CANAUX_CONNUS, FOURNISSEURS };
