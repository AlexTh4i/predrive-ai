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


def _fetch_public_columns(conn_url: str) -> dict[tuple[str, str], tuple[str, str]]:
    eng = create_engine(conn_url)
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, column_name, udt_name, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "  AND table_name NOT IN ('alembic_version', 'v_events_pending_escalation', 'v_driver_usage_7d') "
                "ORDER BY table_name, column_name"
            )
        ).all()
    eng.dispose()
    return {(r[0], r[1]): (r[2], r[3]) for r in rows}


def test_p0_2_alembic_and_models_match_schema_sql(
    isolated_pg_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from alembic import command
    from alembic.config import Config
    from app.core.database import Base
    import app.models.models  # noqa: F401

    # 1. Run `alembic upgrade head` on clean Postgres 15 isolated_pg_db
    monkeypatch.setenv("DATABASE_URL", isolated_pg_db)
    alembic_cfg = Config(str(ROOT_DIR / "backend" / "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location", str(ROOT_DIR / "backend" / "migrations")
    )
    command.upgrade(alembic_cfg, "head")

    alembic_cols = _fetch_public_columns(isolated_pg_db)
    alembic_tables = {t for (t, _) in alembic_cols}
    assert len(alembic_tables) == 22

    # 2. Create a second clean Postgres DB using SQLAlchemy `Base.metadata.create_all`
    orm_db_name = f"predrive_orm_{uuid4().hex[:8]}"
    admin_engine = create_engine(PG_TEST_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{orm_db_name}"'))
    orm_url = PG_TEST_ADMIN_URL.rsplit("/", 1)[0] + f"/{orm_db_name}"
    try:
        orm_engine = create_engine(orm_url)
        Base.metadata.create_all(bind=orm_engine)
        orm_engine.dispose()
        orm_cols = _fetch_public_columns(orm_url)
    finally:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": orm_db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{orm_db_name}"'))
        admin_engine.dispose()

    # Every (table, column) and nullability + Postgres udt_name must match between schema.sql/Alembic and ORM models!
    assert set(orm_cols.keys()) == set(alembic_cols.keys())
    for key, orm_meta in orm_cols.items():
        alembic_meta = alembic_cols[key]
        # Allow float4 vs float8 equivalence in Postgres (REAL vs DOUBLE PRECISION in Python Float)
        udt_a, null_a = orm_meta
        udt_b, null_b = alembic_meta
        assert null_a == null_b, f"Nullability mismatch on {key}: ORM={null_a} vs SQL={null_b}"
        if {udt_a, udt_b} != {"float4", "float8"}:
            assert udt_a == udt_b, f"Type mismatch on {key}: ORM={udt_a} vs SQL={udt_b}"

    # 3. Also verify `alembic upgrade head` works on clean SQLite
    sqlite_url = f"sqlite:///{(tmp_path / 'alembic_sqlite.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", sqlite_url)
    command.upgrade(alembic_cfg, "head")

