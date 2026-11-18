from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import func, select

from app.core import database as db_mod
from app.main import app
from app.models.models import Consent, User
from app.services.sse import sse_broker


@pytest.fixture()
def p1_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_file = tmp_path / "test_predrive_p1.db"
    db_url = f"sqlite:///{db_file.as_posix()}"
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("PREDRIVE_ENABLE_WATCHDOG", "0")

    db_mod.reset_engine(db_url)
    db_mod.Base.metadata.create_all(bind=db_mod.engine)
    sse_broker.clear_history()

    with TestClient(app) as client:
        yield client


def test_p1_1_production_has_no_seed_users_and_manager_created_user_must_change_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # Part A: ENV=production startup -> 0 users, no manager123
    prod_db = tmp_path / "p1_prod.db"
    prod_url = f"sqlite:///{prod_db.as_posix()}"
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DATABASE_URL", prod_url)
    monkeypatch.setenv("PREDRIVE_AUTO_SEED", "1")
    monkeypatch.setenv("PREDRIVE_ENABLE_WATCHDOG", "0")
    db_mod.reset_engine(prod_url)

    with TestClient(app) as prod_client:
        login_res = prod_client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "manager123"},
        )
        assert login_res.status_code == 401
    with db_mod.SessionLocal() as db:
        assert db.scalar(select(func.count(User.id))) == 0

    # Part B: Manager creates a new driver -> temporary password generated (never driver123),
    # mustChangePassword=True, operational endpoints blocked until /auth/change-password!
    dev_db = tmp_path / "p1_dev.db"
    dev_url = f"sqlite:///{dev_db.as_posix()}"
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("DATABASE_URL", dev_url)
    db_mod.reset_engine(dev_url)

    with TestClient(app) as client:
        mgr_login = client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "manager123"},
        )
        assert mgr_login.status_code == 200
        mgr_hdr = {"Authorization": f"Bearer {mgr_login.json()['accessToken']}"}

        created_res = client.post(
            "/api/v1/drivers",
            json={
                "fullName": "Phạm Tân Binh",
                "phone": "0988777666",
                "username": "tan_binh",
            },
            headers=mgr_hdr,
        )
        assert created_res.status_code == 201
        created = created_res.json()
        temp_pwd = created["temporaryPassword"]
        assert temp_pwd is not None and temp_pwd != "driver123"

        # Login with temporary password succeeds, returns mustChangePassword=True
        drv_login = client.post(
            "/api/v1/auth/login",
            json={"username": "tan_binh", "password": temp_pwd},
        )
        assert drv_login.status_code == 200
        drv_body = drv_login.json()
        assert drv_body["user"]["mustChangePassword"] is True
        drv_hdr = {"Authorization": f"Bearer {drv_body['accessToken']}"}

        # Grant consent in DB so we isolate testing the password-change requirement first
        with db_mod.SessionLocal() as db:
            db.add(
                Consent(
                    organization_id=drv_body["user"]["organizationId"],
                    user_id=drv_body["user"]["id"],
                    consent_type="data_processing",
                    version="2026-01",
                    location_consent=False,
                    clip_storage_consent=False,
                )
            )
            db.commit()

        # Starting a driving session BEFORE changing temporary password must return 403 PASSWORD_CHANGE_REQUIRED
        blocked = client.post(
            "/api/v1/sessions",
            json={
                "sessionId": str(uuid4()),
                "startedAt": datetime.now(timezone.utc).isoformat(),
            },
            headers=drv_hdr,
        )
        assert blocked.status_code == 403
        assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"

        # Change password via /api/v1/auth/change-password
        chg = client.post(
            "/api/v1/auth/change-password",
            json={"currentPassword": temp_pwd, "newPassword": "NewStrongPass#2026"},
            headers=drv_hdr,
        )
        assert chg.status_code == 200
        assert chg.json()["mustChangePassword"] is False

        # Now starting a session succeeds!
        ok_sess = client.post(
            "/api/v1/sessions",
            json={
                "sessionId": str(uuid4()),
                "startedAt": datetime.now(timezone.utc).isoformat(),
            },
            headers=drv_hdr,
        )
        assert ok_sess.status_code == 200


def test_p1_2_refresh_token_rotation_hash_revocation_and_reuse_detection(
    p1_client: TestClient,
):
    from app.core.security import hash_token
    from app.models.models import RefreshToken

    # 1. Login issues 15-minute access token (900s) + opaque refreshToken stored ONLY as SHA-256 hash
    login_res = p1_client.post(
        "/api/v1/auth/login",
        json={"username": "manager", "password": "manager123"},
    )
    assert login_res.status_code == 200
    body = login_res.json()
    assert body["expiresIn"] == 900
    rt1 = body["refreshToken"]
    assert rt1 and len(rt1) >= 32

    with db_mod.SessionLocal() as db:
        # Raw refresh token must NEVER exist in DB; only its SHA-256 hash
        assert (
            db.scalar(select(RefreshToken).where(RefreshToken.token_hash == rt1))
            is None
        )
        row1 = db.scalar(
            select(RefreshToken).where(RefreshToken.token_hash == hash_token(rt1))
        )
        assert row1 is not None
        assert row1.revoked_at is None
        family_id = row1.family_id

    # 2. Rotate token rt1 -> gets rt2; rt1 is now marked revoked & replaced_by_id set
    rot1 = p1_client.post("/api/v1/auth/refresh", json={"refreshToken": rt1})
    assert rot1.status_code == 200
    rt2 = rot1.json()["refreshToken"]
    assert rt2 and rt2 != rt1

    # 3. REUSE DETECTION: Replay already-rotated rt1 -> must return 401 REFRESH_TOKEN_REUSED
    # AND immediately revoke the entire family (so rt2 ALSO becomes invalid!)
    replay_res = p1_client.post("/api/v1/auth/refresh", json={"refreshToken": rt1})
    assert replay_res.status_code == 401
    assert replay_res.json()["error"]["code"] == "REFRESH_TOKEN_REUSED"

    rt2_after_compromise = p1_client.post(
        "/api/v1/auth/refresh", json={"refreshToken": rt2}
    )
    assert rt2_after_compromise.status_code == 401

    with db_mod.SessionLocal() as db:
        active_in_family = db.scalars(
            select(RefreshToken).where(
                RefreshToken.family_id == family_id,
                RefreshToken.revoked_at.is_(None),
            )
        ).all()
        assert len(active_in_family) == 0

    # 4. Logout revokes active refresh token
    login2 = p1_client.post(
        "/api/v1/auth/login",
        json={"username": "dispatcher", "password": "dispatcher123"},
    ).json()
    disp_hdr = {"Authorization": f"Bearer {login2['accessToken']}"}
    rt_disp = login2["refreshToken"]
    logout_res = p1_client.post(
        "/api/v1/auth/logout", json={"refreshToken": rt_disp}, headers=disp_hdr
    )
    assert logout_res.status_code == 200
    assert (
        p1_client.post("/api/v1/auth/refresh", json={"refreshToken": rt_disp}).status_code
        == 401
    )


@pytest.mark.parametrize(
    "redis_url",
    ["", "redis://127.0.0.1:63799/0"],
    ids=["in_memory", "redis"],
)
def test_p1_3_rate_limiting_login_pair_events_heartbeat_429_retry_after(
    p1_client: TestClient, monkeypatch: pytest.MonkeyPatch, redis_url: str
):
    from app.services.rate_limiter import rate_limiter

    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("PREDRIVE_RL_LOGIN_USER_LIMIT", "3")
    monkeypatch.setenv("PREDRIVE_RL_PAIR_LIMIT", "2")
    monkeypatch.setenv("PREDRIVE_RL_EVENTS_LIMIT", "2")
    monkeypatch.setenv("PREDRIVE_RL_HEARTBEAT_LIMIT", "2")
    rate_limiter.reset()

    # 1. Login rate limit (per IP + username) -> 4th attempt returns 429 + Retry-After
    for _ in range(3):
        r = p1_client.post(
            "/api/v1/auth/login",
            json={"username": "driver1", "password": "wrong_password"},
        )
        assert r.status_code == 401

    r_429 = p1_client.post(
        "/api/v1/auth/login",
        json={"username": "driver1", "password": "wrong_password"},
    )
    assert r_429.status_code == 429
    assert int(r_429.headers["Retry-After"]) >= 1
    assert r_429.json()["error"]["code"] == "RATE_LIMITED"

    # Different username on same IP is still allowed (proves IP+username key granularity)
    drv2_login = p1_client.post(
        "/api/v1/auth/login",
        json={"username": "driver2", "password": "driver123"},
    )
    assert drv2_login.status_code == 200
    drv2_hdr = {"Authorization": f"Bearer {drv2_login.json()['accessToken']}"}

    # 2. Pair rate limit -> 3rd attempt returns 429 + Retry-After
    for _ in range(2):
        pr = p1_client.post(
            "/api/v1/auth/pair", json={"code": "BAD999"}, headers=drv2_hdr
        )
        assert pr.status_code == 404
    pr_429 = p1_client.post(
        "/api/v1/auth/pair", json={"code": "BAD999"}, headers=drv2_hdr
    )
    assert pr_429.status_code == 429
    assert int(pr_429.headers["Retry-After"]) >= 1

    # 3. Session /events/batch and /heartbeat rate limits (per device/session)
    sess_id = str(uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    assert (
        p1_client.post(
            "/api/v1/sessions",
            json={"sessionId": sess_id, "startedAt": now_iso},
            headers=drv2_hdr,
        ).status_code
        == 200
    )

    hb_body = {
        "state": "NORMAL",
        "imageQuality": "GOOD",
        "continuousDrivingSec": 30,
        "vehicleMoving": True,
        "capturedAt": now_iso,
    }
    for _ in range(2):
        assert (
            p1_client.post(
                f"/api/v1/sessions/{sess_id}/heartbeat",
                json=hb_body,
                headers=drv2_hdr,
            ).status_code
            == 200
        )
    hb_429 = p1_client.post(
        f"/api/v1/sessions/{sess_id}/heartbeat",
        json=hb_body,
        headers=drv2_hdr,
    )
    assert hb_429.status_code == 429
    assert int(hb_429.headers["Retry-After"]) >= 1

    ev_batch = {
        "events": [
            {
                "eventId": str(uuid4()),
                "type": "DROWSINESS",
                "level": "WARNING",
                "status": "OPEN",
                "state": "DROWSINESS_SIGNS",
                "riskScore": 0.8,
                "startedAt": now_iso,
                "durationSec": 2,
                "capturedAt": now_iso,
            }
        ]
    }
    for _ in range(2):
        assert (
            p1_client.post(
                f"/api/v1/sessions/{sess_id}/events/batch",
                json=ev_batch,
                headers=drv2_hdr,
            ).status_code
            == 200
        )
    ev_429 = p1_client.post(
        f"/api/v1/sessions/{sess_id}/events/batch",
        json=ev_batch,
        headers=drv2_hdr,
    )
    assert ev_429.status_code == 429
    assert int(ev_429.headers["Retry-After"]) >= 1

    rate_limiter.reset()


def test_p1_4_audit_logs_exact_one_row_per_action_and_manager_pagination(
    p1_client: TestClient,
):
    from sqlalchemy import delete
    from app.models.models import AuditLog

    # Clear seed audit logs so we count exact 1 row per action
    with db_mod.SessionLocal() as db:
        db.execute(delete(AuditLog))
        db.commit()

    # 1. login_failed (1)
    assert (
        p1_client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "wrong_password"},
        ).status_code
        == 401
    )

    # 2. login_success (1)
    mgr_login = p1_client.post(
        "/api/v1/auth/login",
        json={"username": "manager", "password": "manager123"},
    )
    assert mgr_login.status_code == 200
    mgr_hdr = {"Authorization": f"Bearer {mgr_login.json()['accessToken']}"}

    # 3. ack_event (1)
    ev_page = p1_client.get("/api/v1/events?acked=false&pageSize=1", headers=mgr_hdr).json()
    ev_id = ev_page["items"][0]["id"]
    assert (
        p1_client.post(
            f"/api/v1/events/{ev_id}/ack",
            json={"note": "Kiểm tra audit ack"},
            headers=mgr_hdr,
        ).status_code
        == 200
    )

    # 4. update_settings (1)
    assert (
        p1_client.put(
            "/api/v1/settings",
            json={
                "continuousWarnSec": 7200,
                "continuousCriticalSec": 10800,
                "restResetMin": 20,
                "shareLocation": True,
                "heartbeatIntervalSec": 30,
            },
            headers=mgr_hdr,
        ).status_code
        == 200
    )

    # 5. create_driver (1)
    assert (
        p1_client.post(
            "/api/v1/drivers",
            json={"fullName": "Lê Audit", "phone": "0912345999", "username": "drv_audit"},
            headers=mgr_hdr,
        ).status_code
        == 201
    )

    # 6. create_pairing (1)
    assert (
        p1_client.post(
            "/api/v1/pairing-codes",
            json={"expiresInMinutes": 60},
            headers=mgr_hdr,
        ).status_code
        == 200
    )

    # 7 & 8. create_api_key (1) & revoke_api_key (1)
    ak_res = p1_client.post(
        "/api/v1/api-keys",
        json={"name": "ERP Key", "scopes": ["events:read"]},
        headers=mgr_hdr,
    )
    assert ak_res.status_code == 201
    ak_id = ak_res.json()["id"]
    assert p1_client.delete(f"/api/v1/api-keys/{ak_id}", headers=mgr_hdr).status_code == 200

    # 9. export_report (1)
    rep_res = p1_client.post(
        "/api/v1/reports/export",
        json={"reportType": "weekly", "fileFormat": "pdf"},
        headers=mgr_hdr,
    )
    assert rep_res.status_code == 201

    # Verify paginated API for manager (9 actions total, exact 1 per action!)
    page1 = p1_client.get("/api/v1/audit-logs?page=1&pageSize=5", headers=mgr_hdr)
    assert page1.status_code == 200
    p1_data = page1.json()
    assert p1_data["total"] == 9
    assert len(p1_data["items"]) == 5

    page2 = p1_client.get("/api/v1/audit-logs?page=2&pageSize=5", headers=mgr_hdr).json()
    assert len(page2["items"]) == 4

    all_actions = [x["action"] for x in p1_data["items"] + page2["items"]]
    expected_actions = [
        "login_failed",
        "login_success",
        "ack_event",
        "update_settings",
        "create_driver",
        "create_pairing",
        "create_api_key",
        "revoke_api_key",
        "export_report",
    ]
    for act in expected_actions:
        assert all_actions.count(act) == 1, f"Expected exact 1 audit row for {act}, got {all_actions.count(act)}"

    # Dispatcher MUST be forbidden from reading audit logs
    disp_login = p1_client.post(
        "/api/v1/auth/login",
        json={"username": "dispatcher", "password": "dispatcher123"},
    ).json()
    disp_hdr = {"Authorization": f"Bearer {disp_login['accessToken']}"}
    assert p1_client.get("/api/v1/audit-logs", headers=disp_hdr).status_code == 403


def test_p1_5_strict_multi_tenant_isolation_uuid_guessing_sse_and_reports(
    p1_client: TestClient,
):
    from app.core.security import create_access_token
    from app.services.seed import ORG_ID, ORG_2_ID

    # Login as Org A (manager, dispatcher, driver1) and Org B (manager2, driver6)
    mgr_a = p1_client.post(
        "/api/v1/auth/login", json={"username": "manager", "password": "manager123"}
    ).json()
    mgr_a_hdr = {"Authorization": f"Bearer {mgr_a['accessToken']}"}

    drv_a = p1_client.post(
        "/api/v1/auth/login", json={"username": "driver1", "password": "driver123"}
    ).json()
    drv_a_hdr = {"Authorization": f"Bearer {drv_a['accessToken']}"}

    mgr_b = p1_client.post(
        "/api/v1/auth/login", json={"username": "manager2", "password": "manager123"}
    ).json()
    mgr_b_hdr = {"Authorization": f"Bearer {mgr_b['accessToken']}"}

    drv_b = p1_client.post(
        "/api/v1/auth/login", json={"username": "driver6", "password": "driver123"}
    ).json()
    drv_b_hdr = {"Authorization": f"Bearer {drv_b['accessToken']}"}

    # Org B creates resources: pairing code, API key, report, active session + CRITICAL event
    drv_b_list = p1_client.get("/api/v1/drivers", headers=mgr_b_hdr).json()
    assert len(drv_b_list) == 5
    drv_b_id = drv_b["user"]["id"]
    veh_b_id = drv_b_list[0]["vehicleId"]

    pair_b = p1_client.post(
        "/api/v1/pairing-codes",
        json={"vehicleId": veh_b_id, "expiresInMinutes": 60},
        headers=mgr_b_hdr,
    ).json()
    ak_b = p1_client.post(
        "/api/v1/api-keys",
        json={"name": "Org B Secret Key"},
        headers=mgr_b_hdr,
    ).json()
    rep_b = p1_client.post(
        "/api/v1/reports/export",
        json={"reportType": "weekly", "fileFormat": "pdf"},
        headers=mgr_b_hdr,
    ).json()

    sse_broker.clear_history(ORG_ID)
    sse_broker.clear_history(ORG_2_ID)

    sess_b_id = str(uuid4())
    ev_b_id = str(uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    assert (
        p1_client.post(
            "/api/v1/sessions",
            json={"sessionId": sess_b_id, "startedAt": now_iso},
            headers=drv_b_hdr,
        ).status_code
        == 200
    )
    assert (
        p1_client.post(
            f"/api/v1/sessions/{sess_b_id}/events",
            json={
                "eventId": ev_b_id,
                "type": "DROWSINESS",
                "level": "CRITICAL",
                "status": "OPEN",
                "state": "CRITICAL",
                "riskScore": 0.96,
                "startedAt": now_iso,
                "durationSec": 4,
                "capturedAt": now_iso,
            },
            headers=drv_b_hdr,
        ).status_code
        == 200
    )

    # --- 1. SSE Isolation: Org B emitted CRITICAL alert, Org A must have 0 messages! ---
    assert len(sse_broker.get_recent_messages(ORG_2_ID)) >= 2
    assert len(sse_broker.get_recent_messages(ORG_ID)) == 0

    sse_a_text = p1_client.get(
        "/api/v1/live/stream?max_events=5", headers=mgr_a_hdr
    ).text
    assert drv_b_id not in sse_a_text
    assert ev_b_id not in sse_a_text

    # --- 2. UUID Guessing across ALL endpoints by Org A Manager & Driver ---
    # Cannot read Org B driver detail or stats
    assert p1_client.get(f"/api/v1/drivers/{drv_b_id}", headers=mgr_a_hdr).status_code == 404
    assert p1_client.get(f"/api/v1/drivers/{drv_b_id}/stats", headers=mgr_a_hdr).status_code == 404

    # Cannot see Org B events even when passing Org B driverId or organizationId query param
    ev_leak_check = p1_client.get(
        f"/api/v1/events?driverId={drv_b_id}&organizationId={ORG_2_ID}",
        headers=mgr_a_hdr,
    ).json()
    assert ev_leak_check["total"] == 0

    # Cannot ack Org B event by UUID
    assert (
        p1_client.post(
            f"/api/v1/events/{ev_b_id}/ack",
            json={"note": "cross-tenant hijack"},
            headers=mgr_a_hdr,
        ).status_code
        == 404
    )

    # Cannot create pairing code or driver attached to Org B's vehicle UUID
    assert (
        p1_client.post(
            "/api/v1/pairing-codes",
            json={"vehicleId": veh_b_id},
            headers=mgr_a_hdr,
        ).status_code
        == 404
    )
    assert (
        p1_client.post(
            "/api/v1/drivers",
            json={"fullName": "Cross Veh", "phone": "0977111222", "vehicleId": veh_b_id},
            headers=mgr_a_hdr,
        ).status_code
        == 404
    )

    # Driver A cannot pair using Org B's pairing code!
    assert (
        p1_client.post(
            "/api/v1/auth/pair",
            json={"code": pair_b["code"]},
            headers=drv_a_hdr,
        ).status_code
        == 404
    )

    # Driver A cannot post heartbeat/events/end or hijack Org B's session UUID
    assert (
        p1_client.post(
            "/api/v1/sessions",
            json={"sessionId": sess_b_id, "startedAt": now_iso},
            headers=drv_a_hdr,
        ).status_code
        == 403
    )
    assert (
        p1_client.post(
            f"/api/v1/sessions/{sess_b_id}/heartbeat",
            json={
                "state": "NORMAL",
                "imageQuality": "GOOD",
                "continuousDrivingSec": 10,
                "vehicleMoving": True,
                "capturedAt": now_iso,
            },
            headers=drv_a_hdr,
        ).status_code
        == 404
    )

    # Cannot read or revoke Org B's API keys or reports
    org_a_keys = p1_client.get("/api/v1/api-keys", headers=mgr_a_hdr).json()
    assert all(k["id"] != ak_b["id"] for k in org_a_keys)
    assert p1_client.delete(f"/api/v1/api-keys/{ak_b['id']}", headers=mgr_a_hdr).status_code == 404

    org_a_reports = p1_client.get("/api/v1/reports", headers=mgr_a_hdr).json()
    assert all(r["id"] != rep_b["id"] for r in org_a_reports)
    assert p1_client.get(f"/api/v1/reports/{rep_b['id']}", headers=mgr_a_hdr).status_code == 404

    # Audit logs strictly isolated
    org_a_audits = p1_client.get("/api/v1/audit-logs?pageSize=100", headers=mgr_a_hdr).json()
    assert all(item["organizationId"] == ORG_ID for item in org_a_audits["items"])

    # Forged/mismatched org claim in JWT (user belongs to Org A, token claims Org B) -> 401 ORG_MISMATCH
    mismatched_token = create_access_token(
        user_id=mgr_a["user"]["id"], role="manager", organization_id=ORG_2_ID
    )
    mismatch_res = p1_client.get(
        "/api/v1/live", headers={"Authorization": f"Bearer {mismatched_token}"}
    )
    assert mismatch_res.status_code == 401
    assert mismatch_res.json()["error"]["code"] == "ORG_MISMATCH"




