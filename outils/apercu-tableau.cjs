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
    "   if (vue === 'expeditions') return Promise.resolve({ total: 1, filters: {}, by_status: { DRAFT: 1 }, items: [{ shipment_id: 's1', transport_id: null, code: 'EXP-20261014-0900', mode: 'air', status: 'DRAFT',\n" +
    "     origin: 'MIA · Miami', destination: 'PAP-HUB · Hub Port-au-Prince', transport: null, parcels: 2, weight_lb: 14.5, dispatched_at: null, arrived_at: null, created_at: '2026-10-14T13:00:00Z' }] });\n" +
    "   if (vue === 'transport') return Promise.resolve({ total: 1, filters: {}, items: [{ transport_id: 't1', reference: 'AWB-123-45678901', voyage_number: '2Q-101', carrier: 'Sunrise Airways', mode: 'air',\n" +
    "     status: 'PLANNED', origin: 'MIA · Miami', destination: 'PAP-HUB · Hub Port-au-Prince', planned_departure_at: '2026-10-15T12:00:00Z', actual_departure_at: null,\n" +
    "     planned_arrival_at: '2026-10-15T16:00:00Z', actual_arrival_at: null, late: false, shipments: 0, capacity_weight_lb: 500, capacity_volume_ft3: null, load_weight_lb: 0 }] });\n" +
    "   return Promise.resolve({ total: 0, items: [], filters: {} }); };\n" +
    // la fiche d'une expédition et ce qui peut partir : de quoi voir les écrans, rien ne part nulle part
    " A.tableau.ficheExpedition = function () { return Promise.resolve({ shipment_id: 's1', code: 'EXP-20261014-0900', mode: 'air', status: 'DRAFT', origin: { code: 'MIA', label: 'Miami', country: 'US' },\n" +
    "   destination: { code: 'PAP-HUB', label: 'Hub Port-au-Prince', country: 'HT' }, hub_warehouse: null, planned_departure_at: null, planned_arrival_at: null, transport: null, customs: null }); };\n" +
    " A.tableau.colisExpedition = function () { return Promise.resolve([{ parcel_id: 'p1', tracking_number: 'SES-4821937065', status: 'CONSOLIDATED', customer: { code: 'SES-43521', name: 'Marie' },\n" +
    "   weight_lb: 8, destination_country: 'HT', destination_city: 'Pétion-Ville' }]); };\n" +
    " A.tableau.pret = function () { return Promise.resolve({ parcels: [{ parcel_id: 'p2', tracking_number: 'SES-1029384756', mode: 'air', customer: { code: 'SES-10001', name: 'Jean' }, weight_lb: 6.5,\n" +
    "   destination_country: 'HT', destination_city: 'Cap-Haïtien', warehouse: 'MIA-1' }], consolidations: [] }); };\n" +
    " ['creerChauffeur', 'modifierChauffeur', 'statutChauffeur', 'vehiculeChauffeur', 'creerVehicule', 'statutVehicule', 'creerAgence', 'modifierAgence', 'creerEntrepot', 'modifierEntrepot',\n" +
    "  'creerEmplacement', 'emplacementActif', 'preparer', 'creerExpedition', 'planifierExpedition', 'expeditionPrete', 'rouvrirExpedition', 'partir', 'enTransit', 'arrivee',\n" +
    "  'commencerDouane', 'fixerDroits', 'droitsPayes', 'libererDouane', 'rejeterDouane', 'recevoirHub', 'cloturerExpedition', 'annulerExpedition', 'creerTransport', 'replanifierTransport'].forEach(function (m) { A.tableau[m] = function () { return Promise.resolve({}); }; });\n" +
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
