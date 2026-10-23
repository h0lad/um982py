"""Checks units and provenance in scientific example outputs."""

import json
import math
from pathlib import Path

import pytest
from examples.attitude_budget import Baseline, component_budget
from examples.attitude_budget.__main__ import _payload
from examples.baseband_notice_console import __main__ as notices_cli
from examples.pwv_meteorology import __main__ as pwv_cli
from examples.time_transfer import __main__ as time_cli

from conftest import FIXTURES, SubscriptionTransport
from um982py import Receiver
from um982py.geodesy import geodetic_from_ecef
from um982py.messages import Record


@pytest.mark.parametrize(
    "z, latitude", [(6356752.314245, 90.0), (-6356752.314245, -90.0)]
)
def test_ecef_poles_have_finite_geodetic_coordinates(z: float, latitude: float) -> None:
    observed, longitude, height = geodetic_from_ecef(0, 0, z)
    assert observed == latitude
    assert longitude == 0
    assert abs(height) < 1e-6


def test_geodetic_origin_is_explicitly_undefined() -> None:
    with pytest.raises(ValueError, match="centre"):
        geodetic_from_ecef(0, 0, 0)


def test_time_calendar_fields_are_utc_not_gpst(tmp_path: Path) -> None:
    destination = tmp_path / "time.json"
    assert (
        time_cli.main(
            [
                "--replay",
                str(FIXTURES / "captures" / "TIMEB.bin"),
                "--json",
                str(destination),
            ]
        )
        == 0
    )
    output = json.loads(destination.read_text())
    assert output["utc"] == "2026-10-21T20:52:20"
    assert output["gpst"] == "2026-10-21T20:52:38"


def test_relative_baseline_components_keep_length_and_angle_units_separate() -> None:
    budget = component_budget(Baseline(0.0, 1.0, 0.0), 0.01, 0.03, 0.02)
    assert budget.heading_sigma == pytest.approx(math.degrees(0.01))
    assert budget.pitch_sigma == pytest.approx(math.degrees(0.02))
    payload = _payload(budget, ())
    assert payload["required_baseline"]["one_degree"] == pytest.approx(
        0.01 / math.radians(1.0)
    )


def test_manual_pwv_demonstration_is_explicit(tmp_path: Path) -> None:
    destination = tmp_path / "manual.json"
    assert pwv_cli.main(["--manual", "--json", str(destination)]) == 0
    assert json.loads(destination.read_text())["source"] == "manual"


def test_no_fix_ttff_run_is_reported_without_fabricated_statistics() -> None:
    from examples.ttff_profile import StartKind, measure
    from examples.ttff_profile.__main__ import profile_payload

    measurement = measure((), start=StartKind.COLD, reset_seconds=0.0)
    result = profile_payload([((), measurement)])
    assert result["failed_runs"] == 1
    assert result["statistics"] == []
    assert result["runs"][0]["ttff_seconds"] is None


def test_two_point_line_cannot_measure_multipath_residuals() -> None:
    from examples.multipath_analysis import Observation, multipath_series

    samples = [
        Observation(7, float(index), 1575.42e6, 20e6, -1e8) for index in range(2)
    ]
    assert multipath_series(samples) == ()


def test_absolute_position_uncertainty_is_not_used_as_baseline_uncertainty() -> None:
    from examples.attitude_budget.__main__ import _budget

    baseline = Record(
        "BSLNENUHD", (("delta_1", 0.0), ("delta_2", 1.0), ("delta_3", 0.0))
    )
    position = Record("BESTPOS", (("lat_std", 3.0), ("hgt_std", 5.0)))
    assert _budget([baseline], [position]) is None


def test_expected_cleanup_failures_are_readable_and_keep_failure_exit_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from um982py.console import run
    from um982py.errors import ResponseTimeout

    def failed_restore() -> int:
        raise ExceptionGroup("restore failed", [ResponseTimeout("UNLOG timed out")])

    assert run(failed_restore) == 2
    assert "UNLOG timed out" in capsys.readouterr().err


def test_unexpected_programming_errors_are_not_hidden() -> None:
    from um982py.console import run

    def bug() -> int:
        raise ExceptionGroup("bug", [TypeError("broken code")])

    with pytest.raises(ExceptionGroup, match="bug"):
        run(bug)


def test_missing_baseline_does_not_suppress_receiver_spoof_indicator() -> None:
    from examples.spoof_dual_antenna.__main__ import Capture, _payload

    record = Record("SPOOFINFO", (("position_type", "SINGLE"), ("spoof_indicator", 1)))
    result = _payload(Capture(spoof=(record,)))
    assert result["status"] == "incomplete_checks"
    assert result["alarms"] == ["SPOOF_INDICATOR"]


def test_unchecksummed_baseband_notices_are_recorded_during_acknowledgement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]

    class TimedTransport(SubscriptionTransport):
        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending:
                clock[0] += timeout
            return super().read(size, timeout)

    transport = TimedTransport()
    transport.after_write["BBNOTICE COM1 ONCHANGED"] = b"$TrackMode,2\r\n"
    monkeypatch.setattr("um982py.experimental.raw_data.monotonic", lambda: clock[0])
    monkeypatch.setattr("um982py.experimental.raw_data.receiver_state", lambda _: ())
    monkeypatch.setattr("um982py.receiver.monotonic", lambda: clock[0])
    with Receiver(transport) as receiver:
        notices = notices_cli.capture_baseband_notices(receiver, seconds=0.5).notices
        assert receiver.transport is transport
    assert [notice.name for notice in notices] == ["TRACKMODE"]
    assert not transport.subscriptions
