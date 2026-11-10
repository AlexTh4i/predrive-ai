import asyncio
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..core.config import get_config
from ..core.database import SessionLocal
from ..models.models import (
    EventModel,
    HeartbeatModel,
    LocationModel,
    SessionModel,
    User,
    Vehicle,
)
from ..schemas.m3 import AlertEvent
from .mappers import (
    build_live_driver_state,
    ensure_utc,
    event_to_schema,
    get_or_create_org_settings,
)
from .sse import sse_broker

logger = logging.getLogger("predrive.watchdog")


def check_disconnected_sessions(
    db: Session, now_utc: datetime | None = None
) -> list[AlertEvent]:
    """Scan all open sessions. If elapsed time since last heartbeat > 2 * heartbeatIntervalSec,
    transition session to DISCONNECTED and emit a DISCONNECTED AlertEvent.
    """
    now = ensure_utc(now_utc) or datetime.now(timezone.utc)
    open_sessions = db.scalars(
        select(SessionModel).where(
            SessionModel.ended_at.is_(None),
            SessionModel.current_state != "DISCONNECTED",
        )
    ).all()

    created_alerts: list[AlertEvent] = []
    settings_cache: dict[str, int] = {}

    for sess in open_sessions:
        if sess.organization_id not in settings_cache:
            org_settings = get_or_create_org_settings(db, sess.organization_id)
            settings_cache[sess.organization_id] = org_settings.heartbeat_interval_sec

        hb_interval = settings_cache[sess.organization_id]
        timeout_sec = 2 * hb_interval

        ref_time = ensure_utc(sess.last_heartbeat_at) or ensure_utc(sess.started_at)
        if ref_time is None:
            continue

        elapsed = (now - ref_time).total_seconds()
        if elapsed > timeout_sec:
            sess.current_state = "DISCONNECTED"
            sess.warning_count += 1

            ev = EventModel(
                id=str(uuid4()),
                organization_id=sess.organization_id,
                session_id=sess.id,
                driver_id=sess.driver_id,
                vehicle_id=sess.vehicle_id,
                type="DISCONNECTED",
                level="WARNING",
                status="OPEN",
                state="DISCONNECTED",
                risk_score=None,
                started_at=now,
                duration_sec=int(elapsed),
                delayed=False,
                captured_at=now,
                received_at=now,
            )
            db.add(ev)
            db.commit()
            db.refresh(ev)
            db.refresh(sess)

            driver = db.get(User, sess.driver_id)
            if driver is not None:
                v_id = sess.vehicle_id or driver.vehicle_id
                v_name = "Chưa phân xe"
                if v_id:
                    v_obj = db.get(Vehicle, v_id)
                    if v_obj:
                        v_name = v_obj.name

                alert_schema = event_to_schema(ev, driver.full_name, v_name)
                created_alerts.append(alert_schema)

                live_state = build_live_driver_state(db, driver)
                sse_broker.publish(
                    sess.organization_id,
                    "driver_state",
                    live_state.model_dump(mode="json"),
                )
                sse_broker.publish(
                    sess.organization_id,
                    "alert",
                    alert_schema.model_dump(mode="json"),
                )

    return created_alerts


def cleanup_old_telemetry(
    db: Session,
    now_utc: datetime | None = None,
    retention_days: int | None = None,
) -> int:
    """Delete heartbeats and locations older than retention_days."""
    now = ensure_utc(now_utc) or datetime.now(timezone.utc)
    days = retention_days if retention_days is not None else get_config().heartbeat_retention_days
    cutoff = now - timedelta(days=days)

    hb_res = db.execute(
        delete(HeartbeatModel).where(HeartbeatModel.captured_at < cutoff)
    )
    loc_res = db.execute(
        delete(LocationModel).where(LocationModel.captured_at < cutoff)
    )
    db.commit()
    return int(hb_res.rowcount or 0) + int(loc_res.rowcount or 0)


async def watchdog_loop(stop_event: asyncio.Event) -> None:
    cfg = get_config()
    interval = max(1, cfg.watchdog_interval_sec)
    ticks = 0
    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                check_disconnected_sessions(db)
                ticks += 1
                if ticks % 120 == 0:
                    cleanup_old_telemetry(db)
        except Exception as exc:
            logger.warning("Watchdog cycle error: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

