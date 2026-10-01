# Phase 3 — dashboard Speed Express Shipping

Date : 30 septembre 2026. Branche : `arena/01a0f433-speed-express-site`.

## État de livraison

**Implémentation locale livrée ; activation des agrégats en production bloquée par la vérification/application autorisée de la migration.** Aucun déploiement ni changement de base réelle effectué. La phase 4 n'est pas commencée. Les chiffres réels n'ont pas été comparés à Supabase : ne pas considérer la phase comme validée en production.

## Changements

- Coque responsive noire/blanche/rouge, logo Speed Express existant, navigation verticale, vue d'ensemble par défaut, menu mobile, identité et langue.
- Colis, factures, clients/rôles, réglages et dialogues existants conservés. Liens suivi, espace client, accueil et aide conservés. Aucun faux module Messages/Rapports.
- Navigation par fragments, précédent/suivant navigateur, touches fléchées/Home/End, menu mobile fermé avec Échap et retour du focus.
- Coque accessible à un employé autorisé à lire au moins un domaine, et non uniquement aux employés lisant les colis. Les clients restent redirigés vers leur espace.
- KPI de stock : total colis et en cours par transport. Aucune comparaison historique artificielle sur les stocks.
- Courbe des enregistrements sur période, tableau accessible des valeurs, répartition des statuts, dix premières destinations et nouveaux clients, via agrégats côté PostgreSQL.
- Six périodes : jour, heures, semaine ISO, mois, année et personnalisé. Bornes interprétées côté serveur en `America/Santo_Domingo`, fin exclue, maximum 366 jours, futur refusé et période courante plafonnée à la lecture serveur.
- Transport, pays et statut actuel affectent les agrégats colis sur période, pas les KPI toutes dates ni les créations de comptes clients. Les filtres de liste récente sont indépendants et clairement libellés.
- Liste récente paginée 20 par 20 : recherche numéro/expéditeur/destinataire, statut et tris récence/numéro/poids, ordre secondaire stable par ID. Projection ciblée sans jeton QR ni informations de compte client. Les fiches restent accessibles via leur contrôleur existant.
- Activité : huit derniers événements réels de l'historique, tri stable, références colis jointes ; pas de fausse activité de paiement.
- Skeletons, vide, erreur avec Réessayer, migration manquante et permissions refusées distincts. Aucune substitution de panne par zéro. Les réponses obsolètes ne remplacent pas les résultats récents.
- Réutilisation du Realtime existant et rafraîchissement temporisé ; aucun abonnement parallèle. Actualisation manuelle et au retour sur la page. Les clients restent rafraîchis manuellement/au retour, sans modification de publication Realtime.
- Mode demo/off explicitement refusé par les nouveaux widgets. Pas de données ni signature persistées localement.
- Corrections ciblées des filtres API : `admin.factures({colis_id})` applique maintenant le filtre ; `admin.colis` ne demande plus `colis_id` inexistant dans sa vue.
- Traductions FR/EN/ES/HT ajoutées au mécanisme existant. La couverture visuelle dans chacune des langues reste à compléter.
- Style historique du dashboard neutralisé par renommage de ses sélecteurs dans la page et le générateur, pour éviter qu'il écrase la nouvelle coque. Les autres pages ne sont pas régénérées.

## Migration proposée : `outils/supabase-dashboard.sql`

**Non appliquée dans Supabase. Ne pas l'exécuter en production sans contrôler d'abord le schéma réellement installé.**

### Objets et impact

1. `dashboard_periode_ses(text,date,timestamp,timestamp)` : normalise les bornes et le grain temporel, sans données métier retournées.
2. `dashboard_colis_ses(text,date,timestamp,timestamp,text,text,text)` : stock, série, comparaison et destinations. Exige `colis.lire`.
3. `dashboard_clients_ses(text,date,timestamp,timestamp)` : nouveaux comptes `role='client'` et comparaison. Exige `clients.lire`.
4. Remplacement compatible de la signature `statistiques_ses()` : passage à `SECURITY INVOKER`, contrôle des domaines avant lecture, agrégats interdits à `null`, soldes/trop-perçus par devise calculés avec montants partiels. Le vieux montant scalaire `montant_impaye` est délibérément `null` pour ne pas mélanger les devises ; l'ancien frontend n'affichera donc plus ce détail monétaire. Le nouveau dashboard n'appelle plus cette RPC.

Toutes ces fonctions sont `STABLE`, `SECURITY INVOKER`, `search_path=''`, avec noms de tables qualifiés. EXECUTE retiré à PUBLIC/anon et accordé à authenticated ; contrôles de domaine dans chaque fonction métier. Les RLS des tables continuent de s'appliquer, y compris un éventuel périmètre plus restrictif déjà installé.

Aucune nouvelle table, relation, policy, index, extension ou donnée. Aucune modification des factures/colis. Migration transactionnelle ; échec = rollback. Pas de DROP CASCADE ni de modification des anciennes migrations.

### Avant application

- Confirmer tables/champs du dépôt et présence de `a_droit`, RLS, privilèges de tables et de fonctions, rôles `authenticated`/`anon`.
- Vérifier les droits avec plusieurs comptes autorisés dans un environnement de staging.
- Mesurer les requêtes avec EXPLAIN sur le volume réel. Les index candidats de l'architecture ne sont pas ajoutés aveuglément : le regroupement de toutes dates nécessite de toute façon une agrégation de l'ensemble visible.
- Appliquer en staging, comparer chaque count/série/destination aux sources autorisées, puis seulement autoriser la production. Pas de service_role dans le navigateur.
- Ne pas revenir à l'ancienne version permissive de `statistiques_ses` en cas de retour arrière frontend.

## Ajustements / éléments explicitement non livrés

- **Finance :** carte informative uniquement. Pas de fausse courbe de chiffre d'affaires, de profit ou d'encaissements. Le regroupement de factures non transactionnel et la cohérence des montants restent à traiter séparément avant l'activation d'indicateurs financiers. Les anciennes factures restent utilisables ; aucune correction automatique de leur contenu.
- **Comparaisons :** l'implémentation utilise un intervalle immédiatement précédent de même durée effective, avec les deux bornes visibles. Elle ne prétend pas comparer au même mois calendaire de l'année précédente. Ajustement par rapport à la proposition calendaire de phase 2, choisi pour éviter les ambiguïtés des mois incomplets ; à confirmer avec le propriétaire.
- **Limite de période :** 366 jours maximum pour garder des agrégations bornées. Le champ Heures exige début/fin sur une même journée locale ; un intervalle nocturne utilise Personnalisée.
- **Navigation intermédiaire :** sidebar de 190 px à 1024 px plutôt que rail d'icônes 72 px, afin de garder les libellés métier explicites sans pack d'icônes supplémentaire.
- Pas de recherche client enrichie dans le nouveau tableau récent : expéditeur/destinataire/référence réels seulement, évitant les données de comptes non autorisées. La recherche client existante reste dans la gestion Colis.
- Pas encore de rapports, archives, signature, PDF, nouveaux droits rapports, tables `rapports` ou `rapport_lignes` : phases suivantes.

## Tests réalisés

### 1. Statique / assemblage

`python3 outils/tests/dashboard-static.py`

- Syntaxe JavaScript/Python, IDs uniques du dashboard, liens/ressources locaux.
- Gabarit présent à l'identique dans la page servie.
- Assemblage du générateur testé **en mémoire**, sans régénérer les autres pages.
- Corps/feuille/module du dashboard présents dans la sortie du générateur, clés littérales de traduction présentes.
- `git diff --check` sans erreur.

### 2. Contrats API en mémoire

`node outils/tests/dashboard-api.cjs`

Projections explicites, filtres envoyés à la source, pagination 40–59 pour page 3, tri sur liste blanche + ID, réponse vide, correction `colis_id` factures, absence de `colis_id` sur colis, domaines séparés, RPC absente et permission refusée. Aucun appel réseau ni donnée métier générée.

### 3. SQL isolé

`SES_TEST_DEPS=/chemin/dependances node outils/tests/dashboard-sql.cjs`

PostgreSQL-WASM (PGlite) avec schéma minimal **vide**, rôles/policies techniques : migration exécutée deux fois, agrégats vides, jour/heures/semaine/mois/année/personnalisé, jour bissextile, bornes UTC, mauvais filtres/périodes refusés, droits clients/colis indépendants, anon refusé, aucune fonction SECURITY DEFINER parmi les quatre. Ce n'est pas une introspection ni un test Supabase réel ; les données non vides, les volumes et les policies réellement déployées ne sont pas validés par ce test.

### 4. Navigateur Chromium isolé

`AWS_EXECUTION_ENV=AWS_Lambda_nodejs22.x SES_TEST_DEPS=/chemin/dependances node outils/tests/dashboard-browser.mjs`

Serveur local : `python3 -m http.server 8000 --bind 0.0.0.0` (à maintenir séparément).

Le test intercepte la couche API uniquement dans son navigateur, bloque le réseau externe et renvoie des réponses vides/erreurs. **Aucun compte d'essai ajouté à l'application ou à Supabase ; aucune capture présentée comme données réelles.**

Réussis :
- 320, 360, 390, 414, 768, 1024, 1280, 1440 px : pas de débordement de page pour la vue d'ensemble et les cinq panneaux de gestion testés avec listes vides.
- États vide, réseau en erreur, migration absente ; zéro KPI inventé lors d'une erreur.
- Soumission des six périodes vers la couche API, navigateur configuré en `Asia/Tokyo`.
- Menu mobile, Échap, focus restitué, navigation d'onglets et précédent/suivant navigateur.
- Employé facturation uniquement : ni requête d'agrégat colis/client, ni panneau interdit visible.
- Employé colis uniquement : pas de widget client/finance, pas de requête d'agrégat client.
- Mode demo : message Base réelle requise ; pas de cartes chiffrées.
- Aucune exception JavaScript pendant ces scénarios.

Outils de test installés **hors du dépôt**, pas de dépendance runtime ajoutée au site : `playwright@1.63.0`, `@sparticuz/chromium@153.0.0`, `@electric-sql/pglite@0.5.8`. Le téléchargement Chromium standard et apt ont échoué (réseau) ; le binaire et ses bibliothèques fournis par le paquet npm ont permis les tests isolés. Ces outils ne sont pas publiés avec le site.

## Vérifications encore nécessaires

- Supabase réel : migrations, RLS, valeurs non vides, poids, comptages exacts, filtres sur données existantes, permissions serveur avec comptes réels autorisés.
- Comparaison du graphique à des résultats SQL réels, perfs/EXPLAIN et Realtime authentifié.
- Recherche/pagination/tri et dialogues avec des colis réellement autorisés ; tests non destructifs avant toute mutation métier.
- Régression complète des paiements, regroupements, étiquettes et QR ; ces parcours n'ont pas été exercés sur production.
- Accents/traductions, grands textes/volumes, lecteurs d'écran, Safari/Firefox et appareils tactiles physiques.
- Signature/PDF/rapports et tests associés : non concernés par cette phase.

## Fichiers

Ajouts phase 3 :
- `assets/css/ses-dashboard.css`
- `assets/js/ses-dashboard.js`
- `outils/supabase-dashboard.sql`
- `outils/tests/dashboard-static.py`
- `outils/tests/dashboard-api.cjs`
- `outils/tests/dashboard-sql.cjs`
- `outils/tests/dashboard-browser.mjs`
- `outils/phase-3-dashboard.md`

Modifications :
- `tableau-de-bord.html`, `outils/espace/tableau-de-bord.html`
- `assets/js/ses-admin.js`, `assets/js/ses-api.js`, `assets/js/config.js`
- `assets/js/lang-dict-11.js`, `assets/js/lang-switcher.js`
- `outils/pages-espace.py`, `outils/mise-en-page.py`
- `README.md`

`outils/architecture-dashboard-rapports.md` était déjà ajouté à la phase 2 ; ce n'est pas une nouvelle modification applicative de phase 3.

## Arrêt

Aucun commit/push/déploiement déclenché pour cette phase. Modifications sauvegardées sur la branche de session. La phase 4 attend une validation explicite ; l'activation des agrégats attend séparément le contrôle de la base et l'autorisation d'application SQL.
