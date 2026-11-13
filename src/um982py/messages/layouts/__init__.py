"""Documented receiver and RTCM message layouts."""

from collections.abc import Mapping
from importlib import import_module
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from um982py.messages.schema import Layout

if TYPE_CHECKING:
    LAYOUTS: Mapping[str, Layout]

__all__ = ["LAYOUTS"]


def __getattr__(name: str) -> Mapping[str, Layout]:
    if name != "LAYOUTS":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    families = (
        "observations",
        "ephemeris",
        "atmosphere",
        "navigation",
        "status",
        "corrections",
        "events",
    )
    layouts = MappingProxyType(
        {
            layout.name: layout
            for family in families
            for layout in cast(
                tuple[Layout, ...], import_module(f"{__name__}.{family}").LAYOUTS
            )
        }
    )
    globals()[name] = layouts
    return layouts


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
