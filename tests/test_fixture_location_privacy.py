from __future__ import annotations

import json
import math
from contextlib import suppress
from pathlib import Path

from examples.wls_position import solve_position
from examples.wls_position.__main__ import (
    _decode,
    _decode_firmware,
    _gps_l1,
    epoch_seconds,
    receiver_position,
)

from um982py.capture import read_frames
from um982py.commands import Log
from um982py.errors import ProtocolError
from um982py.experimental import FirmwareLog
from um982py.geodesy import geodetic_from_ecef
from um982py.messages import BinaryMessage, Sentence, decode_log
from um982py.messages.record import Record

FIXTURES = Path(__file__).parent / "fixtures"
POSITION_LOGS = {
    FirmwareLog.BESTPOS,
    FirmwareLog.BESTPOS2,
    FirmwareLog.BESTGNSSPOS,
    FirmwareLog.PSRPOS,
    FirmwareLog.RTKPOS,
    FirmwareLog.BESTXYZ,
    FirmwareLog.REFSTATION,
}


def _synthetic_area(latitude: float, longitude: float) -> bool:
    return 52.2 < latitude < 52.8 and 13.0 < longitude < 13.8


def _position(record: Record) -> tuple[float, float] | None:
    values = dict(record.entries)
    for lat_key, lon_key in (("lat", "lon"), ("latitude", "longitude")):
        if lat_key in values and lon_key in values:
            latitude, longitude = float(values[lat_key]), float(values[lon_key])
            if latitude == longitude == 0.0:
                return None
            return latitude, longitude
    for keys in (
        ("p_x", "p_y", "p_z"),
        ("coordinate_1", "coordinate_2", "coordinate_3"),
    ):
        if all(key in values for key in keys):
            xyz = tuple(float(values[key]) for key in keys)
            if math.dist(xyz, (0.0, 0.0, 0.0)) < 6_000_000:
                return None
            return geodetic_from_ecef(*xyz)[:2]
    return None


def _nmea_position(sentence: Sentence) -> tuple[float, float] | None:
    if sentence.name.endswith("GGA"):
        indices = (1, 2, 3, 4)
    elif sentence.name.endswith("RMC"):
        indices = (2, 3, 4, 5)
    elif sentence.name.endswith("GLL"):
        indices = (0, 1, 2, 3)
    else:
        return None
    try:
        lat_text, north_south, lon_text, east_west = (
            sentence.fields[index] for index in indices
        )

        def degrees(text: str, hemisphere: str) -> float:
            numeric = float(text)
            whole = int(numeric // 100)
            value = whole + (numeric - 100 * whole) / 60
            return -value if hemisphere in ("S", "W") else value

        return degrees(lat_text, north_south), degrees(lon_text, east_west)
    except (IndexError, ValueError):
        return None


def test_position_bearing_replay_frames_are_in_the_synthetic_area() -> None:
    checked = {"nmea": 0, "core": 0, "extended": 0, "bestxyz": 0}
    for path in FIXTURES.rglob("*.bin"):
        extension = next(
            (
                log
                for log in POSITION_LOGS
                if path.stem in (log.value + "A", log.value + "B")
            ),
            None,
        )
        frames = read_frames(path)
        for message in frames:
            if isinstance(message, Sentence):
                position = _nmea_position(message)
                if position is not None:
                    assert _synthetic_area(*position), path
                    checked["nmea"] += 1
            with suppress(ProtocolError, ValueError, TypeError):
                position = _position(decode_log(message))
                if position is not None:
                    assert _synthetic_area(*position), path
                    checked["core"] += 1
            extensions = [extension] if extension is not None else []
            if (
                isinstance(message, BinaryMessage)
                and FirmwareLog.BESTXYZ.request(binary=True).matches(message)
                and FirmwareLog.BESTXYZ not in extensions
            ):
                extensions.append(FirmwareLog.BESTXYZ)
            for log in extensions:
                with suppress(ProtocolError):
                    position = _position(log.decode(message))
                    if position is not None:
                        assert _synthetic_area(*position), path
                        checked["extended"] += 1
                        if log is FirmwareLog.BESTXYZ:
                            checked["bestxyz"] += 1
    assert checked["nmea"] > 100
    assert checked["core"] > 100
    assert checked["extended"] > 10
    assert checked["bestxyz"] > 0


def test_replay_pseudoranges_solve_to_the_synthetic_area() -> None:
    root = FIXTURES / "captures-live"
    ranges = _decode_firmware(read_frames(root / "RANGEA.bin"), FirmwareLog.RANGE)
    positions = _decode_firmware(
        read_frames(root / "BESTPOSA.bin"), FirmwareLog.BESTPOS
    )
    ephemerides = _decode(read_frames(root / "GPSEPHA.bin"), Log.GPSEPH)
    observations = _gps_l1(
        ranges[0],
        {record.integer("prn"): record for record in ephemerides},
        epoch_seconds(ranges[0].message),
    )
    solution = solve_position(observations, (*receiver_position(positions[0]), 0.0))
    assert solution.converged
    assert _synthetic_area(*geodetic_from_ecef(solution.x, solution.y, solution.z)[:2])


def test_labelled_motion_truth_is_in_the_synthetic_area() -> None:
    truth = json.loads(
        (FIXTURES / "specialist" / "rtklib-motion-truth.json").read_text()
    )
    assert _synthetic_area(*geodetic_from_ecef(*truth["observer_ecef_m"])[:2])
