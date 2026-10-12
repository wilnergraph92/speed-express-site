#!/usr/bin/env node
// La sonde de disponibilité de la production : LECTURE SEULE, clé PUBLIQUE, aucun compte, aucun secret.
//   node scripts/surveillance/sonder.mjs [--rapport rapport.json]
// Lancée toutes les 15 minutes par .github/workflows/surveillance.yml ; code de sortie 1 si un contrôle CRITIQUE échoue
// (le workflow ouvre alors un ticket « alerte-production » et GitHub prévient le propriétaire).
//
// Contrôles :
//   critique  le site publié répond (accueil, tableau de bord, configuration) ;
//   critique  l'authentification Supabase répond ;
//   critique  la base répond par l'API publique : le suivi d'un numéro qui n'existe pas rend « rien » (et non une erreur) ;
//   critique  AUCUNE table ni vue n'est lisible sans connexion (une règle de sécurité perdue serait une fuite de données) ;
//   alerte    les fonctions internes restent fermées aux visiteurs (est_admin… : ouvertes tant que supabase-maj.sql §10
//             n'est pas collé — l'alerte le rappelle sans réveiller personne) ;
//   info      la santé du noyau (ses_health, étape 013) : absente tant que le noyau n'est pas installé ; présente, elle doit dire « ok ».
// Chaque contrôle est retenté deux fois, à 10 s d'intervalle : une seconde de réseau perdue ne déclenche pas d'alerte.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const RACINE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
export const SITE = 'https://wilnergraph92.github.io/speed-express-site';
export const TABLES = ['clients', 'colis', 'colis_historique', 'factures', 'prealertes', 'appareils', 'matricules_attribues', 'colis_details', 'factures_details'];
// Fonctions internes, inoffensives à appeler (elles ne lisent ni n'écrivent de données) : elles ne doivent répondre qu'à la base.
export const FONCTIONS_INTERNES = { est_admin: {}, a_droit: { p_droit: 'colis.lire' }, texte_notification: { p_statut: 'livre', p_langue: 'fr' }, prefixe_matricule: { p_role: 'admin' } };

export function configuration(texte) {
  const url = (texte.match(/supabaseUrl:\s*'([^']+)'/) || [])[1];
  const cle = (texte.match(/supabaseKey:\s*'([^']+)'/) || [])[1];
  if (!url || !/^sb_publishable_/.test(cle || '')) throw new Error('config.js : URL ou clé publique introuvable');
  return { url, cle };
}

async function essayer(fn, { essais = 3, attendre }) {
  let dernier;
  for (let i = 0; i < essais; i++) {
    try { return await fn(); } catch (e) { dernier = e; if (i < essais - 1) await attendre(10000); }
  }
  throw dernier;
}

export async function sonder({ fetch, site = SITE, url, cle, attendre = (ms) => new Promise((r) => setTimeout(r, ms)), essais = 3 }) {
  const resultats = [];
  const entetes = { apikey: cle, Authorization: 'Bearer ' + cle };
  const appeler = async (u, options = {}) => {
    const r = await fetch(u, { ...options, signal: AbortSignal.timeout(15000) });
    return { code: r.status, texte: await r.text() };
  };
  async function controle(nom, gravite, fn) {
    const debut = Date.now();
    try {
      const detail = await essayer(fn, { essais, attendre });
      resultats.push({ nom, gravite, ok: true, detail: detail || '', ms: Date.now() - debut });
    } catch (e) {
      resultats.push({ nom, gravite, ok: false, detail: String(e && e.message || e).slice(0, 300), ms: Date.now() - debut });
    }
  }

  for (const [page, marque] of [['/', 'Speed Express'], ['/tableau-de-bord.html', 'tableau'], ['/assets/js/config.js', 'supabaseUrl']]) {
    await controle('site ' + page, 'critique', async () => {
      const r = await appeler(site + page);
      if (r.code !== 200) throw new Error('HTTP ' + r.code);
      if (!r.texte.toLowerCase().includes(marque.toLowerCase())) throw new Error('contenu inattendu (« ' + marque + ' » absent)');
      return 'HTTP 200';
    });
  }
  await controle('authentification Supabase', 'critique', async () => {
    const r = await appeler(url + '/auth/v1/health', { headers: entetes });
    if (r.code !== 200) throw new Error('HTTP ' + r.code + ' ' + r.texte.slice(0, 120));
    return 'HTTP 200';
  });
  await controle('base de données (suivi public)', 'critique', async () => {
    const r = await appeler(url + '/rest/v1/rpc/suivre_colis', { method: 'POST', headers: { ...entetes, 'Content-Type': 'application/json' },
      body: JSON.stringify({ p_numero: 'SES-0000000000' }) });
    if (r.code !== 200) throw new Error('HTTP ' + r.code + ' ' + r.texte.slice(0, 160));
    if (r.texte.trim() !== 'null') throw new Error('réponse inattendue pour un numéro inexistant : ' + r.texte.slice(0, 80));
    return 'répond, rien pour un numéro inexistant';
  });
  await controle('aucune donnée lisible sans connexion', 'critique', async () => {
    const ouvertes = [];
    for (const t of TABLES) {
      const r = await appeler(url + '/rest/v1/' + t + '?select=*&limit=1', { headers: entetes });
      if (r.code === 200) ouvertes.push(t);
      else if (![401, 403, 404].includes(r.code)) throw new Error(t + ' : HTTP ' + r.code + ' (base injoignable ?)');
    }
    if (ouvertes.length) throw new Error('LISIBLES PAR UN VISITEUR : ' + ouvertes.join(', '));
    return TABLES.length + ' tables et vues refusées';
  });
  await controle('fonctions internes fermées aux visiteurs', 'alerte', async () => {
    const ouvertes = [];
    for (const [f, args] of Object.entries(FONCTIONS_INTERNES)) {
      const r = await appeler(url + '/rest/v1/rpc/' + f, { method: 'POST', headers: { ...entetes, 'Content-Type': 'application/json' }, body: JSON.stringify(args) });
      if (r.code === 200) ouvertes.push(f);
    }
    if (ouvertes.length) throw new Error('encore appelables : ' + ouvertes.join(', ') + ' (supabase-maj.sql §10 et supabase-maj-securite.sql à coller)');
    return 'fermées';
  });
  await controle('santé du noyau (ses_health)', 'info', async () => {
    const r = await appeler(url + '/rest/v1/rpc/ses_health', { method: 'POST', headers: { ...entetes, 'Content-Type': 'application/json' }, body: '{}' });
    if (r.code === 404 || /PGRST202/.test(r.texte)) return 'noyau non installé (étape 013 absente)';
    if (r.code !== 200) throw new Error('HTTP ' + r.code);
    const etat = JSON.parse(r.texte);
    if (etat.status !== 'ok') throw new Error('état « ' + etat.status + ' »');
    return 'ok, étape ' + etat.schema_level;
  });
  // La santé du noyau devient critique une fois installée : un « fail » de ses_health réveille alors le propriétaire.
  const sante = resultats[resultats.length - 1];
  if (!sante.ok && !/non installé/.test(sante.detail)) sante.gravite = 'critique';
  return resultats;
}

export function bilan(resultats) {
  const critiques = resultats.filter((r) => !r.ok && r.gravite === 'critique');
  const alertes = resultats.filter((r) => !r.ok && r.gravite !== 'critique');
  const lignes = ['| Contrôle | Gravité | État | Détail |', '|---|---|---|---|'];
  for (const r of resultats) lignes.push('| ' + r.nom + ' | ' + r.gravite + ' | ' + (r.ok ? 'OK' : 'ÉCHEC') + ' | ' + r.detail.replace(/\|/g, '/') + ' |');
  return { etat: critiques.length ? 'panne' : alertes.length ? 'alerte' : 'ok', critiques: critiques.length, alertes: alertes.length, tableau: lignes.join('\n') };
}

async function principal() {
  const { url, cle } = configuration(fs.readFileSync(path.join(RACINE, 'assets', 'js', 'config.js'), 'utf8'));
  const resultats = await sonder({ fetch: globalThis.fetch, url, cle });
  const b = bilan(resultats);
  const i = process.argv.indexOf('--rapport');
  if (i > 0) fs.writeFileSync(process.argv[i + 1], JSON.stringify({ quand: new Date().toISOString(), ...b, resultats }, null, 2));
  for (const r of resultats) console.log(JSON.stringify({ quand: new Date().toISOString(), ...r }));
  if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, '## Surveillance de la production : ' + b.etat + '\n\n' + b.tableau + '\n');
  process.exit(b.critiques ? 1 : 0);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) principal().catch((e) => { console.error(e); process.exit(1); });
