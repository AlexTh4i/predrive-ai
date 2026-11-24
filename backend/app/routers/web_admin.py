import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
import random
import string
from typing import Literal, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.errors import AppError
from ..core.security import (
    generate_opaque_token,
    get_current_user,
    get_current_user_sse,
    get_jwt_org_id,
    hash_password,
    hash_token,
    require_roles,
)
from ..models.models import (
    ApiKey,
    AppUsageDaily,
    AuditLog,
    Escalation,
    EscalationPolicy,
    EventModel,
    HeartbeatModel,
    LocationModel,
    Pairing,
    PushToken,
    ReportModel,
    RiskScore,
    SessionModel,
    User,
    Vehicle,
    Webhook,
)
from ..schemas.m3 import (
    AckEventRequest,
    AlertEvent,
    ApiKeyCreatedResponse,
    ApiKeyItem,
    AuditLogItem,
    CreateApiKeyRequest,
    CreateDriverRequest,
    CreatePairingCodeRequest,
    CreateWebhookRequest,
    DriverDetailResponse,
    DriverFeedbackRequest,
    DriverRankingItem,
    DriverSchema,
    DriverStatsResponse,
    DriverUsage7dItem,
    EscalationItem,
    EscalationPolicyItem,
    EventLevel,
    EventType,
    ExportReportRequest,
    HourlyBreakdownItem,
    HourlyCountItem,
    LiveDriverState,
    LiveVehicleLocationItem,
    LocationTrailAlertPin,
    LocationTrailPoint,
    LocationTrailResponse,
    NearestRestStopItem,
    PaginatedAuditLogsResponse,
    PaginatedEventsResponse,
    PairingCodeResponse,
    PushTokenItem,
    RecomputeRiskScoresRequest,
    RegisterPushTokenRequest,
    ReportItem,
    RiskScoreItem,
    SettingsSchema,
    SystemHealthResponse,
    UnregisterPushTokenRequest,
    WebhookCreatedResponse,
    WebhookItem,
)
from ..services.audit import record_audit_log
from ..services.mappers import (
    build_live_driver_state,
    driver_to_schema,
    ensure_utc,
    event_to_schema,
    get_or_create_org_settings,
    get_vehicle_name_map,
    session_to_schema,
    settings_to_schema,
    to_vn_time,
)
from ..services.sse import sse_broker
from ..services.notify import notification_dispatcher, notify_user
from ..services.webhook_service import seal_webhook_secret
from ..services.rest_service import find_nearest_rest_stops
from ..services.risk_report_service import (
    RiskWeights,
    compute_organization_risk_scores,
    generate_report_file,
    resolve_reports_base_dir,
)

router = APIRouter(prefix="/api/v1", tags=["Web Admin & Dispatcher"])


def _parse_query_dt(val: Optional[str], is_end_of_day: bool = False) -> Optional[datetime]:
    if not val:
        return None
    s = val.strip()
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        dt = datetime.fromisoformat(s)
        if is_end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        return dt.replace(tzinfo=timezone.utc)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "INVALID_DATETIME",
            f"Giá trị thời gian không hợp lệ: {val}",
        ) from exc
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _calc_alerts_per_hour(alert_count: int, total_driving_sec: int) -> float:
    if total_driving_sec <= 0:
        return 0.0
    hours = total_driving_sec / 3600.0
    return round(alert_count / hours, 2)


# --- LIVE & SSE ---
@router.get("/live", response_model=list[LiveDriverState])
def get_live_drivers(
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> list[LiveDriverState]:
    org_id = current_user.organization_id
    drivers = db.scalars(
        select(User)
        .where(User.organization_id == org_id, User.role == "driver")
        .order_by(User.full_name.asc())
    ).all()
    vehicle_map = get_vehicle_name_map(db, org_id)
    org_settings = get_or_create_org_settings(db, org_id)

    return [
        build_live_driver_state(
            db,
            drv,
            vehicle_map=vehicle_map,
            share_location=org_settings.share_location,
        )
        for drv in drivers
    ]


@router.get("/live/stream")
async def stream_live_events(
    request: Request,
    max_events: Optional[int] = Query(default=None, include_in_schema=False),
    current_user: User = Depends(get_current_user_sse),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    if current_user.role not in ("manager", "dispatcher"):
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN",
            "Chỉ quản lý (manager) hoặc người trực (dispatcher) mới được xem luồng trực tiếp",
        )

    org_id = current_user.organization_id
    # Snapshot initial driver states on connect so SSE clients immediately receive current state
    drivers = db.scalars(
        select(User)
        .where(User.organization_id == org_id, User.role == "driver")
        .order_by(User.full_name.asc())
    ).all()
    vehicle_map = get_vehicle_name_map(db, org_id)
    org_settings = get_or_create_org_settings(db, org_id)
    initial_states = [
        build_live_driver_state(
            db,
            drv,
            vehicle_map=vehicle_map,
            share_location=org_settings.share_location,
        ).model_dump_json()
        for drv in drivers
    ]

    queue = sse_broker.subscribe(org_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        sent_count = 0
        try:
            yield ": connected\n\n"
            for state_json in initial_states:
                yield f"event: driver_state\ndata: {state_json}\n\n"
                sent_count += 1
                if max_events is not None and sent_count >= max_events:
                    return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"event: {msg['event']}\ndata: {msg['data']}\n\n"
                    sent_count += 1
                    if max_events is not None and sent_count >= max_events:
                        break
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            sse_broker.unsubscribe(org_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- EVENTS & ACK ---
@router.get("/events", response_model=PaginatedEventsResponse)
def list_events(
    driverId: Optional[str] = Query(default=None),
    from_str: Optional[str] = Query(default=None, alias="from"),
    to_str: Optional[str] = Query(default=None, alias="to"),
    level: Optional[EventLevel] = Query(default=None),
    type: Optional[EventType] = Query(default=None),
    acked: Optional[bool] = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=200),
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> PaginatedEventsResponse:
    org_id = current_user.organization_id
    from_dt = _parse_query_dt(from_str, is_end_of_day=False)
    to_dt = _parse_query_dt(to_str, is_end_of_day=True)

    filters = [EventModel.organization_id == org_id]
    if driverId:
        filters.append(EventModel.driver_id == driverId)
    if from_dt:
        filters.append(EventModel.occurred_at >= from_dt)
    if to_dt:
        filters.append(EventModel.occurred_at <= to_dt)
    if level == "CRITICAL":
        filters.append(EventModel.level == 3)
    elif level == "WARNING":
        filters.append(EventModel.level <= 2)
    if type:
        if type in ("DROWSINESS", "DROWSY"):
            filters.append(EventModel.type.in_(("DROWSINESS", "DROWSY")))
        else:
            filters.append(EventModel.type == type)
    if acked is True:
        filters.append(EventModel.ack_at.is_not(None))
    elif acked is False:
        filters.append(EventModel.ack_at.is_(None))

    total = db.scalar(select(func.count(EventModel.id)).where(*filters)) or 0
    rows = db.scalars(
        select(EventModel)
        .where(*filters)
        .order_by(EventModel.occurred_at.desc(), EventModel.created_at.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
    ).all()

    drivers = db.scalars(
        select(User).where(User.organization_id == org_id)
    ).all()
    driver_map = {d.id: d for d in drivers}
    vehicle_map = get_vehicle_name_map(db, org_id)

    items: list[AlertEvent] = []
    for ev in rows:
        drv = driver_map.get(ev.driver_id)
        d_name = drv.full_name if drv else "Tài xế"
        v_id = ev.vehicle_id or (drv.vehicle_id if drv else None)
        v_name = vehicle_map.get(v_id, "Chưa phân xe") if v_id else "Chưa phân xe"
        ack_usr = driver_map.get(ev.ack_by) if ev.ack_by else None
        ack_name = ack_usr.full_name if ack_usr else None
        items.append(event_to_schema(ev, d_name, v_name, ack_by_name=ack_name))

    return PaginatedEventsResponse(items=items, total=int(total))


@router.post("/events/{id}/ack", response_model=AlertEvent)
def acknowledge_event(
    id: str,
    request: Request,
    payload: AckEventRequest = Body(default=AckEventRequest()),
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> AlertEvent:
    ev = db.get(EventModel, id)
    if ev is None or ev.organization_id != current_user.organization_id:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "EVENT_NOT_FOUND",
            "Không tìm thấy sự kiện cảnh báo trong tổ chức",
        )

    now = datetime.now(timezone.utc)
    ev.ack_by = current_user.id
    ev.ack_at = now
    ev.note = payload.note
    m = dict(ev.metrics or {})
    m["ack_by_name"] = current_user.full_name
    ev.metrics = m

    open_escalations = db.scalars(
        select(Escalation).where(
            Escalation.organization_id == current_user.organization_id,
            Escalation.event_id == ev.id,
            Escalation.status.in_(("sent", "delivered")),
        )
    ).all()
    for esc in open_escalations:
        esc.status = "acked"

    record_audit_log(
        db,
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
        action="ack_event",
        entity="event",
        entity_id=ev.id,
        request=request,
        meta={"note": payload.note or ""},
    )
    db.commit()
    db.refresh(ev)

    drv = db.get(User, ev.driver_id)
    d_name = drv.full_name if drv else "Tài xế"
    vehicle_map = get_vehicle_name_map(db, current_user.organization_id)
    v_id = ev.vehicle_id or (drv.vehicle_id if drv else None)
    v_name = vehicle_map.get(v_id, "Chưa phân xe") if v_id else "Chưa phân xe"

    ack_schema = event_to_schema(
        ev, d_name, v_name, ack_by_name=current_user.full_name
    )
    if not ev.delayed:
        sse_broker.publish(
            current_user.organization_id,
            "alert",
            ack_schema.model_dump(mode="json"),
        )
    return ack_schema


@router.get("/events/{id}/escalations", response_model=list[EscalationItem])
def list_event_escalations(
    id: str,
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> list[EscalationItem]:
    org_id = get_jwt_org_id(current_user)
    ev = db.get(EventModel, id)
    if ev is None or ev.organization_id != org_id:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "EVENT_NOT_FOUND",
            "Không tìm thấy sự kiện cảnh báo trong tổ chức",
        )
    rows = db.scalars(
        select(Escalation)
        .where(Escalation.organization_id == org_id, Escalation.event_id == ev.id)
        .order_by(Escalation.sent_at.asc())
    ).all()
    pol_map = {
        p.id: p
        for p in db.scalars(
            select(EscalationPolicy).where(EscalationPolicy.organization_id == org_id)
        ).all()
    }
    usr_map = {
        u.id: u
        for u in db.scalars(select(User).where(User.organization_id == org_id)).all()
    }
    return [
        EscalationItem(
            id=r.id,
            eventId=r.event_id,
            policyId=r.policy_id,
            level=pol_map[r.policy_id].level if r.policy_id in pol_map else None,
            notifiedUserId=r.notified_user_id,
            notifiedUserName=usr_map[r.notified_user_id].full_name
            if r.notified_user_id in usr_map
            else None,
            notifiedRole=usr_map[r.notified_user_id].role
            if r.notified_user_id in usr_map
            else None,
            channel=r.channel,
            status=r.status,
            sentAt=ensure_utc(r.sent_at),  # type: ignore[arg-type]
        )
        for r in rows
    ]


@router.get("/escalation-policies", response_model=list[EscalationPolicyItem])
def list_escalation_policies(
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> list[EscalationPolicyItem]:
    org_id = get_jwt_org_id(current_user)
    rows = db.scalars(
        select(EscalationPolicy)
        .where(EscalationPolicy.organization_id == org_id)
        .order_by(EscalationPolicy.level.asc())
    ).all()
    return [
        EscalationPolicyItem(
            id=p.id,
            level=int(p.level),
            afterSeconds=int(p.after_seconds),
            notifyRole=p.notify_role,  # type: ignore[arg-type]
            channel=p.channel,  # type: ignore[arg-type]
            isActive=bool(p.is_active),
        )
        for p in rows
    ]


# --- DRIVERS ---
@router.get("/drivers", response_model=list[DriverSchema])
def list_drivers(
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> list[DriverSchema]:
    org_id = current_user.organization_id
    drivers = db.scalars(
        select(User)
        .where(User.organization_id == org_id, User.role == "driver")
        .order_by(User.full_name.asc())
    ).all()
    vehicle_map = get_vehicle_name_map(db, org_id)
    return [driver_to_schema(d, vehicle_map) for d in drivers]


@router.get("/drivers/{id}", response_model=DriverDetailResponse)
def get_driver_detail(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DriverDetailResponse:
    if current_user.role == "driver" and current_user.id != id:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN",
            "Tài xế không được phép đọc thông tin của tài xế khác",
        )

    drv = db.get(User, id)
    if (
        drv is None
        or drv.organization_id != current_user.organization_id
        or drv.role != "driver"
    ):
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "DRIVER_NOT_FOUND",
            "Không tìm thấy tài xế trong tổ chức",
        )

    vehicle_map = get_vehicle_name_map(db, current_user.organization_id)
    base = driver_to_schema(drv, vehicle_map)

    recent_sessions = db.scalars(
        select(SessionModel)
        .where(
            SessionModel.driver_id == drv.id,
            SessionModel.organization_id == current_user.organization_id,
        )
        .order_by(SessionModel.started_at.desc())
        .limit(20)
    ).all()

    return DriverDetailResponse(
        **base.model_dump(),
        recentSessions=[session_to_schema(s) for s in recent_sessions],
    )


@router.get("/drivers/{id}/stats", response_model=DriverStatsResponse)
def get_driver_stats(
    id: str,
    from_str: Optional[str] = Query(default=None, alias="from"),
    to_str: Optional[str] = Query(default=None, alias="to"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DriverStatsResponse:
    if current_user.role == "driver" and current_user.id != id:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN",
            "Tài xế không được phép xem thống kê của tài xế khác",
        )

    drv = db.get(User, id)
    if (
        drv is None
        or drv.organization_id != current_user.organization_id
        or drv.role != "driver"
    ):
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "DRIVER_NOT_FOUND",
            "Không tìm thấy tài xế trong tổ chức",
        )

    from_dt = _parse_query_dt(from_str, is_end_of_day=False)
    to_dt = _parse_query_dt(to_str, is_end_of_day=True)

    sess_filters = [
        SessionModel.driver_id == drv.id,
        SessionModel.organization_id == current_user.organization_id,
    ]
    ev_filters = [
        EventModel.driver_id == drv.id,
        EventModel.organization_id == current_user.organization_id,
    ]
    if from_dt:
        sess_filters.append(SessionModel.started_at >= from_dt)
        ev_filters.append(EventModel.started_at >= from_dt)
    if to_dt:
        sess_filters.append(SessionModel.started_at <= to_dt)
        ev_filters.append(EventModel.started_at <= to_dt)

    total_driving_sec = int(
        db.scalar(
            select(func.coalesce(func.sum(SessionModel.total_driving_sec), 0)).where(
                *sess_filters
            )
        )
        or 0
    )

    events = db.scalars(select(EventModel).where(*ev_filters)).all()
    alert_count = len(events)

    hourly_counts = {h: 0 for h in range(24)}
    for ev in events:
        vn_dt = to_vn_time(ev.started_at)
        hourly_counts[vn_dt.hour] += 1

    return DriverStatsResponse(
        totalDrivingSec=total_driving_sec,
        alertCount=alert_count,
        alertsPerDrivingHour=_calc_alerts_per_hour(alert_count, total_driving_sec),
        hourly=[HourlyCountItem(hour=h, count=hourly_counts[h]) for h in range(24)],
    )


# --- ORGANIZATION STATS ---
@router.get("/stats/hourly", response_model=list[HourlyBreakdownItem])
def get_stats_hourly(
    from_str: Optional[str] = Query(default=None, alias="from"),
    to_str: Optional[str] = Query(default=None, alias="to"),
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> list[HourlyBreakdownItem]:
    from_dt = _parse_query_dt(from_str, is_end_of_day=False)
    to_dt = _parse_query_dt(to_str, is_end_of_day=True)

    ev_filters = [EventModel.organization_id == current_user.organization_id]
    if from_dt:
        ev_filters.append(EventModel.started_at >= from_dt)
    if to_dt:
        ev_filters.append(EventModel.started_at <= to_dt)

    events = db.scalars(select(EventModel).where(*ev_filters)).all()
    buckets = {h: {"warning": 0, "critical": 0} for h in range(24)}

    for ev in events:
        vn_dt = to_vn_time(ev.occurred_at)
        if ev.level >= 3:
            buckets[vn_dt.hour]["critical"] += 1
        else:
            buckets[vn_dt.hour]["warning"] += 1

    return [
        HourlyBreakdownItem(
            hour=h,
            warning=buckets[h]["warning"],
            critical=buckets[h]["critical"],
        )
        for h in range(24)
    ]


@router.get("/stats/ranking", response_model=list[DriverRankingItem])
def get_stats_ranking(
    from_str: Optional[str] = Query(default=None, alias="from"),
    to_str: Optional[str] = Query(default=None, alias="to"),
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> list[DriverRankingItem]:
    org_id = current_user.organization_id
    from_dt = _parse_query_dt(from_str, is_end_of_day=False)
    to_dt = _parse_query_dt(to_str, is_end_of_day=True)

    drivers = db.scalars(
        select(User).where(User.organization_id == org_id, User.role == "driver")
    ).all()

    sess_filters = [SessionModel.organization_id == org_id]
    ev_filters = [EventModel.organization_id == org_id]
    if from_dt:
        sess_filters.append(SessionModel.started_at >= from_dt)
        ev_filters.append(EventModel.started_at >= from_dt)
    if to_dt:
        sess_filters.append(SessionModel.started_at <= to_dt)
        ev_filters.append(EventModel.started_at <= to_dt)

    driving_rows = db.execute(
        select(
            SessionModel.driver_id,
            func.coalesce(func.sum(SessionModel.total_driving_sec), 0),
        )
        .where(*sess_filters)
        .group_by(SessionModel.driver_id)
    ).all()
    driving_map = {r[0]: int(r[1] or 0) for r in driving_rows}

    alert_rows = db.execute(
        select(EventModel.driver_id, func.count(EventModel.id))
        .where(*ev_filters)
        .group_by(EventModel.driver_id)
    ).all()
    alert_map = {r[0]: int(r[1] or 0) for r in alert_rows}

    ranking: list[DriverRankingItem] = []
    for drv in drivers:
        drv_sec = driving_map.get(drv.id, 0)
        a_cnt = alert_map.get(drv.id, 0)
        ranking.append(
            DriverRankingItem(
                driverId=drv.id,
                fullName=drv.full_name,
                alertsPerDrivingHour=_calc_alerts_per_hour(a_cnt, drv_sec),
                alertCount=a_cnt,
            )
        )

    ranking.sort(key=lambda item: (item.alertsPerDrivingHour, item.alertCount), reverse=True)
    return ranking


@router.get("/stats/system-health", response_model=SystemHealthResponse)
def get_stats_system_health(
    from_str: Optional[str] = Query(default=None, alias="from"),
    to_str: Optional[str] = Query(default=None, alias="to"),
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> SystemHealthResponse:
    org_id = current_user.organization_id
    from_dt = _parse_query_dt(from_str, is_end_of_day=False)
    to_dt = _parse_query_dt(to_str, is_end_of_day=True)

    hb_filters = [HeartbeatModel.organization_id == org_id]
    ev_filters = [
        EventModel.organization_id == org_id,
        EventModel.type == "DISCONNECTED",
    ]
    if from_dt:
        hb_filters.append(HeartbeatModel.captured_at >= from_dt)
        ev_filters.append(EventModel.started_at >= from_dt)
    if to_dt:
        hb_filters.append(HeartbeatModel.captured_at <= to_dt)
        ev_filters.append(EventModel.started_at <= to_dt)

    total_hb = int(
        db.scalar(select(func.count(HeartbeatModel.id)).where(*hb_filters)) or 0
    )
    if total_hb > 0:
        too_dark_hb = int(
            db.scalar(
                select(func.count(HeartbeatModel.id)).where(
                    *hb_filters, HeartbeatModel.image_quality == "TOO_DARK"
                )
            )
            or 0
        )
        unavail_hb = int(
            db.scalar(
                select(func.count(HeartbeatModel.id)).where(
                    *hb_filters, HeartbeatModel.state == "MONITORING_UNAVAILABLE"
                )
            )
            or 0
        )
        too_dark_rate = round(too_dark_hb / total_hb, 4)
        unavailable_rate = round(unavail_hb / total_hb, 4)
    else:
        too_dark_rate = 0.0
        unavailable_rate = 0.0

    disc_count = int(
        db.scalar(select(func.count(EventModel.id)).where(*ev_filters)) or 0
    )

    return SystemHealthResponse(
        tooDarkRate=too_dark_rate,
        unavailableRate=unavailable_rate,
        disconnectedCount=disc_count,
    )


# --- SETTINGS ---
@router.get("/settings", response_model=SettingsSchema)
def get_settings(
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> SettingsSchema:
    org_settings = get_or_create_org_settings(db, current_user.organization_id)
    return settings_to_schema(org_settings)


@router.put("/settings", response_model=SettingsSchema)
def update_settings(
    payload: SettingsSchema,
    request: Request,
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> SettingsSchema:
    if payload.continuousCriticalSec < payload.continuousWarnSec:
        raise AppError(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_SETTINGS",
            "continuousCriticalSec phải lớn hơn hoặc bằng continuousWarnSec",
        )

    org_settings = get_or_create_org_settings(db, current_user.organization_id)
    org_settings.continuous_warn_sec = payload.continuousWarnSec
    org_settings.continuous_critical_sec = payload.continuousCriticalSec
    org_settings.rest_reset_min = payload.restResetMin
    org_settings.share_location = payload.shareLocation
    org_settings.heartbeat_interval_sec = payload.heartbeatIntervalSec

    optional_map = {
        "earThreshold": "ear_threshold",
        "eyeClosedSec": "eye_closed_sec",
        "headPoseSec": "head_pose_sec",
        "tooDarkThreshold": "too_dark_threshold",
        "level1Sec": "level1_sec",
        "level2Sec": "level2_sec",
        "level3Sec": "level3_sec",
        "ackTimeoutSec": "ack_timeout_sec",
        "maxContinuousDriveMin": "max_continuous_drive_min",
        "restReminderBeforeMin": "rest_reminder_before_min",
        "locationIntervalSec": "location_interval_sec",
        "heartbeatRetentionDays": "heartbeat_retention_days",
        "locationRetentionDays": "location_retention_days",
        "eventRetentionDays": "event_retention_days",
        "auditRetentionDays": "audit_retention_days",
    }
    for schema_field, model_attr in optional_map.items():
        val = getattr(payload, schema_field, None)
        if val is not None:
            setattr(org_settings, model_attr, val)

    if (
        org_settings.level1_sec > org_settings.level2_sec
        or org_settings.level2_sec > org_settings.level3_sec
    ):
        raise AppError(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_SETTINGS",
            "level1Sec <= level2Sec <= level3Sec là bắt buộc",
        )

    org_settings.updated_at = datetime.now(timezone.utc)
    record_audit_log(
        db,
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
        action="update_settings",
        entity="settings",
        entity_id=current_user.organization_id,
        request=request,
        meta=payload.model_dump(mode="json", exclude_none=True),
    )
    db.commit()
    db.refresh(org_settings)

    return settings_to_schema(org_settings)


# --- PAIRING CODES & DRIVER CREATION (MANAGER ONLY) ---
@router.post("/pairing-codes", response_model=PairingCodeResponse)
def create_pairing_code(
    request: Request,
    payload: CreatePairingCodeRequest = Body(default=CreatePairingCodeRequest()),
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> PairingCodeResponse:
    now = datetime.now(timezone.utc)
    org_id = current_user.organization_id

    veh_id: Optional[str] = None
    if payload.vehicleId:
        veh = db.get(Vehicle, payload.vehicleId)
        if veh is None or veh.organization_id != org_id:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                "VEHICLE_NOT_FOUND",
                "Không tìm thấy xe trong tổ chức",
            )
        veh_id = veh.id

    # Generate unique 6-character code
    alphabet = string.ascii_uppercase + string.digits
    code = ""
    for _ in range(10):
        candidate = "".join(random.choices(alphabet, k=6))
        if db.scalar(select(Pairing).where(Pairing.code == candidate)) is None:
            code = candidate
            break
    if not code:
        code = uuid4().hex[:8].upper()

    expires_at = now + timedelta(minutes=payload.expiresInMinutes)
    pairing = Pairing(
        organization_id=org_id,
        vehicle_id=veh_id,
        driver_id=None,
        code=code,
        expires_at=expires_at,
        consented_at=None,
        created_by=current_user.id,
        status="PENDING",
        created_at=now,
    )
    db.add(pairing)
    db.flush()
    record_audit_log(
        db,
        organization_id=org_id,
        actor_id=current_user.id,
        action="create_pairing",
        entity="pairing",
        entity_id=pairing.id,
        request=request,
        meta={"code": code, "vehicleId": veh_id},
    )
    db.commit()
    db.refresh(pairing)

    return PairingCodeResponse(code=pairing.code, expiresAt=ensure_utc(pairing.expires_at))  # type: ignore[arg-type]


@router.post("/drivers", response_model=DriverSchema, status_code=status.HTTP_201_CREATED)
def create_driver_account(
    payload: CreateDriverRequest,
    request: Request,
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> DriverSchema:
    import secrets

    org_id = current_user.organization_id
    username = (payload.username or payload.phone).strip()
    generated_temp = False
    if payload.password:
        raw_password = payload.password
    else:
        raw_password = secrets.token_urlsafe(8)[:10]
        generated_temp = True

    existing_user = db.scalar(select(User).where(User.username == username))
    if existing_user is not None:
        raise AppError(
            status.HTTP_409_CONFLICT,
            "USERNAME_EXISTS",
            f"Tài khoản '{username}' đã tồn tại",
        )

    veh_id: Optional[str] = None
    if payload.vehicleId:
        veh = db.get(Vehicle, payload.vehicleId)
        if veh is None or veh.organization_id != org_id:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                "VEHICLE_NOT_FOUND",
                "Không tìm thấy xe trong tổ chức",
            )
        veh_id = veh.id
    elif payload.vehicleName:
        new_veh = Vehicle(
            organization_id=org_id,
            plate_number=payload.vehicleName.split("-")[0].strip()[:48],
            name=payload.vehicleName.strip(),
        )
        db.add(new_veh)
        db.flush()
        veh_id = new_veh.id

    driver = User(
        organization_id=org_id,
        username=username,
        password_hash=hash_password(raw_password),
        role="driver",
        full_name=payload.fullName.strip(),
        phone=payload.phone.strip(),
        zalo_phone=payload.phone.strip(),
        vehicle_id=veh_id,
        avatar_url=payload.avatarUrl,
        must_change_password=True,
    )
    db.add(driver)
    db.flush()
    record_audit_log(
        db,
        organization_id=org_id,
        actor_id=current_user.id,
        action="create_driver",
        entity="user",
        entity_id=driver.id,
        request=request,
        meta={"username": username, "fullName": driver.full_name},
    )
    db.commit()
    db.refresh(driver)

    vehicle_map = get_vehicle_name_map(db, org_id)
    out = driver_to_schema(driver, vehicle_map)
    if generated_temp:
        out.temporaryPassword = raw_password
    return out


# --- AUDIT LOGS, API KEYS & REPORTS (MANAGER ONLY - P1-4 / P3-6 / P3-8) ---
@router.get("/audit-logs", response_model=PaginatedAuditLogsResponse)
def list_audit_logs(
    action: Optional[str] = Query(default=None),
    entity: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=200),
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> PaginatedAuditLogsResponse:
    org_id = current_user.organization_id
    filters = [AuditLog.organization_id == org_id]
    if action:
        filters.append(AuditLog.action == action)
    if entity:
        filters.append(AuditLog.entity == entity)

    total = int(db.scalar(select(func.count(AuditLog.id)).where(*filters)) or 0)
    rows = db.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
    ).all()

    users = db.scalars(select(User).where(User.organization_id == org_id)).all()
    user_map = {u.id: u.full_name for u in users}

    items = [
        AuditLogItem(
            id=r.id,
            organizationId=r.organization_id,
            actorId=r.actor_id,
            actorName=user_map.get(r.actor_id) if r.actor_id else None,
            action=r.action,
            entity=r.entity,
            entityId=r.entity_id,
            ip=r.ip,
            meta=r.meta or {},
            createdAt=ensure_utc(r.created_at),  # type: ignore[arg-type]
        )
        for r in rows
    ]
    return PaginatedAuditLogsResponse(items=items, total=total)


@router.get("/api-keys", response_model=list[ApiKeyItem])
def list_api_keys(
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> list[ApiKeyItem]:
    rows = db.scalars(
        select(ApiKey)
        .where(ApiKey.organization_id == current_user.organization_id)
        .order_by(ApiKey.created_at.desc())
    ).all()
    return [
        ApiKeyItem(
            id=k.id,
            name=k.name,
            keyPrefix=k.key_prefix,
            scopes=list(k.scopes or []),
            lastUsedAt=ensure_utc(k.last_used_at),
            revokedAt=ensure_utc(k.revoked_at),
            createdAt=ensure_utc(k.created_at),  # type: ignore[arg-type]
        )
        for k in rows
    ]


@router.post("/api-keys", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    payload: CreateApiKeyRequest,
    request: Request,
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> ApiKeyCreatedResponse:
    org_id = current_user.organization_id
    raw_secret = generate_opaque_token()
    raw_key = f"pd_live_{raw_secret}"
    prefix = raw_key[:14]
    now = datetime.now(timezone.utc)

    row = ApiKey(
        organization_id=org_id,
        name=payload.name.strip(),
        key_prefix=prefix,
        key_hash=hash_token(raw_key),
        scopes=list(payload.scopes),
        created_at=now,
    )
    db.add(row)
    db.flush()
    record_audit_log(
        db,
        organization_id=org_id,
        actor_id=current_user.id,
        action="create_api_key",
        entity="api_key",
        entity_id=row.id,
        request=request,
        meta={"name": row.name, "scopes": list(row.scopes)},
    )
    db.commit()
    db.refresh(row)

    return ApiKeyCreatedResponse(
        id=row.id,
        name=row.name,
        keyPrefix=row.key_prefix,
        scopes=list(row.scopes),
        lastUsedAt=None,
        revokedAt=None,
        createdAt=ensure_utc(row.created_at),  # type: ignore[arg-type]
        rawKey=raw_key,
    )


@router.delete("/api-keys/{id}", response_model=ApiKeyItem)
def revoke_api_key(
    id: str,
    request: Request,
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> ApiKeyItem:
    row = db.get(ApiKey, id)
    if row is None or row.organization_id != current_user.organization_id:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "API_KEY_NOT_FOUND",
            "Không tìm thấy API key trong tổ chức",
        )
    now = datetime.now(timezone.utc)
    if row.revoked_at is None:
        row.revoked_at = now
    record_audit_log(
        db,
        organization_id=current_user.organization_id,
        actor_id=current_user.id,
        action="revoke_api_key",
        entity="api_key",
        entity_id=row.id,
        request=request,
        meta={"name": row.name},
    )
    db.commit()
    db.refresh(row)

    return ApiKeyItem(
        id=row.id,
        name=row.name,
        keyPrefix=row.key_prefix,
        scopes=list(row.scopes or []),
        lastUsedAt=ensure_utc(row.last_used_at),
        revokedAt=ensure_utc(row.revoked_at),
        createdAt=ensure_utc(row.created_at),  # type: ignore[arg-type]
    )


@router.post("/reports/export", response_model=ReportItem, status_code=status.HTTP_201_CREATED)
def export_report_endpoint(
    request: Request,
    payload: ExportReportRequest = Body(default=ExportReportRequest()),
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> ReportItem:
    from datetime import date

    org_id = current_user.organization_id
    today = to_vn_time(datetime.now(timezone.utc)).date()
    p_end = date.fromisoformat(payload.periodEnd) if payload.periodEnd else today
    days_span = 6 if payload.reportType == "weekly" else 29
    p_start = (
        date.fromisoformat(payload.periodStart)
        if payload.periodStart
        else (p_end - timedelta(days=days_span))
    )

    rep_id = str(uuid4())
    storage_path = f"reports/{org_id}/{rep_id}.{payload.fileFormat}"
    rep = ReportModel(
        id=rep_id,
        organization_id=org_id,
        report_type=payload.reportType,
        file_format=payload.fileFormat,
        period_start=p_start,
        period_end=p_end,
        status="ready",
        storage_path=storage_path,
        created_by=current_user.id,
    )
    db.add(rep)
    db.flush()
    generate_report_file(db, rep)
    record_audit_log(
        db,
        organization_id=org_id,
        actor_id=current_user.id,
        action="export_report",
        entity="report",
        entity_id=rep.id,
        request=request,
        meta={
            "reportType": payload.reportType,
            "fileFormat": payload.fileFormat,
            "periodStart": p_start.isoformat(),
            "periodEnd": p_end.isoformat(),
        },
    )
    db.commit()
    db.refresh(rep)

    return ReportItem(
        id=rep.id,
        reportType=rep.report_type,  # type: ignore[arg-type]
        fileFormat=rep.file_format,  # type: ignore[arg-type]
        periodStart=rep.period_start.isoformat(),
        periodEnd=rep.period_end.isoformat(),
        status=rep.status,  # type: ignore[arg-type]
        storagePath=rep.storage_path,
        createdAt=ensure_utc(rep.created_at),  # type: ignore[arg-type]
    )


@router.get("/reports", response_model=list[ReportItem])
def list_reports(
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> list[ReportItem]:
    org_id = get_jwt_org_id(current_user)
    rows = db.scalars(
        select(ReportModel)
        .where(ReportModel.organization_id == org_id)
        .order_by(ReportModel.created_at.desc())
    ).all()
    return [
        ReportItem(
            id=r.id,
            reportType=r.report_type,  # type: ignore[arg-type]
            fileFormat=r.file_format,  # type: ignore[arg-type]
            periodStart=r.period_start.isoformat(),
            periodEnd=r.period_end.isoformat(),
            status=r.status,  # type: ignore[arg-type]
            storagePath=r.storage_path,
            createdAt=ensure_utc(r.created_at),  # type: ignore[arg-type]
        )
        for r in rows
    ]


@router.get("/reports/{id}", response_model=ReportItem)
def get_report_by_id(
    id: str,
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> ReportItem:
    org_id = get_jwt_org_id(current_user)
    rep = db.get(ReportModel, id)
    if rep is None or rep.organization_id != org_id:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "REPORT_NOT_FOUND",
            "Không tìm thấy báo cáo trong tổ chức",
        )
    return ReportItem(
        id=rep.id,
        reportType=rep.report_type,  # type: ignore[arg-type]
        fileFormat=rep.file_format,  # type: ignore[arg-type]
        periodStart=rep.period_start.isoformat(),
        periodEnd=rep.period_end.isoformat(),
        status=rep.status,  # type: ignore[arg-type]
        storagePath=rep.storage_path,
        createdAt=ensure_utc(rep.created_at),  # type: ignore[arg-type]
    )


@router.get("/reports/{id}/download")
def download_report_file(
    id: str,
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> FileResponse:
    org_id = get_jwt_org_id(current_user)
    rep = db.get(ReportModel, id)
    if rep is None or rep.organization_id != org_id:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "REPORT_NOT_FOUND",
            "Không tìm thấy báo cáo trong tổ chức",
        )

    file_path = resolve_reports_base_dir() / org_id / f"{rep.id}.{rep.file_format}"
    if not file_path.exists():
        file_path = generate_report_file(db, rep)

    media_type = (
        "application/pdf"
        if rep.file_format == "pdf"
        else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    filename = f"predrive-{rep.report_type}-{rep.period_start.isoformat()}-to-{rep.period_end.isoformat()}.{rep.file_format}"
    return FileResponse(path=str(file_path), media_type=media_type, filename=filename)


@router.get("/risk-scores", response_model=list[RiskScoreItem])
def list_risk_scores(
    periodType: Literal["shift", "weekly", "monthly"] = Query(default="weekly"),
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> list[RiskScoreItem]:
    org_id = get_jwt_org_id(current_user)
    rows = db.scalars(
        select(RiskScore)
        .where(
            RiskScore.organization_id == org_id,
            RiskScore.period_type == periodType,
        )
        .order_by(RiskScore.period_end.desc(), RiskScore.score.desc())
    ).all()
    if not rows:
        rows = compute_organization_risk_scores(db, org_id, period_type=periodType)
    drv_map = {
        u.id: u.full_name
        for u in db.scalars(select(User).where(User.organization_id == org_id)).all()
    }
    return [
        RiskScoreItem(
            id=r.id,
            driverId=r.driver_id,
            driverName=drv_map.get(r.driver_id, "Tài xế"),
            periodType=r.period_type,  # type: ignore[arg-type]
            periodStart=r.period_start.isoformat(),
            periodEnd=r.period_end.isoformat(),
            score=int(r.score),
            riskLevel=r.risk_level,  # type: ignore[arg-type]
            eventsCount=int(r.events_count),
            drowsyEvents=int(r.drowsy_events),
            distractionEvents=int(r.distraction_events),
            drivingHours=float(r.driving_hours),
        )
        for r in rows
    ]


@router.post("/risk-scores/recompute", response_model=list[RiskScoreItem])
def recompute_risk_scores_endpoint(
    payload: RecomputeRiskScoresRequest = Body(default=RecomputeRiskScoresRequest()),
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> list[RiskScoreItem]:
    from datetime import date

    org_id = get_jwt_org_id(current_user)
    p_start = date.fromisoformat(payload.periodStart) if payload.periodStart else None
    p_end = date.fromisoformat(payload.periodEnd) if payload.periodEnd else None

    base_w = RiskWeights.from_env()
    if payload.weights is not None:
        w = RiskWeights(
            w_critical=payload.weights.wCritical
            if payload.weights.wCritical is not None
            else base_w.w_critical,
            w_drowsy=payload.weights.wDrowsy
            if payload.weights.wDrowsy is not None
            else base_w.w_drowsy,
            w_distraction=payload.weights.wDistraction
            if payload.weights.wDistraction is not None
            else base_w.w_distraction,
            w_overtime=payload.weights.wOvertime
            if payload.weights.wOvertime is not None
            else base_w.w_overtime,
            shift_hours_norm=payload.weights.shiftHoursNorm
            if payload.weights.shiftHoursNorm is not None
            else base_w.shift_hours_norm,
        )
    else:
        w = base_w

    rows = compute_organization_risk_scores(
        db=db,
        org_id=org_id,
        period_type=payload.periodType,
        period_start=p_start,
        period_end=p_end,
        weights=w,
    )
    drv_map = {
        u.id: u.full_name
        for u in db.scalars(select(User).where(User.organization_id == org_id)).all()
    }
    return [
        RiskScoreItem(
            id=r.id,
            driverId=r.driver_id,
            driverName=drv_map.get(r.driver_id, "Tài xế"),
            periodType=r.period_type,  # type: ignore[arg-type]
            periodStart=r.period_start.isoformat(),
            periodEnd=r.period_end.isoformat(),
            score=int(r.score),
            riskLevel=r.risk_level,  # type: ignore[arg-type]
            eventsCount=int(r.events_count),
            drowsyEvents=int(r.drowsy_events),
            distractionEvents=int(r.distraction_events),
            drivingHours=float(r.driving_hours),
        )
        for r in rows
    ]


# --- GPS & FLEET MAP (P3-1) ---
@router.get("/locations/live", response_model=list[LiveVehicleLocationItem])
def get_live_vehicle_locations(
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> list[LiveVehicleLocationItem]:
    org_id = get_jwt_org_id(current_user)
    drivers = db.scalars(
        select(User)
        .where(User.organization_id == org_id, User.role == "driver")
        .order_by(User.full_name.asc())
    ).all()
    vehicle_map = get_vehicle_name_map(db, org_id)

    items: list[LiveVehicleLocationItem] = []
    seen_vehicle_ids: set[str] = set()

    for drv in drivers:
        latest_loc = db.scalar(
            select(LocationModel)
            .where(
                LocationModel.organization_id == org_id,
                LocationModel.driver_id == drv.id,
            )
            .order_by(LocationModel.ts.desc(), LocationModel.id.desc())
        )
        if latest_loc is None and drv.vehicle_id:
            latest_loc = db.scalar(
                select(LocationModel)
                .where(
                    LocationModel.organization_id == org_id,
                    LocationModel.vehicle_id == drv.vehicle_id,
                )
                .order_by(LocationModel.ts.desc(), LocationModel.id.desc())
            )
        if latest_loc is None:
            continue

        active_sess = db.scalar(
            select(SessionModel)
            .where(
                SessionModel.organization_id == org_id,
                SessionModel.driver_id == drv.id,
                SessionModel.ended_at.is_(None),
            )
            .order_by(SessionModel.started_at.desc())
        )
        v_id = latest_loc.vehicle_id or (active_sess.vehicle_id if active_sess else None) or drv.vehicle_id
        if v_id:
            seen_vehicle_ids.add(v_id)
        v_name = vehicle_map.get(v_id, "Chưa phân xe") if v_id else "Chưa phân xe"
        state = active_sess.current_state if active_sess else "OFFLINE"

        items.append(
            LiveVehicleLocationItem(
                driverId=drv.id,
                driverName=drv.full_name,
                vehicleId=v_id,
                vehicleName=v_name,
                state=state,  # type: ignore[arg-type]
                sessionId=active_sess.id if active_sess else latest_loc.session_id,
                lat=latest_loc.lat,
                lng=latest_loc.lng,
                speedKmh=latest_loc.speed_kmh,
                headingDeg=latest_loc.heading_deg,
                at=ensure_utc(latest_loc.ts),  # type: ignore[arg-type]
            )
        )

    # Also include unassigned vehicles that received hardware tracker GPS pings (P3-8)
    vehicles = db.scalars(
        select(Vehicle).where(Vehicle.organization_id == org_id)
    ).all()
    for veh in vehicles:
        if veh.id in seen_vehicle_ids:
            continue
        latest_v_loc = db.scalar(
            select(LocationModel)
            .where(
                LocationModel.organization_id == org_id,
                LocationModel.vehicle_id == veh.id,
            )
            .order_by(LocationModel.ts.desc(), LocationModel.id.desc())
        )
        if latest_v_loc is None:
            continue
        items.append(
            LiveVehicleLocationItem(
                driverId=latest_v_loc.driver_id or f"vehicle:{veh.id}",
                driverName="Thiết bị hành trình",
                vehicleId=veh.id,
                vehicleName=veh.name,
                state="NORMAL",
                sessionId=latest_v_loc.session_id,
                lat=latest_v_loc.lat,
                lng=latest_v_loc.lng,
                speedKmh=latest_v_loc.speed_kmh,
                headingDeg=latest_v_loc.heading_deg,
                at=ensure_utc(latest_v_loc.ts),  # type: ignore[arg-type]
            )
        )

    return items


@router.get("/locations/trail", response_model=LocationTrailResponse)
def get_location_trail(
    driverId: Optional[str] = Query(default=None),
    sessionId: Optional[str] = Query(default=None),
    vehicleId: Optional[str] = Query(default=None),
    from_str: Optional[str] = Query(default=None, alias="from"),
    to_str: Optional[str] = Query(default=None, alias="to"),
    limit: int = Query(default=500, ge=1, le=2000),
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> LocationTrailResponse:
    org_id = get_jwt_org_id(current_user)
    if not driverId and not sessionId and not vehicleId:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "MISSING_FILTER",
            "Cần cung cấp ít nhất một trong các tham số driverId, sessionId hoặc vehicleId",
        )

    from_dt = _parse_query_dt(from_str, is_end_of_day=False)
    to_dt = _parse_query_dt(to_str, is_end_of_day=True)

    driver_obj: Optional[User] = None
    sess_obj: Optional[SessionModel] = None
    veh_obj: Optional[Vehicle] = None

    if sessionId:
        sess_obj = db.get(SessionModel, sessionId)
        if sess_obj is None or sess_obj.organization_id != org_id:
            raise AppError(status.HTTP_404_NOT_FOUND, "SESSION_NOT_FOUND", "Không tìm thấy phiên lái")
        driverId = driverId or sess_obj.driver_id
        vehicleId = vehicleId or sess_obj.vehicle_id

    if driverId and not driverId.startswith("vehicle:"):
        driver_obj = db.get(User, driverId)
        if driver_obj is None or driver_obj.organization_id != org_id:
            raise AppError(status.HTTP_404_NOT_FOUND, "DRIVER_NOT_FOUND", "Không tìm thấy tài xế")
        vehicleId = vehicleId or driver_obj.vehicle_id

    if vehicleId:
        veh_obj = db.get(Vehicle, vehicleId)
        if veh_obj is None or veh_obj.organization_id != org_id:
            raise AppError(status.HTTP_404_NOT_FOUND, "VEHICLE_NOT_FOUND", "Không tìm thấy phương tiện")

    loc_filters = [LocationModel.organization_id == org_id]
    if sessionId:
        loc_filters.append(LocationModel.session_id == sessionId)
    elif driver_obj is not None:
        loc_filters.append(LocationModel.driver_id == driver_obj.id)
    elif veh_obj is not None:
        loc_filters.append(LocationModel.vehicle_id == veh_obj.id)

    if from_dt:
        loc_filters.append(LocationModel.ts >= from_dt)
    if to_dt:
        loc_filters.append(LocationModel.ts <= to_dt)

    loc_rows = list(
        db.scalars(
            select(LocationModel)
            .where(*loc_filters)
            .order_by(LocationModel.ts.desc(), LocationModel.id.desc())
            .limit(limit)
        ).all()
    )
    loc_rows.reverse()

    points = [
        LocationTrailPoint(
            lat=r.lat,
            lng=r.lng,
            speedKmh=r.speed_kmh,
            headingDeg=r.heading_deg,
            at=ensure_utc(r.ts),  # type: ignore[arg-type]
            eventId=r.event_id,
        )
        for r in loc_rows
    ]

    # Collect alert pins along the trail (from linked event_ids AND events with lat/lng in scope)
    ev_filters = [EventModel.organization_id == org_id]
    if sessionId:
        ev_filters.append(EventModel.session_id == sessionId)
    elif driver_obj is not None:
        ev_filters.append(EventModel.driver_id == driver_obj.id)
    elif veh_obj is not None:
        ev_filters.append(EventModel.vehicle_id == veh_obj.id)
    if from_dt:
        ev_filters.append(EventModel.occurred_at >= from_dt)
    if to_dt:
        ev_filters.append(EventModel.occurred_at <= to_dt)

    ev_rows = db.scalars(
        select(EventModel)
        .where(*ev_filters)
        .order_by(EventModel.occurred_at.asc())
    ).all()

    loc_by_event_id = {r.event_id: r for r in loc_rows if r.event_id}
    driver_name = driver_obj.full_name if driver_obj else "Thiết bị hành trình"
    vehicle_name = veh_obj.name if veh_obj else "Chưa phân xe"

    alerts: list[LocationTrailAlertPin] = []
    for ev in ev_rows:
        pin_loc = loc_by_event_id.get(ev.id)
        lat = ev.lat if ev.lat is not None else (pin_loc.lat if pin_loc else None)
        lng = ev.lng if ev.lng is not None else (pin_loc.lng if pin_loc else None)
        if lat is None or lng is None:
            continue
        alerts.append(
            LocationTrailAlertPin(
                eventId=ev.id,
                type=ev.type,  # type: ignore[arg-type]
                level=ev.level_str,  # type: ignore[arg-type]
                severityLevel=int(ev.level),
                status=ev.status,  # type: ignore[arg-type]
                driverId=ev.driver_id,
                driverName=driver_name,
                vehicleName=vehicle_name,
                lat=lat,
                lng=lng,
                occurredAt=ensure_utc(ev.occurred_at),  # type: ignore[arg-type]
                note=ev.note,
            )
        )

    return LocationTrailResponse(
        driverId=driver_obj.id if driver_obj else (driverId or f"vehicle:{vehicleId}"),
        driverName=driver_name,
        vehicleName=vehicle_name,
        sessionId=sessionId or (sess_obj.id if sess_obj else None),
        points=points,
        alerts=alerts,
    )


@router.get("/rest-stops/nearest", response_model=list[NearestRestStopItem])
def get_nearest_rest_stops_endpoint(
    lat: float = Query(ge=-90.0, le=90.0),
    lng: float = Query(ge=-180.0, le=180.0),
    limit: int = Query(default=5, ge=1, le=20),
    current_user: User = Depends(require_roles("manager", "dispatcher", "driver")),
    db: Session = Depends(get_db),
) -> list[NearestRestStopItem]:
    org_id = get_jwt_org_id(current_user)
    return find_nearest_rest_stops(db, org_id, lat=lat, lng=lng, limit=limit)


# --- ALARM FATIGUE & APP USAGE 7D (P3-4) ---
@router.post("/events/{id}/feedback", response_model=AlertEvent)
def post_event_feedback_direct(
    id: str,
    payload: DriverFeedbackRequest,
    current_user: User = Depends(require_roles("driver", "dispatcher", "manager")),
    db: Session = Depends(get_db),
) -> AlertEvent:
    from ..services.events_service import get_or_create_daily_usage

    org_id = get_jwt_org_id(current_user)
    ev = db.get(EventModel, id)
    if ev is None or ev.organization_id != org_id:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "EVENT_NOT_FOUND",
            "Không tìm thấy sự kiện cảnh báo trong tổ chức",
        )
    if current_user.role == "driver" and ev.driver_id != current_user.id:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN",
            "Tài xế chỉ được gửi phản hồi cho cảnh báo của chính mình",
        )

    old_fb = ev.driver_feedback
    ev.driver_feedback = payload.feedback
    usage = get_or_create_daily_usage(
        db, org_id, ev.driver_id, ensure_utc(ev.occurred_at) or datetime.now(timezone.utc)
    )
    if old_fb != "false_alarm" and payload.feedback == "false_alarm":
        usage.alerts_false += 1
        if usage.alerts_total < usage.alerts_false:
            usage.alerts_total = usage.alerts_false
    elif old_fb == "false_alarm" and payload.feedback == "correct":
        usage.alerts_false = max(0, usage.alerts_false - 1)

    db.commit()
    db.refresh(ev)

    drv = db.get(User, ev.driver_id)
    d_name = drv.full_name if drv else "Tài xế"
    vehicle_map = get_vehicle_name_map(db, org_id)
    v_id = ev.vehicle_id or (drv.vehicle_id if drv else None)
    v_name = vehicle_map.get(v_id, "Chưa phân xe") if v_id else "Chưa phân xe"
    return event_to_schema(ev, d_name, v_name)


@router.get("/stats/alarm-fatigue", response_model=list[DriverUsage7dItem])
def get_alarm_fatigue_stats_7d(
    current_user: User = Depends(require_roles("manager", "dispatcher")),
    db: Session = Depends(get_db),
) -> list[DriverUsage7dItem]:
    """Return 7-day per-driver monitoring-off rate & false-alarm % matching `v_driver_usage_7d`."""
    org_id = get_jwt_org_id(current_user)
    cutoff_date = to_vn_time(datetime.now(timezone.utc)).date() - timedelta(days=6)

    drivers = db.scalars(
        select(User)
        .where(User.organization_id == org_id, User.role == "driver")
        .order_by(User.full_name.asc())
    ).all()

    usage_rows = db.scalars(
        select(AppUsageDaily).where(
            AppUsageDaily.organization_id == org_id,
            AppUsageDaily.usage_date >= cutoff_date,
        )
    ).all()

    agg: dict[str, list[int]] = {}
    for r in usage_rows:
        bucket = agg.setdefault(r.driver_id, [0, 0, 0, 0])
        bucket[0] += int(r.monitored_minutes or 0)
        bucket[1] += int(r.monitoring_off_count or 0)
        bucket[2] += int(r.alerts_total or 0)
        bucket[3] += int(r.alerts_false or 0)

    items: list[DriverUsage7dItem] = []
    for drv in drivers:
        mon_min, off_cnt, al_tot, al_false = agg.get(drv.id, [0, 0, 0, 0])
        hours = mon_min / 60.0
        off_per_hour = round(off_cnt / hours, 2) if hours > 0 else 0.0
        false_pct = round((100.0 * al_false) / al_tot, 1) if al_tot > 0 else 0.0
        items.append(
            DriverUsage7dItem(
                driverId=drv.id,
                fullName=drv.full_name,
                monitoredMinutes=mon_min,
                monitoringOffCount=off_cnt,
                alertsTotal=al_tot,
                alertsFalse=al_false,
                offPerHour=off_per_hour,
                falseAlertPct=false_pct,
            )
        )

    items.sort(key=lambda x: (-x.falseAlertPct, -x.offPerHour, x.fullName))
    return items


# --- FCM PUSH TOKENS (P3-7) ---
@router.post("/push-tokens", response_model=PushTokenItem, status_code=status.HTTP_201_CREATED)
def register_push_token(
    payload: RegisterPushTokenRequest,
    current_user: User = Depends(require_roles("manager", "dispatcher", "driver")),
    db: Session = Depends(get_db),
) -> PushTokenItem:
    org_id = get_jwt_org_id(current_user)
    now = datetime.now(timezone.utc)
    existing = db.scalar(
        select(PushToken).where(
            PushToken.user_id == current_user.id,
            PushToken.fcm_token == payload.fcmToken,
        )
    )
    if existing is not None:
        existing.organization_id = org_id
        existing.platform = payload.platform
        existing.updated_at = now
        row = existing
    else:
        row = PushToken(
            organization_id=org_id,
            user_id=current_user.id,
            fcm_token=payload.fcmToken,
            platform=payload.platform,
            updated_at=now,
        )
        db.add(row)

    db.commit()
    db.refresh(row)
    return PushTokenItem(
        id=row.id,
        userId=row.user_id,
        fcmToken=row.fcm_token,
        platform=row.platform,  # type: ignore[arg-type]
        updatedAt=ensure_utc(row.updated_at),  # type: ignore[arg-type]
    )


@router.get("/push-tokens", response_model=list[PushTokenItem])
def list_my_push_tokens(
    current_user: User = Depends(require_roles("manager", "dispatcher", "driver")),
    db: Session = Depends(get_db),
) -> list[PushTokenItem]:
    org_id = get_jwt_org_id(current_user)
    rows = db.scalars(
        select(PushToken)
        .where(
            PushToken.organization_id == org_id,
            PushToken.user_id == current_user.id,
        )
        .order_by(PushToken.updated_at.desc())
    ).all()
    return [
        PushTokenItem(
            id=r.id,
            userId=r.user_id,
            fcmToken=r.fcm_token,
            platform=r.platform,  # type: ignore[arg-type]
            updatedAt=ensure_utc(r.updated_at),  # type: ignore[arg-type]
        )
        for r in rows
    ]


@router.delete("/push-tokens")
def unregister_push_token(
    payload: UnregisterPushTokenRequest,
    current_user: User = Depends(require_roles("manager", "dispatcher", "driver")),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    org_id = get_jwt_org_id(current_user)
    row = db.scalar(
        select(PushToken).where(
            PushToken.organization_id == org_id,
            PushToken.user_id == current_user.id,
            PushToken.fcm_token == payload.fcmToken,
        )
    )
    if row is None:
        return {"deleted": 0}
    db.delete(row)
    db.commit()
    return {"deleted": 1}


# --- OUTBOUND HMAC WEBHOOKS (MANAGER ONLY - P3-8) ---
@router.get("/webhooks", response_model=list[WebhookItem])
def list_webhooks(
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> list[WebhookItem]:
    org_id = get_jwt_org_id(current_user)
    rows = db.scalars(
        select(Webhook)
        .where(Webhook.organization_id == org_id)
        .order_by(Webhook.created_at.desc())
    ).all()
    return [
        WebhookItem(
            id=w.id,
            url=w.url,
            events=list(w.events or []),
            isActive=bool(w.is_active),
            createdAt=ensure_utc(w.created_at),  # type: ignore[arg-type]
        )
        for w in rows
    ]


@router.post("/webhooks", response_model=WebhookCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_webhook(
    payload: CreateWebhookRequest,
    request: Request,
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> WebhookCreatedResponse:
    org_id = get_jwt_org_id(current_user)
    raw_secret = payload.secret.strip() if payload.secret else f"whsec_{generate_opaque_token()}"
    sealed = seal_webhook_secret(raw_secret)
    wh = Webhook(
        organization_id=org_id,
        url=payload.url.strip(),
        secret_hash=sealed,
        events=list(payload.events),
        is_active=True,
    )
    db.add(wh)
    db.flush()
    record_audit_log(
        db,
        organization_id=org_id,
        actor_id=current_user.id,
        action="create_webhook",
        entity="webhook",
        entity_id=wh.id,
        request=request,
        meta={"url": wh.url, "events": list(wh.events or [])},
    )
    db.commit()
    db.refresh(wh)
    return WebhookCreatedResponse(
        id=wh.id,
        url=wh.url,
        events=list(wh.events or []),
        isActive=bool(wh.is_active),
        createdAt=ensure_utc(wh.created_at),  # type: ignore[arg-type]
        secret=raw_secret,
    )


@router.delete("/webhooks/{id}")
def delete_webhook(
    id: str,
    request: Request,
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    org_id = get_jwt_org_id(current_user)
    wh = db.get(Webhook, id)
    if wh is None or wh.organization_id != org_id:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "WEBHOOK_NOT_FOUND",
            "Không tìm thấy webhook trong tổ chức",
        )
    wh.is_active = False
    record_audit_log(
        db,
        organization_id=org_id,
        actor_id=current_user.id,
        action="delete_webhook",
        entity="webhook",
        entity_id=wh.id,
        request=request,
        meta={"url": wh.url},
    )
    db.commit()
    return {"status": "deactivated", "id": wh.id}


# --- ZALO OA/ZNS & SMS NOTIFICATION CHANNELS (P3-9) ---
@router.get("/notifications/status")
def get_notification_channels_status(
    current_user: User = Depends(require_roles("manager")),
) -> dict[str, object]:
    _ = get_jwt_org_id(current_user)
    return {"channels": notification_dispatcher.get_provider_statuses()}


@router.post("/notifications/test")
def send_test_notification(
    channel: Literal["zalo", "sms", "push"] = Query(default="zalo"),
    current_user: User = Depends(require_roles("manager")),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _ = get_jwt_org_id(current_user)
    res = notify_user(
        db=db,
        recipient=current_user,
        channel=channel,
        title="PreDrive AI — Kiểm tra kênh cảnh báo",
        body="Tin nhắn kiểm tra kết nối thông báo tự động.",
    )
    return {
        "delivered": res.delivered,
        "channelUsed": res.channel_used,
        "provider": res.provider,
        "fallbackUsed": res.fallback_used,
        "error": res.error,
    }
