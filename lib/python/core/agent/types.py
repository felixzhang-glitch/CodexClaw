from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class BackendClient(Protocol):
    """Protocol shared by CodexClient, ClaudeCliClient and AgentRouter.

    Handlers depend on this surface so that any backend client (or the router
    itself) can be injected as a drop-in replacement.
    """

    async def chat(self, messages: list[dict[str, str]], trace_id: str) -> str: ...

    def chat_stream(self, messages: list[dict[str, str]], trace_id: str) -> AsyncIterator[str]: ...

    def cancel(self, trace_id: str) -> bool: ...

    async def close(self) -> None: ...
