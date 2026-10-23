"""Orbit comparison with selected GPS positions from an IGS rapid SP3 product."""

import math
from dataclasses import replace
from pathlib import Path

import pytest

from um982py.commands import Log
from um982py.errors import ProtocolError
from um982py.experimental.orbit import KeplerElements, orbit_state
from um982py.protocol import StreamDecoder

# IGS0OPSRAP_20262950000_01D_15M_ORB.SP3.gz, 2026-10-22 16:00 GPST.
# Source: https://igs.bkg.bund.de/root_ftp/IGS/products/2441/
POSITIONS = {
    10: (11161350.840, -23882820.249, -114676.466),
    12: (14587599.447, 4575692.311, 21421556.943),
    17: (-15545470.521, 13209762.775, 17524519.150),
    19: (-3660687.176, 15175389.379, 21402402.504),
}
GPS_SECONDS = 1476720000.0


def _elements(prn: int) -> tuple[KeplerElements, float]:
    capture = Path(__file__).parent / "fixtures/captures/GPSEPHA.bin"
    for frame in StreamDecoder().feed(capture.read_bytes()):
        try:
            record = Log.GPSEPH.decode(frame)
        except ProtocolError:
            continue
        if record.integer("prn") == prn:
            elements = KeplerElements.from_record(record)
            return elements, GPS_SECONDS - (
                record.integer("week") * 604800 + elements.toe
            )
    raise AssertionError(f"no GPSEPH for GPS {prn}")


def _distance(elements: KeplerElements, dt: float, prn: int) -> float:
    state = orbit_state(elements, dt)
    return math.dist((state.x, state.y, state.z), POSITIONS[prn])


@pytest.mark.parametrize("prn", [10, 12, 19])
def test_captured_broadcast_positions_agree_with_igs_rapid(prn: int) -> None:
    elements, dt = _elements(prn)
    assert abs(dt) <= 7200
    assert _distance(elements, dt, prn) < 3.0


def test_g17_capture_disagrees_with_independent_broadcast_message() -> None:
    elements, dt = _elements(17)
    assert dt == 0
    assert _distance(elements, dt, 17) > 3_000_000
    # Two coefficients from IGS BRDC00IGS_R_20262950000_01D_MN.rnx.gz,
    # G17 issue 129 at 16:00 GPST. This is a diagnostic copy only.
    reference = replace(elements, cic=6.70552253723e-08, right_ascension=-2.06668861845)
    assert _distance(reference, dt, 17) < 2.0
