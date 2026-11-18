from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from ..core.config import get_config
from ..core.database import get_db
from ..core.errors import AppError
from ..core.security import (
    create_access_token,
    generate_opaque_token,
    get_current_user_allow_must_change,
    hash_password,
    hash_token,
    require_roles,
    verify_password,
)
from ..models.models import Organization, Pairing, RefreshToken, User, Vehicle, new_uuid
from ..schemas.m3 import (
    AuthUserSchema,
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    PairRequest,
    PairResponse,
    RefreshTokenRequest,
)
from ..services.mappers import ensure_utc
from ..services.rate_limiter import enforce_login_rate_limit, enforce_pair_rate_limit

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


def _client_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    if request.client and request.client.host:
        host = request.client.host
        # Map TestClient 'testclient' pseudo-host to valid loopback IP for PostgreSQL INET column
        return "127.0.0.1" if host == "testclient" else host
    return None


def _user_to_auth_schema(user: User) -> AuthUserSchema:
    return AuthUserSchema(
        id=user.id,
        role=user.role,  # type: ignore[arg-type]
        fullName=user.full_name,
        organizationId=user.organization_id,
        mustChangePassword=bool(user.must_change_password),
    )


def _issue_token_pair(
    db: Session,
    user: User,
    request: Request,
    family_id: str | None = None,
) -> tuple[str, str, RefreshToken]:
    cfg = get_config()
    now = datetime.now(timezone.utc)
    access_token = create_access_token(
        user_id=user.id,
        role=user.role,
        organization_id=user.organization_id,
    )
    raw_refresh = generate_opaque_token()
    rt_row = RefreshToken(
        id=new_uuid(),
        organization_id=user.organization_id,
        user_id=user.id,
        family_id=family_id or new_uuid(),
        token_hash=hash_token(raw_refresh),
        expires_at=now + timedelta(days=cfg.refresh_token_expire_days),
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
        ip=_client_ip(request),
        created_at=now,
    )
    db.add(rt_row)
    return access_token, raw_refresh, rt_row


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    ident = payload.username.strip()
    enforce_login_rate_limit(_client_ip(request), ident)
    user = db.scalar(
        select(User).where(or_(User.username == ident, User.phone == ident))
    )
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_CREDENTIALS",
            "Tên đăng nhập hoặc mật khẩu không chính xác",
        )

    now = datetime.now(timezone.utc)
    user.last_login_at = now
    access_token, raw_refresh, _ = _issue_token_pair(db, user, request)
    db.commit()

    cfg = get_config()
    return LoginResponse(
        accessToken=access_token,
        refreshToken=raw_refresh,
        expiresIn=cfg.jwt_expire_minutes * 60,
        user=_user_to_auth_schema(user),
    )


@router.post("/refresh", response_model=LoginResponse)
def refresh_access_token(
    payload: RefreshTokenRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> LoginResponse:
    now = datetime.now(timezone.utc)
    incoming_hash = hash_token(payload.refreshToken.strip())
    rt = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == incoming_hash)
    )
    if rt is None:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "INVALID_REFRESH_TOKEN",
            "Refresh token không hợp lệ",
        )

    # Reuse detection: if an already-rotated / revoked token is presented again,
    # immediately revoke the ENTIRE token family!
    if rt.revoked_at is not None:
        db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.family_id == rt.family_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        db.commit()
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "REFRESH_TOKEN_REUSED",
            "Phát hiện tái sử dụng refresh token cũ — toàn bộ phiên đã bị thu hồi",
        )

    exp_utc = ensure_utc(rt.expires_at)
    if exp_utc is not None and exp_utc <= now:
        rt.revoked_at = now
        db.commit()
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "REFRESH_TOKEN_EXPIRED",
            "Refresh token đã hết hạn",
        )

    user = db.get(User, rt.user_id)
    if user is None or not user.is_active:
        rt.revoked_at = now
        db.commit()
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHORIZED",
            "Tài khoản không tồn tại hoặc đã bị khóa",
        )

    access_token, new_raw_refresh, new_rt = _issue_token_pair(
        db, user, request, family_id=rt.family_id
    )
    db.flush()
    rt.revoked_at = now
    rt.replaced_by_id = new_rt.id
    db.commit()

    cfg = get_config()
    return LoginResponse(
        accessToken=access_token,
        refreshToken=new_raw_refresh,
        expiresIn=cfg.jwt_expire_minutes * 60,
        user=_user_to_auth_schema(user),
    )


@router.post("/logout")
def logout(
    payload: LogoutRequest = LogoutRequest(),
    current_user: User = Depends(get_current_user_allow_must_change),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    if payload.refreshToken:
        t_hash = hash_token(payload.refreshToken.strip())
        rt = db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == t_hash,
                RefreshToken.user_id == current_user.id,
            )
        )
        if rt is not None:
            db.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == rt.family_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
    else:
        db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == current_user.id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
    db.commit()
    return {"status": "ok"}


@router.post("/change-password", response_model=AuthUserSchema)
def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user_allow_must_change),
    db: Session = Depends(get_db),
) -> AuthUserSchema:
    if not verify_password(payload.currentPassword, current_user.password_hash):
        raise AppError(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_CURRENT_PASSWORD",
            "Mật khẩu hiện tại không chính xác",
        )
    if payload.newPassword == payload.currentPassword:
        raise AppError(
            status.HTTP_400_BAD_REQUEST,
            "SAME_PASSWORD",
            "Mật khẩu mới phải khác mật khẩu hiện tại",
        )

    now = datetime.now(timezone.utc)
    current_user.password_hash = hash_password(payload.newPassword)
    current_user.must_change_password = False

    # Revoke all existing refresh tokens of this user on password change (P1-2)
    db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    db.commit()
    db.refresh(current_user)
    return _user_to_auth_schema(current_user)


@router.get("/me", response_model=AuthUserSchema)
def get_me(
    current_user: User = Depends(get_current_user_allow_must_change),
) -> AuthUserSchema:
    return _user_to_auth_schema(current_user)


@router.post("/pair", response_model=PairResponse)
def pair_driver_vehicle(
    payload: PairRequest,
    request: Request,
    current_user: User = Depends(require_roles("driver", allow_must_change=True)),
    db: Session = Depends(get_db),
) -> PairResponse:
    enforce_pair_rate_limit(current_user.id, _client_ip(request))
    now = datetime.now(timezone.utc)
    code = payload.code.strip().upper()
    # Multi-tenant enforcement (R6 / P1-5): driver can ONLY pair with a code from their own organization!
    pairing = db.scalar(
        select(Pairing).where(
            Pairing.code == code,
            Pairing.organization_id == current_user.organization_id,
        )
    )
    if pairing is None:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "INVALID_PAIRING_CODE",
            "Mã ghép đôi không tồn tại trong tổ chức của bạn",
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
        veh_cand = db.get(Vehicle, pairing.vehicle_id)
        if veh_cand and veh_cand.organization_id == current_user.organization_id:
            vehicle = veh_cand
    if vehicle is None:
        vehicle = db.scalar(
            select(Vehicle)
            .where(Vehicle.organization_id == current_user.organization_id)
            .order_by(Vehicle.created_at.asc())
        )

    org = db.get(Organization, current_user.organization_id)
    org_name = org.name if org else "Nhà xe PreDrive"
    veh_name = vehicle.name if vehicle else "Xe tiêu chuẩn"

    if vehicle is not None:
        current_user.vehicle_id = vehicle.id
        pairing.vehicle_id = vehicle.id

    pairing.driver_id = current_user.id
    pairing.used_at = now
    pairing.consented_at = now
    pairing.status = "PAIRED"
    db.commit()

    return PairResponse(vehicleName=veh_name, organizationName=org_name)
