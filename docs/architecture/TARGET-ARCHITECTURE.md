# Architecture cible — Speed Express Shipping

> Proposée le 5 octobre 2026. Elle part du système **réel** décrit dans
> `ARCHITECTURE-BASELINE.md` et ne remplace aucune brique sans ADR. Chaque décision
> porte son ADR ; sans objection du propriétaire, elle s'applique.

## 1. Principe
**Une seule logique métier, plusieurs interfaces.** Les règles (qui peut faire quoi,
quelles transitions sont permises, comment un prix se calcule) vivent **dans la base**,
derrière une façade de fonctions. Le site, l'application client, l'application des
opérations et le bureau ne font qu'afficher et appeler.

```
                        SPEED EXPRESS PLATFORM
                                 │
                          LOGISTICS CORE
              schéma « logistics » dans PostgreSQL (Supabase)
        règles · machine d'états · événements · audit · finance
                                 │
                 façade d'appels  public.lg_*  (RPC, versionnée)
                                 │
     ┌───────────────┬───────────┴───────────┬──────────────────┐
     │               │                       │                  │
  PORTAIL WEB     APPLICATION             OPÉRATIONS         INTÉGRATIONS
  site + espace   MOBILE CLIENT        entrepôt · chauffeur  notifications, douane,
  client, tableau  (Expo)              (Expo, + export web   paiement, e-mail
  de bord                              pour le bureau)       (Edge Functions)
     │               │                       │                  │
     └───────────────┴──── PostgreSQL ───────┴──────────────────┘
                              │
               Événements (outbox) · File · Stockage de fichiers
```

## 2. Décisions par sujet

| Sujet | Décision | ADR |
|---|---|---|
| Base de données | **PostgreSQL / Supabase reste le cœur.** Nouveau schéma `logistics` ; l'ancien schéma `public` n'est pas touché | 0001 |
| Backend | **« Postgres d'abord »** : règles en fonctions SQL. Pas de serveur Node à maintenir. Les *Edge Functions* ne servent qu'à ce qui sort de la base (push, API de douane, PDF) | 0002 |
| API | PostgREST + **façade `public.lg_*`** : seules ces fonctions sont publiques ; les tables du noyau ne sont jamais exposées | 0002 |
| Vocabulaire | noyau en **anglais** (Parcel, Shipment…), libellés affichés en 4 langues, anciennes tables inchangées | 0004 |
| Événements | **boîte d'envoi transactionnelle** (`domain_event`) écrite dans la même transaction que le changement d'état | 0003 |
| Temps réel | Supabase Realtime sur `tracking_event`, filtré par les règles de sécurité | 0003 |
| File d'attente | réclamation `FOR UPDATE SKIP LOCKED` sur l'outbox, relances et file des échecs ; réexamen au-delà d'un seuil (§4) | 0003 |
| Authentification | **Supabase Auth, inchangé** | — |
| Autorisation | RLS + droits par rôle ; portée par succursale ajoutée avec `Branch` | 0002 |
| Stockage | Supabase Storage, **compartiments privés**, liens signés ; photos de colis et preuves de livraison (phases 7 et 9) | 0002 |
| Notifications | consommateur de l'outbox → Edge Function d'envoi (push Expo, puis e-mail) ; WhatsApp reste un lien | 0003 |
| Mobile | Expo ; **deux applications** : client (existante) et **opérations** (entrepôt + chauffeur), pour séparer ce qui est réservé au personnel | 0005 |
| Bureau | **navigateur** (export web de l'app opérations ; un scanner USB se comporte comme un clavier). Pas d'Electron tant qu'un besoin matériel ne l'impose | 0005 |
| Surveillance | profondeur de la file d'échecs, événements bloqués, journal des sauvegardes, journaux Supabase ; suivi d'erreurs des applications ensuite | — |
| Migration | **étranglement progressif** (strangler) : on ajoute, on remplit, on double-écrit, on bascule ; rien ne disparaît sans sauvegarde et accord | 0006 |

## 3. Ce que l'on ne fait volontairement pas
- Pas de **microservices**, pas de bus de messages externe, pas de nouveau langage serveur : l'équipe est réduite, les données ont besoin de transactions, PostgreSQL les donne.
- Pas de **Prisma ni d'ORM** : le schéma est géré par migrations SQL rejouables et testées sur PostgreSQL réel.
- Pas de **calcul de prix, de statut ou de droit dans un navigateur** : il y est affiché, jamais décidé.
- Aucun **remplacement** du site statique ni de l'application client.

## 4. Seuils de réexamen (quand une décision cesse d'être bonne)
| Décision | On la réexamine si… |
|---|---|
| File = table `domain_event` | plus de ~50 événements/s soutenus, ou besoin de messages différés/planifiés précis → `pgmq` ou file dédiée |
| Tout dans PostgreSQL | un traitement dépasse quelques secondes (génération massive, optimisation de tournées) → travailleur externe |
| Un seul projet Supabase | besoin de préproduction (déjà un manque, voir baseline R10) → second projet pour les essais |
| Edge Functions pour l'I/O | un partenaire impose un protocole que la plateforme ne tient pas |
| Application opérations en Expo | un matériel (imprimante, scanner embarqué) n'est pas pilotable |

## 5. Qualités visées
Cohérence avant tout (transactions, une seule source de vérité) ; **traçabilité** de chaque
opération (événement + audit) ; **réversibilité** (chaque étape de migration a un retour arrière) ;
**testabilité** (tout se prouve sur PostgreSQL jetable) ; **sobriété** (le moins de pièces à surveiller).
