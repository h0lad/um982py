"""Decode extended receiver log bodies."""

from dataclasses import replace

from um982py.errors import ProtocolError
from um982py.firmware_layouts import LAYOUTS
from um982py.messages import AsciiMessage, BinaryMessage, Message, Record
from um982py.messages.reader import BodyReader
from um982py.navigation_layouts import visibility_fields

_DOCUMENTED_FIELDS = {
    "PPSSTATUS": {
        "status": "field_01",
        "gps_week": "field_02",
        "milliseconds_of_week": "field_03",
        "pulse_error_ns": "field_04",
        "observation_offset_0_01_ns": "field_05",
        "config_info": "field_06",
        "register_status": "field_07",
        "time_estimate_error": "field_08",
        "inner_quality": "field_09",
        "pps_inner_status": "field_10",
        "pps_config_status": "field_11",
        "pps_stage": "field_12",
    },
    "SPOOFINFO": {
        "spoof_notice_mask": "field_03",
        "time_notice_mask": "field_04",
        "spoof_frequency_mask": "field_05",
        "gps_satellite_notice_mask": "field_21",
        "bds_satellite_notice_mask": "field_22",
        "galileo_satellite_notice_mask": "field_23",
        "glonass_satellite_notice_mask": "field_24",
    },
}


def decode_extended(name: str, message: Message) -> Record:
    """Decode an extended log whose frame has already been matched."""
    if isinstance(message, BinaryMessage):
        values: bytes | tuple[str, ...] = message.payload
    elif isinstance(message, AsciiMessage):
        values = message.fields
        if name == "HEADINGOFFSET" and len(values) == 3 and values[-1] == "":
            values = values[:-1]
        if name == "SATVIS2":
            values = visibility_fields(values)
    else:
        raise ProtocolError("Expected an extended data log")
    record = BodyReader(values).read(LAYOUTS[name])
    aliases = _DOCUMENTED_FIELDS.get(name, {})
    return replace(
        record,
        entries=record.entries
        + tuple((alias, record[key]) for alias, key in aliases.items()),
        message=message,
    )
