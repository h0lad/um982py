from datetime import UTC, datetime, timedelta, timezone

import pytest

from um982py.commands import assistance


def test_assisted_time_requires_a_verified_leap_second_offset() -> None:
    with pytest.raises(TypeError):
        assistance.time(datetime(2021, 12, 3, tzinfo=UTC))  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        assistance.time_fields(2021, 12, 3, 0, 0, 0, 0)  # type: ignore[call-arg]


def test_assisted_time_converts_timezone_and_preserves_the_offset() -> None:
    local = datetime(2016, 12, 31, 14, 1, 2, 345678, timezone(timedelta(hours=1)))
    assert assistance.time(local, leap_seconds=17).text == (
        "AIDTIME,2016,12,31,13,1,2,345,17"
    )
    assert assistance.time_fields(2016, 12, 31, 23, 59, 60, 0, 17).text == (
        "AIDTIME,2016,12,31,23,59,60,0,17"
    )


@pytest.mark.parametrize("offset", [-1, 256, True, 1.5])
def test_assisted_time_rejects_invalid_leap_seconds(offset: int) -> None:
    with pytest.raises(ValueError):
        assistance.time(datetime(2021, 12, 3, tzinfo=UTC), leap_seconds=offset)
    with pytest.raises(ValueError):
        assistance.time_fields(2021, 12, 3, 0, 0, 0, 0, offset)


def test_assisted_time_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        assistance.time(datetime(2021, 12, 3), leap_seconds=18)
