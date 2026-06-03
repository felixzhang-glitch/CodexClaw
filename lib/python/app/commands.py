from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.agent.claude_cli import ClaudeCliClient
from core.session.manager import SessionManager

HELP_TEXT = (
    "可用命令:\n"
    "/help - 查看帮助\n"
    "/new - 新建会话（不继承历史）\n"
    "/reset - 清空当前会话上下文\n"
    "/compact - 压缩当前会话上下文（保留最近 2 轮）\n"
    "/stop - 终止当前正在运行的任务\n"
    "/backend - 查看当前后端及可切换列表\n"
    "/codex - 切换后端为 Codex CLI\n"
    "/claude - 切换后端为 Claude Code\n"
    "/qodercli - 切换后端为 Qoder CLI\n"
    "/skills - 列出本机可用 skills\n"
    "/remind 10m 内容 - 定时发送提醒（支持 s/m/h/d）"
)

BACKEND_COMMANDS: dict[str, str] = {
    "/codex": "codex",
    "/claude": "claude",
    "/qodercli": "qodercli",
}


@dataclass(slots=True)
class CommandResult:
    handled: bool
    reply_text: str


@dataclass(slots=True)
class ReminderCommand:
    delay_seconds: float
    text: str


def process_command(
    raw_text: str,
    session_manager: SessionManager,
    session_key: str,
    router: Any | None = None,
) -> CommandResult | None:
    text = raw_text.strip().lower()

    if text == "/help":
        return CommandResult(handled=True, reply_text=HELP_TEXT)

    if text == "/skills" or _looks_like_skill_list_request(raw_text):
        skills = ClaudeCliClient._build_skill_summary()
        if not skills:
            return CommandResult(handled=True, reply_text="当前本机未发现可用 skills。")
        return CommandResult(handled=True, reply_text=f"当前本机可用 skills:\n{skills}")

    if text == "/new":
        session_id = session_manager.new_session(session_key)
        return CommandResult(handled=True, reply_text=f"已创建新会话: {session_id[:8]}")

    if text == "/reset":
        session_manager.reset_session(session_key)
        return CommandResult(handled=True, reply_text="已清空当前会话上下文。")

    if text in {"/compact", "/compress"}:
        before, after = session_manager.compact_session(session_key)
        if before == after:
            return CommandResult(handled=True, reply_text="当前会话上下文较短，无需压缩。")
        return CommandResult(handled=True, reply_text=f"已压缩当前会话上下文: {before} 轮 -> {after} 轮。")

    if router is not None:
        if text == "/backend":
            current = router.active
            options = "、".join(f"{name}（{router.label(name)}）" for name in router.available())
            return CommandResult(
                handled=True,
                reply_text=f"当前后端: {current}（{router.label(current)}）\n可切换: {options}",
            )

        if text in BACKEND_COMMANDS:
            target = BACKEND_COMMANDS[text]
            if router.active == target:
                return CommandResult(handled=True, reply_text=f"当前已是 {target}（{router.label(target)}）后端。")
            if router.switch(target):
                session_manager.reset_session(session_key)
                return CommandResult(handled=True, reply_text=f"已切换后端为 {target}（{router.label(target)}）。")
            return CommandResult(handled=True, reply_text=f"切换失败: 未知后端 {target}。")

    return None


def _looks_like_skill_list_request(raw_text: str) -> bool:
    normalized = raw_text.strip().lower()
    if "skill" not in normalized:
        return False
    list_intents = ("列出", "所有", "全部", "可用", "有哪些", "能力", "清单", "列表")
    return any(intent in normalized for intent in list_intents)



def parse_reminder_command(raw_text: str) -> ReminderCommand | None:
    text = raw_text.strip()
    match = re.match(r"^/(?:remind|timer)\s+(\d+(?:\.\d+)?)([smhdSMHD])\s+(.+)$", text, re.DOTALL)
    if match is None:
        return None

    amount = float(match.group(1))
    unit = match.group(2).lower()
    reminder_text = match.group(3).strip()
    if amount <= 0 or not reminder_text:
        return None

    multipliers = {
        "s": 1,
        "m": 60,
        "h": 3600,
        "d": 86400,
    }
    return ReminderCommand(delay_seconds=amount * multipliers[unit], text=reminder_text)
