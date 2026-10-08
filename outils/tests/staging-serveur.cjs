// Le serveur de préproduction (outils/staging/servir.cjs), démarré pour de bon sur un port libre, sans réseau extérieur.
//   node outils/tests/staging-serveur.cjs
// On exige : config.js garde la configuration du site et y ajoute l'URL, la clé PUBLIQUE et l'adresse de préproduction,
// plus le bandeau ; la politique de contenu des pages autorise la préproduction et plus du tout la production ; ni outils/,
// ni docs/, ni .git ne sont servis ; et le serveur REFUSE de démarrer sur la production, sur le projet frère, avec une clé
// secrète, avec la clé de production ou une adresse qui n'est pas celle d'un projet Supabase.
'use strict';
const fs = require('node:fs'), os = require('node:os'), path = require('node:path'), cp = require('node:child_process');
const net = require('node:net'), vm = require('node:vm'), assert = require('node:assert/strict');
let n = 0; const ok = (c, m) => { assert.ok(c, m); n++; };

const RACINE = path.resolve(__dirname, '..', '..');
const SERVEUR = path.join(RACINE, 'outils', 'staging', 'servir.cjs');
const PROD = fs.readFileSync(path.join(RACINE, 'assets', 'js', 'config.js'), 'utf8');
const URL_PROD = PROD.match(/supabaseUrl:\s*'([^']+)'/)[1];
const CLE_PROD = PROD.match(/supabaseKey:\s*'([^']+)'/)[1];
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ses-staging-'));
const STAGING = { supabaseUrl: 'https://abcdefghijklmnopqrst.supabase.co', supabaseKey: 'sb_publishable_essai_PREPRODUCTION_0123' };

function portLibre() {
  return new Promise((r) => { const s = net.createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => r(p)); }); });
}
function config(nom, contenu) {
  const f = path.join(tmp, nom + '.json'); fs.writeFileSync(f, JSON.stringify(contenu)); return f;
}
function refuse(contenu, attendu, msg) {
  const r = cp.spawnSync(process.execPath, [SERVEUR], { env: { ...process.env, SES_STAGING_CONFIG: config('r' + n, contenu), SES_STAGING_PORT: '1' }, encoding: 'utf8', timeout: 10000 });
  ok(r.status === 2 && r.stderr.includes('REFUS') && r.stderr.includes(attendu), msg + ' (sortie : ' + (r.stderr || r.stdout).trim().slice(0, 120) + ')');
}

(async () => {
  // 1. les refus de démarrer
  refuse({ supabaseUrl: URL_PROD, supabaseKey: STAGING.supabaseKey }, 'PRODUCTION', 'refuse le projet de production');
  refuse({ supabaseUrl: 'https://gpfdyslysqjmojgzggib.supabase.co', supabaseKey: STAGING.supabaseKey }, 'protégé', 'refuse le projet frère (Goship)');
  refuse({ supabaseUrl: STAGING.supabaseUrl, supabaseKey: 'sb_' + 'secret_' + 'x'.repeat(30) }, 'PUBLIQUE', 'refuse une clé secrète');
  refuse({ supabaseUrl: STAGING.supabaseUrl, supabaseKey: CLE_PROD }, 'production', 'refuse la clé de production');
  refuse({ supabaseUrl: 'http://evil.example/supabase', supabaseKey: STAGING.supabaseKey }, 'supabaseUrl', 'refuse une adresse qui n\'est pas un projet Supabase');
  refuse(null, 'supabaseKey', 'refuse une configuration vide');

  // 2. le serveur, pour de bon
  const port = await portLibre();
  const p = cp.spawn(process.execPath, [SERVEUR], { env: { ...process.env, SES_STAGING_CONFIG: config('bon', STAGING), SES_STAGING_PORT: String(port) } });
  try {
    await new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error('le serveur ne démarre pas')), 10000);
      p.stdout.on('data', (d) => { if (String(d).includes('Préproduction')) { clearTimeout(t); resolve(); } });
      p.on('exit', (c) => reject(new Error('serveur arrêté : ' + c)));
    });
    const base = 'http://127.0.0.1:' + port;
    const lire = async (u) => { const r = await fetch(base + u); return { code: r.status, texte: await r.text(), type: r.headers.get('content-type') || '' }; };

    const cfg = await lire('/assets/js/config.js');
    ok(cfg.code === 200 && cfg.type.startsWith('text/javascript'), 'config.js est servi');
    ok(cfg.texte.startsWith(PROD), 'la configuration du site est gardée telle quelle (téléphone, mentions…)');
    ok(cfg.texte.includes('c.supabaseUrl = ' + JSON.stringify(STAGING.supabaseUrl)) && cfg.texte.includes('c.supabaseKey = ' + JSON.stringify(STAGING.supabaseKey)),
      'puis remplacée par l\'URL et la clé publique de préproduction');
    ok(cfg.texte.includes('c.siteUrl = "http://localhost:' + port + '"'), 'les liens des e-mails reviennent sur la préproduction');
    ok(cfg.texte.includes("c.environnement = 'staging'") && cfg.texte.includes('PRÉPRODUCTION'), 'le bandeau « PRÉPRODUCTION » s\'affiche');
    // la surcharge s'exécute réellement
    const window = {}; const document = { body: { appendChild: (el) => { window.bandeau = el; } }, getElementById: () => null,
      createElement: () => ({ style: {}, setAttribute() {} }), addEventListener() {} };
    vm.runInNewContext(cfg.texte, { window, document });   // le fichier tel que le navigateur le recevra, isolé
    ok(window.SES_CONFIG.supabaseUrl === STAGING.supabaseUrl && window.SES_CONFIG.telephone && window.bandeau && /PRÉPRODUCTION/.test(window.bandeau.textContent),
      'exécutée : la préproduction l\'emporte, le reste du site est intact, le bandeau est posé');

    const hote = URL_PROD.replace('https://', '');
    for (const page of ['/index.html', '/tableau-de-bord.html', '/espace-client.html', '/']) {
      const r = await lire(page);
      ok(r.code === 200 && !r.texte.includes(hote) && r.texte.includes('abcdefghijklmnopqrst.supabase.co'),
        page + ' : la politique de contenu autorise la préproduction, plus du tout la production');
    }
    for (const interdit of ['/CLAUDE.md', '/outils/supabase.sql', '/docs/production/RUNBOOK.md', '/.git/config', '/scripts/backup/_commun.py', '/.gitignore',
      '/outils/staging/config-staging.exemple.json', '/%2e%2e/%2e%2e/etc/passwd']) {
      ok([403, 404].includes((await lire(interdit)).code), interdit + ' n\'est pas servi');
    }
  } finally {
    p.kill();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  console.log('PASS serveur de préproduction : ' + n + ' vérifications — six refus de démarrer (production, projet frère, clé secrète, clé de production, '
    + 'adresse invalide, configuration vide), configuration du site gardée puis surchargée, bandeau, politique de contenu sans la production, fichiers de travail non servis');
})().catch((e) => { console.error(e); process.exit(1); });
