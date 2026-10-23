"""Tests the raw data tracking example."""

from __future__ import annotations

import struct

import pytest
from examples.raw_data_tracking import (
    catalogue_summary,
    container_summary,
    decoded_messages,
    field_coverage,
    histogram,
    read_containers,
    report,
)

from um982py.errors import ChecksumError
from um982py.experimental import (
    BASEBAND_MESSAGE_CATALOGUE,
    BasebandStream,
    RawBasebandPacket,
    build_message,
)
from um982py.experimental.baseband_messages import IGNORED_IDS

FLOAT_TOLERANCE = 1e-6
"""Single-precision fields are exact here, so 1e-6 absorbs only float32 rounding."""


def payload_for_202() -> bytes:
    """Pack message 202 at the catalogue offsets, written out by hand."""
    data = bytearray(96)
    struct.pack_into("<i", data, 16, -123456)
    struct.pack_into("<I", data, 20, 4_000_000_000)
    struct.pack_into("<I", data, 24, 7)
    struct.pack_into("<I", data, 28, 8)
    struct.pack_into("<I", data, 32, 9)
    data[36] = 5
    data[37] = 6
    data[38] = 7
    for offset, value in zip(
        (40, 44, 48, 52, 56, 60, 64, 68, 72, 76, 80, 84, 88, 92),
        (
            1.5,
            -2.25,
            3.75,
            0.5,
            12.5,
            -0.125,
            8.0,
            0.25,
            100.0,
            -64.0,
            2.0,
            4.0,
            6.0,
            3.75,
        ),
        strict=True,
    ):
        struct.pack_into("<f", data, offset, value)
    return bytes(data)


def container_with(*messages: bytes) -> RawBasebandPacket:
    """Build a container holding the given framed inner messages."""
    return RawBasebandPacket.build(
        sequence=7, major_version=2, content=b"".join(messages)
    )


def test_built_container_round_trips_through_the_stream() -> None:
    built = RawBasebandPacket.build(
        sequence=11,
        major_version=3,
        measurement_sync_tag=0xDEADBEEF,
        antenna_id=2,
        frequency_code=5,
        interval=1000,
        prologue=b"\x01\x02",
        content=build_message(32, payload_for_202()),
    )
    packets = BasebandStream().feed(built.raw)
    assert len(packets) == 1
    assert packets[0].raw == built.raw


def test_decoded_header_fields_equal_the_built_header_fields() -> None:
    built = RawBasebandPacket.build(
        sequence=11,
        major_version=3,
        measurement_sync_tag=0xDEADBEEF,
        antenna_id=2,
        frequency_code=5,
        interval=1000,
        content=build_message(23, b"\x00" * 40),
    )
    packet = read_containers(built.raw)[0]
    assert packet.sequence == pytest.approx(11)
    assert packet.major_version == pytest.approx(3)
    assert packet.measurement_sync_tag == pytest.approx(0xDEADBEEF)
    assert packet.antenna_id == pytest.approx(2)
    assert packet.frequency_code == pytest.approx(5)
    assert packet.interval == pytest.approx(1000)


def test_corrupted_checksum_byte_raises_checksum_error() -> None:
    built = RawBasebandPacket.build(
        sequence=1, content=build_message(202, payload_for_202())
    )
    corrupted = bytearray(built.raw)
    corrupted[-1] ^= 0xFF
    with pytest.raises(ChecksumError):
        RawBasebandPacket.from_bytes(bytes(corrupted))


def test_stream_skips_a_container_with_a_corrupted_checksum() -> None:
    built = RawBasebandPacket.build(
        sequence=1, content=build_message(202, payload_for_202())
    )
    corrupted = bytearray(built.raw)
    corrupted[-1] ^= 0xFF
    assert BasebandStream().feed(bytes(corrupted)) == ()


def test_decoded_fields_sit_at_the_catalogue_offsets() -> None:
    packet = container_with(build_message(202, payload_for_202()))
    record = decoded_messages(packet)[0].record
    assert record is not None
    assert record.integer("field_16") == pytest.approx(-123456)
    assert record.integer("field_20") == pytest.approx(4_000_000_000)
    assert record.integer("field_32") == pytest.approx(9)
    assert record.integer("field_36") == pytest.approx(5)
    assert record.integer("field_38") == pytest.approx(7)
    assert record.real("field_40") == pytest.approx(1.5, abs=FLOAT_TOLERANCE)
    assert record.real("field_44") == pytest.approx(-2.25, abs=FLOAT_TOLERANCE)
    assert record.real("field_92") == pytest.approx(3.75, abs=FLOAT_TOLERANCE)


def test_short_payload_is_flagged_rather_than_decoded() -> None:
    message = decoded_messages(container_with(build_message(202, b"\x00" * 8)))[0]
    assert message.decoded is False
    assert message.record is None


def test_histogram_counts_each_message_id() -> None:
    packet = container_with(
        build_message(32, b"\x00" * 36),
        build_message(32, b"\x00" * 36),
        build_message(61, b"\x00" * 244),
    )
    counts = histogram(decoded_messages(packet))
    assert [entry.message_id for entry in counts] == [32, 61]
    assert counts[0].count == pytest.approx(2)
    assert counts[1].count == pytest.approx(1)


def test_ignored_and_unknown_ids_are_flagged() -> None:
    packet = container_with(
        build_message(20, b"\x00" * 4), build_message(5, b"\x00" * 4)
    )
    summary = report(packet.raw)
    assert summary.ignored_ids == (20,)
    assert summary.unknown_ids == (5,)
    flagged = {entry.message_id: entry for entry in summary.histogram}
    assert flagged[20].ignored is True
    assert flagged[5].unknown is True


def test_report_counts_containers_and_stream_garbage() -> None:
    packet = container_with(build_message(32, b"\x00" * 36))
    summary = report(b"\xff\xff\xff" + packet.raw)
    assert len(summary.containers) == 1
    assert summary.message_count == pytest.approx(1)
    assert summary.discarded_bytes == pytest.approx(3)


def test_report_lists_notice_names() -> None:
    packet = container_with(build_message(32, b"\x00" * 36))
    raw = b"$BB Version: 1.2.3\r\n$TrackMode,2\r\n" + packet.raw
    assert report(raw).notices == ("BB_VERSION", "TRACKMODE")


def test_container_summary_carries_header_fields_and_message_ids() -> None:
    packet = container_with(
        build_message(32, b"\x00" * 36), build_message(23, b"\x00" * 40)
    )
    summary = container_summary(packet)
    assert summary.sequence == pytest.approx(7)
    assert summary.message_ids == (32, 23)
    assert summary.declared_length == pytest.approx(len(packet.raw))


def test_catalogue_covers_every_message_id() -> None:
    summary = catalogue_summary()
    assert summary.first_id == pytest.approx(19)
    assert summary.last_id == pytest.approx(203)
    assert summary.entries == pytest.approx(203 - 19 + 1)
    assert set(BASEBAND_MESSAGE_CATALOGUE) == set(range(19, 204))


def test_catalogue_marks_exactly_one_hundred_ids_ignored() -> None:
    summary = catalogue_summary()
    ignored = {
        spec.message_id for spec in BASEBAND_MESSAGE_CATALOGUE.values() if spec.ignored
    }
    assert summary.ignored == pytest.approx(100)
    assert ignored == set(IGNORED_IDS)
    assert summary.undecoded == pytest.approx(0)


def test_field_coverage_separates_verified_from_unverified_fields() -> None:
    coverage = field_coverage()
    assert coverage.messages > 40
    assert coverage.described > 0
    assert coverage.verified > 0
    assert coverage.unverified > 0
    total = coverage.verified + coverage.unverified
    assert coverage.verified_ratio == pytest.approx(coverage.verified / total)
    assert 0.0 < coverage.verified_ratio < 1.0
