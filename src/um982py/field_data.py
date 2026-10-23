"""Utilities for indexing field samples and hashing recorded files."""

import hashlib
from bisect import bisect_left
from collections.abc import Sequence
from pathlib import Path


def file_sha256(path: Path) -> str:
    """Hash a file without loading the entire recording into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def nearest_epoch[T](
    samples: Sequence[tuple[float, T]], times: Sequence[float], epoch: float
) -> tuple[float, T] | None:
    """Find the nearest sample in a time-sorted index, preferring an earlier tie."""
    index = bisect_left(times, epoch)
    candidates = [samples[i] for i in (index - 1, index) if 0 <= i < len(samples)]
    return min(candidates, key=lambda item: abs(item[0] - epoch), default=None)
