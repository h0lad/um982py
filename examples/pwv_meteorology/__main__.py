# Estimate precipitable water vapour from zenith wet delay.

import math
import sys
from collections.abc import Sequence

from examples._console import (
    ExampleParser,
    add_receiver_arguments,
    debug_header,
    run,
    write_json,
)
from examples._console_capture import capture_records
from examples.pwv_meteorology import (
    Troposphere,
    WaterVapour,
    manual_troposphere,
)
from um982py.commands import Log
from um982py.measurement import receiver_time


def _payload(
    troposphere: Troposphere, mean_temperature: float, source: str
) -> dict[str, object]:
    water = WaterVapour(troposphere=troposphere, mean_temperature=mean_temperature)
    fields = {
        "zenith_total": troposphere.zenith_total,
        "dry": troposphere.dry,
        "wet": troposphere.wet,
        "std": troposphere.std,
    }
    if not all(map(math.isfinite, fields.values())):
        quality = "nonfinite_delay"
    elif troposphere.wet < 0:
        quality = "negative_wet_delay"
    else:
        quality = "converted"
    return {
        "source": source,
        "mean_temperature": mean_temperature,
        "model": str(troposphere.model),
        **{
            key: value if math.isfinite(value) else None
            for key, value in fields.items()
        },
        "delay_quality": quality,
        "pi": water.pi,
        "zwd_to_pwv_ratio": water.zwd_to_pwv_ratio,
        "precipitable_water_mm": water.millimetres if quality == "converted" else None,
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
        help="water vapour weighted mean temperature in kelvin (default: 280 K)",
    )
    parser.add_argument(
        "--frames",
        type=int,
        help="maximum TROPINFO reports (default: one live, all on replay)",
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
    temperature = 280.0 if args.tm is None else args.tm
    if not math.isfinite(temperature) or temperature <= 0:
        parser.error("mean temperature must be finite and positive")
    if args.frames is not None and args.frames < 1:
        parser.error("--frames must be positive")
    debug_header(args, "pwv_meteorology")
    if args.manual:
        source = "manual"
        samples = [_payload(manual_troposphere(), temperature, source)]
    else:
        records = capture_records(
            args,
            [Log.TROPINFO],
            frames=args.frames if args.replay is not None else args.frames or 1,
            duration=args.timeout,
        )["TROPINFO"]
        if not records:
            parser.error(
                "No TROPINFO measurement is available because this log requires "
                "PPP. Use --manual for the published demonstration"
            )
        source = "capture" if args.replay is not None else "receiver"
        samples = []
        for record in records:
            sample = _payload(Troposphere.from_record(record), temperature, source)
            time = receiver_time(record.message)
            sample["gps_seconds"] = time.gps_seconds if time is not None else None
            samples.append(sample)
    converted = sum(sample["delay_quality"] == "converted" for sample in samples)
    payload = {
        **samples[0],
        "mean_temperature_source": "default_assumption"
        if args.tm is None
        else "caller",
        "status": (
            "ok"
            if converted == len(samples)
            else "partial"
            if converted
            else "invalid_delay"
        ),
        "converted_samples": converted,
        "rejected_samples": len(samples) - converted,
        "epochs": samples,
    }
    print(
        f"PWV: converted {converted}/{len(samples)} {source} samples "
        f"at {temperature:g} K",
        file=sys.stderr,
    )
    write_json(payload, args.json)
    return 0 if converted else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
