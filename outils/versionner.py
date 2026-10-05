#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monte le numéro de version du cache, à tous les endroits à la fois.

Pourquoi un outil : ce numéro (« ?v=31 » au bout de chaque script et feuille de
style) force le navigateur d'un visiteur de retour à recharger les fichiers
modifiés. Il est écrit à DEUX sortes d'endroits, et en oublier un sert de vieux
fichiers sans que rien ne le signale :

  · quatre constantes — mise-en-page.py, pages-espace.py, accessibilite.py et
    lang-switcher.js (celui-ci réclame les dictionnaires de traduction) ;
  · les pages sources de outils/pages/, où il est écrit en dur, plus de
    deux cents fois.

Usage :
    python3 outils/versionner.py          # passe au numéro suivant
    python3 outils/versionner.py 40       # impose le numéro 40

L'outil vérifie ensuite qu'il ne reste AUCUN ancien numéro, puis régénère les
pages. Relancé avec le numéro courant, il ne change rien.
"""
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# (fichier, motif dont le groupe 2 est le numéro)
CONSTANTES = [
    ("outils/mise-en-page.py", r'^(VERSION = ")(\d+)(")'),
    ("outils/pages-espace.py", r'^(VERSION = ")(\d+)(")'),
    ("outils/accessibilite.py", r'^(VERSION = ")(\d+)(")'),
    ("assets/js/lang-switcher.js", r"^(\s*var V = ')(\d+)(')"),
]
URL_ASSET = re.compile(r'(assets/[A-Za-z0-9/._-]+\?v=)(\d+)')


def numero_courant():
    texte = (RACINE / "assets/js/lang-switcher.js").read_text(encoding="utf-8")
    m = re.search(CONSTANTES[3][1], texte, re.M)
    return int(m.group(2))


def main():
    courant = numero_courant()
    cible = int(sys.argv[1]) if len(sys.argv) > 1 else courant + 1
    if cible < courant:
        sys.exit(f"Refusé : {cible} est plus ancien que le numéro courant ({courant}).")

    modifies = 0
    for chemin, motif in CONSTANTES:
        p = RACINE / chemin
        t = p.read_text(encoding="utf-8")
        u, n = re.subn(motif, lambda m: m.group(1) + str(cible) + m.group(3), t, count=1, flags=re.M)
        if n != 1:
            sys.exit(f"Constante introuvable dans {chemin} : la structure du fichier a changé.")
        if u != t:
            p.write_text(u, encoding="utf-8"); modifies += 1

    urls = 0
    for p in sorted((RACINE / "outils/pages").glob("*.html")):
        t = p.read_text(encoding="utf-8")
        u, n = URL_ASSET.subn(lambda m: m.group(1) + str(cible), t)
        urls += n
        if u != t:
            p.write_text(u, encoding="utf-8"); modifies += 1

    # Contrôle : rien d'autre que le numéro visé ne doit subsister.
    restes = set()
    for p in (RACINE / "outils/pages").glob("*.html"):
        restes |= {m for m in re.findall(r'assets/[A-Za-z0-9/._-]+\?v=(\d+)', p.read_text(encoding="utf-8"))}
    if restes - {str(cible)}:
        sys.exit(f"Anciens numéros restants dans outils/pages : {sorted(restes - {str(cible)})}")

    print(f"Version {courant} → {cible} : {modifies} fichier(s) modifié(s), {urls} références vérifiées.")
    if modifies:
        subprocess.run([sys.executable, str(RACINE / "outils/mise-en-page.py")], check=True)
    else:
        print("Rien à changer.")


if __name__ == "__main__":
    main()
