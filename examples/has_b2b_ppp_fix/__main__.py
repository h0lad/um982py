"""Runs a dual-service PPP occupation with live divergence telemetry."""

from __future__ import annotations

import math
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from examples.has_b2b_ppp_fix import (
    DivergenceTally,
    MeanFix,
    PrecisionStatistics,
    convergence,
    divergence_tally,
    format_position,
    format_precision,
    mean_fix,
    position_label,
    ppp_epochs,
    precision_statistics,
    xyz_fallback,
)
from um982py.capture import capture_logs, record_epoch
from um982py.commands import Log
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    run,
    write_json,
)
from um982py.experimental import FirmwareLog
from um982py.experimental.carrier import monitor_divergence
from um982py.measurement import RangeSample, SignalKey, gnss_range_samples
from um982py.messages import Record

B2B_LOGS = (
    Log.PPPB2BINFO1,
    Log.PPPB2BINFO2,
    Log.PPPB2BINFO3,
    Log.PPPB2BINFO4,
    Log.PPPB2BINFO5,
    Log.PPPB2BINFO6,
    Log.PPPB2BINFO7,
)
HAS_LOGS = (
    Log.E6MASKBLOCK,
    Log.E6ORBITBLOCK,
    Log.E6CLOCKFULLBLOCK,
    Log.E6CBIASBLOCK,
)


def _signal_name(key: SignalKey) -> str:
    """Compact system/prn/signal tag for one divergence arc."""
    return f"sys{key.system}-prn{key.prn:02d}-sig{key.signal:02d}"


def _divergence_lines(
    range_records: Sequence[Record], *, tau: float, threshold: float, max_gap: float
) -> tuple[tuple[str, int, int, int, float | None], ...]:
    """Per-signal divergence summary used by both the log and the report."""
    series: dict[SignalKey, list[RangeSample]] = defaultdict(list)
    for record in range_records:
        for sample in gnss_range_samples(record, epoch=record_epoch(record)):
            series[sample.key].append(sample)
    summary = []
    for key in sorted(series):
        items = monitor_divergence(
            tuple(series[key]), tau=tau, threshold=threshold, max_gap=max_gap
        )
        usable = sum(1 for item in items if not item.reset)
        resets = sum(1 for item in items if item.reset)
        exceeds = sum(1 for item in items if item.exceeds_threshold)
        peaks = [
            abs(item.filtered_mps)
            for item in items
            if item.filtered_mps is not None and math.isfinite(item.filtered_mps)
        ]
        summary.append(
            (_signal_name(key), usable, resets, exceeds, max(peaks) if peaks else None)
        )
    return tuple(summary)


def _progress(
    name: str,
    captured: dict[str, tuple[Record, ...]],
    *,
    tau: float,
    threshold: float,
    max_gap: float,
) -> None:
    """Log PPP convergence and code-carrier divergence while capturing."""
    ppp = ppp_epochs(captured.get("PPPNAV", ()))
    b2b = sum(
        len(rows)
        for log_name, rows in captured.items()
        if log_name.startswith("PPPB2BINFO")
    )
    has_blocks = sum(
        len(rows) for log_name, rows in captured.items() if log_name.startswith("E6")
    )
    tally = divergence_tally(
        _divergence_lines(
            captured.get("RANGE", ()), tau=tau, threshold=threshold, max_gap=max_gap
        )
    )
    worst = (
        f"{tally.worst_filtered_mps:.4f} m/s {tally.worst_signal}"
        if tally.worst_filtered_mps is not None and tally.worst_signal is not None
        else "n/a"
    )
    if ppp:
        latest = ppp[-1]
        sigma = latest.horizontal_sigma
        sigma_text = f"{sigma:.3f} m" if sigma is not None else "unknown"
        vertical = latest.height_sigma
        vertical_text = f"{vertical:.3f} m" if vertical is not None else "unknown"
        state = (
            f"[{len(ppp):>4}] {position_label(latest.position_type):<14}"
            f"H {sigma_text:>11} V {vertical_text:>11} sats {latest.satellites:>3}"
        )
    else:
        state = "[   0] waiting for first PPPNAV fix"
    print(
        f"{name} debug: {state} | HAS {has_blocks:>3} B2b {b2b:>3} | "
        f"div {tally.signals:>3}sig {tally.exceeds:>4}exc worst {worst}",
        file=sys.stderr,
        flush=True,
    )


def _rule(title: str, width: int = 64) -> str:
    """Centred title rule for report sections."""
    padded = f" {title} "
    side = max(0, (width - len(padded)) // 2)
    line = "=" * side + padded + "=" * side
    return line + "=" * max(0, width - len(line))


def _report(
    fix: MeanFix,
    stats: PrecisionStatistics | None,
    *,
    service: str,
    total: int,
    ppp: int,
    converged_fix: int,
    converged: bool,
    tally: DivergenceTally,
    per_signal: Sequence[tuple[str, int, int, int, float | None]],
    b2b_blocks: int,
    has_blocks: int,
) -> str:
    """Multi-section human-readable occupation report."""
    lines = [
        _rule(f"HAS+B2b PPP FIX · service {service} · {total} PPPNAV epochs"),
        "-- POSITION --",
        *format_position(fix),
    ]
    if stats is not None:
        lines += ["-- PRECISION --", *format_precision(stats)]
    lines += [
        "-- DIVERGENCE --",
        f"  {'samples':.<26} {tally.samples} on {tally.signals} signals",
        f"  {'arc resets':.<26} {tally.resets}",
        f"  {'threshold exceedances':.<26} {tally.exceeds}",
    ]
    if tally.worst_filtered_mps is not None and tally.worst_signal is not None:
        lines.append(
            f"  {'worst filtered':.<26} {tally.worst_filtered_mps:.4f} m/s "
            f"on {tally.worst_signal}"
        )
    ranked = sorted(
        per_signal,
        key=lambda item: item[4] if item[4] is not None else -1.0,
        reverse=True,
    )
    leaders = [item for item in ranked if item[4] is not None][:5]
    if leaders:
        lines.append("  worst signals:")
        for name, samples, _resets, exceeds, peak in leaders:
            assert peak is not None
            lines.append(
                f"    {name:<22} peak {peak:.4f} m/s, {samples} smp, {exceeds} exc"
            )
    lines += [
        "-- CORRECTIONS --",
        f"  {'B2b blocks':.<26} {b2b_blocks}",
        f"  {'HAS blocks':.<26} {has_blocks}",
        f"  {'PPP fixes':.<26} {ppp} ({converged_fix} converged)",
        f"  {'converged':.<26} {converged}",
        _rule("end of report"),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Occupy one point with E6-HAS plus B2b-PPP and average the PPP fixes."""
    parser = experiment_parser(
        "has_b2b_ppp_fix",
        "Ultra-precise PPP fix from Galileo E6-HAS and BeiDou B2b-PPP "
        "with code-carrier divergence telemetry",
    )
    parser.set_defaults(duration=300.0)
    parser.add_argument(
        "--ppp-service",
        dest="ppp_service",
        choices=("AUTO", "E6-HAS", "B2B-PPP"),
        default="AUTO",
        help="free satellite PPP provider asserted on the receiver",
    )
    parser.add_argument(
        "--tau",
        type=float,
        default=100.0,
        help="divergence filter time constant in seconds",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help="divergence alarm threshold in m/s",
    )
    parser.add_argument(
        "--max-gap",
        type=float,
        default=2.0,
        help="largest RANGE gap kept inside one carrier arc, seconds",
    )
    parser.add_argument(
        "--target-h-sigma",
        type=float,
        default=0.10,
        help="converged horizontal sigma in metres",
    )
    parser.add_argument(
        "--target-v-sigma",
        type=float,
        default=0.20,
        help="converged vertical sigma in metres",
    )
    parser.add_argument(
        "--min-ppp",
        type=int,
        default=30,
        help="minimum PPP fixes expected before the fix counts as observed",
    )
    parser.add_argument("--csv", type=Path, default=None, help="write PPP epochs")
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "has_b2b_ppp_fix")
    if min(args.tau, args.threshold, args.max_gap) <= 0:
        parser.error("tau, threshold and maximum gap must be positive")
    if min(args.target_h_sigma, args.target_v_sigma) <= 0:
        parser.error("convergence targets must be positive")
    if args.min_ppp <= 0:
        parser.error("--min-ppp must be positive")
    seen: dict[str, int] = {}

    def on_progress(captured: dict[str, tuple[Record, ...]]) -> None:
        counts = {log_name: len(rows) for log_name, rows in captured.items()}
        if counts == seen:
            return
        seen.update(counts)
        _progress(
            "has_b2b_ppp_fix",
            captured,
            tau=args.tau,
            threshold=args.threshold,
            max_gap=args.max_gap,
        )

    captured = capture_logs(
        args,
        (Log.PPPNAV, FirmwareLog.BESTXYZ, FirmwareLog.RANGE, *B2B_LOGS, *HAS_LOGS),
        on_progress=on_progress if args.debug else None,
    )
    epochs = ppp_epochs(captured.get("PPPNAV", ()))
    per_signal = _divergence_lines(
        captured.get("RANGE", ()),
        tau=args.tau,
        threshold=args.threshold,
        max_gap=args.max_gap,
    )
    tally = divergence_tally(per_signal)
    b2b_blocks = sum(
        len(rows)
        for log_name, rows in captured.items()
        if log_name.startswith("PPPB2BINFO")
    )
    has_blocks = sum(
        len(rows) for log_name, rows in captured.items() if log_name.startswith("E6")
    )
    model = convergence(
        epochs,
        target_horizontal=args.target_h_sigma,
        target_vertical=args.target_v_sigma,
    )
    try:
        fix = mean_fix(epochs, ppp_only=True)
    except ValueError:
        fix = None
    if fix is None:
        try:
            fix = xyz_fallback(captured.get("BESTXYZ", ()))
        except ValueError as error:
            parser.error(f"capture contains no PPPNAV or BESTXYZ positions: {error}")
    assert fix is not None
    fix_epochs = (
        tuple(item for item in epochs if item.is_ppp)
        if fix.source == "PPPNAV"
        else epochs
    )
    stats = precision_statistics(fix_epochs) if fix_epochs else None
    print(
        _report(
            fix,
            stats,
            service=args.ppp_service,
            total=model.total,
            ppp=model.ppp,
            converged_fix=model.converged_fix,
            converged=model.converged,
            tally=tally,
            per_signal=per_signal,
            b2b_blocks=b2b_blocks,
            has_blocks=has_blocks,
        ),
        file=sys.stderr,
    )
    if args.csv is not None:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        lines = ["epoch_gps,lat_deg,lon_deg,hgt_m,pos_type,sats,h_sigma_m,v_sigma_m"]
        lines.extend(
            f"{item.epoch:.3f},{item.latitude:.9f},{item.longitude:.9f},"
            f"{item.height:.3f},{item.position_type},{item.satellites},"
            f"{item.latitude_sigma if item.latitude_sigma is not None else ''},"
            f"{item.height_sigma if item.height_sigma is not None else ''}"
            for item in epochs
        )
        args.csv.write_text("\n".join(lines) + "\n", encoding="ascii")
    write_json(
        {
            "status": "ok" if model.ppp >= args.min_ppp else "insufficient_ppp",
            "service": args.ppp_service,
            "signal_group": "3/6 carries Galileo E6 and BDS B2b; use --augment",
            "fix": {
                "latitude": fix.latitude,
                "longitude": fix.longitude,
                "height": fix.height,
                "ecef": list(fix.ecef),
                "horizontal_scatter": fix.horizontal_scatter,
                "vertical_scatter": fix.vertical_scatter,
                "horizontal_sigma": fix.horizontal_sigma,
                "vertical_sigma": fix.vertical_sigma,
                "epochs": fix.epochs,
                "source": fix.source,
            },
            "precision": asdict(stats) if stats is not None else None,
            "convergence": {
                "total": model.total,
                "ppp": model.ppp,
                "converged_fix": model.converged_fix,
                "first_horizontal_sigma": model.first_horizontal_sigma,
                "last_horizontal_sigma": model.last_horizontal_sigma,
                "improvement": model.improvement,
                "converged": model.converged,
                "classes": list(model.classes),
            },
            "divergence": asdict(tally),
            "divergence_signals": [
                {
                    "signal": name,
                    "samples": samples,
                    "resets": resets,
                    "exceeds": exceeds,
                    "peak_filtered_mps": peak,
                }
                for name, samples, resets, exceeds, peak in per_signal
            ],
            "corrections": {
                "b2b_blocks": b2b_blocks,
                "has_blocks": has_blocks,
                "delivery_is_not_application": True,
            },
            "limitation": (
                "delivery of E6-HAS or B2b blocks does not prove the receiver "
                "applied them, and accuracy needs an independent reference"
            ),
        },
        args.json,
    )
    return 0 if model.ppp >= args.min_ppp or fix.source == "BESTXYZ" else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
