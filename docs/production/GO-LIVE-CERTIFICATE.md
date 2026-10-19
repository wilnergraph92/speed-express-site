# Certificat de mise en service — Speed Express Shipping

> **Verdict : NON CERTIFIÉE « plateforme opérationnelle » — statut BLOCKED.**
> Le socle (base, site, portail, tableau de bord, noyau logistique, sauvegardes) tient tous les essais réels qu'on a pu lui faire passer.
> Mais plusieurs parcours de bout en bout n'ont **jamais été exercés en production**, faute de comptes, de secrets ou d'appareils qui
> appartiennent au propriétaire :
> - paiements, notifications sortantes, applications mobiles publiées, application de bureau signée et matériel ;
> - recette connectée du portail et du tableau de bord.
>
> Un build qui réussit n'est pas une certification ; ces cases restent BLOCKED tant qu'un essai réel ne les a pas passées.

| | |
|---|---|
| Date du relevé | 19 octobre 2026, 17 h 40 – 18 h 05 UTC |
| Version du site en ligne | **v63** (`?v=63`, vérifié sur la page publiée) |
| Commit déployé | **`dd60e8f56095f9f67a0b0afdf773fca05cb5c472`** (fusion de #49, qui contient le correctif #48), déploiement GitHub Pages du 19/10/2026 17 h 51 UTC (exécution 39296539500, approuvée) |
| Version de migration | noyau **001 → 029** (journal `ses_meta.migration`), plus l'ancien schéma (`outils/supabase*.sql`, voir PRODUCTION-READINESS-AUDIT.md) ; base PostgreSQL 17.6 (Supabase, projet `speed-express-site`, ca-central-1) |
| Dernière sauvegarde vérifiée | `ses-20261019T174512Z.tar.gz.age` (122 tables, 636 lignes), prise et restaurée avant la migration 029 ; sauvegarde quotidienne du 19/10 13 h 22 UTC (succès, restauration vérifiée) |
| Application client / Opérations | 1.0.0 dans `App_SES` — **aucune construction de production publiée** |
| Application de bureau | constructions d'essai **non signées** Windows et macOS du 14/10/2026 (pages v60) — aucune version signée |
| Préparé par | Claude (agent de développement), à partir des essais ci-dessous |
| **Responsable de validation** | **le propriétaire** — à signer en bas, après la recette du §4. Rien n'est validé tant que ce n'est pas signé. |

Légende : **PASS** = éprouvé par un essai réel (production quand c'est écrit, sinon réplique PostgreSQL ou essai automatique) ;
**FAIL** = éprouvé et en défaut ; **BLOCKED** = impossible à éprouver aujourd'hui, avec la raison et qui peut le débloquer.

## 1. Résultats

### 1. Base de données — **PASS**

| Point | Verdict | Preuve |
|---|---|---|
| Sauvegarde confirmée | PASS | « Sauvegarde quotidienne » réussie chaque jour du 14 au 19/10 ; contrôle `backup_age_hours` = 4,5 h (OK) |
| Restauration testée | PASS | chaque sauvegarde est restaurée dans une base vide et jetable puis validée (contrôle `restore_check_age_days` = 0,2 j) ; idem avant chaque étape de migration |
| Migration vérifiée | PASS | 001 → 029 au journal ; migration 029 passée par l'outil, contrôles après étape : santé ok, 0 incohérence du workflow, 223 fonctions `lg` |
| Réconciliation = 0 anomalie | PASS | `migration_report()` : prêt, **0 écart inexpliqué** ; recopie allumée, 1 440 traitements planifiés réussis / 0 échec en 24 h |
| RLS validé | PASS | sonde anonyme réelle en production : 8 tables (`clients`, `colis`, `colis_historique`, `factures`, `prealertes`, `appareils`, `matricules_attribues`, `ses_signal`) et 2 vues refusées (`42501`) ; aucune table de `public` sans RLS ; aucun schéma du noyau ouvert aux visiteurs ; 105 tables du noyau sans politique **par choix** (lues seulement par les fonctions qui vérifient les droits) |
| Permissions validées | PASS | `roles-sql.cjs`, `securite-catalogue.py` (CI) ; 8 fonctions exécutables sans compte, toutes justifiées (§11) |

### 2. Site web — **PASS (avec réserves)**

| Point | Verdict | Preuve |
|---|---|---|
| Toutes les pages HTTP 200 | PASS | les 28 pages + `robots.txt`, `sitemap.xml`, manifeste : 31 × 200 en production |
| SEO | PASS | suite `seo` (CI) |
| Sitemap | PASS | 21 adresses publiques ; pages de compte exclues |
| Robots | PASS | `Allow: /`, `Disallow: /outils/`, lien vers le sitemap |
| HTTPS | PASS | HTTP → 301 vers HTTPS ; `strict-transport-security: max-age=31556952` |
| Domaine | PASS (réserve) | `wilnergraph92.github.io/speed-express-site` : **pas de domaine propre**, et le même origine que Goship (stockage local partagé ; la clé de session est reconstruite exactement, voir CLAUDE.md) |
| CSP | PASS (réserve) | CSP et politique de référent en `<meta>` sur chaque page ; anti-cadre éprouvé en production (une page mise dans un cadre refuse de s'y laisser lire) ; **GitHub Pages ne permet ni `X-Frame-Options`, ni `X-Content-Type-Options`, ni `frame-ancestors`** |
| Performance | PASS (réserve) | accueil en production : premier affichage et plus grand élément à 760 ms, chargé à 834 ms, 31 ressources, 909 Ko ; **décalage de mise en page (CLS) 0,124**, au-dessus du seuil « bon » de 0,1 ; une ressource externe (Google Fonts) |
| Accessibilité | PASS | suites `accessibilite.py`, contrastes, essais navigateur (CI) ; tableau de bord à 375 px sans débordement |

### 3. Portail client — **BLOCKED**

| Point | Verdict | Preuve / raison |
|---|---|---|
| Inscription | BLOCKED | 4 comptes réels confirmés en production, mais aucune inscription faite pendant ce relevé (l'agent ne crée pas de compte en production) ; **SMTP non branché** : les e-mails de confirmation partent par l'expéditeur limité de Supabase |
| Connexion | BLOCKED | même raison ; parcours éprouvé sur la réplique et dans les essais de l'application |
| Mot de passe oublié | BLOCKED | dépend du SMTP ; le crochet « Send Email Hook » (4 langues) est un modèle non déployé |
| Suivi | PASS (partiel) | production : `suivre_colis` répond `null` à un numéro inexistant, à un jeton faux ou vide, à une injection ; le parcours positif (vrai numéro + jeton) est à faire au §4 |
| Factures | BLOCKED | recette connectée ; facturation en mode « ancien schéma » (`finance_setting.mode = legacy`) |
| Paiement | BLOCKED | aucun fournisseur actif (voir 8) : paiement à l'agence seulement |
| Notifications | BLOCKED | voir 9 |

### 4. Tableau de bord (équipe) — **BLOCKED (recette en production)**

RBAC, clients, colis, scanner, entrepôts, expéditions, douane, livraisons, finance, rapports et audit sont **PASS sur la réplique de la production** : essais PostgreSQL, rôles sur la grille complète, contrats des écrans sur les réponses réelles. Ce sont `logistique-*-essai.py`, `roles-sql.cjs`, `tableau-contrat.cjs` (676 vérifications) et `analytique-contrat.cjs` (191).

En production, ils n'ont **pas été exercés par un compte connecté**. Le défaut #48 (boutons d'action inactifs jusqu'à la v63, 7 erreurs remontées par les navigateurs du 14 au 19/10) montre que cette recette est nécessaire. Audit : journal en ajout seul en place (4 entrées, la dernière le 14/10).

### 5. Application mobile client — **BLOCKED**

| Point | Verdict | Preuve / raison |
|---|---|---|
| Android, construction de production | BLOCKED | aucune construction EAS de production (compte Expo, signature et Play Console du propriétaire ; test fermé de 12 testeurs × 14 jours si compte récent) |
| iOS, construction de production | BLOCKED | compte Apple Developer, App Store Connect |
| Notifications | BLOCKED | 0 téléphone enregistré en production ; travailleur d'envoi non installé |
| Liens profonds | PASS (essai) | `speedexpress://colis/<numéro>` : 27 vérifications (`npm run essai`) |
| Temps réel | PASS (essai) | 7 vérifications ; publication `supabase_realtime` en production : `colis`, `colis_historique`, `factures`, `ses_signal` |

### 6. Application mobile Opérations — **BLOCKED**

Chauffeur, entrepôt, livraison, scanner, GPS au geste seulement, preuve de livraison et file hors connexion chiffrée : **PASS en essai** (`npm run essai` : terrain 72, Opérations 31, contrat 77). Aucune construction, aucun appareil réel.

### 7. Application de bureau — **BLOCKED**

Constructions d'essai Windows et macOS réussies (workflow `bureau.yml`, 14/10), mais **non signées**, et avec des pages anciennes (v60). Il manque les certificats Apple Developer ID et Windows, ainsi que la clé des mises à jour. Scanner USB, imprimante thermique, étiquette ZPL et PDF ne sont éprouvés qu'en essai (`bureau-contrat.cjs`, `poste-contrat.cjs`) ; aucun matériel réel (`BUREAU.md` §7).

### 8. Paiements — **BLOCKED**

Aucun fournisseur n'est configuré en production : `CARD`, `AZUL`, `MONCASH` et `NATCASH` sont tous **inactifs**, en environnement `test`, sans fonction serveur déployée ni secret. Il n'y a donc **rien à tester**, et aucun montant n'a été engagé. Le chemin d'un webhook est éprouvé en essai (`paiements-webhook`, 23 : signature HMAC, idempotence, refus de ce qui n'est pas vérifié).

### 9. Notifications — **BLOCKED**

En base, les canaux e-mail (Brevo) et push (Expo) sont **allumés**, WhatsApp **éteint**. Le travailleur d'envoi n'est pas installé (secrets du propriétaire) : aucune notification n'a jamais été envoyée. Les essais passent : travailleur 60, fonctions serveur 86, centre de notifications 63.

### 10. Reprise après sinistre — **PASS (base) / BLOCKED (exercice complet)**

- **PASS** : restauration complète de la base (schémas de l'application, du noyau et tables de comptes) dans une base vide, validée chaque jour et avant chaque migration. Restauration de bout en bout éprouvée par `migration-essai.py` (93) et `sauvegarde-essai.py`.
- **BLOCKED** : l'exercice réel, qui demande d'agir dans le compte du propriétaire et n'a jamais été fait. Il consiste à créer un nouveau projet Supabase, restaurer, régler l'authentification, basculer `config.js` et **mesurer le délai de remise en service** (objectif 4 h). Délai de perte maximale (RPO) : 24 h.

### 11. Sécurité (dernier audit) — **PASS (avec réserves)**

| Point | Verdict | Preuve |
|---|---|---|
| RLS | PASS | §1 ; conseiller de sécurité Supabase : 105 « RLS sans politique » (choix documenté, schéma fermé) |
| Authentification | **réserve** | conseiller Supabase : **protection contre les mots de passe compromis désactivée** (réglage Auth, geste du propriétaire) |
| RPC | PASS | fonctions exécutables sans compte : `ses_health` (sonde), `suivre_colis` (exige numéro et jeton), `a_droit` et `est_admin` (rendent « faux » sans compte), `facturer_colis` et `prevenir_client` (fonctions de déclencheur, non appelables), `prefixe_matricule` et `texte_notification` (texte, sans privilège) ; 232 fonctions `SECURITY DEFINER` pour les comptes connectés, chacune vérifie le droit en base |
| Secrets | PASS | suites `secrets` (fichiers et historique Git) ; aucun secret dans les workflows publics ; clé publique seule dans `config.js` |
| En-têtes | PASS (réserve) | §2 (limites de GitHub Pages) |
| Suivi public | PASS | jeton exigé, sondes négatives en production |
| Limitation de débit | PASS | 7 déclencheurs en production ; essai de charge : un employé au-delà de 1 200 scans en 10 min est refusé (`LG007`) |
| Audit | PASS | journal d'audit en ajout seul ; erreurs des navigateurs remontées et nettoyées (7, toutes le défaut #48) |
| Conseiller Supabase | réserve | type `regproc` dans `logistics.event_subscriber.handler` : gêne un futur `pg_upgrade` (pas la sécurité) |

### 12. Essai de charge — **PASS (base) / BLOCKED (chaîne Supabase)**

Essai `outils/tests/charge-essai.py`, sur une réplique PostgreSQL 16 locale portant les étapes 001 à 029, avec les vraies fonctions, droits et déclencheurs. Les utilisateurs simulés n'ont aucun temps de pause, ce qui est bien plus dur que de vrais utilisateurs. Chacun fait 60 % de suivis publics, 30 % de scans d'entrepôt (1 000 employés distincts) et 10 % de lectures du portail.

| Utilisateurs simultanés | Transactions/s | Latence moyenne | Échecs | Scans écrits |
|---|---|---|---|---|
| 100 | 4 450 | 22 ms | 0 | 26 866 |
| 500 | 2 470 | 202 ms | 0 | 14 347 |
| 1 000 | 1 593 | 628 ms | 0 | 8 475 |

Aucun doublon de scan, aucun interblocage, aucune limitation de débit déclenchée à tort ; santé et rattrapage intacts après la charge.

**BLOCKED** : la même charge à travers Supabase n'a pas été mesurée. Elle couvre PostgREST et son pool de connexions (l'offre gratuite en limite fortement le nombre), la diffusion **temps réel** et l'envoi des **notifications**. Elle ne se fait **pas en production** (vrais clients, offre gratuite) : il faut une préproduction ou l'accord du propriétaire. En production, 20 sondes de santé simultanées répondent en 0,4 s.

### 13. Documentation — PASS

Ce certificat ; procédures dans `docs/production/` (ROLLBACK, RUNBOOK, MONITORING, BACKUP-AND-RECOVERY, INCIDENT-RESPONSE, BUREAU).

## 2. Incidents connus

| Date | Incident | État |
|---|---|---|
| 14 → 19/10/2026 | Boutons d'action du centre de commande inactifs (`ses-centre-vues.js` s'arrêtait au chargement ; 7 erreurs remontées) | **corrigé** par #48, en ligne en v63 ; contrat renforcé |
| 14/10/2026 | Une migration en échec (exécution 07 h 29), reprise | résolu |
| 19/10/2026 | Après 027 : 1 écart de rattrapage (client devenu employé) | **corrigé** par l'étape 028 |
| 07/10/2026 | Alerte analytique ouverte : délai de transit impossible ce jour-là (un colis livré sans réception connue) | **ouverte** : donnée historique, à lire et acquitter par la direction |

## 3. Risques résiduels

| Gravité | Risque | Qui | Remède |
|---|---|---|---|
| Élevée | Aucune notification sortante (e-mail, push, WhatsApp) | propriétaire | installer le travailleur (`NOTIFICATIONS.md` §11), brancher le SMTP Brevo dans Supabase Auth |
| Élevée | E-mails de compte (confirmation, mot de passe oublié) par l'expéditeur limité de Supabase | propriétaire | SMTP + crochet « Send Email Hook » |
| Élevée | Aucun paiement en ligne | propriétaire | choisir et configurer un fournisseur, puis la bascule financière (030) |
| Élevée | Parcours connectés jamais recettés en production | propriétaire + direction | recette du §4 |
| Moyenne | Protection contre les mots de passe compromis désactivée | propriétaire | Supabase › Authentication |
| Moyenne | Applications mobiles et de bureau non publiées, non signées | propriétaire | `App_SES/docs/PUBLICATION.md`, `BUREAU.md` |
| Moyenne | Reprise complète jamais exercée ; RPO 24 h | propriétaire | exercice trimestriel ; PITR (offre payante) pour descendre sous 24 h |
| Moyenne | Charge à travers Supabase non mesurée ; offre gratuite (connexions, 500 Mo — 22 Mo aujourd'hui) | propriétaire | préproduction, puis offre adaptée avant d'ouvrir largement |
| Faible | En-têtes de sécurité impossibles sur GitHub Pages ; origine partagée avec Goship | propriétaire | domaine propre derrière un hébergeur qui pose les en-têtes (`_headers` est prêt) |
| Faible | CLS 0,124 sur l'accueil | développement | réserver la place des images et de la police |
| Faible | Champ `regproc` (mise à niveau majeure de PostgreSQL) | développement | le convertir en texte avant un `pg_upgrade` |

## 4. Recette à faire par le propriétaire (débloque les §3 à §9)

1. **Portail**
   - Créer un compte client de test, recevoir la confirmation, se connecter.
   - Faire « mot de passe oublié ».
   - Suivre un vrai colis (numéro et jeton de l'étiquette).
   - Voir ses factures.
2. **Tableau de bord** (comptes administrateur, gérant, employé)
   - Les modules s'ouvrent selon le rôle.
   - Créer un colis ; le scanner (réception, vérification, rangement).
   - Expédition, douane, livraison, preuve.
   - Facture.
   - Analytique : afficher, exporter en CSV et en PDF, acquitter l'alerte du 07/10.
   - Santé : tout au vert.
3. **Notifications** : installer le travailleur, puis vérifier un e-mail et un push reçus (et WhatsApp si allumé).
4. **Paiements** : pour chaque fournisseur activé, un paiement en mode **test**, puis un montant minimal en **live**, puis un remboursement.
5. **Applications** : constructions de production Android et iOS ; essais sur appareil (`App_SES/docs/ESSAIS-APPAREILS.md`).
6. **Bureau** : version signée ; scanner USB, imprimante thermique 4 × 6, A4 et PDF (`BUREAU.md` §7).
7. **Reprise** : exercice complet, avec le délai mesuré et noté ici.

Chaque point passé se note ici, avec la date et la personne ; un point en défaut s'écrit FAIL avec son incident.

## 5. Plan de retour en arrière

Détail : [ROLLBACK.md](ROLLBACK.md). Dans l'ordre du moins au plus lourd :

1. **Site seul** (pages, scripts) : relancer « Mettre le site en ligne » (`workflow_dispatch`) sur un commit connu, puis l'approuver. Version précédente : `154febf` (v61, avec le défaut #48 ; préférer un correctif en avant).
2. **Interrupteurs** (`config.js`, par une PR) : `portailNoyau: false` remet le portail sur l'ancien schéma, `centreNoyau: false` masque le centre de commande. **Recopie** : `interrupteurs.py recopie-eteindre`.
3. **Analytique (029)** : `interrupteurs.py analytique-deplanifier` retire les deux tâches pg_cron ; les chiffres peuvent rester. Rejouer 012 rétablit le calcul de 012.
4. **Base** : restaurer `ses-20261019T174512Z.tar.gz.age` (sauvegarde vérifiée d'avant 029) **seulement** en cas de dommage aux données. Tout ce qui a été écrit depuis serait perdu : préférer une étape correctrice, comme pour 028.

## 6. Version exacte déployée

```
site        https://wilnergraph92.github.io/speed-express-site   v63
commit      dd60e8f56095f9f67a0b0afdf773fca05cb5c472   (main, 19/10/2026 ; #49 + #48)
noyau       001 → 029   (ses_meta.migration)
base        Supabase speed-express-site (ltbqqchtyzlyakcsxxis), PostgreSQL 17.6.1.166
planifié    ses-recopie-noyau (* * * * *), ses-analytique (20 5 * * *), ses-analytique-veille (50 * * * *)
sauvegarde  ses-20261019T174512Z.tar.gz.age (avant 029, vérifiée)
mobile      App_SES 1.0.0 — non publiée
bureau      Speed Express Operations — constructions d'essai non signées (14/10/2026)
```

## 7. Validation

| Rôle | Nom | Date | Verdict | Signature |
|---|---|---|---|---|
| Responsable de validation (propriétaire) | | | | |
