"""Report GPS dual-frequency code TEC and tracking changes together."""

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from statistics import stdev

from examples.ionosphere_tec import Observation, slant_tec
from um982py.capture import capture_records, gps_signals, record_epoch
from um982py.commands import Log
from um982py.console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import FirmwareLog
from um982py.messages import Record
from um982py.observation_quality import audit_observations


def main(argv: Sequence[str] | None = None) -> int:
    parser = ExampleParser(description=__doc__)
    add_receiver_arguments(parser)
    parser.add_argument("--duration", type=float, default=300)
    parser.add_argument("--interval", type=float, default=1)
    parser.add_argument(
        "--low-frequency",
        type=float,
        choices=(1227600000, 1176450000),
        default=1176450000,
    )
    parser.add_argument("--max-gap-s", type=float, default=2)
    parser.add_argument("--roti-window-s", type=float, default=300)
    parser.add_argument(
        "--min-roti-coverage",
        type=float,
        default=1.0,
        help="minimum window fraction covered by continuous rate intervals",
    )
    parser.add_argument(
        "--min-roti-samples",
        type=int,
        default=5,
        help="minimum rate samples required for ROTI, at least two",
    )
    args = parser.parse_args(argv)
    if (
        not math.isfinite(args.max_gap_s)
        or not math.isfinite(args.roti_window_s)
        or args.max_gap_s <= 0
        or args.roti_window_s <= 0
        or not math.isfinite(args.min_roti_coverage)
        or not 0 < args.min_roti_coverage <= 1
        or args.min_roti_samples < 2
    ):
        parser.error(
            "gap and window must be positive, coverage in (0, 1], and samples >= 2"
        )
    paths = [p for p in (args.replay, args.record, args.json) if p is not None]
    if len({p.resolve() for p in paths}) != len(paths):
        parser.error("input, recording and report paths must be distinct")
    captured = capture_records(
        args,
        [FirmwareLog.RANGE, Log.BESTNAV, Log.JAMSTATUS],
        duration=args.duration,
        interval=args.interval,
    )
    previous: dict[int, tuple[float, float, float, float, int, int]] = {}
    rates: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
    timeline = []
    previous_record_epoch = None
    for record in captured["RANGE"]:
        epoch = record_epoch(record)
        if not math.isfinite(epoch) or (
            previous_record_epoch is not None and epoch <= previous_record_epoch
        ):
            raise ValueError("RANGE epochs must be finite and strictly increasing")
        previous_record_epoch = epoch
        by_prn: dict[int, dict[float, Record]] = defaultdict(dict)
        for row, frequency in gps_signals(record, (1575420000, args.low_frequency)):
            by_prn[row.integer("prn")][frequency] = row
        for prn in set(previous):
            if len(by_prn.get(prn, {})) != 2:
                previous.pop(prn)
                rates.pop(prn, None)
        for prn, pair in sorted(by_prn.items()):
            if len(pair) != 2:
                continue
            high, low = pair[1575420000], pair[args.low_frequency]
            if any(
                not math.isfinite(row.real("pseudorange"))
                or row.real("pseudorange") <= 0
                or not math.isfinite(row.real("lock_time"))
                or row.real("lock_time") < 0
                for row in (high, low)
            ):
                previous.pop(prn, None)
                rates[prn].clear()
                continue
            values = [
                Observation(prn, f, r.real("pseudorange"), r.real("carrier_phase"))
                for f, r in ((1575420000, high), (args.low_frequency, low))
            ]
            tec = slant_tec(values)
            if tec is None or not math.isfinite(tec):
                previous.pop(prn, None)
                rates.pop(prn, None)
                continue
            high_lock, low_lock = high.real("lock_time"), low.real("lock_time")
            high_signal = high.integer("tracking_status") & 0x07E00000
            low_signal = low.integer("tracking_status") & 0x07E00000
            before = previous.get(prn)
            rot = None
            if (
                before is not None
                and 0 < epoch - before[0] <= args.max_gap_s
                and high_lock >= before[2]
                and low_lock >= before[3]
                and high_signal == before[4]
                and low_signal == before[5]
            ):
                rot = (tec - before[1]) * 60 / (epoch - before[0])
                rates[prn].append((before[0], epoch, rot))
            else:
                rates[prn].clear()
            window_start = epoch - args.roti_window_s
            rates[prn] = [
                (start, end, x) for start, end, x in rates[prn] if end > window_start
            ]
            covered_s = math.fsum(
                end - max(start, window_start) for start, end, _ in rates[prn]
            )
            coverage = min(1.0, covered_s / args.roti_window_s)
            roti = (
                stdev(x for _, _, x in rates[prn])
                if len(rates[prn]) >= args.min_roti_samples
                and coverage + 1e-12 >= args.min_roti_coverage
                else None
            )
            timeline.append(
                {
                    "gps_seconds": epoch,
                    "prn": prn,
                    "code_slant_tec_proxy_tecu": tec,
                    "code_rot_tecu_per_min": rot,
                    "code_roti_tecu_per_min": roti,
                    "roti_rate_samples": len(rates[prn]),
                    "roti_window_covered_seconds": covered_s,
                    "roti_window_coverage": coverage,
                    "cn0_high_dbhz": high.real("cn0"),
                    "cn0_low_dbhz": low.real("cn0"),
                    "lock_high_s": high_lock,
                    "lock_low_s": low_lock,
                    "high_tracking_signal_bits": high_signal,
                    "low_tracking_signal_bits": low_signal,
                }
            )
            previous[prn] = (epoch, tec, high_lock, low_lock, high_signal, low_signal)
    solution = [
        {
            "gps_seconds": record_epoch(r),
            "solution_status": r["p_sol_status"],
            "position_type": r["pos_type"],
        }
        for r in captured["BESTNAV"]
    ]
    quality = audit_observations(captured["RANGE"]) if captured["RANGE"] else None
    write_json(
        {
            "status": "ok" if timeline else "no_dual_frequency_gps",
            "signals_hz": [1575420000, args.low_frequency],
            "roti_window_seconds": args.roti_window_s,
            "min_roti_coverage": args.min_roti_coverage,
            "min_roti_samples": args.min_roti_samples,
            "timeline": timeline,
            "solution_events": solution,
            "jamming_log_count": len(captured["JAMSTATUS"]),
            "jamming_events": [
                {
                    "gps_seconds": record_epoch(row),
                    "cwratio": row["cwratio"],
                    "cwflag": row["cwflag"],
                }
                for row in captured["JAMSTATUS"]
            ],
            "tracking_quality": asdict(quality) if quality else None,
            "limitations": (
                "Code TEC includes instrumental biases and multipath, while ROTI is "
                "code-based and is not a calibrated scintillation index. Lock "
                "continuity does not prove absence of slips. Signal selection "
                "can change within a frequency. Coverage measures the duration "
                "of accepted rate intervals, not the number of expected samples."
            ),
        },
        args.json,
    )
    return 0 if timeline else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
