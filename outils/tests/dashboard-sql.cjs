// Isolated PostgreSQL-WASM, empty schema contract only. Never production.
// Le test compare des horodatages sérialisés dans le fuseau de la machine : sans cette ligne il échouait
// sur un poste réglé en heure locale et réussissait en UTC (CI). Le produit, lui, sérialise en UTC.
process.env.TZ = 'UTC';
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
 const ancien=require('node:child_process').execFileSync('git',['show','5922510:outils/supabase-dashboard.sql'],{encoding:'utf8'});
 await db.exec(ancien);   // la production : l'ancienne version, à sept paramètres
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
 // le filtre « Destination » (la ville) : insensible à la casse et aux espaces, compté aussi dans la période précédente
 await db.exec(`reset role; insert into colis (id,service,statut,cree_le,pays_destination,ville_destination) values
   (gen_random_uuid(),'aerien','confirme',now()-interval '1 hour','HT','Port-au-Prince'),(gen_random_uuid(),'aerien','confirme',now()-interval '2 hour','HT',' port-au-prince '),
   (gen_random_uuid(),'maritime','livre',now()-interval '3 hour','HT','Jacmel'),(gen_random_uuid(),'aerien','confirme',now()-interval '4 hour','DO','Santo Domingo Este');
   set role authenticated; set test.rights='colis.lire';`);
 const auj=(await db.query(`select (now() at time zone 'America/Santo_Domingo')::date::text d`)).rows[0].d, hier=new Date(Date.parse(auj)-864e5).toISOString().slice(0,10), dem=new Date(Date.parse(auj)+864e5).toISOString().slice(0,10);
 const vue=async(...a)=>(await db.query(`select public.dashboard_colis_ses('personnalise',null,$1,$2,$3,$4,null,$5) d`,[hier+' 00:00',dem+' 00:00',...a])).rows[0].d;
 assert.equal((await vue(null,null,null)).total,4);
 assert.equal((await vue(null,'HT','Port-au-Prince')).total,2);
 assert.equal((await vue('maritime','HT',null)).total,1);
 assert.equal((await vue(null,null,'jacmel')).filtres.ville,'jacmel');
 assert.equal((await vue(null,null,'Inconnue')).total,0);
 await assert.rejects(db.query(`select public.dashboard_colis_ses('mois',null,null,null,null,null,null,'')`));
 await assert.rejects(db.query(`select public.dashboard_colis_ses('mois',null,null,null,null,null,null,$1)`,['x'.repeat(81)]));
 assert.equal((await db.query(`select public.dashboard_colis_ses('mois') d`)).rows[0].d.filtres.ville,null);
 await db.exec('reset role;');const funcs=(await db.query(`select proname,prosecdef from pg_proc where proname like 'dashboard_%_ses' or proname='statistiques_ses'`)).rows;assert.equal(funcs.length,4);assert.ok(funcs.every(f=>!f.prosecdef));
 await db.close();console.log('PASS SQL: migration twice, empty aggregates, 6 periods, leap day, invalid ranges/filters, destination city filter, domain gates, anon rejection, invoker catalog, single signature');
})().catch(e=>{console.error(e);process.exit(1)});
