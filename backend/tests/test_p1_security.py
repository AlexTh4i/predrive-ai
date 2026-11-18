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
