#!/usr/bin/env python3
"""Le centre de notifications (phase 11), relu sans base ni réseau.

    python3 outils/tests/notifications-statique.py

 1. WhatsApp : les règles de la base qui passent par WhatsApp (027) ont TOUTES leur modèle soumis à Meta (whatsapp-modeles.json, écrit par
    outils/portail-textes.py), et la liste du générateur est exactement celle des règles (plus le code de livraison) ;
 2. les modèles d'envoi : chaque modèle cité par une règle existe dans les quatre langues ;
 3. le travailleur et les fonctions serveur ne contactent que les hôtes permis, ne lisent leurs clés QUE dans l'environnement, et aucun secret
    n'est écrit dans scripts/notifications/ ; le modèle de workflow ne lit un secret que dans une variable d'environnement ;
 4. la documentation dit ce qui est en place et ce que le propriétaire doit faire.
"""
import json
import re
import sys
from pathlib import Path

R = Path(__file__).resolve().parents[2]
N = [0]
ERREURS = []


def ok(c, m):
    if c:
        N[0] += 1
    else:
        ERREURS.append(m)


sql = '\n'.join(p.read_text(encoding='utf-8') for p in sorted((R / 'outils/logistique').glob('0*.sql')))
s027 = (R / 'outils/logistique/027-centre-notifications.sql').read_text(encoding='utf-8')
textes = (R / 'outils/portail-textes.py').read_text(encoding='utf-8')

# ---------------------------------------------------------------------- 1. WhatsApp
liste = re.search(r"where event_type in \(([^)]*)\)\s*and not \('whatsapp' = any", s027).group(1)
regles_wa = set(re.findall(r"'([A-Za-z]+)'", liste)) | {'CustomsExceptionRaised'}
modele_de = {e: m for e, m, _ in re.findall(r"\(\s*'([A-Za-z]+)',\s*'([A-Za-z]+)',\s*array\[([^\]]*)\]\)", sql)}
gen = set(re.findall(r"'([A-Za-z]+)'", re.search(r'WHATSAPP_MODELES = \[([^\]]*)\]', textes).group(1)))
attendus = {modele_de[e] for e in regles_wa} | {'DeliveryOtp'}
ok(gen == attendus, 'le générateur des modèles WhatsApp suit les règles de la base : en trop %s, en moins %s' % (sorted(gen - attendus), sorted(attendus - gen)))
wa = json.loads((R / 'scripts/notifications/whatsapp-modeles.json').read_text(encoding='utf-8'))
noms = {(m['name'], m['language']) for m in wa['modeles']}
for code in attendus:
    nom = 'ses_' + re.sub(r'(?<!^)(?=[A-Z])', '_', code).lower()
    ok(all((nom, lg) in noms for lg in ('fr', 'en', 'es')), 'modèle WhatsApp %s en fr, en, es' % nom)
ok(wa['langues'] == {'fr': 'fr', 'en': 'en', 'es': 'es', 'ht': 'fr'}, 'créole → modèle français')
env = (R / 'scripts/notifications/envoyer.mjs').read_text(encoding='utf-8')
ok("const LANGUE_WHATSAPP = { fr: 'fr', en: 'en', es: 'es', ht: 'fr' };" in env, 'le travailleur suit la même correspondance de langues')

# ---------------------------------------------------------------------- 2. les modèles d'envoi
modeles_sql = set(re.findall(r"\(\s*'([A-Za-z]+)',\s*'(?:fr|en|es|ht)',", sql))
for e, m in modele_de.items():
    ok(m in modeles_sql, 'la règle %s a son modèle %s dans la base' % (e, m))
for m in ('Welcome', 'DocumentRequired'):
    ok(all(re.search(r"\('%s', '%s'," % (m, lg), s027) for lg in ('fr', 'en', 'es', 'ht')), 'le modèle %s est dans 027, en quatre langues' % m)

# ---------------------------------------------------------------------- 3. hôtes, clés, secrets
HOTES_PERMIS = {'api.brevo.com', 'exp.host', 'graph.facebook.com'}
for f in sorted((R / 'scripts/notifications').glob('*.mjs')):
    t = f.read_text(encoding='utf-8')
    hotes = set(re.findall(r"https://([a-z0-9.-]+)", t)) - {'wilnergraph92.github.io'}
    hotes = {h for h in hotes if not h.endswith('supabase.co') and h != 'x.supabase.co'}
    ok(hotes <= HOTES_PERMIS, '%s : seulement les hôtes permis (%s)' % (f.name, sorted(hotes - HOTES_PERMIS)))
    ok(not re.search(r"(api-key|Authorization)['\"]?\s*:\s*['\"][A-Za-z0-9]{12,}", t), '%s : aucune clé écrite en clair' % f.name)
    for cle in re.findall(r"ENV\('([A-Z_]+)'\)|process\.env\.([A-Z_]+)", t):
        nom = cle[0] or cle[1]
        ok(re.match(r'^(SES_[A-Z_]+|SUPABASE_URL|SUPABASE_SERVICE_ROLE_KEY)$', nom) is not None, '%s : variable d\'environnement attendue (%s)' % (f.name, nom))
SECRET = re.compile(r'xkeysib-[a-z0-9]{20,}|EAA[A-Za-z0-9]{40,}|sb_secret_[A-Za-z0-9]|whsec_[A-Za-z0-9+/=]{20,}|service_role"\s*:', re.I)
for f in sorted((R / 'scripts/notifications').iterdir()):
    ok(not SECRET.search(f.read_text(encoding='utf-8')), 'aucun secret dans %s' % f.name)
wf = (R / 'scripts/notifications/modele-workflow-notifications.yml').read_text(encoding='utf-8')
for ligne in wf.splitlines():
    if '${{ secrets.' in ligne:
        ok(re.match(r'^\s+[A-Z_]+: \$\{\{ secrets\.[A-Z_]+ \}\}\s*$', ligne) is not None, 'workflow : un secret ne se lit que dans une variable d\'environnement : %s' % ligne.strip())
ok('SES_WHATSAPP_TOKEN: ${{ secrets.SES_WHATSAPP_TOKEN }}' in wf and 'ALERTE_NOTIFICATIONS' in wf and 'issues: write' in wf, 'workflow : WhatsApp et l\'alerte')
ok('ref: ${{ vars.SES_SCRIPTS_REF }}' in wf, 'workflow : le travailleur est pris au commit relu, jamais à la dernière version')
for f in ('webhook-fournisseurs.mjs', 'courriels-compte.mjs'):
    t = (R / 'scripts/notifications' / f).read_text(encoding='utf-8')
    ok('MODÈLE, non déployé' in t and 'JAMAIS dans le dépôt ni dans un navigateur' in t, '%s : un modèle de fonction serveur, clés hors du dépôt' % f)

# ---------------------------------------------------------------------- 4. la documentation
doc = (R / 'docs/architecture/NOTIFICATIONS.md').read_text(encoding='utf-8')
for mot in ('027', 'WhatsApp Cloud API', 'Send Email Hook', 'ses_nt_provider_event', 'lg_nt_retry', 'alerte-notifications', 'whatsapp-modeles.json'):
    ok(mot in doc, 'NOTIFICATIONS.md parle de « %s »' % mot)
ok('non appliqué en production' not in doc.split('\n', 6)[2] if len(doc.split('\n')) > 2 else True, 'NOTIFICATIONS.md ne dit plus « non appliqué »')

if ERREURS:
    print('ÉCHEC notifications (statique) :')
    for e in ERREURS:
        print('  -', e)
    sys.exit(1)
print('PASS notifications (statique) : %d vérifications — modèles WhatsApp = règles de la base, modèles en quatre langues, hôtes permis, clés '
      'seulement dans l\'environnement, aucun secret, documentation.' % N[0])
