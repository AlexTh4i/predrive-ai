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

