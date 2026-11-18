from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest


def _setup_test_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.core import database as db_mod
    from app.main import app
    from app.services.rate_limiter import rate_limiter
    from app.services.sse import sse_broker

    db_file = tmp_path / "p3_test.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("PREDRIVE_ENABLE_WATCHDOG", "0")
    monkeypatch.setenv("PREDRIVE_ENABLE_LEGACY_AI", "0")
    monkeypatch.setenv("ENV", "development")

    db_mod.reset_engine(db_url)
    db_mod.Base.metadata.create_all(bind=db_mod.engine)
    rate_limiter.reset()
    sse_broker.clear_history()
    return app


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_p3_1_gps_locations_live_map_trail_and_event_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app = _setup_test_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        mgr_res = client.post(
            "/api/v1/auth/login", json={"username": "manager", "password": "manager123"}
        )
        assert mgr_res.status_code == 200
        mgr_token = mgr_res.json()["accessToken"]

        mgr2_res = client.post(
            "/api/v1/auth/login", json={"username": "manager2", "password": "manager123"}
        )
        assert mgr2_res.status_code == 200
        mgr2_token = mgr2_res.json()["accessToken"]

        # Enable shareLocation + configurable locationIntervalSec in Org 1 settings
        cur_settings = client.get("/api/v1/settings", headers=_auth(mgr_token)).json()
        cur_settings["shareLocation"] = True
        cur_settings["locationIntervalSec"] = 20
        put_res = client.put("/api/v1/settings", json=cur_settings, headers=_auth(mgr_token))
        assert put_res.status_code == 200
        assert put_res.json()["shareLocation"] is True
        assert put_res.json()["locationIntervalSec"] == 20

        # Login driver1 and ensure locationConsent = True
        drv_res = client.post(
            "/api/v1/auth/login", json={"username": "driver1", "password": "driver123"}
        )
        assert drv_res.status_code == 200
        drv_token = drv_res.json()["accessToken"]
        drv_id = drv_res.json()["user"]["id"]

        consent_res = client.post(
            "/api/v1/auth/consent",
            json={"version": "2026-01", "locationConsent": True, "clipStorageConsent": False},
            headers=_auth(drv_token),
        )
        assert consent_res.status_code == 200

        sess_id = str(uuid4())
        now = datetime.now(timezone.utc)
        s_res = client.post(
            "/api/v1/sessions",
            json={"sessionId": sess_id, "startedAt": (now - timedelta(minutes=10)).isoformat()},
            headers=_auth(drv_token),
        )
        assert s_res.status_code == 200
        assert s_res.json()["settings"]["locationIntervalSec"] == 20

        # Driver app sends moving GPS samples along QL1A
        loc_res = client.post(
            f"/api/v1/sessions/{sess_id}/locations",
            json={
                "points": [
                    {
                        "lat": 10.7769,
                        "lng": 106.7009,
                        "speedKmh": 62.5,
                        "headingDeg": 45.0,
                        "at": (now - timedelta(minutes=4)).isoformat(),
                    },
                    {
                        "lat": 10.7905,
                        "lng": 106.7150,
                        "speedKmh": 68.0,
                        "headingDeg": 48.0,
                        "at": (now - timedelta(minutes=2)).isoformat(),
                    },
                ]
            },
            headers=_auth(drv_token),
        )
        assert loc_res.status_code == 200
        assert loc_res.json()["accepted"] == 2
        assert loc_res.json()["shareLocationEnabled"] is True

        # Driver triggers a CRITICAL drowsiness event with exact route coordinates
        ev_id = str(uuid4())
        ev_res = client.post(
            f"/api/v1/sessions/{sess_id}/events",
            json={
                "eventId": ev_id,
                "type": "DROWSINESS",
                "level": "CRITICAL",
                "status": "ESCALATED",
                "state": "CRITICAL",
                "riskScore": 0.95,
                "startedAt": (now - timedelta(seconds=15)).isoformat(),
                "durationSec": 4,
                "capturedAt": now.isoformat(),
                "lat": 10.8051,
                "lng": 106.7302,
                "speedKmh": 70.2,
                "headingDeg": 50.0,
            },
            headers=_auth(drv_token),
        )
        assert ev_res.status_code == 200
        ev_body = ev_res.json()
        assert ev_body["lat"] == pytest.approx(10.8051)
        assert ev_body["lng"] == pytest.approx(106.7302)

        # Admin Web fetches live vehicle positions
        live_locs = client.get("/api/v1/locations/live", headers=_auth(mgr_token))
        assert live_locs.status_code == 200
        drv1_live = next(x for x in live_locs.json() if x["driverId"] == drv_id)
        assert drv1_live["lat"] == pytest.approx(10.8051)
        assert drv1_live["lng"] == pytest.approx(106.7302)
        assert drv1_live["speedKmh"] == pytest.approx(70.2)

        # Admin Web fetches route trail + alert pins for this session
        trail_res = client.get(
            f"/api/v1/locations/trail?sessionId={sess_id}",
            headers=_auth(mgr_token),
        )
        assert trail_res.status_code == 200
        trail = trail_res.json()
        assert len(trail["points"]) == 3
        assert len(trail["alerts"]) == 1
        assert trail["alerts"][0]["eventId"] == ev_body["id"]
        assert trail["alerts"][0]["lat"] == pytest.approx(10.8051)
        assert any(pt["eventId"] == ev_body["id"] for pt in trail["points"])

        # Cross-tenant check: Org 2 manager cannot view Org 1's session trail
        cross_res = client.get(
            f"/api/v1/locations/trail?sessionId={sess_id}",
            headers=_auth(mgr2_token),
        )
        assert cross_res.status_code == 404


def test_p3_3_multi_level_alerts_and_dynamic_settings_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from app.core import database as db_mod
    from app.services.events_service import classify_alert_level_from_settings
    from app.services.mappers import get_or_create_org_settings
    from app.services.sse import sse_broker

    app = _setup_test_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        mgr = client.post(
            "/api/v1/auth/login", json={"username": "manager", "password": "manager123"}
        ).json()
        mgr_token = mgr["accessToken"]
        org_id = mgr["user"]["organizationId"]

        drv = client.post(
            "/api/v1/auth/login", json={"username": "driver1", "password": "driver123"}
        ).json()
        drv_token = drv["accessToken"]

        # Update dynamic 3-level thresholds in org settings without rebuilding app
        cur_settings = client.get("/api/v1/settings", headers=_auth(mgr_token)).json()
        cur_settings["level1Sec"] = 1.5
        cur_settings["level2Sec"] = 3.0
        cur_settings["level3Sec"] = 5.0
        cur_settings["earThreshold"] = 0.26
        put_res = client.put("/api/v1/settings", json=cur_settings, headers=_auth(mgr_token))
        assert put_res.status_code == 200

        # Driver fetches runtime config & opens session -> gets updated thresholds immediately
        cfg_res = client.get("/api/v1/sessions/config", headers=_auth(drv_token))
        assert cfg_res.status_code == 200
        assert cfg_res.json()["level1Sec"] == pytest.approx(1.5)
        assert cfg_res.json()["level2Sec"] == pytest.approx(3.0)
        assert cfg_res.json()["level3Sec"] == pytest.approx(5.0)
        assert cfg_res.json()["earThreshold"] == pytest.approx(0.26)

        with db_mod.SessionLocal() as db:
            org_s = get_or_create_org_settings(db, org_id)
            assert classify_alert_level_from_settings(1.0, org_s) == 0
            assert classify_alert_level_from_settings(1.6, org_s) == 1
            assert classify_alert_level_from_settings(3.2, org_s) == 2
            assert classify_alert_level_from_settings(5.1, org_s) == 3

        now = datetime.now(timezone.utc)
        sess_id = str(uuid4())
        client.post(
            "/api/v1/sessions",
            json={"sessionId": sess_id, "startedAt": now.isoformat()},
            headers=_auth(drv_token),
        )

        # Level 1 -> gentle_reminder, does NOT emit dispatcher SSE `alert`
        sse_broker.clear_history(org_id)
        ep_id = str(uuid4())
        r_lvl1 = client.post(
            f"/api/v1/sessions/{sess_id}/events",
            json={
                "eventId": ep_id,
                "type": "DROWSINESS",
                "level": "WARNING",
                "severityLevel": 1,
                "status": "OPEN",
                "state": "DROWSINESS_SIGNS",
                "riskScore": 0.55,
                "startedAt": now.isoformat(),
                "durationSec": 2,
                "capturedAt": now.isoformat(),
            },
            headers=_auth(drv_token),
        )
        assert r_lvl1.status_code == 200
        assert r_lvl1.json()["severityLevel"] == 1
        assert r_lvl1.json()["alertAction"] == "gentle_reminder"
        assert [m for m in sse_broker.get_recent_messages(org_id) if m["event"] == "alert"] == []

        # Level 2 -> cabin_bell, upgrades same episode to severityLevel=2, still no dispatcher SSE `alert`
        r_lvl2 = client.post(
            f"/api/v1/sessions/{sess_id}/events",
            json={
                "eventId": ep_id,
                "type": "DROWSINESS",
                "level": "WARNING",
                "severityLevel": 2,
                "status": "OPEN",
                "state": "DROWSINESS_SIGNS",
                "riskScore": 0.80,
                "startedAt": now.isoformat(),
                "durationSec": 3,
                "capturedAt": (now + timedelta(seconds=1)).isoformat(),
            },
            headers=_auth(drv_token),
        )
        assert r_lvl2.status_code == 200
        assert r_lvl2.json()["severityLevel"] == 2
        assert r_lvl2.json()["alertAction"] == "cabin_bell"
        assert [m for m in sse_broker.get_recent_messages(org_id) if m["event"] == "alert"] == []

        # Level 3 -> notify_dispatcher, upgrades to CRITICAL + ESCALATED and emits dispatcher SSE `alert`!
        r_lvl3 = client.post(
            f"/api/v1/sessions/{sess_id}/events",
            json={
                "eventId": ep_id,
                "type": "DROWSINESS",
                "level": "CRITICAL",
                "severityLevel": 3,
                "status": "ESCALATED",
                "state": "CRITICAL",
                "riskScore": 0.95,
                "startedAt": now.isoformat(),
                "durationSec": 5,
                "capturedAt": (now + timedelta(seconds=3)).isoformat(),
            },
            headers=_auth(drv_token),
        )
        assert r_lvl3.status_code == 200
        assert r_lvl3.json()["severityLevel"] == 3
        assert r_lvl3.json()["level"] == "CRITICAL"
        assert r_lvl3.json()["alertAction"] == "notify_dispatcher"
        sse_alerts = [m for m in sse_broker.get_recent_messages(org_id) if m["event"] == "alert"]
        assert len(sse_alerts) == 1

        # Manager updates level3Sec live -> delivered to running Driver App on next heartbeat!
        cur_settings["level3Sec"] = 6.5
        client.put("/api/v1/settings", json=cur_settings, headers=_auth(mgr_token))
        hb_res = client.post(
            f"/api/v1/sessions/{sess_id}/heartbeat",
            json={
                "state": "NORMAL",
                "imageQuality": "GOOD",
                "continuousDrivingSec": 30,
                "vehicleMoving": True,
                "capturedAt": (now + timedelta(seconds=10)).isoformat(),
            },
            headers=_auth(drv_token),
        )
        assert hb_res.status_code == 200
        assert hb_res.json()["settings"]["level3Sec"] == pytest.approx(6.5)


def test_p3_5_auto_escalation_levels_recipients_timing_ack_stop_and_no_duplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from app.core import database as db_mod
    from app.services.notify import notification_dispatcher
    from app.services.watchdog import check_pending_escalations

    app = _setup_test_app(tmp_path, monkeypatch)
    notification_dispatcher.reset_defaults()

    with TestClient(app) as client:
        mgr = client.post(
            "/api/v1/auth/login", json={"username": "manager", "password": "manager123"}
        ).json()
        mgr_token = mgr["accessToken"]
        mgr_id = mgr["user"]["id"]

        disp = client.post(
            "/api/v1/auth/login", json={"username": "dispatcher", "password": "dispatcher123"}
        ).json()
        disp_token = disp["accessToken"]
        disp_id = disp["user"]["id"]

        drv = client.post(
            "/api/v1/auth/login", json={"username": "driver1", "password": "driver123"}
        ).json()
        drv_token = drv["accessToken"]

        # Verify seeded policies: Level 1 (60s -> dispatcher/push), Level 2 (180s -> manager/push), Level 3 (300s -> manager/sms)
        pols = client.get("/api/v1/escalation-policies", headers=_auth(mgr_token)).json()
        assert [(p["level"], p["afterSeconds"], p["notifyRole"], p["channel"]) for p in pols] == [
            (1, 60, "dispatcher", "push"),
            (2, 180, "manager", "push"),
            (3, 300, "manager", "sms"),
        ]

        t0 = datetime.now(timezone.utc)
        sess_id = str(uuid4())
        client.post(
            "/api/v1/sessions",
            json={"sessionId": sess_id, "startedAt": t0.isoformat()},
            headers=_auth(drv_token),
        )

        # Create an OPEN warning event at t0
        ev1_id = str(uuid4())
        r1 = client.post(
            f"/api/v1/sessions/{sess_id}/events",
            json={
                "eventId": ev1_id,
                "type": "DROWSINESS",
                "level": "WARNING",
                "status": "OPEN",
                "state": "DROWSINESS_SIGNS",
                "riskScore": 0.82,
                "startedAt": t0.isoformat(),
                "durationSec": 3,
                "capturedAt": t0.isoformat(),
            },
            headers=_auth(drv_token),
        )
        assert r1.status_code == 200
        ev1_db_id = r1.json()["id"]

        # 1) At t0 + 45s (< ack_timeout_sec=60s): zero escalations
        with db_mod.SessionLocal() as db:
            assert check_pending_escalations(db, now_utc=t0 + timedelta(seconds=45)) == []

        # 2) At t0 + 65s (>= 60s): Level 1 triggers -> dispatcher notified via push, status becomes ESCALATED
        with db_mod.SessionLocal() as db:
            esc_65 = check_pending_escalations(db, now_utc=t0 + timedelta(seconds=65))
            assert len(esc_65) >= 1
            ev1_esc = [e for e in esc_65 if e.event_id == ev1_db_id]
            assert len(ev1_esc) == 1
            assert ev1_esc[0].notified_user_id == disp_id
            assert ev1_esc[0].channel == "push"

            # Re-run at t0 + 70s -> MUST NOT send duplicates!
            dup_check = [
                e
                for e in check_pending_escalations(db, now_utc=t0 + timedelta(seconds=70))
                if e.event_id == ev1_db_id
            ]
            assert dup_check == []

        ev1_list = client.get(
            f"/api/v1/events/{ev1_db_id}/escalations", headers=_auth(mgr_token)
        ).json()
        assert len(ev1_list) == 1
        assert ev1_list[0]["level"] == 1
        assert ev1_list[0]["notifiedUserId"] == disp_id

        # Verify event status transitioned to ESCALATED
        ev_page = client.get("/api/v1/events?pageSize=20", headers=_auth(mgr_token)).json()
        ev1_row = next(x for x in ev_page["items"] if x["id"] == ev1_db_id)
        assert ev1_row["status"] == "ESCALATED"

        # 3) At t0 + 185s (>= 180s): Level 2 triggers -> manager notified via push
        with db_mod.SessionLocal() as db:
            esc_185 = [
                e
                for e in check_pending_escalations(db, now_utc=t0 + timedelta(seconds=185))
                if e.event_id == ev1_db_id
            ]
            assert len(esc_185) == 1
            assert esc_185[0].notified_user_id == mgr_id
            assert esc_185[0].channel == "push"

        # 4) Dispatcher acknowledges event at t0 + 200s -> stops further escalation!
        ack_res = client.post(
            f"/api/v1/events/{ev1_db_id}/ack",
            json={"note": "Đã gọi tài xế dừng nghỉ"},
            headers=_auth(disp_token),
        )
        assert ack_res.status_code == 200

        # At t0 + 320s (>= 300s Level 3): NO Level 3 escalation sent for acked event!
        with db_mod.SessionLocal() as db:
            esc_320 = [
                e
                for e in check_pending_escalations(db, now_utc=t0 + timedelta(seconds=320))
                if e.event_id == ev1_db_id
            ]
            assert esc_320 == []

        final_esc = client.get(
            f"/api/v1/events/{ev1_db_id}/escalations", headers=_auth(mgr_token)
        ).json()
        assert [x["level"] for x in final_esc] == [1, 2]
        assert all(x["status"] == "acked" for x in final_esc)

        # 5) A second un-acked event reaching 310s escalates all the way through Level 1 -> 2 -> 3 (sms)
        ev2_id = str(uuid4())
        r2 = client.post(
            f"/api/v1/sessions/{sess_id}/events",
            json={
                "eventId": ev2_id,
                "type": "DROWSINESS",
                "level": "CRITICAL",
                "status": "OPEN",
                "state": "CRITICAL",
                "riskScore": 0.96,
                "startedAt": t0.isoformat(),
                "durationSec": 5,
                "capturedAt": t0.isoformat(),
            },
            headers=_auth(drv_token),
        )
        ev2_db_id = r2.json()["id"]
        with db_mod.SessionLocal() as db:
            esc_ev2 = [
                e
                for e in check_pending_escalations(db, now_utc=t0 + timedelta(seconds=310))
                if e.event_id == ev2_db_id
            ]
            assert len(esc_ev2) == 3
            assert [e.channel for e in esc_ev2] == ["push", "push", "sms"]


def test_p3_2_continuous_driving_rest_breaks_and_nearest_rest_stops_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from app.services.sse import sse_broker

    app = _setup_test_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        mgr = client.post(
            "/api/v1/auth/login", json={"username": "manager", "password": "manager123"}
        ).json()
        mgr_token = mgr["accessToken"]
        org_id = mgr["user"]["organizationId"]

        drv = client.post(
            "/api/v1/auth/login", json={"username": "driver1", "password": "driver123"}
        ).json()
        drv_token = drv["accessToken"]

        # Set maxContinuousDriveMin = 120, restReminderBeforeMin = 15, restResetMin (min_rest_min) = 20, shareLocation = True
        cur_settings = client.get("/api/v1/settings", headers=_auth(mgr_token)).json()
        cur_settings["maxContinuousDriveMin"] = 120
        cur_settings["restReminderBeforeMin"] = 15
        cur_settings["restResetMin"] = 20
        cur_settings["shareLocation"] = True
        assert (
            client.put("/api/v1/settings", json=cur_settings, headers=_auth(mgr_token)).status_code
            == 200
        )

        client.post(
            "/api/v1/auth/consent",
            json={"version": "2026-01", "locationConsent": True, "clipStorageConsent": False},
            headers=_auth(drv_token),
        )

        # Verify /rest-stops/nearest returns stops strictly sorted by distanceKm ascending
        stops_res = client.get(
            "/api/v1/rest-stops/nearest?lat=20.05&lng=106.04&limit=5",
            headers=_auth(drv_token),
        )
        assert stops_res.status_code == 200
        stops = stops_res.json()
        assert len(stops) == 5
        distances = [s["distanceKm"] for s in stops]
        assert distances == sorted(distances)
        assert distances[0] < distances[-1]

        t0 = datetime.now(timezone.utc) - timedelta(hours=3)
        sess_id = str(uuid4())
        client.post(
            "/api/v1/sessions",
            json={"sessionId": sess_id, "startedAt": t0.isoformat()},
            headers=_auth(drv_token),
        )

        # 1) At 104 min (6240s < 105 min = (120 - 15) * 60 = 6300s): NO rest reminder yet!
        hb_104 = client.post(
            f"/api/v1/sessions/{sess_id}/heartbeat",
            json={
                "state": "NORMAL",
                "imageQuality": "GOOD",
                "continuousDrivingSec": 104 * 60,
                "vehicleMoving": True,
                "capturedAt": (t0 + timedelta(minutes=104)).isoformat(),
                "location": {"lat": 20.05, "lng": 106.04},
            },
            headers=_auth(drv_token),
        )
        assert hb_104.status_code == 200
        assert hb_104.json()["restReminder"] is None

        # 2) At exact 105 min (6300s == (120 - 15) * 60): restReminder fires with sorted suggestedStops + LONG_DRIVING SSE alert!
        sse_broker.clear_history(org_id)
        hb_105 = client.post(
            f"/api/v1/sessions/{sess_id}/heartbeat",
            json={
                "state": "NORMAL",
                "imageQuality": "GOOD",
                "continuousDrivingSec": 105 * 60,
                "vehicleMoving": True,
                "capturedAt": (t0 + timedelta(minutes=105)).isoformat(),
                "location": {"lat": 20.05, "lng": 106.04},
            },
            headers=_auth(drv_token),
        )
        assert hb_105.status_code == 200
        rem = hb_105.json()["restReminder"]
        assert rem is not None
        assert rem["shouldRest"] is True
        assert rem["overMaxLimit"] is False
        assert rem["remainingMin"] == 15
        rem_dists = [s["distanceKm"] for s in rem["suggestedStops"]]
        assert rem_dists == sorted(rem_dists)
        assert [s["id"] for s in rem["suggestedStops"]] == [s["id"] for s in stops]
        assert any(
            m["event"] == "alert" and '"LONG_DRIVING"' in m["data"]
            for m in sse_broker.get_recent_messages(org_id)
        )

        # 3) Short rest break (10 min < minRestMin=20 min) -> rejected (qualifiedReset=False) + REST_CLAIM_REJECTED event
        rb1_start = t0 + timedelta(minutes=106)
        rb1_res = client.post(
            f"/api/v1/sessions/{sess_id}/rest-breaks/start",
            json={"startedAt": rb1_start.isoformat(), "lat": 20.05, "lng": 106.04},
            headers=_auth(drv_token),
        )
        assert rb1_res.status_code == 201
        assert rb1_res.json()["suggestedStopId"] == stops[0]["id"]

        rb1_end_res = client.post(
            f"/api/v1/sessions/{sess_id}/rest-breaks/end",
            json={"endedAt": (rb1_start + timedelta(minutes=10)).isoformat()},
            headers=_auth(drv_token),
        )
        assert rb1_end_res.status_code == 200
        assert rb1_end_res.json()["qualifiedReset"] is False

        # 4) Full rest break (25 min >= minRestMin=20 min) -> qualifiedReset=True, resets continuous driving!
        rb2_start = t0 + timedelta(minutes=117)
        rb2_end = rb2_start + timedelta(minutes=25)
        client.post(
            f"/api/v1/sessions/{sess_id}/rest-breaks/start",
            json={"startedAt": rb2_start.isoformat(), "suggestedStopId": stops[0]["id"]},
            headers=_auth(drv_token),
        )
        rb2_end_res = client.post(
            f"/api/v1/sessions/{sess_id}/rest-breaks/end",
            json={"endedAt": rb2_end.isoformat()},
            headers=_auth(drv_token),
        )
        assert rb2_end_res.status_code == 200
        assert rb2_end_res.json()["qualifiedReset"] is True

        # Heartbeat 10 minutes after qualifying rest -> continuous_driving_sec is ~10m, so restReminder is None!
        hb_after_rest = client.post(
            f"/api/v1/sessions/{sess_id}/heartbeat",
            json={
                "state": "NORMAL",
                "imageQuality": "GOOD",
                "continuousDrivingSec": 152 * 60,
                "vehicleMoving": True,
                "capturedAt": (rb2_end + timedelta(minutes=10)).isoformat(),
                "location": {"lat": 20.05, "lng": 106.04},
            },
            headers=_auth(drv_token),
        )
        assert hb_after_rest.status_code == 200
        assert hb_after_rest.json()["restReminder"] is None


def test_p3_4_alarm_fatigue_driver_feedback_and_usage_7d(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    app = _setup_test_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        mgr = client.post(
            "/api/v1/auth/login", json={"username": "manager", "password": "manager123"}
        ).json()
        mgr_token = mgr["accessToken"]

        # Create a clean driver in Org 1 to verify exact math for offPerHour and falseAlertPct
        created_drv = client.post(
            "/api/v1/drivers",
            json={
                "fullName": "Phạm Kiểm Chứng Fatigue",
                "phone": "0908889900",
                "username": "driver_fatigue",
                "password": "driver123!",
            },
            headers=_auth(mgr_token),
        ).json()
        drv_id = created_drv["id"]

        drv_login = client.post(
            "/api/v1/auth/login",
            json={"username": "driver_fatigue", "password": "driver123!"},
        ).json()
        drv_token = drv_login["accessToken"]
        client.post(
            "/api/v1/auth/change-password",
            json={"currentPassword": "driver123!", "newPassword": "newSafePassword123"},
            headers=_auth(drv_token),
        )
        client.post(
            "/api/v1/auth/consent",
            json={"version": "2026-01", "locationConsent": False, "clipStorageConsent": False},
            headers=_auth(drv_token),
        )

        now = datetime.now(timezone.utc)
        sess_id = str(uuid4())
        client.post(
            "/api/v1/sessions",
            json={"sessionId": sess_id, "startedAt": (now - timedelta(hours=2)).isoformat()},
            headers=_auth(drv_token),
        )

        # Create 4 alerts in this session -> alerts_total = 4
        ev_ids: list[str] = []
        for idx in range(4):
            eid = str(uuid4())
            r = client.post(
                f"/api/v1/sessions/{sess_id}/events",
                json={
                    "eventId": eid,
                    "type": "DROWSINESS",
                    "level": "WARNING",
                    "status": "OPEN",
                    "state": "DROWSINESS_SIGNS",
                    "riskScore": 0.78,
                    "startedAt": (now - timedelta(minutes=30 - idx)).isoformat(),
                    "durationSec": 2,
                    "capturedAt": (now - timedelta(minutes=30 - idx)).isoformat(),
                },
                headers=_auth(drv_token),
            )
            assert r.status_code == 200
            ev_ids.append(r.json()["id"])

        # Driver marks 1 alert as 'false_alarm' and 1 as 'correct'
        fb1 = client.post(
            f"/api/v1/sessions/{sess_id}/events/{ev_ids[0]}/feedback",
            json={"feedback": "false_alarm"},
            headers=_auth(drv_token),
        )
        assert fb1.status_code == 200
        assert fb1.json()["driverFeedback"] == "false_alarm"

        fb2 = client.post(
            f"/api/v1/events/{ev_ids[1]}/feedback",
            json={"feedback": "correct"},
            headers=_auth(drv_token),
        )
        assert fb2.status_code == 200
        assert fb2.json()["driverFeedback"] == "correct"

        # End session: 120 minutes (7200s) monitored, 3 monitoring-off toggles -> offPerHour = 3 / 2.0 = 1.50, falseAlertPct = 1/4 = 25.0%
        end_res = client.post(
            f"/api/v1/sessions/{sess_id}/end",
            json={
                "endedAt": now.isoformat(),
                "summary": {
                    "totalDrivingSec": 7200,
                    "warningCount": 4,
                    "criticalCount": 0,
                    "unavailableSec": 0,
                    "monitoringOffCount": 3,
                },
            },
            headers=_auth(drv_token),
        )
        assert end_res.status_code == 200

        fatigue_res = client.get("/api/v1/stats/alarm-fatigue", headers=_auth(mgr_token))
        assert fatigue_res.status_code == 200
        row = next(x for x in fatigue_res.json() if x["driverId"] == drv_id)
        assert row["monitoredMinutes"] == 120
        assert row["monitoringOffCount"] == 3
        assert row["alertsTotal"] == 4
        assert row["alertsFalse"] == 1
        assert row["offPerHour"] == pytest.approx(1.5)
        assert row["falseAlertPct"] == pytest.approx(25.0)


def test_p3_7_fcm_push_tokens_registration_and_closed_tab_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import json as json_mod
    import threading

    from app.services.notify import notification_dispatcher

    received_fcm_payloads: list[dict] = []

    class _MockFcmHandler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            received_fcm_payloads.append(
                {
                    "auth": self.headers.get("Authorization"),
                    "body": json_mod.loads(raw),
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success":1,"failure":0}')

        def log_message(self, format, *args):  # noqa: A002
            return

    fcm_server = HTTPServer(("127.0.0.1", 0), _MockFcmHandler)
    fcm_port = fcm_server.server_address[1]
    t = threading.Thread(target=fcm_server.serve_forever, daemon=True)
    t.start()

    try:
        monkeypatch.setenv("FCM_SERVER_KEY", "test-fcm-server-key")
        monkeypatch.setenv("FCM_ENDPOINT_URL", f"http://127.0.0.1:{fcm_port}/fcm/send")
        app = _setup_test_app(tmp_path, monkeypatch)
        notification_dispatcher.reset_defaults()

        with TestClient(app) as client:
            disp = client.post(
                "/api/v1/auth/login",
                json={"username": "dispatcher", "password": "dispatcher123"},
            ).json()
            disp_token = disp["accessToken"]

            drv = client.post(
                "/api/v1/auth/login",
                json={"username": "driver1", "password": "driver123"},
            ).json()
            drv_token = drv["accessToken"]

            # 1) Dispatcher registers Web push token; Driver registers Android push token
            r_web = client.post(
                "/api/v1/push-tokens",
                json={"fcmToken": "web-fcm-token-dispatcher-001", "platform": "web"},
                headers=_auth(disp_token),
            )
            assert r_web.status_code == 201
            r_and = client.post(
                "/api/v1/push-tokens",
                json={"fcmToken": "android-fcm-token-driver-001", "platform": "android"},
                headers=_auth(drv_token),
            )
            assert r_and.status_code == 201

            my_tokens = client.get("/api/v1/push-tokens", headers=_auth(disp_token)).json()
            assert any(t_item["fcmToken"] == "web-fcm-token-dispatcher-001" for t_item in my_tokens)

            # 2)Even with no SSE stream open (closed browser tab), CRITICAL event delivers FCM push to dispatcher!
            now = datetime.now(timezone.utc)
            sess_id = str(uuid4())
            client.post(
                "/api/v1/sessions",
                json={"sessionId": sess_id, "startedAt": now.isoformat()},
                headers=_auth(drv_token),
            )
            ev_res = client.post(
                f"/api/v1/sessions/{sess_id}/events",
                json={
                    "eventId": str(uuid4()),
                    "type": "DROWSINESS",
                    "level": "CRITICAL",
                    "severityLevel": 3,
                    "status": "ESCALATED",
                    "state": "CRITICAL",
                    "riskScore": 0.96,
                    "startedAt": now.isoformat(),
                    "durationSec": 5,
                    "capturedAt": now.isoformat(),
                },
                headers=_auth(drv_token),
            )
            assert ev_res.status_code == 200
            assert any(
                p["body"]["to"] == "web-fcm-token-dispatcher-001"
                and p["auth"] == "key=test-fcm-server-key"
                for p in received_fcm_payloads
            )

            # 3) Unregister push token on logout
            del_res = client.request(
                "DELETE",
                "/api/v1/push-tokens",
                json={"fcmToken": "web-fcm-token-dispatcher-001"},
                headers=_auth(disp_token),
            )
            assert del_res.status_code == 200
            assert del_res.json()["deleted"] == 1
    finally:
        fcm_server.shutdown()
        fcm_server.server_close()


def test_p3_6_risk_scores_and_pdf_excel_report_export_manager_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from datetime import date, time
    import io

    from openpyxl import load_workbook
    from sqlalchemy import select

    from app.core import database as db_mod
    from app.models.models import EventModel, SessionModel, User
    from app.services.mappers import VN_TZ, to_vn_time

    reports_dir = tmp_path / "generated_reports"
    monkeypatch.setenv("PREDRIVE_REPORTS_DIR", reports_dir.as_posix())
    app = _setup_test_app(tmp_path, monkeypatch)

    with TestClient(app) as client:
        mgr = client.post(
            "/api/v1/auth/login", json={"username": "manager", "password": "manager123"}
        ).json()
        mgr_token = mgr["accessToken"]
        org_id = mgr["user"]["organizationId"]

        mgr2_token = client.post(
            "/api/v1/auth/login", json={"username": "manager2", "password": "manager123"}
        ).json()["accessToken"]
        disp_token = client.post(
            "/api/v1/auth/login",
            json={"username": "dispatcher", "password": "dispatcher123"},
        ).json()["accessToken"]
        drv_token = client.post(
            "/api/v1/auth/login", json={"username": "driver1", "password": "driver123"}
        ).json()["accessToken"]

        # 1) RBAC: dispatcher & driver blocked (403) on risk-scores & reports
        assert client.get("/api/v1/risk-scores", headers=_auth(disp_token)).status_code == 403
        assert client.get("/api/v1/risk-scores", headers=_auth(drv_token)).status_code == 403
        assert (
            client.post("/api/v1/reports/export", json={}, headers=_auth(disp_token)).status_code
            == 403
        )

        # 2) Compute risk_scores for shift, weekly, and monthly with configurable weights
        for p_type in ("shift", "weekly", "monthly"):
            rc = client.post(
                "/api/v1/risk-scores/recompute",
                json={
                    "periodType": p_type,
                    "weights": {
                        "wCritical": 30.0,
                        "wDrowsy": 15.0,
                        "wDistraction": 8.0,
                        "wOvertime": 10.0,
                        "shiftHoursNorm": 8.0,
                    },
                },
                headers=_auth(mgr_token),
            )
            assert rc.status_code == 200
            items = rc.json()
            assert len(items) >= 5
            assert all(0 <= x["score"] <= 100 for x in items)
            assert all(x["riskLevel"] in ("low", "medium", "high") for x in items)

        # 3) Export monthly XLSX report and verify downloaded Excel numbers match manual DB queries 100%
        today_vn = to_vn_time(datetime.now(timezone.utc)).date()
        p_start = today_vn - timedelta(days=29)
        p_end = today_vn

        xlsx_exp = client.post(
            "/api/v1/reports/export",
            json={
                "reportType": "monthly",
                "fileFormat": "xlsx",
                "periodStart": p_start.isoformat(),
                "periodEnd": p_end.isoformat(),
            },
            headers=_auth(mgr_token),
        )
        assert xlsx_exp.status_code == 201
        xlsx_id = xlsx_exp.json()["id"]

        # Dispatcher (403) and Org 2 manager (404) cannot download Org 1 report
        assert (
            client.get(
                f"/api/v1/reports/{xlsx_id}/download", headers=_auth(disp_token)
            ).status_code
            == 403
        )
        assert (
            client.get(
                f"/api/v1/reports/{xlsx_id}/download", headers=_auth(mgr2_token)
            ).status_code
            == 404
        )

        dl_xlsx = client.get(
            f"/api/v1/reports/{xlsx_id}/download", headers=_auth(mgr_token)
        )
        assert dl_xlsx.status_code == 200
        wb = load_workbook(io.BytesIO(dl_xlsx.content))
        ws_sum = wb["TongHop"]
        summary_kv = {ws_sum.cell(r, 1).value: ws_sum.cell(r, 2).value for r in range(2, 11)}

        # Manual SQL ground-truth query
        start_utc = datetime.combine(p_start, time.min, tzinfo=VN_TZ).astimezone(timezone.utc)
        end_utc = datetime.combine(p_end, time.max, tzinfo=VN_TZ).astimezone(timezone.utc)
        with db_mod.SessionLocal() as db:
            org_drivers = db.scalars(
                select(User).where(User.organization_id == org_id, User.role == "driver")
            ).all()
            expected_sessions = 0
            expected_events = 0
            expected_critical = 0
            expected_hours = 0.0
            for d in org_drivers:
                d_sess = db.scalars(
                    select(SessionModel).where(
                        SessionModel.organization_id == org_id,
                        SessionModel.driver_id == d.id,
                        SessionModel.started_at >= start_utc,
                        SessionModel.started_at <= end_utc,
                    )
                ).all()
                d_ev = db.scalars(
                    select(EventModel).where(
                        EventModel.organization_id == org_id,
                        EventModel.driver_id == d.id,
                        EventModel.occurred_at >= start_utc,
                        EventModel.occurred_at <= end_utc,
                    )
                ).all()
                expected_sessions += len(d_sess)
                expected_hours += round(
                    sum(
                        max(int(s.total_driving_sec or 0), int(s.continuous_driving_sec or 0))
                        for s in d_sess
                    )
                    / 3600.0,
                    1,
                )
                expected_events += len(d_ev)
                expected_critical += sum(1 for e in d_ev if int(e.level) >= 3)

        assert summary_kv["Tong tai xe"] == len(org_drivers)
        assert summary_kv["Tong phien lai"] == expected_sessions
        assert summary_kv["Tong gio lai"] == pytest.approx(round(expected_hours, 1))
        assert summary_kv["Tong su kien"] == expected_events
        assert summary_kv["Tong nguy hiem (Muc 3)"] == expected_critical

        # 4) Export weekly PDF report and verify valid PDF download
        pdf_exp = client.post(
            "/api/v1/reports/export",
            json={"reportType": "weekly", "fileFormat": "pdf"},
            headers=_auth(mgr_token),
        )
        assert pdf_exp.status_code == 201
        pdf_id = pdf_exp.json()["id"]
        dl_pdf = client.get(
            f"/api/v1/reports/{pdf_id}/download", headers=_auth(mgr_token)
        )
        assert dl_pdf.status_code == 200
        assert dl_pdf.headers["content-type"].startswith("application/pdf")
        assert dl_pdf.content.startswith(b"%PDF-")
        assert len(dl_pdf.content) > 500
