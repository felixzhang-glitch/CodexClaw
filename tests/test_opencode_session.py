import json
import os
from types import SimpleNamespace
from unittest.mock import patch

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

    # Rules reach opencode natively via the `instructions` config, so the
    # preamble only carries the skill summary; without one the prompt is the
    # bare user text.
    with patch("core.agent.opencode_cli.ClaudeCliClient._build_skill_summary", return_value=""):
        prompt_new = client._build_native_prompt(messages, include_preamble=True)
    assert prompt_new == "最新问题"

    with patch("core.agent.opencode_cli.ClaudeCliClient._build_skill_summary", return_value="- demo-skill"):
        prompt_with_skills = client._build_native_prompt(messages, include_preamble=True)
    assert "最新问题" in prompt_with_skills
    assert "demo-skill" in prompt_with_skills


def test_build_config_content_points_instructions_at_rules(tmp_path) -> None:
    client = OpenCodeCliClient(settings=_make_settings(tmp_path))

    config = client._build_config_content()

    instructions = config.get("instructions", [])
    assert any(path.endswith("rules/AGENTS.md") for path in instructions)
    for path in instructions:
        assert os.path.isfile(path)


def test_extract_session_id_from_event_and_part(tmp_path) -> None:
    client = OpenCodeCliClient(settings=_make_settings(tmp_path))

    assert client._extract_session_id({"sessionID": "ses_top"}) == "ses_top"
    assert client._extract_session_id({"type": "text", "part": {"sessionID": "ses_part"}}) == "ses_part"
    assert client._extract_session_id({"type": "text", "part": {"id": "p1"}}) == ""


def _text_event(part_id: str, text: str) -> dict:
    return {"type": "text", "part": {"id": part_id, "messageID": "msg_1", "type": "text", "text": text}}


def test_extract_text_delta_emits_each_character_once_per_part(tmp_path) -> None:
    client = OpenCodeCliClient(settings=_make_settings(tmp_path))
    emitted: dict[str, int] = {}

    # opencode sends the full accumulated text of a part on every `text` event,
    # so the delta must be the new suffix only.
    growth = ["杭", "杭州", "杭州今天", "杭州今天多云"]
    deltas = [client._extract_text_delta(_text_event("prt_a", text), emitted) for text in growth]

    assert deltas == ["杭", "州", "今天", "多云"]
    assert "".join(deltas) == growth[-1]

    # A duplicated event must not re-emit text already sent.
    assert client._extract_text_delta(_text_event("prt_a", "杭州今天多云"), emitted) == ""

    # A single event carrying the whole message is the shape opencode actually
    # produces today: one text event per assistant message.
    single = {}
    assert client._extract_text_delta(_text_event("prt_b", "一次性全量"), single) == "一次性全量"


def test_extract_text_delta_tracks_parts_independently(tmp_path) -> None:
    client = OpenCodeCliClient(settings=_make_settings(tmp_path))
    emitted: dict[str, int] = {}

    assert client._extract_text_delta(_text_event("prt_a", "AAA"), emitted) == "AAA"
    # A different part starts from zero instead of inheriting the other's offset.
    assert client._extract_text_delta(_text_event("prt_b", "BBBBB"), emitted) == "BBBBB"
    assert client._extract_text_delta(_text_event("prt_a", "AAACCC"), emitted) == "CCC"

    # Missing ids fall back to messageID, then to a shared anonymous counter.
    anon: dict[str, int] = {}
    no_id = {"type": "text", "part": {"messageID": "msg_x", "text": "以 messageID 计数"}}
    assert client._extract_text_delta(no_id, anon) == "以 messageID 计数"
    assert client._extract_text_delta(no_id, anon) == ""


def test_extract_text_delta_assumes_cumulative_text_not_incremental(tmp_path) -> None:
    """Tripwire for the upstream contract this parser depends on.

    Every `text` event is assumed to carry the full accumulated text. If opencode
    ever switches to emitting true incremental deltas, the prefix diff below
    silently drops content instead of concatenating it -- this test documents
    that failure mode so the breakage surfaces here rather than as truncated
    replies in production.
    """
    client = OpenCodeCliClient(settings=_make_settings(tmp_path))
    emitted: dict[str, int] = {}

    assert client._extract_text_delta(_text_event("prt_a", "第一段"), emitted) == "第一段"
    # A non-cumulative follow-up of equal or shorter length is dropped entirely.
    assert client._extract_text_delta(_text_event("prt_a", "第二段"), emitted) == ""
    # A longer non-cumulative payload is sliced by length, not by content.
    assert client._extract_text_delta(_text_event("prt_a", "第三段续写"), emitted) == "续写"

    # Empty and non-string payloads never produce output.
    assert client._extract_text_delta(_text_event("prt_c", ""), emitted) == ""
    assert client._extract_text_delta({"type": "text", "part": {"id": "prt_d", "text": None}}, emitted) == ""
    assert client._extract_text_delta({"type": "step_finish", "part": {"text": "忽略"}}, emitted) == ""


def test_extract_text_delta_ignores_reasoning_events(tmp_path) -> None:
    """Chain-of-thought must never become reply text.

    When a model is registered with `reasoning: true`, opencode sets
    `enable_thinking` on the DashScope request, the provider returns the
    chain-of-thought in `reasoning_content`, and it arrives here as a
    `reasoning` event instead of a `text` one. Registering the model without
    that capability flag is what previously leaked thinking into replies:
    the provider had nowhere to put it and folded it into `content`, which is
    indistinguishable from an answer at this layer.
    """
    client = OpenCodeCliClient(settings=_make_settings(tmp_path))
    emitted: dict[str, int] = {}

    reasoning = {
        "type": "reasoning",
        "part": {"id": "prt_r", "messageID": "msg_1", "type": "reasoning", "text": "先分析用户意图，再决定回答结构"},
    }
    assert client._extract_text_delta(reasoning, emitted) == ""
    assert emitted == {}

    # A real answer on the same message is unaffected by the skipped reasoning.
    assert client._extract_text_delta(_text_event("prt_t", "杭州今天多云"), emitted) == "杭州今天多云"


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
