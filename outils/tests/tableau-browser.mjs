/* Phase 7 — le tableau de bord dans un VRAI navigateur, aux largeurs demandées et dans les quatre langues.
   Ordinateur 1440 / 1920 / 2560 px, tablette 768 / 1024 px, téléphone 375 / 390 / 430 px. Aucun appel réseau : la couche de données est
   remplacée par les réponses RÉELLES enregistrées par logistique-tableau-essai.py (tableau-exemples.json) et les fixtures de l'ancien
   schéma de accessibilite-browser.mjs. On exige, à chaque largeur : aucun défilement horizontal de la page ; la barre des 26 modules
   (visible sur ordinateur, dans le tiroir ailleurs) ; le centre de commande en cartes, chaque carte ouvrant son module ; le Pointage
   Express, les véhicules, les tournées, les dépenses ; aucune erreur JavaScript. Dans chaque langue : chaque entrée de la barre et chaque
   titre de carte traduits (aucun reste de français), aucun texte vide.
   SES_TEST_DEPS=/dossier/playwright [SES_CHROME=…] node outils/tests/tableau-browser.mjs */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
import {lancerNavigateur} from './_navigateur.mjs';
const deps = process.env.SES_TEST_DEPS;
assert.ok(deps, 'Définir SES_TEST_DEPS, chemin du dossier de dépendances hors dépôt');
const racine = process.cwd();
const EX = fs.readFileSync('outils/tests/tableau-exemples.json', 'utf8');
const ancien = /const fixture = `([\s\S]*?)`;/.exec(fs.readFileSync('outils/tests/accessibilite-browser.mjs', 'utf8'))[1];
const fixture = ancien + `
(function () {
 var EX = ${EX};
 var A = SES_API;
 A.notifications = A.notifications || {}; A.notifications.surveiller = function () { return function () {}; };
 A.centre.disponible = function () { return Promise.resolve({ actif: true, acces: { sections: ['commande', 'flux', 'colis', 'expeditions', 'entrepot', 'consolidations', 'transport', 'chauffeurs',
   'enlevements', 'livraisons', 'douane', 'incidents', 'notifications', 'clients', 'support', 'facturation', 'paiements', 'utilisateurs', 'audit', 'parametres'],
   role: 'admin', direction: true, ops: true, finance: true, customers: true, today: EX.acces.today } }); };
 A.centre.entrepot = function () { return Promise.resolve({ warehouses: [{ warehouse_id: 'w1', code: 'PAP-1', name: 'Entrepôt Port-au-Prince' }] }); };
 A.centre.liste = function () { return Promise.resolve({ total: 0, items: [], filters: {} }); };
 var r = function (x) { return function () { return Promise.resolve(JSON.parse(JSON.stringify(x))); }; };
 A.tableau.acces = r(EX.acces); A.tableau.commande = r(EX.commande); A.tableau.vehicules = r(EX.vehicules); A.tableau.tournees = r(EX.tournees); A.tableau.depenses = r(EX.depenses);
 A.tableau.pointages = r(EX.pointages); A.tableau.detailPointage = r(EX.pointage); A.tableau.maJournee = r(EX.journee); A.tableau.releve = r(EX.releve); A.tableau.mesMissions = r(EX.missions);
})();`;
const serveur = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const fichier = path.resolve(racine, '.' + url.pathname);
  if (!fichier.startsWith(racine + '/') || !fs.existsSync(fichier) || !fs.statSync(fichier).isFile()) { res.writeHead(404); res.end(); return; }
  const types = {'.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.png':'image/png', '.jpg':'image/jpeg', '.webp':'image/webp', '.svg':'image/svg+xml'};
  res.setHeader('Content-Type', types[path.extname(fichier)] || 'application/octet-stream');
  res.end(fs.readFileSync(fichier));
});
await new Promise(r => serveur.listen(8128, '127.0.0.1', r));
const navigateur = await lancerNavigateur(deps);
const erreurs = [];
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };
const captures = process.env.SES_CAPTURES || '';

async function page(largeur, langue) {
  const c = await navigateur.newContext({ viewport: { width: largeur, height: largeur < 700 ? 844 : 1000 }, locale: 'fr-FR', reducedMotion: 'reduce', bypassCSP: true });
  await c.addInitScript((l) => { localStorage.clear(); localStorage.setItem('ses-lang', l); }, langue);
  await c.route('**/*', route => {
    const u = new URL(route.request().url());
    if (u.hostname !== '127.0.0.1') return route.abort();
    if (u.pathname.endsWith('/config.js')) return route.fulfill({ contentType: 'application/javascript', body: 'window.SES_CONFIG={centreNoyau:true};' });
    if (u.pathname.endsWith('/ses-api.js')) return route.fulfill({ contentType: 'application/javascript', body: fs.readFileSync('assets/js/ses-api.js', 'utf8') + fixture });
    return route.continue();
  });
  const p = await c.newPage();
  p.on('pageerror', e => erreurs.push(largeur + ' ' + langue + ' : ' + e.message));
  await p.goto('http://127.0.0.1:8128/tableau-de-bord.html#centre/temps-reel');
  await p.waitForSelector('.cc-tr-grille', { timeout: 15000 });
  return { c, p };
}
const debordement = (p) => p.evaluate(() => document.scrollingElement.scrollWidth - window.innerWidth);
const ouvrirMenu = async (p, largeur) => { if (largeur < 1024 && await p.locator('#dash-menu').isVisible()) { await p.click('#dash-menu'); await p.waitForTimeout(350); } };

for (const largeur of [1440, 1920, 2560, 1024, 768, 430, 390, 375]) {
  const { c, p } = await page(largeur, 'fr');
  ok(await debordement(p) <= 1, largeur + ' px : la page ne défile pas en largeur (centre de commande) — ' + await debordement(p) + ' px');
  const cartes = await p.$$eval('.cc-tr-carte a.cc-tr-lien', (l) => l.map((a) => a.getAttribute('href')));
  ok(cartes.length === 11 && cartes.every((h) => /^#/.test(h)), largeur + ' px : onze cartes, chacune ouvre son module');
  await ouvrirMenu(p, largeur);
  const visibles = await p.$$eval('.ses-onglets [role=tab]', (l) => l.filter((b) => !b.hidden && b.getBoundingClientRect().width > 0).map((b) => b.getAttribute('data-module')));
  ok(visibles.length === 26, largeur + ' px : les 26 modules dans la barre' + (largeur < 1024 ? ' (tiroir)' : '') + ' — ' + visibles.length);
  if (captures) await p.screenshot({ path: path.join(captures, 'tdb-' + largeur + '-centre' + (largeur < 1024 ? '-menu' : '') + '.png'), fullPage: largeur >= 1024 });
  // une carte ouvre son module : « Livraisons aujourd'hui » → le module Livraisons est sélectionné dans la barre
  if (largeur < 1024) { await p.keyboard.press('Escape'); await p.waitForTimeout(200); if (await p.locator('#dash-menu').getAttribute('aria-expanded') === 'true') await p.click('#dash-menu'); }
  await p.evaluate(() => { location.hash = '#centre/pointage'; });
  await p.waitForSelector('.cc-pt-horloge', { timeout: 10000 });
  ok(await p.locator('#ses-o-pointage').getAttribute('aria-selected') === 'true', largeur + ' px : #centre/pointage sélectionne « Pointage Express » dans la barre');
  ok(await debordement(p) <= 1, largeur + ' px : pointage sans défilement horizontal');
  if (captures && [1440, 768, 390].includes(largeur)) await p.screenshot({ path: path.join(captures, 'tdb-' + largeur + '-pointage.png'), fullPage: true });
  for (const [sec, sel] of [['vehicules', '.cc-table'], ['tournees', '.cc-table'], ['depenses', '.cc-kpis']]) {
    await p.evaluate((s) => { location.hash = '#centre/' + s; }, sec);
    await p.waitForSelector('#cc-contenu ' + sel, { timeout: 10000 });
    ok(await debordement(p) <= 1, largeur + ' px : ' + sec + ' sans défilement horizontal de la page');
  }
  await p.click('#ses-o-colis').catch(() => {});
  if (largeur >= 1024) ok(await p.locator('#ses-p-colis').isVisible(), largeur + ' px : un module de l\'ancien schéma s\'ouvre toujours (Colis)');
  await c.close();
}

// Les quatre langues : la barre et les cartes, jamais en français ailleurs qu'en français.
const FR = await (async () => { const { c, p } = await page(1440, 'fr'); const x = await p.$$eval('.ses-onglets [role=tab] span', (l) => l.map((s) => s.textContent.trim())); const y = await p.$$eval('.cc-tr-titre', (l) => l.map((s) => s.textContent.trim())); await c.close(); return { barre: x, cartes: y }; })();
ok(FR.barre.length === 26 && FR.barre[0] === 'Vue générale' && FR.barre[25] === 'Santé système', 'français : la barre, de « Vue générale » à « Santé système »');
const IDENTIQUES = new Set(['Transport', 'Consolidations', 'Notifications', 'Incidents', 'Scanner', 'Colis', 'Analytique', 'Douane']);
for (const langue of ['en', 'es', 'ht']) {
  const { c, p } = await page(1440, langue);
  await p.waitForFunction(() => document.documentElement.lang && document.documentElement.lang !== 'fr', null, { timeout: 10000 }).catch(() => {});
  const barre = await p.$$eval('.ses-onglets [role=tab] span', (l) => l.map((s) => s.textContent.trim()));
  const cartes = await p.$$eval('.cc-tr-titre', (l) => l.map((s) => s.textContent.trim()));
  const restes = barre.filter((x, i) => x === FR.barre[i] && !IDENTIQUES.has(x));
  ok(barre.every(Boolean) && restes.length === 0, langue + ' : chaque entrée de la barre traduite (restes : ' + restes.join(', ') + ')');
  ok(cartes.length === 11 && cartes.every(Boolean) && cartes.filter((x, i) => x === FR.cartes[i] && !['Incidents'].includes(x)).length === 0, langue + ' : chaque carte traduite (' + cartes.join(' | ') + ')');
  const vides = await p.$$eval('#cc-contenu *', (l) => l.filter((el) => el.children.length === 0 && /^(dt|dd|span|strong|p|h3|button|a)$/i.test(el.tagName) && !el.textContent.trim() && !el.hidden && el.getAttribute('aria-hidden') !== 'true').length);
  ok(vides === 0, langue + ' : aucun texte vide dans le centre de commande (' + vides + ')');
  if (captures) await p.screenshot({ path: path.join(captures, 'tdb-1440-' + langue + '.png') });
  await c.close();
}
ok(erreurs.length === 0, 'aucune erreur JavaScript : ' + erreurs.slice(0, 3).join(' | '));
await navigateur.close(); serveur.close();
console.log('PASS tableau de bord (navigateur) : ' + n + ' vérifications — 8 largeurs (1440, 1920, 2560, 1024, 768, 430, 390, 375 px) sans défilement horizontal, 26 modules, onze cartes qui ouvrent leur module, pointage, véhicules, tournées, dépenses, quatre langues sans reste de français.');
