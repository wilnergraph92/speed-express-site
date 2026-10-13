#!/usr/bin/env python3
"""Appliquer les migrations du noyau logistique à une base Supabase, étape par étape, avec ses garde-fous.

    SES_DB_URL='postgresql://…'  python3 scripts/migration/migrer.py --cible preproduction --etape installation --jusqua 021
    SES_DB_URL='postgresql://…'  SES_AGE_RECIPIENT='age1…'  SES_VERIF_DB_URL='postgresql://…'  \\
        python3 scripts/migration/migrer.py --cible production --etape 001 --jusqua 021 --sauvegardes ./sauvegardes
    … + --executer pour appliquer (sans lui : le PLAN seulement, rien n'est écrit)

Ce script remplace le collage à la main dans le SQL Editor (docs/production/GO-LIVE-CHECKLIST.md §4) ; il fait les mêmes gestes,
dans le même ordre, et ajoute ce qu'un collage pressé oublie :

  • la BONNE base. La production doit être le projet « speed-express-site » (sa référence dans l'adresse), porter l'espace client
    et ne PAS être marquée « staging » ; la préproduction doit être marquée « staging » et ne jamais être la production ni Goship.
    Les deux sont vérifiés AVANT chaque étape ;
  • l'ORDRE. Un journal (ses_meta.migration, écrit dans la même transaction que l'étape) dit ce qui est passé ; une étape n'est
    acceptée que si toutes les précédentes y sont ; rejouer la DERNIÈRE est permis (toutes sont rejouables), une plus ancienne
    jamais (006 ne le supporte pas). Un noyau présent sans journal (collé à la main) arrête tout : on ne devine pas ce qui manque ;
  • une SAUVEGARDE VÉRIFIÉE avant chaque étape en production (scripts/backup/sauvegarder.py, restauration de contrôle comprise) :
    sans elle, l'étape ne part pas ;
  • une étape = UNE transaction : une erreur, et rien de l'étape ne reste ; un verrou introuvable en 30 secondes (le site écrit),
    et l'étape échoue proprement au lieu de bloquer le site ;
  • les CONTRÔLES après coup : la santé (ses_health) dès la 013 ; dès la 014, le rattrapage (run_migration) doit être PRÊT (zéro
    écart inexpliqué) ; dès la 015, aucune incohérence de workflow. Le premier écart arrête la suite.

Ce que ce script ne fait JAMAIS : allumer un interrupteur (centreNoyau, portailNoyau, double écriture, bascule financière), supprimer
une donnée, afficher la chaîne de connexion ou son mot de passe.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ICI, '..', 'backup'))
import _commun as C  # noqa: E402

RACINE = C.RACINE
DOSSIER_NOYAU = os.path.join(RACINE, 'outils', 'logistique')
PROJET_PRODUCTION = 'ltbqqchtyzlyakcsxxis'      # public (il figure dans config.js) : un garde-fou, pas un secret
PREPRODUCTION_SEULEMENT = ('installation', 'donnees-synthetiques')

JOURNAL = """
create schema if not exists ses_meta;
revoke all on schema ses_meta from public;
create table if not exists ses_meta.migration (
  etape        text primary key,
  fichier      text not null,
  sha256       text not null,
  ref          text not null,
  premiere_le  timestamptz not null default now(),
  derniere_le  timestamptz not null default now(),
  passages     int not null default 1
);
revoke all on ses_meta.migration from public;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'anon') then execute 'revoke all on ses_meta.migration from anon, authenticated'; end if;
end $$;
insert into ses_meta.migration (etape, fichier, sha256, ref) values (:'etape', :'fichier', :'sha', :'ref')
on conflict (etape) do update set sha256 = excluded.sha256, ref = excluded.ref, derniere_le = now(),
                                  passages = ses_meta.migration.passages + 1;
"""


def etapes_noyau():
    """Les étapes du noyau, dans l'ordre de leur numéro : 001-modele-de-domaine.sql → « 001 »."""
    fichiers = sorted(f for f in os.listdir(DOSSIER_NOYAU) if re.match(r'^\d{3}-.*\.sql$', f))
    return [(f[:3], os.path.join(DOSSIER_NOYAU, f)) for f in fichiers]


def toutes_les_etapes(cible):
    noyau = etapes_noyau()
    if cible == 'production':
        return noyau
    return [('installation', None), ('donnees-synthetiques', os.path.join(RACINE, 'outils', 'staging', 'donnees-synthetiques.sql'))] + noyau


def texte_installation():
    spec = importlib.util.spec_from_file_location('assembler', os.path.join(RACINE, 'outils', 'staging', 'assembler-installation.py'))
    A = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(A)
    return A.assembler()


def empreinte(texte):
    return hashlib.sha256(texte.encode('utf-8')).hexdigest()


# --- Ce que dit la base -----------------------------------------------------------------------------------------------------------

def lire_etat(c):
    l = C.sql(c, "select to_regclass('public.clients') is not null, "
                 "coalesce((select true from pg_class k join pg_namespace n on n.oid = k.relnamespace "
                 "          where n.nspname = 'ses_meta' and k.relname = 'environnement'), false), "
                 "to_regclass('ses_meta.migration') is not null, to_regnamespace('logistics') is not null, "
                 "current_setting('server_version')")[0].split('|')
    etat = {'espace_client': l[0] == 't', 'marquee_staging': False, 'journal': [], 'noyau_present': l[3] == 't', 'postgresql': l[4]}
    if l[1] == 't':
        etat['marquee_staging'] = C.sql(c, "select exists (select 1 from ses_meta.environnement where nom = 'staging')")[0] == 't'
    if l[2] == 't':
        etat['journal'] = C.sql(c, "select etape from ses_meta.migration order by etape")
    return etat


def verifier_identite(c, cible, reference_projet):
    """La bonne base, d'après son ADRESSE (avant toute connexion)."""
    adresse = c['hote'] + ' ' + c['utilisateur']
    autres = [r for r in C.PROJETS_INTERDITS if r != PROJET_PRODUCTION and r in adresse]
    if autres:
        raise C.Echec('ARRÊT : cette adresse est celle du projet protégé « %s » (Goship). Rien n\'est fait.' % autres[0])
    if cible == 'production' and reference_projet not in adresse:
        raise C.Echec('ARRÊT : la cible « production » doit être le projet %s, et cette adresse ne le nomme pas. Rien n\'est fait.'
                      % reference_projet)
    if cible == 'preproduction' and PROJET_PRODUCTION in adresse:
        raise C.Echec('ARRÊT : la cible « preproduction » pointe vers la PRODUCTION (%s). Rien n\'est fait.' % PROJET_PRODUCTION)


def verifier_etat(etat, cible, etape, ordre):
    """La bonne base d'après son CONTENU, et le bon moment d'après le journal. Rend la liste des refus (vide = on peut)."""
    refus = []
    if cible == 'production':
        if etape in PREPRODUCTION_SEULEMENT:
            refus.append('« %s » ne se passe qu\'en préproduction.' % etape)
        if not etat['espace_client']:
            refus.append('cette base ne porte pas l\'espace client (public.clients) : ce n\'est pas la production.')
        if etat['marquee_staging']:
            refus.append('cette base est marquée « staging » : c\'est une PRÉPRODUCTION, pas la production.')
    else:
        if etape == 'installation':
            if etat['espace_client'] and not etat['marquee_staging']:
                refus.append('cette base porte l\'espace client sans être marquée « staging » : est-ce la production ?')
        elif not etat['marquee_staging']:
            refus.append('cette base n\'est pas marquée « staging » : passez d\'abord l\'étape « installation ».')
    if refus:
        return refus
    noyau = [e for e, _ in ordre if re.fullmatch(r'\d{3}', e)]
    faites = [e for e in etat['journal'] if e in noyau]
    if etape == 'installation':
        if faites:
            refus.append('le noyau est déjà passé (%s) : on ne réinstalle pas l\'espace client par-dessus.' % faites[-1])
        return refus
    if etape == 'donnees-synthetiques':
        if 'installation' not in etat['journal']:
            refus.append('l\'installation n\'est pas au journal : passez d\'abord l\'étape « installation ».')
        return refus
    # une étape du noyau
    if etat['noyau_present'] and not faites:
        refus.append('le noyau (schéma logistics) est déjà là, mais le journal ne dit pas quelles étapes sont passées '
                     '(collage à la main ?) : on ne devine pas. Rien n\'est fait.')
    if cible == 'preproduction' and 'installation' not in etat['journal']:
        refus.append('l\'installation n\'est pas au journal : passez d\'abord l\'étape « installation ».')
    rang = noyau.index(etape)
    manquantes = [e for e in noyau[:rang] if e not in faites]
    if manquantes:
        refus.append('l\'étape %s exige que %s soi(en)t passée(s) avant (le journal ne les a pas).' % (etape, ', '.join(manquantes)))
    if etape in faites and faites[-1] != etape:
        refus.append('l\'étape %s est déjà passée et n\'est pas la dernière (%s) : rejouer une étape ancienne après une plus récente '
                     'n\'est pas sûr (006 ne le supporte pas).' % (etape, faites[-1]))
    return refus


# --- La sauvegarde d'avant ---------------------------------------------------------------------------------------------------------

def base_de_controle(etape):
    """La restauration de contrôle exige une base VIDE : une par étape, CRÉÉE (jamais vidée ni supprimée) sur le serveur jetable
    de SES_VERIF_DB_URL. Ce serveur doit être local (le conteneur du workflow) : une adresse distante est refusée."""
    url = C.lire_url('SES_VERIF_DB_URL')
    v = C.decouper(url)
    if v['hote'] not in ('127.0.0.1', 'localhost', '::1'):
        raise C.Echec('SES_VERIF_DB_URL doit être un PostgreSQL LOCAL et jetable (le conteneur du workflow), pas %s.' % v['hote'])
    nom = 'ses_controle_%s_%s' % (re.sub(r'\W', '_', etape), os.getpid())
    C.sql(v, 'create database %s' % nom)
    morceaux = urlsplit(url)
    return urlunsplit((morceaux.scheme, morceaux.netloc, '/' + nom, morceaux.query, morceaux.fragment))


def sauvegarder_avant(dossier, etape):
    """scripts/backup/sauvegarder.py, vérification par restauration EXIGÉE. Rend la ligne de son journal ; échoue sinon."""
    os.makedirs(dossier, exist_ok=True)
    journal = os.path.join(dossier, 'journal.jsonl')
    avant = open(journal, encoding='utf-8').read().count('\n') if os.path.isfile(journal) else 0
    C.info('  · sauvegarde « avant-migration-%s » (restauration de contrôle exigée)…' % etape)
    env = dict(os.environ, SES_VERIF_DB_URL=base_de_controle(etape))
    r = subprocess.run([sys.executable, os.path.join(ICI, '..', 'backup', 'sauvegarder.py'), '--sortie', dossier, '--exiger-verification'],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, env=env)
    lignes = open(journal, encoding='utf-8').read().splitlines() if os.path.isfile(journal) else []
    derniere = json.loads(lignes[-1]) if len(lignes) > avant else {}
    if r.returncode != 0 or derniere.get('statut') != 'ok' or derniere.get('verification') != 'complete':
        raise C.Echec('SAUVEGARDE AVANT L\'ÉTAPE %s EN ÉCHEC : l\'étape ne part pas.\n%s' % (etape, C.nettoyer(r.stdout.strip()[-800:])))
    C.info('    sauvegarde vérifiée : %s (%s table(s), %s ligne(s))' % (derniere['fichier'], derniere['tables'], derniere['lignes']))
    return derniere


# --- Appliquer une étape -----------------------------------------------------------------------------------------------------------

def psql(c, args, timeout=1800):
    """psql sur la base, sans les réglages de session des sauvegardes (fuseau UTC…) : une étape se passe comme au SQL Editor."""
    env = C.env_pg(c)
    env.pop('PGOPTIONS', None)
    return C.executer([C.outil('psql'), '-qAtX', '-v', 'ON_ERROR_STOP=1'] + args, env=env, timeout=timeout)


def appliquer(c, etape, chemin, ref):
    """L'étape et sa ligne de journal dans UNE transaction. L'installation et les données synthétiques ont la leur (et leur
    garde-fou, qui doit pouvoir tout annuler) : leur ligne de journal suit, à part."""
    if etape == 'installation':
        texte, nom = texte_installation(), 'outils/staging/assembler-installation.py'
    else:
        texte, nom = open(chemin, encoding='utf-8').read(), os.path.relpath(chemin, RACINE)
    variables = ['-v', 'etape=' + etape, '-v', 'fichier=' + nom, '-v', 'sha=' + empreinte(texte), '-v', 'ref=' + ref]
    reglages = "set lock_timeout = '30s'; set statement_timeout = 0; set search_path = public, extensions;"
    tmp = os.path.join(os.environ.get('RUNNER_TEMP') or '/tmp', 'ses-migration-%s-%s.sql' % (os.getpid(), etape))
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(texte)
    journal = tmp + '.journal'
    with open(journal, 'w', encoding='utf-8') as f:
        f.write(JOURNAL)
    try:
        if etape in PREPRODUCTION_SEULEMENT:
            psql(c, variables + ['-c', reglages, '-f', tmp])
            psql(c, variables + ['--single-transaction', '-f', journal])
        else:
            psql(c, variables + ['--single-transaction', '-c', reglages, '-f', tmp, '-f', journal])
    finally:
        for p in (tmp, journal):
            if os.path.exists(p):
                os.remove(p)
    return nom


def controler(c, etape, cible, ref):
    """Les vérifications après coup (GO-LIVE-CHECKLIST.md §4). Rend un résumé ; échoue au premier écart."""
    resume = {}
    if not re.fullmatch(r'\d{3}', etape):
        if etape == 'donnees-synthetiques':
            resume['colis'] = int(C.sql(c, 'select count(*) from public.colis')[0])
        return resume
    n = int(etape)
    resume['fonctions_lg'] = int(C.sql(c, "select count(*) from pg_proc where proname like 'lg\\_%'")[0])
    if n >= 13:
        sante = json.loads(C.sql(c, 'select public.ses_health()')[0])
        resume['sante'] = sante.get('status')
        resume['niveau'] = sante.get('schema_level')
        if sante.get('status') != 'ok':
            raise C.Echec('CONTRÔLE : ses_health() ne dit pas « ok » après l\'étape %s : %s' % (etape, sante))
    if n >= 14:
        run = json.loads(C.sql(c, "select logistics.run_migration('migration %s, étape %s (%s)')" % (cible, etape, ref[:12]), timeout=3600)[0])
        rapport = run.get('report') or {}
        resume['rattrapage'] = {'statut': run.get('status'), 'pret': rapport.get('ready'), 'inexpliques': rapport.get('unexplained')}
        if run.get('status') != 'ok' or rapport.get('ready') is not True or rapport.get('unexplained') != 0:
            raise C.Echec('CONTRÔLE : après l\'étape %s, le rattrapage n\'est PAS prêt : %s. La suite attend : lire '
                          'select logistics.migration_report(); (docs/architecture/MIGRATION-REPORT.md §5).'
                          % (etape, json.dumps(resume['rattrapage'], ensure_ascii=False)))
    if n >= 15:
        incoherences = int(C.sql(c, 'select count(*) from logistics.workflow_inconsistencies()')[0])
        resume['incoherences_workflow'] = incoherences
        if incoherences:
            raise C.Echec('CONTRÔLE : %s incohérence(s) de workflow après l\'étape %s (select * from logistics.workflow_inconsistencies();).'
                          % (incoherences, etape))
    return resume


# --- Le déroulé --------------------------------------------------------------------------------------------------------------------

def plage(ordre, debut, fin):
    noms = [e for e, _ in ordre]
    if debut not in noms:
        raise C.Echec('Étape inconnue : %s (connues : %s).' % (debut, ', '.join(noms)))
    fin = fin or debut
    if fin not in noms or noms.index(fin) < noms.index(debut):
        raise C.Echec('« --jusqua %s » doit être une étape connue, égale ou postérieure à %s.' % (fin, debut))
    return ordre[noms.index(debut):noms.index(fin) + 1]


def ref_courante():
    ref = os.environ.get('SES_MIGRATION_REF', '').strip()
    if ref:
        return ref
    try:
        return subprocess.run(['git', '-C', RACINE, 'rev-parse', 'HEAD'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              universal_newlines=True).stdout.strip() or 'inconnue'
    except OSError:
        return 'inconnue'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--cible', choices=('preproduction', 'production'), required=True)
    ap.add_argument('--etape', required=True, help='la première étape : installation, donnees-synthetiques (préproduction), 001 … 021')
    ap.add_argument('--jusqua', default='', help='la dernière étape de la série (par défaut : la seule --etape)')
    ap.add_argument('--sauvegardes', default='', help='dossier des sauvegardes d\'avant chaque étape (OBLIGATOIRE en production)')
    ap.add_argument('--executer', action='store_true', help='appliquer pour de bon (sans cela : le plan seulement)')
    ap.add_argument('--reference-projet', default=PROJET_PRODUCTION, help=argparse.SUPPRESS)   # les essais seulement
    a = ap.parse_args(argv)

    c = C.decouper(C.lire_url('SES_DB_URL'))
    verifier_identite(c, a.cible, a.reference_projet)
    if a.cible == 'production' and a.executer and not a.sauvegardes:
        raise C.Echec('En production, --sauvegardes est obligatoire : une sauvegarde vérifiée précède chaque étape.')
    ordre = toutes_les_etapes(a.cible)
    serie = plage(ordre, a.etape, a.jusqua)
    ref = ref_courante()
    etat = lire_etat(c)
    C.info('Base : %s (PostgreSQL %s) — cible « %s »' % (C.identite_publique(c), etat['postgresql'], a.cible))
    C.info('Journal : %s' % (', '.join(etat['journal']) or 'vide'))
    C.info('Série : %s — version des fichiers : %s' % (', '.join(e for e, _ in serie), ref))

    if not a.executer:
        refus = verifier_etat(etat, a.cible, serie[0][0], ordre)
        if refus:
            raise C.Echec('REFUSÉ :\n  - ' + '\n  - '.join(refus))
        C.info('\nPlan seulement : rien n\'a été écrit. Ajoutez --executer pour appliquer.')
        return 0

    bilan = []
    for etape, chemin in serie:
        C.info('\n== Étape %s ==' % etape)
        etat = lire_etat(c)
        refus = verifier_etat(etat, a.cible, etape, ordre)
        if refus:
            raise C.Echec('ÉTAPE %s REFUSÉE :\n  - %s' % (etape, '\n  - '.join(refus)))
        sauvegarde = sauvegarder_avant(a.sauvegardes, etape) if a.cible == 'production' else None
        C.info('  · application (une seule transaction)…')
        fichier = appliquer(c, etape, chemin, ref)
        resume = controler(c, etape, a.cible, ref)
        ligne = {'etape': etape, 'fichier': fichier, 'controle': resume}
        if sauvegarde:
            ligne['sauvegarde'] = sauvegarde['fichier']
        bilan.append(ligne)
        C.info('  · passée : %s' % json.dumps(resume, ensure_ascii=False, sort_keys=True))
    C.info('\nMIGRATION OK : %s étape(s) passée(s) (%s), sur la cible « %s ».' % (len(bilan), ', '.join(b['etape'] for b in bilan), a.cible))
    C.info('RESULTAT ' + json.dumps({'cible': a.cible, 'ref': ref, 'etapes': bilan}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except C.Echec as e:
        print('ÉCHEC : ' + C.nettoyer(e), file=sys.stderr)
        sys.exit(1)
