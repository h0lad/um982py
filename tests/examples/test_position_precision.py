import json
from dataclasses import replace
from pathlib import Path

from examples.position_precision import __main__ as cli
from examples.position_precision import map_precision

from um982py import Log, load_records
from um982py.messages import Record

FIXTURE = Path(__file__).parents[1] / "fixtures/position-precision.txt"


def test_replay_maps_receiver_ellipse_for_each_antenna(tmp_path: Path) -> None:
    for antenna, expected in (("1", 1.67), ("2", 0.02)):
        report_path = tmp_path / f"report-{antenna}.json"
        map_path = tmp_path / f"map-{antenna}.json"
        assert (
            cli.main(
                [
                    "--replay",
                    str(FIXTURE),
                    "--antenna",
                    antenna,
                    "--reference-frame",
                    "WGS84",
                    "--json",
                    str(report_path),
                    "--geojson",
                    str(map_path),
                ]
            )
            == 0
        )
        report = json.loads(report_path.read_text())
        features = json.loads(map_path.read_text())["features"]
        assert report["matched_precision"] == 1
        precision = features[0]["properties"]["precision"]
        assert precision["ellipse"]["semi_major_m"] == expected
        assert precision["antenna"] == int(antenna)


def test_unmatched_and_ambiguous_statistics_are_never_attached() -> None:
    fixes = load_records(FIXTURE, Log.GPGGA)
    statistics = load_records(FIXTURE, Log.GPGST)
    no_match = replace(
        statistics[0],
        entries=tuple(
            (key, "120001" if key == "utc" else value)
            for key, value in statistics[0].entries
        ),
    )
    result = map_precision(fixes, [no_match])
    assert result["status"] == "no_matched_precision"
    feature = result["geojson"]["features"][0]
    assert feature["properties"]["precision"] is None
    # Byte-identical duplicates, such as GPGGA and GNGGA logs that both print
    # $GNGGA, are one observation. Differing content with one key stays
    # ambiguous and is never attached.
    result = map_precision(fixes * 2, statistics * 2)
    assert result["ambiguous_fixes"] == 0 and result["matched_precision"] == 1
    other_gst = _with(statistics[0], "rms", 9.99)
    result = map_precision(fixes, [statistics[0], other_gst])
    assert result["ambiguous_fixes"] == 1 and result["matched_precision"] == 0
    other_fix = _with(fixes[0], "satellites", 3)
    result = map_precision([fixes[0], other_fix], statistics)
    assert result["ambiguous_fixes"] == 2 and result["matched_precision"] == 0


def _with(record: Record, name: str, value: object) -> Record:
    return replace(
        record,
        entries=tuple(
            (key, value if key == name else old) for key, old in record.entries
        ),
    )
