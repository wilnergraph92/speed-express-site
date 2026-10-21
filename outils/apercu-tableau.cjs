/* Aperçu local du tableau de bord (jamais publié : outils/ est retiré par le déploiement).
   Le site servi tel quel, SAUF deux fichiers remplacés à la volée, pour regarder le centre de commande dans un navigateur sans base :
   - config.js : aucune clé Supabase (le site passe en démonstration, rien ne part vers la production), interrupteur centreNoyau allumé ;
   - ses-api.js : suivi des mêmes réponses que l'essai tableau-browser.mjs — le compte et l'ancien schéma de accessibilite-browser.mjs,
     le noyau nourri par les réponses RÉELLES de la base d'essai (outils/tests/tableau-exemples.json, écrites par logistique-tableau-essai.py ;
     l'analytique : analytique-complete-exemples.json, écrites par logistique-analytique-complete-essai.py).
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
  var AN = fs.readFileSync(path.join(RACINE, 'outils/tests/analytique-complete-exemples.json'), 'utf8');
  var CN = fs.readFileSync(path.join(RACINE, 'outils/tests/colis-noyau-exemples.json'), 'utf8');
  var EC = fs.readFileSync(path.join(RACINE, 'outils/tests/expedition-confirmes-exemples.json'), 'utf8');
  var MS = fs.readFileSync(path.join(RACINE, 'outils/tests/messagerie-exemples.json'), 'utf8');
  var RE = fs.readFileSync(path.join(RACINE, 'outils/tests/rapport-expedition-exemples.json'), 'utf8');
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
    "   if (vue === 'livraisons') return Promise.resolve({ total: 1, filters: {}, delayed: 0, by_stage: { scheduled: 1 }, items: [{ kind: 'TASK', ref_id: 'm1', number: 'DEL-1A2B3C4D',\n" +
    "     customer_code: 'SES-43521', customer_name: 'Marie', address: '12 rue Lamarre, Pétion-Ville', date: '2026-10-14', window_start: null, window_end: null, task_status: 'CREATED',\n" +
    "     request_status: null, stage: 'scheduled', driver: null, priority: 3, delayed: false, parcels: 2, created_at: '2026-10-14T13:00:00Z' }] });\n" +
    "   if (vue === 'consolidations') return Promise.resolve({ total: 3, filters: {}, items: [\n" +
    "     { consolidation_id: 'k1', code: 'CONS-20261014-0900', status: 'OPEN', mode: 'air', destination_country: 'HT', warehouse: 'MIA · Miami', parcels: 3, customers: 2, weight_lb: 21,\n" +
    "       shipment: null, load_unit: null, opened_at: '2026-10-14T13:00:00Z', closed_at: null },\n" +
    "     { consolidation_id: 'k2', code: 'CONS-20261013-1600', status: 'CLOSED', mode: 'air', destination_country: 'HT', warehouse: 'MIA · Miami', parcels: 5, customers: 4, weight_lb: 38,\n" +
    "       shipment: null, load_unit: null, opened_at: '2026-10-13T20:00:00Z', closed_at: '2026-10-13T22:00:00Z' },\n" +
    "     { consolidation_id: 'k3', code: 'CONS-20261012-1000', status: 'CLOSED', mode: 'air', destination_country: 'HT', warehouse: 'MIA · Miami', parcels: 6, customers: 3, weight_lb: 52,\n" +
    "       shipment: null, load_unit: { load_unit_id: 'u1', code: 'PAL-0042', kind: 'PALLET', status: 'OPEN' }, opened_at: '2026-10-12T14:00:00Z', closed_at: '2026-10-12T18:00:00Z' }] });\n" +
    "   return Promise.resolve({ total: 0, items: [], filters: {} }); };\n" +
    // les unités logistiques, le transbordement, les colis d'une consolidation : de quoi voir les écrans
    " A.tableau.unites = function () { return Promise.resolve({ total: 2, filters: {}, items: [\n" +
    "   { load_unit_id: 'u1', code: 'PAL-0042', kind: 'PALLET', status: 'OPEN', seal_number: null, sealed_at: null, opened_reason: null, max_weight_lb: 2000, max_volume_ft3: null,\n" +
    "     mode: 'air', destination_country: 'HT', consolidations: [{ consolidation_id: 'k3', code: 'CONS-20261012-1000', status: 'CLOSED' }], parcels: 6, weight_lb: 52, volume_ft3: 0,\n" +
    "     shipment: null, created_at: '2026-10-12T19:00:00Z' },\n" +
    "   { load_unit_id: 'u2', code: 'ULD-AKE12345', kind: 'ULD', status: 'SEALED', seal_number: 'SL-0001', sealed_at: '2026-10-11T19:00:00Z', opened_reason: null, max_weight_lb: 3500,\n" +
    "     max_volume_ft3: 150, mode: 'air', destination_country: 'HT', consolidations: [{ consolidation_id: 'k4', code: 'CONS-20261010-0800', status: 'CLOSED' }], parcels: 12, weight_lb: 140,\n" +
    "     volume_ft3: 30, shipment: { shipment_id: 's1', code: 'EXP-20261014-0900', status: 'DRAFT' }, created_at: '2026-10-11T12:00:00Z' }] }); };\n" +
    " A.tableau.colisConsolidation = function () { return Promise.resolve([{ parcel_id: 'p4', tracking_number: 'SES-7744112233', status: 'CONSOLIDATION_PENDING', weight_lb: 7,\n" +
    "   destination_city: 'Jacmel', customer: { code: 'SES-43521', name: 'Marie' }, added_at: '2026-10-14T13:05:00Z' }]); };\n" +
    " A.tableau.remplirConsolidation = function () { return Promise.resolve({ consolidation_id: 'k1', added: 1, parcels: 4, results: [{ code: 'SES-1029384756', added: true, reason: null, status: 'CONSOLIDATION_PENDING' },\n" +
    "   { code: 'SES-0000000000', added: false, reason: 'NOT_FOUND', status: null }, { code: 'SES-5566778899', added: false, reason: 'OTHER_COUNTRY', status: 'CONSOLIDATION_PENDING' }] }); };\n" +
    " A.tableau.attenteTransbordement = function () { return Promise.resolve([{ parcel_id: 'p5', tracking_number: 'SES-3141592653', mode: 'sea', weight_lb: 22, destination_country: 'HT',\n" +
    "   destination_city: 'Port-au-Prince', customer: { code: 'SES-10001', name: 'Jean' }, hub: { branch_id: 'b3', code: 'SDQ-HUB', country: 'DO' },\n" +
    "   from_shipment: { shipment_id: 's9', code: 'EXP-20261010-1400', status: 'ARRIVED' } }]); };\n" +
    " A.tableau.attenteHub = function () { return Promise.resolve([{ parcel_id: 'p3', tracking_number: 'SES-5566778899', weight_lb: 4, destination_country: 'HT', destination_city: 'Pétion-Ville',\n" +
    "   hub: { branch_id: 'b2', code: 'PAP-HUB' }, warehouse: 'PAP-1', customer: { customer_id: 'c1', code: 'SES-43521', name: 'Marie', phone: '+509 3700 0000', address: '12 rue Lamarre', city: 'Pétion-Ville' } }]); };\n" +
    " A.tableau.classerChauffeurs = function () { return Promise.resolve([{ driver_id: 'd1', eligible: true, score: 0.9, reasons: [] }]); };\n" +
    " A.tableau.missionsDuJour = function () { return Promise.resolve([{ task_id: 'm2', kind: 'DELIVERY', status: 'ACCEPTED', driver_id: 'd1', address: '3 rue Capois', weight_lb: 6, trip_id: null }]); };\n" +
    // la fiche d'une expédition et ce qui peut partir : de quoi voir les écrans, rien ne part nulle part
    " A.tableau.ficheExpedition = function () { return Promise.resolve({ shipment_id: 's1', code: 'EXP-20261014-0900', mode: 'air', status: 'DRAFT', origin: { code: 'MIA', label: 'Miami', country: 'US' },\n" +
    "   destination: { code: 'PAP-HUB', label: 'Hub Port-au-Prince', country: 'HT' }, hub_warehouse: null, planned_departure_at: null, planned_arrival_at: null, transport: null, customs: null }); };\n" +
    " A.tableau.colisExpedition = function () { return Promise.resolve([{ parcel_id: 'p1', tracking_number: 'SES-4821937065', status: 'CONSOLIDATED', customer: { code: 'SES-43521', name: 'Marie' },\n" +
    "   weight_lb: 8, destination_country: 'HT', destination_city: 'Pétion-Ville' }]); };\n" +
    " A.tableau.pret = function () { return Promise.resolve({ parcels: [{ parcel_id: 'p2', tracking_number: 'SES-1029384756', mode: 'air', customer: { code: 'SES-10001', name: 'Jean' }, weight_lb: 6.5,\n" +
    "   destination_country: 'HT', destination_city: 'Cap-Haïtien', warehouse: 'MIA-1' }], consolidations: [{ consolidation_id: 'k2', code: 'CONS-20261013-1600', mode: 'air',\n" +
    "   destination_country: 'HT', parcels: 5, weight_lb: 38 }], load_units: [{ load_unit_id: 'u1', code: 'PAL-0042', kind: 'PALLET', status: 'OPEN', seal_number: null, mode: 'air',\n" +
    "   destination_country: 'HT', consolidations: 1, parcels: 6, weight_lb: 52 }] }); };\n" +
    " ['creerChauffeur', 'modifierChauffeur', 'statutChauffeur', 'vehiculeChauffeur', 'creerVehicule', 'statutVehicule', 'creerAgence', 'modifierAgence', 'creerEntrepot', 'modifierEntrepot',\n" +
    "  'creerEmplacement', 'emplacementActif', 'preparer', 'creerExpedition', 'planifierExpedition', 'expeditionPrete', 'rouvrirExpedition', 'partir', 'enTransit', 'arrivee',\n" +
    "  'commencerDouane', 'fixerDroits', 'droitsPayes', 'libererDouane', 'rejeterDouane', 'recevoirHub', 'cloturerExpedition', 'annulerExpedition', 'creerTransport', 'replanifierTransport',\n" +
    "  'creerLivraison', 'remettre', 'affecter', 'affecterAuto', 'codeLivraison', 'replanifierMission', 'annulerMission', 'creerTournee', 'annulerTournee',\n" +
    "  'ouvrirConsolidation', 'retirerDeConsolidation', 'fermerConsolidation', 'creerUnite', 'chargerUnite', 'retirerDeUnite', 'scellerUnite', 'ouvrirUnite', 'etapeSuivante'].forEach(function (m) { A.tableau[m] = function () { return Promise.resolve({}); }; });\n" +
    ' var r = function (x) { return function () { return Promise.resolve(JSON.parse(JSON.stringify(x))); }; };\n' +
    ' A.tableau.sites = r(EX.sites || { branches: [], can_manage: true });\n' +
    ' A.tableau.acces = r(EX.acces); A.tableau.commande = r(EX.commande); A.tableau.vehicules = r(EX.vehicules); A.tableau.tournees = r(EX.tournees); A.tableau.depenses = r(EX.depenses);\n' +
    ' A.tableau.pointages = r(EX.pointages); A.tableau.detailPointage = r(EX.pointage); A.tableau.maJournee = r(EX.journee); A.tableau.releve = r(EX.releve); A.tableau.mesMissions = r(EX.missions);\n' +
    // l'analytique (029) : les réponses réelles de logistique-analytique-complete-essai.py, quel que soit le rapport demandé
    ' var AN = ' + AN + ';\n' +
    ' A.analytique.rapport = function (g) { return r(g === \'day\' ? AN.rapport_jour : AN.rapport_semaine)(); }; A.analytique.indicateurs = r(AN.indicateurs);\n' +
    ' A.analytique.executions = r(AN.executions); A.analytique.alertes = r(AN.alertes); A.analytique.verifier = r(AN.verification); A.analytique.recalculer = r(AN.recalcul);\n' +
    ' A.analytique.acquitter = r(AN.acquittement);\n' +
    // « ?colis=noyau » : l'interrupteur colisNoyau simulé, nourri par les réponses réelles de logistique-colis-noyau-essai.py (rien ne part)
    // les colis confirmés de la fenêtre « Nouvelle expédition » (031), tels que la base les rend
    ' var EC = ' + EC + '; var pretAvant = A.tableau.pret; A.tableau.pret = function () { return pretAvant.apply(null, arguments).then(function (d) {\n' +
    '   d = JSON.parse(JSON.stringify(d)); d.confirmed = JSON.parse(JSON.stringify(EC.fenetre.confirmed)); return d; }); };\n' +
    ' A.tableau.creerExpeditionPreparee = r(EC.creation);\n' +
    // le rapport d'une expédition (034) : la réponse réelle de logistique-rapport-expedition-essai.py
    ' var RE = ' + RE + '; A.tableau.rapportExpedition = r(RE.rapport);\n' +
    // la messagerie (032) : les réponses réelles de logistique-messagerie-essai.py ; un envoi ne part nulle part, une photo est un dessin
    ' var MS = ' + MS + '; var M = A.messagerie = {};\n' +
    ' M.boite = r(MS.inbox_direction); M.nonLus = r(MS.unread); M.annuaire = function (q) { return r(q ? MS.directory_clients : MS.directory)(); }; M.envoyer = r(MS.send); M.marquerLu = r(MS.mark_read);\n' +
    ' M.ouvrirDirect = r(MS.open); M.ouvrirClient = r(MS.open); M.creerGroupe = r(MS.group_create); M.modifierGroupe = r(MS.group_update);\n' +
    ' M.messages = function (c) { var g = MS.messages_groupe.conversation.conversation_id === c; return r(g ? MS.messages_groupe : MS.messages_equipe)(); };\n' +
    ' M.deposerPhoto = function (c) { return Promise.resolve(c + \'/apercu.jpg\'); }; M.surveiller = function () { return function () {}; };\n' +
    " M.adressePhoto = function () { return Promise.resolve('data:image/svg+xml,' + encodeURIComponent('<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"320\" height=\"200\"><rect width=\"320\" height=\"200\" fill=\"%23d8dde5\"/></svg>')); };\n" +
    ' var CN = ' + CN + ';\n' +
    ' if (/colis=noyau/.test(location.search)) { A.colisNoyau = true; A.admin.etapesColis = r(CN.etapes_direction);\n' +
    '   A.admin.avancerColis = r(CN.avancement); A.admin.annulerColis = r(CN.annulation);\n' +
    "   A.tableau.sites = r({ can_manage: true, branches: [{ branch_id: 'b1', code: 'MIA', name: 'Miami', kind: 'office', country: 'US', city: 'Miami', active: true,\n" +
    "     warehouses: [{ warehouse_id: 'w1', code: 'MIA-1', name: 'Entrepôt Miami', active: true, locations: [{ location_id: 'l1', code: 'A-01', zone: 'Réception', kind: 'storage', active: true }] }] }] }); }\n" +
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
