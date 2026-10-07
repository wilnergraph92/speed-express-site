// Le prix saisi à la main et les pré-alertes, côté site (assets/js/ses-api.js), contre la base décrite par
// outils/supabase-maj-prix-prealertes.sql. Aucune dépendance, aucun réseau.
//
// Ce qu'on éprouve : (1) trois implémentations, mêmes méthodes ; le site fermé répond « fermé » ; (2) en ligne : la bonne table,
// les filtres, une recherche qui ne peut pas casser le filtre PostgREST, et SEULEMENT les colonnes que la base laisse écrire
// (lues dans le « grant » du fichier SQL) ; les erreurs SE003 / SE004 / 42P01 ont leur message ; (3) en démonstration : mêmes
// règles que la base (le client crée les siennes, 30 par 24 h, l'équipe lit avec colis.lire, traite avec colis.statut, un colis
// relié appartient au même client) ; le prix saisi fait la facture, et l'effacer revient à poids × tarif.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');

let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };
const rejet = async (p) => { try { await p; } catch (e) { return e.code; } return 'aucune-erreur'; };
function charger(config, hote, extra) {
  const bac = Object.assign({ window: { addEventListener: () => {}, SES_CONFIG: config },
    location: { protocol: hote === 'localhost' ? 'http:' : 'https:', hostname: hote, href: 'https://' + hote + '/x.html', pathname: '/x.html', origin: 'https://' + hote },
    document: { documentElement: { lang: 'fr' }, currentScript: null }, console, Promise, URL, setTimeout, clearTimeout, btoa, atob, TextEncoder, TextDecoder }, extra || {});
  vm.runInNewContext(fs.readFileSync('assets/js/ses-api.js', 'utf8'), bac);
  return bac.window.SES_API;
}

// Les colonnes que la base laisse écrire, lues dans le fichier SQL lui-même.
const SQL = fs.readFileSync('outils/supabase-maj-prix-prealertes.sql', 'utf8');
const colonnes = (verbe) => new Set(new RegExp('grant ' + verbe + ' \\(([^)]+)\\) on public\\.prealertes to authenticated').exec(SQL)[1].split(',').map((c) => c.trim()));
const INSERTION = colonnes('insert'), MISE_A_JOUR = colonnes('update');

// Un faux client Supabase qui note chaque appel du constructeur de requêtes.
function fauxClient(reponse) {
  const journal = [];
  const requete = (table) => {
    const q = { table, appels: [] };
    journal.push(q);
    const chaine = new Proxy({}, {
      get(_, nom) {
        if (nom === 'then') return (ok, ko) => Promise.resolve(reponse(q)).then(ok, ko);
        return (...args) => { q.appels.push([nom, args]); return chaine; };
      }
    });
    return chaine;
  };
  return { journal, client: { from: requete, auth: { getSession: () => Promise.resolve({ data: { session: { user: { id: 'moi' } } } }) } } };
}

(async () => {
  const cfg = { supabaseUrl: 'https://x.supabase.co', supabaseKey: 'sb_publishable_essai' };
  // ============================================================ 1. trois implémentations
  let reponse = () => ({ data: [], count: 0, error: null });
  const faux = fauxClient((q) => reponse(q));
  const en = charger(cfg, 'exemple.fr', { window: { addEventListener: () => {}, SES_CONFIG: cfg, supabase: { createClient: () => faux.client } } });
  const demo = charger({}, 'localhost'), off = charger({}, 'exemple.fr');
  const M = Array.from(en.METHODES_PREALERTES).sort();
  ok(M.join() === 'creer,disponible,lister,traiter', 'quatre méthodes');
  for (const [nom, api] of [['en ligne', en], ['démonstration', demo], ['fermé', off]]) ok(JSON.stringify(Object.keys(api.prealertes).sort()) === JSON.stringify(M), nom + ' : mêmes méthodes');
  ok(await off.prealertes.disponible() === false && await rejet(off.prealertes.lister({})) === 'ferme', 'site fermé : pas de pré-alertes');
  ok(Array.from(en.STATUTS_PREALERTE).join() === 'attendue,recue,annulee', 'trois statuts');
  const statutsSQL = /statut\s+text not null default 'attendue' check \(statut in \(([^)]+)\)\)/.exec(SQL)[1].replace(/'/g, '').split(/,\s*/);
  ok(statutsSQL.join() === Array.from(en.STATUTS_PREALERTE).join(), 'les statuts du site sont ceux de la base');

  // ============================================================ 2. en ligne
  ok(await en.prealertes.disponible() === true, 'table présente : disponible');
  reponse = () => ({ data: null, error: { code: '42P01', message: 'relation "public.prealertes" does not exist' } });
  ok(await en.prealertes.disponible() === false, 'table absente (mise à jour pas passée) : l\'onglet reste caché');
  ok(await rejet(en.prealertes.lister({})) === 'base-a-mettre-a-jour', '42P01 : « mettre la base à jour »');
  reponse = () => ({ data: [{ id: 'p1' }], count: 41, error: null });
  faux.journal.length = 0;
  const r = await en.prealertes.lister({ statut: 'attendue', recherche: 'TBA,1)*%', page: 1, parPage: 20 });
  const q = faux.journal[0], appel = (nom) => q.appels.filter((a) => a[0] === nom);
  ok(q.table === 'prealertes' && r.total === 41 && r.lignes.length === 1, 'lister : la table des pré-alertes, le total');
  ok(JSON.stringify(appel('eq')[0][1]) === '["statut","attendue"]', 'lister : filtre de statut');
  ok(JSON.stringify(appel('range')[0][1]) === '[20,39]', 'lister : la page 2 de 20');
  const filtre = appel('or')[0][1][0];
  ok((filtre.match(/,/g) || []).length === 2 && !/[()*]/.test(filtre) && (filtre.match(/%/g) || []).length === 6,
    'lister : la recherche ne peut pas casser le filtre (' + filtre + ')');
  reponse = () => ({ data: { id: 'p1', statut: 'recue' }, error: null });
  faux.journal.length = 0;
  await en.prealertes.traiter('p1', { statut: 'recue', note: 'ok', colis_id: 'c1', magasin: 'triche', client_id: 'x' });
  const maj = faux.journal[0].appels.filter((a) => a[0] === 'update')[0][1][0];
  ok(Object.keys(maj).every((k) => MISE_A_JOUR.has(k)) && maj.statut === 'recue' && !('magasin' in maj), 'traiter : seulement les colonnes que la base laisse écrire');
  ok(await rejet(en.prealertes.traiter('p1', { statut: 'perdue' })) === 'statut-inconnu', 'traiter : statut inconnu refusé avant l\'envoi');
  reponse = () => ({ data: null, error: null });
  ok(await rejet(en.prealertes.traiter('p1', { statut: 'annulee' })) === 'non-autorise', 'traiter : aucune ligne touchée = pas le droit');
  reponse = () => ({ data: { id: 'n1' }, error: null });
  faux.journal.length = 0;
  await en.prealertes.creer({ magasin: ' Amazon ', contenu: 'Chaussures', numero_suivi: 'TBA1', valeur: '', service: 'fusee', statut: 'recue', note: 'x' });
  const ins = faux.journal[0].appels.filter((a) => a[0] === 'insert')[0][1][0];
  ok(Object.keys(ins).every((k) => INSERTION.has(k)) && ins.client_id === 'moi' && ins.magasin === 'Amazon' && ins.service === 'aerien' && ins.valeur === null,
    'creer : le compte connecté, des valeurs nettoyées, seulement les colonnes permises (jamais le statut ni la note)');
  for (const [code, attendu] of [['SE003', 'trop-de-demandes'], ['SE004', 'client-invalide'], ['PGRST205', 'base-a-mettre-a-jour'], ['42501', 'non-autorise']]) {
    reponse = () => ({ data: null, error: { code, message: 'x' } });
    ok(await rejet(en.prealertes.creer({ magasin: 'A', contenu: 'B' })) === attendu, code + ' → ' + attendu);
  }

  // ============================================================ 3. démonstration
  const MDP = 'motdepasse1', ids = {};
  const ADMIN = demo.identifiantsAdmin;
  const entrer = (qui) => qui === 'admin' ? demo.connecter(ADMIN.email, ADMIN.motDePasse) : demo.connecter(qui + '@essai.test', MDP);
  for (const nom of ['client', 'autre', 'lecteur', 'agent']) {
    ids[nom] = (await demo.inscrire({ email: nom + '@essai.test', motDePasse: MDP, nom_complet: nom })).profil.id;
    await demo.deconnecter();
  }
  await entrer('admin');
  await demo.admin.definirRole(ids.lecteur, 'employe', ['colis.lire']);
  await demo.admin.definirRole(ids.agent, 'employe', ['colis.lire', 'colis.statut']);
  const colisClient = await demo.admin.creerColis({ client_id: ids.client, description: 'colis', poids_lb: 10, tarif_lb: 4 });
  const colisAutre = await demo.admin.creerColis({ client_id: ids.autre, description: 'autre', poids_lb: 1, tarif_lb: 4 });

  // le prix saisi à la main fait la facture ; l'effacer revient au calcul
  const facture = async (id) => (await demo.admin.factures({ parPage: 100 })).lignes.filter((f) => f.colis_id === id)[0];
  ok(Number((await facture(colisClient.id)).montant) === 50, 'démo : poids × tarif + 10 $');
  await demo.admin.modifierColis(colisClient.id, { prix_manuel: '25' });
  let f = await facture(colisClient.id);
  ok(Number(f.montant) === 35 && f.lignes[0].prix_manuel === true, 'démo : le prix saisi fait la facture (25 + 10)');
  await demo.admin.modifierColis(colisClient.id, { prix_manuel: '' });
  ok(Number((await facture(colisClient.id)).montant) === 50, 'démo : prix effacé, retour à poids × tarif');
  const forfait = await demo.admin.creerColis({ client_id: ids.client, description: 'forfait', poids_lb: 3, tarif_lb: 4, prix_manuel: 40 });
  ok(Number((await facture(forfait.id)).montant) === 50, 'démo : prix saisi dès l\'enregistrement (40 + 10)');

  ok(await demo.prealertes.disponible() === true, 'démo : disponible');
  ok(await rejet(demo.prealertes.creer({ magasin: 'Amazon', contenu: 'X' })) === 'non-autorise', 'démo : l\'équipe ne crée pas de pré-alerte');
  await entrer('client');
  const p1 = await demo.prealertes.creer({ magasin: 'Amazon', contenu: 'Chaussures', numero_suivi: 'tba1', statut: 'recue' });
  ok(p1.statut === 'attendue' && p1.numero_suivi === 'TBA1', 'démo : le client crée la sienne, attendue');
  ok(await rejet(demo.prealertes.creer({ magasin: '', contenu: 'X' })) === 'champ-mal-rempli', 'démo : magasin obligatoire');
  ok(await rejet(demo.prealertes.lister({})) === 'non-autorise', 'démo : un client ne lit pas la liste de l\'équipe');
  ok(await rejet(demo.prealertes.traiter(p1.id, { statut: 'recue' })) === 'non-autorise', 'démo : un client ne traite pas');
  await entrer('autre');
  for (let i = 0; i < 30; i++) await demo.prealertes.creer({ magasin: 'Amazon', contenu: 'Lot ' + i });
  ok(await rejet(demo.prealertes.creer({ magasin: 'Amazon', contenu: 'De trop' })) === 'trop-de-demandes', 'démo : 30 par 24 h et par client');
  await entrer('lecteur');
  const liste = await demo.prealertes.lister({ statut: 'attendue', parPage: 100 });
  ok(liste.total === 31 && liste.lignes.some((x) => x.clients && x.clients.nom_complet === 'client'), 'démo : « colis.lire » voit tout, avec le client');
  ok((await demo.prealertes.lister({ recherche: 'chauss' })).total === 1, 'démo : recherche');
  ok(await rejet(demo.prealertes.traiter(p1.id, { statut: 'recue' })) === 'non-autorise', 'démo : sans « colis.statut », pas de traitement');
  await entrer('agent');
  ok(await rejet(demo.prealertes.traiter(p1.id, { statut: 'recue', colis_id: colisAutre.id })) === 'client-invalide', 'démo : jamais le colis d\'un autre client');
  const traitee = await demo.prealertes.traiter(p1.id, { statut: 'recue', colis_id: colisClient.id, note: 'Arrivé' });
  ok(traitee.statut === 'recue' && traitee.colis_id === colisClient.id, 'démo : « colis.statut » marque reçue et relie le colis');
  ok(await rejet(demo.prealertes.traiter(p1.id, { statut: 'perdue' })) === 'statut-inconnu', 'démo : statut inconnu refusé');

  // les textes de l'onglet existent sur la page (sinon des cellules vides)
  const page = fs.readFileSync('tableau-de-bord.html', 'utf8'), js = fs.readFileSync('assets/js/ses-prealertes.js', 'utf8');
  for (const [, k] of js.matchAll(/UI\.t\('([\w-]*\w)'[,)]/g)) ok(page.includes('data-t="' + k + '"'), 'tableau de bord : texte « ' + k + ' » présent');
  for (const s of Array.from(en.STATUTS_PREALERTE)) ok(page.includes('data-t="pa-statut-' + s + '"'), 'statut ' + s + ' : un nom');
  ok(page.includes('assets/js/ses-prealertes.js?v='), 'le tableau de bord charge ses-prealertes.js');

  console.log('PASS pré-alertes et prix saisi (site) : ' + n + ' vérifications — trois implémentations, colonnes permises par la base, erreurs nommées, démonstration fidèle à la base, textes présents');
})().catch((e) => { console.error(e); process.exit(1); });
