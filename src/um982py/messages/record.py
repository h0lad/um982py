"""Immutable mapping of decoded message bodies."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Self, cast

from um982py.messages.frames import Message

type Value = int | float | str | bytes | Record | tuple[Value, ...] | None


@dataclass(frozen=True, slots=True)
class Record(Mapping[str, Value]):
    name: str
    entries: tuple[tuple[str, Value], ...]
    message: Message | None = None

    def __getitem__(self, key: str) -> Value:
        for name, value in self.entries:
            if name == key:
                return value
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return (name for name, _ in self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def integer(self, key: str) -> int:
        value = self[key]
        if not isinstance(value, int):
            raise TypeError(f"{key} is not an integer")
        return value

    def real(self, key: str) -> float:
        value = self[key]
        if not isinstance(value, (int, float)):
            raise TypeError(f"{key} is not numeric")
        return float(value)

    def records(self, key: str) -> tuple[Self, ...]:
        value = self[key]
        if not isinstance(value, tuple) or any(
            not isinstance(v, Record) for v in value
        ):
            raise TypeError(f"{key} is not a record sequence")
        return tuple(cast(Self, v) for v in value if isinstance(v, Record))
