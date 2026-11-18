from datetime import datetime, timedelta, timezone
import random
from uuid import NAMESPACE_DNS, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ..core.security import hash_password
from ..models.models import (
    EventModel,
    HeartbeatModel,
    Organization,
    OrgSettings,
    Pairing,
    SessionModel,
    User,
    Vehicle,
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SEED_NS = uuid5(NAMESPACE_DNS, "predrive-ai.m3.seed.2026")


def det_uuid(name: str) -> str:
    return str(uuid5(SEED_NS, name))


ORG_ID = "11111111-1111-4111-8111-111111111111"

VEHICLES_SEED = [
    ("veh-1", "51B-123.45", "51B-123.45 - Giường nằm 40 chỗ"),
    ("veh-2", "51B-234.56", "51B-234.56 - Limousine 34 phòng"),
    ("veh-3", "51B-345.67", "51B-345.67 - Giường nằm 40 chỗ"),
    ("veh-4", "51C-456.78", "51C-456.78 - Xe tải đường dài 15T"),
    ("veh-5", "51C-567.89", "51C-567.89 - Đầu kéo Container"),
]

DRIVERS_SEED = [
    ("drv-1", "driver1", "Nguyễn Văn An", "0901234501", "veh-1"),
    ("drv-2", "driver2", "Trần Minh Bình", "0901234502", "veh-2"),
    ("drv-3", "driver3", "Lê Hoàng Cường", "0901234503", "veh-3"),
    ("drv-4", "driver4", "Phạm Quốc Dũng", "0901234504", "veh-4"),
    ("drv-5", "driver5", "Võ Thanh Hải", "0901234505", "veh-5"),
]


def seed_database(db: Session, ref_now_utc: datetime | None = None) -> dict[str, int]:
    """Idempotently seed 1 organization, 1 manager, 1 dispatcher, 5 Vietnamese drivers,
    5 vehicles, and 30 days of historical sessions/events concentrated around 02:00-04:00 AM VN time.
    """
    now_utc = ref_now_utc or datetime.now(timezone.utc)
    now_vn = now_utc.astimezone(VN_TZ)

    # 1. Organization
    org = db.get(Organization, ORG_ID)
    if org is None:
        org = Organization(
            id=ORG_ID,
            name="Nhà xe Phương Trang - Chi nhánh Miền Nam",
            created_at=now_utc - timedelta(days=60),
        )
        db.add(org)
        db.flush()

    # 2. Settings
    settings = db.get(OrgSettings, ORG_ID)
    if settings is None:
        settings = OrgSettings(
            organization_id=ORG_ID,
            continuous_warn_sec=7200,
            continuous_critical_sec=10800,
            min_rest_min=15,
            share_location=False,
            heartbeat_interval_sec=30,
            updated_at=now_utc,
        )
        db.add(settings)
        db.flush()

    # 3. Vehicles
    vehicle_ids: dict[str, str] = {}
    for key, plate, v_name in VEHICLES_SEED:
        v_id = det_uuid(key)
        vehicle_ids[key] = v_id
        veh = db.get(Vehicle, v_id)
        if veh is None:
            veh = Vehicle(
                id=v_id,
                organization_id=ORG_ID,
                plate_number=plate,
                name=v_name,
                created_at=now_utc - timedelta(days=45),
            )
            db.add(veh)
    db.flush()

    # Pre-compute password hashes once for fast seeding
    mgr_hash = hash_password("manager123")
    disp_hash = hash_password("dispatcher123")
    drv_hash = hash_password("driver123")

    # 4. Manager & Dispatcher
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
                vehicle_id=None,
                created_at=now_utc - timedelta(days=45),
            )
        )

    # 5. Drivers (5 Vietnamese drivers) & Pairings
    driver_records: list[tuple[str, str, str]] = []
    for idx, (drv_key, username, full_name, phone, veh_key) in enumerate(DRIVERS_SEED, start=1):
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
                    vehicle_id=v_id,
                    created_at=now_utc - timedelta(days=40),
                )
            )
    db.flush()

    for idx, (drv_key, _username, _full_name, _phone, veh_key) in enumerate(DRIVERS_SEED, start=1):
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
                    expires_at=now_utc + timedelta(days=30),
                    consented_at=now_utc - timedelta(days=35),
                    status="PAIRED",
                    created_at=now_utc - timedelta(days=35),
                )
            )
    db.flush()

    # 6. 30 Days of Sessions, Events (peaked around 2:00-4:00 AM VN time), and Heartbeats
    rng = random.Random(20261110)
    sessions_created = 0
    events_created = 0
    heartbeats_created = 0

    base_day_vn = now_vn.replace(hour=0, minute=0, second=0, microsecond=0)

    # Weighted hour choices in Vietnam local time: heavy concentration in 2, 3, 4 AM
    peak_hours = [2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4, 1, 5, 13, 14, 22, 23]

    for day_offset in range(30, 0, -1):
        day_vn = base_day_vn - timedelta(days=day_offset)

        for drv_idx, (d_id, v_id, _full_name) in enumerate(driver_records):
            # Each driver drives ~22 out of 30 days
            if (day_offset + drv_idx) % 4 == 0:
                continue

            sess_id = det_uuid(f"sess-d{day_offset}-u{drv_idx}")
            if db.get(SessionModel, sess_id) is not None:
                continue

            # Night shift starting around 00:30 - 01:30 VN time, lasting 3.5 to 5.5 hours
            start_minute = rng.randint(0, 50)
            sess_start_vn = day_vn.replace(hour=1, minute=start_minute)
            driving_sec = rng.randint(3 * 3600 + 1800, 5 * 3600 + 1800)
            sess_end_vn = sess_start_vn + timedelta(seconds=driving_sec)

            sess_start_utc = sess_start_vn.astimezone(timezone.utc)
            sess_end_utc = sess_end_vn.astimezone(timezone.utc)

            # Determine number of events in this session (1 to 3 events, weighted by driver)
            num_events = rng.choices([0, 1, 2, 3], weights=[20, 45, 25, 10])[0]
            warn_cnt = 0
            crit_cnt = 0

            sess = SessionModel(
                id=sess_id,
                organization_id=ORG_ID,
                driver_id=d_id,
                vehicle_id=v_id,
                started_at=sess_start_utc,
                ended_at=sess_end_utc,
                total_driving_sec=driving_sec,
                continuous_driving_sec=0,
                unavailable_sec=rng.randint(0, 180),
                warning_count=0,
                critical_count=0,
                current_state="OFFLINE",
                last_heartbeat_at=sess_end_utc,
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
                    ev_state = "CRITICAL" if ev_level == "CRITICAL" else "DROWSINESS_SIGNS"
                    risk_score = round(rng.uniform(0.88, 0.98), 2) if ev_level == "CRITICAL" else round(rng.uniform(0.72, 0.85), 2)
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
                ack_at = (ev_time_utc + timedelta(minutes=rng.randint(1, 5))) if is_acked else None
                note = "Đã gọi điện nhắc tài xế vào trạm dừng nghỉ" if is_acked else None

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
                )
                db.add(ev)
                events_created += 1

            sess.warning_count = warn_cnt
            sess.critical_count = crit_cnt

            # Add sample recent heartbeats for the last 5 days so system-health has realistic metrics
            if day_offset <= 5:
                for hb_i in range(4):
                    hb_time = sess_start_utc + timedelta(minutes=hb_i * 30 + 5)
                    qual = rng.choices(
                        ["GOOD", "LOW_LIGHT", "TOO_DARK", "BLURRY"],
                        weights=[80, 10, 6, 4],
                    )[0]
                    hb_state = "MONITORING_UNAVAILABLE" if qual == "TOO_DARK" else "NORMAL"
                    db.add(
                        HeartbeatModel(
                            organization_id=ORG_ID,
                            session_id=sess_id,
                            driver_id=d_id,
                            state=hb_state,
                            image_quality=qual,
                            vehicle_moving=True,
                            captured_at=hb_time,
                        )
                    )
                    heartbeats_created += 1

    db.commit()
    return {
        "organizations": 1,
        "users": 7,
        "vehicles": 5,
        "sessions_created": sessions_created,
        "events_created": events_created,
        "heartbeats_created": heartbeats_created,
    }
