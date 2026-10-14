// Speed Express Operations — prépare les pages embarquées dans l'application de bureau (bureau/site/).
//
// L'application montre EXACTEMENT ce que le site publie : la même liste de fichiers, retirés les mêmes fichiers de travail, lue dans
// .github/workflows/deploy.yml (les exclusions de rsync). Deux retouches seulement, et seulement dans la copie :
//   · la politique de sécurité de chaque page autorise en plus le canal interne de Tauri (« ipc: http://ipc.localhost ») — sans lui,
//     Tauri passe par un canal plus lent ; rien d'autre n'est ouvert ;
//   · la page d'accueil de l'application est le tableau de bord (tauri.conf.json), le reste du site reste joignable par ses liens.
// Puis une vérification qui ARRÊTE la construction : aucune clé secrète (service_role, sb_secret_, clé privée) ne doit se trouver dans
// ce qui sera embarqué. L'application ne connaît que la clé PUBLIQUE de Supabase, comme le site.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ICI = path.dirname(fileURLToPath(import.meta.url));
const RACINE = path.resolve(ICI, '..');
const CIBLE = path.join(ICI, 'site');

const deploy = fs.readFileSync(path.join(RACINE, '.github/workflows/deploy.yml'), 'utf8');
const motifs = [...deploy.matchAll(/--exclude\s+'([^']+)'/g)].map((m) => m[1]);
if (motifs.length < 5) throw new Error('deploy.yml : exclusions introuvables (la lecture du fichier a changé ?)');
// En plus du déploiement : ce dossier lui-même, et ce qui n'a rien à faire dans une application.
motifs.push('/bureau', 'node_modules');

function exclu(relatif) {
  const parts = relatif.split('/');
  return motifs.some((m) => (m.startsWith('/') ? parts[0] === m.slice(1) : parts.includes(m)));
}

fs.rmSync(CIBLE, { recursive: true, force: true });
let n = 0;
(function copier(rel) {
  for (const e of fs.readdirSync(path.join(RACINE, rel), { withFileTypes: true })) {
    const r = rel ? rel + '/' + e.name : e.name;
    if (exclu(r)) continue;
    if (e.isDirectory()) { copier(r); continue; }
    if (!e.isFile()) continue;
    fs.mkdirSync(path.join(CIBLE, rel), { recursive: true });
    fs.copyFileSync(path.join(RACINE, r), path.join(CIBLE, r));
    n++;
  }
})('');

const CANAL_TAURI = 'ipc: http://ipc.localhost';
let pages = 0;
for (const f of fs.readdirSync(CIBLE).filter((x) => x.endsWith('.html'))) {
  const p = path.join(CIBLE, f);
  const avant = fs.readFileSync(p, 'utf8');
  const apres = avant.replace(/(<meta http-equiv="Content-Security-Policy" content="[^"]*connect-src )([^";]*)/, (t, debut, liste) =>
    liste.includes(CANAL_TAURI) ? t : debut + liste + ' ' + CANAL_TAURI);
  if (apres !== avant) { fs.writeFileSync(p, apres); pages++; }
}

// Aucun secret dans ce qui part dans l'application.
const INTERDITS = [/service_role/i, /\bsb_secret_[A-Za-z0-9_]+/, /-----BEGIN [A-Z ]*PRIVATE KEY-----/, /SUPABASE_SERVICE/i, /TAURI_SIGNING_PRIVATE_KEY/];
const fautes = [];
(function verifier(rel) {
  for (const e of fs.readdirSync(path.join(CIBLE, rel), { withFileTypes: true })) {
    const r = rel ? rel + '/' + e.name : e.name;
    if (e.isDirectory()) { verifier(r); continue; }
    if (!/\.(html|js|json|css|txt|xml|webmanifest)$/.test(r)) continue;
    const texte = fs.readFileSync(path.join(CIBLE, r), 'utf8');
    for (const motif of INTERDITS) if (motif.test(texte)) fautes.push(r + ' : ' + motif);
  }
})('');
if (fautes.length) {
  fs.rmSync(CIBLE, { recursive: true, force: true });
  console.error('ARRÊT : un secret se trouverait dans l\'application :\n  ' + fautes.join('\n  '));
  process.exit(1);
}
if (!fs.existsSync(path.join(CIBLE, 'tableau-de-bord.html')) || !fs.existsSync(path.join(CIBLE, 'assets/js/ses-bureau.js'))) {
  console.error('ARRÊT : le tableau de bord ou le pont de bureau manque dans la copie.');
  process.exit(1);
}
console.log(`Pages de l'application prêtes : ${n} fichiers copiés depuis le site, ${pages} pages ouvertes au canal de Tauri, aucun secret.`);
