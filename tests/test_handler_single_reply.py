import asyncio
from types import SimpleNamespace

import pytest

from channel.feishu.handler import FeishuWebhookHandler
from core.codex.client import CodexClientCancelled
from core.session.deduplicator import MessageDeduplicator
from core.session.manager import SessionManager
from core.session.task_registry import ActiveTaskRegistry


class FakeFeishuClient:
    def __init__(self) -> None:
        self.reply_calls: list[tuple[str, str | None]] = []
        self.reaction_calls: list[str] = []

    async def reply_text(
        self,
        message_id: str,
        text: str,
        trace_id: str,
        request_uuid: str | None = None,
    ) -> None:
        self.reply_calls.append((text, request_uuid))

    async def create_reaction(
        self,
        message_id: str,
        emoji_type: str,
        trace_id: str,
    ) -> None:
        self.reaction_calls.append(emoji_type)


class FakeCodexClient:
    def __init__(self) -> None:
        self.cancelled = False

    async def chat(self, messages: list[dict[str, str]], trace_id: str) -> str:
        return "你好"

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str):
        for piece in ["你", "好"]:
            yield piece

    def cancel(self, trace_id: str) -> bool:
        self.cancelled = True
        return True


@pytest.mark.asyncio
async def test_handle_text_event_quick_ack_and_single_final_reply() -> None:
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
    )
    feishu_client = FakeFeishuClient()
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=FakeCodexClient(),
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_1",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="你好",
    )

    await handler._handle_text_event(event=event, trace_id="trace_test")

    assert feishu_client.reaction_calls == ["Typing"]
    assert len(feishu_client.reply_calls) == 1
    assert feishu_client.reply_calls[0][0] == "你好"


class BlockingCodexClient:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()
        self.finished = asyncio.Event()

    async def chat(self, messages: list[dict[str, str]], trace_id: str) -> str:
        return "unused"

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str):
        while not self.cancelled.is_set() and not self.finished.is_set():
            await asyncio.sleep(0.01)
        if self.cancelled.is_set():
            raise CodexClientCancelled("cancelled")
        yield "完成"

    def cancel(self, trace_id: str) -> bool:
        self.cancelled.set()
        return True


@pytest.mark.asyncio
async def test_handle_text_event_sends_running_notice_before_final_reply() -> None:
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=0.01,
        feishu_encrypt_key="",
        feishu_verification_token="",
    )
    feishu_client = FakeFeishuClient()
    codex_client = BlockingCodexClient()
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=codex_client,
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_running",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="复杂任务",
    )

    task = asyncio.create_task(handler._handle_text_event(event=event, trace_id="trace-running"))
    await asyncio.sleep(0.05)

    assert any("任务仍在运行中" in text for text, _ in feishu_client.reply_calls)

    codex_client.finished.set()
    await task

    assert feishu_client.reply_calls[-1][0] == "完成"


@pytest.mark.asyncio
async def test_stop_command_cancels_active_task() -> None:
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
    )
    feishu_client = FakeFeishuClient()
    codex_client = BlockingCodexClient()
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=codex_client,
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    active_event = SimpleNamespace(
        message_id="om_test_active",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="请继续处理",
    )
    stop_event = SimpleNamespace(
        message_id="om_test_stop",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="/stop",
    )

    active_task = asyncio.create_task(handler._handle_text_event(event=active_event, trace_id="trace-active"))
    await asyncio.sleep(0.05)
    await handler._handle_text_event(event=stop_event, trace_id="trace-stop")
    await active_task

    reply_texts = [text for text, _ in feishu_client.reply_calls]
    assert "已收到停止请求，正在强制终止当前任务。" in reply_texts
    assert "当前任务已终止。" in reply_texts
