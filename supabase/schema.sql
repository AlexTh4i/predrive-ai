-- =====================================================================
-- PreDrive AI - PostgreSQL / Supabase schema (v1)
-- Chay tren database TRONG (lan dau). Can PostgreSQL 15+ (Supabase dap ung).
-- Khong luu anh/video khuon mat (R1): chi metadata su kien + heartbeat.
-- =====================================================================

create extension if not exists pgcrypto;

-- ---------- Enum ----------
create type user_role      as enum ('manager', 'dispatcher', 'driver');
create type vehicle_type   as enum ('car', 'coach', 'truck', 'container');
create type event_type     as enum ('DROWSY', 'DROWSINESS', 'DISTRACTED', 'HEAD_DOWN', 'TOO_DARK', 'NO_FACE', 'LONG_DRIVING', 'DISCONNECTED', 'REST_CLAIM_REJECTED');
create type event_status   as enum ('OPEN', 'ESCALATED', 'CLOSED');
create type session_status as enum ('active', 'ended', 'disconnected');

-- ---------- 1. Multi-tenant goc ----------
create table organizations (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  slug        text not null unique,
  plan        text not null default 'pilot',
  is_active   boolean not null default true,
  created_at  timestamptz not null default now()
);

create table users (
  id                   uuid primary key default gen_random_uuid(),
  organization_id      uuid not null references organizations(id) on delete cascade,
  username             text not null unique,
  password_hash        text not null,               -- Argon2id (backend tao); '!UNSET' = chua dat mat khau
  full_name            text not null,
  role                 user_role not null,
  phone                text,
  zalo_phone           text,
  vehicle_id           uuid,                        -- FK gan sau khi tao bang vehicles
  avatar_url           text,
  must_change_password boolean not null default false,
  is_active            boolean not null default true,
  last_login_at        timestamptz,
  created_at           timestamptz not null default now()
);
create index users_org_role_idx on users (organization_id, role);

create table vehicles (
  id                 uuid primary key default gen_random_uuid(),
  organization_id    uuid not null references organizations(id) on delete cascade,
  plate              text not null,
  vehicle_type       vehicle_type not null default 'truck',
  brand_model        text,
  tracker_device_id  text,                     -- lien ket thiet bi giam sat hanh trinh ben thu ba
  is_active          boolean not null default true,
  created_at         timestamptz not null default now(),
  unique (organization_id, plate)
);

alter table users
  add constraint users_vehicle_id_fkey
  foreign key (vehicle_id) references vehicles(id) on delete set null;

create table pairings (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  vehicle_id      uuid references vehicles(id) on delete set null,
  driver_id       uuid references users(id) on delete set null,
  code            varchar(32) not null unique,
  status          text not null default 'PENDING',
  expires_at      timestamptz not null,
  used_at         timestamptz,
  consented_at    timestamptz,
  created_by      uuid references users(id) on delete set null,
  created_at      timestamptz not null default now()
);
create index pairings_org_expires_idx on pairings (organization_id, expires_at);

create table sessions (
  id                     uuid primary key default gen_random_uuid(),
  organization_id        uuid not null references organizations(id) on delete cascade,
  driver_id              uuid not null references users(id) on delete cascade,
  vehicle_id             uuid references vehicles(id) on delete set null,
  status                 session_status not null default 'active',
  started_at             timestamptz not null default now(),
  ended_at               timestamptz,
  last_heartbeat_at      timestamptz,
  total_driving_sec      integer not null default 0,
  continuous_driving_sec integer not null default 0,
  unavailable_sec        integer not null default 0,
  warning_count          integer not null default 0,
  critical_count         integer not null default 0,
  current_state          text not null default 'NORMAL',
  app_version            text,
  device_model           text
);
create index sessions_org_status_idx on sessions (organization_id, status);
create index sessions_driver_idx on sessions (driver_id, started_at desc);

create table events (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null references organizations(id) on delete cascade,
  session_id       uuid not null references sessions(id) on delete cascade,
  driver_id        uuid not null references users(id) on delete cascade,
  vehicle_id       uuid references vehicles(id) on delete set null,
  client_event_id  text not null,              -- idempotency key tu app (offline queue)
  type             event_type not null,
  level            smallint not null default 1 check (level between 1 and 3), -- 1 nhac nhe, 2 chuong, 3 bao dieu hanh
  status           event_status not null default 'OPEN',
  delayed          boolean not null default false,   -- gui bu > 60s
  occurred_at      timestamptz not null,
  escalated_at     timestamptz,
  closed_at        timestamptz,
  ack_by           uuid references users(id) on delete set null,
  ack_at           timestamptz,
  note             text,
  lat              double precision,
  lng              double precision,
  metrics          jsonb not null default '{}'::jsonb,
  driver_feedback  text check (driver_feedback in ('correct', 'false_alarm')),
  created_at       timestamptz not null default now(),
  unique (session_id, client_event_id)
);
create index events_org_time_idx   on events (organization_id, occurred_at desc);
create index events_org_status_idx on events (organization_id, status) where status <> 'CLOSED';
create index events_driver_idx     on events (driver_id, occurred_at desc);

create table heartbeats (
  id              bigint generated always as identity primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  session_id      uuid not null references sessions(id) on delete cascade,
  driver_id       uuid references users(id) on delete cascade,
  ts              timestamptz not null default now(),
  state           text not null default 'NORMAL',
  image_quality   text not null default 'GOOD',
  vehicle_moving  boolean not null default true,
  ear             real,
  mar             real,
  battery_pct     smallint check (battery_pct between 0 and 100),
  temp_c          real,
  fps             real,
  lat             double precision,
  lng             double precision,
  speed_kmh       real
);
create index heartbeats_session_ts_idx on heartbeats (session_id, ts desc);
create index heartbeats_ts_idx on heartbeats (ts);

-- Nguong + chinh sach theo tung cong ty (R3: khong hard-code)
create table settings (
  organization_id            uuid primary key references organizations(id) on delete cascade,
  ear_threshold              real    not null default 0.28,
  eye_closed_sec             real    not null default 1.0,
  head_pose_sec              real    not null default 1.8,
  too_dark_threshold         real    not null default 20,
  level1_sec                 real    not null default 1.0,   -- nhac nhe
  level2_sec                 real    not null default 2.0,   -- chuong
  level3_sec                 real    not null default 4.0,   -- bao dieu hanh
  ack_timeout_sec            integer not null default 60,    -- leo thang neu chua "Da lien he"
  continuous_warn_sec        integer not null default 7200,
  continuous_critical_sec    integer not null default 10800,
  max_continuous_drive_min   integer not null default 240,
  min_rest_min               integer not null default 15,
  rest_reminder_before_min   integer not null default 15,
  share_location             boolean not null default false,
  heartbeat_interval_sec     integer not null default 30,
  location_interval_sec      integer not null default 30,
  heartbeat_retention_days   integer not null default 30,
  location_retention_days    integer not null default 90,
  event_retention_days       integer not null default 365,
  audit_retention_days       integer not null default 730,
  updated_at                 timestamptz not null default now()
);

-- ---------- 2. GPS / ban do ----------
create table locations (
  id              bigint generated always as identity primary key,
  organization_id uuid not null references organizations(id) on delete cascade,
  session_id      uuid references sessions(id) on delete cascade,
  vehicle_id      uuid references vehicles(id) on delete cascade,
  driver_id       uuid references users(id) on delete cascade,
  ts              timestamptz not null default now(),
  lat             double precision not null,
  lng             double precision not null,
  speed_kmh       real,
  heading_deg     real,
  event_id        uuid references events(id) on delete set null   -- gan canh bao vao diem tren tuyen
);
create index locations_vehicle_ts_idx on locations (vehicle_id, ts desc);
create index locations_driver_ts_idx on locations (driver_id, ts desc);
create index locations_ts_idx on locations (ts);

create table rest_stops (            -- diem dung nghi (organization_id null = dung chung)
  id                uuid primary key default gen_random_uuid(),
  organization_id   uuid references organizations(id) on delete cascade,
  name              text not null,
  stop_type         text not null check (stop_type in ('rest_area', 'gas_station', 'restaurant', 'parking')),
  lat               double precision not null,
  lng               double precision not null,
  open_24h          boolean not null default false,
  has_truck_parking boolean not null default true
);

-- ---------- 3. Gio lai & nghi ngoi ----------
create table rest_breaks (
  id                       uuid primary key default gen_random_uuid(),
  organization_id          uuid not null references organizations(id) on delete cascade,
  driver_id                uuid not null references users(id) on delete cascade,
  session_id               uuid references sessions(id) on delete set null,
  drive_min_before         integer not null,            -- so phut lai lien tuc truoc khi nghi
  reminder_sent_at         timestamptz,
  suggested_stop_id        uuid references rest_stops(id) on delete set null,
  started_at               timestamptz not null,
  ended_at                 timestamptz
);
create index rest_breaks_driver_idx on rest_breaks (driver_id, started_at desc);

-- ---------- 4. Canh bao nhieu muc & leo thang ----------
create table escalation_policies (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  level           smallint not null check (level between 1 and 3),
  after_seconds   integer not null,
  notify_role     user_role not null,
  channel         text not null check (channel in ('push', 'sms', 'zalo', 'call')),
  is_active       boolean not null default true,
  unique (organization_id, level)
);

create table escalations (
  id               uuid primary key default gen_random_uuid(),
  organization_id  uuid not null references organizations(id) on delete cascade,
  event_id         uuid not null references events(id) on delete cascade,
  policy_id        uuid references escalation_policies(id) on delete set null,
  notified_user_id uuid references users(id) on delete set null,
  channel          text not null,
  status           text not null default 'sent' check (status in ('sent', 'delivered', 'acked', 'failed')),
  sent_at          timestamptz not null default now()
);
create index escalations_event_idx on escalations (event_id);

-- ---------- 5. Diem rui ro, bao cao, su dung app ----------
create table risk_scores (
  id                 uuid primary key default gen_random_uuid(),
  organization_id    uuid not null references organizations(id) on delete cascade,
  driver_id          uuid not null references users(id) on delete cascade,
  period_type        text not null check (period_type in ('shift', 'weekly', 'monthly')),
  period_start       date not null,
  period_end         date not null,
  score              smallint not null check (score between 0 and 100),   -- cao = rui ro cao
  risk_level         text not null check (risk_level in ('low', 'medium', 'high')),
  events_count       integer not null default 0,
  drowsy_events      integer not null default 0,
  distraction_events integer not null default 0,
  driving_hours      numeric(6,1) not null default 0,
  unique (driver_id, period_type, period_start)
);

create table reports (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  report_type     text not null check (report_type in ('weekly', 'monthly')),
  file_format     text not null check (file_format in ('pdf', 'xlsx')),
  period_start    date not null,
  period_end      date not null,
  status          text not null default 'ready' check (status in ('pending', 'ready', 'failed')),
  storage_path    text,
  created_by      uuid references users(id) on delete set null,
  created_at      timestamptz not null default now()
);

-- Do ty le "bo dung app" / nhon canh bao (alarm fatigue)
create table app_usage_daily (
  id                   uuid primary key default gen_random_uuid(),
  organization_id      uuid not null references organizations(id) on delete cascade,
  driver_id            uuid not null references users(id) on delete cascade,
  usage_date           date not null,
  monitored_minutes    integer not null default 0,
  monitoring_off_count integer not null default 0,   -- so lan tai xe tat giam sat
  alerts_total         integer not null default 0,
  alerts_false         integer not null default 0,   -- tai xe bam "bao sai"
  unique (driver_id, usage_date)
);

-- ---------- 6. Bao mat: token, audit, push, consent ----------
create table refresh_tokens (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id         uuid not null references users(id) on delete cascade,
  family_id       uuid not null default gen_random_uuid(),
  token_hash      text not null unique,             -- chi luu hash, khong luu token
  expires_at      timestamptz not null,
  revoked_at      timestamptz,
  replaced_by_id  uuid references refresh_tokens(id) on delete set null,
  user_agent      text,
  ip              inet,
  created_at      timestamptz not null default now()
);
create index refresh_tokens_user_idx on refresh_tokens (user_id);
create index refresh_tokens_family_idx on refresh_tokens (family_id);

create table audit_logs (
  id              bigint generated always as identity primary key,
  organization_id uuid references organizations(id) on delete cascade,
  actor_id        uuid references users(id) on delete set null,
  action          text not null,
  entity          text,
  entity_id       text,
  ip              inet,
  meta            jsonb not null default '{}'::jsonb,
  created_at      timestamptz not null default now()
);
create index audit_logs_org_time_idx on audit_logs (organization_id, created_at desc);

create table push_tokens (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  user_id         uuid not null references users(id) on delete cascade,
  fcm_token       text not null,
  platform        text not null check (platform in ('android', 'ios', 'web')),
  updated_at      timestamptz not null default now(),
  unique (user_id, fcm_token)
);

create table consents (               -- Nghi dinh 13/2023: luu phien ban va thoi diem dong y
  id                   uuid primary key default gen_random_uuid(),
  organization_id      uuid not null references organizations(id) on delete cascade,
  user_id              uuid not null references users(id) on delete cascade,
  consent_type         text not null default 'data_processing',
  version              text not null,
  location_consent     boolean not null default false,
  clip_storage_consent boolean not null default false,   -- mac dinh tat (R1)
  accepted_at          timestamptz not null default now(),
  unique (user_id, consent_type, version)
);

-- ---------- 7. Tich hop ben thu ba ----------
create table api_keys (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  name            text not null,
  key_prefix      text not null,
  key_hash        text not null unique,             -- chi luu hash
  scopes          text[] not null default '{}',
  last_used_at    timestamptz,
  revoked_at      timestamptz,
  created_at      timestamptz not null default now()
);

create table webhooks (
  id              uuid primary key default gen_random_uuid(),
  organization_id uuid not null references organizations(id) on delete cascade,
  url             text not null,
  secret_hash     text not null,
  events          text[] not null default '{}',
  is_active       boolean not null default true,
  created_at      timestamptz not null default now()
);

-- =====================================================================
-- Row Level Security (multi-tenant that su)
-- Backend ket noi bang role postgres/service (bypass RLS) va TU loc theo
-- organization_id. RLS la lop bao ve thu hai neu ai do goi PostgREST/Supabase API.
-- JWT cua Supabase can co app_metadata.org_id.
-- =====================================================================
create or replace function public.current_org_id() returns uuid
language sql stable as $$
  select nullif(
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb -> 'app_metadata' ->> 'org_id'),
    ''
  )::uuid
$$;

do $$
declare
  t text;
  tenant_tables text[] := array[
    'users','vehicles','pairings','sessions','events','heartbeats','settings','locations',
    'rest_breaks','escalation_policies','escalations','risk_scores','reports',
    'app_usage_daily','push_tokens','consents','webhooks'
  ];
  locked_tables text[] := array['refresh_tokens','audit_logs','api_keys'];  -- chi backend/service doc duoc
  has_auth boolean := exists (select 1 from pg_roles where rolname = 'authenticated');
begin
  foreach t in array tenant_tables loop
    execute format('alter table public.%I enable row level security', t);
    if has_auth then
      execute format(
        'create policy tenant_isolation on public.%I for all to authenticated
           using (organization_id = public.current_org_id())
           with check (organization_id = public.current_org_id())', t);
    end if;
  end loop;

  foreach t in array locked_tables loop
    execute format('alter table public.%I enable row level security', t);
  end loop;

  alter table public.organizations enable row level security;
  alter table public.rest_stops    enable row level security;
  if has_auth then
    create policy own_org on public.organizations for select to authenticated
      using (id = public.current_org_id());
    create policy shared_or_own_stops on public.rest_stops for select to authenticated
      using (organization_id is null or organization_id = public.current_org_id());
  end if;
end $$;

-- =====================================================================
-- Views & ham tien ich
-- =====================================================================

-- Su kien OPEN qua han chua "Da lien he" -> watchdog dung de leo thang (P3-5)
create view v_events_pending_escalation with (security_invoker = true) as
select e.id as event_id, e.organization_id, e.driver_id, e.vehicle_id, e.level, e.occurred_at,
       extract(epoch from (now() - e.occurred_at))::int as waiting_sec,
       s.ack_timeout_sec
from events e
join settings s on s.organization_id = e.organization_id
where e.status = 'OPEN'
  and e.ack_at is null
  and not e.delayed
  and e.occurred_at < now() - make_interval(secs => s.ack_timeout_sec);

-- Ty le tat giam sat / canh bao sai trong 7 ngay (alarm fatigue)
create view v_driver_usage_7d with (security_invoker = true) as
select organization_id, driver_id,
       sum(monitored_minutes)            as monitored_minutes,
       sum(monitoring_off_count)         as monitoring_off_count,
       sum(alerts_total)                 as alerts_total,
       sum(alerts_false)                 as alerts_false,
       round(sum(monitoring_off_count)::numeric / nullif(sum(monitored_minutes) / 60.0, 0), 2) as off_per_hour,
       round(100.0 * sum(alerts_false) / nullif(sum(alerts_total), 0), 1)                      as false_alert_pct
from app_usage_daily
where usage_date >= current_date - 6
group by organization_id, driver_id;

-- Diem dung nghi gan nhat (haversine, khong can PostGIS)
create or replace function public.nearest_rest_stops(
  p_lat double precision, p_lng double precision, p_limit int default 5, p_org uuid default null
) returns table (id uuid, name text, stop_type text, lat double precision, lng double precision, distance_km double precision)
language sql stable as $$
  select r.id, r.name, r.stop_type, r.lat, r.lng,
         6371 * acos(least(1, greatest(-1,
           cos(radians(p_lat)) * cos(radians(r.lat)) * cos(radians(r.lng) - radians(p_lng))
           + sin(radians(p_lat)) * sin(radians(r.lat))))) as distance_km
  from rest_stops r
  where r.organization_id is null or r.organization_id = p_org
  order by distance_km
  limit p_limit
$$;

-- Retention: xoa du lieu cu theo cau hinh tung cong ty
create or replace function public.purge_old_data() returns jsonb
language plpgsql as $$
declare
  n_hb bigint; n_loc bigint; n_ev bigint; n_audit bigint; n_rt bigint;
begin
  delete from heartbeats h using settings s
   where s.organization_id = h.organization_id
     and h.ts < now() - make_interval(days => s.heartbeat_retention_days);
  get diagnostics n_hb = row_count;

  delete from locations l using settings s
   where s.organization_id = l.organization_id
     and l.ts < now() - make_interval(days => s.location_retention_days);
  get diagnostics n_loc = row_count;

  delete from events e using settings s
   where s.organization_id = e.organization_id
     and e.status = 'CLOSED'
     and e.occurred_at < now() - make_interval(days => s.event_retention_days);
  get diagnostics n_ev = row_count;

  delete from audit_logs a using settings s
   where s.organization_id = a.organization_id
     and a.created_at < now() - make_interval(days => s.audit_retention_days);
  get diagnostics n_audit = row_count;

  delete from refresh_tokens
   where expires_at < now() - interval '7 days' or revoked_at < now() - interval '7 days';
  get diagnostics n_rt = row_count;

  return jsonb_build_object('heartbeats', n_hb, 'locations', n_loc, 'events', n_ev,
                            'audit_logs', n_audit, 'refresh_tokens', n_rt);
end $$;

-- Lich chay hang ngay 03:00 UTC neu co pg_cron (Supabase: bat extension trong Dashboard)
do $$
begin
  if exists (select 1 from pg_available_extensions where name = 'pg_cron') then
    create extension if not exists pg_cron;
    perform cron.schedule('purge-old-data', '0 3 * * *', 'select public.purge_old_data()');
  end if;
exception when others then
  raise notice 'Bo qua pg_cron: %. Hay bat pg_cron roi chay cron.schedule thu cong.', sqlerrm;
end $$;
