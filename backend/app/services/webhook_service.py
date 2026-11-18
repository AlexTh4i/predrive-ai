from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Literal
import urllib.error
import urllib.request
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_config
from ..models.models import Webhook

logger = logging.getLogger("predrive.webhooks")

WebhookEventType = Literal["alert.created", "alert.escalated"]


def _derive_stream_bytes(master_key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(
            master_key, nonce + counter.to_bytes(4, "big"), hashlib.sha256
        ).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def seal_webhook_secret(raw_secret: str) -> str:
    """Protect `raw_secret` at rest inside `webhooks.secret_hash` using authenticated stream
    encryption keyed by `PREDRIVE_JWT_SECRET` so plaintext webhook secrets are never stored in DB.
    """
    master = hashlib.sha256(get_config().jwt_secret.encode("utf-8")).digest()
    nonce = secrets.token_bytes(16)
    pt = raw_secret.encode("utf-8")
    ks = _derive_stream_bytes(master, nonce, len(pt))
    ct = bytes(a ^ b for a, b in zip(pt, ks))
    tag = hmac.new(master, b"whsec:v1:" + nonce + ct, hashlib.sha256).hexdigest()[:32]
    return f"enc1:{nonce.hex()}:{ct.hex()}:{tag}"


def unseal_webhook_secret(stored_secret_hash: str) -> bytes:
    """Recover signing key bytes from `webhooks.secret_hash` (supports both `enc1:` sealed secrets
    and pre-hashed seed rows).
    """
    if not stored_secret_hash.startswith("enc1:"):
        return stored_secret_hash.encode("utf-8")
    parts = stored_secret_hash.split(":")
    if len(parts) != 4:
        return stored_secret_hash.encode("utf-8")
    _, nonce_hex, ct_hex, tag_hex = parts
    nonce = bytes.fromhex(nonce_hex)
    ct = bytes.fromhex(ct_hex)
    master = hashlib.sha256(get_config().jwt_secret.encode("utf-8")).digest()
    expected_tag = hmac.new(
        master, b"whsec:v1:" + nonce + ct, hashlib.sha256
    ).hexdigest()[:32]
    if not hmac.compare_digest(expected_tag, tag_hex):
        raise ValueError("Webhook secret integrity check failed")
    ks = _derive_stream_bytes(master, nonce, len(ct))
    return bytes(a ^ b for a, b in zip(ct, ks))


def compute_webhook_signature(secret_bytes: bytes, body_bytes: bytes) -> str:
    digest = hmac.new(secret_bytes, body_bytes, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def deliver_single_webhook(
    url: str,
    secret_bytes: bytes,
    event_type: WebhookEventType,
    body_bytes: bytes,
    delivery_id: str,
    max_attempts: int | None = None,
    base_backoff_sec: float | None = None,
) -> tuple[bool, int]:
    """Deliver signed webhook HTTP POST with exponential backoff retry on 5xx / network errors.
    Returns `(delivered_ok, attempts_made)`.
    """
    attempts_limit = (
        max_attempts
        if max_attempts is not None
        else max(1, int(os.getenv("WEBHOOK_MAX_ATTEMPTS", "3")))
    )
    backoff_base = (
        base_backoff_sec
        if base_backoff_sec is not None
        else float(os.getenv("WEBHOOK_BACKOFF_BASE_SEC", "0.2"))
    )
    timeout_sec = float(os.getenv("WEBHOOK_TIMEOUT_SEC", "4.0"))
    signature = compute_webhook_signature(secret_bytes, body_bytes)

    for attempt in range(1, attempts_limit + 1):
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "PreDriveAI-Webhook/1.0",
                "X-PreDrive-Event": event_type,
                "X-PreDrive-Delivery": delivery_id,
                "X-PreDrive-Signature": signature,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                if 200 <= resp.status < 300:
                    return True, attempt
                if resp.status < 500 and resp.status != 429:
                    # 4xx client error (except 429) is permanent; do not retry
                    return False, attempt
        except urllib.error.HTTPError as http_err:
            if 400 <= http_err.code < 500 and http_err.code != 429:
                return False, attempt
        except Exception as exc:
            logger.warning(
                "Webhook delivery %s to %s attempt %d/%d failed: %s",
                delivery_id,
                url,
                attempt,
                attempts_limit,
                exc,
            )

        if attempt < attempts_limit and backoff_base > 0:
            time.sleep(backoff_base * (2 ** (attempt - 1)))

    return False, attempts_limit


def dispatch_webhooks_for_event(
    db: Session,
    org_id: str,
    event_type: WebhookEventType,
    event_payload: dict[str, Any],
) -> int:
    """Find active webhooks subscribed to `event_type` for `org_id` and deliver signed payloads.
    Returns count of successfully delivered webhooks.
    """
    hooks = db.scalars(
        select(Webhook).where(
            Webhook.organization_id == org_id,
            Webhook.is_active.is_(True),
        )
    ).all()
    matching = [h for h in hooks if event_type in (h.events or []) or "*" in (h.events or [])]
    if not matching:
        return 0

    envelope = {
        "event": event_type,
        "organizationId": org_id,
        "sentAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data": event_payload,
    }
    body_bytes = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")

    delivered_count = 0
    for wh in matching:
        # Skip dummy example.com seed URLs unless explicitly overridden in tests
        if "hooks.example.com/" in wh.url and os.getenv("ALLOW_EXAMPLE_WEBHOOKS") != "1":
            continue
        try:
            secret_bytes = unseal_webhook_secret(wh.secret_hash)
            ok, _ = deliver_single_webhook(
                url=wh.url,
                secret_bytes=secret_bytes,
                event_type=event_type,
                body_bytes=body_bytes,
                delivery_id=str(uuid4()),
            )
            if ok:
                delivered_count += 1
        except Exception as exc:
            logger.warning("Webhook %s dispatch error: %s", wh.id, exc)

    return delivered_count
