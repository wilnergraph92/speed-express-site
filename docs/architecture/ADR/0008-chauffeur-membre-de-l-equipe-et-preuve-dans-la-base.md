# ADR 0008 — Le chauffeur est un membre de l'équipe ; la preuve de livraison est exigée par la base
**Statut :** Proposée (5 octobre 2026)

## Contexte
Le dernier kilomètre ajoute des acteurs (chauffeurs) et une exigence forte : un colis ne doit pas être déclaré « livré » sans preuve. Or l'équipe n'est pas la clientèle (pas de profil client, pas de code `SES-#####`),
les rôles sont déjà quatre (client, employé, gérant, administrateur) et se gèrent dans la base.

## Décision
1. **Un chauffeur n'est pas un cinquième rôle** : c'est un **membre de l'équipe** (rôle inchangé) qui a, en plus, une **fiche chauffeur**. L'ancien schéma n'a rien à apprendre.
2. **Un droit étroit, `livraison`**, ouvre seulement trois transitions de colis (sortir en livraison, livrer, ramener au hub). Un chauffeur actif ne l'a **que pendant l'exécution d'une fonction de mission** ; il n'a
   jamais `colis.statut` ni `direction` et ne peut pas changer un statut par la façade générique.
3. **La preuve est exigée par la base** (déclencheur sur le statut du colis), pas par l'application : nom, signature **ou** photo, heure, GPS, et le code si la livraison l'exige. Seule la direction déroge, avec un
   motif, et la dérogation est tracée.
4. **Le code de livraison** n'est conservé que sous forme d'empreinte salée, part vers le **destinataire**, expire, est limité à cinq essais et n'est **jamais visible du chauffeur**.
5. **L'affectation est un moteur qui explique** : chaque chauffeur écarté a sa raison, chaque note son calcul ; forcer est réservé à la direction.

## Conséquences
+ aucun chemin, même un employé autorisé, ne livre sans preuve ; la preuve ne se modifie pas ;
+ pas de nouveau rôle à propager (cinq endroits à toucher, d'après `CLAUDE.md`) ;
− un chauffeur qui est aussi employé garde ses droits d'employé : **l'administrateur règle ses droits en conséquence** ;
− les colis encore sous l'autorité de l'ancien schéma ne sont pas soumis à la règle de preuve (rien ne change pour eux avant la bascule).

## Alternatives écartées
Un rôle `driver` dans `clients.role` : propage le changement dans le site, l'application et cinq endroits de la base ; exiger la preuve dans l'application : contournable.

## Quand la réexaminer
Quand l'application chauffeur existera et qu'on connaîtra ses besoins hors ligne ; si des tiers (sous-traitants) livrent.
