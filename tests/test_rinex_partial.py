from dataclasses import replace

from tests.examples._new_api import observation, record
from um982py.messages import Record
from um982py.rinex import export_rinex


def _with_status(row: Record, status: int) -> Record:
    return replace(
        row,
        entries=tuple(
            (key, status if key == "tracking_status" else value)
            for key, value in row.entries
        ),
    )


def test_partial_code_and_phase_observations_are_preserved() -> None:
    source = record(0, [observation(prn=1), observation(prn=2)])
    first, second = source.records("observations")
    modified = replace(
        source,
        entries=(
            (
                "observations",
                (_with_status(first, 0x1000), _with_status(second, 0x0400)),
            ),
        ),
    )
    result = export_rinex((modified,))
    lines = {
        line[:3]: line[3:]
        for line in result.text.splitlines()
        if line.startswith(("G01", "G02"))
    }
    # The observation order is C, L, D, S. Blank fields have no valid value.
    assert lines["G01"][:14].strip()
    assert lines["G01"][16:48] == " " * 32
    assert lines["G01"][48:62].strip()
    assert lines["G02"][:16] == " " * 16
    assert lines["G02"][16:30].strip()
    assert result.signal_observations == 2
    assert result.omitted["invalid_code_or_phase"] == 2


def test_duplicate_prefers_complete_observation_to_stronger_partial() -> None:
    source = record(
        0, [observation(cn0=50, code=21000000), observation(cn0=40, code=22000000)]
    )
    partial, complete = source.records("observations")
    modified = replace(
        source, entries=(("observations", (_with_status(partial, 0x1000), complete)),)
    )
    result = export_rinex((modified,))
    line = next(line for line in result.text.splitlines() if line.startswith("G01"))
    assert float(line[3:17]) == 22000000
    assert line[19:33].strip()


def test_bad_pseudorange_does_not_discard_valid_phase() -> None:
    source = record(0, [observation(code=0)])
    result = export_rinex((source,))
    line = next(line for line in result.text.splitlines() if line.startswith("G01"))
    assert line[3:19] == " " * 16
    assert line[19:33].strip()
    assert result.omitted["invalid_numeric_value"] == 1
