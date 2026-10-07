// Les numéros de colis « SES- » + dix chiffres au hasard, sur un vrai PostgreSQL (WASM), jamais la production.
//   SES_TEST_DEPS=/dossier/avec/pglite node outils/tests/numeros-colis.cjs
//
// Deux chemins, comme roles-sql.cjs : la PRODUCTION (le schéma d'avant, des colis déjà numérotés à l'ancienne,
// puis le collage de supabase-maj-numeros.sql) et une INSTALLATION NEUVE (supabase.sql). On exige :
//   · le format exact, le premier chiffre jamais nul ;
//   · aucun doublon sur des centaines de colis ;
//   · les colis déjà enregistrés gardent leur numéro (il est sur l'étiquette), et une modification ne le change jamais ;
//   · un numéro saisi à la main reste accepté ;
//   · la fonction de la mise à jour est exactement celle du schéma, et la rejouer ne change rien.
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
const CLIENT = '00000000-0000-0000-0000-0000000000d1';
const FORMAT = /^SES-[1-9][0-9]{9}$/;
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };

async function monter(PGlite, schema) {
  const db = new PGlite();
  await db.exec(SOCLE);
  await db.exec(schema);
  await db.query(`insert into auth.users (id, email) values ($1, 'client@essai.test')`, [CLIENT]);
  return db;
}
const inserer = async (db, numero) => (await db.query(
  `insert into public.colis (client_id, description, numero) values ($1, 'essai', $2) returning numero`, [CLIENT, numero ?? null])).rows[0].numero;
const definition = async (db) => (await db.query(`select pg_get_functiondef('public.preparer_colis()'::regprocedure) d`)).rows[0].d;

async function verifierNeufs(db, ou) {
  const vus = new Set();
  for (let i = 0; i < 400; i++) {
    const num = await inserer(db);
    ok(FORMAT.test(num), ou + ' : format SES- + 10 chiffres (' + num + ')');
    ok(!vus.has(num), ou + ' : numéro jamais attribué deux fois (' + num + ')');
    vus.add(num);
  }
  // le hasard couvre bien les dix chiffres (pas un compteur déguisé)
  const premiers = new Set([...vus].map((v) => v[4]));
  ok(premiers.size >= 7, ou + ' : le premier chiffre varie (' + [...premiers].sort().join('') + ')');
  // un numéro saisi à la main est gardé (en majuscules), comme avant
  ok(await inserer(db, '  ses-manuel-1 ') === 'SES-MANUEL-1', ou + ' : un numéro saisi à la main reste accepté');
  // une modification ne touche jamais au numéro (le contrôle des droits, éprouvé par roles-sql.cjs, est mis de côté le temps de ce geste)
  const num = await inserer(db);
  await db.exec('alter table public.colis disable trigger verifier_modification_colis');
  await db.query(`update public.colis set numero = 'SES-0000000000', description = 'modifié' where numero = $1`, [num]);
  await db.exec('alter table public.colis enable trigger verifier_modification_colis');
  ok((await db.query(`select count(*)::int k from public.colis where numero = $1 and description = 'modifié'`, [num])).rows[0].k === 1,
    ou + ' : le numéro ne change jamais après l\'enregistrement');
}

(async () => {
  const racine = process.env.SES_TEST_DEPS;
  assert.ok(racine, 'SES_TEST_DEPS doit pointer vers un dossier contenant node_modules/@electric-sql/pglite');
  const { PGlite } = await import(racine + '/node_modules/@electric-sql/pglite/dist/index.js');
  const lire = (f) => fs.readFileSync(f, 'utf8');
  const schema = lire('outils/supabase.sql'), maj = lire('outils/supabase-maj.sql'), dash = lire('outils/supabase-dashboard.sql');
  const numeros = lire('outils/supabase-maj-numeros.sql');

  // la mise à jour porte EXACTEMENT la fonction du schéma
  const extraire = (s) => s.slice(s.indexOf('create or replace function public.preparer_colis()'), s.indexOf('$$;', s.indexOf('create or replace function public.preparer_colis()')) + 3);
  ok(extraire(numeros) === extraire(schema), 'supabase-maj-numeros.sql et supabase.sql : la même fonction, mot pour mot');

  // Chemin 1 : la production — le schéma d'avant ce changement, des colis numérotés à l'ancienne, puis le collage.
  const AVANT = '29c152a';
  let ancien = null;
  try {
    ancien = cp.execFileSync('git', ['show', AVANT + ':outils/supabase.sql'], { encoding: 'utf8', maxBuffer: 1 << 24, stdio: ['ignore', 'pipe', 'ignore'] });
  } catch { console.warn('ATTENTION : commit ' + AVANT + ' introuvable (clone superficiel ?) — chemin « production » non éprouvé.'); }
  if (ancien) {
    const db = await monter(PGlite, ancien + '\n' + dash + '\n' + maj);
    const anciens = [await inserer(db), await inserer(db)];
    ok(anciens.every((v) => /^SES-\d+-/.test(v)), 'avant : numéros à l\'ancienne (' + anciens.join(', ') + ')');
    await db.exec(numeros);
    const restes = (await db.query(`select numero from public.colis order by cree_le`)).rows.map((r) => r.numero);
    ok(restes.join() === anciens.join(), 'les colis déjà enregistrés gardent leur numéro');
    await verifierNeufs(db, 'prod');
    const avant = await definition(db);
    await db.exec(numeros);                       // collé une deuxième fois
    ok(await definition(db) === avant, 'prod : rejouer la mise à jour ne change rien');
    await db.close();
  }

  // Chemin 2 : installation neuve, puis la mise à jour rejouée par-dessus.
  const db2 = await monter(PGlite, schema + '\n' + dash + '\n' + maj);
  await verifierNeufs(db2, 'neuf');
  const avant2 = await definition(db2);
  await db2.exec(numeros);
  ok(await definition(db2) === avant2, 'neuf : la mise à jour ne change rien à une installation neuve');
  await db2.close();

  console.log('PASS numéros de colis : ' + n + ' vérifications — SES- et dix chiffres au hasard, aucun doublon, anciens numéros gardés, numéro figé, mise à jour identique au schéma et rejouable');
})().catch((e) => { console.error(e); process.exit(1); });
