"""Estimates user range error from position sigma and DOP."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.geodesy import records_from
from um982py.messages.record import Record
from um982py.stats import percentile


@dataclass(frozen=True, slots=True)
class UereEstimate:
    """UERE implied by one epoch of position sigma and dilution of precision."""

    epoch: float
    horizontal_sigma: float
    """Combined horizontal position sigma in metres."""
    vertical_sigma: float
    """Vertical position sigma in metres."""
    hdop: float
    vdop: float

    @property
    def horizontal_uere(self) -> float:
        """Range error in metres implied by the horizontal position sigma."""
        return self.horizontal_sigma / self.hdop

    @property
    def vertical_uere(self) -> float:
        """Range error in metres implied by the vertical position sigma."""
        return self.vertical_sigma / self.vdop


def horizontal_sigma(lat_std: float, lon_std: float) -> float:
    """Combined horizontal position sigma in metres from two axis sigmas."""
    return math.hypot(lat_std, lon_std)


def vertical_dilution(pdop: float, hdop: float) -> float:
    """Vertical dilution of precision from PDOP and HDOP."""
    if pdop <= 0 or hdop <= 0:
        raise ValueError("dilution of precision values must be positive")
    if pdop <= hdop:
        raise ValueError("PDOP must be greater than HDOP to resolve vertical UERE")
    return math.sqrt(pdop * pdop - hdop * hdop)


def estimate_epoch(epoch: float, position: Record, dilution: Record) -> UereEstimate:
    """Invert sigma_position = DOP * sigma_UERE for one epoch."""
    hdop = dilution.real("hdop")
    return UereEstimate(
        epoch=epoch,
        horizontal_sigma=horizontal_sigma(
            position.real("lat_std"), position.real("lon_std")
        ),
        vertical_sigma=position.real("hgt_std"),
        hdop=hdop,
        vdop=vertical_dilution(dilution.real("pdop"), hdop),
    )


def epoch_estimates(
    positions: Sequence[Record], dilutions: Sequence[Record]
) -> tuple[UereEstimate, ...]:
    """One estimate per BESTPOS record, paired with the DOP record of its epoch."""
    if len(positions) != len(dilutions):
        raise ValueError("BESTPOS and DOP series must hold the same number of epochs")
    return tuple(
        estimate_epoch(epoch, position, dilution)
        for epoch, (position, dilution) in enumerate(
            zip(positions, dilutions, strict=True)
        )
    )


def pseudorange_uere(record: Record) -> float:
    """Median reported pseudorange sigma of one RANGE epoch, in metres."""
    deviations = [
        observation.real("pseudorange_std")
        for observation in records_from(record, "observations")
    ]
    if not deviations:
        raise ValueError("RANGE record carries no observations")
    return percentile(deviations, 0.5)


def median_uere(estimates: Sequence[UereEstimate]) -> tuple[float, float]:
    """Median horizontal and vertical UERE in metres across epochs."""
    if not estimates:
        raise ValueError("at least one epoch is required")
    return (
        percentile([estimate.horizontal_uere for estimate in estimates], 0.5),
        percentile([estimate.vertical_uere for estimate in estimates], 0.5),
    )


def agreement_ratio(estimated: float, reference: float) -> float:
    """Ratio of two independent UERE estimates."""
    if reference <= 0:
        raise ValueError("reference UERE must be positive")
    if estimated <= 0:
        raise ValueError("estimated UERE must be positive")
    return estimated / reference
