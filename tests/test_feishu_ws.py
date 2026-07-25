"""Tests for the Feishu WebSocket client event conversion and handle_event path."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from channel.feishu.models import FeishuTextMessageEvent
from channel.feishu.ws_client import FeishuWsClient


def _make_sdk_event(
    *,
    text: str = "hello",
    message_type: str = "text",
    chat_type: str = "p2p",
    message_id: str = "msg_001",
    chat_id: str = "oc_123",
    event_id: str = "ev_001",
    open_id: str = "ou_user1",
    content: dict | None = None,
    mentions: list | None = None,
) -> MagicMock:
    """Build a mock P2ImMessageReceiveV1 matching lark SDK structure."""
    mock = MagicMock()

    # header
    mock.header.event_id = event_id

    # event.message
    msg = mock.event.message
    msg.message_type = message_type
    msg.chat_type = chat_type
    msg.message_id = message_id
    msg.chat_id = chat_id
    if content is None:
        if message_type == "text":
            content = {"text": text}
        elif message_type == "image":
            content = {"image_key": "img_key_001"}
    msg.content = json.dumps(content)
    msg.mentions = mentions

    # event.sender
    sender_id = mock.event.sender.sender_id
    sender_id.open_id = open_id
    sender_id.user_id = ""
    sender_id.union_id = ""

    return mock


@pytest.fixture
def ws_client():
    """Create a FeishuWsClient with mocked handler and loop."""
    handler = MagicMock()
    handler.handle_event = AsyncMock()
    loop = asyncio.new_event_loop()
    client = FeishuWsClient.__new__(FeishuWsClient)
    client._handler = handler
    client._loop = loop
    client._bot_open_id = ""
    client._group_require_mention = True
    yield client
    loop.close()


class TestConvertEvent:
    """Test _convert_event correctly transforms SDK events."""

    def test_text_message(self, ws_client: FeishuWsClient):
        sdk_event = _make_sdk_event(text="你好世界")
        result = ws_client._convert_event(sdk_event)

        assert result is not None
        assert isinstance(result, FeishuTextMessageEvent)
        assert result.text == "你好世界"
        assert result.message_type == "text"
        assert result.chat_type == "p2p"
        assert result.message_id == "msg_001"
        assert result.chat_id == "oc_123"
        assert result.user_id == "ou_user1"
        assert result.event_id == "ev_001"

    def test_image_message(self, ws_client: FeishuWsClient):
        sdk_event = _make_sdk_event(
            message_type="image",
            content={"image_key": "img_abc"},
        )
        result = ws_client._convert_event(sdk_event)

        assert result is not None
        assert result.message_type == "image"
        assert result.image_key == "img_abc"
        assert result.image_keys == ("img_abc",)
        assert result.text == "用户发送了一张图片。"

    def test_unsupported_message_type_returns_none(self, ws_client: FeishuWsClient):
        sdk_event = _make_sdk_event(message_type="sticker")
        result = ws_client._convert_event(sdk_event)
        assert result is None

    def test_empty_text_returns_none(self, ws_client: FeishuWsClient):
        sdk_event = _make_sdk_event(text="")
        result = ws_client._convert_event(sdk_event)
        assert result is None

    def test_group_without_mention_returns_none(self, ws_client: FeishuWsClient):
        ws_client._bot_open_id = "ou_bot"
        ws_client._group_require_mention = True
        sdk_event = _make_sdk_event(chat_type="group", text="hey")
        sdk_event.event.message.mentions = []
        result = ws_client._convert_event(sdk_event)
        assert result is None

    def test_group_with_mention_passes(self, ws_client: FeishuWsClient):
        ws_client._bot_open_id = "ou_bot"
        ws_client._group_require_mention = True

        mention = MagicMock()
        mention.key = "@_user_1"
        mention.id.open_id = "ou_bot"
        mention.id.user_id = ""
        mention.id.union_id = ""

        sdk_event = _make_sdk_event(chat_type="group", text="@_user_1 hello")
        sdk_event.event.message.mentions = [mention]
        result = ws_client._convert_event(sdk_event)

        assert result is not None
        assert result.text == "hello"

    def test_missing_chat_id_returns_none(self, ws_client: FeishuWsClient):
        sdk_event = _make_sdk_event()
        sdk_event.event.message.chat_id = ""
        result = ws_client._convert_event(sdk_event)
        assert result is None

    def test_post_message(self, ws_client: FeishuWsClient):
        post_content = {
            "post": {
                "zh_cn": {
                    "content": [
                        [{"tag": "text", "text": "段落一"}],
                        [{"tag": "text", "text": "段落二"}],
                    ]
                }
            }
        }
        sdk_event = _make_sdk_event(message_type="post", content=post_content)
        result = ws_client._convert_event(sdk_event)

        assert result is not None
        assert "段落一" in result.text
        assert "段落二" in result.text


class TestHandleEvent:
    """Test the handle_event integration path."""

    @pytest.mark.asyncio
    async def test_handle_event_creates_background_task(self):
        handler = MagicMock()
        handler._handle_text_event = AsyncMock()
        handler._log_background_task_result = MagicMock()

        # Import actual method and bind
        from channel.feishu.handler import FeishuWebhookHandler

        event = FeishuTextMessageEvent(
            event_id="ev_test",
            message_id="msg_test",
            chat_id="oc_test",
            user_id="ou_test",
            text="test",
            chat_type="p2p",
        )

        # Use the real handle_event method
        await FeishuWebhookHandler.handle_event(handler, event)
        await asyncio.sleep(0.05)  # let background task run

        handler._handle_text_event.assert_called_once()
        call_kwargs = handler._handle_text_event.call_args
        assert call_kwargs[1]["event"] == event
        assert "trace_id" in call_kwargs[1]
