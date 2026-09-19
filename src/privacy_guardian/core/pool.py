from __future__ import annotations

import asyncio
import multiprocessing
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from functools import partial
from typing import Any, TypeVar

T = TypeVar("T")


class AnalysisPool:
    def __init__(self, timeout: float = 20) -> None:
        self.timeout = timeout
        self._pool: ProcessPoolExecutor | None = None
        self.generation = 0
        self._semaphore = asyncio.Semaphore(8)

    def _create(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn")
            )
            self.generation += 1
        return self._pool

    def recycle(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            # Python 3.12 lacks terminate_workers; terminate only our owned workers.
            processes = getattr(pool, "_processes", {}) or {}
            for process in processes.values():
                if process.is_alive():
                    process.terminate()
            pool.shutdown(wait=False, cancel_futures=True)

    async def run(self, function: Callable[..., T], *args: Any) -> T:
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.get_running_loop().run_in_executor(
                        self._create(), partial(function, *args)
                    ),
                    self.timeout,
                )
            except (BrokenProcessPool, TimeoutError):
                self.recycle()
                self._create()
                raise RuntimeError("Analysis worker restarted; retry the operation") from None

    def close(self) -> None:
        self.recycle()
