#!/usr/bin/env python3
"""Restaurer une sauvegarde Speed Express dans une base VIDE, puis prouver
que les données sont identiques à celles du jour de la sauvegarde.

    SES_RESTORE_DB_URL='postgresql://…'  \\
    python3 scripts/restore/restaurer.py --archive ses-20261005T020000Z.tar.gz.age \\
        --identite ~/cles/ses-sauvegarde.key --mode postgres-vide            # plan seulement
    … même commande + --executer                                              # restaure

Comportement par défaut : PLAN SEULEMENT. Le script déchiffre, contrôle les
sommes, interroge la base cible en lecture, vérifie les garde-fous, affiche ce
qu'il ferait, et s'arrête. Rien n'est écrit tant que --executer n'est pas donné.

Garde-fous (tous bloquants) :
  • la cible doit être VIDE (aucune table dans public, aucun compte dans auth) ;
  • la cible ne doit pas être la base d'où vient la sauvegarde ;
  • la cible ne doit pas être le projet de production ni celui de Goship, sauf
    double clé explicite (voir docs/backup/DISASTER-RECOVERY.md) ;
  • le fichier d'identité (clé privée) ne doit pas se trouver dans le dépôt Git.

Modes :
  postgres-vide   un PostgreSQL ordinaire (répétition, contrôle quotidien, secours) :
                  le socle (rôles, schéma auth…) est créé d'abord ;
  supabase-vide   un projet Supabase NEUF : le socle existe déjà, seules les
                  données de comptes sont rechargées dans les tables d'origine.
"""
import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'backup'))
import _commun as C  # noqa: E402

ICI = os.path.dirname(os.path.abspath(__file__))


def lire_manifest(dossier):
    import json
    chemin = os.path.join(dossier, 'manifest.json')
    if not os.path.isfile(chemin):
        raise C.Echec('manifest.json manquant : ce n\'est pas une archive Speed Express.')
    with open(chemin, encoding='utf-8') as f:
        m = json.load(f)
    if m.get('format') != C.FORMAT:
        raise C.Echec('Format d\'archive %r non pris en charge par ce script (attendu %s).' % (m.get('format'), C.FORMAT))
    return m


def dechiffrer(archive, identite, sortie):
    """age -d. La clé privée est un fichier HORS DÉPÔT, jamais une variable
    affichable ni un argument."""
    if not identite:
        raise C.Echec('Archive chiffrée : indiquez le fichier de clé privée avec --identite.')
    ident = os.path.realpath(os.path.expanduser(identite))
    if not os.path.isfile(ident):
        raise C.Echec('Fichier de clé introuvable : %s' % identite)
    if ident.startswith(os.path.realpath(C.RACINE) + os.sep):
        raise C.Echec('Refus : la clé privée est DANS le dépôt Git. Une clé de chiffrement ne doit jamais s\'y trouver. '
                      'Déplacez-la hors du dépôt (et considérez-la comme compromise si elle a été commitée).')
    if os.stat(ident).st_mode & 0o077:
        raise C.Echec('Refus : la clé privée est lisible par d\'autres comptes. Exécutez : chmod 600 <fichier>.')
    C.executer([C.outil('age'), '-d', '-i', ident, '-o', sortie, archive])


def garde_fous(cible, manifest, autoriser_projet):
    """Raisons de refuser la cible. Rend la liste (vide = on peut continuer)."""
    refus = []
    interdit = [r for r in C.PROJETS_INTERDITS if r in cible['hote'] or r in cible['utilisateur']]
    if interdit and autoriser_projet != interdit[0]:
        refus.append('la cible est le projet protégé « %s » (production ou Goship). Une restauration de test ne vise jamais '
                     'un projet protégé.' % interdit[0])
    src = manifest.get('source', {})
    if src.get('hote') == cible['hote'] and src.get('base') == cible['base'] and src.get('port', cible['port']) == cible['port']:
        refus.append('la cible est la base d\'où vient la sauvegarde.')
    if refus:
        return refus    # on ne se connecte même pas à une cible déjà refusée
    n = C.sql(cible, "SELECT count(*) FROM information_schema.tables WHERE table_schema = '%s'" % C.SCHEMA_APP)
    if n and int(n[0]) > 0:
        refus.append('la cible n\'est pas vide : %s table(s) dans le schéma public.' % n[0])
    existe = C.sql(cible, "SELECT to_regclass('auth.users') IS NOT NULL")
    if existe and existe[0] == 't':
        comptes = C.sql(cible, 'SELECT count(*) FROM auth.users')
        if comptes and int(comptes[0]) > 0:
            refus.append('la cible n\'est pas vide : %s compte(s) dans auth.users.' % comptes[0])
    return refus


def _pg_restore(cible, dossier, fichier, options):
    cmd = [C.outil('pg_restore'), '--no-owner', '--exit-on-error', '--dbname=' + cible['base']] + options + [os.path.join(dossier, fichier)]
    C.executer(cmd, env=C.env_pg(cible), timeout=7200)


def _psql_fichier(cible, chemin):
    C.executer([C.outil('psql'), '-qX', '-v', 'ON_ERROR_STOP=1', '-f', chemin], env=C.env_pg(cible), timeout=1800)


def restaurer_vers(cible, dossier, mode):
    """Ordre qui compte : comptes (auth) AVANT le schéma public, car public.clients
    pointe vers auth.users ; déclencheur d'inscription APRÈS, car il appelle une
    fonction de public."""
    if mode == 'postgres-vide':
        C.info('  · socle (rôles, schéma auth, extensions)')
        _psql_fichier(cible, os.path.join(ICI, 'socle-postgres-vide.sql'))
    if os.path.isfile(os.path.join(dossier, 'auth.dump')):
        C.info('  · comptes (auth.users, auth.identities)')
        if mode == 'postgres-vide':
            # Schéma + données, SANS les déclencheurs : celui des inscriptions appelle
            # une fonction de public, qui n'existe pas encore. On le recrée à la fin.
            liste = C.executer([C.outil('pg_restore'), '-l', os.path.join(dossier, 'auth.dump')])
            retenu = [l for l in liste.splitlines() if ' TRIGGER ' not in l]
            chemin_liste = os.path.join(dossier, '_auth.liste')
            with open(chemin_liste, 'w', encoding='utf-8') as f:
                f.write('\n'.join(retenu) + '\n')
            _pg_restore(cible, dossier, 'auth.dump', ['--no-privileges', '--single-transaction', '--use-list=' + chemin_liste])
        else:
            # Projet neuf : les tables de comptes existent déjà, AVEC leur clé étrangère
            # (identities.user_id → users.id). Une sauvegarde « données seules » ne porte pas
            # cette dépendance et pg_restore rechargerait identities AVANT users : refus de la
            # base. On impose l'ordre : les comptes d'abord, leurs identités ensuite.
            liste = C.executer([C.outil('pg_restore'), '-l', os.path.join(dossier, 'auth.dump')])
            lignes = [l for l in liste.splitlines() if l and not l.startswith(';')]
            comptes = [l for l in lignes if ' TABLE DATA auth users ' in l]
            ordonnees = comptes + [l for l in lignes if l not in comptes]
            chemin_liste = os.path.join(dossier, '_auth.liste')
            with open(chemin_liste, 'w', encoding='utf-8') as f:
                f.write('\n'.join(ordonnees) + '\n')
            _pg_restore(cible, dossier, 'auth.dump', ['--no-privileges', '--single-transaction', '--data-only',
                                                      '--use-list=' + chemin_liste])
    C.info('  · schéma et données de l\'application (public)')
    # Le schéma « public » existe déjà dans toute base neuve (Supabase compris) : on
    # écarte seulement l'ordre de le CRÉER ; son contenu et ses droits sont restaurés.
    liste = C.executer([C.outil('pg_restore'), '-l', os.path.join(dossier, 'public.dump')])
    retenu = [l for l in liste.splitlines() if ' SCHEMA - public ' not in l]
    chemin_liste = os.path.join(dossier, '_public.liste')
    with open(chemin_liste, 'w', encoding='utf-8') as f:
        f.write('\n'.join(retenu) + '\n')
    _pg_restore(cible, dossier, 'public.dump', ['--single-transaction', '--use-list=' + chemin_liste])
    C.info('  · déclencheur d\'inscription et temps réel')
    _psql_fichier(cible, os.path.join(ICI, 'post-restauration.sql'))


def valider(cible, manifest):
    """Compare la base restaurée à ce que la base contenait au moment de la
    sauvegarde : lignes, empreinte du contenu de chaque table, séquences,
    squelette de sécurité. Rend (problèmes, résumé)."""
    problemes = []
    total = 0
    for nom, att in sorted(manifest['tables'].items()):
        try:
            emp = C.empreinte_table(cible, nom)
        except C.Echec:
            problemes.append('table absente après restauration : %s' % nom)
            continue
        total += emp['lignes']
        if emp['lignes'] != att['lignes']:
            problemes.append('%s : %s ligne(s) restaurée(s) au lieu de %s' % (nom, emp['lignes'], att['lignes']))
        elif emp['empreinte'] != att['empreinte']:
            problemes.append('%s : même nombre de lignes mais contenu DIFFÉRENT (empreinte)' % nom)
    presentes = set(C.lister_tables(cible))
    for en_trop in sorted(presentes - set(manifest['tables'])):
        problemes.append('table inattendue dans la cible : %s' % en_trop)
    seq = C.sequences(cible)
    for nom, val in sorted(manifest.get('sequences', {}).items()):
        if seq.get(nom) != val:
            problemes.append('séquence %s : %s au lieu de %s (les prochains numéros seraient faux)' % (nom, seq.get(nom), val))
    struct = C.structure(cible)
    for cle, val in sorted(manifest.get('structure', {}).items()):
        if struct.get(cle) != val:
            problemes.append('structure de sécurité « %s » : %s au lieu de %s' % (cle, struct.get(cle), val))
    if manifest.get('declencheur_comptes', 0) >= 1 and C.declencheur_comptes(cible) < 1:
        problemes.append('le déclencheur d\'inscription (auth.users) est absent : un nouvel inscrit n\'aurait pas de profil')
    return problemes, {'tables': len(manifest['tables']), 'lignes': total}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--archive', required=True, help='archive .tar.gz.age (chiffrée) ou .tar.gz (déjà déchiffrée)')
    ap.add_argument('--identite', help='fichier de clé privée age (hors dépôt)')
    ap.add_argument('--mode', choices=('postgres-vide', 'supabase-vide'), default='postgres-vide')
    ap.add_argument('--cible-env', default='SES_RESTORE_DB_URL', help='variable d\'environnement qui porte la chaîne de la base cible')
    ap.add_argument('--executer', action='store_true', help='restaurer pour de bon (sans cela : plan seulement)')
    ap.add_argument('--autoriser-projet', default='', help='réservé au sinistre : référence du projet protégé visé (voir DISASTER-RECOVERY.md)')
    a = ap.parse_args(argv)

    travail = tempfile.mkdtemp(prefix='ses-rest-')
    os.chmod(travail, 0o700)
    try:
        archive = os.path.abspath(a.archive)
        if not os.path.isfile(archive):
            raise C.Echec('Archive introuvable : %s' % a.archive)
        tgz = archive
        if archive.endswith('.age'):
            tgz = os.path.join(travail, 'archive.tar.gz')
            C.info('Déchiffrement…')
            dechiffrer(archive, a.identite, tgz)
        C.info('Extraction et contrôle des sommes…')
        dossier = os.path.join(travail, 'contenu')
        os.makedirs(dossier)
        C.extraire_sans_risque(tgz, dossier)
        n = C.verifier_sommes(dossier)
        manifest = lire_manifest(dossier)
        C.info('  %s fichier(s) conformes. Archive du %s, %s table(s), %s ligne(s).' % (
            n, manifest['cree_le'], len(manifest['tables']), sum(t['lignes'] for t in manifest['tables'].values())))

        cible = C.decouper(C.lire_url(a.cible_env))
        refus = garde_fous(cible, manifest, a.autoriser_projet)
        if refus:
            raise C.Echec('Restauration REFUSÉE :\n  - ' + '\n  - '.join(refus))

        C.info('\nPLAN — cible : %s (mode %s)' % (C.identite_publique(cible), a.mode))
        C.info('  1. %s' % ('socle PostgreSQL (rôles, schéma auth, extensions)' if a.mode == 'postgres-vide' else 'aucun socle (projet Supabase neuf)'))
        C.info('  2. comptes : auth.users, auth.identities')
        C.info('  3. schéma et données de l\'application (public), en une seule transaction')
        C.info('  4. déclencheur d\'inscription + temps réel')
        C.info('  5. validation : lignes, empreintes, séquences, sécurité')
        if not a.executer:
            C.info('\nPlan seulement : rien n\'a été écrit. Ajoutez --executer pour restaurer.')
            return 0

        C.info('\nRestauration…')
        restaurer_vers(cible, dossier, a.mode)
        C.info('\nValidation des données…')
        problemes, resume = valider(cible, manifest)
        if problemes:
            C.info('ÉCHEC DE VALIDATION :')
            for p in problemes:
                C.info('  - ' + p)
            return 1
        C.info('VALIDATION OK : %s table(s), %s ligne(s) identiques à la sauvegarde (empreintes, séquences et sécurité compris).'
               % (resume['tables'], resume['lignes']))
        return 0
    finally:
        shutil.rmtree(travail, ignore_errors=True)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except C.Echec as e:
        print('ÉCHEC : ' + C.nettoyer(e), file=sys.stderr)
        sys.exit(1)
