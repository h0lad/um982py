from dataclasses import replace

import pytest

from conftest import FIXTURES, ReplayTransport
from test_extended_logs import captured
from um982py import Receiver
from um982py.errors import ProtocolError
from um982py.experimental import FirmwareLog
from um982py.messages import AsciiMessage, BinaryMessage
from um982py.protocol import StreamDecoder


def visibility_frames(binary: bool) -> list[AsciiMessage | BinaryMessage]:
    name = FirmwareLog.SATVIS2.wire_name(binary=binary)
    return [
        m
        for m in StreamDecoder(strict=True).feed(
            (FIXTURES / "captures" / (name + ".bin")).read_bytes()
        )
        if isinstance(m, (AsciiMessage, BinaryMessage))
    ]


@pytest.mark.parametrize("binary", [False, True])
def test_all_constellations_and_signed_glonass_channels(binary: bool) -> None:
    records = [FirmwareLog.SATVIS2.decode(m) for m in visibility_frames(binary)]
    assert len(records) == 7
    glonass = next(
        r for r in records if r["constellation"] == (1 if binary else "GLONASS")
    )
    channels = [sat.integer("channel") for sat in glonass.records("satellites")]
    assert min(channels) < 0 < max(channels)
    for record in records:
        assert len(record.records("satellites")) == record.integer("count")
    assert sum(r.integer("count") == 0 for r in records) == 3


def test_collect_keeps_satvis2_constellations_and_interleaved_output() -> None:
    frames = visibility_frames(False)
    other = captured(FirmwareLog.ANTENNA, False)
    raw = frames[0].raw + other.raw + b"".join(m.raw for m in frames[1:])
    with Receiver(ReplayTransport({b"SATVIS2A\r\n": raw})) as receiver:
        records = receiver.collect(FirmwareLog.SATVIS2.read(), quiet=0.001)
        assert len(records) == 7
        assert receiver.receive() == other


@pytest.mark.parametrize("binary", [False, True])
@pytest.mark.parametrize("log", [FirmwareLog.SATVIS, FirmwareLog.SATVIS2])
def test_visibility_rejects_bad_counts(log: FirmwareLog, binary: bool) -> None:
    message = captured(log, binary)
    offset = 12 if log == FirmwareLog.SATVIS2 else 8
    for value in (0, 241, 0xFFFFFFFF):
        if isinstance(message, BinaryMessage):
            changed = replace(
                message,
                payload=(
                    message.payload[:offset]
                    + value.to_bytes(4, "little")
                    + message.payload[offset + 4 :]
                ),
            )
        else:
            index = offset // 4
            changed = replace(
                message,
                fields=(
                    *message.fields[:index],
                    str(value),
                    *message.fields[index + 1 :],
                ),
            )
        with pytest.raises(ProtocolError):
            log.decode(changed)


@pytest.mark.parametrize("text", ["-1", "42abc", "42--2", "42-40000", "65536"])
def test_satvis2_satellite_id_validation(text: str) -> None:
    message = captured(FirmwareLog.SATVIS2, False)
    assert isinstance(message, AsciiMessage)
    changed = replace(message, fields=(*message.fields[:4], text, *message.fields[5:]))
    with pytest.raises(ProtocolError):
        FirmwareLog.SATVIS2.decode(changed)


@pytest.mark.parametrize("text", ["nan", "-1", "241", "4294967296"])
def test_satvis2_ascii_count_validation(text: str) -> None:
    message = captured(FirmwareLog.SATVIS2, False)
    assert isinstance(message, AsciiMessage)
    with pytest.raises(ProtocolError):
        FirmwareLog.SATVIS2.decode(
            replace(
                message,
                fields=(*message.fields[:3], text, *message.fields[4:]),
            )
        )


@pytest.mark.parametrize(
    "log",
    [
        FirmwareLog.PSRDOP,
        FirmwareLog.PSRDOP2,
        FirmwareLog.RTKDOP,
        FirmwareLog.RTKDOP2,
    ],
)
def test_dop_counts_and_empty_solutions(log: FirmwareLog) -> None:
    for binary in (False, True):
        record = log.decode(captured(log, binary))
        assert isinstance(record["sats_list"], tuple)
        assert len(record["sats_list"]) == record.integer("count_sats")
    message = captured(log, True)
    assert isinstance(message, BinaryMessage)
    for value in (81, 0xFFFFFFFF):
        with pytest.raises(ProtocolError):
            log.decode(
                replace(
                    message, payload=message.payload[:24] + value.to_bytes(4, "little")
                )
            )


def test_rtk_velocity_and_psr_velocity_have_different_final_field_types() -> None:
    for binary in (False, True):
        rtk = FirmwareLog.RTKVEL.decode(captured(FirmwareLog.RTKVEL, binary))
        psr = FirmwareLog.PSRVEL.decode(captured(FirmwareLog.PSRVEL, binary))
        assert isinstance(rtk["reserved"], float)
        assert isinstance(psr["reserved"], int)
