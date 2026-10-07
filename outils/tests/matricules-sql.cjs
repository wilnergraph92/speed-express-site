// L'identifiant d'équipe (« matricule » : ADM-, GER-, EMP- et quatre chiffres), sur un vrai PostgreSQL (WASM), jamais la production.
//   SES_TEST_DEPS=/dossier/avec/pglite node outils/tests/matricules-sql.cjs
//
// On exige : un client n'en a pas ; un rôle d'équipe donne un identifiant au préfixe du rôle ; il ne change pas tant que le rôle
// ne change pas (droits, écriture directe) ; un nouveau rôle en donne un nouveau, l'ancien est retiré et jamais réutilisé ; le
// registre ne se réécrit ni ne s'efface et seule la direction le lit ; on ne fournit jamais un identifiant soi-même ; l'équipe
// déjà en place reçoit le sien au collage ; le fichier se rejoue sans rien changer. Deux chemins : la production (fichiers d'avant, puis le collage) et
// une installation neuve.
const fs = require('node:fs'), cp = require('node:child_process'), assert = require('node:assert/strict');

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
const ID = (n) => '00000000-0000-0000-0000-' + String(n).padStart(12, '0');

let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };
const code = async (db, sql, p) => { try { await db.query(sql, p); return 'ok'; } catch (e) { return e.code || e.message; } };
const mat = async (db, id) => (await db.query('select matricule from public.clients where id = $1', [id])).rows[0].matricule;

async function monter(PGlite, fichiers) {
  const db = new PGlite();
  await db.exec(SOCLE);
  for (const f of fichiers) await db.exec(f);
  return db;
}
async function compte(db, i, role) {
  await db.query('insert into auth.users (id, email) values ($1, $2)', [ID(i), 'c' + i + '@essai.test']);
  if (role && role !== 'client') await db.query("update public.clients set role = $2, code = null where id = $1", [ID(i), role]);
}

async function verifier(db, ou, dejaEnPlace) {
  // l'équipe d'avant le collage a reçu le sien, au préfixe de son rôle
  for (const [id, prefixe] of dejaEnPlace) ok(new RegExp('^' + prefixe + '-[1-9][0-9]{3}$').test(await mat(db, id) || ''), ou + ' : l\'équipe déjà en place reçoit son identifiant ' + prefixe + '-');
  await compte(db, 100, 'client');
  ok(await mat(db, ID(100)) === null, ou + ' : un client n\'a pas d\'identifiant d\'équipe');
  // l'administrateur nomme un employé par definir_role, comme dans le tableau de bord
  await compte(db, 101, 'admin');
  ok(/^ADM-[1-9][0-9]{3}$/.test(await mat(db, ID(101)) || ''), ou + ' : un administrateur reçoit ADM- et quatre chiffres');
  await compte(db, 102, 'client');
  const comme = (qui) => db.exec(`select set_config('request.jwt.claim.sub', '${qui}', false); set role authenticated`);
  await comme(ID(101));
  ok(await code(db, `select public.definir_role($1, 'employe', '{colis.lire}')`, [ID(102)]) === 'ok', ou + ' : definir_role nomme un employé');
  await db.exec('reset role');
  const emp = await mat(db, ID(102));
  ok(/^EMP-[1-9][0-9]{3}$/.test(emp || ''), ou + ' : l\'employé reçoit EMP- et quatre chiffres (' + emp + ')');
  // inchangeable tant que le rôle ne change pas
  await comme(ID(101));
  await db.query(`select public.definir_role($1, 'employe', '{colis.lire,colis.statut}')`, [ID(102)]);
  await db.exec('reset role');
  ok(await mat(db, ID(102)) === emp, ou + ' : nouveaux droits, même rôle : le même identifiant');
  await db.query("update public.clients set matricule = 'EMP-1111', nom_complet = 'Renommé' where id = $1", [ID(102)]);
  ok(await mat(db, ID(102)) === emp, ou + ' : une écriture directe ne le change pas');
  await db.query("update public.clients set matricule = null where id = $1", [ID(102)]);
  ok(await mat(db, ID(102)) === emp, ou + ' : ni ne l\'efface');
  // un nouveau rôle : un nouvel identifiant, l'ancien retiré et jamais réutilisé
  await comme(ID(101));
  await db.query(`select public.definir_role($1, 'gerant', '{}')`, [ID(102)]);
  await db.exec('reset role');
  const ger = await mat(db, ID(102));
  ok(/^GER-[1-9][0-9]{3}$/.test(ger || ''), ou + ' : promu gérant, il reçoit GER- (' + ger + ')');
  const reg = (await db.query('select matricule, role, retire_le from public.matricules_attribues where client_id = $1 order by attribue_le, matricule', [ID(102)])).rows;
  ok(reg.length === 2 && reg.some((r) => r.matricule === emp && r.retire_le) && reg.some((r) => r.matricule === ger && !r.retire_le), ou + ' : le registre garde l\'ancien (retiré) et le nouveau');
  await db.query("update public.clients set role = 'client' where id = $1", [ID(102)]);
  ok(await mat(db, ID(102)) === null, ou + ' : revenu à la clientèle, plus d\'identifiant d\'équipe');
  ok((await db.query('select count(*)::int k from public.matricules_attribues where client_id = $1 and retire_le is null', [ID(102)])).rows[0].k === 0, ou + ' : et le sien est retiré au registre');
  await db.query("update public.clients set role = 'employe' where id = $1", [ID(102)]);
  const emp2 = await mat(db, ID(102));
  ok(/^EMP-/.test(emp2 || '') && emp2 !== emp, ou + ' : revenu dans l\'équipe : un NOUVEL identifiant, jamais l\'ancien (' + emp2 + ')');
  // le registre ne se réécrit pas, ne s'efface pas, et un client ne le lit pas
  ok(await code(db, "update public.matricules_attribues set client_id = $1 where matricule = $2", [ID(100), emp]) === '42501', ou + ' : le registre ne se réécrit pas');
  ok(await code(db, "delete from public.matricules_attribues where matricule = $1", [emp]) === '42501', ou + ' : le registre ne s\'efface pas');
  await comme(ID(100));
  ok((await db.query('select count(*)::int k from public.matricules_attribues')).rows[0].k === 0, ou + ' : un client ne lit pas le registre');
  ok(await code(db, "update public.clients set matricule = 'ADM-2222' where id = $1", [ID(100)]) === '42501', ou + ' : un client ne s\'attribue pas d\'identifiant');
  ok(await code(db, "select public.nouveau_matricule('ADM')") === '42501', ou + ' : un compte connecté ne peut pas tirer un identifiant lui-même');
  await comme(ID(101));
  ok((await db.query('select count(*)::int k from public.matricules_attribues')).rows[0].k > 0, ou + ' : la direction lit le registre');
  await db.exec('reset role');
  // on ne fournit pas un identifiant : il se reçoit
  const r = await code(db, "insert into public.clients (id, role, matricule) values ($1, 'employe', 'EMP-3333')", [ID(104)]);
  ok(r !== 'ok' || (await mat(db, ID(104))) !== 'EMP-3333', ou + ' : un identifiant fourni à la main est ignoré');
  ok(await code(db, "update public.clients set matricule = 'pas-un-format'") === 'ok', ou + ' : (écriture ignorée sans erreur)');
  ok(await code(db, "select public.nouveau_matricule('XXX')") === '22023', ou + ' : préfixe inconnu refusé');
  // aucun doublon, même avec les retirés, sur une grande équipe
  for (let i = 200; i < 500; i++) await compte(db, i, ['employe', 'gerant', 'admin'][i % 3]);
  const tous = (await db.query("select c.matricule, c.role from public.clients c where c.role <> 'client'")).rows;
  ok(tous.every((x) => new RegExp('^' + { admin: 'ADM', gerant: 'GER', employe: 'EMP' }[x.role] + '-[1-9][0-9]{3}$').test(x.matricule || '')), ou + ' : chacun le préfixe de son rôle (' + tous.length + ')');
  const registre = (await db.query('select matricule from public.matricules_attribues')).rows.map((x) => x.matricule);
  ok(new Set(registre).size === registre.length && tous.every((x) => registre.includes(x.matricule)), ou + ' : aucun identifiant donné deux fois, retirés compris (' + registre.length + ')');
}

(async () => {
  const racine = process.env.SES_TEST_DEPS;
  assert.ok(racine, 'SES_TEST_DEPS doit pointer vers un dossier contenant node_modules/@electric-sql/pglite');
  const { PGlite } = await import(racine + '/node_modules/@electric-sql/pglite/dist/index.js');
  const lire = (f) => fs.readFileSync(f, 'utf8');
  const equipe = lire('outils/supabase-maj-equipe.sql');

  // Chemin 1 : la production — les fichiers d'avant, un administrateur déjà en place, puis le collage (deux fois).
  const AVANT = '5922510';
  const avant = (f) => { try { return cp.execFileSync('git', ['show', AVANT + ':' + f], { encoding: 'utf8', maxBuffer: 1 << 24, stdio: ['ignore', 'pipe', 'ignore'] }); } catch { return null; } };
  const anciens = ['outils/supabase.sql', 'outils/supabase-dashboard.sql', 'outils/supabase-maj.sql'].map(avant);
  if (anciens.every(Boolean)) {
    const db = await monter(PGlite, anciens);
    await compte(db, 1, 'admin');
    await compte(db, 2, 'employe');
    await compte(db, 3, 'gerant');
    await db.exec(equipe);
    const premiers = [await mat(db, ID(1)), await mat(db, ID(2))];
    await db.exec(equipe);
    ok((await mat(db, ID(1))) === premiers[0] && (await mat(db, ID(2))) === premiers[1], 'prod : recollé, aucun identifiant ne change');
    await verifier(db, 'prod', [[ID(1), 'ADM'], [ID(2), 'EMP'], [ID(3), 'GER']]);
    await db.close();
  } else console.warn('ATTENTION : commit ' + AVANT + ' introuvable (clone superficiel ?) — chemin « production » non éprouvé.');

  // Chemin 2 : installation neuve.
  const db2 = await monter(PGlite, [lire('outils/supabase.sql'), lire('outils/supabase-dashboard.sql'), lire('outils/supabase-maj.sql'), equipe]);
  await verifier(db2, 'neuf', []);
  await db2.close();

  console.log('PASS identifiants d\'équipe : ' + n + ' vérifications — ADM-/GER-/EMP- et quatre chiffres donnés par la base, inchangeables tant que le rôle ne change pas, un nouveau à chaque rôle, jamais réutilisés (registre), jamais fournis à la main, rattrapage de l\'équipe en place, rejouable');
})().catch((e) => { console.error(e); process.exit(1); });
