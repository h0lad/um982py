from dataclasses import replace

import pytest

from conftest import FIXTURES
from um982py.errors import ProtocolError
from um982py.experimental import FirmwareLog
from um982py.experimental import configuration as config
from um982py.messages import AsciiMessage, BinaryMessage
from um982py.protocol import StreamDecoder

SENSITIVE = {
    FirmwareLog.ALIGNBSLNENU,
    FirmwareLog.ALIGNBSLNXYZ,
    FirmwareLog.BESTGNSSPOS,
    FirmwareLog.BESTPOS,
    FirmwareLog.BESTPOS2,
    FirmwareLog.BESTXYZ,
    FirmwareLog.BSLNENUHD,
    FirmwareLog.BSLNXYZHD,
    FirmwareLog.PSRPOS,
    FirmwareLog.RANGE,
    FirmwareLog.RANGEH,
    FirmwareLog.RTKPOS,
}

FORMATS = [
    (log, binary)
    for log in FirmwareLog
    for binary in (False, True)
    if (log != FirmwareLog.RXSTATUS or not binary) and log not in SENSITIVE
]


def captured(log: FirmwareLog, binary: bool) -> AsciiMessage | BinaryMessage:
    folder = (
        "captures-extra"
        if log
        in (FirmwareLog.RTKSTATUS2, FirmwareLog.RTKSTATUSD, FirmwareLog.RTKSTATUS2D)
        else "captures"
    )
    raw = (FIXTURES / folder / (log.wire_name(binary=binary) + ".bin")).read_bytes()
    return next(
        m
        for m in StreamDecoder(strict=True).feed(raw)
        if isinstance(m, (AsciiMessage, BinaryMessage))
    )


@pytest.mark.parametrize("log,binary", FORMATS)
def test_live_captures(log: FirmwareLog, binary: bool) -> None:
    message = captured(log, binary)
    record = log.decode(message)
    assert record.name == log.value and record.message is message
    assert log.read(binary=binary).decode(message) == record
    if log in (FirmwareLog.RANGE, FirmwareLog.RANGEH):
        assert len(record.records("observations")) == record.integer("count")
        assert record.records("observations")[0].real("pseudorange") > 1_000_000
    if log == FirmwareLog.HEADINGOFFSET:
        assert record.real("heading") == record.real("pitch") == 0


@pytest.mark.parametrize("log,binary", FORMATS)
def test_truncated_and_extra_fields(log: FirmwareLog, binary: bool) -> None:
    message = captured(log, binary)
    if isinstance(message, BinaryMessage):
        bad = [
            replace(message, payload=message.payload[:-1]),
            replace(message, payload=message.payload + b"\0"),
        ]
    else:
        fields = message.fields
        if log == FirmwareLog.HEADINGOFFSET:
            fields = fields[:-1]
        bad = [
            replace(message, fields=fields[:-1]),
            replace(message, fields=(*fields, "extra")),
        ]
    for changed in bad:
        with pytest.raises(ProtocolError):
            log.decode(changed)


def test_hidden_configuration_grammar() -> None:
    assert config.pvt_reliability(1, 2, 3).text == "CONFIG PVT RELIABILITY 1 2 3"
    assert config.best_position_bias().text == "CONFIG BESTPOSBIAS ENABLE"
    assert config.best_position_bias(enabled=False).text == "CONFIG BESTPOSBIAS DISABLE"
    assert config.best_position_bias(threshold=30000).text.endswith("ENABLE 30000")
    assert config.leap_seconds().text == "CONFIG LEAPSECOND DISABLE"
    assert config.leap_seconds(18).text == "CONFIG LEAPSECOND ENABLE 18"
    assert config.base_type("nov").text == "CONFIG BASETYPE NOV"
    assert config.rtk_elevation_mask().text == "CONFIG RTKELEVMASK AUTO"
    assert config.rtk_elevation_mask(0, secondary=45.5, third=90).text.endswith(
        "0 45.5 90"
    )
    for first in (0, 4, True):
        with pytest.raises(ValueError):
            config.pvt_reliability(first, 1, 1)
    for threshold in (199, 30001, True):
        with pytest.raises(ValueError):
            config.best_position_bias(threshold=threshold)
    for seconds in (-1, 65, True):
        with pytest.raises(ValueError):
            config.leap_seconds(seconds)
    with pytest.raises(ValueError):
        config.best_position_bias(enabled=False, threshold=200)
    with pytest.raises(ValueError):
        config.base_type("UNKNOWN")
    with pytest.raises(ValueError):
        config.rtk_elevation_mask(20, secondary=30)
    with pytest.raises(ValueError):
        config.rtk_elevation_mask(91)
