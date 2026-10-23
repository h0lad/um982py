from struct import pack

import pytest

from test_bodies import binary_message, manual_message
from um982py.messages import decode_log
from um982py.messages.gps_health import GpsLnavHealth, gps_visible_health
from um982py.messages.record import Record


def ephemeris(health: int, prn: int = 3) -> Record:
    return Record("GPSEPH", (("prn", prn), ("health", health)))


def test_lnav_health_code_is_not_a_bitmask() -> None:
    health = GpsLnavHealth.from_record(ephemeris(0b100100))
    assert health.prn == 3
    assert health.navigation_data_ok is False
    assert health.signal_status_code == 4
    assert health.signal_status == "L1 P signal weak"
    assert GpsLnavHealth.from_record(ephemeris(0)).signal_status == "all signals OK"
    # 63 is not the special almanac page-25 unavailable code in subframe 1.
    assert (
        GpsLnavHealth.from_record(ephemeris(63)).signal_status
        == "multiple signal anomalies"
    )


@pytest.mark.parametrize("raw,prn", [(64, 1), (-1, 1), (0, 33)])
def test_lnav_invalid_fields(raw: int, prn: int) -> None:
    with pytest.raises(ValueError):
        GpsLnavHealth.from_record(ephemeris(raw, prn))


def test_visible_health_preserves_unknown() -> None:
    satellites = tuple(
        Record(
            "satellite",
            (
                ("prn_slot", Record("satellite_id", (("prn", i), ("channel", 0)))),
                ("health", value),
            ),
        )
        for i, value in [(1, 0), (4, 1), (8, 9)]
    )
    record = Record(
        "SATELLITE", (("satellite_system", "GPS"), ("satellites", satellites))
    )
    assert gps_visible_health(record) == ((1, True), (4, False), (8, None))
    with pytest.raises(ValueError):
        gps_visible_health(
            Record(
                "SATELLITE",
                (("satellite_system", "GALILEO"), ("satellites", satellites)),
            )
        )


def test_visible_health_decodes_real_ascii_and_binary_layouts() -> None:
    ascii_record = decode_log(manual_message("SATELLITEA"))
    assert gps_visible_health(ascii_record)[0] == (3, True)
    data = pack("<IIIIHhIdddd", 0, 1, 1, 1, 3, 0, 1, 25.2, 308.1, 0.0, 0.0)
    binary_record = decode_log(binary_message("SATELLITE", data))
    assert gps_visible_health(binary_record) == ((3, False),)
