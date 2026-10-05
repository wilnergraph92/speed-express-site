#!/usr/bin/env bash
# Crée la paire de clés de chiffrement des sauvegardes, UNE SEULE FOIS, sur votre
# ordinateur. Rien n'est écrit dans le dépôt, rien n'est envoyé nulle part.
#
#   bash scripts/backup/generer-cle.sh ~/cles-ses/ses-sauvegarde.key
#
# - la clé PRIVÉE reste dans le fichier indiqué (droits 600). Sans elle, AUCUNE
#   sauvegarde n'est lisible, par personne : faites-en au moins DEUX copies hors
#   ligne (gestionnaire de mots de passe + papier ou clé USB dans un autre lieu) ;
# - la clé PUBLIQUE s'affiche : c'est elle (et elle seule) que vous donnez à la
#   sauvegarde (variable SES_AGE_RECIPIENT). Elle n'est pas secrète.
set -euo pipefail
cible="${1:-}"
[ -n "$cible" ] || { echo "Usage : bash scripts/backup/generer-cle.sh <chemin/du/fichier.key>"; exit 2; }
command -v age-keygen >/dev/null || { echo "age-keygen introuvable : installez « age » (brew install age)."; exit 1; }
dossier="$(cd "$(dirname "$cible")" 2>/dev/null && pwd)" || { echo "Le dossier de $cible n'existe pas."; exit 1; }
racine="$(cd "$(dirname "$0")/../.." && pwd)"
case "$dossier/" in "$racine"/*) echo "REFUS : ce chemin est DANS le dépôt Git. Une clé de chiffrement ne doit jamais s'y trouver."; exit 1;; esac
[ ! -e "$cible" ] || { echo "REFUS : $cible existe déjà (on n'écrase jamais une clé)."; exit 1; }
umask 077
age-keygen -o "$cible" >/dev/null 2>&1
chmod 600 "$cible"
echo "Clé privée créée : $cible   (droits 600)"
echo "Clé PUBLIQUE à utiliser pour chiffrer :"
grep -o 'age1[0-9a-z]*' "$cible" | head -1
echo
echo "À FAIRE MAINTENANT : copier $cible dans un coffre HORS LIGNE (2 copies, 2 endroits)."
