"""Provides independent observation tables and labelled phase samples."""

import json
from pathlib import Path
from typing import Any

from um982py.measurement import RangeSample, SignalKey

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "specialist"
TRUTH: dict[str, Any] = json.loads((FIXTURES / "measurement-truth.json").read_text())


def sample(
    epoch: float,
    *,
    prn: int = 1,
    code: float = 100.0,
    phase: float = 100.0,
    rate: float = 0.0,
    lock: float | None = None,
) -> RangeSample:
    """Build a labelled GPS L1 sample without calling an example algorithm."""
    return RangeSample(
        SignalKey(0, prn, 0),
        epoch,
        code,
        phase,
        rate,
        1.0,
        0.01,
        45.0,
        epoch + 100 if lock is None else lock,
    )
