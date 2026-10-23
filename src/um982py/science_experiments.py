"""Calculations for prevalidated, synchronized GNSS observations."""

import itertools
import math
from collections.abc import Sequence

from um982py.geodesy import SPEED_OF_LIGHT
from um982py.stats import correlation as _correlation
from um982py.stats import finite as _finite

C = SPEED_OF_LIGHT
TECU = 1e16


def tec_phase_change(
    high_before_m: float,
    low_before_m: float,
    high_after_m: float,
    low_after_m: float,
    high_hz: float,
    low_hz: float,
) -> float:
    """Return ambiguity-free slant TEC change in TECU along one continuous arc.

    Phases are range-increasing metres. The same frequency pair and unbroken
    carrier arcs are required at both epochs because cycle slips invalidate the result.
    """
    _finite(high_before_m, low_before_m, high_after_m, low_after_m, high_hz, low_hz)
    if not high_hz > low_hz > 0:
        raise ValueError("frequencies must satisfy high > low > 0")
    scale = 40.3 * TECU * (1 / low_hz**2 - 1 / high_hz**2)
    return ((high_after_m - low_after_m) - (high_before_m - low_before_m)) / scale


def sample_variance(values: Sequence[float]) -> float:
    """Calculate unbiased sample variance without implying independence."""
    if len(values) < 2:
        raise ValueError("at least two samples required")
    _finite(*values)
    avg = math.fsum(values) / len(values)
    return math.fsum((v - avg) ** 2 for v in values) / (len(values) - 1)


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Return Pearson correlation, or None for zero variance.

    Raise ``ValueError`` for fewer than two paired samples.
    """
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("at least two paired samples required")
    return _correlation(a, b, minimum_samples=2)


def tec_spatial_summary(
    a: Sequence[float], b: Sequence[float]
) -> dict[str, float | int | None]:
    """Summarize matched, same-satellite TEC changes at two stations."""
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("at least two matched TEC changes required")
    diffs = [x - y for x, y in zip(a, b, strict=True)]
    return {
        "pairs": len(a),
        "mean_difference_tecu": math.fsum(diffs) / len(diffs),
        "difference_std_tecu": math.sqrt(sample_variance(diffs)),
        "correlation": correlation(a, b),
    }


def noise_multipath_summary(
    shared_differences: Sequence[float],
    separate_differences: Sequence[float],
    repeated_a: Sequence[float],
    repeated_b: Sequence[float],
) -> dict[str, float | int | None]:
    """Compare measured difference variances and held-out repeat-track correlation.

    Use the same differencing convention for shared and separate antenna
    series. Their variance difference is descriptive and cannot uniquely
    separate noise.
    """
    shared = sample_variance(shared_differences)
    separate = sample_variance(separate_differences)
    return {
        "shared_count": len(shared_differences),
        "separate_count": len(separate_differences),
        "shared_variance_m2": shared,
        "separate_variance_m2": separate,
        "variance_difference_m2": separate - shared,
        "repeat_pairs": len(repeated_a),
        "repeat_correlation": correlation(repeated_a, repeated_b),
    }


def slip_response(
    frequencies_hz: Sequence[float], slips_cycles: Sequence[int]
) -> dict[str, float]:
    """Ideal phase-jump responses in metres for three ordered frequency channels.

    GF12 is L1-L2. Closure cancels geometry and first-order ionosphere, while its
    response to a slip is a weighted sum of wavelength times slip count.
    """
    if len(frequencies_hz) != 3 or len(slips_cycles) != 3:
        raise ValueError("three frequencies and three slip counts required")
    _finite(*frequencies_hz)
    f1, f2, f3 = frequencies_hz
    if min(frequencies_hz) <= 0 or len(set(frequencies_hz)) != 3:
        raise ValueError("three distinct positive frequencies required")
    r2, r3 = (f1 / f2) ** 2, (f1 / f3) ** 2
    w2 = (r3 - 1) / (r2 - r3)
    weights = (1.0, w2, -1.0 - w2)
    jumps = tuple(C / f * n for f, n in zip(frequencies_hz, slips_cycles, strict=True))
    return {
        "gf12_m": jumps[0] - jumps[1],
        "closure_m": math.fsum(w * x for w, x in zip(weights, jumps, strict=True)),
    }


def slip_detection_matrix(
    frequencies_hz: Sequence[float],
    max_cycles: int,
    gf_threshold_m: float,
    closure_threshold_m: float,
) -> list[dict[str, object]]:
    """Enumerate nonzero signed injected slips and the ideal threshold responses."""
    _finite(gf_threshold_m, closure_threshold_m)
    if not 1 <= max_cycles <= 10 or min(gf_threshold_m, closure_threshold_m) <= 0:
        raise ValueError("max_cycles must be 1..10 and thresholds must be positive")
    out: list[dict[str, object]] = []
    for slips in itertools.product(range(-max_cycles, max_cycles + 1), repeat=3):
        if slips == (0, 0, 0):
            continue
        response = slip_response(frequencies_hz, slips)
        gf = abs(response["gf12_m"]) >= gf_threshold_m
        closure = abs(response["closure_m"]) >= closure_threshold_m
        out.append(
            {
                "slips_cycles": slips,
                **response,
                "gf_detected": gf,
                "closure_detected": closure,
                "either_detected": gf or closure,
            }
        )
    return out


def uncertainty_coverage(
    errors_m: Sequence[float], sigmas_m: Sequence[float], multiplier: float = 1.0
) -> dict[str, float | int]:
    """Empirical per-axis absolute error coverage at multiplier times reported sigma."""
    if len(errors_m) != len(sigmas_m) or not errors_m:
        raise ValueError("at least one paired error and sigma required")
    _finite(*errors_m, *sigmas_m, multiplier)
    if multiplier <= 0 or any(x <= 0 for x in sigmas_m):
        raise ValueError("sigmas and multiplier must be positive")
    covered = sum(
        abs(e) <= multiplier * s for e, s in zip(errors_m, sigmas_m, strict=True)
    )
    return {
        "samples": len(errors_m),
        "covered": covered,
        "fraction": covered / len(errors_m),
        "mean_error_m": math.fsum(errors_m) / len(errors_m),
        "rms_error_m": math.sqrt(math.fsum(e * e for e in errors_m) / len(errors_m)),
    }


def phase_detrended(
    times_s: Sequence[float], phases_m: Sequence[float], max_gap_s: float
) -> dict[str, float | int]:
    """Linear-detrended phase RMS for one gap-free, prevalidated carrier arc."""
    if len(times_s) != len(phases_m) or len(times_s) < 3:
        raise ValueError("at least three paired samples required")
    _finite(*times_s, *phases_m, max_gap_s)
    if max_gap_s <= 0 or any(
        not 0 < b - a <= max_gap_s for a, b in itertools.pairwise(times_s)
    ):
        raise ValueError("times must increase without gaps exceeding max_gap_s")
    t0, p0 = times_s[0], phases_m[0]
    ts = [t - t0 for t in times_s]
    ps = [p - p0 for p in phases_m]
    mt, mp = math.fsum(ts) / len(ts), math.fsum(ps) / len(ps)
    slope = math.fsum(
        (t - mt) * (p - mp) for t, p in zip(ts, ps, strict=True)
    ) / math.fsum((t - mt) ** 2 for t in ts)
    residuals = [p - mp - slope * (t - mt) for t, p in zip(ts, ps, strict=True)]
    return {
        "samples": len(ts),
        "duration_s": ts[-1],
        "slope_m_per_s": slope,
        "residual_rms_m": math.sqrt(math.fsum(x * x for x in residuals) / len(ts)),
        "maximum_gap_s": max(b - a for a, b in itertools.pairwise(times_s)),
    }


def orbit_position_effect(
    los: Sequence[Sequence[float]],
    satellite_delta_m: Sequence[Sequence[float]],
    clock_delta_s: Sequence[float],
    weights: Sequence[float],
) -> dict[str, object]:
    """Linearized receiver ECEF and clock change caused by satellite state changes.

    LOS points from receiver to satellite, and delta means perturbed minus
    reference. Satellite clock changes are in seconds and receiver clock changes
    are in range metres. For fixed observations, the residual is
    -u.dot(delta_sat)+c*delta_clock, and the solution uses H=[-u,1].
    """
    n = len(los)
    if n < 4 or not (len(satellite_delta_m) == len(clock_delta_s) == len(weights) == n):
        raise ValueError("at least four matched satellite states required")
    normal = [[0.0] * 4 for _ in range(4)]
    rhs = [0.0] * 4
    for u, dr, dc, weight in zip(
        los, satellite_delta_m, clock_delta_s, weights, strict=True
    ):
        if len(u) != 3 or len(dr) != 3:
            raise ValueError(
                "line of sight and satellite difference must have 3 components"
            )
        _finite(*u, *dr, dc, weight)
        if weight <= 0 or abs(math.sqrt(math.fsum(x * x for x in u)) - 1) > 1e-6:
            raise ValueError(
                "weights must be positive and line-of-sight vectors unit length"
            )
        row = [-u[0], -u[1], -u[2], 1.0]
        residual = -math.fsum(x * y for x, y in zip(u, dr, strict=True)) + C * dc
        for i in range(4):
            rhs[i] += weight * row[i] * residual
            for j in range(4):
                normal[i][j] += weight * row[i] * row[j]
    matrix = [normal[i] + [rhs[i]] for i in range(4)]
    for i in range(4):
        pivot = max(range(i, 4), key=lambda j: abs(matrix[j][i]))
        if abs(matrix[pivot][i]) < 1e-12 * max(abs(normal[j][j]) for j in range(4)):
            raise ValueError("satellite geometry is singular or ill-conditioned")
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        d = matrix[i][i]
        matrix[i] = [x / d for x in matrix[i]]
        for j in range(4):
            if j != i:
                k = matrix[j][i]
                matrix[j] = [
                    a - k * b for a, b in zip(matrix[j], matrix[i], strict=True)
                ]
    x = [row[4] for row in matrix]
    return {"satellites": n, "ecef_change_m": x[:3], "receiver_clock_change_m": x[3]}
