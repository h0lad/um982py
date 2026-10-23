"""Tests the interference monitor example."""

from __future__ import annotations

from pathlib import Path

import pytest
from examples.interference_monitor import (
    AlertKind,
    AntennaReport,
    AntennaState,
    Cn0Sample,
    Severity,
    SpoofReport,
    antenna_report,
    detect_cn0_collapse,
    median_absolute_deviation,
    robust_z_score,
    spoof_report,
    status_alerts,
)

from um982py.experimental import FirmwareLog
from um982py.messages import Record
from um982py.messages.enums import PositionType
from um982py.protocol import StreamDecoder

FIXTURES = Path(__file__).parents[1] / "fixtures" / "captures"

HAND_REFERENCE = (40.0, 41.0, 39.0, 40.0, 42.0, 38.0, 41.0, 40.0)
HAND_REFERENCE_MEDIAN = 40.0
HAND_REFERENCE_MAD = 1.0
HAND_OUTLIER = 28.0
HAND_OUTLIER_Z = 0.6745 * (HAND_OUTLIER - HAND_REFERENCE_MEDIAN) / HAND_REFERENCE_MAD

CLEAN_MEAN_DB_HZ = 40.0
CLEAN_SIGMA_DB_HZ = 0.7
CLEAN_SATELLITES = range(1, 21)
CLEAN_EPOCHS = range(20)
DROPOUT_EPOCH = 12
DROPOUT_DB = 12.0
DROPOUT_SATELLITES = (3, 5, 7, 9, 11, 13)

JITTERED_SERIES = (39.0, 40.0, 41.0, 40.0, 39.0, 41.0, 40.0, 40.0, 39.0, 41.0)
WARNING_EPOCH = 4
CRITICAL_EPOCH = 6
SHALLOW_DROP_DB = 7.5
DEEP_DROP_DB = 11.5


def record(log: FirmwareLog, *, binary: bool) -> Record:
    path = FIXTURES / f"{log.wire_name(binary=binary)}.bin"
    messages = StreamDecoder().feed(path.read_bytes())
    return next(
        log.decode(message)
        for message in messages
        if log.request(binary=binary).matches(message)
    )


class SeededNoise:
    def __init__(self, seed: int) -> None:
        self._state = seed

    def uniform(self) -> float:
        self._state = (1_103_515_245 * self._state + 12_345) % 2**31
        return (self._state >> 8) / 2**23

    def gauss(self, sigma: float) -> float:
        draws = [self.uniform() for _ in range(4)]
        return sigma * (sum(draws) - 2.0) * 3**0.5


def noisy_series(noise: SeededNoise, *, dropped: bool) -> list[Cn0Sample]:
    samples = []
    for epoch in CLEAN_EPOCHS:
        for satellite in CLEAN_SATELLITES:
            cn0 = CLEAN_MEAN_DB_HZ + noise.gauss(CLEAN_SIGMA_DB_HZ)
            if dropped and epoch == DROPOUT_EPOCH and satellite in DROPOUT_SATELLITES:
                cn0 -= DROPOUT_DB
            samples.append(Cn0Sample(epoch=epoch, satellite=satellite, cn0=cn0))
    return samples


def jittered_series() -> list[Cn0Sample]:
    samples = [
        Cn0Sample(epoch=epoch, satellite=1, cn0=cn0)
        for epoch, cn0 in enumerate(JITTERED_SERIES)
    ]
    samples[WARNING_EPOCH] = Cn0Sample(
        epoch=WARNING_EPOCH, satellite=1, cn0=CLEAN_MEAN_DB_HZ - SHALLOW_DROP_DB
    )
    samples[CRITICAL_EPOCH] = Cn0Sample(
        epoch=CRITICAL_EPOCH, satellite=1, cn0=CLEAN_MEAN_DB_HZ - DEEP_DROP_DB
    )
    return samples


def test_clean_seeded_cn0_series_raises_no_alerts() -> None:
    samples = noisy_series(SeededNoise(1), dropped=False)
    assert detect_cn0_collapse(samples) == ()


def test_injected_dropout_is_flagged_at_exactly_its_epoch() -> None:
    samples = noisy_series(SeededNoise(1), dropped=True)
    alerts = detect_cn0_collapse(samples)
    assert [alert.epoch for alert in alerts] == [DROPOUT_EPOCH]
    assert alerts[0].satellites == DROPOUT_SATELLITES
    assert alerts[0].kind is AlertKind.CN0_COLLAPSE
    assert alerts[0].severity is Severity.CRITICAL
    assert alerts[0].z_score == pytest.approx(-DROPOUT_DB / CLEAN_SIGMA_DB_HZ, rel=0.2)


def test_robust_z_score_matches_hand_computation() -> None:
    assert median_absolute_deviation(HAND_REFERENCE) == pytest.approx(
        HAND_REFERENCE_MAD, abs=1e-12
    )
    assert pytest.approx(-8.094, abs=1e-12) == HAND_OUTLIER_Z
    assert robust_z_score(HAND_OUTLIER, HAND_REFERENCE) == pytest.approx(
        HAND_OUTLIER_Z, abs=1e-12
    )


def test_robust_z_score_uses_the_median_not_the_mean() -> None:
    reference = (1.0, 2.0, 3.0, 4.0, 100.0)
    assert median_absolute_deviation(reference) == pytest.approx(1.0, abs=1e-12)
    assert robust_z_score(100.0, reference) == pytest.approx(0.6745 * 97.0, abs=1e-9)


def test_severity_follows_the_robust_z_score() -> None:
    alerts = detect_cn0_collapse(jittered_series())
    assert [alert.epoch for alert in alerts] == [WARNING_EPOCH, CRITICAL_EPOCH]
    assert alerts[0].severity is Severity.WARNING
    assert -6.0 < alerts[0].z_score < -3.5
    assert alerts[1].severity is Severity.CRITICAL
    assert alerts[1].z_score <= -6.0


def test_series_shorter_than_five_samples_is_not_tested() -> None:
    samples = [
        Cn0Sample(epoch=epoch, satellite=1, cn0=CLEAN_MEAN_DB_HZ) for epoch in range(3)
    ]
    samples.append(Cn0Sample(epoch=3, satellite=1, cn0=5.0))
    assert detect_cn0_collapse(samples) == ()


def test_spoofinfo_fixture_reports_no_spoofing_indicator() -> None:
    binary = spoof_report(record(FirmwareLog.SPOOFINFO, binary=True))
    ascii_record = record(FirmwareLog.SPOOFINFO, binary=False)
    assert binary.spoof_indicator == 0
    assert binary.is_suspect is False
    assert binary.position_type == PositionType.SINGLE
    assert binary.position_type_label == "SINGLE"
    assert ascii_record["position_type"] == binary.position_type_label


def test_antenna_fixture_reports_both_antennas_working() -> None:
    binary = antenna_report(record(FirmwareLog.ANTENNA, binary=True))
    ascii_record = record(FirmwareLog.ANTENNA, binary=False)
    assert (binary.state_1, binary.state_2) == (AntennaState.WORK, AntennaState.WORK)
    assert binary.state_3 is AntennaState.RESERVED
    assert binary.is_degraded is False
    assert ascii_record["status_1"] == AntennaState.WORK
    assert ascii_record["status_3"] == AntennaState.RESERVED


def test_ascii_labels_decode_like_the_binary_codes() -> None:
    for log in (FirmwareLog.SPOOFINFO, FirmwareLog.ANTENNA):
        decoder = spoof_report if log is FirmwareLog.SPOOFINFO else antenna_report
        assert decoder(record(log, binary=False)) == decoder(record(log, binary=True))


def test_unknown_antenna_status_is_reported_as_degraded() -> None:
    report = AntennaReport(status_1=9, status_2=5, status_3=0)
    assert report.state_1 is AntennaState.UNKNOWN
    assert report.is_degraded is True
    alerts = status_alerts(7, None, report)
    assert len(alerts) == 1
    assert alerts[0].kind is AlertKind.ANTENNA
    assert alerts[0].severity is Severity.WARNING
    assert alerts[0].epoch == 7


def test_spoofing_indicator_raises_a_critical_alert() -> None:
    report = SpoofReport(position_type=PositionType.SINGLE, spoof_indicator=3)
    alerts = status_alerts(0, report, None)
    assert len(alerts) == 1
    assert alerts[0].kind is AlertKind.SPOOFING
    assert alerts[0].severity is Severity.CRITICAL


def test_healthy_status_words_raise_no_alert() -> None:
    spoof = SpoofReport(position_type=PositionType.SINGLE, spoof_indicator=0)
    antenna = AntennaReport(status_1=5, status_2=5, status_3=0)
    assert status_alerts(0, spoof, antenna) == ()
