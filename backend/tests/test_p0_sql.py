from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
SCHEMA_SQL = ROOT_DIR / "supabase" / "schema.sql"
SEED_SQL = ROOT_DIR / "supabase" / "seed.sql"

PG_TEST_ADMIN_URL = os.getenv(
    "PREDRIVE_TEST_PG_ADMIN_URL",
    "postgresql+psycopg://predrive:predrive_local_dev@127.0.0.1:54329/postgres",
)


def _pg_available() -> bool:
    try:
        eng = create_engine(PG_TEST_ADMIN_URL, connect_args={"connect_timeout": 3})
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


@pytest.fixture()
def isolated_pg_db():
    if not _pg_available():
        pytest.fail("Local Postgres 15 container (predrive-pg15:54329) is not reachable")

    db_name = f"predrive_p0_{uuid4().hex[:8]}"
    admin_engine = create_engine(PG_TEST_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    target_url = PG_TEST_ADMIN_URL.rsplit("/", 1)[0] + f"/{db_name}"
    try:
        yield target_url
    finally:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()


def test_p0_1_schema_and_seed_sql_on_clean_postgres15(isolated_pg_db: str):
    raw_psycopg_url = isolated_pg_db.replace("postgresql+psycopg://", "postgresql://")
    import psycopg

    schema_sql = SCHEMA_SQL.read_text(encoding="utf-8")
    seed_sql = SEED_SQL.read_text(encoding="utf-8")

    with psycopg.connect(raw_psycopg_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)

            # Verify RLS enabled on all 22 public tables
            cur.execute(
                "SELECT count(*), count(*) FILTER (WHERE rowsecurity) "
                "FROM pg_tables WHERE schemaname = 'public'"
            )
            total_tables, rls_tables = cur.fetchone()  # type: ignore[misc]
            assert total_tables == 22
            assert rls_tables == 22

            # Verify seed.sql refuses to run when app.env = 'production'
            with pytest.raises(Exception, match="production"):
                with conn.transaction():
                    cur.execute("SET LOCAL app.env = 'production'")
                    cur.execute(seed_sql)

            # Run seed.sql in dev mode
            cur.execute(seed_sql)

            expected_counts = {
                "organizations": 3,
                "users": 20,
                "vehicles": 20,
                "pairings": 20,
                "sessions": 20,
                "events": 20,
                "heartbeats": 20,
                "settings": 3,
                "locations": 20,
                "rest_stops": 20,
                "rest_breaks": 20,
                "escalation_policies": 9,
                "escalations": 20,
                "risk_scores": 20,
                "reports": 20,
                "app_usage_daily": 20,
                "refresh_tokens": 20,
                "audit_logs": 20,
                "push_tokens": 20,
                "consents": 14,
                "api_keys": 6,
                "webhooks": 6,
            }
            for tbl, expected in expected_counts.items():
                cur.execute(f"SELECT count(*) FROM {tbl}")
                actual = cur.fetchone()[0]  # type: ignore[index]
                assert actual == expected, f"Table {tbl}: expected {expected}, got {actual}"

            # Verify views & functions execute without error
            cur.execute("SELECT count(*) FROM v_events_pending_escalation")
            assert cur.fetchone()[0] >= 1  # type: ignore[index]

            cur.execute("SELECT count(*) FROM v_driver_usage_7d")
            assert cur.fetchone()[0] == 14  # type: ignore[index]

            cur.execute("SELECT id, distance_km FROM public.nearest_rest_stops(20.9, 105.85, 3)")
            stops = cur.fetchall()
            assert len(stops) == 3
            assert stops[0][1] <= stops[1][1] <= stops[2][1]

            cur.execute("SELECT public.purge_old_data()")
            purge_res = cur.fetchone()[0]  # type: ignore[index]
            assert "heartbeats" in purge_res

    # Test hash_seed_passwords.py helper
    from scripts.hash_seed_passwords import hash_unset_passwords

    updated = hash_unset_passwords(isolated_pg_db)
    assert updated == 20
