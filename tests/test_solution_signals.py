"""Solution signal-mask tests based on R1.15 tables 7-177 and 7-178."""

from dataclasses import replace

import pytest

from test_bodies import binary_message, manual_message
from um982py.messages import AsciiMessage, Record, decode_log
from um982py.messages.solution_signals import (
    GalileoBds3Signals,
    GpsGlonassBds2Signals,
    SolutionSignals,
)


def test_navigation_masks_match_ascii_and_binary() -> None:
    message = manual_message("BESTNAVA")
    assert isinstance(message, AsciiMessage)
    fields = list(message.fields)
    fields[19:21] = ["cf", "91"]
    ascii_record = decode_log(replace(message, fields=tuple(fields)))
    payload = bytearray(120)
    payload[70:72] = b"\xcf\x91"
    binary_record = decode_log(binary_message("BESTNAV", bytes(payload)))
    for record in (ascii_record, binary_record):
        signals = SolutionSignals.from_record(record)
        assert signals.galileo_bds3 & GalileoBds3Signals.GALILEO_E1
        assert signals.galileo_bds3 & GalileoBds3Signals.BDS3_B1C
        assert signals.gps_glonass_bds2 & GpsGlonassBds2Signals.GPS_L1
        assert signals.gps_glonass_bds2 & GpsGlonassBds2Signals.GLONASS_L1
        assert int(signals.galileo_bds3) == 0xCF  # bit 3 is reserved
        assert int(signals.gps_glonass_bds2) == 0x91


def test_invalid_and_missing_signal_masks() -> None:
    with pytest.raises(KeyError):
        SolutionSignals.from_record(Record("BESTNAV", ()))
    for value in (-1, 256):
        record = Record(
            "BESTNAV",
            (("galileo_bds3_sig_mask", value), ("gps_glonass_and_bds2_sig_mask", 0)),
        )
        with pytest.raises(ValueError):
            SolutionSignals.from_record(record)
