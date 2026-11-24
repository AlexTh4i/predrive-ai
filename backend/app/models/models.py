from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column, synonym
from sqlalchemy.types import TypeDecorator

from ..core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid4())


def new_org_slug() -> str:
    return f"org-{uuid4().hex[:10]}"


class UUIDStr(TypeDecorator[str]):
    """Portable UUID column: native UUID on PostgreSQL, CHAR(36) on SQLite, always str in Python."""

    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.UUID(as_uuid=False))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, UUID):
            return str(value)
        return str(UUID(str(value)))

    def process_result_value(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)


class JSONBType(TypeDecorator[dict[str, Any]]):
    """Native JSONB on PostgreSQL, JSON on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.JSONB())
        return dialect.type_descriptor(JSON())


class INETType(TypeDecorator[str]):
    """Native INET on PostgreSQL, String(64) on SQLite."""

    impl = String(64)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.INET())
        return dialect.type_descriptor(String(64))

    def process_bind_param(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value: Any, dialect: Any) -> Optional[str]:
        if value is None:
            return None
        return str(value)


class StringArrayType(TypeDecorator[list[str]]):
    """Native TEXT[] on PostgreSQL, JSON array on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.ARRAY(Text()))
        return dialect.type_descriptor(JSON())


USER_ROLE_ENUM = SAEnum(
    "manager", "dispatcher", "driver", name="user_role", native_enum=True
)
VEHICLE_TYPE_ENUM = SAEnum(
    "car", "coach", "truck", "container", name="vehicle_type", native_enum=True
)
EVENT_TYPE_ENUM = SAEnum(
    "DROWSY",
    "DROWSINESS",
    "DISTRACTED",
    "HEAD_DOWN",
    "TOO_DARK",
    "NO_FACE",
    "LONG_DRIVING",
    "DISCONNECTED",
    "REST_CLAIM_REJECTED",
    name="event_type",
    native_enum=True,
)
EVENT_STATUS_ENUM = SAEnum(
    "OPEN", "ESCALATED", "CLOSED", name="event_status", native_enum=True
)
SESSION_STATUS_ENUM = SAEnum(
    "active", "ended", "disconnected", name="session_status", native_enum=True
)

BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")


def level_str_to_int(level: str | int) -> int:
    if isinstance(level, int):
        return max(1, min(3, level))
    lvl = str(level).upper()
    if lvl == "CRITICAL":
        return 3
    if lvl == "WARNING":
        return 2
    return 1


def level_int_to_str(level: int | str, api_level: Optional[str] = None) -> str:
    if api_level in ("WARNING", "CRITICAL"):
        return api_level
    if isinstance(level, str):
        if level.upper() in ("WARNING", "CRITICAL"):
            return level.upper()
        try:
            level = int(level)
        except ValueError:
            return "WARNING"
    if level >= 3:
        return "CRITICAL"
    return "WARNING"


# ---------- 1. Core Multi-tenant ----------
class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False, default=new_org_slug
    )
    plan: Mapped[str] = mapped_column(Text, nullable=False, default="pilot")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    plate: Mapped[str] = mapped_column(Text, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(
        VEHICLE_TYPE_ENUM, nullable=False, default="truck"
    )
    brand_model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tracker_device_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "plate", name="vehicles_organization_id_plate_key"),
    )

    def __init__(self, **kwargs: Any) -> None:
        plate_num = kwargs.pop("plate_number", None)
        v_name = kwargs.pop("name", None)
        if "plate" not in kwargs and plate_num is not None:
            kwargs["plate"] = plate_num
        if "brand_model" not in kwargs and v_name is not None:
            plate_val = kwargs.get("plate", "")
            if plate_val and v_name.startswith(f"{plate_val} - "):
                kwargs["brand_model"] = v_name[len(f"{plate_val} - ") :].strip()
            else:
                kwargs["brand_model"] = v_name
        super().__init__(**kwargs)

    @property
    def plate_number(self) -> str:
        return self.plate

    @plate_number.setter
    def plate_number(self, val: str) -> None:
        self.plate = val

    @property
    def name(self) -> str:
        if self.brand_model:
            if self.brand_model.startswith(self.plate):
                return self.brand_model
            return f"{self.plate} - {self.brand_model}"
        return self.plate

    @name.setter
    def name(self, val: str) -> None:
        if self.plate and val.startswith(f"{self.plate} - "):
            self.brand_model = val[len(f"{self.plate} - ") :].strip()
        else:
            self.brand_model = val


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(USER_ROLE_ENUM, nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True, default="")
    zalo_phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    vehicle_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (Index("users_org_role_idx", "organization_id", "role"),)


class Pairing(Base):
    __tablename__ = "pairings"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    vehicle_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    driver_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consented_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        Index("pairings_org_expires_idx", "organization_id", "expires_at"),
    )


class SessionModel(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    driver_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    vehicle_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        SESSION_STATUS_ENUM, nullable=False, default="active"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_driving_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    continuous_driving_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    unavailable_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_state: Mapped[str] = mapped_column(Text, nullable=False, default="NORMAL")
    app_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    device_model: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("sessions_org_status_idx", "organization_id", "status"),
        Index("sessions_driver_idx", "driver_id", "started_at"),
    )


class EventModel(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    driver_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    vehicle_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    client_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(EVENT_TYPE_ENUM, nullable=False)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[str] = mapped_column(
        EVENT_STATUS_ENUM, nullable=False, default="OPEN"
    )
    delayed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    escalated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ack_by: Mapped[Optional[str]] = mapped_column(
        UUIDStr, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ack_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    driver_feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    started_at = synonym("occurred_at")
    received_at = synonym("created_at")

    __table_args__ = (
        CheckConstraint("level >= 1 AND level <= 3", name="events_level_check"),
        CheckConstraint(
            "driver_feedback IS NULL OR driver_feedback IN ('correct', 'false_alarm')",
            name="events_driver_feedback_check",
        ),
        UniqueConstraint(
            "session_id", "client_event_id", name="events_session_id_client_event_id_key"
        ),
        Index("events_org_time_idx", "organization_id", "occurred_at"),
        Index("events_driver_idx", "driver_id", "occurred_at"),
    )

    def __init__(self, **kwargs: Any) -> None:
        if "occurred_at" not in kwargs and "started_at" in kwargs:
            kwargs["occurred_at"] = kwargs.pop("started_at")
        if "created_at" not in kwargs and "received_at" in kwargs:
            kwargs["created_at"] = kwargs.pop("received_at")
        if "client_event_id" not in kwargs:
            kwargs["client_event_id"] = str(kwargs.get("id") or new_uuid())

        metrics_dict = dict(kwargs.get("metrics") or {})
        raw_level = kwargs.get("level", 1)
        if isinstance(raw_level, str):
            metrics_dict.setdefault("api_level", raw_level)
            kwargs["level"] = level_str_to_int(raw_level)

        for key in ("state", "risk_score", "duration_sec"):
            if key in kwargs:
                metrics_dict[key] = kwargs.pop(key)
        if "captured_at" in kwargs:
            cap = kwargs.pop("captured_at")
            if isinstance(cap, datetime):
                metrics_dict["captured_at"] = cap.isoformat()
            elif cap is not None:
                metrics_dict["captured_at"] = str(cap)
        if "ack_by_name" in kwargs:
            metrics_dict["ack_by_name"] = kwargs.pop("ack_by_name")

        kwargs["metrics"] = metrics_dict
        super().__init__(**kwargs)

    @property
    def state(self) -> str:
        m = self.metrics or {}
        if m.get("state"):
            return str(m["state"])
        if self.type == "DISCONNECTED":
            return "DISCONNECTED"
        if self.type == "DISTRACTED":
            return "DISTRACTED"
        if self.type in ("TOO_DARK", "NO_FACE"):
            return "MONITORING_UNAVAILABLE"
        if self.level >= 3:
            return "CRITICAL"
        if self.type in ("DROWSY", "DROWSINESS", "HEAD_DOWN"):
            return "DROWSINESS_SIGNS"
        return "NORMAL"

    @state.setter
    def state(self, val: str) -> None:
        m = dict(self.metrics or {})
        m["state"] = val
        self.metrics = m

    @property
    def risk_score(self) -> Optional[float]:
        m = self.metrics or {}
        val = m.get("risk_score")
        return float(val) if val is not None else None

    @risk_score.setter
    def risk_score(self, val: Optional[float]) -> None:
        m = dict(self.metrics or {})
        m["risk_score"] = val
        self.metrics = m

    @property
    def duration_sec(self) -> int:
        m = self.metrics or {}
        return int(m.get("duration_sec") or 0)

    @duration_sec.setter
    def duration_sec(self, val: int) -> None:
        m = dict(self.metrics or {})
        m["duration_sec"] = int(val)
        self.metrics = m

    @property
    def captured_at(self) -> datetime:
        m = self.metrics or {}
        cap = m.get("captured_at")
        if isinstance(cap, str):
            s = cap[:-1] + "+00:00" if cap.endswith("Z") else cap
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                pass
        return self.occurred_at

    @captured_at.setter
    def captured_at(self, val: datetime) -> None:
        m = dict(self.metrics or {})
        m["captured_at"] = val.isoformat()
        self.metrics = m

    @property
    def level_str(self) -> str:
        m = self.metrics or {}
        return level_int_to_str(self.level, m.get("api_level"))


class HeartbeatModel(Base):
    __tablename__ = "heartbeats"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    driver_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    state: Mapped[str] = mapped_column(Text, nullable=False, default="NORMAL")
    image_quality: Mapped[str] = mapped_column(Text, nullable=False, default="GOOD")
    vehicle_moving: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ear: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    mar: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    battery_pct: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    temp_c: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    captured_at = synonym("ts")

    __table_args__ = (
        CheckConstraint(
            "battery_pct IS NULL OR (battery_pct >= 0 AND battery_pct <= 100)",
            name="heartbeats_battery_pct_check",
        ),
        Index("heartbeats_session_ts_idx", "session_id", "ts"),
        Index("heartbeats_ts_idx", "ts"),
    )


class OrgSettings(Base):
    __tablename__ = "settings"

    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ear_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.28)
    eye_closed_sec: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    head_pose_sec: Mapped[float] = mapped_column(Float, nullable=False, default=1.8)
    too_dark_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=20.0)
    level1_sec: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    level2_sec: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    level3_sec: Mapped[float] = mapped_column(Float, nullable=False, default=4.0)
    ack_timeout_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    continuous_warn_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7200
    )
    continuous_critical_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10800
    )
    max_continuous_drive_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=240
    )
    min_rest_min: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    rest_reminder_before_min: Mapped[int] = mapped_column(
        Integer, nullable=False, default=15
    )
    share_location: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    heartbeat_interval_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    location_interval_sec: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    heartbeat_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    location_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=90
    )
    event_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=365
    )
    audit_retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=730
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    rest_reset_min = synonym("min_rest_min")

    def __init__(self, **kwargs: Any) -> None:
        kwargs.pop("id", None)
        super().__init__(**kwargs)


# ---------- 2. GPS / Map ----------
class LocationModel(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=True,
    )
    vehicle_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("vehicles.id", ondelete="CASCADE"),
        nullable=True,
    )
    driver_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    event_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )

    captured_at = synonym("ts")

    __table_args__ = (
        Index("locations_vehicle_ts_idx", "vehicle_id", "ts"),
        Index("locations_driver_ts_idx", "driver_id", "ts"),
        Index("locations_ts_idx", "ts"),
    )


class RestStop(Base):
    __tablename__ = "rest_stops"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    stop_type: Mapped[str] = mapped_column(Text, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lng: Mapped[float] = mapped_column(Float, nullable=False)
    open_24h: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_truck_parking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            "stop_type IN ('rest_area', 'gas_station', 'restaurant', 'parking')",
            name="rest_stops_stop_type_check",
        ),
    )


# ---------- 3. Driving Hours & Rest Breaks ----------
class RestBreak(Base):
    __tablename__ = "rest_breaks"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    driver_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    drive_min_before: Mapped[int] = mapped_column(Integer, nullable=False)
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    suggested_stop_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("rest_stops.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("rest_breaks_driver_idx", "driver_id", "started_at"),)


# ---------- 4. Multi-level Alerts & Escalation ----------
class EscalationPolicy(Base):
    __tablename__ = "escalation_policies"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    after_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    notify_role: Mapped[str] = mapped_column(USER_ROLE_ENUM, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        CheckConstraint(
            "level >= 1 AND level <= 3", name="escalation_policies_level_check"
        ),
        CheckConstraint(
            "channel IN ('push', 'sms', 'zalo', 'call')",
            name="escalation_policies_channel_check",
        ),
        UniqueConstraint(
            "organization_id", "level", name="escalation_policies_organization_id_level_key"
        ),
    )


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    policy_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("escalation_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    notified_user_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="sent")
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('sent', 'delivered', 'acked', 'failed')",
            name="escalations_status_check",
        ),
        Index("escalations_event_idx", "event_id"),
    )


# ---------- 5. Risk Scores, Reports, App Usage ----------
class RiskScore(Base):
    __tablename__ = "risk_scores"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    driver_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_type: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    risk_level: Mapped[str] = mapped_column(Text, nullable=False)
    events_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    drowsy_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distraction_events: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    driving_hours: Mapped[Decimal] = mapped_column(
        Numeric(6, 1), nullable=False, default=Decimal("0.0")
    )

    __table_args__ = (
        CheckConstraint(
            "period_type IN ('shift', 'weekly', 'monthly')",
            name="risk_scores_period_type_check",
        ),
        CheckConstraint(
            "score >= 0 AND score <= 100", name="risk_scores_score_check"
        ),
        CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')",
            name="risk_scores_risk_level_check",
        ),
        UniqueConstraint(
            "driver_id",
            "period_type",
            "period_start",
            name="risk_scores_driver_id_period_type_period_start_key",
        ),
    )


class ReportModel(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_format: Mapped[str] = mapped_column(Text, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="ready")
    storage_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "report_type IN ('weekly', 'monthly')",
            name="reports_report_type_check",
        ),
        CheckConstraint(
            "file_format IN ('pdf', 'xlsx')",
            name="reports_file_format_check",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'failed')",
            name="reports_status_check",
        ),
    )


class AppUsageDaily(Base):
    __tablename__ = "app_usage_daily"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    driver_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)
    monitored_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    monitoring_off_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    alerts_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alerts_false: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint(
            "driver_id", "usage_date", name="app_usage_daily_driver_id_usage_date_key"
        ),
    )


# ---------- 6. Security: Refresh Tokens, Audit Logs, Push Tokens, Consents ----------
class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    family_id: Mapped[str] = mapped_column(UUIDStr, nullable=False, default=new_uuid)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replaced_by_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(INETType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        Index("refresh_tokens_user_idx", "user_id"),
        Index("refresh_tokens_family_idx", "family_id"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BIGINT_PK, primary_key=True, autoincrement=True)
    organization_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    actor_id: Mapped[Optional[str]] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    entity_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(INETType, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONBType, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (Index("audit_logs_org_time_idx", "organization_id", "created_at"),)


class PushToken(Base):
    __tablename__ = "push_tokens"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    fcm_token: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "platform IN ('android', 'ios', 'web')",
            name="push_tokens_platform_check",
        ),
        UniqueConstraint(
            "user_id", "fcm_token", name="push_tokens_user_id_fcm_token_key"
        ),
    )


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    consent_type: Mapped[str] = mapped_column(
        Text, nullable=False, default="data_processing"
    )
    version: Mapped[str] = mapped_column(Text, nullable=False)
    location_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    clip_storage_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "consent_type",
            "version",
            name="consents_user_id_consent_type_version_key",
        ),
    )


# ---------- 7. Third-party Integrations ----------
class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_prefix: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(
        StringArrayType, nullable=False, default=list
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(UUIDStr, primary_key=True, default=new_uuid)
    organization_id: Mapped[str] = mapped_column(
        UUIDStr,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret_hash: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list[str]] = mapped_column(
        StringArrayType, nullable=False, default=list
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
