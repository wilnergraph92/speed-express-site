-- =============================================================================
-- Speed Express Shipping — ANONYMISER une copie restaurée
-- -----------------------------------------------------------------------------
-- Uniquement sur un PostgreSQL LOCAL et JETABLE, marqué « staging » AVANT d'y
-- restaurer une sauvegarde (marquer.sql, puis scripts/restore/restaurer.py
-- --mode postgres-vide). Jamais « speed-express-site », jamais le projet
-- Supabase de préproduction : des données réelles n'y entrent pas, même pour
-- un instant (docs/production/ENVIRONNEMENTS.md §6).
--
-- Ce qu'il fait : remplace tout ce qui désigne une personne — noms, e-mails,
-- téléphones, adresses, notes, descriptions libres, numéros de suivi des
-- marchands — par des valeurs neutres ; retire mots de passe, sessions,
-- identités de connexion et téléphones enregistrés. Il GARDE la forme de
-- l'activité : nombre de clients, colis, factures, montants, statuts, dates,
-- pays et villes, numéros SES et codes clients, pour que les essais restent
-- réalistes.
--
-- Tout tient dans une transaction : si le garde-fou refuse, rien ne change.
-- =============================================================================

begin;

do $$
declare
  v_marquee boolean := false;
begin
  -- Lecture dynamique : sur une base non marquée, la table du marqueur n'existe pas.
  if to_regclass('ses_meta.environnement') is not null then
    execute 'select exists (select 1 from ses_meta.environnement where nom = ''staging'')' into v_marquee;
  end if;
  if not v_marquee then
    raise exception 'ARRÊT : cette base n''est pas marquée « staging » (marquer.sql AVANT la restauration). Rien n''a été modifié.'
      using errcode = 'SE900';
  end if;
end
$$;

-- Les déclencheurs sont suspendus le temps de cette seule transaction (« set local ») : en production, ils
-- interdisent à juste titre de réécrire un colis ou une pré-alerte, et changer la description d'un colis
-- recalculerait sa facture. Ici, on ne change que des textes : aucune facture, aucun historique ne doit bouger.
-- (Réservé à un PostgreSQL local, où l'on est superutilisateur : c'est voulu, le projet Supabase le refuserait.)
set local session_replication_role = replica;

-- 1. Les comptes : plus de mot de passe, d'e-mail ni de métadonnées réelles ; plus de session ni d'identité.
update auth.users
   set email = 'anonyme-' || substr(md5(id::text), 1, 12) || '@exemple.test',
       encrypted_password = '',
       raw_user_meta_data = '{}'::jsonb,
       phone = null;
do $$
begin
  if to_regclass('auth.identities') is not null then execute 'delete from auth.identities'; end if;
  if to_regclass('auth.sessions') is not null then execute 'delete from auth.sessions'; end if;
  if to_regclass('auth.refresh_tokens') is not null then execute 'delete from auth.refresh_tokens'; end if;
end
$$;

-- 2. Les profils : le code SES et le rôle restent ; le reste devient neutre.
update public.clients c
   set nom_complet = case when c.role = 'client' then 'Client ' || coalesce(c.code, substr(md5(c.id::text), 1, 6))
                          else 'Équipe ' || coalesce(c.matricule, substr(md5(c.id::text), 1, 6)) end,
       email = u.email,
       telephone = '+000 0000 ' || substr(md5(c.id::text || 't'), 1, 4),
       adresse = '',
       region = ''
  from auth.users u
 where u.id = c.id;

-- 3. Les colis : expéditeur, destinataire, téléphones, adresses, descriptions et notes libres.
update public.colis
   set description = 'Contenu anonymisé',
       expediteur = 'Expéditeur',
       destinataire = 'Destinataire ' || substr(md5(id::text), 1, 6),
       telephone_destinataire = '',
       adresse_livraison = '',
       note = '';
update public.colis_historique set note = '', auteur = case when auteur = '' then '' else 'équipe' end;

-- 4. Les factures : notes, et dans les lignes figées, tout ce qui n'est ni un numéro ni un montant.
update public.factures f
   set note = '',
       lignes = coalesce((select jsonb_agg((select coalesce(jsonb_object_agg(k, v), '{}'::jsonb)
                                              from jsonb_each(l) as e(k, v)
                                             where jsonb_typeof(v) in ('number', 'boolean') or k = 'numero'))
                            from jsonb_array_elements(case when jsonb_typeof(f.lignes) = 'array' then f.lignes else '[]'::jsonb end) l), '[]'::jsonb);

-- 5. Les pré-alertes : ce qui a été acheté et le numéro de suivi du marchand.
update public.prealertes set contenu = 'Contenu anonymisé', numero_suivi = '', note = '';

-- 6. Les téléphones enregistrés pour les notifications : des identifiants d'appareils réels.
delete from public.appareils;

commit;
