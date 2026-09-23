#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Speed Express Shipping — retouches appliquées aux pages générées.

À lancer après « convertir-export.py ». Chaque fonction est indépendante :
si le motif recherché n'existe pas dans une page, elle la laisse intacte.
"""
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# 1. Liens hérités de l'export, y compris ceux qui portent une ancre
# --------------------------------------------------------------------------
PAGES = {
    "Speed Express Shipping": "index.html", "Goship Express": "index.html",
    "Speed Express Express": "index.html",  # séquelle d'un ancien remplacement
    "Nos-Services": "nos-services.html", "A-propos": "a-propos.html",
    "Suivi": "suivi.html", "Blog": "blog.html", "Contacts": "contacts.html",
    "Confidentialite": "confidentialite.html",
    "Termes-et-Conditions": "termes-et-conditions.html",
    "Support": "support.html",
    "Marchandises-Dangereuses": "marchandises-dangereuses.html",
    "Fermer-un-compte": "fermer-un-compte.html",
    "Article-pourquoi-goship-express": "article-pourquoi-speed-express.html",
}

def corriger_liens(html):
    """X.dc.html et X.dc.html#ancre -> x.html et x.html#ancre."""
    def remplacer(m):
        nom = m.group(1).replace("%20", " ")
        ancre = m.group(2) or ""
        cible = PAGES.get(nom)
        if cible is None:
            cible = re.sub(r"[^a-z0-9-]+", "-", nom.lower()).strip("-") + ".html"
        return 'href="' + cible + ancre + '"'
    return re.sub(r'href="([^"#]+?)\.dc\.html(#[^"]*)?"', remplacer, html)

# --------------------------------------------------------------------------
# 2. Barre supérieure (adresse, e-mail, horaires) : retirée
# --------------------------------------------------------------------------
OUVERTURE = '<div style="overflow-x:hidden">'

def retirer_barre_superieure(html):
    i = html.find(OUVERTURE)
    j = html.find("<header", i)
    if i == -1 or j == -1:
        return html
    return html[:i + len(OUVERTURE)] + "\n\n" + html[j:]

# --------------------------------------------------------------------------
# 3. Entête sur fond blanc (le logo reste tel quel)
# --------------------------------------------------------------------------
ENTETE = [
    # Fond de la barre — les deux familles de pages
    ('<header style="position:sticky;top:0;z-index:60;background:var(--ink2);border-bottom:1px solid rgba(255,255,255,.08)">',
     '<header class="ses-entete" style="position:sticky;top:0;z-index:60;background:#fff;border-bottom:1px solid var(--line);box-shadow:0 6px 24px -20px rgba(11,12,14,.6)">'),
    ('<header style="position:sticky;top:0;z-index:60;background:rgba(11,12,14,.95);backdrop-filter:blur(16px);border-bottom:1px solid rgba(255,255,255,.1)">',
     '<header class="ses-entete" style="position:sticky;top:0;z-index:60;background:#fff;border-bottom:1px solid var(--line);box-shadow:0 6px 24px -20px rgba(11,12,14,.6)">'),
    # Écrin blanc du logo : inutile sur fond blanc
    ('<span style="display:flex;align-items:center;background:#fff;border-radius:9px;padding:7px 13px;box-shadow:0 10px 24px -14px rgba(0,0,0,.9)">',
     '<span style="display:flex;align-items:center">'),
    ('<span style="display:flex;align-items:center;background:#fff;border-radius:13px;padding:8px 14px;box-shadow:0 10px 26px -14px rgba(0,0,0,.7)">',
     '<span style="display:flex;align-items:center">'),
    # Liens du menu : texte sombre
    ('<a href="index.html" style="color:#fff;border-bottom:2px solid var(--red);padding-bottom:3px"',
     '<a href="index.html" style="color:var(--red);border-bottom:2px solid var(--red);padding-bottom:3px"'),
    ('style="color:#e7eaef"', 'style="color:var(--ink)"'),
    ('style="color:#dde5f8"', 'style="color:var(--ink)"'),
    # Bloc téléphone
    ('style="display:flex;align-items:center;gap:10px;color:#fff;white-space:nowrap"',
     'style="display:flex;align-items:center;gap:10px;color:var(--ink);white-space:nowrap"'),
    ('style="display:flex;align-items:center;gap:11px;color:#fff;white-space:nowrap"',
     'style="display:flex;align-items:center;gap:11px;color:var(--ink);white-space:nowrap"'),
    ('background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);color:var(--red)',
     'background:rgba(232,18,27,.08);border:1px solid rgba(232,18,27,.25);color:var(--red)'),
    ('color:#a3abb8">Appelez-nous', 'color:#6b7280">Appelez-nous'),
    ('color:#95a5ca">APPELEZ-NOUS', 'color:#6b7280">APPELEZ-NOUS'),
    # Bouton d'appel à l'action : rouge sur blanc
    ('style="background:#fff;color:var(--ink);font-family:\'Saira\',sans-serif;font-weight:700;font-size:13px;letter-spacing:.06em;text-transform:uppercase;padding:14px 22px;border-radius:7px;white-space:nowrap"',
     'style="background:var(--red);color:#fff;font-family:\'Saira\',sans-serif;font-weight:700;font-size:13px;letter-spacing:.06em;text-transform:uppercase;padding:14px 22px;border-radius:7px;white-space:nowrap"'),
    ('style-hover="background:#d4500a;color:#fff"', 'style-hover="background:var(--red2);color:#fff"'),
]

def entete_blanche(html):
    for avant, apres in ENTETE:
        html = html.replace(avant, apres)
    # Le bouton blanc des pages SES avait un survol devenu illisible
    html = html.replace('style-hover="background:var(--red);color:#fff"',
                        'style-hover="background:var(--red2);color:#fff"')
    return html

# --------------------------------------------------------------------------
# 4. Menu repliable sur téléphone
# --------------------------------------------------------------------------
BOUTON = (
    '<button class="ses-burger" type="button" aria-label="Ouvrir le menu" aria-expanded="false" '
    'style="display:none;place-items:center;width:44px;height:44px;border-radius:9px;border:1px solid var(--line);'
    'background:#fff;cursor:pointer;flex:none">'
    '<span style="display:block;width:20px;height:2px;background:var(--ink);box-shadow:0 -6px 0 var(--ink),0 6px 0 var(--ink)"></span>'
    '</button>'
)

CSS_MENU = """
<style id="ses-entete-css">
.ses-entete nav a{transition:color .15s ease}
/* Les éléments de l'entête portent leur style en attribut : il faut
   « !important » pour que le repli sur téléphone prenne le dessus. */
@media (max-width:1050px){
  .ses-entete .ses-burger{display:grid !important;order:2}
  .ses-entete nav,.ses-entete .ses-actions{display:none !important}
  .ses-entete.ses-ouvert nav{display:flex !important;flex-direction:column;align-items:flex-start;gap:15px;width:100%;order:3;padding:14px 0 6px;border-top:1px solid var(--line)}
  .ses-entete.ses-ouvert .ses-actions{display:flex !important;width:100%;order:4;padding-bottom:12px}
  .ses-entete.ses-ouvert .ses-actions>a:last-child{flex:1;text-align:center;justify-content:center}
}
@media (max-width:560px){
  .ses-entete .ses-logo img{height:30px !important}
  .ses-entete>div{padding-left:18px !important;padding-right:18px !important}
}
</style>
"""

JS_MENU = """
<script>
(function(){
  var e=document.querySelector('.ses-entete');
  if(!e) return;
  var b=e.querySelector('.ses-burger');
  if(!b) return;
  b.addEventListener('click',function(){
    var ouvert=e.classList.toggle('ses-ouvert');
    b.setAttribute('aria-expanded',ouvert?'true':'false');
    b.setAttribute('aria-label',ouvert?'Fermer le menu':'Ouvrir le menu');
  });
  e.querySelectorAll('nav a').forEach(function(a){
    a.addEventListener('click',function(){e.classList.remove('ses-ouvert');});
  });
})();
</script>
"""

def styles_entete(html):
    """(Ré)injecte la feuille de style de l'entête, en remplaçant l'ancienne.

    Le « \\s* » en tête du motif compte : sans lui, chaque passage laissait
    derrière lui une ligne vide de plus avant le bloc."""
    html = re.sub(r'\s*<style id="ses-entete-css">.*?</style>', "", html, flags=re.S)
    return html.replace("</head>", CSS_MENU.strip() + "\n</head>", 1)

def menu_mobile(html):
    if "ses-burger" in html:
        return html
    # Marque le lien du logo et insère le bouton juste après
    i = html.find('<a href="index.html" style="display:flex;align-items:center;flex:none">')
    if i == -1:
        i = html.find('<a href="#top" style="display:flex;align-items:center;flex:none">')
    if i == -1:
        return html
    html = (html[:i] + html[i:].replace('style="display:flex;align-items:center;flex:none">',
                                        'class="ses-logo" style="display:flex;align-items:center;flex:none">', 1))
    fin_logo = html.find("</a>", html.find('class="ses-logo"')) + 4
    html = html[:fin_logo] + "\n    " + BOUTON + html[fin_logo:]
    # Marque la zone des actions (langue, téléphone, bouton devis)
    for motif in ('<div style="display:flex;flex-wrap:wrap;align-items:center;gap:10px 18px">',
                  '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:12px 20px">'):
        html = html.replace(motif, motif.replace("<div ", '<div class="ses-actions" '), 1)
    html = html.replace("</body>", JS_MENU + "</body>", 1)
    return html


# --------------------------------------------------------------------------
# 5. Camion et colis au premier plan du hero (page d'accueil)
# --------------------------------------------------------------------------
CAMION = """
  <div class="ses-hero-camion" aria-hidden="true">
    <img src="assets/img/ses-camion-colis.webp" alt="" loading="eager" decoding="async">
  </div>
"""

CSS_CAMION = """
<style id="ses-hero-css">
/* Camionnette, livreur et colis : image détourée, posée au bas du hero.
   Elle est alignée sur la même colonne que le texte (même conteneur de
   1320 px et même marge de 26 px), et le bas du hero lui réserve sa
   hauteur pour qu'elle ne remonte jamais sur le texte. */
.ses-hero-camion{position:absolute;left:0;right:0;bottom:0;margin:0 auto;max-width:1320px;
  padding:0 26px;display:flex;justify-content:flex-start;align-items:flex-end;
  pointer-events:none;z-index:1}
.ses-hero-camion img{display:block;width:min(48%,620px);height:auto;
  filter:drop-shadow(0 28px 38px rgba(0,0,0,.5))}
.ses-hero-contenu{position:relative;z-index:2}
@media (min-width:900px){
  .ses-hero-section{padding-bottom:clamp(250px,30vw,420px) !important}
}
@media (max-width:899px){
  .ses-hero-camion{display:none}
}
</style>
"""

def hero_camion(html, nom=""):
    """Insère l'image (une seule fois) ; les styles sont posés par styles_hero."""
    if nom != "index.html":
        return html
    if "ses-hero-camion" not in html:
        i = html.find('<section id="top"')
        if i == -1:
            return html
        j = html.find(">", i) + 1
        html = (html[:i]
                + html[i:j].replace('<section id="top"', '<section id="top" class="ses-hero-section"', 1)
                + CAMION + html[j:])
        html = html.replace(
            '<div style="position:relative;max-width:1320px;margin:0 auto;padding:clamp(56px,8vw,120px) 26px clamp(60px,7vw,96px);display:grid',
            '<div class="ses-hero-contenu" style="position:relative;max-width:1320px;margin:0 auto;padding:clamp(56px,8vw,120px) 26px clamp(60px,7vw,96px);display:grid', 1)
    return html

def styles_hero(html, nom=""):
    """(Ré)injecte la feuille de style du hero, en remplaçant l'ancienne."""
    if nom != "index.html":
        return html
    html = re.sub(r'\s*<style id="ses-hero-css">.*?</style>', "", html, flags=re.S)
    return html.replace("</head>", CSS_CAMION.strip() + "\n</head>", 1)

# --------------------------------------------------------------------------
# 6. Bouton principal de l'entête : « Créer un compte »
# --------------------------------------------------------------------------
# Le bouton d'appel à l'action de la barre du haut mène désormais à la
# création de compte. Les autres boutons « Demander un devis » des pages
# (hero, bas de page, articles) restent des demandes de devis : ce sont deux
# intentions différentes.

def bouton_compte(html):
    i = html.find("<header")
    j = html.find("</header>", i)
    if i == -1 or j == -1:
        return html
    entete = html[i:j]
    entete = re.sub(r'(<a href=")contacts\.html#contact("[^>]*>)Demander un devis(</a>)',
                    r'\1creer-un-compte.html\2Créer un compte\3', entete, count=1)
    return html[:i] + entete + html[j:]

# --------------------------------------------------------------------------
# 7. Lien vers l'espace client dans le pied de page
# --------------------------------------------------------------------------
# Un client déjà inscrit doit pouvoir entrer depuis n'importe quelle page,
# sans repasser par « Créer un compte ».
LIEN_CONTACT = re.compile(
    r'<a href="contacts\.html"(\s+style="[^"]*"\s+style-hover="[^"]*")>Contacts?</a>')

def lien_espace_pied(html):
    if "espace-client.html" in html:
        return html
    i = html.find("<footer")
    if i == -1:
        return html
    m = LIEN_CONTACT.search(html, i)
    if not m:
        return html
    ajout = '\n        <a href="espace-client.html"' + m.group(1) + '>Espace client</a>'
    return html[:m.end()] + ajout + html[m.end():]

# --------------------------------------------------------------------------
# 8. Version des scripts (cache des navigateurs)
# --------------------------------------------------------------------------
# Les navigateurs gardent les fichiers .js en mémoire. Sans ce numéro, une
# correction apportée à un script continue d'être ignorée pendant des jours.
# À changer ici ET dans lang-switcher.js (var V) à chaque mise à jour.
VERSION = "15"

def version_scripts(html):
    return re.sub(r'(assets/js/[A-Za-z0-9/._-]+\?v=)\d+', r'\g<1>' + VERSION, html)

# --------------------------------------------------------------------------
# 9. Apparition au défilement
# --------------------------------------------------------------------------
# Chaque grande section du site se révèle quand elle entre dans l'écran. Le
# marquage se fait ici, le mouvement dans assets/js/ses-anim.js : ce qui est
# déjà visible au chargement n'est jamais masqué, et sans JavaScript la page
# reste entière.

SCRIPT_ANIM = ('<script src="assets/js/ses-entete.js?v=' + VERSION + '" defer></script>\n'
               '<script src="assets/js/ses-anim.js?v=' + VERSION + '" defer></script>')

def animations(html):
    if "ses-entete.js" not in html:
        i = html.find('<script src="assets/js/site.js')
        if i == -1:
            i = html.find('<script src="assets/js/lang-switcher.js')
        if i == -1:
            return html
        fin = html.find("</script>", i) + len("</script>")
        html = html[:fin] + "\n" + SCRIPT_ANIM + html[fin:]
    # Les sections de l'export commencent toutes en début de ligne.
    html = re.sub(r'^<section (?!.*data-ses-reveal)', '<section data-ses-reveal="0" ',
                  html, flags=re.M)
    return html

# --------------------------------------------------------------------------
# 10. Page « Suivi » reliée aux vrais colis
# --------------------------------------------------------------------------
# Le QR code des étiquettes mène à suivi.html?colis=SES-10001-HT : la page
# doit donc interroger la base, pas se contenter du parcours de démonstration
# de la maquette. On pose ici les points d'accroche que site.js remplit, et
# les noms de statuts, rangés dans un <template> pour suivre la langue.

ACCROCHES = [
    ('<span data-ses-ref>SES-2417-HT</span>', '<span data-ses-ref>SES-2417-HT</span>'),
    ('>En transit · Miami → Santo Domingo<', ' data-ses-statut>En transit · Miami → Santo Domingo<'),
    ('>Exemple de démonstration<', ' data-ses-maj>Exemple de démonstration<'),
]

TEXTES_SUIVI = """
<template data-textes>
  <span data-t="statut-confirme">Colis confirmé</span>
  <span data-t="statut-expedie">Colis expédié</span>
  <span data-t="statut-disponible">Colis disponible</span>
  <span data-t="statut-livre">Colis livré</span>
  <span data-t="statut-action">Action requise</span>
  <span data-t="suivi-introuvable">Aucun colis ne porte ce numéro. Vérifiez-le, ou écrivez-nous sur WhatsApp.</span>
  <span data-t="suivi-maj">Dernière mise à jour : {date}</span>
  <span data-t="suivi-recherche">Recherche…</span>
</template>
"""

def suivi_reel(html, nom=""):
    if nom != "suivi.html":
        return html
    if "ses-api.js" not in html:
        i = html.find('<script src="assets/js/site.js')
        if i != -1:
            html = (html[:i] + '<script src="assets/js/ses-api.js?v=' + VERSION + '" defer></script>\n'
                    + html[i:])
    for avant, apres in ACCROCHES:
        if apres not in html:
            html = html.replace(avant, apres, 1)
    if "data-textes" not in html:
        html = html.replace("</body>", TEXTES_SUIVI + "</body>", 1)
    return html

# --------------------------------------------------------------------------
ETAPES = [corriger_liens, retirer_barre_superieure, entete_blanche, menu_mobile, styles_entete,
          bouton_compte, lien_espace_pied, animations, version_scripts]
ETAPES_NOMMEES = [hero_camion, styles_hero, suivi_reel]

def main():
    total = 0
    for f in sorted(SITE.glob("*.html")):
        avant = f.read_text(encoding="utf-8")
        apres = avant
        for etape in ETAPES:
            apres = etape(apres)
        for etape in ETAPES_NOMMEES:
            apres = etape(apres, f.name)
        if apres != avant:
            f.write_text(apres, encoding="utf-8")
            total += 1
    print(f"{total} pages retouchees.")

if __name__ == "__main__":
    main()
