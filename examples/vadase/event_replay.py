"""Compare Doppler and carrier-phase motion with independent velocities."""

import argparse
import csv
import itertools
import json
import math
from collections.abc import Sequence
from pathlib import Path

from um982py.field_data import file_sha256, nearest_epoch


def _vector(values: object) -> list[float]:
    if not isinstance(values, (list, tuple)) or len(values) != 3:
        raise ValueError("velocity must have three ECEF components")
    result = [float(v) for v in values]
    if not all(math.isfinite(v) for v in result):
        raise ValueError("velocity components must be finite")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--doppler", type=Path, required=True, help="examples.doppler_velocity JSON"
    )
    parser.add_argument("--tdcp", type=Path, required=True, help="examples.vadase JSON")
    parser.add_argument(
        "--reference",
        type=Path,
        help="independent CSV gps_seconds,vx_mps,vy_mps,vz_mps",
    )
    parser.add_argument(
        "--reference-frame",
        required=True,
        help="common ECEF frame established independently",
    )
    parser.add_argument("--match-window-s", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if (
        not args.reference_frame.strip()
        or not math.isfinite(args.match_window_s)
        or args.match_window_s < 0
    ):
        parser.error("provide a frame and a finite non-negative matching window")
    inputs = [args.doppler, args.tdcp, *([args.reference] if args.reference else [])]
    if args.output.resolve() in {p.resolve() for p in inputs}:
        parser.error("output must differ from inputs")
    doppler, tdcp = (
        json.loads(path.read_text(encoding="utf-8"))
        for path in (args.doppler, args.tdcp)
    )
    dop_rows, phase_rows = doppler["epochs"], tdcp["epochs"]
    reference = []
    if args.reference:
        with args.reference.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                epoch = float(row["gps_seconds"])
                velocity = _vector([row["vx_mps"], row["vy_mps"], row["vz_mps"]])
                if not math.isfinite(epoch):
                    raise ValueError("reference epochs must be finite")
                reference.append((epoch, velocity))
    for rows in (dop_rows, phase_rows):
        times = [float(row["epoch"]) for row in rows]
        if any(not math.isfinite(t) for t in times) or any(
            b <= a for a, b in itertools.pairwise(times)
        ):
            raise ValueError("motion epochs must be finite and strictly increasing")
    reference.sort(key=lambda item: item[0])
    reference_times = [item[0] for item in reference]
    phase_index = [(float(row["epoch"]), row) for row in phase_rows]
    phase_times = [item[0] for item in phase_index]
    matched = []
    matched_phase_epochs: set[float] = set()
    for row in dop_rows:
        epoch = float(row["epoch"])
        dop = _vector(row["velocity"])
        phase_match = nearest_epoch(phase_index, phase_times, epoch)
        phase = phase_match[1] if phase_match else None
        if (
            phase is not None
            and abs(float(phase["epoch"]) - epoch) > args.match_window_s
        ):
            phase = None
        if phase is not None:
            phase_start = float(phase["start_epoch"])
            phase_end = float(phase["epoch"])
            if not math.isfinite(phase_start) or phase_start >= phase_end:
                raise ValueError("TDCP intervals must have finite increasing epochs")
            matched_phase_epochs.add(phase_end)
        ref = nearest_epoch(reference, reference_times, epoch)
        if ref is not None and abs(ref[0] - epoch) > args.match_window_s:
            ref = None
        phase_velocity = _vector(phase["velocity_mps"]) if phase else None
        matched.append(
            {
                "gps_seconds": epoch,
                "doppler_velocity_ecef_mps": dop,
                "tdcp_end_gps_seconds": float(phase["epoch"]) if phase else None,
                "tdcp_start_gps_seconds": float(phase["start_epoch"])
                if phase
                else None,
                "tdcp_velocity_ecef_mps": phase_velocity,
                "tdcp_displacement_ecef_m": _vector(phase["displacement_m"])
                if phase
                else None,
                "reference_gps_seconds": ref[0] if ref else None,
                "reference_velocity_ecef_mps": ref[1] if ref else None,
                "doppler_minus_reference_mps": [
                    x - y for x, y in zip(dop, ref[1], strict=True)
                ]
                if ref
                else None,
                "tdcp_minus_reference_mps": [
                    x - y for x, y in zip(phase_velocity, ref[1], strict=True)
                ]
                if phase_velocity is not None and ref is not None
                else None,
            }
        )
    result = {
        "reference_frame_supplied_by_user": args.reference_frame,
        "match_window_s": args.match_window_s,
        "timeline": matched,
        "doppler_rejected": doppler.get("rejected", []),
        "tdcp_rejected": tdcp.get("rejected", []),
        "unmatched_tdcp_epochs": [
            row["epoch"]
            for row in phase_rows
            if float(row["epoch"]) not in matched_phase_epochs
        ],
        "inputs": [{"path": str(p), "sha256": file_sha256(p)} for p in inputs],
        "limitations": (
            "Doppler is a velocity estimate at an epoch; TDCP is an "
            "interval-average ending at its recorded epoch. Nearest-epoch "
            "matching does not align their temporal response or establish a "
            "common physical reference point. No displacement is integrated "
            "across gaps. Independent reference, common frame, sample rate and "
            "timing are required to evaluate a real event. This is not an "
            "earthquake warning system."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return 0 if matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
