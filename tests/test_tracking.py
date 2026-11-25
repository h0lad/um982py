def test_live_slots_are_reference_cn0_of_both_antennas() -> None:
    # Recorded PTOBSINFOB at GPST 286142 s of week 2446. The same-epoch RANGE
    # (ANT1) and RANGEH (ANT2) give 48.667 and 45.140 dB-Hz as the mean C/N0
    # of the three strongest GPS L1 C/A satellites.
    from pathlib import Path

    from um982py.commands import Log
    from um982py.experimental.tracking import tracking_slots
    from um982py.protocol import StreamDecoder

    fixture = Path(__file__).parent / "fixtures" / "crosscheck" / "PTOBSINFOB.bin"
    message = next(iter(StreamDecoder().feed(fixture.read_bytes())))
    slots = tracking_slots(Log.PTOBSINFO.decode(message))
    ant1 = next(s for s in slots if s.antenna == 1 and s.rf_group == "GPS L1 C/A")
    ant2 = next(s for s in slots if s.antenna == 2 and s.rf_group == "GPS L1 C/A")
    assert ant1.reference_cn0_db_hz is not None
    assert ant2.reference_cn0_db_hz is not None
    assert abs(ant1.reference_cn0_db_hz - 48.667) < 0.02
    assert abs(ant2.reference_cn0_db_hz - 45.140) < 0.02
    assert all(
        slot.reference_cn0_db_hz is None for slot in slots if slot.native_value <= 0
    )
