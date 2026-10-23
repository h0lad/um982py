from dataclasses import replace

import pytest

from test_bodies import manual_message
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


def test_obsv_antenna_isolation_and_compressed_refusal() -> None:
    record = decode_log(manual_message("OBSVMA"))
    with pytest.raises(ValueError, match="one antenna"):
        export_rinex((record, replace(record, name="OBSVH")))
    with pytest.raises(ValueError, match="uncompressed"):
        export_rinex((replace(record, name="OBSVMCMP"),))
