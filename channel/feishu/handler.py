from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

from app.commands import process_command
from app.config import Settings
from channel.feishu.client import FeishuClient, FeishuClientError
from channel.feishu.models import (
    extract_token,
    is_url_verification,
    parse_text_message_event,
)
from channel.feishu.security import (
    FeishuSecurityError,
    decrypt_event_payload,
    verify_request_signature,
)
from core.codex.client import CodexClient, CodexClientCancelled, CodexClientError
from core.session.deduplicator import MessageDeduplicator
from core.session.manager import SessionManager
from core.session.task_registry import ActiveTaskRegistry

logger = logging.getLogger(__name__)


class FeishuWebhookHandler:
    def __init__(
        self,
        settings: Settings,
        feishu_client: FeishuClient,
        codex_client: CodexClient,
        session_manager: SessionManager,
        deduplicator: MessageDeduplicator,
        task_registry: ActiveTaskRegistry,
    ) -> None:
        self._settings = settings
        self._feishu_client = feishu_client
        self._codex_client = codex_client
        self._sessions = session_manager
        self._deduplicator = deduplicator
        self._task_registry = task_registry

    async def handle_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> dict[str, Any]:
        trace_id = uuid.uuid4().hex

        payload = self._parse_payload(raw_body)
        payload = self._verify_and_decrypt_payload(headers=headers, raw_body=raw_body, payload=payload)

        if is_url_verification(payload):
            self._verify_token(payload=payload)
            return {"challenge": payload.get("challenge")}

        event = parse_text_message_event(payload)
        if event is None:
            logger.info("ignored unsupported event", extra={"trace_id": trace_id, "event": "feishu.ignore"})
            return {"code": 0}

        self._verify_token(payload=payload)

        asyncio.create_task(self._handle_text_event(event=event, trace_id=trace_id))
        return {"code": 0}

    async def _handle_text_event(self, event: Any, trace_id: str) -> None:
        if self._deduplicator.seen(event.message_id):
            logger.info("duplicate message ignored", extra={"trace_id": trace_id, "event": "feishu.deduplicate"})
            return

        session_key = SessionManager.build_key(user_id=event.user_id, chat_id=event.chat_id)
        normalized_text = event.text.strip().lower()

        if normalized_text == "/stop":
            await self._handle_stop_command(message_id=event.message_id, session_key=session_key, trace_id=trace_id)
            return

        await self._send_quick_ack(message_id=event.message_id, trace_id=trace_id)

        active_task = self._task_registry.get(session_key)
        if active_task is not None:
            await self._safe_reply(
                message_id=event.message_id,
                text="当前已有任务在运行中。发送 /stop 可强制终止后再试。",
                trace_id=trace_id,
                request_uuid=f"{event.message_id}-busy",
            )
            return

        command = process_command(event.text, session_manager=self._sessions, session_key=session_key)
        if command is not None:
            await self._safe_reply(
                message_id=event.message_id,
                text=command.reply_text,
                trace_id=trace_id,
                request_uuid=f"{event.message_id}-cmd",
            )
            return

        history_messages = self._sessions.build_messages(session_key)
        messages = history_messages + [{"role": "user", "content": event.text}]
        started = self._task_registry.start(
            key=session_key,
            trace_id=trace_id,
            message_id=event.message_id,
            cancel_callback=lambda: self._codex_client.cancel(trace_id),
        )
        if not started:
            await self._safe_reply(
                message_id=event.message_id,
                text="当前已有任务在运行中。发送 /stop 可强制终止后再试。",
                trace_id=trace_id,
                request_uuid=f"{event.message_id}-busy",
            )
            return
        notice_task = asyncio.create_task(
            self._notify_if_still_running(
                session_key=session_key,
                message_id=event.message_id,
                trace_id=trace_id,
            )
        )

        try:
            if self._settings.streaming_enabled:
                answer = await self._stream_to_feishu(message_id=event.message_id, messages=messages, trace_id=trace_id)
            else:
                answer = await self._codex_client.chat(messages=messages, trace_id=trace_id)
                await self._safe_reply(message_id=event.message_id, text=answer, trace_id=trace_id)

            self._sessions.append_round(key=session_key, user=event.text, assistant=answer)
        except CodexClientCancelled:
            logger.info("message cancelled by user", extra={"trace_id": trace_id, "event": "pipeline.cancel"})
            await self._safe_reply(message_id=event.message_id, text="当前任务已终止。", trace_id=trace_id)
        except (CodexClientError, FeishuClientError, Exception):
            logger.exception("failed to process message", extra={"trace_id": trace_id, "event": "pipeline.error"})
            await self._safe_reply(message_id=event.message_id, text="服务繁忙，请稍后重试。", trace_id=trace_id)
        finally:
            notice_task.cancel()
            await asyncio.gather(notice_task, return_exceptions=True)
            self._task_registry.finish(key=session_key, trace_id=trace_id)

    async def _stream_to_feishu(self, message_id: str, messages: list[dict[str, str]], trace_id: str) -> str:
        start = time.monotonic()
        full_text_parts: list[str] = []

        async for piece in self._codex_client.chat_stream(messages=messages, trace_id=trace_id):
            full_text_parts.append(piece)

        answer = "".join(full_text_parts).strip()
        if not answer:
            answer = "(空响应)"

        await self._safe_reply(
            message_id=message_id,
            text=answer,
            trace_id=trace_id,
            request_uuid=f"{message_id}-final",
        )

        logger.info(
            "streaming response finished",
            extra={
                "trace_id": trace_id,
                "event": "pipeline.streaming",
                "duration_ms": int((time.monotonic() - start) * 1000),
            },
        )
        return answer

    async def _notify_if_still_running(self, session_key: str, message_id: str, trace_id: str) -> None:
        await asyncio.sleep(self._settings.task_running_notice_seconds)
        active_task = self._task_registry.get(session_key)
        if active_task is None or active_task.trace_id != trace_id:
            return
        if not self._task_registry.mark_notice_sent(session_key, trace_id):
            return

        await self._safe_reply(
            message_id=message_id,
            text="任务仍在运行中，我会继续处理；如需强制终止请发送 /stop。",
            trace_id=trace_id,
            request_uuid=f"{message_id}-running",
        )

    async def _handle_stop_command(self, message_id: str, session_key: str, trace_id: str) -> None:
        task = self._task_registry.cancel(session_key)
        if task is None:
            await self._safe_reply(
                message_id=message_id,
                text="当前没有可终止的运行中任务。",
                trace_id=trace_id,
                request_uuid=f"{message_id}-stop-idle",
            )
            return

        await self._safe_reply(
            message_id=message_id,
            text="已收到停止请求，正在强制终止当前任务。",
            trace_id=trace_id,
            request_uuid=f"{message_id}-stop",
        )

    async def _safe_reply(
        self,
        message_id: str,
        text: str,
        trace_id: str,
        request_uuid: str | None = None,
    ) -> None:
        content = text.strip()
        if not content:
            return

        try:
            await self._feishu_client.reply_text(
                message_id=message_id,
                text=content,
                trace_id=trace_id,
                request_uuid=request_uuid,
            )
            return
        except FeishuClientError:
            # Fallback: only split when single-message send fails, usually due length limits.
            chunks = self._split_chunks(content)
            if len(chunks) <= 1:
                raise

        for idx, chunk in enumerate(chunks, start=1):
            chunk_uuid = request_uuid
            if request_uuid:
                chunk_uuid = f"{request_uuid}-part-{idx}"
            await self._feishu_client.reply_text(
                message_id=message_id,
                text=chunk,
                trace_id=trace_id,
                request_uuid=chunk_uuid,
            )

    async def _send_quick_ack(self, message_id: str, trace_id: str) -> None:
        try:
            await self._feishu_client.create_reaction(
                message_id=message_id,
                trace_id=trace_id,
                emoji_type="Typing",
            )
        except FeishuClientError:
            logger.warning(
                "failed to send quick ack",
                extra={"trace_id": trace_id, "event": "feishu.quick_ack"},
            )

    def _verify_and_decrypt_payload(
        self,
        headers: Mapping[str, str],
        raw_body: bytes,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        has_signature = any(key.lower() == "x-lark-signature" for key in headers)
        if has_signature:
            if not self._settings.feishu_encrypt_key:
                raise HTTPException(status_code=401, detail="missing FEISHU_ENCRYPT_KEY for signature validation")
            is_valid = verify_request_signature(
                headers=headers,
                raw_body=raw_body,
                encrypt_key=self._settings.feishu_encrypt_key,
            )
            if not is_valid:
                raise HTTPException(status_code=401, detail="invalid feishu signature")

        if "encrypt" in payload:
            if not self._settings.feishu_encrypt_key:
                raise HTTPException(status_code=401, detail="missing FEISHU_ENCRYPT_KEY for encrypted payload")
            try:
                return decrypt_event_payload(payload["encrypt"], self._settings.feishu_encrypt_key)
            except FeishuSecurityError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        return payload

    def _verify_token(self, payload: dict[str, Any]) -> None:
        if not self._settings.feishu_verification_token:
            return

        token = extract_token(payload)
        if token != self._settings.feishu_verification_token:
            raise HTTPException(status_code=401, detail="verification token mismatch")

    @staticmethod
    def _parse_payload(raw_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="invalid request body") from exc

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid payload type")
        return payload

    @staticmethod
    def _split_chunks(text: str, max_len: int = 1500) -> list[str]:
        cleaned = text.strip()
        if not cleaned:
            return []

        if len(cleaned) <= max_len:
            return [cleaned]

        chunks: list[str] = []
        start = 0
        while start < len(cleaned):
            chunks.append(cleaned[start : start + max_len])
            start += max_len
        return chunks
