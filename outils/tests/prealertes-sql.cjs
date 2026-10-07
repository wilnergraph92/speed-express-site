// Le prix saisi à la main et les pré-alertes, sur un vrai PostgreSQL (WASM), jamais la production.
//   SES_TEST_DEPS=/dossier/avec/pglite node outils/tests/prealertes-sql.cjs
//
// Deux chemins : la PRODUCTION (les fichiers tels qu'ils étaient avant ce changement, puis le collage de
// supabase-maj-prix-prealertes.sql) et une INSTALLATION NEUVE (supabase.sql, puis les mises à jour). On exige :
//   · prix : la facture prend le prix saisi, revient à poids × tarif quand on l'efface, ne bouge plus une fois payée ;
//     un employé sans « colis.modifier » ne le touche pas ; un client non plus ;
//   · pré-alertes : un client crée et lit les siennes seulement, sans choisir statut, colis ni note, 30 par 24 h au plus ;
//     l'équipe les lit (« colis.lire ») et les traite (« colis.statut ») ; un colis relié appartient au même client ;
//     un visiteur ne lit rien, personne ne supprime ;
//   · le fichier à coller porte les MÊMES fonctions et la même vue que supabase.sql / supabase-maj.sql, et se rejoue.
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
const ID = {
  admin: '00000000-0000-0000-0000-0000000000a1',
  lecteur: '00000000-0000-0000-0000-0000000000c1',   // employé : colis.lire
  agent: '00000000-0000-0000-0000-0000000000c2',     // employé : colis.lire + colis.statut
  client: '00000000-0000-0000-0000-0000000000d1',
  autre: '00000000-0000-0000-0000-0000000000d2',
};
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };
const code = async (db, sql, p) => { try { await db.query(sql, p); return 'ok'; } catch (e) { return e.code || e.message; } };
const un = async (db, sql, p) => (await db.query(sql, p)).rows[0];
const comme = async (db, qui) => {
  await db.exec('reset role');
  if (qui === 'anon') { await db.exec(`select set_config('request.jwt.claim.sub', '', false); set role anon`); return; }
  await db.exec(`select set_config('request.jwt.claim.sub', '${ID[qui]}', false); set role authenticated`);
};
const moi = (db) => db.exec(`reset role; select set_config('request.jwt.claim.sub', '', false)`);

async function monter(PGlite, sql) {
  const db = new PGlite();
  await db.exec(SOCLE);
  for (const s of sql) await db.exec(s);
  for (const [nom, id] of Object.entries(ID)) await db.query(`insert into auth.users (id, email) values ($1, $2)`, [id, nom + '@essai.test']);
  await db.query(`update public.clients set role = 'admin', droits = '{}' where id = $1`, [ID.admin]);
  await db.query(`update public.clients set role = 'employe', droits = '{colis.lire}' where id = $1`, [ID.lecteur]);
  await db.query(`update public.clients set role = 'employe', droits = '{colis.lire,colis.statut}' where id = $1`, [ID.agent]);
  return db;
}

async function verifier(db, ou) {
  // ---------------------------------------------------------------- prix saisi à la main
  await moi(db);
  const colis = (await un(db, `insert into public.colis (client_id, description, poids_lb, tarif_lb) values ($1, 'essai prix', 10, 4) returning id`, [ID.client])).id;
  const facture = async () => un(db, `select montant::float m, lignes from public.factures where colis_id = $1`, [colis]);
  ok((await facture()).m === 50, ou + ' : sans prix saisi, la facture vaut poids × tarif + 10 $');
  await comme(db, 'admin');
  ok(await code(db, `update public.colis set prix_manuel = 25 where id = $1`, [colis]) === 'ok', ou + ' : l\'administrateur saisit un prix');
  await moi(db);
  let f = await facture();
  ok(f.m === 35 && f.lignes[0].montant === 25 && f.lignes[0].prix_manuel === true, ou + ' : la facture prend le prix saisi (25 + 10) ; la ligne le dit');
  ok((await un(db, `select prix_manuel::float p from public.colis_details where id = $1`, [colis])).p === 25, ou + ' : la vue du tableau de bord voit le prix saisi');
  await comme(db, 'agent');
  ok(await code(db, `update public.colis set prix_manuel = 1 where id = $1`, [colis]) === '42501', ou + ' : sans « colis.modifier », le prix ne se touche pas');
  await comme(db, 'client');
  ok(await code(db, `update public.colis set prix_manuel = 1 where id = $1`, [colis]) !== 'ok' ||
     (await un(db, `select prix_manuel::float p from public.colis where id = $1`, [colis])).p === 25, ou + ' : le client ne touche pas au prix de son colis');
  await comme(db, 'admin');
  await db.query(`update public.colis set prix_manuel = null where id = $1`, [colis]);
  await moi(db);
  f = await facture();
  ok(f.m === 50 && f.lignes[0].prix_manuel === false, ou + ' : prix effacé, retour à poids × tarif');
  await db.query(`update public.factures set montant_paye = 20 where colis_id = $1`, [colis]);
  await comme(db, 'admin');
  await db.query(`update public.colis set prix_manuel = 5 where id = $1`, [colis]);
  await moi(db);
  ok((await facture()).m === 50, ou + ' : une facture déjà réglée en partie ne bouge plus');
  const colisNeuf = (await un(db, `insert into public.colis (client_id, description, poids_lb, tarif_lb, prix_manuel) values ($1, 'forfait', 3, 4, 40) returning id`, [ID.client])).id;
  ok((await un(db, `select montant::float m from public.factures where colis_id = $1`, [colisNeuf])).m === 50, ou + ' : un prix saisi dès l\'enregistrement fait la facture (40 + 10)');
  ok(await code(db, `insert into public.colis (client_id, description, prix_manuel) values ($1, 'négatif', -1)`, [ID.client]) === '23514', ou + ' : un prix négatif est refusé');

  // ---------------------------------------------------------------- pré-alertes
  const pa = `insert into public.prealertes (client_id, magasin, contenu, numero_suivi, valeur, service) values ($1, $2, $3, $4, $5, $6) returning id, statut, numero_suivi`;
  await comme(db, 'client');
  const p1 = await un(db, pa, [ID.client, ' Amazon ', 'Chaussures', ' tba123 ', 45.5, 'aerien']);
  ok(p1.statut === 'attendue' && p1.numero_suivi === 'TBA123', ou + ' : le client crée sa pré-alerte (attendue, numéro en majuscules)');
  ok(await code(db, `insert into public.prealertes (client_id, magasin, contenu, statut) values ($1, 'X', 'Y', 'recue')`, [ID.client]) === '42501', ou + ' : le client ne choisit pas le statut');
  ok(await code(db, pa, [ID.autre, 'SHEIN', 'Robe', '', null, 'aerien']) === '42501', ou + ' : pas de pré-alerte au nom d\'un autre client');
  ok(await code(db, pa, [ID.client, '', 'Vide', '', null, 'aerien']) === '23514', ou + ' : magasin obligatoire');
  ok(await code(db, pa, [ID.client, 'Temu', 'Jouet', '', null, 'fusee']) === '23514', ou + ' : service inconnu refusé');
  ok(await code(db, `update public.prealertes set statut = 'annulee' where id = $1`, [p1.id]) === 'ok' &&
     (await un(db, `select statut from public.prealertes where id = $1`, [p1.id])).statut === 'attendue', ou + ' : le client ne traite pas sa pré-alerte');
  ok(await code(db, `delete from public.prealertes where id = $1`, [p1.id]) === '42501', ou + ' : le client ne la supprime pas');
  await comme(db, 'autre');
  ok((await un(db, `select count(*)::int k from public.prealertes`)).k === 0, ou + ' : un autre client ne voit rien');
  const p2 = await un(db, pa, [ID.autre, 'eBay', 'Montre', '1Z999', null, 'maritime']);
  await comme(db, 'anon');
  ok(await code(db, `select count(*) from public.prealertes`) === '42501', ou + ' : un visiteur est refusé');
  await comme(db, 'admin');
  ok(await code(db, pa, [ID.admin, 'Amazon', 'Équipe', '', null, 'aerien']) === '42501', ou + ' : l\'équipe ne crée pas de pré-alerte (elle n\'est pas cliente)');
  await comme(db, 'lecteur');
  ok((await un(db, `select count(*)::int k from public.prealertes`)).k === 2, ou + ' : « colis.lire » voit toutes les pré-alertes');
  await db.query(`update public.prealertes set statut = 'recue' where id = $1`, [p1.id]);
  ok((await un(db, `select statut from public.prealertes where id = $1`, [p1.id])).statut === 'attendue', ou + ' : sans « colis.statut », pas de traitement');
  await comme(db, 'agent');
  ok(await code(db, `update public.prealertes set statut = 'recue', colis_id = $2, note = 'Arrivé à Miami' where id = $1`, [p1.id, colis]) === 'ok', ou + ' : « colis.statut » marque reçue et relie le colis');
  ok(await code(db, `update public.prealertes set colis_id = $2 where id = $1`, [p2.id, colis]) === 'SE004', ou + ' : jamais le colis d\'un autre client');
  ok(await code(db, `update public.prealertes set magasin = 'Autre' where id = $1`, [p1.id]) === '42501', ou + ' : le contenu d\'une pré-alerte ne se réécrit pas');
  ok(await code(db, `update public.prealertes set statut = 'perdue' where id = $1`, [p2.id]) === '23514', ou + ' : statut inconnu refusé');
  await moi(db);
  await db.query(`update public.prealertes set magasin = magasin where false`);
  ok(await code(db, `update public.prealertes set magasin = 'Triche' where id = $1`, [p1.id]) === '42501', ou + ' : même le propriétaire de la base ne réécrit pas une pré-alerte');
  // 30 par 24 h et par client
  await comme(db, 'autre');
  for (let i = 0; i < 29; i++) await db.query(pa, [ID.autre, 'Amazon', 'Lot ' + i, '', null, 'aerien']);
  ok(await code(db, pa, [ID.autre, 'Amazon', 'Une de trop', '', null, 'aerien']) === 'SE003', ou + ' : la 31e pré-alerte en 24 h est refusée');
  await comme(db, 'client');
  ok(await code(db, pa, [ID.client, 'Amazon', 'Encore', '', null, 'aerien']) === 'ok', ou + ' : la limite est par client');
  await moi(db);
}

(async () => {
  const racine = process.env.SES_TEST_DEPS;
  assert.ok(racine, 'SES_TEST_DEPS doit pointer vers un dossier contenant node_modules/@electric-sql/pglite');
  const { PGlite } = await import(racine + '/node_modules/@electric-sql/pglite/dist/index.js');
  const lire = (f) => fs.readFileSync(f, 'utf8');
  const schema = lire('outils/supabase.sql'), maj = lire('outils/supabase-maj.sql'), dash = lire('outils/supabase-dashboard.sql');
  const numeros = lire('outils/supabase-maj-numeros.sql'), coller = lire('outils/supabase-maj-prix-prealertes.sql');

  // le fichier à coller porte exactement les fonctions et la vue du schéma et de la mise à jour générale
  const morceau = (s, debut, fin) => { const d = s.indexOf(debut); assert.ok(d >= 0, 'introuvable : ' + debut); return s.slice(d, s.indexOf(fin, d) + fin.length); };
  for (const nom of ['facturer_colis', 'verifier_modification_colis']) {
    const m = (s) => morceau(s, 'create or replace function public.' + nom + '()', '$$;');
    ok(m(coller) === m(schema) && m(coller) === m(maj), nom + ' : la même fonction dans les trois fichiers');
  }
  const vue = (s) => morceau(s, 'create view public.colis_details', 'cl.id = c.client_id;');
  ok(vue(coller) === vue(maj) && vue(maj) === vue(schema), 'colis_details : la même vue dans les trois fichiers');

  // Chemin 1 : la production — les fichiers d'avant ce changement, puis le collage (deux fois).
  const AVANT = 'cee8419';
  const avant = (f) => { try { return cp.execFileSync('git', ['show', AVANT + ':' + f], { encoding: 'utf8', maxBuffer: 1 << 24, stdio: ['ignore', 'pipe', 'ignore'] }); } catch { return null; } };
  const ancienSchema = avant('outils/supabase.sql'), ancienneMaj = avant('outils/supabase-maj.sql');
  if (ancienSchema && ancienneMaj) {
    const db = await monter(PGlite, [ancienSchema, dash, ancienneMaj, numeros, coller, coller]);
    await verifier(db, 'prod');
    await db.close();
  } else console.warn('ATTENTION : commit ' + AVANT + ' introuvable (clone superficiel ?) — chemin « production » non éprouvé.');

  // Chemin 2 : installation neuve, toutes les mises à jour, puis le collage rejoué.
  const db2 = await monter(PGlite, [schema, dash, maj, numeros, coller]);
  const def = async () => (await db2.query(`select md5(string_agg(pg_get_functiondef(p.oid), '' order by p.proname)) h from pg_proc p where p.proname in ('facturer_colis','verifier_modification_colis','preparer_prealerte')`)).rows[0].h;
  const avantRejeu = await def();
  await db2.exec(coller);
  ok(await def() === avantRejeu, 'neuf : rejouer le collage ne change rien');
  await verifier(db2, 'neuf');
  await db2.close();

  console.log('PASS prix saisi et pré-alertes : ' + n + ' vérifications — facture au prix saisi puis figée, droits sur le prix, pré-alertes du client seulement, traitement par l\'équipe, limite de 30 par 24 h, fichiers identiques et rejouables');
})().catch((e) => { console.error(e); process.exit(1); });
