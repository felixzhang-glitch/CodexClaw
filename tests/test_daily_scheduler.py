from __future__ import annotations

import asyncio
import datetime
import json

import pytest

from app.commands import execute_daily_command, parse_daily_command
from core.session.daily_scheduler import DailyTask, DailyTaskScheduler


def test_parse_daily_create() -> None:
    command = parse_daily_command("/daily 08:00 搜索过去24小时AI领域大事件，输出中文简报")
    assert command is not None
    assert command.action == "create"
    assert command.hour == 8
    assert command.minute == 0
    assert "AI领域大事件" in command.prompt


def test_parse_daily_list_and_cancel() -> None:
    assert parse_daily_command("/daily list").action == "list"
    assert parse_daily_command("/daily").action == "list"
    cancel = parse_daily_command("/daily cancel abc123")
    assert cancel.action == "cancel"
    assert cancel.task_id_prefix == "abc123"


def test_parse_daily_invalid() -> None:
    assert parse_daily_command("/daily 25:00 test").action == "invalid"
    assert parse_daily_command("/daily foo").action == "invalid"
    assert parse_daily_command("/remind 10m test") is None


def _make_scheduler(tmp_path, run=None, push=None) -> DailyTaskScheduler:
    async def default_run(prompt: str, session_key: str, trace_id: str) -> str:
        return "简报内容"

    async def default_push(channel: str, target_id: str, text: str, trace_id: str) -> None:
        return None

    return DailyTaskScheduler(
        run_callback=run or default_run,
        push_callback=push or default_push,
        store_path=str(tmp_path / "daily-tasks.json"),
    )


@pytest.mark.asyncio
async def test_schedule_persist_and_cancel(tmp_path) -> None:
    scheduler = _make_scheduler(tmp_path)
    task = await scheduler.schedule(channel="feishu", target_id="oc_1", prompt="p", hour=23, minute=59)
    assert len(scheduler.list_tasks()) == 1

    stored = json.loads((tmp_path / "daily-tasks.json").read_text(encoding="utf-8"))
    assert stored[0]["task_id"] == task.task_id
    assert stored[0]["channel"] == "feishu"

    cancelled = await scheduler.cancel(task.task_id[:8])
    assert cancelled is not None
    assert scheduler.list_tasks() == []
    await scheduler.close()


@pytest.mark.asyncio
async def test_cancel_ambiguous_prefix(tmp_path) -> None:
    scheduler = _make_scheduler(tmp_path)
    assert await scheduler.cancel("") is None
    assert await scheduler.cancel("nonexist") is None
    await scheduler.close()


def _task(hour: int, minute: int, last_run_date: str = "") -> DailyTask:
    return DailyTask(
        task_id="t1",
        channel="feishu",
        target_id="oc_1",
        prompt="p",
        hour=hour,
        minute=minute,
        last_run_date=last_run_date,
    )


def test_seconds_until_next_run(tmp_path, monkeypatch) -> None:
    scheduler = _make_scheduler(tmp_path)
    fixed_now = datetime.datetime(2026, 7, 26, 10, 0, 0)
    monkeypatch.setattr(DailyTaskScheduler, "_now", staticmethod(lambda: fixed_now))

    # 未到触发点：当天 11:30
    seconds = scheduler._seconds_until_next_run(_task(11, 30))
    assert seconds == pytest.approx(90 * 60, abs=2)

    # 已过触发点：次日 08:00
    seconds = scheduler._seconds_until_next_run(_task(8, 0))
    assert seconds == pytest.approx(22 * 3600, abs=2)

    # 今天已跑过：即使还没到点也推到次日
    seconds = scheduler._seconds_until_next_run(_task(11, 30, last_run_date="2026-07-26"))
    assert seconds == pytest.approx(25.5 * 3600, abs=2)


def test_catch_up_window(tmp_path, monkeypatch) -> None:
    scheduler = _make_scheduler(tmp_path)
    fixed_now = datetime.datetime(2026, 7, 26, 10, 0, 0)
    monkeypatch.setattr(DailyTaskScheduler, "_now", staticmethod(lambda: fixed_now))

    # 6 小时窗口内且今天没跑 → 补偿
    assert scheduler._should_catch_up(_task(8, 0, last_run_date="2026-07-25")) is True
    # 超过 6 小时 → 跳过
    assert scheduler._should_catch_up(_task(3, 0, last_run_date="2026-07-25")) is False
    # 还没到触发点 → 不补
    assert scheduler._should_catch_up(_task(11, 0, last_run_date="2026-07-25")) is False
    # 今天已跑 → 不补
    assert scheduler._should_catch_up(_task(8, 0, last_run_date="2026-07-26")) is False


@pytest.mark.asyncio
async def test_execute_success_pushes_answer(tmp_path) -> None:
    pushed: list[tuple[str, str, str]] = []

    async def push(channel: str, target_id: str, text: str, trace_id: str) -> None:
        pushed.append((channel, target_id, text))

    scheduler = _make_scheduler(tmp_path, push=push)
    task = _task(8, 0)
    scheduler._tasks[task.task_id] = task
    await scheduler._execute(task)

    assert pushed == [("feishu", "oc_1", "简报内容")]
    assert task.last_run_date == scheduler._today()
    await scheduler.close()


@pytest.mark.asyncio
async def test_execute_failure_pushes_error_notice(tmp_path, monkeypatch) -> None:
    pushed: list[str] = []

    async def failing_run(prompt: str, session_key: str, trace_id: str) -> str:
        raise RuntimeError("backend down")

    async def push(channel: str, target_id: str, text: str, trace_id: str) -> None:
        pushed.append(text)

    scheduler = _make_scheduler(tmp_path, run=failing_run, push=push)
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    task = _task(8, 0)
    scheduler._tasks[task.task_id] = task
    await scheduler._execute(task)

    assert len(pushed) == 1
    assert "简报生成失败" in pushed[0]
    await scheduler.close()


async def _instant_sleep(_seconds: float) -> None:
    return None


@pytest.mark.asyncio
async def test_startup_loads_persisted_tasks(tmp_path) -> None:
    store = tmp_path / "daily-tasks.json"
    store.write_text(
        json.dumps(
            [
                {
                    "task_id": "abc",
                    "channel": "wechat",
                    "target_id": "user1",
                    "prompt": "简报",
                    "hour": 23,
                    "minute": 59,
                    "last_run_date": "2099-01-01",
                    "created_at": 0,
                }
            ]
        ),
        encoding="utf-8",
    )
    scheduler = _make_scheduler(tmp_path)
    await scheduler.start()
    tasks = scheduler.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].channel == "wechat"
    await scheduler.close()


class _FakeSchedulerForCommand:
    def __init__(self) -> None:
        self.tasks: list[DailyTask] = []

    async def schedule(self, channel: str, target_id: str, prompt: str, hour: int, minute: int) -> DailyTask:
        task = DailyTask(
            task_id="deadbeef" * 4,
            channel=channel,
            target_id=target_id,
            prompt=prompt,
            hour=hour,
            minute=minute,
        )
        self.tasks.append(task)
        return task

    def list_tasks(self) -> list[DailyTask]:
        return self.tasks

    async def cancel(self, prefix: str) -> DailyTask | None:
        for task in self.tasks:
            if task.task_id.startswith(prefix):
                self.tasks.remove(task)
                return task
        return None


@pytest.mark.asyncio
async def test_execute_daily_command_flow() -> None:
    scheduler = _FakeSchedulerForCommand()

    create = parse_daily_command("/daily 08:30 早报")
    reply = await execute_daily_command(create, scheduler, channel="feishu", target_id="oc_x")
    assert "已创建" in reply and "08:30" in reply

    listing = await execute_daily_command(parse_daily_command("/daily list"), scheduler, "feishu", "oc_x")
    assert "deadbeef" in listing and "早报" in listing

    cancel = await execute_daily_command(parse_daily_command("/daily cancel deadbeef"), scheduler, "feishu", "oc_x")
    assert "已取消" in cancel

    empty = await execute_daily_command(parse_daily_command("/daily list"), scheduler, "feishu", "oc_x")
    assert "没有每日简报任务" in empty
