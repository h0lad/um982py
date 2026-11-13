"""Shared validation and scheduling for position polling."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from math import isfinite


def validate_interval(interval: float) -> None:
    if isinstance(interval, bool) or not isfinite(interval) or interval <= 0:
        raise ValueError("interval must be finite and positive")


def validate_callback(callback: object) -> None:
    if callback is not None and not callable(callback):
        raise TypeError("on_message must be callable")


async def poll_async[T](
    poll: Callable[[], Awaitable[T]], interval: float, stop: asyncio.Event | None
) -> AsyncIterator[T]:
    while stop is None or not stop.is_set():
        yield await poll()
        if stop is None:
            await asyncio.sleep(interval)
        else:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except TimeoutError:
                continue
            return
