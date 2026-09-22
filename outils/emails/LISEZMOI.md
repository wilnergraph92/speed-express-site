# Les e-mails de l'espace client

Trois modèles à coller dans Supabase → **Authentication → Emails → Templates**,
un par onglet. Ils ne sont pas publiés avec le site : ils vivent chez Supabase,
et ces fichiers en sont la copie de référence, à reprendre si vous voulez les
modifier ou les remettre en place un jour.

| Fichier | Onglet Supabase |
|---|---|
| `confirmation-inscription.html` | **Confirm signup** |
| `mot-de-passe-oublie.html` | **Reset password** |
| `changement-adresse.html` | **Change email address** |

Les autres onglets (*Magic Link*, *Invite user*, *Reauthentication*) ne servent
pas sur ce site : laissez-les tels quels.

## Les quatre langues

À l'inscription, le site range la langue du visiteur dans son compte. Chaque
modèle la relit et choisit le bon texte :

```
{{ $l := printf "%s" .Data.langue }}
{{ if eq $l "en" }}…anglais…{{ else if eq $l "es" }}…espagnol…{{ else if eq $l "ht" }}…créole…{{ else }}…français…{{ end }}
```

Le `printf "%s"` n'est pas une coquetterie : il transforme une langue absente en
texte vide plutôt qu'en erreur. Un compte créé à la main depuis la console
Supabase, sans langue enregistrée, reçoit donc l'e-mail en français au lieu de
faire échouer l'envoi.

**Pour modifier un texte**, changez-le dans les quatre branches du même
`{{ if }}`, sinon un client verra une langue et son voisin une autre.

## Les objets (Subject)

Le champ *Subject* de Supabase ne traite pas toujours ces expressions selon la
version. Deux lignes sûres, en français et en anglais :

| Onglet | Objet |
|---|---|
| Confirm signup | `Confirmez votre adresse e-mail · Confirm your email address` |
| Reset password | `Nouveau mot de passe · New password` |
| Change email address | `Confirmez votre nouvelle adresse · Confirm your new address` |

Si votre version accepte les expressions, vous pouvez y reprendre le même
`{{ if eq $l … }}` que dans le corps du message.

## Vérifier un modèle avant de le coller

Le script `outils/emails/rendre-modeles.py` contrôle que chaque `{{ if }}` a son
`{{ end }}` et produit un aperçu HTML dans les quatre langues :

```bash
python3 outils/emails/rendre-modeles.py
```

Il écrit les douze aperçus dans `outils/emails/apercu/`, à ouvrir dans un
navigateur. Ce dossier n'est pas publié.

## Ce qui reste imparfait

- **L'expéditeur affiche `@…brevosend.com`** au lieu d'une adresse Speed Express.
  Brevo ne peut pas signer une adresse `@gmail.com` qui ne lui appartient pas.
  Le jour où vous prendrez un nom de domaine, on passera à
  `noreply@votre-domaine` et l'adresse deviendra la vôtre.
- **Le lien « Unsubscribe » ajouté par Brevo** n'a rien à faire sur un e-mail de
  compte : un client qui clique dessus ne recevra plus son lien de mot de passe
  oublié. À retirer dans Brevo, **Transactional → Settings**.
- **Le logo est chargé depuis le site** (`assets/img/ses-logo.png`). Beaucoup de
  messageries bloquent les images par défaut : le texte de remplacement
  « Speed Express Shipping » s'affiche alors à sa place, ce qui reste lisible.
