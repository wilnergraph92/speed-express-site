// Browser tests with empty/error responses only, isolated from Supabase.
import fs from 'node:fs';
import assert from 'node:assert/strict';
const root=process.env.SES_TEST_DEPS;
const {default:chromium}=await import(root+'/node_modules/@sparticuz/chromium/build/index.js');
const {chromium:pw}=await import(root+'/node_modules/playwright/index.mjs');
const browser=await pw.launch({executablePath:await chromium.executablePath(),args:chromium.args,headless:true});
const context=await browser.newContext({timezoneId:'Asia/Tokyo'});
let testRights=['colis.lire','clients.lire','factures.lire'];
const p=await context.newPage(),errors=[];
p.on('pageerror',e=>errors.push(e.message));
await context.route('**/*',async route=>{
 const u=new URL(route.request().url());
 if(u.hostname!=='localhost') return route.abort();
 if(u.pathname.endsWith('/config.js')) return route.fulfill({contentType:'application/javascript',body:'window.SES_CONFIG={};'});
 if(u.pathname.endsWith('/ses-api.js')) {
 const original=fs.readFileSync('assets/js/ses-api.js','utf8');
 return route.fulfill({contentType:'application/javascript',body:original+`
 SES_API.mode='supabase'; // mode du double de test, jamais une configuration réelle
 window.__calls=[]; window.__rights=${JSON.stringify(testRights)};
 var profile={role:'employe',droits:window.__rights,nom_complet:'',email:''};
 SES_API.profil=()=>Promise.resolve(profile); SES_API.exigerProfil=SES_API.profil;
 SES_API.surveiller=()=>()=>{};
 SES_API.admin.baseAJour=()=>Promise.resolve(true);
 SES_API.admin.colis=SES_API.admin.factures=SES_API.admin.clients=()=>Promise.resolve({lignes:[],total:0});
 SES_API.admin.resumeClients=()=>Promise.resolve({});
 SES_API.admin.dashboard=(domain,f)=>{
  window.__calls.push({domain,f});
  if(window.__error) return Promise.reject({code:window.__error});
  var period={debut:'2026-09-01T04:00:00Z',fin_effective:'2026-09-02T04:00:00Z',reference:'2026-09-02T04:00:00Z',precedent_debut:'2026-08-31T04:00:00Z',precedent_fin:'2026-09-01T04:00:00Z'};
  return Promise.resolve({version:1,periode:period,total:0,precedent:0,stock:{total:0,services:{},statuts:{}},serie:[],destinations:[],destinations_nombre:0});
 };
 SES_API.admin.dashboardRecents=()=>Promise.resolve({lignes:[],total:0});
 SES_API.admin.dashboardActivite=()=>Promise.resolve([]);
 `});
 }
 return route.continue();
});
await p.goto('http://localhost:8000/tableau-de-bord.html');
await p.waitForSelector('.dash-kpi');
assert.equal(await p.locator('.dash-kpi').count(),4);
for(const width of [320,360,390,414,768,1024,1280,1440]) {
 await p.setViewportSize({width,height:1000});
 await p.waitForTimeout(100);
 const dims=await p.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));
 assert.ok(dims.scroll<=dims.width,`Overflow ${width}: ${JSON.stringify(dims)}`);
 console.log('PASS viewport',width);
}
await p.setViewportSize({width:390,height:844});
await p.locator('#dash-menu').click();assert.equal(await p.locator('#dash-menu').getAttribute('aria-expanded'),'true');
await p.keyboard.press('Escape');assert.equal(await p.locator('#dash-menu').getAttribute('aria-expanded'),'false');
assert.equal(await p.locator('#dash-menu').evaluate(el=>el===document.activeElement),true);
await p.setViewportSize({width:1440,height:1000});
for(const period of ['jour','semaine','mois','annee','heures','personnalise']) {
 await p.locator('[name=periode]').selectOption(period);
 if(['heures','personnalise'].includes(period)) {await p.locator('[name=debut]').fill('2026-09-01T08:00');await p.locator('[name=fin]').fill('2026-09-01T18:00');}
 await p.locator('#dash-filtres button[type=submit]').click();
 await p.waitForTimeout(50);
 assert.equal(await p.evaluate(()=>__calls.at(-1).f.periode),period);
}
// Check each preserved management panel at all required widths (empty source responses).
for (const width of [320,360,390,414,768,1024,1280,1440]) {
 await p.setViewportSize({width,height:1000});
 for (const tab of ['colis','factures','clients','reglages','dashboard']) {
  await p.evaluate(tab=>document.getElementById('ses-o-'+tab).click(),tab);
  assert.ok(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Panel overflow ${width} ${tab}`);
 }
}
await p.setViewportSize({width:1440,height:1000});
await p.evaluate(()=>window.__error='base-a-mettre-a-jour');await p.locator('#dash-refresh').click();await p.waitForTimeout(80);
assert.match(await p.locator('#ses-chiffres').innerText(),/migration/);assert.equal(await p.locator('.dash-kpi').count(),0);
await p.evaluate(()=>window.__error='reseau');await p.locator('#ses-chiffres [data-dash-retry]').click();await p.waitForTimeout(80);assert.match(await p.locator('#ses-chiffres').innerText(),/connexion/);
await p.locator('#ses-o-colis').click();assert.equal(await p.locator('#ses-p-colis').isVisible(),true);
await p.locator('#ses-o-dashboard').click();assert.equal(await p.locator('#ses-p-dashboard').isVisible(),true);
await p.goBack();assert.equal(await p.locator('#ses-p-colis').isVisible(),true);
await p.goForward();assert.equal(await p.locator('#ses-p-dashboard').isVisible(),true);
// A billing-only employee must never request shipment/customer aggregates.
testRights=['factures.lire'];await p.reload();await p.waitForSelector('#ses-identite');await p.waitForTimeout(150);
assert.equal(await p.locator('#ses-o-colis').isVisible(),false);
assert.equal(await p.locator('#ses-o-clients').isVisible(),false);
assert.equal(await p.evaluate(()=>__calls.length),0);
assert.equal(await p.locator('[data-domain=factures]').isVisible(),true);
await p.locator('#ses-o-factures').click();assert.equal(await p.locator('#ses-p-factures').isVisible(),true);
testRights=['colis.lire'];await p.goto('http://localhost:8000/tableau-de-bord.html?permission=colis#dashboard');await p.waitForSelector('.dash-kpi');
assert.equal(await p.locator('[data-domain=clients]').isVisible(),false);
assert.equal(await p.locator('[data-domain=factures]').isVisible(),false);
assert.ok(await p.evaluate(()=>__calls.every(c=>c.domain==='colis')));
await p.evaluate(()=>SES_API.mode='demo');await p.locator('#dash-refresh').click();await p.waitForTimeout(50);
assert.match(await p.locator('#ses-chiffres').innerText(),/Base réelle requise/);
assert.equal(await p.locator('.dash-kpi').count(),0);
assert.deepEqual(errors,[]);
if(process.env.SES_SCREENSHOT) await p.screenshot({path:process.env.SES_SCREENSHOT,fullPage:true});
console.log('PASS browser: empty/error/migration, six filter submissions, navigation, mobile drawer, no JS exceptions (isolated, not real data)');
await browser.close();
