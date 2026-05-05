import asyncio

import pytest

from core.session.reminder_scheduler import ReminderScheduler


@pytest.mark.asyncio
async def test_reminder_scheduler_persists_pending_reminders(tmp_path) -> None:
    delivered: list[tuple[str, str]] = []

    async def callback(chat_id: str, text: str, trace_id: str) -> None:
        delivered.append((chat_id, text))

    store_path = tmp_path / "reminders.json"
    scheduler = ReminderScheduler(callback=callback, store_path=str(store_path))
    await scheduler.schedule(chat_id="oc_1", text="喝水", delay_seconds=60)
    await scheduler.close()

    restored = ReminderScheduler(callback=callback, store_path=str(store_path))
    await restored.start()
    await restored.close()

    assert delivered == []
    assert "喝水" in store_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_reminder_scheduler_delivers_and_removes_store(tmp_path) -> None:
    delivered = asyncio.Event()

    async def callback(chat_id: str, text: str, trace_id: str) -> None:
        delivered.set()

    store_path = tmp_path / "reminders.json"
    scheduler = ReminderScheduler(callback=callback, store_path=str(store_path))
    await scheduler.schedule(chat_id="oc_1", text="喝水", delay_seconds=0.01)

    await asyncio.wait_for(delivered.wait(), timeout=1)
    await asyncio.sleep(0.01)
    await scheduler.close()

    assert store_path.read_text(encoding="utf-8") == "[]"
