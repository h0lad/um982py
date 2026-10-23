"""Inspect experimental firmware-reported satellite state transitions."""

import sys
from collections.abc import Sequence
from contextlib import suppress
from time import monotonic, sleep

from um982py.capture import iter_frames, open_receiver
from um982py.console import experiment_parser, run, write_json
from um982py.errors import ResponseTimeout
from um982py.experimental import (
    MatchedSolution,
    decode_matched_solution,
    matched_solution_read,
)
from um982py.measurement import gps_epoch
from um982py.messages import BinaryMessage


def _report(samples: Sequence[MatchedSolution], max_gap: float) -> dict[str, object]:
    epochs = []
    transitions: list[dict[str, object]] = []
    previous: dict[int, tuple[int, int, int]] = {}
    previous_epoch: float | None = None
    for sample in samples:
        epoch = gps_epoch(sample.message)
        current = {sat.satellite_id: sat.status_codes for sat in sample.satellites}
        if len(current) != len(sample.satellites):
            raise ValueError("duplicate satellite identifiers in MATCHEDSOLUTION")
        if previous_epoch is not None and 0 < epoch - previous_epoch <= max_gap:
            transitions.extend(
                {
                    "previous_epoch": previous_epoch,
                    "epoch": epoch,
                    "satellite_id": satellite,
                    "previous_codes": previous[satellite],
                    "codes": current[satellite],
                }
                for satellite in sorted(previous.keys() & current.keys())
                if previous[satellite] != current[satellite]
            )
        epochs.append(
            {
                "gps_seconds": epoch,
                "satellites": [
                    {
                        "satellite_id": item.satellite_id,
                        "status_codes": item.status_codes,
                        "status_labels": item.status_labels,
                        "values": item.values,
                    }
                    for item in sample.satellites
                ],
            }
        )
        previous, previous_epoch = current, epoch
    return {
        "status": "ok" if samples else "insufficient_data",
        "epochs": epochs,
        "status_transitions": transitions,
        "max_gap_s": max_gap,
        "limitations": (
            "Experimental binary layout. Status meaning, signal "
            "assignment, value units and phase conventions are unverified. "
            "Changes are receiver-reported transitions, not proof of cycle slips "
            "or ambiguity resolution. Legacy header time is assumed GPST."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = experiment_parser("matched_solution", "Inspect MATCHEDSOLUTIONB")
    parser.add_argument("--max-gap", type=float, default=5.0)
    args = parser.parse_args(argv)
    if args.antenna not in ("primary", "1") or args.swap_antennas:
        parser.error("MATCHEDSOLUTION antenna scope is not established")
    samples: list[MatchedSolution] = []
    if args.replay:
        samples.extend(
            decode_matched_solution(frame)
            for frame in iter_frames(args.replay)
            if isinstance(frame, BinaryMessage) and frame.header.message_id == 2020
        )
    else:
        with open_receiver(args) as receiver:
            deadline = monotonic() + args.duration
            while (remaining := deadline - monotonic()) > 0:
                started = monotonic()
                with suppress(ResponseTimeout):
                    samples.append(
                        receiver.execute(
                            matched_solution_read(), timeout=min(remaining, 2)
                        )
                    )
                delay = min(
                    args.interval - (monotonic() - started), deadline - monotonic()
                )
                if delay > 0:
                    sleep(delay)
    payload = _report(samples, args.max_gap)
    write_json(payload, args.json)
    print(f"MATCHEDSOLUTION: {len(samples)} frames", file=sys.stderr)
    return 0 if samples else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
