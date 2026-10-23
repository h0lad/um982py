"""Record RINEX observations, download products and run static PPP in Python."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import TypedDict

from examples.offline_ppp.solver import process_observations
from examples.rinex_export.__main__ import main as record_rinex
from um982py.errors import TransportError
from um982py.field_data import file_sha256
from um982py.receiver import Receiver
from um982py.rinex_merge import merge_gps_observations

GPS_ORIGIN = date(1980, 1, 6)
PRODUCT_ROOT = "https://igs.bkg.bund.de/root_ftp/IGS"
CODE_ROOT = "https://igs.bkg.bund.de/root_ftp/IGSac/products"


class CompletedSegment(TypedDict):
    segment: str
    requested_seconds: float
    capture_sha256: str
    observation_sha256: str


def empty_directory(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"output directory must be empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def observation_dates(path: Path) -> tuple[date, ...]:
    dates: set[date] = set()
    gps_time = False
    with path.open(encoding="ascii") as stream:
        for line in stream:
            if line[60:].strip() == "TIME OF FIRST OBS":
                gps_time = line[48:51] == "GPS"
            if line.startswith("> "):
                fields = line[1:].split()
                if len(fields) < 8:
                    raise ValueError("invalid RINEX observation epoch")
                dates.add(date(*(int(value) for value in fields[:3])))
    if not gps_time:
        raise ValueError("RINEX observation time system must explicitly be GPS")
    if not dates:
        raise ValueError("RINEX file has no observation epochs")
    return tuple(sorted(dates))


def product_urls(day: date, quality: str) -> dict[str, str]:
    if quality not in {"final", "rapid"}:
        raise ValueError("product quality must be final or rapid")
    if day < date(2022, 11, 27):
        raise ValueError("the IGS product naming used here starts on 2022-11-27")
    week = (day - GPS_ORIGIN).days // 7
    stamp = day.strftime("%Y%j")
    kind = "FIN" if quality == "final" else "RAP"
    prefix = f"COD0OPS{kind}_{stamp}0000_01D"
    return {
        f"{stamp}.sp3": f"{CODE_ROOT}/{week}/{prefix}_05M_ORB.SP3.gz",
        f"{stamp}.clk": f"{CODE_ROOT}/{week}/{prefix}_30S_CLK.CLK.gz",
        f"{stamp}.bia": f"{CODE_ROOT}/{week}/{prefix}_01D_OSB.BIA.gz",
        f"{stamp}.nav": (
            f"{PRODUCT_ROOT}/BRDC/{day.year}/{day.timetuple().tm_yday:03d}/"
            f"BRDC00IGS_R_{stamp}0000_01D_MN.rnx.gz"
        ),
    }


def download_product(url: str, path: Path) -> None:
    """Download and decompress an archive with bounded transient retries."""
    request = urllib.request.Request(url, headers={"User-Agent": "um982py"})  # noqa: S310
    for attempt in range(3):
        try:
            with (
                urllib.request.urlopen(request, timeout=60) as response,  # noqa: S310
                gzip.GzipFile(fileobj=response) as compressed,
                path.open("wb") as output,
            ):
                shutil.copyfileobj(compressed, output)
            if path.stat().st_size == 0:
                raise ValueError(f"empty product: {url}")
            return
        except urllib.error.HTTPError as error:
            if attempt == 2 or (error.code not in (408, 429) and error.code < 500):
                raise
        except (OSError, EOFError):
            if attempt == 2:
                raise
        time.sleep(0.5 * 2**attempt)


def download_products(
    observation: Path, destination: Path, quality: str, adjacent_days: int = 1
) -> None:
    if adjacent_days not in (0, 1):
        raise ValueError("adjacent days must be 0 or 1")
    observed_days = observation_dates(observation)
    days = sorted(
        {
            day + timedelta(days=offset)
            for day in observed_days
            for offset in range(-adjacent_days, adjacent_days + 1)
        }
    )
    for day in days:
        product_urls(day, quality)
    empty_directory(destination)
    products: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="um982-ppp-", dir=destination) as temp:
        staged = Path(temp)
        for day in days:
            for name, url in product_urls(day, quality).items():
                print(f"Downloading {url}", file=sys.stderr, flush=True)
                path = staged / name
                download_product(url, path)
                products.append({"path": name, "url": url, "sha256": file_sha256(path)})
        for product in products:
            (staged / product["path"]).replace(destination / product["path"])
    (destination / "products.json").write_text(
        json.dumps(
            {
                "quality": quality,
                "gps_dates": [d.isoformat() for d in days],
                "files": products,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def antenna_type(observation: Path) -> str:
    with observation.open(encoding="ascii") as stream:
        for line in stream:
            if line[60:].strip() == "ANT # / TYPE":
                return line[20:40].strip()
            if line[60:].strip() == "END OF HEADER":
                break
    return ""


def phase_alignment_status(observation: Path) -> str:
    """Report the GPS RINEX header's declaration without validating it."""
    declarations = []
    with observation.open(encoding="ascii") as stream:
        for line in stream:
            label = line[60:].strip()
            if label == "SYS / PHASE SHIFT" and line[:1] == "G":
                declarations.append(line[1:60].strip())
            if label == "END OF HEADER":
                break
    if not declarations:
        return "missing"
    if any(not value for value in declarations):
        return "unknown"
    return "declared_unverified"


def recording_options(
    args: argparse.Namespace, output: Path, duration: float
) -> list[str]:
    """Build the existing exporter options for a bounded recording."""
    options = [
        "--port",
        args.port,
        "--baud",
        str(args.baud),
        "--duration",
        str(duration),
        "--interval",
        str(args.interval),
        "--frames",
        str(math.ceil(duration / args.interval) + 1),
        "--output",
        str(output / "observation.obs"),
        "--record",
        str(output / "capture.bin"),
        "--json",
        str(output / "capture.json"),
        "--marker-name",
        args.marker_name,
    ]
    if args.metadata:
        options += ["--metadata", str(args.metadata)]
    if args.l2c_code:
        options += ["--l2c-code", args.l2c_code]
    return options


def record_segments(args: argparse.Namespace) -> int:
    """Record independent segments with a durable, resumable journal."""
    try:
        import fcntl
    except ImportError as error:
        raise ValueError("segmented recording requires POSIX file locking") from error
    if not args.resume:
        empty_directory(args.output_dir)
    elif not args.output_dir.is_dir():
        raise ValueError("resume requires an existing segmented session")
    with (args.output_dir / ".session.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another process owns the segmented session") from error
        return _record_segments_locked(args)


def receiver_identity(args: argparse.Namespace) -> dict[str, str]:
    """Read a receiver identity and configuration fingerprint without changing it."""
    with Receiver.connect(args.port, args.baud, timeout=3) as receiver:
        version = receiver.version()
        configuration = receiver.configuration()
    if not version.model or not version.serial_number:
        raise ValueError("receiver identity is incomplete")
    entries = json.dumps(sorted(configuration.entries), ensure_ascii=True).encode(
        "ascii"
    )
    return {
        "model": version.model,
        "firmware": version.software,
        "serial_sha256": hashlib.sha256(
            version.serial_number.encode("utf-8")
        ).hexdigest(),
        "configuration_sha256": hashlib.sha256(entries).hexdigest(),
    }


def _record_segments_locked(args: argparse.Namespace) -> int:
    directory = args.output_dir
    manifest = directory / "session.json"
    config = {
        "schema": "um982py-offline-ppp-segments-1",
        "port": args.port,
        "baud": args.baud,
        "interval": args.interval,
        "duration": args.duration,
        "segment_seconds": args.segment_seconds,
        "marker_name": args.marker_name,
        "l2c_code": args.l2c_code,
        "metadata_sha256": file_sha256(args.metadata) if args.metadata else None,
    }
    if args.resume:
        if not manifest.is_file():
            raise ValueError("resume requires an existing segmented session")
        if json.loads(manifest.read_text(encoding="utf-8")) != config:
            raise ValueError("recording settings differ from the existing session")
    else:
        with manifest.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(config, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    journal = directory / "segments.jsonl"
    completed = sum(item["requested_seconds"] for item in completed_segments(directory))
    identity_path = directory / "receiver.json"
    expected_identity = (
        json.loads(identity_path.read_text(encoding="utf-8"))
        if identity_path.exists()
        else None
    )
    if completed and expected_identity is None:
        raise ValueError("completed session has no receiver identity; inspect the data")

    def event(data: dict[str, object]) -> None:
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(data, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    failures = 0
    retry_delay = args.retry_seconds
    while completed < args.duration:
        free = shutil.disk_usage(directory).free
        if free < args.min_free_mib * 1048576:
            raise ValueError("insufficient free disk space for the next segment")
        try:
            identity = receiver_identity(args)
        except (OSError, TransportError) as error:
            failures += 1
            event(
                {"status": "receiver_retry", "attempt": failures, "error": str(error)}
            )
            if failures > args.max_retries:
                raise
            time.sleep(retry_delay)
            retry_delay = min(args.retry_max_seconds, retry_delay * 2)
            continue
        if expected_identity is None:
            with identity_path.open("x", encoding="utf-8") as stream:
                json.dump(identity, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            expected_identity = identity
        elif identity != expected_identity:
            raise ValueError(
                "receiver identity or configuration changed; inspect the session"
            )
        number = 1
        while (directory / f"segment-{number:06d}").exists():
            number += 1
        segment = directory / f"segment-{number:06d}"
        segment.mkdir()
        remaining = args.duration - completed
        duration = (
            remaining
            if remaining <= args.segment_seconds + 2 * args.interval
            else args.segment_seconds
        )
        event(
            {
                "segment": segment.name,
                "status": "started",
                "requested_seconds": duration,
            }
        )
        try:
            result = record_rinex(recording_options(args, segment, duration))
            report = json.loads((segment / "capture.json").read_text(encoding="utf-8"))
            file_info = report["files"][0]
            span = (
                file_info["last_epoch_gps_seconds"]
                - file_info["first_epoch_gps_seconds"]
            )
            tolerance = max(2 * args.interval, 2.0)
            if result != 0 or span < max(0.0, duration - tolerance):
                event(
                    {
                        "segment": segment.name,
                        "status": "incomplete",
                        "span_seconds": span,
                    }
                )
                return 1
            if receiver_identity(args) != expected_identity:
                raise ValueError(
                    "receiver identity or configuration changed during segment"
                )
        except (OSError, TransportError) as error:
            failures += 1
            event({"segment": segment.name, "status": "failed", "error": str(error)})
            if failures > args.max_retries:
                raise
            time.sleep(retry_delay)
            retry_delay = min(args.retry_max_seconds, retry_delay * 2)
            continue
        except BaseException as error:
            event({"segment": segment.name, "status": "failed", "error": str(error)})
            raise
        event(
            {
                "segment": segment.name,
                "status": "complete",
                "requested_seconds": duration,
                "span_seconds": span,
                "capture_sha256": file_sha256(segment / "capture.bin"),
                "observation_sha256": file_sha256(segment / "observation.obs"),
            }
        )
        completed += duration
        failures = 0
        retry_delay = args.retry_seconds
    return 0


def completed_segments(directory: Path) -> list[CompletedSegment]:
    """Read and verify completed segment entries from a session journal."""
    journal = directory / "segments.jsonl"
    if not journal.exists():
        return []
    completed: list[CompletedSegment] = []
    seen: set[str] = set()
    with journal.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.endswith("\n"):
                raise ValueError(
                    "incomplete journal entry; preserve and inspect session"
                )
            item = json.loads(line)
            if item.get("status") != "complete":
                continue
            name = item["segment"]
            if (
                not isinstance(name, str)
                or not name.startswith("segment-")
                or len(name) != 14
                or not name[8:].isdigit()
                or name in seen
            ):
                raise ValueError("invalid or duplicate completed segment")
            seen.add(name)
            segment = directory / name
            if (
                file_sha256(segment / "capture.bin") != item["capture_sha256"]
                or file_sha256(segment / "observation.obs")
                != item["observation_sha256"]
            ):
                raise ValueError("completed segment hash mismatch")
            seconds = float(item["requested_seconds"])
            if not math.isfinite(seconds) or seconds <= 0:
                raise ValueError("invalid completed segment duration")
            completed.append(
                {
                    "segment": name,
                    "requested_seconds": seconds,
                    "capture_sha256": item["capture_sha256"],
                    "observation_sha256": item["observation_sha256"],
                }
            )
    return completed


def merge_segments(session: Path, output: Path) -> None:
    """Merge completed, verified segments into a single GPS-only RINEX file."""
    if not (session / "session.json").is_file():
        raise ValueError("not a segmented offline PPP session")
    configuration = json.loads((session / "session.json").read_text(encoding="utf-8"))
    if configuration.get("schema") != "um982py-offline-ppp-segments-1":
        raise ValueError("unsupported segmented session schema")
    report_path = output.with_name(output.name + ".json")
    if output.exists() or report_path.exists():
        raise ValueError("merge output and report must not already exist")
    entries = completed_segments(session)
    if not entries:
        raise ValueError("session has no complete segments")
    paths = [session / str(item["segment"]) / "observation.obs" for item in entries]
    result = merge_gps_observations(paths, output)
    report = {
        "schema": "um982py-offline-ppp-merge-1",
        "inputs": [{"path": str(path), "sha256": file_sha256(path)} for path in paths],
        "session_sha256": file_sha256(session / "session.json"),
        "journal_sha256": file_sha256(session / "segments.jsonl"),
        "receiver_sha256": file_sha256(session / "receiver.json")
        if (session / "receiver.json").is_file()
        else None,
        "output_sha256": file_sha256(output),
        **asdict(result),
        "limitations": [
            "GPS observations only",
            "phase alignment remains unknown",
            "carrier arcs reset at segment boundaries",
        ],
    }
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")


def verify_antenna(observation: Path, antex: Path) -> str:
    name = antenna_type(observation)
    if not name:
        raise ValueError(
            "RINEX antenna type is missing; supply it in recording metadata"
        )
    offset = None
    with observation.open(encoding="ascii") as stream:
        for line in stream:
            label = line[60:].strip()
            if label == "COMMENT" and "Antenna delta unknown" in line[:60]:
                raise ValueError("antenna offset is unknown; supply measured H/E/N")
            if label == "ANTENNA: DELTA H/E/N":
                offset = [float(line[i : i + 14]) for i in (0, 14, 28)]
            if label == "END OF HEADER":
                break
    if offset is None or not all(math.isfinite(value) for value in offset):
        raise ValueError("RINEX needs a finite antenna offset H/E/N")
    with antex.open(encoding="ascii") as stream:
        if not any(
            line[60:].strip() == "TYPE / SERIAL NO" and line[:20].strip() == name
            for line in stream
        ):
            raise ValueError(f"antenna {name!r} was not found in the ANTEX file")
    return name


def solve(observation: Path, products: Path, antex: Path, output: Path) -> int:
    days = observation_dates(observation)
    name = verify_antenna(observation, antex)
    manifest = json.loads((products / "products.json").read_text(encoding="utf-8"))
    if not {d.isoformat() for d in days} <= set(manifest["gps_dates"]):
        raise ValueError("products do not cover all GPS dates in the observation file")
    paths = []
    for item in manifest["files"]:
        filename = item["path"]
        if Path(filename).name != filename:
            raise ValueError("invalid product manifest path")
        path = products / filename
        if file_sha256(path) != item["sha256"]:
            raise ValueError(f"product hash mismatch: {path}")
        paths.append(path.resolve())
    for day in days:
        stem = day.strftime("%Y%j")
        if not all(
            any(path.name == f"{stem}.{ext}" for path in paths)
            for ext in ("sp3", "clk", "nav", "bia")
        ):
            raise ValueError(
                f"missing orbit, clock, bias or navigation product for {day}"
            )
    empty_directory(output)
    result = process_observations(observation, paths, antex, output)
    report = {
        **result,
        "observation_sha256": file_sha256(observation),
        "antex_sha256": file_sha256(antex),
        "antenna_type": name,
        "gps_phase_alignment": phase_alignment_status(observation),
        "products": manifest,
        "limitations": [
            "A float PPP output does not prove convergence or accuracy",
            "Antenna calibration validity, phase alignment and reference point "
            "are not independently verified",
            "Product coverage and data quality must be independently inspected",
        ],
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if report["status"] == "ppp_output" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    record = sub.add_parser("record", help="record raw observations and export RINEX")
    record.add_argument("--port", required=True)
    record.add_argument("--baud", type=int, default=921600)
    record.add_argument(
        "--duration",
        type=float,
        required=True,
        help="stationary observation time in seconds",
    )
    record.add_argument("--interval", type=float, default=5.0)
    record.add_argument("--output-dir", type=Path, required=True)
    record.add_argument(
        "--metadata", type=Path, help="RinexMetadata JSON with measured antenna details"
    )
    record.add_argument("--marker-name", default="UM982")
    record.add_argument("--segment-seconds", type=float, help="record bounded segments")
    record.add_argument(
        "--resume", action="store_true", help="resume a segmented session"
    )
    record.add_argument("--min-free-mib", type=float, default=512)
    record.add_argument("--max-retries", type=int, default=3)
    record.add_argument("--retry-seconds", type=float, default=1)
    record.add_argument("--retry-max-seconds", type=float, default=30)
    record.add_argument(
        "--l2c-code",
        choices=("2S", "2L", "2X"),
        help="L2C RINEX code only when independently established for the receiver",
    )
    download = sub.add_parser(
        "download", help="download CODE orbit, clock, bias and navigation products"
    )
    download.add_argument("--observation", type=Path, required=True)
    download.add_argument("--output-dir", type=Path, required=True)
    download.add_argument("--quality", choices=("final", "rapid"), default="rapid")
    download.add_argument(
        "--adjacent-days",
        type=int,
        choices=(0, 1),
        default=1,
        help="include the day before and after for interpolation (default: 1)",
    )
    merge = sub.add_parser("merge", help="merge completed segments into GPS RINEX")
    merge.add_argument("--session", type=Path, required=True)
    merge.add_argument("--output", type=Path, required=True)
    process = sub.add_parser(
        "solve", help="process observations using Python static PPP"
    )
    process.add_argument("--observation", type=Path, required=True)
    process.add_argument("--products", type=Path, required=True)
    process.add_argument("--antex", type=Path, required=True)
    process.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "record":
            if (
                not math.isfinite(args.duration)
                or not math.isfinite(args.interval)
                or args.duration <= 0
                or args.interval <= 0
            ):
                raise ValueError("duration and interval must be finite and positive")
            if args.segment_seconds is not None:
                if (
                    not math.isfinite(args.segment_seconds)
                    or args.segment_seconds < 2 * args.interval
                    or args.duration < 2 * args.interval
                    or not math.isfinite(args.min_free_mib)
                    or args.min_free_mib < 0
                    or args.max_retries < 0
                    or not math.isfinite(args.retry_seconds)
                    or not math.isfinite(args.retry_max_seconds)
                    or not 0 < args.retry_seconds <= args.retry_max_seconds
                ):
                    raise ValueError(
                        "segment duration must cover two intervals and "
                        "free space must be non-negative"
                    )
                return record_segments(args)
            if args.resume:
                raise ValueError("resume requires --segment-seconds")
            empty_directory(args.output_dir)
            return record_rinex(recording_options(args, args.output_dir, args.duration))
        if args.action == "download":
            download_products(
                args.observation, args.output_dir, args.quality, args.adjacent_days
            )
            return 0
        if args.action == "merge":
            merge_segments(args.session, args.output)
            return 0
        return solve(args.observation, args.products, args.antex, args.output_dir)
    except (
        OSError,
        EOFError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ) as error:
        print(f"offline_ppp: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
