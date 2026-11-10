"""Write position fixes incrementally as GPX, GeoJSON or CSV."""

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import IO, Literal, Self
from xml.sax.saxutils import escape

from um982py.messages.navigation import BestNavigation, Fix

type TrackFormat = Literal["gpx", "geojson", "csv"]


class TrackWriter:
    """Write valid WGS 84 positions without retaining the track in memory.

    Use a new path: existing files are never replaced. Pass a verified UTC
    timestamp to ``write`` when available; receiver GGA time has no date.
    GPX elevation is the GGA/BESTNAV MSL height. GeoJSON elevation is the
    ellipsoidal height, when available. A track crossing a data gap should use
    a new file rather than implying continuous movement.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        format: TrackFormat,
        reference_frame: Literal["WGS84"],
    ) -> None:
        if format not in ("gpx", "geojson", "csv"):
            raise ValueError("format must be gpx, geojson or csv")
        if reference_frame != "WGS84":
            raise ValueError("track coordinates must be WGS84")
        self.path = Path(path)
        self.format = format
        self._file: IO[str] | None = None
        self._count = 0

    def __enter__(self) -> Self:
        if self._file is not None:
            raise RuntimeError("track is already open")
        self._file = self.path.open("x", encoding="utf-8", newline="")
        if self.format == "gpx":
            self._file.write(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<gpx version="1.1" creator="um982py" '
                'xmlns="http://www.topografix.com/GPX/1/1" '
                'xmlns:um982="urn:um982py:track:1"><trk><trkseg>\n'
            )
        elif self.format == "geojson":
            self._file.write('{"type":"FeatureCollection","features":[\n')
        else:
            csv.writer(self._file).writerow(
                (
                    "time_utc",
                    "latitude",
                    "longitude",
                    "height_msl_m",
                    "ellipsoidal_height_m",
                    "quality",
                )
            )
        return self

    def write(
        self, position: Fix | BestNavigation, *, timestamp: datetime | None = None
    ) -> None:
        """Append one valid fix; ``timestamp`` must be timezone-aware."""
        if self._file is None:
            raise RuntimeError("track is not open")
        if not position.valid:
            raise ValueError("cannot write an invalid position")
        lat, lon = position.latitude, position.longitude
        if lat is None or lon is None:
            raise ValueError("position has no coordinates")
        # Also validates manually constructed Fix coordinates.
        from um982py.geodesy import haversine_distance

        haversine_distance(lat, lon, lat, lon)
        if isinstance(position, BestNavigation) and position.datum != "WGS84":
            raise ValueError("BESTNAV datum must be WGS84")
        if timestamp is not None:
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("timestamp must be timezone-aware")
            stamp = timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
        else:
            stamp = None
        msl, height = position.altitude_msl, position.ellipsoidal_height
        from math import isfinite

        if any(value is not None and not isfinite(value) for value in (msl, height)):
            raise ValueError("position height must be finite")
        quality = str(
            position.quality if isinstance(position, Fix) else position.position_type
        )
        if self.format == "gpx":
            self._file.write(f'<trkpt lat="{lat}" lon="{lon}">')
            if msl is not None:
                self._file.write(f"<ele>{msl}</ele>")
            if stamp is not None:
                self._file.write(f"<time>{stamp}</time>")
            self._file.write(
                f"<extensions><um982:quality>{escape(quality)}</um982:quality></extensions>"
            )
            self._file.write("</trkpt>\n")
        elif self.format == "geojson":
            coordinates = [lon, lat] + ([height] if height is not None else [])
            feature = {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordinates},
                "properties": {
                    "time_utc": stamp,
                    "quality": quality,
                    "height_msl_m": msl,
                },
            }
            self._file.write(
                (",\n" if self._count else "") + json.dumps(feature, allow_nan=False)
            )
        else:
            csv.writer(self._file).writerow((stamp, lat, lon, msl, height, quality))
        self._count += 1

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._file is not None:
            try:
                if self.format == "gpx":
                    self._file.write("</trkseg></trk></gpx>\n")
                elif self.format == "geojson":
                    self._file.write("\n]}\n")
            finally:
                self._file.close()
                self._file = None
