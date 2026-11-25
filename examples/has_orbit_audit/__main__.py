# Score broadcast and HAS-corrected GPS and Galileo states against SP3.

import hashlib
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, replace
from pathlib import Path

from examples._console import (
    add_debug_argument,
    debug_header,
    experiment_parser,
    progress_printer,
    run,
    write_json,
)
from examples._console_capture import capture_logs
from examples.broadcast_orbit_audit import OrbitDifference, compare_state, sisre_summary
from examples.has_orbit_audit import (
    HAS_SYSTEMS,
    SISRE_WEIGHTS,
    BroadcastState,
    apc_reference,
    apply_has,
    broadcast_state,
    clock_aligned,
    correction_timeline,
    ephemeris_identity,
    has_key,
    snapshot_at,
    usable_ephemeris,
)
from um982py.commands import Log
from um982py.measurement import gps_epoch
from um982py.messages import Record
from um982py.precise import parse_sp3

_HAS_LOGS = (Log.E6MASKBLOCK, Log.E6ORBITBLOCK, Log.E6CLOCKFULLBLOCK)
_EPHEMERIS_AGE = 4 * 3600.0
"""Receipt age beyond which a repeated issue number is not trusted (s)."""


def _ephemeris(
    history: Sequence[tuple[float, Record]], issue: int, epoch: float
) -> BroadcastState | None:
    """The latest received ephemeris of the corrected issue, propagated."""
    for received, record in reversed(history):
        if received <= epoch and ephemeris_identity(record)[1] == issue:
            return (
                broadcast_state(record, epoch)
                if epoch - received <= _EPHEMERIS_AGE
                else None
            )
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Compare broadcast and HAS-corrected states at the SP3 epochs."""
    parser = experiment_parser(
        "has_orbit_audit",
        "Galileo HAS orbit and clock correction audit",
        output_rate=False,
    )
    parser.add_argument(
        "--sp3",
        type=Path,
        required=True,
        help="final or rapid SP3-c/d product explicitly in GPS time",
    )
    parser.add_argument(
        "--systems",
        default="GE",
        help="system letters to audit: G for GPS, E for Galileo (default GE)",
    )
    parser.add_argument(
        "--pco-z",
        type=float,
        default=0.0,
        help="satellite ionosphere-free nadir phase-centre offset in metres, "
        "moving the SP3 centre of mass to the HAS reference point",
    )
    add_debug_argument(parser)
    args = parser.parse_args(argv)
    systems = set(args.systems.upper())
    if not systems or not systems <= set(HAS_SYSTEMS.values()):
        parser.error("--systems accepts only G and E")
    debug_header(args, "has_orbit_audit")
    sp3 = args.sp3.read_bytes()
    product = parse_sp3(sp3.decode("ascii"))
    arrival: list[Record] = []
    data = capture_logs(
        args,
        [Log.GPSEPH, Log.GALEPH, *_HAS_LOGS],
        arrival_order=arrival,
        on_progress=progress_printer("has_orbit_audit") if args.debug else None,
    )
    snapshots = correction_timeline(
        record for record in arrival if record.name in {log.value for log in _HAS_LOGS}
    )
    history: dict[str, list[tuple[float, Record]]] = defaultdict(list)
    for record in (*data["GPSEPH"], *data["GALEPH"]):
        if usable_ephemeris(record):
            satellite = ephemeris_identity(record)[0]
            history[satellite].append((gps_epoch(record), record))
    for entries in history.values():
        entries.sort(key=lambda entry: entry[0])
    pairs: dict[float, dict[str, tuple[OrbitDifference, OrbitDifference]]] = (
        defaultdict(dict)
    )
    skipped: dict[str, int] = defaultdict(int)
    for point in product.points:
        letter = point.satellite[0]
        if letter not in systems:
            continue
        if point.predicted_orbit or point.clock_seconds is None:
            skipped["predicted_or_clockless_reference"] += 1
            continue
        snapshot = snapshot_at(snapshots, point.epoch)
        if snapshot is None:
            skipped["no_valid_has_correction"] += 1
            continue
        correction = snapshot.corrections.get(has_key(point.satellite))
        if correction is None or correction.navigation_message != 0:
            skipped["satellite_not_corrected"] += 1
            continue
        state = _ephemeris(history[point.satellite], correction.iod_ref, point.epoch)
        if state is None:
            skipped["no_ephemeris_for_iod_ref"] += 1
            continue
        corrected = apply_has(state, correction)
        if corrected is None:
            skipped["correction_unavailable"] += 1
            continue
        reference = apc_reference(point.position, args.pco_z)
        rows = tuple(
            compare_state(
                point.satellite,
                point.epoch,
                position,
                reference,
                state.velocity,
                broadcast_clock=clock,
                reference_clock=point.clock_seconds,
            )
            for position, clock in (
                (state.position, state.clock_seconds),
                corrected,
            )
        )
        pairs[point.epoch][point.satellite] = rows[0], rows[1]
    results: dict[str, dict[str, list[OrbitDifference]]] = {
        letter: {"broadcast": [], "has": []} for letter in sorted(systems)
    }
    for epoch_pairs in pairs.values():
        for letter in systems:
            selected = {
                satellite: rows
                for satellite, rows in epoch_pairs.items()
                if satellite[0] == letter
            }
            for index, service in enumerate(("broadcast", "has")):
                clocks = {
                    satellite: rows[index].clock_difference_seconds or 0.0
                    for satellite, rows in selected.items()
                }
                aligned = clock_aligned(clocks)
                if not aligned:
                    skipped["epoch_with_fewer_than_four_satellites"] += len(clocks)
                results[letter][service].extend(
                    replace(selected[satellite][index], clock_difference_seconds=value)
                    for satellite, value in aligned.items()
                )
    summary = {
        letter: {
            service: asdict(
                sisre_summary(
                    rows,
                    radial_weight=SISRE_WEIGHTS[letter][0],
                    angular_weight=SISRE_WEIGHTS[letter][1],
                )
            )
            for service, rows in services.items()
        }
        for letter, services in results.items()
    }
    per_satellite: dict[str, dict[str, object]] = {}
    for letter, services in results.items():
        weights = SISRE_WEIGHTS[letter]
        for satellite in sorted({row.satellite for row in services["has"]}):
            per_satellite[satellite] = {
                service: asdict(
                    sisre_summary(
                        [row for row in rows if row.satellite == satellite],
                        radial_weight=weights[0],
                        angular_weight=weights[1],
                    )
                )
                for service, rows in services.items()
            }
    compared = sum(len(services["has"]) for services in results.values())
    write_json(
        {
            "status": "ok" if compared else "insufficient_overlap",
            "reference": str(args.sp3),
            "reference_sha256": hashlib.sha256(sp3).hexdigest(),
            "reference_agency": product.agency,
            "reference_frame": product.coordinate_system,
            "pco_z_m": args.pco_z,
            "has_snapshots": len(snapshots),
            "sisre_m": summary,
            "satellites": per_satellite,
            "skipped": dict(skipped),
            "limitation": (
                "SP3 clocks use the IGS ionosphere-free signal pair, so Galileo "
                "E1/E5a products keep an E5a/E5b group-delay difference against "
                "the I/NAV clock that HAS corrects; per-epoch median clock "
                "alignment removes only the common datum"
            ),
        },
        args.json,
    )
    for letter, scores in summary.items():
        broadcast, has = scores["broadcast"], scores["has"]
        if has["samples"]:
            print(
                f"HAS {letter}: SISRE RMS broadcast {broadcast['rms_m']:.3f} m, "
                f"HAS {has['rms_m']:.3f} m over {has['samples']} samples",
                file=sys.stderr,
            )
        else:
            print(f"HAS {letter}: no comparable samples", file=sys.stderr)
    return 0 if compared else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
