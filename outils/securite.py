"""Protections du navigateur, posées dans l'en-tête de chaque page à la génération.

GitHub Pages ne permet pas d'envoyer des en-têtes HTTP : le seul seul levier est la balise
<meta http-equiv="Content-Security-Policy">, que les navigateurs respectent presque en entier.
Ce que la balise ne peut PAS faire : « frame-ancestors » (qui interdit d'afficher le site dans
le cadre d'un autre), ni X-Frame-Options. Pour les pages où l'on saisit un mot de passe ou une
action, une protection de remplacement est posée : la page reste invisible tant qu'un petit script
n'a pas constaté qu'elle n'est pas dans un cadre.

Tout vient d'ici, et de config.js : l'adresse du projet Supabase autorisée est lue dans config.js,
pour que la politique suive un changement de projet (reprise après sinistre) sans y toucher.

Aucun script écrit dans une page n'est autorisé (script-src 'self') : c'est ce qui ferme la porte
à l'injection de code. Les styles écrits dans les pages le sont encore (style-src 'unsafe-inline'),
parce que le site en dépend largement."""
import re
from pathlib import Path
from urllib.parse import urlsplit

SITE = Path(__file__).resolve().parent.parent

# Pages où l'on se connecte, crée un compte, ou agit sur des colis et des factures.
PAGES_A_PROTEGER_DU_CADRE = {'connexion.html', 'creer-un-compte.html', 'espace-client.html',
                             'nouveau-mot-de-passe.html', 'tableau-de-bord.html'}

MARQUE_DEBUT = '<!-- ses-securite -->'
MARQUE_FIN = '<!-- /ses-securite -->'


def _config():
    return (SITE / 'assets/js/config.js').read_text(encoding='utf-8')


def _valeur(nom):
    m = re.search(nom + r":\s*'([^']*)'", _config())
    return m.group(1).strip() if m else ''


def hote_supabase():
    h = urlsplit(_valeur('supabaseUrl')).hostname
    return h or ''


def hote_formulaire():
    h = urlsplit(_valeur('formEndpoint')).hostname
    return h or ''


def politique(en_tete_http=False):
    """La politique de contenu. Avec en_tete_http=True : la version pour un hébergeur qui accepte
    de vrais en-têtes, qui peut aussi interdire le cadre."""
    sb, form = hote_supabase(), hote_formulaire()
    connexions = ["'self'"] + (['https://' + sb, 'wss://' + sb] if sb else []) + (['https://' + form] if form else [])
    actions = ["'self'"] + (['https://' + form] if form else [])
    dirs = [
        ("default-src", ["'self'"]),
        ("base-uri", ["'self'"]),
        ("object-src", ["'none'"]),
        ("frame-src", ["'none'"]),
        ("worker-src", ["'self'", "blob:"]),
        ("manifest-src", ["'self'"]),
        ("form-action", actions),
        ("script-src", ["'self'"]),
        ("style-src", ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"]),
        ("font-src", ["'self'", "https://fonts.gstatic.com"]),
        ("img-src", ["'self'", "data:", "blob:", "https://images.unsplash.com"]),
        ("connect-src", connexions),
    ]
    if en_tete_http:
        dirs.append(("frame-ancestors", ["'none'"]))
        dirs.append(("upgrade-insecure-requests", []))
    return '; '.join((n + ' ' + ' '.join(v)).strip() for n, v in dirs)


def _version_scripts():
    m = re.search(r"var V = '(\d+)'", (SITE / 'assets/js/lang-switcher.js').read_text(encoding='utf-8'))
    return m.group(1) if m else '1'


def bloc(nom):
    lignes = [MARQUE_DEBUT,
              '<meta http-equiv="Content-Security-Policy" content="%s">' % politique().replace('"', '&quot;'),
              '<meta name="referrer" content="strict-origin-when-cross-origin">']
    if nom in PAGES_A_PROTEGER_DU_CADRE:
        lignes += ['<style id="ses-anti-cadre">html{display:none!important}</style>',
                   '<script src="assets/js/ses-anti-cadre.js?v=%s"></script>' % _version_scripts()]
    lignes.append(MARQUE_FIN)
    return '\n'.join(lignes)


def appliquer_securite(html, nom=''):
    """Pose (ou remplace) le bloc de sécurité juste après <meta charset>. Idempotent."""
    html = re.sub(re.escape(MARQUE_DEBUT) + r'.*?' + re.escape(MARQUE_FIN) + r'\n?', '', html, flags=re.S)
    m = re.search(r'<meta charset="utf-8">\n?', html, flags=re.I)
    if not m:
        return html
    return html[:m.end()] + bloc(nom) + '\n' + html[m.end():]


def ecrire_headers():
    """_headers : la même politique, plus ce que seuls de vrais en-têtes savent faire. GitHub Pages
    ne le lit pas ; il sert le jour où le site passe chez un hébergeur qui le lit (Cloudflare Pages,
    Netlify). Régénéré avec les pages : il ne peut plus se périmer."""
    texte = ("# En-têtes de sécurité (Netlify, Cloudflare Pages…). GitHub Pages ne les lit pas : en attendant, la\n"
             "# politique de contenu est posée par des balises <meta> dans chaque page (outils/securite.py).\n"
             "# Ce fichier est GÉNÉRÉ par outils/mise-en-page.py : ne pas le modifier à la main.\n"
             "/*\n"
             "  Content-Security-Policy: %s\n"
             "  X-Frame-Options: DENY\n"
             "  X-Content-Type-Options: nosniff\n"
             "  Referrer-Policy: strict-origin-when-cross-origin\n"
             "  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), interest-cohort=()\n"
             "  Cross-Origin-Opener-Policy: same-origin\n"
             "  Strict-Transport-Security: max-age=31536000; includeSubDomains\n") % politique(en_tete_http=True)
    cible = SITE / '_headers'
    if not cible.exists() or cible.read_text(encoding='utf-8') != texte:
        cible.write_text(texte, encoding='utf-8')
        return True
    return False
