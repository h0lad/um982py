"""Inspect experimental RTKDATA engine covariance and satellite states."""

import sys
from collections.abc import Sequence
from contextlib import suppress
from time import monotonic, sleep

from um982py.capture import iter_frames, open_receiver
from um982py.console import experiment_parser, run, write_json
from um982py.errors import ResponseTimeout
from um982py.experimental import (
    RtkData,
    decode_rtk_data,
    rtk_data2_read,
    rtk_data_read,
)
from um982py.measurement import gps_epoch
from um982py.messages import BinaryMessage

_MESSAGE_IDS = (215, 2027)


def _report(samples: Sequence[RtkData]) -> dict[str, object]:
    """Summarise engine covariance and satellite states per epoch."""
    epochs = []
    for sample in samples:
        identifiers = [sat.satellite_id for sat in sample.satellites]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate satellite identifiers in RTKDATA")
        epochs.append(
            {
                "gps_seconds": gps_epoch(sample.message),
                "report": sample.name,
                "variances": [
                    sample.covariance[0],
                    sample.covariance[4],
                    sample.covariance[8],
                ],
                "satellites": [
                    {
                        "satellite_id": item.satellite_id,
                        "system": item.system.name if item.system is not None else None,
                        "prn": item.prn,
                        "status": item.status,
                        "value": item.value,
                    }
                    for item in sample.satellites
                ],
            }
        )
    return {
        "status": "ok" if samples else "insufficient_data",
        "epochs": epochs,
        "limitations": (
            "Experimental binary layout. Covariance frame, status meaning, "
            "value units and unmapped satellite identifiers are unverified. "
            "Variances describe the engine state, not measured position "
            "error. Legacy header time is assumed GPST."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Collect RTKDATA frames and report engine covariance and states."""
    parser = experiment_parser("engine_state", "Inspect RTKDATA/RTKDATA2B")
    args = parser.parse_args(argv)
    if args.antenna not in ("primary", "1") or args.swap_antennas:
        parser.error("RTKDATA antenna scope is not established")
    samples: list[RtkData] = []
    if args.replay:
        samples.extend(
            decode_rtk_data(frame)
            for frame in iter_frames(args.replay)
            if isinstance(frame, BinaryMessage)
            and frame.header.message_id in _MESSAGE_IDS
        )
    else:
        with open_receiver(args) as receiver:
            deadline = monotonic() + args.duration
            while (remaining := deadline - monotonic()) > 0:
                started = monotonic()
                for read in (rtk_data_read(), rtk_data2_read()):
                    with suppress(ResponseTimeout):
                        samples.append(
                            receiver.execute(read, timeout=min(remaining, 2))
                        )
                delay = min(
                    args.interval - (monotonic() - started), deadline - monotonic()
                )
                if delay > 0:
                    sleep(delay)
    payload = _report(samples)
    write_json(payload, args.json)
    print(f"RTKDATA: {len(samples)} frames", file=sys.stderr)
    return 0 if samples else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
