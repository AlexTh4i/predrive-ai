#!/usr/bin/env bash
# Push PreDrive AI schema (and dev seed when ENV != production) to Supabase / PostgreSQL.
# SECURITY RULE (R4): NEVER echo, print, or log SUPABASE_DB_URL or credentials.
set -euo pipefail
set +x

if [[ -z "${SUPABASE_DB_URL:-}" ]]; then
  echo "ERROR: SUPABASE_DB_URL environment variable is not set." >&2
  echo "Example (Session Pooler IPv4, eu-west-1):" >&2
  echo "  export SUPABASE_DB_URL='postgresql://postgres.zpbskfqabxdhpdphqnjo:<PASSWORD>@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require'" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
export PREDRIVE_ROOT_DIR="${ROOT_DIR}"
export SUPABASE_REGION="${SUPABASE_REGION:-eu-west-1}"
export ENV="${ENV:-development}"

# Find Python interpreter with psycopg installed
if [[ -x "${ROOT_DIR}/.venv/Scripts/python.exe" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/Scripts/python.exe"
elif [[ -x "${ROOT_DIR}/.venv/bin/python" ]]; then
  PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

"${PYTHON_BIN}" - <<'PY'
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import psycopg

raw_url = os.environ["SUPABASE_DB_URL"].strip()
if raw_url.startswith("postgresql+psycopg://"):
    raw_url = "postgresql://" + raw_url[len("postgresql+psycopg://") :]
elif raw_url.startswith("postgres://"):
    raw_url = "postgresql://" + raw_url[len("postgres://") :]

region = os.environ.get("SUPABASE_REGION", "eu-west-1").strip()
env_mode = os.environ.get("ENV", "development").strip().lower()
root_dir = Path(os.environ["PREDRIVE_ROOT_DIR"])
schema_sql = (root_dir / "supabase" / "schema.sql").read_text(encoding="utf-8")
seed_sql = (root_dir / "supabase" / "seed.sql").read_text(encoding="utf-8")


def ensure_ssl_if_supabase(u: str) -> str:
    parts = urlsplit(u)
    if "supabase.co" in (parts.hostname or "") or "supabase.com" in (parts.hostname or ""):
        q = dict(parse_qsl(parts.query, keep_blank_values=True))
        q.setdefault("sslmode", "require")
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))
    return u


def build_session_pooler_fallback(u: str) -> str | None:
    parts = urlsplit(u)
    host = parts.hostname or ""
    m = re.match(r"^db\.([a-z0-9]+)\.supabase\.co$", host)
    if not m:
        return None
    project_ref = m.group(1)
    user = parts.username or "postgres"
    if "." not in user:
        user = f"{user}.{project_ref}"
    pwd = parts.password or ""
    auth = f"{user}:{pwd}@" if pwd else f"{user}@"
    pooler_netloc = f"{auth}aws-0-{region}.pooler.supabase.com:5432"
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q.setdefault("sslmode", "require")
    return urlunsplit((parts.scheme, pooler_netloc, parts.path or "/postgres", urlencode(q), parts.fragment))


target_url = ensure_ssl_if_supabase(raw_url)
conn = None
try:
    conn = psycopg.connect(target_url, autocommit=True, connect_timeout=10)
except psycopg.OperationalError as exc:
    fallback_url = build_session_pooler_fallback(target_url)
    if fallback_url is None:
        print(f"ERROR: Database connection failed ({exc.__class__.__name__}).", file=sys.stderr)
        sys.exit(2)
    print(f"Direct host unreachable (likely IPv6-only); retrying via Supabase Session Pooler ({region})...")
    conn = psycopg.connect(fallback_url, autocommit=True, connect_timeout=10)

ALL_TABLES = [
    "organizations", "users", "vehicles", "pairings", "sessions", "events",
    "heartbeats", "settings", "locations", "rest_stops", "rest_breaks",
    "escalation_policies", "escalations", "risk_scores", "reports",
    "app_usage_daily", "refresh_tokens", "audit_logs", "push_tokens",
    "consents", "api_keys", "webhooks",
]

with conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY(%s)",
            (ALL_TABLES,),
        )
        existing_count = cur.fetchone()[0]
        if existing_count > 0:
            print(
                f"ABORTED: Target database already contains {existing_count} PreDrive table(s). "
                "Refusing destructive schema reset.",
                file=sys.stderr,
            )
            sys.exit(3)

        print("1/3 Applying supabase/schema.sql...")
        cur.execute(schema_sql)

        if env_mode == "production":
            print("2/3 ENV=production detected -> skipping supabase/seed.sql (strict R5 policy).")
        else:
            print(f"2/3 ENV={env_mode} -> applying supabase/seed.sql...")
            cur.execute(seed_sql)

        print("3/3 Verifying RLS (pg_tables.rowsecurity) and table row counts...")
        cur.execute(
            "SELECT tablename, rowsecurity FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename = ANY(%s) ORDER BY tablename",
            (ALL_TABLES,),
        )
        rls_rows = cur.fetchall()
        missing_rls = [t for (t, rls) in rls_rows if not rls]
        if len(rls_rows) != len(ALL_TABLES) or missing_rls:
            print(f"ERROR: RLS check failed! Missing/disabled RLS: {missing_rls}", file=sys.stderr)
            sys.exit(4)

        print(f"RLS verified: {len(rls_rows)}/{len(ALL_TABLES)} tables have rowsecurity=true.")
        for tbl in ALL_TABLES:
            cur.execute(f'SELECT count(*) FROM "{tbl}"')
            cnt = cur.fetchone()[0]
            print(f"  {tbl:22s}: {cnt}")

conn.close()
print("Push completed successfully.")
PY
