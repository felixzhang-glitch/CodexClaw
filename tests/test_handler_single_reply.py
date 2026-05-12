import asyncio
from types import SimpleNamespace

import pytest

from channel.feishu.client import FeishuClientError
from channel.feishu.handler import FeishuWebhookHandler
from core.codex.client import CodexClientCancelled
from core.session.deduplicator import MessageDeduplicator
from core.session.manager import SessionManager
from core.session.reminder_scheduler import ReminderScheduler
from core.session.task_registry import ActiveTaskRegistry


class FakeFeishuClient:
    def __init__(self) -> None:
        self.reply_calls: list[tuple[str, str | None]] = []
        self.send_calls: list[tuple[str, str, str | None]] = []
        self.image_reply_calls: list[tuple[str, str | None]] = []
        self.image_upload_calls: list[str] = []
        self.reaction_calls: list[str] = []
        self.fail_reply = False
        self.image_upload_delay_seconds = 0.0
        self.image_upload_started_event: asyncio.Event | None = None

    async def reply_text(
        self,
        message_id: str,
        text: str,
        trace_id: str,
        request_uuid: str | None = None,
    ) -> None:
        if self.fail_reply:
            raise FeishuClientError("reply failed")
        self.reply_calls.append((text, request_uuid))

    async def send_text(
        self,
        receive_id: str,
        text: str,
        trace_id: str,
        receive_id_type: str = "chat_id",
        request_uuid: str | None = None,
    ) -> str:
        self.send_calls.append((receive_id, text, request_uuid))
        return "om_sent"

    async def create_reaction(
        self,
        message_id: str,
        emoji_type: str,
        trace_id: str,
    ) -> None:
        self.reaction_calls.append(emoji_type)

    async def upload_image(self, image_path: str, trace_id: str) -> str:
        self.image_upload_calls.append(image_path)
        if self.image_upload_started_event is not None:
            self.image_upload_started_event.set()
        if self.image_upload_delay_seconds:
            await asyncio.sleep(self.image_upload_delay_seconds)
        return "img_test"

    async def reply_image(
        self,
        message_id: str,
        image_key: str,
        trace_id: str,
        request_uuid: str | None = None,
    ) -> None:
        self.image_reply_calls.append((image_key, request_uuid))

    async def send_image(
        self,
        receive_id: str,
        image_key: str,
        trace_id: str,
        receive_id_type: str = "chat_id",
        request_uuid: str | None = None,
    ) -> str:
        self.image_reply_calls.append((image_key, request_uuid))
        return "om_image"


class FakeCodexClient:
    def __init__(self) -> None:
        self.cancelled = False
        self.messages: list[list[dict[str, str]]] = []
        self.reasoning_efforts: list[str | None] = []

    async def chat(self, messages: list[dict[str, str]], trace_id: str, reasoning_effort: str | None = None) -> str:
        self.messages.append(messages)
        self.reasoning_efforts.append(reasoning_effort)
        return "你好"

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str, reasoning_effort: str | None = None):
        self.messages.append(messages)
        self.reasoning_efforts.append(reasoning_effort)
        for piece in ["你", "好"]:
            yield piece

    def cancel(self, trace_id: str) -> bool:
        self.cancelled = True
        return True


class ImageCodexClient(FakeCodexClient):
    def __init__(self, image_path: str) -> None:
        super().__init__()
        self._image_path = image_path

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str, reasoning_effort: str | None = None):
        yield f"Generated Image:\nSaved to: file://{self._image_path}"


class EmptyImageCodexClient(FakeCodexClient):
    def __init__(self, image_path) -> None:
        super().__init__()
        self._image_path = image_path

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str, reasoning_effort: str | None = None):
        self._image_path.write_bytes(b"fake image")
        if False:
            yield ""


class BlockingImageCodexClient(FakeCodexClient):
    def __init__(self, image_path) -> None:
        super().__init__()
        self._image_path = image_path
        self.cancelled_event = asyncio.Event()

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str, reasoning_effort: str | None = None):
        self._image_path.write_bytes(b"fake image")
        while not self.cancelled_event.is_set():
            await asyncio.sleep(0.05)
        raise CodexClientCancelled("auto complete image")
        if False:
            yield ""

    def cancel(self, trace_id: str) -> bool:
        self.cancelled = True
        self.cancelled_event.set()
        return True


class WatchRaceImageCodexClient(FakeCodexClient):
    def __init__(self, image_path, image_upload_started_event: asyncio.Event) -> None:
        super().__init__()
        self._image_path = image_path
        self._image_upload_started_event = image_upload_started_event

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str, reasoning_effort: str | None = None):
        self._image_path.write_bytes(b"fake image")
        await asyncio.wait_for(self._image_upload_started_event.wait(), timeout=2.0)
        if False:
            yield ""


def test_extract_reasoning_effort_option() -> None:
    prompt, effort = FeishuWebhookHandler._extract_reasoning_effort("--effort high 深度分析")

    assert prompt == "深度分析"
    assert effort == "high"


def test_extract_reasoning_effort_equals_option() -> None:
    prompt, effort = FeishuWebhookHandler._extract_reasoning_effort("--effort=low 快速回答")

    assert prompt == "快速回答"
    assert effort == "low"


def test_extract_reasoning_effort_invalid_option_is_left_in_prompt() -> None:
    prompt, effort = FeishuWebhookHandler._extract_reasoning_effort("--effort turbo 分析")

    assert prompt == "--effort turbo 分析"
    assert effort is None


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


@pytest.mark.asyncio
async def test_handle_text_event_requires_codex_trigger_when_enabled() -> None:
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
        codex_trigger_required=True,
        codex_trigger_prefixes="/codex,联动 Codex",
        codex_allowed_user_ids="",
    )
    feishu_client = FakeFeishuClient()
    codex_client = FakeCodexClient()
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=codex_client,
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_trigger_required",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="你好",
    )

    await handler._handle_text_event(event=event, trace_id="trace-trigger-required")

    assert feishu_client.reply_calls == [("未触发 Codex。请使用 /codex <任务>，或明确说“联动 Codex ...”。", "om_test_trigger_required-not-triggered")]
    assert codex_client.messages == []


@pytest.mark.asyncio
async def test_handle_text_event_strips_codex_trigger() -> None:
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
        codex_trigger_required=True,
        codex_trigger_prefixes="/codex,联动 Codex",
        codex_allowed_user_ids="",
    )
    feishu_client = FakeFeishuClient()
    codex_client = FakeCodexClient()
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=codex_client,
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_trigger_strip",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="/codex 检查 inbox",
    )

    await handler._handle_text_event(event=event, trace_id="trace-trigger-strip")

    assert feishu_client.reply_calls[0][0] == "你好"
    assert codex_client.messages[-1][-1]["content"] == "检查 inbox"


@pytest.mark.asyncio
async def test_handle_text_event_passes_reasoning_effort_override() -> None:
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
        codex_trigger_required=True,
        codex_trigger_prefixes="/codex",
        codex_allowed_user_ids="",
    )
    feishu_client = FakeFeishuClient()
    codex_client = FakeCodexClient()
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=codex_client,
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_effort",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="/codex --effort high 检查 inbox",
    )

    await handler._handle_text_event(event=event, trace_id="trace-effort")

    assert codex_client.messages[-1][-1]["content"] == "检查 inbox"
    assert codex_client.reasoning_efforts == ["high"]


@pytest.mark.asyncio
async def test_handle_text_event_rejects_unauthorized_user() -> None:
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
        codex_trigger_required=True,
        codex_trigger_prefixes="/codex",
        codex_allowed_user_ids="ou_allowed",
    )
    feishu_client = FakeFeishuClient()
    codex_client = FakeCodexClient()
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=codex_client,
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_unauthorized",
        user_id="ou_other",
        chat_id="oc_test_1",
        text="/codex 检查 inbox",
    )

    await handler._handle_text_event(event=event, trace_id="trace-unauthorized")

    assert feishu_client.reply_calls == []
    assert feishu_client.reaction_calls == []
    assert codex_client.messages == []


class BlockingCodexClient:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()
        self.finished = asyncio.Event()

    async def chat(self, messages: list[dict[str, str]], trace_id: str, reasoning_effort: str | None = None) -> str:
        return "unused"

    async def chat_stream(self, messages: list[dict[str, str]], trace_id: str, reasoning_effort: str | None = None):
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


@pytest.mark.asyncio
async def test_reply_fallback_sends_to_chat_when_reply_fails() -> None:
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
    )
    feishu_client = FakeFeishuClient()
    feishu_client.fail_reply = True
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=FakeCodexClient(),
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_fallback",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="你好",
    )

    await handler._handle_text_event(event=event, trace_id="trace-fallback")

    assert feishu_client.reply_calls == []
    assert feishu_client.send_calls == [("oc_test_1", "你好", "om_test_fallback-final-part-1")]


@pytest.mark.asyncio
async def test_reminder_command_schedules_chat_message() -> None:
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
    )
    feishu_client = FakeFeishuClient()

    async def callback(chat_id: str, text: str, trace_id: str) -> None:
        await feishu_client.send_text(receive_id=chat_id, text=text, trace_id=trace_id, request_uuid=trace_id)

    reminder_scheduler = ReminderScheduler(callback=callback)
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=FakeCodexClient(),
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
        reminder_scheduler=reminder_scheduler,
    )

    event = SimpleNamespace(
        message_id="om_test_remind",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="/remind 0.01s 喝水",
    )

    await handler._handle_text_event(event=event, trace_id="trace-remind")
    await asyncio.sleep(0.05)
    await reminder_scheduler.close()

    assert any(text.startswith("已设置提醒") for text, _ in feishu_client.reply_calls)
    assert any(call[0] == "oc_test_1" and call[1] == "喝水" for call in feishu_client.send_calls)


@pytest.mark.asyncio
async def test_generated_image_path_is_uploaded_and_replied(tmp_path) -> None:
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"fake image")
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
        codex_generated_images_dir=str(tmp_path / "empty_generated_images"),
    )
    feishu_client = FakeFeishuClient()
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=ImageCodexClient(str(image_path)),
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_image",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="画一张图",
    )

    await handler._handle_text_event(event=event, trace_id="trace-image")

    assert feishu_client.image_upload_calls == [str(image_path)]
    assert feishu_client.image_reply_calls == [("img_test", "om_test_image-final-image-1")]


@pytest.mark.asyncio
async def test_recent_generated_image_is_used_when_codex_output_is_empty(tmp_path) -> None:
    image_root = tmp_path / "generated_images"
    image_dir = image_root / "run"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "generated.png"
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
        codex_generated_images_dir=str(image_root),
    )
    feishu_client = FakeFeishuClient()
    session_manager = SessionManager(max_history_rounds=10)
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=EmptyImageCodexClient(image_path),
        session_manager=session_manager,
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_recent_image",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="画一张图",
    )

    await handler._handle_text_event(event=event, trace_id="trace-recent-image")

    assert feishu_client.reply_calls == []
    assert feishu_client.image_upload_calls == [str(image_path)]
    assert feishu_client.image_reply_calls == [("img_test", "om_test_recent_image-final-image-1")]
    messages = session_manager.build_messages(SessionManager.build_key("ou_test_1", "oc_test_1"))
    assert f"file://{image_path}" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_non_image_request_does_not_pick_up_recent_generated_image(tmp_path) -> None:
    image_root = tmp_path / "generated_images"
    image_dir = image_root / "run"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "generated.png"
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
        codex_generated_images_dir=str(image_root),
    )
    feishu_client = FakeFeishuClient()
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=EmptyImageCodexClient(image_path),
        session_manager=SessionManager(max_history_rounds=10),
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_non_image",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="总结一下",
    )

    await handler._handle_text_event(event=event, trace_id="trace-non-image")

    assert feishu_client.image_upload_calls == []
    assert feishu_client.image_reply_calls == []
    assert feishu_client.reply_calls == [("(空响应)", "om_test_non_image-final")]


@pytest.mark.asyncio
async def test_generated_image_watcher_auto_completes_image_request(tmp_path) -> None:
    image_root = tmp_path / "generated_images"
    image_dir = image_root / "run"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "generated.png"
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
        codex_generated_images_dir=str(image_root),
    )
    feishu_client = FakeFeishuClient()
    session_manager = SessionManager(max_history_rounds=10)
    codex_client = BlockingImageCodexClient(image_path)
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=codex_client,
        session_manager=session_manager,
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_watch_image",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="画一张图",
    )

    await handler._handle_text_event(event=event, trace_id="trace-watch-image")

    assert codex_client.cancelled
    assert feishu_client.image_upload_calls == [str(image_path)]
    assert feishu_client.image_reply_calls == [("img_test", "om_test_watch_image-watch-image-1")]
    assert "当前任务已终止" not in [text for text, _ in feishu_client.reply_calls]


@pytest.mark.asyncio
async def test_generated_image_watcher_reserves_path_before_final_scan(tmp_path) -> None:
    image_root = tmp_path / "generated_images"
    image_dir = image_root / "run"
    image_dir.mkdir(parents=True)
    image_path = image_dir / "generated.png"
    settings = SimpleNamespace(
        streaming_enabled=True,
        task_running_notice_seconds=30.0,
        feishu_encrypt_key="",
        feishu_verification_token="",
        codex_generated_images_dir=str(image_root),
    )
    image_upload_started = asyncio.Event()
    feishu_client = FakeFeishuClient()
    feishu_client.image_upload_started_event = image_upload_started
    feishu_client.image_upload_delay_seconds = 0.1
    session_manager = SessionManager(max_history_rounds=10)
    handler = FeishuWebhookHandler(
        settings=settings,
        feishu_client=feishu_client,
        codex_client=WatchRaceImageCodexClient(image_path, image_upload_started),
        session_manager=session_manager,
        deduplicator=MessageDeduplicator(ttl_seconds=3600),
        task_registry=ActiveTaskRegistry(),
    )

    event = SimpleNamespace(
        message_id="om_test_watch_race",
        user_id="ou_test_1",
        chat_id="oc_test_1",
        text="画一张图",
    )

    await handler._handle_text_event(event=event, trace_id="trace-watch-race")

    assert feishu_client.image_upload_calls == [str(image_path)]
    assert feishu_client.image_reply_calls == [("img_test", "om_test_watch_race-watch-image-1")]
