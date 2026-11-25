"""Checks broadcast leap-second rules and cross-system UTC agreement."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from examples.utc_leap_monitor import galileo_gps_offset, utc_parameters
from examples.utc_leap_monitor.__main__ import main

from um982py.capture import load_records
from um982py.commands import Log
from um982py.gnss import DAY_SECONDS, WEEK_SECONDS, leap_seconds_at
from um982py.messages import Record

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
REPLAY = FIXTURES / "specialist" / "utc-parameters.bin"
GPS = load_records(FIXTURES / "captures" / "IONUTCB.bin", Log.IONUTC)[0]
GALILEO = load_records(FIXTURES / "bodies" / "GALUTCB.bin", Log.GALUTC)[0]
BEIDOU = load_records(FIXTURES / "bodies" / "BDSUTCA.bin", Log.BDSUTC)[0]
LEAP = 2500 * WEEK_SECONDS + 7 * DAY_SECONDS + 18
"""GPS second at which an announced 19th leap second takes effect."""


def edited(record: Record, **fields: object) -> Record:
    return replace(record, entries=tuple((dict(record) | fields).items()))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("epoch", "expected"), [(LEAP - 1, 18), (LEAP, 19), (LEAP + 86_400, 19)]
)
def test_announced_leap_second_applies_after_utc_midnight(
    epoch: float, expected: int
) -> None:
    assert (
        leap_seconds_at(epoch, deltat_ls=18, wn_lsf=2500, dn=7, deltat_lsf=19)
        == expected
    )


def test_eight_bit_leap_week_resolves_near_the_epoch() -> None:
    assert (
        leap_seconds_at(LEAP, deltat_ls=18, wn_lsf=2500 % 256, dn=7, deltat_lsf=19)
        == 19
    )
    with pytest.raises(ValueError, match=r"1\.\.7"):
        leap_seconds_at(LEAP, deltat_ls=18, wn_lsf=2500, dn=0, deltat_lsf=19)


def test_every_system_maps_to_the_gps_week_and_day_convention() -> None:
    systems = [utc_parameters(record) for record in (GPS, GALILEO, BEIDOU)]
    assert {item.wn_lsf for item in systems} == {2441}
    assert {item.dn for item in systems} == {7}
    assert {item.deltat_ls for item in systems} == {18}
    assert utc_parameters(GALILEO).reference == 2441 * WEEK_SECONDS + 72 * 3600


def test_ggto_resolves_its_six_bit_week() -> None:
    epoch = 2441 * WEEK_SECONDS + 345_600 + 100.0
    assert galileo_gps_offset(GALILEO, epoch) == pytest.approx(
        GALILEO.real("da0g") + 100 * GALILEO.real("da1g")
    )


def test_replay_of_one_session_agrees(tmp_path: Path) -> None:
    report = tmp_path / "utc.json"
    assert main(["--replay", str(REPLAY), "--json", str(report)]) == 0
    result = json.loads(report.read_text())
    assert result["status"] == "ok"
    assert result["epoch_utc"] == "2026-10-21T20:52:20+00:00"
    assert set(result["systems"]) == {"GALILEO", "BEIDOU"}
    assert result["receiver_utc_offset_s"] == -18


def capture_of(*records: Record) -> object:
    def capture(args: object, logs: object, **options: object) -> dict[str, object]:
        names = ("IONUTC", "GALUTC", "BDSUTC", "TIME")
        return {
            name: tuple(item for item in records if item.name == name) for name in names
        }

    return capture


def test_announced_leap_second_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    epoch = 2441 * WEEK_SECONDS + 300_000.0
    gps = edited(
        GPS,
        utc_wn=2441,
        tot=294_912,
        wn_lsf=2442,
        dn=1,
        deltat_lsf=19,
    )
    galileo = edited(GALILEO, ulwnlsf=1418, dn=1, deltat_lsf=19)
    monkeypatch.setattr(
        "examples.utc_leap_monitor.__main__.capture_records",
        capture_of(gps, galileo),
    )
    monkeypatch.setattr(
        "examples.utc_leap_monitor.__main__.gps_epoch", lambda record: epoch
    )
    report = tmp_path / "utc.json"
    assert main(["--json", str(report)]) == 0
    result = json.loads(report.read_text())
    for system in ("GPS", "GALILEO"):
        assert result["systems"][system]["leap_second_announced"] is True
        assert (
            result["systems"][system]["leap_second_effective_utc"]
            == "2026-10-26T00:00:00+00:00"
        )
    assert result["galileo_gps_time_offset"] is not None


def test_disagreeing_announcements_raise_an_alarm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    epoch = 2441 * WEEK_SECONDS + 300_000.0
    gps = edited(GPS, utc_wn=2441, tot=294_912, wn_lsf=2442, dn=1, deltat_lsf=19)
    monkeypatch.setattr(
        "examples.utc_leap_monitor.__main__.capture_records",
        capture_of(gps, GALILEO),
    )
    monkeypatch.setattr(
        "examples.utc_leap_monitor.__main__.gps_epoch", lambda record: epoch
    )
    report = tmp_path / "utc.json"
    assert main(["--json", str(report)]) == 1
    assert json.loads(report.read_text())["status"] == "alarm"
