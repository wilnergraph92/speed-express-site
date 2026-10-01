// Isolated PostgreSQL-WASM, empty schema contract only. Never production.
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const {PGlite}=await import(process.env.SES_TEST_DEPS+'/node_modules/@electric-sql/pglite/dist/index.js');
 const db=new PGlite();
 await db.exec(`create role anon; create role authenticated;
 create table clients(id uuid,role text,cree_le timestamptz);
 create table colis(id uuid,service text,statut text,cree_le timestamptz,pays_destination text,ville_destination text);
 create table factures(id uuid,devise text,montant numeric,montant_paye numeric);
 create function public.a_droit(text) returns boolean language sql as $$ select $1=any(string_to_array(current_setting('test.rights',true),',')) $$;
 alter table clients enable row level security; alter table colis enable row level security; alter table factures enable row level security;
 create policy lecture on clients for select to authenticated using (public.a_droit('clients.lire'));
 create policy lecture on colis for select to authenticated using (public.a_droit('colis.lire'));
 create policy lecture on factures for select to authenticated using (public.a_droit('factures.lire'));
 grant usage on schema public to authenticated,anon; grant select on clients,colis,factures to authenticated;`);
 const sql=fs.readFileSync('outils/supabase-dashboard.sql','utf8'); await db.exec(sql); await db.exec(sql);
 await db.exec(`set role authenticated; set test.rights='colis.lire';`);
 let r=(await db.query(`select public.dashboard_colis_ses('jour','2026-09-01') d`)).rows[0].d;
 assert.equal(r.stock.total,0);assert.equal(r.total,0);assert.equal(r.serie.length,24);
 assert.equal(r.periode.debut,'2026-09-01T04:00:00+00:00');
 for(const [type,date,begin,end] of [['semaine','2026-09-02','2026-08-31T04:00:00+00:00','2026-09-07T04:00:00+00:00'],['mois','2026-02-15','2026-02-01T04:00:00+00:00','2026-03-01T04:00:00+00:00'],['annee','2025-02-02','2025-01-01T04:00:00+00:00','2026-01-01T04:00:00+00:00'],['jour','2024-02-29','2024-02-29T04:00:00+00:00','2024-03-01T04:00:00+00:00']]){
  const f=(await db.query('select public.dashboard_periode_ses($1,$2) f',[type,date])).rows[0].f; assert.equal(f.debut,begin);assert.equal(f.fin,end);
 }
 for(const type of ['heures','personnalise']) {const f=(await db.query(`select public.dashboard_periode_ses($1,null,'2026-09-01 08:00','2026-09-01 18:00') f`,[type])).rows[0].f;assert.equal(f.debut,'2026-09-01T12:00:00+00:00');assert.equal(f.fin,'2026-09-01T22:00:00+00:00');}
 for(const q of [`select public.dashboard_clients_ses('jour','2026-09-01')`,`select public.dashboard_colis_ses('bad')`,`select public.dashboard_colis_ses('jour','2026-09-01',null,null,'bad')`,`select public.dashboard_periode_ses('personnalise',null,'2026-09-02','2026-09-01')`]) await assert.rejects(db.query(q));
 r=(await db.query('select public.statistiques_ses() d')).rows[0].d; assert.equal(r.clients,null);assert.equal(r.soldes_par_devise,null);
 await db.exec(`set test.rights='clients.lire';`); await assert.rejects(db.query(`select public.dashboard_colis_ses()`));
 r=(await db.query(`select public.dashboard_clients_ses('mois','2026-09-01') d`)).rows[0].d;assert.equal(r.total,0);
 await db.exec(`set test.rights='';`);await assert.rejects(db.query(`select public.dashboard_clients_ses()`));
 await db.exec('reset role;set role anon;');await assert.rejects(db.query(`select public.dashboard_colis_ses()`));
 await db.exec('reset role;');const funcs=(await db.query(`select proname,prosecdef from pg_proc where proname like 'dashboard_%_ses' or proname='statistiques_ses'`)).rows;assert.equal(funcs.length,4);assert.ok(funcs.every(f=>!f.prosecdef));
 await db.close();console.log('PASS SQL: migration twice, empty aggregates, 6 periods, leap day, invalid ranges/filters, domain gates, anon rejection, invoker catalog');
})().catch(e=>{console.error(e);process.exit(1)});
