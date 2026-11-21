"""Parse PPP solver diagnostics from a line-oriented trace."""

import re
from math import isfinite

from um982py.messages import Record

_NUMBERS = {
    "gap_covariance": ("PPPGAPVCV-from-GAP", 9),
    "position_covariance": ("PPPGAP POS-VCV", 3),
    "gap_variance_scale": ("GAPVARSCAL", 1),
}
_RESET = re.compile(r":?\s*RESET TYPE:\s*([+-]?\d+)\s+CAUSE:\s*(.+)")
_TIMED_RESET = re.compile(
    r"(?::\s*After time\s+)?([+-]?\d+):\s*(Whole PPP reset|Kalman Filter soft reset)"
)
_IODE_MISMATCH = re.compile(r"IODE-NoMatch:Prn\s+(\d+)\s+([+-]?\d+)")
_SOLUTION = re.compile(
    r":?\s*Sol\s+(.+?)\s+clk:\s*(.+?)\s+PDOP\s+(\S+)\s+HDOP\s+(\S+)"
    r"\s+VDOP\s+(\S+)\s+dwtrop:\s*(.+)"
)


def _numbers(text: str, count: int) -> tuple[float, ...]:
    fields = text.split()
    if len(fields) != count:
        raise ValueError("Unexpected PPP trace field count")
    values = tuple(float(field) for field in fields)
    if not all(isfinite(value) for value in values):
        raise ValueError("Non-finite PPP trace value")
    return values


def parse_ppp_solver_trace(raw: bytes | str) -> Record | None:
    """Decode one recognized solver trace line, retaining native field order."""
    line = (raw.decode("latin1") if isinstance(raw, bytes) else raw).strip()
    if (match := _RESET.fullmatch(line)) is not None:
        return Record("reset", (("reset_type", int(match[1])), ("cause", match[2])))
    if (match := _TIMED_RESET.fullmatch(line)) is not None:
        kind = "whole_reset" if match[2] == "Whole PPP reset" else "soft_reset"
        return Record(kind, (("native_time", int(match[1])),))
    if (match := _IODE_MISMATCH.fullmatch(line)) is not None:
        return Record(
            "iode_mismatch", (("slot", int(match[1])), ("native_iode", int(match[2])))
        )

    try:
        for kind, (prefix, count) in _NUMBERS.items():
            if line.startswith(prefix + " "):
                return Record(kind, (("values", _numbers(line[len(prefix) :], count)),))
        if (match := _SOLUTION.fullmatch(line)) is not None:
            return Record(
                "solution",
                (
                    ("solution", _numbers(match[1], 7)),
                    ("clock", _numbers(match[2], 6)),
                    ("dop", _numbers(" ".join(match.groups()[2:5]), 3)),
                    ("troposphere", _numbers(match[6], 3)),
                ),
            )
    except ValueError:
        return None
    return None
