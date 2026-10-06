# Sécurité — Speed Express Shipping

## Signaler un problème
Écrivez à **speedexpresshipping@gmail.com** (objet : « Sécurité ») ou ouvrez un signalement privé de vulnérabilité
sur ce dépôt (*Security › Report a vulnerability*). **Ne publiez pas** le détail d'une faille dans un ticket public.
Donnez : ce que vous avez fait, ce que vous attendiez, ce qui s'est passé. Ne cherchez jamais à lire ou modifier des
données de vrais clients : un signalement fait de bonne foi, sans accès aux données, ne donnera lieu à aucune poursuite.

## Ce que le système protège, et comment (chaque ligne est vérifiée par un test)
| Protection | Mécanisme | Test |
|---|---|---|
| Un client ne voit que ses colis et ses factures | sécurité par ligne (RLS) dans la base ; le navigateur ne décide rien | `roles-sql.cjs`, `securite-sql.py` |
| Un client ne peut changer ni son rôle, ni ses droits, ni son code, ni son e-mail | droits d'écriture **par colonne** (7 colonnes seulement) | `securite-sql.py` |
| Les rôles ne se modifient que par `definir_role()` | hiérarchie appliquée dans la base | `roles-sql.cjs` (498 contrôles) |
| Un visiteur anonyme n'atteint aucune table | aucun droit sur les tables ; **une seule** fonction publique (le suivi) | `securite-sql.py` |
| Aucune clé secrète dans le code | seule la clé publique figure dans le site et l'application | `sauvegarde-statique.py` |
| Aucun script ne s'exécute s'il vient d'ailleurs que du site | politique de contenu `script-src 'self'` | `securite-statique.py` (926 contrôles) |
| Le site ne se laisse pas habiller par un autre | pages de connexion cachées dans un cadre | `securite-statique.py` |
| La session de l'application est chiffrée sur le téléphone | trousseau iOS / Android | `npm run essai:stockage` |
| Les données ont une copie chiffrée hors du fournisseur | `docs/backup/` | `sauvegarde-essai.py` (56 contrôles) |
| Une notification ne peut pas bloquer un colis | envoi isolé dans un bloc d'exception | `securite-sql.py` |

## Ce que le système NE protège pas encore (honnêteté)
- **Le suivi public** accepte un numéro seul : voir `docs/security/TRACKING-SECURITY.md` (décision à prendre).
- **Les réglages d'authentification** du tableau de bord Supabase (e-mail d'envoi, adresses de retour, politique
  de mot de passe, limites) ne se lisent ni ne se changent depuis le code : `docs/security/AUTH-HARDENING.md`.
- **Pas de double authentification** pour le personnel, pas de CAPTCHA à l'inscription.
- **En-têtes HTTP** : GitHub Pages n'en envoie que quelques-uns ; la politique est posée par balises `<meta>`.
  `frame-ancestors` n'y est pas possible, d'où la protection de remplacement des pages de connexion.

## Règles de travail
Jamais de secret dans un fichier, un message ou un journal ; la clé de service Supabase n'approche jamais un navigateur ni
une application ; toute migration est rejouable, testée sur PostgreSQL réel, et passée à la main dans le bon projet ;
toute règle de sécurité s'écrit dans la base, pas dans la page.
