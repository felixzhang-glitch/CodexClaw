from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import time
from collections.abc import AsyncIterator
from typing import Any

from app.config import Settings
from core.agent.claude_cli import ClaudeCliClient
from core.codex.client import CodexClientCancelled, CodexClientError

logger = logging.getLogger(__name__)


class OpenCodeCliClient:
    """Backend client for the `opencode` TUI/CLI (`opencode run --format json`).

    Same public surface as CodexClient (chat / chat_stream / cancel / close) so it
    is interchangeable behind AgentRouter. opencode emits newline-delimited JSON
    events; each `text` event carries the full accumulated text of a message
    "part" identified by `part.id`. To turn that into streaming deltas we remember
    what has been emitted per part.id and only yield the new suffix.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        name: str = "opencode",
        bin_path: str | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        timeout_seconds: float | None = None,
        idle_timeout_seconds: float | None = None,
    ) -> None:
        self._settings = settings
        self._name = name
        self._bin = bin_path or settings.opencode_cli_bin
        self._model = (model if model is not None else settings.opencode_model).strip()
        self._agent = (agent_name if agent_name is not None else settings.opencode_agent).strip()
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.opencode_timeout_seconds
        )
        self._idle_timeout_seconds = (
            idle_timeout_seconds
            if idle_timeout_seconds is not None
            else settings.opencode_idle_timeout_seconds
        )

        self._lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._stream_piece_chars = 80
        self._active_processes: dict[str, asyncio.subprocess.Process] = {}
        self._cancel_requests: set[str] = set()

        self._work_dir = os.path.abspath(os.path.join(settings.codex_work_dir, self._name))
        os.makedirs(self._work_dir, exist_ok=True)

    @property
    def name(self) -> str:
        return self._name

    async def close(self) -> None:
        return None

    async def chat(self, messages: list[dict[str, str]], trace_id: str) -> str:
        self._assert_circuit_closed()

        prompt = self._build_prompt(messages)
        request_summary = self._summarize_messages(messages)
        attempt = 0
        start = time.monotonic()

        try:
            while True:
                try:
                    text = await self._run_once(prompt=prompt, trace_id=trace_id, collect_only=True)
                    self._record_success()
                    duration_ms = int((time.monotonic() - start) * 1000)
                    logger.info(
                        "opencode cli chat completed",
                        extra={
                            "trace_id": trace_id,
                            "event": "opencode.chat",
                            "backend": self._name,
                            "duration_ms": duration_ms,
                            "status_code": 0,
                            "request_summary": request_summary,
                            "response_summary": self._truncate(text),
                        },
                    )
                    return text
                except CodexClientCancelled:
                    logger.info(
                        "opencode cli chat cancelled",
                        extra={"trace_id": trace_id, "event": "opencode.chat", "status_code": 499},
                    )
                    raise
                except CodexClientError as exc:
                    if not self._should_retry(exc) or attempt >= self._settings.codex_max_retries:
                        self._record_failure()
                        duration_ms = int((time.monotonic() - start) * 1000)
                        logger.error(
                            "opencode cli chat failed",
                            extra={
                                "trace_id": trace_id,
                                "event": "opencode.chat",
                                "backend": self._name,
                                "duration_ms": duration_ms,
                                "status_code": 1,
                                "error_code": type(exc).__name__,
                                "request_summary": request_summary,
                            },
                        )
                        raise
                    self._raise_if_cancelled(trace_id)
                    await asyncio.sleep(self._settings.codex_retry_backoff_seconds * (2**attempt))
                    self._raise_if_cancelled(trace_id)
                    attempt += 1
        finally:
            self._clear_cancel_request(trace_id)

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str) -> AsyncIterator[str]:
        self._assert_circuit_closed()

        prompt = self._build_prompt(messages)
        request_summary = self._summarize_messages(messages)
        attempt = 0
        start = time.monotonic()

        try:
            while True:
                emitted = False
                preview_parts: list[str] = []
                try:
                    async for piece in self._run_stream_once(prompt=prompt, trace_id=trace_id):
                        emitted = True
                        if len("".join(preview_parts)) < 240:
                            preview_parts.append(piece)
                        yield piece

                    self._record_success()
                    duration_ms = int((time.monotonic() - start) * 1000)
                    logger.info(
                        "opencode cli stream completed",
                        extra={
                            "trace_id": trace_id,
                            "event": "opencode.stream",
                            "backend": self._name,
                            "duration_ms": duration_ms,
                            "status_code": 0,
                            "request_summary": request_summary,
                            "response_summary": self._truncate("".join(preview_parts)),
                        },
                    )
                    return
                except CodexClientCancelled:
                    duration_ms = int((time.monotonic() - start) * 1000)
                    logger.info(
                        "opencode cli stream cancelled",
                        extra={
                            "trace_id": trace_id,
                            "event": "opencode.stream",
                            "backend": self._name,
                            "duration_ms": duration_ms,
                            "status_code": 499,
                            "request_summary": request_summary,
                            "response_summary": self._truncate("".join(preview_parts)),
                        },
                    )
                    raise
                except CodexClientError as exc:
                    if emitted:
                        self._record_failure()
                        duration_ms = int((time.monotonic() - start) * 1000)
                        logger.error(
                            "opencode cli stream interrupted after partial output",
                            extra={
                                "trace_id": trace_id,
                                "event": "opencode.stream",
                                "backend": self._name,
                                "duration_ms": duration_ms,
                                "status_code": 1,
                                "error_code": type(exc).__name__,
                                "request_summary": request_summary,
                                "response_summary": self._truncate("".join(preview_parts)),
                            },
                        )
                        raise

                    if not self._should_retry(exc) or attempt >= self._settings.codex_max_retries:
                        self._record_failure()
                        duration_ms = int((time.monotonic() - start) * 1000)
                        logger.error(
                            "opencode cli stream failed",
                            extra={
                                "trace_id": trace_id,
                                "event": "opencode.stream",
                                "backend": self._name,
                                "duration_ms": duration_ms,
                                "status_code": 1,
                                "error_code": type(exc).__name__,
                                "request_summary": request_summary,
                            },
                        )
                        raise

                    self._raise_if_cancelled(trace_id)
                    await asyncio.sleep(self._settings.codex_retry_backoff_seconds * (2**attempt))
                    self._raise_if_cancelled(trace_id)
                    attempt += 1
        finally:
            self._clear_cancel_request(trace_id)

    def cancel(self, trace_id: str) -> bool:
        with self._process_lock:
            process = self._active_processes.get(trace_id)
            if process is None:
                return False
            self._cancel_requests.add(trace_id)

        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        return True

    async def _run_stream_once(self, prompt: str, trace_id: str) -> AsyncIterator[str]:
        command = self._build_command()
        command.append(prompt)
        process = await self._spawn_process(command)
        self._register_process(trace_id, process)
        stderr_task = asyncio.create_task(self._read_stream_text(process.stderr))

        emitted_by_part: dict[str, int] = {}
        error_messages: list[str] = []
        fallback_parts: list[str] = []

        try:
            while True:
                self._raise_if_cancelled(trace_id)
                line = await self._readline_with_idle_timeout(process.stdout)
                if not line:
                    break

                text = line.decode("utf-8", errors="replace").strip()
                if not text:
                    continue

                event = self._parse_event(text)
                if event is None:
                    fallback_parts.append(text)
                    continue

                error_message = self._extract_error_message(event)
                if error_message:
                    error_messages.append(error_message)

                delta = self._extract_text_delta(event, emitted_by_part)
                if delta:
                    for chunk in self._split_chunks(delta):
                        yield chunk
        except asyncio.TimeoutError as exc:
            await self._terminate_process(process)
            stderr_text = await stderr_task
            self._raise_if_cancelled(trace_id)
            raise CodexClientError(f"{self._name} cli timeout: {self._truncate(stderr_text)}") from exc
        finally:
            self._unregister_process(trace_id)

        return_code = await process.wait()
        stderr_text = await stderr_task

        self._raise_if_cancelled(trace_id)
        if return_code != 0:
            error_hint = " | ".join(error_messages).strip() or "\n".join(fallback_parts).strip() or stderr_text.strip()
            raise CodexClientError(
                f"{self._name} cli failed: return_code={return_code}, error={self._truncate(error_hint)}"
            )
        if error_messages and not emitted_by_part:
            raise CodexClientError(f"{self._name} cli error: {self._truncate(' | '.join(error_messages))}")

        if not emitted_by_part:
            fallback = "\n".join(fallback_parts).strip()
            if fallback:
                for chunk in self._split_chunks(fallback):
                    yield chunk

    async def _run_once(self, prompt: str, trace_id: str, *, collect_only: bool) -> str:
        parts: list[str] = []
        async for piece in self._run_stream_once(prompt=prompt, trace_id=trace_id):
            parts.append(piece)
        return "".join(parts).strip()

    def _build_command(self) -> list[str]:
        command = [self._bin, "run", "--format", "json"]
        if self._model:
            command.extend(["--model", self._model])
        if self._agent:
            command.extend(["--agent", self._agent])
        return command

    async def _spawn_process(self, command: list[str]) -> asyncio.subprocess.Process:
        return await asyncio.create_subprocess_exec(
            *command,
            cwd=self._work_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=self._settings.codex_stream_read_limit_bytes,
        )

    async def _readline_with_idle_timeout(self, stream: asyncio.StreamReader | None) -> bytes:
        if stream is None:
            return b""
        return await asyncio.wait_for(
            stream.readline(), timeout=self._idle_timeout_seconds
        )

    async def _read_stream_text(self, stream: asyncio.StreamReader | None) -> str:
        if stream is None:
            return ""
        data = await stream.read()
        if not data:
            return ""
        return data.decode("utf-8", errors="replace")

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        process.kill()
        await process.wait()

    def _register_process(self, trace_id: str, process: asyncio.subprocess.Process) -> None:
        with self._process_lock:
            self._active_processes[trace_id] = process

    def _unregister_process(self, trace_id: str) -> None:
        with self._process_lock:
            self._active_processes.pop(trace_id, None)

    def _raise_if_cancelled(self, trace_id: str) -> None:
        with self._process_lock:
            if trace_id not in self._cancel_requests:
                return
        raise CodexClientCancelled(f"{self._name} cli cancelled by user")

    def _clear_cancel_request(self, trace_id: str) -> None:
        with self._process_lock:
            self._cancel_requests.discard(trace_id)

    @staticmethod
    def _parse_event(line: str) -> dict[str, Any] | None:
        try:
            payload = json.loads(line)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            return None
        return None

    @staticmethod
    def _extract_text_delta(event: dict[str, Any], emitted_by_part: dict[str, int]) -> str:
        if event.get("type") != "text":
            return ""
        part = event.get("part")
        if not isinstance(part, dict):
            return ""
        text = part.get("text")
        if not isinstance(text, str) or not text:
            return ""
        part_id = str(part.get("id") or part.get("messageID") or "")
        if not part_id:
            emitted_by_part.setdefault("_anon", 0)
            already = emitted_by_part["_anon"]
            emitted_by_part["_anon"] = len(text)
            return text[already:]
        already = emitted_by_part.get(part_id, 0)
        if len(text) <= already:
            return ""
        emitted_by_part[part_id] = len(text)
        return text[already:]

    @staticmethod
    def _extract_error_message(event: dict[str, Any]) -> str:
        event_type = str(event.get("type", ""))
        if event_type == "error":
            for key in ("message", "error"):
                value = event.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            part = event.get("part")
            if isinstance(part, dict):
                message = part.get("message") or part.get("error")
                if isinstance(message, str):
                    return message.strip()
        return ""

    def _build_prompt(self, messages: list[dict[str, str]]) -> str:
        prompt_lines = [
            "你是 CodexClaw 的后端助手。",
            "请基于以下多轮对话，直接回复最后一条用户消息。",
            "仅输出回复正文，不要加额外前缀。",
        ]
        skill_summary = ClaudeCliClient._build_skill_summary()
        if skill_summary:
            prompt_lines.extend(
                [
                    "",
                    "本机可用 skills 如下。若用户询问 skills，必须基于此列表回答，不要说当前环境没有加载 skill。",
                    skill_summary,
                ]
            )
        prompt_lines.extend(["", "对话历史:"])

        for message in messages:
            role = str(message.get("role", "user"))
            content = str(message.get("content", "")).strip()
            if not content:
                continue
            if role == "assistant":
                label = "助手"
            elif role == "system":
                label = "系统"
            else:
                label = "用户"
            prompt_lines.append(f"{label}: {content}")

        return "\n".join(prompt_lines)

    def _assert_circuit_closed(self) -> None:
        with self._lock:
            if time.time() < self._circuit_open_until:
                raise CodexClientError("circuit breaker is open")

    def _record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._circuit_open_until = 0.0

    def _record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._settings.codex_circuit_breaker_threshold:
                self._circuit_open_until = time.time() + self._settings.codex_circuit_breaker_cooldown_seconds

    def _split_chunks(self, text: str) -> list[str]:
        content = text
        if not content:
            return []
        if len(content) <= self._stream_piece_chars:
            return [content]
        chunks: list[str] = []
        start = 0
        while start < len(content):
            chunks.append(content[start : start + self._stream_piece_chars])
            start += self._stream_piece_chars
        return chunks

    @staticmethod
    def _truncate(text: str, limit: int = 240) -> str:
        compact = " ".join(text.strip().split())
        if len(compact) <= limit:
            return compact
        return f"{compact[: limit - 3]}..."

    def _summarize_messages(self, messages: list[dict[str, str]]) -> str:
        segments: list[str] = []
        for message in messages[-6:]:
            role = str(message.get("role", "?"))
            content = str(message.get("content", ""))
            segments.append(f"{role}: {self._truncate(content, limit=80)}")
        return self._truncate(" | ".join(segments))

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        msg = str(exc).lower()
        if "unauthorized" in msg or "authentication" in msg:
            return False
        if "circuit breaker" in msg:
            return False
        return True
