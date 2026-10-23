import math
from dataclasses import replace
from pathlib import Path

import pytest

from test_bodies import manual_message
from um982py.messages import Record, decode_log
from um982py.rinex_nav import export_rinex_navigation


def sample() -> Record:
    return decode_log(manual_message("GPSEPHA"))


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
    assert fields(body[6])[0] == pytest.approx(2.0)  # receiver URA is m²
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
    with pytest.raises(ValueError, match="GPSEPH"):
        export_rinex_navigation([replace(record, name="BDSEPH")])


def test_navigation_cli_replays_capture(tmp_path: Path) -> None:
    from examples.rinex_navigation.__main__ import main

    source = Path(__file__).parent / "fixtures/captures/GPSEPHA.bin"
    output = tmp_path / "gps.rnx"
    assert main(["--replay", str(source), "--output", str(output)]) == 0
    assert "N: GNSS NAV DATA" in output.read_text()
    assert "END OF HEADER" in output.read_text()
