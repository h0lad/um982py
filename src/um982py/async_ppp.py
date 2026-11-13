"""Asynchronous PPP position monitoring."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from um982py._polling import poll_async, validate_callback, validate_interval
from um982py.commands.configuration import SignalGroup
from um982py.messages.frames import Message
from um982py.ppp import PppService, PppSession, PppSolution

if TYPE_CHECKING:
    from um982py.async_receiver import AsyncReceiver


@dataclass(frozen=True, slots=True)
class AsyncPppSession:
    """An active PPP session accessed through an asynchronous receiver.

    The caller owns the receiver. PPP settings remain active after iteration.
    """

    receiver: AsyncReceiver
    _session: PppSession

    @property
    def service(self) -> PppService:
        return self._session.service

    @property
    def previous_group(self) -> SignalGroup:
        return self._session.previous_group

    @property
    def active_group(self) -> SignalGroup:
        return self._session.active_group

    @property
    def previous_enabled(self) -> bool | None:
        return self._session.previous_enabled

    @property
    def previous_service(self) -> str | None:
        return self._session.previous_service

    @property
    def group_changed(self) -> bool:
        return self._session.group_changed

    @property
    def service_changed(self) -> bool:
        return self._session.service_changed

    async def position(self, *, binary: bool | None = None) -> PppSolution:
        """Read one PPP solution through the receiver's transaction lock."""
        return await self.receiver._run(lambda: self._session.position(binary=binary))

    async def poll_positions(
        self,
        *,
        interval: float = 1.0,
        stop: asyncio.Event | None = None,
        on_message: Callable[[Message], None] | None = None,
    ) -> AsyncIterator[PppSolution]:
        """Poll solutions until stopped, cancelled or the iterator is closed.

        Other messages received during a query go to ``on_message`` or are
        discarded. Previously queued messages remain available to ``receive``.
        The callback runs in the worker thread and must not use the receiver.
        """
        validate_interval(interval)
        validate_callback(on_message)
        async for solution in poll_async(
            lambda: self.receiver._run(
                lambda: self._session._poll_position(on_message)
            ),
            interval,
            stop,
        ):
            yield solution
