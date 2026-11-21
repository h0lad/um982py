"""Human-readable rendering of the captured I/NAV page data."""

from collections.abc import Sequence
from typing import cast

from um982py.experimental import (
    TRACKING_MEMORY_BASE,
    InavCampaign,
    InavPage,
    InavWord,
    PageWindowAudit,
    audit_page_windows,
    extract_channel_states,
    osnma_activity,
)

__all__ = [
    "AUDIT_HEADER",
    "PAGE_HEADER",
    "WORD_HEADER",
    "campaign_window_audits",
    "render_audit",
    "render_campaign",
    "render_page",
    "render_word",
]

PAGE_HEADER = (
    f"{'PRN':>3}  {'Ch':>4}  {'Part':<10}  {'Word':>4}  {'Valid':<5}"
    f"  {'Page':<32}  OSNMA"
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
    valid = "yes" if page.page_valid else "no"
    return (
        f"{page.prn:>3}  {page.channel:>4}  {_part_label(page):<10}"
        f"  {_dash(page.part.word_type):>4}  {valid:<5}"
        f"  {page.page.hex()}  {osnma}"
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

    Campaigns built with :func:`um982py.experimental.capture_inav_pages`
    store the tracking window under the region name ``tracking``; the
    audits are computed against that window.
    """
    regions = {
        f"snapshot{index}": (
            TRACKING_MEMORY_BASE,
            snapshot.regions["tracking"],
        )
        for index, snapshot in enumerate(campaign.snapshots)
    }
    return audit_page_windows(extract_channel_states(regions))


def render_campaign(
    campaign: InavCampaign,
    *,
    audits: Sequence[PageWindowAudit] = (),
) -> str:
    """Return the human-readable report of one capture campaign.

    The report lists every captured page part, the OSNMA activity per
    satellite with the header interpretations, the checksum-verified word
    assemblies and the independent window decodes.
    """
    pages = campaign.pages
    prns = sorted({page.prn for page in pages})
    restored = "yes" if campaign.application_restored else "no"
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
        "OSNMA: raw field of odd nominal parts. Header decoding requires",
        "the first odd part of a GST-aligned sub-frame.",
        "Words: even and odd parts of one page that pass its checksum.",
        "Audits: independent decode of the demodulation symbol window.",
    ]
    return "\n".join(lines)
