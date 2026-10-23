"""Tests the position tracking example."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from examples.position_tracking import (
    Geofence,
    Track,
    TrackPoint,
    analyze_capture,
    collect_positions,
    dop_report,
    satellite_report,
    select_track,
    write_positions_csv,
)
from examples.position_tracking import __main__ as position_cli

from conftest import FIXTURES
from um982py.capture import decode_records, read_frames
from um982py.commands import Log
from um982py.messages.record import Record
from um982py.protocol import StreamDecoder

EQUATOR_DEGREE_METRES = 111194.9
LONDON = (51.5074, -0.1278)
PARIS = (48.8566, 2.3522)
LONDON_PARIS_METRES = 343556.0


def bestnav_record(path: Path) -> Record:
    command = Log.BESTNAV.read()
    frames = StreamDecoder().feed(path.read_bytes())
    return next(
        command.decode(message) for message in frames if command.matches(message)
    )


def pppnav_record(path: Path) -> Record:
    return decode_records(read_frames(path), Log.PPPNAV)[0]


def point(
    timestamp: float, latitude: float, longitude: float, speed: float = 0.0
) -> TrackPoint:
    return TrackPoint(timestamp, latitude, longitude, 250.0, speed, 12, "SINGLE")


def build_track(points: list[TrackPoint]) -> Track:
    track = Track()
    for fix in points:
        track = track.with_point(fix)
    return track


def test_one_degree_of_latitude_matches_published_arc_length() -> None:
    track = build_track([point(0.0, 0.0, 0.0), point(60.0, 1.0, 0.0)])
    assert track.distance == pytest.approx(EQUATOR_DEGREE_METRES, abs=1.0)


def test_london_to_paris_matches_published_distance() -> None:
    track = build_track([point(0.0, *LONDON), point(60.0, *PARIS)])
    assert track.distance == pytest.approx(LONDON_PARIS_METRES, rel=5e-3)


def test_distance_accumulates_every_leg() -> None:
    track = build_track(
        [point(0.0, 0.0, 0.0), point(60.0, 1.0, 0.0), point(120.0, 2.0, 0.0)]
    )
    assert track.distance == pytest.approx(2 * EQUATOR_DEGREE_METRES, abs=2.0)


def test_duration_spans_first_to_last_fix() -> None:
    track = build_track(
        [point(100.0, 0.0, 0.0), point(130.0, 0.0, 0.0), point(190.0, 0.0, 0.0)]
    )
    assert track.duration == pytest.approx(90.0, abs=1e-12)


def test_average_speed_divides_distance_by_duration() -> None:
    track = build_track([point(0.0, 0.0, 0.0), point(60.0, 1.0, 0.0)])
    assert track.average_speed == pytest.approx(EQUATOR_DEGREE_METRES / 60, rel=1e-4)


def test_speed_statistics_summarise_reported_speed() -> None:
    track = build_track(
        [
            point(0.0, 0.0, 0.0, speed=1.0),
            point(1.0, 0.0, 0.0, speed=2.0),
            point(2.0, 0.0, 0.0, speed=3.0),
        ]
    )
    statistics = track.speed_statistics
    assert statistics.mean == pytest.approx(2.0, abs=1e-12)
    assert statistics.minimum == pytest.approx(1.0, abs=1e-12)
    assert statistics.maximum == pytest.approx(3.0, abs=1e-12)
    assert statistics.standard_deviation == pytest.approx(1.0, abs=1e-12)


def test_bounding_box_covers_every_fix() -> None:
    track = build_track(
        [
            point(0.0, 10.0, 20.0),
            point(1.0, 12.0, 19.0),
            point(2.0, 11.0, 21.0),
        ]
    )
    bounds = track.bounds
    assert bounds.minimum_latitude == pytest.approx(10.0, abs=1e-12)
    assert bounds.maximum_latitude == pytest.approx(12.0, abs=1e-12)
    assert bounds.minimum_longitude == pytest.approx(19.0, abs=1e-12)
    assert bounds.maximum_longitude == pytest.approx(21.0, abs=1e-12)


def test_geofence_excludes_fixes_beyond_the_radius() -> None:
    fence = Geofence(0.0, 0.0, 150.0)
    inside = point(0.0, 0.001, 0.0)
    outside = point(1.0, 0.002, 0.0)
    assert fence.contains(inside)
    assert not fence.contains(outside)
    assert build_track([inside, outside, inside]).outside(fence) == (outside,)


def test_geofence_rejects_a_nonpositive_radius() -> None:
    with pytest.raises(ValueError):
        Geofence(0.0, 0.0, 0.0)


def test_bestnava_fixture_reports_the_captured_position_type() -> None:
    fix = TrackPoint.from_record(bestnav_record(FIXTURES / "bodies" / "BESTNAVA.bin"))
    assert fix.position_type == "SINGLE"
    assert fix.satellites == 31
    assert fix.altitude == pytest.approx(74.0, abs=1e-9)
    assert fix.timestamp > 0


def test_geojson_coordinates_are_longitude_then_latitude() -> None:
    track = build_track([point(0.0, 10.0, 20.0), point(5.0, 11.0, 21.0)])
    document = json.loads(json.dumps(track.geojson()))
    assert document["type"] == "FeatureCollection"
    path, *fixes = document["features"]
    assert path["geometry"]["type"] == "LineString"
    assert path["geometry"]["coordinates"] == [[20.0, 10.0], [21.0, 11.0]]
    assert [feature["geometry"]["coordinates"] for feature in fixes] == [
        [20.0, 10.0],
        [21.0, 11.0],
    ]
    assert fixes[0]["geometry"]["type"] == "Point"


def test_geojson_of_one_fix_has_no_line_string() -> None:
    document = json.loads(json.dumps(build_track([point(0.0, 10.0, 20.0)]).geojson()))
    assert [feature["geometry"]["type"] for feature in document["features"]] == [
        "Point"
    ]


def test_empty_track_report_has_no_derived_values() -> None:
    report = json.loads(json.dumps(Track().report()))
    assert report["fixes"] == 0
    assert report["distance_m"] == pytest.approx(0.0, abs=1e-12)
    assert report["average_speed_m_s"] is None
    assert report["bounding_box"] is None


def test_report_counts_fixes_outside_the_fence() -> None:
    fence = Geofence(0.0, 0.0, 150.0)
    track = build_track([point(0.0, 0.0, 0.0), point(1.0, 0.002, 0.0)])
    report = json.loads(json.dumps(track.report(fence)))
    assert report["outside_fence"] == 1
    assert report["bounding_box"]["maximum_latitude"] == pytest.approx(0.002, abs=1e-12)


def test_default_mode_replays_bestnav_positions(tmp_path: Path) -> None:
    report_path = tmp_path / "positions.json"
    assert (
        position_cli.main(
            [
                "--replay",
                str(FIXTURES / "captures-live" / "BESTNAVA.bin"),
                "--json",
                str(report_path),
            ]
        )
        == 0
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["source"] == "BESTNAV"
    assert report["precision_service"] is None
    assert report["status"] == "positioning"
    assert report["fixes"] == len(report["positions"]) > 1
    assert report["latest_fix"]["speed"] is not None


def test_public_analysis_and_csv_work_without_the_cli(tmp_path: Path) -> None:
    record = bestnav_record(FIXTURES / "bodies" / "BESTNAVA.bin")
    result = analyze_capture({"BESTNAV": (record,)}, fence=Geofence(0.0, 0.0, 1.0))
    assert result.status == "positioning"
    assert result.exit_code == 0
    assert result.report["outside_fence"] == 1
    assert result.track.points[0].source == "BESTNAV"
    destination = tmp_path / "nested" / "track.csv"
    write_positions_csv(result.track, str(destination))
    assert len(destination.read_text(encoding="utf-8").splitlines()) == 2


def test_stale_fixed_position_is_reported_without_claiming_current_precision() -> None:
    original = bestnav_record(FIXTURES / "bodies" / "BESTNAVA.bin")
    entries = tuple(
        (
            name,
            "NARROW_INT"
            if name == "pos_type"
            else 419.0
            if name == "diff_age"
            else value,
        )
        for name, value in original.entries
    )
    result = analyze_capture({"BESTNAV": (replace(original, entries=entries),)})
    assert result.status == "stale_corrections"
    assert result.exit_code == 1
    assert result.report["latest_fix"]["correction_age_s"] == 419.0


def test_precision_replay_reports_convergence_and_writes_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report_path = tmp_path / "ppp.json"
    csv_path = tmp_path / "ppp.csv"
    geojson_path = tmp_path / "ppp.geojson"
    assert (
        position_cli.main(
            [
                "--replay",
                str(FIXTURES / "captures-extra" / "PPPNAVB.bin"),
                "--precision-service",
                "AUTO",
                "--json",
                str(report_path),
                "--csv",
                str(csv_path),
                "--geojson",
                str(geojson_path),
                "--debug",
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert output.out == ""
    assert "mode=PPP AUTO" in output.err
    assert "PPPNAV PPP_CONVERGING" in output.err
    assert report["status"] == "converging"
    assert report["source"] == "PPPNAV"
    assert report["positions"][0]["speed"] is None
    assert report["positions"][0]["latitude_sigma_m"] is not None
    assert report["positions"][0]["height_msl"] == pytest.approx(74.0)
    assert report["positions"][0]["height_ellipsoid_m"] == pytest.approx(110.0)
    assert report["speed_m_s"]["mean"] is None
    assert len(csv_path.read_text(encoding="utf-8").splitlines()) == 2
    assert len(json.loads(geojson_path.read_text(encoding="utf-8"))["features"]) == 1


def test_full_ppp_fix_is_a_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = pppnav_record(FIXTURES / "captures-extra" / "PPPNAVB.bin")
    full = Record(
        record.name,
        tuple(
            (name, 69 if name == "pos_type" else value)
            for name, value in record.items()
        ),
        record.message,
    )
    monkeypatch.setattr(
        position_cli,
        "capture_records",
        lambda *_args, **_kwargs: {"BESTNAV": (), "PPPNAV": (full,)},
    )
    report_path = tmp_path / "full.json"
    assert (
        position_cli.main(
            ["--precision-service", "B2B-PPP", "--json", str(report_path)]
        )
        == 0
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "ppp_solution"
    assert report["fix_classes"] == {"PPP": 1}


def test_precision_track_rejects_other_solutions_and_duplicate_epochs() -> None:
    record = pppnav_record(FIXTURES / "captures-extra" / "PPPNAVB.bin")

    def changed(**values: object) -> Record:
        return Record(
            record.name,
            tuple((name, values.get(name, value)) for name, value in record.items()),
            record.message,
        )

    full = changed(pos_type=69)
    track, rejected = collect_positions(
        (changed(sol_status=1), changed(pos_type=16), full, full),
        ppp=True,
    )
    assert len(track.points) == 1
    assert track.points[0].position_type == "PPP"
    assert rejected == {
        "solution_not_computed": 1,
        "not_ppp": 1,
        "non_increasing_epoch": 1,
    }


def test_auto_mode_switches_to_full_ppp_and_keeps_earlier_bestnav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    best = bestnav_record(FIXTURES / "bodies" / "BESTNAVA.bin")
    ppp = pppnav_record(FIXTURES / "captures-extra" / "PPPNAVB.bin")

    def at(record: Record, milliseconds: int, **changes: object) -> Record:
        assert record.message is not None
        message = replace(
            record.message,
            header=replace(record.message.header, week=2441, milliseconds=milliseconds),
        )
        entries = tuple(
            (name, changes.get(name, value)) for name, value in record.items()
        )
        return Record(record.name, entries, message)

    captured = {
        "BESTNAV": (at(best, 1000), at(best, 3000)),
        "PPPNAV": (at(ppp, 2000, pos_type=69), at(ppp, 3000, pos_type=69)),
        "STADOP": (),
        "PPPDOP": (),
        "SATSINFO": (),
    }

    def capture(*args: object, **_kwargs: object) -> dict[str, tuple[Record, ...]]:
        assert {log.value for log in args[1]} == {
            "BESTNAV",
            "PPPNAV",
            "STADOP",
            "PPPDOP",
            "SATSINFO",
        }
        return captured

    monkeypatch.setattr(position_cli, "capture_records", capture)
    report_path = tmp_path / "auto.json"
    assert position_cli.main(["--json", str(report_path)]) == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "ppp_solution"
    assert report["source"] == "PPPNAV"
    assert [row["source"] for row in report["positions"]] == [
        "BESTNAV",
        "PPPNAV",
        "PPPNAV",
    ]
    assert report["source_switches"] == [
        {"time_gps_s": report["first_ppp_gps_s"], "source": "PPPNAV"}
    ]


def test_converging_ppp_does_not_replace_available_bestnav() -> None:
    best = Track((replace(point(1.0, 0.0, 0.0), source="BESTNAV"),))
    ppp = Track(
        (
            replace(
                point(1.0, 0.0, 0.0),
                source="PPPNAV",
                position_type="PPP_CONVERGING",
            ),
        )
    )
    selected, first_ppp = select_track(best, ppp)
    assert selected.points == best.points
    assert first_ppp is None


def test_bestnav_fills_gap_after_full_ppp() -> None:
    best = Track(
        (
            replace(point(1.0, 0.0, 0.0), source="BESTNAV"),
            replace(point(3.0, 0.0, 0.0), source="BESTNAV"),
        )
    )
    ppp = Track((replace(point(2.0, 0.0, 0.0), source="PPPNAV", position_type="PPP"),))
    selected, first_ppp = select_track(best, ppp)
    assert [row.source for row in selected.points] == ["BESTNAV", "PPPNAV", "BESTNAV"]
    assert first_ppp == 2.0


def test_public_selection_rejects_unordered_input() -> None:
    with pytest.raises(ValueError, match="increasing epochs"):
        select_track(Track((point(2.0, 0.0, 0.0), point(1.0, 0.0, 0.0))), Track())


def test_precision_statistics_and_satellite_signal_report() -> None:
    track = Track(
        (
            replace(
                point(1.0, 0.0, 0.0),
                latitude_sigma_m=0.2,
                longitude_sigma_m=0.3,
                height_sigma_m=0.5,
                solution_satellites=12,
            ),
            replace(
                point(2.0, 0.0, 0.0),
                latitude_sigma_m=0.4,
                longitude_sigma_m=0.5,
                height_sigma_m=0.7,
                solution_satellites=14,
            ),
        )
    )
    precision = track.report()["precision_statistics"]
    assert precision["latitude_sigma_m"]["mean"] == pytest.approx(0.3)
    assert precision["height_sigma_m"]["p95"] == pytest.approx(0.69)
    assert precision["solution_satellites"]["maximum"] == 14
    satellite = decode_records(
        read_frames(FIXTURES / "bodies" / "SATSINFOA.bin"), Log.SATSINFO
    )[0]
    report = satellite_report((satellite,))
    assert report["statistics"]["frames"] == 1
    assert report["statistics"]["unique_satellites"] == 30
    assert report["epochs"][0]["satellites"][0]["frequencies"]


def test_dop_report_keeps_epochs_and_valid_statistics() -> None:
    nav = bestnav_record(FIXTURES / "bodies" / "BESTNAVA.bin")
    record = Record(
        "STADOP",
        (
            ("gdop", 1.4),
            ("pdop", 1.2),
            ("tdop", 0.8),
            ("vdop", 1.0),
            ("hdop", 0.7),
            ("ndop", 0.5),
            ("edop", 0.4),
            ("cutoff", 5.0),
            ("count_prn", 2),
            ("prn", (5, 7)),
        ),
        nav.message,
    )
    report = dop_report({"STADOP": (record,)})
    assert report["epochs"][0]["used_prns"] == [5, 7]
    assert report["statistics"]["STADOP"]["hdop"]["mean"] == pytest.approx(0.7)


def test_secondary_ppp_navigation_is_recognized() -> None:
    import json
    from pathlib import Path

    from examples.position_tracking.analysis import analyze_capture

    from um982py.commands import Log
    from um982py.protocol import StreamDecoder

    samples = json.loads(
        (Path(__file__).parents[1] / "fixtures/manual-examples-r1.15.json").read_text()
    )
    raw = (samples["PPPNAVHA"] + "\r\n").encode()
    record = Log.PPPNAVH.decode(StreamDecoder(strict=True).feed(raw)[0])
    result = analyze_capture({"PPPNAV": (record,)})
    assert result.status == "ppp_solution"
    assert result.report["source"] == "PPPNAVH"
