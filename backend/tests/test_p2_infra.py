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


