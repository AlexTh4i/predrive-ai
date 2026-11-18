-- =====================================================================
-- PreDrive AI - DU LIEU MAU (chi cho dev/demo). ~20 dong moi bang.
-- Mat khau = '!UNSET' (khong ai dang nhap duoc) cho den khi chay:
--   python scripts/hash_seed_passwords.py
-- Khong chay file nay o production.
-- =====================================================================

do $$
begin
  if current_setting('app.env', true) = 'production' then
    raise exception 'seed.sql bi chan o production (app.env=production)';
  end if;
end $$;

-- ---------- Ham/bang phu (xoa o cuoi file) ----------
create or replace function public.seed_id(k text, n int) returns uuid
language sql immutable as $$ select md5(k || ':' || n)::uuid $$;

-- user n: 1-3 manager (cong ty n), 4-6 dispatcher (cong ty n-3), 7-20 tai xe (14 nguoi, xoay vong 3 cong ty)
create or replace function public.seed_user_org(n int) returns int
language sql immutable as $$
  select case when n <= 3 then n when n <= 6 then n - 3 else (n - 7) % 3 + 1 end
$$;

-- Ngu canh cho 20 phien: i -> tai xe d, cong ty o, xe v (cung cong ty)
create temp table seed_ctx as
select i,
       ((i - 1) % 14) + 1                                  as d,
       (((i - 1) % 14) % 3) + 1                            as o,
       (((i - 1) % 14) % 3) + 1 + 3 * ((i - 1) % 6)        as v
from generate_series(1, 20) i;

-- ---------- 1. organizations (3 cong ty de demo multi-tenant) ----------
insert into organizations (id, name, slug, plan)
select public.seed_id('org', n),
       (array['Vận tải Bình Minh', 'Xe khách Sao Việt', 'Logistics Thăng Long'])[n],
       (array['binh-minh', 'sao-viet', 'thang-long'])[n],
       (array['pilot', 'standard', 'pilot'])[n]
from generate_series(1, 3) n;

-- ---------- 2. users (20) ----------
insert into users (id, organization_id, username, password_hash, full_name, role, phone, zalo_phone)
select public.seed_id('user', n),
       public.seed_id('org', public.seed_user_org(n)),
       case when n <= 3 then 'manager' || n
            when n <= 6 then 'dispatcher' || (n - 3)
            else 'driver' || (n - 6) end,
       '!UNSET',
       (array['Nguyễn Văn An','Trần Thị Bình','Lê Hoàng Cường','Phạm Minh Dũng','Hoàng Thị Em',
              'Vũ Quốc Phong','Đặng Văn Giang','Bùi Thanh Hải','Ngô Đức Khoa','Đỗ Văn Lâm',
              'Lý Minh Nhật','Phan Văn Quân','Võ Thị Sương','Trương Văn Tài','Dương Quốc Uy',
              'Mai Văn Việt','Hồ Thanh Xuân','Cao Văn Yên','Tạ Quang Huy','Lâm Văn Thịnh'])[n],
       (case when n <= 3 then 'manager' when n <= 6 then 'dispatcher' else 'driver' end)::user_role,
       '09' || lpad((10000000 + n * 137)::text, 8, '0'),
       '09' || lpad((10000000 + n * 137)::text, 8, '0')
from generate_series(1, 20) n;

-- ---------- 3. vehicles (20) ----------
insert into vehicles (id, organization_id, plate, vehicle_type, brand_model, tracker_device_id)
select public.seed_id('vehicle', n),
       public.seed_id('org', (n - 1) % 3 + 1),
       (array['29H','30K','51C','43C','37C'])[(n % 5) + 1] || '-' || lpad((120 + n)::text, 3, '0') || '.' || lpad((n * 7 % 100)::text, 2, '0'),
       (array['car','coach','truck','container'])[(n % 4) + 1]::vehicle_type,
       (array['Hyundai Universe','Thaco Auto','Hino 500','Isuzu FVR','Howo A7','Ford Transit'])[(n % 6) + 1],
       'GPS-' || lpad(n::text, 4, '0')
from generate_series(1, 20) n;

-- Gan xe cho 14 tai xe mau
update users u
   set vehicle_id = public.seed_id('vehicle', ((n - 7) % 20) + 1)
  from generate_series(7, 20) n
 where u.id = public.seed_id('user', n)
   and u.organization_id = (select v.organization_id from vehicles v where v.id = public.seed_id('vehicle', ((n - 7) % 20) + 1));

-- ---------- 4. pairings (20) ----------
insert into pairings (id, organization_id, vehicle_id, driver_id, code, status, expires_at, used_at, consented_at, created_by)
select public.seed_id('pairing', c.i),
       public.seed_id('org', c.o),
       public.seed_id('vehicle', c.v),
       public.seed_id('user', c.d + 6),
       'PAIR' || lpad(c.i::text, 2, '0'),
       case when c.i <= 5 then 'PAIRED' else 'PENDING' end,
       now() + interval '30 days',
       case when c.i <= 5 then now() - make_interval(days => c.i) end,
       case when c.i <= 5 then now() - make_interval(days => c.i) end,
       public.seed_id('user', c.o)
from seed_ctx c;

-- ---------- 5. sessions (20; 3 phien dang chay) ----------
insert into sessions (id, organization_id, driver_id, vehicle_id, status, started_at, ended_at,
                      last_heartbeat_at, total_driving_sec, current_state, app_version, device_model)
select public.seed_id('session', c.i),
       public.seed_id('org', c.o),
       public.seed_id('user', c.d + 6),
       public.seed_id('vehicle', c.v),
       (case when c.i <= 3 then 'active' else 'ended' end)::session_status,
       now() - make_interval(hours => c.i * 3),
       case when c.i > 3 then now() - make_interval(hours => c.i * 3) + interval '4 hours' end,
       case when c.i <= 3 then now() - interval '5 seconds' else now() - make_interval(hours => c.i * 3) + interval '4 hours' end,
       case when c.i <= 3 then 3600 else 14400 end,
       case when c.i <= 3 then 'NORMAL' else 'OFFLINE' end,
       '3.0.' || (c.i % 3),
       (array['Samsung A15','Xiaomi Redmi Note 12','OPPO A58','Vivo Y36','Realme C55'])[(c.i % 5) + 1]
from seed_ctx c;

-- ---------- 6. events (20; OPEN/ESCALATED/CLOSED xoay vong) ----------
insert into events (id, organization_id, session_id, driver_id, vehicle_id, client_event_id, type, level,
                    status, delayed, occurred_at, escalated_at, closed_at, ack_by, ack_at,
                    lat, lng, metrics, driver_feedback)
select public.seed_id('event', c.i),
       public.seed_id('org', c.o),
       public.seed_id('session', c.i),
       public.seed_id('user', c.d + 6),
       public.seed_id('vehicle', c.v),
       'evt-' || lpad(c.i::text, 4, '0'),
       (array['DROWSY','DISTRACTED','HEAD_DOWN','TOO_DARK','NO_FACE'])[(c.i % 5) + 1]::event_type,
       ((c.i % 3) + 1)::smallint,
       (array['OPEN','ESCALATED','CLOSED'])[(c.i % 3) + 1]::event_status,
       (c.i % 7 = 0),
       now() - make_interval(mins => c.i * 45),
       case when c.i % 3 = 1 then now() - make_interval(mins => c.i * 45) + interval '2 minutes' end,
       case when c.i % 3 = 2 then now() - make_interval(mins => c.i * 45) + interval '5 minutes' end,
       case when c.i % 3 = 2 then public.seed_id('user', 3 + c.o) end,
       case when c.i % 3 = 2 then now() - make_interval(mins => c.i * 45) + interval '3 minutes' end,
       20.95 - c.i * 0.11,
       105.85 + c.i * 0.025,
       jsonb_build_object('ear', round((0.15 + (c.i % 5) * 0.03)::numeric, 2), 'duration_sec', 1 + (c.i % 4)),
       (array[null::text, 'correct', 'false_alarm'])[(c.i % 3) + 1]
from seed_ctx c;

-- ---------- 7. heartbeats (20) ----------
insert into heartbeats (organization_id, session_id, driver_id, ts, state, ear, mar, battery_pct, temp_c, fps, lat, lng, speed_kmh)
select public.seed_id('org', c.o),
       public.seed_id('session', c.i),
       public.seed_id('user', c.d + 6),
       now() - make_interval(mins => c.i),
       (array['NORMAL','NORMAL','WARNING','NORMAL'])[(c.i % 4) + 1],
       0.22 + (c.i % 7) * 0.02,
       0.30 + (c.i % 5) * 0.05,
       (95 - c.i)::smallint,
       33 + (c.i % 9),
       10 - (c.i % 3),
       20.95 - c.i * 0.11,
       105.85 + c.i * 0.025,
       50 + (c.i * 3) % 35
from seed_ctx c;

-- ---------- 8. settings (1 dong / cong ty) ----------
insert into settings (organization_id)
select public.seed_id('org', n) from generate_series(1, 3) n;

-- ---------- 9. locations (20; ban do + gan canh bao) ----------
insert into locations (organization_id, session_id, vehicle_id, driver_id, ts, lat, lng, speed_kmh, heading_deg, event_id)
select public.seed_id('org', c.o),
       public.seed_id('session', c.i),
       public.seed_id('vehicle', c.v),
       public.seed_id('user', c.d + 6),
       now() - make_interval(mins => c.i * 2),
       20.95 - c.i * 0.11,
       105.85 + c.i * 0.025,
       50 + (c.i * 3) % 35,
       170 + (c.i % 20),
       case when c.i % 2 = 0 then public.seed_id('event', c.i) end
from seed_ctx c;

-- ---------- 10. rest_stops (20, dung chung, doc QL1A Ha Noi -> Vinh) ----------
insert into rest_stops (id, organization_id, name, stop_type, lat, lng, open_24h, has_truck_parking)
select public.seed_id('stop', n),
       null,
       'Trạm dừng chân QL1A #' || n,
       (array['rest_area','gas_station','restaurant','parking'])[(n % 4) + 1],
       21.0 - n * 0.12,
       105.8 + n * 0.03,
       (n % 2 = 0),
       (n % 5 <> 0)
from generate_series(1, 20) n;

-- ---------- 11. rest_breaks (20) ----------
insert into rest_breaks (organization_id, driver_id, session_id, drive_min_before, reminder_sent_at,
                         suggested_stop_id, started_at, ended_at)
select public.seed_id('org', c.o),
       public.seed_id('user', c.d + 6),
       public.seed_id('session', c.i),
       120 + (c.i % 4) * 30,
       now() - make_interval(hours => c.i * 3) + interval '110 minutes',
       public.seed_id('stop', c.i),
       now() - make_interval(hours => c.i * 3) + interval '2 hours',
       now() - make_interval(hours => c.i * 3) + interval '2 hours 20 minutes'
from seed_ctx c;

-- ---------- 12. escalation_policies (3 cong ty x 3 muc = 9) ----------
insert into escalation_policies (id, organization_id, level, after_seconds, notify_role, channel)
select public.seed_id('pol', o * 10 + l),
       public.seed_id('org', o),
       l,
       (array[60, 180, 300])[l],
       (array['dispatcher', 'manager', 'manager'])[l]::user_role,
       (array['push', 'push', 'sms'])[l]
from generate_series(1, 3) o, generate_series(1, 3) l;

-- ---------- 13. escalations (20) ----------
insert into escalations (organization_id, event_id, policy_id, notified_user_id, channel, status, sent_at)
select public.seed_id('org', c.o),
       public.seed_id('event', c.i),
       p.id,
       public.seed_id('user', case when p.level = 1 then 3 + c.o else c.o end),
       p.channel,
       (array['sent', 'delivered', 'acked'])[(c.i % 3) + 1],
       now() - make_interval(mins => c.i * 45) + make_interval(secs => p.after_seconds)
from seed_ctx c
join escalation_policies p on p.id = public.seed_id('pol', c.o * 10 + ((c.i % 3) + 1));

-- ---------- 14. risk_scores (20: 14 tai xe tuan nay + 6 tuan truoc) ----------
insert into risk_scores (organization_id, driver_id, period_type, period_start, period_end, score, risk_level,
                         events_count, drowsy_events, distraction_events, driving_hours)
select public.seed_id('org', ((((n - 1) % 14) + 1 - 1) % 3) + 1),
       public.seed_id('user', ((n - 1) % 14) + 1 + 6),
       'weekly',
       date_trunc('week', current_date)::date - case when n > 14 then 7 else 0 end,
       date_trunc('week', current_date)::date - case when n > 14 then 7 else 0 end + 6,
       (10 + (n * 37) % 80)::smallint,
       case when 10 + (n * 37) % 80 >= 60 then 'high' when 10 + (n * 37) % 80 >= 35 then 'medium' else 'low' end,
       (n * 3) % 12,
       (n * 3) % 12 - ((n * 3) % 12) / 3,
       ((n * 3) % 12) / 3,
       (20 + n)::numeric
from generate_series(1, 20) n;

-- ---------- 15. reports (20) ----------
insert into reports (organization_id, report_type, file_format, period_start, period_end, status, storage_path, created_by)
select public.seed_id('org', (n - 1) % 3 + 1),
       (array['weekly', 'monthly'])[(n % 2) + 1],
       (array['pdf', 'xlsx'])[((n / 2) % 2) + 1],
       current_date - n * 7,
       current_date - n * 7 + 6,
       'ready',
       'reports/org' || ((n - 1) % 3 + 1) || '/report-' || lpad(n::text, 3, '0'),
       public.seed_id('user', (n - 1) % 3 + 1)
from generate_series(1, 20) n;

-- ---------- 16. app_usage_daily (20) ----------
insert into app_usage_daily (organization_id, driver_id, usage_date, monitored_minutes, monitoring_off_count, alerts_total, alerts_false)
select public.seed_id('org', ((((n - 1) % 14)) % 3) + 1),
       public.seed_id('user', ((n - 1) % 14) + 1 + 6),
       current_date - ((n - 1) / 14),
       300 + (n * 17) % 200,
       n % 4,
       3 + n % 9,
       n % 3
from generate_series(1, 20) n;

-- ---------- 17. refresh_tokens (20; chi hash gia) ----------
insert into refresh_tokens (organization_id, user_id, token_hash, expires_at, revoked_at, user_agent, ip)
select public.seed_id('org', public.seed_user_org(n)),
       public.seed_id('user', n),
       md5('seed-refresh-token-' || n),
       now() + interval '30 days',
       case when n % 5 = 0 then now() - interval '1 day' end,
       case when n <= 6 then 'Chrome/AdminWeb' else 'PreDriveApp/Android' end,
       ('10.0.0.' || n)::inet
from generate_series(1, 20) n;

-- ---------- 18. audit_logs (20) ----------
insert into audit_logs (organization_id, actor_id, action, entity, entity_id, ip, meta, created_at)
select public.seed_id('org', public.seed_user_org(((n - 1) % 6) + 1)),
       public.seed_id('user', ((n - 1) % 6) + 1),
       (array['login','ack_event','update_settings','create_driver','create_pairing'])[(n % 5) + 1],
       (array['session','event','settings','user','pairing'])[(n % 5) + 1],
       n::text,
       ('192.168.1.' || (10 + n))::inet,
       jsonb_build_object('note', 'seed'),
       now() - make_interval(hours => n)
from generate_series(1, 20) n;

-- ---------- 19. push_tokens (20) ----------
insert into push_tokens (organization_id, user_id, fcm_token, platform)
select public.seed_id('org', public.seed_user_org(n)),
       public.seed_id('user', n),
       'dev-fcm-token-' || lpad(n::text, 3, '0'),
       case when n <= 6 then 'web' else 'android' end
from generate_series(1, 20) n;

-- ---------- 20. consents (14 tai xe) ----------
insert into consents (organization_id, user_id, consent_type, version, location_consent, clip_storage_consent, accepted_at)
select public.seed_id('org', public.seed_user_org(n)),
       public.seed_id('user', n),
       'data_processing',
       '2026-01',
       (n % 4 <> 0),
       false,
       now() - make_interval(days => n)
from generate_series(7, 20) n;

-- ---------- 21. api_keys (6) ----------
insert into api_keys (organization_id, name, key_prefix, key_hash, scopes)
select public.seed_id('org', (n - 1) % 3 + 1),
       'Tích hợp GPS #' || n,
       'pd_dev_' || n,
       md5('seed-api-key-' || n),
       array['events:read', 'vehicles:read']
from generate_series(1, 6) n;

-- ---------- 22. webhooks (6) ----------
insert into webhooks (organization_id, url, secret_hash, events)
select public.seed_id('org', (n - 1) % 3 + 1),
       'https://example.com/webhook/' || n,
       md5('seed-webhook-secret-' || n),
       array['alert.created', 'alert.escalated']
from generate_series(1, 6) n;

-- ---------- Don dep ----------
drop table seed_ctx;
drop function public.seed_user_org(int);
drop function public.seed_id(text, int);

-- ---------- Kiem tra nhanh ----------
select 'organizations' t, count(*) from organizations union all
select 'users', count(*) from users union all
select 'vehicles', count(*) from vehicles union all
select 'pairings', count(*) from pairings union all
select 'sessions', count(*) from sessions union all
select 'events', count(*) from events union all
select 'heartbeats', count(*) from heartbeats union all
select 'settings', count(*) from settings union all
select 'locations', count(*) from locations union all
select 'rest_stops', count(*) from rest_stops union all
select 'rest_breaks', count(*) from rest_breaks union all
select 'escalation_policies', count(*) from escalation_policies union all
select 'escalations', count(*) from escalations union all
select 'risk_scores', count(*) from risk_scores union all
select 'reports', count(*) from reports union all
select 'app_usage_daily', count(*) from app_usage_daily union all
select 'refresh_tokens', count(*) from refresh_tokens union all
select 'audit_logs', count(*) from audit_logs union all
select 'push_tokens', count(*) from push_tokens union all
select 'consents', count(*) from consents union all
select 'api_keys', count(*) from api_keys union all
select 'webhooks', count(*) from webhooks;
