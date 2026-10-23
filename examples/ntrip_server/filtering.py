"""Filter this caster's single-record sourcetable using NTRIP query fields."""

import math
import re
from fnmatch import fnmatchcase

_NUMERIC = frozenset((5, 9, 10, 11, 12, 17))


def _split(expression: str, operator: str) -> list[str]:
    depth = 0
    start = 0
    parts = []
    for index, char in enumerate(expression):
        if char == "(":
            depth += 1
            if depth > 16:
                raise ValueError("filter nesting is too deep")
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced filter")
        elif char == operator and depth == 0:
            parts.append(expression[start:index])
            start = index + 1
    if depth:
        raise ValueError("unbalanced filter")
    parts.append(expression[start:])
    if any(not part for part in parts):
        raise ValueError("empty filter expression")
    return parts


def _matches(value: str, expression: str, *, numeric: bool, depth: int = 0) -> bool:
    if depth > 16:
        raise ValueError("filter nesting is too deep")
    for op in ("|", "&"):
        pieces = _split(expression, op)
        if len(pieces) > 1:
            matches = [
                _matches(value, part, numeric=numeric, depth=depth + 1)
                for part in pieces
            ]
            return any(matches) if op == "|" else all(matches)
    if expression.startswith("(") and expression.endswith(")"):
        return _matches(value, expression[1:-1], numeric=numeric, depth=depth + 1)
    if expression.startswith("!") and not expression.startswith("!="):
        return not _matches(value, expression[1:], numeric=numeric, depth=depth + 1)
    if numeric:
        match = re.fullmatch(
            r"(<=|>=|!=|=<|=>|=|<|>|~)?([-+]?(?:\d+(?:\.\d*)?|\.\d+))", expression
        )
        if not match:
            raise ValueError("invalid numeric filter")
        expected = float(match[2])
        actual = float(value)
        if not math.isfinite(expected):
            raise ValueError("invalid numeric filter")
        op = match[1] or "="
        return {
            "=": actual == expected,
            "!=": actual != expected,
            "<": actual < expected,
            ">": actual > expected,
            "<=": actual <= expected,
            "=<": actual <= expected,
            ">=": actual >= expected,
            "=>": actual >= expected,
            # Approximate matching asks for the nearest numeric value. This
            # caster has only one stream record, so it is the only candidate.
            "~": True,
        }[op]
    if not re.fullmatch(r"[A-Za-z0-9_.*+:/ -]+", expression):
        raise ValueError("invalid string filter")
    return fnmatchcase(value.casefold(), expression.casefold())


def filter_table(table: bytes, query: str) -> bytes:
    """Filter one STR, retaining ENDSOURCETABLE when the query has no results."""
    if len(query) > 1024 or any(ord(c) < 32 or ord(c) > 126 for c in query):
        raise ValueError("invalid sourcetable filter")
    lines = table.decode("ascii").splitlines()
    fields = lines[0].split(";")
    filters = query.split(";")
    if len(filters) > len(fields):
        raise ValueError("too many filter fields")
    results = [
        _matches(fields[index], value, numeric=index in _NUMERIC)
        for index, value in enumerate(filters)
        if value
    ]
    return table if all(results) else b"ENDSOURCETABLE\r\n"
