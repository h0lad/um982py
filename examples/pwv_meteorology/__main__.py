"""Runs the precipitable water vapour example from the command line."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from examples.pwv_meteorology import (
    Troposphere,
    WaterVapour,
    manual_troposphere,
)
from um982py.capture import capture_records
from um982py.commands import Command, Log, Trigger, logging
from um982py.console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from um982py.messages import Record

_QUERY_TIMEOUT = 2.0


def _wait_command() -> Command[Record]:
    """Wait for one TROPINFO frame after subscribing to its ONCHANGED output."""
    subscribe = Log.TROPINFO.output(Trigger.ON_CHANGED)
    return Command(
        text=subscribe.text,
        matches=logging.request(Log.TROPINFO.wire_name()).matches,
        decode=Log.TROPINFO.decode,
    )


def _payload(
    troposphere: Troposphere, mean_temperature: float, source: str
) -> dict[str, object]:
    """Serialise one precipitable water vapour estimate."""
    water = WaterVapour(troposphere=troposphere, mean_temperature=mean_temperature)
    return {
        "source": source,
        "mean_temperature": mean_temperature,
        "model": str(troposphere.model),
        "zenith_total": troposphere.zenith_total,
        "dry": troposphere.dry,
        "wet": troposphere.wet,
        "std": troposphere.std,
        "pi": water.pi,
        "zwd_to_pwv_ratio": water.zwd_to_pwv_ratio,
        "precipitable_water_mm": water.millimetres,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Convert a TROPINFO zenith wet delay into precipitable water vapour."""
    parser = ExampleParser(
        prog="python -m examples.pwv_meteorology",
        description="Convert the TROPINFO zenith wet delay into water vapour.",
    )
    add_receiver_arguments(parser)
    parser.add_argument(
        "--tm",
        type=float,
        default=280.0,
        help="water vapour weighted mean temperature in kelvin",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help="use the published manual example, not a receiver measurement",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )
    args = parser.parse_args(argv)
    debug_header(args, "pwv_meteorology")
    if args.manual:
        troposphere = manual_troposphere()
        source = "manual"
    else:
        records = capture_records(
            args, [Log.TROPINFO], frames=1, duration=args.timeout
        )["TROPINFO"]
        if not records:
            parser.error(
                "No TROPINFO measurement is available because this log requires "
                "PPP. Use --manual for the published demonstration"
            )
        troposphere = Troposphere.from_record(records[0])
        source = "capture" if args.replay is not None else "receiver"
    payload = _payload(troposphere, args.tm, source)
    print(
        f"PWV: {payload['precipitable_water_mm']:.2f} mm ({source}; "
        f"zenith wet {payload['wet']:.4f} m)",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
