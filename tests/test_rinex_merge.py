"""Check bounded-session GPS RINEX merging and conservative arc boundaries."""

from pathlib import Path

import pytest

from test_rinex_rtklib import observations
from tests.examples._new_api import observation, record
from um982py.rinex import RinexMetadata, export_rinex
from um982py.rinex_merge import merge_gps_observations


def _write(path: Path, epochs: tuple, *, antenna: str = "TEST") -> None:
    path.write_text(
        export_rinex(epochs, metadata=RinexMetadata(antenna_type=antenna)).text,
        encoding="ascii",
    )


def test_merge_preserves_values_and_resets_phase_at_segment_boundaries(
    tmp_path: Path,
) -> None:
    first, second, output = (
        tmp_path / name for name in ("a.obs", "b.obs", "merged.obs")
    )
    _write(
        first,
        (
            record(0, [observation(), observation(prn=7, system=3, signal=22)]),
            record(1, [observation()]),
        ),
    )
    _write(
        second,
        (
            record(
                2, [observation(), observation(prn=2, signal=17, frequency=1227.60e6)]
            ),
            record(3, [observation()]),
        ),
    )
    result = merge_gps_observations((first, second), output)
    assert result.epochs == 4 and result.gps_satellite_records == 5
    assert result.non_gps_satellite_records == 1 and result.boundary_phase_resets == 2
    expected = {
        key: value
        for path in (first, second)
        for key, value in observations(path).items()
        if key[1].startswith("G")
    }
    assert observations(output) == expected
    lines = output.read_text().splitlines()
    header = [line for line in lines if line[60:].strip() == "SYS / # / OBS TYPES"]
    assert len(header) == 1 and header[0].startswith("G")
    codes = header[0][7:60].split()
    gps1 = [line for line in lines if line.startswith("G01")]
    index = codes.index("L1C")
    assert gps1[0][3 + 16 * index + 14] == " "
    assert gps1[2][3 + 16 * index + 14] == "1"
    assert gps1[3][3 + 16 * index + 14] == " "
    assert all(
        line[0] != "E" for line in lines if len(line) >= 3 and line[1:3].isdigit()
    )


def test_merge_rejects_overlap_and_metadata_changes_without_writing_output(
    tmp_path: Path,
) -> None:
    first, second, output = (
        tmp_path / name for name in ("a.obs", "b.obs", "merged.obs")
    )
    _write(first, (record(0, [observation()]),))
    _write(second, (record(0, [observation()]),))
    with pytest.raises(ValueError, match="overlap"):
        merge_gps_observations((first, second), output)
    assert not output.exists()
    _write(second, (record(1, [observation()]),), antenna="OTHER")
    with pytest.raises(ValueError, match="metadata"):
        merge_gps_observations((first, second), output)
    assert not output.exists()
