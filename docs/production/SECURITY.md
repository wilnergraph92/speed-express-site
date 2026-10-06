# Sécurité en production

> L'état réel au 6 octobre 2026, ce qui le garantit, et ses limites connues. Complète `docs/security/` (authentification, suivi public).

## 1. Où vit chaque secret

| Secret | Où | Jamais |
|---|---|---|
| Clé publique Supabase | `assets/js/config.js` (publique par nature : elle n'ouvre que ce que les règles de la base autorisent) | — |
| Clé secrète Supabase (service role) | secrets GitHub des **dépôts privés** (travailleur, sauvegarde) | dans ce dépôt public, un navigateur, une conversation |
| Chaîne de connexion de la base | secret du dépôt privé de sauvegarde | idem |
| Clés Brevo (API et SMTP) | secret du dépôt privé ; réglages SMTP de Supabase | idem |
| Jeton Expo | secret du dépôt privé | idem |
| Clé privée `age` | hors ligne, hors GitHub | sur l'ordinateur de travail |

Garde-fous : *secret scanning* et *push protection* actifs sur le dépôt ; le test `publication.py` refuse tout fichier non déclaré
public ; les journaux des travaux masquent les secrets et les adresses ; la base nettoie tout texte venu de l'extérieur (`ops.scrub`).

## 2. Accès aux données

- **Règles de sécurité par ligne** sur les tables d'origine ; le noyau (`logistics`, `analytics`, `ops`) est **fermé** : on n'y entre que
  par des fonctions (`public.lg_*`, `public.ses_*`) qui lisent le compte connecté et contrôlent ses droits — aucune ne prend l'identité en
  paramètre. Les essais vérifient ces portes avec les privilèges par défaut de Supabase (toute nouvelle fonction ouverte à tous) simulés.
- **Rôles** : client, employé (droits un par un), gérant, administrateur ; la direction seule voit la santé du système, recalcule les
  rapports, vérifie les exécutions.
- **Clé secrète** : seules les fonctions `ses_nt_*`, `ses_an_refresh`, `ses_ops_heartbeat` l'exigent ; la sonde `ses_health` est la seule
  fonction ouverte aux visiteurs, et ne dit rien d'autre que « ok » et le niveau de migration.

## 3. Limitation de débit

| Où | Plafond |
|---|---|
| Authentification (Supabase) | limites intégrées de Supabase (connexions, e-mails, inscriptions) |
| Portail : demandes d'enlèvement, de livraison, tickets | 10 par heure et par compte (en plus des règles métier : 5 tickets par 24 h…) |
| Portail : messages, adresses | 60 et 30 par heure |
| Terrain : gestes mobiles, scans | 1 200 par 10 minutes et par compte |
| Erreurs signalées par les navigateurs | 20 par heure et par compte |

Au-delà : erreur `LG007`, message « trop de demandes » ; l'application mobile réessaie plus tard. Les travaux sans compte connecté ne sont
jamais limités.

## 4. Navigateur

- **Politique de contenu** posée en `<meta>` dans chaque page à la génération (`outils/securite.py`) : scripts du site seulement, aucune
  bibliothèque depuis un CDN (`assets/js/vendor/`), connexions limitées au projet Supabase, `manifest-src 'self'`.
- **Anti-cadre** par script (`ses-anti-cadre.js`) et politique de référent par `<meta>`.
- **Limites connues** : GitHub Pages ne permet pas de poser des en-têtes HTTP (`_headers` n'est pas lu) — pas de `frame-ancestors` réel,
  pas de `X-Content-Type-Options` ; HTTPS et HSTS sont ceux de `github.io`. Un proxy (Cloudflare) les apporterait : nouvelle pile, ADR
  à part.
- **CORS** : l'API de Supabase répond aux appels du navigateur quelle que soit leur origine ; la protection repose sur la clé publique
  (sans pouvoir propre) et sur les règles de la base, jamais sur l'origine. Les fournisseurs du travailleur (Brevo, Expo) ne sont appelés
  que depuis le serveur.
- Le site partage `localStorage` avec Goship (même domaine) : une session n'est jamais reconnue sur la seule allure d'une clé
  (`ses-entete.js` reconstruit le nom exact).

## 5. Sauvegardes

Quotidiennes, **chiffrées** (`age`), **vérifiées par restauration** dans une base vide jetable avant d'être rendues, gardées 90 jours ;
leur arrivée et leur vérification sont visibles dans la page Santé ([MONITORING](MONITORING.md)).

## 6. Mises en ligne

Aucune mise en ligne sans un geste du propriétaire (envoi sur `main` ou lancement manuel, puis approbation de l'environnement
`github-pages` une fois la règle posée) ; aucune mise en ligne si un essai échoue (la CI rejoue tout, PostgreSQL compris) ; aucune
migration, restauration ou bascule d'interrupteur automatique.

## 7. À faire (propriétaire)

- Protéger `main` ; exiger une approbation sur l'environnement `github-pages` ; activer Dependabot ([GO-LIVE](GO-LIVE-CHECKLIST.md) §2).
- Supprimer `recup-reference.yml` (workflow ponctuel avec droits d'écriture).
- Décider d'une sonde externe sur `ses_health` ([MONITORING](MONITORING.md) §1).
