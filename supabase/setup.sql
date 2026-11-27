-- Ligt er al ijs? — database voor eigen ijsmetingen, foto's en het forum.
-- Plak dit hele script in Supabase > SQL Editor en klik op Run. Het kan veilig opnieuw gedraaid worden.

-- ---------- beheerders (mogen berichten verbergen of verwijderen)
create table if not exists public.admins (user_id uuid primary key references auth.users on delete cascade);
alter table public.admins enable row level security;
drop policy if exists "admins zien zichzelf" on public.admins;
create policy "admins zien zichzelf" on public.admins for select using (user_id = auth.uid());

create or replace function public.is_admin() returns boolean
language sql stable security definer set search_path = public as
$$ select exists (select 1 from public.admins where user_id = auth.uid()) $$;

-- ---------- ijsmetingen van gebruikers
create table if not exists public.reports (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  measured_at timestamptz not null default now(),
  user_id     uuid not null default auth.uid() references auth.users on delete cascade,
  name        text not null check (char_length(name) between 1 and 40),
  cm          numeric(4,1) not null check (cm between 0.2 and 40),
  lat         double precision not null check (lat between 50.6 and 53.7),
  lon         double precision not null check (lon between 3.2 and 7.3),
  place       text check (char_length(place) <= 80),
  note        text check (char_length(note) <= 500),
  photo       text check (char_length(photo) <= 200),
  hidden      boolean not null default false
);
create index if not exists reports_created on public.reports (created_at desc);
alter table public.reports enable row level security;
drop policy if exists "iedereen leest" on public.reports;
drop policy if exists "ingelogd plaatst eigen" on public.reports;
drop policy if exists "eigen of beheer verwijdert" on public.reports;
drop policy if exists "beheer verbergt" on public.reports;
create policy "iedereen leest" on public.reports for select using (not hidden or public.is_admin());
create policy "ingelogd plaatst eigen" on public.reports for insert to authenticated with check (user_id = auth.uid() and not hidden);
create policy "eigen of beheer verwijdert" on public.reports for delete to authenticated using (user_id = auth.uid() or public.is_admin());
create policy "beheer verbergt" on public.reports for update to authenticated using (public.is_admin()) with check (public.is_admin());

-- ---------- forum (draad = bericht zonder parent_id, reactie = bericht met parent_id)
create table if not exists public.posts (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),
  user_id     uuid not null default auth.uid() references auth.users on delete cascade,
  name        text not null check (char_length(name) between 1 and 40),
  parent_id   uuid references public.posts on delete cascade,
  title       text check (char_length(title) <= 120),
  body        text not null check (char_length(body) between 1 and 4000),
  photo       text check (char_length(photo) <= 200),
  hidden      boolean not null default false
);
create index if not exists posts_parent on public.posts (parent_id, created_at);
alter table public.posts enable row level security;
drop policy if exists "iedereen leest" on public.posts;
drop policy if exists "ingelogd plaatst eigen" on public.posts;
drop policy if exists "eigen of beheer verwijdert" on public.posts;
drop policy if exists "beheer verbergt" on public.posts;
create policy "iedereen leest" on public.posts for select using (not hidden or public.is_admin());
create policy "ingelogd plaatst eigen" on public.posts for insert to authenticated with check (user_id = auth.uid() and not hidden);
create policy "eigen of beheer verwijdert" on public.posts for delete to authenticated using (user_id = auth.uid() or public.is_admin());
create policy "beheer verbergt" on public.posts for update to authenticated using (public.is_admin()) with check (public.is_admin());

-- ---------- rechten voor de app (nieuwe Supabase-projecten geven die niet meer automatisch)
grant select on public.reports, public.posts to anon, authenticated;
grant insert, update, delete on public.reports, public.posts to authenticated;
grant select on public.admins to authenticated;
revoke truncate, references, trigger on public.reports, public.posts, public.admins from anon, authenticated;

-- ---------- foto's: openbaar te bekijken, alleen in je eigen map te uploaden, max 3 MB
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('fotos', 'fotos', true, 3145728, array['image/jpeg','image/png','image/webp'])
on conflict (id) do update set public = true, file_size_limit = 3145728, allowed_mime_types = array['image/jpeg','image/png','image/webp'];
drop policy if exists "fotos uploaden in eigen map" on storage.objects;
drop policy if exists "fotos eigen of beheer verwijderen" on storage.objects;
create policy "fotos uploaden in eigen map" on storage.objects for insert to authenticated
  with check (bucket_id = 'fotos' and (storage.foldername(name))[1] = auth.uid()::text);
create policy "fotos eigen of beheer verwijderen" on storage.objects for delete to authenticated
  using (bucket_id = 'fotos' and ((storage.foldername(name))[1] = auth.uid()::text or public.is_admin()));

-- ---------- jezelf beheerder maken: eerst één keer inloggen in de app, dan dit draaien met jouw e-mailadres
-- insert into public.admins select id from auth.users where email = 'JOUW-EMAIL' on conflict do nothing;

-- ---------- profielfoto (toegevoegd 26-11): pad naar de avatar bij elk bericht en elke meting
alter table public.posts add column if not exists avatar text check (char_length(avatar) <= 200);
alter table public.reports add column if not exists avatar text check (char_length(avatar) <= 200);
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
