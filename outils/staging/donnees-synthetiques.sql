-- =============================================================================
-- Speed Express Shipping — DONNÉES SYNTHÉTIQUES de la préproduction (staging)
-- -----------------------------------------------------------------------------
-- À coller UNIQUEMENT dans le SQL Editor du projet de PRÉPRODUCTION, jamais
-- « speed-express-site ». Le garde-fou refuse toute base sans le marqueur
-- « staging » posé par l'installation (outils/staging/assembler-installation.py).
--
-- Ce qu'il crée — tout est INVENTÉ, rien ne vient de la production :
--   · 12 clients « Client Essai 01… » (adresses en @exemple.test, téléphones
--     +000), 3 comptes d'équipe synthétiques (admin, gérant, employé) ;
--   · 60 colis aux statuts, services, destinations et prix variés (dont des
--     prix saisis à la main), leurs factures (créées par la base), quelques
--     paiements, l'historique, et des pré-alertes.
-- Ces comptes n'ont AUCUN mot de passe : personne ne peut s'y connecter. Pour
-- essayer le site, créez votre propre compte sur la préproduction, puis donnez-
-- lui un rôle (docs/production/ENVIRONNEMENTS.md §4).
--
-- Une seule fois : s'il y a déjà des données synthétiques, il s'arrête. Pour
-- recommencer : reinitialiser.sql, puis ce fichier.
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
    raise exception 'ARRÊT : cette base n''est pas la préproduction (marqueur « staging » absent). Rien n''a été modifié.'
      using errcode = 'SE900';
  end if;
  if (select count(*) from auth.users where email not like '%@exemple.test') > 25 then
    raise exception 'ARRÊT : plus de 25 comptes réels dans cette base : ce n''est pas une préproduction. Rien n''a été modifié.'
      using errcode = 'SE900';
  end if;
  if exists (select 1 from auth.users where email like '%@exemple.test') then
    raise exception 'Données synthétiques déjà présentes : lancez d''abord reinitialiser.sql.'
      using errcode = 'SE901';
  end if;
end
$$;

-- 1. Les comptes (sans mot de passe) : le déclencheur d'inscription crée le profil et le code SES-#####.
insert into auth.users (instance_id, id, aud, role, email, encrypted_password, email_confirmed_at,
                        confirmation_token, recovery_token, email_change_token_new, email_change,
                        raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
select '00000000-0000-0000-0000-000000000000', gen_random_uuid(), 'authenticated', 'authenticated',
       case when i <= 12 then 'client' || lpad(i::text, 2, '0') else 'equipe' || lpad((i - 12)::text, 2, '0') end || '@exemple.test',
       '', now() - (i || ' days')::interval, '', '', '', '',
       '{"provider": "email", "providers": ["email"]}'::jsonb,
       jsonb_build_object(
         'nom_complet', case when i <= 12 then 'Client Essai ' || lpad(i::text, 2, '0') else 'Équipe Essai ' || lpad((i - 12)::text, 2, '0') end,
         'pays', (array['Haïti', 'République dominicaine'])[1 + i % 2],
         'ville', (array['Port-au-Prince', 'Cap-Haïtien', 'Santo Domingo', 'Santiago', 'Jacmel', 'Les Cayes'])[1 + i % 6],
         'adresse', 'Adresse fictive n° ' || i,
         'telephone', '+000 0000 ' || lpad(i::text, 4, '0'),
         'langue', (array['fr', 'en', 'es', 'ht'])[1 + i % 4]),
       now() - (i || ' days')::interval, now()
from generate_series(1, 15) i;

-- 2. L'équipe synthétique : pas d'identifiant client (l'équipe n'est pas la clientèle) ; l'identifiant d'équipe
--    ADM- / GER- / EMP- est donné par la base.
update public.clients set role = 'admin',   code = null, droits = '{}' where email = 'equipe01@exemple.test';
update public.clients set role = 'gerant',  code = null, droits = '{}' where email = 'equipe02@exemple.test';
update public.clients set role = 'employe', code = null, droits = array['colis.lire', 'colis.statut', 'clients.lire']
 where email = 'equipe03@exemple.test';

-- 3. Les colis : la base pose le numéro (SES- et dix chiffres), le jeton, la première ligne d'historique et la facture.
select setseed(0.2026);
insert into public.colis (client_id, description, expediteur, destinataire, telephone_destinataire, poids_lb, tarif_lb, prix_manuel,
                          service, pays_destination, ville_destination, adresse_livraison, valeur_declaree, lieu, note)
select c.id,
       (array['Vêtements', 'Chaussures', 'Téléphone', 'Pièces auto', 'Produits de beauté', 'Livres'])[1 + g % 6] || ' (essai)',
       (array['Amazon', 'Shein', 'Walmart', 'eBay', 'Temu'])[1 + g % 5],
       'Destinataire essai ' || g, '+000 0000 9' || lpad(g::text, 3, '0'),
       round((1 + random() * 40)::numeric, 2), (array[3.50, 4.00, 4.50])[1 + g % 3],
       case when g = 5 and c.n % 2 = 0 then 25.00 end,
       (array['aerien', 'maritime', 'aerien', 'terrestre'])[1 + g % 4],
       case when g % 3 = 0 then 'DO' else 'HT' end,
       case when g % 3 = 0 then (array['Santo Domingo', 'Santiago'])[1 + g % 2] else (array['Port-au-Prince', 'Cap-Haïtien', 'Jacmel'])[1 + g % 3] end,
       'Adresse de livraison fictive ' || g, round((random() * 250)::numeric, 2), 'Entrepôt Miami', ''
from (select id, row_number() over (order by email) as n from public.clients where email like 'client%@exemple.test') c
cross join generate_series(1, 5) g;

-- 4. La vie des colis : les changements de statut écrivent l'historique (et préviennent les téléphones : il n'y en a pas).
update public.colis set statut = 'expedie',    lieu = 'En vol vers Port-au-Prince' where description like 'Vêtements%' or description like 'Livres%';
update public.colis set statut = 'disponible', lieu = 'Agence de Port-au-Prince'   where description like 'Chaussures%';
update public.colis set statut = 'livre',      lieu = 'Livré au destinataire'      where description like 'Téléphone%';
update public.colis set statut = 'action',     lieu = 'Douane', note = 'Facture d''achat demandée (essai)' where description like 'Pièces auto%';

-- 5. Des paiements : la moitié des factures des colis livrés, réglées.
update public.factures f set montant_paye = f.montant + f.frais_service
 where exists (select 1 from public.colis c where c.id = f.colis_id and c.statut = 'livre');

-- 6. Des pré-alertes (le déclencheur en fixe le statut et la date).
insert into public.prealertes (client_id, magasin, contenu, numero_suivi, valeur, service)
select c.id, (array['Amazon', 'Shein', 'Walmart'])[1 + g % 3], 'Commande d''essai n° ' || g, 'ESSAI' || lpad((g * 7919)::text, 10, '0'),
       round((10 + random() * 150)::numeric, 2), (array['aerien', 'maritime'])[1 + g % 2]
from (select id from public.clients where email like 'client%@exemple.test' order by email limit 6) c
cross join generate_series(1, 2) g;

commit;
