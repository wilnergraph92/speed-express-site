#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Speed Express Shipping — régénération depuis les sources versionnées.

Commande sans argument : outils/pages + outils/communs + outils/espace → 28 pages.
Les anciennes fonctions de migration restent importables par les tests des
phases précédentes ; elles ne sont plus rejouées sur les pages publiées.
"""
import json
import re
import sys
from html import escape as echapper, unescape as dechiffrer
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Le module reste utilisable quand les tests chargent cet outil via runpy.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from accessibilite import appliquer as appliquer_accessibilite

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
# 2b. Conteneur : « clip » plutôt que « hidden »
# --------------------------------------------------------------------------
# « overflow-x:hidden » sur l'ancêtre casse le « position:sticky » de
# l'entête (l'axe vertical calculé devient « auto », le conteneur ne colle
# plus à la fenêtre). « overflow-x:clip » coupe le débordement horizontal
# exactement pareil, sans créer de conteneur de défilement : le sticky
# refonctionne, et rien d'autre ne change.
def overflow_clip(html):
    return html.replace(OUVERTURE, '<div style="overflow-x:clip">')

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
    # Liens du menu : texte sombre. Le lien actif garde son soulignement rouge
    # mais en rouge sur blanc (et non plus blanc sur blanc, illisible).
    ('style="color:#fff;border-bottom:2px solid var(--red);padding-bottom:3px"',
     'style="color:var(--red);border-bottom:2px solid var(--red);padding-bottom:3px"'),
    ('style="color:#ebebeb"', 'style="color:var(--ink)"'),
    ('style="color:#ebebeb"', 'style="color:var(--ink)"'),
    # Bloc téléphone
    ('style="display:flex;align-items:center;gap:10px;color:#fff;white-space:nowrap"',
     'style="display:flex;align-items:center;gap:10px;color:var(--ink);white-space:nowrap"'),
    ('style="display:flex;align-items:center;gap:11px;color:#fff;white-space:nowrap"',
     'style="display:flex;align-items:center;gap:11px;color:var(--ink);white-space:nowrap"'),
    ('background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);color:var(--red)',
     'background:rgba(232,18,27,.08);border:1px solid rgba(232,18,27,.25);color:var(--red)'),
    ('color:#a3abb8">Appelez-nous', 'color:#6b7280">Appelez-nous'),
    ('color:#b0b0b0">APPELEZ-NOUS', 'color:#6b7280">APPELEZ-NOUS'),
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
    <picture>
      <source media="(min-width: 900px)" type="image/webp"
              srcset="assets/img/ses-camion-colis-640.webp 640w, assets/img/ses-camion-colis.webp 1280w"
              sizes="(min-width: 1320px) 620px, 48vw">
      <img src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=" alt=""
           width="1536" height="1024" loading="eager" decoding="async" fetchpriority="low">
    </picture>
  </div>
"""

CSS_CAMION = """
<style id="ses-hero-css">
/* Camionnette, livreur et colis : image détourée, posée au bas du hero.
   La source n'existe que sur grand écran : le téléphone ne télécharge donc
   pas cette décoration masquée. */
.ses-hero-camion{position:absolute;left:0;right:0;bottom:0;margin:0 auto;max-width:1320px;
  padding:0 26px;display:flex;justify-content:flex-start;align-items:flex-end;
  pointer-events:none;z-index:1}
.ses-hero-camion picture{display:block;width:min(48%,620px);height:auto;
  filter:drop-shadow(0 28px 38px rgba(0,0,0,.5))}
.ses-hero-camion img{display:block;width:100%;height:auto}
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
    """Actualise la source responsive, sans charger le détourage sur téléphone."""
    if nom != "index.html":
        return html
    section = re.search(r'<section\b(?=[^>]*\bid=["\']top["\'])[^>]*>',
                        html, flags=re.I)
    if not section:
        return html
    ouverture = section.group(0)
    if 'ses-hero-section' not in ouverture:
        if re.search(r'\bclass=["\']', ouverture, flags=re.I):
            ouverture = re.sub(r'\bclass=(["\'])(.*?)\1',
                lambda m: 'class=' + m.group(1) + (m.group(2) + ' ses-hero-section' if m.group(2) else 'ses-hero-section') + m.group(1),
                ouverture, count=1, flags=re.I)
        else:
            ouverture = ouverture[:-1] + ' class="ses-hero-section">'
        html = html[:section.start()] + ouverture + html[section.end():]
    camion = re.compile(r'<div class="ses-hero-camion"[^>]*>.*?</div>', flags=re.S)
    if camion.search(html):
        html = camion.sub(lambda m: CAMION.strip(), html, count=1)
    else:
        section = re.search(r'<section\b(?=[^>]*\bid=["\']top["\'])[^>]*>',
                            html, flags=re.I)
        if section:
            html = html[:section.end()] + '\n' + CAMION.strip() + html[section.end():]
    if 'ses-hero-contenu' not in html:
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
# 8. Images responsives et secours des photos externes
# --------------------------------------------------------------------------
# Le HTML statique est aussi la source de déploiement : ces retouches vivent
# donc dans le générateur et restent présentes après une nouvelle exportation.

def valeur_attribut(balise, nom):
    motif = re.search(r'\b' + re.escape(nom) + r'\s*=\s*(["\'])(.*?)\1',
                      balise, flags=re.I | re.S)
    return dechiffrer(motif.group(2)) if motif else None


def valeur_attribut_brute(balise, nom):
    """Comme valeur_attribut, mais garde l'écriture HTML d'origine.

    Indispensable pour recopier une URL telle quelle : « &amp; » doit rester
    « &amp; » une fois remis dans une balise, sinon l'adresse est abîmée.
    """
    motif = re.search(r'\b' + re.escape(nom) + r'\s*=\s*(["\'])(.*?)\1',
                      balise, flags=re.I | re.S)
    return motif.group(2) if motif else None


def poser_attribut(balise, nom, valeur):
    """Ajoute ou remplace un attribut sans réécrire le reste de la balise."""
    motif = re.compile(r'(\s+' + re.escape(nom) + r'\s*=\s*)(["\'])(.*?)\2',
                       flags=re.I | re.S)
    valeur = echapper(str(valeur), quote=True)
    if motif.search(balise):
        return motif.sub(lambda m: m.group(1) + m.group(2) + valeur + m.group(2),
                         balise, count=1)
    fin = balise.rfind('>')
    if fin == -1:
        return balise
    return balise[:fin] + ' ' + nom + '="' + valeur + '"' + balise[fin:]


def url_unsplash_largeur(url, largeur):
    morceaux = urlsplit(url)
    parametres = [(k, v) for k, v in parse_qsl(morceaux.query, keep_blank_values=True)
                  if k != 'w']
    if not any(k == 'q' for k, _ in parametres):
        parametres.append(('q', '72'))
    parametres.append(('w', str(largeur)))
    return urlunsplit((morceaux.scheme, morceaux.netloc, morceaux.path,
                       urlencode(parametres), morceaux.fragment))


def images_responsives(html):
    """Prépare des tailles adaptées sans changer le cadrage des photos."""
    def modifier(m):
        balise = m.group(0)
        source = valeur_attribut(balise, 'src') or ''
        style = valeur_attribut(balise, 'style') or ''
        chargement = (valeur_attribut(balise, 'loading') or '').lower()

        if source == 'assets/img/ses-logo.png':
            # WebP sans perte pour le site ; le PNG original reste le repli des
            # anciens navigateurs, des aperçus sociaux et des courriels.
            balise = poser_attribut(balise, 'width', '616')
            balise = poser_attribut(balise, 'height', '240')
            balise = poser_attribut(balise, 'decoding', 'async')
            debut_picture = html.rfind('<picture class="ses-logo-responsive"', 0, m.start())
            fin_picture = html.rfind('</picture>', 0, m.start())
            if debut_picture > fin_picture:
                return balise
            return ('<picture class="ses-logo-responsive" style="display:block">'
                    '<source type="image/webp" srcset="assets/img/ses-logo.webp">' +
                    balise + '</picture>')

        est_hero_lcp = ('position:absolute' in style and 'inset:0' in style and
                        'object-fit:cover' in style)

        if source == 'assets/img/ses-truck.jpg':
            balise = poser_attribut(balise, 'srcset',
                'assets/img/ses-truck-480.jpg 480w, '
                'assets/img/ses-truck-800.jpg 800w, '
                'assets/img/ses-truck-1200.jpg 1200w, '
                'assets/img/ses-truck.jpg 1584w')
            if '196px' in style:
                tailles = ('(max-width: 680px) calc(100vw - 52px), '
                           '(max-width: 1000px) calc(50vw - 38px), 407px')
            elif chargement == 'lazy':
                tailles = ('(max-width: 680px) calc(100vw - 52px), '
                           '(max-width: 1320px) 48vw, 622px')
            else:
                tailles = '100vw'
                if est_hero_lcp:
                    balise = poser_attribut(balise, 'fetchpriority', 'high')
            balise = poser_attribut(balise, 'sizes', tailles)
            balise = poser_attribut(balise, 'width', '1584')
            balise = poser_attribut(balise, 'height', '672')
            balise = poser_attribut(balise, 'decoding', 'async')
            return balise

        if source in ('assets/img/ses-driver.jpg', 'assets/img/ses-van-team.jpg'):
            nom = 'ses-driver' if source.endswith('ses-driver.jpg') else 'ses-van-team'
            hauteur = '800' if nom == 'ses-driver' else '675'
            balise = poser_attribut(balise, 'srcset',
                'assets/img/' + nom + '-480.jpg 480w, '
                'assets/img/' + nom + '-800.jpg 800w, '
                'assets/img/' + nom + '.jpg 1200w')
            if nom == 'ses-van-team' and '120px' in style:
                tailles = '(max-width: 600px) 220px, 300px'
            else:
                tailles = ('(max-width: 680px) calc(100vw - 52px), '
                           '(max-width: 1320px) 48vw, 622px')
            balise = poser_attribut(balise, 'sizes', tailles)
            balise = poser_attribut(balise, 'width', '1200')
            balise = poser_attribut(balise, 'height', hauteur)
            balise = poser_attribut(balise, 'decoding', 'async')
            return balise

        if not source.startswith('https://images.unsplash.com/'):
            return balise

        morceaux = urlsplit(source)
        parametres = dict(parse_qsl(morceaux.query, keep_blank_values=True))
        try:
            largeur_source = int(parametres.get('w', '2000'))
        except ValueError:
            largeur_source = 2000
        largeurs = (320, 480, 640, 900) if largeur_source <= 1000 else (480, 800, 1200, 1600, 2000)
        srcset = ', '.join(url_unsplash_largeur(source, largeur) + ' ' + str(largeur) + 'w'
                           for largeur in largeurs)
        balise = poser_attribut(balise, 'srcset', srcset)
        if largeur_source <= 1000:
            tailles = ('(max-width: 700px) calc(100vw - 52px), '
                       '(max-width: 1000px) calc(50vw - 38px), 407px')
        else:
            tailles = '100vw'
        balise = poser_attribut(balise, 'sizes', tailles)
        balise = poser_attribut(balise, 'referrerpolicy', 'no-referrer')
        balise = poser_attribut(balise, 'decoding', 'async')
        alt = (valeur_attribut(balise, 'alt') or '').lower()
        if 'camion' in alt or 'truck' in alt:
            balise = poser_attribut(balise, 'data-fallback', 'assets/img/ses-truck-1200.jpg')
        if est_hero_lcp:
            balise = poser_attribut(balise, 'fetchpriority', 'high')
        return balise

    return re.sub(r'<img\b[^>]*>', modifier, html, flags=re.I)


def preconnect_images_externes(html):
    """Preconnect only for eager above-the-fold external images, not lazy galleries."""
    motif = re.compile(
        r'[ \t]*<link\b(?=[^>]*\brel=["\']preconnect["\'])'
        r'(?=[^>]*\bhref=["\']https://images\.unsplash\.com["\'])'
        r'[^>]*>[ \t]*(?:\r?\n)?', flags=re.I)
    existants = motif.findall(html)
    eager = any((valeur_attribut(tag, 'src') or '').startswith('https://images.unsplash.com/')
                and valeur_attribut(tag, 'loading') != 'lazy'
                for tag in re.findall(r'<img\b[^>]*>', html, flags=re.I))
    if not eager:
        return motif.sub('', html)
    lien = '<link rel="preconnect" href="https://images.unsplash.com" crossorigin>'
    if len(existants) == 1 and existants[0].strip() == lien:
        return html
    return motif.sub('', html).replace('</head>', lien + '\n</head>', 1)


def icone_apple_dimensionnee(html):
    """Déclare correctement le PNG 180×180 employé par l'écran d'accueil iOS."""
    def modifier(m):
        balise = m.group(0)
        if re.search(r'\bsizes\s*=', balise, flags=re.I):
            return balise
        return balise.replace('<link rel="apple-touch-icon"',
                              '<link rel="apple-touch-icon" sizes="180x180"', 1)
    return re.sub(r'<link\b[^>]*rel=["\']apple-touch-icon["\'][^>]*>',
                  modifier, html, flags=re.I)


def retirer_template_bundler(html):
    """Élimine l'aperçu résiduel à la source, y compris après réexportation."""
    return re.sub(
        r'[ \t]*<template\b(?=[^>]*\bid=["\']__bundler_thumbnail["\'])'
        r'[^>]*>.*?</template>[ \t]*(?:\r?\n)?',
        '', html, flags=re.I | re.S)

def dictionnaires_differe(html):
    """The common dictionary is only fetched on demand by lang-switcher.js."""
    return re.sub(r'[ \t]*<script\b(?=[^>]*\bsrc=["\']assets/js/lang-dict\.js(?:\?[^"\']*)?["\'])[^>]*>\s*</script>[ \t]*(?:\r?\n)?', '', html, flags=re.I)


def performance_images(html):
    """Select modern derivatives without changing crop, classes or carousel nodes."""
    def modifier(m):
        tag = m.group(0)
        src = valeur_attribut(tag, 'src') or ''
        # A source inserted by a prior run means the picture is already complete.
        before = html[:m.start()]
        if before.rfind('<picture') > before.rfind('</picture>'):
            return tag
        names = {'ses-truck': (1584,672), 'hero-avion': (1584,672), 'hero-navire': (1376,768)}
        name = next((n for n in names if src == 'assets/img/'+n+'.jpg'), None)
        if name:
            width,height = names[name]
            sizes = valeur_attribut(tag,'sizes') or '100vw'
            tag = poser_attribut(tag,'width',str(width))
            tag = poser_attribut(tag,'height',str(height))
            # These pictures are block containers only where an existing image was block.
            css = 'display:block'
            classes = valeur_attribut(tag,'class') or ''
            if 'hero__fond' in classes:
                # Hero JS still targets the img; the picture provides source selection only.
                css = 'display:contents'
            variants = ', '.join('assets/img/'+name+('-'+str(w) if w!=width else '')+'.webp '+str(w)+'w'
                                 for w in [480,800,1200,width])
            return ('<picture data-ses-responsive style="'+css+'"><source type="image/webp" srcset="'+variants+'" sizes="'+sizes+'">'+tag+'</picture>')
        if src == 'assets/img/ses-camion-colis.webp':
            # Current index uses this image visibly on mobile: never hide it.
            tag = poser_attribut(tag,'srcset','assets/img/ses-camion-colis-480.webp 480w, assets/img/ses-camion-colis-640.webp 640w, assets/img/ses-camion-colis-800.webp 800w, assets/img/ses-camion-colis.webp 1280w')
            tag = poser_attribut(tag,'sizes','(max-width: 700px) calc(100vw - 52px), (max-width: 1280px) 48vw, 600px')
            tag = poser_attribut(tag,'width','1280')
            tag = poser_attribut(tag,'height','853')
        if src.startswith('https://images.unsplash.com/'):
            tag = poser_attribut(tag,'referrerpolicy','no-referrer')
            if not valeur_attribut(tag,'data-fallback'):
                tag = poser_attribut(tag,'data-fallback','assets/img/ses-truck-800.jpg')
        return tag
    html = re.sub(r'<img\b[^>]*>',modifier,html,flags=re.I)
    # Match the preload to the picture's format and candidate, not the JPEG fallback.
    for name in ('ses-truck','hero-avion','hero-navire'):
        pattern = r'<picture\b[^>]*data-ses-responsive[^>]*>(<source\b[^>]*>)(<img\b[^>]*fetchpriority="high"[^>]*>)</picture>'
        for match in re.finditer(pattern,html):
            source,img = match.groups()
            if valeur_attribut(img,'src') != 'assets/img/'+name+'.jpg': continue
            link = '<link rel="preload" as="image" type="image/webp" href="assets/img/'+name+'.webp" data-ses-preload="lcp" imagesrcset="'+valeur_attribut_brute(source,'srcset')+'" imagesizes="'+valeur_attribut_brute(source,'sizes')+'" fetchpriority="high">'
            # Préserver sa place si le lien est déjà correct : les phases
            # SEO/accessibilité peuvent ajouter des balises après celui-ci.
            existants = LIEN_PRECHARGEMENT.findall(html)
            if len(existants) == 1 and existants[0].strip() == link:
                break
            html = LIEN_PRECHARGEMENT.sub('',html)
            html = html.replace('</head>',link+'\n</head>',1)
            break
    return html

# --------------------------------------------------------------------------
# 8b. Vitesse de chargement : polices en une requête, photo principale préchargée
# --------------------------------------------------------------------------
# Deux feuilles Google Fonts, c'est deux allers-retours qui bloquent le premier
# pixel. Les familles sont réunies dans une seule adresse : même rendu, une
# seule requête. Les paramètres d'origine sont recopiés tels quels (aucun
# réencodage) pour ne rien casser dans les noms de familles.
#
# La photo du hero est l'élément le plus visible de la page (LCP). Sans
# préchargement, le navigateur ne la découvre qu'en lisant le <body> ; avec le
# lien ci-dessous il la demande dès l'en-tête. Le srcset et le sizes repris à
# l'identique garantissent que le fichier préchargé est exactement celui qui
# sera affiché — un préchargement qui ne correspond pas serait téléchargé deux
# fois, donc pire que rien.

LIEN_PRECHARGEMENT = re.compile(
    r'[ \t]*<link\b(?=[^>]*\bdata-ses-preload=["\']lcp["\'])[^>]*>[ \t]*(?:\r?\n)?',
    flags=re.I)


def polices_une_requete(html):
    """Réunit les feuilles Google Fonts d'une page en une seule requête."""
    motif = re.compile(
        r'<link\b(?=[^>]*\bhref=["\']https://fonts\.googleapis\.com/css2\?)'
        r'(?=[^>]*\brel=["\']stylesheet["\'])[^>]*>', flags=re.I)
    # La même balise, mais avec sa ligne entière : enlever un doublon ne doit
    # pas laisser une ligne vide derrière lui.
    motif_ligne = re.compile(
        r'[ \t]*<link\b(?=[^>]*\bhref=["\']https://fonts\.googleapis\.com/css2\?)'
        r'(?=[^>]*\brel=["\']stylesheet["\'])[^>]*>[ \t]*(?:\r?\n)?', flags=re.I)
    liens = motif.findall(html)
    if len(liens) < 2:
        return html
    familles = []
    affichage = None
    for lien in liens:
        adresse = valeur_attribut_brute(lien, 'href') or ''
        requete = adresse.split('?', 1)[1] if '?' in adresse else ''
        separateur = '&amp;' if '&amp;' in requete else '&'
        for morceau in requete.split(separateur):
            if not morceau:
                continue
            if morceau.startswith('display='):
                affichage = morceau  # une seule fois, et toujours en dernier
            elif morceau not in familles:
                familles.append(morceau)
    if not familles:
        return html
    morceaux = familles + ([affichage] if affichage else [])
    nouveau = ('<link href="https://fonts.googleapis.com/css2?' +
               '&amp;'.join(morceaux) + '" rel="stylesheet">\n')
    emplacement = motif_ligne.search(html).start()
    nettoye = motif_ligne.sub('', html)
    # Tout ce qui précède la première balise est intact : l'indice reste valable.
    return nettoye[:emplacement] + nouveau + nettoye[emplacement:]


def preload_image_principale(html):
    """Précharge la photo la plus visible de la page dès l'en-tête."""
    html = LIEN_PRECHARGEMENT.sub('', html)
    images = re.findall(r'<img\b[^>]*\bfetchpriority=["\']high["\'][^>]*>',
                        html, flags=re.I)
    if not images:
        return html
    balise = images[0]
    source = valeur_attribut_brute(balise, 'src')
    if not source:
        return html
    lien = ('<link rel="preload" as="image" href="' + source +
            '" data-ses-preload="lcp"')
    jeu = valeur_attribut_brute(balise, 'srcset')
    if jeu:
        lien += ' imagesrcset="' + jeu + '"'
        tailles = valeur_attribut_brute(balise, 'sizes')
        if tailles:
            lien += ' imagesizes="' + tailles + '"'
    lien += ' fetchpriority="high">'
    feuille = re.search(r'<link\b[^>]*\brel=["\']stylesheet["\'][^>]*>', html,
                        flags=re.I)
    if feuille:
        return html[:feuille.start()] + lien + '\n' + html[feuille.start():]
    return html.replace('</head>', lien + '\n</head>', 1)


# --------------------------------------------------------------------------
# 9. Version des scripts (cache des navigateurs)
# --------------------------------------------------------------------------
# Les navigateurs gardent les fichiers .js en mémoire. Sans ce numéro, une
# correction apportée à un script continue d'être ignorée pendant des jours.
# À changer ici ET dans lang-switcher.js (var V) à chaque mise à jour.
# Ce numéro était resté à 22 alors que les pages appelaient déjà du 24, du 25
# et du 26 : un même fichier (ses-api.js, 68 Ko) était donc téléchargé sous
# trois adresses différentes et le cache ne servait à rien d'une page à
# l'autre. Tout est ramené au numéro courant de lang-switcher.js.
VERSION = "32"

def version_scripts(html):
    return re.sub(r'(assets/js/[A-Za-z0-9/._-]+\?v=)\d+', r'\g<1>' + VERSION, html)

# --------------------------------------------------------------------------
# 10. Apparition au défilement
# --------------------------------------------------------------------------
# Chaque grande section du site se révèle quand elle entre dans l'écran. Le
# marquage se fait ici, le mouvement dans assets/js/ses-anim.js : ce qui est
# déjà visible au chargement n'est jamais masqué, et sans JavaScript la page
# reste entière.

SCRIPT_ENTETE = '<script src="assets/js/ses-entete.js?v=' + VERSION + '" defer></script>'
SCRIPT_ANIM = '<script src="assets/js/ses-anim.js?v=' + VERSION + '" defer></script>'


def _motif_script(fichier):
    return re.compile(
        r'<script\b(?=[^>]*\bsrc=["\']assets/js/' + re.escape(fichier) +
        r'(?:\?[^"\']*)?["\'])[^>]*>\s*</script>', flags=re.I)


def _unique_script(html, fichier):
    """Garde la première inclusion du script et enlève les copies dupliquées."""
    garder = [True]
    def garder_premiere(m):
        if garder[0]:
            garder[0] = False
            return m.group(0)
        return ''
    return _motif_script(fichier).sub(garder_premiere, html)


def _inserer_script(html, apres, balise):
    motif = _motif_script(apres)
    trouve = motif.search(html)
    if trouve:
        return html[:trouve.end()] + '\n' + balise + html[trouve.end():]
    return html.replace('</head>', balise + '\n</head>', 1)


def animations(html):
    # Le fichier existant contient parfois deux balises d'animation :
    # dédoublonner ici garantit aussi que les prochaines générations restent propres.
    html = _unique_script(html, 'ses-entete.js')
    html = _unique_script(html, 'ses-anim.js')
    if not _motif_script('ses-entete.js').search(html):
        ancre = 'site.js' if _motif_script('site.js').search(html) else 'lang-switcher.js'
        html = _inserer_script(html, ancre, SCRIPT_ENTETE)
    if not _motif_script('ses-anim.js').search(html):
        html = _inserer_script(html, 'ses-entete.js', SCRIPT_ANIM)
    # Les sections de l'export commencent toutes en début de ligne.
    html = re.sub(r'^<section (?!.*data-ses-reveal)', '<section data-ses-reveal="0" ',
                  html, flags=re.M)
    return html

# --------------------------------------------------------------------------
# 11. Pages « Suivi » reliées aux vrais colis
# --------------------------------------------------------------------------
# Le QR code des étiquettes mène à suivi.html?colis=SES-10001-HT, et l'accueil
# propose le même suivi : les deux pages doivent interroger la base, pas se
# contenter du parcours de démonstration de la maquette. On pose ici les
# points d'accroche que site.js remplit, et les noms de statuts, rangés dans
# un <template> pour suivre la langue.

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
  <span data-t="suivi-vide">Saisissez votre numéro de suivi pour voir où est votre colis.</span>
  <span data-t="suivi-indisponible">Le suivi est momentanément indisponible. Réessayez dans un instant, ou écrivez-nous sur WhatsApp.</span>
</template>
"""

def suivi_reel(html, nom=""):
    if nom not in ("suivi.html", "index.html"):
        return html
    if "ses-api.js" not in html:
        i = html.find('<script src="assets/js/site.js')
        if i != -1:
            html = (html[:i] + '<script src="assets/js/ses-api.js?v=' + VERSION + '" defer></script>\n'
                    + html[i:])
    if "data-textes" not in html:
        html = html.replace("</body>", TEXTES_SUIVI + "</body>", 1)
    # Les deux pages partagent le même bloc de résultat : les accroches
    # s'y posent à l'identique, pour que la recherche remplisse les bons
    # blocs sur l'une comme sur l'autre.
    for avant, apres in ACCROCHES:
        if apres not in html:
            html = html.replace(avant, apres, 1)
    return html

# --------------------------------------------------------------------------
# 12. Refonte visuelle : palette du logo, composants plus nets et espacements
# --------------------------------------------------------------------------
# La feuille est posée à la toute fin pour harmoniser les pages publiques,
# les articles et l'espace privé sans toucher à leur texte, leurs données,
# leurs formulaires ou leurs scripts.
CSS_REDESIGN = """
<style id="ses-design-css">
:root{
  --red:#e8121b;--red2:#b60d14;--accent:#e8121b;--accent2:#b60d14;
  --ink:#0b0c0e;--ink2:#14161a;--ink3:#20242a;
  --smoke:#f8f8f8;--cream:#f8f8f8;--mist:#e8e8e8;--line:#e8e8e8;
  --blue:#1a2ed2;--yellow:#e8b111;--green:#13c02c;--r:18px;
}
html{scroll-behavior:smooth;scroll-padding-top:104px}
body{background:#fff;color:#14161a}
h1,h2,h3,h4{letter-spacing:-.025em}
a{text-underline-offset:.16em}
:focus-visible{outline:3px solid rgba(232,18,27,.38);outline-offset:3px}
::selection{background:rgba(232,18,27,.18);color:#0b0c0e}
section[id]{scroll-margin-top:100px}

/* Barre commune */
.ses-entete{
  background:rgba(255,255,255,.96)!important;
  border-bottom-color:rgba(11,12,14,.09)!important;
  box-shadow:0 8px 30px -24px rgba(11,12,14,.48)!important;
  backdrop-filter:blur(16px)
}
.ses-entete nav a{font-weight:700!important;transition:color .18s ease}
.ses-entete nav a:hover{color:var(--red)!important}
.ses-entete .ses-burger{border-radius:12px!important}
.ses-entete .ses-actions a:last-child{
  border-radius:12px!important;
  box-shadow:0 12px 24px -16px rgba(232,18,27,.7)!important;
  transition:transform .18s ease,box-shadow .18s ease,background .18s ease
}
.ses-entete .ses-actions a:last-child:hover{transform:translateY(-1px)}

/* Boutons, liens et surfaces partagés */
.ses-bouton{border-radius:12px!important;transition:transform .18s ease,box-shadow .18s ease,background .18s ease}
.ses-bouton-principal{box-shadow:0 12px 26px -17px rgba(232,18,27,.8)!important}
.ses-bouton-principal:hover{transform:translateY(-1px)}
.ses-bouton-danger{
  background:#fff!important;color:#b60d14!important;
  border-color:rgba(182,13,20,.28)!important;box-shadow:none!important
}
.ses-bouton-danger:hover{background:#b60d14!important;color:#fff!important;border-color:#b60d14!important}
.ses-carte,.ses-bloc,.ses-dialogue{border-radius:20px}
main [style*="border:1px solid var(--line)"]{
  border-color:var(--line)!important;border-radius:20px!important;
  box-shadow:0 18px 44px -32px rgba(11,12,14,.26)!important
}
main a[style*="border:1px solid var(--line)"]{transition:transform .18s ease,box-shadow .18s ease}
main a[style*="border:1px solid var(--line)"]:hover{
  transform:translateY(-3px);box-shadow:0 24px 48px -30px rgba(11,12,14,.32)!important
}
main a[style*="background:var(--red)"]{border-radius:12px!important;transition:transform .18s ease,box-shadow .18s ease}
main input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]),
main select,main textarea{
  border-color:var(--line);border-radius:12px;transition:border-color .16s ease,box-shadow .16s ease
}
main input:not([type="hidden"]):not([type="checkbox"]):not([type="radio"]):focus,
main select:focus,main textarea:focus{
  border-color:var(--red);box-shadow:0 0 0 4px rgba(232,18,27,.12)
}

/* Accueil : mise en scène claire, avec la vraie photo Speed Express à droite. */
@media (min-width:900px){
  #top.ses-hero-section{
    height:clamp(640px,52vw,760px);min-height:640px;padding-bottom:0!important;
    background:linear-gradient(112deg,#fdfdfd 0%,#f8f8f8 54%,#f2f2f2 100%)!important;
    color:var(--ink)!important
  }
  #top.ses-hero-section>img[src*="ses-truck.jpg"]{
    top:0!important;right:0!important;bottom:0!important;left:auto!important;
    width:51%!important;height:100%!important;object-fit:cover!important;
    object-position:61% 48%!important;clip-path:polygon(11% 0,100% 0,100% 100%,0 100%)
  }
  #top.ses-hero-section>div[style*="background:linear-gradient(94deg"]{display:none!important}
  #top.ses-hero-section .ses-hero-camion{display:none!important}
  #top.ses-hero-section .ses-hero-contenu{
    height:100%!important;min-height:100%!important;padding:54px 34px 76px!important;
    grid-template-columns:minmax(0,1.15fr) minmax(320px,.85fr)!important;
    gap:34px!important;align-items:center!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:first-child>div:first-child{
    color:#626262!important;background:rgba(255,255,255,.84)!important;
    border-color:#e8e8e8!important;box-shadow:0 10px 28px -22px rgba(11,12,14,.32)
  }
  #top.ses-hero-section .ses-hero-contenu h1{color:var(--ink)!important}
  #top.ses-hero-section .ses-hero-contenu>div:first-child>p{color:#686868!important}
  #top.ses-hero-section .ses-hero-contenu>div:first-child>p strong{color:var(--ink)!important}
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child{
    max-width:360px!important;background:rgba(255,255,255,.96)!important;
    color:var(--ink)!important;border-color:rgba(11,12,14,.13)!important;
    box-shadow:0 30px 70px -38px rgba(11,12,14,.52)!important;backdrop-filter:blur(12px)
  }
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child>div:first-child{
    border-bottom-color:#eaeaea!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child>div:first-child>span:first-child{
    color:#858585!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child>p:first-of-type{color:var(--ink)!important}
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child>p:nth-of-type(2){color:#858585!important}
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child div[style*="height:4px"]{
    background:#f0f0f0!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child span[style*="font-size:14px"]{
    color:#636363!important
  }
}

/* Sur téléphone, photo puis contenu sur fond clair plutôt que texte posé
   sur l'image : le titre et les deux actions restent faciles à lire. */
@media (max-width:899px){
  #top.ses-hero-section{
    height:auto!important;min-height:0!important;padding:0!important;
    background:linear-gradient(180deg,#f4f4f4 0,#fff 285px)!important;color:var(--ink)!important
  }
  #top.ses-hero-section>img[src*="ses-truck.jpg"]{
    position:relative!important;inset:auto!important;display:block!important;
    width:100%!important;height:clamp(220px,48vw,330px)!important;
    object-fit:cover!important;object-position:62% 48%!important;clip-path:none!important
  }
  #top.ses-hero-section>div[style*="background:linear-gradient(94deg"],
  #top.ses-hero-section>div[style*="clip-path:polygon"]{display:none!important}
  #top.ses-hero-section .ses-hero-camion{display:none!important}
  #top.ses-hero-section .ses-hero-contenu{
    height:auto!important;min-height:0!important;padding:28px 22px 36px!important;
    grid-template-columns:minmax(0,1fr)!important;gap:26px!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:first-child>div:first-child{
    color:#626262!important;background:#f8f8f8!important;border-color:#e8e8e8!important
  }
  #top.ses-hero-section .ses-hero-contenu h1{
    color:var(--ink)!important;font-size:clamp(34px,7.8vw,54px)!important;line-height:1.04!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:first-child>p{
    color:#686868!important;font-size:16.5px!important;line-height:1.72!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:first-child>p strong{color:var(--ink)!important}
  #top.ses-hero-section .ses-hero-contenu>div:first-child>div[style*="margin-top:32px"]{
    flex-direction:column;align-items:stretch!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:first-child>div[style*="margin-top:32px"]>a{
    width:100%;justify-content:center!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:first-child>div[style*="margin-top:32px"]>a:nth-child(2){
    color:var(--ink)!important;background:#fff!important;border-color:#cfd5de!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2){justify-content:flex-start!important}
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child{
    width:100%!important;max-width:440px!important;background:rgba(255,255,255,.97)!important;
    color:var(--ink)!important;border-color:rgba(11,12,14,.13)!important;
    box-shadow:0 24px 56px -38px rgba(11,12,14,.42)!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child>div:first-child{
    border-bottom-color:#eaeaea!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child>div:first-child>span:first-child{
    color:#858585!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child>p:first-of-type{color:var(--ink)!important}
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child>p:nth-of-type(2){color:#858585!important}
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child div[style*="height:4px"]{
    background:#f0f0f0!important
  }
  #top.ses-hero-section .ses-hero-contenu>div:nth-child(2)>div:first-child span[style*="font-size:14px"]{
    color:#636363!important
  }
}

/* Tableau de bord : les valeurs restent fournies par l'API existante. */
.ses-dashboard-legacy{background:#f7f7f7!important}
.ses-dashboard-legacy>div:first-child{
  background:linear-gradient(118deg,#0b0c0e 0%,#14161a 58%,#20242a 100%)!important
}
.ses-dashboard-legacy>div:first-child>div:first-child{min-height:168px}
.ses-dashboard-legacy>div:nth-child(2){max-width:1400px!important;padding-left:30px!important;padding-right:30px!important}
.ses-dashboard-legacy #ses-chiffres{
  grid-template-columns:repeat(5,minmax(0,1fr))!important;gap:16px!important;margin-top:-30px!important
}
.ses-dashboard-legacy .ses-chiffre{
  position:relative;overflow:hidden;background:#fff!important;border:1px solid #eaeaea!important;
  border-radius:18px!important;padding:21px 20px 20px 23px!important;
  box-shadow:0 18px 40px -30px rgba(11,12,14,.34)!important
}
.ses-dashboard-legacy .ses-chiffre:before{
  content:"";position:absolute;left:0;top:14px;bottom:14px;width:4px;
  border-radius:0 4px 4px 0;background:linear-gradient(180deg,#e8121b,#b60d14)
}
.ses-dashboard-legacy .ses-chiffre b{
  display:block;font-size:clamp(25px,3vw,34px);line-height:1.08;color:var(--ink)
}
.ses-dashboard-legacy .ses-chiffre span{margin-top:7px;font-size:13px;line-height:1.45;color:#7e7e7e}
.ses-dashboard-legacy .ses-onglets{
  display:flex;gap:7px;padding:6px;background:#f1f1f1;border:1px solid #e9e9e9;
  border-radius:16px;overflow-x:auto;scrollbar-width:thin
}
.ses-dashboard-legacy .ses-onglet{
  flex:none;margin:0;padding:11px 18px;border:1px solid transparent!important;
  border-radius:11px;font-size:14px;color:#787878;white-space:nowrap
}
.ses-dashboard-legacy .ses-onglet:hover{color:var(--ink);background:rgba(255,255,255,.66)}
.ses-dashboard-legacy .ses-onglet[aria-selected="true"]{
  color:#b60d14!important;background:#fff!important;border-color:#e9e9e9!important;
  box-shadow:0 4px 12px -8px rgba(11,12,14,.32)
}
.ses-dashboard-legacy [role="tabpanel"]{
  padding:clamp(16px,2.3vw,26px)!important;background:#fff;
  border:1px solid #eaeaea;border-radius:20px;
  box-shadow:0 18px 42px -34px rgba(11,12,14,.25)
}
.ses-dashboard-legacy .ses-filtre{border-radius:999px;color:#6c6c6c}
.ses-dashboard-legacy .ses-filtre[aria-pressed="true"]{
  background:#e8121b;border-color:#e8121b;color:#fff
}
.ses-dashboard-legacy .ses-tableau{
  border-color:#eaeaea;border-radius:16px;box-shadow:0 10px 28px -25px rgba(11,12,14,.28)
}
.ses-dashboard-legacy .ses-tableau th{background:#f6f6f6;color:#686868;border-bottom-color:#eaeaea}
.ses-dashboard-legacy .ses-tableau td{border-bottom-color:#f2f2f2}
.ses-dashboard-legacy .ses-tableau tbody tr:hover{background:#fcfcfc}
.ses-dashboard-legacy .ses-bloc{border-color:#eaeaea;border-radius:17px;box-shadow:0 12px 30px -25px rgba(11,12,14,.2)}
.ses-dashboard-legacy #ses-selection-colis{
  background:#fff3f3!important;border-color:#f4c7ca!important;border-radius:14px!important
}
.ses-dashboard-legacy #ses-alerte-base{
  background:#fff7f7!important;border-color:#efc8cb!important;border-radius:14px!important
}
.ses-dashboard-legacy .ses-dialogue{border:1px solid #eaeaea;box-shadow:0 42px 90px -44px rgba(11,12,14,.58)}

@media (max-width:1100px){
  .ses-dashboard-legacy #ses-chiffres{grid-template-columns:repeat(3,minmax(0,1fr))!important}
}
@media (max-width:700px){
  .ses-dashboard-legacy>div:nth-child(2){padding-left:18px!important;padding-right:18px!important}
  .ses-dashboard-legacy #ses-chiffres{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:11px!important}
  .ses-dashboard-legacy .ses-chiffre{padding:17px 14px 16px 18px!important}
  .ses-dashboard-legacy .ses-onglets{gap:4px;padding:4px}
  .ses-dashboard-legacy .ses-onglet{padding:10px 12px;font-size:13px}
  .ses-dashboard-legacy [role="tabpanel"]{padding:14px!important;border-radius:16px}
}
@media (max-width:420px){
  .ses-dashboard-legacy #ses-chiffres{grid-template-columns:1fr!important}
  .ses-dashboard-legacy>div:first-child>div:first-child{padding-left:18px!important;padding-right:18px!important}
}
</style>
"""


def styles_redesign(html, nom=""):
    """Applique les couleurs et styles du nouveau design, sans toucher au contenu."""
    # Palette : uniquement les couleurs du logo Speed Express Shipping —
    # rouge #e8121b, noir #0b0c0e, blanc, et les trois petites touches du
    # logo (bleu #1a2ed2, jaune #e8b111, vert #13c02c). Aucun autre bleu :
    # on ne réécrit donc aucune couleur des pages, on ajoute seulement la feuille.
    html = re.sub(r'\s*<style id="ses-design-css">.*?</style>', "", html, flags=re.S)
    css = CSS_REDESIGN.strip()
    return html.replace("</head>", css + "\n</head>", 1)

# --------------------------------------------------------------------------
# SEO — phase 5 : titres resserrés, descriptions étoffées, données d'indexation
# --------------------------------------------------------------------------
# Le <title> et la meta description ne passent pas par les dictionnaires :
# lang-switcher ne traduit que les nœuds de document.body. On peut donc les
# réécrire sans rendre aucune entrée de dictionnaire caduque. Les og:title et
# og:description reprennent les mêmes valeurs, pour rester cohérents.
BASE_SEO = "https://wilnergraph92.github.io/speed-express-site/"
ORG_ID = BASE_SEO + "#organisation"
SITE_ID = BASE_SEO + "#site"

# Titres remplacés quand ils dépassent ~65 caractères (troncature dans les
# résultats). Le mot-clé principal reste en tête, la marque est raccourcie.
SEO5_TITRES = {
    "index.html":
        "Speed Express Shipping — Colis Miami, Santo Domingo et Haïti",
    "article-boutiques-chinoises.html":
        "Les 6 meilleures boutiques chinoises | Speed Express",
    "article-impact-ecommerce.html":
        "L'impact de la livraison sur le commerce électronique dominicain",
    "article-partenaire-colis-etranger.html":
        "Votre partenaire pour recevoir vos colis depuis l'étranger",
    "article-pourquoi-speed-express.html":
        "Pourquoi choisir Speed Express pour Amazon, Shein et eBay ?",
    "article-service-de-messagerie.html":
        "Service de messagerie : définition et fonctionnement",
}

# Descriptions remplacées quand elles sont trop courtes pour occuper l'extrait
# de résultat (70-165 caractères). Aucune promesse qui ne soit pas vérifiable
# sur la page elle-même.
SEO5_DESCRIPTIONS = {
    "article-impact-ecommerce.html":
        "Comment la logistique transforme le commerce en ligne en République "
        "dominicaine : délais, coûts, suivi et nouvelles attentes des acheteurs.",
    "article-tendances-2026.html":
        "Ce qui change en 2026 dans la logistique et la livraison de colis : "
        "nouvelles routes, suivi en temps réel et attentes des clients.",
    "support.html":
        "Besoin d'aide ? Compte, facturation, colis et livraison : nos réponses "
        "et un conseiller Speed Express Shipping à votre écoute.",
    "fermer-un-compte.html":
        "Comment fermer votre compte client Speed Express Shipping : étapes à "
        "suivre et sort réservé à vos données après la fermeture.",
}

SEO5_ARTICLES = {
    "article-boutiques-chinoises.html", "article-conseils-livraison.html",
    "article-entreprise-fiable.html", "article-impact-ecommerce.html",
    "article-maritime-vs-aerien.html", "article-optimiser-expeditions.html",
    "article-partenaire-colis-etranger.html", "article-pourquoi-speed-express.html",
    "article-premiere-livraison.html", "article-service-de-messagerie.html",
    "article-tendances-2026.html",
}

# Libellés courts du fil d'Ariane pour les pages piliers (les articles
# utilisent leur titre complet).
SEO5_LIBELLES = {
    "nos-services.html": "Nos services",
    "suivi.html": "Suivi de colis",
    "a-propos.html": "À propos",
    "contacts.html": "Contact",
    "support.html": "Support",
    "blog.html": "Blog",
    "marchandises-dangereuses.html": "Marchandises dangereuses",
    "termes-et-conditions.html": "Termes et conditions",
    "confidentialite.html": "Politique de confidentialité",
}

# Pages publiques sans aucun JSON-LD avant la phase 5 : on pose un nœud
# typé qui raccorde la page au site et à l'organisation déclarés dans
# index.html. Les autres (accueil, articles, blog, contacts) ont déjà le
# leur et ne reçoivent que le fil d'Ariane.
SEO5_PAGES_SANS_DONNEES = {
    "a-propos.html": "AboutPage",
    "nos-services.html": "WebPage",
    "suivi.html": "WebPage",
    "support.html": "WebPage",
    "marchandises-dangereuses.html": "WebPage",
    "termes-et-conditions.html": "WebPage",
    "confidentialite.html": "WebPage",
}

# Sections visibles de nos-services.html, avec leur ancre réelle : la
# déclaration ItemList renvoie vers ces ancres, aucun contenu n'est inventé.
SEO5_SERVICES = [
    ("adresse-usa", "Adresse de réception aux États-Unis"),
    ("consolidation", "Consolidation de colis"),
    ("maritime", "Fret maritime"),
    ("aerien", "Fret aérien express"),
    ("dedouanement", "Dédouanement inclus"),
    ("livraison", "Livraison à domicile ou retrait en agence"),
    ("demenagement", "Service de déménagement"),
]

def seo_phase5_meta(html, nom=""):
    """Remplace un titre trop long ou une description trop courte.

    Le remplacement ne part que si la valeur actuelle diffère encore de la
    cible : relancer l'étape ne réécrit rien.
    """
    if nom in SEO5_TITRES:
        nouveau = SEO5_TITRES[nom]
        m = re.search(r"<title>(.*?)</title>", html, re.S)
        if m and m.group(1) != nouveau:
            ancien = m.group(1)
            html = html.replace("<title>" + ancien + "</title>",
                                "<title>" + nouveau + "</title>", 1)
            html = html.replace('<meta property="og:title" content="' + ancien + '">',
                                '<meta property="og:title" content="' + nouveau + '">', 1)
    if nom in SEO5_DESCRIPTIONS:
        nouvelle = SEO5_DESCRIPTIONS[nom]
        m = re.search(r'<meta name="description" content="([^"]*)">', html)
        if m and m.group(1) != nouvelle:
            ancienne = m.group(1)
            html = html.replace('<meta name="description" content="' + ancienne + '">',
                                '<meta name="description" content="' + nouvelle + '">', 1)
            html = html.replace('<meta property="og:description" content="' + ancienne + '">',
                                '<meta property="og:description" content="' + nouvelle + '">', 1)
    return html


def _texte_h1(html):
    """Texte du premier h1, entités résolues et espaces normalisés."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if not m:
        return ""
    return re.sub(r"\s+", " ", dechiffrer(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()


def _bloc_jsonld(donnees):
    """Bloc <script> JSON-LD formaté comme ceux déjà présents sur le site."""
    return ('<script type="application/ld+json">\n'
            + json.dumps(donnees, ensure_ascii=False, indent=2)
            + "\n</script>")


def seo_phase5_donnees_structurees(html, nom=""):
    """Pose le fil d'Ariane JSON-LD et, si besoin, le nœud de page typé.

    Toutes les pages publiques décrivent désormais leur position dans le
    site (Accueil > Blog > Article, Accueil > Page), ce qui permet aux
    moteurs d'afficher le chemin à la place de l'URL brute. L'accueil est
    la racine du fil : il ne se déclare pas lui-même. Les pages privées
    (noindex) sont ignorées. Idempotent : une page qui contient déjà un
    BreadcrumbList n'est pas retouchée.
    """
    if nom == "index.html" or '"BreadcrumbList"' in html:
        return html
    est_article = nom in SEO5_ARTICLES
    if not est_article and nom not in SEO5_LIBELLES:
        return html
    url = BASE_SEO + nom
    fil = [{"@type": "ListItem", "position": 1, "name": "Accueil", "item": BASE_SEO}]
    if est_article:
        fil.append({"@type": "ListItem", "position": 2,
                    "name": "Blog", "item": BASE_SEO + "blog.html"})
        fil.append({"@type": "ListItem", "position": 3,
                    "name": _texte_h1(html), "item": url})
        bloc = _bloc_jsonld({"@context": "https://schema.org",
                             "@type": "BreadcrumbList",
                             "@id": url + "#fil",
                             "itemListElement": fil})
    else:
        fil.append({"@type": "ListItem", "position": 2,
                    "name": SEO5_LIBELLES[nom], "item": url})
        fil_ariane = {"@type": "BreadcrumbList", "@id": url + "#fil",
                      "itemListElement": fil}
        if nom in SEO5_PAGES_SANS_DONNEES:
            m = re.search(r'<meta name="description" content="([^"]*)"', html)
            page = {
                "@type": SEO5_PAGES_SANS_DONNEES[nom],
                "@id": url + "#page",
                "url": url,
                "name": _texte_h1(html),
                "description": m.group(1) if m else "",
                "inLanguage": "fr",
                "isPartOf": {"@id": SITE_ID},
                "about": {"@id": ORG_ID},
            }
            graph = [page]
            if nom == "nos-services.html":
                graph.append({
                    "@type": "ItemList",
                    "@id": url + "#services",
                    "name": "Services logistiques Speed Express Shipping",
                    "itemListElement": [
                        {"@type": "ListItem", "position": i + 1,
                         "item": {"@type": "Service", "name": service,
                                  "url": url + "#" + ancre,
                                  "provider": {"@id": ORG_ID},
                                  "areaServed": ["DO", "HT", "US"]}}
                        for i, (ancre, service) in enumerate(SEO5_SERVICES)],
                })
            graph.append(fil_ariane)
            bloc = _bloc_jsonld({"@context": "https://schema.org", "@graph": graph})
        else:
            bloc = _bloc_jsonld({"@context": "https://schema.org",
                                 "@type": "BreadcrumbList",
                                 "@id": url + "#fil",
                                 "itemListElement": fil})
    return html.replace("</head>", bloc + "\n</head>", 1)

# --------------------------------------------------------------------------
def accessibilite_phase6(html, nom=""):
    """Uniquement les retouches WCAG ; ne relance pas les anciens styles."""
    return appliquer_accessibilite(html, nom)

ETAPES = [corriger_liens, retirer_barre_superieure, overflow_clip, entete_blanche, menu_mobile, styles_entete,
          bouton_compte, lien_espace_pied, retirer_template_bundler, images_responsives,
          preconnect_images_externes, icone_apple_dimensionnee, polices_une_requete,
          preload_image_principale, animations, version_scripts, dictionnaires_differe, performance_images]
ETAPES_NOMMEES = [hero_camion, styles_hero, suivi_reel, styles_redesign,
                  seo_phase5_meta, seo_phase5_donnees_structurees, accessibilite_phase6]

def regenerer():
    """Sources versionnées → composants partagés → pages statiques."""
    from unification import developper
    total = 0
    for source in sorted((SITE / "outils/pages").glob("*.html")):
        texte = source.read_text(encoding="utf-8")
        if "{{contenu}}" in texte:
            continue  # Ces cinq pages appartiennent à pages-espace.py.
        html = developper(texte, source.name)
        cible = SITE / source.name
        if not cible.exists() or cible.read_text(encoding="utf-8") != html:
            cible.write_text(html, encoding="utf-8")
            total += 1
    import runpy
    runpy.run_path(str(SITE / "outils/pages-espace.py"))["main"]()
    print(f"23 pages publiques régénérées ({total} modifiées), 5 pages de comptes assemblées.")


def main():
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        print("Usage : python3 outils/mise-en-page.py\n"
              "Sources : outils/pages, outils/espace, outils/communs, assets/css.\n"
              "Les anciennes retouches --etapes ne sont plus exécutées sur les sorties.")
        return
    if len(sys.argv) != 1:
        sys.exit("Option obsolète ou inconnue : modifier les sources, puis régénérer sans --etapes.")
    regenerer()

if __name__ == "__main__":
    main()
