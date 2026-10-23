"""Runs the empirical C/N0 elevation-pattern example."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path

from examples.antenna_gain_pattern import (
    DEFAULT_CURVE_STEP,
    GainFit,
    SkySample,
    epoch_sky_samples,
    fit_gain_pattern,
    gain_curve,
)
from um982py.capture import capture_records
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record
from um982py.signals import tracking_signal

CSV_HEADER = "elevation_deg,relative_cn0_db,cn0_db_hz"


def _payload(
    samples: Sequence[SkySample],
    fit: GainFit,
    epochs: int,
    step: float,
    *,
    system: int = 0,
    signal: int = 0,
) -> dict[str, object]:
    """Serialise the fit and the curve it predicts."""
    identified = tracking_signal((system << 16) | (signal << 21))
    label = (
        f"{identified.constellation} {identified.name}"
        if identified is not None
        else "GPS L1"
    )
    return {
        "measurement": (
            f"empirical {label} C/N0 pattern; "
            "transmitter power and obstructions are not separated"
        ),
        "signal": None if identified is None else asdict(identified),
        "epochs": epochs,
        "constellations": sorted({str(sample.constellation) for sample in samples}),
        "fit": {
            "zenith_cn0": fit.zenith_cn0,
            "linear_rolloff": fit.linear_rolloff,
            "quadratic_rolloff": fit.quadratic_rolloff,
            "reference_range": fit.reference_range,
            "fit_residual_rms_db": fit.residual_rms_db,
            "sample_count": fit.sample_count,
        },
        "curve": [list(row) for row in gain_curve(fit, step)],
    }


def _write_csv(fit: GainFit, step: float, destination: Path | None) -> None:
    """Write the fitted curve as CSV to a file or to stdout."""
    rows = [CSV_HEADER]
    rows.extend(
        f"{elevation:.1f},{gain:.4f},{cn0:.4f}"
        for elevation, gain, cn0 in gain_curve(fit, step)
    )
    text = "\n".join(rows) + "\n"
    if destination is None:
        sys.stdout.write(text)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.antenna_gain_pattern",
        description="Fit an empirical received C/N0 pattern versus elevation.",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--csv", type=Path, default=None, help="write the fitted curve as CSV here"
    )
    parser.add_argument(
        "--step",
        type=float,
        default=DEFAULT_CURVE_STEP,
        help="elevation step of the reported curve in degrees",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="collection time in seconds when reading the device",
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="output interval in seconds"
    )
    parser.add_argument(
        "--system",
        type=int,
        choices=range(7),
        default=0,
        help="RANGE satellite system code (0=GPS, 1=GLO, 3=GAL, 4=BDS)",
    )
    parser.add_argument(
        "--signal",
        type=int,
        choices=range(32),
        default=0,
        help="RANGE signal ID (e.g. 0=L1CA, 9=L2, 14=L5Q, 22=E6C, 21=B3I)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    return parser


def _progress_callback() -> Callable[[dict[str, tuple[Record, ...]]], None]:
    seen: dict[str, int] = {}

    def progress(captured: dict[str, tuple[Record, ...]]) -> None:
        counts = {name: len(rows) for name, rows in captured.items()}
        if counts == seen:
            return
        seen.update(counts)
        print(
            f"antenna_gain_pattern debug: records={counts}",
            file=sys.stderr,
            flush=True,
        )

    return progress


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        source = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"antenna_gain_pattern debug: {source}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    captured = capture_records(
        args,
        [FirmwareLog.SATVIS2, FirmwareLog.RANGE],
        duration=args.duration,
        interval=args.interval,
        on_progress=_progress_callback() if args.debug else None,
    )
    visibility, observations = captured["SATVIS2"], captured["RANGE"]
    samples = (
        epoch_sky_samples(
            visibility, observations, system=args.system, signal=args.signal
        )
        if visibility and observations
        else ()
    )
    if not samples:
        print("capture holds no joined SATVIS2 and RANGE epoch", file=sys.stderr)
        return 1
    fit = fit_gain_pattern(samples)
    _write_csv(fit, args.step, args.csv)
    payload = _payload(
        samples,
        fit,
        len(observations),
        args.step,
        system=args.system,
        signal=args.signal,
    )
    print(
        f"Antenna gain: {fit.sample_count} samples, residual RMS "
        f"{fit.residual_rms_db:.3f} dB, zenith C/N0 {fit.zenith_cn0:.2f} dB-Hz",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
