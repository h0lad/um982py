"""Decode frames into typed records."""

from collections import defaultdict
from dataclasses import replace
from functools import cache
from math import isfinite
from typing import TYPE_CHECKING

from um982py.errors import ProtocolError, UnknownLogError
from um982py.messages.frames import (
    AbbreviatedAsciiMessage,
    AsciiMessage,
    BinaryMessage,
    LogListMessage,
    Message,
    RtcmMessage,
    Sentence,
)
from um982py.messages.layouts import LAYOUTS
from um982py.messages.nmea import decode_nmea
from um982py.messages.reader import BodyReader
from um982py.messages.record import Record
from um982py.messages.satellites import satellite_information
from um982py.messages.schema import Field

if TYPE_CHECKING:
    from um982py.commands import Log


def _log_entry(line: str) -> Record:
    fields = line.removeprefix("<").replace(",", " ").split()
    if len(fields) == 3:
        name, port, interval = fields
        trigger = interval if interval in ("ONCHANGED", "ONCE") else "ONTIME"
    elif len(fields) == 5 and fields[0] == "LOG":
        _, port, name, trigger, interval = fields
    else:
        raise ProtocolError("Invalid UNILOGLIST entry")
    if port not in ("COM1", "COM2", "COM3") or trigger not in (
        "ONTIME",
        "ONCE",
        "ONCHANGED",
    ):
        raise ProtocolError("Invalid UNILOGLIST port or trigger")
    period = float(interval) if trigger == "ONTIME" else None
    if period is not None and (not isfinite(period) or period <= 0):
        raise ProtocolError("Invalid UNILOGLIST period")
    return Record(
        "log",
        (("name", name), ("port", port), ("trigger", trigger), ("period", period)),
    )


def decode_log(message: Message, *, log: Log | None = None) -> Record:
    """Decode a frame, requiring an explicit log for ambiguous binary IDs."""
    from um982py.commands import Log
    from um982py.commands.logging import request

    if log is not None:
        if not isinstance(log, Log):
            raise TypeError("log must be a Log")
        if (
            log is Log.RTCM1032
            and isinstance(message, RtcmMessage)
            and message.message_type == 1032
        ):
            from um982py.rtcm import decode_rtcm

            return decode_rtcm(message)
        binary = isinstance(message, BinaryMessage)
        if binary and log.definition.binary_command is None:
            raise ProtocolError(f"{log.value} has no binary body")
        if not request(
            log.wire_name(binary=binary), message_id=log.definition.message_id
        ).matches(message):
            raise ProtocolError(f"Expected {log.value}")
    try:
        return _decode_log(message, log=log)
    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise ProtocolError("Malformed log body") from error


def _decode_log(message: Message, *, log: Log | None) -> Record:
    if isinstance(message, Sentence):
        return decode_nmea(message)
    if isinstance(message, RtcmMessage):
        from um982py.rtcm import decode_rtcm

        return decode_rtcm(message)
    if isinstance(message, LogListMessage):
        entries = tuple(_log_entry(line) for line in message.entries)
        return Record(
            "UNILOGLIST", (("logs", tuple(entries)), ("checksum_verified", 0)), message
        )
    if not isinstance(message, (AsciiMessage, BinaryMessage)):
        raise ProtocolError("Expected a documented data log")
    if log is None:
        matches = _matching_logs(message)
        if not matches:
            raise UnknownLogError("Unknown or unsupported data log")
        if len(matches) > 1:
            names = ", ".join(candidate.value for candidate in matches)
            raise ProtocolError(f"Ambiguous message ({names}); specify log")
        log = matches[0]
    name = log.value
    from um982py.commands.extended import EXTENDED_LOGS

    if name in EXTENDED_LOGS:
        from um982py.messages.extended import decode_extended

        return decode_extended(name, message)
    payload: bytes | tuple[str, ...] = (
        message.fields if isinstance(message, AsciiMessage) else message.payload
    )
    if name == "SATSINFO":
        return replace(satellite_information(payload), message=message)
    if name not in LAYOUTS:
        raise ProtocolError(f"No body layout for {name}")
    layout = LAYOUTS[name]
    if name == "L1SMT48" and isinstance(payload, tuple) and len(payload) > 10:
        # The printed example contains five mask bytes. The binary layout has eight.
        hex_mask = payload[10]
        if len(hex_mask) not in (10, 16):
            raise ProtocolError("L1SMT48 BDS mask must contain 5 or 8 bytes")
        layout = replace(
            layout,
            fields=tuple(
                replace(field, size=len(hex_mask) // 2)
                if isinstance(field, Field) and field.name == "bds_mask"
                else field
                for field in layout.fields
            ),
        )
    if name == "LBANDAUTH" and isinstance(payload, tuple) and len(payload) == 6:
        # The R1.15 example includes the field omitted from its table at H+48.
        fields = tuple(
            replace(field, ascii_count=1)
            if isinstance(field, Field) and field.name == "reserved_1"
            else field
            for field in layout.fields
        )
        layout = replace(layout, fields=fields)
    if name == "APPPNAV" and isinstance(payload, tuple) and len(payload) == 21:
        # R1.15's ASCII example has four undocumented tail fields, so retain
        # the values under unverified field names.
        ppp_fields = LAYOUTS["PPPNAV"].fields
        layout = replace(
            layout,
            fields=(
                *ppp_fields[:17],
                *(
                    replace(field, name=f"unverified_tail_{i}")
                    for i, field in enumerate(ppp_fields[17:], 1)
                ),
            ),
        )
    if (
        isinstance(payload, tuple)
        and len(payload) == 29
        and layout.fields[-1].name == "horspd_std"
    ):
        # The manual also shows a single reserved tail instead of two deviations.
        layout = replace(
            layout,
            fields=(*layout.fields[:-2], Field("tail_reserved", "x", 112, 4)),
        )
    unavailable = (
        frozenset({"lat_std", "lon_std", "hgt_std"})
        if name in {"BESTNAV", "BESTNAVH"}
        else frozenset()
    )
    record = BodyReader(payload, nonfinite_as_none=unavailable).read(layout)
    if (
        name
        in {"PPPB2BINFO1", "PPPB2BINFO2", "PPPB2BINFO3", "PPPB2BINFO4", "PPPB2BINFO5"}
        and not 0 <= record.integer("seconds_of_day") < 86400
    ):
        raise ProtocolError("PPPB2BINFO epoch is outside its day")
    if name == "PPPB2BINFO3" and any(
        bias.integer("bias_count") > 15 for bias in record.records("code_biases")
    ):
        raise ProtocolError("PPPB2BINFO3 bias count exceeds the 15-entry array")
    return replace(record, message=message)


def _matching_logs(message: AsciiMessage | BinaryMessage) -> list[Log]:
    if isinstance(message, BinaryMessage):
        key: tuple[str, str | int] = ("binary", message.header.message_id)
    else:
        kind = "table" if isinstance(message, AbbreviatedAsciiMessage) else "ascii"
        key = kind, message.name
    return list(_log_index().get(key, ()))


@cache
def _log_index() -> dict[tuple[str, str | int], tuple[Log, ...]]:
    """Index the static catalogue once, retaining all ambiguous candidates.

    Cache only catalogue entries, never names supplied by incoming traffic.
    Construction stays lazy to preserve the core receiver import boundary.
    """
    from um982py.commands import Log
    from um982py.commands.catalog import RTCM_LOGS
    from um982py.commands.extended import EXTENDED_LOGS

    index: dict[tuple[str, str | int], list[Log]] = defaultdict(list)
    for log in Log:
        definition = log.definition
        if (
            log.value not in RTCM_LOGS
            # SATINFOB uses the same on-wire ID and body as SATSINFOB.
            and log is not Log.SATINFO
            and definition.binary_command is not None
            and definition.message_id is not None
        ):
            index["binary", definition.message_id].append(log)
        index["ascii", definition.ascii_command].append(log)
        if log.value in EXTENDED_LOGS and definition.ascii_command != log.value:
            index["ascii", log.value].append(log)
        for name in {log.value, definition.ascii_command}:
            index["table", name].append(log)
    return {key: tuple(logs) for key, logs in index.items()}
