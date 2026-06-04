-- Product analytics: downloads, installs, trials, license checks
-- Run after schema.sql in Supabase SQL editor (idempotent).

create extension if not exists "uuid-ossp";

create table if not exists public.download_events (
  id uuid primary key default uuid_generate_v4(),
  created_at timestamptz not null default now(),
  ip_address text,
  user_agent text,
  country text,
  referrer text,
  version text,
  channel text default 'windows'
);

create index if not exists download_events_created_at_idx on public.download_events (created_at desc);

create table if not exists public.installs (
  install_id uuid primary key,
  version text,
  os text,
  arch text,
  installed_at timestamptz not null,
  trial_started_at timestamptz,
  created_at timestamptz default now()
);

create index if not exists installs_installed_at_idx on public.installs (installed_at desc);

create table if not exists public.trial_events (
  id uuid primary key default uuid_generate_v4(),
  install_id uuid references public.installs (install_id) on delete set null,
  started_at timestamptz not null,
  created_at timestamptz default now()
);

create index if not exists trial_events_started_at_idx on public.trial_events (started_at desc);

create table if not exists public.license_events (
  id uuid primary key default uuid_generate_v4(),
  install_id uuid,
  license_key text,
  email text,
  event_type text not null check (event_type in ('activation', 'validation')),
  machine_id text,
  created_at timestamptz default now()
);

create index if not exists license_events_created_at_idx on public.license_events (created_at desc);
create index if not exists license_events_type_idx on public.license_events (event_type);

alter table public.download_events enable row level security;
alter table public.installs enable row level security;
alter table public.trial_events enable row level security;
alter table public.license_events enable row level security;

-- No public policies: server uses service role only.
