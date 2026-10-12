#!/usr/bin/env python3
"""Aucun secret dans ce dépôt PUBLIC — ni dans les fichiers, ni dans l'historique Git.

    python3 outils/tests/secrets-statique.py

Le dépôt est public : un secret qui y entre est publié, même effacé au commit suivant (il reste dans l'historique).
On cherche les formes reconnaissables des secrets que ce projet manipule ou manipulera :
- Supabase : clé secrète (sb_secret_…), ancienne clé JWT de rôle « service_role » (la clé « anon » et la clé
  sb_publishable_ sont publiques par nature et permises) ;
- paiement (Stripe : sk_/rk_ live et test, whsec_) ; WhatsApp / Meta (EAA…) ; SMTP Brevo (xkeysib-, xsmtpsib-) ;
- clés privées (PEM, compte de service Firebase, age) ; jetons GitHub, Expo, Slack, AWS ; clés Google (AIza…) ;
- chaînes de connexion PostgreSQL avec mot de passe.
Et les workflows du dépôt public ne lisent aucun secret d'Actions (seul GITHUB_TOKEN, fourni par GitHub, est permis).
Les motifs sont écrits en morceaux pour que ce fichier ne se dénonce pas lui-même."""
import base64
import json
import os
import pathlib
import re
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parents[2]
N = [0]
ECHECS = []


def ok(c, m):
    N[0] += 1
    if not c:
        ECHECS.append(m)


def motif(*morceaux):
    return re.compile(''.join(morceaux))


MOTIFS = [
    ('clé secrète Supabase', motif('sb_', 'secret_', r'[A-Za-z0-9_-]{16,}')),
    ('clé Stripe', motif(r'\b(sk|rk)_', r'(live|test)_', r'[0-9A-Za-z]{16,}')),
    ('secret de webhook Stripe', motif('whsec', r'_[A-Za-z0-9]{24,}')),
    ('clé SMTP / API Brevo', motif(r'\bx(keysib|smtpsib)', r'-[a-f0-9]{32,}')),
    ('jeton WhatsApp / Meta', motif(r'\bEAA', r'[A-Za-z0-9]{60,}')),
    ('clé privée PEM', motif('-----BEGIN ', r'(RSA |EC |OPENSSH |DSA |ENCRYPTED )?', 'PRIVATE KEY-----')),
    ('compte de service Google / Firebase', motif(r'"private_', r'key_id"\s*:\s*"[0-9a-f]{20,}')),
    ('clé privée age', motif('AGE-SECRET', r'-KEY-1[0-9A-Z]{50,}')),
    ('jeton GitHub', motif(r'\b(gh[pousr]_[A-Za-z0-9]{30,}|github_', r'pat_[A-Za-z0-9_]{30,})')),
    ('jeton Slack', motif(r'\bxox[abprs]', r'-[A-Za-z0-9-]{20,}')),
    ('clé AWS', motif(r'\bAKIA', r'[0-9A-Z]{16}\b')),
    ('clé Google (Firebase…)', motif(r'\bAIza', r'[0-9A-Za-z_-]{35}\b')),
    ('jeton Expo', motif(r'EXPO_', r'TOKEN\s*[:=]\s*["\']?[A-Za-z0-9_-]{24,}')),
    ('chaîne PostgreSQL avec mot de passe', motif(r'postgres(ql)?://[^:/@\s\'"<>]+:', r'(?!(\*|x@|<|\$\{|mot|MOT|secret|motdepasse|pass@|mdp@))[^@\s\'"<>]{6,}@[a-z0-9.-]+\.(supabase\.co|supabase\.com|pooler)')),
]
JWT = re.compile(r'eyJ[A-Za-z0-9_-]{8,}\.(eyJ[A-Za-z0-9_-]{8,})\.[A-Za-z0-9_-]{8,}')

# Fichiers qui écrivent ces formes comme EXEMPLES ou motifs de détection, examinés un par un.
PERMIS = {
    'outils/tests/sauvegarde-essai.py': {'clé privée age'},          # fabrique une clé jetable le temps de l'essai
    'outils/tests/sauvegarde-statique.py': {'clé privée age', 'chaîne PostgreSQL avec mot de passe'},   # mots de passe inventés : essai du masquage
    'scripts/backup/sauvegarder.py': {'clé privée age'},
}


def role_jwt(charge):
    try:
        return json.loads(base64.urlsafe_b64decode(charge + '=' * (-len(charge) % 4))).get('role')
    except Exception:
        return None


def examiner(rel, texte, ou):
    for nom, m in MOTIFS:
        if nom in PERMIS.get(rel, set()):
            continue
        t = m.search(texte)
        ok(not t, '%s : %s dans %s (« %s… »)' % (ou, nom, rel, t.group(0)[:12] if t else ''))
    for t in JWT.finditer(texte):
        ok(role_jwt(t.group(1)) != 'service_role', '%s : clé JWT « service_role » de Supabase dans %s' % (ou, rel))


# 1. Les fichiers suivis -----------------------------------------------------------------------------------------
suivis = subprocess.run(['git', 'ls-files', '-z'], cwd=RACINE, stdout=subprocess.PIPE, check=True).stdout.decode().split('\0')
BINAIRES = ('.png', '.jpg', '.jpeg', '.webp', '.avif', '.ico', '.woff', '.woff2', '.pdf', '.gif')
for rel in filter(None, suivis):
    if rel.endswith(BINAIRES) or not (RACINE / rel).is_file():
        continue
    examiner(rel, (RACINE / rel).read_text(encoding='utf-8', errors='ignore'), 'fichier')
    ok(not re.search(r'(^|/)(\.env(\..*)?|.*\.(pem|key|p12|p8|keystore|jks|age|dump)|google-services\.json|GoogleService-Info\.plist|'
                     r'service-account.*\.json)$', rel), 'fichier sensible suivi par Git : ' + rel)

# 2. La configuration publiée : seule la clé publique -------------------------------------------------------------
cfg = (RACINE / 'assets/js/config.js').read_text(encoding='utf-8')
cle = re.search(r"supabaseKey:\s*'([^']*)'", cfg)
ok(cle and cle.group(1).startswith('sb_publishable_'), 'config.js : la clé Supabase est la clé PUBLIQUE (sb_publishable_…)')

# 3. Les workflows du dépôt public ne lisent aucun secret ---------------------------------------------------------
for wf in sorted((RACINE / '.github' / 'workflows').glob('*.yml')):
    texte = wf.read_text(encoding='utf-8')
    autres = sorted(set(re.findall(r'secrets\.([A-Za-z0-9_]+)', texte)) - {'GITHUB_TOKEN'})
    ok(not autres, '%s lit des secrets d\'Actions dans un dépôt public : %s (à placer dans un dépôt privé)' % (wf.name, ', '.join(autres)))
    ok(not re.search(r'pull_request_target', texte), '%s : « pull_request_target » donnerait des droits d\'écriture au code d\'une PR extérieure' % wf.name)
    ok(re.search(r'^permissions:', texte, re.M), '%s déclare ses permissions (sinon il hérite de celles du dépôt)' % wf.name)

# 4. Tout l'historique (CI : actions/checkout avec fetch-depth: 0) -----------------------------------------------
superficiel = subprocess.run(['git', 'rev-parse', '--is-shallow-repository'], cwd=RACINE, stdout=subprocess.PIPE,
                             universal_newlines=True).stdout.strip() == 'true'
if superficiel:
    print('ATTENTION : copie sans historique — seuls les fichiers actuels sont examinés.')
else:
    commits = subprocess.run(['git', 'rev-list', '--all'], cwd=RACINE, stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout.split()
    tous = '|'.join('(%s)' % m.pattern for _, m in MOTIFS if _ != 'clé privée age') + '|' + JWT.pattern
    vus = set()
    for i in range(0, len(commits), 50):
        r = subprocess.run(['git', 'grep', '-I', '-o', '-P', tous] + commits[i:i + 50], cwd=RACINE, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, universal_newlines=True, errors='ignore')
        for ligne in r.stdout.splitlines():
            commit, rel, trouve = ligne.split(':', 2)
            if (rel, trouve) in vus:
                continue
            vus.add((rel, trouve))
            examiner(rel, trouve, 'historique (%s)' % commit[:7])
    ok(True, 'historique examiné : %d commits' % len(commits))

# Contre-épreuve : de faux secrets, fabriqués ici en morceaux, doivent être vus (sinon le test passerait toujours).
avant = len(ECHECS)
faux_jwt = 'eyJhbGciOiJIUzI1NiJ9.' + base64.urlsafe_b64encode(json.dumps({'role': 'service_' + 'role'}).encode()).decode().rstrip('=') + '.c2lnbmF0dXJlLWZhdXNzZQ'
for faux in ['sb_' + 'secret_' + 'A' * 30, 'sk_' + 'live_' + '4' * 24, 'whsec' + '_' + 'b' * 30, 'xkeysib' + '-' + 'a' * 64, 'EAA' + 'Z' * 80,
             '-----BEGIN ' + 'PRIVATE KEY-----', 'ghp' + '_' + 'x' * 36, 'AKIA' + 'ABCDEFGHIJKLMNOP', 'AIza' + 'S' * 35, faux_jwt,
             'postgresql://postgres.ref:' + 'Vr4iM0tDeP' + '@aws-0-us.pooler.supabase.com:5432/postgres']:
    examiner('contre-epreuve.txt', faux, 'contre-épreuve')
vus_faux = len(ECHECS) - avant
del ECHECS[avant:]
ok(vus_faux == 11, 'contre-épreuve : %d faux secrets sur 11 détectés' % vus_faux)
avant = len(ECHECS)
examiner('contre-epreuve.txt', "supabaseKey: 'sb_publishable_abc' ; anon eyJhbGciOiJIUzI1NiJ9." +
         base64.urlsafe_b64encode(b'{"role":"anon"}').decode().rstrip('=') + ".c2lnbmF0dXJl ; postgresql://u:***@h/b", 'contre-épreuve')
ok(len(ECHECS) == avant, 'contre-épreuve : la clé publique, la clé « anon » et un mot de passe masqué ne sont pas des secrets')
del ECHECS[avant:]

if ECHECS:
    print('ÉCHEC secrets (%d) :' % len(ECHECS))
    for e in ECHECS:
        print('  - ' + e)
    sys.exit(1)
print('PASS secrets : %d vérifications — aucune clé secrète Supabase, de paiement, WhatsApp, SMTP, GitHub, Expo, Google ou AWS, aucune clé '
      'privée, aucune chaîne de connexion avec mot de passe, ni dans les fichiers ni dans l\'historique%s ; config.js ne porte que la clé '
      'publique ; aucun workflow public ne lit de secret' % (N[0], '' if superficiel else ' complet'))
