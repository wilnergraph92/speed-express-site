# Speed Express Shipping — Architecture du dashboard et des rapports

**Phase 2 — proposition soumise à validation**  
Date : 30 septembre 2026  
Base inspectée : `a80bd9d`  
Branche : `arena/01a0f433-speed-express-site`  
Fuseau confirmé par le propriétaire : **`America/Santo_Domingo`**.

Ce document définit l'architecture. Il ne constitue ni une implémentation, ni une migration appliquée, ni une validation sur les données de production. Seul ce document est ajouté pendant cette phase. Il est rangé dans `outils/`, dossier déjà exclu de la publication GitHub Pages.

## 1. Décisions et périmètre

- Conserver le site statique, Supabase, `SES_API`, `SES_UI`, les trois rôles et les fonctionnalités existantes.
- Modifier le dashboard équipe, pas réécrire le site ni l'espace client.
- Ajouter les rapports dans le dashboard existant, avec chargement différé du module et du moteur PDF.
- Employer exclusivement la configuration et les assets Speed Express déjà présents dans ce dépôt.
- Ne pas exécuter `convertir-export.py`. Les références historiques à un autre projet signalées en phase 1 ne sont ni des dépendances à réutiliser, ni une autorisation de connexion.
- Les deux images visibles dans le message utilisateur guident la composition et les proportions. Elles ne fournissent aucune donnée et leur marque/palette violette ne sont pas reprises. Les chemins annoncés pour les fichiers joints n'étaient pas accessibles dans le workspace lors de cette phase ; l'analyse visuelle repose sur les images affichées dans la conversation, sans copie de ces fichiers dans le site.
- Le schéma SQL du dépôt reste à comparer au schéma réellement déployé avant toute migration. Aucune session autorisée ni introspection de production n'a été obtenue en phase 1.
- Toutes les données du module proviennent du mode Supabase. En mode `demo` ou `off`, les nouveaux modules affichent « Base réelle requise » ; aucun générateur d'essai, aucun stockage local de rapport/signature et aucun repli silencieux vers des valeurs fictives.

## 2. Direction visuelle retenue

### 2.1 Correspondance avec les références

| Bloc de référence | Adaptation Speed Express |
|---|---|
| Sidebar sombre | Sidebar noire, logo officiel, sélection rouge |
| Header arrondi | Titre, recherche de colis, actualisation, langue et identité réelle |
| Groupe de quatre KPI | Total colis ; aérien, maritime et terrestre en cours |
| Recurring Revenue | Colis enregistrés pendant la période, courbe réelle |
| Shipment over time | Évolution de la facturation si autorisée et cohérente ; sinon espace réorganisé, sans graphe dupliqué |
| Profit statistics | Répartition réelle des cinq statuts autorisés |
| Customer Growth | Nouveaux clients ; évolution uniquement quand calculable |
| Carte des pays | Répartition réelle par pays/ville sous forme de barres et liste, sans géolocalisation inventée |
| Zone inférieure | Activité réelle, colis récents, accès aux rapports |

Il n'existe pas de coûts, de marge, de visites web ou de revenu récurrent dans les sources auditées : aucun widget correspondant n'est créé. Aucun avatar fictif, compteur de notifications ou message non lu décoratif.

### 2.2 Composition desktop

```text
┌──────────────────┬────────────────────────────────────────────────────┐
│ LOGO SPEED       │ Dashboard · recherche colis · langue · compte      │
│ EXPRESS          ├───────────────────────┬────────────────────────────┤
│                  │ Situation actuelle    │ Colis enregistrés          │
│ Dashboard        │ Total  | Aérien        │ Période + courbe réelle    │
│ Colis            │ Mer    | Route         │                            │
│ Suivi            ├───────────────────────┼────────────────────────────┤
│ Clients et rôles │ Destinations          │ Répartition des statuts    │
│ Facturation      │ enregistrées          │ Quantités + pourcentages   │
│ Rapports         ├───────────────────────┼────────────────────────────┤
│ Paramètres       │ Facturation*          │ Nouveaux clients*          │
│                  ├───────────────────────┴────────────────────────────┤
│ Mon espace       │ Colis récents · recherche · filtre · tri · pages   │
│ Aide             ├────────────────────────────────────────────────────┤
│ Déconnexion      │ Activité récente + accès aux rapports autorisés    │
└──────────────────┴────────────────────────────────────────────────────┘
* Sections conditionnées aux permissions et à la disponibilité des données.
```

- Grille principale de 12 colonnes ; sidebar cible 232–248 px, gouttières 20–24 px, cartes 20–24 px de padding.
- Fond gris très clair, cartes blanches, bordures discrètes, rayon 18–22 px et ombres légères.
- Palette actuelle : rouge `#e8121b`, rouge foncé `#b60d14`, noir `#0b0c0e`, gris `#f6f6f6` et bordures `#e6e6e6`.
- Conserver Manrope pour le texte, Saira pour les titres, IBM Plex Mono pour les références. Icônes simples en SVG, décoratives avec `aria-hidden`, pas de nouveau pack chargé à distance.
- Aucun pourcentage sans base calculable. Les cartes de stock n'affichent pas de comparaison historique reconstituée artificiellement.
- La grille se réorganise quand un bloc n'est pas autorisé : pas de trou, pas de remplacement par une fausse statistique.

### 2.3 Navigation et compatibilité

Routes internes simples par fragment : `#dashboard`, `#colis`, `#clients`, `#factures`, `#rapports`, `#reglages`. Les boutons précédent/suivant du navigateur et les liens directs sont pris en charge, sans routeur ni changement des URL publiques existantes.

`Suivi` conserve l'accès à `suivi.html`. Les fiches colis, étiquettes, factures, paiements, rôles et réglages existants restent accessibles. `Mon espace` mène à `espace-client.html`, `Aide` à `support.html`. Ne pas ajouter `Messages` : aucune messagerie interne identifiée.

Accès à la coque : compte équipe avec au moins un droit de lecture de section. Remplacer le verrou global `colis.lire` par des contrôles de section ; cela permet à un employé de facturation autorisé d'accéder à ses tâches sans recevoir les colis. Les boutons et les API gardent leurs contrôles métier. Les clients restent dirigés vers leur espace actuel.

### 2.4 Responsive et accessibilité

| Largeurs à tester | Disposition cible |
|---|---|
| 320, 360, 390, 414 px | Menu tiroir, KPI une colonne, header réorganisé, filtres repliables |
| 768 px | Menu tiroir, KPI deux colonnes, grandes cartes empilées |
| 1024 px | Navigation compacte 72 px avec libellés accessibles, grille adaptée |
| 1280, 1440 px | Sidebar complète, grandes cartes côte à côte |

Pas de largeur minimale rigide dépassant le conteneur. `min-width:0` sur les enfants de grille, textes longs sécables, boutons tactiles d'au moins 44 px, focus visible, contraste vérifié. Le menu se ferme avec Échap et rend le focus au déclencheur. Dialogues accessibles et navigation clavier cohérente.

Les tableaux volumineux disposent d'un défilement horizontal local identifié, jamais du débordement de toute la page. Les colonnes prioritaires sont lisibles sur mobile et la fiche donne accès au reste. Les graphiques ont titre, description et tableau des valeurs ; l'information ne dépend ni de la couleur ni du survol. Animations réduites si `prefers-reduced-motion`.

## 3. Sémantique des données et filtres

### 3.1 Deux périmètres visibles, jamais confondus

**Situation actuelle** : tous les colis actuellement présents et autorisés. Le filtre de dates de la courbe ne modifie pas silencieusement ces KPI. Libellé « Situation actuelle · toutes dates ».

- Total : `COUNT(*)` de `public.colis`.
- En cours : `statut IN ('confirme','expedie','disponible','action')`, définition explicitée dans l'aide ; ventilé par `service`.
- Un mode pris en charge mais sans ligne présente vaut zéro seulement après une requête réussie, pas parce que l'API a échoué.
- Aucun badge d'évolution sur ces stocks : les suppressions et changements historiques empêchent une reconstruction complète fiable.

**Évolution sur période** : fondée sur un champ de date nommé dans chaque section. Période par défaut : mois courant jusqu'à l'instant de référence serveur. Tout changement de filtre relance réellement la requête.

### 3.2 Cartographie opérationnelle

Les expressions ci-dessous décrivent des requêtes à implémenter, non des résultats observés. Toutes les projections sont explicites.

| Widget/rapport | Source et champs | Requête/calcul | Filtres et accès |
|---|---|---|---|
| Total colis | `colis.id` | `COUNT(*)` | Stock actuel ; `colis.lire` |
| En cours par transport | `colis.service, statut` | `COUNT(*) GROUP BY service` sur les quatre statuts non livrés | Stock actuel ; `colis.lire` |
| Statuts | `colis.statut` | `COUNT(*) GROUP BY statut` ; pourcentage = quantité / total × 100 | Stock actuel par défaut ; sélection service/destination facultative |
| Colis enregistrés | `colis.cree_le` | Comptage par heure/jour/semaine/mois local | Période + `service`, destination, statut actuel, `client_id` si autorisé |
| Destinations | `colis.pays_destination, ville_destination, cree_le` | Comptage par pays puis ville ; villes manquantes explicitement regroupées | Même période que les enregistrements ; `colis.lire` |
| Nouveaux clients | `clients.role, cree_le` | `COUNT(*) WHERE role='client'` par jour/semaine/mois | Dates de création ; `clients.lire` ; pas de filtre transport appliqué aux inscriptions |
| Facturation | `factures.montant, devise, cree_le` | `SUM(montant)` par période et devise | `factures.lire` ; statut/client si autorisé |
| Soldes | `factures.montant, montant_paye, devise` | `SUM(GREATEST(montant-montant_paye,0))` ; crédits/trop-perçus séparés | Position actuelle ou cohorte de factures clairement indiquée |
| Montants payés cumulés | `factures.montant_paye, devise` | Somme par devise | Pas de graphe des versements par jour : journal absent |
| Colis récents | `colis_details.id, numero, cree_le, expediteur, destinataire, pays_destination, ville_destination, poids_lb, service, statut` | Tri `cree_le DESC, id DESC`, pagination 20 lignes, count exact | Recherche/tri sur liste blanche, filtres à la source |
| Identité client enrichie | `clients.code, nom_complet` via `colis_details` | Jointure conditionnelle | Seulement avec `clients.lire` ; sinon pas de nom/code client enrichi |
| Activité | `colis_historique.id, colis_id, statut, lieu, cree_le, auteur` + `colis.numero` | Tri `cree_le DESC, id DESC`, liste limitée | Dates d'événement ; `colis.lire` |
| Poids d'un rapport | Instantanés `poids_lb` | Somme des poids non nuls + nombre de poids absents | Unité lb ; si tous absents, valeur inconnue, pas zéro |

Les libellés `confirme`, `expedie`, `disponible`, `livre`, `action` restent ceux du système. Aucun statut « annulé » ou « en attente » inventé. Les dates de création ne sont pas des dates de départ ni de livraison.

L'activité est libellée « Historique du colis », sans déclarer automatiquement chaque ligne « nouveau départ » : les changements de note ou de lieu produisent eux aussi des événements. Pas de fausses activités de paiement, utilisateur ou rapport.

Le tableau récent n'affiche pas de montant arbitraire par colis : une facture peut être groupée. Les montants restent dans la facturation et la fiche liée. Poids, destinataire ou ville manquants sont indiqués comme non renseignés.

### 3.3 Heure de Saint-Domingue

Configuration prévue : `SES_CONFIG.fuseauHoraire = 'America/Santo_Domingo'`. Paramètre explicite des formats de date et du calcul serveur, sans changer silencieusement toutes les autres pages.

- Stockage : `timestamptz`, instants absolus.
- Saisie : date/heure locale métier, interprétée côté PostgreSQL avec `AT TIME ZONE 'America/Santo_Domingo'` ; ne pas utiliser le fuseau de l'ordinateur du visiteur.
- Affichage : `Intl.DateTimeFormat` avec `timeZone` explicite et locale de l'interface.
- Heure serveur : une référence temporelle par chargement permet d'afficher « Dernière mise à jour » sans prendre l'horloge du navigateur comme preuve.
- Semaine proposée : ISO, du lundi 00:00 au lundi suivant 00:00.
- Bornes : **début inclus, fin exclue** (`>= debut AND < fin`). Le libellé d'heure indique « jusqu'à …, exclu » pour lever l'ambiguïté.
- Jour, mois et année sélectionnés : intervalles calendaires locaux complets. Pour une période courante, l'instant effectif et les éventuelles portions futures non tracées sont signalés.
- Heure seule : exige une date. Si l'heure de fin précède le début, demander une fin au jour suivant via la période personnalisée, pas d'interprétation implicite.
- Valeurs invalides, fin antérieure au début, période trop volumineuse : erreur explicite, pas de requête approximative.

Exemples de bornes techniques, **pas de données commerciales** :

| Filtre local | Intervalle UTC |
|---|---|
| 30/09/2026 | `[2026-09-30T04:00Z, 2026-10-01T04:00Z[` |
| 30/09/2026, 08:00–18:00 | `[2026-09-30T12:00Z, 2026-09-30T22:00Z[` |
| Semaine du 28/09/2026 | `[2026-09-28T04:00Z, 2026-10-05T04:00Z[` |
| Septembre 2026 | `[2026-09-01T04:00Z, 2026-10-01T04:00Z[` |

L'offset n'est pas codé en dur : utiliser le fuseau IANA, y compris pour les dates historiques.

### 3.4 Comparaisons, périodes vides et qualité

Comparaison seulement sur flux de création comparables, avec les bornes des deux périodes renvoyées par le serveur. Pour une période incomplète, comparer la même portion écoulée de la période précédente ; si impossible (durées calendaires différentes), annoncer l'absence de comparaison. Pour une période personnalisée, intervalle précédent de même durée.

`(courant - precedent) / precedent * 100` seulement si `precedent > 0`. Sinon « Comparaison indisponible : période précédente sans données ». Si une requête échoue, aucune valeur zéro ni badge d'évolution de secours.

Un créneau à zéro peut être ajouté avec `generate_series` uniquement après comptage exhaustif réussi : zéro signifie absence réelle d'enregistrement dans ce créneau, pas donnée de démonstration. Une période entièrement vide affiche un état vide, sans courbe décorative.

Finance : séparer les devises, ne pas convertir sans taux officiel. Contrôler `montant` contre les lignes et frais ; signaler les incohérences, bloquer la validation d'un rapport financier incohérent. Ne jamais réécrire des factures pour faire coïncider les indicateurs. Le montant facturé décrit les factures actuellement conservées, pas un livre comptable historique complet.

## 4. Architecture frontend et API

### 4.1 Organisation proposée

```text
tableau-de-bord.html                    page servie, coque et gabarits
outils/espace/tableau-de-bord.html      source correspondante
assets/css/ses-dashboard.css           styles isolés de la coque et rapports
assets/js/ses-admin.js                 contrôleur existant : CRUD et navigation
assets/js/ses-dashboard.js             rendu KPI, graphiques, filtres, états
assets/js/ses-rapports.js               rapports, aperçu, sélection, signature
assets/js/ses-pdf.js                    export A4 et impression du PDF
assets/js/ses-api.js                    seule couche réseau, nouvelles méthodes
assets/js/ses-ui.js                     utilitaires existants, extensions ciblées
assets/js/lang-dict-11.js               traductions des nouveaux textes
outils/supabase-*.sql                   nouvelles migrations validées séparément
```

Ces noms sont des propositions de nouveaux fichiers, pas des composants déjà présents. Aucun fichier par petite carte : KPI Card, Chart Card, Filter Bar, Report Table et états sont des fonctions réutilisables au sein de ces modules.

Les styles de la coque sont chargés uniquement par le dashboard. Pas de sélecteurs globaux qui recolorent connexion, suivi ou espace client. Adapter l'assemblage du dashboard explicitement plutôt que le reconstruire depuis une page de contact sans contrôler les différences. Synchroniser page/gabarit, tester l'assemblage en mémoire, actualiser les versions de scripts avec changements ciblés.

Choix graphiques : SVG natif pour courbe, barres et anneau, suffisant pour ces séries agrégées. Pas de bibliothèque de charting supplémentaire. Points, axes, légendes et valeurs proviennent uniquement du contrat API. Accès clavier et tableau des valeurs obligatoire.

Choix PDF : **jsPDF et AutoTable**, versions figées et fichiers locaux après vérification de licence/sécurité en phase 6. Nécessité justifiée par le téléchargement direct, les tableaux multipages et la signature. Chargement différé à la première demande ; pas de capture d'écran HTML ni de CDN tiers. Polices incorporées avec couverture des accents français/créoles/espagnols à vérifier.

### 4.2 Contrats API proposés

Tous les noms ci-dessous désignent des ajouts futurs à `SES_API`, jamais un deuxième client Supabase.

| Méthode logique | Backend proposé | Objet |
|---|---|---|
| `admin.dashboardColis(filtres)` | RPC `dashboard_colis_ses` | Stock, série temporelle, statuts, destinations, poids connus |
| `admin.dashboardClients(filtres)` | RPC `dashboard_clients_ses` | Inscriptions réelles par période |
| `admin.dashboardFactures(filtres)` | RPC `dashboard_factures_ses` | Agrégats par devise et signalements de qualité |
| `admin.activite(filtres)` | Lecture projetée/paginée de l'historique joint aux colis | Événements réels |
| `admin.colis/factures/clients(options)` | Méthodes existantes étendues | Projection, dates, tri stable et pagination |
| `rapports.capacites()` | RPC de disponibilité/version et permissions | Rapports utilisables ; une erreur de connexion n'est pas une absence de module |
| `rapports.apercu(type, filtres, page)` | RPC de lecture par type autorisé | Aperçu de recherche non archivé |
| `rapports.enregistrerBrouillon(...)` | RPC d'écriture contrôlée | En-tête + instantanés canoniques + totaux |
| `rapports.valider(...)` | RPC transactionnelle | Contrôle de version/empreinte, signature, validation |
| `rapports.lister/consulter/lignes(...)` | Lectures RLS avec projections/pagination | Historique et document enregistré |
| `rapports.annuler(...)` | RPC contrôlée | Annulation logique motivée, sans suppression des colis |

Les RPC d'agrégats et d'aperçu utilisent `SECURITY INVOKER` et des contrôles de droits par domaine : elles respectent les RLS des sources. Ne pas réutiliser la RPC `statistiques_ses()` actuelle sans corriger son dépassement de permissions. Conserver sa compatibilité de sortie si elle reste appelée, mais ne plus livrer des agrégats de domaines interdits.

Contrat de chaque domaine : version, filtres normalisés, bornes locale/UTC, fuseau, date de lecture serveur, totaux, séries, avertissements de qualité, informations de comparaison. Montants/poids en décimal exact (chaînes décimales ou unités entières documentées), sans flottants utilisés comme source des totaux d'archive.

Un bloc financier interdit est `non_autorise`, pas zéro. `loading`, `empty`, `error`, `success`, `indisponible` sont distingués. Skeletons `aria-busy`, message d'erreur avec Réessayer et dernier résultat éventuellement affiché comme périmé.

### 4.3 Performance et rafraîchissement

- Agrégations côté PostgreSQL ; pas de chargement de tous les colis pour construire une courbe.
- Une requête agrégée par domaine autorisé, indépendance des erreurs de domaines.
- Recherche avec temporisation, annulation ou jeton de génération : une réponse ancienne ne remplace pas le filtre courant.
- Tri SQL sur liste blanche, paramétrage des filtres, aucune chaîne SQL fournie par le navigateur.
- Realtime réutilisé : coalescer les notifications colis/historique/factures, invalider seulement les domaines affectés. Ajouter clients/rapports au mécanisme existant uniquement si publication et RLS ont été validées, pas de deuxième architecture temps réel.
- Bouton Actualiser ; rafraîchissement au retour sur la page. Pas d'abonnement qui écrase un brouillon de manifeste ou une signature en cours.
- Pagination des listes 20 lignes ; export des instantanés par pages techniques, jamais limité à la page visible.
- Limite initiale proposée : 2 000 lignes par document archivé, configurable après mesures. Si dépassée, refuser clairement et demander un filtre plus précis ou un découpage explicite ; ne jamais tronquer un PDF. C'est une limite technique, pas une statistique.
- Pas de cache persistant de données personnelles, signatures ou PDF dans localStorage. Vider l'état sensible et révoquer les URL Blob à la déconnexion.

## 5. Centre Rapports et parcours manifeste

### 5.1 Centre Rapports

Header « Rapports » et sous-titre de consultation/génération, catalogue filtré par capacités et droits, barre de filtres adaptée au type, aperçu, historique paginé.

Types initiaux : colis général/par statut existant, clients, facturation, activité colis, manifeste. Les presets de statut sont des filtres d'un même type, pas six moteurs différents. Aucun rapport de transactions de paiement, profits ou annulations de colis non supportées.

Les filtres du catalogue ne sont pas tous universels : transport/destination pour colis, auteur pour historique, chauffeur/préparateur pour manifestes déjà créés, statut de rapport pour historique. Ne pas prétendre filtrer les factures groupées par transport tant qu'une règle d'attribution correcte n'est pas définie.

Aperçu : titre, période, critères, génération/lecture locale, compte réel, données paginées, nombre global et poids connus, avertissements. Boutons Enregistrer/Valider, Générer PDF, Imprimer, Télécharger, Fermer selon état et droits. `Générer PDF` prépare le fichier et son aperçu ; `Télécharger` remet le même fichier ; `Imprimer` utilise le même document.

Un aperçu vivant peut changer entre deux pages en cas d'activité concurrente ; il est marqué non archivé. Le PDF final s'appuie uniquement sur l'instantané enregistré, pas sur les pages d'un aperçu vivant.

### 5.2 Manifeste

1. **Informations** : date/heure de Saint-Domingue par défaut, chauffeur texte contrôlé, préparateur et notes. Pas de table chauffeurs parallèle. Le préparateur est prérempli depuis le profil réel, modifiable avec traçabilité distincte du créateur authentifié.
2. **Recherche** : vrais colis par numéro, destinataire et, si autorisé, nom/code client. Résultats paginés, ajout sans doublons, possibilité de clients différents. Aucun appel de facturation.
3. **Liste** : référence, expéditeur, destinataire, destination, poids, service, statut. Retirer demande confirmation puis modifie seulement la sélection ou les lignes de ce brouillon via son API.
4. **Résumé** : quantité distincte, poids connu et nombre de poids manquants, distributions statut/destination/service issues des mêmes lignes.
5. **Sauvegarde du brouillon** : numéro unique généré côté serveur. Avant la première sauvegarde, afficher « Attribué à l'enregistrement », pas un faux numéro. Après sauvegarde, afficher le vrai numéro non modifiable.
6. **Signature** : nom du signataire, préparateur, zone canvas souris/trackpad/tactile, Effacer, aperçu. La date/heure de signature est attribuée par le serveur lors de la validation. Toute modification du contenu signé invalide la signature et exige une nouvelle confirmation.
7. **Validation** : version et empreinte attendues, contrôle des droits et de la sélection, recopie canonique contrôlée. Si les sources ont changé depuis l'aperçu enregistré, renvoyer un conflit explicite ; recharger, revoir le résumé et signer à nouveau. Aucun ajustement silencieux après signature.
8. **Document final** : PDF/print/téléchargement depuis les lignes immuables validées, jamais depuis les colis vivants.

Destination/mode de l'en-tête sont des critères facultatifs, pas des valeurs qui écrasent les colis. S'ils sont imposés, refuser une sélection incompatible. Sinon afficher les répartitions réelles, éventuellement multiples.

Le canvas garde ses traits lors du redimensionnement, gère le facteur de densité écran et `pointercancel`. `touch-action:none` seulement sur la zone à signer ; le reste de la page reste défilable. Un trait est nécessaire pour une signature non vide. Aucun signataire n'est fabriqué. La signature manuscrite capturée n'est pas présentée comme une signature électronique qualifiée.

## 6. Persistance proposée — aucune table créée pendant cette phase

Réutiliser les principes d'instantané déjà présents dans `factures.lignes`, mais pas la table factures pour stocker des rapports. Deux nouvelles tables suffisent ; pas de table chauffeurs, paiements ou permissions parallèle.

### 6.1 `public.rapports`

| Colonnes proposées | Type / contraintes | Rôle |
|---|---|---|
| `id` | `uuid` PK | Identifiant |
| `numero` | `text UNIQUE NOT NULL` | Séquence serveur `RPT-année-compteur`, sans renumérotation ni exigence de continuité |
| `type` | `text` contrôlé | `colis`, `clients`, `facturation`, `activite`, `manifeste` |
| `statut` | `text` contrôlé | `brouillon`, `valide`, `annule` |
| `date_rapport`, `cree_le`, `maj_le` | `timestamptz` | Date métier et horodatages serveur |
| `fuseau` | `text NOT NULL` | `America/Santo_Domingo` |
| `cree_par` | `uuid`, FK `auth.users`, `ON DELETE SET NULL` | Créateur authentifié ; ne pas supprimer le rapport avec le compte |
| `createur_identite`, `preparateur_nom`, `chauffeur_nom`, `signataire_nom` | `text` borné | Identités déclarées/réelles distinguées |
| `notes` | `text` borné | Notes facultatives |
| `filtres` | `jsonb` validé, taille bornée | Filtres normalisés et bornes effectives |
| `droits_sources` | `text[] NOT NULL` | Permissions de lecture exigées pour TOUT le document ; calculées par le serveur |
| `societe` | `jsonb` liste blanche | Copie des mentions Speed Express utilisées lors de validation |
| `totaux` | `jsonb` canonique | Nombre, poids connus/manquants, répartitions et montants par devise |
| `signature_png` | `bytea` nullable | PNG privé, pas de fichier public ; limite proposée 256 Kio |
| `signe_le`, `valide_le` | `timestamptz` nullable | Horodatages serveur |
| `valide_par`, `annule_par` | `uuid`, FK `auth.users`, `ON DELETE SET NULL` | Traçabilité des opérations |
| `annule_le`, `motif_annulation` | `timestamptz`, `text` borné | Annulation logique motivée |
| `version` | `integer` positif | Verrouillage optimiste |
| `version_format` | `integer` positif | Version de rendu et schéma d'instantané |
| `empreinte` | `text` | Empreinte du contenu canonique, pas une preuve légale d'identité |
| `cle_idempotence` | `uuid UNIQUE` | Anti-double-enregistrement, liée au créateur et à la requête dans les contrôles RPC |
| `empreinte_requete` | `text` | Même clé et contenu différent : conflit, pas écrasement |

Le compteur est alloué côté PostgreSQL. Le navigateur ne peut pas fabriquer numéro, auteur authentifié, droits nécessaires, statut final, timestamps, totaux ou empreinte.

La colonne `societe` utilise uniquement la liste blanche des valeurs de `SES_CONFIG` et le nom/logo officiels. Ces valeurs sont publiques et le navigateur peut être modifié : elles ne constituent donc pas une attestation serveur d'identité d'entreprise. Ne jamais copier tout `SES_CONFIG` (notamment pas ses paramètres Supabase) dans le rapport. Si une identité d'entreprise administrable et garantie côté serveur devient nécessaire, une configuration serveur dédiée devra être approuvée ; ne pas présenter le mécanisme actuel comme inviolable.

### 6.2 `public.rapport_lignes`

| Colonnes proposées | Type / contraintes | Rôle |
|---|---|---|
| `id` | `uuid` PK | Identifiant de ligne |
| `rapport_id` | `uuid NOT NULL` FK `rapports`, suppression restreinte | Relation parent |
| `ordre` | `integer > 0`, UNIQUE avec `rapport_id` | Ordre stable |
| `nature` | `text` contrôlé | Nature de source |
| `colis_id`, `client_id`, `facture_id` | `uuid` FK source nullable, `ON DELETE SET NULL` | Référence relationnelle appropriée |
| `historique_id` | `bigint` FK source nullable, `ON DELETE SET NULL` | Référence événement |
| `source_cle` | `text NOT NULL` | Identifiant source figé, conservé même après disparition du lien |
| `instantane` | `jsonb NOT NULL`, liste blanche | Valeurs au moment de validation, sans jeton QR, secret ni colonnes inutiles |
| `UNIQUE(rapport_id, nature, source_cle)` | Contrainte | Pas de doublon |

La correspondance nature/source est contrôlée à l'insertion ; ne pas exiger qu'une FK reste non nulle après suppression de sa source. Le document reste lisible via `source_cle` et `instantane`.

**Point important sur l'immuabilité** : `ON DELETE SET NULL` provoque une mise à jour technique du lien. Le trigger de protection doit laisser uniquement cet effacement de FK, sans modification de `source_cle`, instantané, ordre, compteurs ou empreinte. Cela ne doit pas bloquer la suppression autorisée d'un colis existant ni supprimer une ligne du rapport. Même principe pour les FK de traçabilité sur l'en-tête.

### 6.3 Signature et PDF archivables

PNG seulement : longueur, signature binaire, dimensions IHDR et limites de pixels vérifiées ; SVG/HTML et chaînes data arbitraires refusés. Décodage vérifié dans le moteur de rendu. L'image est incorporée au PDF final, jamais chargée depuis une URL publique.

Pas de bucket de stockage ajouté pour la première version : instantané + signature privés en PostgreSQL ; PDF généré localement et téléchargeable. L'historique peut regénérer le contenu figé avec `version_format` supportée. Une identité byte-à-byte du PDF n'est pas garantie entre versions du moteur. Si l'archivage du fichier exact devient obligatoire, ajouter ultérieurement un bucket privé avec contrôle d'accès et vérification de hash, après validation séparée.

## 7. Permissions, RLS et fonctions d'écriture

### 7.1 Extension du mécanisme existant

Ajouter à `SES_API.DROITS` et aux libellés, sans nouveau rôle :

- `rapports.lire` ;
- `rapports.creer` ;
- `rapports.modifier` (ses propres brouillons pour un employé) ;
- `rapports.valider` ;
- `rapports.exporter` (PDF, impression, téléchargement) ;
- `rapports.annuler` (ses propres rapports pour un employé).

L'admin garde tous les droits via `a_droit`. Aucun droit supplémentaire accordé automatiquement aux employés. L'extension doit rester compatible avec `definir_role`, dont la liste de droits est filtrée côté JS ; revoir également la validation serveur pour ne pas permettre une délégation plus large que le mécanisme autorisé.

| Action | Client / anonyme | Employé | Admin |
|---|---|---|---|
| Voir historique et aperçu | Refusé | `rapports.lire` + tous les droits de sources | Autorisé |
| Créer | Refusé | Lecture + `rapports.creer` + sources | Autorisé |
| Modifier brouillon | Refusé | Lecture + `rapports.modifier` + sources + propriétaire | Autorisé |
| Valider | Refusé | Lecture + `rapports.valider` + sources + propriétaire | Autorisé |
| PDF/impression/téléchargement | Refusé | Lecture + `rapports.exporter` + sources | Autorisé |
| Annuler | Refusé | Lecture + `rapports.annuler` + sources + propriétaire, motif exigé | Autorisé avec motif |
| Modifier contenu validé / supprimer définitivement | Refusé | Refusé | Refusé via l'application ; annulation et nouveau rapport |

Un accès lecture permet techniquement de copier ou d'imprimer les données visibles depuis le navigateur : le droit d'export contrôle les fonctions proposées, pas un DRM. Après téléchargement, une révocation ne peut pas retirer le fichier déjà remis.

### 7.2 Lecture d'instantanés : refus intégral plutôt que fuite partielle

RLS activée sur les deux tables ; aucun accès anonyme. `rapports` SELECT exige compte équipe, `rapports.lire` et **tous** les `droits_sources`. `rapport_lignes` SELECT exige que le parent satisfasse exactement la même règle. Appliquer également ces règles aux RPC et à l'historique, pas seulement aux boutons.

Exemples : manifeste sans identité enrichie client = `colis.lire` ; avec `nom_complet/code` clients = `colis.lire` + `clients.lire` ; rapport financier enrichi client = `factures.lire` + `clients.lire`. Droits requis enregistrés par le serveur, jamais acceptés de l'appelant.

Si un droit est retiré, le **rapport entier** devient inaccessible tant que ses données nécessitent ce droit. Ne pas exposer un JSON contenant les champs sensibles puis les masquer en JavaScript. Ne pas afficher un total ou titre sensible via une liste d'historique moins protégée.

La suppression d'une source ne fait pas disparaître l'archive ; l'accès dépend des permissions de l'archive. La conservation des noms/signatures après suppression d'un compte doit être approuvée par le propriétaire, avec une politique de durée et de purge administrative hors interface courante.

### 7.3 Écriture atomique et confiance

Les écritures passent par des RPC `SECURITY DEFINER` durcies, propriétaire serveur contrôlé, `search_path=''`, noms qualifiés, aucune interpolation SQL. Révoquer explicitement EXECUTE à PUBLIC/anon ; accorder uniquement à authenticated avec rejet des clients/non autorisés dans chaque fonction. Révoquer INSERT/UPDATE/DELETE/TRUNCATE direct sur les tables de rapports à anon/authenticated. Les RPC lisent uniquement des champs source autorisés et calculent elles-mêmes les instantanés et totaux.

**Limite explicitement assumée** : une fonction possédée par le propriétaire de base peut contourner les RLS ; déclarer SECURITY DEFINER ne les préserve pas automatiquement. Avec les politiques du dépôt, exiger le rôle équipe ET `a_droit` de chaque table lue est plus restrictif que l'accès source prévu. Les branches « données personnelles du compte » ne sont pas utilisées pour créer des rapports d'équipe. L'inclusion d'un nom client exige `clients.lire` même si le colis est lisible.

Cette équivalence doit être vérifiée sur le schéma réel et couverte par des tests de droits. **Si les RLS de production comportent un périmètre agence, tenant ou ligne absent du dépôt, bloquer cette implémentation et adapter la lecture à ces politiques avant tout déploiement** (par exemple rôle propriétaire de fonction sans bypass avec privilèges/RLS appropriés). Aucun `service_role` dans le navigateur. Ne pas réutiliser sans correction le modèle permissif de l'ancienne RPC statistiques.

La RPC refuse toute sélection contenant un identifiant absent ou interdit, avec une erreur générique, sans révéler l'existence d'une ligne. Filtre d'aperçu = liste blanche de types/champs, jamais nom de table ou SQL libre transmis au serveur.

Une transaction verrouille l'en-tête, vérifie propriétaire/droits/version/clé d'idempotence, écrit les lignes et calcule les totaux depuis ces lignes. La lecture canonique des sources se fait dans une instruction cohérente ; pas de mélange entre pages vivantes. Rejeu identique = même résultat ; clé réutilisée avec un autre contenu = conflit. Signature et validation appartiennent à la même transaction ; échec = aucun rapport partiellement validé.

Les rapports validés ne permettent plus d'édition de contenu. L'annulation ajoute seulement statut/motif/horodatage et conserve lignes/signature. Les triggers interdisent les mutations non prévues, y compris les tentatives directes ; leurs exceptions techniques de FK sont étroites et testées.

## 8. Migrations et dépendances à traiter

**Aucun SQL n'est créé ou appliqué en phase 2.** Les noms ci-dessous décrivent des nouvelles migrations à préparer au moment approprié, jamais une modification destructive d'un fichier déjà appliqué.

### Avant phase 3 / activation du dashboard

1. Vérifier tables, colonnes, versions des vues, policies, propriétaires/exécution des fonctions et publication Realtime en production autorisée.
2. Corriger le filtre `colis_id` absent de `admin.factures`, supprimer le filtre de colonne inexistante dans `admin.colis` et tester les fiches liées.
3. Nouvelle migration d'agrégats sécurisés `dashboard_*_ses` ; sécuriser aussi `statistiques_ses` pour les anciens clients et corriger la sémantique du solde.
4. Traiter la projection `groupee` de `factures_details` sans DROP CASCADE ; une vue nouvelle explicitement projetée peut être nécessaire si la signature ancienne ne permet pas un remplacement compatible.
5. Vérifier les totaux de factures. Tant que les incohérences financières ne sont pas résolues, ne pas activer un indicateur présenté comme validé.
6. Le regroupement de factures existant doit devenir transactionnel avant d'être utilisé comme source financière fiable ; préserver la fonction métier, ne pas la réutiliser pour les manifestes. Présenter cette correction séparément et ne pas réécrire automatiquement les anciennes factures.

### Index candidats (à confirmer avec EXPLAIN, pas à ajouter aveuglément)

| Index | Type | Motivation / impact |
|---|---|---|
| `colis(cree_le DESC,id DESC)` | B-tree | Périodes + tri récent ; coût additionnel aux écritures |
| `clients(role,cree_le)` | B-tree | Nouveaux clients filtrés par rôle |
| `factures(cree_le DESC,id DESC)` | B-tree | Périodes et pagination financière |
| `colis_historique(cree_le DESC,id DESC)` | B-tree | Activité globale récente ; complète l'index existant par colis |
| `rapports(cree_le DESC,id DESC)` | B-tree | Historique stable |
| `rapports(cree_par,statut,cree_le DESC)` | B-tree | Brouillons et droits de propriétaire |
| `rapport_lignes(rapport_id,ordre)` | UNIQUE/B-tree | Ordre et pagination des lignes |
| `rapport_lignes(rapport_id,nature,source_cle)` | UNIQUE | Déduplication |
| FK sources de `rapport_lignes` | B-tree selon volume | Faciliter SET NULL lors de suppressions sources |

Contraintes PK/numéro/idempotence créent aussi leurs index. Évaluer temps de construction et verrous avant application sur une base volumineuse ; pas de migration automatisée de production depuis GitHub Pages.

### Avant phases 4–5

Nouvelle migration rapports : deux tables, séquence, contraintes, RLS/grants, RPCs de cycle de vie, index et immuabilité décrits ci-dessus. Expliquer le SQL réel et son impact au propriétaire avant application. Ajouter un contrôle de version des capacités : migrations absentes = module indisponible avec message clair, pas de fausse liste vide.

Retour arrière : désactiver les nouveaux modules et revenir au frontend compatible sans supprimer les archives, nouvelles colonnes ou données. Une ancienne version des widgets ne doit pas réintroduire une fuite de permissions.

## 9. PDF A4, aperçu et impression

- Portrait par défaut ; tableau manifeste à colonnes compactes, titres répétés et références lisibles. Pays/ville, expéditeur/destinataire passent à la ligne ; aucun texte coupé.
- Marges réelles, logo officiel incorporé, nom, adresse/téléphone/email configurés, titre/numéro, date locale, fuseau, filtres et identité du générateur.
- Pagination explicite « Page … / … », statistiques et avertissements de poids manquants.
- Pied de page discret et signature avec préparateur, nom du signataire et horodatage local. La zone signature reste entière sur une page, jamais coupée.
- Brouillon imprimable uniquement avec droit export et marquage visible BROUILLON ; document officiel seulement après validation du manifeste signé.
- Un rapport annulé exporté porte clairement ANNULÉ, sans effacement de son contenu d'origine.
- Générer depuis l'instantané, paginer toutes les lignes, vérifier quantité/poids/devises contre l'en-tête avant remise. Refuser tout export incomplet.
- Impression via le PDF généré et URL Blob temporaire déclenchée par l'utilisateur. Si l'impression intégrée est bloquée sur mobile, ouvrir/télécharger le même PDF avec instructions ; ne pas prétendre qu'il est déjà imprimé.
- Conserver `SES_UI.imprimer()` pour les anciennes factures/étiquettes ; ne pas altérer leurs formats A4 et 4×6.
- Aucune transmission de données à un service PDF tiers.

## 10. Tests et critères de passage

### Vérifications réalisées pendant la phase 2

- Branche et arbre Git vérifiés avant modification : base d'audit inchangée.
- Schémas, champs, enums, mécanisme de permissions, vues et points d'entrée revérifiés dans le dépôt.
- Conversions calendaires contrôlées en mémoire avec `zoneinfo` : jour, heures, semaine ISO, mois, année, période personnalisée traversant l'année et jour bissextile.
- Bornes semi-ouvertes et début de semaine lundi contrôlés.
- Contrats de sources vérifiés contre les déclarations SQL, y compris `groupee` dans sa migration.
- Vérification finale : syntaxe des 25 scripts JavaScript et des 4 scripts Python présents directement dans `outils/`, sans exécuter les générateurs ni créer de fixtures métier. Ce recomptage corrige le nombre de 5 scripts Python annoncé précédemment ; il ne faut pas le présenter comme un cinquième fichier contrôlé.
- Revue ciblée de sécurité du schéma d'instantanés : contournement RLS possible des fonctions propriétaire, accès aux JSON, révocation de droits, mutation technique des FK.

Ces contrôles valident la conception et l'existant syntaxique, pas une application implémentée. Aucun test navigateur, PDF, souris/tactile, base réelle ou migration n'est déclaré réussi pendant cette phase.

### Matrice de validation à implémenter

| Groupe | Scénarios obligatoires |
|---|---|
| Données dashboard | Réelles, zéro ligne, API en erreur, refus de permission, réponse périmée ; valeurs affichées comparées aux requêtes SQL autorisées |
| Calendrier | Jour, heures, semaine, mois, année, personnalisé, minuit local, changement mois/année, année bissextile, navigateur dans un autre fuseau |
| Sélection | Recherche réelle, ajout unitaire/multiple, doublon, retrait confirmé ; aucune opération UPDATE/DELETE sur colis ; clients multiples permis |
| Totaux | Nombre sélectionné = lignes archivées ; somme des poids connus ; null distinct de zéro ; répartition = même ensemble |
| Chauffeur/préparateur | Saisie contrôlée, champs requis, identité réelle, aucune création de compte chauffeur |
| Signature | Souris, trackpad, tactile, effacement, redimensionnement, signature vide, modification après signature, apparition dans PDF |
| Persistance | Sauvegarde brouillon, validation atomique, double clic/rejeu, conflit de version/source, rollback et modification refusée après validation |
| Historique | Lecture/filtrage/pagination, source supprimée sans perte d'archive, suppression du compte créateur, statut annulé |
| Sécurité | Anonyme/client/employé limité/admin ; accès direct REST ; interdiction falsification snapshot/totaux ; retrait d'un droit source ; fonction RPC et tables protégées |
| PDF | Aperçu, génération, téléchargement, impression, accents, longs champs, plusieurs pages, signature non coupée, compteur exact, aucune page de données oubliée |
| Responsive | 320/360/390/414/768/1024/1280/1440 ; clavier et focus ; débordements locaux seulement |
| Non-régression | Connexion/récupération, espace client, suivi/QR, CRUD colis, étiquettes, factures, paiements, regroupement, rôles, langues et Realtime |

Ne pas utiliser de données de démonstration dans les captures livrées comme données réelles. Tests techniques d'erreur/vide possibles en mémoire ; tests de droits et mutations métier sur un environnement autorisé et isolé, pas sur les colis de production sans accord.

## 11. Fichiers de la phase et arrêt

**Ajout effectif :** `outils/architecture-dashboard-rapports.md` seulement.

**Aucune modification** de HTML/JS/CSS/configuration applicative, schéma SQL, RLS, workflow ou données métier. Aucun déploiement déclenché.

La phase 3 ne commence qu'après validation de cette architecture. Les décisions proposées incluses dans cette validation sont : semaines lundi–dimanche, distinction stock/période, droits supplémentaires dans le mécanisme existant, chauffeur texte, snapshots privés, signature PNG, conservation de l'archive après suppression d'une source, export jsPDF/AutoTable et limite technique explicite.

Le schéma réel, la durée de conservation légale et les tests RLS restent des prérequis avant activation en production du stockage de rapports. Les autorisations GitHub Actions insuffisantes constatées précédemment restent un sujet de publication, distinct de la conception.
