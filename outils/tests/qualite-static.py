#!/usr/bin/env python3
"""Validation bloquante des 28 pages, sans réseau ni dépendances Python."""
import collections
import json
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / 'outils'))
from unification import developper, corriger_ancres, convertir_survols

VIDES = set('area base br col embed hr img input link meta param source track wbr'.split())
class Page(HTMLParser):
    def __init__(self, texte):
        super().__init__(convert_charrefs=True)
        self.noeuds, self.erreurs, self.pile, self.scripts = [], [], [], []
        self.script = None
        self.feed(texte)
        if self.pile:
            self.erreurs.append('balises non fermées : ' + str(self.pile))
    def handle_starttag(self, tag, attrs):
        cles = [k for k, v in attrs]
        if len(cles) != len(set(cles)):
            self.erreurs.append('attributs doublés : ' + tag)
        d = dict(attrs)
        self.noeuds.append((tag, d))
        if tag not in VIDES:
            self.pile.append(tag)
        if tag == 'script':
            self.script = [d, '']
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VIDES:
            self.handle_endtag(tag)
    def handle_endtag(self, tag):
        if tag in VIDES:
            self.erreurs.append('fermeture de balise vide : ' + tag)
        elif not self.pile or self.pile[-1] != tag:
            self.erreurs.append('imbrication incorrecte : ' + tag)
        else:
            self.pile.pop()
        if tag == 'script' and self.script:
            self.scripts.append(self.script)
            self.script = None
    def handle_data(self, data):
        if self.script:
            self.script[1] += data
    def ids(self):
        return [d['id'] for t, d in self.noeuds if 'id' in d]


def verifier(racine):
    erreurs = []
    textes = {p.name: p.read_text() for p in racine.glob('*.html')}
    pages = {n: Page(t) for n, t in textes.items()}
    sources = {p.name for p in (racine / 'outils/pages').glob('*.html')}
    if len(pages) != 28 or set(pages) != sources:
        erreurs.append('Inventaire : 28 pages attendues et une source par page')
    for nom, page in pages.items():
        def exiger(ok, message):
            if not ok:
                erreurs.append(nom + ' : ' + message)
        texte = textes[nom]
        for e in page.erreurs:
            exiger(False, e)
        ids = page.ids()
        exiger(len(ids) == len(set(ids)), 'IDs dupliqués')
        scripts = [urlsplit(d['src']).path for t, d in page.noeuds if t == 'script' and d.get('src')]
        exiger(len(scripts) == len(set(scripts)), 'scripts dupliqués')
        for tag in ['html', 'head', 'body', 'main', 'h1', 'title', 'footer']:
            exiger(sum(t == tag for t, d in page.noeuds) == 1, 'un seul ' + tag + ' requis')
        for cle, valeur in [('name', 'description'), ('name', 'viewport'), ('property', 'og:title'), ('property', 'og:description'), ('property', 'og:url')]:
            exiger(any(t == 'meta' and d.get(cle) == valeur and d.get('content') for t, d in page.noeuds), 'metadata manquante : ' + valeur)
        exiger(any(t == 'html' and d.get('lang') == 'fr' for t, d in page.noeuds), 'langue manquante')
        css = texte
        for t, d in page.noeuds:
            urls = [d[k] for k in ['src', 'href', 'action'] if d.get(k)]
            if d.get('srcset') and not d['srcset'].startswith('data:'):
                urls += [v.strip().split()[0] for v in d['srcset'].split(',')]
            for lien in urls:
                u = urlsplit(lien)
                if u.scheme or u.netloc:
                    continue
                cible = unquote(u.path).lstrip('/') or nom
                if cible.endswith('/'):
                    cible += 'index.html'
                exiger((racine / cible).is_file(), 'fichier absent : ' + lien)
                if u.fragment and cible in pages:
                    exiger(unquote(u.fragment) in pages[cible].ids(), 'ancre absente : ' + lien)
                if t == 'link' and cible.endswith('.css') and (racine / cible).is_file():
                    css += (racine / cible).read_text()
            for attr in ['aria-controls', 'aria-labelledby', 'aria-describedby', 'for']:
                for ref in d.get(attr, '').split():
                    # Le titre de la fiche est créé avant showModal par ses-admin.js.
                    dynamique = (nom == 'tableau-de-bord.html' and ref == 'ses-fiche-titre'
                                 and 'id="ses-fiche-titre"' in (racine / 'assets/js/ses-admin.js').read_text())
                    exiger(ref in ids or dynamique, attr + ' cible absente : ' + ref)
        defs = set(re.findall(r'(--[\w-]+)\s*:', css))
        usages = set(re.findall(r'var\((--[\w-]+)\s*\)', css))
        exiger(not usages - defs, 'variables CSS indéfinies : ' + str(usages - defs))
        exiger('Archivo' not in texte and 'style-hover=' not in texte, 'ancien système visuel')
        exiger('assets/css/ses-base.css' in texte, 'base Saira manquante')
        for attrs, contenu in page.scripts:
            if attrs.get('type') == 'application/ld+json':
                try:
                    json.loads(contenu)
                except ValueError as e:
                    exiger(False, 'JSON-LD invalide : ' + str(e))
            elif not attrs.get('src') and contenu.strip():
                with tempfile.NamedTemporaryFile(suffix='.js', mode='w') as fichier:
                    fichier.write(contenu); fichier.flush()
                    resultat = subprocess.run(['node', '--check', fichier.name], capture_output=True, text=True)
                    exiger(resultat.returncode == 0, 'JavaScript inline invalide : ' + resultat.stderr)
        source = (racine / 'outils/pages' / nom).read_text()
        if '{{contenu}}' in source:
            source = source.replace('{{contenu}}', (racine / 'outils/espace' / nom).read_text().strip())
        exiger(developper(source, nom) == texte, 'page désynchronisée de sa source')
    return erreurs


def autotests():
    assert Page('<div><span></div>').erreurs
    assert Page('<a href="x" href="y"></a>').erreurs
    assert not Page('<main><img src="x"><p>Texte</p></main>').erreurs
    exemple = '<a href="nos-services.html#services">Fret maritime</a>'
    assert '#maritime' in corriger_ancres(exemple)
    exemple = '<a class="bouton" style-hover="color:#fff">Lien</a>'
    resultat = convertir_survols(exemple)
    assert 'style-hover' not in resultat and 'bouton' in resultat
    assert convertir_survols(resultat) == resultat

if __name__ == '__main__':
    autotests()
    erreurs = verifier(RACINE)
    if erreurs:
        print('\n'.join(erreurs)); sys.exit(1)
    print('PASS qualité : 28 pages, structure, liens, ancres, IDs, scripts, metadata, CSS, sources synchronisées.')
