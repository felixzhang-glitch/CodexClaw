from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException

from app.commands import parse_reminder_command, process_command
from app.config import Settings
from channel.feishu.client import FeishuClient, FeishuClientError
from channel.feishu.formatting import normalize_reply_text, split_message_text
from channel.feishu.media import (
    extract_local_image_paths,
    find_recent_generated_images,
    remove_local_image_references,
)
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
from core.session.reminder_scheduler import ReminderScheduler
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
        reminder_scheduler: ReminderScheduler | None = None,
    ) -> None:
        self._settings = settings
        self._feishu_client = feishu_client
        self._codex_client = codex_client
        self._sessions = session_manager
        self._deduplicator = deduplicator
        self._task_registry = task_registry
        self._reminder_scheduler = reminder_scheduler

    async def handle_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> dict[str, Any]:
        trace_id = uuid.uuid4().hex

        payload = self._parse_payload(raw_body)
        payload = self._verify_and_decrypt_payload(headers=headers, raw_body=raw_body, payload=payload)

        if is_url_verification(payload):
            self._verify_token(payload=payload)
            return {"challenge": payload.get("challenge")}

        event = parse_text_message_event(
            payload,
            bot_open_id=self._settings.feishu_bot_open_id,
            group_require_mention=self._settings.feishu_group_require_mention,
        )
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

        if not self._is_authorized_user(event.user_id):
            logger.warning(
                "unauthorized user ignored",
                extra={"trace_id": trace_id, "event": "feishu.unauthorized", "user_id": event.user_id},
            )
            return

        if normalized_text == "/stop":
            await self._handle_stop_command(
                message_id=event.message_id,
                chat_id=event.chat_id,
                session_key=session_key,
                trace_id=trace_id,
            )
            return

        await self._send_quick_ack(message_id=event.message_id, trace_id=trace_id)

        active_task = self._task_registry.get(session_key)
        if active_task is not None:
            await self._safe_reply(
                message_id=event.message_id,
                chat_id=event.chat_id,
                text="当前已有任务在运行中。发送 /stop 可强制终止后再试。",
                trace_id=trace_id,
                request_uuid=f"{event.message_id}-busy",
            )
            return

        reminder = parse_reminder_command(event.text)
        if reminder is not None:
            await self._handle_reminder_command(
                message_id=event.message_id,
                chat_id=event.chat_id,
                reminder_text=reminder.text,
                delay_seconds=reminder.delay_seconds,
                trace_id=trace_id,
            )
            return

        command = process_command(event.text, session_manager=self._sessions, session_key=session_key)
        if command is not None:
            await self._safe_reply(
                message_id=event.message_id,
                chat_id=event.chat_id,
                text=command.reply_text,
                trace_id=trace_id,
                request_uuid=f"{event.message_id}-cmd",
            )
            return

        codex_prompt = self._extract_codex_prompt(event.text)
        if codex_prompt is None:
            await self._safe_reply(
                message_id=event.message_id,
                chat_id=event.chat_id,
                text="未触发 Codex。请使用 /codex <任务>，或明确说“联动 Codex ...”。",
                trace_id=trace_id,
                request_uuid=f"{event.message_id}-not-triggered",
            )
            return
        if not codex_prompt:
            await self._safe_reply(
                message_id=event.message_id,
                chat_id=event.chat_id,
                text="请在 /codex 后输入任务内容。",
                trace_id=trace_id,
                request_uuid=f"{event.message_id}-empty-trigger",
            )
            return

        history_messages = self._sessions.build_messages(session_key)
        messages = history_messages + [{"role": "user", "content": codex_prompt}]
        started = self._task_registry.start(
            key=session_key,
            trace_id=trace_id,
            message_id=event.message_id,
            cancel_callback=lambda: self._codex_client.cancel(trace_id),
        )
        if not started:
            await self._safe_reply(
                message_id=event.message_id,
                chat_id=event.chat_id,
                text="当前已有任务在运行中。发送 /stop 可强制终止后再试。",
                trace_id=trace_id,
                request_uuid=f"{event.message_id}-busy",
            )
            return
        notice_task = asyncio.create_task(
            self._notify_if_still_running(
                session_key=session_key,
                message_id=event.message_id,
                chat_id=event.chat_id,
                trace_id=trace_id,
            )
        )
        generated_since = time.time()
        delivered_image_paths: list[str] = []
        auto_complete_on_image = self._looks_like_image_request(codex_prompt)
        image_watch_task: asyncio.Task[None] | None = None
        if auto_complete_on_image:
            image_watch_task = asyncio.create_task(
                self._watch_generated_images(
                    message_id=event.message_id,
                    chat_id=event.chat_id,
                    trace_id=trace_id,
                    generated_since=generated_since,
                    delivered_image_paths=delivered_image_paths,
                    auto_complete_on_image=auto_complete_on_image,
                )
            )

        try:
            if self._settings.streaming_enabled:
                answer = await self._stream_to_feishu(
                    message_id=event.message_id,
                    chat_id=event.chat_id,
                    messages=messages,
                    trace_id=trace_id,
                    generated_since=generated_since,
                    already_sent_image_paths=delivered_image_paths,
                    include_recent_generated_images=auto_complete_on_image,
                )
            else:
                answer = await self._codex_client.chat(messages=messages, trace_id=trace_id)
                generated_images = []
                if auto_complete_on_image:
                    generated_images = self._filter_unsent_images(
                        self._find_generated_images_since(generated_since),
                        delivered_image_paths,
                    )
                if not answer.strip() and generated_images:
                    answer = self._format_generated_image_refs(generated_images)
                if not answer.strip() and delivered_image_paths:
                    answer = self._format_generated_image_refs(delivered_image_paths)
                await self._safe_reply_with_images(
                    message_id=event.message_id,
                    chat_id=event.chat_id,
                    text=answer,
                    trace_id=trace_id,
                    extra_image_paths=generated_images,
                    already_sent_image_paths=delivered_image_paths,
                )

            self._sessions.append_round(key=session_key, user=codex_prompt, assistant=answer)
        except CodexClientCancelled:
            if auto_complete_on_image and delivered_image_paths:
                logger.info(
                    "image generation completed before codex final response",
                    extra={"trace_id": trace_id, "event": "pipeline.image_auto_complete"},
                )
                answer = self._format_generated_image_refs(delivered_image_paths)
                self._sessions.append_round(key=session_key, user=codex_prompt, assistant=answer)
                return
            logger.info("message cancelled by user", extra={"trace_id": trace_id, "event": "pipeline.cancel"})
            await self._safe_reply(
                message_id=event.message_id,
                chat_id=event.chat_id,
                text="当前任务已终止。",
                trace_id=trace_id,
            )
        except (CodexClientError, FeishuClientError, Exception):
            logger.exception("failed to process message", extra={"trace_id": trace_id, "event": "pipeline.error"})
            await self._safe_reply(
                message_id=event.message_id,
                chat_id=event.chat_id,
                text="服务繁忙，请稍后重试。",
                trace_id=trace_id,
            )
        finally:
            notice_task.cancel()
            await asyncio.gather(notice_task, return_exceptions=True)
            if image_watch_task is not None:
                await self._finish_image_watch_task(image_watch_task, delivered_image_paths)
            self._task_registry.finish(key=session_key, trace_id=trace_id)

    async def _stream_to_feishu(
        self,
        message_id: str,
        chat_id: str,
        messages: list[dict[str, str]],
        trace_id: str,
        generated_since: float,
        already_sent_image_paths: list[str] | None = None,
        include_recent_generated_images: bool = False,
    ) -> str:
        start = time.monotonic()
        full_text_parts: list[str] = []

        async for piece in self._codex_client.chat_stream(messages=messages, trace_id=trace_id):
            full_text_parts.append(piece)

        answer = "".join(full_text_parts).strip()
        already_sent = already_sent_image_paths or []
        generated_images = []
        if include_recent_generated_images:
            generated_images = self._filter_unsent_images(
                self._find_generated_images_since(generated_since),
                already_sent,
            )
        if not answer:
            if generated_images:
                answer = self._format_generated_image_refs(generated_images)
            elif already_sent:
                answer = self._format_generated_image_refs(already_sent)
            else:
                answer = "(空响应)"

        await self._safe_reply_with_images(
            message_id=message_id,
            chat_id=chat_id,
            text=answer,
            trace_id=trace_id,
            request_uuid=f"{message_id}-final",
            extra_image_paths=generated_images,
            already_sent_image_paths=already_sent,
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

    async def _notify_if_still_running(self, session_key: str, message_id: str, chat_id: str, trace_id: str) -> None:
        await asyncio.sleep(self._settings.task_running_notice_seconds)
        active_task = self._task_registry.get(session_key)
        if active_task is None or active_task.trace_id != trace_id:
            return
        if not self._task_registry.mark_notice_sent(session_key, trace_id):
            return

        await self._safe_reply(
            message_id=message_id,
            chat_id=chat_id,
            text="任务仍在运行中，我会继续处理；如需强制终止请发送 /stop。",
            trace_id=trace_id,
            request_uuid=f"{message_id}-running",
        )

    async def _handle_stop_command(self, message_id: str, chat_id: str, session_key: str, trace_id: str) -> None:
        task = self._task_registry.cancel(session_key)
        if task is None:
            await self._safe_reply(
                message_id=message_id,
                chat_id=chat_id,
                text="当前没有可终止的运行中任务。",
                trace_id=trace_id,
                request_uuid=f"{message_id}-stop-idle",
            )
            return

        await self._safe_reply(
            message_id=message_id,
            chat_id=chat_id,
            text="已收到停止请求，正在强制终止当前任务。",
            trace_id=trace_id,
            request_uuid=f"{message_id}-stop",
        )

    async def _handle_reminder_command(
        self,
        message_id: str,
        chat_id: str,
        reminder_text: str,
        delay_seconds: float,
        trace_id: str,
    ) -> None:
        if self._reminder_scheduler is None:
            await self._safe_reply(
                message_id=message_id,
                chat_id=chat_id,
                text="定时提醒组件未启用。",
                trace_id=trace_id,
                request_uuid=f"{message_id}-remind-disabled",
            )
            return

        reminder = await self._reminder_scheduler.schedule(
            chat_id=chat_id,
            text=reminder_text,
            delay_seconds=delay_seconds,
        )
        await self._safe_reply(
            message_id=message_id,
            chat_id=chat_id,
            text=f"已设置提醒: {reminder.reminder_id[:8]}",
            trace_id=trace_id,
            request_uuid=f"{message_id}-remind",
        )

    async def send_chat_text(self, chat_id: str, text: str, trace_id: str, request_uuid: str | None = None) -> None:
        await self._send_chat_text(chat_id=chat_id, text=text, trace_id=trace_id, request_uuid=request_uuid)

    async def _safe_reply_with_images(
        self,
        message_id: str,
        chat_id: str,
        text: str,
        trace_id: str,
        request_uuid: str | None = None,
        extra_image_paths: list[str] | None = None,
        already_sent_image_paths: list[str] | None = None,
    ) -> None:
        image_paths = self._merge_image_paths(extract_local_image_paths(text), extra_image_paths or [])
        shared_sent_paths = already_sent_image_paths
        already_sent = set(shared_sent_paths or [])
        image_paths_to_send = [path for path in image_paths if path not in already_sent]
        text_without_images = remove_local_image_references(text) if image_paths else text

        if normalize_reply_text(text_without_images):
            await self._safe_reply(
                message_id=message_id,
                chat_id=chat_id,
                text=text_without_images,
                trace_id=trace_id,
                request_uuid=request_uuid,
            )

        for idx, image_path in enumerate(image_paths_to_send, start=1):
            image_uuid = f"{request_uuid or message_id}-image-{idx}"
            if shared_sent_paths is not None:
                if image_path in shared_sent_paths:
                    continue
                shared_sent_paths.append(image_path)
            try:
                await self._safe_reply_image(
                    message_id=message_id,
                    chat_id=chat_id,
                    image_path=image_path,
                    trace_id=trace_id,
                    request_uuid=image_uuid,
                )
            except FeishuClientError:
                if shared_sent_paths is not None and image_path in shared_sent_paths:
                    shared_sent_paths.remove(image_path)
                logger.exception(
                    "failed to send generated image",
                    extra={"trace_id": trace_id, "event": "feishu.image_pipeline"},
                )
                await self._safe_reply(
                    message_id=message_id,
                    chat_id=chat_id,
                    text="图片已生成，但上传到飞书失败。请稍后重试。",
                    trace_id=trace_id,
                    request_uuid=f"{image_uuid}-failed",
                )

        if not image_paths and not normalize_reply_text(text_without_images):
            await self._safe_reply(
                message_id=message_id,
                chat_id=chat_id,
                text="(空响应)",
                trace_id=trace_id,
                request_uuid=request_uuid,
            )

    async def _watch_generated_images(
        self,
        message_id: str,
        chat_id: str,
        trace_id: str,
        generated_since: float,
        delivered_image_paths: list[str],
        auto_complete_on_image: bool,
    ) -> None:
        try:
            while True:
                await asyncio.sleep(1.0)
                image_paths = self._filter_unsent_images(
                    self._find_generated_images_since(generated_since),
                    delivered_image_paths,
                )
                for image_path in image_paths:
                    image_index = len(delivered_image_paths) + 1
                    delivered_image_paths.append(image_path)
                    try:
                        await self._safe_reply_image(
                            message_id=message_id,
                            chat_id=chat_id,
                            image_path=image_path,
                            trace_id=trace_id,
                            request_uuid=f"{message_id}-watch-image-{image_index}",
                        )
                    except Exception:
                        if image_path in delivered_image_paths:
                            delivered_image_paths.remove(image_path)
                        raise
                    logger.info(
                        "generated image delivered while codex is still running",
                        extra={"trace_id": trace_id, "event": "feishu.generated_image_watch"},
                    )

                if auto_complete_on_image and delivered_image_paths:
                    await asyncio.sleep(0.5)
                    self._codex_client.cancel(trace_id)
                    return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "generated image watcher failed",
                extra={"trace_id": trace_id, "event": "feishu.generated_image_watch_error"},
            )

    @staticmethod
    async def _finish_image_watch_task(image_watch_task: asyncio.Task[None], delivered_image_paths: list[str]) -> None:
        if delivered_image_paths and not image_watch_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(image_watch_task), timeout=10.0)
                return
            except asyncio.TimeoutError:
                pass

        if not image_watch_task.done():
            image_watch_task.cancel()
        await asyncio.gather(image_watch_task, return_exceptions=True)

    def _find_generated_images_since(self, since: float) -> list[str]:
        directory = str(getattr(self._settings, "codex_generated_images_dir", "~/.codex/generated_images"))
        # Allow slight clock/order skew between process start and image file write.
        return find_recent_generated_images(directory=directory, since=max(0.0, since - 2.0), until=time.time() + 2.0)

    @staticmethod
    def _filter_unsent_images(image_paths: list[str], delivered_image_paths: list[str]) -> list[str]:
        delivered = set(delivered_image_paths)
        return [path for path in image_paths if path not in delivered]

    @staticmethod
    def _merge_image_paths(*groups: list[str]) -> list[str]:
        seen: set[str] = set()
        paths: list[str] = []
        for group in groups:
            for path in group:
                if path not in seen:
                    seen.add(path)
                    paths.append(path)
        return paths

    @staticmethod
    def _format_generated_image_refs(image_paths: list[str]) -> str:
        return "\n".join(f"file://{path}" for path in image_paths)

    @staticmethod
    def _looks_like_image_request(text: str) -> bool:
        lowered = text.lower()
        keywords = ("画", "图", "图片", "插图", "漫画", "海报", "生成图", "image", "draw", "illustration")
        return any(keyword in lowered for keyword in keywords)

    async def _safe_reply_image(
        self,
        message_id: str,
        chat_id: str,
        image_path: str,
        trace_id: str,
        request_uuid: str | None = None,
    ) -> None:
        image_key = await self._feishu_client.upload_image(image_path=image_path, trace_id=trace_id)
        try:
            await self._feishu_client.reply_image(
                message_id=message_id,
                image_key=image_key,
                trace_id=trace_id,
                request_uuid=request_uuid,
            )
            return
        except FeishuClientError as exc:
            logger.warning(
                "image reply failed, falling back to chat send",
                extra={"trace_id": trace_id, "event": "feishu.image_reply_fallback", "error_code": type(exc).__name__},
            )

        await self._feishu_client.send_image(
            receive_id=chat_id,
            receive_id_type="chat_id",
            image_key=image_key,
            trace_id=trace_id,
            request_uuid=f"{request_uuid}-send" if request_uuid else None,
        )

    async def _safe_reply(
        self,
        message_id: str,
        chat_id: str,
        text: str,
        trace_id: str,
        request_uuid: str | None = None,
    ) -> None:
        content = normalize_reply_text(text)
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
        except FeishuClientError as exc:
            logger.warning(
                "reply failed, falling back to chat send",
                extra={"trace_id": trace_id, "event": "feishu.reply_fallback", "error_code": type(exc).__name__},
            )
            chunks = self._split_chunks(content)

        for idx, chunk in enumerate(chunks, start=1):
            chunk_uuid = request_uuid
            if request_uuid:
                chunk_uuid = f"{request_uuid}-part-{idx}"
            await self._send_chat_text(chat_id=chat_id, text=chunk, trace_id=trace_id, request_uuid=chunk_uuid)

    async def _send_chat_text(
        self,
        chat_id: str,
        text: str,
        trace_id: str,
        request_uuid: str | None = None,
    ) -> None:
        content = normalize_reply_text(text)
        if not content:
            return

        chunks = self._split_chunks(content)
        for idx, chunk in enumerate(chunks, start=1):
            chunk_uuid = request_uuid
            if request_uuid and len(chunks) > 1:
                chunk_uuid = f"{request_uuid}-send-part-{idx}"
            await self._feishu_client.send_text(
                receive_id=chat_id,
                receive_id_type="chat_id",
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

    def _is_authorized_user(self, user_id: str) -> bool:
        raw = str(getattr(self._settings, "codex_allowed_user_ids", "") or "").strip()
        if not raw:
            return True
        allowed = {item.strip() for item in raw.split(",") if item.strip()}
        return user_id in allowed

    def _extract_codex_prompt(self, text: str) -> str | None:
        content = text.strip()
        if not content:
            return ""

        trigger_required = bool(getattr(self._settings, "codex_trigger_required", False))
        if not trigger_required:
            return content

        raw_prefixes = str(
            getattr(
                self._settings,
                "codex_trigger_prefixes",
                "/codex,联动 Codex,联动codex,交给 Codex,让 Codex 处理",
            )
            or ""
        )
        prefixes = [prefix.strip() for prefix in raw_prefixes.split(",") if prefix.strip()]
        lower_content = content.lower()
        for prefix in prefixes:
            lower_prefix = prefix.lower()
            if lower_content == lower_prefix:
                return ""
            if lower_content.startswith(lower_prefix + " "):
                return content[len(prefix) :].strip()
            if lower_content.startswith(lower_prefix + "\n"):
                return content[len(prefix) :].strip()

        return None

    @staticmethod
    def _parse_payload(raw_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="invalid request body") from exc

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid payload type")
        return payload

    def _split_chunks(self, text: str, max_len: int | None = None) -> list[str]:
        configured_max_len = int(getattr(self._settings, "feishu_message_chunk_chars", 1500) or 1500)
        chunk_len = max_len or configured_max_len
        return split_message_text(text, max_chars=chunk_len)
