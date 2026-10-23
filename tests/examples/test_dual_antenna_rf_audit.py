"""Checks antenna pairing against explicitly assigned native observations."""

import json
from pathlib import Path

import pytest
from examples.dual_antenna_rf_audit import (
    compare_antennas,
    summarize_by_elevation,
    summarize_by_signal,
)
from examples.dual_antenna_rf_audit.__main__ import main

from tests.examples._new_api import observation, record, wire
from um982py.messages import Record


def test_paired_differences_median_mad_and_sign_reversal() -> None:
    first = [record(i, [observation(cn0=c)]) for i, c in enumerate((42, 44, 48))]
    second = [record(i, [observation(cn0=40)], secondary=True) for i in range(3)]
    result = compare_antennas(first, second)
    assert [pair.difference_db for pair in result.pairs] == [2, 4, 8]
    assert result.satellites[0].median_difference_db == 4
    assert result.satellites[0].mad_difference_db == 2
    assert compare_antennas(second, first).satellites[0].median_difference_db == -4


def test_unsynchronized_frames_and_l2c_components_are_not_paired() -> None:
    primary = [record(0, [observation(signal=9, l2c=1)]), record(1, [observation()])]
    secondary = [record(0, [observation(signal=9)]), record(2, [observation()])]
    result = compare_antennas(primary, secondary)
    assert result.pairs == ()
    assert result.matched_epochs == 1
    assert result.selected_only_observations == result.other_only_observations == 2


def test_unknown_signal_retained_invalid_cn0_and_unlock_excluded() -> None:
    rows = [
        observation(signal=31),
        observation(prn=2, valid=False),
        observation(prn=3, cn0=0),
    ]
    result = compare_antennas([record(0, rows)], [record(0, rows)])
    assert len(result.pairs) == 1
    assert result.satellites[0].signal_name == "unknown"


def test_duplicate_epochs_rejected() -> None:
    value = record(0, [observation()])
    with pytest.raises(ValueError, match="strictly increasing"):
        compare_antennas([value, value], [value])


def test_cli_secondary_reverses_sign_without_aliasing_both_inputs(
    tmp_path: Path,
) -> None:
    path, output = tmp_path / "dual.bin", tmp_path / "result.json"
    pair_csv, elevation_csv = tmp_path / "pairs.csv", tmp_path / "elevation.csv"
    measurements_csv = tmp_path / "measurements.csv"
    path.write_bytes(
        wire(0, [observation(cn0=47)]) + wire(0, [observation(cn0=40)], secondary=True)
    )
    assert (
        main(
            [
                "--replay",
                str(path),
                "--antenna",
                "2",
                "--json",
                str(output),
                "--pairs-csv",
                str(pair_csv),
                "--elevation-csv",
                str(elevation_csv),
                "--measurements-csv",
                str(measurements_csv),
            ]
        )
        == 0
    )
    data = json.loads(output.read_text())
    assert data["selected_antenna"] == 2
    assert data["pairs"][0]["difference_db"] == -7
    assert pair_csv.read_text().splitlines()[-1].endswith(",-7.000")
    assert elevation_csv.read_text().splitlines()[0].startswith("system,signal")
    assert data["measurement_pairs"][0]["cn0_difference_db"] == -7
    assert "raw_phase_difference_cycles" in measurements_csv.read_text()


def test_fdma_channel_change_prevents_pairing() -> None:
    first = record(0, [observation(system=1, channel=6)])
    second = record(0, [observation(system=1, channel=7)])
    assert not compare_antennas([first], [second]).pairs


def test_signal_band_summary_aggregates_across_satellites() -> None:
    first = [
        record(
            0,
            [
                observation(prn=5, system=3, signal=22, cn0=44.0),
                observation(prn=8, system=3, signal=22, cn0=46.0),
            ],
        )
    ]
    second = [
        record(
            0,
            [
                observation(prn=5, system=3, signal=22, cn0=34.0),
                observation(prn=8, system=3, signal=22, cn0=34.0),
            ],
            secondary=True,
        )
    ]
    comparison = compare_antennas(first, second)
    bands = summarize_by_signal(comparison)
    assert len(bands) == 1
    assert bands[0].constellation == "GALILEO"
    assert bands[0].signal_name == "E6 C"
    assert bands[0].frequency_hz == 1278750000.0
    assert bands[0].satellites == 2
    assert bands[0].pairs == 2
    assert bands[0].median_difference_db == 11.0
    assert bands[0].mad_difference_db == 1.0


def test_elevation_summary_uses_satellites_as_its_distribution_units() -> None:
    first = [
        record(0, [observation(prn=1, cn0=42), observation(prn=2, cn0=48)]),
        record(1, [observation(prn=1, cn0=44)]),
    ]
    second = [
        record(
            0, [observation(prn=1, cn0=40), observation(prn=2, cn0=40)], secondary=True
        ),
        record(1, [observation(prn=1, cn0=40)], secondary=True),
    ]
    visibility = [
        Record(
            "SATVIS2",
            (
                ("constellation", "GPS"),
                (
                    "satellites",
                    tuple(
                        Record("satellite", (("prn", prn), ("elevation", 35.0)))
                        for prn in prns
                    ),
                ),
            ),
            source.message,
        )
        for source, prns in ((first[0], (1, 2)), (first[1], (1,)))
    ]
    summaries = summarize_by_elevation(compare_antennas(first, second), visibility)
    assert len(summaries) == 1
    assert summaries[0].elevation_min_deg == 30
    assert summaries[0].pairs == 3
    assert summaries[0].satellites == 2
    assert summaries[0].median_difference_db == 5.5
    assert summaries[0].satellite_p10_db == pytest.approx(3.5)
    assert summaries[0].satellite_p90_db == pytest.approx(7.5)
