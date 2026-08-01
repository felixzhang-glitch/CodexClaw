"""End-to-end chain tests: channel handler -> AgentRouter -> opencode CLI.

The opencode subprocess is faked at the `create_subprocess_exec` boundary and
replays the exact NDJSON shape observed from `opencode run --format json`
(v1.18.10), so everything above the process boundary is the real code path:
command building, config injection, event parsing, session extraction and
persistence, router dispatch, and the channel reply.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import Settings
from channel.feishu.handler import FeishuWebhookHandler
from channel.wechat.handler import WeChatWebhookHandler
from core.agent.router import AgentRouter
from core.session.deduplicator import MessageDeduplicator
from core.session.manager import SessionManager
from core.session.task_registry import ActiveTaskRegistry

SESSION_ID = "ses_chain0001"
PART_ID = "prt_chain0001"
MESSAGE_ID = "msg_chain0001"


def _make_settings(tmp_path, **overrides) -> Settings:
    values = {
        "ACTIVE_BACKEND": "opencode",
        "BACKEND_STATE_PATH": str(tmp_path / "server" / "backend.json"),
        "CODEX_WORK_DIR": str(tmp_path / "workdir"),
        "CODEX_GENERATED_IMAGES_DIR": str(tmp_path / "generated-images"),
        "FEISHU_RECEIVED_IMAGES_DIR": str(tmp_path / "received-images"),
        "OPENCODE_MODEL": "alibaba-cn/qwen3.7-max",
        "OPENCODE_SESSION_STORE_PATH": str(tmp_path / "server" / "opencode-sessions.json"),
        "MEMORY_ENABLED": False,
        "MEMORY_DIR": str(tmp_path / "memory"),
        "MEMORY_GIT_DIR": str(tmp_path / "memory-git"),
        "MEMORY_CONTEXT_PATH": str(tmp_path / "server" / "memory-context.md"),
        "STREAMING_ENABLED": True,
        "WECHAT_WEBHOOK_TOKEN": "",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _ndjson(reply: str, *, session_id: str = SESSION_ID, reasoning: str | None = None) -> bytes:
    events = [{"type": "step_start", "sessionID": session_id, "timestamp": 1}]
    if reasoning is not None:
        events.append(
            {
                "type": "reasoning",
                "sessionID": session_id,
                "timestamp": 2,
                "part": {
                    "id": "prt_reason0001",
                    "messageID": MESSAGE_ID,
                    "sessionID": session_id,
                    "type": "reasoning",
                    "text": reasoning,
                    "time": {"start": 1, "end": 2},
                },
            }
        )
    events.append(
        {
            "type": "text",
            "sessionID": session_id,
            "timestamp": 2,
            "part": {
                "id": PART_ID,
                "messageID": MESSAGE_ID,
                "sessionID": session_id,
                "type": "text",
                "text": reply,
                "time": {"start": 1, "end": 2},
            },
        }
    )
    events.append({"type": "step_finish", "sessionID": session_id, "timestamp": 3})
    return "".join(f"{json.dumps(event, ensure_ascii=False)}\n" for event in events).encode()


class _FakeProcess:
    def __init__(self, stdout: bytes, *, return_code: int = 0) -> None:
        self.pid = 424242
        self.returncode = None
        self._return_code = return_code
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stdout.feed_eof()
        self.stderr = asyncio.StreamReader()
        self.stderr.feed_eof()

    async def wait(self) -> int:
        self.returncode = self._return_code
        return self._return_code


class _SpawnRecorder:
    """Replaces the opencode subprocess and records how it was invoked."""

    def __init__(self, *replies: str, reasoning: str | None = None) -> None:
        self._replies = list(replies)
        self._reasoning = reasoning
        self.calls: list[tuple[tuple[str, ...], dict]] = []

    async def __call__(self, *command, **kwargs):
        self.calls.append((command, kwargs))
        reply = self._replies[min(len(self.calls) - 1, len(self._replies) - 1)]
        return _FakeProcess(_ndjson(reply, reasoning=self._reasoning))

    def command(self, index: int = 0) -> list[str]:
        return list(self.calls[index][0])

    def env(self, index: int = 0) -> dict:
        return self.calls[index][1]["env"]


class FakeFeishuClient:
    def __init__(self) -> None:
        self.reply_calls: list[tuple[str, str | None]] = []
        self.send_calls: list[tuple[str, str, str | None]] = []
        self.reaction_calls: list[str] = []
        self.image_upload_calls: list[str] = []
        self.image_reply_calls: list[tuple[str, str | None]] = []

    async def reply_markdown(self, message_id, markdown, trace_id, request_uuid=None) -> None:
        self.reply_calls.append((markdown, request_uuid))

    async def reply_text(self, message_id, text, trace_id, request_uuid=None) -> None:
        self.reply_calls.append((text, request_uuid))

    async def send_markdown(self, receive_id, markdown, trace_id, receive_id_type="chat_id", request_uuid=None) -> str:
        self.send_calls.append((receive_id, markdown, request_uuid))
        return "om_sent"

    async def send_text(self, receive_id, text, trace_id, receive_id_type="chat_id", request_uuid=None) -> str:
        self.send_calls.append((receive_id, text, request_uuid))
        return "om_sent"

    async def create_reaction(self, message_id, emoji_type, trace_id) -> None:
        self.reaction_calls.append(emoji_type)

    async def upload_image(self, image_path, trace_id) -> str:
        self.image_upload_calls.append(image_path)
        return "img_chain"

    async def reply_image(self, message_id, image_key, trace_id, request_uuid=None) -> None:
        self.image_reply_calls.append((image_key, request_uuid))

    async def send_image(self, receive_id, image_key, trace_id, receive_id_type="chat_id", request_uuid=None) -> str:
        self.image_reply_calls.append((image_key, request_uuid))
        return "om_image"


def _feishu_handler(settings: Settings, feishu_client: FakeFeishuClient, router: AgentRouter) -> FeishuWebhookHandler:
    return FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=router,
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )


@pytest.mark.asyncio
async def test_feishu_message_reaches_opencode_and_reply_flows_back(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    feishu_client = FakeFeishuClient()
    spawn = _SpawnRecorder("杭州今天多云，18 到 24 度。")

    with (
        patch("core.agent.opencode_cli.memory.write_context_file", return_value=None),
        patch("asyncio.create_subprocess_exec", new=spawn),
    ):
        router = AgentRouter(settings=settings)
        assert router.active == "opencode"

        handler = _feishu_handler(settings, feishu_client, router)
        event = SimpleNamespace(
            message_id="om_chain_1",
            user_id="ou_chain_1",
            chat_id="oc_chain_1",
            text="杭州天气怎么样",
        )
        await handler._handle_text_event(event=event, trace_id="trace-chain-feishu")

    assert feishu_client.reaction_calls == ["Typing"]
    assert [text for text, _ in feishu_client.reply_calls] == ["杭州今天多云，18 到 24 度。"]

    command = spawn.command()
    assert command[:4] == ["opencode", "run", "--format", "json"]
    assert command[command.index("--model") + 1] == "alibaba-cn/qwen3.7-max"
    assert command[-1].endswith("杭州天气怎么样")
    assert "--session" not in command  # first turn has no stored session

    env = spawn.env()
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert config["permission"] == {"*": "allow"}
    assert env["OPENCODE_DISABLE_CLAUDE_CODE_PROMPT"] == "1"
    assert env["PWD"] == str(tmp_path / "workdir" / "opencode")

    # The session id parsed out of the stream survives the whole chain to disk.
    with open(settings.opencode_session_store_path, encoding="utf-8") as fh:
        assert list(json.load(fh).values()) == [SESSION_ID]


@pytest.mark.asyncio
async def test_second_feishu_turn_continues_the_stored_opencode_session(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    feishu_client = FakeFeishuClient()
    spawn = _SpawnRecorder("第一轮回复", "第二轮回复")

    with (
        patch("core.agent.opencode_cli.memory.write_context_file", return_value=None),
        patch("asyncio.create_subprocess_exec", new=spawn),
    ):
        handler = _feishu_handler(settings, feishu_client, AgentRouter(settings=settings))
        for index, text in enumerate(("第一个问题", "第二个问题"), start=1):
            await handler._handle_text_event(
                event=SimpleNamespace(
                    message_id=f"om_chain_turn_{index}",
                    user_id="ou_chain_1",
                    chat_id="oc_chain_1",
                    text=text,
                ),
                trace_id=f"trace-chain-turn-{index}",
            )

    assert [text for text, _ in feishu_client.reply_calls] == ["第一轮回复", "第二轮回复"]

    second = spawn.command(1)
    assert second[second.index("--session") + 1] == SESSION_ID
    # A continued session sends only the newest user message, not the history.
    assert second[-1] == "第二个问题"


@pytest.mark.asyncio
async def test_wechat_webhook_reaches_opencode_through_router(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    spawn = _SpawnRecorder("微信链路通了")

    with (
        patch("core.agent.opencode_cli.memory.write_context_file", return_value=None),
        patch("asyncio.create_subprocess_exec", new=spawn),
    ):
        handler = WeChatWebhookHandler(
            settings=settings,
            codex_client=AgentRouter(settings=settings),
            session_manager=SessionManager(max_history_rounds=10),
            deduplicator=MessageDeduplicator(ttl_seconds=3600),
            task_registry=ActiveTaskRegistry(),
        )
        result = await handler.handle_webhook(
            headers={},
            raw_body=json.dumps(
                {
                    "message_id": "wx_chain_1",
                    "account_id": "bot1",
                    "user_id": "wx_user_1",
                    "text": "链路测试",
                },
                ensure_ascii=False,
            ).encode(),
        )

    assert result["code"] == 0
    assert result["replies"] == ["微信链路通了"]
    assert spawn.command()[:4] == ["opencode", "run", "--format", "json"]


@pytest.mark.asyncio
async def test_reasoning_stream_events_never_reach_either_channel(tmp_path) -> None:
    """Thinking stays out of replies on both channels.

    Both channels join whatever the backend yields, so this invariant lives in
    the opencode event parser rather than in either handler -- one reasoning
    leak would surface in Feishu and WeChat alike.
    """
    settings = _make_settings(tmp_path)
    feishu_client = FakeFeishuClient()
    thinking = "用户问天气。我需要先判断城市，再决定要不要调用工具，最后组织回答。"
    spawn = _SpawnRecorder("杭州今天多云，18 到 24 度。", reasoning=thinking)

    with (
        patch("core.agent.opencode_cli.memory.write_context_file", return_value=None),
        patch("asyncio.create_subprocess_exec", new=spawn),
    ):
        router = AgentRouter(settings=settings)
        feishu = _feishu_handler(settings, feishu_client, router)
        await feishu._handle_text_event(
            event=SimpleNamespace(
                message_id="om_chain_reasoning",
                user_id="ou_chain_1",
                chat_id="oc_chain_1",
                text="杭州天气怎么样",
            ),
            trace_id="trace-chain-reasoning-feishu",
        )

        wechat = WeChatWebhookHandler(
            settings=settings,
            codex_client=router,
            session_manager=SessionManager(max_history_rounds=10),
            deduplicator=MessageDeduplicator(ttl_seconds=3600),
            task_registry=ActiveTaskRegistry(),
        )
        result = await wechat.handle_webhook(
            headers={},
            raw_body=json.dumps(
                {
                    "message_id": "wx_chain_reasoning",
                    "account_id": "bot1",
                    "user_id": "wx_user_1",
                    "text": "杭州天气怎么样",
                },
                ensure_ascii=False,
            ).encode(),
        )

    assert [text for text, _ in feishu_client.reply_calls] == ["杭州今天多云，18 到 24 度。"]
    assert result["replies"] == ["杭州今天多云，18 到 24 度。"]
    for delivered in [text for text, _ in feishu_client.reply_calls] + result["replies"]:
        assert thinking not in delivered
        assert "我需要先判断城市" not in delivered


@pytest.mark.asyncio
async def test_opencode_failure_replies_generic_error_without_leaking_details(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    feishu_client = FakeFeishuClient()

    async def failing_spawn(*command, **kwargs):
        return _FakeProcess(b'{"type":"error","message":"model unavailable"}\n', return_code=1)

    with (
        patch("core.agent.opencode_cli.memory.write_context_file", return_value=None),
        patch("asyncio.create_subprocess_exec", new=failing_spawn),
    ):
        handler = _feishu_handler(settings, feishu_client, AgentRouter(settings=settings))
        await handler._handle_text_event(
            event=SimpleNamespace(
                message_id="om_chain_fail",
                user_id="ou_chain_1",
                chat_id="oc_chain_1",
                text="触发失败",
            ),
            trace_id="trace-chain-fail",
        )

    replied = [text for text, _ in feishu_client.reply_calls]
    # A failed backend run must still produce a user-visible reply, and the raw
    # backend error stays in the logs rather than reaching the chat.
    assert replied == ["服务繁忙，请稍后重试。"]
    assert "model unavailable" not in replied[-1]
