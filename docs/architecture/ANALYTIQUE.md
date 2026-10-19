# Analytique, rapports et alertes (phase 16, complétée en phase 12 par l'étape 029)

> Statut : 012 en production ; **029 écrite et éprouvée** sur PostgreSQL jetable (passe en production par l'outil de migration) ; recalcul
> planifié installé par `interrupteurs.py analytique-planifier` (pg_cron, dans la base).
> Sources : `outils/logistique/012-analytique.sql`, `outils/logistique/029-analytique-complete.sql`, `assets/js/ses-analytique.js`.
> Décision : [ADR 0014](ADR/0014-analytique-separee-faits-quotidiens-traces.md).

## 1. Le chemin d'un chiffre

```
journaux du noyau (ajout seul)  ──analytics.refresh(du, au)──▶  report_run (source, version + empreinte du code, empreinte des faits, état des sources)
                                                                 + daily_fact (jour, mesure, dimension, valeur)
                                                                 + alert (ce que le calcul révèle : KPI impossible, données manquantes, anomalie)
lg_an_report(grain, du, au)  ◀── analytics.aggregate : chaque mesure agrégée selon SA nature (sum / end / distinct), dérivés par période
lg_an_kpis(du, au)           ◀── idem, pour la période et la précédente de même longueur
lg_an_verify(n)              ◀── recalcule l'exécution n : REPRODUCIBLE · VERSION_CHANGED · SOURCES_CHANGED · COMPUTATION_CHANGED
lg_an_alerts / lg_an_ack_alert ◀── les alertes ouvertes (par domaine), acquittées par la direction
```

**Règle absolue** : aucun chiffre n'est calculé dans le navigateur — ni total, ni stock, ni nombre de clients distincts, ni taux, ni marge.
`analytique-contrat.cjs` refuse toute addition ou division dans `ses-analytique.js`.

## 2. Les mesures (42) et leurs familles

| Famille (droit) | Mesures | Dimension |
|---|---|---|
| **Opérations** (`colis.lire`) | colis reçus, livrés, mis en attente, endommagés, perdus, retournés · **en transit** et **en retard** (stocks) · heures de transit et colis au délai mesuré · scans, scans refusés, **scans par usage** · incidents | mode · entrepôt · usage · type |
| **Transport** (`colis.lire`) | expéditions **créées**, parties, arrivées, **en retard** (stock) · arrivées **avec date prévue** et **à l'heure** · **heures de transport** et expéditions au délai mesuré | mode |
| **Dernier kilomètre** (`colis.lire`) | missions terminées, échouées · **livraisons réussies / échouées par chauffeur, par zone, par tournée** · **livraisons à l'heure** | genre · chauffeur · zone · tournée |
| **Finance** (`factures.lire`) | revenus hors taxe, taxes · paiements ($ et nombre) · remboursements · **dépenses** · **reste dû** (stock) | catégorie · moyen |
| **Clientèle** (`clients.lire`) | nouveaux clients · tickets · **clients actifs** · **clients ayant expédié** (distincts) | — (jamais par client à l'écran) |

En gras : ajoutées par 029. Définitions exactes : `select code, family, aggregation, definition from analytics.metric`.

### Trois agrégations, décidées par la base

| `aggregation` | Exemple | Une semaine vaut… |
|---|---|---|
| `sum` (flux) | colis reçus | la somme de ses jours |
| `end` (stock à minuit, heure d'Haïti) | colis en transit, reste dû | son **dernier** jour (borné à la fin du rapport) ; inconnu (`null`, « — ») si ce jour n'a jamais été calculé |
| `distinct` | clients actifs | le nombre de clients **distincts** de la semaine (actif lundi et mardi = 1 client) |

Le statut d'un colis, d'une mission ou d'une expédition « à minuit » est le dernier de son historique **avant** minuit : un colis livré à
0 h 00 pile le 4 est encore en transit à la fin du 3. Seuls les rendez-vous (fenêtre d'une mission, arrivée prévue d'un transport) sont lus tels
qu'ils sont aujourd'hui : replanifier change après coup ce qui était « en retard ». Les journaux n'ayant pas bougé, la vérification d'une
exécution ancienne dit alors « le calcul a changé » : c'est le rendez-vous qui a changé, pas le code (l'empreinte du code le prouve).

### Les indicateurs dérivés (calculés par la base, pour chaque période d'un rapport)

| Famille | Indicateurs |
|---|---|
| Opérations | délai moyen de transit (h) · scans refusés (%) |
| Transport | expéditions à l'heure (%) · délai moyen des expéditions (h) |
| Dernier kilomètre | livraisons réussies (%) · livraisons à l'heure (%) |
| Finance | facturé taxes comprises · encaissé / facturé (%) · encaissé net · marge (revenus − dépenses) · taux de marge |
| Clientèle | fréquence : colis par client ayant expédié |

Une division par zéro rend `null`, affiché « — », jamais 0.

## 3. La traçabilité

| Champ | Où | Sens |
|---|---|---|
| horodatage | `report_run.generated_at`, `report.generated_at` | quand le calcul, puis le rapport, ont été faits |
| source | `report_run.source` | `manual` (direction), `scheduler` (pg_cron), `worker` (clé secrète) |
| période | `period_start`, `period_end`, `report.from/to` | |
| version de calcul | `calc_version` (`029`) + `calc_fingerprint` (md5 du code de `compute_facts`) | l'empreinte change seule si le code change ; le numéro se monte à la main avec le code |
| empreinte | `checksum` (faits de l'exécution), `report_checksum` (lignes et totaux du rapport) | |
| statut de génération | `COMPLETE`, `PROVISIONAL` (touche aujourd'hui) ; rapport : `INCOMPLETE` (jours jamais calculés), `OUTDATED` (jours calculés par une version antérieure) ; échec : `analytics.run_failure` | |
| sources | `report.sources`, `report_run.source_watermark` | les journaux lus, et combien de lignes ils comptaient |

Les exécutions d'avant 029 restent lisibles (version « 012 ») ; leurs jours sont signalés « à recalculer », et leur vérification rend
`VERSION_CHANGED`.

## 4. Les alertes

| Code | Levée par | Quand |
|---|---|---|
| `KPI_IMPOSSIBLE` | chaque calcul, jours clos | délai de transit sans aucune réception connue ; encaissement ou marge sans revenu ; ponctualité sans arrivée prévue |
| `DATA_MISSING` | calcul ; veille | colis livrés sans réception connue ; livraisons sans chauffeur ; jour clos jamais calculé (7 derniers) ; jour calculé par une ancienne version |
| `ANOMALY` | chaque calcul | une mesure surveillée s'écarte de la moyenne des 28 jours calculés précédents de plus de 3 écarts-types ET d'un plancher (5 unités, 100 $, 24 h), avec au moins 14 jours d'historique |
| `REFRESH_NOT_RUN` | veille (chaque heure) | aucun calcul depuis 26 h (grave au-delà de 72 h, ou jamais) |
| `REFRESH_FAILED` | recalcul planifié | une exception : journalisée dans `analytics.run_failure`, battement de cœur `FAIL` |

Sans doublon (une clé par fait signalé), en ajout seul ; l'acquittement (direction, avec une note) est lui aussi en ajout seul. La santé du
système (013) gagne deux contrôles : `analytics_open_alerts` et `analytics_failures_24h`.

## 5. Utiliser

Centre de commande > **Analytique** : choisir un **rapport** (quotidien, hebdomadaire, mensuel, trimestriel, annuel — jusqu'à aujourd'hui) ou une
**période personnalisée** et son regroupement ; l'en-tête dit le statut, la version, l'empreinte et les exécutions ; cartes par famille avec la
période précédente ; un tableau par famille, ses indicateurs dérivés sous les mesures ; le détail par chauffeur, zone et tournée ; les alertes
(« Acquitter » pour la direction) ; « Exporter (CSV) » (la traçabilité en tête, puis les lignes de la base, sans formule possible) et
« Exporter (PDF) » (le même rapport sur A4, par la boîte d'impression du navigateur ou de l'application de bureau) ; le journal des exécutions
avec « Vérifier ».

### Le recalcul planifié

Workflow privé « Interrupteurs du noyau », commande **`analytique-planifier`** (après la migration 029) : inscrit dans pg_cron
- `ses-analytique` — `20 5 * * *` (0 h 20 à Haïti en hiver) — `analytics.scheduled_refresh()` : hier, aujourd'hui, et tout jour de l'année
  écoulée jamais calculé ou calculé par une version antérieure (367 jours au plus par passage), puis la veille, puis le battement de cœur ;
- `ses-analytique-veille` — `50 * * * *` — `analytics.watch()` ;

puis lance un premier recalcul. `analytique-deplanifier` les retire (les chiffres et les alertes restent). `etat` dit si elles sont inscrites.
Le travailleur (clé secrète) peut aussi appeler `ses_an_refresh()` : sans période, c'est le même recalcul planifié.

## 6. Vérifications

| Fichier | Ce qu'il prouve |
|---|---|
| `outils/tests/logistique-analytique-essai.py` (91) | 012 seule : faits quotidiens au second chemin Python, grains, reproductibilité, droits, portes |
| `outils/tests/logistique-analytique-complete-essai.py` (85) | 001 → 029 : passage de 012 (OUTDATED, VERSION_CHANGED, veille, reprise par le recalcul planifié) ; chaque nouvelle mesure = second chemin (minuit pile, retards, ponctualité, chauffeurs, zones, tournées, dépense annulée, reste dû) ; stock = dernier jour, clients distincts ; dérivés ; en-tête et empreintes ; alertes (les cinq genres), sans doublon, en ajout seul, par domaine, acquittement ; échec planifié journalisé ; santé ; portes ; écrit `analytique-complete-rpc.json` et `analytique-complete-exemples.json` |
| `outils/tests/migration-essai.py` | `interrupteurs.py analytique-planifier` / `deplanifier` sur un planificateur de même forme que pg_cron |
| `outils/tests/analytique-contrat.cjs` (191) | sept méthodes, trois implémentations ; écran sur les réponses réelles de 029 sans calcul ni clé absente ; familles, indicateurs, statuts, sources, alertes et sujets nommés ; droits à l'écran ; bornes des rapports types ; CSV et PDF avec la traçabilité |
