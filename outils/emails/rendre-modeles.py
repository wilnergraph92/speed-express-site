#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vérifie et rend les modèles d'e-mails Supabase.

Interprète le sous-ensemble de la syntaxe Go réellement employé :
  {{ $l := printf "%s" .Data.langue }}
  {{ if eq $l "en" }}…{{ else if eq $l "es" }}…{{ else }}…{{ end }}
  {{ .ConfirmationURL }}  {{ .Email }}  {{ .NewEmail }}

Sert à deux choses : confirmer que chaque « if » a bien son « end », et
produire un aperçu HTML dans les quatre langues pour les regarder.
"""
import re
import sys
from pathlib import Path

MODELES = Path(__file__).resolve().parent
SORTIE = Path(__file__).resolve().parent / "apercu"

VALEURS = {
    ".ConfirmationURL": "https://ltbqqchtyzlyakcsxxis.supabase.co/auth/v1/verify?token=exemple&type=signup&redirect_to=https://wilnergraph92.github.io/speed-express-site/espace-client.html",
    ".Email": "kelly@exemple.com",
    ".NewEmail": "kelly.macillien@exemple.com",
}

JETON = re.compile(r"\{\{(.*?)\}\}", re.S)


def equilibre(texte, nom):
    """Chaque « if » doit avoir son « end »."""
    profondeur, ligne_ouverte = 0, []
    for m in JETON.finditer(texte):
        c = m.group(1).strip()
        ligne = texte[:m.start()].count("\n") + 1
        if c.startswith("if "):
            profondeur += 1
            ligne_ouverte.append(ligne)
        elif c == "end":
            profondeur -= 1
            if profondeur < 0:
                sys.exit(f"{nom} ligne {ligne} : « end » sans « if » correspondant.")
            ligne_ouverte.pop()
        elif c.startswith("else"):
            if profondeur == 0:
                sys.exit(f"{nom} ligne {ligne} : « else » hors de tout « if ».")
    if profondeur:
        sys.exit(f"{nom} : {profondeur} « if » jamais fermé (ligne {ligne_ouverte[0]}).")
    return True


def rendre(texte, langue):
    """Rend le modèle pour une langue donnée."""
    sortie, i, pile = [], 0, []      # pile : (on_ecrit, une_branche_a_deja_pris)
    variables = {}

    def ecrit():
        return all(p[0] for p in pile)

    for m in JETON.finditer(texte):
        if ecrit():
            sortie.append(texte[i:m.start()])
        i = m.end()
        c = m.group(1).strip()

        # Déclaration : {{ $l := printf "%s" .Data.langue }}
        decl = re.fullmatch(r'(\$\w+)\s*:=\s*printf\s+"%s"\s+\.Data\.(\w+)', c)
        if decl:
            variables[decl.group(1)] = langue if decl.group(2) == "langue" else ""
            continue

        cond = re.fullmatch(r'(?:else\s+)?if\s+eq\s+(\$\w+)\s+"([^"]*)"', c)
        if cond:
            vrai = variables.get(cond.group(1)) == cond.group(2)
            if c.startswith("else"):
                _, deja = pile.pop()
                # Une branche « else if » n'écrit que si aucune n'a encore pris.
                pile.append(((not deja) and vrai, deja or vrai))
            else:
                pile.append((vrai, vrai))
            continue

        if c == "else":
            parent, deja = pile.pop()
            pile.append((not deja, True))
            continue

        if c == "end":
            pile.pop()
            continue

        if c in VALEURS:
            if ecrit():
                sortie.append(VALEURS[c])
            continue

        sys.exit(f"Expression non reconnue : {{{{ {c} }}}}")

    sortie.append(texte[i:])
    return "".join(sortie)


def main():
    SORTIE.mkdir(exist_ok=True)
    langues = {"fr": "français", "en": "anglais", "es": "espagnol", "ht": "créole"}
    for f in sorted(MODELES.glob("*.html")):
        texte = f.read_text(encoding="utf-8")
        equilibre(texte, f.name)
        n = len(JETON.findall(texte))
        print(f"{f.name} : {n} expressions, structure équilibrée")
        for code, nom in langues.items():
            html = rendre(texte, code)
            if "{{" in html:
                sys.exit(f"  {f.name} [{code}] : une expression n'a pas été remplacée.")
            cible = SORTIE / f"{f.stem}-{code}.html"
            cible.write_text(html, encoding="utf-8")
            # le titre doit changer d'une langue à l'autre
            titre = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
            print(f"    {nom:9s} → {titre.group(1).strip()[:58] if titre else '(pas de titre)'}")
    print(f"\nAperçus écrits dans {SORTIE}")


if __name__ == "__main__":
    main()
