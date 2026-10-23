"""Checks correction coherence against independent day, issue and latency data."""

from dataclasses import replace
from pathlib import Path

import pytest
from examples.b2b_correction_audit import (
    CorrectionCheck,
    CorrectionEvent,
    ServiceAudit,
    align_navigation,
    audit_corrections,
    service_census,
    service_of,
)

from tests.examples._new_api import record as range_record
from um982py.capture import record_epoch
from um982py.experimental import b2b_epoch
from um982py.messages import Record

MASK = CorrectionEvent(100, 219, "mask", 99, 1, 2, mask=b"\x01" * 32)
ORBIT = CorrectionEvent(
    102, 219, "orbit", 100, 1, issues=((72, 3),), navigation=((72, 86),)
)
CLOCK = CorrectionEvent(104, 219, "clock", 103, 1, 2, issues=((72, 3),))


def test_matching_issues_have_no_coherence_faults() -> None:
    result = audit_corrections([MASK, ORBIT, CLOCK], navigation_issues={72: 86})
    assert [item.age_seconds for item in result] == [1, 2, 1]
    assert all(not item.flags for item in result)


def test_wrong_clock_issue_is_not_applied_to_the_latest_orbit() -> None:
    result = audit_corrections([MASK, ORBIT, replace(CLOCK, issues=((72, 4),))])
    assert "iodcorr_mismatch:72" in result[-1].flags


def test_mask_change_needs_an_issue_change() -> None:
    result = audit_corrections(
        [MASK, replace(MASK, received=101, epoch=100, mask=b"\x02" * 32)]
    )
    assert result[-1].flags == ("mask_changed_without_issue",)


def test_reference_navigation_issue_is_independent_of_correction_issue() -> None:
    result = audit_corrections([MASK, ORBIT], navigation_issues={72: 87})
    assert result[-1].flags == ("navigation_issue_mismatch:72",)


def test_different_transmitters_do_not_share_masks() -> None:
    result = audit_corrections([MASK, replace(ORBIT, transmitter=220)])
    assert "missing_mask" in result[-1].flags


def test_stale_orbit_cannot_supply_clock_compatibility() -> None:
    result = audit_corrections([MASK, replace(ORBIT, received=102, epoch=10), CLOCK])
    assert "stale_correction" in result[1].flags
    assert "missing_orbit:72" in result[-1].flags


def test_mask_based_clock_mapping_remains_explicitly_unverified() -> None:
    result = audit_corrections([MASK, replace(CLOCK, issues=())])
    assert result[-1].flags == ("satellite_mapping_unverified",)


def test_bdt_midnight_resolves_to_previous_day_on_gps_time_scale() -> None:
    assert b2b_epoch(86415, 86399) == 86413
    assert b2b_epoch(86410, 86395) == 86409
    assert b2b_epoch(2203 * 604800 + 366209, 20590) == 2203 * 604800 + 366204


@pytest.mark.parametrize("tag", [-1, 86400, 1.5])
def test_invalid_bdt_day_tags_are_rejected(tag: int) -> None:
    with pytest.raises(ValueError):
        b2b_epoch(100, tag)


def test_service_census_reports_an_absent_service_as_no_blocks() -> None:
    census = service_census([], [])
    assert [
        (item.service, item.status, item.blocks, item.clean) for item in census
    ] == [
        ("b2b", "no_blocks", 0, False),
        ("has", "no_blocks", 0, False),
    ]


def test_service_census_counts_flagged_checks_per_service() -> None:
    b2b = audit_corrections([MASK, ORBIT, CLOCK])
    has: tuple[dict[str, object], ...] = (
        {"source": "E6ORBITBLOCK", "flags": []},
        {"source": "E6CLOCKFULLBLOCK", "flags": ["stale_mask"]},
    )
    census = service_census(b2b, has)
    assert census[0].service == "b2b"
    assert census[0].blocks == 3
    assert census[0].flagged == 0
    assert census[1] == ServiceAudit("has", 2, 1, "checked")
    assert not census[1].clean and census[0].clean


def test_service_of_separates_the_two_correction_services() -> None:
    assert service_of("PPPB2BINFO2") == "b2b"
    assert service_of("E6ORBITBLOCK") == "has"
    with pytest.raises(ValueError, match="not a satellite correction"):
        service_of("BESTNAV")


def test_malformed_has_flags_are_rejected() -> None:
    for flags in ("stale", 3, None):
        with pytest.raises(ValueError, match="flag sequence"):
            service_census([], ({"source": "E6MASKBLOCK", "flags": flags},))


def test_correction_blocks_are_ordered_by_epoch_not_by_log_name() -> None:
    from pathlib import Path

    from examples.b2b_correction_audit import chronological

    from um982py.capture import decode_records, read_frames, record_epoch
    from um982py.commands import Log

    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "captures-extra"
    mask = decode_records(read_frames(fixtures / "E6MASKBLOCKB.bin"), Log.E6MASKBLOCK)
    clock = decode_records(
        read_frames(fixtures / "E6CLOCKFULLBLOCKB.bin"), Log.E6CLOCKFULLBLOCK
    )
    orbit = decode_records(
        read_frames(fixtures / "E6ORBITBLOCKB.bin"), Log.E6ORBITBLOCK
    )
    combined = (*clock, *orbit, *mask)
    ordered = chronological(combined)
    epochs = [record_epoch(record) for record in ordered]
    assert epochs == sorted(epochs)
    assert len(ordered) == len(combined)


def test_ppp_alignment_reports_recent_delivery_without_claiming_application() -> None:
    message = range_record(0, []).message
    assert message is not None
    navigation = Record("PPPNAV", (("pos_type", 68), ("sol_status", 0)), message)
    epoch = record_epoch(navigation)
    checks = (CorrectionCheck(epoch - 1, 219, "orbit", 1, ()),)
    has = ({"received_gps_seconds": epoch - 2, "flags": []},)
    aligned = align_navigation((navigation,), checks, has, window_seconds=5)[0]
    assert aligned.position_type == "PPP_CONVERGING"
    assert aligned.recent_b2b_clean_blocks == 1
    assert aligned.recent_has_clean_blocks == 1
    assert not aligned.correction_application_verified
    assert (
        align_navigation((navigation,), checks, has, window_seconds=0.5)[
            0
        ].recent_b2b_blocks
        == 0
    )


def test_cli_correction_csv_and_reference_hash(tmp_path: Path) -> None:
    import hashlib
    import json

    from examples.b2b_correction_audit.__main__ import main

    reference = Path("tests/fixtures/specialist/navigation-issues.csv")
    report, csv_path = tmp_path / "report.json", tmp_path / "checks.csv"
    assert (
        main(
            [
                "--replay",
                "tests/fixtures/specialist/labelled-b2b.bin",
                "--navigation",
                str(reference),
                "--json",
                str(report),
                "--checks-csv",
                str(csv_path),
            ]
        )
        == 0
    )
    data = json.loads(report.read_text())
    assert (
        data["reference_sha256"] == hashlib.sha256(reference.read_bytes()).hexdigest()
    )
    assert csv_path.read_text().startswith(
        "received_gps_seconds,transmitter,kind,age_seconds,flags"
    )
