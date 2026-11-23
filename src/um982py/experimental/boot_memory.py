"""Receiver memory reads through the boot-menu helper protocol."""

import binascii
import struct
from pathlib import Path
from time import monotonic, sleep
from typing import Self

import serial

from um982py.errors import BootMenuError

__all__ = [
    "BootMemoryReader",
    "image_record",
    "sync_packet",
    "xmodem_packet",
]

BOOT_PROMPT = b"boot>"
"""Boot-menu prompt transmitted after every menu action."""

IDENTITY_MARKER = b";UM982,"
"""Identity fragment expected in a receiver version response."""

READY = b"UM982RAM1\r\n"
"""Banner transmitted by the resident helper after upload."""

READ_MARKER = b"URD1"
"""Prefix of every helper read response."""

HELPER_LOAD_ADDRESS = 0x200000
"""Load address of the helper image record."""

IMAGE_MAGIC = 0xA6A7A8A9
"""Image record magic of a downloadable application record."""

MAX_READ_LENGTH = 4096
"""Longest single memory read accepted by the helper."""

XMODEM_BLOCK = 128
"""XMODEM block size used for the helper upload."""

MENU_IDLE_TIMEOUT = 2.5
"""Seconds the boot menu waits before reprinting its prompt."""

ENTER_TIMEOUT = 30.0
"""Seconds to wait for the boot prompt after a reset request."""

TRANSFER_TIMEOUT = 10.0
"""Seconds to wait for a single upload or read response."""

APPLICATION_TIMEOUT = 8.0
"""Seconds to wait for the application after the final reset."""

SYNC_REPETITIONS: dict[int, int] = {115200: 2, 921600: 16}
"""Reset synchronisation word repetitions per baud rate."""


def sync_packet(baud: int) -> bytes:
    """Return the reset synchronisation word train for ``baud``."""
    return b"T@T@" * SYNC_REPETITIONS.get(baud, 8)


def image_record(payload: bytes, load_address: int = HELPER_LOAD_ADDRESS) -> bytes:
    """The 32-byte little-endian header carries the record magic, the load
    address, the payload length and a word sum. Its CRC-16/XMODEM protects the
    first 28 header bytes. The payload is padded to a word boundary.
    """
    payload = payload + b"\0" * (-len(payload) % 4)
    checksum = sum(struct.unpack(f"<{len(payload) // 4}I", payload)) & 0xFFFFFFFF
    header = struct.pack(
        "<7I", IMAGE_MAGIC, 0, load_address, len(payload), 0, 0, checksum
    )
    return header + struct.pack("<HH", binascii.crc_hqx(header, 0), 0) + payload


def xmodem_packet(number: int, block: bytes) -> bytes:
    if len(block) != XMODEM_BLOCK:
        raise ValueError(f"XMODEM block must contain {XMODEM_BLOCK} bytes")
    return (
        bytes((0x01, number & 0xFF, 0xFF - (number & 0xFF)))
        + block
        + struct.pack(">H", binascii.crc_hqx(block, 0))
    )


class _Wire:
    """Serial line bookkeeping for one boot-menu session."""

    def __init__(self, port: serial.SerialBase) -> None:
        self.port = port
        self.pending = bytearray()

    def send(self, data: bytes) -> None:
        self.port.write(data)

    def _fill(self, deadline: float) -> None:
        while monotonic() < deadline:
            data = self.port.read(65536)
            if data:
                self.pending.extend(data)
                return
        raise BootMenuError("Serial receive timeout")

    def exact(self, count: int, timeout: float = TRANSFER_TIMEOUT) -> bytes:
        """Return the next ``count`` bytes, waiting up to ``timeout``."""
        deadline = monotonic() + timeout
        while len(self.pending) < count:
            self._fill(deadline)
        data = bytes(self.pending[:count])
        del self.pending[:count]
        return data

    def until(self, marker: bytes, timeout: float = TRANSFER_TIMEOUT) -> bytes:
        """Return everything up to and including ``marker``."""
        deadline = monotonic() + timeout
        while marker not in self.pending:
            self._fill(deadline)
        end = self.pending.index(marker) + len(marker)
        data = bytes(self.pending[:end])
        del self.pending[:end]
        return data


class BootMemoryReader:
    """Read receiver memory through the boot-menu helper.

    The boot menu accepts a small helper image over UART. While the helper is
    resident it answers read requests for receiver memory, including the
    window that holds per-signal tracking state. The session is read-only:
    no flash write or erase is requested at any stage, and the final helper
    reset restarts the application from flash.

    Use :meth:`connect` as a context manager. Entering the boot menu pauses
    the running application, so leave the context promptly to let the
    receiver return to navigation.
    """

    def __init__(self, wire: _Wire, port: serial.SerialBase) -> None:
        self._wire = wire
        self._port = port
        self.application_restored: bool | None = None
        """Whether the application responded after the final reset."""

    @classmethod
    def connect(
        cls,
        port: str,
        baud: int = 921600,
        *,
        helper: Path,
        boot_menu_only: bool = False,
    ) -> Self:
        """Open ``port``, enter the boot menu and upload ``helper``.

        With ``boot_menu_only``, wait for an existing boot prompt without
        sending application commands to enter the menu.
        The returned reader holds the serial port and must be closed with
        :meth:`close` to reset the receiver back into the application.
        """
        payload = helper.read_bytes()
        handle = serial.Serial(port, baud, timeout=0.01, write_timeout=2)
        reader = cls.__new__(cls)
        reader._port = handle
        reader._wire = _Wire(handle)
        reader.application_restored = None
        try:
            if boot_menu_only:
                reader._receive_boot_prompt(2 * MENU_IDLE_TIMEOUT)
            else:
                reader._enter_boot_menu(baud)
            reader._upload(payload)
        except BootMenuError:
            handle.close()
            raise
        return reader

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _receive_boot_prompt(self, timeout: float, *, sync: bool = False) -> bytes:
        deadline = monotonic() + timeout
        data = bytearray()
        while monotonic() < deadline:
            if sync:
                self._wire.send(sync_packet(921600))
                sleep(0.005)
            chunk = self._port.read(65536)
            if chunk:
                data.extend(chunk)
                if BOOT_PROMPT in data:
                    self._wire.pending.extend(data)
                    return bytes(data)
        self._wire.pending.extend(data)
        raise BootMenuError("No boot-menu prompt before timeout")

    def _enter_boot_menu(self, baud: int, *, timeout: float = ENTER_TIMEOUT) -> None:
        del baud
        data = self._port.read(65536)
        if BOOT_PROMPT in data:
            self._wire.pending.extend(data)
            return
        self._wire.send(b"\r\nVERSION\r\n")
        identity = self._port.read(65536)
        deadline = monotonic() + 2.0
        while IDENTITY_MARKER not in identity and monotonic() < deadline:
            identity += self._port.read(65536)
        if BOOT_PROMPT in identity:
            self._wire.pending.extend(data + identity)
            return
        if IDENTITY_MARKER not in identity:
            raise BootMenuError(
                "Receiver identity missing; no reset was requested. Close other "
                "serial clients and retry, or reset the receiver physically."
            )
        self._wire.send(b"\r\nreset\r\nreset\r\n")
        self._receive_boot_prompt(timeout, sync=True)
        self._wire.send(b"\r\n")
        self._wire.until(BOOT_PROMPT, MENU_IDLE_TIMEOUT)

    def _upload(self, payload: bytes) -> None:
        record = image_record(payload)
        record += b"\x1a" * (-len(record) % XMODEM_BLOCK)
        self._wire.send(b"3\r")
        self._wire.until(b"## Ready for binary (xmodem)")
        self._wire.until(b"C")
        for index in range(0, len(record), XMODEM_BLOCK):
            packet = xmodem_packet(
                index // XMODEM_BLOCK + 1, record[index : index + XMODEM_BLOCK]
            )
            for _ in range(3):
                self._wire.send(packet)
                answer = self._wire.exact(1)
                if answer == b"\x06":
                    break
                if answer != b"\x15":
                    raise BootMenuError(f"Unexpected XMODEM response: {answer.hex()}")
            else:
                raise BootMenuError("XMODEM packet rejected three times")
        self._wire.send(b"\x04")
        if self._wire.exact(1) != b"\x06":
            raise BootMenuError("XMODEM transfer end not acknowledged")
        self._wire.until(READY)

    def read(self, address: int, length: int) -> bytes:
        """Read ``length`` bytes of receiver memory at ``address``.

        Requests are split into chunks accepted by the helper. Every response
        repeats the requested range and a word sum over the returned bytes.
        """
        if not 0 < length <= MAX_READ_LENGTH:
            raise ValueError(f"Read length must be 1..{MAX_READ_LENGTH}")
        self._wire.send(b"M" + struct.pack("<II", address, length))
        self._wire.until(READ_MARKER)
        returned_address, returned_length = struct.unpack("<II", self._wire.exact(8))
        if (returned_address, returned_length) != (address, length):
            raise BootMenuError(
                f"Wrong returned range: {returned_address:#x}, {returned_length}"
            )
        data = self._wire.exact(length)
        checksum = struct.unpack("<I", self._wire.exact(4))[0]
        if sum(data) & 0xFFFFFFFF != checksum:
            raise BootMenuError(f"Read checksum mismatch at {address:#x}")
        return data

    def read_range(self, address: int, length: int) -> bytes:
        result = bytearray()
        for offset in range(0, length, MAX_READ_LENGTH):
            chunk = min(MAX_READ_LENGTH, length - offset)
            result += self.read(address + offset, chunk)
        return bytes(result)

    def close(self) -> None:
        """Reset the receiver and verify that the application returns."""
        try:
            self._wire.send(b"Q")
            deadline = monotonic() + APPLICATION_TIMEOUT
            data = bytearray()
            while monotonic() < deadline:
                data += self._port.read(65536)
                if b"$GN" in data or b"$GP" in data or b"#VERSION" in data:
                    break
            self._wire.send(b"\r\nVERSION\r\n")
            deadline = monotonic() + 3.0
            while monotonic() < deadline:
                data += self._port.read(65536)
                if IDENTITY_MARKER in data:
                    self.application_restored = True
                    break
            else:
                self.application_restored = False
        finally:
            self._port.close()
