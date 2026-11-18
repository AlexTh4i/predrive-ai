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



