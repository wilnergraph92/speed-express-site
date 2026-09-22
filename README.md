# Speed Express Shipping — le site

Site statique : que du HTML, du CSS et du JavaScript. Pas de serveur à gérer,
pas d'outil à installer pour le modifier.

L'espace client (comptes, colis, factures, étiquettes) s'appuie sur
**Supabase** — la même solution que le site Goship Express. Tant qu'il n'est
pas configuré, il fonctionne en démonstration sur votre ordinateur : voir
« Espace client » plus bas.

## Voir le site sur votre ordinateur

```
cd ~/Desktop/Website_SES
python3 -m http.server 8790
```

Puis ouvrez <http://localhost:8790>. Ctrl-C dans le terminal pour arrêter.

## Modifier les coordonnées

Tout est dans **`assets/js/config.js`** — un seul fichier, et le changement
s'applique partout :

| Réglage | À quoi ça sert |
|---|---|
| `whatsapp` | Numéro WhatsApp, chiffres uniquement, indicatif compris |
| `telephone` | Numéro affiché et composé par les boutons « Appeler » |
| `email` | Adresse qui reçoit les demandes |
| `formEndpoint` | Service de formulaires (Formspree…). **Vide : le formulaire de contact prépare le message dans WhatsApp** |
| `siteUrl` | Adresse publique du site, une fois en ligne. Sert au QR code des étiquettes |
| `supabaseUrl` | Adresse du projet Supabase (Project Settings > API). **Vide : espace client en démonstration** |
| `supabaseKey` | Clé publique du projet (« Publishable key » ou « anon public »). Elle est faite pour être lue par les navigateurs : ce n'est pas un secret |
| `devise` | Devise des factures (`USD` par défaut) |

## Les pages

| Groupe | Pages |
|---|---|
| Principales | `index.html`, `nos-services.html`, `a-propos.html`, `suivi.html`, `blog.html`, `contacts.html` |
| Espace client | `creer-un-compte.html`, `connexion.html`, `nouveau-mot-de-passe.html`, `espace-client.html`, `tableau-de-bord.html` |
| Légales et aide | `confidentialite.html`, `termes-et-conditions.html`, `support.html`, `marchandises-dangereuses.html`, `fermer-un-compte.html` |
| Blog | 11 fichiers `article-*.html` |
| Erreur | `404.html` |

Chaque page est autonome : son style est à l'intérieur du fichier. Vous pouvez
en modifier une sans risquer de casser les autres.

## Les langues

Le bouton « Langue » propose français, anglais, espagnol et créole. La
traduction se fait dans le navigateur : le texte français affiché sert de clé.

- `assets/js/lang-dict.js` — vocabulaire commun (menus, pied de page, boutons)
- `assets/js/lang-dict-2.js` à `-10.js` — textes des pages, un fichier par groupe
- `assets/js/lang-dict-11.js` — espace client, tableau de bord, factures, étiquettes

Les pages de l'espace client rangent leurs phrases dans un
`<template data-textes>` : le sélecteur de langue les traduit comme le reste,
et les tableaux de bord se redessinent au changement de langue.

Pour traduire une phrase, ajoutez-la dans le bon fichier :

```js
"Vos colis arrivent": ["Your parcels arrive", "Sus paquetes llegan", "Kolis ou yo rive"],
```

L'ordre est toujours **[anglais, espagnol, créole]**. La clé doit reprendre le
texte français **exactement** tel qu'il s'affiche.

## Espace client

Comptes clients, colis, statuts, factures, QR codes et étiquettes. Trois rôles :

| Rôle | Ce qu'il voit |
|---|---|
| **Client** | Ses informations, ses colis, l'historique daté de chaque étape, ses factures |
| **Employé** | Les tâches que l'administrateur lui coche, une par une |
| **Administrateur** | Tout : clients, colis, factures, rôles et réglages |

Chaque compte reçoit à l'inscription un identifiant unique — `SES-67491` —
qui relie ses colis à son compte. Les colis sont numérotés `SES-10001-HT`, les
factures `FAC-2026-0001`.

### Trois fonctionnements

Le site choisit tout seul, d'après `config.js` :

| Mode | Quand | Ce qui se passe |
|---|---|---|
| `supabase` | `supabaseUrl` et `supabaseKey` renseignés | Tout est enregistré en ligne. Le serveur filtre chaque requête |
| `demo` | Rien de renseigné, sur votre ordinateur | Tout reste dans ce navigateur. Compte d'essai : `admin@speedexpress.demo` / `speed2026` |
| `off` | Rien de renseigné, sur un vrai nom de domaine | L'espace client reste fermé — aucun compte fictif en ligne |

Le tableau de bord affiche le mode en cours dans l'onglet « Réglages », avec
un bouton qui charge un jeu d'essai (deux clients, cinq colis, deux factures).

### Mettre l'espace client en ligne

1. Créez un projet sur [supabase.com](https://supabase.com) (l'offre gratuite suffit).
2. Ouvrez **SQL Editor > New query**, collez tout `outils/supabase.sql`, cliquez **Run**.
   Le script est relançable sans risque après chaque mise à jour du site.
3. Copiez l'adresse du projet et sa clé publique dans `assets/js/config.js`
   (`supabaseUrl`, `supabaseKey`).
4. Créez votre compte sur la page « Créer un compte » du site.
5. Revenez dans **SQL Editor** et lancez :
   `select public.definir_admin('votre-adresse@exemple.com');`

Vous êtes administrateur : le bouton « Tableau de bord » apparaît dans votre
espace. Les rôles suivants se donnent depuis l'onglet « Clients et rôles ».

### Sécurité

- **Les mots de passe ne sont jamais enregistrés en clair.** En ligne, ils sont
  confiés à Supabase Auth, qui les hache et que le site ne voit jamais. En
  démonstration, ils passent par PBKDF2-SHA-256 (150 000 tours, sel tiré au
  hasard pour chaque compte) : seule l'empreinte est écrite.
- **L'isolation des données est faite par le serveur**, pas par la page : les
  règles RLS de `outils/supabase.sql` décident, pour chaque ligne, qui peut la
  lire. Un client qui modifierait la page dans son navigateur n'obtiendrait
  rien de plus.
- **Les droits des employés sont vérifiés deux fois** : la page masque ce qui
  n'est pas permis, et la base refuse l'action de toute façon.
- **Le suivi public** (`suivi.html`) ne renvoie que le numéro, le statut et les
  étapes — jamais de nom, d'adresse ni de note interne.
- Un administrateur ne peut pas retirer son propre rôle.

> En mode démonstration, les comptes vivent dans le `localStorage` du
> navigateur : c'est un mode d'essai, pas un mode de production. Sur un vrai
> nom de domaine sans Supabase, l'espace client reste volontairement fermé.

### QR codes, codes-barres et étiquettes

À l'enregistrement, chaque colis reçoit un numéro, un jeton tiré au hasard, un
code-barres **Code 128** et un **QR code** qui mène à son suivi
(`suivi.html?colis=SES-10001-HT&j=…`). Ces codes ne changent plus ensuite :
une étiquette imprimée reste valable jusqu'à la livraison.

Les deux générateurs sont écrits dans `assets/js/vendor/ses-codes.js`, sans
bibliothèque extérieure : les étiquettes se fabriquent hors ligne, et aucun
script étranger ne s'exécute dans les pages du tableau de bord. Le QR code suit
la norme ISO/IEC 18004 (niveau M, versions 1 à 10) ; ses trames ont été
comparées case par case à une bibliothèque de référence, et une étiquette
produite par le site a été relue par un vrai lecteur de QR codes.

L'étiquette s'imprime au format 4 × 6 pouces, la facture en A4 : le bouton
« Imprimer » pose le document dans la page, masque le reste, et appelle
l'impression du navigateur — pas de fenêtre surgissante à débloquer.

### Imprimer sur une étiqueteuse thermique

Le format 4 × 6 pouces (101,6 × 152,4 mm) est celui des rouleaux d'expédition
courants, ceux de l'Anycash Y812BT par exemple. Trois points comptent :

- **Le logo est monochrome sur l'étiquette** (`assets/img/ses-logo-mono.png`).
  Une thermique n'imprime qu'en noir : elle tramerait le rouge et le jaune en
  gris pointillé. `outils/logo-mono.py` refabrique ce fichier depuis le logo en
  couleurs — toute couleur devient du noir plein, le blanc reste blanc, et les
  contours gardent leur lissage. La facture, elle, garde le logo en couleurs.
- **Les aplats sont forcés à l'impression** (`print-color-adjust:exact`). Sans
  cela, le navigateur laisse les fonds en blanc par défaut : le bandeau noir
  disparaîtrait, emportant son texte blanc avec lui.
- **L'impression attend le chargement des images.** Chrome ouvre la boîte
  d'impression sans les attendre ; une étiquette lancée trop tôt sortait sans
  son logo. Mesuré : au moment de l'insertion, l'image n'est pas encore
  chargée ; elle l'est quand l'impression part.

Dans la boîte d'impression : imprimante **Y812BT**, papier **4 × 6 po**,
échelle **100 %**, marges par défaut, en-têtes et pieds de page décochés.
L'étiquette occupe 93,6 × 119,7 mm sur les 93,6 × 144,4 mm imprimables.

## Les animations

Quatre effets seulement, dans `assets/js/ses-anim.js`, chacun avec une
fonction :

| Effet | À quoi il sert |
|---|---|
| Apparition au défilement | Guide la lecture et annonce la suite. Une seule fois par bloc |
| Parallaxe du camion | Donne de la profondeur à la seule image décorative, 14 px au plus |
| Survol | Montre ce qui est cliquable (cartes, lignes, boutons) |
| Lueur sous le curseur | Détache la carte de chiffres que l'on vise |

Rien n'est masqué par une feuille de style seule : c'est toujours le JavaScript
qui pose le masque juste avant de le lever. Si le script ne se charge pas, la
page reste entière. Tout mouvement s'arrête si le système demande
`prefers-reduced-motion`.

## Ce qui n'est pas encore branché

- **Le formulaire de contact** ouvre WhatsApp avec le message prérempli. Pour
  recevoir les demandes par e-mail, créez un formulaire sur formspree.io et
  collez son adresse dans `formEndpoint`.
- **L'expéditeur des e-mails** affiche `@…brevosend.com` et non une adresse
  Speed Express : Brevo ne peut pas signer une adresse `@gmail.com` qui ne lui
  appartient pas. Un nom de domaine réglerait cela.
- **Le lien « Unsubscribe »** ajouté par Brevo aux e-mails de compte est à
  retirer (**Transactional → Settings**) : un client qui cliquerait dessus ne
  recevrait plus son lien de mot de passe oublié.

## Les e-mails

L'inscription, le mot de passe oublié et le changement d'adresse envoient un
e-mail. Ils partent par **Brevo** (SMTP renseigné dans Supabase) et leurs
modèles, aux couleurs du site et dans les quatre langues, sont dans
`outils/emails/`. Tout est expliqué dans `outils/emails/LISEZMOI.md`.

## Les outils

Le site est reconstructible depuis l'export Claude Design :

| Script | Rôle |
|---|---|
| `outils/convertir-export.py` | Transforme les fichiers `.dc.html` en pages HTML autonomes |
| `outils/mise-en-page.py` | Retouches : liens, entête blanche, menu mobile, camion du hero, bouton « Créer un compte », apparition au défilement, version des scripts |
| `outils/pages-espace.py` | Assemble les cinq pages de l'espace client : contenu dans `outils/espace/`, entête et pied de page repris du reste du site |
| `outils/supabase.sql` | Le schéma de la base : tables, numérotation, historique, rôles et règles de sécurité |

Les deux scripts Python peuvent être relancés autant de fois que nécessaire :
ils remplacent leurs propres blocs au lieu de les empiler. L'ordre est
`pages-espace.py` puis `mise-en-page.py`.

### La version des scripts

Les navigateurs gardent les fichiers `.js` en mémoire. Chaque page les appelle
donc avec un numéro (`?v=7`). **Après toute modification d'un fichier de
`assets/js/`, augmentez ce numéro à trois endroits** :

1. `VERSION` dans `outils/mise-en-page.py`
2. `VERSION` dans `outils/pages-espace.py`
3. `var V` dans `assets/js/lang-switcher.js`

puis relancez les deux scripts. Sans cela, votre correction restera invisible
pendant des jours pour ceux qui ont déjà vu le site.

## Mise en ligne

Chaque `git push` sur `main` met le site à jour automatiquement (voir
`.github/workflows/deploy.yml`). Les fichiers de travail — `outils/`,
`README.md`, `.claude/` — ne sont jamais publiés.

> **Attention :** GitHub Pages ne lit pas `_headers`. Les en-têtes de sécurité
> qu'il contient ne s'appliquent qu'avec Netlify ou Cloudflare Pages.
