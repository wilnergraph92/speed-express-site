/* Aperçu local du tableau de bord (jamais publié : outils/ est retiré par le déploiement).
   Le site servi tel quel, SAUF deux fichiers remplacés à la volée, pour regarder le centre de commande dans un navigateur sans base :
   - config.js : aucune clé Supabase (le site passe en démonstration, rien ne part vers la production), interrupteur centreNoyau allumé ;
   - ses-api.js : suivi des mêmes réponses que l'essai tableau-browser.mjs — le compte et l'ancien schéma de accessibilite-browser.mjs,
     le noyau nourri par les réponses RÉELLES de la base d'essai (outils/tests/tableau-exemples.json, écrites par logistique-tableau-essai.py).
   Ajouter « ?noyau=absent » à l'adresse montre la production d'aujourd'hui : la barre des 26 modules et les écrans « Bientôt disponible ».
   node outils/apercu-tableau.cjs  →  http://localhost:8767/tableau-de-bord.html */
'use strict';
var http = require('http');
var fs = require('fs');
var path = require('path');

var RACINE = path.resolve(__dirname, '..');
var PORT = Number(process.env.PORT) || 8767;
var TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml', '.json': 'application/json', '.webmanifest': 'application/manifest+json',
  '.woff2': 'font/woff2', '.ico': 'image/x-icon', '.txt': 'text/plain; charset=utf-8' };

/* Relu à chaque demande : une retouche d'un essai ou d'un fichier du site se voit au rechargement, sans relancer le serveur. */
function fixture() {
  var ancien = /const fixture = `([\s\S]*?)`;/.exec(fs.readFileSync(path.join(RACINE, 'outils/tests/accessibilite-browser.mjs'), 'utf8'));
  if (!ancien) throw new Error('fixture introuvable dans accessibilite-browser.mjs');
  var EX = fs.readFileSync(path.join(RACINE, 'outils/tests/tableau-exemples.json'), 'utf8');
  return 'if (/noyau=absent/.test(location.search)) window.__noyauAbsent = true;\n' + ancien[1] + '\n(function () {\n var EX = ' + EX + ';\n var A = SES_API;\n' +
    ' A.notifications = A.notifications || {}; A.notifications.surveiller = function () { return function () {}; };\n' +
    " A.centre.disponible = function () { return Promise.resolve({ actif: true, acces: { sections: ['commande', 'flux', 'colis', 'expeditions', 'entrepot', 'consolidations', 'transport', 'chauffeurs',\n" +
    "   'enlevements', 'livraisons', 'douane', 'incidents', 'notifications', 'clients', 'support', 'facturation', 'paiements', 'utilisateurs', 'audit', 'parametres'],\n" +
    '   role: \'admin\', direction: true, ops: true, finance: true, customers: true, today: EX.acces.today } }); };\n' +
    " A.centre.entrepot = function () { return Promise.resolve({ warehouses: [{ warehouse_id: 'w1', code: 'PAP-1', name: 'Entrepôt Port-au-Prince' }] }); };\n" +
    // Un chauffeur et deux membres d'équipe d'exemple : de quoi ouvrir les formulaires du parc (ajouter, modifier), qui ne partent nulle part.
    " A.centre.liste = function (vue) {\n" +
    "   if (vue === 'chauffeurs') return Promise.resolve({ total: 1, filters: {}, items: [{ driver_id: 'd1', name: 'Jean-Marc Étienne', phone: '+509 3700 0000', status: 'ACTIVE',\n" +
    "     vehicle: 'AB-1234', zones: ['PAP-1'], tasks_today: 4, tasks_open: 2, completed_today: 2, failed_today: 0, position_age_min: null, available_today: true }] });\n" +
    "   if (vue === 'utilisateurs') return Promise.resolve({ total: 2, filters: {}, items: [{ user_id: 'u1', email: 'livreur@exemple.test', role: 'employee', active: true, driver: false },\n" +
    "     { user_id: 'u2', email: 'jean-marc@exemple.test', role: 'employee', active: true, driver: true }] });\n" +
    "   return Promise.resolve({ total: 0, items: [], filters: {} }); };\n" +
    " ['creerChauffeur', 'modifierChauffeur', 'statutChauffeur', 'vehiculeChauffeur', 'creerVehicule', 'statutVehicule', 'creerAgence', 'modifierAgence', 'creerEntrepot', 'modifierEntrepot',\n" +
    "  'creerEmplacement', 'emplacementActif'].forEach(function (m) { A.tableau[m] = function () { return Promise.resolve({}); }; });\n" +
    ' var r = function (x) { return function () { return Promise.resolve(JSON.parse(JSON.stringify(x))); }; };\n' +
    ' A.tableau.sites = r(EX.sites || { branches: [], can_manage: true });\n' +
    ' A.tableau.acces = r(EX.acces); A.tableau.commande = r(EX.commande); A.tableau.vehicules = r(EX.vehicules); A.tableau.tournees = r(EX.tournees); A.tableau.depenses = r(EX.depenses);\n' +
    ' A.tableau.pointages = r(EX.pointages); A.tableau.detailPointage = r(EX.pointage); A.tableau.maJournee = r(EX.journee); A.tableau.releve = r(EX.releve); A.tableau.mesMissions = r(EX.missions);\n' +
    " if (window.__noyauAbsent) { A.centre.disponible = function () { return Promise.resolve({ actif: false, raison: 'ferme' }); }; A.tableau.acces = function () { return Promise.reject(new Error('fonction absente')); }; }\n" +
    '})();\n';
}

http.createServer(function (req, res) {
  var chemin;
  try { chemin = decodeURIComponent(req.url.split('?')[0]); } catch (e) { res.writeHead(400); return res.end(); }
  if (chemin.endsWith('/')) chemin += 'index.html';
  var fichier = path.normalize(path.join(RACINE, chemin));
  // Jamais hors du dépôt, et jamais les fichiers de travail (outils/, docs/, .git…) : seulement ce qui serait publié.
  if (!fichier.startsWith(RACINE + path.sep) || /^[\\/](outils|docs|scripts|\.git|\.github|\.claude)([\\/]|$)/.test(chemin)) { res.writeHead(403); return res.end('non'); }
  var entete = { 'Cache-Control': 'no-store', 'Content-Type': TYPES[path.extname(fichier).toLowerCase()] || 'application/octet-stream' };
  if (/\/assets\/js\/config\.js$/.test(chemin)) { res.writeHead(200, entete); return res.end('window.SES_CONFIG = { centreNoyau: true };\n'); }
  fs.readFile(fichier, 'utf8', function (err, contenu) {
    if (err) {
      fs.readFile(fichier, function (err2, brut) {
        if (err2) { res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); return res.end('introuvable'); }
        res.writeHead(200, entete); res.end(brut);
      });
      return;
    }
    if (/\/assets\/js\/ses-api\.js$/.test(chemin)) {
      try { contenu += '\n' + fixture(); } catch (e) { res.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' }); return res.end(String(e.message)); }
    }
    if (/\.(html|js|css|json|svg|txt|webmanifest)$/.test(fichier)) { res.writeHead(200, entete); return res.end(contenu); }
    fs.readFile(fichier, function (err3, brut) { res.writeHead(200, entete); res.end(brut); });
  });
}).listen(PORT, '127.0.0.1', function () {
  console.log('Aperçu du tableau de bord (démonstration, aucune base) : http://localhost:' + PORT + '/tableau-de-bord.html');
  console.log('La production d\'aujourd\'hui (noyau absent) : http://localhost:' + PORT + '/tableau-de-bord.html?noyau=absent');
});
