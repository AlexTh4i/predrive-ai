from __future__ import annotations

from collections import defaultdict, deque
import math
import os
import threading
import time
from uuid import uuid4

from fastapi import status

from ..core.config import get_config
from ..core.errors import AppError

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover
    redis_lib = None  # type: ignore[assignment]


class SlidingWindowRateLimiter:
    """Rate limiter supporting Redis (when REDIS_URL is configured) with automatic
    thread-safe in-memory sliding-window fallback.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._redis_url_cached: str | None = None
        self._redis_client: object | None = None

    def _get_redis(self):
        cfg = get_config()
        url = cfg.redis_url
        if not url or redis_lib is None:
            return None
        if url != self._redis_url_cached or self._redis_client is None:
            self._redis_url_cached = url
            self._redis_client = redis_lib.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=1.5,
                socket_timeout=1.5,
            )
        return self._redis_client

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()
        client = self._get_redis()
        if client is not None:
            try:
                for key in client.scan_iter("predrive:rl:*"):
                    client.delete(key)
            except Exception:
                pass

    def check(self, scope: str, key: str, limit: int, window_sec: int) -> None:
        if limit <= 0 or window_sec <= 0:
            return

        full_key = f"predrive:rl:{scope}:{key}"
        now = time.time()
        cutoff = now - window_sec

        client = self._get_redis()
        if client is not None:
            try:
                pipe = client.pipeline(transaction=True)
                pipe.zremrangebyscore(full_key, "-inf", cutoff)
                pipe.zcard(full_key)
                pipe.zrange(full_key, 0, 0, withscores=True)
                _, current_count, oldest = pipe.execute()

                if int(current_count) >= limit:
                    oldest_ts = float(oldest[0][1]) if oldest else now
                    retry_after = max(1, int(math.ceil(oldest_ts + window_sec - now)))
                    raise AppError(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        "RATE_LIMITED",
                        f"Quá giới hạn tần suất ({scope}). Vui lòng thử lại sau {retry_after} giây.",
                        headers={"Retry-After": str(retry_after)},
                    )

                member = f"{now:.6f}:{uuid4().hex[:8]}"
                pipe2 = client.pipeline(transaction=True)
                pipe2.zadd(full_key, {member: now})
                pipe2.expire(full_key, window_sec + 5)
                pipe2.execute()
                return
            except AppError:
                raise
            except Exception:
                # Fall back to in-memory sliding window if Redis is unreachable
                pass

        with self._lock:
            dq = self._buckets[full_key]
            while dq and dq[0] <= cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry_after = max(1, int(math.ceil(dq[0] + window_sec - now)))
                raise AppError(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "RATE_LIMITED",
                    f"Quá giới hạn tần suất ({scope}). Vui lòng thử lại sau {retry_after} giây.",
                    headers={"Retry-After": str(retry_after)},
                )
            dq.append(now)


rate_limiter = SlidingWindowRateLimiter()


def rl_setting(env_name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(env_name, str(default))))
    except ValueError:
        return default


def enforce_login_rate_limit(ip: str | None, username: str) -> None:
    ip_key = ip or "unknown"
    user_key = username.strip().lower()
    win = rl_setting("PREDRIVE_RL_LOGIN_WINDOW_SEC", 60)
    user_limit = rl_setting("PREDRIVE_RL_LOGIN_USER_LIMIT", 8)
    ip_limit = rl_setting("PREDRIVE_RL_LOGIN_IP_LIMIT", 30)
    rate_limiter.check("login_user", f"{ip_key}:{user_key}", user_limit, win)
    rate_limiter.check("login_ip", ip_key, ip_limit, win)


def enforce_pair_rate_limit(user_id: str, ip: str | None) -> None:
    win = rl_setting("PREDRIVE_RL_PAIR_WINDOW_SEC", 60)
    limit = rl_setting("PREDRIVE_RL_PAIR_LIMIT", 5)
    rate_limiter.check("pair_user", user_id, limit, win)
    if ip:
        rate_limiter.check("pair_ip", ip, limit * 2, win)


def enforce_events_rate_limit(device_or_session_id: str) -> None:
    win = rl_setting("PREDRIVE_RL_EVENTS_WINDOW_SEC", 60)
    limit = rl_setting("PREDRIVE_RL_EVENTS_LIMIT", 30)
    rate_limiter.check("events_device", device_or_session_id, limit, win)


def enforce_heartbeat_rate_limit(device_or_session_id: str) -> None:
    win = rl_setting("PREDRIVE_RL_HEARTBEAT_WINDOW_SEC", 60)
    limit = rl_setting("PREDRIVE_RL_HEARTBEAT_LIMIT", 20)
    rate_limiter.check("heartbeat_device", device_or_session_id, limit, win)
