"""Tests the inner message catalogue and payload decoder."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from struct import pack
from types import MappingProxyType

import pytest

from um982py.errors import ProtocolError
from um982py.experimental import (
    BASEBAND_MESSAGE_CATALOGUE,
    BasebandField,
    BasebandMessageFamily,
    BasebandMessageSpec,
    build_message,
    decode_message_payload,
)
from um982py.experimental._bbmsg_data import CATALOGUE_DATA, IGNORED_IDS
from um982py.experimental.baseband import RawBasebandPacket
from um982py.experimental.baseband_messages import spec


def test_catalogue_covers_the_whole_message_range() -> None:
    assert len(CATALOGUE_DATA) == 185
    assert set(BASEBAND_MESSAGE_CATALOGUE) == set(range(19, 204))
    assert isinstance(BASEBAND_MESSAGE_CATALOGUE, MappingProxyType)


def test_ignored_ids_are_exactly_the_unprocessed_ids() -> None:
    ignored = {
        message_id
        for message_id, entry in BASEBAND_MESSAGE_CATALOGUE.items()
        if entry.ignored
    }
    assert ignored == IGNORED_IDS
    assert len(ignored) == 100
    assert all(
        not entry.fields
        for entry in BASEBAND_MESSAGE_CATALOGUE.values()
        if entry.ignored
    )


def test_every_message_is_classified() -> None:
    classified = [
        entry for entry in BASEBAND_MESSAGE_CATALOGUE.values() if entry.classified
    ]
    assert len(classified) == 185
    assert (
        sum(1 for entry in classified if entry.family is BasebandMessageFamily.PAYLOAD)
        == 82
    )
    assert [
        entry.message_id
        for entry in classified
        if entry.family is BasebandMessageFamily.NOOP
    ] == [41]
    assert (
        sum(
            1 for entry in classified if entry.family is BasebandMessageFamily.DELEGATOR
        )
        == 1
    )


def test_field_layouts_are_self_consistent() -> None:
    for entry in BASEBAND_MESSAGE_CATALOGUE.values():
        offsets = [field.offset for field in entry.fields]
        assert offsets == sorted(offsets), entry.message_id
        assert len(offsets) == len(set(offsets)), entry.message_id
        if entry.fields:
            assert entry.payload_extent == max(
                field.offset + field.size for field in entry.fields
            )
            for field in entry.fields:
                assert field.name == f"field_{field.offset}"
                assert field.size >= 1
        else:
            assert entry.payload_extent is None


def test_repeating_layouts_are_flagged() -> None:
    repeating = {
        entry.message_id
        for entry in BASEBAND_MESSAGE_CATALOGUE.values()
        if entry.repeating
    }
    assert 104 in repeating
    assert 62 in repeating
    assert 202 not in repeating
    assert len(repeating) == 30
    assert all(spec(message_id).payload_extent is not None for message_id in repeating)


@pytest.mark.parametrize("message_id", [20, 30, 60, 198])
def test_ignored_ids_decode_to_an_empty_record(message_id: int) -> None:
    record = decode_message_payload(message_id, b"")
    assert record.name == f"message_{message_id}"
    assert len(record) == 0


def test_out_of_range_ids_are_rejected() -> None:
    for message_id in (18, 204, 0, 255):
        with pytest.raises(ProtocolError, match="outside the catalogue range"):
            spec(message_id)


def test_decode_reads_the_described_offsets() -> None:
    entry = spec(202)
    assert entry.payload_extent is not None
    payload = bytearray(entry.payload_extent)
    payload[16:20] = pack("<i", -1234)
    payload[36] = 0xAB
    record = entry.decode(bytes(payload))
    assert record.name == "message_202"
    assert record["field_16"] == -1234
    assert record["field_36"] == 0xAB
    assert len(record) == len(entry.fields)


def test_decode_rejects_a_truncated_payload() -> None:
    entry = spec(202)
    assert entry.payload_extent is not None
    with pytest.raises(ProtocolError, match=r"needs .* payload bytes"):
        entry.decode(b"\0" * (entry.payload_extent - 1))


def test_decode_accepts_trailing_bytes() -> None:
    entry = spec(202)
    assert entry.payload_extent is not None
    payload = bytes(entry.payload_extent) + b"trailing"
    assert len(entry.decode(payload)) == len(entry.fields)


def test_bytes_fields_are_returned_verbatim() -> None:
    entry = spec(19)
    assert entry.payload_extent is not None
    payload = bytearray(entry.payload_extent)
    payload[16:60] = bytes(range(44))
    record = entry.decode(bytes(payload))
    assert record["field_16"] == bytes(range(44))


def test_float_fields_are_decoded() -> None:
    float_entries = [
        entry
        for entry in BASEBAND_MESSAGE_CATALOGUE.values()
        if any(field.type == "f64" for field in entry.fields)
    ]
    assert float_entries, "expected at least one f64 layout"
    entry = float_entries[0]
    assert entry.payload_extent is not None
    field = next(f for f in entry.fields if f.type == "f64")
    payload = bytearray(entry.payload_extent)
    payload[field.offset : field.offset + 8] = pack("<d", 2.5)
    assert entry.decode(bytes(payload))[field.name] == 2.5


def test_field_type_and_width_validation() -> None:
    with pytest.raises(ValueError, match="Unsupported field type"):
        BasebandField(0, 4, "u128", "field_0")
    with pytest.raises(ValueError, match="does not match"):
        BasebandField(0, 2, "u32", "field_0")
    with pytest.raises(ValueError, match="size positive"):
        BasebandField(0, 0, "u8", "field_0")
    assert BasebandField(0, 44, "bytes", "field_0").read(bytes(44)) == bytes(44)


def test_message_spec_is_frozen() -> None:
    entry = BasebandMessageSpec(19, BasebandMessageFamily.PAYLOAD)
    with pytest.raises(FrozenInstanceError):
        entry.message_id = 20  # type: ignore[misc]


def test_container_message_decodes_through_its_spec() -> None:
    entry = spec(202)
    assert entry.payload_extent is not None
    body = bytearray(entry.payload_extent)
    body[16:20] = pack("<i", 7)
    message = build_message(202, bytes(body))
    packet = RawBasebandPacket.build(content=message)
    (framed,) = packet.messages
    assert framed.spec is entry
    assert framed.decode()["field_16"] == 7


def test_container_message_with_short_body_raises_on_decode() -> None:
    packet = RawBasebandPacket.build(content=build_message(202, b"\0\0\0\0"))
    (framed,) = packet.messages
    with pytest.raises(ProtocolError, match="needs"):
        framed.decode()
