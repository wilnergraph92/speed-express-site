#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Speed Express Shipping — contrôle statique SEO et indexation (phase 5).

Rejoue l'audit de la phase 5 en continu, sans réseau :

  - un h1 par page, titre 20-65 caractères, description publique 70-165 ;
  - pages publiques : canonical absolu cohérent avec og:url, og:title et
    og:description présents ; pages privées : meta robots noindex, absentes
    du sitemap ;
  - tout bloc JSON-LD valide ; fil d'Ariane (BreadcrumbList) sur toutes les
    pages publiques sauf l'accueil, positions continues, URL absolues ;
  - pages sans JSON-LD avant la phase 5 : nœud typé raccordé au site et à
    l'organisation ; nos-services : ItemList des 7 services vers des ancres
    qui existent ;
  - sitemap.xml : exactement les pages publiques, lastmod ISO, changefreq
    et priority valides, images déclarées présentes sur le disque ;
  - robots.txt : ligne Sitemap absolue et /outils/ exclu ;
  - liens internes et og:image résolus sur le disque, alt sur les images.

Lancement, depuis la racine du dépôt :  python3 outils/tests/seo-static.py
"""
import json
import os
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
os.chdir(RACINE)

BASE = "https://wilnergraph92.github.io/speed-express-site/"
ORG_ID = BASE + "#organisation"
SITE_ID = BASE + "#site"

CHANGEFREQS = {"always", "hourly", "daily", "weekly", "monthly", "yearly", "never"}

echecs = []


def ko(message):
    echecs.append(message)


def pages():
    return sorted(Path(".").glob("*.html"))


def valeur(html, motif):
    m = re.search(motif, html, re.S)
    return m.group(1).strip() if m else ""


def blocs_jsonld(html):
    """Tous les blocs JSON-LD d'une page, décodés ; les blocs invalides sont
    comptés comme échecs mais n'arrêtent pas le contrôle."""
    donnees = []
    for i, bloc in enumerate(re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', html, re.S)):
        try:
            donnees.append(json.loads(bloc))
        except ValueError as e:
            ko(f"JSON-LD invalide ({e}) bloc {i}")
    return donnees


def types_de(donnees):
    """Liste plate des @type présents, graphes compris."""
    trouves = []

    def visiter(noeud):
        if isinstance(noeud, dict):
            if "@type" in noeud:
                trouves.append(noeud["@type"])
            for v in noeud.values():
                visiter(v)
        elif isinstance(noeud, list):
            for v in noeud:
                visiter(v)

    visiter(donnees)
    return trouves


def fils_ariane(donnees):
    """Nœuds BreadcrumbList, y compris dans un @graph."""
    def tous(noeud):
        if isinstance(noeud, dict):
            if noeud.get("@type") == "BreadcrumbList":
                fils.append(noeud)
            for v in noeud.values():
                tous(v)
        elif isinstance(noeud, list):
            for v in noeud:
                tous(v)

    fils = []
    tous(donnees)
    return fils


publiques, privees = {}, {}
for f in pages():
    html = f.read_text(encoding="utf-8")
    if 'name="robots" content="noindex' in html:
        privees[f.name] = html
    else:
        publiques[f.name] = html

assert len(publiques) == 21 and len(privees) == 7, (len(publiques), len(privees))

# --- 1. bases de chaque page -------------------------------------------
for nom, html in sorted({**publiques, **privees}.items()):
    h1 = re.findall(r"<h1[\s>]", html)
    if len(h1) != 1:
        ko(f"{nom}: {len(h1)} h1 au lieu de 1")
    titre = valeur(html, r"<title>(.*?)</title>")
    if not (20 <= len(titre) <= 65):
        ko(f"{nom}: titre de {len(titre)} caractères (visé 20-65) : {titre[:70]}")
    for img in re.findall(r"<img\b[^>]*>", html):
        if "alt=" not in img:
            ko(f"{nom}: image sans alt : {img[:80]}")
    # liens internes résolus
    for url in re.findall(r'(?:href|src)="([^"#]+?)(?:#[^"]*)?"', html):
        if url.startswith(("http://", "https://", "mailto:", "tel:", "data:")):
            continue
        if url and not Path(url.split("?")[0]).exists():
            ko(f"{nom}: lien interne cassé -> {url}")

# --- 2. pages publiques : canonical, Open Graph, fil d'Ariane ----------
for nom, html in sorted(publiques.items()):
    desc = valeur(html, r'<meta name="description" content="([^"]*)"')
    if not (70 <= len(desc) <= 165):
        ko(f"{nom}: description de {len(desc)} caractères (visé 70-165)")
    canonical = valeur(html, r'<link rel="canonical" href="([^"]+)"')
    attendu = BASE if nom == "index.html" else BASE + nom
    if canonical != attendu:
        ko(f"{nom}: canonical {canonical!r} != {attendu!r}")
    ogurl = valeur(html, r'property="og:url" content="([^"]+)"')
    if ogurl != canonical:
        ko(f"{nom}: og:url {ogurl!r} != canonical {canonical!r}")
    if not valeur(html, r'property="og:title" content="([^"]+)"'):
        ko(f"{nom}: og:title absent")
    if not valeur(html, r'property="og:description" content="([^"]+)"'):
        ko(f"{nom}: og:description absent")
    ogimg = valeur(html, r'property="og:image" content="([^"]+)"')
    if ogimg.startswith(BASE):
        if not Path(ogimg[len(BASE):]).exists():
            ko(f"{nom}: og:image absente du disque : {ogimg}")
    else:
        ko(f"{nom}: og:image n'est pas une URL absolue du site : {ogimg[:60]}")

    donnees = blocs_jsonld(html)
    if nom == "index.html":
        if "Organization" not in types_de(donnees) or "WebSite" not in types_de(donnees):
            ko("index.html: Organization ou WebSite manquant")
        continue
    fils = fils_ariane(donnees)
    if len(fils) != 1:
        ko(f"{nom}: {len(fils)} BreadcrumbList au lieu de 1")
        continue
    elements = fils[0].get("itemListElement", [])
    if [e.get("position") for e in elements] != list(range(1, len(elements) + 1)):
        ko(f"{nom}: positions du fil d'Ariane non continues : {elements}")
    for e in elements:
        item = e.get("item")
        if isinstance(item, dict):
            item = item.get("@id", "")
        if not str(item).startswith("https://"):
            ko(f"{nom}: item du fil d'Ariane non absolu : {item}")
    if elements and elements[0].get("name") != "Accueil":
        ko(f"{nom}: le fil d'Ariane ne commence pas par Accueil")

# --- 3. articles : BlogPosting + fil Accueil > Blog > article ----------
articles = [n for n in publiques if n.startswith("article-")]
assert len(articles) == 11, len(articles)
for nom in articles:
    donnees = blocs_jsonld(publiques[nom])
    if "BlogPosting" not in types_de(donnees):
        ko(f"{nom}: BlogPosting manquant")
    elements = fils_ariane(donnees)[0]["itemListElement"]
    if len(elements) != 3 or elements[1].get("name") != "Blog":
        ko(f"{nom}: fil attendu Accueil > Blog > article, obtenu {elements}")

# --- 4. pages dotées d'un nœud typé en phase 5 --------------------------
PAGES_TYPEES = {
    "a-propos.html": "AboutPage",
    "nos-services.html": "WebPage",
    "suivi.html": "WebPage",
    "support.html": "WebPage",
    "marchandises-dangereuses.html": "WebPage",
    "termes-et-conditions.html": "WebPage",
    "confidentialite.html": "WebPage",
}
for nom, type_attendu in PAGES_TYPEES.items():
    donnees = blocs_jsonld(publiques[nom])
    types = types_de(donnees)
    if type_attendu not in types:
        ko(f"{nom}: nœud {type_attendu} manquant ({types})")
    if "BreadcrumbList" not in types:
        ko(f"{nom}: BreadcrumbList manquant")
    texte = json.dumps(donnees, ensure_ascii=False)
    if ORG_ID not in texte or SITE_ID not in texte:
        ko(f"{nom}: page non raccordée à {ORG_ID} / {SITE_ID}")

donnees_services = blocs_jsonld(publiques["nos-services.html"])
texte_services = json.dumps(donnees_services, ensure_ascii=False)
if '"@type": "ItemList"' not in texte_services:
    ko("nos-services.html: ItemList des services manquante")
for ancre in ("adresse-usa", "consolidation", "maritime", "aerien",
              "dedouanement", "livraison", "demenagement"):
    if f'id="{ancre}"' not in publiques["nos-services.html"]:
        ko(f"nos-services.html: ancre #{ancre} déclarée en JSON-LD absente de la page")
if texte_services.count('"@type": "Service"') != 7:
    ko("nos-services.html: 7 services attendus dans l'ItemList")

# --- 5. pages privées : noindex et hors sitemap --------------------------
for nom in privees:
    if 'name="robots" content="noindex' not in privees[nom]:
        ko(f"{nom}: page privée sans noindex")

# --- 6. sitemap.xml ------------------------------------------------------
sitemap = Path("sitemap.xml").read_text(encoding="utf-8")
urls = re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>\s*"
                  r"<changefreq>([^<]+)</changefreq>\s*<priority>([^<]+)</priority>",
                  sitemap)
attendues = {BASE if n == "index.html" else BASE + n for n in publiques}
obtenues = {u for u, _, _, _ in urls}
if obtenues != attendues:
    ko(f"sitemap: URL en trop {obtenues - attendues}; manquantes {attendues - obtenues}")
for url, derniere, frequence, priorite in urls:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", derniere):
        ko(f"sitemap {url}: lastmod non ISO {derniere!r}")
    if frequence not in CHANGEFREQS:
        ko(f"sitemap {url}: changefreq invalide {frequence!r}")
    if not (0.0 <= float(priorite) <= 1.0):
        ko(f"sitemap {url}: priority hors bornes {priorite!r}")
for image in re.findall(r"<image:loc>([^<]+)</image:loc>", sitemap):
    if not image.startswith(BASE) or not Path(image[len(BASE):]).exists():
        ko(f"sitemap: image absente du disque : {image}")
if "<image:image>" not in sitemap:
    ko("sitemap: aucune image déclarée")

# --- 7. robots.txt --------------------------------------------------------
robots = Path("robots.txt").read_text(encoding="utf-8")
if f"Sitemap: {BASE}sitemap.xml" not in robots:
    ko("robots.txt: ligne Sitemap absente ou non absolue")
if "Disallow: /outils/" not in robots:
    ko("robots.txt: /outils/ n'est plus exclu")

if echecs:
    print("ÉCHEC seo-static : {} problème(s)".format(len(echecs)))
    for e in echecs:
        print(" -", e)
    sys.exit(1)
print("PASS seo-static : 28 pages, 21 URL indexables, JSON-LD valide, "
      "fils d'Ariane continus, sitemap et robots cohérents")
