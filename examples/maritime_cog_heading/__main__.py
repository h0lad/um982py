# Compare single-antenna COG with dual-antenna heading on a marine vessel.

from __future__ import annotations

import math
import sys
from collections.abc import Sequence

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples._console_capture import capture_records
from examples.maritime_cog_heading import compute_cog_heading
from um982py.capture import record_epoch
from um982py.commands import Log


def _payload(
    positions: Sequence[Record],
    headings: Sequence[Record],
    min_speed_ms: float,
) -> dict[str, object]:
    epochs = compute_cog_heading(positions, headings, min_speed_ms=min_speed_ms)
    differences = [e.heading_minus_cog_deg for e in epochs if e.heading_minus_cog_deg is not None]

    def _mean(values: Sequence[float]) -> float | None:
        return sum(values) / len(values) if values else None

    def _rms(values: Sequence[float]) -> float | None:
        if not values:
            return None
        return math.sqrt(sum(v * v for v in values) / len(values))

    return {
        "min_speed_ms": min_speed_ms,
        "matched_epochs": len(epochs),
        "cog_heading_epochs": len(differences),
        "statistics": {
            "heading_minus_cog_mean_deg": _mean(differences),
            "heading_minus_cog_rms_deg": _rms(differences),
            "heading_minus_cog_min_deg": min(differences) if differences else None,
            "heading_minus_cog_max_deg": max(differences) if differences else None,
        },
        "epochs": [
            {
                "epoch": e.epoch,
                "latitude": e.latitude,
                "longitude": e.longitude,
                "speed_ms": e.speed_ms,
                "cog_deg": e.cog_deg,
                "heading_deg": e.heading_deg,
                "pitch_deg": e.pitch_deg,
                "heading_minus_cog_deg": e.heading_minus_cog_deg,
            }
            for e in epochs
        ],
        "limitation": (
            "COG is computed from finite-difference positions and is undefined "
            "at very low speed.  Heading-COG differences include current, leeway "
            "and latency; they are not purely an attitude error."
        ),
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.maritime_cog_heading",
        description=(
            "Compute COG from successive single-antenna positions and compare "
            "with dual-antenna heading."
        ),
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration",
        type=float,
        default=30.0,
        help="live collection time in seconds",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="capture interval in seconds",
    )
    parser.add_argument(
        "--min-speed",
        type=float,
        default=0.5,
        help="minimum speed in m/s for a reliable COG estimate",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    records = capture_records(
        args,
        [Log.BESTNAV, Log.UNIHEADING],
        duration=args.duration,
        interval=args.interval,
    )
    positions = records.get("BESTNAV", ())
    headings = records.get("UNIHEADING", ())
    if len(positions) < 2:
        parser.error("need at least two BESTNAV positions to compute COG")
    payload = _payload(positions, headings, args.min_speed)
    print(
        f"Matched {payload['matched_epochs']} epochs; "
        f"COG/heading pairs: {payload['cog_heading_epochs']}; "
        f"mean heading-COG = "
        f"{payload['statistics']['heading_minus_cog_mean_deg']:.2f} deg",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
