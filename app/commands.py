from __future__ import annotations

from dataclasses import dataclass

from core.session.manager import SessionManager

HELP_TEXT = (
    "可用命令:\n"
    "/help - 查看帮助\n"
    "/new - 新建会话（不继承历史）\n"
    "/reset - 清空当前会话上下文"
)


@dataclass(slots=True)
class CommandResult:
    handled: bool
    reply_text: str


def process_command(raw_text: str, session_manager: SessionManager, session_key: str) -> CommandResult | None:
    text = raw_text.strip().lower()

    if text == "/help":
        return CommandResult(handled=True, reply_text=HELP_TEXT)

    if text == "/new":
        session_id = session_manager.new_session(session_key)
        return CommandResult(handled=True, reply_text=f"已创建新会话: {session_id[:8]}")

    if text == "/reset":
        session_manager.reset_session(session_key)
        return CommandResult(handled=True, reply_text="已清空当前会话上下文。")

    return None
