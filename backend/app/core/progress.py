"""
OrbitScope - progress reporting for long-running work
=====================================================
Library code calls ``report(stage, done, total)`` without knowing who listens. A background
job installs a callback with ``reporter(cb)``; the context variable is inherited by every
asyncio task and ``asyncio.to_thread`` call started inside it, so progress from parallel
cutout downloads reaches the right job. Outside a job, ``report`` is a no-op.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Iterable, Iterator, Optional

ProgressCallback = Callable[[str, int, int], None]

_current: ContextVar[Optional[ProgressCallback]] = ContextVar("orbitscope_progress", default=None)


def report(stage: str, done: int = 0, total: int = 0) -> None:
    cb = _current.get()
    if cb is not None:
        try:
            cb(stage, done, total)
        except Exception:  # progress must never break the actual work
            pass


@contextmanager
def reporter(cb: ProgressCallback) -> Iterator[None]:
    token = _current.set(cb)
    try:
        yield
    finally:
        _current.reset(token)


async def gather_with_progress(stage: str, coros: Iterable[Awaitable[Any]]) -> list[Any]:
    """``asyncio.gather`` that reports how many of the awaitables have finished."""
    items = list(coros)
    total = len(items)
    done = 0
    report(stage, 0, total)

    async def wrap(c: Awaitable[Any]) -> Any:
        nonlocal done
        try:
            return await c
        finally:
            done += 1
            report(stage, done, total)

    return await asyncio.gather(*(wrap(c) for c in items))
