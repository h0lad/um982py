"""Match GGA fixes with receiver-reported GST precision."""

from collections.abc import Sequence

from um982py import geojson_feature, match_precision
from um982py.messages import Record


def map_precision(
    fixes: Sequence[Record], statistics: Sequence[Record]
) -> dict[str, object]:
    """Match unambiguous time-of-day and antenna pairs from one session."""
    result = match_precision(fixes, statistics)
    features = [
        feature
        for fix in result.fixes
        if (feature := geojson_feature(fix, reference_frame="WGS84")) is not None
    ]
    return {
        "status": "ok" if result.matched else "no_matched_precision",
        "valid_fixes": len(result.fixes),
        "gst_records": result.statistics,
        "matched_precision": result.matched,
        "ambiguous_fixes": result.ambiguous,
        "rejected_records": result.rejected,
        "geojson": {"type": "FeatureCollection", "features": features},
    }
