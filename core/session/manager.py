from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass(slots=True)
class Round:
    user: str
    assistant: str
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class SessionState:
    session_id: str
    rounds: list[Round] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class SessionManager:
    def __init__(self, max_history_rounds: int = 10) -> None:
        self._max_history_rounds = max(1, max_history_rounds)
        self._sessions: dict[str, SessionState] = {}
        self._lock = threading.RLock()

    @staticmethod
    def build_key(user_id: str, chat_id: str) -> str:
        return f"{user_id}:{chat_id}"

    def get_or_create(self, key: str) -> SessionState:
        with self._lock:
            if key not in self._sessions:
                self._sessions[key] = SessionState(session_id=self._new_session_id())
            return self._sessions[key]

    def new_session(self, key: str) -> str:
        with self._lock:
            self._sessions[key] = SessionState(session_id=self._new_session_id())
            return self._sessions[key].session_id

    def reset_session(self, key: str) -> str:
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                session = SessionState(session_id=self._new_session_id())
                self._sessions[key] = session
            session.rounds.clear()
            session.updated_at = time.time()
            return session.session_id

    def append_round(self, key: str, user: str, assistant: str) -> None:
        with self._lock:
            session = self.get_or_create(key)
            session.rounds.append(Round(user=user, assistant=assistant))
            session.updated_at = time.time()
            if len(session.rounds) > self._max_history_rounds:
                over = len(session.rounds) - self._max_history_rounds
                del session.rounds[:over]

    def build_messages(self, key: str) -> list[dict[str, str]]:
        with self._lock:
            session = self.get_or_create(key)
            messages: list[dict[str, str]] = []
            for turn in session.rounds:
                messages.append({"role": "user", "content": turn.user})
                messages.append({"role": "assistant", "content": turn.assistant})
            return messages

    def round_count(self, key: str) -> int:
        with self._lock:
            session = self.get_or_create(key)
            return len(session.rounds)

    @staticmethod
    def _new_session_id() -> str:
        return uuid.uuid4().hex
