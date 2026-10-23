"""Collects a static occupation into one precise, checked position fix."""

from __future__ import annotations

import math
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from examples.precise_fix import (
    Axis,
    FixEstimate,
    FixSample,
    estimate,
    join_undulations,
    marker_position,
    reference_error,
)
from um982py.capture import capture_records
from um982py.console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from um982py.corrections import stale_correction
from um982py.experimental import FirmwareLog
from um982py.geodesy import geodetic_from_ecef


def _parse_ecef(text: str) -> tuple[float, float, float]:
    """Parse ``X,Y,Z`` in metres."""
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3:
        raise ValueError("expected three comma-separated metres")
    values = tuple(float(part) for part in parts)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("reference coordinates must be finite")
    return (values[0], values[1], values[2])


def _axis_payload(axis: Axis) -> dict[str, float]:
    """Serialisable view of one local axis."""
    return {
        "mean": axis.mean,
        "std": axis.std,
        "standard_error": axis.standard_error,
        "sigma95": axis.sigma95,
    }


def _marker_payload(
    ecef: tuple[float, float, float], antenna_height: float
) -> dict[str, object]:
    """Marker position below the antenna phase centre, with its geodetic form."""
    marker = marker_position(ecef, antenna_height)
    latitude, longitude, height = geodetic_from_ecef(*marker)
    return {
        "ecef": list(marker),
        "latitude": latitude,
        "longitude": longitude,
        "height": height,
        "antenna_height": antenna_height,
    }


def _reference_payload(
    position: tuple[float, float, float], reference: tuple[float, float, float]
) -> dict[str, object]:
    """Error of the averaged position against an independently known point."""
    east, north, up = reference_error(position, reference)
    return {
        "ecef": list(reference),
        "east": east,
        "north": north,
        "up": up,
        "horizontal": math.hypot(east, north),
        "total": math.sqrt(east * east + north * north + up * up),
    }


def _payload(
    result: FixEstimate,
    *,
    antenna_height: float,
    reference: tuple[float, float, float] | None,
) -> dict[str, object]:
    """Serialisable report of one static occupation."""
    return {
        "status": "ok" if result.converged else "not_converged",
        "samples": {
            "total": result.samples,
            "accepted": result.accepted,
            "rejected": result.rejected,
        },
        "fix_classes": dict(result.classes),
        "uncertainty_model": {
            "nominal": "independent Gaussian epochs; excludes systematic bias",
            "adjusted": (
                "lag-one AR(1) effective sample size, with negative serial "
                "correlation clipped to zero; still excludes systematic bias"
            ),
            "horizontal_95": "sqrt(chi2_2(0.95) * trace(horizontal covariance / n))",
            "horizontal_95_kind": (
                "conservative radius bound, not exact radial quantile"
            ),
            "single_epoch": "scatter and uncertainty undefined (null)",
        },
        "fix": {
            "ecef": list(result.ecef),
            "latitude": result.latitude,
            "longitude": result.longitude,
            "height": result.height,
            "height_msl": result.height_msl,
            "undulation": result.undulation,
            "east": _axis_payload(result.east),
            "north": _axis_payload(result.north),
            "up": _axis_payload(result.up),
            "epoch_horizontal_sigma": result.epoch_horizontal_sigma,
            "epoch_vertical_sigma": result.epoch_vertical_sigma,
            "horizontal_sigma": result.horizontal_sigma,
            "vertical_sigma": result.vertical_sigma,
            "effective_samples_enu": list(result.effective_samples_enu),
            "correlation_adjusted_horizontal_sigma": (
                result.correlation_adjusted_horizontal_sigma
            ),
            "correlation_adjusted_vertical_sigma": (
                result.correlation_adjusted_vertical_sigma
            ),
            "horizontal_95": result.horizontal_95,
            "vertical_95": result.vertical_95,
            "converged": result.converged,
            "trace": list(result.trace[-120:]),
        },
        "marker": None
        if antenna_height == 0
        else _marker_payload(result.ecef, antenna_height),
        "reference": None
        if reference is None
        else _reference_payload(result.ecef, reference),
        "rejections": [
            {"epoch": item.epoch, "reason": item.reason} for item in result.rejections
        ],
        "limitation": (
            "lag-one effective sample size is a screening approximation, not "
            "a calibrated confidence interval, and antenna and other systematic "
            "biases remain unmeasured, and every computed solution enters "
            "the unweighted mean unless it is a gross outlier"
        ),
    }


def _csv_report(result: FixEstimate, samples: Sequence[FixSample]) -> str:
    """One CSV row per accepted epoch with its local residual."""
    rejected = {item.epoch for item in result.rejections}
    lines = ["epoch_gps,x_m,y_m,z_m,east_m,north_m,up_m,pos_type,satellites,sigma_3d"]
    for sample in samples:
        if sample.epoch in rejected:
            continue
        east, north, up = reference_error(sample.ecef, result.ecef)
        lines.append(
            f"{sample.epoch:.3f},{sample.x:.4f},{sample.y:.4f},{sample.z:.4f},"
            f"{east:.4f},{north:.4f},{up:.4f},{sample.position_type},"
            f"{sample.satellites},{sample.sigma_3d:.4f}"
        )
    return "\n".join(lines) + "\n"


def _summary(result: FixEstimate) -> str:
    """Human-readable summary printed next to the machine-readable report."""
    reasons = Counter(item.reason for item in result.rejections)
    detail = ", ".join(f"{name}={count}" for name, count in sorted(reasons.items()))
    classes = ", ".join(f"{name}={count}" for name, count in result.classes)
    height = f"{result.height:.3f} m"
    if result.height_msl is not None and result.undulation is not None:
        height += f" (MSL {result.height_msl:.3f} m, N {result.undulation:.3f} m)"
    return (
        f"accepted {result.accepted} of {result.samples} epochs"
        + (f", rejected {result.rejected} [{detail}]" if detail else "")
        + f"; fix classes {classes}\n"
        f"fix ECEF {result.ecef[0]:.4f} {result.ecef[1]:.4f} {result.ecef[2]:.4f}\n"
        f"    lat {result.latitude:.9f}  lon {result.longitude:.9f}  h {height}\n"
        f"    epoch sigma {result.epoch_horizontal_sigma:.4f} H / "
        f"{result.epoch_vertical_sigma:.4f} V m\n"
        f"    mean sigma {result.horizontal_sigma:.4f} H / "
        f"{result.vertical_sigma:.4f} V m, "
        f"nominal 95% bound {result.horizontal_95:.4f} H / "
        f"{result.vertical_95:.4f} V m\n"
        f"    serial-adjusted mean sigma "
        f"{result.correlation_adjusted_horizontal_sigma:.4f} H / "
        f"{result.correlation_adjusted_vertical_sigma:.4f} V m\n"
        f"    converged {result.converged}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Average a static occupation into one precise, outlier-checked fix."""
    parser = experiment_parser(
        "precise_fix", "Static occupation averaged into one precise position"
    )
    parser.set_defaults(duration=120.0)
    parser.add_argument(
        "--sigma-k",
        type=float,
        default=4.0,
        help="outlier threshold in median absolute deviations, or 0 to disable",
    )
    parser.add_argument(
        "--min-samples", type=int, default=30, help="epochs reported as converged"
    )
    parser.add_argument(
        "--target-h-sigma", type=float, default=0.01, help="horizontal target, metres"
    )
    parser.add_argument(
        "--target-v-sigma", type=float, default=0.02, help="vertical target, metres"
    )
    parser.add_argument(
        "--antenna-height",
        type=float,
        default=0.0,
        help="phase-centre height above the marker in metres",
    )
    parser.add_argument(
        "--reference-ecef",
        type=_parse_ecef,
        default=None,
        help="independently known X,Y,Z in metres for an error report",
    )
    parser.add_argument("--csv", type=Path, default=None, help="write accepted epochs")
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    debug_header(args, "precise_fix")
    captured = capture_records(
        args,
        [FirmwareLog.BESTXYZ, FirmwareLog.BESTPOS],
        duration=args.duration,
        interval=args.interval,
        on_progress=progress_printer("precise_fix") if args.debug else None,
    )
    samples = join_undulations(captured["BESTXYZ"], captured["BESTPOS"])
    if not samples:
        parser.error("capture contains no BESTXYZ records")
    fresh = tuple(
        sample
        for sample in samples
        if not stale_correction(sample.position_type, sample.correction_age_s)
    )
    if len(fresh) != len(samples):
        print(
            f"Skipped {len(samples) - len(fresh)} positions with stale corrections",
            file=sys.stderr,
        )
    if not fresh:
        parser.error("capture contains no BESTXYZ positions with fresh corrections")
    model = estimate(
        fresh,
        sigma_k=args.sigma_k,
        minimum_samples=args.min_samples,
        target_horizontal_sigma=args.target_h_sigma,
        target_vertical_sigma=args.target_v_sigma,
    )
    print(_summary(model), file=sys.stderr)
    if args.csv is not None:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        args.csv.write_text(_csv_report(model, fresh), encoding="ascii")
    write_json(
        {
            **_payload(
                model,
                antenna_height=args.antenna_height,
                reference=args.reference_ecef,
            ),
            "stale_corrections_skipped": len(samples) - len(fresh),
        },
        args.json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
