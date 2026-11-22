import binascii
import struct
from pathlib import Path

import pytest

from um982py.errors import BootMenuError, TransportError
from um982py.experimental import (
    BootMemoryReader,
    image_record,
    sync_packet,
    xmodem_packet,
)
from um982py.experimental.boot_memory import _Wire


def test_sync_packet_scales_with_baud() -> None:
    assert sync_packet(115200) == b"T@T@" * 2
    assert sync_packet(921600) == b"T@T@" * 16
    assert sync_packet(460800) == b"T@T@" * 8


def test_image_record_round_trips_payload() -> None:
    payload = bytes(range(64))
    record = image_record(payload)
    assert len(record) == 32 + len(payload)
    words = [int.from_bytes(record[i : i + 4], "little") for i in range(0, 28, 4)]
    assert words[0] == 0xA6A7A8A9
    assert words[2] == 0x200000
    assert words[3] == len(payload)
    word_sum = sum(struct.unpack(f"<{len(payload) // 4}I", payload)) & 0xFFFFFFFF
    assert words[6] == word_sum
    header_crc = int.from_bytes(record[28:30], "little")
    assert header_crc == binascii.crc_hqx(record[:28], 0)


def test_image_record_pads_to_word_boundary() -> None:
    record = image_record(b"\x01")
    assert len(record) % 4 == 0
    assert record[32:] == b"\x01\x00\x00\x00"


def test_xmodem_packet_frames_block_with_crc() -> None:
    block = bytes(128)
    packet = xmodem_packet(7, block)
    assert packet[:3] == b"\x01\x07\xf8"
    assert packet[3 + 128 :] == binascii.crc_hqx(block, 0).to_bytes(2, "big")


def test_xmodem_packet_rejects_short_block() -> None:
    with pytest.raises(ValueError, match="128 bytes"):
        xmodem_packet(1, bytes(64))


def test_boot_menu_error_is_a_transport_error() -> None:
    assert issubclass(BootMenuError, TransportError)


class _FakePort:
    """Scripted serial port returning queued response blocks."""

    def __init__(self, responses: list[bytes]) -> None:
        self.responses = list(responses)
        self.pending = bytearray()
        self.writes: list[bytes] = []

    def read(self, size: int) -> bytes:
        while not self.pending and self.responses:
            self.pending.extend(self.responses.pop(0))
        data = bytes(self.pending[:size])
        del self.pending[:size]
        return data

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def close(self) -> None:
        return None


def _reader_with(responses: list[bytes]) -> BootMemoryReader:
    reader = BootMemoryReader.__new__(BootMemoryReader)
    reader._wire = _Wire(_FakePort(responses))
    reader._port = None
    reader.application_restored = None
    return reader


def test_connect_at_existing_boot_menu(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    helper = tmp_path / "reader.bin"
    helper.write_bytes(b"test")
    port = _FakePort(
        [
            b"",
            b"boot>",
            b"## Ready for binary (xmodem)\r\nC",
            b"\x06",
            b"\x06UM982RAM1\r\n",
            b"$GNGGA",
            b"#VERSION;UM982,",
        ]
    )
    monkeypatch.setattr("serial.Serial", lambda *_args, **_kwargs: port)
    with BootMemoryReader.connect(
        "serial", helper=helper, boot_menu_only=True
    ) as reader:
        assert port.writes[0] == b"3\r"
        assert len(port.writes) == 3
        assert port.writes[-1] == b"\x04"
    assert port.writes[3:] == [b"Q", b"\r\nVERSION\r\n"]
    assert reader.application_restored is True


def _read_response(address: int, payload: bytes, *, echo: bool = True) -> bytes:
    return (
        b"noise-URD1"
        + (address if echo else 0x999999).to_bytes(4, "little")
        + len(payload).to_bytes(4, "little")
        + payload
        + (sum(payload) & 0xFFFFFFFF).to_bytes(4, "little")
    )


def test_read_returns_payload_of_verified_response() -> None:
    payload = b"\x10\x20\x30\x40"
    reader = _reader_with([_read_response(0x400000, payload)])
    assert reader.read(0x400000, len(payload)) == payload


def test_read_rejects_mismatched_range_echo() -> None:
    payload = b"\x10\x20\x30\x40"
    reader = _reader_with([_read_response(0x400000, payload, echo=False)])
    with pytest.raises(BootMenuError, match="returned range"):
        reader.read(0x400000, len(payload))


def test_read_rejects_checksum_mismatch() -> None:
    payload = b"\x10\x20\x30\x40"
    response = (
        b"URD1"
        + (0x400000).to_bytes(4, "little")
        + len(payload).to_bytes(4, "little")
        + payload
        + (0).to_bytes(4, "little")
    )
    reader = _reader_with([response])
    with pytest.raises(BootMenuError, match="checksum mismatch"):
        reader.read(0x400000, len(payload))


def test_read_rejects_out_of_range_length() -> None:
    reader = _reader_with([])
    with pytest.raises(ValueError, match="Read length"):
        reader.read(0x400000, 0)
    with pytest.raises(ValueError, match="Read length"):
        reader.read(0x400000, 4097)
