from dataclasses import replace

import pytest

from conftest import FIXTURES, ascii_message
from test_protocol import binary as binary_frame
from um982py.commands import Log, Trigger
from um982py.commands import configuration as documented
from um982py.commands.extended import EXTENDED_LOGS
from um982py.errors import ProtocolError
from um982py.experimental import configuration as config
from um982py.experimental import remote_antenna_phase_center_offset
from um982py.messages import AsciiMessage, BinaryMessage, decode_log
from um982py.protocol import StreamDecoder

SENSITIVE = {
    Log.ALIGNBSLNENU,
    Log.ALIGNBSLNXYZ,
    Log.BESTGNSSPOS,
    Log.BESTPOS,
    Log.BESTPOS2,
    Log.BESTXYZ,
    Log.BSLNENUHD,
    Log.BSLNXYZHD,
    Log.MPSRPOS,
    Log.MPSRPOS2,
    Log.PSRPOS,
    Log.RANGE,
    Log.RANGEH,
    Log.RTKPOS,
}

AUDIT_LOGS = {
    Log.ALGRANGE,
    Log.BASESATS,
    Log.BBPPSMSG,
    Log.EVENTALL,
    Log.EVENTMARK,
    Log.HWSTATUSD,
    Log.JAMSTATUSD,
    Log.PVTSOL,
    Log.RTCSTATUSD,
    Log.RTCM1032,
    Log.SATINFO,
    Log.SATXYZ2,
    Log.SSR1CLOCK,
    Log.SSR1ORBIT,
}

FORMATS = [
    (log, binary)
    for log in Log
    for binary in (False, True)
    if (log.value in EXTENDED_LOGS or log == Log.RTKSTATUS2)
    and (not binary or log.definition.binary_command is not None)
    and log not in SENSITIVE | AUDIT_LOGS
    and not log.value.startswith("SBAS")
]


def captured(log: Log, binary: bool) -> AsciiMessage | BinaryMessage:
    folder = (
        "captures-extra"
        if log in (Log.RTKSTATUS2, Log.RTKSTATUSD, Log.RTKSTATUS2D)
        else "captures"
    )
    raw = (FIXTURES / folder / (log.wire_name(binary=binary) + ".bin")).read_bytes()
    return next(
        m
        for m in StreamDecoder(strict=True).feed(raw)
        if isinstance(m, (AsciiMessage, BinaryMessage))
    )


@pytest.mark.parametrize("log,binary", FORMATS)
def test_live_captures(log: Log, binary: bool) -> None:
    message = captured(log, binary)
    record = log.decode(message)
    assert record.name == log.value and record.message is message
    assert log.read(binary=binary).decode(message) == record
    if log in (Log.RANGE, Log.RANGEH):
        assert len(record.records("observations")) == record.integer("count")
        assert record.records("observations")[0].real("pseudorange") > 1_000_000
    if log == Log.HEADINGOFFSET:
        assert record.real("heading") == record.real("pitch") == 0
    if log == Log.HEADINGSTATUSD:
        assert record.real("cfglength") == 0
        assert record.real("cfgtol") == 5


@pytest.mark.parametrize("log,binary", FORMATS)
def test_truncated_and_extra_fields(log: Log, binary: bool) -> None:
    message = captured(log, binary)
    if isinstance(message, BinaryMessage):
        bad = [
            replace(message, payload=message.payload[:-1]),
            replace(message, payload=message.payload + b"\0"),
        ]
    else:
        fields = message.fields
        if log == Log.HEADINGOFFSET:
            fields = fields[:-1]
        bad = [
            replace(message, fields=fields[:-1]),
            replace(message, fields=(*fields, "extra")),
        ]
    for changed in bad:
        with pytest.raises(ProtocolError):
            log.decode(changed)


@pytest.mark.parametrize("log,message_id", [(Log.MPSRPOS, 3005), (Log.MPSRPOS2, 3006)])
@pytest.mark.parametrize("binary", [False, True])
def test_mpsrpos_position_layout(log: Log, message_id: int, binary: bool) -> None:
    position = captured(Log.BESTPOS, binary)
    expected = Log.BESTPOS.decode(position)
    if isinstance(position, BinaryMessage):
        raw = binary_frame(position.payload, message_id=message_id)
    else:
        raw = ascii_message(log.wire_name(), ",".join(position.fields))
    (frame,) = StreamDecoder(strict=True).feed(raw)
    query = log.read(binary=binary)
    assert query.matches(frame)
    assert query.decode(frame) == decode_log(frame)
    assert query.decode(frame).entries == expected.entries
    assert log.output(Trigger.ON_CHANGED, binary=binary).text == (
        f"{log.wire_name(binary=binary)} ONCHANGED"
    )
    with pytest.raises(ValueError, match="requires ONCHANGED"):
        log.output(1, binary=binary)


def test_gloclock_formats_agree_on_broadcast_parameters() -> None:
    ascii_record = Log.GLOCLOCK.decode(captured(Log.GLOCLOCK, False))
    binary_record = Log.GLOCLOCK.decode(captured(Log.GLOCLOCK, True))
    for field, expected in (
        ("satellite_type", 1),
        ("four_year_interval", 8),
        ("day_number", 1054),
        ("kp", 0),
        ("receiver_word", 3),
    ):
        assert ascii_record.integer(field) == binary_record.integer(field) == expected
    for field, expected in (
        ("tau_gps_s", 1.303851604e-8),
        ("tau_c_s", 1.396983862e-9),
        ("beta1", -0.076171875),
        ("beta2", -0.001800537109),
    ):
        assert ascii_record.real(field) == pytest.approx(expected, rel=1e-9, abs=0)
        assert binary_record.real(field) == pytest.approx(expected, rel=1e-9, abs=0)


def test_glonass_almanac_normalizes_time_and_signed_frequency() -> None:
    for binary in (False, True):
        record = Log.GLOALMANAC.decode(captured(Log.GLOALMANAC, binary))
        assert record.integer("satellite_id") == 39
        assert record.real("reference_tow_s") == 365897.0
        assert record.integer("frequency_channel") == -4


@pytest.mark.parametrize(
    ("log", "leap_seconds", "alpha0"),
    [(Log.IONUTC, 18, 1.955777406692505e-8), (Log.BD2IONUTC, 4, 3.166496753692627e-8)],
)
def test_combined_ionosphere_and_utc_parameters(
    log: Log, leap_seconds: int, alpha0: float
) -> None:
    for binary in (False, True):
        frame = captured(log, binary)
        assert log.decode(frame) == decode_log(frame)
        record = log.decode(frame)
        assert record.real("a0") == pytest.approx(alpha0, rel=1e-12, abs=0)
        assert record.integer("deltat_ls") == leap_seconds
        assert record.real("utc_a0") != record.real("a0")


def test_remote_antenna_offset_uses_north_east_up_millimetres() -> None:
    readback = Log.REMOTEANTENNAPCO.decode(captured(Log.REMOTEANTENNAPCO, False))
    args = tuple(readback.real(field) for field in ("north_mm", "east_mm", "up_mm"))
    assert args == (12.5, -25, 99.75)
    assert remote_antenna_phase_center_offset(*args).text == (
        "CONFIG REMOTEANTENNAPCO 12.5 -25 99.75"
    )
    for invalid in (1_000_001, -1_000_001, float("nan"), True):
        with pytest.raises(ValueError):
            remote_antenna_phase_center_offset(0, invalid, 0)


def test_hidden_configuration_grammar() -> None:
    assert documented.pvt_reliability(1, 2, 3).text == "CONFIG PVT RELIABILITY 1 2 3"
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
            documented.pvt_reliability(first, 1, 1)
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
