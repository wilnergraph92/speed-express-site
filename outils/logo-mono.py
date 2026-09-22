#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Fabrique la version monochrome du logo, destinée à l'imprimante thermique.

Une imprimante thermique n'imprime qu'en noir ou blanc : elle tramerait le
rouge et le jaune du logo en gris pointillé. On convertit donc chaque pixel
coloré en noir plein, en gardant l'antialiasing des contours (c'est l'alpha
qui le porte) et les zones blanches en transparent.

Pur Python : ni Pillow ni ImageMagick sur cette machine.
"""
import struct
import sys
import zlib
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def lire_chunks(octets):
    assert octets[:8] == SIGNATURE, "ce n'est pas un PNG"
    i = 8
    while i < len(octets):
        (taille,) = struct.unpack(">I", octets[i:i + 4])
        type_ = octets[i + 4:i + 8]
        yield type_, octets[i + 8:i + 8 + taille]
        i += 8 + taille + 4


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def defiltrer(brut, largeur, hauteur, bpp):
    """Annule les filtres par ligne (spécification PNG, § 9)."""
    lignes, pas, pos = [], largeur * bpp, 0
    precedente = bytearray(pas)
    for _ in range(hauteur):
        filtre = brut[pos]; pos += 1
        ligne = bytearray(brut[pos:pos + pas]); pos += pas
        if filtre == 1:
            for x in range(bpp, pas):
                ligne[x] = (ligne[x] + ligne[x - bpp]) & 255
        elif filtre == 2:
            for x in range(pas):
                ligne[x] = (ligne[x] + precedente[x]) & 255
        elif filtre == 3:
            for x in range(pas):
                g = ligne[x - bpp] if x >= bpp else 0
                ligne[x] = (ligne[x] + ((g + precedente[x]) >> 1)) & 255
        elif filtre == 4:
            for x in range(pas):
                g = ligne[x - bpp] if x >= bpp else 0
                h = precedente[x - bpp] if x >= bpp else 0
                ligne[x] = (ligne[x] + paeth(g, precedente[x], h)) & 255
        elif filtre != 0:
            sys.exit(f"filtre {filtre} inconnu")
        lignes.append(ligne)
        precedente = ligne
    return lignes


def decoder(chemin):
    octets = Path(chemin).read_bytes()
    donnees, palette, transp, entete = b"", None, None, None
    for type_, contenu in lire_chunks(octets):
        if type_ == b"IHDR":
            entete = struct.unpack(">IIBBBBB", contenu)
        elif type_ == b"PLTE":
            palette = contenu
        elif type_ == b"tRNS":
            transp = contenu
        elif type_ == b"IDAT":
            donnees += contenu
    largeur, hauteur, profondeur, couleur, _, _, entrelace = entete
    assert profondeur == 8 and entrelace == 0, f"PNG non géré : {profondeur} bits, entrelacé {entrelace}"
    canaux = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[couleur]
    lignes = defiltrer(zlib.decompress(donnees), largeur, hauteur, canaux)

    pixels = []
    for ligne in lignes:
        rangee = []
        for x in range(largeur):
            p = ligne[x * canaux:(x + 1) * canaux]
            if couleur == 6:   rangee.append((p[0], p[1], p[2], p[3]))
            elif couleur == 2: rangee.append((p[0], p[1], p[2], 255))
            elif couleur == 4: rangee.append((p[0], p[0], p[0], p[1]))
            elif couleur == 0: rangee.append((p[0], p[0], p[0], 255))
            else:
                i = p[0]
                a = transp[i] if transp and i < len(transp) else 255
                rangee.append((palette[i * 3], palette[i * 3 + 1], palette[i * 3 + 2], a))
        pixels.append(rangee)
    return largeur, hauteur, pixels, couleur


def encre(r, v, b, a):
    """Part de noir à déposer : toute couleur devient noire, le blanc disparaît."""
    if a == 0:
        return 0
    haut, bas = max(r, v, b), min(r, v, b)
    saturation = (haut - bas) / 255
    if saturation > 0.25:            # rouge, bleu, jaune, vert → noir plein
        couverture = 1.0
    else:                            # gris neutre → on garde sa clarté
        couverture = 1.0 - (0.299 * r + 0.587 * v + 0.114 * b) / 255
    return round(255 * (a / 255) * couverture)


def encoder_gris_alpha(chemin, largeur, hauteur, alphas):
    """PNG type 4 (gris + alpha), gris toujours à 0 : c'est du noir plus ou moins opaque."""
    brut = bytearray()
    for y in range(hauteur):
        brut.append(0)               # filtre « None » : le contenu est déjà très répétitif
        for a in alphas[y]:
            brut += bytes((0, a))

    def chunk(type_, contenu):
        return (struct.pack(">I", len(contenu)) + type_ + contenu
                + struct.pack(">I", zlib.crc32(type_ + contenu) & 0xFFFFFFFF))

    Path(chemin).write_bytes(
        SIGNATURE
        + chunk(b"IHDR", struct.pack(">IIBBBBB", largeur, hauteur, 8, 4, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(brut), 9))
        + chunk(b"IEND", b""))


def main():
    source, cible = sys.argv[1], sys.argv[2]
    largeur, hauteur, pixels, couleur = decoder(source)
    print(f"source : {largeur}×{hauteur}, type couleur {couleur}")

    alphas, pleins, vides = [], 0, 0
    for rangee in pixels:
        ligne = []
        for (r, v, b, a) in rangee:
            e = encre(r, v, b, a)
            ligne.append(e)
            if e > 250: pleins += 1
            elif e < 5: vides += 1
        alphas.append(ligne)

    encoder_gris_alpha(cible, largeur, hauteur, alphas)
    total = largeur * hauteur
    print(f"noir plein : {pleins} px ({100*pleins/total:.1f} %) · "
          f"transparent : {vides} px ({100*vides/total:.1f} %) · "
          f"contours : {total-pleins-vides} px")
    print(f"écrit : {cible} ({Path(cible).stat().st_size} octets)")

    # relecture : le fichier produit doit se redécoder proprement
    l2, h2, p2, c2 = decoder(cible)
    assert (l2, h2) == (largeur, hauteur) and c2 == 4
    couleurs = {(r, v, b) for rangee in p2 for (r, v, b, a) in rangee if a > 0}
    assert couleurs <= {(0, 0, 0)}, f"des pixels ne sont pas noirs : {list(couleurs)[:5]}"
    print("relecture : dimensions conservées, aucun pixel non noir")


main()
