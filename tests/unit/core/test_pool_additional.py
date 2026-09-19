from __future__ import annotations

from typing import Any

import pytest

from privacy_guardian.core.pool import AnalysisPool


def _increment(value: int) -> int:
    return value + 1


def test_pool_is_created_lazily_with_spawn_context(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[dict[str, object]] = []

    class Executor:
        def __init__(self, **kwargs: object) -> None:
            created.append(kwargs)

    context = object()
    monkeypatch.setattr(
        "privacy_guardian.core.pool.multiprocessing.get_context",
        lambda name: context if name == "spawn" else None,
    )
    monkeypatch.setattr("privacy_guardian.core.pool.ProcessPoolExecutor", Executor)
    pool = AnalysisPool()

    first = pool._create()

    assert pool._create() is first
    assert pool.generation == 1
    assert created == [{"max_workers": 1, "mp_context": context}]


def test_recycle_terminates_live_owned_processes_and_shuts_down() -> None:
    actions: list[str] = []

    class Process:
        def __init__(self, alive: bool) -> None:
            self.alive = alive

        def is_alive(self) -> bool:
            return self.alive

        def terminate(self) -> None:
            actions.append("terminate")

    class Executor:
        _processes = {1: Process(True), 2: Process(False)}

        def shutdown(self, **kwargs: object) -> None:
            actions.append(f"shutdown:{kwargs}")

    pool = AnalysisPool()
    pool._pool = Executor()  # type: ignore[assignment]

    pool.recycle()

    assert pool._pool is None
    assert actions == ["terminate", "shutdown:{'wait': False, 'cancel_futures': True}"]


@pytest.mark.asyncio
async def test_run_executes_callable_and_restores_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Loop:
        def run_in_executor(self, _executor: object, callback: Any) -> Any:
            async def complete() -> object:
                return callback()

            return complete()

    pool = AnalysisPool(timeout=1)
    executor = object()
    monkeypatch.setattr("privacy_guardian.core.pool.asyncio.get_running_loop", lambda: Loop())
    monkeypatch.setattr(pool, "_create", lambda: executor)

    result = await pool.run(lambda left, right: left + right, 2, 3)

    assert result == 5
    assert pool.active == 0
    assert pool.last_used > 0


@pytest.mark.asyncio
async def test_timeout_recycles_worker_and_returns_retryable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Loop:
        def run_in_executor(self, _executor: object, _callback: Any) -> Any:
            async def fail() -> None:
                raise TimeoutError

            return fail()

    pool = AnalysisPool(timeout=1)
    calls: list[str] = []
    monkeypatch.setattr("privacy_guardian.core.pool.asyncio.get_running_loop", lambda: Loop())
    monkeypatch.setattr(pool, "_create", lambda: calls.append("create") or object())
    monkeypatch.setattr(pool, "recycle", lambda: calls.append("recycle"))

    with pytest.raises(RuntimeError, match="worker restarted"):
        await pool.run(lambda: None)

    assert calls == ["create", "recycle", "create"]
    assert pool.active == 0


def test_close_recycles_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = AnalysisPool()
    calls: list[bool] = []
    monkeypatch.setattr(pool, "recycle", lambda: calls.append(True))

    pool.close()

    assert calls == [True]


@pytest.mark.asyncio
async def test_killed_owned_worker_recovers_for_next_analysis_within_two_seconds() -> None:
    pool = AnalysisPool(timeout=5)
    try:
        assert await pool.run(_increment, 1) == 2
        assert pool._pool is not None
        processes = list((getattr(pool._pool, "_processes", {}) or {}).values())
        assert len(processes) == 1
        processes[0].terminate()
        processes[0].join(timeout=1)
        started = __import__("time").monotonic()

        with pytest.raises(RuntimeError, match="worker restarted"):
            await pool.run(_increment, 2)
        assert await pool.run(_increment, 3) == 4

        assert __import__("time").monotonic() - started < 2
    finally:
        pool.close()
