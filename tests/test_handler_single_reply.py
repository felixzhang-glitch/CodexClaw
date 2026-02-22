from types import SimpleNamespace

import pytest

from channel.feishu.handler import FeishuWebhookHandler
from core.session.deduplicator import MessageDeduplicator
from core.session.manager import SessionManager


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
    async def chat(self, messages: list[dict[str, str]], trace_id: str) -> str:
        return "你好"

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str):
        for piece in ["你", "好"]:
            yield piece


@pytest.mark.asyncio
async def test_handle_text_event_quick_ack_and_single_final_reply() -> None:
    settings = SimpleNamespace(
        streaming_enabled=True,
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
