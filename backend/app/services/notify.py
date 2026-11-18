from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any, Optional, Protocol
import urllib.error
import urllib.request

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.models import PushToken, User

logger = logging.getLogger("predrive.notify")


@dataclass
class NotificationMessage:
    organization_id: str
    recipient_user_id: Optional[str]
    recipient_name: str
    recipient_phone: Optional[str]
    channel: str  # 'push' | 'sms' | 'zalo' | 'call'
    title: str
    body: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationResult:
    delivered: bool
    channel_used: str
    provider: str
    fallback_used: bool = False
    error: Optional[str] = None
    sent_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ChannelProvider(Protocol):
    name: str

    def is_configured(self) -> bool: ...

    def send(self, db: Session, msg: NotificationMessage) -> NotificationResult: ...


class MockCaptureProvider:
    """Deterministic in-memory notification sink used when external credentials
    (FCM / Zalo OA / SMS gateway) are not provided in non-production environments or tests.
    Never fakes real cloud provider credentials; records exactprovider='mock'.
    """

    name = "mock"

    def __init__(self) -> None:
        self.sent_messages: list[tuple[NotificationMessage, NotificationResult]] = []

    def clear(self) -> None:
        self.sent_messages.clear()

    def is_configured(self) -> bool:
        return os.getenv("ENV", "development").strip().lower() != "production"

    def send(self, db: Session, msg: NotificationMessage) -> NotificationResult:
        res = NotificationResult(
            delivered=True,
            channel_used=msg.channel,
            provider="mock",
        )
        self.sent_messages.append((msg, res))
        return res


class FcmPushProvider:
    """Firebase Cloud Messaging HTTP sender using `push_tokens` table (P3-7)."""

    name = "fcm"

    def is_configured(self) -> bool:
        return bool(
            os.getenv("FCM_SERVER_KEY", "").strip()
            or os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        )

    def send(self, db: Session, msg: NotificationMessage) -> NotificationResult:
        if not msg.recipient_user_id:
            return NotificationResult(
                delivered=False,
                channel_used="push",
                provider="fcm",
                error="Missing recipient_user_id",
            )
        tokens = db.scalars(
            select(PushToken).where(
                PushToken.organization_id == msg.organization_id,
                PushToken.user_id == msg.recipient_user_id,
            )
        ).all()
        if not tokens:
            return NotificationResult(
                delivered=False,
                channel_used="push",
                provider="fcm",
                error="No registered push_tokens for recipient",
            )

        server_key = os.getenv("FCM_SERVER_KEY", "").strip()
        if not server_key:
            return NotificationResult(
                delivered=False,
                channel_used="push",
                provider="fcm",
                error="BLOCKED: missing FCM_SERVER_KEY / FIREBASE_SERVICE_ACCOUNT_JSON",
            )

        endpoint = os.getenv("FCM_ENDPOINT_URL", "https://fcm.googleapis.com/fcm/send")
        delivered_any = False
        last_err: Optional[str] = None
        for pt in tokens:
            body_bytes = json.dumps(
                {
                    "to": pt.fcm_token,
                    "notification": {"title": msg.title, "body": msg.body},
                    "data": msg.meta,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=body_bytes,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"key={server_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if 200 <= resp.status < 300:
                        delivered_any = True
            except Exception as exc:
                last_err = str(exc)

        return NotificationResult(
            delivered=delivered_any,
            channel_used="push",
            provider="fcm",
            error=None if delivered_any else (last_err or "FCM send failed"),
        )


class ZaloZnsProvider:
    """Zalo OA / ZNS notification sender (P3-9)."""

    name = "zalo_zns"

    def is_configured(self) -> bool:
        return bool(os.getenv("ZALO_OA_ACCESS_TOKEN", "").strip())

    def send(self, db: Session, msg: NotificationMessage) -> NotificationResult:
        token = os.getenv("ZALO_OA_ACCESS_TOKEN", "").strip()
        if not token:
            return NotificationResult(
                delivered=False,
                channel_used="zalo",
                provider="zalo_zns",
                error="BLOCKED: missing ZALO_OA_ACCESS_TOKEN",
            )
        if not msg.recipient_phone:
            return NotificationResult(
                delivered=False,
                channel_used="zalo",
                provider="zalo_zns",
                error="Missing recipient phone",
            )
        endpoint = os.getenv(
            "ZALO_ZNS_ENDPOINT_URL",
            "https://business.openapi.zalo.me/message/template",
        )
        payload = json.dumps(
            {
                "phone": msg.recipient_phone.lstrip("+"),
                "template_id": os.getenv("ZALO_ZNS_TEMPLATE_ID", "predrive_alert"),
                "template_data": {
                    "title": msg.title,
                    "message": msg.body,
                    **{k: str(v) for k, v in msg.meta.items()},
                },
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "access_token": token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if 200 <= resp.status < 300:
                    return NotificationResult(
                        delivered=True, channel_used="zalo", provider="zalo_zns"
                    )
                return NotificationResult(
                    delivered=False,
                    channel_used="zalo",
                    provider="zalo_zns",
                    error=f"HTTP {resp.status}",
                )
        except Exception as exc:
            return NotificationResult(
                delivered=False,
                channel_used="zalo",
                provider="zalo_zns",
                error=str(exc),
            )


class SmsGatewayProvider:
    """SMS Gateway HTTP provider (P3-9)."""

    name = "sms_gateway"

    def is_configured(self) -> bool:
        return bool(os.getenv("SMS_API_KEY", "").strip() and os.getenv("SMS_API_URL", "").strip())

    def send(self, db: Session, msg: NotificationMessage) -> NotificationResult:
        api_key = os.getenv("SMS_API_KEY", "").strip()
        api_url = os.getenv("SMS_API_URL", "").strip()
        if not api_key or not api_url:
            return NotificationResult(
                delivered=False,
                channel_used="sms",
                provider="sms_gateway",
                error="BLOCKED: missing SMS_API_KEY / SMS_API_URL",
            )
        if not msg.recipient_phone:
            return NotificationResult(
                delivered=False,
                channel_used="sms",
                provider="sms_gateway",
                error="Missing recipient phone",
            )
        payload = json.dumps(
            {
                "to": msg.recipient_phone,
                "text": f"{msg.title}: {msg.body}",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if 200 <= resp.status < 300:
                    return NotificationResult(
                        delivered=True, channel_used="sms", provider="sms_gateway"
                    )
                return NotificationResult(
                    delivered=False,
                    channel_used="sms",
                    provider="sms_gateway",
                    error=f"HTTP {resp.status}",
                )
        except Exception as exc:
            return NotificationResult(
                delivered=False,
                channel_used="sms",
                provider="sms_gateway",
                error=str(exc),
            )


FALLBACK_ORDER: dict[str, list[str]] = {
    "zalo": ["zalo", "sms", "push"],
    "sms": ["sms", "zalo", "push"],
    "call": ["sms", "zalo", "push"],
    "push": ["push", "zalo", "sms"],
}


class NotificationDispatcher:
    """Dispatches operational escalation & safety alerts with automatic channel fallback (P3-5 / P3-7 / P3-9)."""

    def __init__(self) -> None:
        self.mock_provider = MockCaptureProvider()
        self.providers: dict[str, ChannelProvider] = {
            "push": FcmPushProvider(),
            "zalo": ZaloZnsProvider(),
            "sms": SmsGatewayProvider(),
        }

    def set_provider(self, channel: str, provider: ChannelProvider) -> None:
        self.providers[channel] = provider

    def reset_defaults(self) -> None:
        self.mock_provider.clear()
        self.providers = {
            "push": FcmPushProvider(),
            "zalo": ZaloZnsProvider(),
            "sms": SmsGatewayProvider(),
        }

    def dispatch(self, db: Session, msg: NotificationMessage) -> NotificationResult:
        chain = FALLBACK_ORDER.get(msg.channel, [msg.channel, "push"])
        any_real_configured = any(
            self.providers.get(ch) and self.providers[ch].is_configured()
            for ch in chain
            if ch in self.providers
        )

        if not any_real_configured:
            if self.mock_provider.is_configured():
                return self.mock_provider.send(db, msg)
            return NotificationResult(
                delivered=False,
                channel_used=msg.channel,
                provider="unconfigured",
                error=f"BLOCKED: no provider configured for channel {msg.channel}",
            )

        last_error: Optional[str] = None
        for idx, ch in enumerate(chain):
            prov = self.providers.get(ch)
            if prov is None or not prov.is_configured():
                continue
            attempt_msg = NotificationMessage(
                organization_id=msg.organization_id,
                recipient_user_id=msg.recipient_user_id,
                recipient_name=msg.recipient_name,
                recipient_phone=msg.recipient_phone,
                channel=ch,
                title=msg.title,
                body=msg.body,
                meta=msg.meta,
            )
            try:
                res = prov.send(db, attempt_msg)
            except Exception as exc:
                res = NotificationResult(
                    delivered=False,
                    channel_used=ch,
                    provider=prov.name,
                    error=str(exc),
                )
            if res.delivered:
                res.fallback_used = idx > 0 or ch != msg.channel
                return res
            last_error = res.error
            logger.warning(
                "Notification channel %s (%s) failed: %s; trying fallback",
                ch,
                prov.name,
                res.error,
            )

        return NotificationResult(
            delivered=False,
            channel_used=msg.channel,
            provider="fallback_exhausted",
            fallback_used=True,
            error=last_error or "All configured notification channels failed",
        )


notification_dispatcher = NotificationDispatcher()


def notify_user(
    db: Session,
    recipient: User,
    channel: str,
    title: str,
    body: str,
    meta: Optional[dict[str, Any]] = None,
) -> NotificationResult:
    phone = recipient.zalo_phone if channel == "zalo" and recipient.zalo_phone else recipient.phone
    msg = NotificationMessage(
        organization_id=recipient.organization_id,
        recipient_user_id=recipient.id,
        recipient_name=recipient.full_name,
        recipient_phone=phone,
        channel=channel,
        title=title,
        body=body,
        meta=meta or {},
    )
    return notification_dispatcher.dispatch(db, msg)
