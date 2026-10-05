#!/usr/bin/env python3
"""Rétention des sauvegardes : garder les récentes de près, les anciennes de loin.

    python3 scripts/backup/rotation.py --dossier ./sauvegardes            # montre ce qui serait supprimé
    python3 scripts/backup/rotation.py --dossier ./sauvegardes --appliquer

Politique par défaut (grand-père / père / fils) :
    1 sauvegarde par jour pendant 30 jours,
    1 par semaine pendant 12 semaines,
    1 par mois pendant 12 mois,
    1 par an pendant 5 ans.
On garde, pour chaque période, la PLUS RÉCENTE. Tout le reste est supprimé.

Sûretés : sans --appliquer, rien n'est supprimé ; la sauvegarde la plus récente
n'est jamais supprimée ; s'il y a trois sauvegardes ou moins, rien n'est supprimé ;
seuls les fichiers nommés ses-AAAAMMJJTHHMMSSZ.tar.gz.age (et leur .sha256) sont
touchés, jamais le journal, jamais un autre fichier, jamais un sous-dossier."""
import argparse
import datetime
import os
import re
import sys

MOTIF = re.compile(r'^ses-(\d{8}T\d{6}Z)\.tar\.gz\.age$')


def date_de(nom):
    return datetime.datetime.strptime(MOTIF.match(nom).group(1), '%Y%m%dT%H%M%SZ')


def selection(noms, jours=30, semaines=12, mois=12, ans=5):
    """Rend (à garder, à supprimer). Fonction pure : elle ne touche à aucun fichier.
    Les périodes se comptent à partir des sauvegardes elles-mêmes, pas de l'horloge :
    si les sauvegardes s'arrêtent, la rotation ne vide pas le dossier."""
    valides = sorted((n for n in noms if MOTIF.match(n)), key=date_de, reverse=True)   # du plus récent au plus ancien
    if len(valides) <= 3:
        return set(valides), set()
    garder = {valides[0]}

    def un_par(cle, limite):
        vus = {}
        for n in valides:                           # parcours récent → ancien : le premier vu est le plus récent
            k = cle(date_de(n))
            if k not in vus:
                vus[k] = n
        for k in sorted(vus, reverse=True)[:limite]:
            garder.add(vus[k])

    un_par(lambda d: d.date(), jours)
    un_par(lambda d: d.isocalendar()[:2], semaines)
    un_par(lambda d: (d.year, d.month), mois)
    un_par(lambda d: d.year, ans)
    return garder, set(valides) - garder


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--dossier', required=True)
    ap.add_argument('--appliquer', action='store_true')
    ap.add_argument('--jours', type=int, default=30)
    ap.add_argument('--semaines', type=int, default=12)
    ap.add_argument('--mois', type=int, default=12)
    ap.add_argument('--ans', type=int, default=5)
    a = ap.parse_args(argv)
    if not os.path.isdir(a.dossier):
        print('ÉCHEC : dossier introuvable : %s' % a.dossier, file=sys.stderr)
        return 1
    noms = [n for n in os.listdir(a.dossier) if os.path.isfile(os.path.join(a.dossier, n)) and not os.path.islink(os.path.join(a.dossier, n))]
    garder, supprimer = selection(noms, a.jours, a.semaines, a.mois, a.ans)
    print('%s sauvegarde(s) : %s à garder, %s à supprimer.' % (len(garder) + len(supprimer), len(garder), len(supprimer)))
    for n in sorted(supprimer):
        print(('SUPPRIME ' if a.appliquer else 'supprimerait ') + n)
        if a.appliquer:
            os.remove(os.path.join(a.dossier, n))
            somme = os.path.join(a.dossier, n + '.sha256')
            if os.path.isfile(somme):
                os.remove(somme)
    if supprimer and not a.appliquer:
        print('Rien n\'a été supprimé (ajoutez --appliquer).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
