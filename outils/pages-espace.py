#!/usr/bin/env python3
"""Assemble les cinq comptes depuis leurs enveloppes SEO et fragments métier.

Aucune dépendance à une page générée : sources dans outils/pages et outils/espace.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from unification import developper
SITE = Path(__file__).resolve().parent.parent
FRAGMENTS = SITE / "outils/espace"
VERSION = "29"
# Les metadata appartiennent aux enveloppes HTML, pas à une seconde liste Python.
PAGES = [{"nom": nom} for nom in (
    "creer-un-compte.html", "connexion.html", "nouveau-mot-de-passe.html",
    "espace-client.html", "tableau-de-bord.html",
)]


def assembler(page):
    nom = page["nom"]
    source = (SITE / "outils/pages" / nom).read_text(encoding="utf-8")
    fragment = (FRAGMENTS / nom).read_text(encoding="utf-8").strip()
    return developper(source.replace("{{contenu}}", fragment), nom)


def main():
    for page in PAGES:
        html = assembler(page)
        cible = SITE / page["nom"]
        if not cible.exists() or cible.read_text(encoding="utf-8") != html:
            cible.write_text(html, encoding="utf-8")
            print(f"{cible.name} : mise à jour")
        else:
            print(f"{cible.name} : déjà à jour")


if __name__ == "__main__":
    main()
