# Speed Express Shipping — le site

Site statique : que du HTML, du CSS et un peu de JavaScript. Pas de serveur à
gérer, pas de base de données, pas d'outil à installer pour le modifier.

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
| `siteUrl` | Adresse publique du site, une fois en ligne |

## Les pages

| Groupe | Pages |
|---|---|
| Principales | `index.html`, `nos-services.html`, `a-propos.html`, `suivi.html`, `blog.html`, `contacts.html` |
| Légales et aide | `confidentialite.html`, `termes-et-conditions.html`, `support.html`, `marchandises-dangereuses.html`, `fermer-un-compte.html` |
| Blog | 11 fichiers `article-*.html` |
| Erreur | `404.html` |

Chaque page est autonome : son style est à l'intérieur du fichier. Vous pouvez
en modifier une sans risquer de casser les autres.

## Les langues

Le bouton « Langue » propose français, anglais, espagnol et créole. La
traduction se fait dans le navigateur : le texte français affiché sert de clé.

- `assets/js/lang-dict.js` — vocabulaire commun (menus, pied de page, boutons)
- `assets/js/lang-dict-2.js` à `-7.js` — textes des pages, un fichier par groupe

Pour traduire une phrase, ajoutez-la dans le bon fichier :

```js
"Vos colis arrivent": ["Your parcels arrive", "Sus paquetes llegan", "Kolis ou yo rive"],
```

L'ordre est toujours **[anglais, espagnol, créole]**. La clé doit reprendre le
texte français **exactement** tel qu'il s'affiche.

## Ce qui n'est pas encore branché

- **Le suivi de colis** affiche la référence saisie et des étapes d'exemple.
  Il n'y a pas encore de base de données : le vrai statut passe par WhatsApp.
- **Le formulaire de contact** ouvre WhatsApp avec le message prérempli. Pour
  recevoir les demandes par e-mail, créez un formulaire sur formspree.io et
  collez son adresse dans `formEndpoint`.

## Mise en ligne

Chaque `git push` sur `main` met le site à jour automatiquement (voir
`.github/workflows/deploy.yml`). Les fichiers de travail — `outils/`,
`README.md`, `.claude/` — ne sont jamais publiés.

> **Attention :** GitHub Pages ne lit pas `_headers`. Les en-têtes de sécurité
> qu'il contient ne s'appliquent qu'avec Netlify ou Cloudflare Pages.
