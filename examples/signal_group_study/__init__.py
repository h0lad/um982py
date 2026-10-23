"""Compares satellites, C/N0, DOP and fix class across SIGNALGROUP settings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from examples.dop_geometry import (
    DilutionOfPrecision,
    ReportedDilution,
    SatelliteGeometry,
)
from examples.rtk_quality import FixClass, classify
from um982py.commands.configuration import SignalGroup
from um982py.experimental import LogList
from um982py.messages.record import Record
from um982py.stats import mean

DOP_TOLERANCE = 0.05


class DopAgreement(StrEnum):
    """Relation between the recomputed DOP and the receiver's own PSRDOP."""

    MATCH = "match"
    LOWER_BOUND = "lower_bound"
    VIOLATED = "violated"


@dataclass(frozen=True, slots=True)
class SettingSample:
    """One measurement epoch gathered at a single signal-group setting."""

    setting: SignalGroup
    geometry: tuple[SatelliteGeometry, ...]
    reported: ReportedDilution
    cn0: tuple[float, ...]
    position_type: int


@dataclass(frozen=True, slots=True)
class SettingSummary:
    """Satellites, mean C/N0, DOP and fix class of one signal-group setting."""

    setting: SignalGroup
    satellites: int
    signals: int
    mean_cn0: float
    dilutions: DilutionOfPrecision
    reported_pdop: float
    pdop_excess: float
    """Recomputed position DOP minus the value the receiver reports."""
    agreement: DopAgreement
    fix_class: FixClass


@dataclass(frozen=True, slots=True)
class SettingState:
    """Signal group plus configuration, mode, masks and logs of a receiver."""

    setting: SignalGroup
    configuration: tuple[bytes, ...]
    mode: tuple[str, ...]
    masks: tuple[tuple[str, ...], ...]
    logs: LogList

    @classmethod
    def from_parts(
        cls, setting: SignalGroup, parts: tuple[object, ...]
    ) -> SettingState:
        """Build a state from a signal group and the four ``receiver_state`` parts."""
        configuration, mode, masks, logs = parts
        if not isinstance(logs, LogList):
            raise ValueError("the fourth state part is not a log list")
        return cls(
            setting=setting,
            configuration=cast("tuple[bytes, ...]", configuration),
            mode=cast("tuple[str, ...]", mode),
            masks=cast("tuple[tuple[str, ...], ...]", masks),
            logs=logs,
        )

    def difference(self, other: SettingState) -> tuple[str, ...]:
        """Names of the parts that differ from another state."""
        return tuple(
            name
            for name, left, right in (
                ("setting", self.setting, other.setting),
                ("configuration", self.configuration, other.configuration),
                ("mode", self.mode, other.mode),
                ("masks", self.masks, other.masks),
                ("logs", self.logs, other.logs),
            )
            if left != right
        )


def first_visibility_epoch(records: Sequence[Record]) -> tuple[Record, ...]:
    """Visibility frames of the earliest epoch, one frame per constellation."""
    seen = set()
    epoch = []
    for record in records:
        constellation = str(record["constellation"])
        if constellation in seen:
            break
        seen.add(constellation)
        epoch.append(record)
    return tuple(epoch)


def agreement(
    recomputed: float, reported: float, *, tolerance: float = DOP_TOLERANCE
) -> DopAgreement:
    """Classify a recomputed DOP against the value the receiver reports."""
    if not tolerance > 0:
        raise ValueError("tolerance must be positive")
    if recomputed > reported * (1.0 + tolerance):
        return DopAgreement.VIOLATED
    if abs(recomputed - reported) <= reported * tolerance:
        return DopAgreement.MATCH
    return DopAgreement.LOWER_BOUND


def summarise(sample: SettingSample) -> SettingSummary:
    """Reduce one setting's sample to a trade-study row."""
    if len(sample.geometry) < 4:
        raise ValueError(
            "signal-group comparison needs at least four visible satellites"
        )
    dilutions = DilutionOfPrecision.from_geometry(sample.geometry)
    return SettingSummary(
        setting=sample.setting,
        satellites=len(sample.geometry),
        signals=len(sample.cn0),
        mean_cn0=mean(sample.cn0),
        dilutions=dilutions,
        reported_pdop=sample.reported.pdop,
        pdop_excess=dilutions.pdop - sample.reported.pdop,
        agreement=agreement(dilutions.pdop, sample.reported.pdop),
        fix_class=classify(sample.position_type),
    )


def trade_study(samples: Sequence[SettingSample]) -> tuple[SettingSummary, ...]:
    """One summary per setting, in the order the settings were sampled."""
    if len({sample.setting for sample in samples}) != len(samples):
        raise ValueError("a signal-group setting appears twice")
    return tuple(summarise(sample) for sample in samples)
