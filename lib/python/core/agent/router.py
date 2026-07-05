from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import AsyncIterator

from app.config import Settings
from core.agent.claude_cli import ClaudeCliClient
from core.codex.client import CodexClient

logger = logging.getLogger(__name__)

BACKEND_LABELS: dict[str, str] = {
    "codex": "Codex CLI",
    "claude": "Claude Code",
    "qodercli": "Qoder CLI",
}


class AgentRouter:
    """Routes chat traffic to the active backend and supports runtime switching.

    Presents the same surface (chat / chat_stream / cancel / close) the handlers
    expect from a backend client, so it is a drop-in replacement for CodexClient.
    The active backend is persisted to disk so it survives restarts. cancel() is
    broadcast to every backend so /stop works no matter which one ran the task;
    non-active backends with no matching process simply return False.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._state_path = os.path.abspath(settings.backend_state_path)

        codex = CodexClient(settings=settings)
        claude = ClaudeCliClient(
            settings=settings,
            name="claude",
            bin_path=settings.claude_cli_bin,
            model=settings.claude_model,
            permission_mode=settings.claude_permission_mode,
            timeout_seconds=settings.claude_timeout_seconds,
        )
        qodercli = ClaudeCliClient(
            settings=settings,
            name="qodercli",
            bin_path=settings.qodercli_cli_bin,
            model=settings.qodercli_model,
            permission_mode=settings.qodercli_permission_mode,
            timeout_seconds=settings.qodercli_timeout_seconds,
            use_verbose=False,
            use_partial_messages=False,
        )
        self._clients: dict[str, object] = {
            "codex": codex,
            "claude": claude,
            "qodercli": qodercli,
        }

        self._active = self._load_active() or self._normalize(settings.active_backend) or "codex"

    @property
    def active(self) -> str:
        with self._lock:
            return self._active

    def available(self) -> list[str]:
        return list(self._clients.keys())

    @staticmethod
    def label(name: str) -> str:
        return BACKEND_LABELS.get(name, name)

    def _normalize(self, name: str) -> str | None:
        candidate = (name or "").strip().lower()
        return candidate if candidate in self._clients else None

    def switch(self, name: str) -> bool:
        normalized = self._normalize(name)
        if normalized is None:
            return False
        with self._lock:
            self._active = normalized
            self._save_active(normalized)
        logger.info("backend switched", extra={"event": "agent.switch", "backend": normalized})
        return True

    def _active_client(self):
        with self._lock:
            return self._clients[self._active]

    async def chat(self, messages: list[dict[str, str]], trace_id: str) -> str:
        return await self._active_client().chat(messages=messages, trace_id=trace_id)

    def chat_stream(self, messages: list[dict[str, str]], trace_id: str) -> AsyncIterator[str]:
        return self._active_client().chat_stream(messages=messages, trace_id=trace_id)

    def cancel(self, trace_id: str) -> bool:
        cancelled = False
        for client in self._clients.values():
            if client.cancel(trace_id):
                cancelled = True
        return cancelled

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()

    def _load_active(self) -> str | None:
        try:
            with open(self._state_path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        if isinstance(data, dict):
            return self._normalize(str(data.get("active_backend", "")))
        return None

    def _save_active(self, name: str) -> None:
        try:
            os.makedirs(os.path.dirname(self._state_path), exist_ok=True)
            tmp_path = f"{self._state_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump({"active_backend": name}, fh)
            os.replace(tmp_path, self._state_path)
        except OSError:
            logger.warning("failed to persist backend state", extra={"event": "agent.persist", "backend": name})
