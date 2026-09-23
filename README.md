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

L'étiquette porte le **téléphone du destinataire**, pas son adresse postale :
le livreur appelle avant de se déplacer, et une adresse tient rarement sur une
ligne à Port-au-Prince. L'adresse reste enregistrée et s'affiche dans la fiche
du colis. Le numéro vient du champ « Téléphone du destinataire » ; s'il est
vide, l'étiquette reprend celui du compte client, qui est le cas courant.

Le **pays** (obligatoire, c'est lui qui termine le numéro du colis) et la
**ville** sont regroupés sous « Lieu de livraison ». Le pays est rangé en deux
lettres mais s'écrit en entier partout où on le montre — « Haïti », pas « HT »
— et le séparateur disparaît si la ville manque.

Le menu des villes se remplit selon le pays choisi, depuis
`assets/js/ses-villes.js` : les 140 communes d'Haïti par département, les 158
municipios dominicains par province, et les villes des États-Unis où le service
livre réellement. Il se termine toujours par **« Autre ville… »**, qui ouvre un
champ libre : aucune liste n'est complète, et une commune oubliée ne doit
jamais empêcher d'enregistrer un colis.

### Imprimer sur une étiqueteuse thermique

Le format 4 × 6 pouces (101,6 × 152,4 mm) est celui des rouleaux d'expédition
courants, ceux de l'Anycash Y812BT par exemple. Trois points comptent :

- **Le logo est monochrome sur l'étiquette** (`assets/img/ses-logo-mono.png`).
  Une thermique n'imprime qu'en noir : elle tramerait le rouge et le jaune en
  gris pointillé. `outils/logo-mono.py` refabrique ce fichier depuis le logo en
  couleurs — toute couleur devient du noir plein, le blanc reste blanc, et les
  contours gardent leur lissage. La facture, elle, garde le logo en couleurs.
- **L'étiquette n'a aucun aplat.** Son en-tête est un simple logo noir sur
  fond blanc, séparé du reste par un filet : une thermique sort un trait net
  là où un grand à-plat noir la fait chauffer et baver.
- **Les aplats restants sont forcés à l'impression** (`print-color-adjust:exact`).
  Sans cela, la facture perdrait l'en-tête de son tableau et sa pastille
  « payée / impayée », que le navigateur laisse en blanc par défaut.
- **L'impression attend le chargement des images.** Chrome ouvre la boîte
  d'impression sans les attendre ; une étiquette lancée trop tôt sortait sans
  son logo. Mesuré : au moment de l'insertion, l'image n'est pas encore
  chargée ; elle l'est quand l'impression part.

Dans la boîte d'impression : imprimante **Y812BT**, papier **4 × 6 po**,
échelle **100 %**, marges par défaut, en-têtes et pieds de page décochés.
L'étiquette occupe 93,6 × 119,7 mm sur les 93,6 × 144,4 mm imprimables.

### Mettre la base à jour

`outils/supabase.sql` décrit la base complète, pour une installation neuve. Une
base déjà en service se met à jour avec les fichiers `supabase-maj-*.sql`, à
passer une fois chacun dans **SQL Editor** :

| Fichier | Ce qu'il ajoute |
|---|---|
| `supabase-maj-telephone.sql` | Le téléphone du destinataire sur le colis |
| `supabase-maj-facturation.sql` | Le tarif au livre, les frais de service, les paiements, la facture automatique |

Ils sont écrits pour pouvoir tourner deux fois sans rien casser, et ne touchent
aucune donnée existante.

## La facturation

Le tarif d'expédition n'est pas un barème : il se choisit **colis par colis**,
à l'enregistrement, en dollars par livre. Le prix du colis suit tout seul —
`poids × tarif` — et ne se saisit jamais à la main.

```
8 lb × 5 $/lb = 40 $   + 10 $ de frais de service = 50 $
8 lb × 7 $/lb = 56 $   + 10 $ de frais de service = 66 $
```

**Chaque colis enregistré reçoit aussitôt sa facture.** Ce n'est pas le
navigateur qui la crée mais la base elle-même (`facturer_colis`, dans
`outils/supabase.sql`) : une facture ne peut donc ni manquer, ni viser le
mauvais client. Le mode démonstration applique la même règle, écrite une
seconde fois dans `ses-api.js`.

### Ce qui fige une facture

Tant qu'aucun paiement n'est entré, la facture suit son colis : corriger un
poids mal saisi corrige la facture. **Dès qu'un paiement est enregistré, elle
ne bouge plus** — ses lignes gardent le poids, le tarif et le montant du jour
où elle a été établie. Changer le tarif d'un colis suivant, ou même celui de
ce colis-là, ne réécrit aucune facture ancienne.

### Les frais de service

10 $, fixes, ajoutés une fois par facture. Ils ne se règlent pas depuis le
formulaire : la base les pose. Sur une **facture regroupée**, ils ne sont
comptés qu'une seule fois pour l'ensemble des colis, et non une fois par
colis.

### Paiements et balance

Le champ « Montant payé » porte le **total encaissé depuis le début**, pas le
dernier versement. La balance en découle : `grand total − montant payé`. Une
facture réglée en entier passe d'elle-même en « payée », et basculer le statut
à la main vaut règlement complet — le statut et le montant payé ne peuvent
jamais se contredire.

### Facture regroupée

Dans l'onglet **Colis**, cocher plusieurs colis **d'un même client** fait
apparaître une barre « Facture regroupée ». Le document reprend les lignes de
chaque colis telles qu'elles ont été figées — chacun garde donc son tarif — et
n'ajoute les frais de service qu'une fois. Cocher un colis d'un autre client
est refusé.

### La signature

La facture ne montre pas le tarif au livre : le client paie un montant, pas un
barème. Le tarif reste dans les données et dans le calcul. Le poids, lui, est
affiché ; quand une facture ancienne ne le porte pas dans ses lignes, il est
repris du colis auquel elle est liée — le montant, jamais.

Le pied de page ne dit qu'une chose, « Merci pour votre confiance ! », et
s'imprime au bas de la feuille. Les marges de `@page` sont à zéro, les vraies
marges étant posées à l'intérieur : c'est ce qui empêche le navigateur
d'imprimer ses propres en-têtes — la date, le titre de l'onglet, l'adresse du
site et le numéro de page — sur une facture remise au client.

La facture réserve une zone de signature. Déposez l'image dans
`assets/img/ses-signature.png` : elle apparaîtra d'elle-même. Sans le fichier,
il reste le trait à signer à la main, et rien ne casse.

### Ce qui ne doit jamais venir de l'autre site

Ce site et **Goship Express** sont publiés tous deux sur
`wilnergraph92.github.io` : **même origine, donc même `localStorage`**. Une
session ouverte sur l'un est lisible depuis l'autre.

Ce qui les sépare, et qu'il faut garder séparé :

| | Speed Express | Goship Express |
|---|---|---|
| Réglages | `window.SES_CONFIG` | `window.GOSHIP_CONFIG` |
| Clés de stockage | `ses-…` | `gse-…` |
| Projet Supabase | `ltbqqchtyzlyakcsxxis` | `gpfdyslysqjmojgzggib` |
| Code client | `SES-0000` | `GSE-0000` |
| Adresse de facturation | C. Fausto Cejas Rodríguez Km12 | Calle 25 de Febrero, La Caleta |
| RNC | 1-33-40588-1 | 133-79976-6 |

`ses-entete.js` ne reconnaît que le jeton `sb-ltbqqchtyzlyakcsxxis-auth-token`,
et pas n'importe quel `sb-*`. Sans ce filtre, un visiteur connecté chez Goship
verrait ici « Mon espace » et tomberait sur la page de connexion de Speed
Express. **Toute lecture de `localStorage` ajoutée plus tard doit viser une
clé précise, jamais un motif.**

Les coordonnées de facturation vivent dans `assets/js/config.js`
(`factureAdresse`, `factureTelephone`, `factureRNC`). C'est le seul endroit à
changer, et le seul à vérifier avant d'imprimer.

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
