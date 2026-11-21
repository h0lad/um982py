"""Capture Galileo E1-B I/NAV pages and verify their authentication data."""

from __future__ import annotations

import sys
from pathlib import Path

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from examples.inav_page_capture import campaign_window_audits, render_campaign
from um982py.experimental import (
    InavCampaign,
    InavSnapshot,
    capture_inav_campaign,
    capture_inav_pages,
    load_public_key,
    read_inav_stream_csv,
    verify_osnma_stream,
)

DEFAULT_READER = (
    Path(__file__).resolve().parents[2] / "tools" / "boot-reader" / "reader.bin"
)
"""Reader image shipped with the repository, used when --helper is omitted."""


def build_parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.inav_page_capture", description=__doc__
    )
    add_receiver_arguments(parser, antenna=False, replay=False)
    parser.add_argument(
        "--stream-csv",
        type=Path,
        help="verify a Galileo test-vector format stream without opening the receiver",
    )
    parser.add_argument(
        "--public-key",
        type=Path,
        action="append",
        default=[],
        help="trusted Galileo public-key XML for offline replay, repeatable",
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
        "capture instant. Odd nominal parts carry the OSNMA field. Word "
        "assembly pairs even and odd parts across snapshots; only pairs "
        "that pass the page checksum are reported as words. A full "
        "OSNMA sub-frame needs fifteen consecutive odd parts of one "
        "satellite and a public key from the Galileo key directory."
    )
    return report


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:])
    if args.stream_csv is not None:
        if not args.public_key:
            parser.error("--stream-csv requires at least one --public-key")
        if args.json is not None and args.json.resolve() in {
            path.resolve() for path in (args.stream_csv, *args.public_key)
        }:
            parser.error("--json must not overwrite a replay input file")
        keys = {}
        for path in args.public_key:
            key_id, _, point = load_public_key(path)
            if key_id in keys and keys[key_id] != point:
                parser.error(f"conflicting public keys for PKID {key_id}")
            keys[key_id] = point
        replay = verify_osnma_stream(read_inav_stream_csv(args.stream_csv), keys)
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
    if args.public_key:
        parser.error("--public-key requires --stream-csv")
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
        report = _report(campaign)
    else:
        snapshot: InavSnapshot = capture_inav_pages(
            args.port, helper=helper, baud=args.baud
        )
        campaign = InavCampaign((snapshot,))
        report = _report(campaign)
    text = render_campaign(campaign, audits=campaign_window_audits(campaign))
    print(text, file=sys.stdout if args.json is not None else sys.stderr)
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
