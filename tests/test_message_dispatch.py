"""All frame consumers share log identification and ambiguity handling."""

from dataclasses import replace
from struct import pack_into

import pytest
from examples.telemetry_bridge import frame_from

from conftest import sentence
from test_bodies import binary_message, manual_message
from test_extended_logs import captured
from test_protocol import binary
from um982py import decode_message
from um982py.commands import Log
from um982py.dsp import decode_dsp
from um982py.errors import ProtocolError
from um982py.messages import (
    AsciiMessage,
    BestNavigation,
    BinaryMessage,
    Fix,
    Heading,
    Version,
    decode_log,
)
from um982py.protocol import StreamDecoder
from um982py.protocol.ascii import parse_ascii


@pytest.mark.parametrize("binary_format", [False, True])
def test_extended_range_uses_the_same_dispatcher(binary_format: bool) -> None:
    frame = captured(Log.RANGE, binary_format)
    record = decode_log(frame)
    assert record == Log.RANGE.decode(frame)
    assert record.name == "RANGE"
    assert record.records("observations")
    telemetry = frame_from(frame)
    assert telemetry.name in ("RANGE", "RANGEA")
    assert telemetry.record == record
    assert decode_message(frame.raw).entries == record.entries


@pytest.mark.parametrize(
    "identifier,names",
    [(42, ("BESTPOS", "BESTPOS2")), (99, ("BESTVEL", "BESTGNSSVEL", "BESTVEL2"))],
)
def test_ambiguous_binary_ids_require_an_explicit_log(
    identifier: int, names: tuple[str, ...]
) -> None:
    size = 72 if identifier == 42 else 44
    (frame,) = StreamDecoder(strict=True).feed(binary(bytes(size), identifier))
    assert isinstance(frame, BinaryMessage)
    with pytest.raises(ProtocolError, match="Ambiguous"):
        decode_log(frame)
    with pytest.raises(ProtocolError, match="Ambiguous"):
        decode_dsp(frame)
    assert frame_from(frame).record is None
    for name in names:
        log = Log[name]
        assert decode_log(frame, log=log).name == name
        assert log.decode(frame).name == name
        assert decode_message(frame.raw, log=log).name == name


def test_dsp_retains_unknown_binary_payload_as_opaque() -> None:
    (frame,) = StreamDecoder(strict=True).feed(binary(b"unknown", 65500))
    record = decode_dsp(frame)
    assert record.name == "OPAQUE"
    assert record["message_id"] == 65500
    assert record["payload"] == b"unknown"


def test_navigation_and_version_models_use_decoded_records() -> None:
    for name, model in (("BESTNAVA", BestNavigation), ("VERSIONA", Version)):
        frame = manual_message(name)
        assert model.from_message(frame) == model.from_record(decode_log(frame))


@pytest.mark.parametrize(
    "body,model",
    [
        (b"GNGGA,120001,4807.038,N,01131.000,E,4,12,0.7,545.4,M,46.9,M,0.5,0123", Fix),
        (b"GPTHS,123.4,A", Heading),
    ],
)
def test_nmea_models_use_decoded_records(
    body: bytes, model: type[Fix] | type[Heading]
) -> None:
    frame = parse_ascii(sentence(body))
    assert model.from_message(frame) == model.from_record(decode_log(frame))


def test_nmea_heading_range_is_validated_by_both_paths() -> None:
    frame = parse_ascii(sentence(b"GPTHS,361,A"))
    with pytest.raises(ProtocolError, match="THS"):
        decode_log(frame)
    with pytest.raises(ProtocolError, match="THS"):
        Heading.from_message(frame)


@pytest.mark.parametrize("binary_format", [False, True])
def test_navigation_and_record_reject_same_invalid_latency(binary_format: bool) -> None:
    if binary_format:
        payload = bytearray(120)
        pack_into("<f", payload, 80, float("nan"))
        frame = binary_message("BESTNAV", bytes(payload))
    else:
        original = manual_message("BESTNAVA")
        assert isinstance(original, AsciiMessage)
        fields = list(original.fields)
        fields[23] = "nan"
        frame = replace(original, fields=tuple(fields))
    with pytest.raises(ProtocolError, match="latency"):
        decode_log(frame)
    with pytest.raises(ProtocolError, match="latency"):
        BestNavigation.from_message(frame)
