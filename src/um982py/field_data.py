"""Utilities for indexing field samples and hashing recorded files."""

import csv
import hashlib
import math
import os
from bisect import bisect_left
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path


def file_sha256(path: str | os.PathLike[str]) -> str:
    """Hash a file incrementally."""
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_ecef_positions(
    path: str | os.PathLike[str],
) -> list[tuple[float, float, float, float]]:
    """Read ordered GPS seconds and ECEF metres from a position CSV."""
    with Path(path).open(newline="", encoding="utf-8") as stream:
        result = [
            (
                float(row["gps_seconds"]),
                float(row["x_m"]),
                float(row["y_m"]),
                float(row["z_m"]),
            )
            for row in csv.DictReader(stream)
        ]
    if any(not all(math.isfinite(value) for value in row) for row in result):
        raise ValueError("position epochs and coordinates must be finite")
    if any(b[0] <= a[0] for a, b in pairwise(result)):
        raise ValueError("position epochs must be strictly increasing")
    return result


def nearest_epoch[T](
    samples: Sequence[tuple[float, T]], times: Sequence[float], epoch: float
) -> tuple[float, T] | None:
    """Find the nearest sample in a time-sorted index, preferring an earlier tie."""
    index = bisect_left(times, epoch)
    candidates = [samples[i] for i in (index - 1, index) if 0 <= i < len(samples)]
    return min(candidates, key=lambda item: abs(item[0] - epoch), default=None)
