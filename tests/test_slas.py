"""Conservative QZSS SLAS mapping checks against the documented examples."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from test_bodies import binary_message, manual_latest_message
from um982py.commands import Log
from um982py.errors import ProtocolError
from um982py.messages import AsciiMessage, Record
from um982py.protocol import StreamDecoder
from um982py.slas import SlasTracker, slas_candidates, slas_corrections, slas_selection

EXAMPLES = json.loads(
    (Path(__file__).parent / "fixtures/manual-examples-r1.15.json").read_text()
)


def decode(name: str) -> Record:
    frame = StreamDecoder(strict=True).feed((EXAMPLES[name + "A"] + "\r\n").encode())[0]
    return Log[name].decode(frame)


def test_mt48_candidates_from_documented_example() -> None:
    candidates = slas_candidates(decode("L1SMT48"))
    names = [c.name for c in candidates]
    # GPS mask 085e570800000000 (msb unpacking) selects 12 G-slots.
    gps = [c for c in candidates if c.system == "GPS"]
    assert len(gps) == 12
    assert gps[0].name == "G05"
    assert gps[-1].name == "G29"
    # QZSS mask 7200 selects four of the nine J-slots.
    qzss = [c for c in candidates if c.system == "QZSS"]
    assert [c.name for c in qzss] == ["J02", "J03", "J04", "J07"]
    # Zero masks select nothing.
    assert not [c for c in candidates if c.system == "GLONASS"]
    assert not [c for c in candidates if c.system == "BEIDOU"]
    assert len(candidates) == 16 <= 23
    assert names == sorted(names, key=lambda c: (c[0], int(c[1:])))


def test_bit_order_is_explicit_and_not_assumed() -> None:
    msb = slas_candidates(decode("L1SMT48"), msb=True)
    lsb = slas_candidates(decode("L1SMT48"), msb=False)
    assert msb != lsb


@pytest.mark.parametrize("hex_mask", ["8000000000", "8000000000000000"])
def test_beidou_mask_preserves_ascii_and_binary_byte_order(hex_mask: str) -> None:
    message = manual_latest_message("L1SMT48A")
    assert isinstance(message, AsciiMessage)
    fields = list(message.fields)
    fields[10] = hex_mask
    ascii_record = Log.L1SMT48.decode(replace(message, fields=tuple(fields)))
    payload = bytearray(36)
    payload[24:32] = b"\x80" + bytes(7)
    binary_record = Log.L1SMT48.decode(binary_message("L1SMT48", bytes(payload)))
    for record in (ascii_record, binary_record):
        candidates = slas_candidates(record)
        assert [
            candidate.name for candidate in candidates if candidate.system == "BEIDOU"
        ] == ["C01"]


def test_beidou_ascii_mask_rejects_unknown_lengths() -> None:
    message = manual_latest_message("L1SMT48A")
    assert isinstance(message, AsciiMessage)
    fields = list(message.fields)
    fields[10] = "8000"
    with pytest.raises(ProtocolError, match="BDS mask"):
        Log.L1SMT48.decode(replace(message, fields=tuple(fields)))


def test_mt49_selection_maps_iod_values_onto_candidates() -> None:
    candidates = slas_candidates(decode("L1SMT48"))
    selection = slas_selection(candidates, decode("L1SMT49"))
    assert selection
    satellites = [name for name, _ in selection]
    # MT49 Mask-SV ffff0000 selects the first slots in candidate order.
    assert satellites == [candidate.name for candidate in candidates[: len(satellites)]]
    assert all(0 <= iod <= 255 for _, iod in selection)


def test_mt50_corrections_are_never_marked_usable() -> None:
    candidates = slas_candidates(decode("L1SMT48"))
    selection = slas_selection(candidates, decode("L1SMT49"))
    corrections = slas_corrections(candidates, selection, decode("L1SMT50"))
    assert corrections
    assert all(not correction.usable for correction in corrections)
    assert all(
        isinstance(correction.pseudorange_m, float) for correction in corrections
    )


def test_tracker_requires_mt49_and_matching_iod_before_mt50() -> None:
    tracker = SlasTracker()
    result = tracker.process(decode("L1SMT48"), source_prn=189, mask_iodp=1)
    assert result is not None and result.status.startswith("bit_order")
    result = tracker.process(decode("L1SMT49"), source_prn=189)
    assert result is not None and result.status == "conditional_mapping"
    assert result.selected
    original = decode("L1SMT50")
    same_source = Record(
        original.name,
        tuple(
            (key, (189,) if key == "prefix" else value)
            for key, value in original.entries
        ),
    )
    result = tracker.process(same_source, source_prn=189)
    assert result is not None
    assert result.corrections
    assert result.status == "mapping_unverified_not_safe_for_positioning"
    assert not result.usable


def test_tracker_rejects_iod_mismatch() -> None:
    tracker = SlasTracker()
    tracker.process(decode("L1SMT48"), source_prn=189, mask_iodp=1)
    tracker.process(decode("L1SMT49"), source_prn=189)
    mismatched = Record(
        "L1SMT50",
        (
            ("iodp", 99),
            ("iodi", 99),
            ("gms_code", 1),
            ("gms_health", 0),
            ("mask_sv", b"\x96\xe3\x00"),
            ("prc", (0.0,) * 14),
        ),
    )
    result = tracker.process(mismatched, source_prn=189)
    assert result is not None
    assert result.status.startswith("error: MT50 IODI/IODP mismatch")


def test_tracker_requires_preceding_mt48() -> None:
    tracker = SlasTracker()
    result = tracker.process(decode("L1SMT49"), source_prn=189)
    assert result is not None
    assert result.status.startswith("error: MT49 requires preceding MT48")


def test_non_slas_message_is_ignored() -> None:
    tracker = SlasTracker()
    assert tracker.process(Record("BESTNAV", (("lat", 1.0),))) is None


def test_invalid_slas_field_types_are_rejected() -> None:
    candidates = (slas_candidates(decode("L1SMT48"))[0],)
    invalid = Record("L1SMT49", (("mask_sv", b"\x80\x00\x00"), ("iod", None)))
    with pytest.raises(TypeError, match="iod is not a sequence"):
        slas_selection(candidates, invalid)

    invalid = Record("L1SMT50", (("mask_sv", b"\x80\x00\x00"), ("prc", (None,))))
    with pytest.raises(TypeError, match="expected a numeric value"):
        slas_corrections(candidates, ((candidates[0].name, 1),), invalid)


def test_sparse_iod_values_use_mask_slot_index() -> None:
    candidates = slas_candidates(decode("L1SMT48"))[:3]
    issue = Record("L1SMT49", (("mask_sv", b"\xa0\x00\x00"), ("iod", (10, 20, 30))))
    assert slas_selection(candidates, issue) == (
        (candidates[0].name, 10),
        (candidates[2].name, 30),
    )


def test_tracker_rejects_mixed_satellites_and_invalidates_stale_issue() -> None:
    tracker = SlasTracker()
    tracker.process(decode("L1SMT48"), source_prn=189, mask_iodp=1)
    tracker.process(decode("L1SMT49"), source_prn=189)
    mixed = tracker.process(decode("L1SMT50"), source_prn=185)
    assert mixed is not None and "source PRN mismatch" in mixed.status
    bad_issue = Record("L1SMT49", (("iodi", 1), ("iodp", 2)))
    result = tracker.process(bad_issue, source_prn=189)
    assert result is not None and "IODP mismatch" in result.status
    correction = Record("L1SMT50", (("iodi", 1), ("iodp", 1)))
    result = tracker.process(correction, source_prn=189)
    assert result is not None and "requires preceding MT49" in result.status


def test_corrections_require_mt49_selection() -> None:
    candidates = slas_candidates(decode("L1SMT48"))[:1]
    correction = Record("L1SMT50", (("mask_sv", b"\x80\x00\x00"), ("prc", (1.0,))))
    with pytest.raises(ValueError, match="not selected by MT49"):
        slas_corrections(candidates, (), correction)


def test_binary_records_require_source_and_mask_iodp() -> None:
    original = decode("L1SMT48")
    binary = Record(
        original.name, tuple(e for e in original.entries if e[0] != "prefix")
    )
    tracker = SlasTracker()
    result = tracker.process(binary)
    assert result is not None and "source PRN required" in result.status
    result = tracker.process(binary, source_prn=189)
    assert result is not None and "MT48 IODP required" in result.status
    result = tracker.process(binary, source_prn=189, mask_iodp=1)
    assert result is not None and result.status.startswith("bit_order")


def test_ascii_prefix_is_not_assumed_to_be_metadata() -> None:
    tracker = SlasTracker()
    record = decode("L1SMT48")
    result = tracker.process(record)
    assert result is not None and "source PRN required" in result.status
    result = tracker.process(record, source_prn=189)
    assert result is not None and "MT48 IODP required" in result.status
