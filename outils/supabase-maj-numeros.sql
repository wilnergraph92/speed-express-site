-- =============================================================================
-- Speed Express Shipping — mise à jour : nouveaux numéros de colis
-- -----------------------------------------------------------------------------
-- Tout sélectionner, copier, coller dans Supabase > SQL Editor, puis Run.
--
-- AVANT DE LANCER : vérifiez en haut de la page que le projet ouvert est bien
-- « speed-express-site ». Ce script ne doit jamais être passé sur la base de
-- Goship Express : les deux entreprises ont leurs propres données.
--
-- Ce qu'elle change :
--   · chaque NOUVEAU colis reçoit un numéro « SES- » suivi de dix chiffres tirés
--     au hasard (SES-4821937065), jamais deux fois le même, au lieu de
--     SES-10003-HT (un compteur qu'on pouvait deviner, suivi du pays).
--
-- Ce qu'elle ne change pas :
--   · les colis DÉJÀ enregistrés gardent leur numéro : il est imprimé sur leur
--     étiquette, envoyé au client et lu par le QR code. Aucune ligne n'est modifiée.
--   · un numéro saisi à la main par l'équipe reste accepté tel quel.
--
-- Rejouable sans risque : une seule fonction est remplacée, rien n'est supprimé.
-- La même fonction est dans supabase.sql (installation neuve) : les deux doivent
-- rester identiques (test outils/tests/numeros-colis.cjs).
-- =============================================================================

create or replace function public.preparer_colis()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_numero text;
begin
  if tg_op = 'INSERT' then
    if coalesce(trim(new.numero), '') = '' then
      -- « SES- » suivi de dix chiffres tirés au hasard (le premier jamais nul : un tableur
      -- n'en mange aucun), puisés dans gen_random_uuid(), aléa cryptographique : un numéro
      -- ne permet pas de deviner le suivant. On retire tant que le numéro existe déjà ; la
      -- contrainte « unique » de la colonne reste le dernier rempart.
      loop
        v_numero := 'SES-' || (1000000000
          + ('x' || substr(md5(gen_random_uuid()::text), 1, 15))::bit(60)::bigint % 9000000000)::text;
        exit when not exists (select 1 from public.colis c where c.numero = v_numero);
      end loop;
      new.numero := v_numero;
    end if;
    new.numero := upper(trim(new.numero));
    new.cree_le := now();
  else
    new.numero := old.numero;
    new.jeton := old.jeton;
    new.cree_le := old.cree_le;
  end if;
  new.maj_le := now();
  return new;
end;
$$;
