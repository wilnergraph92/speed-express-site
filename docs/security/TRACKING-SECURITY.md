# Sécurité du suivi public — décision à prendre

> **Rien n'a été changé** : le format `SES-<n°>-<pays>` reste tel quel. Ce document expose la situation et les
> conséquences de chaque option pour que vous choisissiez. Une fois choisie, l'option devient un chantier avec
> migration, tests et impression d'étiquettes (§6).

## 1. Ce qui existe aujourd'hui **[PROD + CODE]**
`public.suivre_colis(p_numero, p_jeton default null)`, **ouverte sans connexion**. Elle exige un numéro d'au moins 4
caractères ; **le jeton du QR est facultatif**.

**Ce qu'elle rend** : numéro, statut, service, pays de destination, date de mise à jour, et l'historique (statut, lieu, date).
**Ce qu'elle ne rend jamais** : nom, adresse, téléphone, description, note, tarif, identifiant interne.

**Le numéro** : `SES-` + un compteur **séquentiel** (départ 10000) + `-` + `HT`, `DO` ou `US`. Il a deux propriétés :
1. **il se devine** : connaissant un numéro, on connaît ses voisins ; le pays n'a que 3 valeurs ;
2. **il révèle l'activité** : le plus grand compteur trouvé donne le nombre de colis enregistrés, et son rythme.

**Aucune limitation de débit** n'existe, ni dans la base ni autour (GitHub Pages n'en offre pas ; l'API Supabase n'en met pas par défaut sur cette fonction).

## 2. Ce qu'un attaquant obtient, concrètement
| Il peut | Gravité |
|---|---|
| parcourir tous les numéros et dresser la liste des colis en cours, leur statut, leur pays | **moyenne** : donnée commerciale |
| déduire votre volume d'envois, votre croissance, vos pics (concurrent) | **moyenne** |
| connaître les **lieux** successifs d'un colis (champ libre « lieu ») : si l'équipe y écrit une adresse précise ou un nom, il est lu | **à surveiller** |
| apprendre à qui appartient un colis | **non** : aucune donnée personnelle n'est rendue |
| retrouver un colis précis sans le connaître | **non** sans énumérer |

Le danger n'est donc pas la fuite de données personnelles ; c'est l'**énumération** (inventaire et espionnage de l'activité) et,
indirectement, le fait que quelqu'un qui connaît un numéro par hasard (une photo d'étiquette, un message transféré) voit tout son parcours.

## 3. Les trois options

### Option A — le numéro seul (situation actuelle, avec ou sans limitation)
Le visiteur tape son numéro, il voit son colis.
- **Pour** : aucun changement ; le client retrouve son colis avec ce qu'il a sous les yeux (SMS, WhatsApp, facture) ; pas d'étiquette à réimprimer.
- **Contre** : l'énumération reste possible ; rien ne la ralentit ni ne la détecte ; le compteur révèle l'activité.
- **Atténuations sans changer le format** : ne jamais mettre d'adresse ou de nom dans « lieu » (consigne à l'équipe) ; limiter le débit devant l'API (nécessite un domaine à vous derrière un service comme Cloudflare, voir `TARGET-ARCHITECTURE.md`) ; surveiller les journaux.

### Option B — le numéro **et** un jeton secret (le jeton du QR devient obligatoire)
Le suivi exige `numéro + jeton` (16 hexadécimaux déjà présents sur chaque colis et chaque étiquette). Le QR contient déjà les deux.
- **Pour** : énumérer devient **impossible** (le jeton fait 2⁶⁴ possibilités) ; les **étiquettes déjà imprimées marchent** (leur QR porte le jeton) ; coût de mise en œuvre faible (un contrôle dans la fonction).
- **Contre** : un client qui **ne connaît que le numéro** (reçu par WhatsApp, lu sur une facture) **ne peut plus suivre son colis en le tapant**. Il faut lui donner un **lien complet** (`suivi.html?colis=…&j=…`) partout où l'on donne aujourd'hui le numéro : messages WhatsApp, factures, notifications. Le formulaire manuel perd son sens, ou demande deux champs.
- **Risque résiduel** : un lien complet transféré donne accès à ce seul colis (voulu).

### Option C — un identifiant public non séquentiel, distinct de l'identifiant interne
Chaque colis reçoit un **code public aléatoire** (par exemple 10 caractères sans voyelles ambiguës : ≈ 10¹⁵ possibilités), celui que le client voit et tape. Le numéro séquentiel `SES-10001-HT` devient une **référence interne** (entrepôt, factures de l'équipe), et l'identifiant technique (`uuid`) reste séparé des deux.
- **Pour** : énumération **infaisable** sans jeton ; le compteur ne fuit plus ; le client garde un **code court à taper** ; un seul code à communiquer ; séparation propre (interne / référence / public), conforme au modèle du noyau (`parcel.id`, `tracking_number`, `public_token`).
- **Contre** : **chantier** : nouvelle colonne, génération, remplissage des colis existants, **nouvelle étiquette** (code-barres et QR), mise à jour du site, de l'application, du tableau de bord (recherche), des messages ; les colis **déjà étiquetés et en transit** portent l'ancien numéro : il faut une **période de transition** où l'ancien numéro reste accepté **avec** son jeton (option B) puis s'éteint ; **réimpression** pour les colis en cours.
- **Pour le noyau logistique** (phases 5 à 9) : c'est l'option naturelle, car le noyau sépare déjà ces trois identités.

## 4. Comparatif
| | A — numéro seul | B — numéro + jeton | C — code public aléatoire |
|---|---|---|---|
| Énumération | **possible** | impossible | impossible |
| Le client tape son code | oui | **non** (lien complet) | **oui** |
| Étiquettes déjà imprimées | valables | **valables** | à remplacer (transition possible) |
| Compteur / volume révélé | **oui** | non (si le numéro est masqué) | **non** |
| Effort | aucun | **faible** | élevé |
| Changement de format | aucun | aucun | **nouveau code** |
| Risque de rupture pour les clients | aucun | **élevé** (suivi manuel) | moyen (transition) |

## 5. Recommandation
**B maintenant, C ensuite.**
1. **B** apporte presque toute la protection pour un effort faible, sans réimprimer : on exige le jeton, on met le lien complet dans les messages et les factures. C'est réversible (un contrôle à retirer).
2. **C** s'intègre au chantier du noyau logistique (phase 7, étiquette de réception) : le code public naît avec la nouvelle étiquette, l'ancien numéro reste accepté avec son jeton le temps de la transition.
3. **Dans tous les cas** : consigne à l'équipe de ne rien écrire de personnel dans « lieu » ; vérifier ce qui y figure aujourd'hui.

## 6. Ce qui sera fait **quand vous aurez choisi**
- **A** : consigne « lieu » ; éventuellement limitation de débit (domaine requis). Aucune migration.
- **B** : une migration (la fonction exige le jeton) ; le site et les messages portent le lien complet ; des tests (numéro seul refusé, jeton faux refusé, lien valide accepté, étiquettes existantes valables) ; retour arrière = retirer le contrôle.
- **C** : colonne `public_code` (unique, aléatoire, sans ambiguïté de lecture), remplissage idempotent, accepte l'ancien numéro **avec jeton** pendant la transition, étiquette et recherche mises à jour, tests d'unicité et d'entropie, date d'extinction de l'ancien format.

**Aucune de ces trois voies n'est lancée.** Dites-moi **A**, **B** ou **C** (ou « B puis C »).
