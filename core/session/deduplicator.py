from __future__ import annotations

import threading
import time


class MessageDeduplicator:
    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl_seconds = ttl_seconds
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def seen(self, message_id: str) -> bool:
        now = time.time()
        with self._lock:
            self._cleanup(now)
            if message_id in self._seen:
                return True
            self._seen[message_id] = now
            return False

    def _cleanup(self, now: float) -> None:
        expired = [msg_id for msg_id, ts in self._seen.items() if now - ts > self._ttl_seconds]
        for msg_id in expired:
            self._seen.pop(msg_id, None)
