"""Collect SATVIS2 frames and report constellation visibility and a sky plot."""

from __future__ import annotations

import math
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from examples.satellite_monitor import (
    AngleRange,
    ConstellationVisibility,
    FieldStatistics,
    latest_frames,
    sky_plot_csv,
    visibility_summary,
)
from um982py.capture import capture_records, latest_epoch
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages.record import Record


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.satellite_monitor", description=__doc__
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=5.0, help="collection time in seconds"
    )
    parser.add_argument(
        "--interval", type=float, default=1.0, help="SATVIS2 output interval in seconds"
    )
    parser.add_argument(
        "--mask", type=float, default=0.0, help="elevation mask in degrees"
    )
    parser.add_argument(
        "--binary", action="store_true", help="request binary SATVIS2 frames"
    )
    parser.add_argument(
        "--csv", type=Path, default=None, help="write azimuth, elevation, prn rows here"
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
            f"satellite_monitor debug: records={counts}",
            file=sys.stderr,
            flush=True,
        )

    return progress


def _range_payload(values: AngleRange) -> dict[str, float | None]:
    return {"minimum": _finite(values.minimum), "maximum": _finite(values.maximum)}


def _field_payload(values: FieldStatistics) -> dict[str, float | None]:
    return {
        "mean": _finite(values.mean),
        "minimum": _finite(values.minimum),
        "maximum": _finite(values.maximum),
        "standard_deviation": _finite(values.standard_deviation),
    }


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _payload(rows: Sequence[ConstellationVisibility]) -> dict[str, object]:
    return {
        "constellations": [
            {
                "constellation": row.constellation.value,
                "count": row.count,
                "elevation": _range_payload(row.elevation),
                "azimuth": _range_payload(row.azimuth),
                "field_7": _field_payload(row.field_7),
                "satellites": [
                    {
                        "prn": satellite.prn,
                        "channel": satellite.channel,
                        "elevation": satellite.elevation,
                        "azimuth": satellite.azimuth,
                        "field_7": satellite.field_7,
                    }
                    for satellite in row.satellites
                ],
            }
            for row in rows
        ]
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Collect SATVIS2 frames, then report visibility and the sky-plot CSV."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.debug:
        origin = f"replay {args.replay}" if args.replay else f"receiver {args.port}"
        print(
            f"satellite_monitor debug: {origin}; "
            f"duration={args.duration:g}s; interval={args.interval:g}s",
            file=sys.stderr,
            flush=True,
        )
    records = capture_records(
        args,
        [FirmwareLog.SATVIS2],
        duration=args.duration,
        interval=args.interval,
        binary=args.binary,
        on_progress=_progress_callback() if args.debug else None,
    )["SATVIS2"]
    frames = latest_frames(latest_epoch(records))
    rows = visibility_summary(frames, args.mask)
    total = sum(row.count for row in rows)
    print(
        f"Satellite visibility: {total} satellites in "
        f"{len(rows)} constellations above {args.mask:g} deg",
        file=sys.stderr,
    )
    write_json(_payload(rows), args.json)
    if args.csv is not None:
        satellites = [item for row in rows for item in row.satellites]
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        args.csv.write_text(sky_plot_csv(satellites), encoding="utf-8")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
