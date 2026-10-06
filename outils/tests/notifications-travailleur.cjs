// Le travailleur des notifications (scripts/notifications/envoyer.mjs), sans réseau : un faux « fetch » joue la base et les fournisseurs.
//
// Ce qu'on éprouve : la configuration incomplète s'arrête avant tout appel ; seuls trois hôtes sont jamais contactés (la base du projet,
// Brevo, Expo) ; chaque réponse de fournisseur devient le bon compte rendu (envoyée / plus tard / échec définitif) ; un jeton refusé est
// désactivé ; une coupure réseau ne fait pas tomber le passage ; le journal ne contient ni clé, ni adresse complète.
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const T = await import(path.resolve('scripts/notifications/envoyer.mjs'));
  let n = 0; const ok = () => { n++; };
  const CLE = 'eyJ.service-role-secret-0123456789', BREVO = 'xkeysib-brevo-secret-0123456789', EXPO = 'expo-secret-0123456789';
  const ENV = { SES_SUPABASE_URL: 'https://abcdefgh.supabase.co', SES_SUPABASE_SERVICE_KEY: CLE, SES_BREVO_API_KEY: BREVO, SES_EMAIL_EXPEDITEUR: 'notifications@exemple.test', SES_EXPO_TOKEN: EXPO };

  // 1. configuration
  assert.throws(() => T.lireConfiguration({}), /SES_SUPABASE_URL, SES_SUPABASE_SERVICE_KEY/); ok();
  assert.throws(() => T.lireConfiguration(Object.assign({}, ENV, { SES_SUPABASE_URL: 'https://pirate.example.com' })), /supabase\.co/); ok();
  assert.throws(() => T.lireConfiguration(Object.assign({}, ENV, { SES_EMAIL_EXPEDITEUR: '' })), /EXPEDITEUR/); ok();
  assert.deepEqual(T.lireConfiguration(Object.assign({}, ENV, { SES_BREVO_API_KEY: '' })).canaux, ['push'], 'sans clé Brevo : on ne réclame pas les e-mails (ils attendent)'); ok();
  const cfg = T.lireConfiguration(ENV);
  assert.deepEqual(cfg.canaux, ['push', 'email']); assert.equal(cfg.lot, 50); ok();
  assert.equal(T.masquerEmail('client9@essai.test'), 'c***@essai.test'); assert.equal(T.masquerEmail('pas-un-email'), '[masqué]'); ok();

  // 2. un passage complet, contre une fausse base et de faux fournisseurs
  const LOT = [
    { notification_id: 1, channel: 'email', attempt: 1, language: 'fr', title: 'Colis reçu', body: 'Votre colis N-001 <b>est</b> arrivé.', template: 'ParcelReceived', recipient: { email: 'client9@essai.test', name: 'Marie' } },
    { notification_id: 2, channel: 'email', attempt: 1, language: 'en', title: 'Invoice', body: 'x', template: 'InvoiceIssued', recipient: { email: 'invalide@essai.test', name: 'X' } },
    { notification_id: 3, channel: 'email', attempt: 2, language: 'es', title: 'T', body: 'x', template: 'Delivered', recipient: { email: 'lent@essai.test', name: 'Y' } },
    { notification_id: 4, channel: 'push', attempt: 1, language: 'ht', title: 'Kolis livre', body: 'x', template: 'Delivered', recipient: { tokens: ['ExponentPushToken[bon]', 'ExponentPushToken[perime]'] } },
    { notification_id: 5, channel: 'push', attempt: 1, language: 'fr', title: 'T', body: 'x', template: 'Delivered', recipient: { tokens: ['ExponentPushToken[perime2]'] } },
    { notification_id: 6, channel: 'email', attempt: 1, language: 'fr', title: 'T', body: 'x', template: 'Delivered', recipient: { email: 'coupure@essai.test', name: 'Z' } },
    { notification_id: 7, channel: 'sms', attempt: 1, language: 'fr', title: 'T', body: 'x', template: 'OutForDelivery', recipient: { phone: '+509 3000 0000' } }
  ];
  const appels = [], comptes = {}, desactives = [], battements = [];
  async function faux(url, o) {
    const u = new URL(url); appels.push({ hote: u.host, chemin: u.pathname, entetes: o.headers, corps: o.body ? JSON.parse(o.body) : null });
    const rep = (status, corps) => ({ ok: status >= 200 && status < 300, status, text: async () => (typeof corps === 'string' ? corps : JSON.stringify(corps)) });
    if (u.host === 'abcdefgh.supabase.co') {
      assert.equal(o.headers.apikey, CLE); assert.equal(o.headers.Authorization, 'Bearer ' + CLE);
      const nom = u.pathname.split('/').pop(), a = JSON.parse(o.body);
      if (nom === 'ses_nt_dispatch') return rep(200, { dispatched: 3 });
      if (nom === 'ses_nt_claim') { assert.deepEqual(a.p_channels, ['push', 'email']); assert.equal(a.p_limit, 50); return rep(200, LOT); }
      if (nom === 'ses_nt_disable_tokens') { desactives.push.apply(desactives, a.p_tokens); return rep(200, a.p_tokens.length); }
      if (nom === 'ses_nt_report') { comptes[a.p_id] = a; return rep(200, { notification_id: a.p_id, status: a.p_ok ? 'SENT' : (a.p_permanent ? 'FAILED' : 'PENDING') }); }
      if (nom === 'ses_nt_purge_signals') return rep(200, 4);
      if (nom === 'ses_ops_heartbeat') { battements.push(a); return faux.sansExploitation ? rep(404, { code: 'PGRST202', message: 'Could not find the function public.ses_ops_heartbeat' }) : rep(200, { id: 1 }); }
      throw new Error('fonction inattendue ' + nom);
    }
    if (u.host === 'api.brevo.com') {
      assert.equal(o.headers['api-key'], BREVO);
      const c = JSON.parse(o.body), dest = c.to[0].email;
      if (dest === 'coupure@essai.test') throw new Error('ECONNRESET');
      if (dest === 'invalide@essai.test') return rep(400, { code: 'invalid_parameter', message: 'email is not valid' });
      if (dest === 'lent@essai.test') return rep(503, 'Service Unavailable');
      return rep(201, { messageId: '<msg-1@brevo>' });
    }
    if (u.host === 'exp.host') {
      assert.equal(o.headers.Authorization, 'Bearer ' + EXPO);
      const msgs = JSON.parse(o.body);
      return rep(200, { data: msgs.map((m) => (/perime/.test(m.to) ? { status: 'error', message: 'not registered', details: { error: 'DeviceNotRegistered' } } : { status: 'ok', id: 'ticket-' + m.to.length })) });
    }
    throw new Error('hôte interdit : ' + u.host);
  }
  const lignes = [];
  const journal = T.journaliste([CLE, BREVO, EXPO], (l) => lignes.push(l));
  const bilan = await T.executer({ cfg, fetch: faux, journal });
  assert.deepEqual(new Set(appels.map((a) => a.hote)), new Set(['abcdefgh.supabase.co', 'api.brevo.com', 'exp.host']), 'trois hôtes, jamais un autre'); ok();
  assert.deepEqual(comptes[1], { p_id: 1, p_ok: true, p_provider_ref: '<msg-1@brevo>', p_error: null, p_worker: 'github-actions', p_permanent: false }, 'e-mail accepté : envoyé, avec la référence Brevo'); ok();
  assert.equal(comptes[2].p_ok, false); assert.equal(comptes[2].p_permanent, true); assert.match(comptes[2].p_error, /brevo 400/); ok();
  assert.equal(comptes[3].p_permanent, false, '503 : la base réessaiera plus tard'); ok();
  assert.equal(comptes[4].p_ok, true); assert.match(comptes[4].p_provider_ref, /^ticket-/); ok();
  assert.equal(comptes[5].p_ok, false); assert.equal(comptes[5].p_permanent, true, 'le seul jeton est refusé : échec définitif'); ok();
  assert.deepEqual(desactives.sort(), ['ExponentPushToken[perime2]', 'ExponentPushToken[perime]'], 'les jetons refusés sont désactivés, les bons gardés'); ok();
  assert.equal(comptes[6].p_permanent, false); assert.match(comptes[6].p_error, /réseau : ECONNRESET/, 'une coupure réseau : plus tard, et le passage continue'); ok();
  assert.equal(comptes[7].p_ok, false); assert.match(comptes[7].p_error, /aucun fournisseur/); ok();
  assert.deepEqual(bilan, { reclamees: 7, envoyees: 2, relances: 3, echecs: 2, jetons_desactives: 2, signaux_purges: 4 }); ok();
  assert.equal(battements.length, 1); assert.equal(battements[0].p_source, 'notifications_worker'); assert.equal(battements[0].p_status, 'WARN', 'des échecs : battement « alerte »');
  assert.deepEqual(battements[0].p_detail, bilan, 'le bilan du passage accompagne le battement'); ok();
  // sans l'étape 013 : le passage se termine quand même, avec son bilan
  faux.sansExploitation = true; const l3 = [];
  const bilan2 = await T.executer({ cfg, fetch: faux, journal: T.journaliste([CLE], (l) => l3.push(l)) });
  assert.equal(bilan2.reclamees, 7, 'sans la 013, le passage garde son résultat'); assert.ok(l3.some((l) => /battement de cœur non déposé/.test(l)), 'et le note au journal'); ok();
  faux.sansExploitation = false;
  // le contenu de l'e-mail
  const mail = appels.find((a) => a.hote === 'api.brevo.com' && a.corps.to[0].email === 'client9@essai.test').corps;
  assert.equal(mail.subject, 'Colis reçu'); assert.equal(mail.sender.email, 'notifications@exemple.test');
  assert.ok(mail.htmlContent.includes('&lt;b&gt;est&lt;/b&gt;') && !mail.htmlContent.includes('<b>est'), 'le texte est échappé dans la version HTML'); ok();
  assert.ok(mail.textContent.includes('espace client'), 'un pied qui renvoie vers l\'espace client, dans la langue du client'); ok();
  assert.ok(appels.find((a) => a.corps && a.corps.to && a.corps.to[0].email === 'lent@essai.test').corps.textContent.includes('espacio de cliente'), 'en espagnol pour un client hispanophone'); ok();
  // le journal
  const tout = lignes.join('\n');
  [CLE, BREVO, EXPO, 'client9@essai.test', 'invalide@essai.test', '+509 3000 0000'].forEach((s) => assert.ok(!tout.includes(s), 'le journal ne contient jamais « ' + s.slice(0, 12) + '… »'));
  lignes.forEach((l) => JSON.parse(l)); ok();
  assert.ok(tout.includes('c***@essai.test'), 'les adresses y sont masquées'); ok();
  // un fournisseur qui renverrait la clé dans son message d'erreur : masquée quand même
  const l2 = [];
  T.journaliste([BREVO], (x) => l2.push(x))({ erreur: 'refusé pour ' + BREVO });
  assert.ok(!l2[0].includes(BREVO) && l2[0].includes('[masqué]')); ok();

  // 3. la base indisponible : le passage s'arrête net, sans rien envoyer
  const vus = [];
  await assert.rejects(T.executer({ cfg, fetch: async (url) => { vus.push(new URL(url).host); return { ok: false, status: 503, text: async () => 'indisponible' }; }, journal: () => {} }), /base ses_nt_dispatch : 503/);
  assert.deepEqual(vus, ['abcdefgh.supabase.co'], 'aucun fournisseur contacté si la base ne répond pas'); ok();
  console.log('PASS travailleur des notifications : ' + n + ' vérifications — configuration, trois hôtes seulement, chaque réponse de fournisseur devient le bon compte rendu, jetons refusés désactivés, coupure réseau, journal sans secret.');
})().catch((e) => { console.error('ÉCHEC travailleur des notifications : ' + (e && e.message)); process.exit(1); });
