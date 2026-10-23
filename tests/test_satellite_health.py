from dataclasses import replace

import pytest

from test_bodies import manual_message
from um982py.messages import decode_log
from um982py.messages.record import Record
from um982py.messages.satellite_health import (
    EphemerisHealth,
    GalileoDataValidity,
    GalileoEphemerisHealth,
    GalileoSignalHealth,
)


def test_manual_ephemerides() -> None:
    gal = GalileoEphemerisHealth.from_record(decode_log(manual_message("GALEPHA")))
    assert gal.satellite_id == 36
    assert gal.e1b.health is GalileoSignalHealth.OK
    assert gal.e5a.data_validity is GalileoDataValidity.VALID
    glo = EphemerisHealth.from_record(decode_log(manual_message("GLOEPHA")))
    assert (glo.system, glo.satellite_id, glo.healthy) == ("GLONASS", 3, True)
    bds = EphemerisHealth.from_record(decode_log(manual_message("BDSEPHA")))
    assert (bds.satellite_id, bds.healthy) == (60, True)
    bd3 = EphemerisHealth.from_record(decode_log(manual_message("BD3EPHA")))
    assert (bd3.satellite_id, bd3.signal, bd3.healthy) == (44, "B2a", True)


def test_galileo_reception_and_unknown_codes() -> None:
    original = decode_log(manual_message("GALEPHA"))
    values = dict(original.entries)
    values.update(
        fnavreceived="FALSE", inavreceived=1, e1bhealth=2, e1bdvs=1, e5bhealth=4
    )
    report = GalileoEphemerisHealth.from_record(
        replace(original, entries=tuple(values.items()))
    )
    assert report.e5a.health is None and report.e5a.data_validity is None
    assert report.e1b.health is GalileoSignalHealth.EXTENDED_OPERATIONS
    assert report.e1b.data_validity is GalileoDataValidity.WITHOUT_GUARANTEE
    assert report.e5b.health is None and report.e5b.health_code == 4
    values["inavreceived"] = "UNKNOWN"
    assert (
        GalileoEphemerisHealth.from_record(
            replace(original, entries=tuple(values.items()))
        ).e1b.health
        is None
    )


def test_unknown_and_incompatible_records() -> None:
    record = Record("GLOEPH", (("sloto", 40), ("health", 2)))
    assert EphemerisHealth.from_record(record).healthy is None
    with pytest.raises(ValueError):
        EphemerisHealth.from_record(Record("GPSEPH", ()))
    with pytest.raises(ValueError):
        GalileoEphemerisHealth.from_record(record)
