"""PPP convergence benchmark for low-cost GNSS receivers.

Collects PPP position epochs, reports time-to-first-fix, time to a sustained
precision window, and empirical error distributions against an optional
reference position.

Reference
---------
Marut, G., Hadas, T., Kazmierski, K., et al. (2024). Affordable Real-Time PPP—
Combining Low-Cost GNSS Receivers with Galileo HAS Corrections in Static,
Pseudo-Kinematic, and UAV Experiments. Remote Sensing, 16(21), 4008.
doi:10.3390/rs16214008
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from um982py.geodesy import enu_from_ecef
from um982py.messages import Record
from um982py.messages.navigation import BestNavigation


@dataclass(frozen=True, slots=True)
class PppEpoch:
    """One PPP navigation epoch with optional reference error."""

    epoch: float
    elapsed_s: float
    latitude: float
    longitude: float
    height_ellipsoidal: float
    horizontal_rms_m: float | None
    vertical_std_m: float | None
    converged: bool
    east_error_m: float | None
    north_error_m: float | None
    up_error_m: float | None
    horizontal_error_m: float | None
    three_d_error_m: float | None


def bestnav_from_record(record: Record) -> BestNavigation:
    """Decode a BESTNAV or PPPNAV record."""
    return BestNavigation.from_record(record)


def _reference_error(
    position: tuple[float, float, float],
    reference: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Return ENU error of *position* relative to *reference* (ECEF metres)."""
    dx = position[0] - reference[0]
    dy = position[1] - reference[1]
    dz = position[2] - reference[2]
    return enu_from_ecef(dx, dy, dz, reference[0], reference[1])


def epoch_from_navigation(
    nav: BestNavigation,
    elapsed_s: float,
    reference_ecef: tuple[float, float, float] | None,
) -> PppEpoch:
    """Convert one navigation solution into a benchmark epoch."""
    h_rms = None
    v_std = None
    if nav.precision is not None:
        h_rms = nav.precision.horizontal_rms_m
        v_std = nav.precision.up_std_m

    position = (
        nav.latitude,
        nav.longitude,
        nav.altitude_msl + nav.geoid_separation,
    )
    ecef = None
    try:
        from um982py.geodesy import ecef_from_geodetic

        ecef = ecef_from_geodetic(*position)
    except ValueError:
        pass

    e_err = n_err = u_err = h_err = t_err = None
    if ecef is not None and reference_ecef is not None:
        e_err, n_err, u_err = _reference_error(ecef, reference_ecef)
        h_err = math.hypot(e_err, n_err)
        t_err = math.sqrt(e_err * e_err + n_err * n_err + u_err * u_err)

    return PppEpoch(
        epoch=nav.epoch_gps_seconds if nav.epoch_gps_seconds is not None else elapsed_s,
        elapsed_s=elapsed_s,
        latitude=nav.latitude,
        longitude=nav.longitude,
        height_ellipsoidal=position[2],
        horizontal_rms_m=h_rms,
        vertical_std_m=v_std,
        converged=False,
        east_error_m=e_err,
        north_error_m=n_err,
        up_error_m=u_err,
        horizontal_error_m=h_err,
        three_d_error_m=t_err,
    )


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear-interpolation percentile of a sorted sample."""
    if not values:
        return None
    sorted_values = sorted(values)
    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]
    k = (n - 1) * p / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)
