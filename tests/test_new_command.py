from app.commands import process_command
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
