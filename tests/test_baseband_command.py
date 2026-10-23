"""Checks the boundary behaviour of the baseband command builders."""

import pytest

from conftest import ReplayTransport, acknowledgement
from um982py import Receiver
from um982py.experimental import (
    UNVERIFIED_COMMANDS,
    BasebandCommand,
    acquisition_frequency_mask,
    adr_initial,
    adr_reliability,
    agnss_info,
    ai_enable,
    baseband_command,
    baseband_message,
    bb_command,
    bb_message_to_ap,
    dangerous_force_error_trap,
    dangerous_force_reset,
    dangerous_hot_start,
    dangerous_reset,
    dangerous_single_satellite_tracking,
    event_config,
    jam_status_enable,
    log_enable,
    mmp_enable,
    ppp_enable,
    ppp_rtk_enable,
    rec_info_enable,
    rf_spi_read,
    rf_spi_write,
    rtc_status_enable,
    sbas_control,
    signal_group,
    signal_mask,
    timing_mode,
    track_mode,
)
from um982py.messages import CommandResponse
from um982py.protocol import StreamDecoder


def test_catalogue_is_complete_and_categorised() -> None:
    assert len(BasebandCommand) == 41
    # Keep the table in catalogue order.
    table = [
        "RESET",
        "BBMSG2AP",
        "LOG",
        "PPSCONFIG",
        "TIMINGMODE",
        "FRESET",
        "EVENTCONFIG",
        "SBASCONTROL",
        "FORCEERRORTRAP",
        "ACQFREQ",
        "TRACKMODE",
        "AEEN",
        "RFSPIREAD",
        "RFSPIWRITE",
        "SIGNALMASK",
        "RFCONFIG",
        "PPPEN",
        "RECINFOEN",
        "RTCSTATUSEN",
        "JAMSTATUSEN",
        "SIGNALGROUP",
        "AIENA",
        "AICONFIG",
        "RCVRUNNINGMODE",
        "MODE",
        "AGNSSINFO",
        "AGNSSCONFIG",
        "CFGWNKROR",
        "ADRRELIABLITY",
        "ADRINITIAL",
        "MMPEN",
        "SATMASK",
        "HOTSTART",
        "TCXOJUMPEN",
        "DCRMSGEN",
        "LEAPSECOND",
        "CUSTOMMODE",
        "PPPRTKEN",
        "ONESATTRK",
        "ANTISPOOFENA",
    ]
    assert [BasebandCommand(name).value for name in table] == table
    assert BasebandCommand.BBLOGEN.value == "BBLOGEN"
    assert BasebandCommand.RESET.category == "DESTRUCTIVE"
    assert BasebandCommand.RFSPIREAD.category == "QUERY"
    assert BasebandCommand.TIMINGMODE.category == "CONFIGURATION"
    assert BasebandCommand.AEEN.category == "CONFIGURATION"
    assert BasebandCommand.AGNSSINFO.category == "CONFIGURATION"
    assert set(UNVERIFIED_COMMANDS) <= set(BasebandCommand)


def test_typed_builders_produce_expected_wire_text() -> None:
    assert timing_mode(1).text == "BBCMD $TIMINGMODE,1"
    assert track_mode(0).text == "BBCMD $TRACKMODE,0"
    assert acquisition_frequency_mask(0xFFFFFFFF).text == "BBCMD $ACQFREQ,-1"
    assert acquisition_frequency_mask(0).text == "BBCMD $ACQFREQ,0"
    assert signal_mask(1, 2).text == "BBCMD $SIGNALMASK,1,2"
    assert signal_group(3, 4).text == "BBCMD $SIGNALGROUP,3,4"
    assert event_config(1, 2, 3, 4).text == "BBCMD $EVENTCONFIG,1,2,3,4"
    assert ai_enable(1).text == "BBCMD $AIENA,1"
    assert ppp_enable(0).text == "BBCMD $PPPEN,0"
    assert ppp_rtk_enable(1).text == "BBCMD $PPPRTKEN,1"
    assert rec_info_enable(1).text == "BBCMD $RECINFOEN,1"
    assert rtc_status_enable(0).text == "BBCMD $RTCSTATUSEN,0"
    assert jam_status_enable(1).text == "BBCMD $JAMSTATUSEN,1"
    assert adr_reliability(3).text == "BBCMD $ADRRELIABLITY,3"
    assert adr_initial(2).text == "BBCMD $ADRINITIAL,2"
    assert mmp_enable(1).text == "BBCMD $MMPEN,1"
    assert sbas_control(1, 2, 3, 4).text == "BBCMD $SBASCONTROL,1,2,3,4"
    assert log_enable(7).text == "BBCMD $LOG,7"
    assert bb_message_to_ap().text == "BBCMD $BBMSG2AP,1"
    assert bb_message_to_ap(enabled=False).text == "BBCMD $BBMSG2AP,0"
    with pytest.raises(ValueError):
        bb_message_to_ap(enabled=1)  # type: ignore[arg-type]


def test_query_builders() -> None:
    assert rf_spi_read(0x7C).text == "BBCMD $RFSPIREAD,000000007C"
    assert rf_spi_read(0).text == "BBCMD $RFSPIREAD,0000000000"
    assert rf_spi_write(0xABCD).text == "BBCMD $RFSPIWRITE,000000ABCD"
    assert agnss_info(2441, 399541, 0, 0, 0, 0).text == (
        "BBCMD $AGNSSINFO,2441,399541,0,0,0,0"
    )


def test_destructive_builders_are_explicit() -> None:
    assert dangerous_reset().text == "BBCMD $RESET,00000000,0"
    assert dangerous_force_reset().text == "BBCMD $FRESET,0"
    assert dangerous_hot_start().text == "BBCMD $HOTSTART"
    assert dangerous_force_error_trap(0xDEAD).text == "BBCMD $FORCEERRORTRAP,57005"
    assert dangerous_single_satellite_tracking().text == "BBCMD $ONESATTRK,1"


def test_generic_and_message_helpers() -> None:
    assert baseband_message(BasebandCommand.TIMINGMODE, "1") == "TIMINGMODE,1"
    assert baseband_message("bbmsg2ap") == "BBMSG2AP"
    assert baseband_command(BasebandCommand.LOG, "1").text == "BBCMD $LOG,1"
    assert bb_command("$BBLOGEN,00000000").text == "BBCMD $BBLOGEN,00000000"


def test_argument_validation() -> None:
    for builder, bad in (
        (timing_mode, -1),
        (track_mode, -1),
        (acquisition_frequency_mask, 1 << 32),
        (signal_mask, 1),
        (rf_spi_read, 1 << 40),
    ):
        with pytest.raises(ValueError):
            builder(bad)
    with pytest.raises(ValueError):
        baseband_message("BAD NAME")
    with pytest.raises(ValueError):
        baseband_message(BasebandCommand.RESET, "a*b")
    with pytest.raises(ValueError):
        baseband_command(BasebandCommand.RESET, "a;b")
    with pytest.raises(ValueError):
        bb_command("TIMINGMODE,1")


def _response(command: str) -> CommandResponse:
    messages = StreamDecoder().feed(acknowledgement(command))
    assert len(messages) == 1
    message = messages[0]
    assert isinstance(message, CommandResponse)
    return message


def test_builders_match_and_decode_application_acknowledgement() -> None:
    for builder in (
        timing_mode(1),
        track_mode(0),
        acquisition_frequency_mask(0xFFFFFFFF),
        signal_mask(1, 2),
        event_config(1, 2, 3, 4),
        ai_enable(1),
        ppp_enable(0),
        rec_info_enable(1),
        rf_spi_read(0x7C),
        dangerous_reset(),
    ):
        response = _response(builder.text)
        assert builder.matches(response)
        assert builder.decode(response) is response


def test_builders_reject_unrelated_messages() -> None:
    response = _response("BBCMD $TRACKMODE,9")
    assert not timing_mode(1).matches(response)


def test_receiver_execute_round_trip() -> None:
    command = timing_mode(1)
    transport = ReplayTransport({command.encode(): acknowledgement(command.text)})
    with Receiver(transport) as receiver:
        result = receiver.execute(command)
    assert isinstance(result, CommandResponse)
    assert result.accepted
    assert transport.closed


def test_receiver_rejects_failed_baseband_command() -> None:
    from um982py.errors import CommandRejected

    command = track_mode(0)
    transport = ReplayTransport(
        {command.encode(): acknowledgement(command.text, "INVALID PARAMETER")}
    )
    with (
        pytest.raises(CommandRejected),
        Receiver(transport, timeout=0.01) as receiver,
    ):
        receiver.execute(command)


def test_every_command_is_categorised() -> None:
    assert {command.category for command in BasebandCommand} == {
        "DESTRUCTIVE",
        "QUERY",
        "CONFIGURATION",
        "UNVERIFIED",
        "NO_OP",
    }
    for command in BasebandCommand:
        if command.category == "DESTRUCTIVE":
            assert command.name in {
                "RESET",
                "FRESET",
                "HOTSTART",
                "FORCEERRORTRAP",
                "ONESATTRK",
                "CUSTOMMODE",
                "RCVRUNNINGMODE",
                "CFGWNKROR",
                "AIENA",
                "SIGNALGROUP",
                "RFSPIWRITE",
                "RFCONFIG",
            }
    # No replies are known for unverified commands.
    assert set(UNVERIFIED_COMMANDS) == {
        command for command in BasebandCommand if command.category == "UNVERIFIED"
    }
    assert UNVERIFIED_COMMANDS == (
        BasebandCommand.MODE,
        BasebandCommand.SATMASK,
        BasebandCommand.BBLOGEN,
    )
