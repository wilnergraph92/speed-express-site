"""Briques communes à la sauvegarde et à la restauration de Speed Express.

Python 3.8+, bibliothèque standard seulement. Les outils externes sont ceux de
PostgreSQL (pg_dump, pg_restore, psql) et `age` pour le chiffrement.

Règles de ce module, qui valent pour tous les scripts :
  • la chaîne de connexion à la base ne passe JAMAIS en argument de commande
    (un `ps` la montrerait) : elle est découpée et transmise par variables
    d'environnement (PGHOST, PGPASSWORD…) ;
  • aucun mot de passe n'est jamais écrit dans un message, un journal ou un
    fichier : tout texte affiché passe par `nettoyer()` ;
  • la lecture de la base est en LECTURE SEULE ;
  • aucune clé de chiffrement n'est lue, écrite ni stockée ici : on ne manipule
    que la clé PUBLIQUE du destinataire (sauvegarde) ou le chemin d'un fichier
    d'identité hors dépôt (restauration).
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from urllib.parse import parse_qs, unquote, urlsplit

FORMAT = 1                      # version du contenu de l'archive (manifest.json)
SCHEMA_APP = 'public'           # tout ce schéma est sauvegardé : une table ajoutée demain l'est aussi
TABLES_AUTH = ('users', 'identities')

# Projets qu'une restauration de test ne doit JAMAIS viser. Ces identifiants
# sont publics (ils figurent dans config.js) : ce n'est pas un secret, c'est
# un garde-fou.
PROJETS_INTERDITS = (
    'ltbqqchtyzlyakcsxxis',     # Speed Express Shipping — production
    'gpfdyslysqjmojgzggib',     # Goship Express — projet frère, intouchable
)

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Echec(Exception):
    """Erreur attendue, expliquée en une phrase à celui qui lance le script."""


# --- Affichage sans fuite ---------------------------------------------------

_secrets = set()


def secret(valeur):
    """Déclare une valeur à ne jamais afficher (mot de passe de la base…)."""
    if valeur and len(valeur) >= 4:
        _secrets.add(valeur)


def nettoyer(texte):
    texte = str(texte)
    for s in sorted(_secrets, key=len, reverse=True):
        texte = texte.replace(s, '***')
    # Une URL de connexion qui traînerait dans un message : le mot de passe saute.
    return re.sub(r'(postgres(?:ql)?://[^:/@\s]+:)[^@\s]+@', r'\1***@', texte)


def info(msg):
    print(nettoyer(msg), flush=True)


def avertir(msg):
    print('ATTENTION : ' + nettoyer(msg), file=sys.stderr, flush=True)


# --- Outils externes --------------------------------------------------------

def outil(nom):
    """Chemin d'un exécutable : d'abord SES_PG_BIN (pour les outils PostgreSQL),
    puis le PATH."""
    dossier = os.environ.get('SES_PG_BIN')
    if dossier and nom in ('pg_dump', 'pg_restore', 'psql'):
        chemin = os.path.join(dossier, nom)
        if os.access(chemin, os.X_OK):
            return chemin
    chemin = shutil.which(nom)
    if not chemin:
        raise Echec("Outil introuvable : %s. Installez-le (voir docs/backup/BACKUP-STRATEGY.md §Outils)." % nom)
    return chemin


def executer(cmd, env=None, entree=None, timeout=3600, sortie=None):
    """Lance une commande ; ne montre jamais les secrets ; échoue avec un texte
    lisible. Rend la sortie standard (texte)."""
    try:
        r = subprocess.run(cmd, env=env, input=entree, stdout=subprocess.PIPE if sortie is None else sortie,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Echec('Commande trop longue (%s s) : %s' % (timeout, os.path.basename(cmd[0])))
    if r.returncode != 0:
        detail = nettoyer((r.stderr or '').strip().splitlines()[-1] if (r.stderr or '').strip() else 'sans message')
        raise Echec('%s a échoué (code %s) : %s' % (os.path.basename(cmd[0]), r.returncode, detail))
    return r.stdout or ''


# --- Connexion à une base ---------------------------------------------------

def lire_url(nom_variable):
    url = os.environ.get(nom_variable, '').strip()
    if not url:
        raise Echec('La variable %s est vide. La chaîne de connexion se passe par variable '
                    "d'environnement (ou secret de la CI), jamais en argument ni dans un fichier du dépôt." % nom_variable)
    return url


def decouper(url):
    """Découpe postgresql://utilisateur:mdp@hote:port/base?sslmode=… sans rien
    afficher. Déclare le mot de passe comme secret."""
    # Un mot de passe qui contient @ / : ? # % doit être encodé dans l'URL (%40 %2F %3A %3F %23 %25).
    # Sinon l'URL est ambiguë : on le dit, sans jamais répéter l'URL.
    conseil = ('Chaîne de connexion illisible (attendu : postgresql://utilisateur:mot-de-passe@hote:5432/base). '
               'Si le mot de passe contient @ / : ? # ou %, encodez-le : @ = %40, / = %2F, : = %3A, ? = %3F, # = %23, % = %25.')
    try:
        p = urlsplit(url)
        port = p.port
    except ValueError:
        raise Echec(conseil)
    if p.scheme not in ('postgres', 'postgresql') or not p.hostname:
        raise Echec(conseil)
    mdp = unquote(p.password) if p.password else ''
    secret(mdp)
    secret(p.password or '')
    q = {k: v[0] for k, v in parse_qs(p.query).items()}
    return {
        'hote': p.hostname, 'port': str(port or 5432), 'utilisateur': unquote(p.username or 'postgres'),
        'mdp': mdp, 'base': (p.path or '/postgres').lstrip('/') or 'postgres', 'ssl': q.get('sslmode'),
    }


def identite_publique(c):
    """Ce qu'on a le droit d'écrire dans un journal : jamais le mot de passe."""
    return '%s@%s:%s/%s' % (c['utilisateur'], c['hote'], c['port'], c['base'])


def env_pg(c):
    e = dict(os.environ)
    e.update({'PGHOST': c['hote'], 'PGPORT': c['port'], 'PGUSER': c['utilisateur'], 'PGDATABASE': c['base'],
              'PGCONNECT_TIMEOUT': '20',
              # Mêmes réglages des deux côtés : les empreintes comparent du texte.
              'PGOPTIONS': '-c TimeZone=UTC -c DateStyle=ISO,YMD -c IntervalStyle=postgres -c extra_float_digits=3'})
    if c['mdp']:
        e['PGPASSWORD'] = c['mdp']
    if c['ssl']:
        e['PGSSLMODE'] = c['ssl']
    return e


def sql(c, requete, instantane=None, timeout=600):
    """Exécute une requête et rend les lignes (champs séparés par |). Avec un
    instantané, la lecture voit exactement l'état figé au début de la sauvegarde."""
    prefixe = ''
    if instantane:
        if not re.fullmatch(r'[0-9A-Fa-f-]+', instantane):
            raise Echec('Instantané invalide.')
        prefixe = "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY; SET TRANSACTION SNAPSHOT '%s'; " % instantane
    sortie = executer([outil('psql'), '-qAtX', '-v', 'ON_ERROR_STOP=1', '-c', prefixe + requete],
                      env=env_pg(c), timeout=timeout)
    return [l for l in sortie.splitlines() if l != '']


class Instantane(object):
    """Garde ouverte une transaction en lecture seule dont l'état est exporté :
    pg_dump et les lectures de contrôle s'y rattachent, et voient donc EXACTEMENT
    les mêmes données, même si le site écrit pendant la sauvegarde."""

    def __init__(self, c):
        self.c = c
        self.p = None
        self.id = None

    def __enter__(self):
        self.p = subprocess.Popen([outil('psql'), '-qAtX', '-v', 'ON_ERROR_STOP=1'], env=env_pg(self.c),
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  universal_newlines=True)
        try:
            self.p.stdin.write('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSELECT pg_export_snapshot();\n')
            self.p.stdin.flush()
            self.id = (self.p.stdout.readline() or '').strip()
        except Exception:
            self.id = ''
        if not re.fullmatch(r'[0-9A-Fa-f]+(-[0-9A-Fa-f]+)+', self.id or ''):
            erreur = ''
            try:
                self.p.kill()
                erreur = self.p.stderr.read()
            except Exception:
                pass
            raise Echec('Impossible de figer un instantané de la base : %s' % (nettoyer(erreur.strip().splitlines()[-1]) if erreur.strip() else 'pas de réponse'))
        return self

    def __exit__(self, *a):
        try:
            self.p.stdin.write('ROLLBACK;\n')
            self.p.stdin.close()
            self.p.wait(timeout=30)
        except Exception:
            self.p.kill()


# --- Empreintes : ce qui prouve qu'une copie est fidèle ---------------------

def guillemets(nom):
    return '"' + nom.replace('"', '""') + '"'


def lister_tables(c, instantane=None):
    """Toutes les tables du schéma de l'application (public) + les deux tables de
    comptes (auth). Rien n'est écrit en dur : une table de logistique ajoutée
    demain est sauvegardée et vérifiée sans toucher à ce script."""
    lignes = sql(c, "SELECT table_schema || '.' || table_name FROM information_schema.tables "
                    "WHERE table_type = 'BASE TABLE' AND (table_schema = '%s' OR "
                    "(table_schema = 'auth' AND table_name IN (%s))) ORDER BY 1"
                 % (SCHEMA_APP, ','.join("'%s'" % t for t in TABLES_AUTH)), instantane)
    return lignes


def empreinte_table(c, nom_complet, instantane=None):
    schema, table = nom_complet.split('.', 1)
    r = sql(c, "SELECT count(*), coalesce(md5(string_agg(md5(t::text), '' ORDER BY md5(t::text))), '') "
               "FROM %s.%s t" % (guillemets(schema), guillemets(table)), instantane)
    n, h = r[-1].split('|')
    return {'lignes': int(n), 'empreinte': h}


def sequences(c, instantane=None):
    r = sql(c, "SELECT schemaname || '.' || sequencename, coalesce(last_value::text, '') FROM pg_sequences "
               "WHERE schemaname = '%s' ORDER BY 1" % SCHEMA_APP, instantane)
    return dict(l.split('|') for l in r)


def structure(c, instantane=None):
    """Le squelette de sécurité : si une restauration le perd, les données sont
    là mais la protection a disparu — ce qui est pire qu'une panne."""
    r = sql(c, "SELECT 'politiques', count(*) FROM pg_policies WHERE schemaname = '%s' UNION ALL "
               "SELECT 'tables_rls', count(*) FROM pg_class k JOIN pg_namespace n ON n.oid = k.relnamespace "
               " WHERE n.nspname = '%s' AND k.relkind = 'r' AND k.relrowsecurity UNION ALL "
               "SELECT 'fonctions', count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
               " WHERE n.nspname = '%s' UNION ALL "
               "SELECT 'declencheurs_public', count(*) FROM pg_trigger t JOIN pg_class k ON k.oid = t.tgrelid "
               " JOIN pg_namespace n ON n.oid = k.relnamespace WHERE n.nspname = '%s' AND NOT t.tgisinternal"
               % (SCHEMA_APP, SCHEMA_APP, SCHEMA_APP, SCHEMA_APP), instantane)
    return dict((l.split('|')[0], int(l.split('|')[1])) for l in r)


def declencheur_comptes(c):
    """Le déclencheur qui crée le profil à l'inscription vit sur auth.users, pas
    dans le schéma public : un dump de public ne l'emporte pas."""
    r = sql(c, "SELECT count(*) FROM pg_trigger t JOIN pg_class k ON k.oid = t.tgrelid JOIN pg_namespace n ON n.oid = k.relnamespace "
               "WHERE n.nspname = 'auth' AND k.relname = 'users' AND t.tgname = 'creer_profil_client' AND NOT t.tgisinternal")
    return int(r[0]) if r else 0


# --- Fichiers ---------------------------------------------------------------

def sha256_fichier(chemin):
    h = hashlib.sha256()
    with open(chemin, 'rb') as f:
        for bloc in iter(lambda: f.read(1024 * 1024), b''):
            h.update(bloc)
    return h.hexdigest()


def maintenant_utc():
    return datetime.datetime.utcnow().replace(microsecond=0)


def horodatage(d=None):
    return (d or maintenant_utc()).strftime('%Y%m%dT%H%M%SZ')


def extraire_sans_risque(archive_tgz, dossier):
    """Extrait une archive en refusant tout ce qui sortirait du dossier (chemin
    absolu, « .. », lien) : une archive reçue n'est jamais crue sur parole."""
    base = os.path.realpath(dossier)
    with tarfile.open(archive_tgz, 'r:gz') as t:
        for m in t.getmembers():
            cible = os.path.realpath(os.path.join(base, m.name))
            if not (cible == base or cible.startswith(base + os.sep)):
                raise Echec('Archive refusée : chemin suspect (%s).' % m.name)
            if not (m.isfile() or m.isdir()):
                raise Echec('Archive refusée : élément non ordinaire (%s).' % m.name)
        t.extractall(base)


def verifier_sommes(dossier):
    """Relit SHA256SUMS et contrôle chaque fichier de l'archive."""
    somme = os.path.join(dossier, 'SHA256SUMS')
    if not os.path.isfile(somme):
        raise Echec('SHA256SUMS manquant dans l\'archive.')
    n = 0
    with open(somme, encoding='utf-8') as f:
        for ligne in f:
            ligne = ligne.rstrip('\n')
            if not ligne:
                continue
            h, nom = ligne.split('  ', 1)
            chemin = os.path.join(dossier, nom)
            if not os.path.isfile(chemin) or sha256_fichier(chemin) != h:
                raise Echec('Somme de contrôle fausse ou fichier absent : %s. L\'archive est corrompue ou altérée.' % nom)
            n += 1
    return n


def ecrire_json(chemin, objet):
    with open(chemin, 'w', encoding='utf-8') as f:
        json.dump(objet, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write('\n')
