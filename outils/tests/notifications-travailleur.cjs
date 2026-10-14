// Le travailleur des notifications (scripts/notifications/envoyer.mjs), sans réseau : un faux « fetch » joue la base et les fournisseurs.
//
// Ce qu'on éprouve : la configuration incomplète s'arrête avant tout appel ; seuls quatre hôtes sont jamais contactés (la base du projet,
// Brevo, Expo, Meta pour WhatsApp) ; chaque réponse de fournisseur devient le bon compte rendu (envoyée / plus tard / échec définitif) ; un jeton refusé est
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
  const appels = [], comptes = {}, desactives = [], battements = [], pushData = [];
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
      if (nom === 'ses_nt_push_data') {
        assert.deepEqual(a.p_ids, [4, 5], 'les données de TOUS les push du lot, en un seul appel'); pushData.push(a);
        if (faux.sansDonnees) return rep(404, { code: 'PGRST202', message: 'Could not find the function public.ses_nt_push_data' });
        return rep(200, { 4: { template: 'Delivered', tracking_number: 'SES-4821937065', url: 'speedexpress://colis/SES-4821937065' },
                          5: { template: 'Delivered', url: 'javascript:alert(1)', secret: 'jamais' } });
      }
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
  // ce qu'emporte chaque push (étape 020) : le numéro et le lien du colis, rien d'autre ; un lien inconnu ne part pas
  const envois = appels.filter((a) => a.hote === 'exp.host').flatMap((a) => a.corps);
  assert.equal(pushData.length, 1, 'un seul appel pour tout le lot'); ok();
  assert.deepEqual(envois.find((m) => m.to === 'ExponentPushToken[bon]').data, { notification_id: 4, template: 'Delivered', tracking_number: 'SES-4821937065', url: 'speedexpress://colis/SES-4821937065' },
    'le toucher ouvrira le colis SES-4821937065'); ok();
  assert.deepEqual(envois.find((m) => m.to === 'ExponentPushToken[perime2]').data, { notification_id: 5, template: 'Delivered' }, 'un lien qui n\'est pas celui de l\'application ne part pas, ni une clé inconnue'); ok();
  assert.ok(envois.every((m) => m.channelId === 'colis'), 'le canal Android « colis » de l\'application'); ok();
  assert.deepEqual(T.dataPush({ notification_id: 9 }, null), { notification_id: 9 }); ok();
  // sans l'étape 020 : les push partent quand même, avec leur seul identifiant
  faux.sansDonnees = true; appels.length = 0; const l4 = [];
  const bilan3 = await T.executer({ cfg, fetch: faux, journal: T.journaliste([CLE], (l) => l4.push(l)) });
  assert.equal(bilan3.reclamees, 7); assert.ok(l4.some((l) => /données des push indisponibles/.test(l)), 'sans la 020 : noté au journal');
  assert.deepEqual(appels.filter((a) => a.hote === 'exp.host').flatMap((a) => a.corps).map((m) => m.data), [{ notification_id: 4 }, { notification_id: 4 }, { notification_id: 5 }],
    'et chaque push part avec son seul identifiant'); ok();
  faux.sansDonnees = false;
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
  // 4. WhatsApp (phase 11) : un modèle approuvé, des paramètres nommés, le numéro au format international, la clé jamais au journal
  const WA = 'EAAG-meta-secret-0123456789abcdef';
  assert.throws(() => T.lireConfiguration(Object.assign({}, ENV, { SES_WHATSAPP_TOKEN: WA })), /SES_WHATSAPP_PHONE_ID/, 'un jeton sans numéro : arrêt avant tout appel'); ok();
  assert.throws(() => T.lireConfiguration(Object.assign({}, ENV, { SES_WHATSAPP_TOKEN: WA, SES_WHATSAPP_PHONE_ID: '1234567890', SES_WHATSAPP_VERSION: '../x' })), /v23\.0/); ok();
  const cfgw = T.lireConfiguration(Object.assign({}, ENV, { SES_WHATSAPP_TOKEN: WA, SES_WHATSAPP_PHONE_ID: '1234567890' }));
  assert.deepEqual(cfgw.canaux, ['push', 'email', 'whatsapp']); assert.equal(cfgw.version, 'v23.0'); ok();
  assert.equal(T.nomModeleWhatsapp('ParcelAtDestinationHub'), 'ses_parcel_at_destination_hub'); assert.equal(T.nomModeleWhatsapp('DocumentRequired'), 'ses_document_required'); ok();
  for (const [tel, pays, attendu] of [['3700 1234', 'HT', '50937001234'], ['+509 3700-1234', null, '50937001234'], ['00509 37001234', null, '50937001234'], ['(809) 555-1234', 'DO', '18095551234'],
    ['305 555 0100', 'US', '13055550100'], ['37001234', null, null], ['12', 'HT', null], ['', 'HT', null], ['+1 (305) 555-0100', 'HT', '13055550100']]) {
    assert.equal(T.numeroInternational(tel, pays), attendu, tel + ' (' + pays + ')'); ok();
  }
  const modeles = JSON.parse(require('node:fs').readFileSync('scripts/notifications/whatsapp-modeles.json', 'utf8'));
  const LOTW = [
    { notification_id: 21, channel: 'whatsapp', attempt: 1, language: 'ht', title: 'T', body: 'x', template: 'ParcelAtDestinationHub', recipient: { phone: '3700 1234' } },
    { notification_id: 22, channel: 'whatsapp', attempt: 1, language: 'fr', title: 'T', body: 'x', template: 'Delivered', recipient: { phone: '37001234' } },
    { notification_id: 23, channel: 'whatsapp', attempt: 1, language: 'es', title: 'T', body: 'x', template: 'Delivered', recipient: { phone: '+1 809 555 1234' } },
    { notification_id: 24, channel: 'whatsapp', attempt: 1, language: 'en', title: 'T', body: 'x', template: 'PaymentReceived', recipient: { phone: '+1 305 555 0100' } },
    { notification_id: 25, channel: 'whatsapp', attempt: 1, language: 'fr', title: 'T', body: 'x', template: 'InvoiceIssued', recipient: { phone: '+509 3700 9999' } }
  ];
  const DONNEES = { 21: { template: 'ParcelAtDestinationHub', language: 'ht', country: 'HT', variables: { tracking_number: 'SES-4821937065', stage: 'Au hub' } },
                    22: { template: 'Delivered', language: 'fr', country: null, variables: { tracking_number: 'SES-1' } },
                    23: { template: 'Delivered', language: 'es', country: 'DO', variables: { tracking_number: 'SES-2' } },
                    24: { template: 'PaymentReceived', language: 'en', country: 'US', variables: { amount: '45.50', currency: 'USD', invoice_number: 'FAC-1' } },
                    25: { template: 'InvoiceIssued', language: 'fr', country: 'HT', variables: { invoice_number: 'FAC-2', amount: '10.00', currency: 'USD', date: '2026-10-20' } } };
  const appelsW = [], comptesW = {}, lignesW = [];
  async function fauxW(url, o) {
    const u = new URL(url); appelsW.push({ hote: u.host, chemin: u.pathname, entetes: o.headers, corps: o.body ? JSON.parse(o.body) : null });
    const rep = (status, corps) => ({ ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(corps) });
    if (u.host === 'abcdefgh.supabase.co') {
      const nom = u.pathname.split('/').pop(), a = JSON.parse(o.body);
      if (nom === 'ses_nt_dispatch') return rep(200, { dispatched: 0 });
      if (nom === 'ses_nt_claim') { assert.deepEqual(a.p_channels, ['push', 'email', 'whatsapp']); return rep(200, LOTW); }
      if (nom === 'ses_nt_template_data') { assert.deepEqual(a.p_ids, [21, 22, 23, 24, 25], 'les données de tous les WhatsApp du lot, en un appel'); return rep(200, DONNEES); }
      if (nom === 'ses_nt_report') { comptesW[a.p_id] = a; return rep(200, { notification_id: a.p_id, status: a.p_ok ? 'SENT' : (a.p_permanent ? 'FAILED' : 'PENDING') }); }
      if (nom === 'ses_nt_purge_signals') return rep(200, 0);
      if (nom === 'ses_nt_alert') return rep(200, { alert: true, channels: [{ channel: 'whatsapp', failed_24h: 12 }] });
      if (nom === 'ses_ops_heartbeat') return rep(200, { id: 1 });
      throw new Error('fonction inattendue ' + nom);
    }
    if (u.host === 'graph.facebook.com') {
      assert.equal(u.pathname, '/v23.0/1234567890/messages'); assert.equal(o.headers.Authorization, 'Bearer ' + WA);
      const c = JSON.parse(o.body);
      if (c.to === '18095551234') return rep(400, { error: { code: 132001, message: 'Template name does not exist in the translation' } });
      if (c.to === '13055550100') return rep(429, { error: { code: 130429, message: 'Rate limit hit' } });
      return rep(200, { messaging_product: 'whatsapp', contacts: [{ wa_id: c.to }], messages: [{ id: 'wamid.HBg' + c.to }] });
    }
    throw new Error('hôte interdit : ' + u.host);
  }
  const bilanW = await T.executer({ cfg: cfgw, fetch: fauxW, journal: T.journaliste([CLE, BREVO, EXPO, WA], (l) => lignesW.push(l)) });
  assert.deepEqual(new Set(appelsW.map((a) => a.hote)), new Set(['abcdefgh.supabase.co', 'graph.facebook.com']), 'WhatsApp : la base et Meta, rien d\'autre'); ok();
  const envoi21 = appelsW.find((a) => a.hote === 'graph.facebook.com' && a.corps.to === '50937001234').corps;
  assert.deepEqual(envoi21, { messaging_product: 'whatsapp', to: '50937001234', type: 'template', template: { name: 'ses_parcel_at_destination_hub', language: { code: 'fr' },
    components: [{ type: 'body', parameters: [{ type: 'text', parameter_name: 'tracking_number', text: 'SES-4821937065' }] }] } },
    'un client créolophone d\'Haïti : le modèle français approuvé, l\'indicatif 509, les paramètres NOMMÉS — seulement ceux du modèle (pas « stage »)'); ok();
  assert.ok(modeles.modeles.some((m) => m.name === envoi21.template.name && m.language === 'fr'), 'le modèle envoyé est dans le fichier soumis à Meta'); ok();
  for (const e of appelsW.filter((a) => a.hote === 'graph.facebook.com')) {
    const m = modeles.modeles.find((x) => x.name === e.corps.template.name && x.language === e.corps.template.language.code);
    assert.ok(m, 'modèle soumis : ' + e.corps.template.name + '/' + e.corps.template.language.code);
    const attendus = (m.components.find((c) => c.type === 'BODY').text.match(/\{\{([a-z_]+)\}\}/g) || []).map((x) => x.slice(2, -2)).sort();
    assert.deepEqual(e.corps.template.components.length ? e.corps.template.components[0].parameters.map((p) => p.parameter_name).sort() : [], [...new Set(attendus)],
      'les paramètres envoyés sont EXACTEMENT ceux du modèle approuvé : ' + m.name); ok();
  }
  assert.equal(comptesW[21].p_ok, true); assert.equal(comptesW[21].p_provider_ref, 'wamid.HBg50937001234', 'envoyé, avec la référence de Meta (pour ses accusés)'); ok();
  assert.equal(comptesW[22].p_ok, false); assert.equal(comptesW[22].p_permanent, true); assert.match(comptesW[22].p_error, /sans indicatif/, 'un numéro sans pays connu : rien n\'est deviné'); ok();
  assert.equal(comptesW[23].p_permanent, true); assert.match(comptesW[23].p_error, /132001/, 'un modèle pas encore approuvé : échec définitif'); ok();
  assert.equal(comptesW[24].p_permanent, false, 'débit dépassé (130429) : plus tard'); ok();
  assert.equal(comptesW[25].p_ok, true, 'une facture : les quatre paramètres du modèle'); ok();
  DONNEES[25].variables = { invoice_number: 'FAC-2' }; appelsW.length = 0;
  await T.executer({ cfg: cfgw, fetch: fauxW, journal: () => {} });
  assert.equal(comptesW[25].p_permanent, true); assert.match(comptesW[25].p_error, /variable absente pour ses_invoice_issued : amount, currency, date/, 'une variable du modèle manque : rien ne part (Meta refuserait)'); ok();
  assert.ok(!appelsW.some((a) => a.hote === 'graph.facebook.com' && a.corps.to === '50937009999'), 'et Meta n\'est même pas appelé'); ok();
  assert.equal(bilanW.alerte, true); assert.ok(lignesW.some((l) => /ALERTE_NOTIFICATIONS/.test(l)), 'au-delà du seuil : l\'alerte est au journal (le workflow ouvre un ticket)'); ok();
  const toutW = lignesW.join('\n');
  [WA, '37001234', '8095551234', '3055550100'].forEach((x) => assert.ok(!toutW.includes(x), 'le journal ne contient jamais « ' + x.slice(0, 8) + '… »'));
  assert.ok(toutW.includes('***234'), 'les numéros y sont masqués'); ok();

  console.log('PASS travailleur des notifications : ' + n + ' vérifications — configuration, quatre hôtes seulement (la base, Brevo, Expo, Meta), chaque réponse de fournisseur devient le bon compte rendu, jetons refusés désactivés, coupure réseau, journal sans secret.');
})().catch((e) => { console.error('ÉCHEC travailleur des notifications : ' + (e && e.message)); process.exit(1); });
