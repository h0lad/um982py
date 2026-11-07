import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from test_bodies import manual_message
from um982py.messages import Record, decode_log
from um982py.messages.frames import AsciiHeader, AsciiMessage
from um982py.protocol import StreamDecoder
from um982py.rinex_nav import export_rinex_navigation


def sample() -> Record:
    return decode_log(manual_message("GPSEPHA"))


def timed_sample(name: str) -> Record:
    samples = json.loads(
        (Path(__file__).parent / "fixtures/manual-examples-r1.4.json").read_text()
    )
    message = StreamDecoder(strict=True).feed((samples[name] + "\r\n").encode())[0]
    return decode_log(message)


def fields(line: str, start: int = 4) -> list[float | None]:
    return [
        float(part.replace("D", "E")) if part.strip() else None
        for part in (line[i : i + 19] for i in range(start, len(line), 19))
    ]


def test_manual_gps_ephemeris_export() -> None:
    record = sample()
    result = export_rinex_navigation([record])
    body = result.text.split("END OF HEADER\n", 1)[1].splitlines()
    assert result.messages == 1 and len(body) == 8
    assert body[0][:23] == "G10 2021 12 30 06 00 00"
    assert fields(body[0], 23) == pytest.approx(
        [record.real("af0"), record.real("af1"), record.real("af2")]
    )
    assert fields(body[1]) == pytest.approx(
        [30, record.real("crs"), record.real("delta_n"), record.real("m0")]
    )
    assert fields(body[2])[3] == pytest.approx(math.sqrt(record.real("a")))
    assert fields(body[5]) == [record.real("idot"), None, 2190, None]
    # The receiver reports URA in square metres; RINEX uses metres.
    assert fields(body[6])[0] == pytest.approx(2.0)
    assert fields(body[7]) == [999999999.999, None, None, None]
    assert all(len(line) == 80 for line in body)


def test_week_boundary_and_reject_inconsistent_ephemeris() -> None:
    record = sample()
    data = dict(record.entries)
    data.update(week=2190, tow=10.0, toe=604790.0, toc=604790.0)
    changed = replace(record, entries=tuple(data.items()))
    body = (
        export_rinex_navigation([changed])
        .text.split("END OF HEADER\n", 1)[1]
        .splitlines()
    )
    assert fields(body[5])[2] == 2189
    data["iode2"] = data["iode1"] + 1
    with pytest.raises(ValueError, match="issue"):
        export_rinex_navigation([replace(record, entries=tuple(data.items()))])
    with pytest.raises(ValueError, match="unsupported"):
        export_rinex_navigation([replace(record, name="GLOEPH")])


def test_galileo_and_beidou_against_dlr_broadcast_records() -> None:
    galileo = timed_sample("GALEPHA")
    beidou = timed_sample("BDSEPHA")
    with pytest.raises(ValueError, match="time scale"):
        export_rinex_navigation([beidou])
    result = export_rinex_navigation([galileo, beidou], bdseph_time_scale="BDT")
    actual = result.text.split("END OF HEADER\n", 1)[1].splitlines()
    reference = (
        (Path(__file__).parent / "fixtures/dlr_nav_2021364.txt")
        .read_text()
        .splitlines()
    )
    assert result.messages == 3 and len(actual) == len(reference) == 24
    assert "galileo_inav_source_signals" in result.unknown_fields
    for block in range(3):
        start = block * 8
        assert actual[start][:23] == reference[start][:23]
        for row in range(8):
            ours = fields(actual[start + row], 23 if row == 0 else 4)
            published = fields(reference[start + row], 23 if row == 0 else 4)
            for column, (value, expected) in enumerate(
                zip(ours, published, strict=True)
            ):
                # The receiver does not identify the I/NAV source signals or
                # establish the transmission time; blank fields stay unknown.
                if value is None or (row == 7 and column == 0):
                    continue
                if block == 0 and row == 5 and column == 1:
                    assert value == 512 and expected == 517
                    continue
                assert expected is not None
                assert value == pytest.approx(expected, rel=5e-4, abs=1e-15)


def test_beidou_gpst_conversion_crosses_week_boundary() -> None:
    record = timed_sample("BDSEPHA")
    values = dict(record.entries)
    values.update(toe=10.0, toc=10.0, week=2190)
    assert isinstance(record.message, AsciiMessage)
    assert isinstance(record.message.header, AsciiHeader)
    message = replace(
        record.message, header=replace(record.message.header, milliseconds=20000)
    )
    changed = replace(record, entries=tuple(values.items()), message=message)
    lines = (
        export_rinex_navigation([changed], bdseph_time_scale="GPST")
        .text.split("END OF HEADER\n", 1)[1]
        .splitlines()
    )
    assert fields(lines[3])[0] == 604796
    assert fields(lines[5])[2] == 833


def test_galileo_rejects_missing_health_and_unavailable_sisa() -> None:
    record = timed_sample("GALEPHA")
    values = dict(record.entries)
    values["inavreceived"] = "FALSE"
    with pytest.raises(ValueError, match="both F/NAV and I/NAV"):
        export_rinex_navigation([replace(record, entries=tuple(values.items()))])
    values["inavreceived"] = "TRUE"
    values["sisa"] = 255
    with pytest.raises(ValueError, match="SISA"):
        export_rinex_navigation([replace(record, entries=tuple(values.items()))])


def test_navigation_cli_replays_capture(tmp_path: Path) -> None:
    from examples.rinex_navigation.__main__ import main

    source = Path(__file__).parent / "fixtures/captures/GPSEPHA.bin"
    output = tmp_path / "gps.rnx"
    report = tmp_path / "gps.json"
    assert (
        main(["--replay", str(source), "--output", str(output), "--json", str(report)])
        == 0
    )
    assert "N: GNSS NAV DATA" in output.read_text()
    assert "END OF HEADER" in output.read_text()
    data = json.loads(report.read_text())
    assert data["messages"] > 0
    assert data["unknown_fields"] == [
        "l2_codes",
        "l2_p_data_flag",
        "fit_interval",
        "transmission_time",
    ]
