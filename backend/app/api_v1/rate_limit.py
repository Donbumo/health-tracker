from collections import defaultdict, deque
from threading import Lock
from time import time

from flask import current_app

from app.api_v1.errors import ApiError


class MemoryRateLimiter:
    """Per-process QA limiter. Production needs a shared backend for many workers."""

    def __init__(self):
        self._events = defaultdict(deque)
        self._lock = Lock()

    def check(self, bucket: str, identity: str, limit: int) -> None:
        if not current_app.config.get("API_RATE_LIMIT_ENABLED", True):
            return
        window = current_app.config["API_RATE_LIMIT_WINDOW_SECONDS"]
        now = time()
        key = (bucket, identity)
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now - window:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + window - now) + 1)
                raise ApiError(
                    "rate_limit_exceeded",
                    "Demasiadas solicitudes; inténtalo más tarde.",
                    429,
                    {"retry_after": retry_after},
                )
            events.append(now)

    def clear(self):
        with self._lock:
            self._events.clear()


rate_limiter = MemoryRateLimiter()
