# Compare independent master/slave RTK baselines with UNIHEADING.

from __future__ import annotations

import math
import sys
from collections.abc import Sequence

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples._console_capture import capture_records
from examples.dual_rtk_consistency import (
    ConsistencyEpoch,
    baseline_from_positions,
    heading_difference,
    heading_from_enu,
    pitch_from_enu,
)
from um982py.capture import record_epoch
from um982py.commands import Log


def _match_epochs(
    master_records: Sequence[Record],
    slave_records: Sequence[Record],
    heading_records: Sequence[Record],
) -> list[ConsistencyEpoch]:
    """Match master, slave and heading records by epoch."""
    headings: dict[float, Record] = {}
    for h in heading_records:
        epoch = record_epoch(h)
        if epoch is not None:
            headings[epoch] = h

    slaves: dict[float, Record] = {}
    for s in slave_records:
        epoch = record_epoch(s)
        if epoch is not None:
            slaves[epoch] = s

    epochs: list[ConsistencyEpoch] = []
    for master in master_records:
        epoch = record_epoch(master)
        if epoch is None:
            continue
        slave = slaves.get(epoch)
        if slave is None:
            continue
        result = baseline_from_positions(master, slave)
        if result is None:
            continue
        heading = headings.get(epoch)
        receiver_heading = heading.real("heading") if heading is not None else None
        receiver_pitch = heading.real("pitch") if heading is not None else None
        epochs.append(
            ConsistencyEpoch(
                epoch=epoch,
                master_ecef=result.master_ecef,
                slave_ecef=result.slave_ecef,
                diff_ecef=result.diff_ecef,
                diff_enu=result.diff_enu,
                diff_length_m=result.diff_length_m,
                receiver_heading_deg=receiver_heading
                if receiver_heading is not None and math.isfinite(receiver_heading)
                else None,
                receiver_pitch_deg=receiver_pitch
                if receiver_pitch is not None and math.isfinite(receiver_pitch)
                else None,
                master_rtk_fixed=result.master_rtk_fixed,
                slave_rtk_fixed=result.slave_rtk_fixed,
            )
        )
    return epochs


def _payload(epochs: Sequence[ConsistencyEpoch]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    heading_residuals: list[float] = []
    pitch_residuals: list[float] = []
    both_fixed_count = 0
    only_master_fixed = 0
    only_slave_fixed = 0
    neither_fixed = 0

    for epoch in epochs:
        computed_heading = heading_from_enu(*epoch.diff_enu[:2])
        computed_pitch = pitch_from_enu(epoch.diff_enu[2], epoch.diff_length_m)
        h_res = None
        p_res = None
        if epoch.receiver_heading_deg is not None:
            h_res = heading_difference(computed_heading, epoch.receiver_heading_deg)
            heading_residuals.append(h_res)
        if epoch.receiver_pitch_deg is not None:
            p_res = computed_pitch - epoch.receiver_pitch_deg
            pitch_residuals.append(p_res)

        if epoch.master_rtk_fixed and epoch.slave_rtk_fixed:
            both_fixed_count += 1
        elif epoch.master_rtk_fixed:
            only_master_fixed += 1
        elif epoch.slave_rtk_fixed:
            only_slave_fixed += 1
        else:
            neither_fixed += 1

        rows.append(
            {
                "epoch": epoch.epoch,
                "master_ecef": list(epoch.master_ecef),
                "slave_ecef": list(epoch.slave_ecef),
                "diff_enu": list(epoch.diff_enu),
                "diff_length_m": epoch.diff_length_m,
                "computed_heading_deg": computed_heading,
                "computed_pitch_deg": computed_pitch,
                "receiver_heading_deg": epoch.receiver_heading_deg,
                "receiver_pitch_deg": epoch.receiver_pitch_deg,
                "heading_residual_deg": h_res,
                "pitch_residual_deg": p_res,
                "master_rtk_fixed": epoch.master_rtk_fixed,
                "slave_rtk_fixed": epoch.slave_rtk_fixed,
            }
        )

    def _rms(values: Sequence[float]) -> float | None:
        if not values:
            return None
        return math.sqrt(sum(v * v for v in values) / len(values))

    def _mean(values: Sequence[float]) -> float | None:
        if not values:
            return None
        return sum(values) / len(values)

    return {
        "matched_epochs": len(rows),
        "fix_state_counts": {
            "both_rtk_fixed": both_fixed_count,
            "only_master_fixed": only_master_fixed,
            "only_slave_fixed": only_slave_fixed,
            "neither_fixed": neither_fixed,
        },
        "epochs": rows,
        "statistics": {
            "diff_length_mean_m": _mean([e.diff_length_m for e in epochs]) if epochs else None,
            "diff_length_std_m": (
                math.sqrt(
                    sum((e.diff_length_m - (sum(ep.diff_length_m for ep in epochs) / len(epochs))) ** 2 for e in epochs)
                    / (len(epochs) - 1)
                )
                if len(epochs) > 1
                else None
            ),
            "heading_residual_mean_deg": _mean(heading_residuals),
            "heading_residual_rms_deg": _rms(heading_residuals),
            "pitch_residual_mean_deg": _mean(pitch_residuals),
            "pitch_residual_rms_deg": _rms(pitch_residuals),
        },
        "limitation": (
            "The master-slave position difference is an independent RTK "
            "baseline estimate, but its accuracy depends on both RTK fixes "
            "and on antenna-specific multipath.  Residuals are relative to "
            "UNIHEADING, not an independent truth."
        ),
    }


def _parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.dual_rtk_consistency",
        description=(
            "Cross-check the dual-RTK master/slave baseline against "
            "UNIHEADING."
        ),
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="live collection time in seconds",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="capture interval in seconds",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    records = capture_records(
        args,
        [Log.BESTNAV, Log.BESTNAVH, Log.UNIHEADING],
        duration=args.duration,
        interval=args.interval,
    )
    master = records.get("BESTNAV", ())
    slave = records.get("BESTNAVH", ())
    if not master or not slave:
        parser.error("need both BESTNAV (master) and BESTNAVH (slave) logs")
    headings = records.get("UNIHEADING", ())
    epochs = _match_epochs(master, slave, headings)
    if not epochs:
        parser.error("no matched master/slave/heading epochs")
    payload = _payload(epochs)
    print(
        f"Matched {payload['matched_epochs']} epochs; "
        f"both fixed: {payload['fix_state_counts']['both_rtk_fixed']}; "
        f"heading residual RMS = "
        f"{payload['statistics']['heading_residual_rms_deg']:.3f} deg",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
