from core.session.manager import SessionManager


def test_session_fifo_trim() -> None:
    manager = SessionManager(max_history_rounds=2)
    key = SessionManager.build_key("u1", "c1")

    manager.append_round(key, "q1", "a1")
    manager.append_round(key, "q2", "a2")
    manager.append_round(key, "q3", "a3")

    messages = manager.build_messages(key)

    assert manager.round_count(key) == 2
    assert messages[0]["content"] == "q2"
    assert messages[1]["content"] == "a2"
    assert messages[2]["content"] == "q3"
    assert messages[3]["content"] == "a3"
