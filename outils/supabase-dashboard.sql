-- Phase 3 / migration proposée, NON APPLIQUÉE.
-- Lire outils/phase-3-dashboard.md avant application autorisée en staging.
-- Ajoute des fonctions uniquement : aucune table/ligne/policy supprimée.
begin;

-- Bornes locales métier. La fin effective est plafonnée à l'instant serveur.
create or replace function public.dashboard_periode_ses(
  p_periode text default 'mois', p_date date default null,
  p_debut timestamp default null, p_fin timestamp default null
) returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare
  z constant text := 'America/Santo_Domingo';
  ref timestamptz := statement_timestamp();
  d date := coalesce(p_date, (ref at time zone z)::date);
  a timestamp; b timestamp; ua timestamptz; ub timestamptz; fin_effective timestamptz;
  grain text;
begin
  case p_periode
    when 'jour' then a := d; b := a + interval '1 day';
    when 'semaine' then a := date_trunc('week', d::timestamp); b := a + interval '1 week';
    when 'mois' then a := date_trunc('month', d::timestamp); b := a + interval '1 month';
    when 'annee' then a := date_trunc('year', d::timestamp); b := a + interval '1 year';
    when 'heures', 'personnalise' then a := p_debut; b := p_fin;
    else raise exception 'Période invalide' using errcode = '22023';
  end case;
  if a is null or b is null or not isfinite(a) or not isfinite(b) or b <= a
     or b-a > interval '366 days' or a::date < date '2000-01-01' then
    raise exception 'Période invalide (maximum 366 jours)' using errcode = '22023';
  end if;
  if p_periode = 'heures' and (b-a > interval '1 day' or a::date <> (b-interval '1 microsecond')::date) then
    raise exception 'Choisissez des heures sur une même journée' using errcode = '22023';
  end if;
  ua := a at time zone z; ub := b at time zone z;
  if ua >= ref then raise exception 'La période commence dans le futur' using errcode = '22023'; end if;
  fin_effective := least(ub, ref);
  grain := case when b-a <= interval '1 day' then 'hour'
                when b-a <= interval '62 days' then 'day' else 'month' end;
  return jsonb_build_object('fuseau',z,'reference',ref,'debut',ua,'fin',ub,
    'fin_effective',fin_effective,'debut_local',a,'fin_locale',b,'grain',grain,
    'precedent_debut',ua-(fin_effective-ua),'precedent_fin',ua,
    'comparaison','intervalle précédent de même durée effective');
end $$;

create or replace function public.dashboard_colis_ses(
  p_periode text default 'mois', p_date date default null,
  p_debut timestamp default null, p_fin timestamp default null,
  p_service text default null, p_pays text default null, p_statut text default null
) returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare
  f jsonb; a timestamptz; b timestamptz; pa timestamptz; grain text; resultat jsonb;
begin
  if not public.a_droit('colis.lire') then raise exception 'Accès réservé' using errcode='42501'; end if;
  if (p_service is not null and p_service not in ('aerien','maritime','terrestre'))
     or (p_pays is not null and p_pays not in ('HT','DO','US'))
     or (p_statut is not null and p_statut not in ('confirme','expedie','disponible','livre','action')) then
    raise exception 'Filtre invalide' using errcode='22023';
  end if;
  f := public.dashboard_periode_ses(p_periode,p_date,p_debut,p_fin);
  a := (f->>'debut')::timestamptz; b := (f->>'fin_effective')::timestamptz;
  pa := (f->>'precedent_debut')::timestamptz; grain := f->>'grain';
  with periode as materialized (
    select cree_le, pays_destination, ville_destination from public.colis
    where cree_le >= a and cree_le < b
      and (p_service is null or service=p_service)
      and (p_pays is null or pays_destination=p_pays)
      and (p_statut is null or statut=p_statut)
  ), comptes as (
    select date_trunc(grain,cree_le at time zone 'America/Santo_Domingo') as tranche, count(*) as n
    from periode group by 1
  ), tranches as (
    select s from generate_series(
      date_trunc(grain,a at time zone 'America/Santo_Domingo'),
      date_trunc(grain,(b-interval '1 microsecond') at time zone 'America/Santo_Domingo'),
      case grain when 'hour' then interval '1 hour' when 'day' then interval '1 day' else interval '1 month' end
    ) s
  ), destinations as (
    select pays_destination as pays, coalesce(nullif(trim(ville_destination),''),'—') as ville,count(*) as n
    from periode group by 1,2
  )
  select jsonb_build_object('version',1,'periode',f,
    'filtres',jsonb_build_object('service',p_service,'pays',p_pays,'statut',p_statut),
    'stock',jsonb_build_object(
      'total',(select count(*) from public.colis),
      'services',coalesce((select jsonb_object_agg(service,n) from (
        select service,count(*) n from public.colis where statut in ('confirme','expedie','disponible','action') group by service
      ) x),'{}'::jsonb),
      'statuts',coalesce((select jsonb_object_agg(statut,n) from (select statut,count(*) n from public.colis group by statut) x),'{}'::jsonb)),
    'total',(select count(*) from periode),
    'precedent',(select count(*) from public.colis where cree_le>=pa and cree_le<a
      and (p_service is null or service=p_service) and (p_pays is null or pays_destination=p_pays)
      and (p_statut is null or statut=p_statut)),
    'serie',coalesce((select jsonb_agg(jsonb_build_object('date',s,'n',coalesce(n,0)) order by s)
      from tranches left join comptes on tranche=s),'[]'::jsonb),
    'destinations',coalesce((select jsonb_agg(to_jsonb(x) order by n desc,pays,ville)
      from (select * from destinations order by n desc,pays,ville limit 10) x),'[]'::jsonb),
    'destinations_nombre',(select count(*) from destinations)
  ) into resultat;
  return resultat;
end $$;

create or replace function public.dashboard_clients_ses(
  p_periode text default 'mois', p_date date default null,
  p_debut timestamp default null, p_fin timestamp default null
) returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare f jsonb; a timestamptz; b timestamptz; pa timestamptz;
begin
  if not public.a_droit('clients.lire') then raise exception 'Accès réservé' using errcode='42501'; end if;
  f := public.dashboard_periode_ses(p_periode,p_date,p_debut,p_fin);
  a := (f->>'debut')::timestamptz; b := (f->>'fin_effective')::timestamptz;
  pa := (f->>'precedent_debut')::timestamptz;
  return jsonb_build_object('version',1,'periode',f,
    'total',(select count(*) from public.clients where role='client' and cree_le>=a and cree_le<b),
    'precedent',(select count(*) from public.clients where role='client' and cree_le>=pa and cree_le<a));
end $$;

-- Compatibilité : même signature jsonb, aucun agrégat d'un domaine interdit.
-- Le montant scalaire obsolète reste NULL : jamais de mélange de devises ni
-- de modification silencieuse en « USD seulement ». Le nouveau frontend ne
-- consomme plus cette RPC. Les soldes par devise sont explicitement séparés.
create or replace function public.statistiques_ses()
returns jsonb language plpgsql stable security invoker set search_path = '' as $$
declare r jsonb;
begin
  if not public.a_droit('colis.lire') then raise exception 'Accès réservé' using errcode='42501'; end if;
  r := jsonb_build_object('colis',(select count(*) from public.colis),
    'statuts',coalesce((select jsonb_object_agg(statut,n) from (select statut,count(*) n from public.colis group by statut) x),'{}'::jsonb),
    'clients',null,'factures_impayees',null,'montant_impaye',null,'soldes_par_devise',null);
  if public.a_droit('clients.lire') then
    r := r || jsonb_build_object('clients',(select count(*) from public.clients where role='client'));
  end if;
  if public.a_droit('factures.lire') then
    r := r || jsonb_build_object('factures_impayees',(select count(*) from public.factures where montant>montant_paye),
      'soldes_par_devise',coalesce((select jsonb_agg(to_jsonb(x)) from (
        select devise,sum(greatest(montant-montant_paye,0))::text solde,
          sum(greatest(montant_paye-montant,0))::text trop_percu
        from public.factures group by devise order by devise
      ) x),'[]'::jsonb));
  end if;
  return r;
end $$;

revoke all on function public.dashboard_periode_ses(text,date,timestamp,timestamp) from public,anon;
revoke all on function public.dashboard_colis_ses(text,date,timestamp,timestamp,text,text,text) from public,anon;
revoke all on function public.dashboard_clients_ses(text,date,timestamp,timestamp) from public,anon;
revoke all on function public.statistiques_ses() from public,anon;
grant execute on function public.dashboard_periode_ses(text,date,timestamp,timestamp) to authenticated;
grant execute on function public.dashboard_colis_ses(text,date,timestamp,timestamp,text,text,text) to authenticated;
grant execute on function public.dashboard_clients_ses(text,date,timestamp,timestamp) to authenticated;
grant execute on function public.statistiques_ses() to authenticated;
commit;
