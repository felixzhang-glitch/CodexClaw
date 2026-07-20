from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(slots=True)
class ActiveTask:
    trace_id: str
    message_id: str
    started_at: float = field(default_factory=time.time)
    cancel_requested: bool = False


class ActiveTaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, ActiveTask] = {}
        self._cancel_callbacks: dict[str, Callable[[], bool]] = {}
        self._lock = threading.RLock()

    def start(self, key: str, trace_id: str, message_id: str, cancel_callback: Callable[[], bool]) -> bool:
        with self._lock:
            if key in self._tasks:
                return False
            self._tasks[key] = ActiveTask(trace_id=trace_id, message_id=message_id)
            self._cancel_callbacks[key] = cancel_callback
            return True

    def get(self, key: str) -> ActiveTask | None:
        with self._lock:
            return self._tasks.get(key)

    def finish(self, key: str, trace_id: str) -> None:
        with self._lock:
            task = self._tasks.get(key)
            if task is None or task.trace_id != trace_id:
                return
            self._tasks.pop(key, None)
            self._cancel_callbacks.pop(key, None)

    def cancel(self, key: str) -> ActiveTask | None:
        with self._lock:
            task = self._tasks.get(key)
            if task is None:
                return None
            task.cancel_requested = True
            cancel_callback = self._cancel_callbacks.get(key)

        if cancel_callback is not None:
            cancel_callback()
        return task
