"""Optional interoperability checks against the external RTKLIB convbin tool."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from examples.rinex_navigation.__main__ import main as navigation_main

from test_extra_captures import captured
from tests.examples._new_api import observation, record
from um982py.rinex import export_rinex
from um982py.rinex_merge import merge_gps_observations


@pytest.fixture
def convbin() -> str:
    executable = os.environ.get("RTKLIB_CONVBIN") or shutil.which("convbin")
    if not executable:
        pytest.skip("set RTKLIB_CONVBIN to the RTKLIB convbin executable")
    return executable


def convert(convbin: str, source: Path, destination: Path, *, nav: bool) -> None:
    options = ["-r", "rinex", "-v", "3.05"]
    if nav:
        options += ["-n", str(destination)]
    else:
        options += ["-f", "5", "-od", "-os", "-o", str(destination)]
    subprocess.run(
        [convbin, *options, str(source)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def observations(path: Path) -> dict[tuple[str, str, str], float]:
    types: dict[str, list[str]] = {}
    values: dict[tuple[str, str, str], float] = {}
    system = epoch = ""
    for line in path.read_text(encoding="ascii").splitlines():
        if line[60:].strip() == "SYS / # / OBS TYPES":
            system = line[0] if line[0] != " " else system
            types.setdefault(system, []).extend(line[6:60].split())
        elif line.startswith(">"):
            parts = line[1:].split()
            epoch = " ".join(str(int(part)) for part in parts[:5])
            epoch += f" {float(parts[5]):.7f}"
        elif epoch and line[:1] in "GRSECJI" and line[1:3].isdigit():
            for index, code in enumerate(types[line[0]]):
                field = line[3 + 16 * index : 17 + 16 * index].strip()
                if field:
                    values[epoch, line[:3], code] = float(field)
    return values


def navigation(path: Path) -> dict[tuple[str, str], list[float | None]]:
    data = path.read_text(encoding="ascii").split("END OF HEADER", 1)[1]
    lines = [line for line in data.splitlines() if line.strip()]
    assert len(lines) % 8 == 0
    records: dict[tuple[str, str], list[float | None]] = {}
    for offset in range(0, len(lines), 8):
        rows = lines[offset : offset + 8]
        key = rows[0][:3], rows[0][4:23]
        assert key not in records
        fields: list[float | None] = []
        for index, row in enumerate(rows):
            start, count = (23, 3) if index == 0 else (4, 4)
            for column in range(count):
                field = row[start + 19 * column : start + 19 * (column + 1)].strip()
                fields.append(float(field.replace("D", "E")) if field else None)
        records[key] = fields
    return records


def test_rtklib_round_trip_preserves_captured_observations(
    convbin: str, tmp_path: Path
) -> None:
    source, output = tmp_path / "source.obs", tmp_path / "roundtrip.obs"
    source.write_text(export_rinex((captured("RANGE"),)).text, encoding="ascii")
    convert(convbin, source, output, nav=False)
    before, after = observations(source), observations(output)
    assert len(before) == 234
    assert before.keys() == after.keys()
    assert after == before


def test_rtklib_round_trip_preserves_two_epochs_and_loss_of_lock(
    convbin: str, tmp_path: Path
) -> None:
    source, output = tmp_path / "epochs.obs", tmp_path / "roundtrip.obs"
    records = (record(0, [observation(lock=100)]), record(1, [observation(lock=1)]))
    source.write_text(export_rinex(records).text, encoding="ascii")
    convert(convbin, source, output, nav=False)
    before, after = observations(source), observations(output)
    # RTKLIB represents zero Doppler as a missing observation on output.
    assert {key: value for key, value in before.items() if value != 0} == after
    input_lines = [
        line for line in source.read_text().splitlines() if line.startswith("G01")
    ]
    output_lines = [
        line for line in output.read_text().splitlines() if line.startswith("G01")
    ]
    assert len(input_lines) == len(output_lines) == 2
    assert input_lines[0][33] == " "
    assert input_lines[1][33] == output_lines[1][33] == "1"


def test_rtklib_round_trip_preserves_merged_segment_values_and_resets(
    convbin: str, tmp_path: Path
) -> None:
    first, second = tmp_path / "a.obs", tmp_path / "b.obs"
    merged, output = tmp_path / "merged.obs", tmp_path / "roundtrip.obs"
    first.write_text(export_rinex((record(0, [observation()]),)).text)
    second.write_text(export_rinex((record(1, [observation()]),)).text)
    result = merge_gps_observations((first, second), merged)
    assert result.boundary_phase_resets == 1
    convert(convbin, merged, output, nav=False)
    before, after = observations(merged), observations(output)
    assert {key: value for key, value in before.items() if value != 0} == after
    lines = [line for line in output.read_text().splitlines() if line.startswith("G01")]
    assert len(lines) == 2 and lines[1][33] == "1"


def test_rtklib_reads_known_gps_navigation_fields(convbin: str, tmp_path: Path) -> None:
    source, output = tmp_path / "source.nav", tmp_path / "roundtrip.nav"
    capture = Path(__file__).parent / "fixtures/captures/GPSEPHA.bin"
    assert navigation_main(["--replay", str(capture), "--output", str(source)]) == 0
    convert(convbin, source, output, nav=True)
    before, after = navigation(source), navigation(output)
    assert len(before) == 20
    assert before.keys() == after.keys()
    for key, fields in before.items():
        # RTKLIB changes the unknown transmission-time sentinel and treats
        # blank flags and fit interval as zero. Compare only known fields.
        assert fields[27] == 999999999.999
        for index, value in enumerate(fields):
            if value is not None and index != 27:
                assert after[key][index] == pytest.approx(value, rel=1e-11, abs=1e-12)
