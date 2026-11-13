import json
from dataclasses import replace
from pathlib import Path

from examples.position_precision import __main__ as cli
from examples.position_precision import map_precision

from um982py import Log, load_records

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
    result = map_precision(fixes, statistics * 2)
    assert result["ambiguous_fixes"] == 1 and result["matched_precision"] == 0
    result = map_precision(fixes * 2, statistics)
    assert result["ambiguous_fixes"] == 2 and result["matched_precision"] == 0
