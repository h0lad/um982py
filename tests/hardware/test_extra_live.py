"""New diagnostic APIs must consume real frames and preserve receiver state."""

import json
import math
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

import pytest

from um982py import Receiver, export_rinex, gnss_range_samples
from um982py.capture import capture_live, record_epoch
from um982py.commands import Log, configuration
from um982py.diagnostics import (
    DOCTOR_LOGS,
    PPP_LOGS,
    RTK_LOGS,
    collect_diagnostics,
    doctor,
    ppp_diagnostics,
    rtk_diagnostics,
)
from um982py.experimental import (
    FirmwareLog,
    InternalDebugLog,
    capture_internal_debug,
    parse_mpt_debug,
    parse_pos_debug,
    parse_ppp_debug,
)
from um982py.experimental.capture import receiver_state
from um982py.experimental.tracking import tracking_slots
from um982py.messages import Record
from um982py.rinex import _observation

pytestmark = pytest.mark.hardware


@pytest.fixture
def device(request: pytest.FixtureRequest) -> Iterator[Receiver]:
    with Receiver.connect(
        request.config.getoption("--hardware-port"),
        request.config.getoption("--hardware-baud"),
        timeout=3,
    ) as receiver:
        before = receiver_state(receiver)
        try:
            yield receiver
        finally:
            assert receiver_state(receiver) == before


def save(request: pytest.FixtureRequest, name: str, payload: object) -> None:
    path = Path(request.config.getoption("--hardware-report"))
    path.with_name(f"extended-{name}.json").write_text(
        json.dumps(payload, indent=2, default=str) + "\n"
    )


def test_live_range_and_obsv_report_same_receiver_phases(device: Receiver) -> None:
    """Compare same-epoch receiver logs, not independent phase alignment."""
    captured = capture_live(
        device, [FirmwareLog.RANGE, Log.OBSVM], duration=10, interval=1
    )
    ranges = {record_epoch(item): item for item in captured["RANGE"]}
    obsv = {record_epoch(item): item for item in captured["OBSVM"]}
    shared = ranges.keys() & obsv.keys()
    if not shared:
        pytest.skip("receiver produced no shared observation epochs")

    def rows(record: Record) -> dict[tuple[int, int, bool], tuple[float, bool, bool]]:
        result = {}
        for item in record.records("observations"):
            row = _observation(item, record.name)
            status = row.integer("tracking_status")
            if (status >> 16) & 7:
                continue
            key = (row.integer("prn"), (status >> 21) & 31, bool(status & (1 << 26)))
            result[key] = (
                row.real("carrier_phase"),
                bool(status & 0x400),
                bool(status & 0x1000),
            )
        return result

    compared = 0
    for epoch in shared:
        a, b = rows(ranges[epoch]), rows(obsv[epoch])
        for key in a.keys() & b.keys():
            assert a[key][1:] == b[key][1:]
            if a[key][1]:
                assert a[key][0] == pytest.approx(b[key][0], abs=1e-4)
                compared += 1
    if not compared:
        pytest.skip("no shared valid GPS carrier phases")


def test_live_both_antenna_carriers_and_doctor(
    device: Receiver,
    request: pytest.FixtureRequest,
) -> None:
    capture = collect_diagnostics(device, DOCTOR_LOGS, seconds=3)
    report = doctor(capture, antenna=2)
    assert capture.configuration_restored and capture.subscriptions_restored
    results = {}
    # These frequencies were observed on this setup.
    frequencies = {
        (0, 0): 1575420000,
        (0, 3): 1575420000,
        (0, 6): 1176450000,
        (0, 9): 1227600000,
        (0, 11): 1575420000,
        (0, 14): 1176450000,
        (0, 17): 1227600000,
        (1, 6): 1202025000,
        (1, 7): 1202025000,
        (2, 0): 1575420000,
        (3, 1): 1575420000,
        (3, 2): 1575420000,
        (3, 12): 1176450000,
        (3, 17): 1207140000,
        (3, 18): 1278750000,
        (3, 22): 1278750000,
        (4, 0): 1561098000,
        (4, 4): 1561098000,
        (4, 5): 1207140000,
        (4, 6): 1268520000,
        (4, 8): 1575420000,
        (4, 12): 1176450000,
        (4, 13): 1207140000,
        (4, 17): 1207140000,
        (4, 21): 1268520000,
        (4, 23): 1575420000,
        (4, 28): 1176450000,
    }
    for name in ("RANGE", "RANGEH"):
        record = capture.records[name][-1]
        samples = gnss_range_samples(record)
        assert samples and record.integer("count") > 0
        assert any(s.key.system == 0 and s.key.signal == 9 for s in samples)
        for sample in samples:
            row = next(
                o
                for o in record.records("observations")
                if o.integer("prn") == sample.key.prn
                and o.integer("tracking_status") >> 16 & 7 == sample.key.system
                and o.integer("tracking_status") >> 21 & 31 == sample.key.signal
            )
            if sample.key.system == 1:
                k = row.integer("frequency_channel") - 7
                frequency = (
                    (1602 + 0.5625 * k)
                    if sample.key.signal == 0
                    else (1246 + 0.4375 * k)
                ) * 1e6
            else:
                frequency = frequencies[sample.key.system, sample.key.signal]
            assert sample.phase_m == pytest.approx(
                -row.real("carrier_phase") * 299792458 / frequency
            )
            assert sample.rate_mps == pytest.approx(
                -row.real("doppler") * 299792458 / frequency
            )
        exported = export_rinex(capture.records[name])
        assert exported.omitted["unverified_l2c_component"] > 0
        assert "L2S" in export_rinex(capture.records[name], l2c_code="2S").text
        results[name] = {
            "raw_count": record.integer("count"),
            "valid_samples": len(samples),
            "rinex_signals": exported.signal_observations,
            "systems": sorted({sample.key.system for sample in samples}),
        }
    save(request, "doctor", {"diagnosis": report, "conversion": results})


def test_live_rtk_status_variants(
    device: Receiver,
    request: pytest.FixtureRequest,
) -> None:
    capture = collect_diagnostics(device, RTK_LOGS, seconds=2)
    assert capture.configuration_restored and capture.subscriptions_restored
    for name in ("RTKSTATUS", "RTKSTATUS2", "RTKSTATUSD", "RTKSTATUS2D"):
        assert capture.records[name]
        assert isinstance(capture.records[name][-1]["dual_rtk_flag"], int)
    save(request, "rtk", rtk_diagnostics(capture))


def test_live_native_ppp_diagnostics(
    device: Receiver,
    request: pytest.FixtureRequest,
) -> None:
    capture = collect_diagnostics(device, PPP_LOGS, seconds=2)
    assert capture.configuration_restored and capture.subscriptions_restored
    report = ppp_diagnostics(capture)
    assert report["correction_application_verified"] is False
    save(request, "ppp", report)


def test_live_tracking_diagnostic_slots(
    device: Receiver,
    request: pytest.FixtureRequest,
) -> None:
    record = device.execute(FirmwareLog.PTOBSINFO.read(binary=True))
    slots = tracking_slots(record)
    assert len(slots) == 18 and any(slot.written for slot in slots)
    assert all(math.isfinite(slot.native_value) for slot in slots)
    ascii_record = device.execute(FirmwareLog.PTOBSINFO.read())
    assert len(tracking_slots(ascii_record)) == 18
    save(request, "tracking", [asdict(slot) for slot in slots])


def test_live_config_snapshot_after_single_field_query(
    device: Receiver,
    request: pytest.FixtureRequest,
) -> None:
    snapshots = []
    for _ in range(3):
        device.execute(configuration.current_signal_group())
        snapshots.append(receiver_state(device))
    assert all(state == snapshots[0] for state in snapshots)
    save(
        request,
        "snapshots",
        {
            "repeated_single_field_queries_stable": True,
            "unique_configuration_rows": len(snapshots[0][0]),
        },
    )


def test_live_internal_debug_streams(
    device: Receiver,
    request: pytest.FixtureRequest,
) -> None:
    fast = capture_internal_debug(device, InternalDebugLog.FAST_DEBUG, seconds=2)
    assert fast.acknowledged and fast.subscription_registered and fast.state_restored
    assert not fast.manifest()["normal_decoder_errors"]
    pos_records = [
        item
        for line in fast.raw.splitlines()
        if (item := parse_pos_debug(line)) is not None
    ]
    assert pos_records and pos_records[-1].tracked_satellites > 0

    mpt = capture_internal_debug(device, InternalDebugLog.MPT_DEBUG, seconds=2)
    assert mpt.acknowledged and mpt.subscription_registered and mpt.state_restored
    assert not mpt.manifest()["normal_decoder_errors"]
    mpt_records = [
        item
        for line in mpt.raw.splitlines()
        if (item := parse_mpt_debug(line)) is not None
    ]
    assert mpt_records and mpt_records[-1].tracked_satellites > 0

    ppp = capture_internal_debug(device, InternalDebugLog.PPP_DEBUG, seconds=2)
    assert ppp.acknowledged and ppp.subscription_registered and ppp.state_restored
    assert not ppp.manifest()["normal_decoder_errors"]
    ppp_records = [
        item
        for line in ppp.raw.splitlines()
        if (item := parse_ppp_debug(line)) is not None
    ]
    assert ppp_records and ppp_records[-1].milliseconds > 0
    save(
        request,
        "internal-debug",
        {
            "fast_debug": [asdict(item) for item in pos_records],
            "mpt_debug": [asdict(item) for item in mpt_records],
            "ppp_debug": [asdict(item) for item in ppp_records],
        },
    )
