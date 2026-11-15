"""Shared observation normalization for quality checks and file exporters."""

from um982py.errors import ProtocolError
from um982py.messages.observations import Observation
from um982py.messages.record import Record


def range_observation(row: Record, name: str) -> Record:
    """Normalize native observations without reconstructing modulo carrier phase."""
    if name in ("OBSVMCMP", "OBSVHCMP"):
        if not isinstance(row.get("cmp_record"), bytes):
            raise ProtocolError("Expected a compressed observation")
        compressed = Observation.from_record(row)
        return Record(
            "observation",
            (
                ("prn", compressed.prn),
                (
                    "frequency_channel",
                    (compressed.glonass_frequency or 0) + 7,
                ),
                ("pseudorange", compressed.pseudorange_m),
                ("carrier_phase", compressed.carrier_phase_cycles),
                ("phase_available", 0),
                ("doppler", compressed.doppler_hz),
                ("cn0", compressed.cn0_db_hz),
                ("lock_time", compressed.lock_seconds),
                ("tracking_status", compressed.tracking.raw),
            ),
        )
    if name not in ("OBSVM", "OBSVH", "OBSVBASE"):
        return row
    return Record(
        "observation",
        (
            ("prn", row.integer("prn_slot")),
            ("frequency_channel", row.integer("system_freq")),
            ("pseudorange", row.real("psr")),
            ("carrier_phase", row.real("adr")),
            ("doppler", row.real("dopp")),
            ("cn0", row.real("c_n0") / 100),
            ("lock_time", row.real("locktime")),
            ("tracking_status", row.integer("ch_tr_status")),
        ),
    )
