#!/usr/bin/env node
// La PRÉPRODUCTION du site : le dépôt servi sur ce poste, branché sur le projet Supabase de préproduction.
//   node outils/staging/servir.cjs            → http://localhost:8792
//
// Rien n'est changé dans les fichiers du dépôt ni dans le site publié. Au moment de servir :
//   · assets/js/config.js reçoit, à la suite de la configuration de production, l'URL, la clé PUBLIQUE et l'adresse du
//     site de préproduction (lues dans outils/staging/config-staging.local.json, non suivi par Git — modèle :
//     config-staging.exemple.json) ; un bandeau « PRÉPRODUCTION » s'affiche en haut de chaque page ;
//   · la politique de contenu de chaque page autorise le projet de préproduction À LA PLACE de celui de production :
//     une page de préproduction ne peut donc pas joindre la base réelle, même par erreur.
// Le serveur refuse de démarrer si la configuration désigne le projet de production, un projet protégé (Goship), une clé
// secrète, ou une adresse qui n'est pas https://<projet>.supabase.co. Il n'écoute que ce poste (127.0.0.1) et ne sert que
// ce que le site publie (ni outils/, ni docs/, ni .git…).
'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const RACINE = path.resolve(__dirname, '..', '..');
const PORT = Number(process.env.SES_STAGING_PORT || 8792);
const FICHIER = process.env.SES_STAGING_CONFIG || path.join(__dirname, 'config-staging.local.json');
// Projets qui ne sont JAMAIS une préproduction : la production (lue dans config.js) et le projet frère (scripts/backup/_commun.py).
const COMMUN = fs.readFileSync(path.join(RACINE, 'scripts', 'backup', '_commun.py'), 'utf8');
const PROTEGES = (COMMUN.match(/PROJETS_INTERDITS\s*=\s*[({[]([^)}\]]*)/) || [, ''])[1].match(/[a-z0-9]{20}/g) || [];
const CONFIG_PROD = fs.readFileSync(path.join(RACINE, 'assets', 'js', 'config.js'), 'utf8');
const URL_PROD = (CONFIG_PROD.match(/supabaseUrl:\s*'([^']+)'/) || [])[1];
const PUBLIES_JAMAIS = /^\/(\.git|\.github|\.claude|outils|docs|scripts|node_modules)(\/|$)|^\/(CLAUDE|README|SECURITY|ARCHITECTURE-BASELINE)\.md$|^\/\.gitignore$/;

function arreter(message) {
  console.error('REFUS : ' + message);
  process.exit(2);
}

function lireConfiguration() {
  let c;
  try { c = JSON.parse(fs.readFileSync(FICHIER, 'utf8')); } catch (e) {
    arreter('configuration de préproduction illisible (' + FICHIER + ') : copiez config-staging.exemple.json en config-staging.local.json et remplissez-le.');
  }
  if (!c || typeof c !== 'object') arreter('configuration de préproduction vide : il faut supabaseUrl et supabaseKey (' + FICHIER + ').');
  const m = /^https:\/\/([a-z0-9]{20})\.supabase\.co$/.exec(c.supabaseUrl || '');
  if (!m) arreter('supabaseUrl doit être https://<projet>.supabase.co (reçu : ' + c.supabaseUrl + ').');
  if (c.supabaseUrl === URL_PROD || PROTEGES.includes(m[1])) arreter('supabaseUrl désigne le projet de PRODUCTION ou un projet protégé : jamais en préproduction.');
  if (!/^sb_publishable_[A-Za-z0-9_-]{10,}$/.test(c.supabaseKey || '')) {
    arreter('supabaseKey doit être la clé PUBLIQUE du projet de préproduction (sb_publishable_…). Une clé secrète ne quitte jamais Supabase.');
  }
  if (CONFIG_PROD.includes(c.supabaseKey)) arreter('supabaseKey est la clé de production.');
  return { supabaseUrl: c.supabaseUrl, supabaseKey: c.supabaseKey, hote: m[1] + '.supabase.co' };
}

const CFG = lireConfiguration();
const HOTE_PROD = URL_PROD.replace('https://', '');
const SITE = 'http://localhost:' + PORT;

// Ajouté à config.js : les valeurs de préproduction, et le bandeau (style posé par le DOM : la politique de contenu le permet).
const SURCHARGE = `
;(function () {
  var c = window.SES_CONFIG = window.SES_CONFIG || {};
  c.supabaseUrl = ${JSON.stringify(CFG.supabaseUrl)};
  c.supabaseKey = ${JSON.stringify(CFG.supabaseKey)};
  c.siteUrl = ${JSON.stringify(SITE)};
  c.environnement = 'staging';
  function bandeau() {
    if (document.getElementById('ses-bandeau-preproduction')) return;
    var b = document.createElement('div');
    b.id = 'ses-bandeau-preproduction';
    b.setAttribute('role', 'note');
    b.textContent = 'PRÉPRODUCTION — données d\\u2019essai, aucun vrai client';
    b.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:#b45309;color:#fff;' +
      'font:600 13px/1.2 system-ui,sans-serif;text-align:center;padding:6px 8px;letter-spacing:.02em;pointer-events:none';
    document.body.appendChild(b);
  }
  if (document.body) bandeau(); else document.addEventListener('DOMContentLoaded', bandeau);
})();
`;

const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.ico': 'image/x-icon', '.woff2': 'font/woff2',
  '.txt': 'text/plain; charset=utf-8', '.xml': 'application/xml' };

function repondre(res, code, type, corps) {
  res.writeHead(code, { 'Content-Type': type, 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex' });
  res.end(corps);
}

const serveur = http.createServer((req, res) => {
  let chemin;
  try { chemin = decodeURIComponent(new URL(req.url, SITE).pathname); } catch (e) { return repondre(res, 400, 'text/plain', 'requête invalide'); }
  if (chemin.endsWith('/')) chemin += 'index.html';
  if (PUBLIES_JAMAIS.test(chemin)) return repondre(res, 404, 'text/plain; charset=utf-8', 'non publié');
  const fichier = path.resolve(RACINE, '.' + chemin);
  if (!fichier.startsWith(RACINE + path.sep)) return repondre(res, 403, 'text/plain', 'interdit');
  fs.readFile(fichier, (err, donnees) => {
    if (err) return repondre(res, 404, 'text/html; charset=utf-8', fs.existsSync(path.join(RACINE, '404.html')) ? fs.readFileSync(path.join(RACINE, '404.html')) : '404');
    const ext = path.extname(fichier).toLowerCase();
    if (chemin === '/assets/js/config.js') return repondre(res, 200, TYPES['.js'], donnees.toString('utf8') + SURCHARGE);
    if (ext === '.html') {
      // La base de production disparaît de la politique de contenu : seule la préproduction est joignable.
      return repondre(res, 200, TYPES['.html'], donnees.toString('utf8').split(HOTE_PROD).join(CFG.hote));
    }
    repondre(res, 200, TYPES[ext] || 'application/octet-stream', donnees);
  });
});

serveur.listen(PORT, '127.0.0.1', () => {
  console.log('Préproduction : ' + SITE + '  →  ' + CFG.supabaseUrl + '  (Ctrl+C pour arrêter)');
});
