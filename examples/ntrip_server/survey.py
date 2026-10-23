"""Captures RINEX surveys with antenna metadata."""

import argparse
import math
from collections.abc import Sequence

from um982py.capture import capture_records
from um982py.experimental import FirmwareLog
from um982py.messages import Record
from um982py.rinex import export_rinex
from um982py.signals import tracking_signal

PPP_SIGNALS = {
    0: frozenset(("1C", "1W", "1L", "1X", "2C", "2W", "2L", "2S", "2X")),
    3: frozenset(("1X", "1C", "5X", "5Q")),
}


def format_header_record(content: str, *, label: str) -> str:
    if (
        not content.isascii()
        or len(content) > 60
        or any(ord(char) < 32 or ord(char) == 127 for char in content)
    ):
        raise ValueError(f"invalid RINEX {label}")
    return f"{content:<60}{label}"


def has_dual_frequency(records: Sequence[Record], l2c_code: str | None) -> bool:
    """Require supported GPS L1/L2 or Galileo E1/E5a code and phase pairs."""
    for record in records:
        bands: dict[tuple[int, int], set[str]] = {}
        for row in record.records("observations"):
            status = row.integer("tracking_status")
            signal = tracking_signal(status, l2c_code=l2c_code)
            if (
                signal is None
                or signal.rinex_code not in PPP_SIGNALS.get(signal.system, ())
                or status & 0x1400 != 0x1400
            ):
                continue
            if (
                not all(
                    math.isfinite(row.real(name))
                    for name in (
                        "pseudorange",
                        "carrier_phase",
                        "doppler",
                        "cn0",
                        "lock_time",
                    )
                )
                or row.real("pseudorange") <= 0
            ):
                continue
            key = signal.system, row.integer("prn")
            bands.setdefault(key, set()).add(signal.rinex_code[0])
            if len(bands[key]) >= 2:
                return True
    return False


def validate_metadata(
    *,
    marker_name: str,
    antenna_type: str,
    antenna_serial: str,
    receiver_serial: str,
    receiver_firmware: str,
    approx_position: Sequence[float],
    antenna_hen: Sequence[float],
) -> dict[str, str]:
    for value in (
        marker_name,
        antenna_type,
        antenna_serial,
        receiver_serial,
        receiver_firmware,
    ):
        if not value.strip() or len(value) > 20:
            raise ValueError("RINEX identity fields need 1..20 ASCII characters")
        format_header_record(value, label="identity")
    if len(approx_position) != 3 or len(antenna_hen) != 3:
        raise ValueError("position and H/E/N offsets need three components")
    if not all(math.isfinite(value) for value in (*approx_position, *antenna_hen)):
        raise ValueError("position and antenna offsets must be finite")
    if not 6_000_000 < math.hypot(*approx_position) < 7_000_000:
        raise ValueError("approximate marker position must be Earth-surface ECEF")
    if not 0 <= antenna_hen[0] <= 100 or any(abs(v) > 100 for v in antenna_hen[1:]):
        raise ValueError("antenna H/E/N offsets exceed 100 m or have negative height")
    return {
        "REC # / TYPE / VERS": (
            f"{receiver_serial:<20}{'UM982':<20}{receiver_firmware:<20}"
        ),
        "ANT # / TYPE": f"{antenna_serial:<20}{antenna_type:<20}",
        "APPROX POSITION XYZ": "".join(f"{value:14.4f}" for value in approx_position),
        "ANTENNA: DELTA H/E/N": "".join(f"{value:14.4f}" for value in antenna_hen),
    }


def export_survey(
    records: Sequence[Record],
    *,
    marker_name: str,
    antenna_type: str,
    antenna_serial: str,
    receiver_serial: str,
    receiver_firmware: str,
    approx_position: Sequence[float],
    antenna_hen: Sequence[float],
    l2c_code: str | None = None,
) -> str:
    replacements = validate_metadata(
        marker_name=marker_name,
        antenna_type=antenna_type,
        antenna_serial=antenna_serial,
        receiver_serial=receiver_serial,
        receiver_firmware=receiver_firmware,
        approx_position=approx_position,
        antenna_hen=antenna_hen,
    )
    if not has_dual_frequency(records, l2c_code):
        raise ValueError(
            "capture needs supported dual-frequency GPS L1/L2 or GAL E1/E5a"
        )
    exported = export_rinex(records, marker_name=marker_name, l2c_code=l2c_code)
    if exported.omitted:
        print(f"RINEX omitted observations: {exported.omitted}")
    lines = []
    for line in exported.text.splitlines():
        label = line[60:]
        if label == "COMMENT" and line.startswith("Position, antenna offsets"):
            continue
        lines.append(
            format_header_record(replacements[label], label=label)
            if label in replacements
            else line
        )
    return "\n".join(lines) + "\n"


def capture_survey(args: argparse.Namespace) -> None:
    if args.interval < 15 or args.seconds > 172800:
        raise ValueError("survey capture supports 15+ second cadence and at most 48 h")
    metadata = {
        "marker_name": args.marker_name,
        "antenna_type": args.antenna_type,
        "antenna_serial": args.antenna_serial,
        "receiver_serial": args.receiver_serial,
        "receiver_firmware": args.receiver_firmware,
        "approx_position": args.approx_position,
        "antenna_hen": args.antenna_hen,
    }
    validate_metadata(**metadata)
    for source in (args.record, args.replay):
        if source is not None and args.survey_output.resolve() == source.resolve():
            raise ValueError("survey output must differ from wire capture and replay")
    with args.survey_output.open("x", encoding="ascii") as stream:
        captured = capture_records(
            args,
            [FirmwareLog.RANGE],
            interval=args.interval,
            duration=args.seconds,
            frames=math.ceil(args.seconds / args.interval),
        )
        records = captured["RANGE"]
        stream.write(export_survey(records, **metadata, l2c_code=args.l2c_code))
    print(f"Wrote {len(records)} epochs to {args.survey_output}")
