from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from examples.time_transfer import (
    LEAP_SECONDS,
    date_of_year,
    day_of_year,
    gpst_from_utc,
    leap_seconds,
    utc_from_gpst,
    utc_offset_seconds,
)

from um982py.commands import Log
from um982py.messages.record import Record
from um982py.protocol import StreamDecoder

FIXTURES = Path(__file__).parents[2] / "tests" / "fixtures" / "captures"

ROUND_TRIP_EPOCHS = (
    datetime(2012, 7, 1),
    datetime(2013, 1, 1, 12, 30, 15),
    datetime(2015, 7, 1),
    datetime(2016, 12, 31, 23, 59, 59),
    datetime(2017, 1, 1),
    datetime(2020, 2, 29, 6, 0, 0),
    datetime(2026, 10, 21, 20, 52, 20),
)


def time_record() -> Record:
    frames = StreamDecoder().feed((FIXTURES / "TIMEB.bin").read_bytes())
    return next(
        Log.TIME.decode(message)
        for message in frames
        if Log.TIME.request(binary=True).matches(message)
    )


def test_leap_second_table_matches_the_published_steps() -> None:
    published = (
        (datetime(2017, 1, 1), 18),
        (datetime(2015, 7, 1), 17),
        (datetime(2012, 7, 1), 16),
    )
    assert [
        (entry.effective, entry.total_seconds) for entry in LEAP_SECONDS[:3]
    ] == list(published)
    assert LEAP_SECONDS[-1].effective == datetime(1980, 1, 6)
    assert leap_seconds(datetime(1980, 1, 6)) == 0
    assert leap_seconds(datetime(1999, 1, 1)) == 13


def test_leap_seconds_in_force_follow_the_table_boundaries() -> None:
    assert leap_seconds(datetime(2012, 7, 1)) == 16
    assert leap_seconds(datetime(2015, 6, 30, 23, 59, 59)) == 16
    assert leap_seconds(datetime(2015, 7, 1)) == 17
    assert leap_seconds(datetime(2017, 1, 1)) == 18
    assert leap_seconds(datetime(2030, 1, 1)) == 18


def test_epoch_before_the_table_raises() -> None:
    with pytest.raises(ValueError, match="predates"):
        leap_seconds(datetime(1980, 1, 5))


@pytest.mark.parametrize("utc", ROUND_TRIP_EPOCHS)
def test_utc_gpst_utc_round_trip_is_exact(utc: datetime) -> None:
    assert utc_from_gpst(gpst_from_utc(utc)) == utc


def test_gpst_leads_utc_by_the_tabulated_seconds() -> None:
    assert gpst_from_utc(datetime(2026, 10, 21, 20, 52, 20)) == datetime(
        2026, 10, 21, 20, 52, 38
    )


def test_receiver_utc_offset_sign_matches_the_table() -> None:
    assert utc_offset_seconds(datetime(2026, 10, 21, 20, 52, 20)) == pytest.approx(
        -18.0, abs=0.0
    )


def test_inserted_leap_second_is_rejected_instead_of_shifted() -> None:
    with pytest.raises(ValueError, match="leap second"):
        utc_from_gpst(datetime(2017, 1, 1, 0, 0, 17))
    assert utc_from_gpst(datetime(2017, 1, 1, 0, 0, 18)) == datetime(2017, 1, 1)


def test_disagreement_between_receiver_and_table_does_not_emit_gpst(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from examples.time_transfer import __main__ as cli

    record = Record(
        "TIME",
        tuple(
            {
                "year": 2026,
                "month": 1,
                "day": 1,
                "hour": 0,
                "minute": 0,
                "millisecond": 0,
                "utc_status": "VALID",
                "utc_offset": -19.0,
            }.items()
        ),
    )
    monkeypatch.setattr(cli, "capture_records", lambda *a, **kw: {"TIME": [record]})
    assert cli.main([]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "offset_disagreement"
    assert data["gpst"] is None


def test_fixture_utc_offset_equals_the_tabulated_leap_seconds() -> None:
    record = time_record()
    gpst = datetime(
        int(record.real("year")),
        int(record.real("month")),
        int(record.real("day")),
        int(record.real("hour")),
        int(record.real("minute")),
    ) + timedelta(seconds=record.real("millisecond") / 1000.0)
    assert record.real("utc_offset") == pytest.approx(
        -float(leap_seconds(utc_from_gpst(gpst))), abs=0.0
    )


def test_known_gpst_epoch_converts_to_the_hand_computed_calendar_date() -> None:
    gpst = datetime(2026, 10, 21, 20, 52, 20)
    utc = utc_from_gpst(gpst)
    assert utc == datetime(2026, 10, 21, 20, 52, 2)
    assert (utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second) == (
        2026,
        10,
        21,
        20,
        52,
        2,
    )
    assert day_of_year(utc.date()) == 294


def test_day_of_year_handles_leap_years() -> None:
    assert day_of_year(date(2016, 2, 29)) == 60
    assert day_of_year(date(2017, 3, 1)) == 60
    assert day_of_year(date(2020, 12, 31)) == 366
    assert day_of_year(date(2019, 12, 31)) == 365


def test_day_of_year_round_trips_through_the_calendar() -> None:
    assert date_of_year(2016, 60) == date(2016, 2, 29)
    assert date_of_year(2017, 60) == date(2017, 3, 1)
    for moment in (date(2012, 7, 1), date(2020, 2, 29), date(2026, 10, 21)):
        assert date_of_year(moment.year, day_of_year(moment)) == moment
        assert day_of_year(moment) == moment.timetuple().tm_yday


def test_day_outside_the_year_raises() -> None:
    with pytest.raises(ValueError, match="outside the year"):
        date_of_year(2019, 366)
    with pytest.raises(ValueError, match="positive"):
        date_of_year(2019, 0)


def test_invalid_receiver_utc_is_reported_without_calendar_conversion(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from examples.time_transfer import __main__ as cli

    from um982py.messages import Record

    invalid = Record("TIME", (("year", 0), ("utc_status", "INVALID")))
    monkeypatch.setattr(cli, "capture_records", lambda *a, **kw: {"TIME": [invalid]})
    assert cli.main([]) == 1
    assert "receiver UTC is not valid" in capsys.readouterr().out


def test_replay_reports_receiver_pps_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from examples.time_transfer import __main__ as cli

    replay = tmp_path / "time-and-pps.bin"
    replay.write_bytes(
        (FIXTURES / "TIMEB.bin").read_bytes()
        + (FIXTURES / "PPSSTATUSB.bin").read_bytes()
    )
    assert cli.main(["--replay", str(replay), "--pps-status"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["pps_status"]["status"] == 3
    assert result["pps_status"]["pulse_error_ns"] is not None
