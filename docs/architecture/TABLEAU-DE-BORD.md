# Le tableau de bord administratif (phase 7, étape 019)

Le tableau de bord de l'équipe (`tableau-de-bord.html`) devient la seule entrée de l'exploitation : une barre de **26 modules**, un
**centre de commande** en cartes temps réel, et le **Pointage Express** (colis et personnel). L'étape **019**
(`outils/logistique/019-tableau-de-bord.sql`, après 018) décide qui voit quoi et compte tout ce qui s'affiche ; le navigateur ne fait
qu'afficher.

Essais :
- `outils/tests/logistique-tableau-essai.py` : 108 vérifications, sur la réplique de la production **et** sur une préproduction montée
  comme la vraie (modules par rôle, cartes, listes, pointage des colis, pointage du personnel). Il enregistre `tableau-exemples.json`
  (réponses réelles) et `tableau-rpc.json` (formes) avec `SES_FORME_ECRIRE=1` ;
- `outils/tests/tableau-contrat.cjs` : la barre (ordre, identifiants, sections), les méthodes dans les trois implémentations de
  `SES_API`, les textes et leurs traductions, aucun calcul de chiffre dans `ses-modules.js` ;
- `outils/tests/tableau-browser.mjs` : un vrai navigateur, à 1440, 1920, 2560, 1024, 768, 430, 390 et 375 px, dans les quatre langues
  (lancé à la main, comme les autres essais `*-browser.mjs`).

État : **non appliquée**. Sans 019, la barre des 26 modules s'affiche quand même ; les modules du noyau ouvrent un écran « Bientôt disponible », sans chiffre (§7).

## 1. Le principe

La règle des rôles vit dans la base. `lg_dashboard_access` rend la liste ordonnée des modules qu'un compte peut ouvrir ; chaque fonction
de chaque module revérifie ses droits à chaque appel. Les cartes du centre de commande sont comptées par `lg_cc_command` : le navigateur
n'additionne rien, il ne recalcule aucun indicateur.

## 2. La barre des 26 modules

Dans l'ordre : Vue générale, Centre de commande, Colis, Pré-alertes, Scanner, Entrepôts, Consolidations, Expéditions, Transport,
Douane, Livraisons, Chauffeurs, Véhicules, Tournées, Incidents, Clients, Factures, Encaissements, Dépenses, Rapports, Analytique,
Notifications, Équipe, Pointage Express, Paramètres, Santé système.

Chaque entrée est un `<button role="tab" data-module>` dans `outils/espace/tableau-de-bord.html`. Deux familles :
- les modules de l'**ancien schéma** gardent leur panneau et leur identifiant (`ses-o-dashboard` = Vue générale, `ses-o-colis`,
  `ses-o-prealertes`, `ses-o-clients`, `ses-o-factures`, `ses-o-equipe`, `ses-o-reglages` = Paramètres) ;
- les modules du **noyau** partagent le panneau du centre (`aria-controls="ses-p-centre"`) et nomment leurs sections
  (`data-sections="paiements facturation"`…). La première section est l'accueil du module ; les autres apparaissent en puces sous le
  titre. L'adresse reste `#centre/<section>`, et `ses-admin.js` (`route()`) choisit l'onglet qui possède la section.

Plusieurs onglets ouvrant le même panneau, `SES_A11Y.onglets` ne cache un panneau que s'il n'est pas celui de l'onglet choisi.

### 2 bis. Cinq modules retirés de la barre (20/10/2026)

À la demande du propriétaire, **Entrepôts, Consolidations, Transport, Douane et Pointage Express** ne sont plus dans la barre (21 modules
affichés). La base les ouvre toujours (`dashboard_access` inchangée) et aucune donnée n'est touchée : le site ne dessine plus leurs sections
(`SECTIONS_RETIREES` dans `ses-centre.js` : `entrepot`, `consolidations`, `unites`, `transport`, `douane`, `pointage`).

| Ce qui reste possible | Où |
|---|---|
| Douane (ouvrir, droits, payés, libérer, rejeter), départ, arrivée, réception au HUB | la fiche d'une expédition (Expéditions) |
| Agences, entrepôts, emplacements | Paramètres › « Agences et entrepôts » (section `sites`) |
| Cartes du temps réel Départs, Douane, Arrivages, Retards | elles ouvrent les Expéditions ; la carte Tâches (Pointage) reste affichée, sans lien |

Les remettre : retirer leur nom de `SECTIONS_RETIREES`, remettre leur bouton dans `outils/espace/tableau-de-bord.html` (historique Git) et la
liste `RETIRES` de `tableau-contrat.cjs`.

## 3. Qui voit quoi

| Compte | Modules |
|---|---|
| administrateur | tous |
| gérant | opérations, clientèle, facturation, rapports, analytique, équipe, santé — `definir_role()` lui refuse toujours de créer ou modifier un administrateur |
| employé | ce que ses droits cochés ouvrent (`colis.lire` → opérations, `colis.statut` → Scanner, `factures.lire` → facturation, `clients.lire` → Clients, `roles.gerer` → Équipe) |
| chauffeur seul | Livraisons (ses missions), Tournées (les siennes), Pointage Express, Paramètres — rien d'autre (`driver_only`) |
| client | rien : `staff = false`, et `SES_API.accesTableauDeBord()` le renvoie avant même l'appel |

Un module n'apparaît que si la base l'ouvre **et** si le site sait dessiner au moins une de ses sections pour ce compte.

## 4. Le centre de commande

`lg_cc_command` rend onze cartes : colis à traiter, scans récents, arrivages, départs, douane, livraisons aujourd'hui, retards,
incidents, paiements en attente, tâches, alertes. Chaque carte porte `{key, module, count, severity, detail, items}` ; `module` est le
module qu'elle ouvre, et une carte n'est rendue que si ce module est ouvert au compte (la carte « Alertes » d'un chauffeur ouvre
Livraisons). Rafraîchissement : le signal temps réel (`ses_signal`) et la minuterie du centre.

## 5. Véhicules, tournées, dépenses

`lg_cc_vehicles`, `lg_cc_trips` (un chauffeur ne voit que les siennes, `mine_only`) et `lg_cc_expenses` (totaux par catégorie et par
statut calculés par la base).

## 6. Le Pointage Express

**Colis** — `lg_open_tally` fige une liste attendue (expédition, consolidation, entrepôt ou liste libre ; numéro `PTG-`).
`lg_tally_scan` pointe un code (clé d'idempotence) : `CHECKED`, `DUPLICATE`, `EXTRA` ou `UNKNOWN`. `lg_close_tally` rend attendus,
pointés, manquants, en trop. Une ligne ne se pointe qu'une fois ; un pointage clos ne change plus ; rien ne se supprime (`LG004`).

**Personnel** — `lg_clock` : arrivée, pause, reprise, départ, contrôlés par un automate (`LG004` sur un enchaînement impossible).
`lg_my_clock` rend la journée : minutes travaillées, minutes de pause, anomalies (`NO_OUT`, `DOUBLE_IN`, `SEQUENCE`). La direction lit
`lg_clock_report` (31 jours au plus) et corrige par `lg_clock_correct`, avec un motif obligatoire, en **ajout seul** (source
`CORRECTION`) : l'original reste.

## 7. Le site

- `assets/js/ses-modules.js` : les sections « temps-reel », « vehicules », « tournees », « depenses », « pointage », « mes-missions »,
  inscrites dans le centre (`SES_CENTRE.enregistrer`).
- `assets/js/ses-centre.js` : lit `lg_dashboard_access`, montre les onglets permis, dessine les puces des sections du module courant.
  Les sections s'inscrivent pendant le chargement : le centre attend la fin du chargement avant de décider quels onglets montrer.
- `SES_API.tableau` (`METHODES_TABLEAU`) : la démonstration répond « non autorisé », comme le centre ; le mode `off`, « fermé ».
- **Sans 019 (ou sans `centreNoyau`)** — la production d'aujourd'hui : `attendreNoyau` (`ses-centre.js`) montre quand même les modules
  que le compte ouvrira, d'après ses droits de l'ancien schéma (`colis.lire` → opérations, `colis.statut` → Scanner, `factures.lire` →
  Encaissements et Dépenses, direction → Analytique et Santé, tout membre → Pointage Express). Ils ouvrent le panneau `ses-p-attente` :
  l'étiquette « Bientôt disponible », ce que le module apportera (`c-bientot-<module>`), et **aucun chiffre** — il n'y en a pas encore de
  réels. Les modules de l'ancien schéma fonctionnent comme avant. Le jour où le centre démarre, ce mode ne s'enclenche plus.
- Textes : `outils/centre-textes.py` (familles `c-mod-`, `c-tr-`, `c-veh-`, `c-trip-`, `c-dep-`, `c-pt-`, `c-mm-`).

## 8. Retour en arrière

`019` **ajoute** (types d'événements, trois tables, fonctions et façades). Aucune fonction existante n'est redéfinie, rien n'est
supprimé.

| Besoin | Geste |
|---|---|
| revenir à l'ancien tableau de bord | éteindre `centreNoyau` dans `config.js` : les modules du noyau repassent en « Bientôt disponible » |
| retirer l'accès aux façades 019 | `revoke execute on function public.lg_dashboard_access(), … from authenticated` : le site retombe sur l'ancien tableau de bord |
| corriger un pointage du personnel | `lg_clock_correct` (jamais de mise à jour ni de suppression) |
