from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.commands import process_command
from app.config import Settings
from channel.feishu.formatting import normalize_reply_text, split_message_text
from core.codex.client import CodexClient, CodexClientCancelled, CodexClientError
from core.session.deduplicator import MessageDeduplicator
from core.session.manager import SessionManager
from core.session.task_registry import ActiveTaskRegistry

logger = logging.getLogger(__name__)

WECHAT_HELP_TEXT = (
    "可用命令:\n"
    "/help - 查看帮助\n"
    "/new - 新建会话（不继承历史）\n"
    "/reset - 清空当前会话上下文\n"
    "/compact - 压缩当前会话上下文（保留最近 2 轮）\n"
    "/stop - 终止当前正在运行的任务\n"
    "/backend - 查看当前后端及可切换列表\n"
    "/codex - 切换后端为 Codex CLI\n"
    "/claude - 切换后端为 Claude Code\n"
    "/qodercli - 切换后端为 Qoder CLI\n"
    "/skills - 列出本机可用 skills"
)


@dataclass(slots=True)
class WeChatTextMessageEvent:
    message_id: str
    account_id: str
    user_id: str
    text: str
    context_token: str = ""


class WeChatWebhookHandler:
    def __init__(
        self,
        settings: Settings,
        codex_client: CodexClient,
        session_manager: SessionManager,
        deduplicator: MessageDeduplicator,
        task_registry: ActiveTaskRegistry,
    ) -> None:
        self._settings = settings
        self._codex_client = codex_client
        self._sessions = session_manager
        self._deduplicator = deduplicator
        self._task_registry = task_registry

    async def handle_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> dict[str, Any]:
        self._verify_token(headers)
        payload = self._parse_payload(raw_body)
        event = self._parse_event(payload)
        trace_id = uuid.uuid4().hex

        replies = await self._handle_text_event(event=event, trace_id=trace_id)
        return {
            "code": 0,
            "replies": replies,
            "context_token": event.context_token,
        }

    async def _handle_text_event(self, event: WeChatTextMessageEvent, trace_id: str) -> list[str]:
        if self._deduplicator.seen(f"wechat:{event.message_id}"):
            logger.info("duplicate wechat message ignored", extra={"trace_id": trace_id, "event": "wechat.deduplicate"})
            return []

        session_key = self._build_session_key(event)
        normalized_text = event.text.strip().lower()

        if normalized_text == "/stop":
            task = self._task_registry.cancel(session_key)
            if task is None:
                return self._split_reply("当前没有可终止的运行中任务。")
            return self._split_reply("已收到停止请求，正在强制终止当前任务。")

        if normalized_text == "/help":
            return self._split_reply(WECHAT_HELP_TEXT)

        active_task = self._task_registry.get(session_key)
        if active_task is not None:
            return self._split_reply("当前已有任务在运行中。发送 /stop 可强制终止后再试。")

        command = process_command(
            event.text,
            session_manager=self._sessions,
            session_key=session_key,
            router=self._codex_client,
        )
        if command is not None:
            return self._split_reply(command.reply_text)

        history_messages = self._sessions.build_messages(session_key)
        messages = history_messages + [{"role": "user", "content": event.text}]

        started = self._task_registry.start(
            key=session_key,
            trace_id=trace_id,
            message_id=event.message_id,
            cancel_callback=lambda: self._codex_client.cancel(trace_id),
        )
        if not started:
            return self._split_reply("当前已有任务在运行中。发送 /stop 可强制终止后再试。")

        try:
            if self._settings.streaming_enabled:
                parts: list[str] = []
                async for piece in self._codex_client.chat_stream(messages=messages, trace_id=trace_id):
                    parts.append(piece)
                answer = "".join(parts).strip()
            else:
                answer = await self._codex_client.chat(messages=messages, trace_id=trace_id)

            if not answer.strip():
                answer = "(空响应)"
            self._sessions.append_round(key=session_key, user=event.text, assistant=answer)
            return self._split_reply(answer)
        except CodexClientCancelled:
            logger.info("wechat message cancelled by user", extra={"trace_id": trace_id, "event": "wechat.cancel"})
            return self._split_reply("当前任务已终止。")
        except (CodexClientError, Exception):
            logger.exception("failed to process wechat message", extra={"trace_id": trace_id, "event": "wechat.error"})
            return self._split_reply("服务繁忙，请稍后重试。")
        finally:
            self._task_registry.finish(key=session_key, trace_id=trace_id)

    def _verify_token(self, headers: Mapping[str, str]) -> None:
        expected = self._settings.wechat_webhook_token.strip()
        if not expected:
            return

        auth_header = ""
        for key, value in headers.items():
            if key.lower() == "authorization":
                auth_header = value.strip()
                break
        if auth_header != f"Bearer {expected}":
            raise HTTPException(status_code=401, detail="invalid wechat webhook token")

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
    def _parse_event(payload: dict[str, Any]) -> WeChatTextMessageEvent:
        message_id = str(payload.get("message_id", "") or payload.get("client_id", "")).strip()
        account_id = str(payload.get("account_id", "")).strip()
        user_id = str(payload.get("user_id", "") or payload.get("from_user_id", "")).strip()
        text = str(payload.get("text", "")).strip()
        context_token = str(payload.get("context_token", "")).strip()

        if not message_id or not account_id or not user_id:
            raise HTTPException(status_code=400, detail="missing wechat message identity")
        if not text:
            raise HTTPException(status_code=400, detail="missing wechat text")

        return WeChatTextMessageEvent(
            message_id=message_id,
            account_id=account_id,
            user_id=user_id,
            text=text,
            context_token=context_token,
        )

    @staticmethod
    def _build_session_key(event: WeChatTextMessageEvent) -> str:
        return f"wechat:{event.account_id}:{event.user_id}"

    def _split_reply(self, text: str) -> list[str]:
        content = normalize_reply_text(text) or "(空响应)"
        max_chars = int(getattr(self._settings, "wechat_message_chunk_chars", 1800) or 1800)
        return split_message_text(content, max_chars=max_chars)
