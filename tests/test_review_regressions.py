"""Regression cases found during the architecture and numerical review."""

import math
from dataclasses import replace

import pytest

from conftest import FIXTURES, rtcm, sentence
from test_protocol import binary
from tests.examples._new_api import observation, record
from um982py.geodesy import (
    WGS84_A,
    WGS84_F,
    ecef_from_geodetic,
    geodetic_from_ecef,
)
from um982py.measurement import range_samples, sample_series
from um982py.protocol import StreamDecoder


@pytest.mark.parametrize(
    "following",
    [
        binary(b"receiver payload"),
        (FIXTURES / "captures/BESTPOSB.bin").read_bytes(),
        rtcm(b"\x3e\xd0receiver payload"),
        sentence(b"GPGGA,1,2"),
    ],
)
def test_corrupt_length_does_not_consume_fragmented_next_frame(
    following: bytes,
) -> None:
    # The damaged frame claims three bytes that belong to the next frame.
    damaged = binary(b"broken")[:-3]
    wire = damaged + following
    for split in range(len(damaged) + 1, len(wire) + 1):
        decoder = StreamDecoder()
        messages = (*decoder.feed(wire[:split]), *decoder.feed(wire[split:]))
        assert [message.raw for message in messages] == [following], split
        assert decoder.discarded_bytes == len(damaged)
        decoder.finish()


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("horizontal", [1e-8, 1e-6, 0.001, 0.1])
def test_ecef_height_is_stable_close_to_both_poles(
    sign: int, horizontal: float
) -> None:
    polar_radius = WGS84_A * (1 - WGS84_F)
    latitude, longitude, height = geodetic_from_ecef(
        horizontal, 0, sign * (polar_radius + 10)
    )
    assert height == pytest.approx(10, abs=1e-7)
    assert longitude == 0
    assert math.copysign(1, latitude) == sign


@pytest.mark.parametrize("latitude", [-90, -80, -45, 0, 45, 80, 90])
@pytest.mark.parametrize("height", [-500, 0, 10000, 35_786_000])
def test_ecef_round_trip_from_below_sea_level_to_orbit(
    latitude: float, height: float
) -> None:
    xyz = ecef_from_geodetic(latitude, 23, height)
    recovered = geodetic_from_ecef(*xyz)
    assert recovered[0] == pytest.approx(latitude, abs=1e-10)
    assert recovered[2] == pytest.approx(height, abs=1e-7)
    assert ecef_from_geodetic(*recovered) == pytest.approx(xyz, abs=1e-7)


def test_l2_tracking_variants_are_separate_measurement_series() -> None:
    rows = [observation(signal=9, l2c=flag) for flag in (0, 1)]
    records = [record(epoch, rows) for epoch in (0, 1)]
    samples = range_samples(records[0])
    assert len(samples) == 2
    assert {sample.key.l2c_flag for sample in samples} == {False, True}
    assert sorted(map(len, sample_series(records).values())) == [2, 2]


@pytest.mark.parametrize("other", ["RANGEH", "OBSVBASE"])
def test_measurement_series_reject_mixed_observation_sources(other: str) -> None:
    first = record(0, [observation()])
    second = replace(record(1, [observation()]), name=other)
    with pytest.raises(ValueError, match="one observation log"):
        sample_series([first, second])
