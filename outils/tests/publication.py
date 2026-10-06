#!/usr/bin/env python3
"""Ce qui part en ligne, et seulement cela.

Tout fichier à la racine du dépôt est publié, sauf ce que .github/workflows/
deploy.yml retire (rsync --exclude). Un document de travail ajouté à la racine
— les notes d'architecture, les procédures de reprise, les scripts de
sauvegarde — serait donc lisible par n'importe qui, sans que rien ne le
signale. Ce test reconstitue ce que le déploiement publie et refuse tout ce
qui n'est pas explicitement public.

Il ne modifie aucun fichier."""
import fnmatch, re, subprocess, sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]

# Les seules entrées de la racine qui ont le droit d'être servies aux visiteurs.
# tableau-de-bord.webmanifest : le manifeste d'installation du tableau de bord comme application de bureau (phase 15, ADR 0013) — public par nature.
PUBLIC = {'assets', 'robots.txt', 'sitemap.xml', '_headers', '_redirects', 'tableau-de-bord.webmanifest'}
# Exclusions posées d'avance pour des fichiers annoncés mais pas encore écrits
# (procédures de sauvegarde, politique de sécurité). Elles ne sont pas reprochées
# tant que le fichier n'existe pas ; si l'un d'eux est créé, l'exclusion agit.
ANTICIPEES = {'/scripts', '/SECURITY.md'}
# Ce qui ne doit JAMAIS être publié, quoi qu'il arrive.
INTERDIT = ['CLAUDE.md', 'README.md', 'SECURITY.md', 'ARCHITECTURE-BASELINE.md',
            'docs/', 'scripts/', 'outils/', '.github/', '.claude/', '.git/']

def exclusions():
    texte = (RACINE / '.github/workflows/deploy.yml').read_text(encoding='utf8')
    return re.findall(r"--exclude\s+'([^']+)'", texte)

def exclu(chemin, motifs):
    """Reproduit la règle de rsync pour les motifs utilisés ici : « /x »
    n'atteint que la racine, « x » atteint n'importe quel niveau."""
    parts = chemin.split('/')
    for m in motifs:
        if m.startswith('/'):
            if fnmatch.fnmatch(parts[0], m[1:]): return True
        elif any(fnmatch.fnmatch(p, m) for p in parts):
            return True
    return False

def fichiers():
    sortie = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard'],
                            cwd=RACINE, capture_output=True, text=True, check=True).stdout
    return [l for l in sortie.splitlines() if l and (RACINE / l).exists()]

def main():
    motifs = exclusions()
    erreurs = []
    if not motifs:
        erreurs.append('deploy.yml : aucune exclusion trouvée (la lecture du fichier a changé ?)')

    publies = [f for f in fichiers() if not exclu(f, motifs)]
    racine_publiee = sorted({f.split('/')[0] for f in publies})

    for entree in racine_publiee:
        if entree.endswith('.html') and '/' not in entree: continue
        if entree not in PUBLIC:
            erreurs.append(f"publié mais pas déclaré public : {entree} "
                           f"— ajoute --exclude '/{entree}' dans deploy.yml, ou déclare-le ici si c'est voulu")

    for interdit in INTERDIT:
        for f in publies:
            if f == interdit or (interdit.endswith('/') and f.startswith(interdit)):
                erreurs.append(f'PUBLIÉ alors que cela ne doit jamais l\'être : {f}')
                break

    # Les exclusions ne doivent pas viser dans le vide : un motif qui ne retire
    # plus rien est le signe d'un fichier renommé, donc d'une protection perdue.
    tous = fichiers()
    for m in motifs:
        if m in ('.DS_Store', '_site', '.git') or m in ANTICIPEES: continue
        if not any(exclu(f, [m]) for f in tous):
            erreurs.append(f"exclusion sans effet : {m} (le fichier a-t-il été renommé ?)")

    if erreurs:
        print('ÉCHEC publication :'); [print('  -', e) for e in erreurs]; sys.exit(1)
    print(f"PASS publication : {len(publies)} fichiers publiés, racine = "
          f"{len([e for e in racine_publiee if e.endswith('.html')])} pages + "
          f"{', '.join(e for e in racine_publiee if not e.endswith('.html'))} ; "
          f"{len(motifs)} exclusions actives")

main()
