import csv
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from conftest import sentence
from test_bodies import manual_message
from um982py import (
    ErrorEllipse,
    Fix,
    Log,
    Position,
    PositionPrecision,
    PppSolution,
    RoverPosition,
    TrackWriter,
    geojson_feature,
    navsatfix,
)
from um982py.messages import BestNavigation, Record, decode_log
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.protocol.ascii import parse_ascii


def gst(*, utc: str = "120000.00", secondary: bool = False) -> Record:
    name = "GNGSTH" if secondary else "GNGST"
    frame = sentence(f"{name},{utc},0.67,1.67,1.37,115.38,1.432,1.620,3.399".encode())
    return decode_log(parse_ascii(frame))


def fix(*, utc: str = "120000", secondary: bool = False) -> Fix:
    name = "GNGGAH" if secondary else "GNGGA"
    frame = sentence(
        f"{name},{utc},5232.0,N,01322.0,E,4,17,1.3,38.0,M,36.0,M,1.0,1".encode()
    )
    return Fix.from_message(parse_ascii(frame))


def bestnav() -> BestNavigation:
    return replace(
        BestNavigation.from_record(decode_log(manual_message("BESTNAVA"))),
        solution_status=SolutionStatus.SOL_COMPUTED,
        position_type=PositionType.SINGLE,
        datum="WGS84",
        latitude_std_m=2.0,
        longitude_std_m=3.0,
        height_std_m=4.0,
    )


def ppp() -> PppSolution:
    return PppSolution.from_record(Log.PPPNAV.decode(manual_message("PPPNAVA")))


def test_gst_matches_fix_epoch_and_antenna_without_inventing_confidence() -> None:
    original = fix()
    assert original.precision is None and original.antenna == 1
    enriched = original.with_gst(gst())
    precision = enriched.precision
    assert precision is not None
    assert (precision.east_std_m, precision.north_std_m, precision.up_std_m) == (
        1.620,
        1.432,
        3.399,
    )
    assert precision.horizontal_rms_m == pytest.approx((1.620**2 + 1.432**2) ** 0.5)
    assert precision.ellipse == ErrorEllipse(1.67, 1.37, 115.38)
    assert precision.pseudorange_rms_m == 0.67
    assert precision.epoch_gps_seconds is None and precision.utc == "120000.00"
    assert original.precision is None
    assert replace(enriched, utc="120001").precision is None
    assert replace(enriched, antenna=2).precision is None
    assert replace(enriched, quality=0).precision is None
    assert fix(secondary=True).with_gst(gst(secondary=True)).precision is not None
    with pytest.raises(ValueError, match="UTC times"):
        original.with_gst(gst(utc="120001"))
    with pytest.raises(ValueError, match="same antenna"):
        original.with_gst(gst(secondary=True))
    with pytest.raises(ValueError, match="same antenna"):
        replace(original, antenna=None).with_gst(gst())
    with pytest.raises(ValueError, match="valid fix"):
        replace(original, quality=0).with_gst(gst())


def test_missing_and_invalid_gst_measurements_stay_unknown() -> None:
    record = gst()
    invalid = {
        "latitude_std": None,
        "longitude_std": -1.0,
        "altitude_std": float("nan"),
        "semi_major": -0.2,
        "semi_minor": 2.0,
    }
    record = replace(
        record, entries=tuple((k, invalid.get(k, v)) for k, v in record.entries)
    )
    assert fix().with_gst(record).precision is None
    with pytest.raises(ValueError, match="expected a GST"):
        PositionPrecision.from_gst(Record("GNGGA", ()))
    with pytest.raises(ValueError, match="UTC"):
        fix(utc="126000").with_gst(gst())
    with pytest.raises(ValueError, match="ellipse"):
        ErrorEllipse(1, 2, 90)
    reversed_axes = replace(
        gst(),
        entries=tuple(
            (key, 0.2 if key == "semi_major" else value) for key, value in gst().entries
        ),
    )
    with pytest.raises(ValueError, match="ellipse"):
        fix().with_gst(reversed_axes)
    with pytest.raises(ValueError, match="non-negative"):
        PositionPrecision("test", east_std_m=-1)


def test_all_position_models_share_precision_interface() -> None:
    nav = bestnav()
    rover = RoverPosition(nav, None, None, None, None, None)
    solution = ppp()
    for position in (fix(), nav, rover, solution):
        assert isinstance(position, Position)
    assert nav.precision is not None and nav.precision.east_std_m == 3
    assert rover.precision == nav.precision
    assert solution.valid and solution.precision is not None
    assert not hasattr(solution, "horizontal_std_m")
    assert solution.precision.north_std_m == solution.latitude_std_m
    assert (
        replace(nav, solution_status=SolutionStatus.INSUFFICIENT_OBS).precision is None
    )
    assert (
        replace(solution, solution_status=SolutionStatus.INSUFFICIENT_OBS).precision
        is None
    )
    assert (
        replace(
            nav, latitude_std_m=None, longitude_std_m=None, height_std_m=None
        ).precision
        is None
    )


def test_secondary_position_precision_keeps_antenna_provenance() -> None:
    secondary_nav = replace(
        BestNavigation.from_record(decode_log(manual_message("BESTNAVHA"))),
        solution_status=SolutionStatus.SOL_COMPUTED,
        position_type=PositionType.SINGLE,
    )
    samples = json.loads(
        (Path(__file__).parent / "fixtures/manual-examples.json").read_text()
    )
    secondary_message = parse_ascii((samples["PPPNAVHA"] + "\r\n").encode())
    secondary_ppp = PppSolution.from_record(Log.PPPNAVH.decode(secondary_message))
    assert secondary_nav.precision is not None
    assert secondary_nav.precision.source == "BESTNAVH"
    assert secondary_nav.precision.antenna == 2
    assert secondary_ppp.precision is not None
    assert secondary_ppp.precision.source == "PPPNAVH"
    assert secondary_ppp.precision.antenna == 2


def test_custom_position_can_be_written_with_precision(tmp_path: Path) -> None:
    class CustomPosition:
        latitude = 52.0
        longitude = 13.0
        valid = True
        rtk_fixed = False
        correction_age_s = None
        epoch_gps_seconds = 100.0
        satellites_used = None
        ellipsoidal_height = 42.0
        altitude_msl = None
        precision = PositionPrecision("external", east_std_m=1, north_std_m=2)

    position = CustomPosition()
    assert isinstance(position, Position)
    path = tmp_path / "custom.geojson"
    with TrackWriter(path, format="geojson", reference_frame="WGS84") as writer:
        writer.write(position)
    properties = json.loads(path.read_text())["features"][0]["properties"]
    assert properties["precision"]["source"] == "external"
    assert properties["precision"]["up_std_m"] is None


def test_geojson_and_ros_use_precision_for_all_position_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NavSatFix:
        COVARIANCE_TYPE_UNKNOWN = 0
        COVARIANCE_TYPE_DIAGONAL_KNOWN = 2

        def __init__(self) -> None:
            self.header = SimpleNamespace()
            self.status = SimpleNamespace()
            self.position_covariance = [0.0] * 9

    monkeypatch.setattr(
        "um982py.adapters.import_module", lambda _: SimpleNamespace(NavSatFix=NavSatFix)
    )
    for position in (
        fix().with_gst(gst()),
        bestnav(),
        ppp(),
        RoverPosition(bestnav(), None, None, None, None, None),
    ):
        feature = geojson_feature(position, reference_frame="WGS84")
        assert feature is not None and feature["properties"]["precision"] is not None
        message = navsatfix(
            position,
            stamp=object(),
            frame_id="antenna",
            reference_frame="WGS84",
            status=0,
        )
        assert message.position_covariance_type == 2
        assert message.position_covariance[0] == pytest.approx(
            position.precision.east_std_m**2
        )
    assert (
        geojson_feature(fix(), reference_frame="WGS84")["properties"]["precision"]
        is None
    )
    with pytest.raises(ValueError, match="datum"):
        geojson_feature(replace(bestnav(), datum=0), reference_frame="WGS84")


@pytest.mark.parametrize("fmt", ["gpx", "geojson", "csv"])
def test_track_exports_receiver_precision_and_unknown_values(
    tmp_path: Path, fmt: str
) -> None:
    path = tmp_path / f"track.{fmt}"
    with TrackWriter(path, format=fmt, reference_frame="WGS84") as writer:
        writer.write(fix().with_gst(gst()), timestamp=datetime(2024, 1, 1, tzinfo=UTC))
        writer.write(fix())
        writer.write(ppp())
        writer.write(RoverPosition(bestnav(), None, None, None, None, None))
    if fmt == "geojson":
        features = json.loads(path.read_text())["features"]
        assert features[0]["properties"]["precision"]["ellipse"]["semi_major_m"] == 1.67
        assert features[1]["properties"]["precision"] is None
        assert features[2]["properties"]["precision"]["source"] == "PPPNAV"
    elif fmt == "csv":
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert rows[0]["precision_east_std_m"] == "1.62"
        assert rows[0]["precision_ellipse_orientation_deg"] == "115.38"
        assert rows[1]["precision_source"] == ""
        assert rows[2]["precision_source"] == "PPPNAV"
    else:
        root = ElementTree.parse(path).getroot()  # noqa: S314
        values = root.findall(".//{urn:um982py:track:1}precision_ellipse_semi_major_m")
        assert len(values) == 1 and values[0].text == "1.67"
