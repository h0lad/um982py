"""Receiver positions must match absolute GNSS epochs, not capture order."""

from dataclasses import replace
from pathlib import Path

import pytest

from um982py.capture import load_records, select_position, select_position_pair
from um982py.commands import Log
from um982py.messages import AsciiMessage, OemAsciiHeader, Record

FIXTURE = Path(__file__).parent / "fixtures" / "captures" / "BESTXYZA.bin"


def position(week: int, sow: float, status: str = "SOL_COMPUTED") -> Record:
    record = load_records(FIXTURE, Log.BESTXYZ)[0]
    assert isinstance(record.message, AsciiMessage)
    assert isinstance(record.message.header, OemAsciiHeader)
    fields = list(record.message.header.fields)
    fields[4:6] = str(week), str(sow)
    header = replace(record.message.header, fields=tuple(fields))
    return replace(
        record,
        message=replace(record.message, header=header),
        entries=tuple(
            (key, status if key == "p_sol_status" else value)
            for key, value in record.entries
        ),
    )


def test_position_selection_crosses_week_boundary_and_prefers_earlier_tie() -> None:
    earlier = position(2440, 604799.5)
    later = position(2441, 0.5)
    epoch = 2441 * 604800
    assert select_position([later, earlier], epoch, 0.5) is earlier
    with pytest.raises(ValueError, match="no valid"):
        select_position([earlier, later], epoch, 0.4)


def test_invalid_and_untimestamped_positions_do_not_mask_valid_fix() -> None:
    valid = position(2441, 100.5)
    invalid = position(2441, 100, "INSUFFICIENT_OBS")
    untimed = replace(valid, message=None)
    at_centre = replace(
        valid,
        entries=tuple(
            (key, 0 if key in ("p_x", "p_y", "p_z") else value)
            for key, value in valid.entries
        ),
    )
    assert (
        select_position([invalid, untimed, at_centre, valid], 2441 * 604800 + 100, 1)
        is valid
    )


def test_pairing_skips_unmatched_startup_epoch() -> None:
    unmatched = position(2441, 100.0)
    observation = position(2441, 102.0)
    before = position(2441, 101.5)
    after = position(2441, 102.5)
    assert select_position_pair([unmatched, observation], [after, before], 0.5) == (
        observation,
        before,
    )


@pytest.mark.parametrize(
    "epoch,tolerance", [(float("nan"), 1), (0, float("inf")), (0, -1)]
)
def test_invalid_matching_parameters_are_rejected(
    epoch: float, tolerance: float
) -> None:
    with pytest.raises(ValueError, match="finite"):
        select_position([], epoch, tolerance)
