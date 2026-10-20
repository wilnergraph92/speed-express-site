# La bascule des colis : le noyau, source de vérité (étape 030)

> Statut : écrite et éprouvée sur la réplique de la production (`logistique-colis-noyau-essai.py`, `colis-noyau-contrat.cjs`).
> Interrupteur `colisNoyau` de `config.js` : **éteint** tant que le propriétaire ne l'a pas allumé après sa recette (§5).
> Source : `outils/logistique/030-colis-noyau.sql`. Décisions du propriétaire du 19/10/2026 :
> - tous les écrans sont des clients qui parlent directement à Supabase, par les mêmes fonctions ;
> - un colis ne s'efface plus, il s'annule ;
> - la facturation reste celle de l'ancien schéma jusqu'à la bascule de la Finance (031).

## 1. Avant, après

| | Avant (interrupteur éteint) | Après (allumé) |
|---|---|---|
| Créer un colis | le tableau de bord écrit dans `public.colis` ; le noyau en reçoit une copie chaque minute | `lg_create_parcel` : ancien schéma (numéro, jeton, facture : règles inchangées) **et** noyau, dans la même transaction |
| Modifier | écriture directe dans `public.colis` | `lg_update_parcel` (la facture suit, comme avant ; statut et lieu refusés par ce chemin) |
| Changer de statut | l'un des cinq statuts d'avant, écrit dans `public.colis` | `lg_parcel_next_steps` puis `lg_move_parcels` : les étapes de la machine d'états du noyau, chaque refus avec sa raison |
| Supprimer | `delete` de la ligne | **Annuler** : `lg_cancel_parcel`, motif obligatoire, direction seulement ; rien n'est effacé |
| Suivi public | `suivre_colis` (ancien schéma) | `ses_track` : même règle (numéro ; jeton du QR code vérifié s'il est donné), parcours du noyau, et la forme de l'ancien suivi |
| Profil (site, application) | écriture directe dans `public.clients` | `lg_update_my_profile` : seulement les champs du profil |
| Historique dans la fiche colis | `colis_historique` | le journal du noyau (`lg_cc_parcel`) |

## 2. Le reflet

Le noyau décide du statut. Chaque statut est recopié dans `public.colis` (statut ramené aux cinq d'avant, et lieu) par le déclencheur
`reflet_ancien_schema` ; c'est ce que lisent encore l'onglet Colis, l'ancienne facturation et les anciens écrans.

| Noyau | Ancien schéma |
|---|---|
| `CREATED` … `READY_FOR_EXPORT` | `confirme` |
| `LOADED` … `CUSTOMS_CLEARED` | `expedie` |
| `AT_DESTINATION_HUB`, `DELIVERY_ASSIGNED`, `OUT_FOR_DELIVERY`, `FAILED_DELIVERY` | `disponible` |
| `DELIVERED` | `livre` |
| `ON_HOLD`, `DAMAGED`, `LOST`, `RETURNED`, `CANCELLED` | `action` |

Pendant le reflet (et pendant toute modification d'un colis déjà sous l'autorité du noyau), la variable de transaction `ses.reflet` vaut
`on`. Deux déclencheurs de l'ancien schéma se taisent alors, grâce à une condition `WHEN` sur leur déclencheur (et non dans leur code) :
- `historiser_colis` : l'ancien historique deviendrait, à la recopie, des événements **en double** dans le journal du noyau. Une étape serait comptée deux fois dans l'Analytique, et un faux « Enregistré » apparaîtrait au milieu d'un parcours ;
- `prevenir_client` : l'ancienne notification push préviendrait le client une seconde fois.

**Un reflet en échec ne bloque jamais le noyau** : il est journalisé (`logistics.sync_failure`, table `colis_reflet`), la santé du système
le voit (contrôle `parcel_reflection_gaps`), et le reflet suivant le résorbe.

## 3. Ce qui ne change pas

- La facture d'un colis naît, se recalcule et se fige exactement comme avant (`facturer_colis`). Annuler un colis ne touche pas à sa facture : elle se gère dans l'onglet Factures.
- Un colis créé avant la bascule reste sous l'autorité de l'ancien schéma jusqu'à sa première étape dans le noyau. À ce moment, il passe sous l'autorité du noyau, pour de bon.
- Les écrans du centre de commande, du portail, des applications : déjà sur le noyau.

## 4. Points d'attention

- **Entrepôts** : la réception et la vérification exigent un entrepôt, le rangement un emplacement. Sans agence ni entrepôt saisis (Entrepôts › Agences et entrepôts), le formulaire le dit, et aucun colis ne peut être reçu.
- **Annulation** : direction seulement, depuis les étapes qui la permettent (avant le départ, ou après une mise en attente).
- **Rattrapage** : il ne touche jamais au statut d'un colis sous l'autorité du noyau ; il continue de recopier ses autres champs.

## 5. Mise en service

1. Migration 030 (outil de migration, sauvegarde vérifiée avant). Interrupteur éteint : aucun effet visible.
2. Site en ligne (cache v64), interrupteur éteint.
3. Saisir au moins une agence, un entrepôt et un emplacement.
4. **Recette du propriétaire**, interrupteur allumé sur une copie locale ou en accord avec lui :
   - créer un colis (numéro, étiquette, facture) ;
   - le recevoir, le vérifier, le ranger ;
   - le suivre sur la page Suivi (avec et sans le QR code) ;
   - l'annuler (direction) ;
   - modifier son profil.
5. Allumer `colisNoyau` (une PR sur `config.js`), puis surveiller `parcel_reflection_gaps` dans la Santé.
6. Application mobile : nouvelle construction. Le suivi public et le profil passent par le noyau, avec un repli si la base n'a pas la fonction.

Retour en arrière : éteindre `colisNoyau` (une PR). Les colis déjà sous l'autorité du noyau le restent, et leur reflet continue. Rien n'est
à défaire dans la base.

## 6. Vérifications

| Fichier | Ce qu'il prouve |
|---|---|
| `outils/tests/logistique-colis-noyau-essai.py` (75) | réplique de la production, 001 → 030, recopie allumée. Il prouve, dans l'ordre : création immédiate dans les deux mondes, avec la facture de toujours ; modification et facture qui suit ; étapes permises par droit, entrepôt et emplacement demandés ; reflet sans historique ni doublon d'événement ; Analytique comptée une fois ; une note après la bascule ne crée pas de faux événement ; lot avec un refus motivé ; annulation (motif, direction, rien d'effacé) ; reflet en échec non bloquant et visible ; suivi public sans donnée personnelle ; profil sans rôle ; rattrapage prêt ; rejeu sans effet ; portes. |
| `outils/tests/colis-noyau-contrat.cjs` (83) | éteint, rien ne change ; allumé, les sept fonctions avec leurs paramètres réels ; démonstration sans noyau ; réponses réelles ; écran |
| `App_SES/tests/contrat-colis-noyau.cjs` (13) | suivi public et profil de l'application par les mêmes fonctions, repli seulement si la fonction manque |
