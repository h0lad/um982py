"""Summarize station journal events and verify recorded artifact hashes."""

import argparse
import itertools
import json
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from um982py.field_data import file_sha256


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, help="optional readable summary")
    parser.add_argument("--date", type=date.fromisoformat, help="UTC date, YYYY-MM-DD")
    args = parser.parse_args(argv)
    root = args.directory.resolve()
    journal = root / "station.jsonl"
    if not journal.is_file():
        raise ValueError("station journal does not exist")
    if args.output.resolve().is_relative_to(root):
        parser.error("put the report outside the station directory")
    if args.markdown is not None and (
        args.markdown.resolve().is_relative_to(root)
        or args.markdown.resolve() == args.output.resolve()
    ):
        parser.error("put distinct reports outside the station directory")
    events = []
    with journal.open(encoding="utf-8") as file:
        for number, line in enumerate(file, 1):
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid journal line {number}") from exc
            if not isinstance(event, dict):
                raise ValueError(f"invalid event on journal line {number}")
            events.append(event)
    by_segment: dict[str, list[dict[str, object]]] = {}
    for event in events:
        name = event.get("segment")
        if isinstance(name, str):
            if not name.startswith("segment-") or not name[8:].isdigit():
                raise ValueError("invalid segment name in journal")
            by_segment.setdefault(name, []).append(event)
    segments: list[dict[str, Any]] = []
    for name, entries in sorted(by_segment.items()):
        directory = (root / name).resolve()
        if not directory.is_relative_to(root):
            raise ValueError("segment is outside station directory")
        start = next(
            (item for item in entries if item.get("status") == "started"), None
        )
        finish = next(
            (
                item
                for item in reversed(entries)
                if item.get("status") in ("complete", "failed")
            ),
            None,
        )
        date_source = (start or {}).get("started_utc") or (finish or {}).get(
            "finished_utc"
        )
        if args.date is not None and (
            not isinstance(date_source, str)
            or datetime.fromisoformat(date_source).date() != args.date
        ):
            continue
        manifest_path = directory / "manifest.json"
        manifest = (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest_path.is_file()
            else None
        )
        checks: list[dict[str, object]] = []
        if isinstance(manifest, dict):
            raw = manifest.get("raw_capture")
            raw_path = (directory / "capture.bin").resolve()
            if not raw_path.is_relative_to(directory):
                raise ValueError("raw capture path is outside segment")
            if (
                manifest.get("input_mode") == "live"
                and isinstance(raw, dict)
                and raw.get("sha256")
            ):
                raw_actual = file_sha256(raw_path) if raw_path.is_file() else None
                checks.append(
                    {
                        "artifact": "raw_capture",
                        "path": str(raw_path.relative_to(root)),
                        "sha256_expected": raw["sha256"],
                        "sha256_actual": raw_actual,
                        "matches": raw_actual == raw["sha256"]
                        if raw_actual is not None
                        else None,
                        "exists": raw_actual is not None,
                    }
                )
            artifacts = manifest.get("artifacts", {})
            if isinstance(artifacts, dict):
                for kind, info in artifacts.items():
                    if not isinstance(info, dict) or not isinstance(
                        info.get("path"), str
                    ):
                        continue
                    path = (directory / info["path"]).resolve()
                    if not path.is_relative_to(directory):
                        raise ValueError("artifact path is outside segment")
                    expected = info.get("sha256")
                    actual = file_sha256(path) if path.is_file() else None
                    checks.append(
                        {
                            "artifact": kind,
                            "path": str(path.relative_to(root)),
                            "sha256_expected": expected,
                            "sha256_actual": actual,
                            "matches": actual == expected
                            if actual is not None and isinstance(expected, str)
                            else None,
                            "exists": actual is not None,
                            "epochs": info.get("epochs"),
                            "quality": info.get("quality"),
                        }
                    )
        before = finish.get("receiver_before") if finish else None
        after = finish.get("receiver_after") if finish else None

        def digest(snapshot: object) -> object:
            if not isinstance(snapshot, dict) or not isinstance(
                snapshot.get("configuration"), dict
            ):
                return None
            return snapshot["configuration"].get("entries_sha256")

        digest_before, digest_after = digest(before), digest(after)
        changed = (
            digest_before != digest_after
            if digest_before is not None and digest_after is not None
            else None
        )
        segments.append(
            {
                "segment": name,
                "status": finish.get("status") if finish else "incomplete",
                "started_utc": start.get("started_utc") if start else None,
                "finished_utc": finish.get("finished_utc") if finish else None,
                "error": finish.get("error") if finish else None,
                "free_bytes_before": (start or {}).get("free_bytes_before"),
                "configuration_changed_between_snapshots": changed,
                "receiver_before": before,
                "receiver_after": after,
                "capture_counts": manifest.get("capture_counts")
                if isinstance(manifest, dict)
                else None,
                "artifacts": checks,
                "manifest_present": manifest is not None,
            }
        )
    gaps = []
    for first, second in itertools.pairwise(segments):
        a, b = first["finished_utc"], second["started_utc"]
        if isinstance(a, str) and isinstance(b, str):
            seconds = (
                datetime.fromisoformat(b) - datetime.fromisoformat(a)
            ).total_seconds()
            gaps.append(
                {
                    "after_segment": first["segment"],
                    "before_segment": second["segment"],
                    "host_elapsed_s": seconds,
                }
            )
    disk_low_events = [
        event
        for event in events
        if event.get("status") == "disk_low"
        and (
            args.date is None
            or (
                isinstance(event.get("time_utc"), str)
                and datetime.fromisoformat(event["time_utc"]).date() == args.date
            )
        )
    ]
    result = {
        "journal_sha256": file_sha256(journal),
        "date_utc": args.date.isoformat() if args.date else None,
        "segments": segments,
        "between_segments": gaps,
        "disk_low_events": disk_low_events,
        "limitations": (
            "Host times are not an independent reference. Inter-segment "
            "intervals do not measure actual observation gaps. Matching "
            "snapshots do not prove settings remained unchanged between queries. "
            "Date filtering assigns each segment to its start date."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    if args.markdown is not None:
        lines = [
            "# Station health report",
            "",
            f"UTC date: {args.date.isoformat() if args.date else 'all dates'}",
            f"Segments: {len(segments)}",
            f"Disk-low events: {len(disk_low_events)}",
            "",
            "| Segment | Status | Start UTC | Manifest | Artifact checks |",
            "| --- | --- | --- | --- | --- |",
        ]
        for segment in segments:
            checks = segment["artifacts"]
            verified = sum(item["matches"] is True for item in checks)
            missing = sum(item["exists"] is False for item in checks)
            mismatch = sum(item["matches"] is False for item in checks)
            lines.append(
                f"| {segment['segment']} | {segment['status']} | "
                f"{segment['started_utc'] or 'unknown'} | "
                f"{'present' if segment['manifest_present'] else 'missing'} | "
                f"{verified} verified, {mismatch} mismatched, {missing} missing |"
            )
        lines.extend(
            [
                "",
                "The JSON report includes receiver snapshots, observation quality, "
                "hashes and inter-segment intervals. Host times do not establish "
                "observation gaps.",
            ]
        )
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
