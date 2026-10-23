"""Read values from ASCII and binary payloads."""

import re
from math import isfinite
from struct import unpack

from um982py.errors import ProtocolError
from um982py.messages.record import Record, Value
from um982py.messages.schema import Field, Group, Layout


class BodyReader:
    def __init__(self, data: bytes | tuple[str, ...]) -> None:
        self.data = data
        self.position = 0

    def field(self, field: Field, offset: int, context: Record) -> Value:
        count = field.count
        if not isinstance(self.data, bytes) and field.ascii_count is not None:
            count = field.ascii_count
        if count is None:
            return self.scalar(field, offset + field.offset)
        length = context.integer(count) if isinstance(count, str) else count
        self.bound(length, field.limit)
        if (
            length == 0
            and isinstance(self.data, tuple)
            and self.position < len(self.data)
            and self.data[self.position] == ""
        ):
            self.position += 1
        return tuple(
            self.scalar(field, offset + field.offset + i * field.size)
            for i in range(length)
        )

    def scalar(self, field: Field, offset: int) -> Value:
        try:
            if isinstance(self.data, bytes):
                end = offset + field.size
                if end > len(self.data):
                    raise ProtocolError(f"Truncated {field.name}")
                data = self.data[offset:end]
                self.position = max(self.position, end)
                if field.kind == "s":
                    return data.split(b"\0", 1)[0].decode("ascii")
                if field.kind in ("f", "d"):
                    value: Value = unpack("<" + field.kind, data)[0]
                elif field.kind == "b":
                    return data
                else:
                    value = int.from_bytes(
                        data,
                        "big" if field.kind == "X" else "little",
                        signed=field.kind == "i",
                    )
                if field.kind == "sat":
                    number = int.from_bytes(data[:2], "little")
                    channel = int.from_bytes(data[2:], "little", signed=True)
                    return Record(
                        "satellite_id", (("prn", number), ("channel", channel))
                    )
            else:
                text = self.data[self.position]
                self.position += 1
                if not text:
                    return None
                if field.kind in ("s", "e"):
                    return text
                if field.kind in ("f", "d"):
                    value = float(text)
                elif field.kind == "b":
                    data = bytes.fromhex(text)
                    if len(data) != field.size:
                        raise ValueError("Invalid hexadecimal field length")
                    return data
                elif field.kind == "sat":
                    match = re.fullmatch(r"(\d+)([+-]\d+)?", text)
                    if match is None:
                        raise ValueError("Invalid satellite ID")
                    return Record(
                        "satellite_id",
                        (("prn", int(match[1])), ("channel", int(match[2] or 0))),
                    )
                elif field.kind in ("x", "X"):
                    value = int(text, 16)
                else:
                    value = int(text, 16 if text.lower().startswith("0x") else 10)
                if isinstance(value, int):
                    bits = field.size * 8
                    minimum = -(1 << (bits - 1)) if field.kind == "i" else 0
                    maximum = (1 << (bits - (field.kind == "i"))) - 1
                    if not minimum <= value <= maximum:
                        raise ValueError("Integer field out of range")
            if isinstance(value, float) and not isfinite(value):
                raise ValueError("Non-finite value")
            return value
        except (ValueError, UnicodeError, IndexError) as error:
            raise ProtocolError(f"Invalid {field.name}") from error

    @staticmethod
    def bound(count: int, maximum: int = 4096) -> None:
        if not 0 <= count <= maximum:
            raise ProtocolError(f"Array count out of range: {count}")

    def structure(
        self,
        name: str,
        fields: tuple[Field | Group, ...],
        offset: int = 0,
        inherited: tuple[tuple[str, Value], ...] = (),
    ) -> Record:
        entries: list[tuple[str, Value]] = []
        for field in fields:
            context = Record(name, inherited + tuple(entries))
            if isinstance(field, Field):
                value = self.field(field, offset, context)
            else:
                selected_count = field.count
                if not isinstance(self.data, bytes) and field.ascii_count is not None:
                    selected_count = field.ascii_count
                count = (
                    context.integer(selected_count)
                    if isinstance(selected_count, str)
                    else selected_count
                )
                self.bound(count, field.limit)
                records = []
                position = offset + field.offset
                for _ in range(count):
                    records.append(
                        self.structure(
                            field.name, field.fields, position, context.entries
                        )
                    )
                    position = (
                        position + field.stride if field.stride else self.position
                    )
                value = tuple(records)
            entries.append((field.name, value))
        return Record(name, tuple(entries))

    def read(self, layout: Layout) -> Record:
        if (
            isinstance(self.data, bytes)
            and layout.size is not None
            and len(self.data) != layout.size
        ):
            raise ProtocolError(f"Expected {layout.size} bytes for {layout.name}")
        record = self.structure(layout.name, layout.fields)
        if self.position != len(self.data):
            raise ProtocolError(f"Unexpected trailing data in {layout.name}")
        return record
