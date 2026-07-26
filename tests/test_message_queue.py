from __future__ import annotations

import asyncio

import pytest

from core.session.message_queue import SessionMessageQueue


@pytest.mark.asyncio
async def test_fifo_order() -> None:
    queue = SessionMessageQueue(max_pending=10)
    results: list[int] = []

    async def make_job(index: int):
        async def job() -> None:
            await asyncio.sleep(0.01)
            results.append(index)

        return job

    for i in range(5):
        status = await queue.submit("s1", await make_job(i))
        assert status.accepted
    await asyncio.sleep(0.2)
    assert results == [0, 1, 2, 3, 4]
    await queue.close()


@pytest.mark.asyncio
async def test_queue_position_feedback() -> None:
    queue = SessionMessageQueue(max_pending=10)
    release = asyncio.Event()

    async def blocking_job() -> None:
        await release.wait()

    async def noop_job() -> None:
        return None

    first = await queue.submit("s1", blocking_job)
    assert first.position == 0
    await asyncio.sleep(0.01)  # 让 worker 拿到第一条
    second = await queue.submit("s1", noop_job)
    assert second.accepted and second.position == 1
    third = await queue.submit("s1", noop_job)
    assert third.accepted and third.position == 2

    release.set()
    await asyncio.sleep(0.05)
    await queue.close()


@pytest.mark.asyncio
async def test_queue_full_rejected() -> None:
    queue = SessionMessageQueue(max_pending=2)
    release = asyncio.Event()

    async def blocking_job() -> None:
        await release.wait()

    await queue.submit("s1", blocking_job)
    await asyncio.sleep(0.01)
    assert (await queue.submit("s1", blocking_job)).accepted
    assert (await queue.submit("s1", blocking_job)).accepted
    overflow = await queue.submit("s1", blocking_job)
    assert not overflow.accepted

    release.set()
    await asyncio.sleep(0.05)
    await queue.close()


@pytest.mark.asyncio
async def test_clear_drops_pending_and_fires_on_drop() -> None:
    queue = SessionMessageQueue(max_pending=10)
    release = asyncio.Event()
    dropped_flags: list[int] = []
    executed: list[int] = []

    async def blocking_job() -> None:
        await release.wait()
        executed.append(0)

    async def make_pending(index: int):
        async def job() -> None:
            executed.append(index)

        return job

    await queue.submit("s1", blocking_job)
    await asyncio.sleep(0.01)
    for i in range(1, 4):
        await queue.submit("s1", await make_pending(i), on_drop=lambda i=i: dropped_flags.append(i))

    dropped = await queue.clear("s1")
    assert dropped == 3
    assert dropped_flags == [1, 2, 3]

    release.set()
    await asyncio.sleep(0.05)
    assert executed == [0]  # 只有正在跑的执行了
    await queue.close()


@pytest.mark.asyncio
async def test_sessions_are_independent() -> None:
    queue = SessionMessageQueue(max_pending=1)
    release = asyncio.Event()
    results: list[str] = []

    async def blocking_job() -> None:
        await release.wait()
        results.append("s1")

    async def fast_job() -> None:
        results.append("s2")

    await queue.submit("s1", blocking_job)
    await queue.submit("s2", fast_job)
    await asyncio.sleep(0.05)
    assert results == ["s2"]  # s2 不被 s1 阻塞

    release.set()
    await asyncio.sleep(0.05)
    assert results == ["s2", "s1"]
    await queue.close()


@pytest.mark.asyncio
async def test_job_exception_does_not_kill_worker() -> None:
    queue = SessionMessageQueue(max_pending=10)
    results: list[str] = []

    async def bad_job() -> None:
        raise RuntimeError("boom")

    async def good_job() -> None:
        results.append("ok")

    await queue.submit("s1", bad_job)
    await queue.submit("s1", good_job)
    await asyncio.sleep(0.1)
    assert results == ["ok"]
    await queue.close()
