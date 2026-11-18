from __future__ import annotations

from datetime import datetime, timezone
import ipaddress
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.orm import Session

from ..models.models import AuditLog


def extract_client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    xff = request.headers.get("x-forwarded-for")
    cand: Optional[str] = None
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            cand = first
    if not cand and request.client and request.client.host:
        cand = request.client.host
    if not cand:
        return None
    if cand in ("testclient", "localhost"):
        return "127.0.0.1"
    try:
        return str(ipaddress.ip_address(cand))
    except ValueError:
        return None


def record_audit_log(
    db: Session,
    *,
    organization_id: Optional[str],
    actor_id: Optional[str],
    action: str,
    entity: Optional[str] = None,
    entity_id: Optional[str] = None,
    request: Optional[Request] = None,
    ip: Optional[str] = None,
    meta: Optional[dict[str, Any]] = None,
    commit: bool = False,
) -> AuditLog:
    row = AuditLog(
        organization_id=organization_id,
        actor_id=actor_id,
        action=action,
        entity=entity,
        entity_id=str(entity_id) if entity_id is not None else None,
        ip=ip if ip is not None else extract_client_ip(request),
        meta=meta or {},
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    if commit:
        db.commit()
    return row
