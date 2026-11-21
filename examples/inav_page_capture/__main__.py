"""Capture Galileo E1-B I/NAV pages from a receiver memory snapshot."""

from __future__ import annotations

import sys
from pathlib import Path

from examples._console import ExampleParser, add_receiver_arguments, run, write_json
from um982py.experimental import InavSnapshot, capture_inav_pages


def build_parser() -> ExampleParser:
    parser = ExampleParser(
        prog="python -m examples.inav_page_capture", description=__doc__
    )
    add_receiver_arguments(parser, antenna=False, replay=False)
    parser.add_argument(
        "--helper",
        required=True,
        help="path of the RAM-resident reader image for the boot menu",
    )
    return parser


def _report(snapshot: InavSnapshot) -> dict[str, object]:
    report: dict[str, object] = snapshot.manifest()
    report["interpretation"] = (
        "Pages are the decoded E1-B page parts stored per signal at the "
        "capture instant. Odd nominal parts carry the OSNMA field; a "
        "sub-frame needs fifteen consecutive odd parts of one satellite."
    )
    return report


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:])
    helper = Path(args.helper)
    if not helper.exists():
        parser.error(f"helper image not found: {helper}")
    snapshot = capture_inav_pages(args.port, helper=helper, baud=args.baud)
    write_json(_report(snapshot), args.json)
    with_osnma = sum(page.part.osnma is not None for page in snapshot.pages)
    print(
        f"{len(snapshot.pages)} pages, {with_osnma} with OSNMA data, "
        f"application_restored={snapshot.application_restored}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run(main))
