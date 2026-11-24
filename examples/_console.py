"""Shared command-line parsing, execution and JSON output."""

import argparse
import csv
import json
import math
import os
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, cast, overload

from um982py.commands.configuration import rtk_reliability
from um982py.commands.logging import interval_from_rate
from um982py.errors import UM982Error
from um982py.messages import Record
from um982py.stats import finite

if TYPE_CHECKING:
    from um982py.receiver import Receiver

__all__ = [
    "ExampleParser",
    "add_debug_argument",
    "add_receiver_arguments",
    "add_reliability_arguments",
    "apply_reliability",
    "debug_header",
    "experiment_parser",
    "progress_printer",
    "read_numeric_csv",
    "run",
    "write_json",
]


class ExampleParser(argparse.ArgumentParser):
    """Validate shared capture options before opening a connection."""

    def add_output_interval(
        self, *, default: float = 1.0, help: str = "log output interval in seconds"
    ) -> None:
        """Add alternative second-interval and documented Hertz options."""
        options = self.add_mutually_exclusive_group()
        options.add_argument("--interval", type=float, default=default, help=help)
        options.add_argument(
            "--rate-hz",
            type=float,
            help="requested periodic log output in Hz (1, 2, 5, 10, 20 or 50, "
            "device dependent)",
        )

    @overload
    def parse_args(
        self, args: Iterable[str] | None = None, namespace: None = None
    ) -> argparse.Namespace: ...

    @overload
    def parse_args[N](self, args: Iterable[str] | None, namespace: N) -> N: ...

    @overload
    def parse_args[N](self, *, namespace: N) -> N: ...

    def parse_args(
        self, args: Iterable[str] | None = None, namespace: object | None = None
    ) -> object:
        supplied = list(sys.argv[1:] if args is None else args)
        parsed = super().parse_args(supplied, namespace)
        rate_hz = getattr(parsed, "rate_hz", None)
        if rate_hz is not None:
            try:
                cast(argparse.Namespace, parsed).interval = interval_from_rate(rate_hz)
            except ValueError as error:
                self.error(str(error))
        positive = {
            "baud",
            "duration",
            "seconds",
            "interval",
            "frames",
            "window",
            "frequency",
            "minimum_samples",
            "minimum_satellites",
            "runs",
            "epochs",
            "samples",
            "cadence",
            "period",
            "tm",
            "timeout",
            "timeout_seconds",
            "window_seconds",
            "reboot_seconds",
            "horizontal_tolerance",
            "vertical_tolerance",
            "threshold",
            "max_gap",
            "phase_tolerance",
            "tau",
            "sigma",
            "cell_degrees",
            "minimum_cell_samples",
            "max_age",
            "mask_max_age",
            "agreement",
        }
        for name, value in vars(parsed).items():
            values = value if isinstance(value, (list, tuple)) else (value,)
            for item in values:
                if isinstance(item, float) and not math.isfinite(item):
                    self.error(f"--{name.replace('_', '-')} must be finite")
                if name in positive and isinstance(item, (int, float)) and item <= 0:
                    self.error(f"--{name.replace('_', '-')} must be positive")
                if (
                    name
                    in ("join_tolerance", "sustained_seconds", "position_tolerance")
                    and isinstance(item, (int, float))
                    and item < 0
                ):
                    self.error(f"--{name.replace('_', '-')} must be nonnegative")
            if name in ("mask", "masks", "ceiling") and any(
                not 0 <= item <= 90 for item in values
            ):
                self.error(f"--{name.replace('_', '-')} must be in 0..90 degrees")
        if (
            hasattr(parsed, "min_elevation")
            and hasattr(parsed, "max_elevation")
            and not 0 <= parsed.min_elevation < parsed.max_elevation <= 90
        ):
            self.error("elevation window must satisfy 0 <= minimum < maximum <= 90")
        if getattr(parsed, "replay", None) is not None and any(
            option == "--port" or option.startswith("--port=") for option in supplied
        ):
            self.error("choose --replay or --port for this run")
        recording_path = getattr(parsed, "record", None)
        try:
            validate_file_paths(vars(parsed))
        except ValueError as error:
            self.error(str(error))
        if recording_path is not None:
            if (
                getattr(parsed, "replay", None) is not None
                or getattr(parsed, "transcripts", None) is not None
                or getattr(parsed, "manual", False)
            ):
                self.error("--record requires a live connection")
            if getattr(parsed, "port", None) is None:
                self.error("--record requires --port for a live run")
        return parsed


def add_reliability_arguments(parser: argparse.ArgumentParser) -> None:
    """Add optional RTK and carrier-phase reliability thresholds."""
    parser.add_argument(
        "--rtk-reliability",
        type=int,
        choices=(1, 2, 3, 4),
        help="RTK engine reliability threshold; lower values accept float "
        "solutions sooner (1 low, 3 default, 4 high)",
    )
    parser.add_argument(
        "--adr-reliability",
        type=int,
        choices=(1, 2, 3, 4),
        help="carrier-phase reliability threshold, default 1 when supplied",
    )


def apply_reliability(receiver: "Receiver", args: argparse.Namespace) -> bool:
    """Apply reliability options when at least one was supplied."""
    rtk = getattr(args, "rtk_reliability", None)
    adr = getattr(args, "adr_reliability", None)
    if rtk is None and adr is None:
        return False
    receiver.execute(rtk_reliability(rtk or 3, adr))
    return True


def validate_file_paths(arguments: Mapping[str, object]) -> None:
    """Keep output files distinct from every Path input, including hardlinks.

    File arguments must use ``type=Path``. The explicit output names avoid
    confusing inputs such as ``reference_json`` with destinations.
    """
    output_names = {
        "record",
        "json",
        "csv",
        "geojson",
        "output",
        "plot",
        "markdown",
        "timeline_csv",
        "checks_csv",
        "differences_csv",
        "pairs_csv",
        "elevation_csv",
        "measurements_csv",
        "samples_csv",
        "spectra_csv",
        "secondary_output",
        "survey_output",
    }
    paths = {
        name: tuple(item for item in values if isinstance(item, Path))
        for name, value in arguments.items()
        for values in [value if isinstance(value, (list, tuple)) else (value,)]
    }
    outputs = {name: values for name, values in paths.items() if name in output_names}
    for name, destinations in outputs.items():
        for destination in destinations:
            for other, sources in paths.items():
                if other == name:
                    continue
                for source in sources:
                    if destination.resolve() == source.resolve() or (
                        destination.exists()
                        and source.exists()
                        and destination.samefile(source)
                    ):
                        option = name.replace("_", "-")
                        other_option = other.replace("_", "-")
                        if other in outputs:
                            raise ValueError(
                                f"--{option} and --{other_option} "
                                "need different output paths"
                            )
                        raise ValueError(
                            f"--{option} must not overwrite --{other_option} input"
                        )


def run(main: Callable[[], int]) -> int:
    """Report expected input and receiver failures as concise errors."""
    try:
        return main()
    except (OSError, UM982Error, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except ExceptionGroup as error:
        handled, unexpected = error.split((OSError, UM982Error, ValueError))
        if unexpected is not None:
            raise unexpected from None

        def report(group: BaseException) -> None:
            if isinstance(group, BaseExceptionGroup):
                for failure in group.exceptions:
                    report(failure)
            else:
                print(f"error: {group}", file=sys.stderr)

        if handled is not None:
            report(handled)
        return 2
    except KeyboardInterrupt:
        return 130


def add_receiver_arguments(
    parser: argparse.ArgumentParser, *, antenna: bool = True, replay: bool = True
) -> None:
    """Add connection options and optional antenna, replay and recording options."""
    parser.add_argument(
        "--port", default="/dev/ttyUSB0", help="serial device or tcp://host:port"
    )
    parser.add_argument(
        "--baud", type=int, default=921600, help="serial baud rate, ignored for TCP"
    )
    if antenna:
        parser.add_argument(
            "--antenna",
            choices=("primary", "secondary", "1", "2"),
            default="primary",
            help="select ANT1/primary or ANT2/secondary measurements without "
            "changing RF power. Receiver-wide logs and dual-antenna baselines "
            "retain their documented scope",
        )
        parser.add_argument(
            "--swap-antennas",
            action="store_true",
            help="treat ANT2 as the first antenna and ANT1 as the second, for cabling "
            "or mounting that reverses the two inputs. This applies after "
            "--antenna and does not switch RF power",
        )
    parser.add_argument(
        "--timeout", type=float, default=3.0, help="I/O timeout in seconds"
    )
    parser.add_argument(
        "--augment",
        action="store_true",
        help="enable augmentation, with signal group changes saved by the receiver",
    )
    parser.add_argument(
        "--json", type=Path, default=None, help="write the result as JSON here"
    )
    if replay:
        parser.add_argument(
            "--replay",
            type=Path,
            default=None,
            help="read captured bytes from a file instead of the device",
        )
        parser.add_argument(
            "--record",
            type=Path,
            default=None,
            help="save received wire bytes for replay to a new file",
        )


def write_json(
    payload: object, destination: str | os.PathLike[str] | None = None
) -> None:
    """Serialise to the given file or to stdout by default."""

    def finite(value: object) -> object:
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, Mapping):
            return {key: finite(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [finite(item) for item in value]
        return value

    text = json.dumps(finite(payload), indent=2, default=str, allow_nan=False)
    if destination is None:
        sys.stdout.write(text + "\n")
    else:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")


def add_debug_argument(parser: ExampleParser) -> None:
    """Add the shared --debug flag for live capture updates on stderr."""
    parser.add_argument(
        "--debug",
        action="store_true",
        help="print live capture updates to stderr",
    )


def debug_header(args: argparse.Namespace, name: str) -> None:
    """Print the debug origin line when --debug was given."""
    if not getattr(args, "debug", False):
        return
    replay = getattr(args, "replay", None)
    origin = f"replay {replay}" if replay else f"receiver {getattr(args, 'port', '?')}"
    detail = ""
    if getattr(args, "duration", None) is not None:
        detail += f"; duration={args.duration:g}s"
    if getattr(args, "interval", None) is not None:
        detail += f"; interval={args.interval:g}s"
    print(f"{name} debug: {origin}{detail}", file=sys.stderr, flush=True)


def progress_printer(name: str) -> Callable[[dict[str, tuple[Record, ...]]], None]:
    """Build an on_progress callback that logs record counts to stderr."""
    seen: dict[str, int] = {}

    def progress(captured: dict[str, tuple[Record, ...]]) -> None:
        counts = {log_name: len(rows) for log_name, rows in captured.items()}
        if counts == seen:
            return
        seen.update(counts)
        print(f"{name} debug: records={counts}", file=sys.stderr, flush=True)

    return progress


def experiment_parser(
    name: str, description: str, *, output_rate: bool = True
) -> ExampleParser:
    """Create a parser with bounded receiver capture and optional replay."""
    parser = ExampleParser(prog=f"python -m examples.{name}", description=description)
    add_receiver_arguments(parser)
    parser.add_argument(
        "--duration", type=float, default=30.0, help="live capture seconds"
    )
    if output_rate:
        parser.add_output_interval()
    else:
        parser.add_argument(
            "--interval", type=float, default=1.0, help="interval in seconds"
        )
    return parser


def read_numeric_csv(
    path: str | os.PathLike[str], columns: Sequence[str]
) -> tuple[dict[str, float], ...]:
    """Read named finite numeric columns from an experiment reference file."""
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not set(columns) <= set(reader.fieldnames):
            raise ValueError(f"{path} needs CSV columns {', '.join(columns)}")
        rows = []
        for row in reader:
            try:
                values = {name: float(row[name]) for name in columns}
            except (TypeError, ValueError):
                raise ValueError(
                    f"{path}: invalid numeric CSV row {reader.line_num}"
                ) from None
            finite(*values.values())
            rows.append(values)
    if not rows:
        raise ValueError(f"{path} contains no reference rows")
    return tuple(rows)
