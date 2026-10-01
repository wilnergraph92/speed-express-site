/* Phase 6 — navigateur réel, clavier et axe-core.
   Dépendances hors dépôt via SES_TEST_DEPS (playwright, @sparticuz/chromium,
   axe-core). Aucun appel Supabase, WhatsApp ou service d'envoi : toutes les
   données ci-dessous sont des fixtures synthétiques réservées aux tests. */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
const deps = process.env.SES_TEST_DEPS;
assert.ok(deps, 'Définir SES_TEST_DEPS, chemin du dossier de dépendances hors dépôt');
const {default:chromium} = await import(deps + '/node_modules/@sparticuz/chromium/build/index.js');
const {chromium:pw} = await import(deps + '/node_modules/playwright/index.mjs');
const racine = process.cwd();
const axe = fs.readFileSync(deps + '/node_modules/axe-core/axe.min.js', 'utf8');
const bilan = {date:'2026-10-01',succes:false, axe:[], clavier:[], erreursJavascript:[]};
const serveur = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  if (url.pathname.endsWith('/config.js')) {
    res.setHeader('Content-Type','application/javascript');res.end('window.SES_CONFIG={};');return;
  }
  const fichier = path.resolve(racine, '.' + url.pathname);
  if (!fichier.startsWith(racine + '/') || !fs.existsSync(fichier) || !fs.statSync(fichier).isFile()) {
    res.writeHead(404); res.end(); return;
  }
  const types = {'.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.png':'image/png', '.jpg':'image/jpeg', '.webp':'image/webp'};
  res.setHeader('Content-Type', types[path.extname(fichier)] || 'application/octet-stream');
  res.end(fs.readFileSync(fichier));
});
await new Promise(r => serveur.listen(8127, '0.0.0.0', r));
const navigateur = await pw.launch({executablePath:await chromium.executablePath(), args:chromium.args.filter(a => a !== '--single-process'), headless:true});
bilan.navigateur = navigateur.version();
const fixture = `
(function () {
 var clients = [1,2,3].map(function (n) {return {id:'client-test-'+n,code:'SES-TEST-'+n,nom_complet:'Client de test '+n,email:'test'+n+'@example.invalid',role:'client',pays:'Haïti',cree_le:'2026-09-01',telephone:'+1 555 0100'};});
 var profil = Object.assign({},clients[0],{role:location.pathname.indexOf('espace-client')>=0?'client':'admin'});
 if (window.__droitsTest) {profil.role='employe';profil.droits=window.__droitsTest;}
 var colis = SES_API.STATUTS.map(function (s,n) {return {id:'colis-test-'+n,client_id:clients[0].id,numero:'SES-TEST-100'+n,code_client:clients[0].code,description:'Colis de test',statut:s,service:'aerien',pays_destination:'HT',ville_destination:'Port-au-Prince',destinataire:'Destinataire de test',poids_lb:2,tarif_lb:5,prix_total:10,cree_le:'2026-09-01',maj_le:'2026-09-02',historique:[{statut:s,lieu:'Entrepôt de test',cree_le:'2026-09-02'}]};});
 var factures = ['payee','impayee'].map(function (s,n) {return {id:'facture-test-'+n,client_id:clients[0].id,numero:'F-TEST-'+n,code_client:clients[0].code,statut:s,montant:10,montant_paye:s==='payee'?10:0,devise:'USD',cree_le:'2026-09-01',lignes:[{libelle:'Prestation de test',montant:10}]};});
 window.__completionDebut=0; window.__completionFin=0; window.__envois=0;
 SES_API.mode='supabase'; SES_API.exigerProfil=function(){return Promise.resolve(profil);}; SES_API.profil=function(){return Promise.resolve(/(?:connexion|creer-un-compte)\.html$/.test(location.pathname)?null:profil);}; SES_API.surveiller=function(){return function(){};};
 SES_API.mesColis=function(){return Promise.resolve(window.__vide?[]:colis);}; SES_API.mesFactures=function(){return Promise.resolve(window.__vide?[]:factures);};
 SES_API.attendreRecuperation=function(){return Promise.resolve(true);};
 SES_API.suivre=function(ref){return ref==='ERREUR'?Promise.reject({code:'reseau'}):Promise.resolve(ref==='SES-TEST'?colis[0]:null);};
 ['connecter','inscrire','envoyerLienMotDePasse','changerMotDePasse','modifierProfil'].forEach(function(n){SES_API[n]=function(){window.__envois++;return Promise.reject({code:'reseau'});};});
 SES_API.admin.baseAJour=function(){return Promise.resolve(true);};
 SES_API.admin.colis=function(){return Promise.resolve({lignes:window.__vide?[]:colis,total:window.__vide?0:colis.length});};
 SES_API.admin.factures=function(){return Promise.resolve({lignes:window.__vide?[]:factures,total:window.__vide?0:factures.length});};
 SES_API.admin.clients=function(f){
   if(!f.recherche) return Promise.resolve({lignes:window.__vide?[]:clients,total:window.__vide?0:clients.length});
   window.__completionDebut++;
   return new Promise(function(resolve,reject){setTimeout(function(){window.__completionFin++;if(f.recherche==='ERR')return reject({code:'reseau'});resolve({lignes:f.recherche==='ZZ'?[]:clients,total:f.recherche==='ZZ'?0:clients.length});},window.__retardCompletion||0);});
 };
 SES_API.admin.resumeClients=function(){return Promise.resolve({});};
 SES_API.admin.colisParId=function(id){return Promise.resolve(colis.filter(function(c){return c.id===id;})[0]);};
 SES_API.admin.historique=function(){return Promise.resolve(colis[0].historique);};
 ['creerColis','modifierColis','creerFacture','modifierFacture','changerStatut','definirRole','supprimerColis','supprimerFacture'].forEach(function(n){SES_API.admin[n]=function(){window.__envois++;return Promise.reject({code:'reseau'});};});
 SES_API.admin.dashboard=function(){return Promise.resolve({version:1,periode:{debut:'2026-09-01T04:00:00Z',fin_effective:'2026-09-02T04:00:00Z',reference:'2026-09-02T04:00:00Z',precedent_debut:'2026-08-31T04:00:00Z',precedent_fin:'2026-09-01T04:00:00Z'},total:window.__vide?0:5,precedent:2,stock:{total:window.__vide?0:5,services:{aerien:2,maritime:2,terrestre:1},statuts:{confirme:1,expedie:1,disponible:1,livre:1,action:1}},serie:window.__vide?[]:[{date:'2026-09-01T04:00:00Z',n:2},{date:'2026-09-02T04:00:00Z',n:3}],destinations:window.__vide?[]:[{pays:'HT',ville:'Port-au-Prince',n:3},{pays:'DO',ville:'Santo Domingo',n:2}],destinations_nombre:2});};
 SES_API.admin.dashboardRecents=function(){return Promise.resolve({lignes:window.__vide?[]:colis,total:window.__vide?0:colis.length});}; SES_API.admin.dashboardActivite=function(){return Promise.resolve(window.__vide?[]:[{colis:{numero:colis[0].numero},statut:'confirme',lieu:'Entrepôt de test',auteur:'Équipe de test',cree_le:'2026-09-01'}]);};
})();`;

async function contexte(largeur=1440, reglages={}) {
  const c = await navigateur.newContext({viewport:{width:largeur,height:1000}, locale:'fr-FR', reducedMotion:'reduce', ...reglages});
  await c.addInitScript(() => {localStorage.clear();localStorage.setItem('ses-lang','fr');});
  await c.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname !== 'localhost') return route.abort();
    if (u.pathname.endsWith('/config.js')) return route.fulfill({contentType:'application/javascript',body:'window.SES_CONFIG={};'});
    if (u.pathname.endsWith('/ses-api.js')) return route.fulfill({contentType:'application/javascript',body:fs.readFileSync('assets/js/ses-api.js','utf8') + fixture});
    return route.continue();
  });
  return c;
}
async function pageDe(c) {
  const p = await c.newPage();
  p.on('pageerror', e => bilan.erreursJavascript.push(e.message));
  return p;
}
async function aller(p, nom) {
  await p.goto('http://localhost:8127/' + nom);
  await p.waitForFunction(() => window.SES_A11Y && customElements.get('lang-switcher'));
  assert.equal(new URL(p.url()).pathname,'/'+nom,'La page auditée ne doit pas être redirigée');
  if (nom === 'tableau-de-bord.html') await p.waitForSelector('.dash-kpi');
  if (nom === 'espace-client.html') await p.waitForFunction(() => document.getElementById('ses-bonjour').textContent.indexOf('Client de test') >= 0);
}
async function verifierAxe(p, nom) {
  if (!await p.evaluate(() => !!window.axe)) await p.addScriptTag({content:axe});
  const resultat = await p.evaluate(() => window.axe.run(document, {
    runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa','best-practice']}
  }));
  const resume = {etat:nom, violations:resultat.violations.map(v => ({id:v.id,noeuds:v.nodes.map(n => ({cible:n.target,html:n.html,raison:n.failureSummary}))})),
    incomplets:resultat.incomplete.map(v => ({id:v.id,noeuds:v.nodes.map(n => ({cible:n.target,raison:n.failureSummary}))}))};
  bilan.axe.push(resume);
  assert.deepEqual(resume.violations, [], 'axe ' + nom + ': ' + JSON.stringify(resume.violations));
}
async function actif(p, selecteur) {
  assert.ok(await p.locator(selecteur).evaluate(el => el === (el.getRootNode().activeElement || document.activeElement)), 'Focus attendu : ' + selecteur);
}
async function erreurLiee(p, selecteur) {
  const champ = p.locator(selecteur);
  await champ.waitFor({state:'visible'});
  await p.waitForFunction(s => document.querySelector(s).getAttribute('aria-invalid') === 'true', selecteur);
  const id = await champ.getAttribute('data-ses-erreur');
  assert.ok(id && (await champ.getAttribute('aria-describedby')).split(' ').includes(id));
  assert.equal(await p.locator('#'+id).getAttribute('role'),'alert');
  assert.ok((await p.locator('#'+id).innerText()).length);
  await actif(p,selecteur);
  return id;
}
async function onglet(p, selecteur) {await p.locator(selecteur).focus();await p.keyboard.press('Enter');}
function fait(nom) {bilan.clavier.push(nom);console.log('PASS clavier : '+nom);}

try {
  // Les 28 pages, en grand écran et en téléphone ; mode réduit pour que tous
  // les blocs existent immédiatement, pas seulement ceux déjà défilés.
  for (const largeur of [1440,390]) {
    const c = await contexte(largeur), p = await pageDe(c);
    for (const nom of fs.readdirSync(racine).filter(f => f.endsWith('.html')).sort()) {
      await aller(p,nom);
      assert.equal(await p.locator('main#contenu').count(),1);
      assert.equal(await p.locator('#contenu').count(),1);
      await p.keyboard.press('Tab');await actif(p,'.ses-skip-link');
      assert.ok(await p.locator('.ses-skip-link').evaluate(el => el.getBoundingClientRect().top >= 0));
      await p.keyboard.press('Enter');await actif(p,'main#contenu');
      await p.keyboard.press('Tab');
      assert.ok(await p.evaluate(() => document.activeElement !== document.body && !document.activeElement.closest('.ses-entete')),'Le saut doit contourner la navigation');
      await verifierAxe(p,nom+' '+largeur);
      assert.ok(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Débordement '+nom+' '+largeur);
    }
    await c.close();
  }
  fait('skip-link et repère main sur les 28 pages, desktop/mobile');

  const c = await contexte(), p = await pageDe(c);
  // Navigation mobile : ouverture native au clavier, Tab, Escape et état.
  await p.setViewportSize({width:390,height:844});await aller(p,'index.html');
  await p.locator('.ses-burger').focus();await p.keyboard.press('Enter');
  assert.equal(await p.locator('.ses-burger').getAttribute('aria-expanded'),'true');
  await p.keyboard.press('Tab');assert.ok(await p.evaluate(() => !!document.activeElement.closest('#ses-navigation')));
  await p.keyboard.press('Escape');await actif(p,'.ses-burger');
  assert.equal(await p.locator('.ses-burger').getAttribute('aria-expanded'),'false');
  fait('navigation mobile : Enter, Tab, Escape, retour du focus');

  // Shadow DOM : le premier Escape ne ferme pas aussi la navigation.
  await p.keyboard.press('Enter');
  const langue = p.locator('header.ses-entete lang-switcher');
  await langue.locator('.btn').focus();await p.keyboard.press('Enter');
  assert.equal(await langue.locator('.btn').getAttribute('aria-expanded'),'true');
  assert.equal(await langue.locator('[role=menuitemradio]').count(),4);
  assert.ok(await langue.evaluate(el=>!!el.shadowRoot.getElementById(el.shadowRoot.querySelector('.btn').getAttribute('aria-controls'))));
  await verifierAxe(p,'menu langue ouvert mobile');
  await p.keyboard.press('Escape');await actif(p,'header.ses-entete lang-switcher .btn');
  assert.equal(await p.locator('.ses-burger').getAttribute('aria-expanded'),'true');
  for (const [code, touches] of [['en',['Home']],['es',['Home','ArrowDown']],['ht',['End']],['fr',['End','ArrowUp']]]) {
    await p.keyboard.press('ArrowDown');
    for (const touche of touches) await p.keyboard.press(touche);
    await p.keyboard.press(code==='ht'?'Space':'Enter');
    await p.waitForFunction(code => document.documentElement.lang===code,code);
    await actif(p,'header.ses-entete lang-switcher .btn');
    assert.equal(await langue.locator('.btn').getAttribute('aria-expanded'),'false');
    assert.equal(await langue.locator('[aria-checked=true]').getAttribute('data-code'),code);
    assert.ok((await p.locator('.ses-skip-link').innerText()).length);
  }
  await p.keyboard.press('ArrowUp');await p.keyboard.press('Tab');
  assert.equal(await langue.locator('.btn').getAttribute('aria-expanded'),'false');
  assert.ok(await p.evaluate(() => document.activeElement.tagName!=='BODY'));
  await langue.locator('.btn').click();await langue.locator('[data-code=es]').click();
  await p.waitForFunction(() => document.documentElement.lang==='es');await actif(p,'header.ses-entete lang-switcher .btn');
  await langue.locator('.btn').click();await langue.locator('[data-code=fr]').click();
  await p.waitForFunction(() => document.documentElement.lang==='fr');
  fait('langue : flèches, Home/End, Enter/Espace, Escape, sortie Tab, souris, FR/EN/ES/HT et focus après traduction');

  await p.setViewportSize({width:1440,height:1000});
  for (const nom of ['index.html','a-propos.html','nos-services.html','suivi.html']) {
    await aller(p,nom);await p.locator('#rsn-onglet-1').focus();
    await p.keyboard.press('ArrowRight');await actif(p,'#rsn-onglet-2');
    assert.equal(await p.locator('#rsn-onglet-2').getAttribute('aria-selected'),'true');
    await p.keyboard.press('End');await actif(p,'#rsn-onglet-3');
    await p.keyboard.press('Home');await actif(p,'#rsn-onglet-1');
    await p.keyboard.press('ArrowLeft');await actif(p,'#rsn-onglet-3');
    await p.keyboard.press('Tab');await actif(p,'#rsn-panneau-3');
    await p.keyboard.press('Shift+Tab');await actif(p,'#rsn-onglet-3');
    await verifierAxe(p,nom+' onglet 3');
  }
  fait('onglets publics : activation automatique, flèches circulaires, Home/End, Tab vers panneau');

  // Une seule interaction par carte, cliquable aussi sur l'image. Le
  // pseudo-élément doit réellement recouvrir la carte, pas seulement le titre.
  for (const nom of ['index.html','blog.html']) {
    await aller(p,nom);
    for (const image of await p.locator('.ses-carte-article img').all()) {
      await image.scrollIntoViewIfNeeded();
      assert.ok(await image.evaluate(el=>{const r=el.getBoundingClientRect();return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.closest('a')===el.closest('article').querySelector('.ses-carte-lien');}),'Carte cliquable sur son image '+nom);
    }
    const lien=p.locator('.ses-carte-lien').first(), href=await lien.getAttribute('href');
    await lien.focus();await Promise.all([p.waitForURL('**/'+href),p.keyboard.press('Enter')]);
    assert.ok(new URL(p.url()).pathname.endsWith('/'+href));
  }
  fait('cartes blog/accueil : un lien par carte, activation Enter et clic sur toute l’image conservé');

  await aller(p,'espace-client.html');await p.locator('#ses-o-colis').focus();
  await p.keyboard.press('Tab');await actif(p,'#ses-p-colis');
  await p.keyboard.press('Shift+Tab');await p.keyboard.press('ArrowRight');await actif(p,'#ses-o-factures');
  assert.equal(await p.locator('#ses-o-colis').getAttribute('aria-selected'),'true');
  await p.keyboard.press('Enter');assert.equal(await p.locator('#ses-o-factures').getAttribute('aria-selected'),'true');
  await verifierAxe(p,'espace client factures non vides');
  await p.keyboard.press('End');await p.keyboard.press('Space');assert.equal(await p.locator('#ses-o-compte').getAttribute('aria-selected'),'true');
  await verifierAxe(p,'espace client compte');
  await p.locator('#ses-profil [name=telephone]').fill('abc');await p.locator('#ses-profil button[type=submit]').focus();await p.keyboard.press('Enter');
  await erreurLiee(p,'#ses-profil [name=telephone]');await verifierAxe(p,'espace client erreur profil');
  await p.locator('#ses-mdp button[type=submit]').focus();await p.keyboard.press('Enter');await erreurLiee(p,'#ses-mdp [name=motDePasse]');
  await verifierAxe(p,'espace client erreur mot de passe');
  await p.locator('#ses-o-compte').focus();
  await p.keyboard.press('Home');await p.keyboard.press('Space');
  await p.locator('#ses-filtres-colis [data-statut=expedie]').focus();await p.keyboard.press('Enter');await actif(p,'#ses-filtres-colis [data-statut=expedie]');
  await p.locator('#ses-o-colis').focus();await p.keyboard.press('ArrowLeft');await actif(p,'#ses-o-compte');
  fait('espace client : un tab-stop, activation manuelle Enter/Espace, flèches, Home/End');

  await aller(p,'tableau-de-bord.html');await p.locator('#ses-o-dashboard').focus();
  await p.keyboard.press('ArrowDown');await actif(p,'#ses-o-colis');
  assert.equal(await p.locator('#ses-o-dashboard').getAttribute('aria-selected'),'true');
  await p.keyboard.press('Enter');assert.equal(await p.locator('#ses-o-colis').getAttribute('aria-selected'),'true');
  await verifierAxe(p,'gestion colis non vides');
  await p.keyboard.press('ArrowRight');await p.keyboard.press('Space');await verifierAxe(p,'gestion factures non vides');
  await p.keyboard.press('ArrowDown');await p.keyboard.press('Enter');await verifierAxe(p,'gestion clients non vides');
  await p.keyboard.press('End');await p.keyboard.press('Enter');await verifierAxe(p,'gestion réglages');
  await p.keyboard.press('Home');await p.keyboard.press('Enter');
  await p.locator('#dash-serie summary').focus();await p.keyboard.press('Enter');
  await verifierAxe(p,'gestion graphique et valeurs tabulaires');
  await p.locator('#dash-filtres [name=periode]').selectOption('personnalise');
  await p.locator('#dash-filtres [name=debut]').fill('2026-09-02T10:00');await p.locator('#dash-filtres [name=fin]').fill('2026-09-01T10:00');
  await p.locator('#dash-filtres button[type=submit]').focus();await p.keyboard.press('Enter');await erreurLiee(p,'#dash-filtres [name=fin]');
  await verifierAxe(p,'gestion erreur de période');
  await p.setViewportSize({width:390,height:844});await p.locator('#dash-menu').focus();await p.keyboard.press('Enter');
  assert.equal(await p.locator('#dash-menu').getAttribute('aria-expanded'),'true');
  for (let i=0;i<12;i++) {await p.keyboard.press('Tab');assert.ok(await p.evaluate(() => !!document.activeElement.closest('#dash-navigation')));}
  await p.keyboard.press('Escape');await actif(p,'#dash-menu');
  assert.equal(await p.locator('#dash-menu').getAttribute('aria-expanded'),'false');
  await p.setViewportSize({width:1440,height:1000});
  fait('gestion : onglets verticaux/manuels et tiroir mobile, Tab contenu, Escape/focus');

  // Formulaires de compte : erreurs locales associées et erreurs serveur.
  for (const [nom, form, champ] of [['connexion.html','#ses-connexion','email'],['creer-un-compte.html','#ses-inscription','nom_complet'],['nouveau-mot-de-passe.html','#ses-nouveau-mdp','motDePasse']]) {
    await aller(p,nom);await p.locator(form+' button[type=submit]').focus();await p.keyboard.press('Enter');
    const s=form+' [name='+champ+']';const id=await erreurLiee(p,s);
    await verifierAxe(p,nom+' erreur de champ');
    await p.locator(s).fill('test');assert.equal(await p.locator('#'+id).count(),0);
    assert.equal(await p.locator(s).getAttribute('aria-invalid'),null);
  }
  await aller(p,'connexion.html');
  await p.locator('[name=email]').fill('test@example.invalid');await p.locator('[name=motDePasse]').fill('incorrect-test');
  await p.locator('#ses-connexion button[type=submit]').focus();await p.keyboard.press('Enter');
  await p.waitForFunction(() => document.getElementById('ses-message').getAttribute('role')==='alert');
  assert.ok((await p.locator('#ses-connexion').getAttribute('aria-describedby')).includes('ses-message'));
  await verifierAxe(p,'connexion erreur réseau simulée');
  await p.locator('.ses-voir-mdp').focus();await p.keyboard.press('Space');assert.equal(await p.locator('[name=motDePasse]').getAttribute('type'),'text');
  await p.keyboard.press('Space');assert.equal(await p.locator('[name=motDePasse]').getAttribute('type'),'password');
  // Vérifie expressément que la correction conserve les descriptions d'aide.
  await p.evaluate(() => {const aide=document.createElement('p');aide.id='aide-test';aide.textContent='Aide';document.querySelector('#ses-connexion').appendChild(aide);const champ=document.querySelector('[name=email]');champ.setAttribute('aria-describedby','aide-test');SES_UI.erreurChamp(champ,'Erreur de test');SES_UI.erreurChamp(champ,'Erreur de test répétée');});
  assert.equal(await p.locator('.ses-erreur').count(),1);
  await p.locator('[name=email]').fill('corrige@example.invalid');assert.equal(await p.locator('[name=email]').getAttribute('aria-describedby'),'aide-test');
  fait('comptes : erreurs locales/serveur annoncées, IDs uniques, aide conservée, correction et boutons mot de passe');

  await aller(p,'creer-un-compte.html');
  await p.locator('[name=pays]').focus();await p.keyboard.press('Home');await p.keyboard.press('ArrowDown');
  assert.ok(await p.locator('[name=pays]').inputValue());
  await p.locator('[name=pays]').selectOption('autre');await actif(p,'input[name=pays]');
  assert.equal(await p.locator('input[name=pays]').evaluate(el => !!el.labels.length),true);
  fait('pays natif au clavier et champ « autre pays » nommé avec focus');
  for (const [nom,valeur] of Object.entries({nom_complet:'Test',pays:'Canada',adresse:'Adresse de test',region:'Région de test',ville:'Ville de test',telephone:'abc',email:'test@example.invalid',motDePasse:'mot-de-passe-test'})) await p.locator('[name='+nom+']').fill(valeur);
  await p.locator('#ses-inscription button[type=submit]').focus();await p.keyboard.press('Enter');
  await erreurLiee(p,'#ses-inscription [name=telephone]');await verifierAxe(p,'inscription erreur téléphone');

  for (const nom of ['index.html','suivi.html']) {
    await aller(p,nom);await p.locator('#ses-ref-input').focus();await p.keyboard.press('Enter');
    await erreurLiee(p,'#ses-ref-input');await verifierAxe(p,nom+' suivi vide');
    await p.locator('#ses-ref-input').fill('INCONNU');await p.keyboard.press('Enter');await erreurLiee(p,'#ses-ref-input');
    await p.locator('#ses-ref-input').fill('SES-TEST');await p.keyboard.press('Enter');
    await p.waitForFunction(() => document.getElementById('ses-suivi-annonce').textContent.includes('SES-TEST'));
    assert.equal(await p.locator('#ses-ref-input').getAttribute('aria-invalid'),null);
    await verifierAxe(p,nom+' résultat suivi');
    await p.locator('[data-ses-form=suivi] button[type=submit]').focus();await p.keyboard.press('Enter');
    await p.waitForFunction(()=>!document.querySelector('[data-ses-form=suivi] button[type=submit]').disabled);
    await actif(p,'[data-ses-form=suivi] button[type=submit]');
  }
  fait('suivi accueil/page : label, Enter, erreurs vide/inconnu, résultat annoncé et défilement réduit');

  await aller(p,'contacts.html');await p.locator('[data-ses-form=contact] button[type=submit]').focus();await p.keyboard.press('Enter');
  await erreurLiee(p,'[name=Nom]');await verifierAxe(p,'contact erreur obligatoire');
  await p.locator('[name=Nom]').fill('Test');await p.locator('[name=Email]').fill('invalide');
  await p.locator('[data-ses-form=contact] button[type=submit]').focus();await p.keyboard.press('Enter');await erreurLiee(p,'[name=Email]');
  await p.locator('[name=Email]').fill('test@example.invalid');await p.locator('[name=Téléphone]').fill('abc');await p.locator('[name=Message]').fill('Message de test');
  await p.locator('[data-ses-form=contact] button[type=submit]').focus();await p.keyboard.press('Enter');await erreurLiee(p,'[name=Téléphone]');
  await p.locator('[name=Téléphone]').fill('+1 (555) 010-0100');
  assert.equal(await p.locator('[name=Téléphone]').evaluate(el => el.checkValidity()),true);
  await p.evaluate(() => {SES_CONFIG.formEndpoint='https://example.invalid/test';window.fetch=()=>Promise.reject(new Error('Test hors réseau'));});
  // site.js garde la même référence de configuration, pas une requête réelle.
  await p.locator('[data-ses-form=contact] button[type=submit]').focus();await p.keyboard.press('Enter');
  await p.waitForFunction(() => document.getElementById('ses-contact-erreur').getAttribute('role')==='alert');
  assert.equal(await p.locator('[name=Message]').getAttribute('aria-invalid'),null);
  await verifierAxe(p,'contact erreur de service');
  await p.evaluate(() => {window.fetch=()=>Promise.resolve({ok:true});});
  await p.locator('[data-ses-form=contact] button[type=submit]').focus();await p.keyboard.press('Enter');
  await p.locator('[data-ses-if=sent]').waitFor({state:'visible'});await actif(p,'[data-ses-if=sent]');
  await p.keyboard.press('Tab');await p.keyboard.press('Enter');await actif(p,'[name=Nom]');
  fait('contact : validation nom/email/téléphone, alerte de service, succès et remise à zéro au clavier');

  // Deux combobox indépendantes : mêmes interactions et des IDs distincts.
  for (const [tab, ouvreur, dialogue, suffixe, suivant] of [['colis','ses-nouveau-colis','ses-form-colis','','description'],['factures','ses-nouvelle-facture','ses-form-facture','-f','colis_id']]) {
    await aller(p,'tableau-de-bord.html');await onglet(p,'#ses-o-'+tab);
    await p.locator('#'+ouvreur).focus();await p.keyboard.press('Enter');
    await p.locator('#'+dialogue).waitFor({state:'visible'});
    await actif(p,'#'+dialogue+' .ses-fermer');await p.keyboard.press('Tab');
    const champ='#ses-client-recherche'+suffixe, liste='#ses-clients-trouves'+suffixe;
    await actif(p,champ);await p.keyboard.press('Enter');await erreurLiee(p,champ);
    await verifierAxe(p,'formulaire '+tab+' client requis');
    await p.locator(champ).fill('TE');await p.locator(liste).waitFor({state:'visible'});
    assert.equal(await p.locator(liste+' [role=option]').count(),3);
    assert.equal(await p.locator(liste+' button').count(),0);
    await p.keyboard.press('ArrowDown');assert.equal(await p.locator(champ).getAttribute('aria-activedescendant'),liste.slice(1)+'-option-0');
    await p.keyboard.press('ArrowDown');await p.keyboard.press('ArrowUp');await p.keyboard.press('ArrowUp');
    assert.equal(await p.locator(champ).getAttribute('aria-activedescendant'),liste.slice(1)+'-option-2');
    await verifierAxe(p,'combobox '+tab+' suggestions actives');
    await p.keyboard.press('Enter');await actif(p,champ);
    assert.equal(await p.locator('#'+dialogue+' [name=client_id]').inputValue(),'client-test-3');
    assert.equal(await p.locator(champ).getAttribute('aria-activedescendant'),null);
    assert.equal(await p.evaluate(() => window.__envois),0,'Enter sélectionne, ne soumet pas');
    await p.locator(champ).fill('TE');await p.locator(liste).waitFor({state:'visible'});
    await p.locator(liste+' [role=option]').nth(1).click();await actif(p,champ);
    assert.equal(await p.locator('#'+dialogue+' [name=client_id]').inputValue(),'client-test-2');
    await p.locator(champ).fill('TE');await p.locator(liste).waitFor({state:'visible'});
    await p.keyboard.press('Tab');await actif(p,'#'+dialogue+' [name='+suivant+']');
    assert.equal(await p.locator(champ).getAttribute('aria-expanded'),'false');
    await p.locator(champ).focus();await p.locator(champ).fill('ZZ');
    await p.waitForFunction(id => document.getElementById(id+'-message').textContent.length>0,liste.slice(1));
    assert.equal(await p.locator(champ).getAttribute('aria-expanded'),'false');
    await verifierAxe(p,'combobox '+tab+' aucun résultat');
    await p.evaluate(() => {window.__retardCompletion=120;});
    await p.locator(champ).fill('TE');await p.keyboard.press('ArrowDown');
    const fini = await p.evaluate(() => window.__completionDebut);
    await p.keyboard.press('Escape');
    await p.waitForFunction(n => window.__completionFin>=n,fini);
    assert.equal(await p.locator(champ).getAttribute('aria-expanded'),'false');
    assert.equal(await p.locator('#'+dialogue).isVisible(),true);
    await p.keyboard.press('Escape');await p.locator('#'+dialogue).waitFor({state:'hidden'});await actif(p,'#'+ouvreur);
    // Boucles Tab et Shift+Tab dans le dialogue ; Escape reste une sortie.
    await p.keyboard.press('Enter');await p.locator('#'+dialogue).waitFor({state:'visible'});
    for(let i=0;i<32;i++){await p.keyboard.press('Tab');assert.ok(await p.evaluate(id => document.activeElement.closest('dialog')?.id===id,dialogue),'Tab dialog '+dialogue+' #'+i+' '+await p.evaluate(()=>document.activeElement.outerHTML.slice(0,400)));}
    await p.locator('#'+dialogue+' button').first().focus();await p.keyboard.press('Shift+Tab');
    assert.ok(await p.evaluate(id=>document.activeElement.closest('dialog')?.id===id,dialogue));
    await p.locator('#'+dialogue+' .ses-fermer').focus();await p.keyboard.press('Enter');await actif(p,'#'+ouvreur);
  }
  fait('deux combobox : flèches/Enter/Escape/Tab, focus conservé, souris, aucun résultat, réponse tardive, dialogues et retour du focus');

  // Les cinq autres dialogues : contenu dynamique nommé, boucles Tab et
  // fermeture Escape. La confirmation est annulée, aucune suppression.
  await aller(p,'tableau-de-bord.html');
  for (const [tab, action, id, dialogue] of [
    ['colis','fiche','colis-test-0','ses-fiche'],['colis','statut','colis-test-0','ses-form-statut'],
    ['clients','role','client-test-1','ses-form-role'],['colis','supprimer','colis-test-0','ses-confirmer']
  ]) {
    await onglet(p,'#ses-o-'+tab);
    const ouvreur='#ses-p-'+tab+' [data-action='+action+'][data-id='+id+']';
    await p.locator(ouvreur).focus();await p.keyboard.press('Enter');await p.locator('#'+dialogue).waitFor({state:'visible'});
    await verifierAxe(p,'dialogue '+dialogue);
    if(dialogue==='ses-form-role'){await p.locator('#ses-role [name=role]').selectOption('employe');await verifierAxe(p,'rôle employé et droits affichés');}
    for(let i=0;i<16;i++){await p.keyboard.press('Tab');assert.ok(await p.evaluate(id=>document.activeElement.closest('dialog')?.id===id,dialogue));}
    await p.locator('#'+dialogue+' button').first().focus();await p.keyboard.press('Shift+Tab');
    assert.ok(await p.evaluate(id=>document.activeElement.closest('dialog')?.id===id,dialogue));
    await p.keyboard.press('Escape');await p.locator('#'+dialogue).waitFor({state:'hidden'});await actif(p,ouvreur);
  }
  // Parcours réel : fiche client → aperçu de facture → paiement. Le rendu
  // de l'aperçu remplace le bouton précédent : le focus ne doit pas être
  // laissé sur body, même quand le même dialogue est déjà ouvert.
  await onglet(p,'#ses-o-clients');
  const profil='#ses-p-clients [data-action=profil][data-id=client-test-1]';
  await p.locator(profil).focus();await p.keyboard.press('Enter');await p.locator('#ses-fiche').waitFor({state:'visible'});
  await verifierAxe(p,'fiche client, chiffres et solde');
  await p.locator('#ses-fiche [data-action=apercu-facture][data-id=facture-test-1]').focus();await p.keyboard.press('Enter');
  await p.locator('#ses-fiche [data-action=paiement]').waitFor({state:'visible'});
  assert.ok(await p.evaluate(()=>document.activeElement.closest('dialog')?.id==='ses-fiche'));
  await verifierAxe(p,'aperçu facture dans fiche client');
  await p.locator('#ses-fiche [data-action=paiement]').focus();await p.keyboard.press('Enter');
  await p.locator('#ses-form-paiement').waitFor({state:'visible'});await verifierAxe(p,'dialogue paiement');
  for(let i=0;i<8;i++){await p.keyboard.press('Tab');assert.ok(await p.evaluate(()=>document.activeElement.closest('dialog')?.id==='ses-form-paiement'));}
  await p.locator('#ses-form-paiement .ses-fermer').focus();await p.keyboard.press('Shift+Tab');
  assert.ok(await p.evaluate(()=>document.activeElement.closest('dialog')?.id==='ses-form-paiement'));
  await p.keyboard.press('Escape');await actif(p,'#ses-fiche [data-action=paiement]');
  await p.keyboard.press('Escape');await actif(p,profil);
  fait('sept dialogues : noms, ordre et boucle Tab/Shift+Tab, fermeture Escape, retour aux ouvreurs');

  // Vue limitée et états vides : les droits ne créent pas d'onglet fantôme.
  const limite = await contexte();await limite.addInitScript(() => {window.__droitsTest=['factures.lire'];window.__vide=true;});
  const pl = await pageDe(limite);await pl.goto('http://localhost:8127/tableau-de-bord.html');
  await pl.waitForFunction(() => document.getElementById('ses-o-colis').hidden);
  await pl.locator('#ses-o-dashboard').focus();await pl.keyboard.press('ArrowDown');await actif(pl,'#ses-o-factures');
  await pl.keyboard.press('Enter');await verifierAxe(pl,'gestion droits limités et état vide');await limite.close();
  fait('onglets masqués par les droits exclus du clavier, état vide');

  // Réduction des mouvements initiale ET basculée pendant la visite.
  await aller(p,'index.html');
  for (const s of ['html','.corridor__piste','.rsn__medaillon svg']) {
    assert.equal(await p.locator(s).first().evaluate(el => getComputedStyle(el).animationName),'none');
  }
  assert.equal(await p.locator('html').evaluate(el => getComputedStyle(el).scrollBehavior),'auto');
  const standard = await contexte(1440,{reducedMotion:'no-preference'}), ps = await pageDe(standard);
  await ps.addInitScript(() => {window.__intervalles=0;const ancien=window.setInterval;window.setInterval=function(fn,ms,...args){if(ms===6500)window.__intervalles++;return ancien(fn,ms,...args);};});
  await aller(ps,'index.html');await ps.waitForFunction(() => window.__intervalles>0);
  await ps.emulateMedia({reducedMotion:'reduce'});
  await ps.waitForFunction(() => getComputedStyle(document.querySelector('.corridor__piste')).animationName==='none');
  const avant = await ps.locator('[data-aller][aria-pressed=true]').getAttribute('data-aller');
  await ps.waitForTimeout(6700); // couvre un intervalle entier, pas un polling
  assert.equal(await ps.locator('[data-aller][aria-pressed=true]').getAttribute('data-aller'),avant);
  await ps.emulateMedia({reducedMotion:'no-preference'});
  await ps.locator('[data-ses-hero-pause]').focus();await ps.keyboard.press('Enter');
  assert.equal(await ps.locator('[data-ses-hero-pause]').getAttribute('aria-pressed'),'true');
  await ps.keyboard.press('Tab');
  const pauseAvant=await ps.locator('[data-aller][aria-pressed=true]').getAttribute('data-aller');
  await ps.waitForTimeout(6700);
  assert.equal(await ps.locator('[data-aller][aria-pressed=true]').getAttribute('data-aller'),pauseAvant);
  await verifierAxe(ps,'accueil mouvement normal, pause');
  await standard.close();
  fait('reduced motion : CSS, scrolling JS, changement système à chaud, arrêt carrousel, pause explicite');

  await c.close();
  assert.deepEqual(bilan.erreursJavascript,[]);
  bilan.succes=true;
  console.log('PASS axe-core : '+bilan.axe.length+' états, zéro violation WCAG A/AA 2.0–2.2 et bonnes pratiques testées.');
} finally {
  if (process.env.SES_A11Y_REPORT) fs.writeFileSync(process.env.SES_A11Y_REPORT,JSON.stringify(bilan,null,2));
  await navigateur.close();await new Promise(r => serveur.close(r));
}
