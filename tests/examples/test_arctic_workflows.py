import json
from pathlib import Path

from examples.gnss_reflectometry.snow_series import main as snow
from examples.research_session.compare_reference import main as compare


def test_snow_height_and_rejected_arc(tmp_path: Path) -> None:
    arcs = tmp_path / "arcs.csv"
    arcs.write_text(
        "antenna,system,prn,signal,direction,start_gps_s,end_gps_s,height_m,height_resolution_m,rejection\nANT1,0,1,0,rising,100,200,1.5,0.1,\nANT1,0,2,0,rising,100,200,,,low_snr\n"
    )
    field = tmp_path / "field.csv"
    field.write_text("gps_seconds,snow_depth_m\n151,0.4\n")
    output = tmp_path / "snow.json"
    assert (
        snow(
            [
                "--arcs",
                str(arcs),
                "--antenna",
                "ANT1",
                "--baseline-height-m",
                "2",
                "--field",
                str(field),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    data = json.loads(output.read_text())
    assert data["accepted_arcs"][0]["snow_height_proxy_m"] == 0.5
    assert abs(data["accepted_arcs"][0]["proxy_minus_field_m"] - 0.1) < 1e-12
    assert data["rejected_arcs"][0]["rejection"] == "low_snr"


def test_reference_comparison_does_not_interpolate(tmp_path: Path) -> None:
    observed, reference, output = (
        tmp_path / x for x in ("obs.csv", "ref.csv", "output.json")
    )
    observed.write_text("gps_seconds,x_m,y_m,z_m\n100,1,2,3\n200,1,2,3\n")
    reference.write_text("gps_seconds,x_m,y_m,z_m\n100.2,1,2,4\n")
    assert (
        compare(
            [
                "--observed",
                str(observed),
                "--reference",
                str(reference),
                "--reference-frame",
                "ITRF2020",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    data = json.loads(output.read_text())
    assert data["matches"][0]["ecef_difference_m"] == [0, 0, -1]
    assert data["unmatched_observed_epochs"] == [200]
    assert data["same_point_asserted_by_user"] is False


def test_ice_motion_velocity_and_gap(tmp_path: Path) -> None:
    from examples.ice_motion.__main__ import main

    source, output = tmp_path / "positions.csv", tmp_path / "motion.json"
    source.write_text(
        "gps_seconds,x_m,y_m,z_m\n100,6378137,0,0\n101,6378137,2,0\n110,6378137,3,0\n"
    )
    assert (
        main(
            [
                "--input",
                str(source),
                "--output",
                str(output),
                "--reference-frame",
                "ITRF2020",
                "--max-gap-s",
                "2",
            ]
        )
        == 0
    )
    samples = json.loads(output.read_text())["samples"]
    assert samples[1]["displacement_enu_m"] == [2.0, 0.0, 0.0]
    assert samples[1]["velocity_enu_mps"] == [2.0, 0.0, 0.0]
    assert samples[2]["velocity_ecef_mps"] is None


def test_polar_replay_reports_code_proxy(tmp_path: Path) -> None:
    from examples.polar_ionosphere.__main__ import main

    output = tmp_path / "polar.json"
    assert (
        main(
            [
                "--replay",
                "tests/fixtures/captures-extra/RANGEB.bin",
                "--json",
                str(output),
            ]
        )
        == 0
    )
    data = json.loads(output.read_text())
    assert data["timeline"]
    assert "code_slant_tec_proxy_tecu" in data["timeline"][0]
    assert "not a calibrated scintillation index" in data["limitations"]


def test_compare_dual_antenna_elevation_bins(tmp_path: Path) -> None:
    from examples.dual_antenna_rf_audit.compare_passes import main

    earlier, later, output = (tmp_path / x for x in ("a.csv", "b.csv", "out.json"))
    header = (
        "system,signal,l2c_flag,elevation_min_deg,elevation_max_deg,"
        "satellites,pairs,median_difference_db,satellite_p10_db,satellite_p90_db\n"
    )
    earlier.write_text(header + "0,0,0,0,15,2,5,1.5,0,3\n")
    later.write_text(header + "0,0,0,0,15,2,5,2.0,0,3\n")
    assert (
        main(
            [
                "--earlier",
                str(earlier),
                "--later",
                str(later),
                "--earlier-note",
                "snow",
                "--later-note",
                "water",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text())["matched_bins"][0]["change_db"] == 0.5
