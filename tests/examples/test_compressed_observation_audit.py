from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from examples.compressed_observation_audit import __main__ as cli
from examples.compressed_observation_audit import (
    agree_epoch,
    summarise_epochs,
)

from test_protocol import binary
from um982py.experimental import CompressedObservation
from um982py.messages import BinaryMessage, Record
from um982py.messages.frames import BinaryHeader
from um982py.protocol.binary import parse_binary


def observation(
    status: int,
    pseudorange: float,
    doppler: float,
    phase: float,
    *,
    prn: int = 7,
) -> Record:
    """Build one synthetic RANGE observation record."""
    return Record(
        "observation",
        (
            ("prn", prn),
            ("tracking_status", status),
            ("pseudorange", pseudorange),
            ("doppler", doppler),
            ("carrier_phase", phase),
        ),
    )


def compressed(
    status: int,
    pseudorange: float,
    doppler: float,
    phase: float | None,
    saturated: bool = False,
    *,
    prn: int = 7,
) -> CompressedObservation:
    """Build one synthetic compressed observation."""
    return CompressedObservation(
        tracking_status=status,
        prn=prn,
        doppler_hz=doppler,
        pseudorange_m=pseudorange,
        carrier_phase_cycles=phase,
        pseudorange_std_m=0.380,
        carrier_phase_std_cycles=0.004,
        lock_time_s=120.0,
        cn0_db_hz=20 if saturated else 35,
        cn0_saturated=saturated,
        glonass_channel=0,
        divergence_cycles=1.5 if phase is not None else None,
    )


def test_shared_status_scores_residuals() -> None:
    reference = observation(0x43, 20234567.125, -1234.5, -98765432.0)
    compressed_observation = compressed(0x43, 20234567.1, -1234.4, -98765431.9)
    agreement = agree_epoch(
        (reference,),
        (compressed_observation,),
        range_bytes=1000,
        compressed_bytes=600,
    )
    assert agreement.matched == 1
    assert agreement.unmatched == 0
    assert agreement.worst_pseudorange_m == pytest.approx(0.025)
    assert agreement.worst_doppler_hz == pytest.approx(0.1)
    assert agreement.worst_phase_cycles == pytest.approx(0.1)
    assert agreement.saturated_cn0 == 0
    assert (agreement.range_bytes, agreement.compressed_bytes) == (1000, 600)


def test_unknown_status_counts_as_unmatched() -> None:
    agreement = agree_epoch(
        (observation(0x43, 20234567.0, 0.0, 0.0),),
        (compressed(0x44, 20234567.0, 0.0, 0.0),),
        range_bytes=100,
        compressed_bytes=60,
    )
    assert (agreement.matched, agreement.unmatched) == (0, 1)
    assert agreement.worst_phase_cycles is None


def test_missing_phase_skips_the_phase_residual() -> None:
    reference = observation(0x43, 20234567.0, 0.0, -100.0)
    agreement = agree_epoch(
        (reference,),
        (compressed(0x43, 20234567.0, 0.0, None),),
        range_bytes=100,
        compressed_bytes=60,
    )
    assert agreement.matched == 1
    assert agreement.worst_phase_cycles is None


def test_saturated_cn0_counts_separately() -> None:
    reference = observation(0x43, 20234567.0, 0.0, 0.0)
    observations = (
        compressed(0x43, 20234567.0, 0.0, 0.0),
        compressed(0x43, 20234567.0, 0.0, 0.0, saturated=True),
    )
    agreement = agree_epoch(
        (reference,), observations, range_bytes=100, compressed_bytes=60
    )
    assert agreement.saturated_cn0 == 1


def test_summary_combines_epochs_with_wire_ratio() -> None:
    first = agree_epoch(
        (observation(0x43, 20234567.0, 0.0, 0.0),),
        (compressed(0x43, 20234567.05, 0.02, 0.03),),
        range_bytes=1000,
        compressed_bytes=600,
    )
    second = agree_epoch(
        (observation(0x44, 20234568.0, 1.0, 1.0),),
        (compressed(0x44, 20234568.5, 1.5, None),),
        range_bytes=1000,
        compressed_bytes=600,
    )
    summary = summarise_epochs((first, second))
    assert summary.epochs == 2
    assert summary.matched == 2
    assert summary.worst_pseudorange_m == pytest.approx(0.5)
    assert summary.worst_doppler_hz == pytest.approx(0.5)
    assert summary.worst_phase_cycles == pytest.approx(0.03)
    assert (summary.range_bytes, summary.compressed_bytes) == (2000, 1200)
    assert summary.ratio == pytest.approx(0.6)


def test_empty_summary_has_zero_ratio() -> None:
    summary = summarise_epochs(())
    assert summary.epochs == 0
    assert summary.matched == 0
    assert summary.worst_phase_cycles is None
    assert summary.ratio == pytest.approx(0.0)


def test_same_status_from_different_satellites_keeps_both_observations() -> None:
    agreement = agree_epoch(
        (
            observation(0x43, 20234567.0, 0.0, 0.0),
            observation(0x43, 21234567.0, 0.0, 0.0, prn=9),
        ),
        (
            compressed(0x43, 21234567.0, 0.0, 0.0, prn=9),
            compressed(0x43, 20234567.0, 0.0, 0.0),
        ),
        range_bytes=100,
        compressed_bytes=60,
    )
    assert agreement.matched == 2
    assert agreement.worst_pseudorange_m == 0


@pytest.mark.parametrize(
    "antenna,range_id,compressed_id", [(1, 43, 140), (2, 6005, 2111)]
)
def test_replay_pairs_shared_receiver_epochs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    antenna: int,
    range_id: int,
    compressed_id: int,
) -> None:
    def frame(message_id: int, milliseconds: int) -> BinaryMessage:
        message = parse_binary(binary(bytes(4), message_id=message_id))
        assert isinstance(message.header, BinaryHeader)
        return replace(
            message, header=replace(message.header, milliseconds=milliseconds)
        )

    frames = (
        frame(range_id, 1000),
        frame(compressed_id, 2000),
        frame(range_id, 2000),
        frame(compressed_id, 3000),
    )
    monkeypatch.setattr(cli, "iter_frames", lambda _: iter(frames))
    report = tmp_path / "report.json"
    assert (
        cli.main(
            [
                "--replay",
                str(tmp_path / "capture.bin"),
                "--antenna",
                str(antenna),
                "--json",
                str(report),
            ]
        )
        == 0
    )
    result = json.loads(report.read_text())
    assert result["antenna"] == antenna
    assert result["summary"]["epochs"] == 1
    assert result["unpaired_range_epochs"] == result["unpaired_compressed_epochs"] == 1
