// In-memory query contract tests: no credentials, network, records or writes.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const calls=[];
let response={data:[],count:0,error:null};
const query=new Proxy({}, {get(_,method){if(method==='then')return (yes,no)=>Promise.resolve(response).then(yes,no);return (...args)=>{calls.push([method,...args]);return query;};}});
const client={from:t=>{calls.push(['from',t]);return query;},rpc:(...args)=>{calls.push(['rpc',...args]);return Promise.resolve(response);}};
const sandbox={window:{addEventListener:()=>{},SES_CONFIG:{supabaseUrl:'https://example.invalid',supabaseKey:'public-test-placeholder'},supabase:{createClient:()=>client}},location:{hostname:'example.invalid',protocol:'https:',href:'https://example.invalid/tableau-de-bord.html'},document:{documentElement:{lang:'fr'}},console,Promise,URL,setTimeout,clearTimeout};
vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js','utf8'),sandbox);
const api=sandbox.window.SES_API;
(async()=>{
 const empty=await api.admin.dashboardRecents({page:2,tri:'DROP TABLE',asc:true,statut:'action',recherche:'abc,()%'});
 assert.equal(empty.total,0);assert.equal(empty.lignes.length,0);
 assert.ok(calls.some(c=>c[0]==='range'&&c[1]===40&&c[2]===59));
 assert.ok(calls.some(c=>c[0]==='order'&&c[1]==='cree_le'));
 assert.ok(calls.some(c=>c[0]==='order'&&c[1]==='id'));
 assert.ok(calls.some(c=>c[0]==='eq'&&c[1]==='statut'&&c[2]==='action'));
 assert.ok(!calls.some(c=>c[0]==='select'&&c[1].includes('*')));
 calls.length=0;await api.admin.factures({colis_id:'id-technique'});assert.ok(calls.some(c=>c[0]==='eq'&&c[1]==='colis_id'));
 calls.length=0;await api.admin.colis({colis_id:'invalid-view-column'});assert.ok(!calls.some(c=>c[0]==='eq'&&c[1]==='colis_id'));
 calls.length=0;await api.admin.dashboard('colis',{periode:'heures',debut:'2026-09-01T08:00',fin:'2026-09-01T18:00',service:'aerien',pays:'DO',statut:'action'});
 assert.equal(calls[0][1],'dashboard_colis_ses');assert.equal(calls[0][2].p_service,'aerien');assert.equal(calls[0][2].p_debut,'2026-09-01T08:00');
 calls.length=0;await api.admin.dashboard('clients',{service:'aerien',periode:'annee'});assert.equal(calls[0][2].p_service,undefined);
 await assert.rejects(api.admin.dashboard('factures',{}));
 response={error:{code:'PGRST202',message:'missing function'}};await assert.rejects(api.admin.dashboard('colis',{}),e=>e.code==='base-a-mettre-a-jour');
 response={error:{code:'42501'}};await assert.rejects(api.admin.dashboardRecents({}),e=>e.code==='non-autorise');
 console.log('PASS API: projections, pagination, stable allowlisted sort, source filters, invoice fix, domain contract, missing migration and permissions');
})().catch(e=>{console.error(e);process.exit(1);});
