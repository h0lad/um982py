"""Checks measurement readers against captured bytes and product formats."""

from dataclasses import replace
from pathlib import Path
from struct import unpack_from

import pytest

from um982py import PrecisePoint, gps_epoch, interpolate_sp3, parse_sp3, range_samples
from um982py.capture import decode_records, read_frames
from um982py.experimental import FirmwareLog, tracking_fields
from um982py.messages import BinaryMessage, Record

FIXTURES = Path(__file__).parent / "fixtures"
SPECIALIST = FIXTURES / "specialist"


def test_captured_range_phase_and_doppler_signs_match_raw_binary_values() -> None:
    frames = read_frames(FIXTURES / "captures/RANGEB.bin")
    message = next(
        frame
        for frame in frames
        if FirmwareLog.RANGE.request(binary=True).matches(frame)
    )
    assert isinstance(message, BinaryMessage)
    record = FirmwareLog.RANGE.decode(message)
    samples = range_samples(record)
    assert samples
    assert all(item.key.system == 0 and item.key.signal in (0, 14) for item in samples)
    for sample in samples:
        observations = record.records("observations")
        index = next(
            i
            for i, item in enumerate(observations)
            if item.integer("prn") == sample.key.prn
            and (item.integer("tracking_status") >> 16) & 7 == 0
            and (item.integer("tracking_status") >> 21) & 31 == sample.key.signal
        )
        adr = unpack_from("<d", message.payload, 4 + index * 44 + 16)[0]
        doppler = unpack_from("<f", message.payload, 4 + index * 44 + 28)[0]
        frequency = 1575420000 if sample.key.signal == 0 else 1176450000
        assert sample.phase_m == pytest.approx(-adr * 299792458 / frequency)
        assert sample.rate_mps == pytest.approx(-doppler * 299792458 / frequency)
        assert sample.epoch == gps_epoch(message)


def test_equal_prns_in_other_constellations_cannot_become_gps_samples() -> None:
    record = decode_records(
        read_frames(FIXTURES / "captures/RANGEB.bin"), FirmwareLog.RANGE
    )[0]
    observation = record.records("observations")[0]
    fields = dict(observation.entries)
    fields.update(tracking_status=0x1400 | (3 << 16), lock_time=100)
    other = Record("observations", tuple(fields.items()))
    assert range_samples(Record("RANGE", (("observations", (other,)),)), epoch=0) == ()


def test_unstamped_measurements_require_an_explicit_epoch() -> None:
    with pytest.raises(ValueError, match="timestamp"):
        range_samples(Record("RANGE", (("observations", ()),)))


def test_tracking_fields_match_captured_byte_offsets_without_renaming() -> None:
    record = decode_records(
        read_frames(FIXTURES / "captures/PTOBSINFOB.bin"), FirmwareLog.PTOBSINFO
    )[0]
    assert isinstance(record.message, BinaryMessage)
    fields = tracking_fields(record)
    assert len(fields) == 29
    assert [field.offset for field in fields] == list(range(0, 116, 4))
    assert tuple(field.storage for field in fields) == (
        ("u",) * 5 + ("f",) + ("u",) * 4 + ("x",) + ("f",) * 18
    )
    for field in fields:
        kind = "f" if field.storage == "f" else "I"
        expected = unpack_from("<" + kind, record.message.payload, field.offset)[0]
        assert field.value == expected
    assert fields[0].value == 1
    assert fields[5].value == pytest.approx(0.8918271660804749)


def test_official_igs_example_converts_units_and_retains_prediction_flags() -> None:
    product = parse_sp3((SPECIALIST / "igs-sp3c-example.sp3").read_text())
    assert product.coordinate_system == "IGS97"
    assert product.agency == "IGS"
    first = product.points[0]
    assert first.epoch == 1126 * 604800 + 259200
    assert first.position == pytest.approx((-11044805.8, -10475672.35, 21929418.2))
    assert first.clock_seconds == pytest.approx(0.0001891633, abs=1e-15)
    assert not first.predicted_orbit
    assert product.points[-1].predicted_orbit
    assert product.points[-1].predicted_clock
    assert product.points[-1].clock_event
    assert product.points[1].maneuver


def test_sp3_non_gps_time_is_never_silently_interpreted_as_gps() -> None:
    text = (SPECIALIST / "igs-sp3c-example.sp3").read_text()
    with pytest.raises(ValueError, match="GPS-time"):
        parse_sp3(text.replace("%c G  cc GPS", "%c G  cc UTC"))


def test_missing_sp3_clock_remains_missing() -> None:
    lines = (SPECIALIST / "igs-sp3c-example.sp3").read_text().splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("PG01"))
    lines[index] = lines[index][:46] + " 999999.999999" + lines[index][60:]
    assert parse_sp3("\n".join(lines)).points[0].clock_seconds is None


def test_sp3_position_on_a_coordinate_plane_is_retained() -> None:
    lines = (SPECIALIST / "igs-sp3c-example.sp3").read_text().splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith("PG01"))
    original = lines[index]
    lines[index] = original[:4] + f"{0.0:14.6f}" + original[18:]
    product = parse_sp3("\n".join(lines))
    assert product.points[0].position[0] == 0
    assert product.points[0].position[1:] == pytest.approx(
        tuple(float(original[start : start + 14]) * 1000 for start in (18, 32))
    )
    lines[index] = original[:4] + 3 * f"{0.0:14.6f}" + original[46:]
    assert len(parse_sp3("\n".join(lines)).points) == len(product.points) - 1


def test_precise_interpolation_reproduces_an_independent_cubic() -> None:
    points = [
        PrecisePoint(
            "G01",
            float(t),
            (float(t**3 + 1), float(2 * t**2 + 2), float(3 * t + 3)),
            t * 1e-6,
        )
        for t in range(5)
    ]
    result = interpolate_sp3(points, 1.5, order=3)
    assert result.position == pytest.approx((4.375, 6.5, 7.5))
    assert result.clock_seconds == pytest.approx(1.5e-6)


def test_precise_interpolation_refuses_gaps_and_extrapolation() -> None:
    points = [PrecisePoint("G01", t, (1, 2, 3), None) for t in (0, 1000)]
    with pytest.raises(ValueError, match="gap"):
        interpolate_sp3(points, 500)
    with pytest.raises(ValueError, match="extrapolation"):
        interpolate_sp3(points, -1)
    with pytest.raises(ValueError, match="duplicate"):
        interpolate_sp3([points[0], points[0]], 0)
    assert interpolate_sp3(points, 0) is points[0]


def test_precise_missing_clock_is_not_interpolated_through() -> None:
    points = [
        PrecisePoint("G01", 0, (1, 2, 3), None),
        PrecisePoint("G01", 1, (2, 3, 4), 1e-6),
    ]
    assert interpolate_sp3(points, 0.5).clock_seconds is None
    assert interpolate_sp3(
        [points[0], replace(points[1], predicted_clock=True)], 0.5
    ).predicted_clock


def test_sp3_interpolation_withholds_a_clock_crossing_a_discontinuity() -> None:
    points = [
        PrecisePoint("G01", 0, (1, 2, 3), 0),
        PrecisePoint("G01", 1, (2, 3, 4), 1e-6, clock_event=True),
    ]
    assert interpolate_sp3(points, 0.5).clock_seconds is None
    assert interpolate_sp3(points, 1).clock_seconds == 1e-6


def test_sp3_interpolation_refuses_an_orbit_maneuver() -> None:
    points = [
        PrecisePoint("G01", 0, (1, 2, 3), 0),
        PrecisePoint("G01", 1, (2, 3, 4), 1e-6, maneuver=True),
    ]
    with pytest.raises(ValueError, match="maneuver"):
        interpolate_sp3(points, 0.5)


def test_truncated_sp3_reference_is_rejected() -> None:
    text = (SPECIALIST / "igs-sp3c-example.sp3").read_text()
    with pytest.raises(ValueError, match="incomplete"):
        parse_sp3(text.removesuffix("EOF\n"))
