"""Regresses against fresh hardware captures."""

from dataclasses import replace
from pathlib import Path

import pytest

from conftest import ReplayTransport, ascii_message
from um982py import (
    Receiver,
    export_rinex,
    gnss_range_samples,
    range_samples,
    tracking_signal,
)
from um982py.commands import Log
from um982py.corrections import audit_has
from um982py.diagnostics import DiagnosticCapture, ppp_diagnostics
from um982py.experimental import FirmwareLog
from um982py.experimental.capture import receiver_state
from um982py.experimental.tracking import tracking_slots
from um982py.messages import Record
from um982py.protocol import StreamDecoder
from um982py.protocol.checksums import nmea_checksum
from um982py.rinex import satellite_id

FIXTURES = Path(__file__).parent / "fixtures/captures-extra"


def captured(name: str, form: str = "B") -> Record:
    frame = StreamDecoder(strict=True).feed(
        (FIXTURES / f"{name}{form}.bin").read_bytes()
    )[0]
    return (Log[name] if name in Log.__members__ else FirmwareLog[name]).decode(frame)


def test_has_signal_masks_from_receiver_capture() -> None:
    systems = captured("E6MASKBLOCK").records("systems")
    masks = [(row.integer("gnss_id"), row.integer("signal_mask")) for row in systems]
    assert masks == [
        (0, 0x8140),
        (2, 0x4904),
    ]


def test_b2b_ascii_epoch_feeds_correction_audit() -> None:
    import json

    from um982py.corrections import correction_events

    samples = json.loads((FIXTURES.parent / "manual-examples-r1.15.json").read_text())
    message = StreamDecoder(strict=True).feed(
        (samples["PPPB2BINFO1A"] + "\r\n").encode()
    )[0]
    record = Log.PPPB2BINFO1.decode(message)
    assert record.integer("seconds_of_day") == 20590
    event = correction_events(record)[0]
    assert event.received - event.epoch == 5


@pytest.mark.parametrize(
    "name", ("RTKSTATUS", "RTKSTATUS2", "RTKSTATUSD", "RTKSTATUS2D")
)
def test_real_ascii_ff_matches_binary_flag(name: str) -> None:
    ascii_record, binary_record = captured(name, "A"), captured(name)
    assert ascii_record.integer("dual_rtk_flag") == 0xFF
    assert binary_record.integer("dual_rtk_flag") == 0xFF
    assert set(ascii_record) == set(binary_record)
    assert ascii_record["pos_type"] == "NONE"
    assert binary_record["pos_type"] == 0


def test_l2_discriminator_and_glonass_channel_are_not_l1() -> None:
    assert tracking_signal(9 << 21).frequency_hz == 1227600000  # type: ignore[union-attr]
    l2 = tracking_signal((9 << 21) | (1 << 26))
    assert l2 is not None and l2.rinex_code == ""
    assert tracking_signal((9 << 21) | (1 << 26), l2c_code="2S").rinex_code == "2S"  # type: ignore[union-attr]
    glo = tracking_signal(1 << 16, glonass_channel=-7)
    assert glo is not None and glo.frequency_hz == 1598062500
    unknown_frequency = tracking_signal(1 << 16)
    assert unknown_frequency is not None and unknown_frequency.frequency_hz is None
    assert tracking_signal(7 << 16) is None


@pytest.mark.parametrize("name", ("RANGE", "RANGEH"))
def test_live_captures_expand_without_changing_legacy_gps_selection(name: str) -> None:
    record = captured(name)
    old, expanded = range_samples(record), gnss_range_samples(record)
    assert old and set(old) <= set(expanded)
    assert {sample.key.system for sample in expanded} == {0, 1, 3, 4}
    l2 = [
        sample
        for sample in expanded
        if sample.key.system == 0 and sample.key.signal == 9
    ]
    assert l2
    export = export_rinex((record,))
    assert export.signal_observations > len(old)
    assert export.omitted["unverified_l2c_component"] > 0
    explicit = export_rinex((record,), l2c_code="2S")
    assert "C2S" in explicit.text and "L2S" in explicit.text
    assert "supplied by caller" in explicit.text
    assert "GLONASS SLOT / FRQ #" in export.text
    assert "C5P" in export.text
    assert export.omitted["invalid_code_or_phase"] > 0


def test_export_rejects_mixed_antennas_and_duplicate_epochs() -> None:
    first, second = captured("RANGE"), captured("RANGEH")
    with pytest.raises(ValueError, match="one antenna"):
        export_rinex((first, second))
    with pytest.raises(ValueError, match="strictly increasing"):
        export_rinex((first, first))
    with pytest.raises(ValueError, match="timestamp"):
        export_rinex((replace(first, message=None),))


def test_prn_boundaries_follow_unicore_table_7_53() -> None:
    assert satellite_id(1, 38) == "R01"
    assert satellite_id(1, 61) == "R24"
    assert satellite_id(2, 120) == "S20"
    assert satellite_id(5, 193) == "J01"
    assert satellite_id(5, 202) == "J10"
    assert satellite_id(0, 33) is None


def test_tracking_slot_mask_does_not_mean_valid_or_average_cn0() -> None:
    record = captured("PTOBSINFO")
    slots = tracking_slots(record)
    assert len(slots) == 18
    for index, slot in enumerate(slots):
        assert slot.written == bool(record.integer("field_11") & (1 << index))
        assert slot.native_value == record.real(f"field_{index + 12:02}")
    assert slots[9].bank == 1 and slots[9].bank_slot == 0
    assert any(slot.written and slot.native_value < 0 for slot in slots)


def test_live_has_mask_orbit_clock_and_ppp_convergence() -> None:
    records = tuple(
        captured(name)
        for name in ("E6MASKBLOCK", "E6ORBITBLOCK", "E6CBIASBLOCK", "E6CLOCKFULLBLOCK")
    )
    checks = audit_has(records)
    assert len(checks) == 4 and all(not row["flags"] for row in checks)
    assert {row["mask_id"] for row in checks} == {27}
    assert {row["iod_set_id"] for row in checks} == {1}
    nav = captured("PPPNAV")
    capture = DiagnosticCapture(
        {"PPPNAV": (nav,)},
        30,
        True,
        True,
        (("SIGNALGROUP", "CONFIG SIGNALGROUP 3 6"),),
        (*records, nav),
    )
    report = ppp_diagnostics(capture)
    assert report["position_type_label"] == "PPP_CONVERGING"
    assert report["receiver_reports_ppp"] is True
    assert report["correction_application_verified"] is False


def test_has_reference_time_must_precede_reception_not_be_nearest_hour() -> None:
    record = captured("E6MASKBLOCK")
    # A TOH one second ahead refers to the previous hour (ICD 7.7).
    assert record.message is not None
    from um982py.measurement import gps_epoch

    received = gps_epoch(record.message)
    next_second = int(received % 3600) + 1
    changed = Record(
        record.name, tuple({**dict(record), "toh": next_second}.items()), record.message
    )
    check = audit_has((changed,))[0]
    assert check["age_seconds"] == 3599
    assert check["flags"] == ["stale_correction"]


def test_snapshot_ignores_duplicate_config_rows_but_retains_different_values() -> None:
    def config_line(fields: bytes) -> bytes:
        body = b"$CONFIG," + fields
        return body + f"*{nmea_checksum(body):02X}\r\n".encode()

    config = config_line(b"PPP,CONFIG PPP ENABLE AUTO")
    mask = config_line(b"MASK,MASK 5.0")
    transport = ReplayTransport(
        {
            b"CONFIG\r\n": config,
            b"MODE\r\n": ascii_message("MODE", "MODE ROVER UAV,"),
            b"MASK\r\n": mask,
            b"LOGLISTA\r\n": ascii_message("LOGLISTA", "0"),
        }
    )
    receiver = Receiver(transport, timeout=0.1)
    baseline = receiver_state(receiver)
    transport.responses[b"CONFIG\r\n"] = config + config
    transport.responses[b"MASK\r\n"] = mask + mask
    assert receiver_state(receiver) == baseline
    transport.responses[b"CONFIG\r\n"] = config + config_line(b"PPP,CONFIG PPP DISABLE")
    assert receiver_state(receiver) != baseline


def test_qzss_l1_is_not_given_an_unverified_rinex_code() -> None:
    signal = tracking_signal(5 << 16)
    assert signal is not None
    assert signal.frequency_hz == 1575.42e6
    assert signal.rinex_code == ""
    assert "L1C/B" in signal.name
    gps = tracking_signal(0)
    assert gps is not None and gps.rinex_code == "1C"


def test_rinex_omits_ambiguous_qzss_l1() -> None:
    from test_protocol import binary

    frame = StreamDecoder(strict=True).feed(binary(b"", 43))[0]
    observation = Record(
        "observation",
        (("tracking_status", (5 << 16) | 0x1400), ("prn", 193)),
    )
    gps = Record(
        "observation",
        (
            ("tracking_status", 0x1400),
            ("prn", 1),
            ("pseudorange", 20_000_000.0),
            ("carrier_phase", 10.0),
            ("doppler", 0.0),
            ("cn0", 40.0),
            ("lock_time", 30.0),
        ),
    )
    record = Record("RANGE", (("observations", (observation, gps)),), frame)
    result = export_rinex((record,))
    assert result.signal_observations == 1
    assert result.omitted["ambiguous_qzss_l1"] == 1


def test_rinex_explicit_bdt_week_scale() -> None:
    original = captured("RANGE")
    assert original.message is not None
    from um982py.messages import BinaryHeader

    updated_header = BinaryHeader(0, 43, 0, 1, 0, 0, 0, 0, 0, 18, 0)
    updated_message = replace(original.message, header=updated_header)
    updated = replace(original, message=updated_message)
    with pytest.raises(ValueError, match="time reference"):
        export_rinex((updated,))
    result = export_rinex((updated,), week_scale="BDT")
    assert "> 2006 01 01 00 00 14.0000000" in result.text
    assert "Input week scale supplied by caller: BDT" in result.text
