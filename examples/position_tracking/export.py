"""Write position tracks to CSV."""

from __future__ import annotations

import csv
from dataclasses import asdict, fields
from pathlib import Path

from examples.position_tracking.track import Track, TrackPoint


def write_positions_csv(track: Track, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, [field.name for field in fields(TrackPoint)])
        writer.writeheader()
        writer.writerows(asdict(point) for point in track.points)
