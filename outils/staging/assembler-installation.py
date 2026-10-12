#!/usr/bin/env python3
"""Assemble le script d'installation d'un projet Supabase de PRÉPRODUCTION (staging).

    python3 outils/staging/assembler-installation.py
    → outils/staging/sortie/installation-staging.sql   (non suivi par Git : il se régénère)

Un seul fichier à coller dans le SQL Editor d'un projet Supabase NEUF, créé pour la préproduction. Il contient :
1. un garde-fou qui REFUSE toute base où l'espace client existe déjà sans être marquée « staging » (la production,
   le projet Goship…) et qui, sinon, pose le marqueur ses_meta.environnement = 'staging' ; le tout dans UNE
   transaction : si le garde-fou refuse, rien ne s'applique, même si l'on poursuit le script avec psql ;
2. les migrations de l'espace client, dans l'ordre éprouvé par outils/tests/schema-rejouable.py (toutes rejouables).

Le noyau logistique (001 → 013) n'y est pas : il se passe ensuite, étape par étape, comme en production
(docs/production/GO-LIVE-CHECKLIST.md §4), pour que la préproduction en soit la répétition générale.
Les scripts de données (donnees-synthetiques.sql, reinitialiser.sql, anonymiser.sql) exigent ce marqueur."""
import os
import re
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(os.path.dirname(ICI))


def garde():
    """Le marqueur (outils/staging/marquer.sql), sans sa transaction : les fichiers qui suivent ont la leur."""
    texte = open(os.path.join(ICI, 'marquer.sql'), encoding='utf-8').read()
    texte = texte.split('begin;\n\n', 1)[1].rsplit('commit;', 1)[0]   # sans son en-tête ni sa transaction
    entete = ('-- =============================================================================\n'
              '-- Speed Express Shipping — INSTALLATION DE LA PRÉPRODUCTION (staging)\n'
              '-- GÉNÉRÉ par outils/staging/assembler-installation.py : ne pas modifier à la main.\n'
              '-- À coller UNIQUEMENT dans le SQL Editor du projet Supabase de PRÉPRODUCTION (jamais « speed-express-site »,\n'
              '-- jamais Goship). Le garde-fou ci-dessous refuse une base qui porte déjà l\'espace client sans être marquée « staging ».\n'
              '-- =============================================================================\n\n')
    return entete + texte + '\n'


def ordre():
    texte = open(os.path.join(RACINE, 'outils', 'tests', 'schema-rejouable.py'), encoding='utf-8').read()
    return re.findall(r"'(supabase[\w.-]*\.sql)'", re.search(r'^ORDRE = \[(.*?)\]', texte, re.M | re.S).group(1))


def assembler():
    """Tout dans UNE transaction : si le garde-fou refuse, rien d'autre ne s'applique, même avec psql lancé sans arrêt
    sur erreur (chaque instruction suivante échoue dans la transaction annulée, et le « commit » final l'annule).
    Les fichiers qui ouvrent leur propre transaction (« begin; » / « commit; » en début de ligne) y sont fondus."""
    morceaux = ['begin;\n\n', garde()]
    for f in ordre():
        texte = open(os.path.join(RACINE, 'outils', f), encoding='utf-8').read()
        texte = re.sub(r'^(begin|commit);[ \t]*$', r'-- (\1; fondu dans la transaction unique)', texte, flags=re.M)
        morceaux.append('\n-- ===== outils/%s =====\n' % f)
        morceaux.append(texte.rstrip() + '\n')
    morceaux.append('\ncommit;\n')
    return ''.join(morceaux)


def main():
    sortie = os.path.join(ICI, 'sortie')
    os.makedirs(sortie, exist_ok=True)
    chemin = os.path.join(sortie, 'installation-staging.sql')
    with open(chemin, 'w', encoding='utf-8') as f:
        f.write(assembler())
    print('Écrit : %s (%d fichiers : %s)' % (os.path.relpath(chemin, RACINE), len(ordre()), ', '.join(ordre())))
    return 0


if __name__ == '__main__':
    sys.exit(main())
