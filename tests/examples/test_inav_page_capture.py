from __future__ import annotations

import json
import sys
from pathlib import Path

import examples.inav_page_capture.__main__ as cli
import pytest
from examples.inav_page_capture import (
    render_audit,
    render_campaign,
    render_page,
    render_word,
)
from examples.inav_page_capture.__main__ import _report

from um982py.experimental import (
    GlonassFdmaString,
    GpsLnavSubframe,
    InavCampaign,
    InavSnapshot,
    InavWord,
    PageWindowAudit,
    WordTiming,
    extract_inav_pages,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

TRACKING_BASE = 0x3C2C00
PAGE_STATE_BASE = 0x3E5B00


def _snapshot() -> InavSnapshot:
    regions = {
        "tracking": (
            TRACKING_BASE,
            (FIXTURES / "inav-tracking-records.mem").read_bytes(),
        ),
        "page_states": (
            PAGE_STATE_BASE,
            (FIXTURES / "inav-page-states.mem").read_bytes(),
        ),
    }
    return InavSnapshot.from_regions(regions, application_restored=True)


def test_report_lists_pages_and_osnma_counts() -> None:
    report = _report(_snapshot())
    assert report["pages"] == 10
    assert report["pages_with_osnma"] == 3
    assert report["odd_pages"] == 6
    assert sorted(report["prns"]) == [6, 7, 11, 12, 14, 15, 16, 20, 29, 36]
    assert report["application_restored"] is True
    assert "OSNMA" in str(report["interpretation"])


@pytest.mark.parametrize("option", [None, "--native-nav", "--no-native-nav"])
def test_live_report_native_navigation(
    option: str | None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    dest = tmp_path / "nav.json"
    argv = ["inav_page_capture", "--json", str(dest)]
    if option is not None:
        argv.append(option)
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(cli, "capture_inav_pages", lambda *args, **kwargs: _snapshot())
    gps = GpsLnavSubframe(26, 1, 3, 577038, (0x22C18D0D,), (0x8B0634,))
    glonass = GlonassFdmaString(65, 34, 11, 0x0B7EDAA35FFFFDD9EFD682)
    monkeypatch.setattr(cli, "extract_native_nav", lambda regions: ((gps,), (glonass,)))

    assert cli.main() == 0
    output = capsys.readouterr().out
    report = json.loads(dest.read_text())
    if option == "--no-native-nav":
        assert "native_nav" not in report
        assert "GPS LNAV" not in output
        assert "GLONASS FDMA" not in output
    else:
        assert "GPS LNAV (1 parity-checked subframes)" in output
        assert "GLONASS FDMA (1 Hamming-checked strings)" in output
        assert "22c18d0d" in output and "0b7edaa35ffffdd9efd682" in output
        assert report["native_nav"] == [
            {"gps_lnav": [gps.manifest()], "glonass_fdma": [glonass.manifest()]}
        ]


def test_report_details_carry_the_decoded_part_fields() -> None:
    report = _report(_snapshot())
    details = {detail["prn"]: detail for detail in report["details"]}
    assert details[11]["osnma"] == "440b8924a2"
    assert details[11]["sar"] == "954918"
    assert details[11]["sar_decoded"] == {
        "start": True,
        "long_rlm": False,
        "data_hex": "55246",
    }
    assert details[29]["word_type"] == 1
    assert details[11]["even"] is False
    assert details[29]["even"] is True


def test_extracted_snapshot_matches_direct_extraction() -> None:
    snapshot = _snapshot()
    regions = {
        "tracking": (TRACKING_BASE, snapshot.regions["tracking"]),
        "page_states": (PAGE_STATE_BASE, snapshot.regions["page_states"]),
    }
    assert snapshot.pages == extract_inav_pages(regions)


def _campaign() -> InavCampaign:
    return InavCampaign((_snapshot(),))


def test_render_page_row_shows_part_word_and_osnma() -> None:
    pages = {page.prn: page for page in _campaign().pages}
    row = render_page(pages[11])
    assert " 11  " in row
    assert "odd/nom" in row
    assert "96c71102e24928a55246905500c0ebed" in row
    assert "440b8924a2" in row
    assert row.endswith("954918")
    assert "yes" in row


def test_render_page_row_marks_alert_and_invalid() -> None:
    pages = {page.prn: page for page in _campaign().pages}
    assert "odd/alert" in render_page(pages[36])
    assert "  no " in render_page(pages[15])


def test_render_campaign_renders_all_sections() -> None:
    text = render_campaign(_campaign())
    assert "Galileo I/NAV page capture" in text
    assert "Snapshots:             1" in text
    assert "Pages:                 10 (10 unique)" in text
    assert "6, 7, 11, 12, 14, 15, 16, 20, 29, 36" in text
    assert "Application restored:  yes" in text
    assert "Captured page parts" in text
    assert "PRN    Ch  Part        Word  Valid" in text
    assert "OSNMA activity" in text
    assert "Checksum-verified words\n----------------------\n-" in text
    assert "Window decode audits" in text
    assert text.count("-") >= 2


def test_snapshot_activity_reports_presence_without_header_status() -> None:
    text = render_campaign(_campaign())
    assert " 11 " in text
    assert "test/0/end_of_chain" not in text
    assert "Observed" in text
    assert "yes" in text
    activity = _report(_campaign())["osnma_activity"]
    assert isinstance(activity, dict)
    assert activity["prns"][11]["observed_osnma"] is True
    assert activity["prns"][11]["headers"] == []


def test_campaign_report_lists_raw_sar_fields() -> None:
    fields = _report(_campaign())["sar_fields"]
    assert isinstance(fields, list)
    assert len(fields) == 3
    assert next(field for field in fields if field["prn"] == 11)["sar"] == "954918"


def test_render_word_row_shows_fields_and_timing() -> None:
    word = InavWord(
        word_type=4,
        content=bytes(16),
        iod_nav=58,
        svid=2,
        timing=None,
    )
    row = render_word(word)
    assert row == "   4      58     2       -  -"
    timed = InavWord(
        word_type=5,
        content=bytes(16),
        iod_nav=None,
        svid=None,
        timing=WordTiming(week_number=1248, time_of_week=345655),
    )
    assert render_word(timed) == "   5       -     -    1248  345655"


def test_render_audit_row_and_empty_section() -> None:
    audit = PageWindowAudit(
        prn=12,
        sync_offset=49,
        viterbi_errors=33,
        tail_valid=False,
        ssp=None,
        decoded=bytes.fromhex("130225b0d8d602c7b602e443db9340"),
    )
    row = render_audit(audit)
    assert row == (
        " 12    49      33  no        -  130225b0d8d602c7b602e443db9340"
    )
    text = render_campaign(_campaign(), audits=[audit])
    assert "Window decode audits" in text
    assert row in text
    empty = render_campaign(_campaign(), audits=[])
    assert "Window decode audits" in empty
    assert "Decoded\n-" in empty
