"""Solution quality timelines from receiver status fields and ages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from um982py.capture import record_epoch
from um982py.corrections import stale_correction
from um982py.messages import Value

if TYPE_CHECKING:
    from um982py.messages import Record
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.stats import mean


class FixClass(StrEnum):
    """Solution categories used by the quality timeline."""

    FIXED = "fixed"
    FLOAT = "float"
    PPP = "ppp"
    PPP_CONVERGING = "ppp_converging"
    SINGLE = "single"
    NONE = "none"


POSITION_CLASSES: Mapping[PositionType, FixClass] = MappingProxyType(
    {
        PositionType.NONE: FixClass.NONE,
        PositionType.FIXEDPOS: FixClass.SINGLE,
        PositionType.FIXEDHEIGHT: FixClass.SINGLE,
        PositionType.SINGLE: FixClass.SINGLE,
        PositionType.PSRDIFF: FixClass.SINGLE,
        PositionType.SBAS: FixClass.SINGLE,
        PositionType.L1_FLOAT: FixClass.FLOAT,
        PositionType.IONOFREE_FLOAT: FixClass.FLOAT,
        PositionType.NARROW_FLOAT: FixClass.FLOAT,
        PositionType.L1_INT: FixClass.FIXED,
        PositionType.WIDE_INT: FixClass.FIXED,
        PositionType.NARROW_INT: FixClass.FIXED,
        PositionType.INS_PSRSP: FixClass.SINGLE,
        PositionType.INS_PSRDIFF: FixClass.SINGLE,
        PositionType.INS_RTKFLOAT: FixClass.FLOAT,
        PositionType.INS_RTKFIXED: FixClass.FIXED,
        PositionType.PPP_CONVERGING: FixClass.PPP_CONVERGING,
        PositionType.PPP: FixClass.PPP,
        PositionType.PPP_AR: FixClass.PPP,
        PositionType.PPP_RTK: FixClass.PPP,
    }
)


@dataclass(frozen=True, slots=True)
class EpochSolution:
    """One solution epoch reported by a position log."""

    epoch: float
    """Absolute GPS seconds, or sample index for unstamped synthetic records."""
    position_type: int
    """Position type code of the Unicore manual position type table."""
    solution_status: int
    """Solution status code of the Unicore manual solution status table."""
    differential_age: float
    """Age of the differential corrections in seconds."""
    solution_age: float
    """Age of the computed solution in seconds."""
    satellites_used: int
    """Satellites contributing to the solution."""

    @property
    def fix_class(self) -> FixClass:
        """Return the solution category for the reported position type."""
        return classify(self.position_type)

    @property
    def position_label(self) -> str:
        """Documented name of the reported position type."""
        return position_label(self.position_type)

    @property
    def solution_label(self) -> str:
        """Documented name of the reported solution status."""
        return solution_label(self.solution_status)

    @property
    def is_available(self) -> bool:
        """True when the epoch carries a computed position solution."""
        return (
            self.solution_status == SolutionStatus.SOL_COMPUTED
            and self.fix_class is not FixClass.NONE
        )

    @property
    def fresh_fixed(self) -> bool:
        return (
            self.is_available
            and self.fix_class is FixClass.FIXED
            and not stale_correction(self.position_type, self.differential_age)
        )


@dataclass(frozen=True, slots=True)
class QualitySummary:
    """Availability and fix statistics of a solution timeline."""

    epochs: int
    availability: float
    """Fraction of epochs carrying a computed solution, 0..1."""
    time_to_first_fix: float | None
    """Seconds to the first RTK fix, or sample units for synthetic data."""
    fresh_fixed_epochs: int
    class_counts: Mapping[FixClass, int]
    """Number of epochs in each solution category."""
    mean_differential_age: float
    """Mean differential age in seconds."""
    maximum_solution_age: float
    """Largest solution age in seconds."""


def classify(position_type: int) -> FixClass:
    """Classify a documented position type code."""
    try:
        documented = PositionType(position_type)
    except ValueError:
        raise ValueError(f"unknown position type {position_type}") from None
    try:
        return POSITION_CLASSES[documented]
    except KeyError:
        raise ValueError(f"no fix class for {documented.name}") from None


def position_label(position_type: int) -> str:
    """Documented name of a position type code."""
    return PositionType(position_type).name


def solution_label(solution_status: int) -> str:
    """Documented name of a solution status code."""
    return SolutionStatus(solution_status).name


def position_type_code(record: Record) -> int:
    """Numeric position type of a record, accepting the ASCII label."""
    return _code(record["pos_type"], PositionType, "pos_type")


def solution_status_code(record: Record) -> int:
    """Numeric solution status of a record, accepting the ASCII label."""
    return _code(record["p_sol_status"], SolutionStatus, "p_sol_status")


def _code(value: Value, enum: type[IntEnum], field: str) -> int:
    """Reduce a binary code or an ASCII label to the numeric code."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return enum[value].value
        except KeyError:
            raise ValueError(f"unknown {field} label {value}") from None
    raise ValueError(f"{field} is neither a code nor a label")


def solution_from_record(epoch: float, record: Record) -> EpochSolution:
    """Build one epoch from a BESTPOS, RTKPOS or BESTXYZ record."""
    return EpochSolution(
        epoch=epoch,
        position_type=position_type_code(record),
        solution_status=solution_status_code(record),
        differential_age=record.real("diff_age"),
        solution_age=record.real("sol_age"),
        satellites_used=record.integer("count_svs"),
    )


def timeline(records: Sequence[Record]) -> tuple[EpochSolution, ...]:
    """Number a capture of position records in arrival order."""
    return tuple(
        solution_from_record(
            record_epoch(record) if record.message is not None else float(epoch), record
        )
        for epoch, record in enumerate(records)
    )


def summarise(solutions: Sequence[EpochSolution]) -> QualitySummary:
    """Summarise availability, time to first fix and per-class counts."""
    if not solutions:
        raise ValueError("at least one solution epoch is required")
    counts = dict.fromkeys(FixClass, 0)
    for solution in solutions:
        counts[solution.fix_class] += 1
    first_fixed = next(
        (solution.epoch for solution in solutions if solution.fresh_fixed),
        None,
    )
    return QualitySummary(
        epochs=len(solutions),
        availability=sum(solution.is_available for solution in solutions)
        / len(solutions),
        time_to_first_fix=(
            None if first_fixed is None else first_fixed - solutions[0].epoch
        ),
        fresh_fixed_epochs=sum(solution.fresh_fixed for solution in solutions),
        class_counts=MappingProxyType(counts),
        mean_differential_age=mean(
            [solution.differential_age for solution in solutions]
        ),
        maximum_solution_age=max(solution.solution_age for solution in solutions),
    )
