from app.commands import parse_reminder_command, process_command
from core.session.manager import SessionManager


def test_new_command_starts_fresh_session() -> None:
    manager = SessionManager(max_history_rounds=10)
    key = SessionManager.build_key("u1", "c1")

    old_session_id = manager.get_or_create(key).session_id
    manager.append_round(key, "hello", "world")

    result = process_command("/new", manager, key)

    assert result is not None
    assert result.handled is True
    assert "已创建新会话" in result.reply_text
    assert manager.round_count(key) == 0
    assert manager.get_or_create(key).session_id != old_session_id


def test_parse_reminder_command() -> None:
    result = parse_reminder_command("/remind 10m 喝水")

    assert result is not None
    assert result.delay_seconds == 600
    assert result.text == "喝水"


def test_compact_command_compresses_session_history() -> None:
    manager = SessionManager(max_history_rounds=10)
    key = SessionManager.build_key("u1", "c1")
    for idx in range(5):
        manager.append_round(key, f"question {idx}", f"answer {idx}")

    result = process_command("/compact", manager, key)

    assert result is not None
    assert "已压缩当前会话上下文" in result.reply_text
    assert manager.round_count(key) == 3
    messages = manager.build_messages(key)
    assert "已压缩的历史上下文摘要" in messages[1]["content"]
    assert messages[-2]["content"] == "question 4"
