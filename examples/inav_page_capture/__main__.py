"""Capture Galileo, GPS, GLONASS and BeiDou navigation or replay Galileo streams."""

from __future__ import annotations

import json
import sys
from argparse import BooleanOptionalAction
from collections.abc import Sequence
from datetime import datetime
from hashlib import sha256
from math import isfinite
from pathlib import Path

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples.inav_page_capture import (
    render_campaign,
    render_native_nav,
)
from um982py.experimental import (
    TRACKING_MEMORY_BASE,
    BeidouLegacySubframe,
    GlonassFdmaString,
    GpsLnavSubframe,
    InavCampaign,
    InavSnapshot,
    PageWindowAudit,
    capture_inav_campaign,
    capture_inav_pages,
    extract_beidou_nav,
    extract_native_nav,
    load_public_key,
    read_inav_stream_csv,
    replay_inav_ced,
    replay_sar_stream,
    verify_osnma_stream,
)

DEFAULT_READER = (
    Path(__file__).resolve().parents[2] / "tools" / "boot-reader" / "reader.bin"
)
"""Reader image shipped with the repository, used when --helper is omitted."""


def build_parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python3 -m examples.inav_page_capture", description=__doc__
    )
    add_receiver_arguments(parser, antenna=False, replay=False)
    offline = parser.add_mutually_exclusive_group()
    offline.add_argument(
        "--stream-csv",
        type=Path,
        help="verify a Galileo test-vector format stream without opening the receiver",
    )
    offline.add_argument(
        "--tracking-ram",
        type=Path,
        help="extract navigation bits from a saved tracking window",
    )
    replay_mode = parser.add_mutually_exclusive_group()
    replay_mode.add_argument(
        "--public-key",
        type=Path,
        action="append",
        default=[],
        help="trusted Galileo public-key XML for offline replay, repeatable",
    )
    replay_mode.add_argument(
        "--sar-only",
        action="store_true",
        help="decode SAR return-link messages from --stream-csv",
    )
    replay_mode.add_argument(
        "--ced-only",
        action="store_true",
        help="decode RedCED and recover clock and ephemeris using FEC2",
    )
    parser.add_argument(
        "--native-nav",
        action=BooleanOptionalAction,
        help="show checked GPS, GLONASS and BeiDou bits in snapshots (default: on)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="show counts instead of raw tables while keeping the full snapshot JSON",
    )
    parser.add_argument(
        "--save-tracking",
        type=Path,
        metavar="DIR",
        help="archive each live tracking window and its metadata to a new directory",
    )
    parser.add_argument(
        "--helper",
        type=Path,
        default=DEFAULT_READER,
        help="path of the RAM-resident reader image for the boot menu; "
        "defaults to tools/boot-reader/reader.bin of this repository",
    )
    parser.add_argument(
        "--snapshots",
        type=int,
        default=1,
        help="number of boot-menu snapshots; two or more allow word assembly",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=5.0,
        help="seconds between snapshots so page parts advance",
    )
    return parser


def _report(
    campaign: InavCampaign | InavSnapshot,
    *,
    audits: Sequence[Sequence[PageWindowAudit]] | None = None,
) -> dict[str, object]:
    report = (
        campaign.manifest(audits=audits)
        if isinstance(campaign, InavCampaign)
        else campaign.manifest()
    )
    report["interpretation"] = (
        "Pages are the decoded E1-B page parts stored per signal at each "
        "capture instant. Odd nominal parts carry OSNMA and SAR fields. Word "
        "assembly pairs even and odd parts across snapshots; only pairs "
        "that pass the page checksum are reported as words. A full "
        "OSNMA sub-frame needs fifteen consecutive odd parts of one "
        "satellite and a public key from the Galileo key directory. SAR "
        "message assembly requires a continuous stream."
    )
    return report


def _native_nav_manifest(
    gps: Sequence[GpsLnavSubframe],
    glonass: Sequence[GlonassFdmaString],
    beidou: Sequence[BeidouLegacySubframe],
) -> dict[str, object]:
    return {
        "gps_lnav": [subframe.manifest() for subframe in gps],
        "glonass_fdma": [string.manifest() for string in glonass],
        "beidou_legacy": [subframe.manifest() for subframe in beidou],
    }


def _write_snapshot_report(
    campaign: InavCampaign,
    destination: Path | None,
    *,
    native_nav: bool,
    summary: bool,
    archive: Sequence[dict[str, object]] = (),
) -> None:
    audits = [snapshot.window_audits() for snapshot in campaign.snapshots]
    report = _report(campaign, audits=audits)
    if archive:
        report["tracking_archive"] = list(archive)
    table = [] if summary else [
        render_campaign(campaign, audits=[audit for group in audits for audit in group])
    ]
    gps_count = glonass_count = beidou_count = 0
    if native_nav:
        native = [
            (*extract_native_nav(snapshot.memory_windows),
             extract_beidou_nav(snapshot.memory_windows))
            for snapshot in campaign.snapshots
        ]
        report["native_nav"] = [
            _native_nav_manifest(*records) for records in native
        ]
        for index, (gps, glonass, beidou) in enumerate(native, start=1):
            gps_count += len(gps)
            glonass_count += len(glonass)
            beidou_count += len(beidou)
            if not summary:
                heading = f"Snapshot {index}\n" if len(native) > 1 else ""
                table.append(heading + render_native_nav(gps, glonass, beidou))
    if table:
        print("\n\n".join(table), file=sys.stdout if destination else sys.stderr)
    write_json(report, destination)
    words = report["words"]
    assert isinstance(words, list)
    totals = (
        f"{len(campaign.snapshots)} snapshots, {report['pages']} Galileo parts, "
        f"{len(words)} CRC-checked words"
    )
    if native_nav:
        totals += (
            f", {gps_count} GPS subframes, {glonass_count} GLONASS strings, "
            f"{beidou_count} BeiDou subframes"
        )
    if campaign.application_restored is not None:
        totals += f", application_restored={campaign.application_restored}"
    print(totals, file=sys.stdout if summary and destination else sys.stderr)


def _save_tracking(
    directory: Path, index: int, snapshot: InavSnapshot
) -> dict[str, object]:
    base, data = snapshot.memory_windows["tracking"]
    target = directory / f"tracking-{index:04d}.bin"
    partial = target.with_suffix(".partial")
    partial.write_bytes(data)
    partial.rename(target)
    result: dict[str, object] = {
        "snapshot_index": index,
        "path": str(target),
        "base_address": base,
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "capture_started_utc": snapshot.capture_started_utc.isoformat()
        if snapshot.capture_started_utc is not None else None,
        "capture_finished_utc": snapshot.capture_finished_utc.isoformat()
        if snapshot.capture_finished_utc is not None else None,
        "application_restored": snapshot.application_restored,
    }
    write_json(result, target.with_suffix(".metadata.json"))
    return result


def _load_tracking(path: Path) -> InavSnapshot:
    data = path.read_bytes()
    sidecar = path.with_suffix(".metadata.json")
    if not sidecar.is_file():
        return InavSnapshot.from_regions({"tracking": (TRACKING_MEMORY_BASE, data)})
    metadata = json.loads(sidecar.read_text(encoding="utf-8"))
    if (
        not isinstance(metadata, dict)
        or metadata.get("sha256") != sha256(data).hexdigest()
    ):
        raise ValueError(f"Tracking window checksum does not match {sidecar}")
    started = metadata.get("capture_started_utc")
    finished = metadata.get("capture_finished_utc")
    base = metadata.get("base_address")
    if type(base) is not int or base < 0:
        raise ValueError(f"Invalid tracking window base address in {sidecar}")
    return InavSnapshot.from_regions(
        {"tracking": (base, data)},
        application_restored=metadata.get("application_restored"),
        capture_started_utc=datetime.fromisoformat(started) if started else None,
        capture_finished_utc=datetime.fromisoformat(finished) if finished else None,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:])
    if args.stream_csv is not None:
        if args.summary or args.save_tracking is not None:
            parser.error("--summary and --save-tracking apply to tracking snapshots")
        if args.native_nav is not None:
            parser.error("--native-nav and --no-native-nav require a tracking snapshot")
        if not (args.public_key or args.sar_only or args.ced_only):
            parser.error("--stream-csv requires --public-key, --sar-only or --ced-only")
        if args.json is not None and args.json.resolve() in {
            path.resolve() for path in (args.stream_csv, *args.public_key)
        }:
            parser.error("--json must not overwrite a replay input file")
        streams = read_inav_stream_csv(args.stream_csv)
        if args.ced_only:
            ced = {svid: replay_inav_ced(parts) for svid, parts in streams.items()}
            write_json({"ced": ced}, args.json)
            return 0
        if args.sar_only:
            sar = {
                svid: replay_sar_stream(parts).manifest()
                for svid, parts in streams.items()
            }
            write_json({"sar": sar}, args.json)
            return 0
        keys = {}
        for path in args.public_key:
            key_id, _, point = load_public_key(path)
            if key_id in keys and keys[key_id] != point:
                parser.error(f"conflicting public keys for PKID {key_id}")
            keys[key_id] = point
        replay = verify_osnma_stream(streams, keys)
        write_json(
            {
                "osnma_subframes": replay.osnma_subframes,
                "verified_roots": [root.manifest() for root in replay.roots],
                "verified_tag0": [
                    {
                        "svid": tag.svid,
                        "tag_gst": tag.tag_gst,
                        "data_gst": tag.data_gst,
                        "status": tag.status.value,
                        "tag": tag.tag.hex(),
                        "tag_bits": tag.tag_bits,
                    }
                    for tag in replay.verified_tags
                ],
            },
            args.json,
        )
        return 0
    if args.public_key or args.sar_only or args.ced_only:
        parser.error("--public-key, --sar-only and --ced-only require --stream-csv")
    if args.tracking_ram is not None:
        if args.save_tracking is not None:
            parser.error("--save-tracking requires a live capture")
        if args.json is not None and args.json.resolve() in {
            args.tracking_ram.resolve(),
            args.tracking_ram.with_suffix(".metadata.json").resolve(),
        }:
            parser.error("--json must not overwrite the tracking window or metadata")
        snapshot = _load_tracking(args.tracking_ram)
        _write_snapshot_report(
            InavCampaign((snapshot,)), args.json,
            native_nav=args.native_nav is not False, summary=args.summary,
        )
        return 0
    helper = Path(args.helper)
    if not helper.exists():
        parser.error(
            f"reader image not found: {helper}; pass --helper with the "
            "path of the RAM-resident reader image "
            "(tools/boot-reader/reader.bin in this repository)"
        )
    if args.snapshots < 1 or not isfinite(args.pause) or args.pause < 0:
        parser.error("--snapshots must be positive and --pause finite and nonnegative")

    archive: list[dict[str, object]] = []
    directory: Path | None = args.save_tracking
    if directory is not None:
        output = None if args.json is None else args.json.resolve()
        archive_path = directory.resolve()
        if output == archive_path or (
            output is not None
            and output.parent == archive_path
            and output.name.startswith("tracking-")
        ):
            parser.error("--json must not overwrite a tracking archive file")
        directory.mkdir(parents=True)

    def archive_snapshot(snapshot: InavSnapshot) -> None:
        if directory is not None:
            archive.append(_save_tracking(directory, len(archive) + 1, snapshot))

    if args.snapshots > 1:
        campaign = capture_inav_campaign(
            args.port,
            helper=helper,
            baud=args.baud,
            snapshots=args.snapshots,
            pause_seconds=args.pause,
            on_snapshot=archive_snapshot if directory is not None else None,
        )
    else:
        snapshot: InavSnapshot = capture_inav_pages(
            args.port, helper=helper, baud=args.baud
        )
        archive_snapshot(snapshot)
        campaign = InavCampaign((snapshot,))
    _write_snapshot_report(
        campaign, args.json, native_nav=args.native_nav is not False,
        summary=args.summary, archive=archive,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
