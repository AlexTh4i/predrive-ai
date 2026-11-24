"""Align schema to Supabase Production v1 (22 tables, UUID, enums, RLS, views, functions)

Revision ID: 0002_production_v1
Revises: 0001_initial_m3
Create Date: 2026-11-18 11:50:00

"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.database import Base
import app.models.models  # noqa: F401

revision: str = "0002_production_v1"
down_revision: Union[str, None] = "0001_initial_m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_M3_TABLES = [
    "locations",
    "settings",
    "heartbeats",
    "events",
    "sessions",
    "pairings",
    "users",
    "vehicles",
    "organizations",
]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Drop M3 prototype string-PK tables created by 0001_initial_m3 before applying
    # the canonical 22-table UUID/Enum production schema.
    for tbl in LEGACY_M3_TABLES:
        if dialect == "postgresql":
            op.execute(sa.text(f'DROP TABLE IF EXISTS "{tbl}" CASCADE'))
        else:
            op.execute(sa.text(f'DROP TABLE IF EXISTS "{tbl}"'))

    if dialect == "postgresql":
        root_dir = Path(__file__).resolve().parent.parent.parent.parent
        schema_sql_path = root_dir / "supabase" / "schema.sql"
        raw_conn = bind.connection.dbapi_connection
        with raw_conn.cursor() as cur:
            cur.execute(schema_sql_path.read_text(encoding="utf-8"))
    else:
        Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    all_tables = [t.name for t in reversed(Base.metadata.sorted_tables)]
    if dialect == "postgresql":
        op.execute(sa.text("DROP VIEW IF EXISTS v_events_pending_escalation CASCADE"))
        op.execute(sa.text("DROP VIEW IF EXISTS v_driver_usage_7d CASCADE"))
        op.execute(
            sa.text(
                "DROP FUNCTION IF EXISTS public.nearest_rest_stops("
                "double precision, double precision, int, uuid) CASCADE"
            )
        )
        op.execute(sa.text("DROP FUNCTION IF EXISTS public.purge_old_data() CASCADE"))
        op.execute(sa.text("DROP FUNCTION IF EXISTS public.current_org_id() CASCADE"))
        for tbl in all_tables:
            op.execute(sa.text(f'DROP TABLE IF EXISTS "{tbl}" CASCADE'))
        for enum_name in (
            "session_status",
            "event_status",
            "event_type",
            "vehicle_type",
            "user_role",
        ):
            op.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name} CASCADE"))
    else:
        for tbl in all_tables:
            op.execute(sa.text(f'DROP TABLE IF EXISTS "{tbl}"'))
