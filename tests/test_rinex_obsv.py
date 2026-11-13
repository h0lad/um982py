from dataclasses import replace

import pytest

from conftest import FIXTURES
from test_bodies import binary_message, manual_message
from um982py import decode_message
from um982py.errors import ProtocolError
from um982py.messages import decode_log
from um982py.messages.frames import AsciiHeader
from um982py.rinex import export_rinex


def test_export_documented_obsv_manual_example() -> None:
    message = manual_message("OBSVMA")
    message = replace(
        message,
        header=AsciiHeader("OBSVMA", 0, "GPS", "FINE", 2190, 117395000, 0, 0, 18, 0),
    )
    record = decode_log(message)
    result = export_rinex((record,))
    assert result.signal_observations > 0
    assert "Native OBSVM input; GPST epochs" in result.text
    assert "G26" in result.text
    assert "21720097.812" in result.text


def test_obsv_antenna_isolation() -> None:
    message = replace(
        manual_message("OBSVMA"),
        header=AsciiHeader("OBSVMA", 0, "GPS", "FINE", 2190, 117395000, 0, 0, 18, 0),
    )
    record = decode_log(message)
    with pytest.raises(ValueError, match="one antenna"):
        export_rinex((record, replace(record, name="OBSVH")))
    with pytest.raises(ProtocolError, match="compressed observation"):
        export_rinex((replace(record, name="OBSVMCMP"),))


@pytest.mark.parametrize("name", ["OBSVMCMP", "OBSVHCMP"])
def test_compressed_observations_export_without_ambiguous_phase(name: str) -> None:
    status = (1 << 10) | (1 << 12)
    encoded = (
        status
        | (((1 << 28) - 256) << 32)
        | (2_560_000_000 << 60)
        | (768 << 96)
        | (1 << 136)
        | (320 << 144)
        | (17 << 165)
    ).to_bytes(24, "little")
    message = binary_message(name, (1).to_bytes(4, "little") + encoded)
    result = export_rinex((decode_log(message),))
    row = next(line for line in result.text.splitlines() if line.startswith("G01"))
    assert float(row[3:17]) == pytest.approx(20_000_000)
    assert row[19:35] == " " * 16  # No reconstructed carrier phase.
    assert float(row[35:49]) == pytest.approx(-1)
    assert float(row[51:65]) == pytest.approx(37)
    assert result.omitted["unresolved_compressed_phase"] == 1
    assert "Compressed carrier phases omitted" in result.text


def test_compressed_receiver_capture_exports_code_and_doppler() -> None:
    record = decode_message((FIXTURES / "bodies/OBSVMCMPB.bin").read_bytes())
    result = export_rinex((record,))
    row = next(line for line in result.text.splitlines() if line.startswith("G29"))
    assert float(row[3:17]) == pytest.approx(21_506_277.852)
    assert row[19:35] == " " * 16
    assert float(row[35:49]) == pytest.approx(-2166.473)
    assert float(row[51:65]) == pytest.approx(32)
    assert result.omitted["unresolved_compressed_phase"] > 0
