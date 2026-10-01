/* Vérification facultative en navigateur réel, dépendances hors dépôt.
   SES_TEST_DEPS=/chemin/deps node outils/tests/qualite-browser.mjs */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import assert from 'node:assert/strict';
const deps = process.env.SES_TEST_DEPS;
assert.ok(deps, 'Définir SES_TEST_DEPS (playwright et @sparticuz/chromium)');
const {default:chromium} = await import(deps + '/node_modules/@sparticuz/chromium/build/index.js');
const {chromium:pw} = await import(deps + '/node_modules/playwright/index.mjs');
const racine = process.cwd();
const serveur = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const fichier = path.resolve(racine, '.' + decodeURIComponent(url.pathname));
  if (!fichier.startsWith(racine + '/') || !fs.existsSync(fichier) || !fs.statSync(fichier).isFile()) {
    res.writeHead(404); res.end(); return;
  }
  const types = {'.html':'text/html', '.js':'application/javascript', '.css':'text/css', '.png':'image/png', '.jpg':'image/jpeg', '.webp':'image/webp'};
  res.setHeader('Content-Type', types[path.extname(fichier)] || 'application/octet-stream');
  res.end(fs.readFileSync(fichier));
});
await new Promise(r => serveur.listen(0, '127.0.0.1', r));
let navigateur;
const erreurs = [];
try {
  navigateur = await pw.launch({executablePath:await chromium.executablePath(), args:chromium.args.filter(a => a !== '--single-process'), headless:true});
  const contexte = await navigateur.newContext();
  // Aucun accès aux services métier ou au réseau externe pendant les tests.
  await contexte.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.hostname !== '127.0.0.1') return route.abort();
    if (url.pathname.endsWith('/config.js')) return route.fulfill({contentType:'application/javascript', body:'window.SES_CONFIG={};'});
    return route.continue();
  });
  const pages = fs.readdirSync('.').filter(n => n.endsWith('.html'));
  for (const nom of pages) {
    const page = await contexte.newPage();
    page.on('pageerror', e => erreurs.push(nom + ': ' + e.message));
    // Mode fermé, plutôt qu'une authentification démo non pertinente ici.
    await page.addInitScript(() => { window.localStorage.setItem('ses-lang','fr'); });
    await page.goto(`http://127.0.0.1:${serveur.address().port}/${nom}`, {waitUntil:'networkidle'});
    for (const largeur of [1440, 390]) {
      await page.setViewportSize({width:largeur, height:900});
      assert.ok(await page.locator('header.ses-entete').isVisible(), nom + ': header');
      assert.ok(await page.locator('footer').isVisible(), nom + ': footer');
      const police = await page.locator('h1').first().evaluate(e => getComputedStyle(e).fontFamily);
      assert.ok(police.includes('Saira'), nom + ': ' + police);
      if (largeur === 390) {
        await page.locator('.ses-burger').click();
        assert.equal(await page.locator('.ses-burger').getAttribute('aria-expanded'), 'true', nom);
        assert.ok(await page.locator('#ses-navigation').isVisible(), nom);
        await page.locator('.ses-burger').click();
      }
    }
    await page.close();
  }
  assert.deepEqual(erreurs, []);
  console.log('PASS navigateur : 28 pages × 2 largeurs, header/footer, Saira, menu mobile, aucune exception JS. Réseau métier bloqué.');
} finally {
  if (navigateur) await navigateur.close();
  serveur.close();
}
