#!/usr/bin/env python3
"""Validation automatique des migrations SQL — avant même de les essayer sur PostgreSQL.

    python3 outils/tests/migrations-garde-fou.py

Une migration se colle à la main dans la base de PRODUCTION. Ce test refuse, sans rien exécuter :
- toute instruction DESTRUCTIVE au niveau du script : drop table / schema / database / extension / sequence,
  alter table … drop column, changement de type d'une colonne, truncate, delete, rename ;
- toute création NON REJOUABLE : create table / index / sequence / schema sans « if not exists », add column sans
  « if not exists », create function sans « or replace », drop … sans « if exists » ;
- un fichier de migration oublié par l'essai de rejeu (schema-rejouable.py) : il échapperait à toute preuve ;
- un fichier à coller sans l'avertissement « speed-express-site » (le projet Goship partage le même compte).
Les corps de fonctions ($$ … $$) ne sont pas examinés : ce qu'ils font est éprouvé par les essais PostgreSQL.
Les scripts de PRÉPRODUCTION (outils/staging/) ont leur propre règle : ils peuvent effacer, mais seulement derrière le
marqueur « staging » (vérifié ici, et prouvé sur PostgreSQL par staging-essai.py)."""
import glob
import os
import re
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
N = [0]
ECHECS = []


def ok(c, m):
    N[0] += 1
    if not c:
        ECHECS.append(m)


def instructions(sql):
    """Les instructions du script, sans commentaires, sans chaînes, sans corps de fonctions."""
    s = re.sub(r'--[^\n]*', '', sql)
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.S)
    s = re.sub(r'(\$[A-Za-z_]*\$).*?\1', '$corps$', s, flags=re.S)
    s = re.sub(r"'(?:[^']|'')*'", "''", s)
    return [re.sub(r'\s+', ' ', i).strip().lower() for i in s.split(';') if i.strip()]


# Exceptions examinées une par une : (fichier, début d'instruction, raison).
PERMIS = [
    ('007-finance.sql', 'alter table logistics.invoice_item alter column unit_price type numeric(12, 4)',
     'élargissement de précision (10,2 → 12,4) sur une table du noyau : aucune valeur ne peut être perdue'),
]

DESTRUCTIF = [
    (r'^drop (table|schema|database|extension|sequence|materialized view)\b', 'suppression d\'objet porteur de données'),
    (r'^truncate\b', 'vidage de table'),
    (r'^delete\b', 'effacement de lignes'),
    (r'^alter table .* drop column\b', 'suppression de colonne'),
    (r'^alter table .* alter column .* type\b', 'changement de type de colonne (réécriture des données)'),
    (r'\brename (to|column)\b', 'renommage (casse le site et l\'application en place)'),
]
NON_REJOUABLE = [
    (r'^create (unlogged )?table (?!if not exists)', 'create table sans « if not exists »'),
    (r'^create (unique )?index (?!(concurrently )?if not exists)', 'create index sans « if not exists »'),
    (r'^create sequence (?!if not exists)', 'create sequence sans « if not exists »'),
    (r'^create schema (?!if not exists)', 'create schema sans « if not exists »'),
    (r'\badd column (?!if not exists)', 'add column sans « if not exists »'),
    (r'^create function\b', 'create function sans « or replace »'),
    (r'^drop (view|function|trigger|policy|index|type) (?!if exists)', 'drop sans « if exists »'),
    (r'\bdrop constraint (?!if exists)', 'drop constraint sans « if exists »'),
]


def permis(nom, inst):
    return any(nom == f and inst.startswith(debut) for f, debut, _ in PERMIS)


def examiner(chemin):
    nom = os.path.basename(chemin)
    for inst in instructions(open(chemin, encoding='utf-8').read()):
        if permis(nom, inst):
            continue
        for motif, quoi in DESTRUCTIF + NON_REJOUABLE:
            ok(not re.search(motif, inst), '%s : %s — « %s »' % (nom, quoi, inst[:140]))


migrations = sorted(glob.glob(os.path.join(RACINE, 'outils', '*.sql')))
noyau = sorted(glob.glob(os.path.join(RACINE, 'outils', 'logistique', '*.sql')))
for f in migrations + noyau:
    examiner(f)
    texte = open(f, encoding='utf-8').read()
    ok('speed-express-site' in texte[:3000], '%s : l\'en-tête doit rappeler de vérifier le projet « speed-express-site » avant de coller' % os.path.basename(f))

# Chaque migration de l'héritage est rejouée par schema-rejouable.py, dans l'ordre déclaré.
rejouable = open(os.path.join(RACINE, 'outils', 'tests', 'schema-rejouable.py'), encoding='utf-8').read()
ordre = re.findall(r"'(supabase[\w.-]*\.sql)'", re.search(r'^ORDRE = \[(.*?)\]', rejouable, re.M | re.S).group(1))
for f in migrations:
    ok(os.path.basename(f) in ordre, '%s n\'est pas dans ORDRE de schema-rejouable.py : aucun essai ne la rejouerait' % os.path.basename(f))
ok(set(ordre) == {os.path.basename(f) for f in migrations}, 'ORDRE de schema-rejouable.py cite un fichier qui n\'existe pas')
catalogue = open(os.path.join(RACINE, 'outils', 'tests', 'securite-catalogue.py'), encoding='utf-8').read()
ok(re.search(r'^ORDRE = \[(.*?)\]', catalogue, re.M | re.S).group(1).split() == re.search(r'^ORDRE = \[(.*?)\]', rejouable, re.M | re.S).group(1).split(),
   'securite-catalogue.py et schema-rejouable.py doivent installer les mêmes fichiers dans le même ordre')

# Le noyau : des étapes numérotées sans trou (rejouer une étape ancienne après une récente n'est pas sûr : l'ordre compte).
numeros = [int(os.path.basename(f)[:3]) for f in noyau]
ok(numeros == list(range(1, len(numeros) + 1)), 'étapes du noyau non contiguës : %s' % numeros)

# La préproduction : chaque script commence par refuser toute base qui n'est pas marquée « staging ».
for f in sorted(glob.glob(os.path.join(RACINE, 'outils', 'staging', '*.sql'))):
    texte = open(f, encoding='utf-8').read()
    debut = texte[texte.find('do $'):]
    ok("raise exception" in debut[:900] and "staging" in debut[:900] and texte.find('do $') < texte.lower().find(';\n') + 2000,
       '%s : un script de préproduction commence par le garde-fou « staging »' % os.path.basename(f))
    ok(re.search(r'^begin;', texte, re.M) and re.search(r'^commit;', texte, re.M),
       '%s : tout le script tient dans une transaction (le garde-fou annule tout, même lancé avec psql sans ON_ERROR_STOP)' % os.path.basename(f))

# Contre-épreuve : le garde-fou attrape vraiment ce qu'il prétend attraper (sinon il passerait toujours).
def attrape(sql):
    return any(re.search(m, i) for i in instructions(sql) for m, _ in DESTRUCTIF + NON_REJOUABLE)


for mauvais in ['drop table public.colis', 'DROP SCHEMA logistics CASCADE', 'truncate public.factures', 'delete from public.clients where true',
                'alter table public.colis drop column note', 'alter table public.colis alter column poids_lb type int',
                'alter table public.colis rename to paquets', 'create table public.x (a int)', 'create index x on public.colis (note)',
                'alter table public.colis add column x int', 'create function public.f() returns int language sql as $$ select 1 $$',
                'drop policy colis_lecture on public.colis', 'alter table public.colis drop constraint x']:
    ok(attrape(mauvais), 'contre-épreuve : « %s » devrait être refusé' % mauvais)
for bon in ["create or replace function public.f() returns void language plpgsql as $$ begin delete from public.x; drop table y; end $$",
            "-- drop table public.colis\nselect 1", "comment on table public.colis is 'drop table, delete from'",
            'revoke truncate, references, trigger on public.colis from anon', 'update public.clients set role = role where false',
            'create table if not exists public.x (a int)', 'alter table public.colis add column if not exists x int']:
    ok(not attrape(bon), 'contre-épreuve : « %s » est permis (corps de fonction, commentaire, chaîne, retrait de droit, rattrapage)' % bon[:60])

if ECHECS:
    print('ÉCHEC garde-fou des migrations (%d sur %d) :' % (len(ECHECS), N[0]))
    for e in ECHECS:
        print('  - ' + e)
    sys.exit(1)
print('PASS garde-fou des migrations : %d vérifications — %d migrations et %d étapes du noyau sans instruction destructive ni création non '
      'rejouable, chacune rejouée par l\'essai PostgreSQL, en-têtes « speed-express-site », scripts de préproduction derrière leur marqueur'
      % (N[0], len(migrations), len(noyau)))
