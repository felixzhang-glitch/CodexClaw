from app.commands import parse_reminder_command, process_command
from core.agent.claude_cli import ClaudeCliClient
from core.session.manager import SessionManager


class FakeRouter:
    def __init__(self, active: str = "codex") -> None:
        self.active = active

    def available(self) -> list[str]:
        return ["codex", "claude", "qodercli"]

    @staticmethod
    def label(name: str) -> str:
        return name

    def switch(self, name: str) -> bool:
        if name not in self.available():
            return False
        self.active = name
        return True


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


def test_backend_switch_resets_current_session_history() -> None:
    manager = SessionManager(max_history_rounds=10)
    key = SessionManager.build_key("u1", "c1")
    manager.append_round(key, "列出所有 skills", "Qoder skills")

    result = process_command("/claude", manager, key, router=FakeRouter(active="qodercli"))

    assert result is not None
    assert "已切换后端为 claude" in result.reply_text
    assert manager.round_count(key) == 0


def test_backend_switch_noop_keeps_current_session_history() -> None:
    manager = SessionManager(max_history_rounds=10)
    key = SessionManager.build_key("u1", "c1")
    manager.append_round(key, "hello", "world")

    result = process_command("/claude", manager, key, router=FakeRouter(active="claude"))

    assert result is not None
    assert "当前已是 claude" in result.reply_text
    assert manager.round_count(key) == 1


def test_skill_list_request_returns_local_skill_catalog(tmp_path, monkeypatch) -> None:
    skill_dir = tmp_path / "skills" / "yfinance"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: yfinance
description: "查询全球股票行情。"
---
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(ClaudeCliClient, "SKILL_ROOTS", (str(tmp_path / "skills"),))
    manager = SessionManager(max_history_rounds=10)
    key = SessionManager.build_key("u1", "c1")

    result = process_command("列出你的所有可用 skills", manager, key)

    assert result is not None
    assert result.handled is True
    assert "当前本机可用 skills" in result.reply_text
    assert "`yfinance`" in result.reply_text
