"""Tests the annotated navigation-message hex dump against ground truth."""

from __future__ import annotations

from pathlib import Path

import pytest
from examples.navigation_message_hex import (
    FieldHex,
    annotate,
    families,
    field_span,
    hex_bytes,
    message_hex,
    render_text,
    satellite_of,
)
from examples.navigation_message_hex import __main__ as cli

from conftest import SubscriptionTransport, sentence
from um982py import Receiver
from um982py.commands import Log, Trigger
from um982py.commands.types import Port
from um982py.messages import BinaryMessage
from um982py.protocol import StreamDecoder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "captures-live"

CAPTURED = ("GPS", "GALILEO", "BEIDOU", "GLONASS")


def decode_family(log_name: str) -> list[tuple[BinaryMessage, object]]:
    """Every binary frame of an ephemeris log with its decoded record."""
    path = FIXTURES / f"{log_name}B.bin"
    if not path.is_file():
        return []
    log = Log[log_name]
    request = log.request(binary=True)
    return [
        (message, log.decode(message))
        for message in StreamDecoder().feed(path.read_bytes())
        if isinstance(message, BinaryMessage) and request.matches(message)
    ]


def test_every_family_has_a_layout() -> None:
    names = [log for _, log in families()]
    assert names == [
        "GPSEPH",
        "GALEPH",
        "BDSEPH",
        "BD3EPH",
        "GLOEPH",
        "QZSSEPH",
        "IRNSSEPH",
    ]


@pytest.mark.parametrize("constellation", CAPTURED)
def test_captured_family_messages_are_annotated(constellation: str) -> None:
    log_name = dict(families())[constellation]
    frames = decode_family(log_name)
    assert frames, f"no {log_name}B frames captured"
    message, record = frames[0]
    view = message_hex(
        constellation, log_name, message.header.message_id, message.payload, record
    )
    assert view.constellation == constellation
    assert view.satellite == satellite_of(record)  # type: ignore[arg-type]
    assert view.fields


@pytest.mark.parametrize("constellation", CAPTURED)
def test_annotated_bytes_match_the_payload(constellation: str) -> None:
    log_name = dict(families())[constellation]
    message, record = decode_family(log_name)[0]
    view = message_hex(
        constellation, log_name, message.header.message_id, message.payload, record
    )
    for field in view.fields:
        assert field.raw == message.payload[field.offset : field.end]
        assert bytes.fromhex(field.hex) == field.raw


@pytest.mark.parametrize("constellation", CAPTURED)
def test_reparsing_an_annotated_span_returns_the_same_value(
    constellation: str,
) -> None:
    log_name = dict(families())[constellation]
    message, record = decode_family(log_name)[0]
    view = message_hex(
        constellation, log_name, message.header.message_id, message.payload, record
    )
    offset, _ = field_span(log_name, view.fields[0].name)
    assert view.fields[0].offset == offset
    assert view.fields[0].value == record[view.fields[0].name]  # type: ignore[index]


def test_satellite_identifier_sits_at_the_first_field() -> None:
    offset, size = field_span("GPSEPH", "prn")
    assert (offset, size) == (0, 4)
    offset, size = field_span("GLOEPH", "sloto")
    assert (offset, size) == (0, 2)


@pytest.mark.parametrize("constellation", CAPTURED)
def test_every_payload_byte_is_covered_exactly_once(constellation: str) -> None:
    log_name = dict(families())[constellation]
    message, record = decode_family(log_name)[0]
    view = message_hex(
        constellation, log_name, message.header.message_id, message.payload, record
    )
    cursor = 0
    for field in view.fields:
        assert field.offset == cursor, f"gap or overlap at {cursor} in {log_name}"
        cursor = field.end
    assert cursor == len(message.payload)
    assert sum(field.size for field in view.fields) == len(message.payload)


def test_reserved_fields_are_flagged(constellation: str = "GLONASS") -> None:
    log_name = dict(families())[constellation]
    message, record = decode_family(log_name)[0]
    view = message_hex(
        constellation, log_name, message.header.message_id, message.payload, record
    )
    reserved = [field for field in view.fields if field.reserved]
    assert reserved, "GLOEPH carries reserved fields"
    assert all(
        field.name.startswith(("reserved", "field_", "unnamed")) for field in reserved
    )
    assert sum(field.size for field in reserved) > 0


def test_unknown_log_marks_every_field_neutral() -> None:
    raw = (FIXTURES.parent / "captures" / "ENVINFOB.bin").read_bytes()
    log = Log.ENVINFO if "ENVINFO" in Log.__members__ else None
    assert log is None
    from um982py.experimental import FirmwareLog

    request = FirmwareLog.ENVINFO.request(binary=True)
    message = next(
        m
        for m in StreamDecoder().feed(raw)
        if isinstance(m, BinaryMessage) and request.matches(m)
    )
    record = FirmwareLog.ENVINFO.decode(message)
    view = message_hex(
        "ENVINFO", "ENVINFO", message.header.message_id, message.payload, record
    )
    assert view.satellite is None
    assert view.fields
    assert all(field.reserved for field in view.fields)
    assert sum(field.size for field in view.fields) == len(message.payload)


def test_payload_is_recovered_by_concatenating_the_spans() -> None:
    log_name = "GPSEPH"
    message, record = decode_family(log_name)[0]
    view = message_hex(
        "GPS", log_name, message.header.message_id, message.payload, record
    )
    rebuilt = b"".join(field.raw for field in view.fields)
    assert rebuilt == message.payload


def test_message_count_per_family_matches_the_capture() -> None:
    for constellation in CAPTURED:
        log_name = dict(families())[constellation]
        assert len(decode_family(log_name)) > 0


def test_hex_bytes_grouping() -> None:
    assert hex_bytes(b"\x01\x02\x03") == ("01 02 03",)
    assert hex_bytes(b"\x01\x02\x03\x04", width=2) == ("01 02", "03 04")
    assert hex_bytes(b"", width=4) == ()
    with pytest.raises(ValueError, match="width"):
        hex_bytes(b"\x00", width=0)


def test_render_text_contains_table_and_dump() -> None:
    log_name = "GLOEPH"
    message, record = decode_family(log_name)[0]
    view = message_hex(
        "GLONASS", log_name, message.header.message_id, message.payload, record
    )
    text = render_text(view, width=16)
    assert "GLONASS GLOEPH" in text
    assert "offset size" in text
    assert "000000  " in text
    assert str(len(view.payload)) in text


def test_field_hex_rejects_nothing_and_exposes_span() -> None:
    field = FieldHex("prn", 0, 4, b"\x05\0\0\0", 5)
    assert field.hex == "05000000"
    assert field.end == 4


def test_annotate_skips_truncated_payloads() -> None:
    log_name = "GPSEPH"
    message, record = decode_family(log_name)[0]
    truncated = message.payload[:16]
    annotated = annotate(log_name, truncated, record)  # type: ignore[arg-type]
    assert all(field.end <= len(truncated) for field in annotated)
    assert len(annotated) < len(annotate(log_name, message.payload, record))  # type: ignore[arg-type]


@pytest.mark.parametrize("fallback", [False, True])
def test_collection_waits_through_quiet_and_keeps_interleaved_families(
    monkeypatch: pytest.MonkeyPatch, fallback: bool
) -> None:
    clock = [0.0]
    frames = decode_family("GPSEPH")[:1] + decode_family("GALEPH")[:1]
    wire = sentence(b"GPGGA,1") + b"".join(message.raw for message, _ in frames)

    class TimedTransport(SubscriptionTransport):
        emitted = False

        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending:
                clock[0] += timeout
                if clock[0] >= 0.75 and not self.emitted:
                    self.pending.extend(wire)
                    self.emitted = True
            return super().read(size, timeout)

    monkeypatch.setattr(cli, "monotonic", lambda: clock[0])
    monkeypatch.setattr("um982py.receiver.monotonic", lambda: clock[0])
    transport = TimedTransport()
    transport.subscriptions = {
        ("GPSEPHB", Port.COM1): 10.0,
        ("GPSEPHB", Port.COM2): Trigger.ON_CHANGED,
    }
    before = transport.subscriptions.copy()
    if fallback:
        transport.rejected.add("GPSEPHB ONCHANGED")
    with Receiver(transport) as receiver:
        views = cli.collect(receiver, 1.5, ["GPS", "GALILEO"])
    assert [view.constellation for view in views] == ["GPS", "GALILEO"]
    assert [view.payload for view in views] == [
        message.payload for message, _ in frames
    ]
    assert clock[0] == pytest.approx(1.5)
    assert transport.subscriptions == before
    if fallback:
        assert b"GPSEPHB 1\r\n" in transport.writes


def test_replay_keeps_all_matching_families_in_wire_order() -> None:
    frames = [
        decode_family("GALEPH")[0][0],
        decode_family("GPSEPH")[0][0],
        decode_family("GLOEPH")[0][0],
    ]
    views = cli.replay(frames, [])
    assert [view.constellation for view in views] == ["GALILEO", "GPS", "GLONASS"]
    assert [view.payload for view in views] == [frame.payload for frame in frames]
    assert [view.constellation for view in cli.replay(frames, ["GPS"])] == ["GPS"]


def test_replay_cli_uses_no_receiver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    def no_receiver(*args: object) -> None:
        pytest.fail("replay must not open a receiver")

    monkeypatch.setattr(cli, "open_receiver", no_receiver)
    output = tmp_path / "messages.json"
    assert (
        cli.main(["--replay", str(FIXTURES / "GPSEPHB.bin"), "--json", str(output)])
        == 0
    )
    report = json.loads(output.read_text())
    assert len(report["messages"]) == len(decode_family("GPSEPH"))
    assert {message["constellation"] for message in report["messages"]} == {"GPS"}
    assert "GPS GPSEPH" in capsys.readouterr().out


@pytest.mark.parametrize(
    "arguments",
    [
        ["--seconds", "0"],
        ["--seconds", "nan"],
        ["--family", "unknown"],
        ["--log", "unknown"],
        ["--log", "GPGGA"],
    ],
)
def test_cli_validates_before_opening_receiver(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    def no_receiver(*args: object) -> None:
        pytest.fail("invalid arguments must not open a receiver")

    monkeypatch.setattr(cli, "open_receiver", no_receiver)
    with pytest.raises(SystemExit) as caught:
        cli.main(arguments)
    assert caught.value.code == 2


def test_duplicate_log_selection_does_not_duplicate_frames() -> None:
    frame = decode_family("GPSEPH")[0][0]
    assert len(cli.replay([frame], ["GPS"], ["GPSEPH", "GPSEPH"])) == 1
