// Les quatre rôles côté couche de données : qui entre dans le tableau de bord,
// et la hiérarchie de definirRole() en mode démonstration. Aucune dépendance,
// aucun réseau : le mode démo vit dans la mémoire du test.
//
// La même grille que outils/tests/roles-sql.cjs, qui l'éprouve sur la vraie
// base : le mode démo ne doit permettre que ce que la base permet.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

const bac = { window: { addEventListener: () => {}, SES_CONFIG: {} },
  location: { protocol: 'http:', hostname: 'localhost', href: 'http://localhost/x.html', pathname: '/x.html' },
  document: { documentElement: { lang: 'fr' } },
  console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder };
vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), bac);
const api = bac.window.SES_API;
let n = 0; const ok = () => { n++; };

(async () => {
  assert.equal(api.mode, 'demo');
  assert.deepEqual(Array.from(api.ROLES), ['client', 'employe', 'gerant', 'admin']); ok();

  // --- 1. Qui entre dans le tableau de bord ---------------------------------
  const tous = Array.from(api.DROITS);
  const entre = (p) => api.accesTableauDeBord(p);
  assert.equal(entre(null), false); ok();
  assert.equal(entre({ role: 'client', droits: [] }), false); ok();
  // La colonne « droits » d'un client falsifiée n'ouvre rien.
  assert.equal(entre({ role: 'client', droits: tous }), false); ok();
  assert.deepEqual(Array.from(api.droitsDe({ role: 'client', droits: tous })), []); ok();
  // Un rôle inventé non plus : la règle est fermée par défaut.
  assert.equal(entre({ role: 'superman', droits: tous }), false); ok();
  // L'employé : seulement s'il peut lire quelque chose.
  assert.equal(entre({ role: 'employe', droits: [] }), false); ok();
  assert.equal(entre({ role: 'employe', droits: ['roles.gerer'] }), false); ok();
  assert.equal(entre({ role: 'employe', droits: ['colis.creer'] }), false); ok();
  assert.equal(entre({ role: 'employe', droits: ['colis.lire'] }), true); ok();
  assert.equal(entre({ role: 'employe', droits: ['factures.lire'] }), true); ok();
  // La direction : tous les droits, sans rien à cocher.
  for (const role of ['gerant', 'admin']) {
    assert.equal(entre({ role, droits: [] }), true); ok();
    assert.deepEqual(Array.from(api.droitsDe({ role, droits: [] })).sort(), tous.slice().sort()); ok();
  }
  assert.deepEqual(Array.from(api.ROLES_DIRECTION), ['gerant', 'admin']); ok();
  assert.deepEqual(Array.from(api.ROLES_EQUIPE), ['employe', 'gerant', 'admin']); ok();

  // --- 2. La hiérarchie de definirRole, en mode démo --------------------------
  const ADMIN = api.identifiantsAdmin, MDP = 'motdepasse1', ids = {};
  const entrer = (qui) => qui === 'admin' ? api.connecter(ADMIN.email, ADMIN.motDePasse) : api.connecter(qui + '@essai.test', MDP);
  const essai = async (qui, cible, role, droits) => {
    await entrer(qui);
    try { await api.admin.definirRole(ids[cible], role, droits || []); return 'ok'; } catch (e) { return e.code; }
  };
  const etat = async (cible) => {
    await entrer('admin');
    const r = await api.admin.clients({ parPage: 100 });
    const c = r.lignes.filter((x) => x.id === ids[cible])[0];
    return { role: c.role, droits: Array.from(c.droits) };
  };

  for (const nom of ['gerant', 'gerant2', 'chef', 'simple', 'client', 'autre', 'avecColis']) {
    const r = await api.inscrire({ email: nom + '@essai.test', motDePasse: MDP, nom_complet: nom });
    ids[nom] = r.profil.id;
    await api.deconnecter();
  }
  await entrer('admin'); ids.admin = (await api.profil()).id;
  assert.equal(await essai('admin', 'gerant', 'gerant'), 'ok'); ok();
  assert.equal(await essai('admin', 'gerant2', 'gerant'), 'ok'); ok();
  assert.equal(await essai('admin', 'chef', 'employe', ['colis.lire', 'roles.gerer']), 'ok'); ok();
  assert.equal(await essai('admin', 'simple', 'employe', ['colis.lire']), 'ok'); ok();

  // Un gérant, une fois nommé, entre dans le tableau de bord ; un client jamais.
  await entrer('gerant'); assert.equal(entre(await api.profil()), true); ok();
  await entrer('client'); assert.equal(entre(await api.profil()), false); ok();

  // Le client n'a aucun pouvoir.
  assert.equal(await essai('client', 'autre', 'employe'), 'non-autorise'); ok();
  // Un rôle qui n'existe pas.
  assert.equal(await essai('admin', 'client', 'superman'), 'role-inconnu'); ok();

  // Le gérant gère l'équipe …
  assert.equal(await essai('gerant', 'client', 'employe', ['colis.lire', 'factures.lire']), 'ok'); ok();
  assert.deepEqual(await etat('client'), { role: 'employe', droits: ['colis.lire', 'factures.lire'] }); ok();
  assert.equal(await essai('gerant', 'client', 'client'), 'ok'); ok();
  // … mais ne nomme ni gérant ni administrateur, et ne touche à aucun des deux.
  assert.equal(await essai('gerant', 'client', 'gerant'), 'non-autorise'); ok();
  assert.equal(await essai('gerant', 'client', 'admin'), 'non-autorise'); ok();
  assert.equal(await essai('gerant', 'admin', 'employe'), 'non-autorise'); ok();
  assert.equal(await essai('gerant', 'gerant2', 'employe'), 'non-autorise'); ok();
  assert.equal(await essai('gerant', 'gerant', 'gerant'), 'pas-soi-meme'); ok();
  assert.equal((await etat('admin')).role, 'admin'); ok();
  assert.equal((await etat('gerant2')).role, 'gerant'); ok();

  // L'employé à qui l'on a confié roles.gerer : mêmes limites.
  assert.equal(await essai('chef', 'admin', 'client'), 'non-autorise'); ok();
  assert.equal(await essai('chef', 'gerant', 'client'), 'non-autorise'); ok();
  assert.equal(await essai('chef', 'client', 'gerant'), 'non-autorise'); ok();
  assert.equal(await essai('chef', 'chef', 'employe', tous), 'pas-soi-meme'); ok();
  assert.equal(await essai('chef', 'autre', 'employe', ['colis.lire']), 'ok'); ok();
  assert.equal(await essai('simple', 'autre', 'client'), 'non-autorise'); ok();   // pas roles.gerer

  // L'administrateur nomme et retire, mais ne se retire pas lui-même.
  assert.equal(await essai('admin', 'client', 'gerant', ['colis.lire']), 'ok'); ok();
  assert.deepEqual(await etat('client'), { role: 'gerant', droits: [] }); ok();   // rien à cocher pour un gérant
  assert.equal(await essai('admin', 'client', 'client'), 'ok'); ok();
  assert.equal(await essai('admin', 'admin', 'employe'), 'pas-soi-meme'); ok();
  assert.equal(await essai('admin', 'admin', 'gerant'), 'pas-soi-meme'); ok();
  assert.equal((await etat('admin')).role, 'admin'); ok();

  // --- 3. L'équipe n'est pas la clientèle ------------------------------------
  const compteDe = async (cible) => {
    await entrer('admin');
    return (await api.admin.clients({ parPage: 100 })).lignes.filter((x) => x.id === ids[cible])[0];
  };
  // La section précédente l'a laissé employé : il n'a donc pas d'identifiant. Redevenu
  // client, il en reçoit un nouveau (SES-#####).
  assert.equal((await compteDe('autre')).code, null); ok();
  assert.equal(await essai('admin', 'autre', 'client'), 'ok'); ok();
  assert.match((await compteDe('autre')).code, /^SES-\d{5}$/); ok();
  // En entrant dans l'équipe, il le perd ; en en sortant, il en reçoit un nouveau.
  assert.equal(await essai('admin', 'autre', 'employe', ['colis.lire']), 'ok'); ok();
  assert.equal((await compteDe('autre')).code, null); ok();
  assert.equal(await essai('admin', 'autre', 'gerant'), 'ok'); ok();
  assert.equal((await compteDe('autre')).code, null); ok();
  assert.equal(await essai('admin', 'autre', 'client'), 'ok'); ok();
  assert.match((await compteDe('autre')).code, /^SES-\d{5}$/); ok();

  // Un client qui a un colis ne passe pas dans l'équipe : il en perdrait le propriétaire.
  await entrer('admin');
  await api.admin.creerColis({ client_id: ids.avecColis, description: 'colis d\'essai', poids_lb: 5, tarif_lb: 2 });
  assert.equal(await essai('admin', 'avecColis', 'employe', ['colis.lire']), 'compte-a-des-colis'); ok();
  assert.equal(await essai('admin', 'avecColis', 'gerant'), 'compte-a-des-colis'); ok();
  assert.equal((await compteDe('avecColis')).role, 'client'); ok();

  // Aucun colis ni facture pour un membre de l'équipe.
  const refus = async (fn) => { try { await fn(); return 'ok'; } catch (e) { return e.code; } };
  await entrer('admin');
  assert.equal(await refus(() => api.admin.creerColis({ client_id: ids.gerant, description: 'x' })), 'client-invalide'); ok();
  assert.equal(await refus(() => api.admin.creerColis({ client_id: ids.admin, description: 'x' })), 'client-invalide'); ok();
  assert.equal(await refus(() => api.admin.creerFacture({ client_id: ids.chef, montant: 10 })), 'client-invalide'); ok();
  assert.equal(await refus(() => api.admin.creerColis({ client_id: ids.client, description: 'pour un client' })), 'ok'); ok();

  // Trois devises (étape 038), comme facturer_colis : (prix en dollars + 10 $) × taux du colis, gelé au premier paiement.
  const factureDe = async (id) => (await api.admin.factures({ colis_id: id, parPage: 1 })).lignes[0];
  assert.equal(await api.admin.dernierTaux('HTG'), null, 'aucun colis en gourdes : rien à proposer'); ok();
  const htg = await api.admin.creerColis({ client_id: ids.client, description: 'gourdes', poids_lb: 10, tarif_lb: 5, devise: 'HTG', taux_change: 131 });
  let fh = await factureDe(htg.id);
  assert.deepEqual([fh.devise, fh.montant, fh.frais_service, fh.lignes[0].montant_usd], ['HTG', 7860, 1310, 50]); ok();
  assert.equal(await api.admin.dernierTaux('HTG'), 131, 'le dernier taux employé est proposé'); ok();
  assert.equal(await api.admin.dernierTaux('USD'), 1); ok();
  await api.admin.modifierColis(htg.id, { taux_change: 132 });
  fh = await factureDe(htg.id); assert.equal(fh.montant, 7920, 'facture impayée : elle suit le nouveau taux'); ok();
  const dop = await api.admin.creerColis({ client_id: ids.client, description: 'pesos', poids_lb: 1, tarif_lb: 0, prix_manuel: 40, devise: 'DOP', taux_change: 58.5 });
  const fd = await factureDe(dop.id); assert.deepEqual([fd.devise, fd.montant], ['DOP', 2925]); ok();
  const usd = await api.admin.creerColis({ client_id: ids.client, description: 'dollars', poids_lb: 4, tarif_lb: 5, devise: 'USD', taux_change: 7 });
  assert.equal(usd.taux_change, 1, 'en dollars, le taux est toujours 1'); ok();
  assert.equal(await refus(() => api.admin.creerColis({ client_id: ids.client, description: 'x', devise: 'HTG', taux_change: 0 })), 'taux-invalide'); ok();
  assert.equal(await refus(() => api.admin.creerFacture({ client_id: ids.client, devise: 'HTG', groupee: true,
    lignes: [{ colis_id: htg.id, montant: 1 }, { colis_id: dop.id, montant: 1 }] })), 'devises-melangees', 'une groupée ne mélange pas les devises'); ok();

  // Les deux listes ne se mélangent pas : « client » ne montre que des clients,
  // « equipe » que l'équipe.
  const roles = async (o) => Array.from(new Set((await api.admin.clients(Object.assign({ parPage: 100 }, o))).lignes.map((x) => x.role))).sort();
  assert.deepEqual(await roles({ role: 'client' }), ['client']); ok();
  assert.deepEqual(await roles({ role: 'equipe' }), ['admin', 'employe', 'gerant']); ok();
  // Un compte d'équipe n'est jamais proposé comme destinataire d'un colis.
  const equipe = (await api.admin.clients({ role: 'equipe', parPage: 100 })).lignes;
  assert.ok(equipe.every((x) => !x.code)); ok();

  // L'identifiant d'équipe, comme la base : le préfixe du rôle, un nouveau à chaque rôle, jamais réutilisé, retiré pour un client.
  const mat = async (cible) => { await entrer('admin'); const r = await api.admin.clients({ parPage: 200 }); return (r.lignes.filter((x) => x.id === ids[cible])[0] || {}).matricule; };
  assert.equal(await essai('admin', 'avecColis', 'client'), 'ok'); ok();
  const neuf = (await api.inscrire({ email: 'matricule@essai.test', motDePasse: MDP, nom_complet: 'Matricule' })).profil.id; await api.deconnecter();
  ids.matricule = neuf;
  assert.equal(await essai('admin', 'matricule', 'employe', ['colis.lire']), 'ok'); ok();
  const m1 = await mat('matricule'); assert.match(m1, /^EMP-[1-9][0-9]{3}$/); ok();
  assert.equal(await essai('admin', 'matricule', 'employe', ['colis.lire', 'colis.statut']), 'ok'); ok();
  assert.equal(await mat('matricule'), m1, 'mêmes rôle : même identifiant'); ok();
  assert.equal(await essai('admin', 'matricule', 'gerant'), 'ok'); ok();
  const m2 = await mat('matricule'); assert.match(m2, /^GER-[1-9][0-9]{3}$/); ok();
  assert.equal(await essai('admin', 'matricule', 'client'), 'ok'); ok();
  assert.equal(await mat('matricule'), null, 'client : plus d\'identifiant d\'équipe'); ok();
  assert.equal(await essai('admin', 'matricule', 'employe', ['colis.lire']), 'ok'); ok();
  const m3 = await mat('matricule'); assert.ok(/^EMP-/.test(m3) && m3 !== m1, 'retour : un nouvel identifiant, jamais l\'ancien'); ok();

  // L'identité donnée à l'inscription (étape 037), comme la base : gardée si elle est bien formée, laissée vide sinon.
  const ident = async (email, champs) => { const p = (await api.inscrire(Object.assign({ email, motDePasse: MDP, nom_complet: 'Identité' }, champs))).profil;
    await api.deconnecter(); return [p.date_naissance, p.document_type, p.document_numero].join('|'); };
  assert.equal(await ident('identite1@essai.test', { date_naissance: '1990-05-14', document_type: 'cedula', document_numero: '  001-1234567-8 ' }),
    '1990-05-14|cedula|001-1234567-8'); ok();
  assert.equal(await ident('identite2@essai.test', { date_naissance: '14/05/1990', document_type: 'permis', document_numero: 'N'.repeat(60) }),
    '|' + '|' + 'N'.repeat(40), 'date d\'un autre format et type inconnu laissés vides, numéro coupé à 40'); ok();
  assert.equal(await ident('identite3@essai.test', {}), '||', 'sans identité (application mobile) : rien d\'inventé'); ok();
  for (const [i, date] of [['4', '1990-02-30'], ['5', '2999-01-01'], ['6', '1850-06-01']]) {
    assert.equal(await ident('identite' + i + '@essai.test', { date_naissance: date }), '||', date + ' : impossible, future ou avant 1900 — laissée vide'); ok();
  }

  console.log(`PASS rôles API : ${n} vérifications — accès au tableau de bord fermé par défaut, hiérarchie du mode démo identique à la base`);
})().catch((e) => { console.error(e); process.exit(1); });
