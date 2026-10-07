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

  console.log(`PASS rôles API : ${n} vérifications — accès au tableau de bord fermé par défaut, hiérarchie du mode démo identique à la base`);
})().catch((e) => { console.error(e); process.exit(1); });
