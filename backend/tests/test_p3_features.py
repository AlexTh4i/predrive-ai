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
