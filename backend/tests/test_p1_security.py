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

