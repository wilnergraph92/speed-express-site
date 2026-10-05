// Les quatre rôles, exécutés sur un vrai PostgreSQL (WASM), jamais sur la base
// de production. Le schéma réel est chargé tel quel ; seuls l'annuaire des
// comptes (auth.users) et ses fonctions sont simulés.
//
// Deux chemins sont éprouvés, parce que la production n'a pas le même état
// qu'une installation neuve :
//   1. l'ANCIEN schéma (trois rôles) puis supabase-maj.sql — ce que fait le
//      collage dans le SQL Editor ;
//   2. le NOUVEAU schéma, puis supabase-maj.sql rejoué — il doit rester sans effet.
const fs = require('node:fs'), cp = require('node:child_process'), assert = require('node:assert/strict');

const ID = {
  admin:  '00000000-0000-0000-0000-0000000000a1',
  gerant: '00000000-0000-0000-0000-0000000000b1',
  gerant2:'00000000-0000-0000-0000-0000000000b2',
  chef:   '00000000-0000-0000-0000-0000000000c1', // employé à qui l'on a confié roles.gerer
  simple: '00000000-0000-0000-0000-0000000000c2', // employé : colis.lire seulement
  rien:   '00000000-0000-0000-0000-0000000000c3', // employé sans aucun droit
  client: '00000000-0000-0000-0000-0000000000d1',
  autre:  '00000000-0000-0000-0000-0000000000d2', // un second client
  triche: '00000000-0000-0000-0000-0000000000d3', // client dont la colonne « droits » a été falsifiée
  neuf:   '00000000-0000-0000-0000-0000000000e1', // client sans colis ni facture : peut rejoindre l'équipe
  neuf2:  '00000000-0000-0000-0000-0000000000e2'
};
const DROITS = ['colis.lire','colis.creer','colis.modifier','colis.statut','colis.supprimer',
  'factures.lire','factures.creer','factures.modifier','factures.supprimer','clients.lire','roles.gerer'];

const SOCLE = `
  create role anon nologin; create role authenticated nologin; create role service_role nologin;
  create schema auth;
  create table auth.users (id uuid primary key, email text, raw_user_meta_data jsonb default '{}'::jsonb);
  create function auth.uid() returns uuid language sql stable
    as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  grant usage on schema auth to anon, authenticated;
  create publication supabase_realtime;
  create function public.gen_random_bytes(n int) returns bytea language sql
    as $$ select decode(md5(random()::text), 'hex') $$;
`;

async function monter(PGlite, schema) {
  const db = new PGlite();
  await db.exec(SOCLE);
  await db.exec(schema);
  return db;
}
async function comptes(db) {
  for (const [nom, id] of Object.entries(ID))
    await db.query(`insert into auth.users (id, email) values ($1, $2)`, [id, nom + '@essai.test']);
  const role = (id, r, d) => db.query(`update public.clients set role=$2, droits=$3 where id=$1`, [id, r, d]);
  await role(ID.admin, 'admin', []);        await role(ID.gerant, 'gerant', []);
  await role(ID.gerant2, 'gerant', []);     await role(ID.chef, 'employe', ['colis.lire', 'roles.gerer']);
  await role(ID.simple, 'employe', ['colis.lire']); await role(ID.rien, 'employe', []);
  // Un client dont la colonne « droits » contient tout : elle ne doit rien donner.
  await role(ID.triche, 'client', DROITS);
  await db.query(`insert into public.colis (client_id, description) values ($1,'colis du client'), ($2,'colis de l''autre')`, [ID.client, ID.autre]);
}
const comme = async (db, qui) => {
  await db.exec('reset role');
  await db.exec(`select set_config('request.jwt.claim.sub', '${ID[qui]}', false); set role authenticated`);
};
const code = async (db, sql, p) => { try { await db.query(sql, p); return 'ok'; } catch (e) { return e.code || e.message; } };
const valeur = async (db, sql, p) => (await db.query(sql, p)).rows[0];
let n = 0;
const ok = (msg) => { n++; };

// Une base d'AVANT la règle : des comptes d'équipe qui portent un identifiant
// client. supabase-maj.sql doit le retirer à ceux qui n'ont ni colis ni facture,
// et SEULEMENT à eux : on ne coupe pas en silence le lien d'un compte qui porte
// encore des colis.
const HERITES = {
  sans:    '00000000-0000-0000-0000-0000000000f1',   // ni colis ni facture : perd son identifiant
  colis:   '00000000-0000-0000-0000-0000000000f2',   // un colis, aucune facture
  facture: '00000000-0000-0000-0000-0000000000f3'    // une facture, aucun colis
};
async function preparerHeritage(db) {
  for (const [nom, id] of Object.entries(HERITES))
    await db.query(`insert into auth.users (id, email) values ($1, $2)`, [id, 'herite-' + nom + '@essai.test']);
  await db.query(`update public.clients set role='employe' where id = any($1)`, [Object.values(HERITES)]);
  // Un colis fait naître sa facture (facturer_colis) : on la retire pour isoler la dépendance « colis seul ».
  await db.query(`insert into public.colis (client_id, description) values ($1,'colis hérité')`, [HERITES.colis]);
  await db.query(`delete from public.factures where client_id=$1`, [HERITES.colis]);
  // Et une facture écrite à la main, sans colis : la dépendance « facture seule ».
  await db.query(`insert into public.factures (client_id, montant) values ($1, 25)`, [HERITES.facture]);
  const lignes = (await db.query(`select code from public.clients where id = any($1)`, [Object.values(HERITES)])).rows;
  assert.equal(lignes.length, 3);
  assert.ok(lignes.every((r) => /^SES-\d{5}$/.test(r.code)), 'avant la mise à jour, les comptes hérités ont un identifiant client');
  assert.equal((await db.query(`select count(*)::int n from public.factures where client_id=$1`, [HERITES.colis])).rows[0].n, 0, 'le compte « colis » n’a pas de facture');
  assert.equal((await db.query(`select count(*)::int n from public.colis where client_id=$1`, [HERITES.facture])).rows[0].n, 0, 'le compte « facture » n’a pas de colis');
}
async function controlerHeritage(db, libelle) {
  const code = async (id) => (await db.query(`select code c from public.clients where id=$1`, [id])).rows[0].c;
  assert.equal(await code(HERITES.sans), null, libelle + ' : sans colis ni facture, un compte d’équipe perd son identifiant'); ok();
  assert.match(await code(HERITES.colis), /^SES-\d{5}$/, libelle + ' : avec un colis, il le garde'); ok();
  assert.match(await code(HERITES.facture), /^SES-\d{5}$/, libelle + ' : avec une facture, il le garde'); ok();
}

async function verifier(db, libelle) {
  await db.exec('reset role');
  await comptes(db);

  // --- 1. a_droit : qui peut quoi ---------------------------------------------
  for (const [qui, attendu] of [
    ['admin', DROITS], ['gerant', DROITS], ['chef', ['colis.lire', 'roles.gerer']],
    ['simple', ['colis.lire']], ['rien', []], ['client', []], ['triche', []]
  ]) {
    await comme(db, qui);
    for (const d of DROITS) {
      const a = (await valeur(db, `select public.a_droit($1) v`, [d])).v;
      assert.equal(a, attendu.includes(d), `${libelle} · a_droit(${d}) pour ${qui}`); ok();
    }
  }
  // La falsification de la colonne « droits » d'un client n'ouvre rien.
  await comme(db, 'triche');
  assert.equal(await code(db, `select public.dashboard_colis_ses()`), '42501'); ok();

  // --- 2. Le tableau de bord : le client n'y entre jamais ---------------------
  for (const qui of ['client', 'autre', 'triche', 'rien']) {
    await comme(db, qui);
    for (const sql of [`select public.dashboard_colis_ses()`, `select public.dashboard_clients_ses()`, `select public.statistiques_ses()`])
      assert.equal(await code(db, sql), '42501', `${libelle} · ${qui} ne lit pas : ${sql}`), ok();
  }
  for (const qui of ['admin', 'gerant']) {
    await comme(db, qui);
    for (const sql of [`select public.dashboard_colis_ses()`, `select public.dashboard_clients_ses()`, `select public.statistiques_ses()`])
      assert.equal(await code(db, sql), 'ok', `${libelle} · ${qui} lit : ${sql}`), ok();
  }
  await comme(db, 'simple');
  assert.equal(await code(db, `select public.dashboard_colis_ses()`), 'ok'); ok();
  assert.equal(await code(db, `select public.dashboard_clients_ses()`), '42501'); ok();   // pas clients.lire

  // --- 3. Les lignes elles-mêmes : un client ne voit que les siennes ----------
  await comme(db, 'client');
  assert.equal((await valeur(db, `select count(*)::int n from public.colis`)).n, 1); ok();
  assert.equal((await valeur(db, `select count(*)::int n from public.clients`)).n, 1); ok();
  // Le gérant voit TOUS les colis : le total réel, pas un nombre figé (le chemin
  // « production » en contient un de plus : celui du compte d'équipe hérité).
  await db.exec('reset role');
  const tousLesColis = (await valeur(db, `select count(*)::int n from public.colis`)).n;
  await comme(db, 'gerant');
  assert.equal((await valeur(db, `select count(*)::int n from public.colis`)).n, tousLesColis); ok();
  assert.ok(tousLesColis >= 2); ok();
  await comme(db, 'rien');
  assert.equal((await valeur(db, `select count(*)::int n from public.colis`)).n, 0); ok();

  // --- 4. Écrire : le gérant crée, l'employé en lecture seule non -------------
  await comme(db, 'gerant');
  assert.equal(await code(db, `insert into public.colis (client_id, description) values ($1,'créé par le gérant')`, [ID.client]), 'ok'); ok();
  await comme(db, 'simple');
  assert.equal(await code(db, `insert into public.colis (client_id, description) values ($1,'refusé')`, [ID.client]), '42501'); ok();
  await comme(db, 'client');
  assert.equal(await code(db, `insert into public.colis (client_id, description) values ($1,'refusé')`, [ID.client]), '42501'); ok();

  // --- 5. Les coordonnées : le gérant en corrige, pas l'employé ---------------
  await comme(db, 'gerant');
  await db.query(`update public.clients set telephone='+509 1111 1111' where id=$1`, [ID.client]);
  await db.exec('reset role');
  assert.equal((await valeur(db, `select telephone t from public.clients where id=$1`, [ID.client])).t, '+509 1111 1111'); ok();
  await comme(db, 'simple');
  await db.query(`update public.clients set telephone='piraté' where id=$1`, [ID.client]);   // 0 ligne visible
  await db.exec('reset role');
  assert.equal((await valeur(db, `select telephone t from public.clients where id=$1`, [ID.client])).t, '+509 1111 1111'); ok();
  // Le rôle ne se change JAMAIS par une mise à jour directe, même pour la direction.
  await comme(db, 'gerant');
  assert.equal(await code(db, `update public.clients set role='admin' where id=$1`, [ID.client]), '42501'); ok();
  await comme(db, 'client');
  assert.equal(await code(db, `update public.clients set role='admin' where id=$1`, [ID.client]), '42501'); ok();

  // --- 6. definir_role : la hiérarchie ----------------------------------------
  const role = async (qui, cible, r, d = []) => { await comme(db, qui); return code(db, `select public.definir_role($1,$2,$3)`, [ID[cible], r, d]); };
  const etat = async (cible) => { await db.exec('reset role'); return valeur(db, `select role, droits from public.clients where id=$1`, [ID[cible]]); };

  // Le client n'a aucun pouvoir.
  assert.equal(await role('client', 'autre', 'employe'), '42501'); ok();
  assert.equal(await role('triche', 'autre', 'employe'), '42501'); ok();
  // Un rôle qui n'existe pas.
  assert.equal(await role('admin', 'neuf', 'superman'), '22023'); ok();

  // Le gérant gère l'équipe …
  assert.equal(await role('gerant', 'neuf', 'employe', ['colis.lire', 'factures.lire']), 'ok'); ok();
  assert.deepEqual(await etat('neuf'), { role: 'employe', droits: ['colis.lire', 'factures.lire'] }); ok();
  assert.equal(await role('gerant', 'neuf', 'client'), 'ok'); ok();
  // … mais ne nomme ni gérant ni administrateur, et ne touche à aucun des deux.
  assert.equal(await role('gerant', 'neuf', 'gerant'), '42501'); ok();
  assert.equal(await role('gerant', 'neuf', 'admin'), '42501'); ok();
  assert.equal(await role('gerant', 'admin', 'employe'), '42501'); ok();
  assert.equal(await role('gerant', 'gerant2', 'employe'), '42501'); ok();
  assert.equal(await role('gerant', 'gerant', 'gerant'), '42501'); ok();          // pas soi-même
  assert.equal((await etat('admin')).role, 'admin'); ok();
  assert.equal((await etat('gerant2')).role, 'gerant'); ok();

  // L'employé à qui l'on a confié roles.gerer : mêmes limites. C'était une
  // brèche — il pouvait rétrograder un administrateur.
  assert.equal(await role('chef', 'admin', 'client'), '42501'); ok();
  assert.equal(await role('chef', 'gerant', 'client'), '42501'); ok();
  assert.equal(await role('chef', 'neuf', 'gerant'), '42501'); ok();
  assert.equal(await role('chef', 'chef', 'employe', DROITS), '42501'); ok();      // pas de s'auto-promouvoir
  assert.equal(await role('chef', 'neuf2', 'employe', ['colis.lire']), 'ok'); ok();
  assert.equal(await role('chef', 'neuf2', 'client'), 'ok'); ok();
  // Un employé sans roles.gerer ne peut rien.
  assert.equal(await role('simple', 'neuf2', 'employe'), '42501'); ok();

  // L'administrateur nomme et retire, mais ne se retire pas lui-même.
  assert.equal(await role('admin', 'neuf', 'gerant', ['colis.lire']), 'ok'); ok();
  assert.deepEqual(await etat('neuf'), { role: 'gerant', droits: [] }, 'un gérant n’a pas de droits à cocher'); ok();
  assert.equal(await role('admin', 'neuf', 'admin'), 'ok'); ok();
  assert.equal(await role('admin', 'neuf', 'client'), 'ok'); ok();
  assert.equal(await role('admin', 'admin', 'employe'), '42501'); ok();
  assert.equal(await role('admin', 'admin', 'gerant'), '42501'); ok();
  assert.equal(await role('admin', 'admin', 'admin'), 'ok'); ok();
  assert.equal((await etat('admin')).role, 'admin'); ok();


  // --- 6b. L'équipe n'est pas la clientèle ------------------------------------
  const code_de = async (cible) => { await db.exec('reset role'); return (await valeur(db, `select code c from public.clients where id=$1`, [ID[cible]])).c; };

  // Un client a un identifiant ; en entrant dans l'équipe, il le perd.
  assert.match(await code_de('neuf'), /^SES-\d{5}$/); ok();
  assert.equal(await role('admin', 'neuf', 'employe', ['colis.lire']), 'ok'); ok();
  assert.equal(await code_de('neuf'), null, 'un employé n’a pas d’identifiant client'); ok();
  assert.equal(await role('admin', 'neuf', 'gerant'), 'ok'); ok();
  assert.equal(await code_de('neuf'), null); ok();
  assert.equal(await role('admin', 'neuf', 'admin'), 'ok'); ok();
  assert.equal(await code_de('neuf'), null); ok();
  // Redevenu client, il en reçoit un nouveau.
  assert.equal(await role('admin', 'neuf', 'client'), 'ok'); ok();
  assert.match(await code_de('neuf'), /^SES-\d{5}$/); ok();

  // Un client qui a des colis (ou des factures) ne passe pas dans l'équipe : ils
  // perdraient leur propriétaire.
  assert.equal(await role('admin', 'client', 'employe', ['colis.lire']), 'SE001'); ok();
  assert.equal(await role('admin', 'client', 'gerant'), 'SE001'); ok();
  assert.equal((await etat('client')).role, 'client'); ok();
  assert.match(await code_de('client'), /^SES-\d{5}$/); ok();

  // Aucun colis ni facture pour un membre de l'équipe — même en appelant la
  // base directement, même pour la direction.
  await db.exec('reset role');
  await db.query(`update public.clients set role='employe', droits='{}' where id=$1`, [ID.neuf2]);   // en superutilisateur : le compte devient membre de l'équipe
  for (const qui of ['admin', 'gerant']) {
    await comme(db, qui);
    assert.equal(await code(db, `insert into public.colis (client_id, description) values ($1,'pour un employé')`, [ID.neuf2]), 'SE002', `${qui} : colis pour un membre de l'équipe`); ok();
    assert.equal(await code(db, `insert into public.factures (client_id, montant) values ($1, 10)`, [ID.neuf2]), 'SE002', `${qui} : facture pour un membre de l'équipe`); ok();
    // Un colis déjà rattaché à un client ne peut pas être « donné » à l'équipe.
    assert.equal(await code(db, `update public.colis set client_id=$1 where client_id=$2`, [ID.neuf2, ID.client]), 'SE002'); ok();
  }
  // Un client reste un destinataire valable.
  await comme(db, 'gerant');
  assert.equal(await code(db, `insert into public.colis (client_id, description) values ($1,'pour un vrai client')`, [ID.client]), 'ok'); ok();

  // Un colis hérité d'avant la règle, resté chez un compte d'équipe, continue de
  // vivre : changement de statut, paiement. Seul un changement de client est refusé.
  await db.exec('reset role');
  const [herite] = (await db.query(`insert into public.colis (client_id, description) values ($1,'hérité') returning id`, [ID.client])).rows;
  // Fabriquer l'état hérité : rattacher un colis à un compte d'équipe, ce que la
  // règle interdit désormais — d'où les deux déclencheurs mis en veille un instant.
  await db.query(`alter table public.colis disable trigger verifier_client_colis`);
  await db.query(`alter table public.factures disable trigger verifier_client_facture`);
  await db.query(`update public.colis set client_id=$1 where id=$2`, [ID.neuf2, herite.id]);
  await db.query(`alter table public.colis enable trigger verifier_client_colis`);
  await db.query(`alter table public.factures enable trigger verifier_client_facture`);
  await comme(db, 'gerant');
  assert.equal(await code(db, `update public.colis set statut='expedie' where id=$1`, [herite.id]), 'ok', 'un colis hérité garde sa vie normale'); ok();
  // Modifier son poids réécrit sa facture (facturer_colis) : cela ne doit pas non plus échouer.
  assert.equal(await code(db, `update public.colis set poids_lb=12, tarif_lb=2 where id=$1`, [herite.id]), 'ok', 'poids et tarif d’un colis hérité'); ok();
  // … et son compte d'équipe, qui porte encore ce colis, peut changer de rôle d'équipe, en gardant son identifiant.
  await db.exec('reset role');
  await db.query(`update public.clients set code='SES-99999' where id=$1`, [ID.neuf2]);
  assert.equal(await role('admin', 'neuf2', 'gerant'), 'ok'); ok();
  assert.equal(await code_de('neuf2'), 'SES-99999', 'on ne coupe pas en silence un lien existant'); ok();
  await db.exec('reset role');
  await db.query(`delete from public.colis where client_id=$1`, [ID.neuf2]);
  await db.query(`update public.clients set role='client', droits='{}', code=null where id=$1`, [ID.neuf2]);

  // --- 7. La contrainte : aucun rôle inventé, même en superutilisateur --------
  await db.exec('reset role');
  assert.equal(await code(db, `update public.clients set role='superman' where id=$1`, [ID.client]), '23514'); ok();
  assert.equal(await code(db, `update public.clients set role='gerant' where id=$1`, [ID.client]), 'ok'); ok();
  await db.query(`update public.clients set role='client' where id=$1`, [ID.client]);
  return n;
}

(async () => {
  const racine = process.env.SES_TEST_DEPS;
  assert.ok(racine, 'SES_TEST_DEPS doit pointer vers un dossier contenant node_modules/@electric-sql/pglite');
  const { PGlite } = await import(racine + '/node_modules/@electric-sql/pglite/dist/index.js');
  const lire = (f) => fs.readFileSync(f, 'utf8');
  const maj = lire('outils/supabase-maj.sql'), dash = lire('outils/supabase-dashboard.sql');

  // Chemin 1 : la production — le schéma tel qu'il était AVANT les rôles (à ce
  // commit précis, pas à HEAD qui le contient désormais), puis le collage de la
  // mise à jour. Un dépôt cloné en surface n'a pas ce commit : on le dit au lieu
  // de passer sous silence.
  const AVANT_ROLES = 'cef8da6';
  let avantRoles = null;
  try {
    avantRoles = cp.execFileSync('git', ['show', AVANT_ROLES + ':outils/supabase.sql'],
      { encoding: 'utf8', maxBuffer: 1 << 24, stdio: ['ignore', 'pipe', 'ignore'] });
  } catch (e) { console.warn(`ATTENTION : commit ${AVANT_ROLES} introuvable (clone superficiel ?) — chemin « production » non éprouvé.`); }
  let total = 0;
  if (avantRoles) {
    const db = await monter(PGlite, avantRoles + '\n' + dash);
    await preparerHeritage(db);
    await db.exec(maj);
    await controlerHeritage(db, 'prod');
    total += await verifier(db, 'prod (ancien schéma + maj)');
    await db.exec(maj);                       // collé une deuxième fois : sans effet
    await db.close();
  }
  // Chemin 2 : installation neuve, puis la mise à jour rejouée.
  const db2 = await monter(PGlite, lire('outils/supabase.sql') + '\n' + dash);
  await db2.exec(maj);
  total += await verifier(db2, 'neuf (schéma + maj rejouée)');
  await db2.close();
  console.log(`PASS rôles SQL : ${total} vérifications — hiérarchie client/employé/gérant/admin, tableau de bord fermé aux clients, brèche « roles.gerer » close, migration rejouable`);
})().catch((e) => { console.error(e); process.exit(1); });
