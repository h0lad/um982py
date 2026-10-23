"""Checks baseband parser contracts for builders and diagnostic notices."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from um982py.experimental import (
    ae_enable,
    agnss_config,
    agnss_info,
    dangerous_reset,
    dangerous_single_satellite_tracking,
    dc_message_enable,
    leap_second_config,
    log_config,
    parse_baseband_notice,
    rf_spi_read,
    rf_spi_register_write,
    rf_spi_write,
    tcxo_jump_config,
)


def test_control_builders_preserve_native_width_and_decimal_grammar() -> None:
    assert ae_enable(65535).text == "BBCMD $AEEN,65535"
    assert agnss_config(enabled=True).text == "BBCMD $AGNSSCONFIG,1"
    assert agnss_config(enabled=False).text == "BBCMD $AGNSSCONFIG,0"
    assert tcxo_jump_config(1, parameter=-20).text == "BBCMD $TCXOJUMPEN,1,-20"
    assert dc_message_enable(-1).text == "BBCMD $DCRMSGEN,-1"
    assert leap_second_config(18, enabled=True).text == "BBCMD $LEAPSECOND,1,18"
    assert log_config(1000, mode=2).text == "BBCMD $LOG,1000,2"
    assert dangerous_reset(0xA, mode=-1).text == "BBCMD $RESET,0000000A,-1"
    assert (
        dangerous_single_satellite_tracking(enabled=False).text == "BBCMD $ONESATTRK,0"
    )


@pytest.mark.parametrize(
    "build",
    [
        lambda: ae_enable(65536),
        lambda: ae_enable(True),
        lambda: agnss_config(enabled=1),
        lambda: agnss_info(),
        lambda: agnss_info(1, 2, 128, 0, 0, 0),
        lambda: tcxo_jump_config(1 << 31, parameter=0),
        lambda: dc_message_enable(-(1 << 31) - 1),
        lambda: leap_second_config(18, enabled=1),
        lambda: log_config(1000, mode=3),
        lambda: log_config(65536),
        lambda: rf_spi_read(125),
        lambda: rf_spi_read(1 << 32),
        lambda: rf_spi_register_write(125, 0),
        lambda: rf_spi_register_write(0, 1 << 32),
        lambda: rf_spi_write(0x8000000000),
    ],
)
def test_control_arguments_reject_truncation_and_invalid_selector(
    build: Callable[[], object],
) -> None:
    with pytest.raises(ValueError):
        build()


def test_rf_register_write_packs_selector_above_the_32_bit_value() -> None:
    command = rf_spi_register_write(0x7C, 0x89ABCDEF)
    assert command.text == "BBCMD $RFSPIWRITE,7C89ABCDEF"
    packed = int(command.text.rsplit(",", 1)[1], 16)
    assert packed >> 32 == 124
    assert packed & 0xFFFFFFFF == 0x89ABCDEF
    assert rf_spi_read(0xFFFFFFFF).text == "BBCMD $RFSPIREAD,00FFFFFFFF"


@pytest.mark.parametrize(
    "raw,name,expected",
    [
        (
            b"$SmpClkInit: 1, N: 0x0A, Div:4,Reg: 0x1234ABCD, Cnt:20, ClkSel:2\r\n",
            "SAMPLE_CLOCK",
            {
                "n": 10,
                "divider": 4,
                "register": 0x1234ABCD,
                "count": 20,
                "clock_select": 2,
            },
        ),
        (
            b"$GROUP, 1, 2,S: 3,Ant:0,Flag: 4,AIMode:AUTO,"
            b"IFreq: -123456,Fs:25000000,0,-1,CH:  1 -  16,"
            b"InV:0123456789abcdef\r\n",
            "RF_GROUP",
            {
                "antenna": 0,
                "sample_frequency": 25000000,
                "intermediate_frequency": -123456,
                "channel_first": 1,
                "channel_last": 16,
                "inversion_word_1": 0x1234567,
                "inversion_word_2": 0x89ABCDEF,
                "ai_mode": "AUTO",
            },
        ),
        (b"LogSwitchCMD: 1,0,50\r\n", "LOG_SWITCH", {"value_3": 50}),
        (
            b"$RFSPIRead:000000123456789Ax can not parsed!\r\n",
            "RFSPIWRITE_PARSE_ERROR",
            {"value": 0x123456789A},
        ),
        (b"$ConfigRcvRunningMode,0, 1, 2\r\n", "RUNNING_MODE", {"value_2": 1}),
        (
            b"$ConfigRcvRunningMode,1, 0x80000000\r\n",
            "RUNNING_MODE_MASK",
            {"mask": 1 << 31},
        ),
    ],
)
def test_clock_rf_and_control_notices_decode_diagnostic_fields(
    raw: bytes, name: str, expected: dict[str, object]
) -> None:
    notice = parse_baseband_notice(raw)
    assert notice is not None
    assert notice.name == name
    result = notice.decode()
    for key, value in expected.items():
        assert result[key] == value
