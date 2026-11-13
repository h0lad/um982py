"""Structured RTCM decoding against independent wire vectors."""

import json
import subprocess
import sys
from dataclasses import replace

import pytest

from conftest import FIXTURES, rtcm
from um982py import Log, decode_message, decode_rtcm
from um982py.errors import ChecksumError, ProtocolError
from um982py.messages import Record
from um982py.protocol.binary import parse_rtcm
from um982py.rtcm import STANDARD_RTCM_TYPES, UNICORE_RTCM_TYPES

VECTORS = json.loads((FIXTURES / "rtcm-vectors.json").read_text())["vectors"]


def fields(record: Record) -> Record:
    result = record["fields"]
    assert isinstance(result, Record)
    return result


def flat_fields(record: Record) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in record.items():
        if key in ("satellites", "cells"):
            for index, child in enumerate(record.records(key), 1):
                result.update(
                    (f"{name}_{index:02}", item)
                    for name, item in child.items()
                    if name.startswith("DF")
                )
        elif key.startswith("DF"):
            if isinstance(value, str):
                result.update(
                    (f"{key}_{i:02}", char) for i, char in enumerate(value, 1)
                )
            else:
                result[key] = value
    return result


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: str(v["message_type"]))
def test_scaled_data_fields_match_independent_vectors(vector: dict) -> None:
    raw = bytes.fromhex(vector["hex"])
    record = decode_rtcm(raw)
    assert record["status"] == "decoded"
    assert record.integer("message_type") == vector["message_type"]
    assert record["payload"] == raw[3:-3]
    assert record.message == parse_rtcm(raw)
    assert flat_fields(fields(record)) == pytest.approx(vector["fields"])
    assert decode_message(raw) == record
    assert Log[f"RTCM{vector['message_type']}"].decode(parse_rtcm(raw)) == record


def test_vectors_cover_every_standard_decoder() -> None:
    assert {v["message_type"] for v in VECTORS} == STANDARD_RTCM_TYPES


@pytest.mark.parametrize("vector", VECTORS, ids=lambda v: str(v["message_type"]))
def test_truncation_and_extra_bytes_are_rejected(vector: dict) -> None:
    payload = bytes.fromhex(vector["hex"])[3:-3]
    for size in range(len(payload)):
        with pytest.raises(ProtocolError):
            decode_rtcm(rtcm(payload[:size]))
    with pytest.raises(ProtocolError, match="trailing"):
        decode_rtcm(rtcm(payload + b"\x00"))


def test_msm_sparse_cells_keep_satellite_signal_pairing() -> None:
    raw = bytes.fromhex(next(v["hex"] for v in VECTORS if v["message_type"] == 1075))
    body = fields(decode_rtcm(raw))
    assert body["signal_ids"] == (2, 8)
    assert [r["satellite_id"] for r in body.records("satellites")] == [1, 3]
    assert [(r["satellite_id"], r["signal_id"]) for r in body.records("cells")] == [
        (1, 2),
        (3, 2),
        (3, 8),
    ]
    assert body.integer("cell_count") == 3
    assert body.records("cells")[0].real("DF404") == pytest.approx(-0.0003)


@pytest.mark.parametrize("kind", [63, 1104, 1105, 4090])
def test_private_and_unknown_payloads_are_preserved(kind: int) -> None:
    payload = (kind << 4).to_bytes(2, "big") + b"opaque"
    record = decode_rtcm(rtcm(payload))
    assert record["status"] == (
        "unicore_private" if kind in UNICORE_RTCM_TYPES else "unsupported"
    )
    assert record["payload"] == payload
    assert len(fields(record)) == 0
    assert decode_message(rtcm(payload)) == record


def test_crc_and_inconsistent_frame_metadata_are_rejected() -> None:
    raw = bytes.fromhex(VECTORS[0]["hex"])
    with pytest.raises(ChecksumError):
        decode_rtcm(raw[:-1] + bytes([raw[-1] ^ 1]))
    with pytest.raises(ProtocolError, match="metadata"):
        decode_rtcm(replace(parse_rtcm(raw), message_type=1007))


def test_padding_is_not_an_extra_data_field() -> None:
    payload = bytes.fromhex(
        next(v["hex"] for v in VECTORS if v["message_type"] == 1042)
    )[3:-3]
    with pytest.raises(ProtocolError, match="padding"):
        decode_rtcm(rtcm(payload[:-1] + bytes([payload[-1] | 1])))


def test_station_coordinates_use_signed_38_bit_values() -> None:
    bits = 152
    payload = (1005 << (bits - 12)) | (42 << (bits - 24))
    coordinates = (-(1 << 37), (1 << 37) - 1, -1)
    for offset, coordinate in zip((34, 74, 114), coordinates, strict=True):
        payload |= (coordinate & ((1 << 38) - 1)) << (bits - offset - 38)
    body = fields(decode_rtcm(rtcm(payload.to_bytes(19, "big"))))
    assert body.integer("DF003") == 42
    for name, coordinate in zip(("DF025", "DF026", "DF027"), coordinates, strict=True):
        assert body.real(name) == pytest.approx(coordinate * 0.0001)


def test_glonass_sign_magnitude_negative_zero() -> None:
    payload = bytes.fromhex(
        next(v["hex"] for v in VECTORS if v["message_type"] == 1020)
    )[3:-3]
    shift = len(payload) * 8 - 48 - 24
    value = int.from_bytes(payload, "big")
    value &= ~(((1 << 24) - 1) << shift)
    value |= (1 << 23) << shift
    body = fields(decode_rtcm(rtcm(value.to_bytes(len(payload), "big"))))
    assert body.real("DF111") == 0


def test_msm_empty_masks_and_cell_count_limit() -> None:
    def header(satellites: int, signals: int, cells: int) -> bytes:
        # 73 header bits precede the satellite mask; no observation columns.
        pairs = satellites.bit_count() * signals.bit_count()
        bits = 169 + pairs
        value = (1074 << (bits - 12)) | (satellites << (32 + pairs))
        value |= (signals << pairs) | cells
        padding = -bits % 8
        return rtcm((value << padding).to_bytes((bits + padding) // 8, "big"))

    body = fields(decode_rtcm(header(0, 0, 0)))
    assert body.records("satellites") == body.records("cells") == ()
    assert body.integer("cell_count") == 0
    with pytest.raises(ProtocolError, match="64 active cells"):
        decode_rtcm(header((1 << 9) - 1, (1 << 8) - 1, (1 << 72) - 1))


def test_decoder_has_no_optional_imports() -> None:
    code = """
import sys
from um982py import decode_rtcm
assert not any(name.startswith(("pyrtcm", "pynmeagps")) for name in sys.modules)
result = decode_rtcm(bytes.fromhex(sys.argv[1]))
assert result["status"] == "decoded"
assert not any(name.startswith(("pyrtcm", "pynmeagps")) for name in sys.modules)
"""
    subprocess.run(
        [sys.executable, "-c", code, VECTORS[0]["hex"]], check=True, timeout=10
    )
