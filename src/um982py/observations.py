"""Record and inspect a bounded set of raw receiver observations."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from um982py.antenna import antenna_log
from um982py.capture import capture_live
from um982py.commands import Log
from um982py.measurement import RangeSample, SignalKey, sample_series
from um982py.messages import Record
from um982py.observation_quality import ObservationQuality, audit_observations
from um982py.receiver import Receiver
from um982py.rinex import RinexExport, RinexMetadata, export_rinex


@dataclass(frozen=True, slots=True)
class Observations:
    """Receiver records kept in memory, with quality and RINEX helpers.

    Preserve the original wire capture separately for reproducibility. Quality
    checks use receiver-reported flags and do not establish measurement accuracy.
    """

    records: tuple[Record, ...]

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
    ) -> RinexExport:
        """Export observations and return the RINEX text and omission counts."""
        return export_rinex(
            self.records,
            marker_name=marker_name,
            l2c_code=l2c_code,
            week_scale=week_scale,
            metadata=metadata,
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
) -> Observations:
    """Capture a single observation log and restore previous subscriptions.

    Select RANGE, OBSVM or OBSVMCMP; antenna 2 selects the matching secondary
    log. Records are held in memory. InterruptedCapture retains partial records
    under the selected logical log name. For long captures use SessionRecorder.
    Actual cadence is receiver-dependent and must be checked in the records.
    """
    if not isinstance(log, Log) or log not in (Log.RANGE, Log.OBSVM, Log.OBSVMCMP):
        raise ValueError("log must be RANGE, OBSVM or OBSVMCMP")
    selected = antenna_log(log, antenna)
    records = capture_live(
        receiver,
        selected,
        duration=duration,
        interval=interval,
        rate_hz=rate_hz,
        frames=frames,
    )
    return Observations(records[log.value])
