from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlalchemy.orm import Session

from ..models.models import User
from .config import get_config
from .database import get_db
from .errors import AppError

# Argon2id hasher (configured for fast interactive auth while maintaining Argon2id security)
_ph = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    if password == "!UNSET":
        return "!UNSET"
    return _ph.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    if not password_hash or password_hash == "!UNSET":
        return False
    try:
        return _ph.verify(password_hash, plain_password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def generate_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_access_token(
    user_id: str,
    role: str,
    organization_id: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    cfg = get_config()
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=cfg.jwt_expire_minutes))
    payload = {
        "sub": user_id,
        "role": role,
        "org": organization_id,
        "app_metadata": {"org_id": organization_id},
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    cfg = get_config()
    try:
        return jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED, "TOKEN_EXPIRED", "Access token has expired"
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Invalid access token"
        ) from exc


def _resolve_user_from_token(raw_token: str, db: Session) -> User:
    payload = decode_access_token(raw_token)
    user_id = payload.get("sub")
    jwt_org_id = payload.get("org")
    if not user_id or not jwt_org_id:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Malformed token payload"
        )
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHORIZED",
            "User no longer exists or is inactive",
        )
    if str(user.organization_id) != str(jwt_org_id):
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "ORG_MISMATCH",
            "Token organization claim no longer matches user organization",
        )
    # Enforce organization_id extracted directly from verified JWT claim (R6 / P1-5)
    object.__setattr__(user, "_jwt_org_id", str(jwt_org_id))
    return user


def get_current_user_allow_must_change(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHORIZED",
            "Missing Authorization Bearer token",
        )
    return _resolve_user_from_token(credentials.credentials, db)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    user = get_current_user_allow_must_change(credentials=credentials, db=db)
    if user.must_change_password:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "PASSWORD_CHANGE_REQUIRED",
            "Tài khoản bắt buộc đổi mật khẩu trong lần đăng nhập đầu tiên",
        )
    return user


def get_current_user_sse(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    token: Optional[str] = Query(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
) -> User:
    raw_token = (
        credentials.credentials if credentials and credentials.credentials else token
    )
    if not raw_token:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHORIZED",
            "Missing Authorization Bearer token",
        )
    user = _resolve_user_from_token(raw_token, db)
    if user.must_change_password:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "PASSWORD_CHANGE_REQUIRED",
            "Tài khoản bắt buộc đổi mật khẩu trong lần đăng nhập đầu tiên",
        )
    return user


def require_roles(
    *allowed_roles: str, allow_must_change: bool = False
) -> Callable[[User], User]:
    dep = get_current_user_allow_must_change if allow_must_change else get_current_user

    def dependency(current_user: User = Depends(dep)) -> User:
        if current_user.role not in allowed_roles:
            raise AppError(
                status.HTTP_403_FORBIDDEN,
                "FORBIDDEN",
                f"Role '{current_user.role}' is not permitted for this action",
            )
        return current_user

    return dependency
