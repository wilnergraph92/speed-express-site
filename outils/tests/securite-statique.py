#!/usr/bin/env python3
"""Sécurité des pages servies : politique de contenu, scripts, cadres, référent.

Ce test lit les 28 pages GÉNÉRÉES (celles que les visiteurs reçoivent) et vérifie que :
  • chacune porte une politique de contenu, posée AVANT toute ressource ;
  • aucun script n'est écrit dans une page, aucun gestionnaire « onclick= », aucun « javascript: » ;
  • chaque ressource externe appelée par une page est autorisée par la politique — sinon le
    navigateur la bloquerait en silence le jour où la politique est appliquée ;
  • l'adresse de la base autorisée est celle de config.js (la politique suit un changement de projet) ;
  • les pages où l'on se connecte sont protégées de l'affichage dans le cadre d'un autre site ;
  • _headers dit la même chose que les pages.
Ne modifie aucun fichier."""
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / 'outils'))
sys.dont_write_bytecode = True
import securite as SEC   # noqa: E402

N = 0


def ok(c, m):
    global N
    if not c:
        print('ÉCHEC sécurité des pages : ' + m)
        sys.exit(1)
    N += 1


def directives(politique):
    d = {}
    for part in politique.split(';'):
        mots = part.strip().split()
        if mots:
            d[mots[0]] = mots[1:]
    return d


def hote_autorise(url, sources):
    h = urlsplit(url).hostname or ''
    for s in sources:
        if s.startswith('https://') and urlsplit(s).hostname == h:
            return True
    return False


pages = sorted(RACINE.glob('*.html'))
ok(len(pages) == 28, '28 pages attendues, %d trouvées' % len(pages))
attendue = SEC.politique()
D = directives(attendue)

# --- La politique elle-même ------------------------------------------------------------------
ok(D['script-src'] == ["'self'"], "script-src doit être « 'self' » seul (aucun script écrit dans une page)")
for interdit in ("'unsafe-eval'", "'unsafe-inline'", '*', 'data:', 'http:', 'https:'):
    ok(interdit not in D['script-src'], 'script-src contient ' + interdit)
    ok(interdit not in D['connect-src'], 'connect-src contient ' + interdit)
ok(D['object-src'] == ["'none'"] and D['frame-src'] == ["'none'"] and D['base-uri'] == ["'self'"], 'object-src none, frame-src none, base-uri self')
ok(D['default-src'] == ["'self'"], "default-src « 'self' » : tout ce qui n'est pas listé est refusé")
config = (RACINE / 'assets/js/config.js').read_text(encoding='utf-8')
hote = re.search(r"supabaseUrl:\s*'https://([a-z0-9]+\.supabase\.co)'", config).group(1)
ok(set(D['connect-src']) == {"'self'", 'https://' + hote, 'wss://' + hote}, 'connect-src = ce site + EXACTEMENT le projet de config.js (%s…), https et wss' % hote[:6])
ok(not re.search(r'sb_secret_|service_role|eyJ[A-Za-z0-9_-]{20,}\.', config), 'config.js ne contient aucune clé secrète ni jeton JWT')

# --- Chaque page --------------------------------------------------------------------------------
RESSOURCES = re.compile(r'<(link|script|img|source|iframe|embed|object|video|audio|use|image)\b[^>]*>', re.I)
for page in pages:
    html = page.read_text(encoding='utf-8')
    nom = page.name
    metas = re.findall(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html)
    ok(len(metas) == 1, '%s : exactement une politique de contenu (%d)' % (nom, len(metas)))
    ok(metas[0].replace('&quot;', '"') == attendue, '%s : la politique de la page n\'est pas celle du générateur' % nom)
    pos_csp = html.index('Content-Security-Policy')
    premiere = RESSOURCES.search(html)
    ok(premiere is None or premiere.start() > pos_csp, '%s : la politique doit venir AVANT toute ressource (%s)' % (nom, premiere.group(0)[:40] if premiere else ''))
    ok('<meta name="referrer" content="strict-origin-when-cross-origin">' in html, '%s : politique de référent' % nom)

    # aucun script écrit dans la page, aucun gestionnaire inline
    for m in re.finditer(r'<script\b([^>]*)>(.*?)</script>', html, re.S):
        attrs = m.group(1)
        if 'src=' in attrs:
            continue
        ok(re.search(r'type="application/ld\+json"', attrs) is not None, '%s : script écrit dans la page (interdit par la politique) : %s' % (nom, m.group(2).strip()[:50]))
    ok(not re.search(r'\son[a-z]{3,}\s*=\s*["\']', html), '%s : gestionnaire inline (onclick=, onsubmit=…)' % nom)
    ok('javascript:' not in html.lower(), '%s : adresse javascript:' % nom)
    ok(not re.search(r'<(iframe|embed|object)\b', html, re.I), '%s : cadre ou objet intégré' % nom)

    # chaque ressource externe est autorisée par la directive qui la concerne
    for m in RESSOURCES.finditer(html):
        balise = m.group(0)
        tag = m.group(1).lower()
        urls = re.findall(r'\b(?:src|href|srcset|imagesrcset)=["\']([^"\']+)["\']', balise)
        for brute in urls:
            for u in re.split(r',\s*', brute):
                u = u.strip().split(' ')[0]
                if not u.startswith(('http://', 'https://')):
                    continue
                ok(u.startswith('https://'), '%s : ressource en http (non chiffré) : %s' % (nom, u[:60]))
                rel = re.search(r'\brel="([^"]+)"', balise)
                rel = rel.group(1).lower() if rel else ''
                if tag == 'link' and rel in ('preconnect', 'dns-prefetch', 'canonical', 'alternate'):
                    continue            # indications au navigateur ou liens documentaires : pas des chargements
                if tag == 'script':
                    directive = 'script-src'
                elif tag == 'link' and ('stylesheet' in rel):
                    directive = 'style-src'
                elif tag == 'link' and ('icon' in rel or rel == 'preload' and 'image' in balise):
                    directive = 'img-src'
                elif tag == 'link' and rel == 'preload' and 'font' in balise:
                    directive = 'font-src'
                elif tag in ('img', 'source', 'image'):
                    directive = 'img-src'
                else:
                    directive = 'default-src'
                ok(hote_autorise(u, D[directive]), '%s : « %s » (%s) serait BLOQUÉE par la politique (%s)' % (nom, u[:70], tag, directive))

    # protection contre l'affichage dans le cadre d'un autre site
    protegee = nom in SEC.PAGES_A_PROTEGER_DU_CADRE
    a_le_style = 'id="ses-anti-cadre"' in html
    ok(a_le_style == protegee, '%s : protection anti-cadre %s' % (nom, 'ABSENTE sur une page de connexion/d\'action' if protegee else 'inutile sur une page publique'))
    if protegee:
        i_style = html.index('id="ses-anti-cadre"')
        m = re.search(r'<script src="assets/js/ses-anti-cadre\.js\?v=\d+"></script>', html)
        ok(m is not None, '%s : script anti-cadre absent, ou mal appelé (il doit être bloquant : ni defer ni async)' % nom)
        ok(i_style < m.start(), '%s : le style qui cache la page doit précéder le script qui la montre' % nom)
        ok('html{display:none!important}' in html[i_style:i_style + 120], '%s : la page doit être cachée par défaut' % nom)

ok((RACINE / 'assets/js/ses-anti-cadre.js').is_file(), 'ses-anti-cadre.js existe')
js = (RACINE / 'assets/js/ses-anti-cadre.js').read_text(encoding='utf-8')
ok('window.top === window.self' in js and 'ses-anti-cadre' in js and 'window.top.location' in js, 'le script ne montre la page que hors cadre, et tente de sortir du cadre')

# --- _headers dit la même chose ---------------------------------------------------------------
h = (RACINE / '_headers').read_text(encoding='utf-8')
m = re.search(r'Content-Security-Policy: (.*)', h)
ok(m and directives(m.group(1)) == {**D, 'frame-ancestors': ["'none'"], 'upgrade-insecure-requests': []}, '_headers : la même politique, plus frame-ancestors none')
ok('X-Frame-Options: DENY' in h and 'X-Content-Type-Options: nosniff' in h and 'Referrer-Policy: strict-origin-when-cross-origin' in h, '_headers : cadre, type de contenu, référent')

print('PASS sécurité des pages : %d vérifications — politique de contenu sur les 28 pages (script-src « self » seul), aucun script ni gestionnaire écrit '
      'dans une page, toute ressource externe autorisée, base alignée sur config.js, pages de connexion protégées du cadre, _headers cohérent.' % N)
