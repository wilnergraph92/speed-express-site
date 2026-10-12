# Liste de contrôle de sécurité avant mise en production

> Phase 1 « sécuriser la production », 8 octobre 2026. À dérouler **avant toute migration métier** (noyau 001 → 013, paiements,
> notifications). Elle complète [GO-LIVE-CHECKLIST.md](GO-LIVE-CHECKLIST.md) (l'ordre des migrations) sans la remplacer.
> Chaque ligne dit **ce qui est vérifié**, **par quoi**, et **qui** fait ce qui reste. « ✅ » = vérifié le 8 octobre (test ou mesure en
> lecture seule) ; « ⬜ » = geste à faire ; « 🟡 » = préparé, en attente d'un geste.

## 1. Chaîne de publication (GitHub)

| | Contrôle | État | Preuve / geste |
|---|---|---|---|
| ✅ | `main` protégée : PR obligatoire, CI `valider` verte et à jour, aussi pour l'administrateur ; ni envoi forcé ni suppression | réglé le 8/10 | `gh api …/branches/main/protection` |
| ✅ | Déploiement en production **approuvé par le propriétaire** (environnement `github-pages`, relecteur obligatoire, branche `main` seule) | réglé le 8/10 | *Settings › Environments* |
| ✅ | Workflows en lecture seule par défaut ; Actions ne peut pas approuver de PR ; aucun `pull_request_target` ; permissions déclarées partout | vérifié | `secrets-statique.py` |
| ✅ | Workflow ponctuel `recup-reference.yml` (droit d'écriture) retiré | dans cette PR | — |
| ✅ | Alertes Dependabot actives ; secret scanning et push protection actifs | réglé le 8/10 | *Settings › Code security* |
| ✅ | Chaque PR classe ses fichiers (migrations / site / préproduction / outillage / documentation) et signale une migration | CI | `qualite.yml` |
| ✅ | Régénération des 28 pages, de `_headers` et du plan du site vérifiée ; aucun fichier modifié par la génération ni par les essais | CI | `qualite.yml` |
| ⬜ | **Double authentification** du compte GitHub `wilnergraph92` | propriétaire | *Settings › Password and authentication* |
| ⬜ | Revoir *Settings › Applications* et *Integrations* : l'application `arena-ai-coding-agent` a un droit d'écriture ; la garder seulement si elle sert encore (elle ne peut plus écrire sur `main`) | propriétaire | — |
| ⬜ | Trier la PR n° 17 et les 18 branches `arena/…` dormantes (en retard de 12 à 49 commits) | propriétaire | fermer sans fusionner si plus utiles |

## 2. Secrets

| | Contrôle | État | Preuve |
|---|---|---|---|
| ✅ | Aucune clé secrète Supabase (`sb_secret_`, JWT `service_role`), de paiement (Stripe), WhatsApp/Meta, SMTP (Brevo), GitHub, Expo, Google, AWS ; aucune clé privée ; aucune chaîne de connexion avec mot de passe — **dans les fichiers et dans tout l'historique** | 4 900+ contrôles, contre-épreuve de 11 faux secrets | `secrets-statique.py` |
| ✅ | `config.js` ne porte que la clé **publique** `sb_publishable_` | vérifié | idem |
| ✅ | Aucun workflow du dépôt public ne lit de secret d'Actions (seul le jeton fourni par GitHub) | vérifié | idem |
| ✅ | `.gitignore` protège `.env*`, clés, sauvegardes, configuration locale de préproduction | vérifié | `sauvegarde-statique.py` |
| — | Règle : `service_role`, clé secrète, chaîne de connexion, clés de paiement, WhatsApp, SMTP vivent **uniquement** dans Supabase ou dans des secrets de dépôts **privés** ; jamais ici, jamais dans un message | permanente | `CLAUDE.md`, `SECURITY.md` |

## 3. Base de données

| | Contrôle | État | Preuve |
|---|---|---|---|
| ✅ | Sécurité par ligne (RLS) sur **chaque** table du schéma public | installation neuve et réplique de la production | `securite-catalogue.py` |
| ✅ | Aucun droit d'aucune sorte d'un visiteur sur une table ou une vue | idem + **mesuré en production** (9 tables et vues refusées) | `securite-catalogue.py`, sonde |
| ✅ | Chaque vue obéit aux règles de celui qui la lit (`security_invoker`) | vérifié | idem |
| ✅ | Chaque fonction `SECURITY DEFINER` a un `search_path` figé | vérifié | idem |
| ✅ | Un client ne modifie ni rôle, ni droits, ni code, ni e-mail, ni prix, ni statut, ni facture | 79 + 498 contrôles | `securite-sql.py`, `roles-sql.cjs` |
| ✅ | Les droits par défaut de Supabase (tout objet nouveau ouvert à `anon` et `authenticated`) sont **reproduits** dans les essais : une migration qui oublie de refermer un objet échoue en CI | nouveau | `_pgjetable.SUPABASE_DEFAUTS` |
| ✅ | Migrations : rien de destructif, tout rejouable, chacune rejouée par l'essai PostgreSQL, en-tête « speed-express-site » | 9 migrations + 13 étapes | `migrations-garde-fou.py`, `schema-rejouable.py` |
| 🟡 | **En production, quatre fonctions internes restent appelables par un visiteur** (`est_admin`, `a_droit`, `texte_notification`, `prefixe_matricule` — inoffensives, mais contraires à la règle « une seule fonction publique ») ; `TRUNCATE` / `TRIGGER` / `REFERENCES` ouverts aux comptes connectés ; la vue `factures_details` sans `groupee` ; **R18** (le déclencheur de notification casserait le changement de statut d'un client dont le téléphone s'enregistre) | mesuré le 7-8/10 (lecture seule) ; remède **éprouvé sur une réplique** de la production | `securite-catalogue.py` |
| ⬜ | **Coller le remède**, dans cet ordre, après une sauvegarde « avant migration » et d'abord en préproduction : `supabase-maj-facture-groupee.sql`, `supabase-maj.sql`, `supabase-maj-securite.sql` (tous rejouables, aucune donnée changée — prouvé) ; puis la requête de contrôle §3.1 | propriétaire | — |
| ⬜ | Avant de coller, une lecture : `select email, role, code, matricule from public.clients where role <> 'client';` — si un compte d'équipe porte encore un code `SES-#####` sans colis ni facture, la règle 8b de `supabase-maj.sql` (« l'équipe n'est pas la clientèle », déjà voulue) le lui retire. Rien d'autre ne change. | propriétaire | — |
| ⬜ | Ensuite seulement : brancher Firebase (notifications Android) | propriétaire | R18 doit être corrigé avant |

### 3.1 Requête de contrôle après le remède (SQL Editor, projet `speed-express-site`)

```sql
select
  has_function_privilege('anon', 'public.est_admin()', 'execute')                     as est_admin_ouverte,        -- false
  has_function_privilege('anon', 'public.prefixe_matricule(text)', 'execute')         as prefixe_ouverte,          -- false
  to_regprocedure('public.enregistrer_appareil(text,text)') is not null               as enregistrement_present,   -- true
  position('extensions.net.' in pg_get_functiondef('public.prevenir_client()'::regprocedure)) = 0 as r18_corrige,  -- true
  exists (select 1 from pg_attribute where attrelid = 'public.factures_details'::regclass and attname = 'groupee') as vue_groupee, -- true
  has_table_privilege('authenticated', 'public.factures', 'truncate')                 as truncate_ouvert;          -- false
```

La sonde de surveillance (§6) passera alors d'« alerte » à « ok » toute seule.

## 4. Site publié

| | Contrôle | État | Preuve |
|---|---|---|---|
| ✅ | Politique de contenu `script-src 'self'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `connect-src` limité à Supabase | 28 pages | `securite-statique.py` (926) |
| ✅ | Protection anti-cadre : `frame-ancestors` impossible par balise sur GitHub Pages → protection de remplacement sur les pages de connexion | idem | idem |
| ✅ | `Referrer-Policy: strict-origin-when-cross-origin` (balise) | idem | idem |
| ✅ | `_headers` généré avec la même politique (prêt si l'hébergeur change ; GitHub Pages ne le lit pas) | idem | `mise-en-page.py` |
| ✅ | Fichiers de travail jamais publiés (`outils/`, `docs/`, `scripts/`, `.github/`…) | mesuré en production (404) | `publication.py` |
| — | Limite connue : GitHub Pages n'envoie ni CSP ni `X-Frame-Options` en en-tête HTTP ; seul un hébergeur avec en-têtes (Cloudflare Pages, Netlify) lèverait cette limite — décision à part, avec ADR | accepté | — |

## 5. Authentification (réglages Supabase : lisibles seulement par vous)

Mesuré le 8/10 (réglages publics) : inscription ouverte, **confirmation d'e-mail obligatoire**, fournisseur e-mail seul, ni SMS, ni
SAML, ni passkeys. Le reste se règle dans *Supabase › speed-express-site › Authentication* (détail et raisons :
[AUTH-HARDENING.md](../security/AUTH-HARDENING.md) §3) :

| | Réglage | Valeur |
|---|---|---|
| ⬜ | **Site URL** | `https://wilnergraph92.github.io/speed-express-site/` |
| ⬜ | **Redirect URLs** | seulement `…/espace-client.html` et `…/nouveau-mot-de-passe.html` de la production ; **aucun joker** ; pas de `localhost` (il appartient au projet de préproduction) |
| ⬜ | **SMTP** Brevo, expéditeur du domaine ; un e-mail de test reçu hors indésirables | — |
| ⬜ | **Mot de passe** : minimum 8 (aligné sur le site) ; protection contre les mots de passe divulgués si l'offre le permet | — |
| ⬜ | **Sessions** : jeton d'accès 3 600 s (défaut, ne pas allonger) ; détection et révocation des jetons de renouvellement rejoués **activée** ; délai d'inactivité et durée maximale de session si l'offre le permet (recommandé pour l'équipe : 12 h) | — |
| ⬜ | **Limites de débit** d'Auth : valeurs par défaut au minimum, jamais augmentées | — |
| ⬜ | **Data API** : schéma exposé `public` seulement ; jamais `logistics` | — |
| ⬜ | Double authentification (TOTP) des administrateurs : à activer côté Supabase ; l'écran du tableau de bord est un chantier distinct | décision |

Après chaque changement : parcours complet (inscription → e-mail → confirmation → connexion → mot de passe oublié).

## 6. Suivi public et limitation de débit

| | Contrôle | État |
|---|---|---|
| ✅ | Le suivi public ne rend ni nom, ni adresse, ni note ; numéros nouveaux à 10 chiffres au hasard (non devinables) | `securite-sql.py`, `numeros-colis.cjs` |
| 🟡 | Anciens numéros séquentiels acceptés **sans jeton**, sans limite de débit : décision A / B / C | [TRACKING-SECURITY.md](../security/TRACKING-SECURITY.md) |
| ✅ | Pré-alertes : 30 par client et par 24 h (base, `SE003`) | `prealertes-sql.cjs` |
| ✅ | Auth : limites de Supabase (voir §5) | réglage |
| 🟡 | Limitation des façades du noyau par déclencheurs (`LG007`) : prête dans 013, active à son installation | `logistique-exploitation-essai.py` |

## 7. Surveillance et alertes

| | Contrôle | État | Où |
|---|---|---|---|
| 🟡 | **Disponibilité** : sonde en lecture seule toutes les 15 min (site, Auth, base, aucune table lisible sans connexion, fonctions internes, santé du noyau) ; ticket `alerte-production` ouvert en panne, fermé au retour ; e-mail de GitHub | active **dès la fusion** de cette PR | `.github/workflows/surveillance.yml`, `surveillance.cjs` |
| ⬜ | Notifications GitHub du propriétaire : e-mail pour *Actions* (échecs) et pour les tickets du dépôt (*Watch › All activity* ou *Issues*) | propriétaire | *Settings › Notifications* |
| 🟡 | Erreurs du site (navigateurs) : remontées à la base pour les comptes connectés, page Santé | à l'installation de 013 | `ops.client_error` |
| 🟡 | Erreurs de la base, sauvegardes, notifications : quinze contrôles et page Santé | à l'installation de 013 | [MONITORING.md](MONITORING.md) |
| ⬜ | Erreurs de l'application mobile : aucun outil aujourd'hui ; un suivi d'erreurs (Sentry ou équivalent) demande un ADR | décision | — |
| — | Paiements : aucun paiement en ligne n'existe ; leur surveillance naîtra avec le prestataire (ADR) | sans objet | — |
| ⬜ | Supabase : alertes e-mail de l'offre (quota, base proche de 500 Mo en offre gratuite) | propriétaire | *Settings › Billing / Usage* |

## 8. Sauvegarde

Voir [BACKUP-AND-RECOVERY.md](BACKUP-AND-RECOVERY.md) : **⬜ non installée** (risque n° 1). Rien du §3 « remède » ni aucune migration
métier avant : dépôt privé, clé `age` (deux copies hors ligne), première sauvegarde `verification: complete`, premier exercice de
restauration chronométré.

## 9. Validation de la phase

| Date | Qui | Sauvegarde de référence | Préproduction créée | Remède collé et contrôlé | Notes |
|---|---|---|---|---|---|
| | | | | | |
