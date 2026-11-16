from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from um982py.capture import InterruptedCapture, load_records
from um982py.commands import Log
from um982py.measurement import sample_series
from um982py.messages import Record
from um982py.observation_pairing import pair_base_rover_observations
from um982py.observation_quality import audit_observations
from um982py.observations import Observations, record_observations
from um982py.provenance import ObservationSource
from um982py.rinex import export_rinex

SOURCE = ObservationSource("UM982-test", "occupation-1", 1)
RECORDS = load_records(
    Path(__file__).parent / "fixtures/captures-live/RANGEA.bin", Log.RANGE
)


def test_source_tags_survive_slicing_and_wrapping_without_changing_wire_data() -> None:
    captured = Observations(RECORDS, source=SOURCE)
    assert captured.source == SOURCE
    assert all(record.source == SOURCE for record in captured.records)
    assert all(record.source is None for record in RECORDS)
    subset = Observations(captured.records[:2])
    assert subset.source == SOURCE
    assert subset.records[0].message is RECORDS[0].message
    assert dict(subset.records[0]) == dict(RECORDS[0])
    assert ObservationSource(**asdict(SOURCE)) == SOURCE
    created_at = datetime(2025, 1, 1, tzinfo=UTC)
    assert (
        captured.to_rinex(created_at=created_at).text
        == Observations(RECORDS).to_rinex(created_at=created_at).text
    )
    assert captured.quality() == Observations(RECORDS).quality()
    assert captured.signals() == Observations(RECORDS).signals()


def test_rinex_creation_time_is_explicit_and_normalized() -> None:
    local = datetime(2025, 1, 1, 2, tzinfo=timezone(timedelta(hours=2)))
    utc = datetime(2025, 1, 1, tzinfo=UTC)
    first = export_rinex(RECORDS, created_at=local).text
    assert first == Observations(RECORDS).to_rinex(created_at=utc).text
    assert "20250101 000000 UTC" in first
    with pytest.raises(ValueError, match="timezone-aware"):
        export_rinex(RECORDS, created_at=datetime(2025, 1, 1))


@pytest.mark.parametrize(
    "other",
    [
        replace(SOURCE, receiver_id="another-receiver"),
        replace(SOURCE, session_id="another-occupation"),
        replace(SOURCE, antenna=2),
    ],
)
@pytest.mark.parametrize(
    "analyse", [Observations, sample_series, audit_observations, export_rinex]
)
def test_analysis_rejects_combined_sources_even_with_ordered_matching_log_epochs(
    other: ObservationSource, analyse: Callable[[tuple[Record, ...]], object]
) -> None:
    records = (replace(RECORDS[0], source=SOURCE), replace(RECORDS[1], source=other))
    with pytest.raises(ValueError, match="different receiver, session or antenna"):
        analyse(records)


@pytest.mark.parametrize(
    "analyse", [Observations, sample_series, audit_observations, export_rinex]
)
def test_known_and_unknown_sources_cannot_be_silently_combined(
    analyse: Callable[[tuple[Record, ...]], object],
) -> None:
    records = (replace(RECORDS[0], source=SOURCE), RECORDS[1])
    with pytest.raises(ValueError, match="known and unknown"):
        analyse(records)


def test_source_cannot_relabel_tagged_records_from_another_session() -> None:
    records = Observations(RECORDS, source=SOURCE).records
    with pytest.raises(ValueError, match="different receiver, session or antenna"):
        Observations(records, source=replace(SOURCE, session_id="different"))


def test_declared_antenna_must_agree_with_native_observation_log() -> None:
    with pytest.raises(ValueError, match="antenna disagrees"):
        Observations(RECORDS, source=replace(SOURCE, antenna=2))
    secondary = tuple(replace(record, name="RANGEH") for record in RECORDS)
    assert (
        Observations(secondary, source=replace(SOURCE, antenna=2)).source.antenna == 2
    )


def test_live_captures_receive_distinct_ids_and_keep_the_declared_receiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "um982py.observations.capture_live", lambda *args, **kwargs: {"RANGE": RECORDS}
    )
    first = record_observations(None, duration=1, receiver_id="serial-42")  # type: ignore[arg-type]
    second = record_observations(None, duration=1, receiver_id="serial-42")  # type: ignore[arg-type]
    assert first.source is not None and second.source is not None
    assert first.source.receiver_id == second.source.receiver_id == "serial-42"
    assert first.source.session_id != second.source.session_id
    assert first.records[0].source == first.source
    with pytest.raises(ValueError, match="different receiver, session or antenna"):
        Observations(first.records[:1] + second.records[1:])


def test_interruption_preserves_source_tags_for_partial_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(*args: object, **kwargs: object) -> None:
        raise InterruptedCapture({"RANGE": RECORDS})

    monkeypatch.setattr("um982py.observations.capture_live", interrupt)
    with pytest.raises(InterruptedCapture) as caught:
        record_observations(None, duration=1, receiver_id="serial-42")  # type: ignore[arg-type]
    partial = Observations(caught.value.records["RANGE"])
    assert partial.source is not None
    assert partial.source.receiver_id == "serial-42"
    assert partial.to_rinex().epochs == 26


def test_pairing_validates_each_input_stream_separately() -> None:
    base = (
        Record("OBSVBASE", (), source=SOURCE),
        Record("OBSVBASE", (), source=replace(SOURCE, session_id="another")),
    )
    with pytest.raises(ValueError, match="different receiver, session or antenna"):
        pair_base_rover_observations(base, ())
    rover = tuple(replace(record, name="OBSVM") for record in base)
    with pytest.raises(ValueError, match="different receiver, session or antenna"):
        pair_base_rover_observations((), rover)


@pytest.mark.parametrize(
    "changes",
    [
        {"receiver_id": ""},
        {"receiver_id": 42},
        {"session_id": " "},
        {"session_id": None},
        {"antenna": True},
        {"antenna": 0},
        {"antenna": 3},
    ],
)
def test_invalid_provenance_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        replace(SOURCE, **changes)


def test_invalid_source_objects_fail_before_analysis() -> None:
    with pytest.raises(TypeError, match="ObservationSource"):
        Observations(RECORDS, source="serial-42")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="ObservationSource"):
        Observations((replace(RECORDS[0], source="serial-42"),))
