"""Compare encoded GPS L1 code with a candidate fold recovered from L2 phase."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from math import isfinite

from um982py.capture import gps_signals
from um982py.experimental import CompressedRange2
from um982py.experimental.range_compressed2 import (
    GPS_L1_CODE_STEP_M as _STEP_M,
)
from um982py.experimental.range_compressed2 import (
    GPS_L1_CODE_WINDOW_M as _WINDOW_M,
)
from um982py.geodesy import SPEED_OF_LIGHT
from um982py.messages import Record

_L1_TO_L2_FREQUENCY_RATIO = 154 / 120
_L2_WAVELENGTH_M = SPEED_OF_LIGHT / 1227.60e6


@dataclass(frozen=True, slots=True)
class Comparison:
    prn: int
    encoded_error_m: float
    wrap_count: int | None
    l1_phase_at_ceiling: bool
    l2_anchored_error_m: float | None
    l2_phase_distance_error_m: float | None


def compare_gps_l1(reference: Record, compressed: CompressedRange2) -> list[Comparison]:
    """Test an L2 phase anchor against a simultaneous full GPS L1 observation."""
    by_prn = {
        row.integer("prn"): row.real("pseudorange")
        for row, _ in gps_signals(reference, (1575.42e6,), phase=False)
    }
    l2_reference = {
        row.integer("prn"): -row.real("carrier_phase") * _L2_WAVELENGTH_M
        for row, _ in gps_signals(reference, (1227.60e6,))
    }
    rows = []
    for satellite in compressed.satellites:
        pseudorange = by_prn.get(satellite.prn)
        if (
            satellite.system != 0
            or pseudorange is None
            or not isfinite(pseudorange)
            or pseudorange <= 0
        ):
            continue
        signals = {signal.signal_type: signal for signal in satellite.signals}
        l1 = signals.get(1)
        if l1 is None or not l1.code_locked:
            continue
        encoded_code = satellite.range_base_m + l1.pseudorange_offset_m
        error = encoded_code - pseudorange
        resolved = satellite.resolve_gps_l1_code(
            reference_m=pseudorange, max_reference_error_m=0.0
        )
        l2 = signals.get(4)
        anchored_error = None
        phase_error = None
        if (
            l1.phase_at_ceiling
            and l2 is not None
            and l2.phase_locked
            and not l2.phase_at_ceiling
        ):
            l2_phase_m = (
                satellite.range_base_m + l2.phase_offset_m
            ) * _L1_TO_L2_FREQUENCY_RATIO
            fold = round((l2_phase_m - encoded_code) / _WINDOW_M)
            anchored_error = error + fold * _WINDOW_M
            full_phase = l2_reference.get(satellite.prn)
            if full_phase is not None and isfinite(full_phase):
                phase_error = l2_phase_m - full_phase
        rows.append(
            Comparison(
                satellite.prn,
                error,
                round((encoded_code - resolved) / _WINDOW_M)
                if resolved is not None
                else None,
                l1.phase_at_ceiling,
                anchored_error,
                phase_error,
            )
        )
    return rows


def report_gps_l1(
    pairs: Sequence[tuple[float, Record, CompressedRange2, int]],
) -> dict[str, object]:
    """Report wire size and distinguish wraps from other discrepancies."""
    epochs = []
    comparisons = []
    for epoch, reference, compressed, reference_bytes in pairs:
        rows = compare_gps_l1(reference, compressed)
        comparisons.extend(rows)
        epochs.append(
            {
                "gps_epoch_s": epoch,
                "range_bytes": reference_bytes,
                "compressed_bytes": len(compressed.message.raw),
                "gps_l1": [asdict(row) for row in rows],
            }
        )
    range_bytes = sum(size for _, _, _, size in pairs)
    compressed_bytes = sum(len(frame.message.raw) for _, _, frame, _ in pairs)
    anchored = [
        abs(row.l2_anchored_error_m)
        for row in comparisons
        if row.l2_anchored_error_m is not None
    ]
    wraps = [row for row in comparisons if row.wrap_count not in (None, 0)]
    phase_errors = [
        abs(row.l2_phase_distance_error_m)
        for row in comparisons
        if row.l2_phase_distance_error_m is not None
    ]
    return {
        "epochs": epochs,
        "summary": {
            "matched_gps_l1": len(comparisons),
            "pseudorange_wraps": len(wraps),
            "non_modulo_mismatches": sum(row.wrap_count is None for row in comparisons),
            "wraps_with_l1_phase_at_ceiling": sum(
                row.l1_phase_at_ceiling for row in wraps
            ),
            "l2_anchor_candidates": len(anchored),
            "l2_anchor_agrees": sum(error <= _STEP_M for error in anchored),
            "l2_anchor_wrong_fold": sum(error >= _WINDOW_M / 2 for error in anchored),
            "worst_l2_anchor_error_m": max(anchored, default=None),
            "l2_phase_comparisons": len(phase_errors),
            "worst_l2_phase_distance_error_m": max(phase_errors, default=None),
            "worst_encoded_error_m": max(
                (abs(row.encoded_error_m) for row in comparisons), default=None
            ),
            "range_bytes": range_bytes,
            "compressed_bytes": compressed_bytes,
            "ratio": compressed_bytes / range_bytes if range_bytes else 0.0,
        },
    }
