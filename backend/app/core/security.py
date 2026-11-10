from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
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
    return _ph.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, plain_password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


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


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHORIZED",
            "Missing Authorization Bearer token",
        )
    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Malformed token payload"
        )
    user = db.get(User, user_id)
    if user is None:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED", "User no longer exists"
        )
    return user


def get_current_user_sse(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    token: Optional[str] = Query(default=None, include_in_schema=False),
    db: Session = Depends(get_db),
) -> User:
    raw_token = credentials.credentials if credentials and credentials.credentials else token
    if not raw_token:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED,
            "UNAUTHORIZED",
            "Missing Authorization Bearer token",
        )
    payload = decode_access_token(raw_token)
    user_id = payload.get("sub")
    if not user_id:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED, "INVALID_TOKEN", "Malformed token payload"
        )
    user = db.get(User, user_id)
    if user is None:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED", "User no longer exists"
        )
    return user


def require_roles(*allowed_roles: str) -> Callable[[User], User]:
    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise AppError(
                status.HTTP_403_FORBIDDEN,
                "FORBIDDEN",
                f"Role '{current_user.role}' is not permitted for this action",
            )
        return current_user

    return dependency

