"""Checks the boundary behaviour of the raw-data dump command surface."""

import pytest

from conftest import SubscriptionTransport, acknowledgement, sentence
from um982py import Receiver
from um982py.commands.types import Port, Trigger
from um982py.experimental import (
    STAGE_ACCESS,
    BasebandCapture,
    BasebandStage,
    InternalDebugLog,
    RawDataLog,
    build_message,
    capture_baseband,
    capture_internal_debug,
    closest_access,
    parse_mpt_debug,
    parse_pos_debug,
    parse_ppp_debug,
)
from um982py.experimental.baseband import RawBasebandPacket
from um982py.messages import TextLine
from um982py.protocol import StreamDecoder


def test_raw_data_log_builders() -> None:
    assert RawDataLog.SAMPLE_DATA.once().text == "DATASAMPLE"
    assert RawDataLog.BASEBAND_PACKAGES.output(1).text == "RAWBBPKG 1"
    assert RawDataLog.BASEBAND_PACKAGES.output(0.2).text == "RAWBBPKG 0.2"
    assert RawDataLog.RAW_DATA.output(1).text == "RAWDATAB 1"
    assert RawDataLog.RAW_DATA_SECONDARY.output(1).text == "RAWDATAHB 1"
    assert RawDataLog.RAW_DATA_ASCII.output(1).text == "RAWDATAA 1"
    assert RawDataLog.RAW_DATA_SECONDARY_ASCII.output(1).text == "RAWDATAHA 1"
    assert RawDataLog.BASEBAND_TRANSFER.output(1).text == "TRANSBBPKG 1"
    assert RawDataLog.BASEBAND_PACKAGES.stop().text == "UNLOG RAWBBPKG"
    assert RawDataLog.RAW_DATA.stop().text == "UNLOG RAWDATAB"
    assert RawDataLog.BASEBAND_PACKAGES.carries_baseband_containers
    assert not RawDataLog.SAMPLE_DATA.carries_baseband_containers


def test_raw_data_log_values_match_wire_identifiers() -> None:
    assert RawDataLog.SAMPLE_DATA.value == "DATASAMPLE"
    assert RawDataLog.BASEBAND_TRANSFER.value == "TRANSBBPKG"
    assert RawDataLog.RAW_DATA.value == "RAWDATAB"
    assert RawDataLog.RAW_DATA_SECONDARY.value == "RAWDATAHB"
    assert RawDataLog.RAW_DATA_ASCII.value == "RAWDATAA"
    assert RawDataLog.RAW_DATA_SECONDARY_ASCII.value == "RAWDATAHA"
    assert RawDataLog.BASEBAND_PACKAGES.value == "RAWBBPKG"


def test_baseband_stage_chain_is_ordered_and_mapped() -> None:
    stages = list(BasebandStage)
    assert stages == [
        BasebandStage.RF_FRONTEND,
        BasebandStage.ADC,
        BasebandStage.CORRELATOR,
        BasebandStage.TRACKING,
        BasebandStage.MEASUREMENT,
        BasebandStage.NAVIGATION,
    ]
    for stage in stages:
        assert closest_access(stage) == STAGE_ACCESS[stage]
        assert closest_access(stage.value) == STAGE_ACCESS[stage]
    # The receiver does not expose I/Q samples on the wire.
    assert "RFSPIREAD/RFSPIWRITE" in closest_access(BasebandStage.RF_FRONTEND)[0]
    assert "RANGE / RANGEH" in closest_access(BasebandStage.MEASUREMENT)[0]


def _packet() -> RawBasebandPacket:
    return RawBasebandPacket.build(
        content=build_message(0x10, b"\x01"),
        sequence=3,
    )


def test_baseband_capture_scans_containers_and_notices() -> None:
    packet = _packet()
    blob = packet.raw + b"$TrackMode,0\r\n"
    capture = BasebandCapture.from_bytes(blob)
    assert capture.packets == (packet,)
    assert [notice.name for notice in capture.notices] == ["TRACKMODE"]
    assert capture.discarded_bytes == 0
    assert not capture.byte_limit_reached
    assert capture.state_restored
    assert capture.cleanup_errors == ()


def test_baseband_capture_manifest() -> None:
    capture = BasebandCapture.from_bytes(b"$FPGA Version: 2\r\n")
    manifest = capture.manifest()
    assert manifest["baseband_packets"] == 0
    assert manifest["notices"] == 1
    assert manifest["notice_details"][0]["name"] == "FPGA_VERSION"
    assert manifest["state_restored"] is True


def test_baseband_capture_reports_metadata() -> None:
    capture = BasebandCapture.from_bytes(
        b"", byte_limit_reached=True, state_restored=False, cleanup_errors=("x",)
    )
    assert capture.byte_limit_reached
    assert not capture.state_restored
    assert capture.cleanup_errors == ("x",)
    assert capture.packets == ()
    assert capture.notices == ()


def test_capture_retains_incomplete_candidate_and_unknown_provenance() -> None:
    packet = _packet()
    capture = BasebandCapture.from_bytes(packet.raw[:-1])
    assert not capture.packets
    assert capture.pending_bytes == len(packet.raw) - 1
    assert capture.discarded_bytes == 0
    assert capture.acknowledged is None
    assert capture.subscription_registered is None


@pytest.mark.parametrize("registered", [True, False])
def test_capture_distinguishes_ack_registration_and_actual_data(
    monkeypatch: pytest.MonkeyPatch,
    registered: bool,
) -> None:
    class RawTransport(SubscriptionTransport):
        def write(self, data: bytes, timeout: float) -> None:
            if not registered and data.startswith(b"RAWBBPKG "):
                self.writes.append(data)
                self.pending.extend(acknowledgement(data.decode().strip()))
            else:
                super().write(data, timeout)

    transport = RawTransport()
    transport.after_write["LOGLISTA"] = sentence(b"GNRMC,,V")
    monkeypatch.setattr("um982py.experimental.raw_data.receiver_state", lambda _: ())
    with Receiver(transport, timeout=0.05) as receiver:
        capture = capture_baseband(
            receiver,
            seconds=0.001,
            interval=Trigger.ON_CHANGED,
            port=Port.COM1,
        )
    assert capture.command == "RAWBBPKG COM1 ONCHANGED"
    assert capture.acknowledged is True
    assert capture.subscription_registered is registered
    assert not capture.packets and not capture.gate_command_sent
    assert capture.state_restored and not transport.subscriptions
    assert b"UNLOG COM1 RAWBBPKG\r\n" in transport.writes
    assert all(not command.startswith(b"BBCMD") for command in transport.writes)
    assert capture.manifest()["nmea_sentences"] > 0


def test_gate_cleanup_failure_is_reported_and_transport_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class GateTransport(SubscriptionTransport):
        def write(self, data: bytes, timeout: float) -> None:
            if data.startswith(b"BBCMD"):
                self.writes.append(data)
                status = "INVALID PARAMETER" if b",0" in data else "OK"
                self.pending.extend(acknowledgement(data.decode().strip(), status))
            else:
                super().write(data, timeout)

    transport = GateTransport()
    monkeypatch.setattr("um982py.experimental.raw_data.receiver_state", lambda _: ())
    with Receiver(transport, timeout=0.05) as receiver:
        capture = capture_baseband(receiver, seconds=0.001, enable_gate=True)
        assert receiver.transport is transport
    assert len(capture.cleanup_errors) == 1
    assert not capture.state_restored
    assert capture.gate_command_sent
    assert not transport.subscriptions


def test_capture_baseband_argument_validation() -> None:
    with pytest.raises(ValueError):
        capture_baseband(None, seconds=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        capture_baseband(None, max_bytes=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        capture_baseband(None, max_length=0x34)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        RawDataLog("NOT_A_LOG")


def test_internal_debug_log_builders_and_parsers() -> None:
    assert InternalDebugLog.FAST_DEBUG.output(1).text == "FASTDEBUGMSG 1"
    assert InternalDebugLog.PPP_DEBUG.on_changed().text == "PPPDEBUGMSG ONCHANGED"
    assert InternalDebugLog.MPT_DEBUG.output().text == "MPTDEBUGMSG ONCHANGED"
    assert InternalDebugLog.PPP_DEBUG.stop().text == "UNLOG PPPDEBUGMSG"
    with pytest.raises(ValueError, match="ONCHANGED"):
        InternalDebugLog.PPP_DEBUG.output(1)
    with pytest.raises(ValueError, match="numeric"):
        InternalDebugLog.DEBUG_INFO.on_changed()

    ppp_line = (
        b"$PPPDEBUGMSG,$PPPDATA,Msec:557827000SsrT:557820,0,557820,0,0"
        b"Type:8,9,8,6,6CorNum:G24C0E27R0C6;IODE:S8S49S66"
        b"Vel:0.021,0.014,-0.074 PrcNum11;Sy4F4False;dX-0.032,-0.007,0.056"
        b"S15F1:0.018S18F3:-0.049*End\r\n"
    )
    pos_line = (
        b"$POSDEBUG,1,0,0,656,2441,557823.000,34,34,ls=10,0;557822.000,34;"
        b"adr18,21,0.00;flpp,68,0;hgt,557822.00,1,-0.028,-0.002;-0.02,311.341;*End\r\n"
    )
    mpt_line = (
        b"$MPTDEBUG,1;pte,1000,0,2,1;s0;ae689,2441,557824.000,SatCnt:34,22,"
        b"557824.000,rsk0,0;tm1,557824.000,557823.000;3782563.8,899476.3,5039205.4;"
        b"1,444*End\r\n"
    )
    decoder = StreamDecoder(strict=True)
    frames = decoder.feed(ppp_line + pos_line + mpt_line)
    assert len(frames) == 3
    assert all(isinstance(frame, TextLine) for frame in frames)
    assert not decoder.errors

    ppp = parse_ppp_debug(ppp_line)
    assert ppp is not None
    assert ppp.source == "PPPDEBUGMSG"
    assert ppp.milliseconds == 557827000
    assert ppp.corrected_counts["GPS"] == 24
    assert ppp.corrected_counts["GALILEO"] == 27
    assert ppp.iode_slots == (8, 49, 66)
    assert ppp.processed_satellites == 11
    without_processing_count = parse_ppp_debug(ppp_line.replace(b"PrcNum11;", b""))
    assert without_processing_count is not None
    assert without_processing_count.processed_satellites is None
    assert ppp.delta_position_m == (-0.032, -0.007, 0.056)
    assert [(r.slot, r.frequency_index, r.residual_m) for r in ppp.residuals] == [
        (15, 1, 0.018),
        (18, 3, -0.049),
    ]

    pos = parse_pos_debug(pos_line)
    assert pos is not None
    assert pos.week == 2441
    assert pos.seconds_of_week == 557823.0
    assert pos.tracked_satellites == 34
    assert pos.previous_seconds_of_week is None
    assert pos.filter_rate_hz is None
    assert pos.rtk_gap is None
    assert pos.trailer is None
    assert pos.adr_locked == 18
    assert pos.adr_total == 21
    assert pos.ppp_position_type == 68
    assert pos.height_msl == 311.341

    mpt = parse_mpt_debug(mpt_line)
    assert mpt is not None
    assert mpt.week == 2441
    assert mpt.tracked_satellites == 34
    assert mpt.used_satellites == 22
    assert mpt.ecef_m == (3782563.8, 899476.3, 5039205.4)


def test_capture_internal_debug_restores_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = SubscriptionTransport()
    transport.after_write["PPPDEBUGMSG COM1 ONCHANGED"] = (
        b"$PPPDEBUGMSG,$PPPDATA,Msec:1000SsrT:0,0,0,0,0Type:0,0,0,0,0"
        b"CorNum:G10C0E12R0C0;IODE:S1PrcNum8;*End\r\n"
    )
    monkeypatch.setattr("um982py.experimental.raw_data.receiver_state", lambda _: ())
    with Receiver(transport, timeout=0.05) as receiver:
        capture = capture_internal_debug(
            receiver, InternalDebugLog.PPP_DEBUG, seconds=0.001
        )
    assert capture.acknowledged is True
    assert capture.subscription_registered is True
    assert capture.state_restored
    assert [notice.name for notice in capture.notices] == ["PPP_DEBUG"]


def test_pos_debug_pairs_semicolon_split_sl1_and_lse_blocks() -> None:
    line = (
        "$POSDEBUG,1,0,0,656,2441,559003.000,33,23,ls=10,0;"
        "sq;0,0,16,sl0,-0.0084,-0.0092,-0.0025,-1.281,2.413;16,1,10;"
        "sl1,0,4,5;-0.807,0.128,-1.027;lse0,1,16,1.0;1;"
        "hgt,559002.00,1,-0.028,-0.002;0.05,307.725;*End"
    )
    parsed = parse_pos_debug(line)
    assert parsed is not None
    assert len(parsed.satellite_qualities) == 1
    assert parsed.satellite_qualities[0].slot_mode is None
    assert parsed.satellite_qualities[0].slot_status is None
    assert parsed.sl1_blocks == (((0, 4, 5), (-0.807, 0.128, -1.027)),)
    assert parsed.lse_blocks == (((0, 1, 16, 1.0), 1),)
    assert parsed.height_msl == pytest.approx(307.725)
    assert not any(
        token in {"sl1,0,4,5", "-0.807,0.128,-1.027", "lse0,1,16,1.0"}
        for token, _ in parsed.extra
    )


def test_pos_debug_preserves_unpaired_sl1_header() -> None:
    line = "$POSDEBUG,1,0,0,656,2441,559003.000,33,23,ls=10,0;sl1,0,4,5;*End"
    parsed = parse_pos_debug(line)
    assert parsed is not None
    assert parsed.sl1_blocks == ()
    assert ("sl1,0,4,5", "sl1,0,4,5") in parsed.extra


def test_pos_debug_retains_repeated_sl1_blocks() -> None:
    line = (
        "$POSDEBUG,1,0,0,656,2441,559003.000,33,23,ls=10,0;"
        "sl1,0,4,5;-0.807,0.128,-1.027;"
        "sl1,0,8,9;-0.228,-0.245,0.917;*End"
    )
    parsed = parse_pos_debug(line)
    assert parsed is not None
    assert parsed.sl1_blocks == (
        ((0, 4, 5), (-0.807, 0.128, -1.027)),
        ((0, 8, 9), (-0.228, -0.245, 0.917)),
    )
