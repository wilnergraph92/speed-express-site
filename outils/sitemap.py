#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Speed Express Shipping — sitemap.xml régénéré depuis les pages.

La liste des URL est relue dans les pages elles-mêmes : y figurent toutes
les pages publiques (celles sans meta robots noindex), jamais une URL
tapée à la main qui pourrait dériver. Chaque URL emporte l'image og:image
de sa page, pour l'indexation dans Google Images. Les pages privées
(connexion, espace client, tableau de bord, 404…) sont exclues par leur
seule meta robots.

    python3 outils/sitemap.py                     # régénère, garde les lastmod
    python3 outils/sitemap.py --touches=a.html,b.html   # date ces pages au jour même

Relançable sans risque : sans --touches et sans page modifiée, le fichier
est réécrit à l'identique (les lastmod de l'ancien sitemap sont repris).
"""
import re
import sys
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape as xml_echapper

SITE = Path(__file__).resolve().parent.parent

BASE = "https://wilnergraph92.github.io/speed-express-site/"
SITEMAP = SITE / "sitemap.xml"

# Priorité et fréquence de relecture par nature de page. Google précise que
# ces deux champs ne sont que des indices : on reste sobre et cohérent, pas
# de 1.0 partout.
PILIER = {  # pages qui portent l'essentiel du trafic
    "index.html": ("1.0", "weekly"),
    "nos-services.html": ("0.9", "monthly"),
    "suivi.html": ("0.9", "monthly"),
    "a-propos.html": ("0.8", "monthly"),
    "contacts.html": ("0.8", "monthly"),
    "blog.html": ("0.8", "weekly"),
    "support.html": ("0.6", "monthly"),
    "marchandises-dangereuses.html": ("0.5", "yearly"),
    "termes-et-conditions.html": ("0.3", "yearly"),
    "confidentialite.html": ("0.3", "yearly"),
}
ARTICLE = ("0.7", "monthly")  # tous les article-*.html


def valeur(html, motif):
    m = re.search(motif, html, re.S)
    return m.group(1).strip() if m else ""


def lastmod_actuels():
    """Carte URL -> lastmod de l'ancien sitemap (vide si aucun)."""
    if not SITEMAP.exists():
        return {}
    return dict(re.findall(
        r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>",
        SITEMAP.read_text(encoding="utf-8")))


def main():
    touches = []
    for argument in sys.argv[1:]:
        if argument.startswith("--touches="):
            touches = [nom.strip() for nom in argument.split("=", 1)[1].split(",") if nom.strip()]
        elif argument in ("-h", "--help"):
            print("Usage : sitemap.py [--touches=page1.html,page2.html]")
            return
    anciens = lastmod_actuels()
    aujourd_hui = date.today().isoformat()

    lignes = []
    lignes.append('<?xml version="1.0" encoding="UTF-8"?>')
    lignes.append("<!-- Pages publiques indexables uniquement. Exclues volontairement : connexion, création de compte,\n"
                  "     nouveau mot de passe, espace client, tableau de bord, fermeture de compte, 404 (toutes en noindex).\n"
                  "     Régénéré par outils/sitemap.py ; ne pas modifier à la main. -->")
    lignes.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
                  '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">')

    pages = sorted(SITE.glob("*.html"))
    inconnues = [nom for nom in touches if not (SITE / nom).exists()]
    if inconnues:
        sys.exit("Pages inconnues dans --touches : " + ", ".join(inconnues))

    for f in pages:
        html = f.read_text(encoding="utf-8")
        if 'name="robots" content="noindex' in html:
            continue  # page privée : elle ne doit figurer dans aucun index
        url = valeur(html, r'<link rel="canonical" href="([^"]+)"') or BASE + f.name
        image = valeur(html, r'<meta property="og:image" content="([^"]+)"')
        if f.name in touches:
            derniere = aujourd_hui
        else:
            derniere = anciens.get(url, aujourd_hui)
        priorite, frequence = PILIER.get(f.name, ARTICLE)
        lignes.append("  <url>")
        lignes.append("    <loc>" + xml_echapper(url) + "</loc>")
        lignes.append("    <lastmod>" + derniere + "</lastmod>")
        lignes.append("    <changefreq>" + frequence + "</changefreq>")
        lignes.append("    <priority>" + priorite + "</priority>")
        if image:
            lignes.append("    <image:image>")
            lignes.append("      <image:loc>" + xml_echapper(image) + "</image:loc>")
            lignes.append("    </image:image>")
        lignes.append("  </url>")
    lignes.append("</urlset>")
    lignes.append("")

    avant = SITEMAP.read_text(encoding="utf-8") if SITEMAP.exists() else ""
    apres = "\n".join(lignes)
    if apres != avant:
        SITEMAP.write_text(apres, encoding="utf-8")
        total = sum(1 for l in lignes if l == "  <url>")
        print("sitemap.xml régénéré : {} URL{}.".format(
            total,
            f", {len(touches)} datée(s) du {aujourd_hui}" if touches else ""))
    else:
        print("sitemap.xml inchangé.")


if __name__ == "__main__":
    main()
