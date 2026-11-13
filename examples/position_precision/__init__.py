"""Match GGA fixes with receiver-reported GST precision."""

from collections import Counter, defaultdict
from collections.abc import Sequence
from decimal import Decimal

from um982py import Fix, PositionPrecision, geojson_feature
from um982py.errors import ProtocolError
from um982py.messages import Record
from um982py.precision import utc_seconds


def map_precision(
    fixes: Sequence[Record], statistics: Sequence[Record]
) -> dict[str, object]:
    """Match unambiguous time-of-day and antenna pairs from one session."""
    parsed: list[tuple[Fix, tuple[int, Decimal]]] = []
    rejected = 0
    for record in fixes:
        try:
            fix = Fix.from_record(record)
            if not fix.valid or fix.antenna is None:
                raise ValueError("fix is unavailable")
            parsed.append((fix, (fix.antenna, utc_seconds(fix.utc))))
        except (ProtocolError, ValueError):
            rejected += 1
    candidates: dict[tuple[int, Decimal], list[Record]] = defaultdict(list)
    for record in statistics:
        try:
            precision = PositionPrecision.from_gst(record)
            if precision.antenna is None or precision.utc is None:
                raise ValueError("GST identity is unavailable")
            candidates[(precision.antenna, utc_seconds(precision.utc))].append(record)
        except ValueError:
            rejected += 1
    fix_counts = Counter(key for _, key in parsed)
    features = []
    matched = ambiguous = 0
    for fix, key in parsed:
        available = candidates.get(key, [])
        if fix_counts[key] == 1 and len(available) == 1:
            fix = fix.with_gst(available[0])
            matched += fix.precision is not None
        elif available:
            ambiguous += 1
        feature = geojson_feature(fix, reference_frame="WGS84")
        if feature is not None:
            features.append(feature)
    return {
        "status": "ok" if matched else "no_matched_precision",
        "valid_fixes": len(parsed),
        "gst_records": len(statistics),
        "matched_precision": matched,
        "ambiguous_fixes": ambiguous,
        "rejected_records": rejected,
        "geojson": {"type": "FeatureCollection", "features": features},
    }
