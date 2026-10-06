#!/usr/bin/env python3
"""Sauvegarde → chiffrement → vérification → restauration → validation, DE BOUT EN BOUT,
sur un vrai PostgreSQL jetable. Jamais la production.

    SES_PG_BIN=/dossier/des/binaires/postgres python3 outils/tests/sauvegarde-essai.py

Il faut un dossier contenant initdb, pg_ctl, postgres, psql, pg_dump et pg_restore
(PostgreSQL 15 à 17), et `age` / `age-keygen` dans le PATH. Sans SES_PG_BIN, le test
s'annonce SAUTÉ (il n'échoue pas : c'est un essai lourd, comme celui des rôles SQL).

Ce que le test fait :
  1. démarre un PostgreSQL vide dans un dossier temporaire, sur un port local ;
  2. y charge le VRAI schéma du projet (outils/*.sql) et des données FICTIVES
     (adresses en .test, accents, apostrophes, retours à la ligne, emoji) ;
  3. sauvegarde, avec contrôle de restauration, puis restaure dans une base vide ;
  4. éprouve la base restaurée comme le ferait un client (sécurité par ligne, séquences,
     inscription) ;
  5. prouve que les garde-fous et la validation PEUVENT échouer : octet altéré, mauvaise
     clé, cible non vide, cible protégée, ligne modifiée, ligne supprimée, séquence
     faussée, règle de sécurité perdue, table ajoutée demain.
"""
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(RACINE, 'scripts', 'backup'))
sys.path.insert(0, os.path.join(RACINE, 'scripts', 'restore'))

PG = os.environ.get('SES_PG_BIN', '').strip()
if not PG:
    print('SKIP sauvegarde de bout en bout : définissez SES_PG_BIN (dossier des binaires PostgreSQL).')
    sys.exit(0)
os.environ['SES_PG_BIN'] = PG
for outil in ('initdb', 'pg_ctl', 'postgres', 'psql', 'pg_dump', 'pg_restore'):
    if not os.access(os.path.join(PG, outil), os.X_OK):
        print('ÉCHEC : %s introuvable dans SES_PG_BIN=%s' % (outil, PG)); sys.exit(1)
for outil in ('age', 'age-keygen'):
    if not shutil.which(outil):
        print('ÉCHEC : %s introuvable dans le PATH' % outil); sys.exit(1)

import _commun as C   # noqa: E402
import restaurer as R   # noqa: E402
import sauvegarder as S   # noqa: E402

N = [0]
MDP = 'Mot2Passe-Secret!42'   # ne doit apparaître NULLE PART dans ce que les scripts écrivent


def ok(cond, msg):
    if not cond:
        raise AssertionError(msg)
    N[0] += 1


def port_libre():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


def pg(port, base, requete, role=None, claims=None, fichier=None, erreur_attendue=False):
    """psql direct sur le cluster d'essai. Rend (code, sortie)."""
    script = ''
    if role:
        script += 'SET ROLE %s;\n' % role
    if claims:
        script += "SELECT set_config('request.jwt.claim.sub', '%s', false);\n" % claims
    script += requete + '\n'
    cmd = [os.path.join(PG, 'psql'), '-h', '127.0.0.1', '-p', str(port), '-U', 'postgres', '-d', base, '-qAtX', '-v', 'ON_ERROR_STOP=1']
    env = dict(os.environ, PGOPTIONS='-c search_path=public,extensions')
    r = subprocess.run(cmd, input=script, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=env)
    if r.returncode != 0 and not erreur_attendue:
        raise AssertionError('SQL en échec sur %s : %s\n%s' % (base, r.stderr.strip()[-300:], requete[:120]))
    if r.returncode != 0:
        return r.returncode, r.stderr.strip()
    lignes = [l for l in r.stdout.splitlines() if l.strip()]
    return 0, (lignes[-1] if lignes else '')   # la dernière ligne : celle de la requête, pas du set_config


def url(port, base):
    return 'postgresql://postgres:%s@127.0.0.1:%s/%s' % (MDP, port, base)


def lancer(script, args, env_extra, cwd=RACINE):
    env = dict(os.environ); env.update(env_extra)
    r = subprocess.run([sys.executable, script] + args, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    return r.returncode, r.stdout + r.stderr


def cle_age(dossier, nom):
    chemin = os.path.join(dossier, nom)
    subprocess.run(['age-keygen', '-o', chemin], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    os.chmod(chemin, 0o600)
    pub = re.search(r'public key: (age1\w+)', open(chemin).read()).group(1)
    return chemin, pub


# --- Données fictives -------------------------------------------------------

AUTH = """
create table auth.users (
  instance_id uuid, id uuid primary key, aud varchar(255), role varchar(255), email varchar(255) unique,
  encrypted_password varchar(255), email_confirmed_at timestamptz, phone_confirmed_at timestamptz,
  created_at timestamptz default now(), updated_at timestamptz, last_sign_in_at timestamptz,
  raw_app_meta_data jsonb, raw_user_meta_data jsonb default '{}'::jsonb, is_super_admin boolean,
  confirmed_at timestamptz generated always as (least(email_confirmed_at, phone_confirmed_at)) stored
);
create table auth.identities (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
  identity_data jsonb not null, provider text not null, provider_id text not null,
  last_sign_in_at timestamptz, created_at timestamptz default now(), updated_at timestamptz,
  email text generated always as (lower(identity_data ->> 'email')) stored, unique (provider_id, provider)
);
"""

APPAREILS = """
create table public.appareils (
  jeton text primary key, client_id uuid not null references public.clients (id) on delete cascade,
  plateforme text, vu_le timestamptz not null default now(), cree_le timestamptz not null default now());
alter table public.appareils enable row level security;
create policy appareils_lecture on public.appareils for select to authenticated using (client_id = (select auth.uid()));
create policy appareils_ajout on public.appareils for insert to authenticated with check (client_id = (select auth.uid()));
grant select, insert, update, delete on public.appareils to authenticated;
"""

NOMS = ["Marie-Ève Léger", "Jean D'Alembert", "Société « Étoile & Fils »", "Ana Pérez", "Wilfrid \"Wil\" Jean-Baptiste",
        "Fanmi Pòtoprens 🇭🇹", "O'Brien, Sean", "Chantal Pierre", "Luc Saint-Fleur", "Maëlle Désir", "Carlos Núñez",
        "Roseline Augustin", "Ève-Marie Thélusma", "Dimitri Volkov"]

DONNEES = """
insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at, phone_confirmed_at, raw_user_meta_data, last_sign_in_at)
select '00000000-0000-0000-0000-000000000000', ('00000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid, 'authenticated', 'authenticated',
       'client' || i || '@essai.test', '$2a$10$fictif' || i, now() - (i || ' days')::interval, now() - (i || ' days')::interval,
       jsonb_build_object('nom_complet', (%(noms)s::text[])[i], 'pays', 'Haïti', 'ville', 'Pétion-Ville',
                          'adresse', E'12 rue de l''Église\\nApt « 4 »', 'telephone', '+509 3' || lpad(i::text, 7, '0'), 'langue', (array['fr','en','es','ht'])[1 + i %% 4]),
       now() - (i || ' hours')::interval
from generate_series(1, 14) i;
insert into auth.identities (user_id, identity_data, provider, provider_id)
select id, jsonb_build_object('email', email, 'sub', id::text), 'email', id::text from auth.users;

update public.clients set role = 'admin' where code is not null and email = 'client1@essai.test';
update public.clients set role = 'gerant' where email = 'client2@essai.test';
update public.clients set role = 'employe', droits = array['colis.lire','colis.statut'] where email in ('client3@essai.test', 'client4@essai.test');

select setseed(0.42);
insert into public.colis (client_id, description, expediteur, destinataire, poids_lb, tarif_lb, service, pays_destination, ville_destination, valeur_declaree, statut, lieu, note)
select c.id, 'Colis n°' || g || E' — vêtements, "chaussures" & jouets', 'Miami, FL', 'Dest. ' || g, round((1 + random() * 60)::numeric, 2), round((1.5 + random() * 2)::numeric, 2),
       (array['aerien','maritime','terrestre'])[1 + g %% 3], (array['HT','DO','US'])[1 + g %% 3], 'Ville ' || g, round((random() * 300)::numeric, 2),
       'confirme', 'Entrepôt Miami', 'note, avec virgule'
from public.clients c cross join generate_series(1, 20) g
where c.role in ('client');
update public.colis set statut = 'expedie', lieu = 'En vol' where (id::text) < '4';
update public.colis set statut = 'disponible', lieu = 'Port-au-Prince' where (id::text) between '4' and '6';
update public.colis set statut = 'livre', lieu = 'Livré', note = 'remis en main propre' where (id::text) between '6' and '7';
update public.factures set montant_paye = montant where (id::text) < '5';
update public.factures set montant_paye = 15 where (id::text) between '5' and '6' and montant > 15;
insert into public.factures (client_id, colis_id, montant, frais_service, devise, groupee, note, lignes)
select client_id, null, 100.50, 10, 'USD', true, 'Regroupe : essai', '[{"numero":"X","montant":90.5}]'::jsonb
from public.colis limit 1;
insert into public.appareils (jeton, client_id, plateforme)
select 'ExponentPushToken[essai-' || n || ']', id, (array['ios','android'])[1 + n %% 2]
from (select id, row_number() over () n from public.clients where role = 'client' limit 6) q;
"""


def monter_source(port, dossier_sql):
    pg(port, 'postgres', 'create database source')
    socle = open(os.path.join(RACINE, 'scripts', 'restore', 'socle-postgres-vide.sql'), encoding='utf-8').read()
    pg(port, 'source', socle)
    pg(port, 'source', AUTH)
    for f in ('supabase.sql', 'supabase-maj-facture-groupee.sql', 'supabase-maj-jeton.sql', 'supabase-dashboard.sql', 'supabase-maj.sql'):
        pg(port, 'source', open(os.path.join(RACINE, 'outils', f), encoding='utf-8').read())
    # (« appareils » vient de supabase-maj.sql, section 9)
    pg(port, 'source', DONNEES % {'noms': "array[%s]" % ','.join("'%s'" % n.replace("'", "''") for n in NOMS)})


def main():
    racine_tmp = tempfile.mkdtemp(prefix='ses-essai-sauv-')
    os.chmod(racine_tmp, 0o700)
    port = port_libre()
    donnees = os.path.join(racine_tmp, 'pg')
    serveur = None
    try:
        subprocess.run([os.path.join(PG, 'initdb'), '-D', donnees, '-U', 'postgres', '--auth=trust', '-E', 'UTF8', '--locale=C'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        subprocess.run([os.path.join(PG, 'pg_ctl'), '-D', donnees, '-l', os.path.join(racine_tmp, 'pg.log'), '-w', '-o',
                        "-p %s -c listen_addresses=127.0.0.1 -c unix_socket_directories='' -c fsync=off" % port, 'start'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        serveur = True

        # ---------------------------------------------------------------- 1. source fictive
        monter_source(port, None)
        n_colis = int(pg(port, 'source', 'select count(*) from public.colis')[1])
        n_clients = int(pg(port, 'source', 'select count(*) from public.clients')[1])
        ok(n_colis >= 200 and n_clients == 14, 'données fictives chargées (%s colis, %s clients)' % (n_colis, n_clients))
        ok(int(pg(port, 'source', 'select count(*) from public.colis_historique')[1]) > n_colis, 'historique alimenté par les déclencheurs')
        ok(int(pg(port, 'source', 'select count(*) from public.factures')[1]) > n_colis, 'factures nées des colis, plus une groupée')

        # table de logistique « ajoutée demain » : doit être sauvegardée sans toucher aux scripts
        pg(port, 'source', "create table public.tournee_essai (id serial primary key, chauffeur text, jour date);"
                           "insert into public.tournee_essai (chauffeur, jour) values ('Jean-Marc Étienne', '2026-10-06'), ('Léa', '2026-10-07');"
                           "alter table public.tournee_essai enable row level security;")

        # ---------------------------------------------------------------- 2. clés et sauvegarde
        cles = os.path.join(racine_tmp, 'cles'); os.makedirs(cles, mode=0o700)
        ident, pub = cle_age(cles, 'sauvegarde.key')
        ident_autre, pub_autre = cle_age(cles, 'autre.key')
        sortie = os.path.join(racine_tmp, 'sauvegardes')
        pg(port, 'postgres', 'create database controle')
        env = {'SES_DB_URL': url(port, 'source'), 'SES_AGE_RECIPIENT': pub, 'SES_VERIF_DB_URL': url(port, 'controle'), 'SES_PG_BIN': PG}
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'backup', 'sauvegarder.py'), ['--sortie', sortie, '--exiger-verification'], env)
        ok(code == 0, 'sauvegarde réussie : ' + texte[-400:])
        ok('SAUVEGARDE OK' in texte and 'vérification complete' in texte, 'verification complète annoncée')
        ok('restauration fidèle' in texte, 'restauration de contrôle exécutée avant de rendre l\'archive')
        archives = glob.glob(os.path.join(sortie, 'ses-*.tar.gz.age'))
        ok(len(archives) == 1, 'une archive chiffrée produite')
        archive = archives[0]
        ok(os.path.exists(archive + '.sha256'), 'somme de contrôle de l\'archive écrite')
        ok(oct(os.stat(archive).st_mode & 0o777) == '0o600', 'archive en lecture réservée au propriétaire')
        journal = [json.loads(l) for l in open(os.path.join(sortie, 'journal.jsonl'), encoding='utf-8')]
        ok(len(journal) == 1 and journal[0]['statut'] == 'ok' and journal[0]['verification'] == 'complete', 'journal : une ligne, statut ok, vérification complète')
        ok(journal[0]['tables'] >= 8 and journal[0]['lignes'] > 500, 'journal : tables et lignes comptées')

        # le clair n'est lisible que par la bonne clé ; le fichier n'est pas du tar en clair
        brut = open(archive, 'rb').read()
        ok(brut.startswith(b'age-encryption.org'), 'archive au format age')
        for mot in (b'Marie-', b'essai.test', b'Haiti', b'CREATE TABLE', b'PGDMP'):
            ok(mot not in brut, 'aucune donnée lisible dans l\'archive chiffrée (%s)' % mot.decode())

        # ---------------------------------------------------------------- 3. aucun secret n'a fuité
        tout = texte + open(os.path.join(sortie, 'journal.jsonl'), encoding='utf-8').read() + open(archive + '.sha256').read()
        ok(MDP not in tout, 'le mot de passe de la base n\'apparaît ni dans les messages, ni dans le journal')
        ok('AGE-SECRET-KEY' not in tout, 'aucune clé privée dans les sorties')

        # ---------------------------------------------------------------- 4. restauration (plan, puis exécution)
        pg(port, 'postgres', 'create database restaure')
        envr = {'SES_RESTORE_DB_URL': url(port, 'restaure'), 'SES_PG_BIN': PG}
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'), ['--archive', archive, '--identite', ident], envr)
        ok(code == 0 and 'Plan seulement' in texte, 'plan affiché, rien d\'exécuté : ' + texte[-300:])
        ok(pg(port, 'restaure', "select count(*) from information_schema.tables where table_schema = 'public'")[1] == '0',
           'sans --executer, la cible reste VIDE')
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'), ['--archive', archive, '--identite', ident, '--executer'], envr)
        ok(code == 0 and 'VALIDATION OK' in texte, 'restauration validée : ' + texte[-500:])
        ok(MDP not in texte, 'aucun mot de passe dans la sortie de restauration')

        # ---------------------------------------------------------------- 4b. mode « projet Supabase NEUF »
        # Un projet neuf a déjà ses rôles, son schéma auth et ses tables de comptes (vides) : les
        # comptes se rechargent DANS les tables existantes (données seules), le socle ne passe pas.
        pg(port, 'postgres', 'create database projet_neuf')
        pg(port, 'projet_neuf', open(os.path.join(RACINE, 'scripts', 'restore', 'socle-postgres-vide.sql'), encoding='utf-8').read())
        pg(port, 'projet_neuf', AUTH)
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'),
                             ['--archive', archive, '--identite', ident, '--mode', 'supabase-vide', '--executer'],
                             {'SES_RESTORE_DB_URL': url(port, 'projet_neuf'), 'SES_PG_BIN': PG})
        ok(code == 0 and 'VALIDATION OK' in texte, 'mode projet Supabase neuf : restauration validée : ' + texte[-400:])
        ok(pg(port, 'projet_neuf', "select count(*) from public.clients c join auth.users u on u.id = c.id")[1] == str(n_clients),
           'projet neuf : chaque profil retrouve son compte')

        # ---------------------------------------------------------------- 5. la base restaurée FONCTIONNE
        ok(pg(port, 'restaure', 'select count(*) from public.colis')[1] == str(n_colis), 'restauré : même nombre de colis')
        ok(pg(port, 'restaure', 'select count(*) from public.tournee_essai')[1] == '2', 'table ajoutée « demain » restaurée sans changer les scripts')
        un_client = pg(port, 'restaure', "select id from public.clients where role = 'client' order by code limit 1")[1]
        propres = pg(port, 'restaure', "select count(*) from public.colis where client_id = '%s'" % un_client)[1]
        vus = pg(port, 'restaure', 'select count(*) from public.colis', role='authenticated', claims=un_client)[1]
        ok(vus == propres and int(propres) < n_colis, 'sécurité par ligne : un client ne voit que SES colis (%s sur %s)' % (vus, n_colis))
        c, msg = pg(port, 'restaure', 'select count(*) from public.colis', role='anon', erreur_attendue=True)
        ok(c != 0 and 'permission denied' in msg, 'un anonyme est refusé après restauration')
        c, msg = pg(port, 'restaure', "update public.clients set role = 'admin' where id = '%s'" % un_client, role='authenticated', claims=un_client, erreur_attendue=True)
        ok(c != 0, 'un client ne peut toujours pas se promouvoir après restauration')
        pg(port, 'restaure', "insert into auth.users (id, email) values ('99999999-0000-0000-0000-000000000001', 'nouveau@essai.test')")
        ok(pg(port, 'restaure', "select count(*) from public.clients where email = 'nouveau@essai.test'")[1] == '1',
           'le déclencheur d\'inscription est revenu : un nouvel inscrit reçoit son profil')
        pg(port, 'restaure', "delete from auth.users where id = '99999999-0000-0000-0000-000000000001'")
        max_seq = int(pg(port, 'restaure', "select max(split_part(numero, '-', 2)::int) from public.colis")[1])
        suivant = int(pg(port, 'restaure', "select nextval('public.numero_colis_seq')")[1])
        ok(suivant > max_seq, 'le prochain numéro de colis (%s) dépasse le plus grand existant (%s) : pas de doublon' % (suivant, max_seq))
        un_numero = pg(port, 'restaure', 'select numero from public.colis limit 1')[1]
        ok(pg(port, 'restaure', "select (public.suivre_colis('%s'))->>'statut'" % un_numero, role='anon')[1] != '', 'suivi public fonctionnel après restauration')
        ok(pg(port, 'restaure', "select count(*) from pg_publication_tables where pubname = 'supabase_realtime'")[1] == '3', 'temps réel : 3 tables publiées')

        # ---------------------------------------------------------------- 6. ÇA PEUT ÉCHOUER (preuves par mutation)
        # 6a. un octet altéré dans l'archive chiffrée
        alteree = os.path.join(racine_tmp, 'alteree.tar.gz.age')
        b = bytearray(brut); b[len(b) // 2] ^= 0xFF; open(alteree, 'wb').write(bytes(b))
        pg(port, 'postgres', 'create database v_alteree')
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'), ['--archive', alteree, '--identite', ident, '--executer'],
                             {'SES_RESTORE_DB_URL': url(port, 'v_alteree'), 'SES_PG_BIN': PG})
        ok(code != 0, 'archive altérée : refusée au déchiffrement')
        ok(pg(port, 'v_alteree', "select count(*) from information_schema.tables where table_schema = 'public'")[1] == '0', 'archive altérée : la cible reste vide')
        # 6b. mauvaise clé
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'), ['--archive', archive, '--identite', ident_autre, '--executer'],
                             {'SES_RESTORE_DB_URL': url(port, 'v_alteree'), 'SES_PG_BIN': PG})
        ok(code != 0, 'mauvaise clé : refusée')
        # 6c. contenu altéré SOUS une enveloppe valide (le chiffrement est correct, les sommes ne le sont plus)
        claire = os.path.join(racine_tmp, 'claire.tar.gz')
        subprocess.run(['age', '-d', '-i', ident, '-o', claire, archive], check=True)
        deballe = os.path.join(racine_tmp, 'deballe'); os.makedirs(deballe)
        C.extraire_sans_risque(claire, deballe)
        with open(os.path.join(deballe, 'public.dump'), 'r+b') as f:
            f.seek(200); octet = f.read(1); f.seek(200); f.write(bytes([octet[0] ^ 0x01]))
        truquee = os.path.join(racine_tmp, 'truquee.tar.gz')
        with tarfile.open(truquee, 'w:gz') as t:
            for rel in os.listdir(deballe):
                t.add(os.path.join(deballe, rel), arcname=rel)
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'), ['--archive', truquee, '--executer'],
                             {'SES_RESTORE_DB_URL': url(port, 'v_alteree'), 'SES_PG_BIN': PG})
        ok(code != 0 and ('Somme de contrôle' in texte), 'contenu altéré sous enveloppe valide : détecté par SHA256SUMS')
        # 6d. cible non vide
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'), ['--archive', archive, '--identite', ident, '--executer'], envr)
        ok(code != 0 and 'n\'est pas vide' in texte, 'cible non vide : restauration REFUSÉE')
        # 6e. cible = la base d'origine
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'), ['--archive', archive, '--identite', ident, '--executer'],
                             {'SES_RESTORE_DB_URL': url(port, 'source'), 'SES_PG_BIN': PG})
        ok(code != 0 and 'd\'où vient' in texte, 'cible = base source : refusée')
        # 6f. cible protégée (production / Goship) : refusée AVANT toute connexion
        for ref in C.PROJETS_INTERDITS:
            code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'), ['--archive', archive, '--identite', ident, '--executer'],
                                 {'SES_RESTORE_DB_URL': 'postgresql://postgres:x@db.%s.supabase.co:5432/postgres' % ref, 'SES_PG_BIN': PG})
            ok(code != 0 and 'projet protégé' in texte, 'cible protégée %s… refusée sans connexion' % ref[:6])
        # 6g. clé privée dans le dépôt Git : refusée
        dans_depot = os.path.join(RACINE, 'cle-essai-a-supprimer.key'); shutil.copy(ident, dans_depot)
        try:
            code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'), ['--archive', archive, '--identite', dans_depot], envr)
            ok(code != 0 and 'DANS le dépôt' in texte, 'clé privée dans le dépôt : refusée')
        finally:
            os.remove(dans_depot)
        os.chmod(ident, 0o644)
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'restore', 'restaurer.py'), ['--archive', archive, '--identite', ident], envr)
        ok(code != 0 and 'chmod 600' in texte, 'clé privée lisible par tous : refusée')
        os.chmod(ident, 0o600)
        # 6h. sauvegarde : clé privée donnée à la place de la clé publique
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'backup', 'sauvegarder.py'), ['--sortie', sortie],
                             dict(env, SES_AGE_RECIPIENT=re.search(r'(AGE-SECRET-KEY-\S+)', open(ident).read()).group(1)))
        ok(code != 0 and 'PRIVÉE' in texte, 'clé privée fournie au chiffrement : refusée')
        # 6i. vérification exigée sans base de contrôle
        e2 = dict(env); e2['SES_VERIF_DB_URL'] = ''
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'backup', 'sauvegarder.py'), ['--sortie', sortie, '--exiger-verification'], e2)
        ok(code != 0 and 'exigée' in texte, 'sans base de contrôle, --exiger-verification échoue')
        ok(len(glob.glob(os.path.join(sortie, 'ses-*.tar.gz.age'))) == 1, 'aucune archive à moitié vérifiée n\'a été rendue')
        journal = [json.loads(l) for l in open(os.path.join(sortie, 'journal.jsonl'), encoding='utf-8')]
        ok(journal[-1]['statut'] == 'echec', 'l\'échec est consigné au journal')
        # 6j. base de contrôle = base sauvegardée
        code, texte = lancer(os.path.join(RACINE, 'scripts', 'backup', 'sauvegarder.py'), ['--sortie', sortie, '--exiger-verification'],
                             dict(env, SES_VERIF_DB_URL=url(port, 'source')))
        ok(code != 0 and 'sauvegardée' in texte, 'contrôle dans la base sauvegardée elle-même : refusé')

        # ---------------------------------------------------------------- 7. la VALIDATION sait voir le mal
        with open(os.path.join(deballe, 'manifest.json'), encoding='utf-8') as f:
            manifest = json.load(f)
        cible = C.decouper(url(port, 'restaure'))
        # Les essais de la section 5 ont consommé un numéro (nextval) : on remet la séquence
        # là où la sauvegarde l'avait laissée avant de juger l'état « sain ».
        seq_ok = int(manifest['sequences']['public.numero_colis_seq'])
        pg(port, 'restaure', "select setval('public.numero_colis_seq', %d)" % seq_ok)
        problemes, _ = R.valider(cible, manifest)
        ok(problemes == [], 'état sain : aucune anomalie')
        mutations = [
            ('ligne modifiée', "set session_replication_role = replica; update public.colis set description = description || '!' where id = (select id from public.colis limit 1)",
             "set session_replication_role = replica; update public.colis set description = rtrim(description, '!') where description like '%!'", 'DIFFÉRENT'),
            ('séquence faussée', "select setval('public.numero_colis_seq', 10)", "select setval('public.numero_colis_seq', %d)" % seq_ok, 'séquence'),
            ('règle de sécurité perdue', 'drop policy colis_lecture on public.colis',
             "create policy colis_lecture on public.colis for select to authenticated using (client_id = (select auth.uid()) or (select public.a_droit('colis.lire')))",
             'politiques'),
            ('déclencheur d\'inscription perdu', 'drop trigger creer_profil_client on auth.users',
             'create trigger creer_profil_client after insert on auth.users for each row execute function public.creer_profil_client()', 'déclencheur'),
            ('table inattendue', 'create table public.intruse (x int)', 'drop table public.intruse', 'inattendue'),
        ]
        for nom, mal, remede, mot in mutations:
            pg(port, 'restaure', mal)
            problemes, _ = R.valider(cible, manifest)
            ok(any(mot in p for p in problemes), 'validation détecte : %s (%s)' % (nom, problemes[:1]))
            pg(port, 'restaure', remede)
        # ligne supprimée : irréversible sans tout refaire, on vérifie d'abord, on le fait en dernier
        pg(port, 'restaure', "delete from public.appareils where jeton = (select jeton from public.appareils limit 1)")
        problemes, _ = R.valider(cible, manifest)
        ok(any('ligne(s) restaurée(s) au lieu de' in p for p in problemes), 'validation détecte : ligne supprimée')

        print('PASS sauvegarde de bout en bout : %d vérifications — chiffrement, vérification par restauration, restauration, '
              'validation par empreintes, garde-fous, et les cas où la chaîne DOIT échouer (PostgreSQL %s).'
              % (N[0], pg(port, 'postgres', 'show server_version')[1]))
        return 0
    except AssertionError as e:
        print('ÉCHEC sauvegarde de bout en bout (après %d vérifications) : %s' % (N[0], e))
        return 1
    finally:
        if serveur:
            subprocess.run([os.path.join(PG, 'pg_ctl'), '-D', donnees, '-m', 'immediate', 'stop'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        shutil.rmtree(racine_tmp, ignore_errors=True)


sys.exit(main())
