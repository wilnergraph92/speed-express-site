// No business mock data. Static public pages only. External requests blocked.
import fs from 'node:fs';import path from 'node:path';import http from 'node:http';import assert from 'node:assert/strict';
const deps=process.env.SES_TEST_DEPS;
const {default:chromium}=await import(deps+'/node_modules/@sparticuz/chromium/build/index.js');
const {chromium:pw}=await import(deps+'/node_modules/playwright/index.mjs');
const root=process.cwd();
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');if(url.pathname.endsWith('/config.js')){res.setHeader('Content-Type','application/javascript');res.end('window.SES_CONFIG={};');return;}const base=url.pathname.startsWith('/before/')?process.env.SES_PERF_BASELINE:root;
 const rel=url.pathname.replace(/^\/(before\/)?/,'')||'index.html';const file=path.resolve(base,rel);
 if(!file.startsWith(base+'/')||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
 res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':file.endsWith('.html')?'text/html':file.endsWith('.webp')?'image/webp':file.endsWith('.png')?'image/png':file.endsWith('.jpg')?'image/jpeg':'application/octet-stream');
 const body=fs.readFileSync(file);res.setHeader('Content-Length',body.length);res.end(body);
});await new Promise(r=>server.listen(8124,'0.0.0.0',r));
const browser=await pw.launch({executablePath:await chromium.executablePath(),args:chromium.args.filter(a=>a!=='--single-process'),headless:true});
async function context(lang='fr',viewport={width:390,height:844},dpr=2){
 const c=await browser.newContext({viewport,deviceScaleFactor:dpr,reducedMotion:'reduce'});
 await c.addInitScript(lang=>{try { localStorage.setItem('ses-lang',lang); } catch {} window.__walkers=0;const old=document.createTreeWalker.bind(document);document.createTreeWalker=function(...args){window.__walkers++;return old(...args);};window.__lcp=null;new PerformanceObserver(list=>{const l=list.getEntries().at(-1);window.__lcp={url:l.url,tag:l.element?.tagName};}).observe({type:'largest-contentful-paint',buffered:true});},lang);
 await c.route('**/*',r=>{const u=new URL(r.request().url());if(u.hostname!=='localhost')return r.abort();if(u.pathname.endsWith('/config.js'))return r.fulfill({contentType:'application/javascript',body:'window.SES_CONFIG={};'});return r.continue();});return c;
}
const measurements={};
if(process.env.SES_PERF_BASELINE){
 for(const version of ['before','after']){
 const c=await context();const p=await c.newPage();await p.goto('http://localhost:8124/'+(version==='before'?'before/':'')+'index.html');await p.waitForTimeout(1800);
 measurements[version]=await p.evaluate(()=>{const entries=performance.getEntriesByType('resource').filter(r=>new URL(r.name).hostname==='localhost');return {requested_local_files:entries.map(r=>new URL(r.name).pathname),requests:entries.length,dicts:entries.filter(r=>r.name.includes('lang-dict')).map(r=>({url:r.name.split('/').pop()})),images:entries.filter(r=>r.initiatorType==='img'||r.initiatorType==='link'&&/\.webp|\.jpg/.test(r.name)).map(r=>({url:r.name.split('/').pop()})),layout:Object.fromEntries(['header','.hero','.hero__fond','.why__media'].map(s=>{const r=document.querySelector(s).getBoundingClientRect();return [s,{x:r.x,y:r.y,width:r.width,height:r.height}];})),lcp:window.__lcp,walkers:window.__walkers};});
 measurements[version].requested_file_bytes=measurements[version].requested_local_files.reduce((sum,url)=>{const file=path.join(version==='before'?process.env.SES_PERF_BASELINE:root,url.replace(/^\/(before\/)?/,''));return sum+(fs.existsSync(file)?fs.statSync(file).size:0);},0);await c.close();
 }
}
if(measurements.before) assert.deepEqual(measurements.after.layout,measurements.before.layout,'Mobile geometry unchanged');
const c=await context();const p=await c.newPage();const errors=[];p.on('pageerror',e=>errors.push(e.message));
await p.goto('http://localhost:8124/index.html');await p.waitForTimeout(300);
assert.equal(await p.evaluate(()=>__walkers),0,'French should not walk translation tree');
assert.equal(await p.locator('script[src*=lang-dict]').count(),0);
assert.equal(await p.locator('script[src*=ses-anim]').count(),1);
const source=await p.locator('.hero__fond.est-active').evaluate(el=>el.currentSrc);assert.match(source,/ses-truck-800.webp/);
// Explicit choices preserve all three translations and restore source French.
for(const [lang,label] of [['en','Home'],['es','Inicio'],['ht','Akèy'],['fr','Accueil']]){
 await p.locator('lang-switcher').evaluate((el,lang)=>el.pick(lang),lang);
 await p.waitForFunction(lang=>document.documentElement.lang===lang,lang);
 await p.waitForTimeout(160);assert.ok((await p.locator('header').textContent()).includes(label),lang+': '+await p.locator('header').textContent());
}
assert.equal(await p.locator('script[src*=lang-dict]').count(),3);
// Dynamic content: only added subtree visited, and attributes translated too.
await p.locator('lang-switcher').evaluate(el=>el.pick('en'));await p.waitForTimeout(200);
let w=await p.evaluate(()=>__walkers);
await p.evaluate(()=>{const n=document.createElement('div');n.id='dynamic-test';n.innerHTML='<span>Accueil</span><input placeholder="Accueil">';document.body.appendChild(n);});
await p.waitForTimeout(220);assert.equal(await p.locator('#dynamic-test span').innerText(),'Home');assert.equal(await p.locator('#dynamic-test input').getAttribute('placeholder'),'Home');
assert.equal((await p.evaluate(()=>__walkers))-w,1);
await p.evaluate(()=>document.querySelector('#dynamic-test span').firstChild.nodeValue='Blog');await p.waitForTimeout(200);assert.equal(await p.locator('#dynamic-test span').innerText(),'Blog');
await p.evaluate(()=>document.querySelector('#dynamic-test span').firstChild.nodeValue='Accueil');await p.waitForTimeout(200);
await p.locator('lang-switcher').evaluate(el=>el.pick('fr'));assert.equal(await p.locator('#dynamic-test span').innerText(),'Accueil');
await p.evaluate(()=>document.querySelector('#dynamic-test span').firstChild.nodeValue='Blog');await p.waitForTimeout(180);
await p.locator('lang-switcher').evaluate(el=>el.pick('es'));assert.equal(await p.locator('#dynamic-test span').innerText(),'Blog');
await p.locator('lang-switcher').evaluate(el=>el.pick('fr'));
// The camion artwork IS visible in today's mobile design and must remain visible.
await p.locator('.why__media').scrollIntoViewIfNeeded();await p.waitForTimeout(200);
const camion=await p.locator('.why__media img').evaluate(el=>({src:el.currentSrc,width:el.naturalWidth,display:getComputedStyle(el).display}));assert.ok(camion.width>0);assert.notEqual(camion.display,'none');assert.match(camion.src,/ses-camion-colis-(640|800).webp/);
// Fallback on an external image must use local file once, not an error loop.
await p.locator('[data-fallback]').first().scrollIntoViewIfNeeded();await p.waitForTimeout(300);
assert.equal(await p.locator('[data-fallback]').first().getAttribute('data-ses-fallback-applique'),'1');
assert.ok(await p.locator('[data-fallback]').first().evaluate(el=>el.naturalWidth>0));
// Carousel still shows the same image nodes; second image loads & decodes.
await p.locator('[data-aller="1"]').click();assert.equal(await p.locator('.hero__fond.est-active').getAttribute('src'),'assets/img/hero-avion.jpg');
assert.ok(await p.locator('.hero__fond.est-active').evaluate(el=>el.complete&&el.naturalWidth>0));
assert.deepEqual(errors,[]);await c.close();
// All public pages: exactly one animation, no thumbnail, no French page parts.
for(const file of fs.readdirSync(root).filter(f=>f.endsWith('.html')&&!['espace-client.html','tableau-de-bord.html','connexion.html','nouveau-mot-de-passe.html'].includes(f))){
 const cx=await context();const page=await cx.newPage();await page.goto('http://localhost:8124/'+file);await page.waitForTimeout(60);
 assert.equal(await page.locator('script[src*=ses-anim]').count(),1,file);assert.equal(await page.locator('script[src*=lang-dict]').count(),0,file);
 assert.equal(await page.locator('#__bundler_thumbnail').count(),0,file);await cx.close();
}
// Direct initial non-French load and template translations (account form).
for(const lang of ['en','es','ht']){
 const cx=await context(lang);const page=await cx.newPage();await page.goto('http://localhost:8124/creer-un-compte.html');await page.waitForFunction(lang=>document.documentElement.lang===lang,lang);
 assert.ok(await page.locator('script[src*=lang-dict-11]').count());
 const expected={en:'Home',es:'Inicio',ht:'Akèy'};
 assert.ok((await page.locator('header').textContent()).includes(expected[lang]));
 const translated=await page.locator('template[data-textes]').evaluate(el=>Array.from(el.content.querySelectorAll('[data-t]')).map(s=>s.textContent));
 await page.locator('lang-switcher').evaluate(el=>el.pick('fr'));
 const french=await page.locator('template[data-textes]').evaluate(el=>Array.from(el.content.querySelectorAll('[data-t]')).map(s=>s.textContent));
 assert.ok(translated.some((s,i)=>s!==french[i]),'template must actually translate '+lang);
 await page.locator('lang-switcher').evaluate(el=>el.pick('fr'));assert.equal(await page.evaluate(()=>document.documentElement.lang),'fr');await cx.close();
}
for(const width of [320,360,390,414,768,1024,1280,1440]) {
 const cx=await context('fr',{width,height:900},1);const page=await cx.newPage();await page.goto('http://localhost:8124/index.html');
 await page.waitForTimeout(100);
 assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'overflow '+width);
 for(const image of await page.locator('.hero__fond').all()) assert.ok(await image.evaluate(el=>el.complete&&el.naturalWidth>0),'hero decode '+width);
 await cx.close();
}
// First load failure retries only the missing page dictionary, not successful ones.
{
 const cx=await context();let fail=true;let requests=0;
 await cx.route('**/lang-dict-3.js*',async r=>{requests++;if(fail){fail=false;await r.abort();}else await r.continue();});
 const page=await cx.newPage();await page.goto('http://localhost:8124/index.html');
 await page.locator('lang-switcher').evaluate(el=>el.pick('en'));await page.waitForTimeout(180);
 await page.locator('lang-switcher').evaluate(el=>el.pick('en'));await page.waitForFunction(()=>document.documentElement.lang==='en');
 assert.equal(requests,2);assert.equal(await page.locator('script[src*=lang-dict-2]').count(),1);await cx.close();
}
// Legacy decorative hero fixture follows the generator media contract.
{
 const cx=await context();const page=await cx.newPage();const requests=[];
 page.on('request',r=>requests.push(r.url()));
 await page.goto('http://localhost:8124/404.html');
 await page.setContent('<style>@media(max-width:899px){.legacy{display:none}}</style><div class="legacy"><picture><source media="(min-width:900px)" type="image/webp" srcset="http://localhost:8124/assets/img/ses-camion-colis-640.webp"><img src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" alt=""></picture></div>');
 await page.waitForTimeout(100);assert.ok(!requests.some(u=>u.includes('ses-camion-colis')));
 await page.setViewportSize({width:1280,height:900});await page.waitForTimeout(200);
 assert.ok(requests.some(u=>u.includes('ses-camion-colis-640.webp')));await cx.close();
}
await browser.close();await new Promise(r=>server.close(r));
if(process.env.SES_PERF_METRICS) fs.writeFileSync(process.env.SES_PERF_METRICS,JSON.stringify(measurements,null,2));
console.log('PASS performance browser: French zero extra dictionaries/walkers; FR/EN/ES/HT switch & restore; dynamic subtree; images, carousel & CDN fallback; all public pages.');console.log(JSON.stringify(measurements,null,2));
