-- Sentinel Prime unified account schema (run in Supabase SQL editor)
-- Enables single account for auth, billing, licenses, dashboard

create extension if not exists "uuid-ossp";

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique,
  full_name text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists public.subscriptions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  stripe_customer_id text,
  stripe_subscription_id text unique,
  plan text not null check (plan in ('monthly', 'annual', 'lifetime')),
  status text not null default 'active',
  current_period_end timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists public.product_licenses (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.profiles(id) on delete set null,
  license_key text not null unique,
  tier text not null default 'pro',
  plan text,
  machine_id text,
  activated_at timestamptz,
  created_at timestamptz default now()
);

create table if not exists public.payment_history (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.profiles(id) on delete set null,
  stripe_payment_intent text,
  stripe_invoice_id text,
  amount_cents integer not null,
  currency text default 'usd',
  plan text not null,
  status text not null,
  created_at timestamptz default now()
);

create table if not exists public.audit_logs (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid,
  action text not null,
  detail jsonb,
  created_at timestamptz default now()
);

alter table public.profiles enable row level security;
alter table public.subscriptions enable row level security;
alter table public.product_licenses enable row level security;
alter table public.payment_history enable row level security;

create policy "profiles_select_own" on public.profiles for select using (auth.uid() = id);
create policy "subscriptions_select_own" on public.subscriptions for select using (auth.uid() = user_id);
create policy "licenses_select_own" on public.product_licenses for select using (auth.uid() = user_id);

-- ─── Product analytics (downloads, installs, trials, license checks) ─────────
-- See also: supabase/migrations/001_product_analytics.sql

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
