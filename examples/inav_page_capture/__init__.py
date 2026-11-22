"""Human-readable rendering of the captured I/NAV page data."""

from collections.abc import Sequence
from typing import cast

from um982py.experimental import (
    BeidouLegacySubframe,
    GlonassFdmaString,
    GpsLnavSubframe,
    InavCampaign,
    InavPage,
    InavWord,
    PageWindowAudit,
    osnma_activity,
)

__all__ = [
    "AUDIT_HEADER",
    "PAGE_HEADER",
    "WORD_HEADER",
    "campaign_window_audits",
    "render_audit",
    "render_campaign",
    "render_native_nav",
    "render_page",
    "render_word",
]

PAGE_HEADER = (
    f"{'PRN':>3}  {'Ch':>4}  {'Part':<10}  {'Word':>4}  {'Valid':<5}"
    f"  {'Page':<32}  {'OSNMA':<10}  SAR"
)
"""Column header of the captured page part table."""

WORD_HEADER = (
    f"{'Word':>4}  {'IODnav':>6}  {'SVID':>4}  {'GST WN':>6}  TOW"
)
"""Column header of the word table."""

AUDIT_HEADER = (
    f"{'PRN':>3}  {'Sync':>4}  {'Errors':>6}  {'Tail':<5}  {'SSP':>4}"
    f"  Decoded"
)
"""Column header of the window decode table."""

ACTIVITY_HEADER = (
    f"{'PRN':>3}  {'Odd':>3}  {'Nonzero':>7}  Observed"
)
"""Column header of the OSNMA activity table."""


def _dash(value: object) -> str:
    return "-" if value is None else str(value)


def _part_label(page: InavPage) -> str:
    half = "even" if page.part.even else "odd"
    return f"{half}/{'nom' if page.part.nominal else 'alert'}"


def _activity_entries(
    pages: Sequence[InavPage],
) -> dict[int, dict[str, object]]:
    activity = osnma_activity(pages)
    return cast("dict[int, dict[str, object]]", activity["prns"])


def render_page(page: InavPage) -> str:
    """Return one table row of a captured page part."""
    osnma = "-" if page.part.osnma is None else page.part.osnma.hex()
    sar = "-" if page.part.sar is None else page.part.sar.hex()
    valid = "yes" if page.page_valid else "no"
    return (
        f"{page.prn:>3}  {page.channel:>4}  {_part_label(page):<10}"
        f"  {_dash(page.part.word_type):>4}  {valid:<5}"
        f"  {page.page.hex()}  {osnma:<10}  {sar}"
    )


def render_word(word: InavWord) -> str:
    """Return one table row of a checksum-verified word."""
    if word.timing is None:
        week = "-"
        tow = "-"
    else:
        week = str(word.timing.week_number)
        tow = str(word.timing.time_of_week)
    return (
        f"{word.word_type:>4}  {_dash(word.iod_nav):>6}"
        f"  {_dash(word.svid):>4}  {week:>6}  {tow}"
    )


def render_audit(audit: PageWindowAudit) -> str:
    """Return one table row of an independent window decode."""
    tail = "-" if audit.tail_valid is None else (
        "yes" if audit.tail_valid else "no"
    )
    ssp = "-" if audit.ssp is None else f"0x{audit.ssp:02x}"
    decoded = "-" if audit.decoded is None else audit.decoded.hex()
    return (
        f"{audit.prn:>3}  {_dash(audit.sync_offset):>4}"
        f"  {_dash(audit.viterbi_errors):>6}  {tail:<5}"
        f"  {ssp:>4}  {decoded}"
    )


def campaign_window_audits(
    campaign: InavCampaign,
) -> tuple[PageWindowAudit, ...]:
    """Return the window decodes of a campaign captured from a receiver.

    Each audit uses only the memory regions of its own snapshot.
    """
    return tuple(
        audit for snapshot in campaign.snapshots for audit in snapshot.window_audits()
    )


def render_native_nav(
    gps: Sequence[GpsLnavSubframe],
    glonass: Sequence[GlonassFdmaString],
    beidou: Sequence[BeidouLegacySubframe] = (),
) -> str:
    """Render the parity-checked native navigation records of one snapshot."""
    lines = [
        f"GPS LNAV ({len(gps)} parity-checked subframes)",
        "PRN    Ch  Subframe  Next TOW (s)  30-bit words (hex)",
    ]
    for frame in gps:
        words = " ".join(f"{word:08x}" for word in frame.words)
        lines.append(
            f"{frame.prn:>3}  {frame.channel:>4}  {frame.subframe:>8}"
            f"  {frame.next_subframe_tow_s:>12}  {words}"
        )
    if not gps:
        lines.append("-")

    lines += [
        "",
        f"GLONASS FDMA ({len(glonass)} Hamming-checked strings)",
        "SVID    Ch  String  85-bit string (hex)",
    ]
    lines.extend(
        f"{record.receiver_svid:>4}  {record.channel:>4}"
        f"  {record.string_number:>6}  {record.bits:022x}"
        for record in glonass
    )
    if not glonass:
        lines.append("-")

    lines += [
        "",
        f"BeiDou legacy ({len(beidou)} BCH-checked subframes)",
        "SVID    Ch  Subframe  BDT SOW (s)  30-bit words (hex)",
    ]
    for frame in beidou:
        words = " ".join(f"{word:08x}" for word in frame.words)
        lines.append(
            f"{frame.receiver_svid:>4}  {frame.channel:>4}  {frame.subframe:>8}"
            f"  {frame.sow_s:>11}  {words}"
        )
    if not beidou:
        lines.append("-")
    return "\n".join(lines)


def render_campaign(
    campaign: InavCampaign,
    *,
    audits: Sequence[PageWindowAudit] = (),
) -> str:
    """Return the human-readable report of one capture campaign.

    The report lists every captured page part, the OSNMA activity per
    satellite, the raw SAR fields, the checksum-verified word
    assemblies and the independent window decodes.
    """
    pages = campaign.pages
    prns = sorted({page.prn for page in pages})
    restored = "yes" if campaign.application_restored else "no"
    if campaign.application_restored is None:
        restored = "-"
    lines = [
        "Galileo I/NAV page capture",
        "==========================",
        "",
        f"Snapshots:             {len(campaign.snapshots)}",
        f"Pages:                 {len(pages)}"
        f" ({len(campaign.unique_pages)} unique)",
        f"PRNs:                  {', '.join(str(prn) for prn in prns) or '-'}",
        f"Application restored:  {restored}",
        "",
        "Captured page parts",
        "-------------------",
        PAGE_HEADER,
    ]
    if pages:
        lines.extend(render_page(page) for page in pages)
    else:
        lines.append("-")

    lines += ["", "OSNMA activity", "--------------", ACTIVITY_HEADER]
    entries = _activity_entries(pages)
    if entries:
        for prn in sorted(entries):
            entry = entries[prn]
            observed = "yes" if entry["observed_osnma"] else "no"
            lines.append(
                f"{prn:>3}  {entry['odd_pages']:>3}"
                f"  {entry['osnma_nonzero']:>7}  {observed}"
            )
    else:
        lines.append("-")

    lines += ["", "Checksum-verified words", "----------------------"]
    words = campaign.words()
    if words:
        lines.append(WORD_HEADER)
        lines.extend(render_word(word) for word in words)
    else:
        lines.append("-")

    lines += ["", "Window decode audits", "--------------------", AUDIT_HEADER]
    if audits:
        lines.extend(render_audit(audit) for audit in audits)
    else:
        lines.append("-")

    lines += [
        "",
        "Part: page half and page type of the stored page part.",
        "Valid: receiver flag for the stored part.",
        "OSNMA: raw field of odd nominal parts. Header decoding requires",
        "the first odd part of a GST-aligned sub-frame.",
        "SAR: raw 22-bit field in hex with two trailing padding bits.",
        "Words: even and odd parts of one page that pass its checksum.",
        "Audits: independent decode of the demodulation symbol window.",
    ]
    return "\n".join(lines)
