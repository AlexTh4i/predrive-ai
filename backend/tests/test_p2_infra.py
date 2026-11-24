from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


def test_p2_1_dockerfiles_and_compose_healthchecks():
    assert (ROOT_DIR / "backend" / "Dockerfile").exists()
    assert (ROOT_DIR / "admin-web" / "Dockerfile").exists()
    assert (ROOT_DIR / "admin-web" / "nginx.conf").exists()
    assert (ROOT_DIR / "docker-compose.yml").exists()

    # Validate docker compose config with --profile local and inspect JSON output
    res = subprocess.run(
        ["docker", "compose", "--profile", "local", "config", "--format", "json"],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode == 0, res.stderr
    parsed = json.loads(res.stdout)
    services = parsed["services"]

    expected_services = {
        "postgres",
        "redis",
        "backend",
        "admin-web",
        "caddy",
        "prometheus",
        "grafana",
    }
    assert expected_services.issubset(set(services.keys()))

    # Every service MUST declare a healthcheck
    for svc_name in expected_services:
        assert "healthcheck" in services[svc_name], f"Missing healthcheck on {svc_name}"

    # Postgres must belong to profile 'local'
    assert "local" in services["postgres"].get("profiles", [])


def test_p2_2_caddyfile_https_sse_flush_and_grafana_subdomain():
    caddyfile = (ROOT_DIR / "infra" / "caddy" / "Caddyfile").read_text(encoding="utf-8")
    assert "flush_interval -1" in caddyfile
    assert "/api/*" in caddyfile
    assert "admin-web:80" in caddyfile
    assert "grafana:3000" in caddyfile


def test_p2_3_github_actions_ci_cd_with_schema_check_and_rollback():
    ci_file = ROOT_DIR / ".github" / "workflows" / "ci.yml"
    assert ci_file.exists()
    content = ci_file.read_text(encoding="utf-8")
    assert "postgres:15-alpine" in content
    assert "supabase/schema.sql" in content
    assert "playwright test" in content or "npm test" in content
    assert "Rolling back to" in content


def test_p2_4_prometheus_metrics_grafana_dashboard_and_sentry_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from fastapi.testclient import TestClient
    import sentry_sdk

    from app.core import database as db_mod
    from app.main import app
    from app.services.observability import init_sentry_if_configured

    db_url = f"sqlite:///{(tmp_path / 'p2_obs.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("PREDRIVE_ENABLE_WATCHDOG", "0")
    db_mod.reset_engine(db_url)
    db_mod.Base.metadata.create_all(bind=db_mod.engine)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        m_res = client.get("/metrics")
        assert m_res.status_code == 200
        text_out = m_res.text
        for required_metric in (
            "predrive_active_sessions",
            "predrive_disconnected_drivers",
            "predrive_events_last_hour",
            "predrive_http_request_duration_seconds",
            "predrive_sse_publish_latency_seconds",
            "predrive_db_up 1.0",
        ):
            assert required_metric in text_out, f"Missing metric {required_metric}"

    # Verify Grafana provisioning & dashboard JSON
    dash_path = ROOT_DIR / "infra" / "grafana" / "dashboards" / "predrive-overview.json"
    dash = json.loads(dash_path.read_text(encoding="utf-8"))
    assert dash["uid"] == "predrive-overview"
    assert len(dash["panels"]) >= 6

    alerts_yml = (ROOT_DIR / "infra" / "prometheus" / "alerts.yml").read_text(encoding="utf-8")
    assert "PreDriveDatabaseDown" in alerts_yml
    assert "PreDriveHighApiErrorRate" in alerts_yml
    assert "PreDriveNoHeartbeatsForActiveSessions" in alerts_yml

    # Verify Sentry SDK test error capture via custom transport (no external DSN needed)
    captured_envelopes: list[object] = []
    monkeypatch.setenv("SENTRY_DSN", "https://public@sentry.example.invalid/1")
    assert init_sentry_if_configured(transport=captured_envelopes.append) is True
    try:
        raise RuntimeError("PreDrive P2-4 Sentry probe error")
    except RuntimeError as exc:
        sentry_sdk.capture_exception(exc)
    sentry_sdk.flush(timeout=2.0)
    assert len(captured_envelopes) >= 1


def test_p2_5_backup_script_and_restore_drill_on_postgres15(tmp_path: Path):
    import os
    import shutil
    from uuid import uuid4
    from sqlalchemy import create_engine, text

    assert (ROOT_DIR / "docs" / "backup-restore.md").exists()
    script_path = ROOT_DIR / "scripts" / "backup.sh"
    assert script_path.exists()

    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    bash_bin = str(git_bash) if git_bash.exists() else shutil.which("bash")
    assert bash_bin is not None

    backup_dir = tmp_path / "backups"
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql://predrive:predrive_local_dev@127.0.0.1:54329/predrive"
    env["BACKUP_DIR"] = str(backup_dir.as_posix())

    res = subprocess.run(
        [bash_bin, str(script_path.as_posix())],
        cwd=str(ROOT_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert res.returncode == 0, res.stderr
    assert "predrive_local_dev" not in res.stdout
    dumps = list(backup_dir.glob("predrive_*.dump"))
    assert len(dumps) == 1 and dumps[0].stat().st_size > 1000
    assert (backup_dir / f"{dumps[0].name}.sha256").exists()

    # Restore drill into temporary Postgres 15 database
    drill_db = f"predrive_drill_{uuid4().hex[:8]}"
    admin_url = "postgresql+psycopg://predrive:predrive_local_dev@127.0.0.1:54329/postgres"
    admin_eng = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_eng.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{drill_db}"'))
    try:
        with dumps[0].open("rb") as fh:
            restore_res = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    "predrive-pg15",
                    "pg_restore",
                    "-U",
                    "predrive",
                    "-d",
                    drill_db,
                    "--no-owner",
                    "--no-privileges",
                ],
                stdin=fh,
                capture_output=True,
                timeout=30,
            )
        assert restore_res.returncode == 0, restore_res.stderr.decode("utf-8", errors="ignore")

        drill_eng = create_engine(
            f"postgresql+psycopg://predrive:predrive_local_dev@127.0.0.1:54329/{drill_db}"
        )
        with drill_eng.connect() as dconn:
            total_t, rls_t = dconn.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE rowsecurity) "
                    "FROM pg_tables WHERE schemaname='public'"
                )
            ).one()
            assert total_t == 22 and rls_t == 22
        drill_eng.dispose()
    finally:
        with admin_eng.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": drill_db},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{drill_db}"'))
        admin_eng.dispose()


def test_p2_6_retention_settings_and_purge_deletes_expired_keeps_fresh_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    from datetime import datetime, timedelta, timezone
    import logging
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from app.core import database as db_mod
    from app.main import app
    from app.models.models import AuditLog, EventModel, HeartbeatModel, LocationModel
    from app.services.seed import ORG_ID, det_uuid
    from app.services.watchdog import purge_expired_organization_data

    db_url = f"sqlite:///{(tmp_path / 'p2_ret.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("PREDRIVE_ENABLE_WATCHDOG", "0")
    db_mod.reset_engine(db_url)
    db_mod.Base.metadata.create_all(bind=db_mod.engine)

    with TestClient(app) as client:
        mgr = client.post(
            "/api/v1/auth/login", json={"username": "manager", "password": "manager123"}
        ).json()
        mgr_hdr = {"Authorization": f"Bearer {mgr['accessToken']}"}

        # Manager updates retention policy via PUT /api/v1/settings
        upd = client.put(
            "/api/v1/settings",
            json={
                "continuousWarnSec": 7200,
                "continuousCriticalSec": 10800,
                "restResetMin": 15,
                "shareLocation": True,
                "heartbeatIntervalSec": 30,
                "heartbeatRetentionDays": 5,
                "locationRetentionDays": 10,
                "eventRetentionDays": 15,
                "auditRetentionDays": 20,
            },
            headers=mgr_hdr,
        )
        assert upd.status_code == 200
        assert upd.json()["heartbeatRetentionDays"] == 5
        assert upd.json()["eventRetentionDays"] == 15

        now = datetime.now(timezone.utc)
        drv_id = det_uuid("drv-1")
        sess_id = str(uuid4())
        open_ev_old_id = str(uuid4())
        closed_ev_old_id = str(uuid4())
        closed_ev_fresh_id = str(uuid4())

        with db_mod.SessionLocal() as db:
            from app.models.models import SessionModel

            db.add(
                SessionModel(
                    id=sess_id,
                    organization_id=ORG_ID,
                    driver_id=drv_id,
                    status="active",
                    started_at=now - timedelta(days=40),
                    current_state="NORMAL",
                )
            )
            db.flush()
            # 1 old CLOSED event (40d > 15d -> MUST be deleted)
            db.add(
                EventModel(
                    id=closed_ev_old_id,
                    organization_id=ORG_ID,
                    session_id=sess_id,
                    driver_id=drv_id,
                    client_event_id=closed_ev_old_id,
                    type="DROWSINESS",
                    level="WARNING",
                    status="CLOSED",
                    occurred_at=now - timedelta(days=40),
                    created_at=now - timedelta(days=40),
                )
            )
            # 1 old OPEN event (40d > 15d, but OPEN -> MUST be preserved!)
            db.add(
                EventModel(
                    id=open_ev_old_id,
                    organization_id=ORG_ID,
                    session_id=sess_id,
                    driver_id=drv_id,
                    client_event_id=open_ev_old_id,
                    type="DROWSINESS",
                    level="CRITICAL",
                    status="OPEN",
                    occurred_at=now - timedelta(days=40),
                    created_at=now - timedelta(days=40),
                )
            )
            # 1 fresh CLOSED event (2d < 15d -> MUST be preserved!)
            db.add(
                EventModel(
                    id=closed_ev_fresh_id,
                    organization_id=ORG_ID,
                    session_id=sess_id,
                    driver_id=drv_id,
                    client_event_id=closed_ev_fresh_id,
                    type="DROWSINESS",
                    level="WARNING",
                    status="CLOSED",
                    occurred_at=now - timedelta(days=2),
                    created_at=now - timedelta(days=2),
                )
            )
            # 1 old heartbeat (8d > 5d) + 1 fresh heartbeat (1d < 5d)
            old_hb = HeartbeatModel(
                organization_id=ORG_ID,
                session_id=sess_id,
                driver_id=drv_id,
                state="NORMAL",
                ts=now - timedelta(days=8),
            )
            fresh_hb = HeartbeatModel(
                organization_id=ORG_ID,
                session_id=sess_id,
                driver_id=drv_id,
                state="NORMAL",
                ts=now - timedelta(days=1),
            )
            old_loc = LocationModel(
                organization_id=ORG_ID,
                session_id=sess_id,
                driver_id=drv_id,
                lat=10.7,
                lng=106.6,
                ts=now - timedelta(days=12),
            )
            old_aud = AuditLog(
                organization_id=ORG_ID,
                actor_id=mgr["user"]["id"],
                action="old_action",
                created_at=now - timedelta(days=25),
            )
            db.add_all([old_hb, fresh_hb, old_loc, old_aud])
            db.commit()
            fresh_hb_id = fresh_hb.id
            old_hb_id = old_hb.id

            with caplog.at_level(logging.INFO, logger="predrive.watchdog"):
                counts = purge_expired_organization_data(db, now_utc=now)

            assert counts["heartbeats"] >= 1
            assert counts["locations"] >= 1
            assert counts["events"] >= 1
            assert counts["audit_logs"] >= 1
            assert any("Retention purge completed" in rec.message for rec in caplog.records)

            # Old rows deleted, fresh rows & OPEN event preserved!
            assert db.get(EventModel, closed_ev_old_id) is None
            assert db.get(EventModel, open_ev_old_id) is not None
            assert db.get(EventModel, closed_ev_fresh_id) is not None
            assert db.get(HeartbeatModel, old_hb_id) is None
            assert db.get(HeartbeatModel, fresh_hb_id) is not None
            assert (
                db.scalar(select(AuditLog).where(AuditLog.action == "old_action"))
                is None
            )


def test_p2_7_redis_sse_pubsub_across_two_backend_instances():
    import asyncio
    from app.services.sse import SSEBroker

    redis_url = "redis://127.0.0.1:63799/0"
    org_a = "11111111-1111-4111-8111-111111111111"
    org_b = "22222222-2222-4222-8222-222222222222"

    async def _run_cross_instance_check() -> None:
        instance_a = SSEBroker(redis_url=redis_url)
        instance_b = SSEBroker(redis_url=redis_url)
        assert instance_a.instance_id != instance_b.instance_id

        try:
            assert instance_a.start_redis_listener() is True
            assert instance_b.start_redis_listener() is True

            # Client for Org A & Client for Org B both connect to Instance B
            queue_org_a_on_b = instance_b.subscribe(org_a)
            queue_org_b_on_b = instance_b.subscribe(org_b)

            # Driver event arrives at Instance A for Org A!
            instance_a.publish(
                org_a,
                "alert",
                {"id": "ev-cross-instance-01", "level": "CRITICAL", "type": "DROWSINESS"},
            )

            # Client on Instance B MUST receive the event via Redis Pub/Sub!
            msg = await asyncio.wait_for(queue_org_a_on_b.get(), timeout=3.0)
            assert msg["event"] == "alert"
            parsed = json.loads(msg["data"])
            assert parsed["id"] == "ev-cross-instance-01"
            assert parsed["level"] == "CRITICAL"

            # Org B subscriber on Instance B must NOT receive Org A's message!
            assert queue_org_b_on_b.empty()
        finally:
            instance_a.stop_redis_listener()
            instance_b.stop_redis_listener()

    asyncio.run(_run_cross_instance_check())





