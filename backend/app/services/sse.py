from __future__ import annotations

import asyncio
from collections import defaultdict
import json
import logging
import threading
import time
from typing import Any
from uuid import uuid4

from ..core.config import get_config
from .observability import observe_sse_publish

try:
    import redis as redis_lib
except ImportError:  # pragma: no cover
    redis_lib = None  # type: ignore[assignment]

logger = logging.getLogger("predrive.sse")

REDIS_SSE_CHANNEL = "predrive:sse:broadcast"


class SSEBroker:
    """Thread/Async-safe multi-client & multi-instance SSE pub/sub broker
    partitioned strictly by organization_id, with Redis Pub/Sub fan-out (P2-7).
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self.instance_id: str = uuid4().hex
        self._explicit_redis_url: str | None = redis_url
        self._lock = threading.Lock()
        self._subscribers: dict[
            str, dict[asyncio.Queue[dict[str, str]], asyncio.AbstractEventLoop | None]
        ] = defaultdict(dict)
        self._history: dict[str, list[dict[str, str]]] = defaultdict(list)

        self._pub_client: Any = None
        self._pub_url_cached: str | None = None
        self._listener_thread: threading.Thread | None = None
        self._listener_stop = threading.Event()
        self._listener_ready = threading.Event()
        self._pubsub: Any = None

    def _effective_redis_url(self) -> str | None:
        if self._explicit_redis_url is not None:
            return self._explicit_redis_url or None
        return get_config().redis_url

    def _get_pub_client(self) -> Any:
        url = self._effective_redis_url()
        if not url or redis_lib is None:
            return None
        if self._pub_client is None or self._pub_url_cached != url:
            self._pub_url_cached = url
            self._pub_client = redis_lib.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=1.5,
                socket_timeout=1.5,
            )
        return self._pub_client

    def start_redis_listener(self, wait_ready_sec: float = 1.5) -> bool:
        url = self._effective_redis_url()
        if not url or redis_lib is None:
            return False
        if self._listener_thread is not None and self._listener_thread.is_alive():
            return True

        self._listener_stop.clear()
        self._listener_ready.clear()

        def _worker() -> None:
            client = None
            pubsub = None
            try:
                client = redis_lib.Redis.from_url(
                    url,
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                    socket_timeout=0.5,
                )
                pubsub = client.pubsub(ignore_subscribe_messages=True)
                pubsub.subscribe(REDIS_SSE_CHANNEL)
                self._pubsub = pubsub
                self._listener_ready.set()

                while not self._listener_stop.is_set():
                    try:
                        raw_msg = pubsub.get_message(timeout=0.2)
                    except Exception:
                        if self._listener_stop.is_set():
                            break
                        continue
                    if not raw_msg or raw_msg.get("type") != "message":
                        continue
                    try:
                        envelope = json.loads(raw_msg["data"])
                    except Exception:
                        continue
                    if envelope.get("instance_id") == self.instance_id:
                        continue
                    org_id = envelope.get("org_id")
                    ev_name = envelope.get("event")
                    ev_data = envelope.get("data")
                    if org_id and ev_name and isinstance(ev_data, str):
                        self._deliver_local(
                            str(org_id), {"event": str(ev_name), "data": ev_data}
                        )
            except Exception as exc:
                logger.warning("Redis SSE listener stopped: %s", exc)
                self._listener_ready.set()
            finally:
                try:
                    if pubsub is not None:
                        pubsub.close()
                except Exception:
                    pass
                try:
                    if client is not None:
                        client.close()
                except Exception:
                    pass

        self._listener_thread = threading.Thread(
            target=_worker, name=f"sse-redis-{self.instance_id[:6]}", daemon=True
        )
        self._listener_thread.start()
        self._listener_ready.wait(timeout=wait_ready_sec)
        return True

    def stop_redis_listener(self) -> None:
        self._listener_stop.set()
        if self._listener_thread is not None and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=2.0)
        self._listener_thread = None
        if self._pub_client is not None:
            try:
                self._pub_client.close()
            except Exception:
                pass
            self._pub_client = None

    @staticmethod
    def _push_to_queue(queue: asyncio.Queue[dict[str, str]], msg: dict[str, str]) -> None:
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.put_nowait(msg)
            except Exception:
                pass

    def _deliver_local(self, org_id: str, msg: dict[str, str]) -> int:
        with self._lock:
            hist = self._history[org_id]
            hist.append(msg)
            if len(hist) > 100:
                del hist[:-100]
            subs = list(self._subscribers.get(org_id, {}).items())
            total_subs = sum(len(s) for s in self._subscribers.values())

        for q, loop in subs:
            if loop is not None and not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(self._push_to_queue, q, msg)
                except RuntimeError:
                    self._push_to_queue(q, msg)
            else:
                self._push_to_queue(q, msg)
        return total_subs

    def subscribe(self, org_id: str) -> asyncio.Queue[dict[str, str]]:
        if self._effective_redis_url():
            self.start_redis_listener(wait_ready_sec=1.0)
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue(maxsize=256)
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        with self._lock:
            self._subscribers[org_id][queue] = loop
        return queue

    def unsubscribe(self, org_id: str, queue: asyncio.Queue[dict[str, str]]) -> None:
        with self._lock:
            subs = self._subscribers.get(org_id)
            if subs:
                subs.pop(queue, None)

    def publish(self, org_id: str, event_name: str, payload: dict[str, Any]) -> None:
        t0 = time.perf_counter()
        data_str = json.dumps(payload, ensure_ascii=False)
        msg = {
            "event": event_name,
            "data": data_str,
        }
        total_subs = self._deliver_local(org_id, msg)

        pub = self._get_pub_client()
        if pub is not None:
            try:
                envelope = json.dumps(
                    {
                        "instance_id": self.instance_id,
                        "org_id": org_id,
                        "event": event_name,
                        "data": data_str,
                    },
                    ensure_ascii=False,
                )
                pub.publish(REDIS_SSE_CHANNEL, envelope)
            except Exception as exc:
                logger.warning("Redis SSE publish error (local delivery unaffected): %s", exc)

        observe_sse_publish(time.perf_counter() - t0, total_subs)

    def get_recent_messages(self, org_id: str) -> list[dict[str, str]]:
        with self._lock:
            return list(self._history.get(org_id, ()))

    def clear_history(self, org_id: str | None = None) -> None:
        with self._lock:
            if org_id is None:
                self._history.clear()
            else:
                self._history.pop(org_id, None)


sse_broker = SSEBroker()
