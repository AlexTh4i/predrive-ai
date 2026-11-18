from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import random
from uuid import NAMESPACE_DNS, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..core.config import get_config
from ..core.security import hash_password
from ..models.models import (
    ApiKey,
    AppUsageDaily,
    AuditLog,
    Consent,
    Escalation,
    EscalationPolicy,
    EventModel,
    HeartbeatModel,
    LocationModel,
    Organization,
    OrgSettings,
    Pairing,
    PushToken,
    ReportModel,
    RestBreak,
    RestStop,
    RiskScore,
    SessionModel,
    User,
    Vehicle,
    Webhook,
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SEED_NS = uuid5(NAMESPACE_DNS, "predrive-ai.m3.seed.2026")


def det_uuid(name: str) -> str:
    return str(uuid5(SEED_NS, name))


ORG_ID = "11111111-1111-4111-8111-111111111111"
ORG_2_ID = "22222222-2222-4222-8222-222222222222"
ORG_3_ID = "33333333-3333-4333-8333-333333333333"

ORGS_SEED = [
    (ORG_ID, "Vận tải Bình Minh", "binh-minh", "pilot"),
    (ORG_2_ID, "Xe khách Sao Việt", "sao-viet", "standard"),
    (ORG_3_ID, "Logistics Thăng Long", "thang-long", "pilot"),
]

# Org 1 (5 vehicles + 5 drivers for M3 dashboard & tests), Org 2 (8 vehicles + 5 drivers), Org 3 (7 vehicles + 4 drivers) -> 20 vehicles, 14 drivers, 20 users total
ORG1_VEHICLES = [
    ("veh-1", "51B-123.45", "coach", "Giường nằm 40 chỗ", "GPS-0001"),
    ("veh-2", "51B-234.56", "coach", "Limousine 34 phòng", "GPS-0002"),
    ("veh-3", "51B-345.67", "coach", "Giường nằm 40 chỗ", "GPS-0003"),
    ("veh-4", "51C-456.78", "truck", "Xe tải đường dài 15T", "GPS-0004"),
    ("veh-5", "51C-567.89", "container", "Đầu kéo Container", "GPS-0005"),
]

ORG1_DRIVERS = [
    ("drv-1", "driver1", "Nguyễn Văn An", "0901234501", "veh-1"),
    ("drv-2", "driver2", "Trần Minh Bình", "0901234502", "veh-2"),
    ("drv-3", "driver3", "Lê Hoàng Cường", "0901234503", "veh-3"),
    ("drv-4", "driver4", "Phạm Quốc Dũng", "0901234504", "veh-4"),
    ("drv-5", "driver5", "Võ Thanh Hải", "0901234505", "veh-5"),
]

EXTRA_ORGS_DATA = [
    (
        ORG_2_ID,
        "2",
        "manager2",
        "Hoàng Thị Em",
        "dispatcher2",
        "Vũ Quốc Phong",
        [
            ("veh-6", "29H-126.42", "coach", "Hyundai Universe", "GPS-0006"),
            ("veh-7", "29H-127.49", "coach", "Thaco Auto", "GPS-0007"),
            ("veh-8", "30K-128.56", "car", "Ford Transit", "GPS-0008"),
            ("veh-9", "30K-129.63", "truck", "Hino 500", "GPS-0009"),
            ("veh-10", "30K-130.70", "truck", "Isuzu FVR", "GPS-0010"),
        ],
        [
            ("drv-6", "driver6", "Đặng Văn Giang", "0902234506", "veh-6"),
            ("drv-7", "driver7", "Bùi Thanh Hải", "0902234507", "veh-7"),
            ("drv-8", "driver8", "Ngô Đức Khoa", "0902234508", "veh-8"),
            ("drv-9", "driver9", "Đỗ Văn Lâm", "0902234509", "veh-9"),
            ("drv-10", "driver10", "Lý Minh Nhật", "0902234510", "veh-10"),
        ],
    ),
    (
        ORG_3_ID,
        "3",
        "manager3",
        "Phan Văn Quân",
        "dispatcher3",
        "Võ Thị Sương",
        [
            ("veh-11", "43C-131.77", "container", "Howo A7", "GPS-0011"),
            ("veh-12", "43C-132.84", "truck", "Hino 500", "GPS-0012"),
            ("veh-13", "37C-133.91", "container", "Howo A7", "GPS-0013"),
            ("veh-14", "37C-134.98", "truck", "Isuzu FVR", "GPS-0014"),
        ],
        [
            ("drv-11", "driver11", "Trương Văn Tài", "0903234511", "veh-11"),
            ("drv-12", "driver12", "Dương Quốc Uy", "0903234512", "veh-12"),
            ("drv-13", "driver13", "Mai Văn Việt", "0903234513", "veh-13"),
            ("drv-14", "driver14", "Hồ Thanh Xuân", "0903234514", "veh-14"),
        ],
    ),
]


def seed_database(db: Session, ref_now_utc: datetime | None = None) -> dict[str, int]:
    """Idempotently seed 3 multi-tenant organizations, 20 users (3 managers, 3 dispatchers,
    14 drivers), vehicles, pairings, rest stops, escalation policies, consents, and historical
    sessions/events. Strictly blocked when ENV == 'production' (R5 / P0-4 / P1-1).
    """
    if get_config().is_production:
        raise RuntimeError(
            "seed_database is strictly prohibited when ENV=production (R5)"
        )

    now_utc = ref_now_utc or datetime.now(timezone.utc)
    now_vn = now_utc.astimezone(VN_TZ)

    # Pre-compute password hashes once for fast seeding
    mgr_hash = hash_password("manager123")
    disp_hash = hash_password("dispatcher123")
    drv_hash = hash_password("driver123")

    # 1. Organizations & Settings & Escalation Policies
    for o_id, o_name, o_slug, o_plan in ORGS_SEED:
        if db.get(Organization, o_id) is None:
            db.add(
                Organization(
                    id=o_id,
                    name=o_name,
                    slug=o_slug,
                    plan=o_plan,
                    is_active=True,
                    created_at=now_utc - timedelta(days=60),
                )
            )
            db.flush()

        if db.get(OrgSettings, o_id) is None:
            db.add(
                OrgSettings(
                    organization_id=o_id,
                    continuous_warn_sec=7200,
                    continuous_critical_sec=10800,
                    min_rest_min=15,
                    share_location=False,
                    heartbeat_interval_sec=30,
                    updated_at=now_utc,
                )
            )
            db.flush()

        for lvl, after_sec, role_target, chan in (
            (1, 60, "dispatcher", "push"),
            (2, 180, "manager", "push"),
            (3, 300, "manager", "sms"),
        ):
            pol_id = det_uuid(f"pol-{o_slug}-{lvl}")
            if db.get(EscalationPolicy, pol_id) is None:
                db.add(
                    EscalationPolicy(
                        id=pol_id,
                        organization_id=o_id,
                        level=lvl,
                        after_seconds=after_sec,
                        notify_role=role_target,
                        channel=chan,
                        is_active=True,
                    )
                )
    db.flush()

    # 2. Shared Rest Stops (20 stops along QL1A)
    stop_types = ["rest_area", "gas_station", "restaurant", "parking"]
    stop_ids: list[str] = []
    for n in range(1, 21):
        st_id = det_uuid(f"rest-stop-{n}")
        stop_ids.append(st_id)
        if db.get(RestStop, st_id) is None:
            db.add(
                RestStop(
                    id=st_id,
                    organization_id=None,
                    name=f"Trạm dừng chân QL1A #{n}",
                    stop_type=stop_types[(n - 1) % 4],
                    lat=round(21.0 - n * 0.12, 5),
                    lng=round(105.8 + n * 0.03, 5),
                    open_24h=(n % 2 == 0),
                    has_truck_parking=(n % 5 != 0),
                )
            )
    db.flush()

    # 3. Org 1 Vehicles, Manager, Dispatcher, 5 Drivers, Pairings & Consents
    vehicle_ids: dict[str, str] = {}
    for key, plate, v_type, brand, tracker_id in ORG1_VEHICLES:
        v_id = det_uuid(key)
        vehicle_ids[key] = v_id
        if db.get(Vehicle, v_id) is None:
            db.add(
                Vehicle(
                    id=v_id,
                    organization_id=ORG_ID,
                    plate=plate,
                    vehicle_type=v_type,
                    brand_model=brand,
                    tracker_device_id=tracker_id,
                    created_at=now_utc - timedelta(days=45),
                )
            )
    db.flush()

    mgr_id = det_uuid("user-manager")
    if db.get(User, mgr_id) is None:
        db.add(
            User(
                id=mgr_id,
                organization_id=ORG_ID,
                username="manager",
                password_hash=mgr_hash,
                role="manager",
                full_name="Nguyễn Quốc Quản Lý",
                phone="0909000001",
                zalo_phone="0909000001",
                vehicle_id=None,
                created_at=now_utc - timedelta(days=45),
            )
        )

    disp_id = det_uuid("user-dispatcher")
    if db.get(User, disp_id) is None:
        db.add(
            User(
                id=disp_id,
                organization_id=ORG_ID,
                username="dispatcher",
                password_hash=disp_hash,
                role="dispatcher",
                full_name="Trần Thị Trực Ban",
                phone="0909000002",
                zalo_phone="0909000002",
                vehicle_id=None,
                created_at=now_utc - timedelta(days=45),
            )
        )

    driver_records: list[tuple[str, str, str]] = []
    for idx, (drv_key, username, full_name, phone, veh_key) in enumerate(
        ORG1_DRIVERS, start=1
    ):
        d_id = det_uuid(drv_key)
        v_id = vehicle_ids[veh_key]
        driver_records.append((d_id, v_id, full_name))
        if db.get(User, d_id) is None:
            db.add(
                User(
                    id=d_id,
                    organization_id=ORG_ID,
                    username=username,
                    password_hash=drv_hash,
                    role="driver",
                    full_name=full_name,
                    phone=phone,
                    zalo_phone=phone,
                    vehicle_id=v_id,
                    created_at=now_utc - timedelta(days=40),
                )
            )
    db.flush()

    for idx, (drv_key, _u, _fn, _ph, veh_key) in enumerate(ORG1_DRIVERS, start=1):
        d_id = det_uuid(drv_key)
        v_id = vehicle_ids[veh_key]
        pair_id = det_uuid(f"pairing-{drv_key}")
        if db.get(Pairing, pair_id) is None:
            db.add(
                Pairing(
                    id=pair_id,
                    organization_id=ORG_ID,
                    vehicle_id=v_id,
                    driver_id=d_id,
                    code=f"PAIR0{idx}",
                    status="PAIRED",
                    expires_at=now_utc + timedelta(days=30),
                    used_at=now_utc - timedelta(days=35),
                    consented_at=now_utc - timedelta(days=35),
                    created_by=mgr_id,
                    created_at=now_utc - timedelta(days=35),
                )
            )
        consent_id = det_uuid(f"consent-{drv_key}")
        if db.get(Consent, consent_id) is None:
            db.add(
                Consent(
                    id=consent_id,
                    organization_id=ORG_ID,
                    user_id=d_id,
                    consent_type="data_processing",
                    version="2026-01",
                    location_consent=True,
                    clip_storage_consent=False,
                    accepted_at=now_utc - timedelta(days=35),
                )
            )
    db.flush()

    # 4. Org 2 & Org 3 Multi-tenant Seed (matching seed.sql structure)
    pair_counter = 6
    for (
        o_id,
        suffix,
        m_user,
        m_name,
        d_user,
        d_name,
        vehs,
        drvs,
    ) in EXTRA_ORGS_DATA:
        o_mgr_id = det_uuid(f"user-manager-{suffix}")
        if db.get(User, o_mgr_id) is None:
            db.add(
                User(
                    id=o_mgr_id,
                    organization_id=o_id,
                    username=m_user,
                    password_hash=mgr_hash,
                    role="manager",
                    full_name=m_name,
                    phone=f"090900010{suffix}",
                    zalo_phone=f"090900010{suffix}",
                    created_at=now_utc - timedelta(days=45),
                )
            )
        o_disp_id = det_uuid(f"user-dispatcher-{suffix}")
        if db.get(User, o_disp_id) is None:
            db.add(
                User(
                    id=o_disp_id,
                    organization_id=o_id,
                    username=d_user,
                    password_hash=disp_hash,
                    role="dispatcher",
                    full_name=d_name,
                    phone=f"090900020{suffix}",
                    zalo_phone=f"090900020{suffix}",
                    created_at=now_utc - timedelta(days=45),
                )
            )

        for v_key, plate, v_type, brand, tracker_id in vehs:
            v_id = det_uuid(v_key)
            vehicle_ids[v_key] = v_id
            if db.get(Vehicle, v_id) is None:
                db.add(
                    Vehicle(
                        id=v_id,
                        organization_id=o_id,
                        plate=plate,
                        vehicle_type=v_type,
                        brand_model=brand,
                        tracker_device_id=tracker_id,
                        created_at=now_utc - timedelta(days=45),
                    )
                )
        db.flush()

        for drv_key, username, full_name, phone, veh_key in drvs:
            d_id = det_uuid(drv_key)
            v_id = vehicle_ids[veh_key]
            if db.get(User, d_id) is None:
                db.add(
                    User(
                        id=d_id,
                        organization_id=o_id,
                        username=username,
                        password_hash=drv_hash,
                        role="driver",
                        full_name=full_name,
                        phone=phone,
                        zalo_phone=phone,
                        vehicle_id=v_id,
                        created_at=now_utc - timedelta(days=40),
                    )
                )
            db.flush()

            p_id = det_uuid(f"pairing-{drv_key}")
            if db.get(Pairing, p_id) is None:
                db.add(
                    Pairing(
                        id=p_id,
                        organization_id=o_id,
                        vehicle_id=v_id,
                        driver_id=d_id,
                        code=f"PAIR{pair_counter:02d}",
                        status="PAIRED",
                        expires_at=now_utc + timedelta(days=30),
                        used_at=now_utc - timedelta(days=20),
                        consented_at=now_utc - timedelta(days=20),
                        created_by=o_mgr_id,
                        created_at=now_utc - timedelta(days=20),
                    )
                )
            pair_counter += 1

            c_id = det_uuid(f"consent-{drv_key}")
            if db.get(Consent, c_id) is None:
                db.add(
                    Consent(
                        id=c_id,
                        organization_id=o_id,
                        user_id=d_id,
                        consent_type="data_processing",
                        version="2026-01",
                        location_consent=True,
                        clip_storage_consent=False,
                        accepted_at=now_utc - timedelta(days=20),
                    )
                )

            # Seed 1 historical session & event for Org 2 / Org 3 drivers for multi-tenant isolation tests
            s_id = det_uuid(f"sess-extra-{drv_key}")
            if db.get(SessionModel, s_id) is None:
                s_start = now_utc - timedelta(days=2, hours=4)
                s_end = s_start + timedelta(hours=3)
                db.add(
                    SessionModel(
                        id=s_id,
                        organization_id=o_id,
                        driver_id=d_id,
                        vehicle_id=v_id,
                        status="ended",
                        started_at=s_start,
                        ended_at=s_end,
                        total_driving_sec=10800,
                        warning_count=1,
                        critical_count=0,
                        current_state="OFFLINE",
                        last_heartbeat_at=s_end,
                    )
                )
                db.flush()
                e_id = det_uuid(f"ev-extra-{drv_key}")
                db.add(
                    EventModel(
                        id=e_id,
                        organization_id=o_id,
                        session_id=s_id,
                        driver_id=d_id,
                        vehicle_id=v_id,
                        client_event_id=e_id,
                        type="DROWSINESS",
                        level="WARNING",
                        status="CLOSED",
                        state="DROWSINESS_SIGNS",
                        risk_score=0.81,
                        started_at=s_start + timedelta(hours=1),
                        closed_at=s_start + timedelta(hours=1, seconds=5),
                        duration_sec=5,
                        delayed=False,
                        captured_at=s_start + timedelta(hours=1, seconds=5),
                        received_at=s_start + timedelta(hours=1, seconds=6),
                    )
                )
    db.flush()

    # 5. 30 Days of Sessions, Events (peaked around 2:00-4:00 AM VN time), Heartbeats, Locations, RestBreaks, Usage, RiskScores
    rng = random.Random(20261110)
    sessions_created = 0
    events_created = 0
    heartbeats_created = 0

    base_day_vn = now_vn.replace(hour=0, minute=0, second=0, microsecond=0)
    peak_hours = [2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4, 1, 5, 13, 14, 22, 23]

    for day_offset in range(30, 0, -1):
        day_vn = base_day_vn - timedelta(days=day_offset)

        for drv_idx, (d_id, v_id, _full_name) in enumerate(driver_records):
            if (day_offset + drv_idx) % 4 == 0:
                continue

            sess_id = det_uuid(f"sess-d{day_offset}-u{drv_idx}")
            if db.get(SessionModel, sess_id) is not None:
                continue

            start_minute = rng.randint(0, 50)
            sess_start_vn = day_vn.replace(hour=1, minute=start_minute)
            driving_sec = rng.randint(3 * 3600 + 1800, 5 * 3600 + 1800)
            sess_end_vn = sess_start_vn + timedelta(seconds=driving_sec)

            sess_start_utc = sess_start_vn.astimezone(timezone.utc)
            sess_end_utc = sess_end_vn.astimezone(timezone.utc)

            num_events = rng.choices([0, 1, 2, 3], weights=[20, 45, 25, 10])[0]
            warn_cnt = 0
            crit_cnt = 0

            sess = SessionModel(
                id=sess_id,
                organization_id=ORG_ID,
                driver_id=d_id,
                vehicle_id=v_id,
                status="ended",
                started_at=sess_start_utc,
                ended_at=sess_end_utc,
                total_driving_sec=driving_sec,
                continuous_driving_sec=0,
                unavailable_sec=rng.randint(0, 180),
                warning_count=0,
                critical_count=0,
                current_state="OFFLINE",
                last_heartbeat_at=sess_end_utc,
                app_version="3.0.0",
                device_model="Samsung A15",
            )
            db.add(sess)
            db.flush()
            sessions_created += 1

            for ev_idx in range(num_events):
                ev_id = det_uuid(f"ev-d{day_offset}-u{drv_idx}-e{ev_idx}")
                hour_vn = rng.choice(peak_hours)
                minute_vn = rng.randint(0, 58)
                second_vn = rng.randint(0, 58)
                ev_time_vn = day_vn.replace(
                    hour=hour_vn, minute=minute_vn, second=second_vn
                )
                ev_time_utc = ev_time_vn.astimezone(timezone.utc)

                ev_type = rng.choices(
                    ["DROWSINESS", "LONG_DRIVING", "DISCONNECTED"],
                    weights=[78, 14, 8],
                )[0]
                if ev_type == "DROWSINESS":
                    ev_level = rng.choices(["WARNING", "CRITICAL"], weights=[65, 35])[0]
                    ev_state = (
                        "CRITICAL" if ev_level == "CRITICAL" else "DROWSINESS_SIGNS"
                    )
                    risk_score = (
                        round(rng.uniform(0.88, 0.98), 2)
                        if ev_level == "CRITICAL"
                        else round(rng.uniform(0.72, 0.85), 2)
                    )
                    duration_sec = rng.randint(3, 12)
                elif ev_type == "LONG_DRIVING":
                    ev_level = rng.choices(["WARNING", "CRITICAL"], weights=[75, 25])[0]
                    ev_state = "NORMAL"
                    risk_score = 0.65
                    duration_sec = 7200 if ev_level == "WARNING" else 10800
                else:
                    ev_level = "WARNING"
                    ev_state = "DISCONNECTED"
                    risk_score = None
                    duration_sec = rng.randint(65, 180)

                if ev_level == "CRITICAL":
                    crit_cnt += 1
                else:
                    warn_cnt += 1

                is_acked = rng.random() < 0.8
                ack_by = disp_id if is_acked else None
                ack_by_name = "Trần Thị Trực Ban" if is_acked else None
                ack_at = (
                    (ev_time_utc + timedelta(minutes=rng.randint(1, 5)))
                    if is_acked
                    else None
                )
                note = (
                    "Đã gọi điện nhắc tài xế vào trạm dừng nghỉ" if is_acked else None
                )

                ev_lat = round(20.95 - (drv_idx + 1) * 0.11 - ev_idx * 0.02, 5)
                ev_lng = round(105.85 + (drv_idx + 1) * 0.025 + ev_idx * 0.01, 5)

                ev = EventModel(
                    id=ev_id,
                    organization_id=ORG_ID,
                    session_id=sess_id,
                    driver_id=d_id,
                    vehicle_id=v_id,
                    client_event_id=ev_id,
                    type=ev_type,
                    level=ev_level,
                    status="CLOSED",
                    state=ev_state,
                    risk_score=risk_score,
                    started_at=ev_time_utc,
                    closed_at=ev_time_utc + timedelta(seconds=duration_sec),
                    duration_sec=duration_sec,
                    delayed=False,
                    captured_at=ev_time_utc + timedelta(seconds=duration_sec),
                    received_at=ev_time_utc + timedelta(seconds=duration_sec + 1),
                    ack_by=ack_by,
                    ack_by_name=ack_by_name,
                    ack_at=ack_at,
                    note=note,
                    lat=ev_lat,
                    lng=ev_lng,
                )
                db.add(ev)
                events_created += 1

            sess.warning_count = warn_cnt
            sess.critical_count = crit_cnt

            if day_offset <= 7:
                usage_id = det_uuid(f"usage-d{day_offset}-u{drv_idx}")
                if db.get(AppUsageDaily, usage_id) is None:
                    db.add(
                        AppUsageDaily(
                            id=usage_id,
                            organization_id=ORG_ID,
                            driver_id=d_id,
                            usage_date=day_vn.date(),
                            monitored_minutes=driving_sec // 60,
                            monitoring_off_count=drv_idx % 3,
                            alerts_total=max(1, num_events),
                            alerts_false=1 if (num_events > 1 and drv_idx % 2 == 0) else 0,
                        )
                    )

                rb_id = det_uuid(f"rb-d{day_offset}-u{drv_idx}")
                if db.get(RestBreak, rb_id) is None:
                    db.add(
                        RestBreak(
                            id=rb_id,
                            organization_id=ORG_ID,
                            driver_id=d_id,
                            session_id=sess_id,
                            drive_min_before=180,
                            reminder_sent_at=sess_start_utc + timedelta(minutes=165),
                            suggested_stop_id=stop_ids[drv_idx % len(stop_ids)],
                            started_at=sess_start_utc + timedelta(minutes=180),
                            ended_at=sess_start_utc + timedelta(minutes=200),
                        )
                    )

            if day_offset <= 5:
                for hb_i in range(4):
                    hb_time = sess_start_utc + timedelta(minutes=hb_i * 30 + 5)
                    qual = rng.choices(
                        ["GOOD", "LOW_LIGHT", "TOO_DARK", "BLURRY"],
                        weights=[80, 10, 6, 4],
                    )[0]
                    hb_state = (
                        "MONITORING_UNAVAILABLE" if qual == "TOO_DARK" else "NORMAL"
                    )
                    hb_lat = round(20.95 - (drv_idx + 1) * 0.11 - hb_i * 0.03, 5)
                    hb_lng = round(105.85 + (drv_idx + 1) * 0.025 + hb_i * 0.01, 5)
                    db.add(
                        HeartbeatModel(
                            organization_id=ORG_ID,
                            session_id=sess_id,
                            driver_id=d_id,
                            state=hb_state,
                            image_quality=qual,
                            vehicle_moving=True,
                            ts=hb_time,
                            ear=0.29,
                            fps=10.0,
                            battery_pct=85 - hb_i * 3,
                            lat=hb_lat,
                            lng=hb_lng,
                            speed_kmh=65.0,
                        )
                    )
                    db.add(
                        LocationModel(
                            organization_id=ORG_ID,
                            session_id=sess_id,
                            vehicle_id=v_id,
                            driver_id=d_id,
                            ts=hb_time,
                            lat=hb_lat,
                            lng=hb_lng,
                            speed_kmh=65.0,
                            heading_deg=175.0,
                        )
                    )
                    heartbeats_created += 1

    # 6. Weekly Risk Scores for Org 1 drivers
    week_start = (now_vn - timedelta(days=now_vn.weekday())).date()
    week_end = week_start + timedelta(days=6)
    for drv_idx, (d_id, _v_id, _fn) in enumerate(driver_records):
        rs_id = det_uuid(f"risk-weekly-{drv_idx}")
        if db.get(RiskScore, rs_id) is None:
            sc = 25 + drv_idx * 14
            r_lvl = "high" if sc >= 60 else ("medium" if sc >= 35 else "low")
            db.add(
                RiskScore(
                    id=rs_id,
                    organization_id=ORG_ID,
                    driver_id=d_id,
                    period_type="weekly",
                    period_start=week_start,
                    period_end=week_end,
                    score=sc,
                    risk_level=r_lvl,
                    events_count=3 + drv_idx,
                    drowsy_events=2 + drv_idx,
                    distraction_events=1,
                    driving_hours=Decimal("24.5"),
                )
            )

    # Seed 1 sample API key & webhook & report & push token & audit log for completeness
    ak_id = det_uuid("seed-api-key-1")
    if db.get(ApiKey, ak_id) is None:
        db.add(
            ApiKey(
                id=ak_id,
                organization_id=ORG_ID,
                name="Tích hợp GPS #1",
                key_prefix="pd_dev_1",
                key_hash=hashlib.sha256(b"seed-dev-api-key-1").hexdigest(),
                scopes=["events:read", "vehicles:read"],
            )
        )
    wh_id = det_uuid("seed-webhook-1")
    if db.get(Webhook, wh_id) is None:
        db.add(
            Webhook(
                id=wh_id,
                organization_id=ORG_ID,
                url="https://example.com/webhook/1",
                secret_hash=hashlib.sha256(b"seed-webhook-secret-1").hexdigest(),
                events=["alert.created", "alert.escalated"],
                is_active=True,
            )
        )
    rep_id = det_uuid("seed-report-1")
    if db.get(ReportModel, rep_id) is None:
        db.add(
            ReportModel(
                id=rep_id,
                organization_id=ORG_ID,
                report_type="weekly",
                file_format="pdf",
                period_start=week_start - timedelta(days=7),
                period_end=week_end - timedelta(days=7),
                status="ready",
                storage_path="reports/org1/report-001.pdf",
                created_by=mgr_id,
            )
        )
    pt_id = det_uuid("seed-push-mgr")
    if db.get(PushToken, pt_id) is None:
        db.add(
            PushToken(
                id=pt_id,
                organization_id=ORG_ID,
                user_id=mgr_id,
                fcm_token="dev-fcm-token-mgr-001",
                platform="web",
            )
        )
    if sessions_created > 0:
        db.add(
            AuditLog(
                organization_id=ORG_ID,
                actor_id=mgr_id,
                action="seed_initialized",
                entity="organization",
                entity_id=ORG_ID,
                ip="127.0.0.1",
                meta={"note": "dev_seed"},
            )
        )
        # Seed 1 sample escalation linked to an existing Org 2 event if present
        ev_extra = db.get(EventModel, det_uuid("ev-extra-drv-6"))
        if ev_extra is not None:
            esc_id = det_uuid("seed-esc-1")
            if db.get(Escalation, esc_id) is None:
                db.add(
                    Escalation(
                        id=esc_id,
                        organization_id=ORG_2_ID,
                        event_id=ev_extra.id,
                        policy_id=det_uuid("pol-sao-viet-1"),
                        notified_user_id=det_uuid("user-dispatcher-2"),
                        channel="push",
                        status="sent",
                    )
                )

    db.commit()
    return {
        "organizations": 3,
        "users": 20,
        "vehicles": 14,
        "rest_stops": 20,
        "sessions_created": sessions_created,
        "events_created": events_created,
        "heartbeats_created": heartbeats_created,
    }
