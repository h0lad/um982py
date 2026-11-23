"""Check typed parsing of DSP diagnostic notices."""

from um982py.experimental import extract_dsp_receiver_diagnostics

NAVPOS = (
    b"$NAVPOS,1383709,9,16,1,48.735755,9.323464,294.533728,"
    b"   4159083.172,682825.048,4771450.170,  12\r\n"
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
    assert (position.latitude_deg, position.longitude_deg) == (48.735755, 9.323464)
    assert (position.x_m, position.y_m, position.z_m) == (
        4_159_083.172,
        682_825.048,
        4_771_450.170,
    )
    assert position.count == 12

    assert len(diagnostics.nav_velocities) == 1
    velocity = diagnostics.nav_velocities[0]
    assert velocity.values == (-0.014, -0.001, -0.018, 0.023, -0.565)
    assert velocity.age == 12
    assert velocity.trailing == 0.109
