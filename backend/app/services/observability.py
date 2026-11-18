from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import time
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from sqlalchemy import func, select, text

from ..core import database as db_mod
from ..core.config import get_config
from ..models.models import EventModel, SessionModel

logger = logging.getLogger("predrive.observability")

REGISTRY = CollectorRegistry()

HTTP_REQUEST_DURATION = Histogram(
    "predrive_http_request_duration_seconds",
    "HTTP API request latency in seconds",
    ["method", "route", "status_code"],
    registry=REGISTRY,
)

HTTP_ERRORS_TOTAL = Counter(
    "predrive_http_errors_total",
    "Total HTTP 5xx server errors",
    ["method", "route"],
    registry=REGISTRY,
)

SSE_PUBLISH_LATENCY = Histogram(
    "predrive_sse_publish_latency_seconds",
    "Latency to fan-out SSE messages to subscribers / Redis",
    registry=REGISTRY,
)

SSE_SUBSCRIBERS = Gauge(
    "predrive_sse_subscribers",
    "Current active SSE client connections across all organizations",
    registry=REGISTRY,
)

ACTIVE_SESSIONS = Gauge(
    "predrive_active_sessions",
    "Current number of open driving sessions",
    registry=REGISTRY,
)

DISCONNECTED_DRIVERS = Gauge(
    "predrive_disconnected_drivers",
    "Current number of open driving sessions in DISCONNECTED state",
    registry=REGISTRY,
)

EVENTS_LAST_HOUR = Gauge(
    "predrive_events_last_hour",
    "Safety events recorded in the last 60 minutes",
    registry=REGISTRY,
)

HEARTBEATS_RECEIVED_TOTAL = Counter(
    "predrive_heartbeats_received_total",
    "Total driver heartbeats received",
    registry=REGISTRY,
)

DB_UP = Gauge(
    "predrive_db_up",
    "Database reachability (1 = healthy, 0 = unreachable)",
    registry=REGISTRY,
)

_sentry_initialized_dsn: str | None = None


def init_sentry_if_configured(transport: Any = None) -> bool:
    """Initialize Sentry SDK when SENTRY_DSN is configured (never store/send PII or images - R1)."""
    global _sentry_initialized_dsn
    cfg = get_config()
    dsn = cfg.sentry_dsn
    if not dsn:
        return False
    if dsn == _sentry_initialized_dsn and transport is None:
        return True
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=dsn,
            environment=cfg.env,
            send_default_pii=False,
            traces_sample_rate=0.1,
            transport=transport,
        )
        _sentry_initialized_dsn = dsn
        return True
    except Exception as exc:
        logger.warning("Failed to initialize Sentry SDK: %s", exc)
        return False


def record_http_metric(method: str, route: str, status_code: int, elapsed_sec: float) -> None:
    HTTP_REQUEST_DURATION.labels(
        method=method, route=route, status_code=str(status_code)
    ).observe(max(0.0, elapsed_sec))
    if status_code >= 500:
        HTTP_ERRORS_TOTAL.labels(method=method, route=route).inc()


def observe_sse_publish(elapsed_sec: float, subscriber_count: int) -> None:
    SSE_PUBLISH_LATENCY.observe(max(0.0, elapsed_sec))
    SSE_SUBSCRIBERS.set(max(0, subscriber_count))


def refresh_fleet_gauges() -> None:
    try:
        now = datetime.now(timezone.utc)
        one_hour_ago = now - timedelta(hours=1)
        with db_mod.SessionLocal() as db:
            db.execute(text("SELECT 1"))
            DB_UP.set(1)

            active_cnt = int(
                db.scalar(
                    select(func.count(SessionModel.id)).where(
                        SessionModel.ended_at.is_(None)
                    )
                )
                or 0
            )
            disc_cnt = int(
                db.scalar(
                    select(func.count(SessionModel.id)).where(
                        SessionModel.ended_at.is_(None),
                        SessionModel.current_state == "DISCONNECTED",
                    )
                )
                or 0
            )
            ev_1h_cnt = int(
                db.scalar(
                    select(func.count(EventModel.id)).where(
                        EventModel.occurred_at >= one_hour_ago
                    )
                )
                or 0
            )
            ACTIVE_SESSIONS.set(active_cnt)
            DISCONNECTED_DRIVERS.set(disc_cnt)
            EVENTS_LAST_HOUR.set(ev_1h_cnt)
    except Exception as exc:
        logger.warning("Metrics DB probe failed: %s", exc)
        DB_UP.set(0)


def render_prometheus_metrics() -> tuple[bytes, str]:
    refresh_fleet_gauges()
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
