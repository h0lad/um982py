"""Record and inspect a bounded set of raw receiver observations."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal
from uuid import uuid4

from um982py.antenna import antenna_log
from um982py.capture import InterruptedCapture, capture_live
from um982py.commands import Log
from um982py.measurement import RangeSample, SignalKey, sample_series
from um982py.messages import Record
from um982py.observation_quality import ObservationQuality, audit_observations
from um982py.provenance import ObservationSource, _observation_source
from um982py.receiver import Receiver
from um982py.rinex import RinexExport, RinexMetadata, export_rinex


@dataclass(frozen=True, slots=True)
class Observations:
    """Receiver records kept in memory, with quality and RINEX helpers.

    Preserve the original wire capture separately for reproducibility. Quality
    checks use receiver-reported flags and do not establish measurement accuracy.
    Source tags survive slicing and concatenation of ``records``. For replay,
    supply ``source`` from acquisition metadata, because untagged wire bytes
    cannot identify a physical receiver or session.
    """

    records: tuple[Record, ...]
    source: ObservationSource | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        source = _observation_source(self.records, self.source)
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self,
            "records",
            tuple(
                replace(record, source=source)
                if record.source is None and source
                else record
                for record in self.records
            ),
        )

    def quality(self, *, expected_interval: float | None = None) -> ObservationQuality:
        """Audit gaps, receiver lock resets and measurement flags."""
        return audit_observations(self.records, expected_interval=expected_interval)

    def signals(
        self,
        *,
        systems: tuple[int, ...] | None = None,
        signals: tuple[int, ...] | None = None,
        glonass_channels: Mapping[int, int] | None = None,
    ) -> dict[SignalKey, tuple[RangeSample, ...]]:
        """Group valid uncompressed code and phase measurements by signal.

        Samples use increasing-range metres and GPS seconds. The receiver's
        system and signal codes select subsets. Unknown frequencies or invalid
        code/phase measurements are omitted, and compressed logs are unsupported.
        """
        return sample_series(
            self.records,
            systems=systems,
            signals=signals,
            glonass_channels=glonass_channels,
        )

    def to_rinex(
        self,
        *,
        marker_name: str = "UM982",
        l2c_code: str | None = None,
        week_scale: Literal["GPST", "BDT"] | None = None,
        metadata: RinexMetadata | None = None,
        created_at: datetime | None = None,
    ) -> RinexExport:
        """Export observations with a fix-aware ``created_at`` for
        reproducible text."""
        return export_rinex(
            self.records,
            marker_name=marker_name,
            l2c_code=l2c_code,
            week_scale=week_scale,
            metadata=metadata,
            created_at=created_at,
        )


def record_observations(
    receiver: Receiver,
    *,
    duration: float,
    interval: float | None = None,
    rate_hz: float | None = None,
    antenna: int = 1,
    log: Log = Log.RANGE,
    frames: int | None = None,
    receiver_id: str | None = None,
) -> Observations:
    """Capture a single observation log and restore previous subscriptions.

    Select RANGE, OBSVM or OBSVMCMP, where antenna 2 selects the matching
    secondary log. Records are held in memory. InterruptedCapture retains
    partial records under the selected logical log name. For long captures
    use SessionRecorder.
    Actual cadence is receiver-dependent and must be checked in the records.

    Each capture gets a new source session ID, including interrupted captures.
    ``receiver_id`` is an optional known serial number or application label,
    and no identity query is issued. Separate captures are separate carrier arcs.
    """
    if not isinstance(log, Log) or log not in (Log.RANGE, Log.OBSVM, Log.OBSVMCMP):
        raise ValueError("log must be RANGE, OBSVM or OBSVMCMP")
    selected = antenna_log(log, antenna)
    source = ObservationSource(receiver_id, uuid4().hex, antenna)
    try:
        records = capture_live(
            receiver,
            selected,
            duration=duration,
            interval=interval,
            rate_hz=rate_hz,
            frames=frames,
        )
    except InterruptedCapture as error:
        error.records[log.value] = Observations(
            error.records[log.value], source=source
        ).records
        raise
    return Observations(records[log.value], source=source)
