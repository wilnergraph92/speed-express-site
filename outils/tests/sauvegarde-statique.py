#!/usr/bin/env python3
"""Sauvegarde et restauration : ce qui se vérifie SANS base de données.

Les scripts de sauvegarde tiennent la chaîne de connexion de la base et les données
des clients : leurs garde-fous sont du code de sécurité, ils se testent comme tel.
(L'essai de bout en bout sur un vrai PostgreSQL est dans sauvegarde-essai.py.)

Ne modifie aucun fichier du dépôt."""
import ast
import datetime
import os
import io
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / 'scripts' / 'backup'))
sys.path.insert(0, str(RACINE / 'scripts' / 'restore'))
sys.dont_write_bytecode = True

import _commun as C   # noqa: E402
import rotation as ROT   # noqa: E402
import sauvegarder as SAUV   # noqa: E402

N = 0


def ok(cond, msg):
    global N
    if not cond:
        print('ÉCHEC sauvegarde (statique) : ' + msg)
        sys.exit(1)
    N += 1


def fichiers_du_depot():
    sortie = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=RACINE,
                            capture_output=True, text=True, check=True).stdout.splitlines()
    return [RACINE / f for f in sortie if (RACINE / f).is_file()]


# 1. Tous les scripts se compilent -----------------------------------------------------
for f in list((RACINE / 'scripts').rglob('*.py')) + [RACINE / 'outils/tests/sauvegarde-essai.py']:
    ast.parse(f.read_text(encoding='utf-8'), filename=str(f))
    ok(True, f.name)
for f in (RACINE / 'scripts').rglob('*.sh'):
    ok(subprocess.run(['bash', '-n', str(f)]).returncode == 0, 'bash -n ' + f.name)

# 2. Mots de passe : jamais affichés ----------------------------------------------------
c = C.decouper('postgresql://postgres.abcd:p%40ss%3Aw%2Frd!@aws-0-us.pooler.supabase.com:5432/postgres?sslmode=require')
ok(c['mdp'] == 'p@ss:w/rd!' and c['utilisateur'] == 'postgres.abcd' and c['port'] == '5432' and c['ssl'] == 'require',
   'découpage d\'une URL à mot de passe compliqué')
ok('p@ss' not in C.identite_publique(c) and '***' not in C.identite_publique(c), 'identité publique sans mot de passe')
ok('p@ss:w/rd!' not in C.nettoyer('échec avec p@ss:w/rd! dans le texte'), 'nettoyer() masque le mot de passe déclaré')
ok('Zx9Secret' not in C.nettoyer('postgresql://u:Zx9Secret@h:5432/b a échoué'), 'nettoyer() masque une URL qui traîne')
ok('PGPASSWORD' in C.env_pg(c) and 'p@ss' not in ' '.join(str(v) for k, v in C.env_pg(c).items() if k != 'PGPASSWORD'),
   'le mot de passe ne passe que par PGPASSWORD')
try:
    C.decouper('postgresql://u:mot/de:passe@h:5432/b'); ok(False, 'URL ambiguë (mot de passe non encodé) acceptée')
except C.Echec as e:
    ok('encodez' in str(e) and 'mot/de' not in str(e), 'mot de passe non encodé : message qui explique, sans répéter l\'URL')
try:
    C.decouper('mysql://x:y@h/b'); ok(False, 'URL non PostgreSQL acceptée')
except C.Echec:
    ok(True, 'URL non PostgreSQL refusée')
try:
    os.environ.pop('SES_ABSENTE', None); C.lire_url('SES_ABSENTE'); ok(False, 'variable vide acceptée')
except C.Echec as e:
    ok('argument' in str(e), 'variable de connexion absente : message clair')

# 3. Clés de chiffrement ---------------------------------------------------------------
PUB = 'age1' + 'q' * 58
ok(SAUV.destinataires([PUB]) == [PUB], 'clé publique acceptée')
ok(SAUV.destinataires(['%s, %s' % (PUB, PUB)]) == [PUB, PUB], 'plusieurs destinataires (clé de secours)')
for mauvais in ('AGE-SECRET-KEY-1ABCDEF', 'age1court', 'ssh-rsa AAAA', ''):
    try:
        SAUV.destinataires([mauvais]); ok(False, 'clé %r acceptée' % mauvais[:12])
    except C.Echec:
        ok(True, 'clé refusée : %r' % mauvais[:12])

# 4. Extraction d'archive : jamais crue sur parole ------------------------------------
with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    (t / 'x').write_text('x')
    for nom, chemin in (('absolu', '/tmp/ses-evade'), ('remonte', '../evade')):
        arch = t / ('%s.tgz' % nom)
        with tarfile.open(arch, 'w:gz') as tf:
            info = tarfile.TarInfo(chemin); info.size = 1
            tf.addfile(info, io.BytesIO(b'x'))     # nom posé à la main : tar le garde tel quel
        try:
            C.extraire_sans_risque(str(arch), str(t / 'dest')); ok(False, 'archive « %s » extraite' % nom)
        except C.Echec:
            ok(True, 'archive « %s » refusée' % nom)
    ok(not (t.parent / 'evade').exists() and not Path('/tmp/ses-evade').exists(), 'rien n\'a été écrit hors du dossier')
    lien = t / 'lien.tgz'
    with tarfile.open(lien, 'w:gz') as tf:
        info = tarfile.TarInfo('raccourci'); info.type = tarfile.SYMTYPE; info.linkname = '/etc/passwd'; tf.addfile(info)
    try:
        C.extraire_sans_risque(str(lien), str(t / 'dest2')); ok(False, 'lien symbolique accepté')
    except C.Echec:
        ok(True, 'archive contenant un lien symbolique refusée')
    # somme fausse
    (t / 'dest3').mkdir(); (t / 'dest3' / 'a.txt').write_text('contenu')
    (t / 'dest3' / 'SHA256SUMS').write_text('%s  a.txt\n' % ('0' * 64))
    try:
        C.verifier_sommes(str(t / 'dest3')); ok(False, 'somme fausse acceptée')
    except C.Echec:
        ok(True, 'somme de contrôle fausse détectée')

# 5. Rotation : on garde les bonnes, jamais la dernière ---------------------------------
def noms(jours, debut=datetime.datetime(2026, 10, 5, 6, 17, 0)):
    return ['ses-%s.tar.gz.age' % (debut - datetime.timedelta(days=i)).strftime('%Y%m%dT%H%M%SZ') for i in range(jours)]

tous = noms(800)
garder, supprimer = ROT.selection(tous)
ok(noms(1)[0] in garder, 'la sauvegarde la plus récente est toujours gardée')
ok(all(n in garder for n in noms(30)), 'les 30 derniers jours : une sauvegarde par jour, toutes gardées')
ok(len(garder) < 80 and len(supprimer) > 700, 'sur 800 jours de sauvegardes, la rotation en garde %d (≈ 30 + 12 + 12 + 5)' % len(garder))
mois = {n[4:10] for n in garder}
ok(all((datetime.datetime(2026, 10, 5) - datetime.timedelta(days=30 * k)).strftime('%Y%m') in mois for k in range(0, 12)),
   'un point par mois sur les 12 derniers mois')
g2, s2 = ROT.selection(sorted(garder))
ok(s2 == set(), 'rotation idempotente : rejouée sur ce qu\'elle a gardé, elle ne supprime plus rien (%d en trop)' % len(s2))
ok(ROT.selection(['journal.jsonl', 'ses-20261005T061700Z.tar.gz.age.sha256', 'autre.txt'] + noms(2))[1] == set(),
   'les fichiers qui ne sont pas des archives ne sont jamais candidats')
g3, s3 = ROT.selection(noms(3))
ok(len(s3) == 0, 'trois sauvegardes ou moins : rien n\'est supprimé')
g4, s4 = ROT.selection(noms(40, datetime.datetime(2026, 1, 1)))
ok(len(g4) >= 30, 'les périodes se comptent depuis les sauvegardes, pas depuis l\'horloge')

# 6. Aucun secret dans le dépôt ---------------------------------------------------------
PLACEHOLDER = re.compile(r'(<[^>]+>|\*\*\*|…|\$\{|mot-de-passe|MOT_DE_PASSE|\bpass\b|motdepasse|x@|:x@|secret|jetable|example|exemple|\bpw\b|\bmdp\b|utilisateur:)', re.I)
for f in fichiers_du_depot():
    rel = f.relative_to(RACINE).as_posix()
    ok(f.suffix not in ('.age', '.key', '.dump', '.pem', '.p12'), 'fichier de clé ou de sauvegarde dans le dépôt : ' + rel)
    if f.suffix in ('.png', '.jpg', '.jpeg', '.webp', '.avif', '.ico', '.woff2', '.pdf') or 'assets/js/vendor/' in rel:
        continue
    texte = f.read_text(encoding='utf-8', errors='ignore')
    if 'AGE-SECRET-KEY-' in texte and rel not in ('outils/tests/sauvegarde-essai.py', 'outils/tests/sauvegarde-statique.py',
                                                  'scripts/backup/sauvegarder.py'):
        ok(False, 'clé privée age dans ' + rel)
    for m in re.finditer(r'postgres(?:ql)?://([^:/@\s\'"]+):([^@\s\'"]+)@', texte):
        if not PLACEHOLDER.search(m.group(0)) and rel != 'outils/tests/sauvegarde-essai.py' and rel != 'outils/tests/sauvegarde-statique.py':
            ok(False, 'chaîne de connexion avec mot de passe réel dans %s : %s…' % (rel, m.group(0)[:30]))
ok(True, 'aucune clé, aucun mot de passe de base dans les fichiers du dépôt')

# 7. .gitignore protège les sauvegardes -----------------------------------------------
gi = (RACINE / '.gitignore').read_text(encoding='utf-8')
for motif in ('sauvegardes/', '*.age', '*.key', '*.dump'):
    ok(motif in gi.splitlines(), '.gitignore protège ' + motif)

# 8. Garde-fous alignés sur le projet réel ------------------------------------------
cfg = (RACINE / 'assets/js/config.js').read_text(encoding='utf-8')
ref = re.search(r"supabaseUrl:\s*'https://([a-z0-9]+)\.supabase\.co'", cfg).group(1)
ok(ref in C.PROJETS_INTERDITS, 'le projet de production (%s…) figure parmi les cibles interdites : config.js et _commun.py concordent' % ref[:6])
ok(len(C.PROJETS_INTERDITS) >= 2, 'le projet frère (Goship) est aussi protégé')

# 9. Le déclencheur d'inscription restauré = celui du schéma ------------------------
def normaliser(sql):
    return re.sub(r'\s+', ' ', re.sub(r'--[^\n]*', '', sql)).strip().lower()

schema = (RACINE / 'outils/supabase.sql').read_text(encoding='utf-8')
bloc = re.search(r'create trigger creer_profil_client.*?;', schema, re.S | re.I).group(0)
post = (RACINE / 'scripts/restore/post-restauration.sql').read_text(encoding='utf-8')
ok(normaliser(bloc) in normaliser(post), 'post-restauration.sql recrée le déclencheur d\'inscription À L\'IDENTIQUE de supabase.sql')
for t in ('colis', 'colis_historique', 'factures'):
    ok(("table public.%s" % t) in post, 'post-restauration.sql republie %s pour le temps réel' % t)

# 10. Le modèle de workflow est sûr -------------------------------------------------
wf = (RACINE / 'scripts/backup/modele-workflow-sauvegarde.yml').read_text(encoding='utf-8')
ok('secrets.SES_DB_URL' in wf and not re.search(r'postgres(ql)?://[^\s$]*supabase', wf), 'la base vient d\'un secret, jamais écrite dans le workflow')
ok('--exiger-verification' in wf, 'le workflow exige la restauration de contrôle')
ok(re.search(r'permissions:\s*\n\s*contents:\s*read', wf), 'permissions minimales (lecture seule)')
ok('vars.SES_SCRIPTS_REF' in wf, 'scripts épinglés sur une version relue')
ok('cron:' in wf and 'retention-days' in wf and 'if-no-files-found: error' in wf, 'planifié, avec rétention, et en échec si aucune sauvegarde produite')
ok('sauvegardes/*.tar.gz.age' in wf and 'sauvegardes/*\n' not in wf and '.dump' not in wf and '.csv' not in wf, 'seul le chiffré est envoyé en artefact')
ok('AGE-SECRET-KEY' not in wf and 'PRIVATE' not in wf.split('SES_AGE_RECIPIENT')[0].upper().replace('PRIVÉ', ''), 'aucune clé privée dans le workflow')

# 10 bis. La version de pg_dump, telle que l'écrit chaque système --------------------
import importlib.util as _iu  # noqa: E402
_spec = _iu.spec_from_file_location('sauvegarder_essai', str(RACINE / 'scripts/backup/sauvegarder.py'))
_sauv = _iu.module_from_spec(_spec)
sys.path.insert(0, str(RACINE / 'scripts/backup'))
_spec.loader.exec_module(_sauv)
for sortie_, attendu_ in (('pg_dump (PostgreSQL) 16.10 (Ubuntu 16.10-0ubuntu0.24.04.1)', 16),          # runner GitHub (Ubuntu)
                          ('pg_dump (PostgreSQL) 17.6 (Ubuntu 17.6-1.pgdg24.04+1)', 17),               # dépôt PGDG
                          ('pg_dump (PostgreSQL) 16.4', 16), ('pg_dump (PostgreSQL) 15.8 (Homebrew)', 15), # macOS
                          ('pg_dump (PostgreSQL) 18beta1', 18), ('pg_dump (PostgreSQL) 9.6.24', 9), ('', 0), ('rien', 0)):
    ok(_sauv.lire_version_majeure(sortie_) == attendu_, 'version de pg_dump lue dans « %s » : %s' % (sortie_, attendu_))

# 11. La restauration n'écrit rien sans --executer ----------------------------------
rest = (RACINE / 'scripts/restore/restaurer.py').read_text(encoding='utf-8')
ok("if not a.executer:" in rest and rest.index("if not a.executer:") < rest.index('restaurer_vers(cible, dossier, a.mode)'),
   'le plan s\'arrête AVANT toute écriture quand --executer n\'est pas donné')
ok(rest.index('refus = garde_fous') < rest.index('restaurer_vers(cible, dossier, a.mode)'), 'les garde-fous précèdent toute restauration')

# 12. La sauvegarde couvre le noyau, et la migration est gardée --------------------------
ok(C.SCHEMAS_APP[0] == 'public' and set(C.SCHEMAS_NOYAU) >= {'logistics', 'analytics', 'ops', 'ses_meta'},
   'la sauvegarde emporte les schémas du noyau et le journal des migrations')
noyau_sql = '\n'.join(p.read_text(encoding='utf-8') for p in sorted((RACINE / 'outils/logistique').glob('*.sql')))
crees = set(re.findall(r'create schema if not exists (\w+)', noyau_sql))
ok(crees <= set(C.SCHEMAS_APP), 'chaque schéma créé par le noyau est sauvegardé (%s)' % sorted(crees - set(C.SCHEMAS_APP)))
ok('ses_signal' in post, 'post-restauration.sql republie le signal temps réel du noyau')
mig = (RACINE / 'scripts/migration/migrer.py').read_text(encoding='utf-8')
code_mig = re.sub(r'(?s)""".*?"""', '', mig)
for interdit in ('set_double_write', 'lg_set_finance_mode', 'centreNoyau', 'portailNoyau', 'drop ', 'delete ', 'truncate'):
    ok(interdit not in code_mig.lower().replace('centrenoyau', 'centreNoyau').replace('portailnoyau', 'portailNoyau') if interdit[0].islower() else interdit not in code_mig,
       'migrer.py n\'allume aucun interrupteur et ne supprime rien (%s)' % interdit.strip())
ok("raise C.Echec('En production, --sauvegardes est obligatoire" in mig and mig.index('sauvegarder_avant(a.sauvegardes, etape)') < mig.index('fichier = appliquer(c, etape, chemin, ref)'),
   'en production, la sauvegarde vérifiée précède chaque étape')
ok(mig.index('verifier_identite(c, a.cible') < mig.index('etat = lire_etat(c)'), 'la base est reconnue à son adresse AVANT toute connexion')
ok("'--single-transaction', '-c', reglages, '-f', tmp, '-f', journal" in mig and "lock_timeout = '30s'" in mig,
   'une étape du noyau et sa ligne de journal : une transaction ; un verrou introuvable fait échouer, ne bloque pas le site')
wm = (RACINE / 'scripts/migration/modele-workflow-migration.yml').read_text(encoding='utf-8')
ok(re.search(r'permissions:\s*\n\s*contents:\s*read', wm) and 'merge-base --is-ancestor "$REF" origin/main' in wm,
   'migration : permissions en lecture, version exigée dans main (relue par PR et CI)')
ok(not re.search(r'run:[^\n]*\$\{\{\s*inputs\.', wm) and not re.search(r'\n\s{10,}[^\n]*\$\{\{\s*inputs\.[^\n]*\n', wm.split('steps:', 1)[1].split('uses: actions/checkout@v4')[0]),
   'migration : les entrées passent par l\'environnement, jamais collées dans un script')
ok('secrets.SES_DB_URL' in wm and 'secrets.SES_STAGING_DB_URL' in wm and not re.search(r'postgres(ql)?://[^\s$]*supabase', wm),
   'migration : les bases viennent de secrets')
ok('sauvegardes/*.tar.gz.age' in wm and '.dump' not in wm and '.csv' not in wm and 'retention-days: 90' in wm,
   'migration : seules les sauvegardes chiffrées sont conservées, 90 jours')

# 13. La recopie : allumée dans l'ordre sûr, jamais un interrupteur de config.js ---------------
inter = (RACINE / 'scripts/exploitation/interrupteurs.py').read_text(encoding='utf-8')
corps = inter.split('def allumer(c):', 1)[1].split('def eteindre(c):', 1)[0]
ok(corps.index('run_migration') < corps.index('cron.schedule') < corps.index('set_double_write(true)'),
   'recopie : rattrapage prêt, PUIS planification, PUIS interrupteur (une file jamais traitée est pire que pas de file)')
eteint = inter.split('def eteindre(c):', 1)[1].split('def main', 1)[0]
ok(eteint.index('set_double_write(false)') < eteint.index('cron.unschedule'), 'recopie : on éteint l\'interrupteur avant de retirer la planification')
code_inter = re.sub(r'(?s)""".*?"""', '', inter)
ok(not re.search(r'(?i)\b(drop|delete|truncate)\b', code_inter) and 'config.js' not in code_inter, 'interrupteurs.py ne supprime rien et ne touche pas config.js')
ok("verifier_base(c, a.reference_projet)" in inter and inter.index('verifier_base(c, a.reference_projet)') < inter.index("if a.commande == 'recopie-allumer':"),
   'interrupteurs.py reconnaît la production (adresse, contenu, noyau complet) avant tout geste')
we = (RACINE / 'scripts/exploitation/modele-workflow-exploitation.yml').read_text(encoding='utf-8')
ok('schedule:' not in we and 'cron:' not in we, 'aucun workflow à intervalles : la planification vit dans la base')
ok(re.search(r'permissions:\s*\n\s*contents:\s*read', we) and 'merge-base --is-ancestor "$REF" origin/main' in we and '--exiger-verification' in we,
   'interrupteurs : lecture seule, version dans main, sauvegarde vérifiée avant d\'allumer')

print('PASS sauvegarde (statique) : %d vérifications — scripts, mots de passe et clés jamais exposés, rotation, archive piégée, '
      'garde-fous alignés sur config.js, déclencheur restauré identique, modèle de workflow, noyau sauvegardé, migration gardée.' % N)
