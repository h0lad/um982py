"""PPP-B2b correction epochs on the receiver GPS time scale."""

import math

__all__ = ["b2b_epoch"]


def b2b_epoch(received_gps_seconds: float, seconds_of_day: int) -> float:
    """Resolve a BeiDou seconds-of-day tag to the nearest GPS day, adding 14 s."""
    if not math.isfinite(received_gps_seconds):
        raise ValueError("receiver epoch must be finite")
    if type(seconds_of_day) is not int or not 0 <= seconds_of_day < 86400:
        raise ValueError("BeiDou seconds of day must be in 0..86399")
    received_bdt = received_gps_seconds - 14.0
    day = math.floor(received_bdt / 86400)
    candidate = day * 86400 + seconds_of_day + 14.0
    difference = candidate - received_gps_seconds
    if difference > 43200:
        candidate -= 86400
    elif difference < -43200:
        candidate += 86400
    return candidate
