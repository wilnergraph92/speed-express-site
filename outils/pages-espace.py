#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Speed Express Shipping — assemblage des pages de l'espace client.

Les cinq pages de comptes (inscription, connexion, mot de passe, espace
client, tableau de bord) ne viennent pas de l'export Claude Design : leur
contenu est écrit à la main dans outils/espace/*.html. Ce script leur pose
autour l'entête et le pied de page du reste du site, pris tels quels sur une
page existante : le jour où l'entête change, il suffit de relancer ce script
et les cinq pages suivent.

    python3 outils/pages-espace.py

Relançable sans risque : les pages sont réécrites à l'identique.
"""
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent
FRAGMENTS = Path(__file__).resolve().parent / "espace"

# Page dont on emprunte l'entête, le pied de page et la feuille de style de base.
MODELE = "contacts.html"

# Version des scripts (cache des navigateurs) — la même que le reste du site.
VERSION = "17"

PAGES = [
    {
        "nom": "creer-un-compte.html",
        "titre": "Créer un compte",
        "description": "Créez votre compte Speed Express Shipping et recevez votre identifiant client pour suivre vos colis.",
        "scripts": ["ses-api.js", "ses-ui.js", "ses-compte.js"],
    },
    {
        "nom": "connexion.html",
        "titre": "Se connecter",
        "description": "Connectez-vous à votre espace client Speed Express Shipping : vos colis, leurs statuts et vos factures.",
        "scripts": ["ses-api.js", "ses-ui.js", "ses-compte.js"],
    },
    {
        "nom": "nouveau-mot-de-passe.html",
        "titre": "Nouveau mot de passe",
        "description": "Choisissez un nouveau mot de passe pour votre compte Speed Express Shipping.",
        "scripts": ["ses-api.js", "ses-ui.js", "ses-compte.js"],
    },
    {
        "nom": "espace-client.html",
        "titre": "Mon espace client",
        "description": "Vos colis, leurs statuts, l'historique de chaque étape et vos factures, au même endroit.",
        "scripts": ["ses-api.js", "vendor/ses-codes.js", "ses-ui.js", "ses-espace.js"],
        "noindex": True,
    },
    {
        "nom": "tableau-de-bord.html",
        "titre": "Tableau de bord",
        "description": "Gestion des colis, des statuts, des factures, des clients et des rôles.",
        "scripts": ["ses-api.js", "vendor/ses-codes.js", "ses-villes.js", "ses-ui.js", "ses-admin.js"],
        "noindex": True,
    },
]

# ---------------------------------------------------------------------------
# Feuille de style partagée par les cinq pages
# ---------------------------------------------------------------------------
CSS = """
<style id="ses-espace-css">
/* Espace client et tableau de bord — les briques communes aux cinq pages.
   Le reste du site porte ses styles en attribut ; ici, les mêmes motifs
   reviennent des dizaines de fois (champs, boutons, tableaux) : une classe
   vaut mieux qu'un attribut recopié. */

/* « hidden » doit l'emporter sur les classes qui posent un display : sans
   cette règle, un bouton .ses-bouton marqué hidden restait affiché. */
[hidden]{display:none !important}

/* --- Champs ------------------------------------------------------------- */
.ses-champ{display:grid;gap:7px;min-width:0}
.ses-champ>span:first-child{font-size:14px;font-weight:700;color:var(--ink)}
.ses-champ i{color:var(--red);font-style:normal;margin-left:2px}
.ses-champ input,.ses-champ select,.ses-champ textarea{
  width:100%;font:inherit;font-size:15.5px;color:var(--ink);background:#fff;
  border:1px solid var(--line);border-radius:11px;padding:13px 15px;
  transition:border-color .16s ease,box-shadow .16s ease}
.ses-champ textarea{resize:vertical;line-height:1.55}
.ses-champ select{appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%236b7280' stroke-width='1.5'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 15px center;background-size:10px;padding-right:38px}
.ses-champ input:focus,.ses-champ select:focus,.ses-champ textarea:focus{
  outline:none;border-color:var(--red);box-shadow:0 0 0 3px rgba(232,18,27,.13)}
.ses-champ input[aria-invalid],.ses-champ select[aria-invalid],.ses-champ textarea[aria-invalid]{border-color:var(--red)}
.ses-champ input:disabled,.ses-champ input[readonly]{background:var(--smoke);color:#6b7280}
.ses-grille2{display:grid;grid-template-columns:1fr 1fr;gap:16px 20px}
.ses-grille3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px 20px}
@media (max-width:680px){.ses-grille2,.ses-grille3{grid-template-columns:1fr}}

.ses-voir-mdp{position:absolute;right:7px;top:50%;transform:translateY(-50%);
  background:var(--smoke);border:1px solid var(--line);border-radius:8px;
  padding:7px 11px;font:inherit;font-size:13px;font-weight:700;color:#4b5563;cursor:pointer}
.ses-voir-mdp:hover{color:var(--ink);border-color:#cfd5de}

/* --- Boutons ------------------------------------------------------------ */
.ses-bouton{display:inline-flex;align-items:center;justify-content:center;gap:8px;
  font:inherit;font-weight:700;font-size:14.5px;border-radius:11px;padding:13px 20px;
  border:1px solid transparent;cursor:pointer;text-align:center;white-space:nowrap;text-decoration:none}
.ses-bouton:disabled{opacity:.55;cursor:default}
.ses-bouton-principal{background:var(--red);color:#fff;box-shadow:0 12px 26px -16px rgba(232,18,27,.9)}
.ses-bouton-principal:hover{background:var(--red2);color:#fff}
.ses-bouton-second{background:#fff;color:var(--ink);border-color:var(--line)}
.ses-bouton-second:hover{background:var(--smoke);color:var(--ink);border-color:#cfd5de}
.ses-bouton-clair{background:rgba(255,255,255,.1);color:#fff;border-color:rgba(255,255,255,.22)}
.ses-bouton-clair:hover{background:rgba(255,255,255,.2);color:#fff}
.ses-bouton-danger{background:#fff;color:var(--red2);border-color:rgba(232,18,27,.35)}
.ses-bouton-danger:hover{background:var(--red);color:#fff;border-color:var(--red)}
.ses-bouton-mini{padding:8px 12px;font-size:13px;border-radius:9px}
.ses-lien{background:none;border:0;padding:0;font:inherit;font-weight:700;color:var(--red);cursor:pointer;text-decoration:underline}
.ses-lien:hover{color:var(--ink2)}

/* --- Onglets ------------------------------------------------------------ */
.ses-onglets{display:flex;flex-wrap:wrap;gap:6px;border-bottom:1px solid var(--line)}
.ses-onglet{background:none;border:0;border-bottom:3px solid transparent;margin-bottom:-1px;
  padding:12px 16px;font:inherit;font-weight:700;font-size:15px;color:#6b7280;cursor:pointer;
  transition:color .16s ease,border-color .16s ease}
.ses-onglet:hover{color:var(--ink)}
.ses-onglet[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--red)}

/* --- Filtres ------------------------------------------------------------ */
.ses-filtres{display:flex;flex-wrap:wrap;gap:8px}
.ses-filtre{background:#fff;border:1px solid var(--line);border-radius:999px;
  padding:8px 15px;font:inherit;font-size:13.5px;font-weight:700;color:#4b5563;cursor:pointer;
  transition:background .16s ease,color .16s ease,border-color .16s ease}
.ses-filtre:hover{border-color:#cfd5de;color:var(--ink)}
.ses-filtre[aria-pressed="true"]{background:var(--ink);border-color:var(--ink);color:#fff}

/* --- Blocs et chiffres -------------------------------------------------- */
.ses-bloc{background:#fff;border:1px solid var(--line);border-radius:16px;padding:clamp(18px,2.4vw,26px)}
.ses-chiffre{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px 20px;
  box-shadow:0 20px 40px -34px rgba(11,12,14,.5)}
.ses-chiffre b{display:block;font-family:'Saira',Manrope,sans-serif;font-size:clamp(25px,3.4vw,33px);
  font-weight:800;line-height:1.1;letter-spacing:-.02em}
.ses-chiffre span{display:block;margin-top:3px;font-size:13.5px;color:#6b7280;font-weight:600}

/* --- Tableaux -----------------------------------------------------------
   Sur téléphone, chaque ligne devient une petite fiche : le libellé de la
   colonne est repris dans data-libelle et s'affiche devant la valeur.     */
.ses-tableau{width:100%;border-collapse:collapse;background:#fff;
  border:1px solid var(--line);border-radius:16px;overflow:hidden}
.ses-tableau th{text-align:left;padding:13px 16px;background:var(--smoke);
  font-size:11.5px;letter-spacing:.1em;color:#4b5563;font-weight:700;
  border-bottom:1px solid var(--line);white-space:nowrap}
.ses-tableau td{padding:14px 16px;border-bottom:1px solid #eef0f3;font-size:14.5px;vertical-align:middle}
.ses-tableau tr:last-child td{border-bottom:0}
.ses-tableau .ses-mono{font-family:'IBM Plex Mono',monospace;font-weight:600;letter-spacing:.04em}
.ses-actions-ligne{display:flex;flex-wrap:wrap;gap:6px;justify-content:flex-end}
@media (max-width:900px){
  .ses-tableau,.ses-tableau tbody,.ses-tableau tr,.ses-tableau td{display:block;width:100%}
  .ses-tableau thead{display:none}
  .ses-tableau{border:0;background:none}
  .ses-tableau tr{background:#fff;border:1px solid var(--line);border-radius:14px;
    margin-bottom:12px;padding:6px 2px}
  .ses-tableau td{border-bottom:1px solid #f2f4f6;display:flex;gap:14px;
    align-items:center;justify-content:space-between;padding:11px 15px}
  .ses-tableau td:last-child{border-bottom:0}
  .ses-tableau td::before{content:attr(data-libelle);font-size:11.5px;letter-spacing:.08em;
    color:#6b7280;font-weight:700;flex:none}
  .ses-tableau td:empty{display:none}
  .ses-actions-ligne{justify-content:flex-start}
}

/* --- Étapes du parcours ------------------------------------------------- */
.ses-etapes{display:grid;grid-template-columns:repeat(4,1fr);gap:0;margin:0;padding:0;list-style:none}
.ses-etapes li{position:relative;padding-top:20px;text-align:center;font-size:12px;
  font-weight:700;color:#9aa2ae;min-width:0}
.ses-etapes li::before{content:"";position:absolute;top:5px;left:50%;transform:translateX(-50%);
  width:11px;height:11px;border-radius:50%;background:#e2e5ea;z-index:1}
.ses-etapes li::after{content:"";position:absolute;top:10px;left:50%;width:100%;height:2px;background:#e2e5ea}
.ses-etapes li:last-child::after{display:none}
.ses-etapes li.ses-faite{color:var(--ink)}
.ses-etapes li.ses-faite::before{background:var(--red)}
.ses-etapes li.ses-faite::after{background:var(--red)}
.ses-etapes li.ses-faite:last-of-type{color:var(--red)}

/* --- Historique --------------------------------------------------------- */
.ses-historique{list-style:none;margin:0;padding:0}

/* --- Suggestions de clients -------------------------------------------- */
.ses-suggestions{position:relative;z-index:3;margin-top:-2px;background:#fff;
  border:1px solid var(--line);border-radius:11px;box-shadow:0 20px 40px -26px rgba(11,12,14,.5);
  max-height:230px;overflow:auto}
.ses-suggestions button{display:block;width:100%;text-align:left;background:none;border:0;
  border-bottom:1px solid #f2f4f6;padding:11px 14px;font:inherit;font-size:14px;cursor:pointer}
.ses-suggestions button:last-child{border-bottom:0}
.ses-suggestions button:hover,.ses-suggestions button:focus{background:var(--smoke);outline:none}

/* --- Pagination --------------------------------------------------------- */
.ses-pagination{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:16px;
  font-size:14px;color:#6b7280}
.ses-pagination:empty{display:none}

/* --- Fenêtres ----------------------------------------------------------- */
.ses-dialogue{width:min(760px,calc(100vw - 32px));max-height:min(86vh,900px);
  border:0;border-radius:18px;padding:clamp(22px,3vw,32px);
  background:#fff;color:var(--ink);box-shadow:0 50px 90px -40px rgba(11,12,14,.65)}
.ses-dialogue-etroit{width:min(520px,calc(100vw - 32px))}
.ses-dialogue::backdrop{background:rgba(11,12,14,.55);backdrop-filter:blur(3px)}
.ses-fermer{position:absolute;top:14px;right:14px;width:36px;height:36px;border-radius:10px;
  background:var(--smoke);border:1px solid var(--line);font-size:15px;color:#4b5563;cursor:pointer;line-height:1}
.ses-fermer:hover{background:#eceef1;color:var(--ink)}

/* --- Impression --------------------------------------------------------- */
#ses-impression{display:none}
</style>
"""


def shell():
    """Entête (tout ce qui précède </header>) et pied de page du site."""
    html = (SITE / MODELE).read_text(encoding="utf-8")
    fin_entete = html.find("</header>") + len("</header>")
    debut_pied = html.find("<footer")
    if fin_entete < 0 or debut_pied < 0:
        sys.exit(f"{MODELE} : entête ou pied de page introuvable.")
    return html[:fin_entete], html[debut_pied:]


def titrer(tete, page):
    """Titre, description et aperçus sociaux de la page."""
    titre = f"{page['titre']} — Speed Express Shipping"
    tete = re.sub(r"<title>.*?</title>", f"<title>{titre}</title>", tete, count=1, flags=re.S)
    tete = re.sub(r'(<meta name="description" content=")[^"]*(")',
                  lambda m: m.group(1) + page["description"] + m.group(2), tete, count=1)
    tete = re.sub(r'(<meta property="og:title" content=")[^"]*(")',
                  lambda m: m.group(1) + titre + m.group(2), tete, count=1)
    tete = re.sub(r'(<meta property="og:description" content=")[^"]*(")',
                  lambda m: m.group(1) + page["description"] + m.group(2), tete, count=1)
    if page.get("noindex"):
        # Un espace privé n'a rien à faire dans les moteurs de recherche.
        tete = tete.replace('<meta name="theme-color"',
                            '<meta name="robots" content="noindex,nofollow">\n<meta name="theme-color"', 1)
    return tete


def scripter(tete, page):
    """Remplace la liste des scripts par celle dont la page a besoin."""
    fichiers = (["config.js", "lang-dict.js", "lang-switcher.js"] + page["scripts"]
                + ["ses-entete.js", "ses-anim.js"])
    balises = "\n".join(f'<script src="assets/js/{f}?v={VERSION}" defer></script>' for f in fichiers)
    return re.sub(r'(<script src="assets/js/[^"]*"[^>]*></script>\s*)+', balises + "\n", tete, count=1)


def assembler(page, tete_modele, pied):
    fragment = (FRAGMENTS / page["nom"]).read_text(encoding="utf-8").strip()

    # Les <style id="ses-…"> d'un fragment remontent dans <head>.
    styles = re.findall(r'<style id="ses-[^"]*">.*?</style>', fragment, flags=re.S)
    for s in styles:
        fragment = fragment.replace(s, "").strip()

    tete = scripter(titrer(tete_modele, page), page)
    # Posée avant la feuille de l'entête, pour que « mise-en-page.py », qui
    # remet la sienne juste avant </head>, ne déplace rien à chaque passage.
    bloc = "\n".join([CSS.strip()] + styles) + "\n"
    ancre = '<style id="ses-entete-css">'
    if ancre in tete:
        tete = tete.replace(ancre, bloc + ancre, 1)
    else:
        tete = tete.replace("</head>", bloc + "</head>", 1)

    return tete + "\n\n" + fragment + "\n\n" + pied


def main():
    tete_modele, pied = shell()
    for page in PAGES:
        cible = SITE / page["nom"]
        html = assembler(page, tete_modele, pied)
        avant = cible.read_text(encoding="utf-8") if cible.exists() else None
        if html != avant:
            cible.write_text(html, encoding="utf-8")
            print(f"{page['nom']} : {'mise à jour' if avant else 'créée'} ({len(html) // 1024} Ko)")
        else:
            print(f"{page['nom']} : déjà à jour")


if __name__ == "__main__":
    main()
