"""Tests the signal-group trade study against ground truth."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from examples.dop_geometry import (
    ReportedDilution,
    SatelliteGeometry,
    geometry_from_records,
)
from examples.rtk_quality import FixClass
from examples.signal_group_study import (
    DopAgreement,
    SettingSample,
    agreement,
    first_visibility_epoch,
    summarise,
    trade_study,
)
from examples.signal_group_study.__main__ import main

from conftest import FIXTURES
from um982py.commands.configuration import SignalGroup
from um982py.experimental import FirmwareLog
from um982py.messages.enums import PositionType
from um982py.messages.record import Record
from um982py.protocol import StreamDecoder

LIVE = FIXTURES / "captures-live"
CAPTURED_SATELLITES = 33
CAPTURED_PDOP = 0.8118
CAPTURED_REPORTED_PDOP = 1.0243
ZENITH = SatelliteGeometry(0.0, 90.0)
NORTH = SatelliteGeometry(0.0, 0.0)
EAST = SatelliteGeometry(90.0, 0.0)
SOUTH = SatelliteGeometry(180.0, 0.0)
WEST = SatelliteGeometry(270.0, 0.0)
THREE_HORIZONS = (ZENITH,) * 4 + (NORTH, EAST, SOUTH)
FOUR_HORIZONS = (*THREE_HORIZONS, WEST)
SEVEN_SATELLITE_PDOP = math.sqrt(2.75)
EIGHT_SATELLITE_PDOP = math.sqrt(1.5)
WIDE_CN0 = (45.0, 44.5, 46.0, 43.5, 39.0, 38.5, 40.0, 39.5)
NARROW_CN0 = (45.0, 44.5, 46.0, 43.5, 39.0, 38.5, 40.0)


def reported(pdop: float, *, satellites: int) -> ReportedDilution:
    """Reported DOP carrying a stated position DOP for the injected sky."""
    return ReportedDilution(
        source="injected",
        gdop=pdop,
        pdop=pdop,
        hdop=pdop,
        tdop=pdop,
        elevation_mask=5.0,
        satellites=satellites,
    )


def sample(
    setting: SignalGroup,
    geometry: tuple[SatelliteGeometry, ...],
    cn0: tuple[float, ...],
    pdop: float,
    position_type: PositionType,
) -> SettingSample:
    """Injected sample whose reported DOP is the closed form of its geometry."""
    return SettingSample(
        setting=setting,
        geometry=geometry,
        reported=reported(pdop, satellites=len(geometry)),
        cn0=cn0,
        position_type=position_type,
    )


def injected_samples() -> tuple[SettingSample, ...]:
    """Two settings whose closed-form DOPs differ by one horizon satellite."""
    return (
        sample(
            SignalGroup(4, 5),
            FOUR_HORIZONS,
            WIDE_CN0,
            EIGHT_SATELLITE_PDOP,
            PositionType.NARROW_INT,
        ),
        sample(
            SignalGroup(5, 0),
            THREE_HORIZONS,
            NARROW_CN0,
            SEVEN_SATELLITE_PDOP,
            PositionType.NARROW_FLOAT,
        ),
    )


def live_records(name: str) -> list[Record]:
    """Decode one log of the 26-epoch live capture."""
    request = FirmwareLog[name].request()
    return [
        FirmwareLog[name].decode(message)
        for message in StreamDecoder().feed((LIVE / (name + "A.bin")).read_bytes())
        if request.matches(message)
    ]


def captured_dop() -> ReportedDilution:
    return ReportedDilution.from_record(live_records("PSRDOP")[0], "PSRDOPA")


def captured_geometry() -> tuple[SatelliteGeometry, ...]:
    return geometry_from_records(
        first_visibility_epoch(live_records("SATVIS2")),
        captured_dop().elevation_mask,
    )


def test_recomputed_pdop_matches_the_closed_form_of_the_injected_sky() -> None:
    wide, narrow = trade_study(injected_samples())
    assert wide.dilutions.pdop == pytest.approx(EIGHT_SATELLITE_PDOP, abs=1e-12)
    assert narrow.dilutions.pdop == pytest.approx(SEVEN_SATELLITE_PDOP, abs=1e-12)
    assert wide.dilutions.hdop == pytest.approx(1.0, abs=1e-12)
    assert narrow.dilutions.vdop == pytest.approx(math.sqrt(0.75), abs=1e-12)


def test_receiver_pdop_agreement_is_exact_for_the_injected_table() -> None:
    for summary in trade_study(injected_samples()):
        assert summary.agreement is DopAgreement.MATCH
        assert summary.pdop_excess == pytest.approx(0.0, abs=1e-12)


def test_agreement_accepts_a_reported_value_within_five_percent() -> None:
    assert agreement(1.2875, 1.25) is DopAgreement.MATCH
    assert agreement(1.2125, 1.25) is DopAgreement.MATCH


def test_agreement_reports_a_reported_value_above_the_recomputation() -> None:
    assert agreement(0.5, 1.25) is DopAgreement.LOWER_BOUND


def test_agreement_flags_a_recomputation_above_the_reported_value() -> None:
    assert agreement(1.5, 1.25) is DopAgreement.VIOLATED


def test_trade_study_tabulates_satellites_cn0_and_fix_class() -> None:
    wide, narrow = trade_study(injected_samples())
    assert (wide.satellites, wide.signals) == (8, 8)
    assert (narrow.satellites, narrow.signals) == (7, 7)
    assert wide.mean_cn0 == pytest.approx(42.0, abs=1e-12)
    assert narrow.mean_cn0 == pytest.approx(42.357142857142854, abs=1e-12)
    assert wide.fix_class is FixClass.FIXED
    assert narrow.fix_class is FixClass.FLOAT


def test_trade_study_keeps_the_sampling_order() -> None:
    summaries = trade_study(injected_samples())
    assert [summary.setting.master for summary in summaries] == [4, 5]


def test_trade_study_rejects_a_repeated_setting() -> None:
    samples = injected_samples()
    with pytest.raises(ValueError):
        trade_study((samples[0], samples[0]))


def test_captured_satellite_count_agrees_with_the_visibility_epoch() -> None:
    assert len(captured_geometry()) == CAPTURED_SATELLITES
    assert captured_dop().satellites < CAPTURED_SATELLITES


def test_captured_dop_is_a_lower_bound_of_the_receiver_psrdop() -> None:
    dilution = captured_dop()
    summary = summarise(
        SettingSample(
            setting=SignalGroup(4, 5),
            geometry=captured_geometry(),
            reported=dilution,
            cn0=WIDE_CN0,
            position_type=PositionType.SINGLE,
        )
    )
    assert summary.satellites == CAPTURED_SATELLITES
    assert dilution.pdop == pytest.approx(CAPTURED_REPORTED_PDOP, abs=1e-12)
    assert summary.dilutions.pdop == pytest.approx(CAPTURED_PDOP, abs=1e-4)
    assert summary.dilutions.pdop <= dilution.pdop + 1e-9
    assert summary.agreement is DopAgreement.LOWER_BOUND
    assert summary.pdop_excess == pytest.approx(
        summary.dilutions.pdop - dilution.pdop, abs=1e-12
    )


def test_main_reports_the_two_injected_settings(tmp_path: Path) -> None:
    destination = tmp_path / "study.json"
    assert main(["--json", str(destination)]) == 0
    payload = json.loads(destination.read_text())
    assert [row["master"] for row in payload["settings"]] == [4, 5]
    assert payload["settings"][0]["pdop"] == pytest.approx(
        EIGHT_SATELLITE_PDOP, abs=1e-12
    )
    assert payload["restore"] is None


def test_live_study_restores_receiver_after_measurement_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from argparse import Namespace
    from unittest.mock import MagicMock

    from examples.signal_group_study import __main__ as cli

    from um982py.state import ReceiverState, StateRestoration

    receiver = MagicMock()
    receiver.__enter__.return_value = receiver
    original = SignalGroup(3, 6)
    receiver.execute.return_value = original
    baseline = ReceiverState((), ("MODE ROVER SURVEY", ""), (), ())
    restore = MagicMock(return_value=StateRestoration(baseline, baseline, ()))
    monkeypatch.setattr(cli, "open_receiver", lambda args: receiver)
    monkeypatch.setattr(cli, "snapshot_receiver_state", lambda device: baseline)
    monkeypatch.setattr(cli, "restore_receiver_state", restore)
    monkeypatch.setattr(cli, "sleep", lambda seconds: None)

    def fail_measurement(args: Namespace, setting: SignalGroup) -> SettingSample:
        raise ValueError("measurement failed")

    monkeypatch.setattr(cli, "measure_setting", fail_measurement)
    with pytest.raises(ValueError, match="measurement failed"):
        cli.live_study(Namespace(settings=[(4, 5)], reboot_seconds=0))
    receiver.send.assert_called_once()
    assert receiver.send.call_args.args[0].text == "CONFIG SIGNALGROUP 3 6"
    restore.assert_called_once_with(receiver, baseline)
