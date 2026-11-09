from pathlib import Path

import pytest

from um982py.messages import decode_log
from um982py.messages.record import Record
from um982py.protocol import StreamDecoder
from um982py.satellites import Satellite, SatelliteSignal, satellites_from_record

FIXTURES = Path(__file__).parent / "fixtures" / "bodies"


@pytest.mark.parametrize("suffix", ["A", "B"])
def test_recorded_satellite_report_has_named_constellations_and_signals(
    suffix: str,
) -> None:
    decoder = StreamDecoder(strict=True)
    (message,) = decoder.feed((FIXTURES / f"SATSINFO{suffix}.bin").read_bytes())
    decoder.finish()
    satellites = satellites_from_record(decode_log(message))

    assert len(satellites) == 30
    first = satellites[0]
    assert (first.constellation, first.prn) == ("GPS", 29)
    assert (first.azimuth_deg, first.elevation_deg) == (72, 43)
    assert len(first.signals) == 1
    assert (first.signals[0].name, first.signals[0].snr) == ("L1 C/A", 22)
    galileo = next(sat for sat in satellites if sat.constellation == "Galileo")
    assert galileo.signals[0].constellation == "Galileo"
    assert galileo.signals[0].name == "E1 C"


@pytest.mark.parametrize(
    ("system", "signal", "constellation", "name"),
    [
        (0, 9, "GPS", "L2 P(Y)"),
        (1, 5, "GLONASS", "L2 C/A"),
        (2, 6, "SBAS", "L5 I"),
        (3, 18, "Galileo", "E6 B"),
        (4, 13, "BeiDou", "B2b I"),
        (5, 18, "QZSS", "L61 data"),
        (5, 22, "QZSS", "L61 pilot"),
        (5, 24, "QZSS", "L62 data 1"),
        (5, 25, "QZSS", "L62 data 2"),
        (6, 14, "NavIC", "L5 pilot"),
    ],
)
def test_satellite_signal_uses_satsinfo_frequency_identifiers(
    system: int, signal: int, constellation: str, name: str
) -> None:
    tracked = SatelliteSignal(system, signal, 42)
    assert tracked.constellation == constellation
    assert tracked.name == name


def test_unknown_and_mixed_identifiers_are_preserved() -> None:
    unknown = SatelliteSignal(255, 200, 31)
    assert unknown.constellation is None
    assert unknown.name is None
    assert (unknown.system_id, unknown.signal_id, unknown.snr) == (255, 200, 31)

    unknown_signal = SatelliteSignal(0, 255, 18)
    assert unknown_signal.constellation == "GPS"
    assert unknown_signal.name is None

    mixed = Satellite(
        12, 50, 30, (SatelliteSignal(0, 0, 40), SatelliteSignal(3, 2, 41))
    )
    assert mixed.constellation is None
    assert [signal.constellation for signal in mixed.signals] == ["GPS", "Galileo"]


def test_satellite_report_rejects_unrelated_logs() -> None:
    with pytest.raises(ValueError, match="SATSINFO"):
        satellites_from_record(Record("BESTNAV", ()))
