#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retouches ciblées et idempotentes de la phase 6.

Le parseur sert uniquement à repérer les balises à retoucher : les pages ne
sont pas sérialisées de nouveau (métadonnées, images et maquette préservées).
Utilisé par mise-en-page.py et par l'assemblage des fragments de comptes.
"""
import re
from html.parser import HTMLParser

VERSION = "40"


def attribut(balise, nom, valeur):
    motif = r'\b' + re.escape(nom) + r'="[^"]*"'
    texte = nom + '="' + valeur + '"'
    if re.search(motif, balise):
        return re.sub(motif, lambda m: texte, balise, count=1)
    return balise[:-1] + ' ' + texte + '>'


def classe(balise, nom):
    m = re.search(r'\bclass="([^"]*)"', balise)
    classes = m.group(1).split() if m else []
    if nom not in classes:
        classes.append(nom)
    return attribut(balise, "class", " ".join(classes))


class RetouchesBalises(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.lignes = [0]
        for m in re.finditer("\n", html):
            self.lignes.append(m.end())
        self.retours = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        avant = self.get_starttag_text()
        apres = avant
        style = attrs.get("style", "")
        classes = attrs.get("class", "").split()
        # Toutes ces ligatures accompagnent déjà un texte compréhensible.
        # Les informations non décoratives (ex. note /5) ont leur propre nom.
        icone = ("Material Symbols" in style or any("material-symbols" in c for c in classes)
                 or "ico" in classes or "tel-ico" in classes or "about__eyebrow-ico" in classes)
        # À 1180 px le numéro visuel de l'accueil disparaît : le lien qui
        # contient uniquement l'icône décorative garde donc son propre nom.
        if "ses-entete-tel" in classes:
            apres = attribut(apres, "aria-label", "Appeler le 829 265-3727")
        if icone and not attrs.get("aria-label"):
            apres = attribut(apres, "aria-hidden", "true")
        if attrs.get("role") == "tab":
            apres = attribut(apres, "tabindex", "0" if attrs.get("aria-selected") == "true" else "-1")
        if attrs.get("role") == "tabpanel":
            apres = attribut(apres, "tabindex", "0")
        # Le contexte de surface ne modifie que les couleurs de texte, jamais
        # la couleur de marque des boutons, traits ou fonds.
        fond = re.search(r'(?:^|;)\s*background(?:-color)?\s*:\s*([^;]+)', style)
        if fond:
            valeur = fond.group(1).strip().lower()
            if valeur in ("var(--ink)", "var(--ink2)", "var(--ink3)", "var(--brand-dark)",
                          "#0b0c0e", "#101114", "#14161a", "#20242a"):
                apres = classe(apres, "ses-surface-sombre")
            elif valeur in ("#fff", "#ffffff", "#f6f6f6", "#f7f7f7", "#f8f8f8", "var(--smoke)"):
                apres = classe(apres, "ses-surface-claire")
        if avant != apres:
            ligne, colonne = self.getpos()
            debut = self.lignes[ligne - 1] + colonne
            self.retours.append((debut, debut + len(avant), apres))

    def resultat(self):
        self.feed(self.html)
        html = self.html
        for debut, fin, apres in reversed(self.retours):
            html = html[:debut] + apres + html[fin:]
        return html


def cartes_blog(html):
    def retoucher(m):
        article = m.group(0)
        liens = re.findall(r'<a\b[^>]*href="(article-[^"]+)"[^>]*>', article)
        if len(liens) < 2 or len(set(liens)) != 1:
            return article
        titre = re.search(r'(<h3\b[^>]*>\s*)(<a\b[^>]*>)(.*?)</a>', article, re.S)
        if not titre:
            return article
        lien_titre = titre.group(2)
        def lien(mm):
            balise, contenu = mm.group(1), mm.group(2)
            if balise == lien_titre:
                return classe(balise, "ses-carte-lien") + contenu + "</a>"
            # L'image, son badge et l'appel à lire restent à la même place.
            tag = "div" if "<img" in contenu else "span"
            balise = re.sub(r'\s+(href|tabindex|aria-hidden)="[^"]*"', "", balise)
            return balise.replace("<a", "<" + tag, 1) + contenu + "</" + tag + ">"
        article = re.sub(r'(<a\b[^>]*>)(.*?)</a>', lien, article, flags=re.S)
        return re.sub(r'<article\b[^>]*>', lambda mm: classe(mm.group(0), "ses-carte-article"), article, count=1)
    return re.sub(r'<article\b[^>]*>.*?</article>', retoucher, html, flags=re.S)


def combobox(html):
    for suffixe in ("", "-f"):
        liste = "ses-clients-trouves" + suffixe
        choisi = "ses-client-choisi" + suffixe
        champ = "ses-client-recherche" + suffixe
        motif = (r'<label class="ses-champ"><span>Client<i>\*</i></span>\s*'
                 r'<input[^>]*aria-controls="' + liste + r'"[^>]*>.*?</label>')
        bloc = ('<div class="ses-champ">\n'
                '      <label for="' + champ + '"><span>Client<i>*</i></span></label>\n'
                '      <input id="' + champ + '" type="text" name="client_recherche" placeholder="Identifiant SES, nom ou e-mail" autocomplete="off" role="combobox" aria-autocomplete="list" aria-haspopup="listbox" aria-required="true" aria-expanded="false" aria-controls="' + liste + '" aria-describedby="' + choisi + '">\n'
                '      <input type="hidden" name="client_id" required>\n'
                '      <div id="' + liste + '" class="ses-suggestions" hidden role="listbox" aria-label="Clients"></div>\n'
                '      <p id="' + liste + '-message" class="ses-completion-message" role="status" aria-atomic="true"></p>\n'
                '      <small id="' + choisi + '" style="color:#0b7a19;font-size:13.5px;font-weight:700"></small>\n'
                '    </div>')
        html = re.sub(motif, lambda m: bloc, html, flags=re.S)
    return html


def appliquer(html, nom="", complet=True):
    # Seule la propriété de texte change : jamais border-color/background.
    html = re.sub(r'(?<![\w-])color\s*:\s*(?:#e8121b|var\(--(?:red|accent|brand-primary|rsn-rouge)\))(?=[;}"\s])',
                  'color:var(--red-text)', html)
    html = re.sub(r'(?<![\w-])color\s*:\s*#(?:8d949f|7a828e|9b9b9b|6b7280)\b',
                  'color:var(--muted-2)', html)
    html = html.replace('--muted-2:#8d949f', '--muted-2:#626b78')
    # Le paragraphe de la carte rouge est du texte blanc, pas du blanc atténué.
    if nom == "nos-services.html":
        html = html.replace('color:rgba(255,255,255,.92)', 'color:#fff')
    # Les titres du pied de page sont des sections de niveau 2. Leur classe
    # conserve les styles de h4 sans reproduire un saut de niveau pour les AT.
    def pied(m):
        texte = re.sub(r'<h4\b[^>]*>', lambda mm: classe(mm.group(0).replace('<h4', '<h2', 1), "ses-titre-pied"), m.group(0))
        return texte.replace('</h4>', '</h2>')
    html = re.sub(r'<footer\b.*?</footer>', pied, html, flags=re.S)
    if nom == "contacts.html":
        # Le mode Unicode v des navigateurs impose d'échapper ces caractères
        # dans une classe. Une regex invalide désactivait la vérification tel.
        html = re.sub(r'pattern="[^\"]+"', lambda m: 'pattern="[0-9+\\.\\(\\)\\s\\-]{7,25}"', html, count=1)
        html = re.sub(r'<h3([^>]*font-size:18px[^>]*)>(.*?)</h3>', r'<h2\1>\2</h2>', html, flags=re.S)
    if nom == "article-conseils-livraison.html":
        html = re.sub(r'<h3([^>]*font-size:clamp\(17px,1.9vw,21px\)[^>]*)>(.*?)</h3>', r'<h2\1>\2</h2>', html, flags=re.S)
    html = RetouchesBalises(html).resultat()
    html = combobox(html)
    # Les validateurs utilisaient déjà cette clé, mais aucun de ces gabarits
    # ne la définissait : une erreur de téléphone donnait un message vide.
    if nom in ("creer-un-compte.html", "espace-client.html", "tableau-de-bord.html") and 'data-t="telephone-invalide"' not in html:
        html = html.replace('</template>', '  <span data-t="telephone-invalide">Ce numéro de téléphone ne semble pas valide.</span>\n</template>', 1)
    if nom in ("index.html", "blog.html"):
        html = cartes_blog(html)

    # Quelques pages éditoriales appelaient déjà leur section « contenu ».
    # Ce nom appartient désormais au repère main, sans créer un ID en double.
    if re.search(r'<section\b[^>]*id="contenu"', html):
        html = re.sub(r'<section\b[^>]*id="contenu"[^>]*>', lambda m: attribut(m.group(0), "id", "contenu-page"), html)
        html = re.sub(r'<a\b[^>]*href="#contenu"[^>]*>', lambda m: m.group(0) if 'ses-skip-link' in m.group(0) else attribut(m.group(0), "href", "#contenu-page"), html)

    def principal(m):
        balise = m.group(0)
        ancien = re.search(r'\bid="([^"]*)"', balise)
        balise = attribut(balise, "id", "contenu")
        balise = attribut(balise, "tabindex", "-1")
        if ancien and ancien.group(1) == "top":
            balise += '\n<span id="top" class="sr-only" aria-hidden="true"></span>'
        return balise
    html = re.sub(r'<main\b[^>]*>', principal, html, count=1)
    if complet and "<main" not in html:
        html = html.replace('</header>', '</header>\n\n<main id="contenu" tabindex="-1">', 1)
        html = html.replace('<footer', '</main>\n\n<footer', 1)

    # Un seul code clavier pour les raisons et l'entête : retire les anciennes
    # IIFE inline, sans toucher au carrousel, au scroll de l'entête ou au SEO.
    html = re.sub(r'<script>\s*/\* Section « Trois raisons ».*?</script>', '', html, flags=re.S)
    html = re.sub(r'<script>\s*\(function\(\)\{\s*var e=document.querySelector\(\'.ses-entete\'\);.*?</script>', '', html, flags=re.S)
    if nom == "index.html":
        if 'data-ses-hero-pause' not in html:
            bouton = ('\n      <button type="button" class="hero__pause" data-ses-hero-pause aria-label="Mettre en pause le défilement" aria-pressed="false">'
                      '<svg class="hero__arreter" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>'
                      '<svg class="hero__reprendre" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 3l14 9-14 9z"/></svg></button>')
            html = re.sub(r'(<button[^>]*data-aller="2"[^>]*>03</button>)', lambda m: m.group(1) + bouton, html, count=1)
        html = re.sub(r"    var burger = entete.querySelector\('.ses-burger'\);.*?\n    var bas = false;", "    var bas = false;", html, flags=re.S)

    # Les régions de résultat sont nommées sans annoncer toute la chronologie.
    html = re.sub(r'<div\b[^>]*data-ses-if="(?:trackResult|result)"[^>]*>',
                  lambda m: attribut(attribut(m.group(0), "role", "region"), "aria-label", "Résultat du suivi"), html)
    if 'data-ses-form="suivi"' in html and 'id="ses-suivi-annonce"' not in html:
        html = re.sub(r'(<form\b[^>]*data-ses-form="suivi"[^>]*>.*?</form>)',
                      lambda m: m.group(1) + '\n<p id="ses-suivi-annonce" class="sr-only" role="status" aria-atomic="true"></p>', html, count=1, flags=re.S)
    if 'data-ses-form="contact"' in html:
        html = re.sub(r'<form\b[^>]*data-ses-form="contact"[^>]*>',
                      lambda m: attribut(m.group(0), "aria-describedby", "ses-contact-erreur") if 'novalidate' in m.group(0) else attribut(m.group(0)[:-1] + ' novalidate>', "aria-describedby", "ses-contact-erreur"), html, count=1)
        if 'id="ses-contact-erreur"' not in html:
            html = html.replace('<div data-ses-if="notSent">', '<div data-ses-if="notSent">\n<p id="ses-contact-erreur" class="ses-erreur" hidden></p>', 1)
        html = re.sub(r'<div\b[^>]*data-ses-if="sent"[^>]*>', lambda m: attribut(attribut(m.group(0), "tabindex", "-1"), "role", "status"), html, count=1)
    if complet:
        if 'class="ses-skip-link"' not in html:
            html = re.sub(r'(<body\b[^>]*>)', r'\1\n<a class="ses-skip-link" href="#contenu">Aller au contenu</a>', html, count=1)
        css = '<link rel="stylesheet" href="assets/css/ses-accessibilite.css?v=' + VERSION + '">'
        if 'assets/css/ses-accessibilite.css' not in html:
            html = html.replace('</head>', css + '\n</head>', 1)
        if 'assets/js/ses-accessibilite.js' not in html:
            html = re.sub(r'(<script src="assets/js/)', '<script src="assets/js/ses-accessibilite.js?v=' + VERSION + '" defer></script>\n' + r'\1', html, count=1)
        html = re.sub(r'(assets/(?:js|css)/[A-Za-z0-9/._-]+\?v=)\d+', r'\g<1>' + VERSION, html)
        html = re.sub(r'<nav\b[^>]*>', lambda m: attribut(attribut(m.group(0), "id", "ses-navigation"), "aria-label", "Navigation principale"), html, count=1)
        html = re.sub(r'<div\b[^>]*class="ses-actions"[^>]*>', lambda m: attribut(m.group(0), "id", "ses-actions"), html, count=1)
        html = re.sub(r'<button\b[^>]*class="ses-burger"[^>]*>', lambda m: attribut(m.group(0), "aria-controls", "ses-navigation ses-actions"), html, count=1)
    return html
