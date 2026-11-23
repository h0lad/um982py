"""Read DSP tracking RAM through the boot menu or replay an archived snapshot."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from math import degrees
from pathlib import Path

from examples._console import ExampleParser, run, validate_file_paths, write_json
from um982py.experimental import (
    DSP_EPHEMERIS_MEMORY_WINDOWS,
    DSP_RECEIVER_MEMORY_WINDOWS,
    DSP_SATELLITE_STATE_FILES,
    DSP_TRACKING_CLOCK_REFERENCE_WINDOW,
    DSP_TRACKING_MEMORY_WINDOWS,
    BootMemoryReader,
    DspGalileoEphemeris,
    DspGlonassEphemeris,
    DspGlonassPropagationRecord,
    DspKeplerEphemeris,
    DspReceiverDiagnostics,
    DspSatellitePosition,
    DspTrackingChannel,
    extract_dsp_ephemerides,
    extract_dsp_glonass_propagation,
    extract_dsp_receiver_diagnostics,
    extract_dsp_satellite_positions,
    extract_dsp_tracking,
    read_dsp_satellite_state_windows,
)

DEFAULT_READER = (
    Path(__file__).resolve().parents[2] / "tools" / "boot-reader" / "reader.bin"
)


def _channel_report(channel: DspTrackingChannel) -> dict[str, object]:
    report = asdict(channel)
    report.pop("address", None)
    observation = channel.observation
    if observation is not None:
        report["observation"].pop("address", None)
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
            "name": notice.name,
            "text": notice.raw.decode("latin1"),
        }
        for _, notice in dsp.cached_notices
    ]
    return report


def _value(value: object, spec: str = "") -> str:
    if value is None:
        return "-"
    return format(value, spec) if spec else str(value)


def _print_receiver_state(dsp: DspReceiverDiagnostics, restored: bool | None) -> None:
    epoch = (
        f"{dsp.gps_epoch.week}:{dsp.gps_epoch.tow_ms}"
        if dsp.gps_epoch is not None
        else "-"
    )
    agc = "/".join(str(code) for code in dsp.rf_agc_codes) if dsp.rf_agc_codes else "-"
    adc = (
        f"{dsp.sensor_adc.channel}:{dsp.sensor_adc.value_1}/{dsp.sensor_adc.value_2}"
        if dsp.sensor_adc is not None
        else "-"
    )
    iono = (
        f"{dsp.gps_ionosphere.flags[0]}/{dsp.gps_ionosphere.flags[1]}"
        if dsp.gps_ionosphere is not None
        else "-"
    )
    restored_text = "-" if restored is None else "yes" if restored else "no"
    print(
        f"RX epoch={epoch} agc={agc} adc={adc} iono={iono} "
        f"notices={len(dsp.cached_notices)} navpos={len(dsp.nav_positions)} "
        f"navvel={len(dsp.nav_velocities)} restored={restored_text}"
    )
    if dsp.nav_positions:
        position = dsp.nav_positions[-1]
        print(
            f"  NAVPOS t={position.tag} type={position.position_type} "
            f"lat={position.latitude_deg:.6f} lon={position.longitude_deg:.6f} "
            f"h={position.height_m:.3f} ecef={position.x_m:.3f}/"
            f"{position.y_m:.3f}/{position.z_m:.3f}"
        )
    if dsp.nav_velocities:
        velocity = dsp.nav_velocities[-1]
        print(
            f"  NAVVEL age={velocity.age} v={velocity.values[0]:.3f}/"
            f"{velocity.values[1]:.3f}/{velocity.values[2]:.3f} "
            f"extra={velocity.values[3]:.3f}/{velocity.values[4]:.3f}/"
            f"{velocity.trailing:.3f}"
        )


def _print_channels(channels: Sequence[DspTrackingChannel]) -> None:
    print(f"CH n={len(channels)}")
    if not channels:
        return
    print(
        " CH SIGNAL     ID RF    CN0   DOPPLER      CARRIER        TOW"
        "     NATIVE SCL       PRANGE    PRCORR  PHASEOFF  LOCK EPOCH"
    )
    for entry in channels:
        observation = entry.observation
        satellite = _value(entry.satellite_id)
        doppler = _value(entry.doppler_hz, "+9.2f")
        tow = _value(observation.gps_tow_ms if observation else None)
        native = _value(observation.native_time_s if observation else None, ".3f")
        scale = observation.native_time_scale if observation else None
        pseudorange = _value(observation.pseudorange_m if observation else None, ".3f")
        prcorr = _value(
            observation.range_correction_m if observation else None, "+8.1f"
        )
        phase_offset = _value(
            observation.phase_offset_cycles if observation else None, "+9.4f"
        )
        lock = _value(observation.phase_lock_ms if observation else None)
        epoch = _value(observation.epoch_counter if observation else None)
        print(
            f"{entry.channel:3d} {entry.constellation[:3]}/{entry.band:<3} "
            f"{satellite:>3} {entry.rf_index:2d} {entry.cn0_dbhz:6.2f} "
            f"{doppler:>9} {entry.carrier_word:12d} {tow:>9} "
            f"{native:>10} {scale or '-':>4} {pseudorange:>13} "
            f"{prcorr:>8} {phase_offset:>9} {lock:>5} {epoch:>5}"
        )


def _print_satellites(satellites: Sequence[DspSatellitePosition]) -> None:
    print(f"SAT n={len(satellites)}")
    if not satellites:
        return
    print(
        "SYS  ID SID     RADIUS     ELEV      AZ       RANGE          PR"
        "      RATE  AGE       T1       T2  FLAGS FREQ"
    )
    for position in satellites:
        elevation = (
            f"{degrees(position.elevation_rad):7.2f}"
            if position.elevation_rad is not None
            else "      -"
        )
        azimuth = (
            f"{degrees(position.azimuth_rad):8.2f}"
            if position.azimuth_rad is not None
            else "       -"
        )
        print(
            f"{position.constellation[:3]:>3} {position.satellite_id:3d} "
            f"{position.receiver_id:3d} {position.radius_m:10.0f} "
            f"{elevation} {azimuth} "
            f"{_value(position.range_m, '12.1f'):>12} "
            f"{_value(position.pseudorange_m, '14.1f'):>14} "
            f"{_value(position.approach_rate_mps, '+8.1f'):>8} "
            f"{_value(position.broadcast_ephemeris_age_s):>4} "
            f"{_value(position.state_time_ms):>8} "
            f"{_value(position.secondary_time_ms):>8} "
            f"{position.state_flags:08x} "
            f"{_value(position.glonass_frequency_channel):>4}"
        )


def _compact(data: dict[str, object]) -> str:
    return " ".join(f"{key}={_value(value)}" for key, value in data.items())


def _print_channel_details(channels: Sequence[DspTrackingChannel]) -> None:
    print(f"CHX n={len(channels)}")
    for entry in channels:
        calibration = entry.calibration
        cal = (
            f"{calibration.reference_word}/{calibration.hz_per_count:.9g}/"
            f"{calibration.effective_sample_clock_hz:.9g}"
            if calibration is not None
            else "-"
        )
        diagnostics = ",".join(f"{word:08x}" for word in entry.diagnostic_words)
        detail = {
            "ch": entry.channel,
            "fam": f"0x{entry.signal_family:02x}",
            "svid": entry.svid,
            "trk": entry.tracking_svid,
            "state": entry.state,
            "status": f"0x{entry.tracking_status:08x}",
            "lock": entry.lock_count,
            "addr": f"0x{entry.address:06x}",
            "freq": f"{entry.frequency_hz:.3f}",
            "wl": f"{entry.wavelength_m:.9f}",
            "dop": _value(entry.doppler_hz, "+.2f"),
            "norm": _value(entry.normalized_accumulator, ".3f"),
            "cal": cal,
            "diag": diagnostics,
            "raw": entry.raw.hex(),
        }
        print(f"  {_compact(detail)}")
        observation = entry.observation
        if observation is None:
            continue
        obs = asdict(observation)
        obs.pop("address", None)
        obs["addr"] = f"0x{observation.address:06x}"
        obs["phase_offset_cycles"] = observation.phase_offset_cycles
        print(f"  OBS ch={entry.channel} {_compact(obs)}")


def _print_receiver_details(dsp: DspReceiverDiagnostics) -> None:
    ionosphere = dsp.gps_ionosphere
    alpha = ionosphere.alpha if ionosphere else ()
    beta = ionosphere.beta if ionosphere else ()
    flags = ionosphere.flags if ionosphere else ()
    print(
        f"RXD iono_a={alpha} iono_b={beta} iono_flags={flags} "
        f"notices={len(dsp.cached_notices)} navpos={len(dsp.nav_positions)} "
        f"navvel={len(dsp.nav_velocities)}"
    )
    for position in dsp.nav_positions:
        print(f"  NAVP {_compact(asdict(position))}")
    for velocity in dsp.nav_velocities:
        print(f"  NAVV {_compact(asdict(velocity))}")
    for base, notice in dsp.cached_notices:
        text = notice.raw.decode("latin1").rstrip("\r\n")
        print(f"  NOTE base=0x{base:06x} name={notice.name} text={text!r}")


def _print_ephemerides(
    ephemerides: Sequence[
        DspKeplerEphemeris | DspGalileoEphemeris | DspGlonassEphemeris
    ],
) -> None:
    print(f"EPH n={len(ephemerides)}")
    for entry in ephemerides:
        data = asdict(entry)
        if isinstance(entry, DspKeplerEphemeris):
            data["gps_week"] = entry.gps_week
            data["iode"] = entry.iode
        elif isinstance(entry, DspGalileoEphemeris):
            data["gps_week"] = entry.gps_week
        print(f"  {_compact(data)}")


def _print_glonass_propagation(
    records: Sequence[DspGlonassPropagationRecord],
) -> None:
    print(f"GLOPROP n={len(records)}")
    for record in records:
        print(f"  {_compact(asdict(record))}")


def main(argv: Sequence[str] | None = None) -> int:
    """Capture or replay a per-channel UM982 tracking snapshot."""
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
    parser.add_argument(
        "--satellite-states",
        action="store_true",
        help="read per-constellation satellite ECEF state tables",
    )
    parser.add_argument("--json", type=Path, help="write the decoded records as JSON")
    args = parser.parse_args(argv)

    if args.replay is not None and (
        args.boot_menu
        or args.save_ram is not None
        or args.receiver_state
        or args.satellite_states
    ):
        parser.error(
            "--boot-menu, --save-ram, --receiver-state and --satellite-states "
            "require live capture"
        )
    if args.save_ram is not None and args.save_ram.exists():
        parser.error("--save-ram requires a new directory")
    directory = args.replay if args.replay is not None else args.save_ram
    windows: tuple[tuple[str, int, int], ...] = (
        *DSP_TRACKING_MEMORY_WINDOWS,
        DSP_TRACKING_CLOCK_REFERENCE_WINDOW,
        *DSP_EPHEMERIS_MEMORY_WINDOWS,
    )
    if args.replay is not None or args.receiver_state:
        windows += DSP_RECEIVER_MEMORY_WINDOWS
    if args.satellite_states and not any(name == "gps_time" for name, _, _ in windows):
        windows += tuple(
            item for item in DSP_RECEIVER_MEMORY_WINDOWS if item[0] == "gps_time"
        )
    if directory is not None:
        ram_files = tuple(directory / f"{name}.bin" for name, _, _ in windows)
        if args.satellite_states:
            ram_files += tuple(
                directory / f"{name}.bin" for name in DSP_SATELLITE_STATE_FILES
            )
        validate_file_paths({"json": args.json, "ram_windows": ram_files})

    restored = None
    regions = {}
    satellite_state_data = {}
    if args.replay is not None:
        for name in DSP_SATELLITE_STATE_FILES:
            path = args.replay / f"{name}.bin"
            if path.exists():
                satellite_state_data[name] = path.read_bytes()
        for name, base, length in windows:
            path = args.replay / f"{name}.bin"
            if name not in ("tracking", "channels") and not path.exists():
                continue
            data = path.read_bytes()
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
            if args.satellite_states:
                satellite_state_data = read_dsp_satellite_state_windows(reader)
        restored = reader.application_restored
        if args.save_ram is not None:
            args.save_ram.mkdir(parents=True)
            for name, (_, data) in regions.items():
                (args.save_ram / f"{name}.bin").write_bytes(data)
            for name, data in satellite_state_data.items():
                (args.save_ram / f"{name}.bin").write_bytes(data)

    channels = extract_dsp_tracking(regions)
    dsp = extract_dsp_receiver_diagnostics(regions)
    satellite_positions = extract_dsp_satellite_positions(satellite_state_data)
    ephemeris_regions = {name: data for name, (_, data) in regions.items()}
    ephemerides = extract_dsp_ephemerides(ephemeris_regions)
    glonass_propagation = extract_dsp_glonass_propagation(ephemeris_regions)
    print(f"DSP n={len(channels)} sats={len(satellite_positions)}")
    _print_receiver_state(dsp, restored)
    _print_channels(channels)
    if satellite_state_data:
        _print_satellites(satellite_positions)
    print("DETAIL")
    _print_channel_details(channels)
    _print_receiver_details(dsp)
    _print_ephemerides(ephemerides)
    _print_glonass_propagation(glonass_propagation)

    if args.json is not None:
        report = {
            "application_restored": restored,
            "channels": [_channel_report(entry) for entry in channels],
            "receiver_state": _receiver_report(dsp),
        }
        if satellite_state_data:
            report["satellite_positions"] = [
                asdict(position) for position in satellite_positions
            ]
        report["broadcast_ephemerides"] = [asdict(entry) for entry in ephemerides]
        report["glonass_propagation"] = [asdict(entry) for entry in glonass_propagation]
        write_json(report, args.json)
    if restored is False:
        return 2
    return 0 if channels else 1


if __name__ == "__main__":
    raise SystemExit(run(main))
