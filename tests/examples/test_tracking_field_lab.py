"""Checks field associations against labelled increasing and constant values."""

import pytest
from examples.tracking_field_lab import correlate_fields, written_fields

from um982py.experimental import TrackingField
from um982py.messages import Record


def test_known_field_rank_and_sign_are_recovered_without_assigning_names() -> None:
    frames = [
        (
            float(i),
            (
                TrackingField("field_06", 20, "f", 2 * i + 10),
                TrackingField("field_12", 44, "f", 10 - i),
                TrackingField("field_01", 0, "u", 1),
                TrackingField("field_11", 40, "x", i),
            ),
        )
        for i in range(6)
    ]
    result = {
        item.name: item
        for item in correlate_fields(frames, {float(i): i for i in range(6)})
    }
    assert result["field_06"].correlation == pytest.approx(1)
    assert result["field_12"].correlation == pytest.approx(-1)
    assert result["field_01"].correlation is None
    assert "field_11" not in result
    assert result["field_06"].offset == 20


def test_duplicate_epochs_require_channel_selection() -> None:
    with pytest.raises(ValueError, match="channel selector"):
        correlate_fields([(1, ()), (1, ())], {1: 2})


def test_ambiguous_reference_join_is_rejected() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        correlate_fields([(1, ())], {1.0: 1, 1.0001: 2})


def test_constant_label_has_no_correlation_claim() -> None:
    result = correlate_fields(
        [(float(i), (TrackingField("field_06", 20, "f", i),)) for i in range(6)],
        {float(i): 4 for i in range(6)},
    )
    assert result[0].correlation is None


def test_unwritten_slots_are_excluded_even_when_they_contain_values() -> None:
    fields = [(f"field_{i:02}", 1 << 1 if i == 11 else float(i)) for i in range(1, 30)]
    result = written_fields(Record("PTOBSINFO", tuple(fields)))
    names = {field.name for field in result}
    assert "field_12" not in names
    assert "field_13" in names
    assert "field_14" not in names
