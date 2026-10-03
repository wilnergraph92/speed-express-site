#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Contrôles phase 6 sans navigateur ni réseau, depuis la racine du dépôt."""
import collections
import re
import runpy
import sys
from html.parser import HTMLParser
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "outils"))
from accessibilite import appliquer, VERSION


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.noeuds = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.noeuds.append((tag, dict(attrs)))


def luminance(couleur):
    valeurs = [int(couleur[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    valeurs = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in valeurs]
    return sum(v * poids for v, poids in zip(valeurs, (.2126, .7152, .0722)))


def contraste(a, b):
    haut, bas = sorted((luminance(a), luminance(b)), reverse=True)
    return (haut + .05) / (bas + .05)


icones = 0
for fichier in sorted(RACINE.glob("*.html")):
    html = fichier.read_text()
    page = Page(html)
    ids = [a["id"] for _, a in page.noeuds if a.get("id")]
    assert not [id for id, n in collections.Counter(ids).items() if n > 1], fichier.name
    principaux = [a for t, a in page.noeuds if t == "main"]
    assert len(principaux) == 1 and principaux[0].get("id") == "contenu", fichier.name
    assert principaux[0].get("tabindex") == "-1", fichier.name
    sauts = [a for t, a in page.noeuds if "ses-skip-link" in a.get("class", "").split()]
    assert len(sauts) == 1 and sauts[0].get("href") == "#contenu", fichier.name
    assert 'href="#contenu">Aller au contenu</a>' in html, fichier.name
    assert f'assets/css/ses-accessibilite.css?v={VERSION}' in html, fichier.name
    assert html.index('assets/js/ses-accessibilite.js') < html.index('assets/js/ses-entete.js'), fichier.name
    assert appliquer(html, fichier.name) == html, (fichier.name, "retouche non idempotente")
    for tag, a in page.noeuds:
        classe = a.get("class", "").split()
        if ("Material Symbols" in a.get("style", "") or any("material-symbols" in c for c in classe)
                or any(c in classe for c in ("ico", "tel-ico", "svc__ico", "about__eyebrow-ico", "about__badge-ico"))):
            assert a.get("aria-hidden") == "true" or (a.get("role") == "img" and a.get("aria-label")), (fichier.name, a)
            icones += 1
        if a.get("role") == "tab":
            assert a.get("aria-controls") in ids, (fichier.name, a)
            assert a.get("tabindex") == ("0" if a.get("aria-selected") == "true" else "-1"), (fichier.name, a)
        if a.get("role") == "tabpanel":
            assert a.get("aria-labelledby") in ids and a.get("tabindex") == "0", (fichier.name, a)
        if a.get("role") == "combobox":
            assert a.get("aria-autocomplete") == "list" and a.get("aria-expanded") == "false", a
            assert a.get("aria-controls") in ids and a.get("aria-describedby") in ids, a
            assert any(t == "label" and l.get("for") == a.get("id") for t, l in page.noeuds), a
        if a.get("aria-controls") and "ses-burger" in classe:
            assert all(id in ids for id in a["aria-controls"].split()), fichier.name
    # Les couleurs initialement fautives n'alimentent plus aucune propriété
    # de texte ; elles peuvent rester dans des commentaires explicatifs.
    assert not re.search(r'(?<![\w-])color\s*:\s*#(?:8d949f|7a828e|9b9b9b)\b', html), fichier.name

for fichier in (RACINE / "outils/espace").glob("*.html"):
    html = fichier.read_text()
    assert appliquer(html, fichier.name, complet=False) == html, fichier.name
    assert html.strip() in (RACINE / fichier.name).read_text(), (fichier.name, "fragment désynchronisé")

for nom, attendu in (("index.html", 4), ("blog.html", 11)):
    html = (RACINE / nom).read_text()
    cartes = re.findall(r'<article\b[^>]*ses-carte-article[^>]*>.*?</article>', html, re.S)
    assert len(cartes) == attendu, (nom, len(cartes))
    for carte in cartes:
        assert len(re.findall(r'<a\b', carte)) == 1, carte
        assert re.search(r'<h3[^>]*><a[^>]*ses-carte-lien', carte), carte
        assert 'tabindex="-1"' not in carte, carte

for nom in ('creer-un-compte.html','espace-client.html','tableau-de-bord.html'):
    assert 'data-t="telephone-invalide">Ce numéro de téléphone ne semble pas valide.' in (RACINE / nom).read_text(), nom

for nom in ("index.html", "suivi.html"):
    html = (RACINE / nom).read_text()
    assert '<label class="sr-only" for="ses-ref-input">Numéro de suivi</label>' in html, nom
    assert 'id="ses-suivi-annonce"' in html and 'role="status"' in html, nom

for avant in ("#8d949f", "#7a828e"):
    print(f"Avant {avant} / blanc : {contraste(avant, '#ffffff'):.2f}:1")
for texte, fond in (("#626b78", "#ffffff"), ("#626b78", "#f8f8f8"),
                    ("#b60d14", "#ffffff"), ("#b60d14", "#f6e1e2"),
                    ("#ff7278", "#20242a"), ("#ff7278", "#2e0d10"),
                    ("#ffffff", "#e8121b"), ("#737c89", "#f7f7f7"),
                    ("#0b7a19", "#ffffff"), ("#a3abb8", "#20242a"),
                    ("#626b78", "#f6f6f6")):
    ratio = contraste(texte, fond)
    assert ratio >= (3 if texte == "#737c89" else 4.5), (texte, fond, ratio)
    print(f"Après {texte} / {fond} : {ratio:.2f}:1")

css = (RACINE / "assets/css/ses-accessibilite.css").read_text()
assert '@media (prefers-reduced-motion: reduce)' in css
for attendu in ('animation:none!important', 'transition:none!important', 'scroll-behavior:auto!important', '.ses-cache.ses-vu'):
    assert attendu in css, attendu
for nom in ("site.js", "ses-compte.js", "ses-admin.js"):
    assert "behavior: 'smooth'" not in (RACINE / "assets/js" / nom).read_text(), nom
langue = (RACINE / "assets/js/lang-switcher.js").read_text()
for attendu in ('aria-expanded', 'aria-controls', "ev.key === 'Escape'", 'avaitFocus', 'prefers-reduced-motion:reduce'):
    assert attendu in langue, attendu
print(f"PASS accessibilité statique : 28 pages, {icones} icônes, repères, labels, cartes, ARIA, fragments, idempotence et palette AA.")
