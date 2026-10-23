from pathlib import Path

import pytest

from um982py.experimental import FirmwareLog
from um982py.messages import AsciiMessage, BinaryMessage
from um982py.protocol import StreamDecoder

FIXTURES = Path(__file__).parent / "fixtures" / "captures"


def message(wire_name: str, binary: bool) -> AsciiMessage | BinaryMessage:
    raw = (FIXTURES / (wire_name + ".bin")).read_bytes()
    wanted = BinaryMessage if binary else AsciiMessage
    messages = StreamDecoder(strict=True).feed(raw)
    return next(m for m in messages if isinstance(m, wanted))


def decoded(log: FirmwareLog, binary: bool) -> dict:
    return dict(log.decode(message(log.wire_name(binary=binary), binary)).entries)


def test_bestsats_fields() -> None:
    body = decoded(FirmwareLog.BESTSATS, False)
    binary = decoded(FirmwareLog.BESTSATS, True)
    assert body["count"] == binary["count"] == 10
    first = body["satellites"][0]
    assert first["system"] == "GPS"
    assert dict(first["satellite"].entries) == {"prn": 15, "channel": 0}
    assert first["state"] == "GOOD"
    assert first["flags"] == 3
    glonass = body["satellites"][3]
    assert glonass["system"] == "GLONASS"
    assert dict(glonass["satellite"].entries) == {"prn": 44, "channel": 12}
    assert binary["satellites"][3]["flags"] == 3
    assert binary["satellites"][0]["system"] == 0
    assert binary["satellites"][6]["system"] == 5
    assert binary["satellites"][7]["system"] == 6
    assert len(binary["satellites"]) == 10


def test_aligndop_fields() -> None:
    body = decoded(FirmwareLog.ALIGNDOP, False)
    binary = decoded(FirmwareLog.ALIGNDOP, True)
    assert body["gdop"] == pytest.approx(12.2004, abs=1e-4)
    assert body["elev_mask"] == pytest.approx(2.0)
    assert body["count_sats"] == binary["count_sats"] == 8
    assert len(body["sats_list"]) == len(binary["sats_list"]) == 8
    assert binary["gdop"] == pytest.approx(12.2003, abs=1e-3)


def test_antenna_group_layouts() -> None:
    first = decoded(FirmwareLog.ANT1GROUP, False)
    second = decoded(FirmwareLog.ANT2GROUP, False)
    first_binary = decoded(FirmwareLog.ANT1GROUP, True)
    second_binary = decoded(FirmwareLog.ANT2GROUP, True)
    assert (first["field_01"], first["count"]) == (3, 5)
    assert (second["field_01"], second["count"]) == (6, 4)
    assert first["groups"][0]["system"] == "GP"
    assert first["groups"][0]["mask"] == 0x1D
    assert second["groups"][0]["mask"] == 0x0D
    assert first_binary["count"] == 5
    assert second_binary["count"] == 4
    assert len(first["groups"]) == len(first_binary["groups"]) == 5
    assert len(second["groups"]) == len(second_binary["groups"]) == 4
