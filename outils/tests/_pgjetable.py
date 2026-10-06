"""Un PostgreSQL JETABLE pour les essais lourds : jamais la production.

    SES_PG_BIN=/dossier/des/binaires python3 outils/tests/logistique-essai.py

Démarre un cluster vide dans un dossier temporaire (port libre, TCP local seulement), y charge le
VRAI schéma historique du projet (outils/*.sql) et des données FICTIVES (adresses en .test, accents,
apostrophes, retours à la ligne), puis détruit tout en sortant."""
import os
import shutil
import socket
import subprocess
import sys
import tempfile

RACINE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PG = os.environ.get('SES_PG_BIN', '').strip()

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

update public.clients set role = 'admin' where email = 'client1@essai.test';
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

TABLES_HISTORIQUES = ('public.clients', 'public.colis', 'public.colis_historique', 'public.factures', 'public.appareils', 'auth.users')


def verifier_environnement():
    if not PG:
        print('SKIP : définissez SES_PG_BIN (dossier des binaires PostgreSQL : initdb, pg_ctl, postgres, psql).')
        sys.exit(0)
    for outil in ('initdb', 'pg_ctl', 'postgres', 'psql'):
        if not os.access(os.path.join(PG, outil), os.X_OK):
            print('ÉCHEC : %s introuvable dans SES_PG_BIN=%s' % (outil, PG)); sys.exit(1)


class Cluster(object):
    def __init__(self):
        verifier_environnement()
        self.tmp = tempfile.mkdtemp(prefix='ses-pgjetable-')
        os.chmod(self.tmp, 0o700)
        s = socket.socket(); s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]; s.close()
        self.donnees = os.path.join(self.tmp, 'pg')
        self.demarre = False

    def __enter__(self):
        subprocess.run([os.path.join(PG, 'initdb'), '-D', self.donnees, '-U', 'postgres', '--auth=trust', '-E', 'UTF8', '--locale=C'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        subprocess.run([os.path.join(PG, 'pg_ctl'), '-D', self.donnees, '-l', os.path.join(self.tmp, 'pg.log'), '-w', '-o',
                        "-p %s -c listen_addresses=127.0.0.1 -c unix_socket_directories='' -c fsync=off" % self.port, 'start'],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        self.demarre = True
        return self

    def __exit__(self, *a):
        if self.demarre:
            subprocess.run([os.path.join(PG, 'pg_ctl'), '-D', self.donnees, '-m', 'immediate', 'stop'],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run(self, base, requete, role=None, claims=None, expect_error=False):
        """psql direct. Rend (code_retour, dernière ligne de sortie ou message d'erreur détaillé)."""
        script = ''
        if role:
            script += 'SET ROLE %s;\n' % role
        if claims:
            script += "SELECT set_config('request.jwt.claim.sub', '%s', false);\n" % claims
        script += requete + '\n'
        cmd = [os.path.join(PG, 'psql'), '-h', '127.0.0.1', '-p', str(self.port), '-U', 'postgres', '-d', base,
               '-qAtX', '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose']
        env = dict(os.environ, PGOPTIONS='-c search_path=public,extensions')
        r = subprocess.run(cmd, input=script, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=env)
        if r.returncode != 0:
            if not expect_error:
                raise AssertionError('SQL en échec sur %s : %s\n%s' % (base, r.stderr.strip()[-400:], requete[:160]))
            return r.returncode, r.stderr.strip()
        lignes = [l for l in r.stdout.splitlines() if l.strip()]
        return 0, (lignes[-1] if lignes else '')

    def un(self, base, requete, **kw):
        return self.run(base, requete, **kw)[1]

    def lignes(self, base, requete, **kw):
        """Toutes les lignes de sortie (là où `run` ne rend que la dernière)."""
        cmd = [os.path.join(PG, 'psql'), '-h', '127.0.0.1', '-p', str(self.port), '-U', 'postgres', '-d', base, '-qAtX', '-v', 'ON_ERROR_STOP=1']
        env = dict(os.environ, PGOPTIONS='-c search_path=public,extensions')
        r = subprocess.run(cmd, input=requete + '\n', stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=env)
        if r.returncode != 0:
            raise AssertionError('SQL en échec : %s' % r.stderr.strip()[-300:])
        return [l for l in r.stdout.splitlines() if l.strip()]


def lire_sql(chemin):
    with open(os.path.join(RACINE, chemin), encoding='utf-8') as f:
        return f.read()


def monter_historique(cl, base='ses'):
    """La base telle qu'elle est aujourd'hui en production : schéma historique + migrations + données fictives."""
    cl.run('postgres', 'create database %s' % base)
    cl.run(base, lire_sql('scripts/restore/socle-postgres-vide.sql'))
    cl.run(base, AUTH)
    for f in ('supabase.sql', 'supabase-maj-facture-groupee.sql', 'supabase-maj-jeton.sql', 'supabase-dashboard.sql', 'supabase-maj.sql'):
        cl.run(base, lire_sql('outils/' + f))
    # La table « appareils » vient maintenant de supabase-maj.sql (section 9) : plus rien à créer ici.
    noms = "array[%s]" % ','.join("'%s'" % n.replace("'", "''") for n in NOMS)
    cl.run(base, DONNEES % {'noms': noms})


def empreintes_historiques(cl, base):
    """Empreinte du contenu de chaque ancienne table : prouve qu'une migration ne les a pas touchées."""
    sortie = {}
    for t in TABLES_HISTORIQUES:
        sortie[t] = cl.un(base, "select count(*) || ':' || coalesce(md5(string_agg(md5(x::text), '' order by md5(x::text))), '') from %s x" % t)
    return sortie
