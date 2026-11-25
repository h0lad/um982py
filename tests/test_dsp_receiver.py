"""Check typed parsing of DSP diagnostic notices."""

from pathlib import Path

import pytest

from um982py.experimental import extract_dsp_receiver_diagnostics
from um982py.experimental.dsp_receiver import DSP_RECEIVER_MEMORY_WINDOWS

NAVPOS = (
    b"$NAVPOS,1383709,9,16,1,52.533665,13.376327,73.994866,"
    b"   3782565.550,899482.810,5039202.930,  12\r\n"
)
NAVVEL = b"$NAVVEL,-0.014,-0.001,-0.018,0.023,-0.565,  12,    0.109\r\n"


def test_typed_navpos_and_navvel_notices() -> None:
    payload = NAVPOS + NAVVEL
    payload += b"\x00" * (0x2000 - len(payload))
    regions = {"notice": (0x402C00, payload)}
    diagnostics = extract_dsp_receiver_diagnostics(regions)

    assert len(diagnostics.nav_positions) == 1
    position = diagnostics.nav_positions[0]
    assert position.position_type == 16
    assert (position.latitude_deg, position.longitude_deg) == (52.533665, 13.376327)
    assert (position.x_m, position.y_m, position.z_m) == (
        3_782_565.550,
        899_482.810,
        5_039_202.930,
    )
    assert position.count == 12

    assert len(diagnostics.nav_velocities) == 1
    velocity = diagnostics.nav_velocities[0]
    assert velocity.values == (-0.014, -0.001, -0.018, 0.023, -0.565)
    assert velocity.age == 12
    assert velocity.trailing == 0.109


FIXTURES = Path(__file__).parent / "fixtures" / "crosscheck"


def _clock_regions(table: bytes | None = None) -> dict[str, tuple[int, bytes]]:
    windows = {name: base for name, base, _ in DSP_RECEIVER_MEMORY_WINDOWS}
    if table is None:
        table = (FIXTURES / "dsp-system-time-table.ram").read_bytes()
    return {
        "system_time_table": (windows["system_time_table"], table),
        "system_time": (
            windows["system_time"],
            (FIXTURES / "dsp-system-time.ram").read_bytes(),
        ),
    }


def test_live_per_constellation_clock_state() -> None:
    # Recorded state at GPS 2446:287102. RECTIME reported +305.559 us at that
    # epoch. Over a 10 min session RTKLIB estimated GLO-GPS +27..+39 ns and
    # BDS-GPS +17..+26 ns, the opposite sign of the inter-system biases below.
    state = extract_dsp_receiver_diagnostics(_clock_regions()).clock_state

    assert state is not None
    assert state.bias_vector_consistent
    assert [clock.constellation for clock in state.clocks] == [
        "GPS",
        "BEIDOU",
        "GALILEO",
        "GLONASS",
    ]
    gps, beidou, galileo, glonass = state.clocks
    assert (gps.time_ms, gps.week) == (287_102_000, 2446)
    # GLONASS time of day: GPS - 18 s leap seconds + 3 h.
    assert (glonass.time_ms, glonass.week) == (
        (287_102 - 3 * 86_400 - 18 + 10_800) * 1000,
        None,
    )
    assert (beidou.time_ms, beidou.week) == (287_088_000, 2446 - 1356)
    assert (galileo.time_ms, galileo.week) == (287_102_000, 2446 - 1024)
    # Day 1060 of GLONASS four-year interval 8 (2024-2027) is the GPS date.
    assert (state.glonass_four_year_period, state.glonass_day) == (8, 1060)
    assert gps.clock_offset_s == pytest.approx(305.636182e-6, abs=1e-12)
    biases = {name: value * 1e9 for name, value in state.inter_system_bias_s().items()}
    assert biases == pytest.approx(
        {"GLONASS": -43.964, "BEIDOU": -18.293, "GALILEO": -7.304}, abs=1e-3
    )


def test_clock_state_rejects_unknown_layout() -> None:
    table = bytearray((FIXTURES / "dsp-system-time-table.ram").read_bytes())
    table[0] ^= 0x08
    assert (
        extract_dsp_receiver_diagnostics(_clock_regions(bytes(table))).clock_state
        is None
    )
    regions = _clock_regions()
    del regions["system_time_table"]
    assert extract_dsp_receiver_diagnostics(regions).clock_state is None
