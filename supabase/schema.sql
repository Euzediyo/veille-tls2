-- Comptes Veille TLS : à coller une seule fois dans Supabase (SQL Editor, puis Run).
-- Une ligne par lecteur : ses articles lus, ses favoris et ses articles masqués.
-- Chaque lecteur ne peut lire, créer, modifier ou supprimer que sa propre ligne (Row Level Security).

create table if not exists public.preferences (
  user_id uuid primary key references auth.users (id) on delete cascade,
  lus text[] not null default '{}',
  favoris text[] not null default '{}',
  masques text[] not null default '{}',
  maj timestamptz not null default now(),
  constraint preferences_taille check (cardinality(lus) <= 20000 and cardinality(favoris) <= 5000 and cardinality(masques) <= 5000)
);

alter table public.preferences enable row level security;

-- Aucun accès sans être connecté ; accès limité aux lecteurs connectés.
revoke all on table public.preferences from anon, authenticated;
grant select, insert, update, delete on table public.preferences to authenticated;

drop policy if exists "lire sa ligne" on public.preferences;
drop policy if exists "creer sa ligne" on public.preferences;
drop policy if exists "modifier sa ligne" on public.preferences;
drop policy if exists "supprimer sa ligne" on public.preferences;
create policy "lire sa ligne" on public.preferences for select to authenticated using ((select auth.uid()) = user_id);
create policy "creer sa ligne" on public.preferences for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "modifier sa ligne" on public.preferences for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "supprimer sa ligne" on public.preferences for delete to authenticated using ((select auth.uid()) = user_id);

-- Bouton « Supprimer mon compte » : un lecteur connecté efface son propre compte, et sa ligne avec lui.
create or replace function public.supprimer_mon_compte() returns void
language plpgsql security definer set search_path = '' as $$
begin
  if auth.uid() is null then
    raise exception 'non connecté';
  end if;
  delete from auth.users where id = auth.uid();
end;
$$;
revoke all on function public.supprimer_mon_compte() from public, anon;
grant execute on function public.supprimer_mon_compte() to authenticated;

-- Nettoyage automatique, chaque nuit à 3 h (heure UTC) :
-- comptes jamais confirmés après 7 jours, comptes inactifs après 3 ans (annoncé dans la politique de confidentialité).
create extension if not exists pg_cron;
select cron.unschedule(jobid) from cron.job where jobname = 'veille-tls-nettoyage';
select cron.schedule('veille-tls-nettoyage', '0 3 * * *', $$
  delete from auth.users where email_confirmed_at is null and created_at < now() - interval '7 days';
  delete from auth.users where coalesce(last_sign_in_at, created_at) < now() - interval '3 years';
$$);
