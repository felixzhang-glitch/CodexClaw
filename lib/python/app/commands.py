from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

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
    "/opencode - 切换后端为 OpenCode CLI\n"
    "/pi - 切换后端为 Pi Agent\n"
    "/skills - 列出本机可用 skills\n"
    "/remind 10m 内容 - 定时发送提醒（支持 s/m/h/d）\n"
    "/daily HH:MM 提示词 - 每日定时简报（/daily list 查看，/daily cancel <id> 取消）"
)


def build_help_text(*, include_remind: bool = True) -> str:
    lines = [
        "可用命令:",
        "/help - 查看帮助",
        "/new - 新建会话（不继承历史）",
        "/reset - 清空当前会话上下文",
        "/compact - 压缩当前会话上下文（保留最近 2 轮）",
        "/stop - 终止当前正在运行的任务",
        "/backend - 查看当前后端及可切换列表",
        "/codex - 切换后端为 Codex CLI",
        "/claude - 切换后端为 Claude Code",
        "/qodercli - 切换后端为 Qoder CLI",
        "/opencode - 切换后端为 OpenCode CLI",
        "/pi - 切换后端为 Pi Agent",
        "/skills - 列出本机可用 skills",
    ]
    if include_remind:
        lines.append("/remind 10m 内容 - 定时发送提醒（支持 s/m/h/d）")
    else:
        lines.append("/remind - 微信渠道暂不支持")
    lines.append("/daily HH:MM 提示词 - 每日定时简报（/daily list 查看，/daily cancel <id> 取消）")
    return "\n".join(lines)

BACKEND_COMMANDS: dict[str, str] = {
    "/codex": "codex",
    "/claude": "claude",
    "/qodercli": "qodercli",
    "/opencode": "opencode",
    "/pi": "pi",
}


@dataclass(slots=True)
class CommandResult:
    handled: bool
    reply_text: str


@dataclass(slots=True)
class ReminderCommand:
    delay_seconds: float
    text: str


@dataclass(slots=True)
class DailyCommand:
    action: str  # "create" | "list" | "cancel" | "invalid"
    hour: int = 0
    minute: int = 0
    prompt: str = ""
    task_id_prefix: str = ""
    error: str = ""


def parse_daily_command(raw_text: str) -> DailyCommand | None:
    text = raw_text.strip()
    if not text.lower().startswith("/daily"):
        return None

    rest = text[len("/daily"):].strip()
    if not rest or rest.lower() in {"list", "ls"}:
        return DailyCommand(action="list")

    cancel_match = re.match(r"^cancel\s+(\S+)$", rest, re.IGNORECASE)
    if cancel_match is not None:
        return DailyCommand(action="cancel", task_id_prefix=cancel_match.group(1))

    create_match = re.match(r"^(\d{1,2}):(\d{2})\s+(.+)$", rest, re.DOTALL)
    if create_match is not None:
        hour = int(create_match.group(1))
        minute = int(create_match.group(2))
        prompt = create_match.group(3).strip()
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return DailyCommand(action="invalid", error="时间格式错误，应为 HH:MM（00:00-23:59）。")
        if not prompt:
            return DailyCommand(action="invalid", error="缺少简报提示词。")
        return DailyCommand(action="create", hour=hour, minute=minute, prompt=prompt)

    return DailyCommand(
        action="invalid",
        error="用法: /daily HH:MM 提示词 | /daily list | /daily cancel <id前缀>",
    )


async def execute_daily_command(daily: DailyCommand, scheduler: Any, channel: str, target_id: str) -> str:
    if daily.action == "invalid":
        return daily.error

    if daily.action == "create":
        task = await scheduler.schedule(
            channel=channel,
            target_id=target_id,
            prompt=daily.prompt,
            hour=daily.hour,
            minute=daily.minute,
        )
        return f"已创建每日简报任务 {task.task_id[:8]}，每天 {daily.hour:02d}:{daily.minute:02d} 执行。"

    if daily.action == "cancel":
        task = await scheduler.cancel(daily.task_id_prefix)
        if task is None:
            return f"未找到唯一匹配的任务: {daily.task_id_prefix}（用 /daily list 查看）。"
        return f"已取消每日简报任务 {task.task_id[:8]}。"

    tasks = scheduler.list_tasks()
    if not tasks:
        return "当前没有每日简报任务。用 /daily HH:MM 提示词 创建。"
    lines = ["每日简报任务:"]
    for task in tasks:
        summary = task.prompt if len(task.prompt) <= 30 else f"{task.prompt[:30]}…"
        lines.append(f"- {task.task_id[:8]} {task.hour:02d}:{task.minute:02d} [{task.channel}] {summary}")
    return "\n".join(lines)


def process_command(
    raw_text: str,
    session_manager: SessionManager,
    session_key: str,
    router: Any | None = None,
) -> CommandResult | None:
    text = raw_text.strip().lower()

    if text == "/help":
        return CommandResult(handled=True, reply_text=HELP_TEXT)

    if text == "/new":
        session_id = session_manager.new_session(session_key)
        _reset_backend_session(router, session_key)
        return CommandResult(handled=True, reply_text=f"已创建新会话: {session_id[:8]}")

    if text == "/reset":
        session_manager.reset_session(session_key)
        _reset_backend_session(router, session_key)
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
                _reset_backend_session(router, session_key)
                return CommandResult(handled=True, reply_text=f"已切换后端为 {target}（{router.label(target)}）。")
            return CommandResult(handled=True, reply_text=f"切换失败: 未知后端 {target}。")

    return None


def _reset_backend_session(router: Any | None, session_key: str) -> None:
    if router is None:
        return
    reset = getattr(router, "reset_backend_session", None)
    if callable(reset):
        reset(session_key)


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
