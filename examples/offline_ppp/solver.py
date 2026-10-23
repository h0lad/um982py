"""Static GPS PPP using CSSRlib's Python implementation and CODE products."""

from __future__ import annotations

import csv
import hashlib
import importlib
import importlib.metadata
import json
import math
from copy import deepcopy
from itertools import pairwise
from pathlib import Path
from typing import Any

from um982py.geodesy import geodetic_from_ecef


def validate_rinex_flags(observation: Path, phase_indices: list[int]) -> None:
    """Reject receiver events and LLI flags the selected decoder cannot handle."""
    with observation.open(encoding="ascii") as stream:
        in_body = False
        for line in stream:
            if line[60:].strip() == "END OF HEADER":
                in_body = True
                continue
            if not in_body:
                continue
            if line.startswith(">") and line[31:32] != "0":
                raise ValueError("RINEX event epochs are not supported by this solver")
            if line.startswith("G"):
                for index in phase_indices:
                    flag = line[16 * index + 17 : 16 * index + 18]
                    if flag not in ("", " ", "0", "1"):
                        raise ValueError("unsupported carrier-phase LLI flag")


def process_observations(
    observation: Path, paths: list[Path], antex: Path, output: Path
) -> dict[str, Any]:
    """Process RINEX with CSSRlib. Output is experimental float PPP."""
    try:
        gnss = importlib.import_module("cssrlib.gnss")
        rinex = importlib.import_module("cssrlib.rinex")
        precise = importlib.import_module("cssrlib.peph")
        solver = importlib.import_module("cssrlib.pppssr")
        np = importlib.import_module("numpy")
    except ModuleNotFoundError as error:
        raise ValueError(
            "Python PPP dependencies are missing; install "
            "examples/offline_ppp/requirements.txt"
        ) from error
    if solver.__file__ is None:
        raise ValueError("CSSRlib solver module has no source file")

    reader = rinex.rnxdec()
    if reader.decode_obsh(str(observation)) != 0:
        raise ValueError("unsupported RINEX observation file")
    if (
        not all(math.isfinite(float(x)) for x in reader.pos)
        or np.linalg.norm(reader.pos) < 6_000_000
    ):
        raise ValueError("RINEX needs approximate marker ECEF coordinates in metres")

    available = {str(sig) for sig in reader.sig_map.get(gnss.uGNSS.GPS, {}).values()}
    pair = next(
        (
            (first, second)
            for first in ("1C", "1W", "1L", "1X")
            for second in ("2W", "2L", "2S", "2X")
            if all(
                "G" + kind + band in available
                for band in (first, second)
                for kind in ("C", "L", "S")
            )
        ),
        None,
    )
    if pair is None:
        raise ValueError(
            "GPS L1/L2 code, carrier phase and signal strength are required"
        )
    sigs = [gnss.rSigRnx("G" + kind + band) for kind in "CLS" for band in pair]
    reader.setSignals(sigs)

    # This CSSRlib revision treats only LLI value 1 as a slip. Reject other set
    # bits instead of silently accepting an unresolved half-cycle ambiguity.
    phase_indices = [
        i
        for i, signal in reader.sig_map[gnss.uGNSS.GPS].items()
        if str(signal) in {"GL" + band for band in pair}
    ]
    validate_rinex_flags(observation, phase_indices)

    nav = gnss.Nav(nf=2)
    nav.pmode = 0
    for i, path in enumerate(sorted(p for p in paths if p.suffix == ".nav")):
        reader.decode_nav(str(path), nav, append=i > 0)
    orbit = precise.peph()
    for path in sorted(p for p in paths if p.suffix == ".sp3"):
        orbit.parse_sp3(str(path), nav)
    orbit_map = {(item.time.time, item.time.sec): item for item in nav.peph}
    nav.peph = [orbit_map[key] for key in sorted(orbit_map)]
    nav.ne = len(nav.peph)
    clocks: list[Any] = []
    for path in sorted(p for p in paths if p.suffix == ".clk"):
        day_nav = gnss.Nav(nf=2)
        reader.decode_clk(str(path), day_nav)
        clocks.extend(day_nav.pclk)
    clock_map = {(item.time.time, item.time.sec): item for item in clocks}
    nav.pclk = [clock_map[key] for key in sorted(clock_map)]
    nav.nc = len(nav.pclk)
    if not nav.ne or not nav.nc:
        raise ValueError("precise orbit or clock file contains no usable records")
    for records, maximum_gap, label in (
        (nav.peph, 301, "orbit"),
        (nav.pclk, 31, "clock"),
    ):
        if any(
            gnss.timediff(later.time, earlier.time) > maximum_gap
            for earlier, later in pairwise(records)
        ):
            raise ValueError(f"precise {label} product contains an epoch gap")
    bias = precise.biasdec()
    for path in sorted(p for p in paths if p.suffix == ".bia"):
        bias.parse(str(path))
    if not bias.osb:
        raise ValueError("no observable-specific biases found")
    calibrations = precise.atxdec()
    calibrations.readpcv(str(antex))
    nav.sat_ant = calibrations.pcvs
    nav.rcv_ant = deepcopy(precise.searchpcv(calibrations.pcvr, reader.ant, reader.ts))
    if nav.rcv_ant is None:
        raise ValueError(
            "no receiver antenna calibration valid at the observation date"
        )
    # ANTEX offsets are in mm and reader.ecc is the measured E/N/U marker-to-ARP
    # offset in metres. The resulting state refers to the marker.
    for sig in nav.rcv_ant.off:
        nav.rcv_ant.off[sig] += reader.ecc * 1000
    config = deepcopy(gnss.default_config)
    config["nav"]["csmooth"] = False
    ppp = solver.pppos(nav, reader.pos, config=config)
    nav.ephopt = 4
    nav.armode = 0
    nav.tidecorr = gnss.uTideModel.SIMPLE
    nav.elmin = np.deg2rad(10.0)
    nav.q[:3] = 0.0
    nav.monlevel = 0
    count = 0
    outside_coverage = 0
    no_gps = 0
    solver_rejected = 0
    received = 0
    satellite_total = 0
    satellite_min: int | None = None
    satellite_max = 0
    first: dict[str, Any] | None = None
    first_time = None
    last_time = None
    previous = None
    last: dict[str, Any] | None = None
    with (output / "solution.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "gps_time",
                "x_m",
                "y_m",
                "z_m",
                "latitude_deg",
                "longitude_deg",
                "ellipsoidal_height_m",
                "satellites",
            ]
        )
        try:
            while True:
                obs = reader.decode_obs()
                if obs.t.time == 0:
                    break
                received += 1
                if previous is not None and gnss.timediff(obs.t, previous) <= 0:
                    raise ValueError("observation epochs must increase strictly")
                previous = obs.t
                if len(obs.sat) == 0:
                    no_gps += 1
                    continue
                # Leave a margin for the signal transmit time: CSSRlib otherwise
                # extrapolates beyond a product boundary for up to 15 minutes.
                if any(
                    gnss.timediff(obs.t, records[0].time) < 1.0
                    or gnss.timediff(records[-1].time, obs.t) < 0.0
                    for records in (nav.peph, nav.pclk)
                ):
                    outside_coverage += 1
                    continue
                if precise.searchpcv(calibrations.pcvr, reader.ant, obs.t) is None:
                    raise ValueError(
                        "receiver calibration expires during the occupation"
                    )
                if nav.t.time == 0:
                    nav.t = obs.t
                status = ppp.process(obs, orb=orbit, bsx=bias)
                if status != 0 or not all(math.isfinite(float(x)) for x in nav.x[:3]):
                    solver_rejected += 1
                    continue
                xyz = [float(x) for x in nav.x[:3]]
                latitude, longitude, height = geodetic_from_ecef(*xyz)
                last = {
                    "gps_time": gnss.time2str(obs.t),
                    "ecef_m": xyz,
                    "latitude_deg": latitude,
                    "longitude_deg": longitude,
                    "ellipsoidal_height_m": height,
                    "satellites": int(nav.nsat[2]),
                }
                if first is None:
                    first = last
                    first_time = obs.t
                last_time = obs.t
                satellites = int(nav.nsat[2])
                satellite_total += satellites
                satellite_min = (
                    satellites
                    if satellite_min is None
                    else min(satellite_min, satellites)
                )
                satellite_max = max(satellite_max, satellites)
                writer.writerow(
                    [
                        last["gps_time"],
                        *xyz,
                        latitude,
                        longitude,
                        height,
                        last["satellites"],
                    ]
                )
                count += 1
        finally:
            reader.fobs.close()
    distribution = importlib.metadata.distribution("cssrlib")
    source = json.loads(distribution.read_text("direct_url.json") or "{}")
    return {
        "status": "ppp_output" if count else "no_ppp_solution",
        "engine": "cssrlib",
        "engine_version": distribution.version,
        "engine_source": source or None,
        "engine_solver_sha256": hashlib.sha256(
            Path(solver.__file__).read_bytes()
        ).hexdigest(),
        "numerical_dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "scipy", "numba")
        },
        "signals": list(pair),
        "epochs_received": received,
        "epochs_without_gps": no_gps,
        "epochs_outside_product_coverage": outside_coverage,
        "epochs_solver_rejected": solver_rejected,
        "ppp_epochs": count,
        "satellites_used": {
            "minimum": satellite_min,
            "maximum": satellite_max if count else None,
            "mean": satellite_total / count if count else None,
        },
        "first_ppp_epoch": first,
        "last_ppp_epoch": last,
        "solution_span_seconds": gnss.timediff(last_time, first_time)
        if last_time is not None and first_time is not None
        else None,
        "first_to_last_displacement_m": math.dist(first["ecef_m"], last["ecef_m"])
        if first is not None and last is not None
        else None,
    }
