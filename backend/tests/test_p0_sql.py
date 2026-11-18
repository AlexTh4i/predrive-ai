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


def test_p0_3_supabase_pooler_url_and_full_m3_suite_on_postgres15(
    isolated_pg_db: str, monkeypatch: pytest.MonkeyPatch
):
    from fastapi.testclient import TestClient
    from sqlalchemy.pool import NullPool

    from app.core import database as db_mod
    from app.core.config import normalize_database_url
    from app.main import app
    from app.services.sse import sse_broker
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "m3_tests_mod", Path(__file__).resolve().parent / "test_m3_backend.py"
    )
    assert spec and spec.loader
    m3_tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m3_tests)

    # 1. Verify Supabase URL normalization & pooler handling
    supa_session_url = normalize_database_url(
        "postgres://postgres.ref:pwd@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
    )
    assert supa_session_url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in supa_session_url

    supa_tx_url = (
        "postgres://postgres.ref:pwd@aws-0-eu-west-1.pooler.supabase.com:6543/postgres?pgbouncer=true"
    )
    tx_eng = db_mod.build_engine(supa_tx_url)
    assert isinstance(tx_eng.pool, NullPool)
    tx_eng.dispose()

    # 2. Apply schema.sql to isolated_pg_db, then run EVERY M3 integration test on Postgres 15!
    import psycopg

    raw_psycopg_url = isolated_pg_db.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(raw_psycopg_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL.read_text(encoding="utf-8"))

    monkeypatch.setenv("DATABASE_URL", isolated_pg_db)
    monkeypatch.setenv("PREDRIVE_ENABLE_WATCHDOG", "0")
    db_mod.reset_engine(isolated_pg_db)
    sse_broker.clear_history()

    with TestClient(app) as pg_client:
        m3_tests.test_step1_seed_idempotency_and_2am_4am_peak(pg_client)
        m3_tests.test_step2_auth_rbac_and_org_isolation(pg_client)
        m3_tests.test_step3_idempotency_out_of_order_events_and_delayed(pg_client)
        m3_tests.test_step6_heartbeat_watchdog_disconnect_and_auto_recovery(pg_client)
        m3_tests.test_step7_simulate_driver_and_openapi_contract(pg_client)
        m3_tests.test_step4_and_step5_web_endpoints_div_by_zero_and_sse(pg_client)


def test_p0_4_production_startup_creates_zero_users(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from fastapi.testclient import TestClient
    from sqlalchemy import func, select

    from app.core import database as db_mod
    from app.main import app
    from app.models.models import Organization, User
    from app.services.seed import seed_database

    prod_db = tmp_path / "prod_empty.db"
    prod_url = f"sqlite:///{prod_db.as_posix()}"
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("DATABASE_URL", prod_url)
    monkeypatch.setenv("PREDRIVE_AUTO_SEED", "1")
    monkeypatch.setenv("PREDRIVE_ENABLE_WATCHDOG", "0")

    db_mod.reset_engine(prod_url)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        # Login with default seed credentials MUST fail on production
        res = client.post(
            "/api/v1/auth/login",
            json={"username": "manager", "password": "manager123"},
        )
        assert res.status_code == 401

    with db_mod.SessionLocal() as db:
        assert db.scalar(select(func.count(User.id))) == 0
        assert db.scalar(select(func.count(Organization.id))) == 0
        with pytest.raises(RuntimeError, match="production"):
            seed_database(db)


def test_p0_5_push_to_supabase_script_dev_and_prod(isolated_pg_db: str):
    import shutil
    import subprocess

    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if git_bash.exists():
        bash_bin: str | None = str(git_bash)
    else:
        bash_bin = shutil.which("bash")
    assert bash_bin is not None, "bash not found to run push_to_supabase.sh"

    script_path = str((ROOT_DIR / "scripts" / "push_to_supabase.sh").as_posix())

    # 1. Run in dev mode on isolated_pg_db
    env_dev = os.environ.copy()
    env_dev["SUPABASE_DB_URL"] = isolated_pg_db
    env_dev["ENV"] = "development"
    res_dev = subprocess.run(
        [bash_bin, script_path],
        cwd=str(ROOT_DIR),
        env=env_dev,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res_dev.returncode == 0, res_dev.stderr
    assert "RLS verified: 22/22 tables have rowsecurity=true." in res_dev.stdout
    assert "users" in res_dev.stdout and ": 20" in res_dev.stdout
    assert "predrive_local_dev" not in res_dev.stdout
    assert "predrive_local_dev" not in res_dev.stderr

    # 2. Re-running against non-empty DB must safely abort (exit 3) without destructive drop
    res_abort = subprocess.run(
        [bash_bin, script_path],
        cwd=str(ROOT_DIR),
        env=env_dev,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res_abort.returncode == 3

    # 3. Run in ENV=production on a fresh DB -> skips seed.sql -> 0 users
    prod_db_name = f"predrive_p0_prod_{uuid4().hex[:8]}"
    admin_engine = create_engine(PG_TEST_ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{prod_db_name}"'))
    prod_pg_url = PG_TEST_ADMIN_URL.rsplit("/", 1)[0] + f"/{prod_db_name}"
    try:
        env_prod = os.environ.copy()
        env_prod["SUPABASE_DB_URL"] = prod_pg_url
        env_prod["ENV"] = "production"
        res_prod = subprocess.run(
            [bash_bin, script_path],
            cwd=str(ROOT_DIR),
            env=env_prod,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert res_prod.returncode == 0, res_prod.stderr
        assert "skipping supabase/seed.sql" in res_prod.stdout
        assert "RLS verified: 22/22 tables have rowsecurity=true." in res_prod.stdout
        assert "users                 : 0" in res_prod.stdout
    finally:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": prod_db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{prod_db_name}"'))
        admin_engine.dispose()




