"""Decode frames into typed records."""

from dataclasses import replace
from math import isfinite

from um982py.commands.catalog import LOGS, RTCM_LOGS
from um982py.errors import ProtocolError
from um982py.messages.frames import (
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


def decode_log(message: Message) -> Record:
    try:
        return _decode_log(message)
    except (ValueError, TypeError, KeyError, IndexError) as error:
        raise ProtocolError("Malformed log body") from error


def _decode_log(message: Message) -> Record:
    if isinstance(message, Sentence):
        return decode_nmea(message)
    if isinstance(message, RtcmMessage):
        return Record(
            "RTCM",
            (("message_type", message.message_type), ("payload", message.payload)),
            message,
        )
    if isinstance(message, LogListMessage):
        entries = tuple(_log_entry(line) for line in message.entries)
        return Record(
            "UNILOGLIST", (("logs", tuple(entries)), ("checksum_verified", 0)), message
        )
    if isinstance(message, AsciiMessage):
        name = next(
            (
                name
                for name, definition in LOGS.items()
                if definition.ascii_command == message.name
            ),
            None,
        )
        payload: bytes | tuple[str, ...] = message.fields
    elif isinstance(message, BinaryMessage):
        name = next(
            (
                name
                for name, definition in LOGS.items()
                if name not in RTCM_LOGS
                and definition.message_id == message.header.message_id
            ),
            None,
        )
        payload = message.payload
    else:
        raise ProtocolError("Expected a documented data log")
    if name == "SATSINFO":
        return replace(satellite_information(payload), message=message)
    if name is None or name not in LAYOUTS:
        raise ProtocolError(f"No body layout for {name}")
    layout = LAYOUTS[name]
    if name == "L1SMT48" and isinstance(payload, tuple) and len(payload) > 10:
        # The printed example contains five mask bytes, rather than eight.
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
            if isinstance(field, Field) and field.name == "legacy"
            else field
            for field in layout.fields
        )
        layout = replace(layout, fields=fields)
    if name == "APPPNAV" and isinstance(payload, tuple) and len(payload) == 21:
        # R1.15's ASCII example has four undocumented tail fields, so retain
        # their values without assuming PPPNAV semantics for those fields.
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
        layout = replace(
            layout,
            fields=(*layout.fields[:-2], Field("legacy_reserved", "x", 112, 4)),
        )
    record = BodyReader(payload).read(layout)
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
