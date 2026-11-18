import asyncio
import json
from collections import defaultdict
import time
from typing import Any

from .observability import observe_sse_publish


class SSEBroker:
    """Thread/Async-safe multi-client SSE pub/sub broker partitioned by organization_id."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, str]]]] = defaultdict(set)
        self._history: dict[str, list[dict[str, str]]] = defaultdict(list)

    def subscribe(self, org_id: str) -> asyncio.Queue[dict[str, str]]:
        queue: asyncio.Queue[dict[str, str]] = asyncio.Queue(maxsize=256)
        self._subscribers[org_id].add(queue)
        return queue

    def unsubscribe(self, org_id: str, queue: asyncio.Queue[dict[str, str]]) -> None:
        subs = self._subscribers.get(org_id)
        if subs and queue in subs:
            subs.remove(queue)

    def publish(self, org_id: str, event_name: str, payload: dict[str, Any]) -> None:
        t0 = time.perf_counter()
        msg = {
            "event": event_name,
            "data": json.dumps(payload, ensure_ascii=False),
        }
        # Keep short recent ring buffer per org for testing/diagnostics
        hist = self._history[org_id]
        hist.append(msg)
        if len(hist) > 100:
            del hist[:-100]

        subs = list(self._subscribers.get(org_id, ()))
        for q in subs:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(msg)
                except Exception:
                    pass
        total_subs = sum(len(s) for s in self._subscribers.values())
        observe_sse_publish(time.perf_counter() - t0, total_subs)

    def get_recent_messages(self, org_id: str) -> list[dict[str, str]]:
        return list(self._history.get(org_id, ()))

    def clear_history(self, org_id: str | None = None) -> None:
        if org_id is None:
            self._history.clear()
        else:
            self._history.pop(org_id, None)


sse_broker = SSEBroker()

