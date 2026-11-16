"""Initial M3 schema for PreDrive AI

Revision ID: 0001_initial_m3
Revises:
Create Date: 2026-11-10 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_m3"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "vehicles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("plate_number", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vehicles_organization_id", "vehicles", ["organization_id"])
    op.create_index("ix_vehicles_org_plate", "vehicles", ["organization_id", "plate_number"])

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=False),
        sa.Column("vehicle_id", sa.String(length=36), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_org_role", "users", ["organization_id", "role"])

    op.create_table(
        "pairings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("vehicle_id", sa.String(length=36), nullable=True),
        sa.Column("driver_id", sa.String(length=36), nullable=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("ix_pairings_organization_id", "pairings", ["organization_id"])
    op.create_index("ix_pairings_code", "pairings", ["code"], unique=True)
    op.create_index("ix_pairings_org_expires", "pairings", ["organization_id", "expires_at"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("driver_id", sa.String(length=36), nullable=False),
        sa.Column("vehicle_id", sa.String(length=36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_driving_sec", sa.Integer(), nullable=False),
        sa.Column("continuous_driving_sec", sa.Integer(), nullable=False),
        sa.Column("unavailable_sec", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("critical_count", sa.Integer(), nullable=False),
        sa.Column("current_state", sa.String(length=32), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sessions_organization_id", "sessions", ["organization_id"])
    op.create_index("ix_sessions_driver_id", "sessions", ["driver_id"])
    op.create_index("ix_sessions_started_at", "sessions", ["started_at"])
    op.create_index("ix_sessions_ended_at", "sessions", ["ended_at"])
    op.create_index("ix_sessions_org_started", "sessions", ["organization_id", "started_at"])
    op.create_index("ix_sessions_driver_started", "sessions", ["driver_id", "started_at"])
    op.create_index("ix_sessions_org_ended", "sessions", ["organization_id", "ended_at"])

    op.create_table(
        "events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("driver_id", sa.String(length=36), nullable=False),
        sa.Column("vehicle_id", sa.String(length=36), nullable=True),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_sec", sa.Integer(), nullable=False),
        sa.Column("delayed", sa.Boolean(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ack_by", sa.String(length=150), nullable=True),
        sa.Column("ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_organization_id", "events", ["organization_id"])
    op.create_index("ix_events_session_id", "events", ["session_id"])
    op.create_index("ix_events_driver_id", "events", ["driver_id"])
    op.create_index("ix_events_type", "events", ["type"])
    op.create_index("ix_events_level", "events", ["level"])
    op.create_index("ix_events_started_at", "events", ["started_at"])
    op.create_index("ix_events_org_started", "events", ["organization_id", "started_at"])
    op.create_index("ix_events_driver_started", "events", ["driver_id", "started_at"])
    op.create_index(
        "ix_events_org_filter", "events", ["organization_id", "level", "type", "ack_at"]
    )

    op.create_table(
        "heartbeats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("driver_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("image_quality", sa.String(length=20), nullable=False),
        sa.Column("vehicle_moving", sa.Boolean(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_heartbeats_organization_id", "heartbeats", ["organization_id"])
    op.create_index("ix_heartbeats_session_id", "heartbeats", ["session_id"])
    op.create_index("ix_heartbeats_driver_id", "heartbeats", ["driver_id"])
    op.create_index("ix_heartbeats_captured_at", "heartbeats", ["captured_at"])
    op.create_index("ix_heartbeats_org_captured", "heartbeats", ["organization_id", "captured_at"])

    op.create_table(
        "settings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("continuous_warn_sec", sa.Integer(), nullable=False),
        sa.Column("continuous_critical_sec", sa.Integer(), nullable=False),
        sa.Column("rest_reset_min", sa.Integer(), nullable=False),
        sa.Column("share_location", sa.Boolean(), nullable=False),
        sa.Column("heartbeat_interval_sec", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id"),
    )
    op.create_index("ix_settings_organization_id", "settings", ["organization_id"], unique=True)

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("driver_id", sa.String(length=36), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["driver_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_locations_organization_id", "locations", ["organization_id"])
    op.create_index("ix_locations_session_id", "locations", ["session_id"])
    op.create_index("ix_locations_driver_id", "locations", ["driver_id"])
    op.create_index("ix_locations_captured_at", "locations", ["captured_at"])
    op.create_index("ix_locations_driver_captured", "locations", ["driver_id", "captured_at"])
    op.create_index("ix_locations_org_captured", "locations", ["organization_id", "captured_at"])


def downgrade() -> None:
    op.drop_table("locations")
    op.drop_table("settings")
    op.drop_table("heartbeats")
    op.drop_table("events")
    op.drop_table("sessions")
    op.drop_table("pairings")
    op.drop_table("users")
    op.drop_table("vehicles")
    op.drop_table("organizations")

