"""Select and report receiver positions from decoded log records."""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

from examples.position_tracking.quality import dop_report, satellite_report
from examples.position_tracking.track import Geofence, Track, TrackPoint
from um982py.corrections import stale_correction
from um982py.messages.record import Record


@dataclass(frozen=True, slots=True)
class PositionAnalysis:
    track: Track
    status: str
    report: dict[str, object]
    exit_code: int


def collect_positions(
    records: Sequence[Record], *, ppp: bool = False, status_field: str | None = None
) -> tuple[Track, Counter[str]]:
    """Keep valid, ordered navigation fixes and count rejected records."""
    points: list[TrackPoint] = []
    rejected: Counter[str] = Counter()
    for record in records:
        status = record.get(status_field or ("sol_status" if ppp else "p_sol_status"))
        if status not in (0, "SOL_COMPUTED"):
            rejected["solution_not_computed"] += 1
            continue
        position = TrackPoint.from_record(record)
        if position.position_type == "NONE":
            rejected["no_position_type"] += 1
            continue
        if ppp and position.position_type not in (
            "PPP",
            "PPP_CONVERGING",
            "PPP_AR",
            "PPP_RTK",
        ):
            rejected["not_ppp"] += 1
            continue
        if not (
            math.isfinite(position.timestamp)
            and math.isfinite(position.latitude)
            and math.isfinite(position.longitude)
            and math.isfinite(position.altitude)
            and -90 <= position.latitude <= 90
            and -180 <= position.longitude <= 180
        ):
            rejected["invalid_coordinates"] += 1
            continue
        if points and position.timestamp <= points[-1].timestamp:
            rejected["non_increasing_epoch"] += 1
            continue
        points.append(position)
    return Track(tuple(points)), rejected


def _near(times: list[float], epoch: float, tolerance: float) -> bool:
    index = bisect_left(times, epoch)
    return any(
        abs(times[candidate] - epoch) <= tolerance
        for candidate in (index - 1, index)
        if 0 <= candidate < len(times)
    )


def select_track(
    best: Track, ppp: Track, *, interval_s: float = 1.0
) -> tuple[Track, float | None]:
    """Prefer full PPP fixes at matching epochs, with BESTNAV in PPP gaps."""
    if not math.isfinite(interval_s) or interval_s <= 0:
        raise ValueError("interval_s must be finite and positive")
    if any(
        later.timestamp <= earlier.timestamp
        for track in (best, ppp)
        for earlier, later in pairwise(track.points)
    ):
        raise ValueError("each source track needs increasing epochs")
    first_ppp = next(
        (point.timestamp for point in ppp.points if point.position_type == "PPP"),
        None,
    )
    tolerance = min(0.5, interval_s / 2)
    best_times = [point.timestamp for point in best.points]
    full_ppp_times = [
        point.timestamp for point in ppp.points if point.position_type == "PPP"
    ]
    points = [
        point
        for point in best.points
        if not _near(full_ppp_times, point.timestamp, tolerance)
    ]
    points.extend(
        point
        for point in ppp.points
        if point.position_type == "PPP"
        or not _near(best_times, point.timestamp, tolerance)
    )
    points.sort(key=lambda point: point.timestamp)
    return Track(tuple(points)), first_ppp


def analyze_capture(
    captured: Mapping[str, Sequence[Record]],
    *,
    interval_s: float = 1.0,
    precision_service: str | None = None,
    fence: Geofence | None = None,
) -> PositionAnalysis:
    """Build the same track and report from live capture or replayed records."""
    best, best_rejected = collect_positions(captured.get("BESTNAV", ()))
    ppp, ppp_rejected = collect_positions(captured.get("PPPNAV", ()), ppp=True)
    track, first_ppp = select_track(best, ppp, interval_s=interval_s)
    latest = track.points[-1] if track.points else None
    if latest is None:
        status = "no_fix"
    elif stale_correction(latest.position_type, latest.correction_age_s):
        status = "stale_corrections"
    elif (
        latest.source in ("PPPNAV", "PPPNAVH")
        and latest.position_type == "PPP_CONVERGING"
    ):
        status = "converging"
    elif latest.source in ("PPPNAV", "PPPNAVH"):
        status = "ppp_solution"
    else:
        status = "positioning"
    switches = [
        {"time_gps_s": point.timestamp, "source": point.source}
        for previous, point in pairwise(track.points)
        if point.source != previous.source
    ]
    report = track.report(fence)
    report.update(
        {
            "status": status,
            "source": latest.source if latest else None,
            "precision_service": precision_service,
            "record_counts": {name: len(rows) for name, rows in captured.items()},
            "rejected": {
                "BESTNAV": dict(best_rejected),
                "PPPNAV": dict(ppp_rejected),
            },
            "first_ppp_gps_s": first_ppp,
            "source_switches": switches,
            "ppp_fix_classes": dict(
                Counter(point.position_type for point in ppp.points)
            ),
            "dop": dop_report(captured),
            "satellites": satellite_report(captured.get("SATSINFO", ())),
            "quality_note": (
                "Position standard deviations are receiver estimates. Accuracy "
                "requires an independent reference. PPP_CONVERGING is not a full "
                "PPP fix, and a PPP fix does not identify which correction "
                "service supplied it. Differential and RTK fixes need current "
                "corrections, with ages above 10 seconds reported as stale."
            ),
        }
    )
    exit_code = int(
        latest is None
        or status == "converging"
        or status == "stale_corrections"
        or (precision_service is not None and status != "ppp_solution")
    )
    return PositionAnalysis(track, status, report, exit_code)
