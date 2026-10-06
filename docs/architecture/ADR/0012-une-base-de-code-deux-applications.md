# ADR 0012 — Une base de code, deux applications, deux racines de routes ; la base décide du profil et rejoue les gestes hors connexion
**Statut :** Proposée (6 octobre 2026). Précise l'[ADR 0005](0005-applications-operations-expo-et-bureau-web.md), sans la remplacer.

## Contexte
La phase 14 demande une application mobile pour les profils CUSTOMER, DRIVER, WAREHOUSE_AGENT et DELIVERY_AGENT : stockage sécurisé,
notifications, caméra, codes-barres et QR, GPS, file hors connexion, synchronisation, la base restant source de vérité. L'ADR 0005 a fixé
deux applications Expo (client, « Opérations ») et une règle : **les fonctions du personnel ne partent pas dans une application que tout
client installe**. L'application client existe déjà (`App_SES`, dépôt privé, Expo SDK 57) ; recopier son socle (session chiffrée, langue,
thème, polices) dans un second dépôt doublerait chaque correction.

## Décision
1. **Un dépôt, deux variantes** fixées à la construction : `APP_VARIANT=operations` (`app.config.ts`). Sans variable, l'application
   client, **inchangée** : mêmes identifiants (`com.speedexpressshipping.app`), mêmes écrans. La variante « Opérations » a ses identifiants
   (`com.speedexpressshipping.operations`), son nom, son lien profond, et seule elle configure la caméra et la position.
2. **Deux racines de routes** : `src/app` (client) et `src/app-operations` (équipe, choisie par `extra.router.root`). Metro n'empaquette que
   la racine de la variante et ce qu'elle importe : le paquet client ne contient **aucun** écran ni module de l'équipe — vérifié par
   `tests/variantes.cjs`, qui suit les imports de `src/app` de proche en proche. Le socle commun (`src/api`, `src/design`, `src/i18n`,
   `src/ecrans/Connexion.tsx`) est partagé.
3. **La base décide du profil** : `lg_my_staff_profile()` (migration 011) rend `staff`, les profils (DRIVER si fiche chauffeur active ;
   WAREHOUSE_AGENT et DELIVERY_AGENT selon le droit `colis.statut` et le type de succursale), les entrepôts. L'application n'en fait que
   des onglets ; un client, ou un membre sans rôle de terrain, voit pourquoi il ne peut rien y faire. La session refuse un compte client
   dans « Opérations », comme l'application client refuse un compte d'équipe.
4. **Une seule porte pour les gestes du terrain** : `lg_mobile_command(clé, commande, arguments)`. Chaque geste reçoit sur le téléphone une
   clé unique, est gardé dans une file chiffrée (trousseau du système), et part dès que le réseau le permet ; rejouée, la clé rend le
   résultat d'origine sans rien refaire ; la même clé pour un autre geste est refusée (LG006) ; un refus ne consomme pas la clé. Les
   lectures (missions, tournées) et les gestes de répartition (attribuer, émettre un code) se font **en ligne seulement** : décider à
   l'aveugle sur un tableau périmé ferait plus de mal qu'attendre le réseau.
5. **Preuve de livraison** : nom, code à 6 chiffres si exigé, position, photo. La photo est déposée dans le dossier privé `preuves` du
   stockage, sous `pod/<mission>/<clé du geste>.jpg` (un nouvel essai réécrit au même endroit) ; seul un chauffeur actif peut y déposer,
   personne ne lit ni ne supprime depuis un téléphone. C'est la base qui vérifie le code et accepte la preuve.
6. **Position** : seulement pendant une mission commencée, application ouverte (« pendant l'utilisation ») ; jamais en arrière-plan ;
   une position ancienne rejouée ne remplace jamais une plus récente.
7. **Contrat vérifié des deux côtés** : le test PostgreSQL du site écrit les signatures (`applications-rpc.json`) et les formes réelles des
   réponses, des commandes, des intentions de scan, des verdicts et des statuts (`applications-formes.json`) ; l'application en garde une
   copie (`tests/rpc-noyau.json`, `tests/formes-noyau.json`) et `tests/contrat-rpc.cjs` y compare ses appels, ses types et ses gestes.

## Conséquences
+ une correction du socle (session, langue, thème) profite aux deux applications ; aucune ligne de l'équipe chez les clients ;
+ un geste fait sans réseau n'est jamais perdu ni fait deux fois ; le téléphone ne décide jamais d'une règle métier ;
− les modules natifs caméra et position sont **liés** dans les deux binaires (une seule liste de dépendances) : dans l'application client,
  leurs permissions Android sont bloquées et iOS reçoit un texte d'usage honnête (« n'utilise pas »), exigé dès qu'un module est lié ;
− deux fiches de magasin ; « Opérations » peut être distribuée en privé (TestFlight, test interne Google Play) ;
− les types de routes d'Expo ne décrivent qu'une racine à la fois : les adresses de « Opérations » sont déclarées `Href`.

## Alternatives écartées
Un second dépôt (socle dupliqué) ; un seul binaire avec les écrans de l'équipe cachés (contraire à l'ADR 0005 : le code partirait chez
chaque client) ; des gestes hors connexion par appels directs aux fonctions métier (pas d'idempotence de bout en bout).

## Quand la réexaminer
Si les deux applications divergent au point que le socle commun devient une contrainte ; si un module natif doit être exclu du binaire
client (liaison sélective par variante).
