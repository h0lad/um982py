"""Capture Galileo, GPS and GLONASS navigation or replay Galileo streams."""

from __future__ import annotations

import sys
from argparse import BooleanOptionalAction
from collections.abc import Sequence
from pathlib import Path

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples.inav_page_capture import (
    campaign_window_audits,
    render_campaign,
    render_native_nav,
)
from um982py.experimental import (
    TRACKING_MEMORY_BASE,
    GlonassFdmaString,
    GpsLnavSubframe,
    InavCampaign,
    InavSnapshot,
    capture_inav_campaign,
    capture_inav_pages,
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
        help="extract GPS and GLONASS navigation bits from a saved tracking window",
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
        help="show parity-checked GPS and GLONASS bits in snapshots (default: on)",
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


def _report(campaign: InavCampaign) -> dict[str, object]:
    report: dict[str, object] = campaign.manifest()
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
    gps: Sequence[GpsLnavSubframe], glonass: Sequence[GlonassFdmaString]
) -> dict[str, object]:
    return {
        "gps_lnav": [subframe.manifest() for subframe in gps],
        "glonass_fdma": [string.manifest() for string in glonass],
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:])
    if args.stream_csv is not None:
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
        if args.native_nav is False:
            parser.error("--tracking-ram requires native navigation extraction")
        if args.json is not None and args.json.resolve() == args.tracking_ram.resolve():
            parser.error("--json must not overwrite the tracking window")
        gps, glonass = extract_native_nav(
            {"tracking": (TRACKING_MEMORY_BASE, args.tracking_ram.read_bytes())}
        )
        print(
            render_native_nav(gps, glonass),
            file=sys.stdout if args.json is not None else sys.stderr,
        )
        report = {"native_nav": [_native_nav_manifest(gps, glonass)]}
        write_json(report, args.json)
        return 0
    helper = Path(args.helper)
    if not helper.exists():
        parser.error(
            f"reader image not found: {helper}; pass --helper with the "
            "path of the RAM-resident reader image "
            "(tools/boot-reader/reader.bin in this repository)"
        )
    if args.snapshots > 1:
        campaign = capture_inav_campaign(
            args.port,
            helper=helper,
            baud=args.baud,
            snapshots=args.snapshots,
            pause_seconds=args.pause,
        )
    else:
        snapshot: InavSnapshot = capture_inav_pages(
            args.port, helper=helper, baud=args.baud
        )
        campaign = InavCampaign((snapshot,))
    report = _report(campaign)
    text = [render_campaign(campaign, audits=campaign_window_audits(campaign))]
    if args.native_nav is not False:
        native = [
            extract_native_nav(
                {"tracking": (TRACKING_MEMORY_BASE, snapshot.regions["tracking"])}
            )
            for snapshot in campaign.snapshots
        ]
        report["native_nav"] = [
            _native_nav_manifest(gps, glonass) for gps, glonass in native
        ]
        for index, (gps, glonass) in enumerate(native, start=1):
            heading = f"Snapshot {index}\n" if len(native) > 1 else ""
            text.append(heading + render_native_nav(gps, glonass))
    print("\n\n".join(text), file=sys.stdout if args.json is not None else sys.stderr)
    write_json(report, args.json)
    words = campaign.words()
    with_osnma = sum(
        page.part.osnma is not None for page in campaign.pages
    )
    print(
        f"{len(campaign.pages)} pages, {with_osnma} with OSNMA data, "
        f"{len(words)} checksum-verified words, "
        f"application_restored={campaign.application_restored}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
