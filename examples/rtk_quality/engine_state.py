"""Inspect experimental RTKDATA engine covariance and satellite states."""

import sys
from collections.abc import Sequence
from contextlib import suppress
from time import monotonic, sleep

from examples._console import experiment_parser, run, write_json
from examples._console_capture import open_receiver
from um982py.capture import iter_frames
from um982py.errors import ResponseTimeout
from um982py.experimental import (
    RtkData,
    decode_rtk_data,
    rtk_data2_read,
    rtk_data_read,
    rtk_datah_read,
)
from um982py.measurement import gps_epoch
from um982py.messages import BinaryMessage


def _report(samples: Sequence[RtkData]) -> dict[str, object]:
    """Summarise engine covariance and satellite states per epoch."""
    epochs = []
    for sample in samples:
        identifiers = [sat.satellite_id for sat in sample.satellites]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate satellite identifiers in RTKDATA")
        epoch: dict[str, object] = {
            "gps_seconds": gps_epoch(sample.message),
            "report": sample.name,
            "solution_status": sample.solution_status,
            "position_type": sample.position_type,
            "covariance": sample.covariance,
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
                    "status_label": item.status_label,
                    "ambiguity_fixed": item.ambiguity_fixed,
                    "value": item.value,
                }
                for item in sample.satellites
            ],
        }
        if sample.name == "RTKDATAH":
            epoch["ambiguities"] = {
                "float": sum(
                    item.ambiguity_fixed is False for item in sample.satellites
                ),
                "fixed": sum(
                    item.ambiguity_fixed is True for item in sample.satellites
                ),
                "reference_satellite_ids": [
                    item.satellite_id
                    for item in sample.satellites
                    if item.status_label == "REFERENCE"
                ],
            }
        epochs.append(epoch)
    return {
        "status": "ok" if samples else "insufficient_data",
        "epochs": epochs,
        "limitations": (
            "RTKDATAH labels come from the receiver's ASCII report. "
            "The covariance coordinate frame, raw value units and some satellite "
            "identifiers remain unresolved. OEM-style header time is assumed GPST."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Collect RTKDATA frames and report engine covariance and states."""
    parser = experiment_parser(
        "engine_state", "Inspect RTKDATA, RTKDATA2 and RTKDATAH", output_rate=False
    )
    parser.add_argument(
        "--heading", action="store_true", help="Show the heading engine"
    )
    args = parser.parse_args(argv)
    if args.antenna not in ("primary", "1") or args.swap_antennas:
        parser.error("RTKDATA antenna scope is not established")
    samples: list[RtkData] = []
    if args.replay:
        message_ids = (6007,) if args.heading else (215, 2027, 6007)
        samples.extend(
            decode_rtk_data(frame)
            for frame in iter_frames(args.replay)
            if isinstance(frame, BinaryMessage)
            and frame.header.message_id in message_ids
        )
    else:
        reads = (
            (rtk_datah_read(),) if args.heading else (rtk_data_read(), rtk_data2_read())
        )
        with open_receiver(args) as receiver:
            deadline = monotonic() + args.duration
            while monotonic() < deadline:
                started = monotonic()
                for read in reads:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        break
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
