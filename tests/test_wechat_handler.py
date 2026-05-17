from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from channel.wechat.handler import WeChatWebhookHandler
from core.codex.client import CodexClientCancelled
from core.session.deduplicator import MessageDeduplicator
from core.session.manager import SessionManager
from core.session.task_registry import ActiveTaskRegistry


class FakeCodexClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []
        self.cancelled = False

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str):
        self.messages = messages
        yield "微信"
        yield "回复"

    async def chat(self, messages: list[dict[str, str]], trace_id: str) -> str:
        self.messages = messages
        return "微信回复"

    def cancel(self, trace_id: str) -> bool:
        self.cancelled = True
        return True


class BlockingCodexClient(FakeCodexClient):
    def __init__(self) -> None:
        super().__init__()
        import asyncio

        self.started = asyncio.Event()
        self.cancel_event = asyncio.Event()

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str):
        self.started.set()
        await self.cancel_event.wait()
        raise CodexClientCancelled("cancelled")
        if False:
            yield ""

    def cancel(self, trace_id: str) -> bool:
        self.cancelled = True
        self.cancel_event.set()
        return True


def make_handler(codex_client=None, token: str = "") -> WeChatWebhookHandler:
    settings = SimpleNamespace(
        streaming_enabled=True,
        wechat_webhook_token=token,
        wechat_message_chunk_chars=1800,
    )
    return WeChatWebhookHandler(
        settings=settings,
        codex_client=codex_client or FakeCodexClient(),
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )


@pytest.mark.asyncio
async def test_wechat_webhook_returns_codex_reply() -> None:
    codex = FakeCodexClient()
    handler = make_handler(codex_client=codex, token="secret")

    result = await handler.handle_webhook(
        headers={"authorization": "Bearer secret"},
        raw_body=(
            b'{"message_id":"m1","account_id":"bot1","user_id":"u1",'
            b'"text":"hello","context_token":"ctx1"}'
        ),
    )

    assert result["code"] == 0
    assert result["replies"] == ["微信回复"]
    assert codex.messages[-1] == {"role": "user", "content": "hello"}


@pytest.mark.asyncio
async def test_wechat_webhook_handles_session_command_without_codex() -> None:
    codex = FakeCodexClient()
    handler = make_handler(codex_client=codex)

    result = await handler.handle_webhook(
        headers={},
        raw_body=b'{"message_id":"m2","account_id":"bot1","user_id":"u1","text":"/new"}',
    )

    assert result["code"] == 0
    assert "已创建新会话" in result["replies"][0]
    assert codex.messages == []


@pytest.mark.asyncio
async def test_wechat_webhook_rejects_bad_token() -> None:
    handler = make_handler(token="secret")

    with pytest.raises(HTTPException) as exc_info:
        await handler.handle_webhook(
            headers={"authorization": "Bearer wrong"},
            raw_body=b'{"message_id":"m3","account_id":"bot1","user_id":"u1","text":"hello"}',
        )

    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_wechat_stop_cancels_running_task() -> None:
    import asyncio

    codex = BlockingCodexClient()
    handler = make_handler(codex_client=codex)

    running = asyncio.create_task(
        handler.handle_webhook(
            headers={},
            raw_body=b'{"message_id":"m4","account_id":"bot1","user_id":"u1","text":"slow"}',
        )
    )
    await asyncio.wait_for(codex.started.wait(), timeout=2.0)

    stop_result = await handler.handle_webhook(
        headers={},
        raw_body=b'{"message_id":"m5","account_id":"bot1","user_id":"u1","text":"/stop"}',
    )
    running_result = await asyncio.wait_for(running, timeout=2.0)

    assert stop_result["replies"] == ["已收到停止请求，正在强制终止当前任务。"]
    assert running_result["replies"] == ["当前任务已终止。"]
    assert codex.cancelled is True
