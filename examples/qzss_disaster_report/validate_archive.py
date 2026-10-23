"""Check MT43 and MT44 frames in an official QZSS daily L1S archive."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from um982py.messages.qzss_dcr import decode_qzqsm
from um982py.messages.record import Record


def validate_archive(data: bytes) -> dict[str, object]:
    """Decode complete archived frames without interpreting unknown MT44 fields."""
    if len(data) < 37 or (len(data) - 1) % 36:
        raise ValueError("L1S archive must contain a PRN byte and 36-byte records")
    types: Counter[int] = Counter()
    accepted: Counter[int] = Counter()
    rejected: Counter[str] = Counter()
    categories: Counter[int] = Counter()
    first: tuple[int, int] | None = None
    last: tuple[int, int] | None = None
    nonzero_archive_spare = 0
    satellite = data[0]
    for start in range(1, len(data), 36):
        block = data[start : start + 36]
        stamp = int.from_bytes(block[:4], "big")
        timestamp = stamp >> 20, stamp & ((1 << 20) - 1)
        if timestamp[1] >= 604800:
            raise ValueError("archive contains an invalid GPS time of week")
        first = timestamp if first is None else first
        last = timestamp
        if block[-1] & 0x3F:
            nonzero_archive_spare += 1
        frame = int.from_bytes(block[4:], "big") >> 6
        message_type = (frame >> 236) & 63
        types[message_type] += 1
        if message_type not in (43, 44):
            continue
        payload = f"{frame << 2:063X}"
        try:
            report = decode_qzqsm(
                Record("QZQSM", (("prn", satellite), ("dc_message", payload)))
            )
        except ValueError as error:
            rejected[str(error)] += 1
            continue
        accepted[message_type] += 1
        if report.category_code is not None:
            categories[report.category_code] += 1
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "satellite_identifier": satellite,
        "records": (len(data) - 1) // 36,
        "first_gps_week_tow": first,
        "last_gps_week_tow": last,
        "nonzero_archive_spare": nonzero_archive_spare,
        "message_types": dict(sorted(types.items())),
        "accepted_dcr_by_type": dict(sorted(accepted.items())),
        "rejected_dcr": dict(sorted(rejected.items())),
        "mt43_categories": dict(sorted(categories.items())),
        "limitation": (
            "Archive input and CRC checks do not independently validate report "
            "semantics. MT44 content is retained without interpretation."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="downloaded official .l1s file")
    args = parser.parse_args()
    result = validate_archive(args.archive.read_bytes())
    print(json.dumps(result, indent=2))
    return 1 if result["rejected_dcr"] or result["nonzero_archive_spare"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
