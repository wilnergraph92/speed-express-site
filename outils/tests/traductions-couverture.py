#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Couverture des traductions, PAGE PAR PAGE, comme le navigateur les applique.

Pourquoi ce test existe, alors que i18n.cjs vérifie déjà les dictionnaires : il
fusionne tous les dictionnaires et ne regarde que leur forme. Il ne voit donc
pas les trois façons dont un texte reste en français quand on change de langue :

  1. Chaque page ne charge QUE son dictionnaire (lang-dict.js + sa partie, voir
     PAGE_PARTS dans lang-switcher.js). Un texte traduit dans lang-dict-3.js
     reste français sur le tableau de bord, qui ne charge pas cette partie.
  2. Le moteur compare chaque nœud de texte, après avoir remplacé ’ par '. Une
     clé écrite avec ’ ne correspond donc jamais : elle est inatteignable.
  3. Un texte absent de tous les dictionnaires.

Sont vérifiés : le texte du <body> (le contenu des <template data-textes>
compris), les attributs que le moteur traduit — placeholder, title, aria-label,
alt — et le <title> de la page, qui s'affiche dans l'onglet du navigateur. Les
balises <meta> (description, Open Graph) restent en français : elles servent
aux moteurs de recherche, pas à la lecture.

Usage : python3 outils/tests/traductions-couverture.py            (contrôle)
        python3 outils/tests/traductions-couverture.py --rapport  (détail)
"""
import json
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
ATTRS = ("placeholder", "title", "aria-label", "alt")
IGNORES = {"script", "style", "textarea"}

# Ce qui ne se traduit pas : noms propres, sigles, codes. Une chaîne qui ne
# contient aucune lettre (« 12 », « — », « $ ») est ignorée d'office.
NON_TRADUISIBLES = {
    "Speed Express Shipping", "Speed Express", "SES", "WhatsApp", "Facebook", "TikTok",
    "Instagram", "HT", "DO", "US", "FR", "EN", "ES", "Code 128", "QR", "PDF", "SES-00000",
    "RNC", "USD", "FAC", "Brevo", "Supabase", "Formspree", "Saira", "Manrope",
    # Un titre qui s'écrit pareil dans les quatre langues n'a pas d'entrée de dictionnaire.
    "Blog — Speed Express Shipping",
    # Le slogan de la marque est en créole dans toutes les langues.
    "Mèt colis a",
    # Des noms de lieux, écrits pareil dans les quatre langues. Les noms qui ont un
    # équivalent (Canada → Canadá, Ouest → West…) sont, eux, dans les dictionnaires.
    "Santo Domingo", "Santiago", "La Altagracia", "Florida", "New York",
}


def norm(s):
    """La même normalisation que lang-switcher.js : ’ → ', espaces repliés, rognage."""
    return re.sub(r"\s+", " ", re.sub("[‘’]", "'", s)).strip()


def traduisible(n):
    if not re.search(r"[A-Za-zÀ-ÿ]", n):
        return False
    if n in NON_TRADUISIBLES:
        return False
    # Une adresse, un lien : pas de traduction — sauf l'adresse d'EXEMPLE (vous@exemple.com),
    # qui devient you@example.com, usted@ejemplo.com…
    if re.fullmatch(r"(https?://\S+|\S+@\S+\.\S+|www\.\S+|[\w.-]+\.(com|ht|do|html|css|js))", n) and "exemple" not in n:
        return False
    if re.fullmatch(r"[+\d][\d\s().+-]{6,}", n):          # un numéro de téléphone
        return False
    if re.fullmatch(r"[A-Z]{2,4}-[\dA-Z-]+", n):          # un code : SES-10001-HT, FAC-2026-0001
        return False
    # L'adresse postale de l'entreprise : la même dans toutes les langues.
    if "Fausto Cejas" in n or "Santo Domingo Este" in n:
        return False
    # Le nom de la marque, suivi de son slogan ou d'une légende : « Speed Express Shipping — … ».
    if n.startswith("Speed Express Shipping — "):
        return False
    # La marque seule, en majuscules ou suivie d'une ponctuation.
    if n.rstrip(" ,.;:").lower() in {"speed express shipping", "speed express"}:
        return False
    # Un prénom suivi d'une initiale (« Marie-Ange D. »), des initiales seules (« MA »).
    if re.fullmatch(r"[A-ZÉ][a-zéèëï]+(-[A-ZÉ][a-zéèëï]+)? [A-Z]\.", n) or re.fullmatch(r"[A-Z]{2,3}", n):
        return False
    # Un identifiant de fuseau horaire (America/Santo_Domingo), un chemin de fichier (…/x.sql).
    if re.fullmatch(r"[A-Za-z]+/[A-Za-z_]+", n) or re.fullmatch(r"\S+\.(sql|py|js|css|json)", n):
        return False
    return True


class Page(HTMLParser):
    """Les textes et attributs que le moteur voit : ceux du <body> seulement."""

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.dans_body = False
        self.pile = []        # (balise, est-ce une icône ?)
        self.textes = []      # (texte brut, d'où)
        self.titre = None
        self._dans_titre = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "body":
            self.dans_body = True
        if tag == "title":
            self._dans_titre = True
        if tag not in ("br", "img", "input", "meta", "link", "hr", "source", "area", "base", "col", "embed", "wbr"):
            a = dict(attrs)
            # Un élément décoratif : « call », « location_on »… sont des ligatures de la
            # police Material Symbols ; les traduire casserait l'icône. On ne les
            # écarte que s'ils ressemblent à un identifiant (voir handle_data) : un vrai
            # texte visible, même sous un aria-hidden, reste contrôlé.
            classes = (a.get("class") or "").split()
            decoratif = (a.get("aria-hidden") == "true" or "material-symbols-outlined" in classes
                         or "ico" in classes or "svc__ico" in classes
                         or "Material Symbols" in (a.get("style") or ""))
            self.pile.append((tag, decoratif))
        if self.dans_body:
            for nom, val in attrs:
                if nom in ATTRS and val:
                    self.textes.append((val, f"attribut {nom}"))

    def handle_startendtag(self, tag, attrs):
        if self.dans_body:
            for nom, val in attrs:
                if nom in ATTRS and val:
                    self.textes.append((val, f"attribut {nom}"))

    def handle_endtag(self, tag):
        if tag == "title":
            self._dans_titre = False
        if any(t == tag for t, _ in self.pile):
            while self.pile and self.pile.pop()[0] != tag:
                pass

    def handle_data(self, data):
        if self._dans_titre:
            self.titre = (self.titre or "") + data
            return
        if not self.dans_body or not data.strip():
            return
        if any(t in IGNORES for t, _ in self.pile):
            return
        # Une ligature d'icône : identifiant en minuscules, dans un élément décoratif.
        if any(deco for _, deco in self.pile) and re.fullmatch(r"[a-z][a-z0-9_]*", data.strip()):
            return
        self.textes.append((data, "texte"))


def lire_dictionnaires():
    """Exporte les dictionnaires par fichier, en les exécutant : ce sont des .js."""
    prog = r"""
const vm=require('vm'),fs=require('fs');
const sortie={};
fs.readdirSync('assets/js').filter(n=>/^lang-dict(-\d+)?\.js$/.test(n)).forEach(n=>{
  const ctx={window:{SES_DICT:{}}};vm.createContext(ctx);
  vm.runInContext(fs.readFileSync('assets/js/'+n,'utf8'),ctx,{filename:n});
  sortie[n]=ctx.window.SES_DICT;
});
process.stdout.write(JSON.stringify(sortie));
"""
    r = subprocess.run(["node", "-e", prog], cwd=RACINE, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def parties_par_page():
    """Le tableau PAGE_PARTS de lang-switcher.js, lu tel quel."""
    src = (RACINE / "assets/js/lang-switcher.js").read_text(encoding="utf-8")
    bloc = src[src.index("var PAGE_PARTS = {"):]
    bloc = bloc[:bloc.index("};")]
    return {m[0]: re.findall(r"'(lang-dict-\d+\.js)'", m[1])
            for m in re.findall(r"'([\w.-]+\.html)':\s*\[([^\]]*)\]", bloc)}


def main():
    rapport = "--rapport" in sys.argv
    dicts = lire_dictionnaires()
    parties = parties_par_page()
    echecs = 0

    # 1. Les clés inatteignables : le moteur normalise le texte de la page, jamais la clé.
    inatteignables = [(f, k) for f, d in dicts.items() for k in d if norm(k) != k]
    if inatteignables:
        echecs += len(inatteignables)
        print(f"INATTEIGNABLES : {len(inatteignables)} clé(s) ne peuvent jamais correspondre "
              "(écrire ' et non ’, sans espace superflu) :")
        for f, k in inatteignables:
            print(f"   {f} : {k[:100]!r}")

    # 2. Une traduction vide, ou identique au français, est suspecte (hors sigles).
    identiques = []
    for f, d in dicts.items():
        for k, v in d.items():
            for lang, t in zip(("en", "es", "ht"), v):
                if t.strip() == k.strip() and traduisible(norm(k)) and len(k) > 12:
                    identiques.append((f, lang, k))
    if rapport and identiques:
        print(f"\nTRADUCTION IDENTIQUE AU FRANÇAIS : {len(identiques)} (à vérifier — parfois légitime)")
        for f, lang, k in identiques[:25]:
            print(f"   {f} [{lang}] {k[:90]!r}")

    # 3. Page par page : ce que le navigateur ne trouverait pas dans SES dictionnaires.
    ou_est = {}
    for f, d in dicts.items():
        for k in d:
            ou_est.setdefault(k, []).append(f)

    total_manquants = 0
    resume = []
    for page in sorted(RACINE.glob("*.html")):
        chargees = ["lang-dict.js"] + parties.get(page.name, [])
        # Les clés BRUTES, comme le navigateur : il compare le texte normalisé de la page à
        # la clé telle qu'elle est écrite. Une clé en ’ ne correspond donc jamais.
        cles = {k for f in chargees for k in dicts.get(f, {})}
        html = page.read_text(encoding="utf-8")
        p = Page(html)
        manquants, mal_places = {}, {}
        for brut, origine in p.textes:
            n = norm(brut)
            if not traduisible(n) or n in cles:
                continue
            ailleurs = [f for f in ou_est.get(n, []) if f not in chargees]
            (mal_places if ailleurs else manquants).setdefault(n, (origine, ailleurs))
        # Le titre de l'onglet : le moteur le traduit comme un texte, avec la même clé.
        if p.titre and traduisible(norm(p.titre)) and norm(p.titre) not in cles:
            ailleurs = [f for f in ou_est.get(norm(p.titre), []) if f not in chargees]
            (mal_places if ailleurs else manquants).setdefault(norm(p.titre), ("<title>", ailleurs))
        total_manquants += len(manquants) + len(mal_places)
        resume.append((page.name, len(manquants), len(mal_places), p.titre))
        if manquants or mal_places:
            echecs += len(manquants) + len(mal_places)
            print(f"\n{page.name}  — charge {', '.join(chargees)}")
            for n, (origine, _) in manquants.items():
                print(f"   ABSENT       {origine:<16} {n[:110]!r}")
            for n, (origine, ailleurs) in mal_places.items():
                print(f"   MAL PLACÉ    {origine:<16} {n[:80]!r} → dans {', '.join(ailleurs)}, non chargé ici")

    if echecs:
        print(f"\nÉCHEC : {echecs} problème(s) de traduction.")
        sys.exit(1)
    print(f"PASS traductions : {len(resume)} pages, chacune couverte par les dictionnaires qu'elle charge réellement.")


if __name__ == "__main__":
    main()
