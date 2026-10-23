"""Conservative QZSS SLAS (L1S) satellite mapping for L1SMT48/49/50 records."""

from dataclasses import dataclass
from typing import Literal

from um982py.messages import Record

# (system, SLAS slot prefix, mask width in bits). QZSS SLAS slots J01..J09 are
# mask indices distinct from navigation PRNs (193+), and the mapping to live PRNs
# is revision-dependent and not verified, so results are never marked usable.
_SLOT_WIDTHS: tuple[tuple[str, str, int], ...] = (
    ("GPS", "G", 64),
    ("QZSS", "J", 9),
    ("GLONASS", "R", 36),
    ("GALILEO", "E", 36),
    ("BEIDOU", "C", 36),
)

_MASK_FIELDS = {
    "GPS": "gps_mask",
    "QZSS": "qzss_mask",
    "GLONASS": "glo_mask",
    "GALILEO": "gal_mask",
    "BEIDOU": "bds_mask",
}

BitOrder = Literal["msb", "lsb"]


def _number(value: object) -> int | float | str | bytes:
    if not isinstance(value, (int, float, str, bytes)):
        raise TypeError("expected a numeric value")
    return value


def _values(record: Record, field: str) -> tuple[object, ...] | bytes:
    value = record[field]
    if not isinstance(value, (tuple, bytes)):
        raise TypeError(f"{field} is not a sequence")
    return value


def _bits(data: bytes, count: int, *, msb: bool) -> tuple[bool, ...]:
    bit_order = range(7, -1, -1) if msb else range(8)
    bits = [int((byte >> shift) & 1) for byte in data for shift in bit_order]
    if len(bits) < count:
        raise ValueError(f"mask too short: {len(bits)} bits, need {count}")
    return tuple(bool(bit) for bit in bits[:count])


def _mask_bytes(record: Record, system: str) -> bytes:
    value = record[_MASK_FIELDS[system]]
    if not isinstance(value, bytes):
        raise TypeError(f"{system} mask is not bytes")
    return value


@dataclass(frozen=True, slots=True)
class SlasCandidate:
    """One candidate satellite slot from the MT48 PRN mask."""

    system: str
    slot: int
    name: str

    @property
    def slot_name(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class SlasCorrection:
    """One MT50 pseudorange correction for a selected slot.

    ``usable`` is always False: the slot-to-PRN mapping and bit packing are
    not verified against receiver data, so this must never correct a fix.
    """

    satellite: str
    pseudorange_m: float
    iod: int | None
    usable: bool = False


@dataclass(frozen=True, slots=True)
class SlasResult:
    """The conservative result of mapping L1SMT48/49/50 records."""

    candidates: tuple[SlasCandidate, ...]
    selected: tuple[str, ...]
    iod_by_satellite: tuple[tuple[str, int], ...]
    corrections: tuple[SlasCorrection, ...]
    status: str
    usable: bool = False


def slas_candidates(
    mask_record: Record, *, msb: bool = True
) -> tuple[SlasCandidate, ...]:
    """Extract candidate satellite slots from an L1SMT48 record."""
    candidates: list[SlasCandidate] = []
    for system, prefix, width in _SLOT_WIDTHS:
        bits = _bits(_mask_bytes(mask_record, system), width, msb=msb)
        for index, bit in enumerate(bits, 1):
            if bit:
                candidates.append(SlasCandidate(system, index, f"{prefix}{index:02d}"))
    if len(candidates) > 23:
        raise ValueError(f"MT48 has {len(candidates)} selected satellites (>23)")
    return tuple(candidates)


def _mask_sv_bits(record: Record, *, msb: bool) -> tuple[bool, ...]:
    value = record["mask_sv"]
    if not isinstance(value, bytes):
        raise TypeError("mask_sv is not bytes")
    return _bits(value, 23, msb=msb)


def slas_selection(
    candidates: tuple[SlasCandidate, ...],
    issue_record: Record,
    *,
    msb: bool = True,
) -> tuple[tuple[str, int], ...]:
    """Map an L1SMT49 record onto MT48 candidates.

    Returns (slot name, IOD) pairs and raises ValueError when the MT49 Mask-SV
    selects bits outside the MT48 candidate list.
    """
    bits = _mask_sv_bits(issue_record, msb=msb)
    if any(bits[len(candidates) :]):
        raise ValueError("MT49 Mask-SV set outside MT48 candidate list")
    iod_values = _values(issue_record, "iod")
    if any(bit and index >= len(iod_values) for index, bit in enumerate(bits)):
        raise ValueError("MT49 has fewer IOD values than selected satellites")
    selected: list[tuple[str, int]] = []
    for index, (candidate, bit) in enumerate(zip(candidates, bits, strict=False)):
        if bit:
            selected.append((candidate.name, int(_number(iod_values[index]))))
    return tuple(selected)


def slas_corrections(
    candidates: tuple[SlasCandidate, ...],
    selection: tuple[tuple[str, int], ...],
    correction_record: Record,
    *,
    msb: bool = True,
) -> tuple[SlasCorrection, ...]:
    """Map an L1SMT50 record onto the MT49 selection.

    The caller must check MT50 IODP/IODI against MT49, as SlasTracker does.
    """
    bits = _mask_sv_bits(correction_record, msb=msb)
    if any(bits[len(candidates) :]):
        raise ValueError("MT50 Mask-SV set outside MT48 candidate list")
    chosen = [
        candidate.name for candidate, bit in zip(candidates, bits, strict=False) if bit
    ]
    if len(chosen) > 14:
        raise ValueError("MT50 has more than 14 corrected satellites")
    iod_by_satellite = dict(selection)
    if any(satellite not in iod_by_satellite for satellite in chosen):
        raise ValueError("MT50 contains satellite not selected by MT49")
    prc = _values(correction_record, "prc")
    if len(prc) < len(chosen):
        raise ValueError("MT50 has fewer corrections than selected satellites")
    return tuple(
        SlasCorrection(
            satellite, float(_number(prc[index])), iod_by_satellite.get(satellite)
        )
        for index, satellite in enumerate(chosen)
    )


class SlasTracker:
    """Sequential L1SMT48/49/50 mapping with cross-message consistency checks.

    Mirrors the conservative reference mapper: MT49 needs a preceding MT48 and
    MT50 needs matching IODI/IODP from the MT49 block. Everything is reported
    as unusable until the slot-to-PRN mapping is validated against receiver
    data.
    """

    def __init__(self, *, mask_msb: bool = True, sv_msb: bool = True) -> None:
        self.mask_msb = mask_msb
        self.sv_msb = sv_msb
        self._candidates: tuple[SlasCandidate, ...] = ()
        self._iodi: int | None = None
        self._iodp: int | None = None
        self._selection: tuple[tuple[str, int], ...] = ()
        self._source_prn: int | None = None
        self._mask_iodp: int | None = None

    def process(
        self,
        record: Record,
        *,
        source_prn: int | None = None,
        mask_iodp: int | None = None,
    ) -> SlasResult | None:
        """Map one source using independently verified transmitter and MT48 IODP.

        R1.15 does not identify the extra ASCII fields or include these two
        fields in the binary tables, so callers must supply them explicitly.
        """
        name = record.name
        try:
            if name not in ("L1SMT48", "L1SMT49", "L1SMT50"):
                return None
            if source_prn is None:
                raise ValueError("source PRN required")
            if self._source_prn is not None and source_prn != self._source_prn:
                raise ValueError("source PRN mismatch; use a tracker per satellite")
            if name == "L1SMT48":
                # Invalidate old state even when the new mask is malformed.
                self._candidates = ()
                self._iodi = self._iodp = None
                self._selection = ()
                self._mask_iodp = None
                if mask_iodp is None:
                    raise ValueError("MT48 IODP required")
                self._candidates = slas_candidates(record, msb=self.mask_msb)
                self._source_prn = source_prn
                self._mask_iodp = mask_iodp
                return SlasResult(
                    candidates=self._candidates,
                    selected=(),
                    iod_by_satellite=(),
                    corrections=(),
                    status="bit_order_requires_receiver_validation",
                )
            if name == "L1SMT49":
                self._iodi = self._iodp = None
                self._selection = ()
                if not self._candidates:
                    raise ValueError("MT49 requires preceding MT48")
                iodi = int(_number(record["iodi"]))
                iodp = int(_number(record["iodp"]))
                if iodp != self._mask_iodp:
                    raise ValueError("MT49 IODP mismatch")
                selection = slas_selection(self._candidates, record, msb=self.sv_msb)
                self._selection, self._iodi, self._iodp = selection, iodi, iodp
                return SlasResult(
                    candidates=self._candidates,
                    selected=tuple(satellite for satellite, _ in self._selection),
                    iod_by_satellite=self._selection,
                    corrections=(),
                    status="conditional_mapping",
                )
            if name == "L1SMT50":
                if not self._candidates:
                    raise ValueError("MT50 requires preceding MT48")
                if self._iodi is None:
                    raise ValueError("MT50 requires preceding MT49")
                if (
                    int(_number(record["iodi"])) != self._iodi
                    or int(_number(record["iodp"])) != self._iodp
                ):
                    raise ValueError(
                        "MT50 IODI/IODP mismatch; correction must not be applied"
                    )
                corrections = slas_corrections(
                    self._candidates, self._selection, record, msb=self.sv_msb
                )
                return SlasResult(
                    candidates=self._candidates,
                    selected=tuple(satellite for satellite, _ in self._selection),
                    iod_by_satellite=self._selection,
                    corrections=corrections,
                    status="mapping_unverified_not_safe_for_positioning",
                )
        except (ValueError, KeyError, TypeError, IndexError) as error:
            if name in ("L1SMT48", "L1SMT49", "L1SMT50"):
                return SlasResult(
                    candidates=self._candidates,
                    selected=(),
                    iod_by_satellite=(),
                    corrections=(),
                    status=f"error: {error}",
                )
        return None
