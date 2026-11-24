from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Security, status
from fastapi.security import APIKeyHeader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.errors import AppError
from ..core.security import hash_token
from ..models.models import (
    ApiKey,
    EventModel,
    LocationModel,
    SessionModel,
    User,
    Vehicle,
)
from ..schemas.m3 import (
    AlertEvent,
    CamelModel,
    EventLevel,
    PaginatedEventsResponse,
    UtcDatetime,
)
from ..services.mappers import (
    build_live_driver_state,
    ensure_utc,
    event_to_schema,
    get_or_create_org_settings,
    get_vehicle_name_map,
)
from ..services.sse import sse_broker

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Khóa tích hợp đối tác (`pd_live_...`), chỉ lưu SHA-256 hash trong bảng `api_keys`.",
)

router = APIRouter(
    prefix="/api/public/v1",
    tags=["Third-Party Public API (X-API-Key)"],
)


class PublicVehicleItem(CamelModel):
    id: str
    plate: str
    vehicleType: str
    brandModel: Optional[str] = None
    trackerDeviceId: Optional[str] = None
    isActive: bool


class TrackerLocationPayload(CamelModel):
    trackerDeviceId: str
    lat: float
    lng: float
    speedKmh: Optional[float] = None
    headingDeg: Optional[float] = None
    at: Optional[UtcDatetime] = None


class TrackerLocationAcceptedResponse(CamelModel):
    status: str = "accepted"
    vehicleId: str
    plate: str
    driverId: Optional[str] = None
    recordedAt: UtcDatetime


def require_api_key_scope(required_scope: str):
    def _dep(
        raw_key: Optional[str] = Security(api_key_header),
        db: Session = Depends(get_db),
    ) -> ApiKey:
        if not raw_key or not raw_key.strip():
            raise AppError(
                status.HTTP_401_UNAUTHORIZED,
                "MISSING_API_KEY",
                "Thiếu header X-API-Key hợp lệ",
            )
        token_hash = hash_token(raw_key.strip())
        key_row = db.scalar(select(ApiKey).where(ApiKey.key_hash == token_hash))
        if key_row is None:
            raise AppError(
                status.HTTP_401_UNAUTHORIZED,
                "INVALID_API_KEY",
                "API key không tồn tại hoặc không hợp lệ",
            )
        if key_row.revoked_at is not None:
            raise AppError(
                status.HTTP_401_UNAUTHORIZED,
                "API_KEY_REVOKED",
                "API key này đã bị thu hồi",
            )
        scopes = set(key_row.scopes or [])
        if required_scope not in scopes and "*" not in scopes:
            raise AppError(
                status.HTTP_403_FORBIDDEN,
                "INSUFFICIENT_SCOPE",
                f"API key thiếu quyền truy cập '{required_scope}'",
            )
        key_row.last_used_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(key_row)
        return key_row

    return _dep


@router.get(
    "/vehicles",
    response_model=list[PublicVehicleItem],
    summary="Danh sách phương tiện của công ty (yêu cầu scope `vehicles:read`)",
)
def public_list_vehicles(
    api_key: ApiKey = Depends(require_api_key_scope("vehicles:read")),
    db: Session = Depends(get_db),
) -> list[PublicVehicleItem]:
    org_id = api_key.organization_id
    rows = db.scalars(
        select(Vehicle)
        .where(Vehicle.organization_id == org_id)
        .order_by(Vehicle.plate.asc())
    ).all()
    return [
        PublicVehicleItem(
            id=v.id,
            plate=v.plate,
            vehicleType=v.vehicle_type,
            brandModel=v.brand_model,
            trackerDeviceId=v.tracker_device_id,
            isActive=bool(v.is_active),
        )
        for v in rows
    ]


@router.get(
    "/events",
    response_model=PaginatedEventsResponse,
    summary="Truy vấn sự kiện cảnh báo của công ty (yêu cầu scope `events:read`)",
)
def public_list_events(
    level: Optional[EventLevel] = Query(default=None),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=20, ge=1, le=200),
    api_key: ApiKey = Depends(require_api_key_scope("events:read")),
    db: Session = Depends(get_db),
) -> PaginatedEventsResponse:
    org_id = api_key.organization_id
    filters = [EventModel.organization_id == org_id]
    if level == "CRITICAL":
        filters.append(EventModel.level == 3)
    elif level == "WARNING":
        filters.append(EventModel.level <= 2)

    total = int(db.scalar(select(func.count(EventModel.id)).where(*filters)) or 0)
    rows = db.scalars(
        select(EventModel)
        .where(*filters)
        .order_by(EventModel.occurred_at.desc())
        .offset((page - 1) * pageSize)
        .limit(pageSize)
    ).all()

    drivers = {
        u.id: u.full_name
        for u in db.scalars(select(User).where(User.organization_id == org_id)).all()
    }
    vehicles = get_vehicle_name_map(db, org_id)

    items: list[AlertEvent] = [
        event_to_schema(
            ev,
            drivers.get(ev.driver_id, "Tài xế"),
            vehicles.get(ev.vehicle_id, "Chưa phân xe") if ev.vehicle_id else "Chưa phân xe",
        )
        for ev in rows
    ]
    return PaginatedEventsResponse(items=items, total=total)


@router.post(
    "/tracker/locations",
    response_model=TrackerLocationAcceptedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Nhận tọa độ GPS từ hộp đen / thiết bị giám sát hành trình qua `trackerDeviceId` (scope `tracker:write`)",
)
def public_ingest_tracker_location(
    payload: TrackerLocationPayload,
    api_key: ApiKey = Depends(require_api_key_scope("tracker:write")),
    db: Session = Depends(get_db),
) -> TrackerLocationAcceptedResponse:
    org_id = api_key.organization_id
    vehicle = db.scalar(
        select(Vehicle).where(
            Vehicle.organization_id == org_id,
            Vehicle.tracker_device_id == payload.trackerDeviceId.strip(),
        )
    )
    if vehicle is None:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "TRACKER_NOT_FOUND",
            "Không tìm thấy phương tiện khớp trackerDeviceId trong tổ chức",
        )

    now = datetime.now(timezone.utc)
    rec_at = ensure_utc(payload.at) if payload.at else now

    active_sess = db.scalar(
        select(SessionModel)
        .where(
            SessionModel.organization_id == org_id,
            SessionModel.vehicle_id == vehicle.id,
            SessionModel.ended_at.is_(None),
        )
        .order_by(SessionModel.started_at.desc())
    )
    assigned_driver = None
    if active_sess is not None:
        assigned_driver = db.get(User, active_sess.driver_id)
    if assigned_driver is None:
        assigned_driver = db.scalar(
            select(User).where(
                User.organization_id == org_id,
                User.vehicle_id == vehicle.id,
                User.role == "driver",
            )
        )

    loc = LocationModel(
        organization_id=org_id,
        session_id=active_sess.id if active_sess else None,
        vehicle_id=vehicle.id,
        driver_id=assigned_driver.id if assigned_driver else None,
        lat=payload.lat,
        lng=payload.lng,
        speed_kmh=payload.speedKmh,
        heading_deg=payload.headingDeg,
        ts=rec_at,
    )
    db.add(loc)
    db.commit()

    if assigned_driver is not None:
        org_settings = get_or_create_org_settings(db, org_id)
        live_state = build_live_driver_state(
            db, assigned_driver, share_location=org_settings.share_location
        )
        sse_broker.publish(org_id, "driver_state", live_state.model_dump(mode="json"))

    return TrackerLocationAcceptedResponse(
        status="accepted",
        vehicleId=vehicle.id,
        plate=vehicle.plate,
        driverId=assigned_driver.id if assigned_driver else None,
        recordedAt=rec_at,
    )
