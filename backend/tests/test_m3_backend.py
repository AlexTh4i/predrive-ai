from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.core import database as db_mod
from app.core.security import hash_password
from app.main import app
from app.models.models import Organization, OrgSettings, User, Vehicle
from app.services.seed import seed_database
from app.services.sse import sse_broker
from app.services.watchdog import check_disconnected_sessions, cleanup_old_telemetry


@pytest.fixture()
def m3_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated SQLite WAL database per test module/function with seed data."""
    db_file = tmp_path / "test_predrive_m3.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("PREDRIVE_ENABLE_WATCHDOG", "0")

    db_mod.reset_engine(db_url)
    db_mod.Base.metadata.create_all(bind=db_mod.engine)
    sse_broker.clear_history()

    with TestClient(app) as client:
        yield client


def auth_headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    res = client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert res.status_code == 200, res.text
    token = res.json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


def test_step1_seed_idempotency_and_2am_4am_peak(m3_client: TestClient):
    # Running seed_database again must not create any duplicate rows
    with db_mod.SessionLocal() as db:
        second_run = seed_database(db)
        assert second_run["sessions_created"] == 0
        assert second_run["events_created"] == 0

    mgr_hdr = auth_headers(m3_client, "manager", "manager123")

    drivers = m3_client.get("/api/v1/drivers", headers=mgr_hdr).json()
    assert len(drivers) == 5

    hourly = m3_client.get("/api/v1/stats/hourly", headers=mgr_hdr).json()
    assert len(hourly) == 24
    by_hour = {item["hour"]: item["warning"] + item["critical"] for item in hourly}
    peak_2_to_4 = by_hour[2] + by_hour[3] + by_hour[4]
    total_all_hours = sum(by_hour.values())
    assert total_all_hours > 50
    # Alerts must be heavily concentrated around 02:00-04:00 AM Vietnam time
    assert peak_2_to_4 > total_all_hours * 0.5


def test_step2_auth_rbac_and_org_isolation(m3_client: TestClient):
    # 1. Invalid login returns standard error structure
    bad_login = m3_client.post(
        "/api/v1/auth/login", json={"username": "manager", "password": "wrong"}
    )
    assert bad_login.status_code == 401
    assert "error" in bad_login.json()
    assert bad_login.json()["error"]["code"] == "INVALID_CREDENTIALS"

    mgr_hdr = auth_headers(m3_client, "manager", "manager123")
    disp_hdr = auth_headers(m3_client, "dispatcher", "dispatcher123")
    drv1_hdr = auth_headers(m3_client, "driver1", "driver123")
    drv2_hdr = auth_headers(m3_client, "driver2", "driver123")

    drv1_me = m3_client.get("/api/v1/auth/me", headers=drv1_hdr).json()
    drv2_me = m3_client.get("/api/v1/auth/me", headers=drv2_hdr).json()
    assert drv1_me["role"] == "driver"

    # 2. Driver cannot read other driver's profile, stats, or web endpoints
    assert (
        m3_client.get(f"/api/v1/drivers/{drv2_me['id']}", headers=drv1_hdr).status_code
        == 403
    )
    assert (
        m3_client.get(
            f"/api/v1/drivers/{drv2_me['id']}/stats", headers=drv1_hdr
        ).status_code
        == 403
    )
    assert m3_client.get("/api/v1/drivers", headers=drv1_hdr).status_code == 403
    assert m3_client.get("/api/v1/live", headers=drv1_hdr).status_code == 403
    assert m3_client.get("/api/v1/events", headers=drv1_hdr).status_code == 403

    # Driver 1 opens a session; Driver 2 cannot post heartbeat or events to Driver 1's session
    sess_id = str(uuid4())
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    res_s = m3_client.post(
        "/api/v1/sessions",
        json={"sessionId": sess_id, "startedAt": now_iso},
        headers=drv1_hdr,
    )
    assert res_s.status_code == 200
    assert (
        m3_client.post(
            f"/api/v1/sessions/{sess_id}/heartbeat",
            json={
                "state": "NORMAL",
                "imageQuality": "GOOD",
                "continuousDrivingSec": 60,
                "vehicleMoving": True,
                "capturedAt": now_iso,
            },
            headers=drv2_hdr,
        ).status_code
        == 403
    )

    # 3. Dispatcher can read settings, live, events, and ack, but CANNOT modify settings or create drivers/pairing codes
    assert m3_client.get("/api/v1/settings", headers=disp_hdr).status_code == 200
    assert (
        m3_client.put(
            "/api/v1/settings",
            json={
                "continuousWarnSec": 7200,
                "continuousCriticalSec": 10800,
                "restResetMin": 15,
                "shareLocation": True,
                "heartbeatIntervalSec": 30,
            },
            headers=disp_hdr,
        ).status_code
        == 403
    )
    assert m3_client.post("/api/v1/pairing-codes", headers=disp_hdr).status_code == 403
    assert (
        m3_client.post(
            "/api/v1/drivers",
            json={"fullName": "Test", "phone": "0999888777"},
            headers=disp_hdr,
        ).status_code
        == 403
    )

    # Manager CAN update settings
    assert (
        m3_client.put(
            "/api/v1/settings",
            json={
                "continuousWarnSec": 7200,
                "continuousCriticalSec": 10800,
                "restResetMin": 15,
                "shareLocation": True,
                "heartbeatIntervalSec": 30,
            },
            headers=mgr_hdr,
        ).status_code
        == 200
    )

    # 4. Organization A cannot see Organization B data
    org_b_id = str(uuid4())
    drv_b_id = str(uuid4())
    mgr_b_id = str(uuid4())
    with db_mod.SessionLocal() as db:
        db.add(Organization(id=org_b_id, name="Nhà xe Tổ chức B"))
        db.flush()
        db.add(OrgSettings(organization_id=org_b_id))
        db.add(
            User(
                id=mgr_b_id,
                organization_id=org_b_id,
                username="manager_b",
                password_hash=hash_password("pass123"),
                role="manager",
                full_name="Quản lý B",
                phone="0911222333",
            )
        )
        db.add(
            User(
                id=drv_b_id,
                organization_id=org_b_id,
                username="driver_b",
                password_hash=hash_password("pass123"),
                role="driver",
                full_name="Tài xế B",
                phone="0911222444",
            )
        )
        db.commit()

    mgr_b_hdr = auth_headers(m3_client, "manager_b", "pass123")

    # Org A manager cannot see Org B driver
    org_a_drivers = m3_client.get("/api/v1/drivers", headers=mgr_hdr).json()
    assert all(d["id"] != drv_b_id for d in org_a_drivers)
    assert (
        m3_client.get(f"/api/v1/drivers/{drv_b_id}", headers=mgr_hdr).status_code
        == 404
    )

    # Org B manager only sees Org B driver (1 driver) and 0 Org A events
    org_b_drivers = m3_client.get("/api/v1/drivers", headers=mgr_b_hdr).json()
    assert len(org_b_drivers) == 1
    assert org_b_drivers[0]["id"] == drv_b_id
    org_b_events = m3_client.get("/api/v1/events", headers=mgr_b_hdr).json()
    assert org_b_events["total"] == 0


def test_step3_idempotency_out_of_order_events_and_delayed(m3_client: TestClient):
    drv_hdr = auth_headers(m3_client, "driver1", "driver123")
    disp_hdr = auth_headers(m3_client, "dispatcher", "dispatcher123")
    me = m3_client.get("/api/v1/auth/me", headers=drv_hdr).json()
    org_id = me["organizationId"]

    now = datetime.now(timezone.utc)
    sess_id = str(uuid4())

    # 1. Idempotent session creation
    r1 = m3_client.post(
        "/api/v1/sessions",
        json={"sessionId": sess_id, "startedAt": now.isoformat()},
        headers=drv_hdr,
    )
    r2 = m3_client.post(
        "/api/v1/sessions",
        json={"sessionId": sess_id, "startedAt": now.isoformat()},
        headers=drv_hdr,
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["sessionId"] == sess_id == r2.json()["sessionId"]

    # 2. Out-of-order & duplicate event upsert (level only increases, status only advances)
    ev_id = str(uuid4())
    t0 = now - timedelta(seconds=10)
    t1 = now - timedelta(seconds=5)
    t2 = now - timedelta(seconds=2)

    # Suppose CLOSED + CRITICAL arrives first
    res_closed = m3_client.post(
        f"/api/v1/sessions/{sess_id}/events",
        json={
            "eventId": ev_id,
            "type": "DROWSINESS",
            "level": "CRITICAL",
            "status": "CLOSED",
            "state": "CRITICAL",
            "riskScore": 0.95,
            "startedAt": t0.isoformat(),
            "durationSec": 8,
            "capturedAt": t2.isoformat(),
        },
        headers=drv_hdr,
    )
    assert res_closed.status_code == 200
    assert res_closed.json()["delayed"] is False

    # Then an older OPEN + WARNING retry arrives out-of-order
    res_open = m3_client.post(
        f"/api/v1/sessions/{sess_id}/events",
        json={
            "eventId": ev_id,
            "type": "DROWSINESS",
            "level": "WARNING",
            "status": "OPEN",
            "state": "DROWSINESS_SIGNS",
            "riskScore": 0.75,
            "startedAt": t0.isoformat(),
            "durationSec": 2,
            "capturedAt": t0.isoformat(),
        },
        headers=drv_hdr,
    )
    assert res_open.status_code == 200
    merged = res_open.json()
    # Level must stay CRITICAL, status must stay CLOSED, durationSec must stay 8, riskScore 0.95
    assert merged["level"] == "CRITICAL"
    assert merged["status"] == "CLOSED"
    assert merged["durationSec"] == 8
    assert merged["riskScore"] == 0.95

    # Then ESCALATED arrives out-of-order
    res_esc = m3_client.post(
        f"/api/v1/sessions/{sess_id}/events",
        json={
            "eventId": ev_id,
            "type": "DROWSINESS",
            "level": "CRITICAL",
            "status": "ESCALATED",
            "state": "CRITICAL",
            "riskScore": 0.90,
            "startedAt": t0.isoformat(),
            "durationSec": 5,
            "capturedAt": t1.isoformat(),
        },
        headers=drv_hdr,
    )
    assert res_esc.json()["status"] == "CLOSED"
    assert res_esc.json()["level"] == "CRITICAL"

    # 3. Delayed offline event (> 60s old) via batch endpoint must set delayed=True and NOT emit SSE `alert`
    sse_broker.clear_history(org_id)
    delayed_ev_id = str(uuid4())
    old_time = now - timedelta(seconds=180)
    batch_res = m3_client.post(
        f"/api/v1/sessions/{sess_id}/events/batch",
        json={
            "events": [
                {
                    "eventId": delayed_ev_id,
                    "type": "DROWSINESS",
                    "level": "WARNING",
                    "status": "CLOSED",
                    "state": "DROWSINESS_SIGNS",
                    "riskScore": 0.82,
                    "startedAt": (old_time - timedelta(seconds=5)).isoformat(),
                    "durationSec": 5,
                    "capturedAt": old_time.isoformat(),
                }
            ]
        },
        headers=drv_hdr,
    )
    assert batch_res.status_code == 200
    batch_item = batch_res.json()["items"][0]
    assert batch_item["id"] == delayed_ev_id
    assert batch_item["delayed"] is True

    # Verify SSE broker did NOT emit an `alert` event for the delayed event
    published_alerts = [
        m for m in sse_broker.get_recent_messages(org_id) if m["event"] == "alert"
    ]
    assert len(published_alerts) == 0

    # Verify delayed event IS saved in history (/api/v1/events)
    ev_list = m3_client.get(
        f"/api/v1/events?driverId={me['id']}&pageSize=10", headers=disp_hdr
    ).json()
    ids_in_history = {item["id"]: item for item in ev_list["items"]}
    assert delayed_ev_id in ids_in_history
    assert ids_in_history[delayed_ev_id]["delayed"] is True
    assert ev_id in ids_in_history


def test_step4_and_step5_web_endpoints_div_by_zero_and_sse(m3_client: TestClient):
    mgr_hdr = auth_headers(m3_client, "manager", "manager123")
    disp_hdr = auth_headers(m3_client, "dispatcher", "dispatcher123")

    # 1. Create a brand new driver with 0 driving hours to verify division-by-zero handling
    new_drv_res = m3_client.post(
        "/api/v1/drivers",
        json={
            "fullName": "Đặng Văn Mới",
            "phone": "0905556677",
            "username": "driver_zero",
            "password": "driver123",
            "vehicleName": "51D-999.99 - Xe khách 29 chỗ",
        },
        headers=mgr_hdr,
    )
    assert new_drv_res.status_code == 201
    new_drv = new_drv_res.json()

    zero_stats = m3_client.get(
        f"/api/v1/drivers/{new_drv['id']}/stats", headers=disp_hdr
    ).json()
    assert zero_stats["totalDrivingSec"] == 0
    assert zero_stats["alertCount"] == 0
    assert zero_stats["alertsPerDrivingHour"] == 0.0
    assert len(zero_stats["hourly"]) == 24

    # 2. Test pairing code flow
    pair_code_res = m3_client.post(
        "/api/v1/pairing-codes",
        json={"vehicleId": new_drv["vehicleId"], "expiresInMinutes": 30},
        headers=mgr_hdr,
    )
    assert pair_code_res.status_code == 200
    code = pair_code_res.json()["code"]

    new_drv_hdr = auth_headers(m3_client, "driver_zero", "driver123")
    pair_res = m3_client.post(
        "/api/v1/auth/pair", json={"code": code}, headers=new_drv_hdr
    )
    assert pair_res.status_code == 200
    assert "51D-999.99" in pair_res.json()["vehicleName"]

    # 3. Test SSE stream (/api/v1/live/stream)
    sse_res = m3_client.get(
        "/api/v1/live/stream?max_events=2",
        headers=disp_hdr,
    )
    assert sse_res.status_code == 200
    assert "text/event-stream" in sse_res.headers["content-type"]
    assert "event: driver_state" in sse_res.text

    # 4. Test event ack
    events_page = m3_client.get("/api/v1/events?acked=false&pageSize=5", headers=disp_hdr).json()
    assert events_page["total"] > 0
    target_ev = events_page["items"][0]

    ack_res = m3_client.post(
        f"/api/v1/events/{target_ev['id']}/ack",
        json={"note": "Đã gọi Zalo nhắc tài xế nghỉ tại trạm Cai Lậy"},
        headers=disp_hdr,
    )
    assert ack_res.status_code == 200
    acked_ev = ack_res.json()
    assert acked_ev["ackBy"] == "Trần Thị Trực Ban"
    assert acked_ev["ackAt"] is not None
    assert acked_ev["note"] == "Đã gọi Zalo nhắc tài xế nghỉ tại trạm Cai Lậy"

    # 5. Test ranking and system-health
    ranking = m3_client.get("/api/v1/stats/ranking", headers=disp_hdr).json()
    assert len(ranking) >= 6
    health = m3_client.get("/api/v1/stats/system-health", headers=disp_hdr).json()
    assert 0.0 <= health["tooDarkRate"] <= 1.0
    assert 0.0 <= health["unavailableRate"] <= 1.0
    assert isinstance(health["disconnectedCount"], int)


def test_step6_heartbeat_watchdog_disconnect_and_auto_recovery(m3_client: TestClient):
    drv_hdr = auth_headers(m3_client, "driver3", "driver123")
    disp_hdr = auth_headers(m3_client, "dispatcher", "dispatcher123")
    me = m3_client.get("/api/v1/auth/me", headers=drv_hdr).json()

    now = datetime.now(timezone.utc)
    sess_id = str(uuid4())

    # Open session and send initial heartbeat
    m3_client.post(
        "/api/v1/sessions",
        json={"sessionId": sess_id, "startedAt": now.isoformat()},
        headers=drv_hdr,
    )
    m3_client.post(
        f"/api/v1/sessions/{sess_id}/heartbeat",
        json={
            "state": "NORMAL",
            "imageQuality": "GOOD",
            "continuousDrivingSec": 120,
            "vehicleMoving": True,
            "capturedAt": now.isoformat(),
        },
        headers=drv_hdr,
    )

    # Simulate time advancing by 65 seconds (> 2 * 30s heartbeatIntervalSec)
    future_time = now + timedelta(seconds=65)
    with db_mod.SessionLocal() as db:
        alerts = check_disconnected_sessions(db, now_utc=future_time)
        assert any(a.sessionId == sess_id and a.type == "DISCONNECTED" for a in alerts)

    # Verify /live shows state == DISCONNECTED
    live_list = m3_client.get("/api/v1/live", headers=disp_hdr).json()
    drv_live = next(item for item in live_list if item["driverId"] == me["id"])
    assert drv_live["state"] == "DISCONNECTED"

    # Now driver sends a new heartbeat -> must automatically recover to NORMAL!
    recovery_time = datetime.now(timezone.utc)
    hb_res = m3_client.post(
        f"/api/v1/sessions/{sess_id}/heartbeat",
        json={
            "state": "NORMAL",
            "imageQuality": "GOOD",
            "continuousDrivingSec": 185,
            "vehicleMoving": True,
            "capturedAt": recovery_time.isoformat(),
        },
        headers=drv_hdr,
    )
    assert hb_res.status_code == 200
    assert hb_res.json()["state"] == "NORMAL"

    live_after = m3_client.get("/api/v1/live", headers=disp_hdr).json()
    drv_live_after = next(item for item in live_after if item["driverId"] == me["id"])
    assert drv_live_after["state"] == "NORMAL"

    # End session cleanly
    end_res = m3_client.post(
        f"/api/v1/sessions/{sess_id}/end",
        json={
            "endedAt": (recovery_time + timedelta(seconds=10)).isoformat(),
            "summary": {
                "totalDrivingSec": 195,
                "warningCount": 1,
                "criticalCount": 0,
                "unavailableSec": 0,
            },
        },
        headers=drv_hdr,
    )
    assert end_res.status_code == 200
    assert end_res.json()["endedAt"] is not None

    # Test telemetry cleanup
    with db_mod.SessionLocal() as db:
        deleted = cleanup_old_telemetry(
            db, now_utc=now + timedelta(days=30), retention_days=7
        )
        assert deleted >= 1


def test_step7_simulate_driver_and_openapi_contract(m3_client: TestClient):
    from scripts.simulate_driver import run_simulation

    sim_out = run_simulation(m3_client, username="driver2", password="driver123", step_delay=0.0)
    assert sim_out["endedSession"] is not None
    assert sim_out["endedSession"]["totalDrivingSec"] == 1800
    assert sim_out["liveCount"] == 5

    # Verify OpenAPI schema contains all required M3 endpoints
    openapi = m3_client.get("/openapi.json").json()
    paths = openapi["paths"]
    expected_paths = [
        "/api/v1/auth/login",
        "/api/v1/auth/me",
        "/api/v1/auth/pair",
        "/api/v1/sessions",
        "/api/v1/sessions/{id}/events",
        "/api/v1/sessions/{id}/events/batch",
        "/api/v1/sessions/{id}/heartbeat",
        "/api/v1/sessions/{id}/end",
        "/api/v1/live",
        "/api/v1/live/stream",
        "/api/v1/events",
        "/api/v1/events/{id}/ack",
        "/api/v1/drivers",
        "/api/v1/drivers/{id}",
        "/api/v1/drivers/{id}/stats",
        "/api/v1/stats/hourly",
        "/api/v1/stats/ranking",
        "/api/v1/stats/system-health",
        "/api/v1/settings",
        "/api/v1/pairing-codes",
    ]
    for p in expected_paths:
        assert p in paths, f"Missing OpenAPI path: {p}"

