#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Speed Express Shipping — carte du monde en pointillés.

Le tableau de bord affiche, sous « Destinations les plus actives », un fond de
carte sur lequel `ses-dashboard.js` pose un repère par pays desservi. Ce fond
est un fichier SVG fabriqué ici, jamais téléchargé : le site n'a aucune
dépendance externe, et la carte doit rester identique dans dix ans.

Commande :

    python3 outils/carte-monde.py                # écrit la carte servie
    python3 outils/carte-monde.py --apercu p.ppm # rend un aperçu pour l'œil

La projection est équirectangulaire et **connue des deux côtés** :

    x = (lon + 180) / 360 * 720      y = (90 - lat) / 150 * 300

`ses-dashboard.js` répète exactement ces deux formules en pourcentages pour
poser ses repères. Changer une constante ici oblige à changer l'autre.

Les contours sont volontairement grossiers : c'est un fond décoratif en
pointillés, pas une carte de navigation. Les repères, eux, sont réels.
"""
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
CIBLE = SITE / 'assets' / 'img' / 'ses-carte-monde.svg'

# Cadre de la carte : 90°N en haut (y = 0), 60°S en bas (y = 300). L'Antarctique
# n'est pas dessiné, comme sur les cartes de fret.
LON_MIN, LON_MAX = -180.0, 180.0
LAT_HAUT, LAT_BAS = 90.0, -60.0
LARGEUR, HAUTEUR = 720.0, 300.0
PAS = 2.5  # écart entre deux points, en degrés

# La carte est dessinée de 90°N à 60°S, mais le tableau de bord la recadre :
# les deux pôles n'ont aucun repère et mangeaient la moitié de la hauteur.
# `ses-dashboard.js` place ses repères avec (78 - latitude) / 136 : les mêmes
# constantes, écrites une seconde fois dans le navigateur.
CROPE_LAT_HAUT, CROPE_LAT_BAS = 78.0, -58.0


def projeter(lon, lat):
    x = (lon - LON_MIN) / (LON_MAX - LON_MIN) * LARGEUR
    y = (LAT_HAUT - lat) / (LAT_HAUT - LAT_BAS) * HAUTEUR
    return x, y


# --------------------------------------------------------------------------
# Contours des terres, en degrés (longitude, latitude), sens indifférent :
# le test d'appartenance utilise la règle pair-impair sur l'ensemble.
# --------------------------------------------------------------------------
TERRES = [
    # Amérique du Nord, de l'Alaska au Panama.
    [(-168, 65), (-165, 60), (-152, 59), (-140, 60), (-131, 54), (-125, 49),
     (-124, 40), (-117, 32), (-110, 23), (-105, 20), (-97, 16), (-92, 15),
     (-84, 10), (-79, 9), (-83, 15), (-88, 21), (-97, 26), (-90, 29),
     (-82, 25), (-81, 31), (-76, 35), (-70, 42), (-66, 45), (-60, 47),
     (-64, 52), (-70, 60), (-78, 62), (-95, 68), (-125, 70), (-140, 70),
     (-156, 71)],
    # Groenland.
    [(-45, 60), (-30, 66), (-19, 72), (-24, 80), (-45, 83), (-62, 80),
     (-55, 70), (-48, 65)],
    # Amérique du Sud.
    [(-77, 8), (-72, 12), (-62, 11), (-52, 5), (-50, 0), (-44, -3),
     (-35, -6), (-38, -13), (-40, -22), (-48, -25), (-58, -34), (-62, -40),
     (-65, -45), (-68, -52), (-75, -50), (-73, -42), (-71, -33), (-70, -18),
     (-76, -14), (-81, -5), (-79, 2)],
    # Afrique.
    [(-17, 15), (-7, 4), (3, 6), (9, 4), (12, -6), (15, -18), (18, -34),
     (27, -34), (32, -26), (40, -16), (41, -2), (51, 11), (43, 11), (38, 17),
     (33, 28), (32, 31), (20, 32), (10, 37), (0, 36), (-6, 36), (-10, 30),
     (-17, 21)],
    # Eurasie : Europe, Asie, Arabie, Inde et Asie du Sud-Est.
    [(-10, 36), (-9, 43), (-2, 49), (2, 51), (8, 54), (10, 57), (5, 58),
     (6, 62), (12, 70), (30, 71), (60, 72), (80, 74), (100, 77), (140, 73),
     (160, 70), (180, 66), (170, 60), (160, 58), (155, 50), (140, 45),
     (130, 35), (122, 31), (120, 22), (110, 20), (105, 9), (100, 2),
     (98, 8), (95, 16), (90, 22), (88, 21), (80, 15), (78, 8), (73, 15),
     (68, 23), (60, 25), (57, 26), (50, 29), (48, 29), (55, 25), (59, 22),
     (52, 15), (43, 13), (39, 20), (35, 28), (34, 31), (36, 36), (30, 40),
     (26, 40), (23, 38), (18, 40), (16, 38), (15, 40), (12, 42), (10, 44),
     (13, 45), (3, 43), (0, 39), (-2, 37), (-6, 36)],
    # Australie.
    [(114, -22), (122, -18), (130, -12), (137, -12), (142, -11), (145, -15),
     (150, -22), (153, -28), (150, -37), (146, -39), (140, -38), (130, -32),
     (115, -34), (113, -26)],
    # Îles principales : sans elles, la carte paraît vide.
    [(43, -12), (50, -15), (48, -25), (44, -22)],                      # Madagascar
    [(130, 31), (134, 34), (141, 40), (145, 44), (142, 45), (140, 36),
     (136, 34), (132, 33)],                                            # Japon
    [(-10, 51), (-6, 52), (-6, 55), (-9, 58), (-11, 54)],               # Irlande
    [(-6, 50), (-2, 51), (-1, 54), (-2, 58), (-5, 58), (-6, 55)],       # Grande-Bretagne
    [(166, -46), (170, -43), (174, -41), (178, -38), (176, -36),
     (172, -41), (168, -44)],                                          # Nouvelle-Zélande
    [(95, 6), (106, 2), (116, -4), (126, -3), (140, -3), (134, -1),
     (120, 1), (106, 1)],                                              # Sumatra, Bornéo, Java
    [(119, 1), (126, 2), (126, -6), (119, -6)],                         # Sulawesi
    [(131, -1), (146, -6), (150, -9), (140, -9)],                       # Nouvelle-Guinée
    [(120, 6), (126, 8), (126, 18), (120, 16)],                         # Philippines
    [(80, 6), (82, 9), (80, 10)],                                       # Sri Lanka
    [(-24, 64), (-14, 66), (-16, 63)],                                  # Islande
    [(-84, 22), (-77, 20), (-74, 20), (-77, 23), (-84, 23)],            # Cuba
    [(-74, 18), (-68, 18), (-68, 20), (-74, 20)],                       # Hispaniola, PR
    [(-78, 18), (-76, 18), (-76, 19)],                                  # Jamaïque
    [(-62, 17), (-61, 18)],                                             # Petites Antilles
    [(-90, 29), (-89, 30)],                                             # delta du Mississippi
]


def dans_les_terres(lon, lat):
    """Règle pair-impair : un point est sur terre s'il croise un nombre impair
    de côtés de l'ensemble des contours."""
    dedans = False
    for contour in TERRES:
        for i in range(len(contour)):
            x1, y1 = contour[i]
            x2, y2 = contour[(i + 1) % len(contour)]
            if (y1 > lat) != (y2 > lat):
                croisement = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
                if lon < croisement:
                    dedans = not dedans
    return dedans


def ranges_par_ligne():
    """Une suite de segments horizontaux par ligne de latitude : les
    pointillés sont obtenus par `stroke-dasharray`, donc un seul chemin suffit
    et le fichier reste léger."""
    lignes = []
    y = LAT_HAUT - PAS / 2
    while y > LAT_BAS:
        debut, precedent = None, None
        for i in range(int((LON_MAX - LON_MIN) / PAS) + 1):
            lon = LON_MIN + i * PAS + PAS / 2
            if lon > LON_MAX:
                break
            if dans_les_terres(lon, y):
                if debut is None:
                    debut = lon
                precedent = lon
            elif debut is not None:
                lignes.append((debut, precedent, y))
                debut = None
        if debut is not None:
            lignes.append((debut, precedent, y))
        y -= PAS
    return lignes


def chemin(lignes):
    morceaux = []
    for debut, fin, lat in lignes:
        x1, y = projeter(debut, lat)
        x2, _ = projeter(fin, lat)
        morceaux.append('M%.1f %.1fH%.1f' % (x1, y, x2))
    return ''.join(morceaux)


def ecrire_svg():
    lignes = ranges_par_ligne()
    _, y_haut = projeter(0, CROPE_LAT_HAUT)
    hauteur_cadre = (CROPE_LAT_HAUT - CROPE_LAT_BAS) / (LAT_HAUT - LAT_BAS) * HAUTEUR
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!-- Speed Express Shipping — carte du monde décorative, fabriquée par\n'
        '     outils/carte-monde.py. Ne pas modifier à la main. -->\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 %.1f %g %.1f" '
        'role="img" aria-hidden="true" focusable="false">\n'
        '<title>Carte du monde</title>\n'
        '<path fill="none" stroke="#d5d9e0" stroke-width="3.1" '
        'stroke-linecap="round" stroke-dasharray="0.01 %.1f" d="%s"/>\n'
        '</svg>\n' % (y_haut, LARGEUR, hauteur_cadre,
                      PAS / (LON_MAX - LON_MIN) * LARGEUR * 0.8, chemin(lignes))
    )
    CIBLE.write_text(svg, encoding='utf-8')
    print('%s : %d lignes, %.1f ko' % (CIBLE.name, len(lignes), len(svg) / 1024))


def apercu(destination):
    """Aperçu écrit à la main en PPM : aucun outil graphique n'est requis pour
    relire la carte, et `convert` suffit ensuite à en faire une image."""
    echelle = 2
    largeur, hauteur = int(LARGEUR * echelle), int(HAUTEUR * echelle)
    image = [[(255, 255, 255) for _ in range(largeur)] for _ in range(hauteur)]

    def point(px, py):
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                if dx * dx + dy * dy > 5:
                    continue
                x, y = int(px + dx), int(py + dy)
                if 0 <= x < largeur and 0 <= y < hauteur:
                    image[y][x] = (120, 126, 140)

    y = LAT_HAUT - PAS / 2
    while y > LAT_BAS:
        x = LON_MIN + PAS / 2
        while x < LON_MAX:
            if dans_les_terres(x, y):
                px, py = projeter(x, y)
                point(px * echelle, py * echelle)
            x += PAS
        y -= PAS
    with open(destination, 'wb') as fichier:
        fichier.write(b'P6 %d %d 255\n' % (largeur, hauteur))
        for ligne in image:
            fichier.write(bytes(valeur for pixel in ligne for valeur in pixel))
    print('%s écrit' % destination)


if __name__ == '__main__':
    if '--apercu' in sys.argv:
        apercu(sys.argv[sys.argv.index('--apercu') + 1])
    else:
        ecrire_svg()
