"""Field, group and layout schema types."""

from dataclasses import dataclass
from typing import Literal, Self

type Kind = Literal["u", "i", "f", "d", "s", "x", "X", "e", "b", "sat"]


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    kind: Kind
    offset: int
    size: int
    count: int | str | None = None
    ascii_count: int | str | None = None
    limit: int = 4096


@dataclass(frozen=True, slots=True)
class Group:
    name: str
    offset: int
    fields: tuple[Field | Self, ...]
    count: int | str
    stride: int | None
    ascii_count: int | str | None = None
    limit: int = 4096


@dataclass(frozen=True, slots=True)
class Layout:
    name: str
    table: str
    fields: tuple[Field | Group, ...]
    size: int | None
