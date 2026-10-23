from dataclasses import replace

import pytest

from um982py.messages import BinaryHeader, BinaryMessage, Record
from um982py.observation_pairing import pair_base_rover_observations


def observation(prn: int, signal: int = 0, system: int = 0) -> Record:
    status = (system << 16) | (signal << 21) | 0x1C00
    return Record(
        "observations",
        (("prn_slot", prn), ("system_freq", 0), ("ch_tr_status", status)),
    )


def epoch(name: str, seconds: int, items: tuple[Record, ...]) -> Record:
    header = BinaryHeader(
        0, 284 if name == "OBSVBASE" else 12, 0, 0, 0, 2300, seconds * 1000, 0, 0, 0, 0
    )
    return Record(name, (("observations", items),), BinaryMessage(header, b"", b""))


def test_pairs_only_matching_native_signal_and_preserves_unmatched() -> None:
    base = epoch("OBSVBASE", 100, (observation(1), observation(2, 9)))
    rover = epoch("OBSVM", 100, (observation(1), observation(2, 14), observation(3)))
    result = pair_base_rover_observations([base], [rover])
    assert len(result) == 1
    assert [item.identity.satellite for item in result[0].pairs] == [1]
    assert result[0].base_only == 1 and result[0].rover_only == 2


def test_rejects_ambiguous_epochs_and_duplicate_signals() -> None:
    row = observation(1)
    base = epoch("OBSVBASE", 100, (row,))
    rover = epoch("OBSVM", 100, (row,))
    with pytest.raises(ValueError, match="duplicate observation epochs"):
        pair_base_rover_observations([base, base], [rover])
    with pytest.raises(ValueError, match="multiple rover epochs"):
        pair_base_rover_observations(
            [base], [rover, epoch("OBSVM", 101, (row,))], tolerance=1
        )
    with pytest.raises(ValueError, match="duplicate native signal"):
        pair_base_rover_observations(
            [replace(base, entries=(("observations", (row, row)),))], [rover]
        )


def test_rejects_reusing_a_rover_epoch_and_nonfinite_tolerance() -> None:
    base = [epoch("OBSVBASE", n, (observation(1),)) for n in (100, 101)]
    rover = [epoch("OBSVM", 100, (observation(1),))]
    with pytest.raises(ValueError, match="same rover epoch"):
        pair_base_rover_observations(base, rover, tolerance=1)
    with pytest.raises(ValueError, match="finite"):
        pair_base_rover_observations(base, rover, tolerance=float("nan"))
