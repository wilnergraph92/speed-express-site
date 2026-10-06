# Analytique et rapports (phase 16)

> Statut : écrit et éprouvé sur PostgreSQL 16 jetable ; **non appliqué en production** ; recalcul planifié **non installé**.
> Source : `outils/logistique/012-analytique.sql`, `assets/js/ses-analytique.js`. Décision : [ADR 0014](ADR/0014-analytique-separee-faits-quotidiens-traces.md).

## 1. Le chemin d'un chiffre

```
journaux du noyau (ajout seul)  ──analytics.refresh(du, au)──▶  report_run (empreinte, état des sources)  +  daily_fact (jour, mesure, dimension, valeur)
                                                                              │
lg_an_report(grain, du, au)  ◀── somme des jours, de la DERNIÈRE exécution de chaque jour, filtrée par les droits du lecteur
lg_an_kpis(du, au)           ◀── idem, pour la période et la précédente de même longueur, plus les rapports calculés
lg_an_verify(n)              ◀── recalcule l'exécution n : REPRODUCIBLE · SOURCES_CHANGED · COMPUTATION_CHANGED
```

## 2. Les mesures (22)

| Domaine (droit) | Mesures | Dimension |
|---|---|---|
| Activité (`colis.lire`) | colis reçus, livrés · mis en attente, endommagés, perdus, retournés · heures de transit (somme) et colis au délai mesuré · expéditions parties, arrivées · missions terminées, échouées · scans, scans refusés · incidents signalés | mode (air, mer, route) · genre de mission · entrepôt · type d'incident |
| Finance (`factures.lire`) | revenus hors taxe · taxes · paiements reçus ($) et nombre · remboursements | catégorie de revenu · moyen de paiement |
| Clientèle (`clients.lire`) | nouveaux clients · tickets de support ouverts | — |

Rapports calculés par la base : **livraisons réussies** (missions de livraison terminées / terminées + échouées), **délai moyen de
transit** (heures / colis mesurés), **scans refusés** (%), **encaissé / facturé** (paiements / revenus). Une division par zéro rend « — ».

Définitions exactes : `select * from analytics.metric` (chaque mesure a sa phrase). Le jour est celui d'Haïti ; une livraison à 23 h 30
compte pour ce jour-là (le lendemain en UTC). Le transit se mesure en heures **réelles** (le passage à l'heure d'été retire une heure).

## 3. Utiliser

Centre de commande > **Analytique** : regrouper par jour, semaine, mois, trimestre ou année ; cartes avec la période précédente ; un tableau
par domaine ; « Exporter (CSV) » (les lignes de la base, sans formule possible) ; la source du rapport (n° d'exécution et empreinte) ; les
jours jamais calculés, avec « Calculer ces jours » pour la direction ; le journal des exécutions avec « Vérifier ».

Recalcul planifié (geste du propriétaire, après 001 à 012) — au choix :
- Supabase, extension **pg_cron** : `select cron.schedule('ses-analytique', '15 5 * * *', $$select public.ses_an_refresh()$$);`
- ou le travailleur (clé secrète) : `POST /rest/v1/rpc/ses_an_refresh` une fois par nuit.

Première mise en service : depuis le tableau de bord, « Recalculer la période » sur l'année en cours (367 jours au plus par calcul).

## 4. Vérifications

| Fichier | Ce qu'il prouve |
|---|---|
| `outils/tests/logistique-analytique-essai.py` (PostgreSQL jetable, 91) | une activité datée fait bouger exactement les chiffres attendus, calculés par un second chemin en Python (fuseau d'Haïti, heures réelles) ; grains = somme des jours (calendrier de Python) ; totaux ; reproductibilité, rattrapage détecté, calcul modifié détecté ; ajout seul ; droits par domaine ; jours manquants ; provisoire ; indicateurs et rapports ; schéma fermé, travailleur seul au recalcul planifié ; écrit `analytique-rpc.json` et `analytique-exemples.json` |
| mutations de 012 (30) | 27 détectées ; 3 équivalentes (le résultat ne change pas : `sum` ignore déjà les nuls, un filtre final borne les jours) |
| `outils/tests/analytique-contrat.cjs` (103) | trois implémentations ; signatures réelles ; refus avant appel ; écran sur réponses réelles, sans addition ni clé absente ; textes ; échappement ; CSV ; ordre de lecture |
| à l'écran (serveur d'essai) | français, espagnol, 375 px sans débordement ; « Vérifier » → « Reproductible » |
