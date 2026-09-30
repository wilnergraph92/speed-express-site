-- =============================================================================
-- Speed Express Shipping — mise à jour : le jeton du QR code est vérifié
-- -----------------------------------------------------------------------------
-- Tout sélectionner, copier, coller dans Supabase > SQL Editor, puis Run.
--
-- AVANT DE LANCER : vérifiez en haut de la page que le projet ouvert est bien
-- « speed-express-site ». Ce script ne doit jamais être passé sur la base de
-- Goship Express : les deux entreprises ont leurs propres données.
--
-- Ce qu'elle change :
--   · suivre_colis accepte le jeton du QR code (&j=…) et le vérifie : un lien
--     falsifié ne résout plus.
--
-- Sans jeton (numéro tapé à la main), la recherche reste publique — statut et
-- étapes seulement, comme avant. Les appels existants sans jeton continuent
-- donc de fonctionner.
--
-- Rejouable sans risque : rien n'est supprimé sauf l'ancienne version de la
-- fonction (recréée aussitôt avec les mêmes droits), aucune donnée existante
-- n'est touchée, et le passer deux fois ne change rien.
-- =============================================================================


-- 1. Nouvelle signature : le jeton devient un second paramètre facultatif ----
-- (PostgreSQL ne remplace pas une fonction en changeant ses paramètres : on
-- retire l'ancienne version, on crée la nouvelle, on lui rend ses droits.)
drop function if exists public.suivre_colis(text);

create function public.suivre_colis(p_numero text, p_jeton text default null)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  select jsonb_build_object(
    'numero', c.numero,
    'statut', c.statut,
    'service', c.service,
    'pays_destination', c.pays_destination,
    'maj_le', c.maj_le,
    'historique', coalesce((
      select jsonb_agg(jsonb_build_object('statut', h.statut, 'lieu', h.lieu, 'cree_le', h.cree_le)
                       order by h.cree_le)
      from public.colis_historique h
      where h.colis_id = c.id), '[]'::jsonb))
  from public.colis c
  where length(trim(coalesce(p_numero, ''))) >= 4
    and c.numero = upper(trim(p_numero))
    and (p_jeton is null or c.jeton = p_jeton)
  limit 1
$$;

grant execute on function public.suivre_colis(text, text) to anon, authenticated;
