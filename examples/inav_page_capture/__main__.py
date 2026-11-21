"""Capture Galileo E1-B I/NAV pages and verify their authentication data."""

from __future__ import annotations

import sys
from pathlib import Path

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import (
    InavCampaign,
    InavSnapshot,
    capture_inav_campaign,
    capture_inav_pages,
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
