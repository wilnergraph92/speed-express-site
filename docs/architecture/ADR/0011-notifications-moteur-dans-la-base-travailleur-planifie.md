# ADR 0011 — Notifications : le moteur dans la base, l'envoi par un travailleur planifié, le temps réel par un signal sans donnée
**Statut :** Proposée (6 octobre 2026)

## Contexte
La phase 13 demande des notifications multi-canal (portail, téléphone, e-mail ; WhatsApp et SMS en architecture), des modèles, des
relances, l'idempotence, un journal de livraison, et du temps réel pour le tableau de bord, le suivi, le chauffeur, la livraison et
l'entrepôt. Contraintes : aucune nouvelle pile sans ADR ; aucun secret dans le dépôt ni dans un navigateur ; une panne d'envoi ne doit
jamais bloquer une opération (défaut d'origine : un appel HTTP dans un déclencheur, `DATABASE.md` §7.7).

## Décision
1. **Le moteur est un abonné interne du moteur d'événements** (phase 6, ADR 0003) : règle par événement × modèle traduit × préférence du
   client × canal allumé × destinataire joignable. Il travaille **hors** de la transaction métier ; `unique (event_row_id, channel)` rend tout
   rejeu inoffensif. Le texte est **figé** à la création, dans la langue du client.
2. **Les modèles sont les textes du portail** (`outils/portail-textes.py` écrit les deux) : un e-mail dit exactement ce que le client lit
   dans son espace, dans les quatre langues.
3. **L'envoi est un travailleur Node sans dépendance** (`scripts/notifications/envoyer.mjs`) lancé par **GitHub Actions** — deux outils déjà
   en service ici (déploiement, sauvegarde) : pas de nouvelle pile. Il réclame avec un **bail** (`for update skip locked`), envoie (Brevo pour
   l'e-mail, Expo pour le téléphone), rend compte ; la base décide : envoyée, relance avec attente doublée, échec définitif au maximum
   d'essais du canal. Chaque essai a sa ligne (journal en ajout seul). Sa façade (`public.ses_nt_*`) n'est exécutable que par la clé
   secrète ; son modèle de workflow n'est **pas** installé (`scripts/notifications/modele-workflow-notifications.yml`) : l'activation est un
   geste explicite du propriétaire.
4. **SMS et WhatsApp sont déclarés, éteints** : rien n'est créé pour un canal éteint. Le code de livraison, prévu pour WhatsApp, est
   **relayé** au portail et à l'e-mail du client tant que WhatsApp n'a pas de fournisseur.
5. **Le temps réel est un signal sans donnée** : une ligne `public.ses_signal` (audience, sujet) par événement, lue par le temps réel de
   Supabase sous sécurité par ligne (un client : les siens ; l'équipe : ceux de l'équipe). L'écran **relit** par les fonctions qui contrôlent
   les droits. Une erreur d'écriture du signal est avalée : elle ne peut pas annuler l'opération.

## Conséquences
+ aucune notification ne peut bloquer un colis, une facture ou une livraison ; une panne du moteur se rattrape seule (relance d'événement) ;
+ aucune donnée métier ne transite par le temps réel ; aucune clé secrète n'approche un navigateur ;
+ les envois sont mesurés (santé par canal dans le centre de commande, journal par essai) ;
− latence d'envoi = période du travailleur (5 minutes proposées) ; l'e-mail et le téléphone ne sont pas instantanés ;
− GitHub Actions planifié peut être retardé aux heures chargées : acceptable pour des notifications d'information, pas pour un code de
  livraison urgent (d'où le relais immédiat au portail) ;
− l'application mobile actuelle enregistre ses jetons dans `public.appareils` ; le rattrapage les recopie dans `logistics.device`.

## Alternatives écartées
Edge Functions de Supabase : Deno n'est ni en service ici ni testable sur ce poste ; à réexaminer si la latence compte. Envoyer depuis un
déclencheur : le défaut que la phase 6 a supprimé. Diffuser les données par le temps réel : fuite assurée au premier filtre oublié.
Un fournisseur SMS/WhatsApp choisi maintenant : coût et contrat à décider par le propriétaire.

## Quand la réexaminer
Si la latence de cinq minutes gêne (passer à une Edge Function ou à `pg_cron` + `pg_net`) ; au choix d'un fournisseur SMS/WhatsApp ; si le
volume dépasse quelques milliers de notifications par jour.
