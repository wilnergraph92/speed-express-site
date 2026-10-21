# La messagerie (étape 032)

> Demande du propriétaire (20/10/2026) : un chat interne entre le tableau de bord et les deux applications, pour une communication
> professionnelle et interne ; un chat direct avec le client, dans l'application ; messages directs, groupes, colis cités, photos.
> Source : `outils/logistique/032-messagerie.sql`. Essais : `logistique-messagerie-essai.py` (144), `messagerie-contrat.cjs` (156),
> `App_SES/tests/contrat-messagerie.cjs` (126).

## 1. Le principe

Comme tout le reste : le tableau de bord (module **Messagerie**), l'application client (**Messages**) et SES Opérations (onglet **Messages**)
parlent directement à Supabase par les **mêmes fonctions** `public.lg_chat_*`. Aucun serveur entre eux. La base décide, à chaque appel, qui
lit, qui écrit, qui gère un groupe, et compte les non-lus.

| Conversation | Qui la voit | Qui la crée |
|---|---|---|
| **DIRECT** | les deux membres de l'équipe, et eux seuls (même la direction ne la lit pas) | l'un ou l'autre ; une seule par paire |
| **GROUP** | ses membres actuels (retiré : il ne lit plus ; l'historique reste) | la direction (gérant, administrateur), qui ajoute, retire, renomme, archive |
| **CUSTOMER** | le client, et l'équipe qui lit les clients (`clients.lire`, comme le support) | le client (depuis l'application), ou l'équipe (annuaire) ; une seule par client |

Un client ne voit **jamais** une conversation interne, l'annuaire de l'équipe, ni sa propre fiche ; de qui lui répond, il ne voit que le
**prénom**. Un chauffeur (sans profil de terrain ou non) a l'onglet Messages : directs et groupes.

## 2. Les règles de la base

- Messages en **ajout seul** (`forbid_mutation`, LG004) ; chaque envoi porte une **clé d'idempotence** : un double appui ne fait qu'un message.
- Texte (4 000 caractères au plus), **colis cité** (son numéro) et **photo**. Un client ne cite que ses colis ; dans la conversation d'un
  client, l'équipe ne cite que les colis de **ce** client (sinon le numéro et le statut d'un autre lui seraient montrés).
- Un groupe archivé se lit, on n'y écrit plus.
- Débit limité (déclencheurs `ops_rate_limit`, LG007) : 600 messages et 60 conversations par heure et par compte.
- Chaque geste de la direction sur un groupe est au journal d'audit (`chat.group.create`, `chat.group.update`).

## 3. Les photos

Dossier **privé** `messagerie` du stockage (5 Mo, JPEG/PNG/WebP), rangé par conversation : `<conversation>/<clé de l'envoi>.jpg`. Les règles
du stockage (`ses_messagerie_depot`, `ses_messagerie_lecture`) n'ouvrent le dépôt et la lecture qu'à ceux qui lisent la conversation (et pas
de dépôt dans un groupe archivé). À l'envoi, la base vérifie que la photo est dans le dossier de **sa** conversation et déposée par **celui qui
l'envoie**. Une photo ne s'ouvre que par une adresse signée de dix minutes. Personne ne la remplace ni ne l'efface.

L'application client **n'embarque pas l'appareil photo** (elle ne demande jamais cette autorisation, `tests/variantes.cjs`) : elle montre les
photos reçues, elle n'en prend pas. L'équipe en prend depuis SES Opérations, ou en joint une depuis le tableau de bord. Ouvrir la photo au
client : une décision du propriétaire (autorisation de l'appareil photo dans l'application client, déclarations des magasins, nouvelle construction).

## 4. Le temps réel

`public.ses_chat_signal` : une ligne par destinataire, **sans aucune donnée** (pas même la conversation) ; chacun ne lit que les siennes. L'écran
relit sa boîte et le fil ouvert. Purgé au passage (deux jours). Les applications relisent aussi toutes les 30 secondes (fil) et deux minutes
(pastille) si un signal s'est perdu.

## 5. Les façades

`lg_chat_inbox`, `lg_chat_unread`, `lg_chat_messages`, `lg_chat_send`, `lg_chat_mark_read`, `lg_chat_directory`, `lg_chat_open_direct`,
`lg_chat_open_customer`, `lg_chat_create_group`, `lg_chat_update_group`. Changer l'une d'elles : relancer `logistique-messagerie-essai.py`
avec `SES_FORME_ECRIRE=1`, recopier `messagerie-exemples.json` dans `App_SES/tests/exemples-messagerie.json`, y lancer `npm run essai`.

Le module **Messagerie** s'ajoute à `dashboard_access` pour toute l'équipe (27 modules dans la base). Seulement en ligne : la démonstration et le
site fermé refusent (une conversation inventée serait une fausse conversation).

## 6. Ce qui n'est pas fait

- **Notifications push et e-mail** d'un nouveau message : elles passeront par le centre de notifications (027) quand le travailleur d'envoi sera
  installé ; aujourd'hui, la pastille et le temps réel dans l'application ouverte.
- La gestion d'un groupe (membres, archivage) se fait depuis le tableau de bord ; l'application SES Opérations crée un groupe et y écrit.
- Les applications mobiles doivent être **reconstruites** pour recevoir ces écrans.
