"""Tests the telemetry bridge example."""

from __future__ import annotations

import json

import pytest
from examples.telemetry_bridge import (
    FrameKind,
    frame_from,
    record_object,
    value_object,
)

from um982py.messages import (
    Record,
    RtcmMessage,
    decode_log,
)

JSON_TOLERANCE = 1e-12
"""A JSON round trip of a float is exact; 1e-12 only guards repr formatting."""


def assert_record_matches(record: Record, encoded: object) -> None:
    """Compare a decoded record field by field with its JSON form."""
    assert isinstance(encoded, dict)
    assert list(encoded) == list(record)
    for key, value in record.entries:
        field = encoded[key]
        if isinstance(value, Record):
            assert_record_matches(value, field)
        elif isinstance(value, tuple):
            assert isinstance(field, list)
            assert len(field) == len(value)
            for item, encoded_item in zip(value, field, strict=True):
                if isinstance(item, Record):
                    assert_record_matches(item, encoded_item)
                elif isinstance(item, float):
                    assert encoded_item == pytest.approx(item, rel=JSON_TOLERANCE)
                else:
                    assert encoded_item == item
        elif isinstance(value, float):
            assert field == pytest.approx(value, rel=JSON_TOLERANCE)
        else:
            assert field == value


def test_rtcm_payload_is_encoded_as_hexadecimal() -> None:
    message = RtcmMessage(message_type=1005, payload=b"\x01\x02\xff", raw=b"")
    frame = frame_from(message)
    assert frame.kind is FrameKind.RTCM
    assert frame.name == "RTCM_1005"
    assert json.loads(frame.to_line())["fields"]["payload"] == "0102ff"
    assert record_object(decode_log(message))["payload"] == "0102ff"


def test_record_values_convert_to_plain_json_types() -> None:
    record = Record("probe", (("count", 3), ("ratio", 0.5), ("blob", b"\x00\xff")))
    assert value_object(record) == {"count": 3, "ratio": 0.5, "blob": "00ff"}
