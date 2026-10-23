import math

import pytest

from test_extra_captures import captured
from um982py.rinex import RinexMetadata, export_rinex


def test_metadata_fixed_width_and_unknowns() -> None:
    metadata = RinexMetadata(
        observer="A",
        agency="Institute",
        receiver_number="123",
        receiver_type="UM982",
        receiver_version="v1",
        antenna_number="456",
        antenna_type="TEST NONE",
        position_xyz=(4000000.0, 1000000.0, 4800000.0),
        antenna_delta_hen=(1.2, -0.03, 0.04),
    )
    text = export_rinex((captured("RANGE"),), metadata=metadata).text
    header = {
        line[60:].strip(): line[:60] for line in text.splitlines() if len(line) >= 60
    }
    assert header["OBSERVER / AGENCY"] == f"{'A':20}{'Institute':40}"
    assert header["REC # / TYPE / VERS"] == f"{'123':20}{'UM982':20}{'v1':20}"
    assert header["ANT # / TYPE"][:40] == f"{'456':20}{'TEST NONE':20}"
    assert (
        header["APPROX POSITION XYZ"][:42]
        == f"{4000000.0:14.4f}{1000000.0:14.4f}{4800000.0:14.4f}"
    )
    assert (
        header["ANTENNA: DELTA H/E/N"][:42] == f"{1.2:14.4f}{-0.03:14.4f}{0.04:14.4f}"
    )
    assert "unknown; zeros are placeholders" not in text
    default = export_rinex((captured("RANGE"),)).text
    assert "Approximate position unknown; zeros are placeholders" in default
    assert "Antenna delta unknown; zeros are placeholders" in default


def test_unknown_phase_alignment_is_declared_for_each_constellation() -> None:
    text = export_rinex((captured("RANGE"),)).text
    lines = text.splitlines()
    systems = {line[0] for line in lines if line[60:] == "SYS / # / OBS TYPES"}
    shifts = [line for line in lines if line[60:] == "SYS / PHASE SHIFT"]
    assert {line[0] for line in shifts} == systems
    assert all(line[1:60] == " " * 59 for line in shifts)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"receiver_type": "X" * 21},
        {"observer": "A\nB"},
        {"antenna_type": "ä"},
        {"position_xyz": (1.0, 2.0, math.nan)},
        {"antenna_delta_hen": (1.0, 2.0)},
        {"position_xyz": (1e20, 0.0, 0.0)},
    ],
)
def test_reject_invalid_metadata(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        RinexMetadata(**kwargs)
