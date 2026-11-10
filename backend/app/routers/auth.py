from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.errors import AppError
from ..core.security import (
    create_access_token,
    get_current_user,
    require_roles,
    verify_password,
)
from ..models.models import Organization, Pairing, User, Vehicle
from ..schemas.m3 import (
    AuthUserSchema,
    LoginRequest,
    LoginResponse,
    PairRequest,
    PairResponse,
)
from ..services.mappers import ensure_utc

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


def _user_to_auth_schema(user: User) -> AuthUserSchema:
    return AuthUserSchema(
        id=user.id,
        role=user.role,  # type: ignore[arg-type]
        fullName=user.full_name,
        organizationId=user.organization_id,
    )


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    ident = payload.username.strip()
    user = db.scalar(
        select(User).where(or_(User.username == ident, User.phone == ident))
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_CREDENTIALS",
            "Tên đăng nhập hoặc mật khẩu không chính xác",
        )

    token = create_access_token(
        user_id=user.id,
        role=user.role,
        organization_id=user.organization_id,
    )
    return LoginResponse(accessToken=token, user=_user_to_auth_schema(user))


@router.get("/me", response_model=AuthUserSchema)
def get_me(current_user: User = Depends(get_current_user)) -> AuthUserSchema:
    return _user_to_auth_schema(current_user)


@router.post("/pair", response_model=PairResponse)
def pair_driver_vehicle(
    payload: PairRequest,
    current_user: User = Depends(require_roles("driver")),
    db: Session = Depends(get_db),
) -> PairResponse:
    now = datetime.now(timezone.utc)
    code = payload.code.strip().upper()
    pairing = db.scalar(select(Pairing).where(Pairing.code == code))
    if pairing is None:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "INVALID_PAIRING_CODE",
            "Mã ghép đôi không tồn tại",
        )

    exp = ensure_utc(pairing.expires_at)
    if pairing.status == "EXPIRED" or (exp is not None and exp <= now):
        pairing.status = "EXPIRED"
        db.commit()
        raise AppError(
            status.HTTP_400_BAD_REQUEST,
            "PAIRING_CODE_EXPIRED",
            "Mã ghép đôi đã hết hạn",
        )

    if pairing.status == "PAIRED" and pairing.driver_id not in (None, current_user.id):
        raise AppError(
            status.HTTP_409_CONFLICT,
            "PAIRING_CODE_USED",
            "Mã ghép đôi đã được sử dụng bởi tài xế khác",
        )

    vehicle: Vehicle | None = None
    if pairing.vehicle_id:
        vehicle = db.get(Vehicle, pairing.vehicle_id)
    if vehicle is None:
        vehicle = db.scalar(
            select(Vehicle)
            .where(Vehicle.organization_id == pairing.organization_id)
            .order_by(Vehicle.created_at.asc())
        )

    org = db.get(Organization, pairing.organization_id)
    org_name = org.name if org else "Nhà xe PreDrive"
    veh_name = vehicle.name if vehicle else "Xe tiêu chuẩn"

    current_user.organization_id = pairing.organization_id
    if vehicle is not None:
        current_user.vehicle_id = vehicle.id
        pairing.vehicle_id = vehicle.id

    pairing.driver_id = current_user.id
    pairing.consented_at = now
    pairing.status = "PAIRED"
    db.commit()

    return PairResponse(vehicleName=veh_name, organizationName=org_name)

