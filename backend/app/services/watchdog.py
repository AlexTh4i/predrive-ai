import asyncio
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..core.config import get_config
from ..core.database import SessionLocal
from ..models.models import (
    AuditLog,
    Escalation,
    EscalationPolicy,
    EventModel,
    HeartbeatModel,
    LocationModel,
    Organization,
    OrgSettings,
    RefreshToken,
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
from .notify import notify_user
from .risk_report_service import compute_organization_risk_scores
from .sse import sse_broker
from .webhook_service import dispatch_webhooks_for_event

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
            sess.status = "disconnected"
            sess.current_state = "DISCONNECTED"
            sess.warning_count += 1

            ev_id = str(uuid4())
            ev = EventModel(
                id=ev_id,
                organization_id=sess.organization_id,
                session_id=sess.id,
                driver_id=sess.driver_id,
                vehicle_id=sess.vehicle_id,
                client_event_id=f"disc-{ev_id}",
                type="DISCONNECTED",
                level="WARNING",
                status="OPEN",
                state="DISCONNECTED",
                risk_score=None,
                occurred_at=now,
                duration_sec=int(elapsed),
                delayed=False,
                captured_at=now,
                created_at=now,
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


def _ensure_org_escalation_policies(db: Session, org_settings: OrgSettings) -> list[EscalationPolicy]:
    policies = list(
        db.scalars(
            select(EscalationPolicy)
            .where(
                EscalationPolicy.organization_id == org_settings.organization_id,
                EscalationPolicy.is_active.is_(True),
            )
            .order_by(EscalationPolicy.level.asc())
        ).all()
    )
    if policies:
        return policies

    any_existing = db.scalar(
        select(EscalationPolicy).where(
            EscalationPolicy.organization_id == org_settings.organization_id
        )
    )
    if any_existing is not None:
        return []

    base_sec = max(10, int(org_settings.ack_timeout_sec))
    defaults = [
        (1, base_sec, "dispatcher", "push"),
        (2, base_sec * 3, "manager", "push"),
        (3, base_sec * 5, "manager", "sms"),
    ]
    created: list[EscalationPolicy] = []
    for lvl, after_sec, role_target, chan in defaults:
        pol = EscalationPolicy(
            organization_id=org_settings.organization_id,
            level=lvl,
            after_seconds=after_sec,
            notify_role=role_target,
            channel=chan,
            is_active=True,
        )
        db.add(pol)
        created.append(pol)
    db.flush()
    return created


def check_pending_escalations(
    db: Session, now_utc: datetime | None = None
) -> list[Escalation]:
    """Evaluate unacknowledged, non-delayed events exceeding `settings.ack_timeout_sec`
    (mirrors `v_events_pending_escalation` + progressive `escalation_policies` levels 1..3).
    Transitions event status to ESCALATED, sends notifications without duplicates, and stops once acked.
    """
    now = ensure_utc(now_utc) or datetime.now(timezone.utc)
    candidates = db.scalars(
        select(EventModel).where(
            EventModel.ack_at.is_(None),
            EventModel.delayed.is_(False),
            EventModel.status.in_(("OPEN", "ESCALATED")),
        )
    ).all()

    settings_cache: dict[str, OrgSettings] = {}
    policies_cache: dict[str, list[EscalationPolicy]] = {}
    created_escalations: list[Escalation] = []

    for ev in candidates:
        occurred = ensure_utc(ev.occurred_at)
        if occurred is None:
            continue

        if ev.organization_id not in settings_cache:
            settings_cache[ev.organization_id] = get_or_create_org_settings(
                db, ev.organization_id
            )
            policies_cache[ev.organization_id] = _ensure_org_escalation_policies(
                db, settings_cache[ev.organization_id]
            )

        org_settings = settings_cache[ev.organization_id]
        waiting_sec = (now - occurred).total_seconds()
        if waiting_sec < float(org_settings.ack_timeout_sec):
            continue

        policies = policies_cache[ev.organization_id]
        driver = db.get(User, ev.driver_id)
        driver_name = driver.full_name if driver else "Tài xế"
        vehicle_name = "Chưa phân xe"
        v_id = ev.vehicle_id or (driver.vehicle_id if driver else None)
        if v_id:
            v_obj = db.get(Vehicle, v_id)
            if v_obj:
                vehicle_name = v_obj.name

        status_changed = False
        for pol in policies:
            required_wait = max(int(org_settings.ack_timeout_sec), int(pol.after_seconds))
            if waiting_sec < required_wait:
                continue

            recipients = db.scalars(
                select(User).where(
                    User.organization_id == ev.organization_id,
                    User.role == pol.notify_role,
                    User.is_active.is_(True),
                )
            ).all()
            for recipient in recipients:
                already_sent = db.scalar(
                    select(Escalation).where(
                        Escalation.event_id == ev.id,
                        Escalation.policy_id == pol.id,
                        Escalation.notified_user_id == recipient.id,
                    )
                )
                if already_sent is not None:
                    continue

                if ev.status == "OPEN":
                    ev.status = "ESCALATED"
                    status_changed = True
                if ev.escalated_at is None:
                    ev.escalated_at = now
                    status_changed = True

                title = f"[Leo thang Mức {pol.level}] Chưa liên hệ tài xế {driver_name}"
                body = (
                    f"Sự kiện {ev.type} trên xe {vehicle_name} đã chờ {int(waiting_sec)}s "
                    f"chưa xác nhận liên hệ."
                )
                res = notify_user(
                    db=db,
                    recipient=recipient,
                    channel=pol.channel,
                    title=title,
                    body=body,
                    meta={
                        "eventId": ev.id,
                        "driverId": ev.driver_id,
                        "policyLevel": str(pol.level),
                    },
                )
                esc = Escalation(
                    organization_id=ev.organization_id,
                    event_id=ev.id,
                    policy_id=pol.id,
                    notified_user_id=recipient.id,
                    channel=res.channel_used if res.delivered else pol.channel,
                    status="sent" if res.delivered else "failed",
                    sent_at=now,
                )
                db.add(esc)
                created_escalations.append(esc)

        if status_changed or created_escalations:
            db.flush()
        if status_changed:
            alert_schema = event_to_schema(ev, driver_name, vehicle_name)
            alert_json = alert_schema.model_dump(mode="json")
            sse_broker.publish(
                ev.organization_id,
                "alert",
                alert_json,
            )
            dispatch_webhooks_for_event(
                db, ev.organization_id, "alert.escalated", alert_json
            )

    if created_escalations:
        db.commit()
        for esc in created_escalations:
            db.refresh(esc)

    return created_escalations


def purge_expired_organization_data(
    db: Session, now_utc: datetime | None = None
) -> dict[str, int]:
    """Purge expired heartbeats, locations, CLOSED events, audit_logs per organization's
    configured retention days in `settings`, plus expired/revoked refresh_tokens > 7 days.
    Mirrors `public.purge_old_data()` across both PostgreSQL and SQLite and logs row counts.
    """
    now = ensure_utc(now_utc) or datetime.now(timezone.utc)
    all_settings = db.scalars(select(OrgSettings)).all()

    n_hb = 0
    n_loc = 0
    n_ev = 0
    n_audit = 0

    for s in all_settings:
        hb_cut = now - timedelta(days=max(1, s.heartbeat_retention_days))
        loc_cut = now - timedelta(days=max(1, s.location_retention_days))
        ev_cut = now - timedelta(days=max(1, s.event_retention_days))
        aud_cut = now - timedelta(days=max(1, s.audit_retention_days))

        n_hb += int(
            db.execute(
                delete(HeartbeatModel).where(
                    HeartbeatModel.organization_id == s.organization_id,
                    HeartbeatModel.ts < hb_cut,
                )
            ).rowcount
            or 0
        )
        n_loc += int(
            db.execute(
                delete(LocationModel).where(
                    LocationModel.organization_id == s.organization_id,
                    LocationModel.ts < loc_cut,
                )
            ).rowcount
            or 0
        )
        n_ev += int(
            db.execute(
                delete(EventModel).where(
                    EventModel.organization_id == s.organization_id,
                    EventModel.status == "CLOSED",
                    EventModel.occurred_at < ev_cut,
                )
            ).rowcount
            or 0
        )
        n_audit += int(
            db.execute(
                delete(AuditLog).where(
                    AuditLog.organization_id == s.organization_id,
                    AuditLog.created_at < aud_cut,
                )
            ).rowcount
            or 0
        )

    rt_cut = now - timedelta(days=7)
    n_rt = int(
        db.execute(
            delete(RefreshToken).where(
                or_(
                    RefreshToken.expires_at < rt_cut,
                    RefreshToken.revoked_at < rt_cut,
                )
            )
        ).rowcount
        or 0
    )

    db.commit()
    summary = {
        "heartbeats": n_hb,
        "locations": n_loc,
        "events": n_ev,
        "audit_logs": n_audit,
        "refresh_tokens": n_rt,
    }
    logger.info("Retention purge completed: %s", summary)
    return summary


def cleanup_old_telemetry(
    db: Session,
    now_utc: datetime | None = None,
    retention_days: int | None = None,
) -> int:
    """Delete heartbeats and locations older than retention_days (or per-org retention)."""
    if retention_days is None:
        counts = purge_expired_organization_data(db, now_utc=now_utc)
        return sum(counts.values())

    now = ensure_utc(now_utc) or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=retention_days)

    hb_res = db.execute(delete(HeartbeatModel).where(HeartbeatModel.ts < cutoff))
    loc_res = db.execute(delete(LocationModel).where(LocationModel.ts < cutoff))
    db.commit()
    return int(hb_res.rowcount or 0) + int(loc_res.rowcount or 0)


async def watchdog_loop(stop_event: asyncio.Event) -> None:
    cfg = get_config()
    interval = max(1, cfg.watchdog_interval_sec)
    ticks = 0
    last_daily_purge = 0.0
    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                check_disconnected_sessions(db)
                check_pending_escalations(db)
                ticks += 1
                now_ts = datetime.now(timezone.utc).timestamp()
                # Run full retention purge + risk score refresh once on startup and every 24h thereafter (P2-6 / P3-6)
                if now_ts - last_daily_purge >= 86400 or ticks % 720 == 0:
                    purge_expired_organization_data(db)
                    for org in db.scalars(select(Organization).where(Organization.is_active.is_(True))).all():
                        for p_type in ("shift", "weekly", "monthly"):
                            compute_organization_risk_scores(db, org.id, period_type=p_type)  # type: ignore[arg-type]
                    last_daily_purge = now_ts
        except Exception as exc:
            logger.warning("Watchdog cycle error: %s", exc)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
