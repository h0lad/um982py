"""Cross-checks broadcast GPS, Galileo and BeiDou UTC and leap-second data."""

from dataclasses import dataclass

from um982py.gnss import (
    BDT_GPS_SECONDS,
    BDT_GPS_WEEKS,
    WEEK_SECONDS,
    leap_seconds_at,
    wrap,
)
from um982py.messages.record import Record

GST_GPS_WEEKS = 1024
"""GPS week in which Galileo system time week zero starts (22 August 1999)."""


@dataclass(frozen=True, slots=True)
class UtcParameters:
    """One system's UTC parameters on the GPS week and day convention.

    ``deltat_ls`` and ``deltat_lsf`` are GPST minus UTC in whole seconds,
    ``dn`` counts 1 for Sunday, and ``wn_lsf`` is a GPS week. ``a0`` and
    ``a1`` model the sub-second system-time minus UTC offset from
    ``reference`` (GPS seconds), or from the start of each BDT week for
    BeiDou, which broadcasts no reference time.
    """

    system: str
    deltat_ls: int
    deltat_lsf: int
    wn_lsf: int
    dn: int
    a0: float
    a1: float
    reference: float | None

    def leap_seconds(self, gps_seconds: float) -> int:
        """GPST minus UTC whole seconds in force at an epoch."""
        return leap_seconds_at(
            gps_seconds,
            deltat_ls=self.deltat_ls,
            wn_lsf=self.wn_lsf,
            dn=self.dn,
            deltat_lsf=self.deltat_lsf,
        )

    @property
    def leap_epoch(self) -> float:
        """GPS seconds at which ``deltat_lsf`` takes effect."""
        return self.wn_lsf * WEEK_SECONDS + self.dn * 86_400 + self.deltat_ls

    def fractional_offset(self, gps_seconds: float) -> float:
        """Sub-second system time minus UTC from A0 and A1 in seconds."""
        if self.reference is None:
            bdt_of_week = (gps_seconds - BDT_GPS_SECONDS) % WEEK_SECONDS
            return self.a0 + self.a1 * bdt_of_week
        return self.a0 + self.a1 * (gps_seconds - self.reference)


def utc_parameters(record: Record) -> UtcParameters:
    """Normalize IONUTC, GPSUTC, GALUTC or BDSUTC to the GPS convention.

    BeiDou counts BDT weeks and days 0..6 from Sunday, with BDT 14 seconds
    behind GPST (BDS-SIS-ICD-B1I-1.0, section 5.2.4.17). Galileo counts GST
    weeks from GPS week 1024 (Galileo OS SIS ICD, section 5.1.7). The UM982
    reports the GALUTC reference time in the ICD's hour units.
    """
    match record.name:
        case "IONUTC" | "GPSUTC":
            prefix = "utc_" if record.name == "IONUTC" else ""
            reference = record.integer("utc_wn") * WEEK_SECONDS + record.real("tot")
            return UtcParameters(
                "GPS",
                record.integer("deltat_ls"),
                record.integer("deltat_lsf"),
                record.integer("wn_lsf"),
                record.integer("dn"),
                record.real(f"{prefix}a0"),
                record.real(f"{prefix}a1"),
                reference,
            )
        case "GALUTC":
            return UtcParameters(
                "GALILEO",
                record.integer("deltat_ls"),
                record.integer("deltat_lsf"),
                record.integer("ulwnlsf") + GST_GPS_WEEKS,
                record.integer("dn"),
                record.real("a0"),
                record.real("a1"),
                (record.integer("utc_wn") + GST_GPS_WEEKS) * WEEK_SECONDS
                + record.integer("tot") * 3600,
            )
        case "BDSUTC":
            offset = round(BDT_GPS_SECONDS)
            return UtcParameters(
                "BEIDOU",
                record.integer("deltat_ls") + offset,
                record.integer("deltat_lsf") + offset,
                record.integer("wn_lsf") + BDT_GPS_WEEKS,
                record.integer("dn") + 1,
                record.real("a0"),
                record.real("a1"),
                None,
            )
    raise ValueError(f"{record.name} carries no supported UTC parameters")


def galileo_gps_offset(record: Record, gps_seconds: float) -> float:
    """Broadcast GST minus GPST (GGTO) in seconds, Galileo OS SIS ICD 5.1.8.

    The reference week is broadcast modulo 64 and is resolved near the epoch.
    """
    week = gps_seconds // WEEK_SECONDS - GST_GPS_WEEKS
    reference_week = week + wrap(record.integer("ulwn0g") - week, 64)
    elapsed = (
        gps_seconds
        - (reference_week + GST_GPS_WEEKS) * WEEK_SECONDS
        - record.integer("ult0g")
    )
    return record.real("da0g") + record.real("da1g") * elapsed
