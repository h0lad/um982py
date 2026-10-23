"""ANT2 routing must never accept an ANT1 measurement as its replacement."""

import argparse
from pathlib import Path

import pytest

from um982py.antenna import (
    AntennaLog,
    antenna_index,
    antenna_log,
    mirror,
    other_antenna,
    swap_antenna,
)
from um982py.capture import capture_records, decode_records
from um982py.commands import Log, queries
from um982py.console import add_receiver_arguments
from um982py.experimental import FirmwareLog
from um982py.messages.navigation import BestNavigation
from um982py.protocol import StreamDecoder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "captures"


@pytest.mark.parametrize("antenna", ["secondary", "2"])
def test_secondary_replay_reads_only_rangeh(antenna: str) -> None:
    args = argparse.Namespace(replay=FIXTURES / "RANGEHB.bin", antenna=antenna)
    records = capture_records(args, [FirmwareLog.RANGE])["RANGE"]
    assert records
    assert all(record.name == "RANGEH" for record in records)
    raw = (FIXTURES / "RANGEB.bin").read_bytes()
    assert not decode_records(
        StreamDecoder().feed(raw), antenna_log(FirmwareLog.RANGE, antenna)
    )


def test_primary_replay_does_not_consume_secondary() -> None:
    args = argparse.Namespace(replay=FIXTURES / "RANGEHB.bin", antenna="primary")
    assert not capture_records(args, [FirmwareLog.RANGE])["RANGE"]


@pytest.mark.parametrize(
    ("source", "wire"),
    [
        (FirmwareLog.RANGE, "RANGEHB"),
        (FirmwareLog.BESTPOS, "BESTNAVHB"),
        (FirmwareLog.BESTXYZ, "BESTNAVXYZHB"),
        (FirmwareLog.PSRDOP, "SPPDOPHB"),
        (FirmwareLog.RTKDOP, "ADRDOPHB"),
        (Log.BESTNAV, "BESTNAVHB"),
        (Log.OBSVM, "OBSVHB"),
    ],
)
def test_secondary_wire_command(source: Log | FirmwareLog, wire: str) -> None:
    assert antenna_log(source, "2").request(binary=True).text == wire


def test_receiver_wide_and_baseline_logs_keep_scope() -> None:
    for log in (FirmwareLog.TIME, FirmwareLog.ANTENNA, FirmwareLog.BSLNENUHD):
        assert antenna_log(log, "2") is log
    with pytest.raises(ValueError, match="no verified secondary"):
        antenna_log(FirmwareLog.PTOBSINFO, "2")


def test_secondary_navigation_query_matches_real_wire_identity() -> None:
    from dataclasses import replace

    primary = next(
        frame
        for frame in StreamDecoder().feed(
            (FIXTURES.parent / "bodies" / "BESTNAVB.bin").read_bytes()
        )
        if queries.best_navigation(binary=True).matches(frame)
    )
    # The same body with a secondary ID must not make the primary frame match.
    secondary = replace(primary, header=replace(primary.header, message_id=2119))
    command = queries.best_navigation(binary=True, antenna=2)
    assert not command.matches(primary)
    assert command.matches(secondary)
    assert command.decode(secondary) == BestNavigation.from_message(primary)
    assert queries.fix(antenna=2).text == "GPGGAH"


def test_common_parser_exposes_antenna_selection() -> None:
    parser = argparse.ArgumentParser()
    add_receiver_arguments(parser)
    assert parser.parse_args(["--antenna", "2"]).antenna == "2"


def test_hex_extra_log_uses_secondary_identity() -> None:
    from examples.navigation_message_hex.__main__ import _targets

    targets = _targets(["GPS"], ["RANGE", "RANGEH"], "2")
    assert [log.value for _, log in targets] == ["GPSEPH", "RANGEH"]


def test_secondary_dop_reports_actual_source() -> None:
    from examples.dop_geometry import ReportedDilution

    from um982py.messages import Record

    record = Record(
        "SPPDOPH",
        tuple(
            (key, value)
            for key, value in {
                "gdop": 2.0,
                "pdop": 1.5,
                "hdop": 1.0,
                "tdop": 1.0,
                "elev_mask": 5.0,
                "count_sats": 8,
            }.items()
        ),
    )
    assert ReportedDilution.from_record(record, "PSRDOP").source == "SPPDOPH"


def test_mirror_pairs_documented_inputs_in_both_directions() -> None:
    assert mirror(FirmwareLog.RANGE) is FirmwareLog.RANGEH
    assert mirror(FirmwareLog.RANGEH) is FirmwareLog.RANGE
    assert mirror(Log.OBSVM) is Log.OBSVH
    assert mirror(Log.OBSVH) is Log.OBSVM
    assert mirror(Log.PPPNAV) is Log.PPPNAVH
    assert mirror(Log.PPPNAVH) is Log.PPPNAV
    for receiver_wide in (FirmwareLog.TIME, FirmwareLog.BSLNENUHD):
        assert mirror(receiver_wide) is receiver_wide


def test_a_target_shared_by_two_primaries_is_not_mirrored_arbitrarily() -> None:
    # BESTPOS and BESTNAV both map to BESTNAVH.
    assert mirror(Log.BESTNAVH) is Log.BESTNAVH


def test_swap_retains_the_logical_key_and_only_moves_the_wire() -> None:
    swapped = swap_antenna(AntennaLog(FirmwareLog.RANGE, FirmwareLog.RANGE))
    assert swapped.logical is FirmwareLog.RANGE
    assert swapped.wire is FirmwareLog.RANGEH


def test_swap_makes_the_primary_role_read_the_secondary_transcript() -> None:
    args = argparse.Namespace(
        replay=FIXTURES / "RANGEHB.bin", antenna="primary", swap_antennas=True
    )
    records = capture_records(args, [FirmwareLog.RANGE])["RANGE"]
    assert records
    assert all(record.name == "RANGEH" for record in records)


def test_selection_is_applied_before_the_swap() -> None:
    args = argparse.Namespace(
        replay=FIXTURES / "RANGEB.bin", antenna="secondary", swap_antennas=True
    )
    records = capture_records(args, [FirmwareLog.RANGE])["RANGE"]
    assert records
    assert all(record.name == "RANGE" for record in records)


def test_antenna_names_map_to_input_numbers() -> None:
    assert (antenna_index("primary"), antenna_index("1")) == (1, 1)
    assert (antenna_index("secondary"), antenna_index("2")) == (2, 2)
    assert other_antenna("primary") == "secondary"
    assert other_antenna("2") == "primary"
    with pytest.raises(ValueError, match="primary/1 or secondary/2"):
        antenna_index("ant3")
