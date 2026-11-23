"""Read DSP tracking RAM through the boot menu or replay an archived snapshot."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from examples._console import ExampleParser, run, validate_file_paths, write_json
from um982py.experimental import (
    DSP_RECEIVER_MEMORY_WINDOWS,
    DSP_TRACKING_MEMORY_WINDOWS,
    BootMemoryReader,
    DspReceiverDiagnostics,
    DspTrackingChannel,
    extract_dsp_receiver_diagnostics,
    extract_dsp_tracking,
)

DEFAULT_READER = (
    Path(__file__).resolve().parents[2] / "tools" / "boot-reader" / "reader.bin"
)


def _channel_report(channel: DspTrackingChannel) -> dict[str, object]:
    report = asdict(channel)
    observation = channel.observation
    if observation is not None:
        report["observation"]["phase_offset_cycles"] = observation.phase_offset_cycles
    report["raw"] = channel.raw.hex()
    report["constellation"] = channel.constellation
    report["band"] = channel.band
    report["frequency_hz"] = channel.frequency_hz
    report["wavelength_m"] = channel.wavelength_m
    report["glonass_frequency_channel"] = channel.glonass_frequency_channel
    report["doppler_hz"] = channel.doppler_hz
    report["diagnostic_words"] = channel.diagnostic_words
    report["normalized_accumulator"] = channel.normalized_accumulator
    return report


def _receiver_report(dsp: DspReceiverDiagnostics) -> dict[str, object]:
    report = asdict(dsp)
    report["cached_notices"] = [
        {
            "buffer_address": base,
            "name": notice.name,
            "text": notice.raw.decode("latin1"),
        }
        for base, notice in dsp.cached_notices
    ]
    return report


def main(argv: Sequence[str] | None = None) -> int:
    """Capture or replay one UM982 build 25164 tracking snapshot."""
    parser = ExampleParser(prog="python3 -m examples.dsp_tracking", description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--port", help="serial device (default: /dev/ttyUSB0)")
    source.add_argument("--replay", type=Path, metavar="DIR", help="replay RAM windows")
    parser.add_argument("--baud", type=int, default=921600)
    parser.add_argument("--helper", type=Path, default=DEFAULT_READER)
    parser.add_argument(
        "--boot-menu", action="store_true", help="wait for an existing boot prompt"
    )
    parser.add_argument(
        "--save-ram", type=Path, metavar="DIR", help="archive RAM windows"
    )
    parser.add_argument(
        "--receiver-state", action="store_true", help="read additional DSP diagnostics"
    )
    parser.add_argument("--json", type=Path, help="write the decoded records as JSON")
    args = parser.parse_args(argv)

    if args.replay is not None and (
        args.boot_menu or args.save_ram is not None or args.receiver_state
    ):
        parser.error(
            "--boot-menu, --save-ram and --receiver-state require live capture"
        )
    if args.save_ram is not None and args.save_ram.exists():
        parser.error("--save-ram requires a new directory")
    directory = args.replay if args.replay is not None else args.save_ram
    windows: tuple[tuple[str, int, int], ...] = DSP_TRACKING_MEMORY_WINDOWS
    if args.replay is not None or args.receiver_state:
        windows += DSP_RECEIVER_MEMORY_WINDOWS
    if directory is not None:
        validate_file_paths(
            {
                "json": args.json,
                "ram_windows": tuple(
                    directory / f"{name}.bin" for name, _, _ in windows
                ),
            }
        )

    restored = None
    regions = {}
    if args.replay is not None:
        for name, base, length in windows:
            path = args.replay / f"{name}.bin"
            if name not in ("tracking", "channels") and not path.exists():
                continue
            data = path.read_bytes()
            # Old archives hold only the first 157 channel pointers.
            short_channel_table = (
                name == "channels" and 0 < len(data) < length and len(data) % 4 == 0
            )
            if len(data) != length and not short_channel_table:
                raise ValueError(
                    f"{path} contains {len(data)} bytes, expected {length}"
                )
            regions[name] = (base, data)
    else:
        with BootMemoryReader.connect(
            args.port or "/dev/ttyUSB0",
            args.baud,
            helper=args.helper,
            boot_menu_only=args.boot_menu,
        ) as reader:
            regions = {
                name: (base, reader.read_range(base, length))
                for name, base, length in windows
            }
        restored = reader.application_restored
        if args.save_ram is not None:
            args.save_ram.mkdir(parents=True)
            for name, (_, data) in regions.items():
                (args.save_ram / f"{name}.bin").write_bytes(data)

    channels = extract_dsp_tracking(regions)
    dsp = extract_dsp_receiver_diagnostics(regions)
    print(f"DSP tracking snapshot (build 25164), {len(channels)} channels")
    if channels:
        print(
            "  Ch  Signal       Sat  RF  C/N0 dB-Hz   Doppler Hz  Carrier word"
            "       TOW ms  Native time   Scale  Pseudorange m"
        )
    for entry in channels:
        signal = f"{entry.constellation[:3]} {entry.band}"
        satellite = str(entry.satellite_id) if entry.satellite_id is not None else "-"
        doppler = f"{entry.doppler_hz:+.2f}" if entry.doppler_hz is not None else "-"
        observation = entry.observation
        tow = (
            str(observation.gps_tow_ms)
            if observation and (observation.gps_tow_ms is not None)
            else "-"
        )
        native_time = (
            f"{observation.native_time_s:.3f}"
            if observation and observation.native_time_s is not None
            else "-"
        )
        time_scale = observation.native_time_scale if observation else None
        pseudorange = (
            f"{observation.pseudorange_m:.3f}"
            if observation and (observation.pseudorange_m is not None)
            else "-"
        )
        print(
            f"{entry.channel:4d}  {signal:<10}  {satellite:>4}"
            f"  {entry.rf_index:2d}  {entry.cn0_dbhz:9.2f}  {doppler:>11}"
            f"  {entry.carrier_word:12d}  {tow:>11}  {native_time:>11}"
            f"  {time_scale or '-':>5}  {pseudorange:>13}"
        )
    if restored is not None:
        print(f"Application restored {'yes' if restored else 'no'}")
    if dsp.gps_epoch is not None:
        print(f"DSP GPS week {dsp.gps_epoch.week}, TOW {dsp.gps_epoch.tow_ms} ms")
    if dsp.rf_agc_codes is not None:
        print("RF AGC codes " + ", ".join(map(str, dsp.rf_agc_codes)))

    if args.json is not None:
        write_json(
            {
                "firmware_layout": "R4.10Build25164",
                "application_restored": restored,
                "channels": [_channel_report(entry) for entry in channels],
                "receiver_state": _receiver_report(dsp),
            },
            args.json,
        )
    if restored is False:
        return 2
    return 0 if channels else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
