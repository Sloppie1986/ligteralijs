-- Bezoekersmonitor: één regel per keer dat iemand de app opent. Geen namen, e-mail of IP;
-- het bezoekers-id is een willekeurige code die elke dag opnieuw wordt gemaakt.
create table if not exists public.visits (
  id bigint generated always as identity primary key,
  at timestamptz not null default now(),
  vid text not null check (char_length(vid) between 8 and 40),
  again boolean not null default false,
  mobile boolean, app boolean, member boolean,
  tab text check (char_length(tab) <= 20),
  ref text check (char_length(ref) <= 80)
);
create index if not exists visits_at on public.visits (at);
alter table public.visits enable row level security;
drop policy if exists "iedereen telt mee" on public.visits;
create policy "iedereen telt mee" on public.visits for insert to anon, authenticated with check (at > now() - interval '5 minutes' and at < now() + interval '5 minutes');
revoke all on public.visits from anon, authenticated;
grant insert (vid, again, mobile, app, member, tab, ref) on public.visits to anon, authenticated;

-- Alleen beheerders krijgen de cijfers (samengevat, geen losse regels)
create or replace function public.visit_stats(days int default 30) returns json
language plpgsql security definer set search_path = public as $$
declare r json;
begin
  if not public.is_admin() then raise exception 'alleen voor beheerders'; end if;
  with v as (select *, (at at time zone 'Europe/Amsterdam') as lt from public.visits
             where at > now() - make_interval(days => least(greatest(days, 1), 365)))
  select json_build_object(
    'days', (select coalesce(json_agg(d order by d.day), '[]') from (
        select lt::date as day, count(distinct vid) as visitors, count(*) as opens,
               count(distinct vid) filter (where member) as members,
               count(distinct vid) filter (where app) as app,
               count(distinct vid) filter (where not again) as new
        from v group by 1) d),
    'hours', (select coalesce(json_agg(h order by h.hour), '[]') from (
        select extract(hour from lt)::int as hour, count(*) as opens from v
        where lt::date = (now() at time zone 'Europe/Amsterdam')::date group by 1) h),
    'tabs', (select coalesce(json_object_agg(coalesce(tab, '?'), n), '{}') from (select tab, count(*) n from v group by tab) t),
    'refs', (select coalesce(json_agg(x), '[]') from (select ref, count(*) n from v where ref is not null and ref <> '' group by ref order by 2 desc limit 8) x),
    'mobile', (select count(*) filter (where mobile) from v), 'total', (select count(*) from v),
    'last', (select max(at) from v)
  ) into r;
  return r;
end $$;
revoke all on function public.visit_stats(int) from public, anon;
grant execute on function public.visit_stats(int) to authenticated;
