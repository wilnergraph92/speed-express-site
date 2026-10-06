# Le bureau Windows et macOS (phase 15)

> Statut : écrit, vérifié sans base réelle (faux serveur nourri des formes relevées sur PostgreSQL) ; **dépend des migrations 004 et 011,
> non appliquées en production** ; jamais essayé avec un vrai scanner USB ni une vraie imprimante d'étiquettes.
> Décision : [ADR 0013](ADR/0013-bureau-tableau-de-bord-installable.md).

## 1. Installer le tableau de bord sur un ordinateur

| Système | Navigateur | Geste |
|---|---|---|
| Windows | Chrome ou Edge | ouvrir `tableau-de-bord.html`, menu ⋮ (ou l'icône dans la barre d'adresse) > « Installer Speed Express — Centre de commande » |
| macOS | Chrome ou Edge | idem |
| macOS | Safari 17 ou plus | Fichier > Ajouter au Dock |

Le tableau de bord s'ouvre alors dans sa propre fenêtre, avec son icône. Le poste de scan affiche aussi un bouton « Installer sur cet
ordinateur » quand le navigateur le propose. Rien n'est installé hors du navigateur ; désinstaller = l'enlever comme une application.

## 2. Le poste de scan

Centre de commande > **Poste de scan** (visible si l'interrupteur `centreNoyau` est allumé et que le compte voit les opérations ; utilisable
si la base lui donne le profil entrepôt et au moins un entrepôt).

| Matériel | Comment c'est lu | Réglage conseillé |
|---|---|---|
| Scanner USB ou Bluetooth (mode clavier) | partout dans la page tant que le poste est affiché ; une rafale de touches terminée par Entrée (ou Tab) | suffixe « Entrée », préfixe aucun, clavier dans la langue du système |
| Saisie à la main | le champ « Numéro ou code lu » + Entrée | — |
| Imprimante d'étiquettes (pilote système) | bouton « Étiquette » d'une lecture acceptée : l'étiquette 4 × 6 du tableau de bord | papier 4 × 6 pouces, marges nulles, échelle 100 % |
| Imprimante de bureau | « Imprimer le bordereau » : la liste de la session | A4 ou Lettre |
| Fichiers | « Exporter (CSV) » ; « Importer une liste » (.txt ou .csv, 1 Mo, 500 numéros au plus) | — |
| Notifications du système | case « Notifications du bureau » (la permission n'est demandée qu'à ce clic) | — |

Une lecture : texte lu → `lg_scan_parcel(code, intention, entrepôt, genre, clé, {source: desktop})` → verdict de la base (accepté, doublon,
colis inconnu, mauvais entrepôt, étape impossible…), affiché en grand, son bref en cas de refus (réglable). Une coupure : la ligne dit « pas
parti » et propose « Réessayer », avec la même clé. Le même code relu dans la seconde et demie (scanner qui « bégaie », ou caméra et USB
ensemble) ne compte qu'une fois.

## 3. Vérifications

| Fichier | Ce qu'il prouve |
|---|---|
| `outils/tests/poste-contrat.cjs` (120) | trois implémentations ; signatures réelles (`poste-rpc.json`) ; refus avant tout appel (intention, entrepôt, clé) ; intentions et verdicts de la base ; CSV (BOM, guillemets, aucune formule) ; liste importée (sans en-tête ni doublon, plafonnée, un export se réimporte) ; clés neuves et « Réessayer » avec la même ; section ouverte sur « ops », sans relecture automatique ; textes ; manifeste et icônes |
| `outils/tests/scanner.cjs` (28) | scanner USB (rafale contre frappe humaine), anti-rebond, lecteurs multiples |
| `outils/tests/logistique-applications-essai.py` | écrit `poste-rpc.json` sur PostgreSQL jetable |
| à l'écran (serveur d'essai) | rafales de touches simulées : accepté, doublon, inconnu ; saisie à la main ; créole ; 375 px sans débordement ; plus aucune lecture hors du poste |

## 4. Avant de s'en servir

1. Migrations 004 et 011 en production, après sauvegarde vérifiée ; allumer `centreNoyau`.
2. Rattacher chaque agent à sa succursale et lui donner le droit de faire avancer les colis.
3. **Essayer avec le vrai matériel** : le scanner de l'entrepôt (suffixe Entrée), l'imprimante d'étiquettes (une étiquette, un QR lu par un
   téléphone), l'installation sur un Windows et un Mac, une notification reçue onglet caché.
