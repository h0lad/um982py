"""Recoverable NTRIP correction relay for a running receiver stream."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock
from time import monotonic
from typing import TYPE_CHECKING

from um982py.messages import RtcmMessage
from um982py.ntrip import ReconnectPolicy, retryable_ntrip_error
from um982py.protocol import StreamDecoder

if TYPE_CHECKING:
    from collections.abc import Callable

    from um982py.ntrip import NtripClient
    from um982py.streaming import ReceiverStream


class CorrectionWriteError(RuntimeError):
    """A correction could not be delivered to the receiver."""


class GgaProviderError(RuntimeError):
    """The application could not obtain its rover position."""


@dataclass(frozen=True, slots=True)
class RtkHealth:
    state: str
    connection_attempts: int
    reconnects: int
    frames_forwarded: int
    last_byte_monotonic: float | None
    last_correction_monotonic: float | None
    last_error: str | None


class RtkSession:
    """Relay RTCM until stopped, retrying transient caster failures.

    ``client_factory`` creates a fresh NtripClient for each attempt; set its
    initial GGA if the caster requires one during connection. ``gga_provider``
    returns a complete GPGGA sentence, or None while a fix is unavailable.
    Run the session in an application-owned thread. It leaves receiver settings
    unchanged and stops on authentication or TLS failures.
    """

    def __init__(
        self,
        stream: ReceiverStream,
        client_factory: Callable[[], NtripClient],
        *,
        gga_provider: Callable[[], bytes | None] | None = None,
        gga_interval: float = 10.0,
        read_interval: float = 1.0,
        correction_timeout: float = 60.0,
        reconnect: ReconnectPolicy | None = None,
    ) -> None:
        for value in (gga_interval, read_interval, correction_timeout):
            if not 0 < value < float("inf"):
                raise ValueError("intervals must be finite and positive")
        self.stream = stream
        self.client_factory = client_factory
        self.gga_provider = gga_provider
        self.gga_interval = gga_interval
        self.read_interval = min(read_interval, gga_interval, correction_timeout)
        self.correction_timeout = correction_timeout
        self.reconnect = reconnect or ReconnectPolicy()
        self._lock = Lock()
        self._state = "idle"
        self._attempts = 0
        self._connections = 0
        self._frames = 0
        self._last_byte: float | None = None
        self._last_correction: float | None = None
        self._error: str | None = None

    def health(self) -> RtkHealth:
        with self._lock:
            return RtkHealth(
                self._state,
                self._attempts,
                max(0, self._connections - 1),
                self._frames,
                self._last_byte,
                self._last_correction,
                self._error,
            )

    def run(self, stop: Event) -> None:
        """Run until stopped or a non-retryable error occurs.

        The terminal error is raised to the caller and reflected in ``health``.
        A stop may wait for an in-flight connect or receiver write to finish.
        """
        with self._lock:
            if self._state != "idle":
                raise RuntimeError("session can only be run once")
            self._state = "connecting"
        delay = self.reconnect.initial_seconds
        try:
            while not stop.is_set():
                with self._lock:
                    self._state = "connecting"
                    self._attempts += 1
                    frames_before = self._frames
                client = self.client_factory()
                try:
                    client.connect()
                    client.set_read_timeout(self.read_interval)
                    with self._lock:
                        self._state = "connected"
                        self._connections += 1
                    self._relay(client, stop)
                    if stop.is_set():
                        break
                except Exception as error:
                    with self._lock:
                        self._error = str(error)
                    if not retryable_ntrip_error(error):
                        raise
                    if self._frames > frames_before:
                        delay = self.reconnect.initial_seconds
                finally:
                    client.close()
                with self._lock:
                    self._state = "backoff"
                if stop.wait(delay):
                    break
                delay = self.reconnect.next_delay(delay)
        except Exception as error:
            with self._lock:
                self._state = "failed"
                self._error = str(error)
            raise
        else:
            with self._lock:
                self._state = "stopped"

    def _relay(self, client: NtripClient, stop: Event) -> None:
        decoder = StreamDecoder()
        now = monotonic()
        last_frame = now
        next_gga = now + self.gga_interval
        while not stop.is_set():
            now = monotonic()
            if self.gga_provider is not None and now >= next_gga:
                try:
                    sentence = self.gga_provider()
                except Exception as error:
                    raise GgaProviderError("GGA provider failed") from error
                if sentence is not None:
                    client.send_gga(sentence)
                next_gga = monotonic() + self.gga_interval
                if stop.is_set():
                    return
            try:
                data = client.read()
            except TimeoutError:
                data = None
            if data == b"":
                raise ConnectionError("caster closed the correction stream")
            if data:
                with self._lock:
                    self._last_byte = monotonic()
                for message in decoder.feed(data):
                    if isinstance(message, RtcmMessage):
                        try:
                            self.stream.send_correction(message).result()
                        except Exception as error:
                            raise CorrectionWriteError(
                                "receiver correction write failed"
                            ) from error
                        last_frame = monotonic()
                        with self._lock:
                            self._frames += 1
                            self._last_correction = last_frame
            if monotonic() - last_frame >= self.correction_timeout:
                raise ConnectionError("no RTCM corrections before timeout")
