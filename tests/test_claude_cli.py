from types import SimpleNamespace

from core.agent.claude_cli import ClaudeCliClient


def make_settings(tmp_path):
    return SimpleNamespace(codex_work_dir=str(tmp_path))


def test_claude_family_clients_use_backend_scoped_work_dirs(tmp_path) -> None:
    claude = ClaudeCliClient(
        settings=make_settings(tmp_path),
        name="claude",
        bin_path="claude",
        model="",
        permission_mode="auto",
    )
    qodercli = ClaudeCliClient(
        settings=make_settings(tmp_path),
        name="qodercli",
        bin_path="qodercli",
        model="",
        permission_mode="dangerously-skip-permissions",
        use_verbose=False,
        use_partial_messages=False,
    )

    claude_command = claude._build_command("hello", streaming=True)
    qoder_command = qodercli._build_command("hello", streaming=True)

    assert str(tmp_path / "claude") in claude_command
    assert str(tmp_path / "qodercli") in qoder_command
    assert "--verbose" in claude_command
    assert "--include-partial-messages" in claude_command
    assert "--verbose" not in qoder_command
    assert "--include-partial-messages" not in qoder_command
