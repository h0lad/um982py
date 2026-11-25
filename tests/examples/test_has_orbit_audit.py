"""Checks HAS correction geometry, slot mapping and an end-to-end SISRE audit."""

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest
from examples.has_orbit_audit import (
    BroadcastState,
    apc_reference,
    apply_has,
    broadcast_state,
    correction_timeline,
    ntw_axes,
    snapshot_at,
    usable_ephemeris,
)
from examples.has_orbit_audit.__main__ import main

from um982py.capture import load_records
from um982py.commands import Log
from um982py.gnss import SPEED_OF_LIGHT, has_epoch
from um982py.messages import Record
from um982py.messages.corrections import (
    Availability,
    Correction,
    HasSatelliteCorrection,
    has_satellite_corrections,
)
from um982py.messages.frames import BinaryHeader, BinaryMessage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
HAS = FIXTURES / "captures-extra"
MASK, ORBIT, CLOCK = (
    load_records(HAS / f"{log.value}B.bin", log)[0]
    for log in (Log.E6MASKBLOCK, Log.E6ORBITBLOCK, Log.E6CLOCKFULLBLOCK)
)
EPHEMERIDES = load_records(FIXTURES / "captures-live" / "GALEPHB.bin", Log.GALEPH)
EPOCH = 1476717000.0
"""An SP3 epoch after the GALEPH fixture was received."""


def metres(value: float) -> Correction:
    return Correction(round(value / 0.0025), value, Availability.AVAILABLE)


def correction(
    radial: float = 0.0,
    in_track: float = 0.0,
    cross_track: float = 0.0,
    clock: float | None = 0.0,
) -> HasSatelliteCorrection:
    return HasSatelliteCorrection(
        2,
        1,
        7,
        0,
        metres(radial),
        metres(in_track),
        metres(cross_track),
        None if clock is None else metres(clock),
    )


EQUATORIAL = BroadcastState(
    "E01", 7, (29_600_000.0, 0.0, 0.0), (0.0, 3_000.0, 0.0), 1e-4
)


def test_ntw_axes_follow_the_has_icd_definitions() -> None:
    radial, in_track, cross_track = ntw_axes(EQUATORIAL.position, EQUATORIAL.velocity)
    assert radial == (1.0, 0.0, 0.0)
    assert in_track == (0.0, 1.0, 0.0)
    assert cross_track == (0.0, 0.0, 1.0)


def test_corrections_are_added_to_the_broadcast_state() -> None:
    applied = apply_has(EQUATORIAL, correction(1.0, 2.0, 3.0, clock=0.3))
    assert applied is not None
    position, clock = applied
    assert position == pytest.approx((29_600_001.0, 2.0, 3.0))
    assert clock == pytest.approx(1e-4 + 0.3 / SPEED_OF_LIGHT, abs=1e-18)


def test_unavailable_clock_withholds_the_correction() -> None:
    assert apply_has(EQUATORIAL, correction(clock=None)) is None
    unavailable = replace(
        correction(), radial=Correction(-4096, None, Availability.UNAVAILABLE)
    )
    assert apply_has(EQUATORIAL, unavailable) is None


def test_receiver_slots_follow_the_mask_order() -> None:
    corrections = has_satellite_corrections(MASK, ORBIT, CLOCK)
    assert sum(key[0] == 0 for key in corrections) == 22
    assert sum(key[0] == 2 for key in corrections) == 25
    first = corrections[0, 1]
    assert first.iod_ref == 9
    assert first.radial.meters == pytest.approx(-36 * 0.0025)
    assert first.in_track.meters == pytest.approx(19 * 0.008)
    assert first.clock is not None
    assert first.clock.meters == pytest.approx(-174 * 0.0025)


def test_blocks_of_another_iod_set_are_refused() -> None:
    entries = dict(ORBIT)
    entries["iod_set_id"] = 2
    with pytest.raises(ValueError, match="another HAS mask"):
        has_satellite_corrections(
            MASK, replace(ORBIT, entries=tuple(entries.items())), CLOCK
        )


def test_time_of_hour_resolves_to_the_hour_before_receipt() -> None:
    assert has_epoch(7_200 + 10.0, 5) == 7_205
    assert has_epoch(7_200 + 10.0, 3_590) == 7_200 - 10
    with pytest.raises(ValueError, match=r"0\.\.3599"):
        has_epoch(0.0, 3_600)


def test_centre_of_mass_moves_towards_the_earth() -> None:
    assert apc_reference((10.0, 0.0, 0.0), 0.75) == (9.25, 0.0, 0.0)


def at(record: Record, gps_seconds: float, entries: dict[str, object]) -> Record:
    """Move a fixture record to another receipt time with replaced fields."""
    message = record.message
    assert isinstance(message, BinaryMessage)
    assert isinstance(message.header, BinaryHeader)
    week, seconds = divmod(gps_seconds, 604_800)
    header = replace(message.header, week=int(week), milliseconds=round(seconds * 1e3))
    return replace(
        record,
        entries=tuple(entries.items()),  # type: ignore[arg-type]
        message=replace(message, header=header),
    )


def corrected_scenario() -> tuple[list[Record], dict[str, tuple[float, ...]]]:
    """HAS records for the fixture satellites and the HAS-corrected truth."""
    healthy = [record for record in EPHEMERIDES if usable_ephemeris(record)]
    satellites = sorted({record.integer("satid") for record in healthy})
    assert len(satellites) >= 4
    latest = {record.integer("satid"): record for record in healthy}
    mask_bits = bytearray(5)
    for prn in satellites:
        mask_bits[(prn - 1) // 8] |= 0x80 >> ((prn - 1) % 8)
    system = dict(MASK.records("systems")[1])
    system["satellite_mask"] = bytes(mask_bits)
    received = EPOCH - 5
    toh = int(received % 3600)
    mask = dict(MASK) | {
        "toh": toh,
        "system_count": 1,
        "systems": (
            replace(MASK.records("systems")[1], entries=tuple(system.items())),
        ),
    }
    slots = [
        replace(
            ORBIT.records("corrections")[0],
            entries=(
                ("iod_ref", latest[prn].integer("iodnav")),
                ("radial", 40 * index - 100),
                ("in_track", 25 - 10 * index),
                ("cross_track", 15),
            ),
        )
        for index, prn in enumerate(satellites)
    ]
    orbit = dict(ORBIT) | {
        "toh": toh,
        "corrections": tuple(slots) + ORBIT.records("corrections")[len(slots) :],
    }
    clocks = tuple(60 * index - 150 for index in range(len(satellites)))
    clock = dict(CLOCK) | {
        "toh": toh,
        "delta_clock_multipliers": (0, 0, 0, 0),
        "delta_clock_corrections": clocks + (0,) * (68 - len(clocks)),
    }
    records = [
        at(MASK, received, mask),
        at(ORBIT, received, orbit),
        at(CLOCK, received, clock),
    ]
    snapshot = snapshot_at(correction_timeline(records), EPOCH)
    assert snapshot is not None
    truth: dict[str, tuple[float, ...]] = {}
    for prn in satellites:
        state = broadcast_state(latest[prn], EPOCH)
        applied = apply_has(state, snapshot.corrections[2, prn])
        assert applied is not None
        (x, y, z), clock_seconds = applied
        truth[state.satellite] = (x, y, z, clock_seconds + 2e-9)
    return records, truth


def sp3(truth: dict[str, tuple[float, ...]]) -> str:
    """A one-epoch GPS-time SP3-d product of the given truth states."""
    lines = [
        "#dP2026 10 21 21  0  0.00000000       1 ORBIT IGS20 FIT  TEST",
        "%c M  cc GPS ccc cccc cccc cccc cccc ccccc ccccc ccccc ccccc",
        "*  2026 10 22 15 10  0.00000000",
    ]
    for satellite, (x, y, z, clock) in sorted(truth.items()):
        lines.append(
            f"P{satellite}{x / 1e3:14.6f}{y / 1e3:14.6f}{z / 1e3:14.6f}"
            f"{clock * 1e6:14.6f}"
        )
    return "\n".join([*lines, "EOF", ""])


def test_has_corrected_truth_scores_zero_while_broadcast_does_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    records, truth = corrected_scenario()
    product = tmp_path / "truth.sp3"
    text = sp3(truth)
    product.write_text(text)
    epoch_line = text.splitlines()[2].split()[1:]
    assert epoch_line == ["2026", "10", "22", "15", "10", "0.00000000"]

    def capture(args: object, logs: object, **options: object) -> dict[str, object]:
        arrival = options["arrival_order"]
        assert isinstance(arrival, list)
        arrival.extend(records)
        return {"GPSEPH": (), "GALEPH": EPHEMERIDES}

    monkeypatch.setattr("examples.has_orbit_audit.__main__.capture_logs", capture)
    report = tmp_path / "report.json"
    assert main(["--sp3", str(product), "--systems", "E", "--json", str(report)]) == 0
    result = json.loads(report.read_text())
    galileo = result["sisre_m"]["E"]
    assert galileo["has"]["samples"] == len(truth)
    assert galileo["has"]["rms_m"] < 0.005
    assert galileo["broadcast"]["rms_m"] > 0.1
    assert math.isfinite(galileo["broadcast"]["maximum_m"])
