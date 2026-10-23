"""Mapping from log names to documented body layouts."""

from types import MappingProxyType

from um982py.messages.layouts import (
    atmosphere,
    corrections,
    ephemeris,
    events,
    navigation,
    observations,
    status,
)

__all__ = ["LAYOUTS"]

LAYOUTS = MappingProxyType(
    {
        layout.name: layout
        for family in (
            observations.LAYOUTS,
            ephemeris.LAYOUTS,
            atmosphere.LAYOUTS,
            navigation.LAYOUTS,
            status.LAYOUTS,
            corrections.LAYOUTS,
            events.LAYOUTS,
        )
        for layout in family
    }
)
