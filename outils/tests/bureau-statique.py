#!/usr/bin/env python3
"""L'application de bureau « Speed Express Operations » (phase 10, ADR 0016), relue sans la construire.

    python3 outils/tests/bureau-statique.py

La construction elle-même (Windows, macOS) et les essais Rust tournent dans .github/workflows/bureau.yml. Ici, ce qu'un oubli
rendrait dangereux sans bruit :
 1. la configuration Tauri : le nom, l'identifiant, la fenêtre sur le tableau de bord, en HTTPS sous Windows, les pages embarquées
    (pas une adresse distante), le glisser-déposer laissé à la page (import de listes), les mises à jour éteintes tant qu'aucune clé
    publique n'est posée ;
 2. les droits : une seule capacité, « core:default », sur la seule fenêtre ; aucune commande de shell ni de fichiers ouverte à la page ;
 3. AUCUN secret dans bureau/ ni dans le pont (clé de service de Supabase, clé privée, mot de passe) ; le workflow ne lit les secrets que
    dans des variables d'environnement, jamais dans une commande ; aucun secret de Supabase n'y figure ;
 4. les pages embarquées sont celles que le site publie (bureau/preparer.mjs lit les exclusions de deploy.yml), et bureau/ n'est jamais
    publié sur le site ;
 5. la navigation : seules les pages internes ; un lien externe, au navigateur du système, en https, mailto ou tel seulement ;
 6. l'impression Windows : nom d'imprimante et données par l'environnement, jamais dans le texte du script ;
 7. la documentation : l'ADR et la procédure de construction, signature et recette existent.
"""
import json
import re
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[2]
B = R / 'bureau'
N = [0]
ERREURS = []


def ok(c, m):
    if c:
        N[0] += 1
    else:
        ERREURS.append(m)


conf = json.loads((B / 'src-tauri/tauri.conf.json').read_text(encoding='utf-8'))
# ---------------------------------------------------------------------- 1. la configuration
ok(conf['productName'] == 'Speed Express Operations' and conf['identifier'] == 'com.speedexpressshipping.operations', 'nom et identifiant de l\'application')
ok(conf['build']['frontendDist'] == '../site' and 'devUrl' not in conf['build'], 'les pages EMBARQUÉES (bureau/site), jamais une adresse distante')
f = conf['app']['windows']
ok(len(f) == 1 and f[0]['label'] == 'principale' and f[0]['url'] == 'tableau-de-bord.html', 'une seule fenêtre, sur le tableau de bord')
ok(f[0].get('useHttpsScheme') is True, 'Windows : https://tauri.localhost (sinon « upgrade-insecure-requests » et les cookies sécurisés casseraient)')
ok(f[0].get('dragDropEnabled') is False, 'le glisser-déposer reste à la page (import d\'une liste au poste de scan)')
ok(f[0]['minWidth'] >= 1024 and f[0]['width'] >= 1280, 'une taille de poste de travail (1080p, 1440p, 4K)')
ok(conf['app']['withGlobalTauri'] is True, 'le pont (ses-bureau.js) trouve window.__TAURI__ sans module')
ok(conf['bundle']['createUpdaterArtifacts'] is False and conf['plugins']['updater']['pubkey'] == '', 'dans le dépôt : mises à jour éteintes, AUCUNE clé (le workflow pose la clé publique)')
ok(all(u.startswith('https://github.com/wilnergraph92/speed-express-site/releases/download/bureau-canal-') for u in conf['plugins']['updater']['endpoints']), 'les mises à jour ne viennent que du canal publié')
ok(set(conf['bundle']['targets']) >= {'nsis', 'msi', 'dmg'}, 'Windows : setup.exe et MSI ; macOS : DMG')
ok(conf['bundle']['macOS']['entitlements'] == './Entitlements.plist', 'macOS : exécution renforcée avec ses droits déclarés')
ent = (B / 'src-tauri/Entitlements.plist').read_text(encoding='utf-8')
ok(re.findall(r'<key>([^<]+)</key>', ent) == ['com.apple.security.device.camera'], 'macOS : la caméra (poste de scan), et aucun autre droit')
ok('NSCameraUsageDescription' in (B / 'src-tauri/Info.plist').read_text(encoding='utf-8'), 'macOS : la raison de la caméra est dite')
ok(json.loads((B / 'package.json').read_text(encoding='utf-8'))['devDependencies']['@tauri-apps/cli'] == json.loads((B / 'package-lock.json').read_text(encoding='utf-8'))['packages']['node_modules/@tauri-apps/cli']['version'],
   'la version de l\'outil Tauri est figée (package-lock)')

# ---------------------------------------------------------------------- 2. les droits
caps = list((B / 'src-tauri/capabilities').glob('*.json'))
ok(len(caps) == 1, 'une seule capacité')
cap = json.loads(caps[0].read_text(encoding='utf-8'))
ok(cap['windows'] == ['principale'] and cap['permissions'] == ['core:default'], 'la fenêtre n\'a que « core:default » : ni shell, ni fichiers, ni http, ni opener ouverts à la page')
ok('remote' not in cap, 'aucune page distante n\'a accès à l\'enveloppe')
cargo = (B / 'src-tauri/Cargo.toml').read_text(encoding='utf-8')
ok(not re.search(r'tauri-plugin-(shell|fs|http|sql|store)', cargo), 'aucun plugin qui ouvrirait le shell, les fichiers ou le réseau à la page')
ok(re.search(r'^tauri = \{ version = "2"', cargo, re.M) is not None, 'Tauri 2')

# ---------------------------------------------------------------------- 3. aucun secret
SECRET = re.compile(r'service_role|sb_secret_[A-Za-z0-9]|-----BEGIN [A-Z ]*PRIVATE KEY|eyJhbGciOi[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}|untrusted comment: rsign', re.I)
for p in sorted(list(B.rglob('*'))):
    # preparer.mjs porte les motifs interdits : c'est le garde-fou lui-même (vérifié plus bas)
    if not p.is_file() or p.name == 'preparer.mjs' or any(x in p.parts for x in ('node_modules', 'target', 'site', 'gen', 'icons')):
        continue
    try:
        texte = p.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        continue
    ok(not SECRET.search(texte), 'aucun secret dans %s' % p.relative_to(R))
ok(not SECRET.search((R / 'assets/js/ses-bureau.js').read_text(encoding='utf-8')), 'aucun secret dans le pont')
wf = (R / '.github/workflows/bureau.yml').read_text(encoding='utf-8')
ok('secrets.' not in wf and 'tauri-action' not in wf and 'contents: read' in wf, 'le workflow PUBLIC ne lit aucun secret et ne publie rien (installateurs d\'essai seulement)')
mp = (R / 'scripts/bureau/modele-workflow-publication.yml').read_text(encoding='utf-8')
for texte, nom in ((wf, 'bureau.yml'), (mp, 'modèle de publication')):
    ok(not re.search(r'SUPABASE|service_role|SES_DB_URL', texte, re.I), '%s : aucun secret de Supabase ni de la base' % nom)
    ok(not re.search(r'run:.*\$\{\{ (github\.event|github\.head_ref|inputs\.)', texte), '%s : aucune donnée saisie dans une commande' % nom)
for ligne in mp.splitlines():
    if '${{ secrets.' in ligne:
        ok(re.match(r'^\s+([A-Z_]+|[A-Z]{1,3}): \$\{\{ secrets\.[A-Z_]+ \}\}\s*$', ligne) or re.match(r'^\s+[A-Z_]+: \$\{\{ secrets\.[A-Z_]+ != \'\'', ligne),
           'modèle : un secret ne se lit que dans une variable d\'environnement : %s' % ligne.strip())
ok('ETIQUETTE: ${{ inputs.etiquette }}' in mp and re.search(r"bureau-beta-v\(\[0-9\]\+\\\.\[0-9\]\+\\\.\[0-9\]\+\)\$", mp) is not None,
   'modèle : l\'étiquette passe par l\'environnement et n\'est acceptée que de forme bureau[-beta]-vX.Y.Z')
ok("prerelease: ${{ steps.version.outputs.canal == 'beta' }}" in mp and '--latest=false' in mp, 'modèle : une bêta est une préversion ; le canal n\'est jamais « latest »')
ok('repository: wilnergraph92/speed-express-site' in mp and 'ref: refs/tags/' in mp, 'modèle : construit le site PUBLIC, à une étiquette précise')

# ---------------------------------------------------------------------- 4. les pages embarquées = le site
prep = (B / 'preparer.mjs').read_text(encoding='utf-8')
ok('deploy.yml' in prep and "motifs.push('/bureau'" in prep, 'preparer.mjs reprend les exclusions du déploiement, plus bureau/')
ok('process.exit(1)' in prep and 'service_role' in prep, 'preparer.mjs ARRÊTE la construction si un secret se trouvait dans les pages')
ok("--exclude '/bureau'" in (R / '.github/workflows/deploy.yml').read_text(encoding='utf-8'), 'bureau/ n\'est jamais publié sur le site')
ig = (R / '.gitignore').read_text(encoding='utf-8')
ok(all(x in ig for x in ('bureau/site/', 'bureau/node_modules/', 'bureau/src-tauri/target/')), 'ce qui se fabrique n\'entre pas dans Git')

# ---------------------------------------------------------------------- 5. la navigation
lib = (B / 'src-tauri/src/lib.rs').read_text(encoding='utf-8')
ok('on_navigation' in lib and '"tauri" => url.host_str() == Some("localhost")' in lib and 'Some("tauri.localhost")' in lib, 'la fenêtre ne navigue que dans ses pages')
ok('matches!(url.scheme(), "https" | "mailto" | "tel")' in lib, 'un lien externe : https, mailto ou tel seulement')
ok('connues.iter().any(|n| n == &imprimante)' in lib, 'l\'étiquette brute ne part que vers une imprimante déclarée par le système')
ok('tauri_plugin_single_instance' in lib, 'une seule fenêtre par poste (deux postes de scan ouverts liraient deux fois)')

# ---------------------------------------------------------------------- 6. l'impression Windows
ps = (B / 'src-tauri/src/impression-windows.ps1').read_text(encoding='utf-8')
ok('$env:SES_IMPRIMANTE' in ps and '$env:SES_DONNEES' in ps and 'pDataType = "RAW"' in ps, 'Windows : nom et données par l\'environnement, envoi RAW')
imp = (B / 'src-tauri/src/impression.rs').read_text(encoding='utf-8')
ok('.env("SES_IMPRIMANTE", imprimante)' in imp and 'format!(' not in imp.split('fn powershell')[1].split('fn lister')[0].replace('format!("PowerShell indisponible', ''), 'Windows : rien n\'est collé dans le texte du script')
ok('.args(["-d", imprimante, "-o", "raw"' in imp and 'sh -c' not in imp, 'macOS : arguments séparés, jamais un interpréteur de commandes')

# ---------------------------------------------------------------------- 7. la documentation
ok((R / 'docs/architecture/ADR/0016-bureau-tauri-autour-du-tableau-de-bord.md').exists(), 'l\'ADR 0016 existe')
ok((R / 'docs/production/BUREAU.md').exists(), 'la procédure (construire, signer, publier, recette) existe')

if ERREURS:
    print('ÉCHEC application de bureau (statique) :')
    for e in ERREURS:
        print('  -', e)
    sys.exit(1)
print('PASS application de bureau (statique) : %d vérifications — configuration, une capacité minimale, aucun secret, pages = site, '
      'navigation fermée, impression sans injection, documentation.' % N[0])
