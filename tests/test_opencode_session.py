import json
from types import SimpleNamespace

import pytest

from core.agent.opencode_cli import OpenCodeCliClient


def _make_settings(tmp_path):
    return SimpleNamespace(
        opencode_cli_bin="opencode",
        opencode_model="",
        opencode_agent="",
        opencode_timeout_seconds=300.0,
        opencode_idle_timeout_seconds=120.0,
        opencode_session_store_path=str(tmp_path / "server" / "opencode-sessions.json"),
        codex_work_dir=str(tmp_path / "workdir"),
        codex_stream_read_limit_bytes=262144,
        codex_max_retries=2,
        codex_retry_backoff_seconds=0.0,
        codex_circuit_breaker_threshold=5,
        codex_circuit_breaker_cooldown_seconds=30,
    )


def test_build_command_appends_session_flag(tmp_path) -> None:
    client = OpenCodeCliClient(settings=_make_settings(tmp_path))

    assert "--session" not in client._build_command(None)

    command = client._build_command("ses_abc")
    assert command[:4] == ["opencode", "run", "--format", "json"]
    assert "--session" in command
    assert command[command.index("--session") + 1] == "ses_abc"


def test_native_prompt_only_uses_latest_user_message(tmp_path) -> None:
    client = OpenCodeCliClient(settings=_make_settings(tmp_path))
    messages = [
        {"role": "user", "content": "旧问题"},
        {"role": "assistant", "content": "旧回答"},
        {"role": "user", "content": "最新问题"},
    ]

    prompt_continue = client._build_native_prompt(messages, include_preamble=False)
    assert prompt_continue == "最新问题"
    assert "旧问题" not in prompt_continue

    prompt_new = client._build_native_prompt(messages, include_preamble=True)
    assert "最新问题" in prompt_new
    assert "codeClaw" in prompt_new


def test_extract_session_id_from_event_and_part(tmp_path) -> None:
    client = OpenCodeCliClient(settings=_make_settings(tmp_path))

    assert client._extract_session_id({"sessionID": "ses_top"}) == "ses_top"
    assert client._extract_session_id({"type": "text", "part": {"sessionID": "ses_part"}}) == "ses_part"
    assert client._extract_session_id({"type": "text", "part": {"id": "p1"}}) == ""


def test_session_persistence_roundtrip_and_reset(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    client = OpenCodeCliClient(settings=settings)
    key = "u1:c1"

    assert client._get_session_id(key) is None

    client._persist_session(key, {"id": "ses_persist"})
    assert client._get_session_id(key) == "ses_persist"

    # A fresh client loads the persisted mapping from disk.
    reloaded = OpenCodeCliClient(settings=settings)
    assert reloaded._get_session_id(key) == "ses_persist"

    with open(settings.opencode_session_store_path, encoding="utf-8") as fh:
        assert json.load(fh) == {key: "ses_persist"}

    client.reset_session(key)
    assert client._get_session_id(key) is None
    assert OpenCodeCliClient(settings=settings)._get_session_id(key) is None


@pytest.mark.asyncio
async def test_chat_continues_stored_session_and_persists_new_id(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    client = OpenCodeCliClient(settings=settings)
    key = "u1:c1"
    captured: dict[str, object] = {}

    async def fake_run_stream_once(prompt, trace_id, *, session_id=None, session_holder=None):
        captured["prompt"] = prompt
        captured["session_id"] = session_id
        if session_holder is not None:
            session_holder["id"] = "ses_created"
        yield "回复正文"

    client._run_stream_once = fake_run_stream_once  # type: ignore[assignment]

    messages = [{"role": "user", "content": "第一条消息"}]
    answer = await client.chat(messages=messages, trace_id="t1", session_key=key)

    assert answer == "回复正文"
    assert captured["prompt"].endswith("第一条消息") or captured["prompt"] == "第一条消息"
    assert captured["session_id"] is None  # first turn has no stored session
    assert client._get_session_id(key) == "ses_created"

    # Second turn should continue the captured session id and send only the new message.
    answer2 = await client.chat(
        messages=messages + [{"role": "assistant", "content": "回复正文"}, {"role": "user", "content": "第二条"}],
        trace_id="t2",
        session_key=key,
    )
    assert answer2 == "回复正文"
    assert captured["session_id"] == "ses_created"
    assert captured["prompt"] == "第二条"
