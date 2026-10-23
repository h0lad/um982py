"""Event and status body layouts."""

from um982py.messages.schema import Field, Layout

HEADER = (
    Field("event_id", "u", 0, 1),
    Field("status", "u", 1, 1),
    Field("reserved", "u", 2, 1),
    Field("reserved_2", "u", 3, 1),
    Field("week", "u", 4, 4),
    Field("second", "u", 8, 4),
    Field("subsecond", "u", 12, 4),
    Field("reserved_3", "u", 16, 4),
    Field("offset_second", "i", 20, 4),
    Field("offset_subsecond", "i", 24, 4),
)
LAYOUTS = (
    Layout("EVENTFLAG", "0-1", HEADER, 28),
    Layout(
        "EVENTSLN",
        "0-3",
        (
            *HEADER,
            Field("solution_status", "e", 28, 4),
            Field("position_type", "e", 32, 4),
            Field("latitude", "d", 36, 8),
            Field("longitude", "d", 44, 8),
            Field("height_msl", "d", 52, 8),
            Field("undulation", "f", 60, 4),
            Field("datum", "e", 64, 4),
            Field("latitude_std", "f", 68, 4),
            Field("longitude_std", "f", 72, 4),
            Field("height_std", "f", 76, 4),
            Field("station_id", "s", 80, 4),
            Field("differential_age", "f", 84, 4),
            Field("solution_age", "f", 88, 4),
            Field("satellites", "u", 92, 1),
            Field("solution_satellites", "u", 93, 1),
            Field("reserved_4", "u", 94, 1),
            Field("reserved_5", "u", 95, 1),
            Field("east_velocity", "f", 96, 4),
            Field("north_velocity", "f", 100, 4),
            Field("up_velocity", "f", 104, 4),
        ),
        108,
    ),
)
