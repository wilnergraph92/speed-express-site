"""Composants Saira communs et migration déterministe des anciens exports."""
import hashlib
import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
COMMUNS = SITE / 'outils' / 'communs'

def convertir_survols(html):
    """Classes stables ; !important est nécessaire face aux styles inline hérités."""
    def balise(m):
        tag = m[0]
        survol = re.search(r' style-hover="([^"]*)"', tag)
        if not survol:
            return tag
        classe = 'ses-hover-' + hashlib.sha256(survol[1].encode()).hexdigest()[:10]
        tag = tag.replace(survol[0], '')
        if ' class="' in tag:
            tag = tag.replace(' class="', ' class="' + classe + ' ', 1)
        else:
            tag = tag[:-1] + ' class="' + classe + '">'
        return tag
    return re.sub(r'<[^>]+>', balise, html)

def corriger_ancres(html):
    destinations = {'Consolidation de colis': 'consolidation', 'Fret maritime': 'maritime',
                    'Fret aérien express': 'aerien', 'Dédouanement': 'dedouanement'}
    def lien(m):
        cible = next((ancre for texte, ancre in destinations.items() if texte in m[0]), 'transport')
        return m[0].replace('#services', '#' + cible)
    html = re.sub(r'<a\b[^>]*href="nos-services.html#services"[^>]*>.*?</a>', lien, html, flags=re.S)
    return html.replace('href="index.html#adresse"', 'href="nos-services.html#adresse-usa"')

def appliquer(html, nom=''):
    html = corriger_ancres(html)
    html = html.replace('Archivo:wdth,wght@75..125,400..900', 'Saira:ital,wght@0,400..900;1,400..900')
    html = html.replace('Archivo', 'Saira')
    html = re.sub(r'font-stretch:[^;}]+;?', '', html)
    # Les composants partagés sont la source, jamais une autre page générée.
    for tag, fichier in [('header', 'entete.html'), ('footer', 'pied.html')]:
        commun = (COMMUNS / fichier).read_text()
        if tag == 'header':
            actif = 'blog.html' if nom.startswith('article-') else nom
            commun = commun.replace('href="' + actif + '" style="color:var(--ink)"',
                                    'href="' + actif + '" aria-current="page" style="color:var(--red-text);border-bottom:2px solid var(--red);padding-bottom:3px"')
        html = re.sub(r'<' + tag + r'\b.*?</' + tag + '>', lambda m: commun.strip(), html, count=1, flags=re.S)
    if nom == '404.html' and 'id="top"' not in html:
        html = html.replace('<body>', '<body id="top">', 1)
    from securite import appliquer_securite   # CSP, référent, anti-cadre (outils/securite.py)
    return appliquer_securite(convertir_survols(html), nom)

def developper(source, nom):
    for fichier in COMMUNS.glob('*.html'):
        source = source.replace('{{' + fichier.stem + '}}', fichier.read_text().strip())
    return appliquer(source, nom)
