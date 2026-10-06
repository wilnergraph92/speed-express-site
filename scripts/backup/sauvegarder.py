#!/usr/bin/env python3
"""Sauvegarde complète et chiffrée de la base Speed Express, vérifiée avant d'être rendue.

    SES_DB_URL='postgresql://…'            la base à sauvegarder (secret : variable d'environnement)
    SES_AGE_RECIPIENT='age1…'              clé PUBLIQUE de chiffrement (pas un secret)
    SES_VERIF_DB_URL='postgresql://…'      une base VIDE jetable, pour le contrôle de restauration
    python3 scripts/backup/sauvegarder.py --sortie ./sauvegardes --exiger-verification

Ce que contient l'archive (ses-AAAAMMJJTHHMMSSZ.tar.gz.age) :
    public.dump     toutes les tables, fonctions, règles de sécurité et données du schéma public
                    (une table ajoutée demain y est sans rien changer ici)
    auth.dump       les comptes (auth.users, auth.identities)
    csv/            chaque table en CSV, lisible sans PostgreSQL (dernier recours)
    manifest.json   lignes et EMPREINTE du contenu de chaque table, séquences, squelette de sécurité
    SHA256SUMS      la somme de chaque fichier ci-dessus
Tout est lu dans UNE transaction figée en lecture seule : l'archive est cohérente
même si le site écrit pendant la sauvegarde.

Contrôle automatique : l'archive est restaurée dans une base vide jetable puis
comparée au manifest. Une sauvegarde qui ne se restaure pas n'est PAS rendue.
Sans base de contrôle, la vérification est « partielle » (structure de l'archive)
et --exiger-verification fait échouer le script.

Rien de secret n'est jamais écrit : ni mot de passe, ni clé privée.
"""
import argparse
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
sys.path.insert(0, os.path.join(ICI, '..', 'restore'))
import _commun as C  # noqa: E402
import restaurer as R  # noqa: E402

CLE_AGE = re.compile(r'^age1[0-9a-z]{58}$')


def destinataires(valeurs):
    liste = []
    for v in valeurs:
        liste += [x for x in re.split(r'[\s,]+', v or '') if x]
    if not liste:
        raise C.Echec("Aucune clé de chiffrement. Donnez la clé PUBLIQUE (age1…) par --destinataire ou SES_AGE_RECIPIENT.")
    for d in liste:
        if d.startswith('AGE-SECRET-KEY'):
            raise C.Echec("Refus : c'est une clé PRIVÉE. Seule la clé publique (age1…) sert à chiffrer ; "
                          "la clé privée ne doit jamais quitter son coffre.")
        if not CLE_AGE.match(d):
            raise C.Echec('Clé de chiffrement illisible : attendu age1 suivi de 58 caractères.')
    return liste


def lire_version_majeure(sortie):
    """La version majeure dans « pg_dump (PostgreSQL) 16.10 (Ubuntu 16.10-0ubuntu0.24.04.1) » : le nombre qui suit « (PostgreSQL) »,
    jamais celui d'une parenthèse de distribution (sous Ubuntu, la ligne se TERMINE par une parenthèse : lire après la dernière ne
    donnait rien, et la sauvegarde refusait de tourner)."""
    m = re.search(r'\(PostgreSQL\)\s+(\d+)', sortie or '') or re.search(r'pg_dump\D*?(\d+)', sortie or '')
    return int(m.group(1)) if m else 0


def version_pg_dump():
    return lire_version_majeure(C.executer([C.outil('pg_dump'), '--version']))


def exporter_csv(source, instantane, tables, dossier):
    os.makedirs(os.path.join(dossier, 'csv'))
    for nom in tables:
        schema, table = nom.split('.', 1)
        if schema == 'auth':
            requete = ('SELECT id, email, created_at, email_confirmed_at, last_sign_in_at FROM auth.users ORDER BY created_at'
                       if table == 'users' else None)
            if requete is None:
                continue   # identities : pas de CSV (jetons d'identité), l'archive binaire la porte
            fichier = 'auth_users_sans_mot_de_passe.csv'
        else:
            requete = 'SELECT * FROM %s.%s ORDER BY 1' % (C.guillemets(schema), C.guillemets(table))
            fichier = '%s.csv' % table
        script = ("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSET TRANSACTION SNAPSHOT '%s';\n"
                  "COPY (%s) TO STDOUT WITH (FORMAT csv, HEADER true);\nROLLBACK;\n") % (instantane, requete)
        with open(os.path.join(dossier, 'csv', fichier), 'w', encoding='utf-8') as f:
            C.executer([C.outil('psql'), '-qAtX', '-v', 'ON_ERROR_STOP=1'], env=C.env_pg(source), entree=script, sortie=f)


def verifier_completude(dossier, manifest):
    """Contrôle sans base : l'archive porte-t-elle une entrée « données » par table ?"""
    liste = C.executer([C.outil('pg_restore'), '-l', os.path.join(dossier, 'public.dump')])
    donnees = len([l for l in liste.splitlines() if ' TABLE DATA ' in l])
    attendues = len([t for t in manifest['tables'] if t.startswith(C.SCHEMA_APP + '.')])
    if donnees != attendues:
        raise C.Echec('public.dump est incomplet : %s table(s) de données au lieu de %s.' % (donnees, attendues))


def verifier_par_restauration(dossier, manifest, env_verif, source_c):
    """La vraie preuve : restaurer dans une base vide jetable et comparer."""
    cible = C.decouper(C.lire_url(env_verif))
    if (cible['hote'], cible['port'], cible['base']) == (source_c['hote'], source_c['port'], source_c['base']):
        raise C.Echec('La base de contrôle est la base sauvegardée : refus. Il faut une base vide JETABLE, distincte.')
    refus = R.garde_fous(cible, manifest, '')
    if refus:
        raise C.Echec('Base de contrôle refusée :\n  - ' + '\n  - '.join(refus))
    R.restaurer_vers(cible, dossier, 'postgres-vide')
    problemes, resume = R.valider(cible, manifest)
    if problemes:
        raise C.Echec('RESTAURATION DE CONTRÔLE INFIDÈLE — sauvegarde non rendue :\n  - ' + '\n  - '.join(problemes))
    return resume


def signaler(source, nom, statut, detail):
    """Le battement de cœur de ce travail, déposé dans la base (étape 013 : public.ses_ops_heartbeat), pour que le tableau de bord sache
    quand a eu lieu la dernière sauvegarde réussie et la dernière restauration vérifiée. Jamais bloquant : si la 013 n'est pas passée, ou si
    la base ne répond pas, on l'écrit dans le journal et la sauvegarde garde son résultat."""
    if source is None:
        return False
    corps = json.dumps(detail, ensure_ascii=False, sort_keys=True)
    if '$sig$' in corps:
        return False
    try:
        C.sql(source, "select public.ses_ops_heartbeat('%s', '%s', $sig$%s$sig$::jsonb)" % (nom, statut, corps))
        return True
    except C.Echec as e:
        C.avertir('Signal « %s » non déposé dans la base (étape 013 pas encore passée ?) : %s' % (nom, str(e).splitlines()[0][:160]))
        return False


def sauvegarder(args):
    debut = time.time()
    recipients = destinataires([args.destinataire, os.environ.get('SES_AGE_RECIPIENT', '')])
    source = C.decouper(C.lire_url('SES_DB_URL'))
    sortie = os.path.abspath(args.sortie)
    os.makedirs(sortie, exist_ok=True)
    os.chmod(sortie, 0o700)

    serveur = C.sql(source, "SELECT current_setting('server_version'), current_setting('server_version_num')::int / 10000")
    version_serveur, majeur = serveur[0].split('|')
    if version_pg_dump() < int(majeur):
        raise C.Echec('pg_dump (v%s) est plus ancien que le serveur (v%s) : il refuserait. Installez le client PostgreSQL %s.'
                      % (version_pg_dump(), majeur, majeur))
    C.outil('age')

    travail = tempfile.mkdtemp(prefix='ses-sauv-')
    os.chmod(travail, 0o700)
    try:
        contenu = os.path.join(travail, 'contenu')
        os.makedirs(contenu)
        C.info('Source : %s (PostgreSQL %s)' % (C.identite_publique(source), version_serveur))

        with C.Instantane(source) as inst:
            tables = C.lister_tables(source, inst.id)
            if not [t for t in tables if t.startswith(C.SCHEMA_APP + '.')]:
                raise C.Echec('Aucune table dans le schéma public : mauvaise base ? Rien n\'est sauvegardé.')
            C.info('Empreinte de %s table(s)…' % len(tables))
            manifest = {
                'format': C.FORMAT, 'cree_le': C.maintenant_utc().isoformat() + 'Z',
                'source': {'hote': source['hote'], 'port': source['port'], 'base': source['base'], 'postgresql': version_serveur},
                'outil': {'pg_dump_majeur': version_pg_dump()},
                'tables': dict((t, C.empreinte_table(source, t, inst.id)) for t in tables),
                'sequences': C.sequences(source, inst.id),
                'structure': C.structure(source, inst.id),
                'declencheur_comptes': C.declencheur_comptes(source),
            }
            C.info('Export (public, comptes)…')
            env = C.env_pg(source)
            base = [C.outil('pg_dump'), '--format=custom', '--compress=6', '--no-owner', '--snapshot=' + inst.id]
            C.executer(base + ['--schema=' + C.SCHEMA_APP, '--file=' + os.path.join(contenu, 'public.dump')], env=env, timeout=7200)
            auth = [t for t in tables if t.startswith('auth.')]
            if auth:
                C.executer(base + ['--no-privileges'] + ['--table=' + t for t in auth]
                           + ['--file=' + os.path.join(contenu, 'auth.dump')], env=env, timeout=7200)
            else:
                C.avertir('Aucune table de comptes (auth) : l\'archive ne pourra pas recréer les utilisateurs.')
            if not args.sans_csv:
                C.info('Export CSV (lisible sans PostgreSQL)…')
                exporter_csv(source, inst.id, tables, contenu)

        # Sommes de contrôle de tout ce qui précède, puis le manifest les consigne.
        fichiers = {}
        for racine, _, noms in os.walk(contenu):
            for n in sorted(noms):
                chemin = os.path.join(racine, n)
                rel = os.path.relpath(chemin, contenu).replace(os.sep, '/')
                fichiers[rel] = {'octets': os.path.getsize(chemin), 'sha256': C.sha256_fichier(chemin)}
        manifest['fichiers'] = fichiers
        C.ecrire_json(os.path.join(contenu, 'manifest.json'), manifest)
        with open(os.path.join(contenu, 'SHA256SUMS'), 'w', encoding='utf-8') as f:
            for rel in sorted(fichiers) + ['manifest.json']:
                f.write('%s  %s\n' % (C.sha256_fichier(os.path.join(contenu, rel)), rel))

        # Vérification AVANT de rendre l'archive.
        niveau = 'aucune'
        C.info('Vérification…')
        C.verifier_sommes(contenu)
        verifier_completude(contenu, manifest)
        niveau = 'partielle'
        if os.environ.get(args.verifier_sur_env, '').strip():
            C.info('Restauration de contrôle dans une base vide jetable…')
            resume = verifier_par_restauration(contenu, manifest, args.verifier_sur_env, source)
            niveau = 'complete'
            C.info('  restauration fidèle : %s table(s), %s ligne(s), empreintes identiques.' % (resume['tables'], resume['lignes']))
        elif args.exiger_verification:
            raise C.Echec('Vérification complète exigée, mais %s est vide : fournissez une base de contrôle vide et jetable.'
                          % args.verifier_sur_env)
        else:
            C.avertir('Pas de base de contrôle : vérification PARTIELLE seulement (structure de l\'archive).')

        # Archive, puis chiffrement. Le clair n'existe que dans le dossier de travail temporaire.
        nom = 'ses-%s.tar.gz' % C.horodatage()
        clair = os.path.join(travail, nom)
        with tarfile.open(clair, 'w:gz') as t:
            for rel in sorted(os.listdir(contenu)):
                t.add(os.path.join(contenu, rel), arcname=rel)
        final = os.path.join(sortie, nom + '.age')
        cmd = [C.outil('age')]
        for r in recipients:
            cmd += ['-r', r]
        C.executer(cmd + ['-o', final, clair])
        os.chmod(final, 0o600)
        empreinte = C.sha256_fichier(final)
        with open(final + '.sha256', 'w', encoding='utf-8') as f:
            f.write('%s  %s\n' % (empreinte, os.path.basename(final)))

        total = sum(t['lignes'] for t in manifest['tables'].values())
        enreg = {'horodatage': manifest['cree_le'], 'fichier': os.path.basename(final), 'octets': os.path.getsize(final),
                 'sha256': empreinte, 'tables': len(tables), 'lignes': total, 'verification': niveau,
                 'duree_s': round(time.time() - debut, 1), 'postgresql': version_serveur,
                 'source': C.identite_publique(source).split('@', 1)[1], 'statut': 'ok'}
        journaliser(sortie, enreg)
        if args.signaler:
            signaler(source, 'backup', 'OK', {k: enreg[k] for k in ('octets', 'tables', 'lignes', 'verification', 'duree_s', 'postgresql')})
            if niveau == 'complete':
                signaler(source, 'restore_check', 'OK', {'tables': resume['tables'], 'lignes': resume['lignes']})
        C.info('\nSAUVEGARDE OK : %s (%s octets), %s table(s), %s ligne(s), vérification %s.'
               % (final, enreg['octets'], len(tables), total, niveau))
        return 0
    finally:
        shutil.rmtree(travail, ignore_errors=True)


def journaliser(sortie, enreg):
    """Une ligne par exécution, succès ou échec. Aucun secret : l'hôte et la base,
    jamais le mot de passe."""
    with open(os.path.join(sortie, 'journal.jsonl'), 'a', encoding='utf-8') as f:
        f.write(json.dumps(enreg, ensure_ascii=False, sort_keys=True) + '\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--sortie', default=os.environ.get('SES_BACKUP_DIR', './sauvegardes'))
    ap.add_argument('--destinataire', default='', help='clé publique age (age1…) ; plusieurs : séparées par des virgules')
    ap.add_argument('--verifier-sur-env', default='SES_VERIF_DB_URL',
                    help='variable qui porte la chaîne de la base de contrôle (vide et jetable)')
    ap.add_argument('--exiger-verification', action='store_true', help='échouer si la restauration de contrôle ne peut pas être faite')
    ap.add_argument('--sans-csv', action='store_true')
    ap.add_argument('--signaler', action='store_true', help='déposer le résultat dans la base (public.ses_ops_heartbeat, étape 013) pour la surveillance')
    a = ap.parse_args(argv)
    try:
        return sauvegarder(a)
    except C.Echec as e:
        message = C.nettoyer(e)
        try:
            os.makedirs(a.sortie, exist_ok=True)
            journaliser(os.path.abspath(a.sortie), {'horodatage': C.maintenant_utc().isoformat() + 'Z', 'statut': 'echec',
                                                    'message': message.splitlines()[0][:300]})
        except Exception:
            pass
        if a.signaler:
            try:
                signaler(C.decouper(C.lire_url('SES_DB_URL')), 'backup', 'FAIL', {'message': message.splitlines()[0][:200]})
            except Exception:
                pass
        print('ÉCHEC : ' + message, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
