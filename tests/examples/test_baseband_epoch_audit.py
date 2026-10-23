"""Checks counter and slot auditing against labelled memory and real wire."""

import json
from pathlib import Path

from examples.baseband_epoch_audit import audit_baseband
from examples.baseband_epoch_audit.__main__ import main

from um982py.experimental import scan_notices
from um982py.messages import Record

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/baseband-notice.bin"


def test_native_counters_are_classified_without_inventing_packet_loss() -> None:
    raw = b"".join(
        (
            "$BBNOTICE:usStringSize=100 usTotalLen=100 ucReserved=0 "
            f"uiTagCount={tag} ucBoardType=2\r\n"
        ).encode()
        for tag in (10, 11, 11, 15, 0)
    )
    result = audit_baseband(scan_notices(raw), [])
    assert [t.difference for t in result.transitions] == [1, 0, 4, -15]
    assert [t.classification for t in result.transitions] == [
        "unit_increment",
        "duplicate",
        "forward_jump",
        "backward_or_wrap",
    ]


def test_unwritten_memory_and_nonfinite_written_values_never_enter_statistics() -> None:
    def tracking(mask: int, value: float) -> Record:
        return Record(
            "PTOBSINFO",
            (("field_11", mask), *((f"field_{i + 12:02}", value) for i in range(18))),
        )

    result = audit_baseband(
        [], [tracking(0, 9999), tracking(1, -2), tracking(1, float("nan"))]
    )
    first, second = result.slot_summaries[:2]
    assert first.written_frames == 2 and first.unwritten_frames == 1
    assert first.nonfinite_written_frames == 1 and first.median_native == -2
    assert second.median_native is None and second.written_frames == 0


def test_real_wire_replay_preserves_four_native_headers_and_written_slots(
    tmp_path: Path,
) -> None:
    output = tmp_path / "audit.json"
    assert main(["--replay", str(FIXTURE), "--json", str(output)]) == 0
    result = json.loads(output.read_text())
    assert result["native_tag_counts"] == [12113, 12114, 12115, 12116]
    assert result["decoder_errors"] == []
    assert result["discarded_bytes"] == 0
    assert len(result["slot_summaries"]) == 18


def test_empty_wire_has_no_success_claim(tmp_path: Path) -> None:
    source, output = tmp_path / "empty.bin", tmp_path / "out.json"
    source.write_bytes(b"")
    assert main(["--replay", str(source), "--json", str(output)]) == 1
    assert json.loads(output.read_text())["status"] == "insufficient_diagnostics"
