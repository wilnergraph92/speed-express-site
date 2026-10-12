// La sonde de surveillance (scripts/surveillance/sonder.mjs) et son workflow, sans réseau : un faux « fetch » joue chaque situation.
//   node outils/tests/surveillance.cjs
// On exige : tout va bien → « ok » ; le site, l'authentification ou la base tombent → « panne » (code 1) ; une table devient
// lisible sans connexion → « panne » ; des fonctions internes ouvertes → « alerte » seulement ; le noyau absent → info ; installé
// et malade → « panne » ; un incident d'une seconde est absorbé par les nouvelles tentatives. Et le workflow : planifié,
// permissions minimales, aucun secret, la sonde ne fait que lire (aucune méthode d'écriture vers la base).
'use strict';
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };
const RACINE = path.resolve(__dirname, '..', '..');

(async () => {
  const S = await import(path.join(RACINE, 'scripts', 'surveillance', 'sonder.mjs'));
  const URL = 'https://abcdefghijklmnopqrst.supabase.co';
  const cfg = S.configuration(fs.readFileSync(path.join(RACINE, 'assets', 'js', 'config.js'), 'utf8'));
  ok(cfg.cle.startsWith('sb_publishable_') && cfg.url.endsWith('.supabase.co'), 'la sonde lit la clé PUBLIQUE et l\'URL dans config.js');

  // Le monde simulé : chaque situation modifie une réponse.
  function monde(situation = {}) {
    const appels = [];
    let pannesPassageres = situation.passager || 0;
    const fetch = async (u, o = {}) => {
      appels.push({ u, methode: o.method || 'GET', corps: o.body });
      const rep = (code, texte) => ({ status: code, text: async () => texte });
      if (pannesPassageres > 0 && u.endsWith('/auth/v1/health')) { pannesPassageres--; throw new Error('ECONNRESET'); }
      if (u.startsWith(S.SITE)) {
        if (situation.siteEnPanne) return rep(503, 'indisponible');
        if (u.endsWith('config.js')) return rep(200, "supabaseUrl: '" + URL + "'");
        return rep(200, '<title>Speed Express Shipping</title> tableau de bord');
      }
      if (u.endsWith('/auth/v1/health')) return situation.authEnPanne ? rep(503, '') : rep(200, '{"name":"GoTrue"}');
      if (u.endsWith('/rpc/suivre_colis')) return situation.baseEnPanne ? rep(503, 'upstream') : rep(200, 'null');
      if (u.endsWith('/rpc/ses_health')) {
        if (!situation.noyau) return rep(404, '{"code":"PGRST202"}');
        return rep(200, JSON.stringify({ status: situation.noyau, schema_level: 13 }));
      }
      const f = u.match(/\/rpc\/([a-z_]+)$/);
      if (f) return situation.fonctionsOuvertes ? rep(200, 'false') : rep(401, '{"code":"42501"}');
      const t = u.match(/\/rest\/v1\/([a-z_]+)\?/);
      if (t) return situation.tableOuverte === t[1] ? rep(200, '[{"id":1}]') : rep(401, '{"code":"42501"}');
      return rep(404, '');
    };
    return { fetch, appels };
  }
  const passer = async (situation) => {
    const m = monde(situation);
    const r = await S.sonder({ fetch: m.fetch, url: URL, cle: 'sb_publishable_essai', attendre: async () => {} });
    return { r, b: S.bilan(r), appels: m.appels };
  };

  let x = await passer({});
  ok(x.b.etat === 'ok' && x.b.critiques === 0, 'tout va bien : « ok »');
  ok(x.r.length === 8 && x.r.every((c) => c.ok), 'huit contrôles, tous verts');
  ok(x.appels.every((a) => a.methode === 'GET' || /\/rpc\//.test(a.u)), 'la sonde ne fait que LIRE : des GET, et des appels de fonctions de lecture');
  ok(x.appels.every((a) => !/\/rest\/v1\/[a-z_]+\?/.test(a.u) || a.methode === 'GET'), 'aucune écriture vers une table');
  ok(x.b.tableau.includes('| site / | critique | OK |'), 'le résumé est un tableau lisible');

  for (const [situation, attendu] of [[{ siteEnPanne: true }, 'site /'], [{ authEnPanne: true }, 'authentification Supabase'], [{ baseEnPanne: true }, 'base de données']]) {
    x = await passer(situation);
    ok(x.b.etat === 'panne' && x.r.some((c) => !c.ok && c.gravite === 'critique' && c.nom.startsWith(attendu)), JSON.stringify(situation) + ' : panne, « ' + attendu + ' » en échec');
  }
  x = await passer({ tableOuverte: 'factures' });
  ok(x.b.etat === 'panne' && /LISIBLES PAR UN VISITEUR : factures/.test(x.r.find((c) => !c.ok).detail), 'une table lisible sans connexion : PANNE (fuite de données)');
  x = await passer({ fonctionsOuvertes: true });
  ok(x.b.etat === 'alerte' && x.b.critiques === 0, 'des fonctions internes ouvertes : alerte, sans réveiller personne');
  ok(/est_admin, a_droit, texte_notification, prefixe_matricule/.test(x.r.find((c) => !c.ok).detail), 'et l\'alerte nomme les fonctions et le remède');
  x = await passer({});
  ok(/non installé/.test(x.r.find((c) => c.nom.startsWith('santé')).detail), 'noyau absent : information seulement');
  x = await passer({ noyau: 'ok' });
  ok(x.b.etat === 'ok' && /étape 13/.test(x.r.find((c) => c.nom.startsWith('santé')).detail), 'noyau installé et sain : ok');
  x = await passer({ noyau: 'fail' });
  ok(x.b.etat === 'panne' && x.r.find((c) => c.nom.startsWith('santé')).gravite === 'critique', 'noyau installé et malade : PANNE');
  x = await passer({ passager: 2 });
  ok(x.b.etat === 'ok', 'deux coupures passagères : absorbées par les nouvelles tentatives');
  x = await passer({ passager: 3 });
  ok(x.b.etat === 'panne', 'trois coupures de suite : panne');

  // Le workflow
  const wf = fs.readFileSync(path.join(RACINE, '.github', 'workflows', 'surveillance.yml'), 'utf8');
  ok(/schedule:\s*\n\s*- cron: '[^']+'/.test(wf) && /workflow_dispatch/.test(wf), 'planifié, et lançable à la main');
  ok(/^permissions:\s*\n\s*contents: read\s*\n\s*issues: write\s*$/m.test(wf), 'permissions minimales : lire le dépôt, écrire un ticket');
  ok(!/secrets\./.test(wf) && /github\.token/.test(wf), 'aucun secret : seul le jeton fourni par GitHub, pour le ticket');
  ok(/sparse-checkout/.test(wf) && /alerte-production/.test(wf) && /gh issue close/.test(wf), 'ticket ouvert en panne, fermé au retour');

  console.log('PASS surveillance : ' + n + ' vérifications — tout vert, panne du site, de l\'authentification, de la base, table exposée, fonctions '
    + 'internes ouvertes (alerte), noyau absent / sain / malade, coupures passagères absorbées ; la sonde ne fait que lire ; workflow planifié, '
    + 'permissions minimales, sans secret');
})().catch((e) => { console.error(e); process.exit(1); });
