#!/usr/bin/env python3
"""
Convertit l'export Claude Design (.dc.html) en site statique.

Utilisation : décompressez l'export, faites pointer SRC sur le dossier obtenu,
puis lancez ce script, et enfin « mise-en-page.py ».

    python3 outils/convertir-export.py
    python3 outils/mise-en-page.py
"""
import re, sys
from pathlib import Path

SRC = Path("/private/tmp/claude-501/-Users-ing-wilner-Desktop-Website-GSE/346bfd9c-f8d3-405c-ba88-029d796250d8/scratchpad/ses-export")
OUT = Path("/Users/ing.wilner/Desktop/Website_SES")

# (fichier source, fichier de sortie, titre, description, rebrander)
PAGES = [
 ("Speed Express Shipping", "index.html",
  "Speed Express Shipping — Envoi de colis Miami, Santo Domingo et Haïti",
  "Réception, consolidation et livraison de vos colis entre les États-Unis, la République dominicaine et Haïti. Fret maritime et aérien, dédouanement inclus.", False),
 ("Nos-Services", "nos-services.html", "Nos services — Speed Express Shipping",
  "Adresse de réception aux USA, consolidation, fret maritime et aérien, dédouanement, livraison et retrait. Tous nos services logistiques.", False),
 ("A-propos", "a-propos.html", "À propos — Speed Express Shipping",
  "Qui nous sommes : Speed Express Shipping, votre partenaire logistique entre Miami, Santo Domingo et Haïti.", False),
 ("Suivi", "suivi.html", "Suivi de colis — Speed Express Shipping",
  "Suivez votre colis Speed Express Shipping étape par étape, de la réception à Miami jusqu'à la livraison.", False),
 ("Blog", "blog.html", "Blog — Speed Express Shipping",
  "Conseils, guides et actualités sur l'envoi de colis, le fret maritime et aérien et le commerce en ligne.", False),
 ("Contacts", "contacts.html", "Contact — Speed Express Shipping",
  "Demandez un devis gratuit en moins de 2 heures. Téléphone, WhatsApp et formulaire de contact Speed Express Shipping.", False),
 ("Confidentialite", "confidentialite.html", "Politique de confidentialité — Speed Express Shipping",
  "Comment Speed Express Shipping collecte, utilise et protège vos données personnelles.", True),
 ("Termes-et-Conditions", "termes-et-conditions.html", "Termes et conditions — Speed Express Shipping",
  "Conditions générales d'utilisation des services Speed Express Shipping.", True),
 ("Support", "support.html", "Support — Speed Express Shipping",
  "Besoin d'aide ? Contactez l'équipe Speed Express Shipping.", True),
 ("Marchandises-Dangereuses", "marchandises-dangereuses.html", "Marchandises dangereuses — Speed Express Shipping",
  "Liste des articles interdits et réglementés à l'expédition chez Speed Express Shipping.", True),
 ("Fermer-un-compte", "fermer-un-compte.html", "Fermer un compte — Speed Express Shipping",
  "Comment fermer votre compte client Speed Express Shipping.", True),
 ("Article-boutiques-chinoises", "article-boutiques-chinoises.html",
  "Les 6 meilleures boutiques chinoises pour acheter depuis la République dominicaine",
  "Shein, Temu, AliExpress… notre sélection des boutiques chinoises les plus fiables et économiques pour vos achats.", True),
 ("Article-conseils-livraison", "article-conseils-livraison.html",
  "10 conseils essentiels pour utiliser un service de livraison",
  "Éviter les mauvaises surprises : nos 10 conseils pour bien utiliser un service de livraison internationale.", True),
 ("Article-entreprise-fiable", "article-entreprise-fiable.html",
  "Une entreprise de livraison fiable : comment choisir la meilleure",
  "Les critères qui distinguent un transporteur sérieux d'un mauvais choix pour vos envois.", True),
 ("Article-impact-ecommerce", "article-impact-ecommerce.html",
  "L'impact des services de livraison sur le commerce électronique en République dominicaine",
  "Comment la logistique transforme le commerce en ligne dominicain.", True),
 ("Article-maritime-vs-aerien", "article-maritime-vs-aerien.html",
  "Transport maritime ou aérien : lequel choisir ?",
  "Délais, coûts, types de marchandises : le comparatif complet entre fret maritime et fret aérien.", True),
 ("Article-optimiser-expeditions", "article-optimiser-expeditions.html",
  "Comment optimiser les expéditions dans votre entreprise",
  "Réduire les coûts et les délais d'expédition : méthodes concrètes pour les entreprises.", True),
 ("Article-partenaire-colis-etranger", "article-partenaire-colis-etranger.html",
  "Votre partenaire de confiance pour recevoir vos colis depuis l'étranger",
  "Pourquoi passer par un consolidateur pour recevoir vos achats internationaux.", True),
 ("Article-pourquoi-goship-express", "article-pourquoi-speed-express.html",
  "Pourquoi Speed Express Shipping est votre meilleur choix",
  "Ce qui distingue Speed Express Shipping des autres transporteurs sur le corridor Miami — Santo Domingo — Haïti.", True),
 ("Article-premiere-livraison", "article-premiere-livraison.html",
  "Erreurs courantes lors de l'utilisation d'un service de livraison",
  "Les pièges les plus fréquents pour une première expédition, et comment les éviter.", True),
 ("Article-service-de-messagerie", "article-service-de-messagerie.html",
  "Qu'est-ce qu'un service de messagerie et comment fonctionne-t-il ?",
  "Le fonctionnement d'un service de messagerie internationale, expliqué simplement.", True),
 ("Article-tendances-2026", "article-tendances-2026.html",
  "Tendances de la logistique et de la livraison de colis pour 2026",
  "Ce qui change en 2026 dans la logistique et la livraison de colis.", True),
]

LIENS = {
 "Speed%20Express%20Shipping.dc.html": "index.html",
 "Speed Express Shipping.dc.html": "index.html",
 "Goship%20Express.dc.html": "index.html",
 "Goship Express.dc.html": "index.html",
 "Article-pourquoi-goship-express.dc.html": "article-pourquoi-speed-express.html",
}
for s, o, *_ in PAGES:
    LIENS.setdefault(s + ".dc.html", o)
    LIENS.setdefault(s.replace(" ", "%20") + ".dc.html", o)

IMAGES = {
 'src="ses-logo.png"': 'src="assets/img/ses-logo.png"',
 'src="./ses-logo.png"': 'src="assets/img/ses-logo.png"',
 'src="ses-truck.png"': 'src="assets/img/ses-truck.jpg"',
 'src="./ses-truck.png"': 'src="assets/img/ses-truck.jpg"',
 'src="ses-driver.png"': 'src="assets/img/ses-driver.jpg"',
 'src="./ses-driver.png"': 'src="assets/img/ses-driver.jpg"',
 'src="ses-van-team.png"': 'src="assets/img/ses-van-team.jpg"',
 'src="./ses-van-team.png"': 'src="assets/img/ses-van-team.jpg"',
 'src="goship-logo.png"': 'src="assets/img/ses-logo.png"',
 'src="./goship-logo.png"': 'src="assets/img/ses-logo.png"',
 'src="./logo-w-mu7cz2s7-qtjg.png"': 'src="assets/img/ses-logo.png"',
 'src="logo-w-mu7cz2s7-qtjg.png"': 'src="assets/img/ses-logo.png"',
}

MARQUE = [
 ("goshipexpressllc@gmail.com", "speedexpresshipping@gmail.com"),
 ("+18495386262", "+18292653727"), ("18495386262", "18292653727"),
 ("849 538-6262", "829 265-3727"), ("849 538 6262", "829 265 3727"),
 ("8140 NW 74th Ave, Unit 3, Apt 46780, Medley, Florida 33166",
  "C. Fausto Cejas Rodriguez #89 k12, Las Américas, Santo Domingo Este"),
 ("8140 NW 74th Ave, Unit 3, Apt 46780",
  "C. Fausto Cejas Rodriguez #89 k12, Las Américas, Santo Domingo Este"),
 ("8140 NW 74th Ave", "C. Fausto Cejas Rodriguez #89 k12"),
 ("Medley, Florida 33166", "Las Américas, Santo Domingo Este"),
 ("Boxpaq", "Speed Express Shipping"),
 ("BOXPAQ", "SPEED EXPRESS SHIPPING"),
 ("GOSHIP EXPRESS", "SPEED EXPRESS SHIPPING"),
 ("GOShip Express", "Speed Express Shipping"), ("GOShip", "Speed Express"),
 ("GoShip Express", "Speed Express Shipping"), ("Goship Express", "Speed Express Shipping"),
 ("GOSHIP", "SPEED EXPRESS"), ("GoShip", "Speed Express"), ("Goship", "Speed Express"),
 ("goship", "speed-express"),
]


CHAMPS = [
 ('<input required placeholder="Votre nom"', '<input required name="Nom" placeholder="Votre nom"'),
 ('<input required type="email"', '<input required name="Email" type="email"'),
 ('<input placeholder="829 000-0000"', '<input name="Téléphone" placeholder="829 000-0000"'),
 ('<select ', '<select name="Service" '),
 ('<textarea required rows="5"', '<textarea required name="Message" rows="5"'),
]

def nommer_champs(corps):
    for a, b in CHAMPS:
        corps = corps.replace(a, b, 1)
    return corps


# Palette GoShip (bleu marine + orange) -> palette Speed Express (noir + rouge)
COULEURS = [
 ("#f4600d", "#e8121b"),   # orange vif      -> rouge Speed Express
 ("#061a3f", "#0b0c0e"),   # bleu marine     -> noir d'encre
 ("#0d2b6b", "#14161a"),   # bleu moyen      -> noir 2
 ("#1746a8", "#20242a"),   # bleu clair      -> noir 3
 ("#1f5fe0", "#1a2ed2"),   # bleu secondaire -> bleu Speed Express
 ("#e7edf9", "#e2e5ea"),   # brume bleutee   -> gris de trait
 ("#f5f7fb", "#f5f6f8"),   # creme bleutee   -> gris clair
 ("#f4f6fa", "#f5f6f8"),   # gris bleute     -> gris clair
 ("--r:18px", "--r:12px"), # coins tres arrondis -> coins Speed Express
]

def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

def recolorer(corps):
    for a, b in COULEURS:
        corps = corps.replace(a, b).replace(a.upper(), b)
    # Les memes couleurs ecrites en rgb()/rgba() : rgba(6,26,63,.4) etc.
    for a, b in COULEURS:
        if not a.startswith("#"):
            continue
        ra, rb = _rgb(a), _rgb(b)
        for sep in (",", ", "):
            corps = corps.replace(sep.join(map(str, ra)), sep.join(map(str, rb)))
    return corps


def uniformiser_nav(corps):
    """Les pages reprises de GoShip n'ont pas de lien Suivi : on l'ajoute,
       et on aligne les libelles sur ceux des pages Speed Express."""
    def inserer(m):
        ouvre, ferme = m.group(1), m.group(2)
        lien_suivi = ouvre.replace('href="nos-services.html"', 'href="suivi.html"') + "Suivi" + ferme
        return ouvre + "Services" + ferme + lien_suivi
    corps = re.sub(r'(<a href="nos-services\.html"[^>]*>)Nos Services(</a>)', inserer, corps)
    corps = corps.replace(">Contacts</a>", ">Contact</a>")
    return corps

def resoudre_scif(s):
    STATIQUES = {"showTracking", "showPricing"}
    while True:
        fin = s.find("</sc-if>")
        if fin == -1:
            break
        deb = s.rfind("<sc-if", 0, fin)
        if deb == -1:
            break
        fin_balise = s.find(">", deb)
        balise = s[deb:fin_balise + 1]
        interieur = s[fin_balise + 1:fin]
        mv = re.search(r'value="\{\{\s*(\w+)\s*\}\}"', balise)
        var = mv.group(1) if mv else "bloc"
        md = re.search(r'hint-placeholder-val="\{\{\s*(\w+)\s*\}\}"', balise)
        defaut = md.group(1) if md else "true"
        if defaut == "true":
            remp = interieur if var in STATIQUES else f'<div data-ses-if="{var}">{interieur}</div>'
        else:
            remp = f'<div data-ses-if="{var}" hidden>{interieur}</div>'
        s = s[:deb] + remp + s[fin + len("</sc-if>"):]
    return s

def resoudre_liaisons(s):
    s = s.replace('onSubmit="{{ onTrack }}"', 'data-ses-form="suivi"')
    s = s.replace('onSubmit="{{ onSubmit }}"', 'data-ses-form="contact"')
    s = s.replace('onClick="{{ onReset }}"', 'data-ses-reset="contact"')
    s = re.sub(r'value="\{\{ trackValue \}\}"\s*onChange="\{\{ \w+ \}\}"', 'data-ses-input="suivi"', s)
    s = re.sub(r'onChange="\{\{ \w+ \}\}"', "", s)
    s = re.sub(r'\{\{\s*(trackResult|result)\s*\}\}', '<span data-ses-ref>SES-2417-HT</span>', s)
    s = re.sub(r'\s*on[A-Z][a-zA-Z]*="\{\{[^}]*\}\}"', "", s)
    s = re.sub(r'\s*\w+="\{\{[^}]*\}\}"', "", s)
    s = re.sub(r'\{\{[^}]*\}\}', "", s)
    return s

GABARIT = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titre}</title>
<meta name="description" content="{desc}">
<meta name="theme-color" content="#0b0c0e">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Speed Express Shipping">
<meta property="og:title" content="{titre}">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="assets/img/ses-logo.png">
<meta property="og:locale" content="fr_FR">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" type="image/png" sizes="32x32" href="assets/img/favicon-32.png">
<link rel="apple-touch-icon" href="assets/img/favicon-180.png">
{tetes}
{style}
<script src="assets/js/config.js?v=6" defer></script>
<script src="assets/js/lang-dict.js?v=6" defer></script>
<script src="assets/js/lang-switcher.js?v=6" defer></script>
<script src="assets/js/site.js?v=6" defer></script>
</head>
<body>
{corps}
</body>
</html>
"""

def convertir(stem, sortie, titre, desc, rebrander):
    brut = (SRC / f"{stem}.dc.html").read_text(encoding="utf-8")
    mh = re.search(r"<helmet>(.*?)</helmet>", brut, re.S)
    helmet = mh.group(1) if mh else ""
    style = "\n".join(re.findall(r"<style>.*?</style>", helmet, re.S))
    tetes = "\n".join(l.strip() for l in re.findall(r'<link [^>]*>', helmet)
                      if "fonts.g" in l)
    corps = brut.split("</helmet>", 1)[1].split("</x-dc>")[0]
    corps = resoudre_scif(corps)
    corps = resoudre_liaisons(corps)
    for a, b in IMAGES.items():
        corps = corps.replace(a, b)
    corps = corps.replace('src="./lang-dict.js"', 'src="assets/js/lang-dict.js"')
    corps = corps.replace('src="./lang-switcher.js"', 'src="assets/js/lang-switcher.js"')
    corps = re.sub(r'<script[^>]*src="\./(support|lang-[^"]*)\.js"[^>]*>\s*</script>', "", corps)
    for a, b in LIENS.items():
        corps = corps.replace(f'href="{a}"', f'href="{b}"')
    if rebrander:
        for a, b in MARQUE:
            corps = corps.replace(a, b)
        corps = recolorer(corps)
        corps = uniformiser_nav(corps)
        style = recolorer(style)
    if sortie == "contacts.html":
        corps = nommer_champs(corps)
    page = GABARIT.format(titre=titre, desc=desc, tetes=tetes, style=style, corps=corps.strip())
    (OUT / sortie).write_text(page, encoding="utf-8")
    return len(page)

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    total = 0
    for p in PAGES:
        n = convertir(*p)
        total += n
        print(f"  {p[1]:42} {n//1024:4} Ko")
    print(f"\n{len(PAGES)} pages, {total//1024} Ko au total")
