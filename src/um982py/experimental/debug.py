"""Build receiver debug commands without sending or saving them."""

import re
from dataclasses import dataclass
from enum import StrEnum

from um982py.commands import logging
from um982py.commands.core import Command, action
from um982py.commands.types import Port, Trigger
from um982py.commands.validation import config, integer, text
from um982py.messages import CommandResponse

_WORD_MASK = (1 << 32) - 1


def debug_write_target(value: int) -> int:
    """Return the destination of ENTERDEBUGMODE's fixed 0x33 word write."""
    integer(value, -(1 << 31), (1 << 31) - 1)
    return ~value & _WORD_MASK


def enter_debug_mode(value: int) -> Command[CommandResponse]:
    """Build ``ENTERDEBUGMODE``, a one-word write rather than a query."""
    return action(f"ENTERDEBUGMODE {integer(value, -(1 << 31), (1 << 31) - 1)}")


def enter_debug_mode_at(target: int) -> Command[CommandResponse]:
    """Build the fixed word write for an aligned 32-bit target."""
    integer(target, 0, _WORD_MASK)
    if target % 4:
        raise ValueError("Debug word-write target must be four-byte aligned")
    value = ~target & _WORD_MASK
    if value >= 1 << 31:
        value -= 1 << 32
    return enter_debug_mode(value)


def bb_debug(*, enabled: bool) -> Command[CommandResponse]:
    """Build BBDEBUG ON/OFF, whose original setting has no verified query."""
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    return action("BBDEBUG ON" if enabled else "BBDEBUG OFF")


def bb_command(command: str) -> Command[CommandResponse]:
    """Forward one ``$``-prefixed command to the baseband via ``BBCMD``."""
    if not command.startswith("$"):
        raise ValueError("Baseband command must start with '$'")
    if len(command) > 127:
        raise ValueError("Baseband command is limited to 127 characters")
    if any(not 32 <= ord(char) < 127 for char in command):
        raise ValueError("Baseband command must contain printable ASCII only")
    if any(char in command for char in "*#;"):
        raise ValueError("Baseband command contains a protocol delimiter")
    return action(f"BBCMD {command}")


def bb_log_enable(mask: int) -> Command[CommandResponse]:
    """Build ``$BBLOGEN,<hex>`` and forward it through ``BBCMD``."""
    integer(mask, 0, _WORD_MASK)
    return bb_command(f"$BBLOGEN,{mask:08X}")


def debug_level(level: int) -> Command[CommandResponse]:
    """Set the single-digit diagnostic level 0..8, which CONFIG reports back."""
    return config("DEBUGLEVEL", integer(level, 0, 8))


def event_cpu_speed(profile: int) -> Command[CommandResponse]:
    """Build EVTCPUSPEED 0..3, whose frequencies and effects are unverified."""
    return action(f"EVTCPUSPEED {integer(profile, 0, 3)}")


def event_memory(value: int) -> Command[CommandResponse]:
    """Build EVTMEMORY 0..1024, which is not a documented memory-read API."""
    return action(f"EVTMEMORY {integer(value, 0, 1024)}")


def event_stack(task: str) -> Command[CommandResponse]:
    """Build EVTSHOWSTACK for a task token of at most 31 ASCII characters."""
    return action(f"EVTSHOWSTACK {text(task, 31)}")


class DebugOutput(StrEnum):
    """Raw-output paths where an acknowledgement proves no delivery."""

    SAMPLE_DATA = "DATASAMPLE"
    BASEBAND_PACKETS = "RAWBBPKG"
    BASEBAND_TRANSFER = "TRANSBBPKG"
    RAWDATA = "RAWDATAB"
    RAWDATA_SECONDARY = "RAWDATAHB"
    BASEBAND_NOTICE = "BBNOTICE"

    def once(self) -> Command[CommandResponse]:
        """Request the path and match only its command acknowledgement."""
        return action(self.value)

    def output(
        self, interval: float | Trigger = 1, *, port: Port | None = None
    ) -> Command[CommandResponse]:
        if self == self.BASEBAND_NOTICE and interval != Trigger.ON_CHANGED:
            raise ValueError("BBNOTICE requires ONCHANGED; use on_changed()")
        return logging.output(self.value, interval, port=port)

    def on_changed(self, *, port: Port | None = None) -> Command[CommandResponse]:
        if self not in (self.BASEBAND_PACKETS, self.BASEBAND_NOTICE):
            raise ValueError("Only RAWBBPKG and BBNOTICE support ONCHANGED here")
        return self.output(Trigger.ON_CHANGED, port=port)

    def stop(self, *, port: Port | None = None) -> Command[CommandResponse]:
        return logging.stop(self.value, port=port)

    @property
    def carries_baseband_containers(self) -> bool:
        """Return true only for the path with a container output (RAWBBPKG)."""
        return self == self.BASEBAND_PACKETS


class InternalDebugLog(StrEnum):
    """Selects registered internal filter and positioning debug streams."""

    FAST_DEBUG = "FASTDEBUGMSG"
    PVT_DEBUG = "PVTDEBUGMSG"
    MPT_DEBUG = "MPTDEBUGMSG"
    PPP_DEBUG = "PPPDEBUGMSG"
    PPP_DEBUG_SECONDARY = "PPPHDEBUGMSG"
    MPPP_DEBUG = "MPPPDEBUGMSG"
    MPPP_DEBUG_SECONDARY = "MPPPHDEBUGMSG"
    DEBUG_INFO = "DEBUGINFOA"

    @property
    def onchanged_only(self) -> bool:
        """Return true when the stream only accepts ONCHANGED subscriptions."""
        return self not in (self.FAST_DEBUG, self.DEBUG_INFO)

    def output(
        self,
        interval: float | Trigger = Trigger.ON_CHANGED,
        *,
        port: Port | None = None,
    ) -> Command[CommandResponse]:
        """Build a periodic or ONCHANGED subscription command."""
        if self.onchanged_only and interval != Trigger.ON_CHANGED:
            raise ValueError(f"{self.value} requires ONCHANGED; use on_changed()")
        return logging.output(self.value, interval, port=port)

    def on_changed(self, *, port: Port | None = None) -> Command[CommandResponse]:
        """Subscribe to event-driven output."""
        if self == self.DEBUG_INFO:
            raise ValueError("DEBUGINFOA requires a numeric interval")
        return logging.output(self.value, Trigger.ON_CHANGED, port=port)

    def stop(self, *, port: Port | None = None) -> Command[CommandResponse]:
        """Stop the debug stream."""
        return logging.stop(self.value, port=port)


@dataclass(frozen=True, slots=True)
class PppDebugResidual:
    """One satellite and frequency residual from PPPDEBUGMSG."""

    slot: int
    frequency_index: int
    residual_m: float


@dataclass(frozen=True, slots=True)
class PppDebugData:
    """Parsed internal PPP filter state from PPPDEBUGMSG or PPPHDEBUGMSG."""

    source: str
    milliseconds: int
    ssr_epochs: tuple[int, int, int, int, int]
    ssr_types: tuple[int, int, int, int, int]
    corrected_counts: dict[str, int]
    iode_slots: tuple[int, ...]
    velocity_mps: tuple[float, float, float] | None
    processed_satellites: int | None
    delta_position_m: tuple[float, float, float] | None
    residuals: tuple[PppDebugResidual, ...]


_PPP_HEADER = re.compile(
    r"^\$(PPPDEBUGMSG|PPPHDEBUGMSG),\$PPPDATA,"
    r"Msec:(\d+)"
    r"SsrT:(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+)"
    r"Type:(-?\d+),(-?\d+),(-?\d+),(-?\d+),(-?\d+)"
    r"CorNum:G(\d+)C(\d+)E(\d+)R(\d+)C(\d+);"
    r"IODE:([S0-9]*)"
    r"(.*) \*End$".replace(" ", "")
)
_PPP_VEL = re.compile(r"Vel:(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_PPP_PRC = re.compile(r"PrcNum(\d+);")
_PPP_DX = re.compile(r"dX(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_PPP_RES = re.compile(r"S(\d+)F(\d):(-?\d+(?:\.\d+)?)")


def parse_ppp_debug(raw: bytes | str) -> PppDebugData | None:
    """Parse a PPPDEBUGMSG or PPPHDEBUGMSG line into structured filter state."""
    text_line = (
        raw.decode("latin1", errors="replace") if isinstance(raw, bytes) else raw
    ).strip()
    match = _PPP_HEADER.match(text_line)
    if match is None:
        return None
    source = match.group(1)
    milliseconds = int(match.group(2))
    ssr_epochs = (
        int(match.group(3)),
        int(match.group(4)),
        int(match.group(5)),
        int(match.group(6)),
        int(match.group(7)),
    )
    ssr_types = (
        int(match.group(8)),
        int(match.group(9)),
        int(match.group(10)),
        int(match.group(11)),
        int(match.group(12)),
    )
    corrected = {
        "GPS": int(match.group(13)),
        "BEIDOU_B2B": int(match.group(14)),
        "GALILEO": int(match.group(15)),
        "GLONASS": int(match.group(16)),
        "BEIDOU": int(match.group(17)),
    }
    iode_text = match.group(18)
    iode_slots = tuple(int(part) for part in iode_text.split("S") if part)
    tail = match.group(19)
    vel_match = _PPP_VEL.search(tail)
    velocity = (
        (
            float(vel_match.group(1)),
            float(vel_match.group(2)),
            float(vel_match.group(3)),
        )
        if vel_match is not None
        else None
    )
    prc_match = _PPP_PRC.search(tail)
    processed = int(prc_match.group(1)) if prc_match is not None else None
    dx_match = _PPP_DX.search(tail)
    delta_pos = (
        (
            float(dx_match.group(1)),
            float(dx_match.group(2)),
            float(dx_match.group(3)),
        )
        if dx_match is not None
        else None
    )
    residuals = tuple(
        PppDebugResidual(int(m.group(1)), int(m.group(2)), float(m.group(3)))
        for m in _PPP_RES.finditer(tail)
    )
    return PppDebugData(
        source=source,
        milliseconds=milliseconds,
        ssr_epochs=ssr_epochs,
        ssr_types=ssr_types,
        corrected_counts=corrected,
        iode_slots=iode_slots,
        velocity_mps=velocity,
        processed_satellites=processed,
        delta_position_m=delta_pos,
        residuals=residuals,
    )


@dataclass(frozen=True, slots=True)
class PosDebugSatelliteQuality:
    satellite: int
    system: int
    signal: int
    slot_id: int
    slot_mode: int | None
    slot_status: int | None
    displacement_1: float
    displacement_2: float
    displacement_3: float
    residual: float
    doppler_rate: float
    satellites_used: int
    frequency_index: int
    status_hex: int


@dataclass(frozen=True, slots=True)
class PosDebugData:
    """Parsed POSDEBUG fields and undecoded tokens."""

    week: int
    seconds_of_week: float
    tracked_satellites: int
    used_satellites: int
    mode_1: int
    mode_2: int
    mode_3: int
    message_type: int
    previous_seconds_of_week: float | None
    previous_tracked_satellites: int | None
    ls_locked: int | None
    ls_mode: int | None
    ls_extra: int | None
    filter_rate_hz: float | None
    signal_count: int | None
    rtk_gap: tuple[int, int, int, int] | None
    rtk_base_count: int | None
    rtk_base_satellites: int | None
    trailer: int | None
    adr_locked: int | None
    adr_total: int | None
    adr_rate: float | None
    time_to_fix_mode: int | None
    time_to_fix_flags: int | None
    phase_bias_value: float | None
    phase_bias_flag: int | None
    phase_bias_components: tuple[float, float, float, float] | None
    doppler_epoch: float | None
    doppler_flag: int | None
    doppler_velocity: tuple[float, float, float, float] | None
    baseline_correction: float | None
    data_interval_seconds: float | None
    residual_phase_2_slot: int | None
    residual_phase_2_mode: int | None
    residual_phase_2_id: int | None
    residual_phase_2_value: float | None
    next_week_state: int | None
    next_week_satellites: int | None
    next_week_flag: int | None
    measurement_bit_rate: int | None
    reference_filter_phase_slot: int | None
    reference_filter_phase_value: float | None
    satellite_qualities: tuple[PosDebugSatelliteQuality, ...]
    sl1_blocks: tuple[tuple[tuple[int, int, int], tuple[float, float, float]], ...]
    lse_blocks: tuple[tuple[tuple[int, int, int, float], int], ...]
    baseline_residuals: tuple[float, float, float] | None
    doppler_filter: float | None
    filter_30hz_value: float | None
    filter_30hz_flag: int | None
    ppp_position_type: int | None
    ppp_flag: int | None
    ppp_error_satellite: int | None
    ppp_error_position_type: int | None
    ppp_error_value: float | None
    height_epoch: float | None
    height_mode: int | None
    height_change: float | None
    height_bias: float | None
    height_secondary: float | None
    height_msl: float | None
    filter_l1_phase_value: float | None
    filter_l1_phase_flag: int | None
    settings: tuple[int, int, int, int, float, int] | None
    settings_extended: tuple[int, ...] | None
    position_jump_threshold: int | None
    position_jump_config: tuple[int, int, int, int] | None
    base_station_cycle_error: int | None
    trailer_fields: tuple[str, ...]
    extra: tuple[tuple[str, str], ...]
    tokens: tuple[str, ...]


_POS_HEADER = re.compile(
    r"^\$POSDEBUG,(-?\d+),(-?\d+),(-?\d+),656,(\d+),(-?\d+(?:\.\d+)?),(\d+),(\d+),"
)
_POS_ADR = re.compile(r"^adr(\d+),(\d+),(-?\d+(?:\.\d+)?)$")
_POS_FLPP = re.compile(r"^flpp,(\d+),(\d+)$")
_POS_TFINI = re.compile(r"^tfini(\d+),([0-9A-Fa-f]+)$")
_POS_PB = re.compile(
    r"^pb,(-?\d+(?:\.\d+)?),([0-9A-Fa-f]{2}),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$"
)
_POS_DV = re.compile(
    r"^dv,(-?\d+(?:\.\d+)?),([0-9A-Fa-f]{2}),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$"
)
_POS_BR = re.compile(r"^br,(-?\d+(?:\.\d+)?)$")
_POS_DDT = re.compile(r"^ddt,(-?\d+(?:\.\d+)?)$")
_POS_RP2 = re.compile(r"^rp2,(\d+),(\d+),(\d+)(\d)(\d),(-?\d+(?:\.\d+)?)$")
_POS_RP3 = re.compile(r"^rp3,(\d+),(-?\d+(?:\.\d+)?)$")
_POS_NWST2 = re.compile(r"^nwst2,(\d+),(\d+),(\d+)$")
_POS_RFP0 = re.compile(r"^rfp0,(\d+),(-?\d+(?:\.\d+)?)$")
_POS_SQ_SL0 = re.compile(
    r"^(\d+),(\d+),(\d+),sl(\d),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$"
)
_POS_SQ_TAIL = re.compile(r"^(\d+),(\d+),([0-9A-Fa-f]{2})$")
_POS_SL1 = re.compile(r"^sl1,(\d+),(\d+),(\d+)$")
_POS_SL1_VALUES = re.compile(r"^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$")
_POS_LSE = re.compile(r"^lse(\d+),(\d+),(\d+),(-?\d+(?:\.\d+)?)$")
_POS_LSE_FLAG = re.compile(r"^[0-9A-Fa-f]+$")
_POS_BR3 = re.compile(r"^br3,(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$")
_POS_DF = re.compile(r"^df,(-?\d+(?:\.\d+)?)$")
_POS_F30 = re.compile(r"^f30,(-?\d+(?:\.\d+)?),(\d+)$")
_POS_HGT = re.compile(
    r"^hgt,(-?\d+(?:\.\d+)?),(\d+),(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$"
)
_POS_HGT_TAIL = re.compile(r"^(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$")
_POS_FLP0 = re.compile(r"^flp0,(-?\d+(?:\.\d+)?),(\d+)$")
_POS_SET = re.compile(r"^set,(\d+),(\d+),(\d+),(\d+),(-?\d+(?:\.\d+)?),(\d+)$")
_POS_SET1 = re.compile(r"^set1,([0-9A-Fa-f]+),(\d+)$")
_POS_BSCE = re.compile(r"^bsce([0-9A-Fa-f]{2})$")
_POS_XJ = re.compile(r"^xj,(\d+)$")


def _float_or_none(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _int_or_none(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_pos_debug(raw: bytes | str) -> PosDebugData | None:
    """Parse selected FASTDEBUGMSG fields while retaining undecoded tokens."""
    text_line = (
        raw.decode("latin1", errors="replace") if isinstance(raw, bytes) else raw
    ).strip()
    if not text_line.startswith("$POSDEBUG,") or not text_line.endswith("*End"):
        return None
    body = text_line[:-4]
    match = _POS_HEADER.match(body)
    if match is None:
        return None
    tokens = tuple(part for part in body.split(";") if part)

    adr_locked = adr_total = None
    adr_rate = None
    tfini_mode = tfini_flags = None
    pb_value = pb_flag = None
    pb_components = None
    dv_epoch = dv_flag = None
    dv_components = None
    br_value = None
    ddt_value = None
    rp2_slot = rp2_mode = rp2_id = rp2_value = None
    nwst2_state = nwst2_sat = nwst2_flag = None
    rfp0_slot = rfp0_value = None
    qualities: list[PosDebugSatelliteQuality] = []
    sl1_blocks: list[tuple[tuple[int, int, int], tuple[float, float, float]]] = []
    lse_blocks: list[tuple[tuple[int, int, int, float], int]] = []
    consumed: set[int] = set()
    br3 = None
    df_value = None
    f30_value = f30_flag = None
    flpp_type = flpp_flag = None
    fppe_sat = fppe_type = fppe_value = None
    hgt_epoch = hgt_mode = None
    hgt_change = hgt_bias = hgt_secondary = hgt_msl = None
    flp0_value = flp0_flag = None
    set_fields = None
    set1_fields = None
    xj_threshold = None
    bsce_value = None
    trailer: tuple[str, ...] = ()
    extra: list[tuple[str, str]] = []
    pending_satellite: (
        tuple[int, int, int, int, float, float, float, float, float] | None
    ) = None
    for index, token in enumerate(tokens):
        if index in consumed:
            continue
        if token.startswith("sq") and len(token) <= 2:
            continue
        adr_match = _POS_ADR.match(token)
        if adr_match is not None:
            adr_locked = int(adr_match.group(1))
            adr_total = int(adr_match.group(2))
            adr_rate = float(adr_match.group(3))
            continue
        tfini_match = _POS_TFINI.match(token)
        if tfini_match is not None:
            tfini_mode = int(tfini_match.group(1))
            tfini_flags = int(tfini_match.group(2), 16)
            continue
        pb_match = _POS_PB.match(token)
        if pb_match is not None:
            pb_value = float(pb_match.group(1))
            pb_flag = int(pb_match.group(2), 16)
            pb_components = (
                float(pb_match.group(3)),
                float(pb_match.group(4)),
                float(pb_match.group(5)),
                float(pb_match.group(6)),
            )
            continue
        dv_match = _POS_DV.match(token)
        if dv_match is not None:
            dv_epoch = float(dv_match.group(1))
            dv_flag = int(dv_match.group(2), 16)
            dv_components = (
                float(dv_match.group(3)),
                float(dv_match.group(4)),
                float(dv_match.group(5)),
                float(dv_match.group(6)),
            )
            continue
        br_match = _POS_BR.match(token)
        if br_match is not None:
            br_value = float(br_match.group(1))
            continue
        ddt_match = _POS_DDT.match(token)
        if ddt_match is not None:
            ddt_value = float(ddt_match.group(1))
            continue
        rp2_match = _POS_RP2.match(token)
        if rp2_match is not None:
            rp2_slot = int(rp2_match.group(1))
            rp2_mode = int(rp2_match.group(2))
            rp2_id = int(rp2_match.group(3) + rp2_match.group(4) + rp2_match.group(5))
            rp2_value = float(rp2_match.group(6))
            continue
        rp3_match = _POS_RP3.match(token)
        if rp3_match is not None:
            continue
        nwst2_match = _POS_NWST2.match(token)
        if nwst2_match is not None:
            nwst2_state = int(nwst2_match.group(1))
            nwst2_sat = int(nwst2_match.group(2))
            nwst2_flag = int(nwst2_match.group(3))
            continue
        rfp0_match = _POS_RFP0.match(token)
        if rfp0_match is not None:
            rfp0_slot = int(rfp0_match.group(1))
            rfp0_value = float(rfp0_match.group(2))
            continue
        sq_match = _POS_SQ_SL0.match(token)
        if sq_match is not None:
            pending_satellite = (
                int(sq_match.group(1)),
                int(sq_match.group(2)),
                int(sq_match.group(3)),
                int(sq_match.group(4)),
                float(sq_match.group(5)),
                float(sq_match.group(6)),
                float(sq_match.group(7)),
                float(sq_match.group(8)),
                float(sq_match.group(9)),
            )
            continue
        sq_tail_match = _POS_SQ_TAIL.match(token)
        if sq_tail_match is not None and pending_satellite is not None:
            s = pending_satellite
            qualities.append(
                PosDebugSatelliteQuality(
                    s[0],
                    s[1],
                    s[2],
                    s[3],
                    None,
                    None,
                    s[4],
                    s[5],
                    s[6],
                    s[7],
                    s[8],
                    int(sq_tail_match.group(1)),
                    int(sq_tail_match.group(2)),
                    int(sq_tail_match.group(3), 16),
                )
            )
            pending_satellite = None
            continue
        sl1_match = _POS_SL1.match(token)
        if sl1_match is not None and index + 1 < len(tokens):
            sl1_values_match = _POS_SL1_VALUES.match(tokens[index + 1])
            if sl1_values_match is not None:
                sl1_blocks.append(
                    (
                        (
                            int(sl1_match.group(1)),
                            int(sl1_match.group(2)),
                            int(sl1_match.group(3)),
                        ),
                        (
                            float(sl1_values_match.group(1)),
                            float(sl1_values_match.group(2)),
                            float(sl1_values_match.group(3)),
                        ),
                    )
                )
                consumed.add(index + 1)
                continue
        lse_match = _POS_LSE.match(token)
        if (
            lse_match is not None
            and index + 1 < len(tokens)
            and _POS_LSE_FLAG.fullmatch(tokens[index + 1])
        ):
            lse_blocks.append(
                (
                    (
                        int(lse_match.group(1)),
                        int(lse_match.group(2)),
                        int(lse_match.group(3)),
                        float(lse_match.group(4)),
                    ),
                    int(tokens[index + 1], 16),
                )
            )
            consumed.add(index + 1)
            continue
        br3_match = _POS_BR3.match(token)
        if br3_match is not None:
            br3 = (
                float(br3_match.group(1)),
                float(br3_match.group(2)),
                float(br3_match.group(3)),
            )
            continue
        df_match = _POS_DF.match(token)
        if df_match is not None:
            df_value = float(df_match.group(1))
            continue
        f30_match = _POS_F30.match(token)
        if f30_match is not None:
            f30_value = float(f30_match.group(1))
            f30_flag = int(f30_match.group(2))
            continue
        flpp_match = _POS_FLPP.match(token)
        if flpp_match is not None:
            flpp_type = int(flpp_match.group(1))
            flpp_flag = int(flpp_match.group(2))
            continue
        fppe_match = re.compile(r"^fppe,(\d+), *(\d+),(-?\d+(?:\.\d+)?)$").match(token)
        if fppe_match is not None:
            fppe_sat = int(fppe_match.group(1))
            fppe_type = int(fppe_match.group(2))
            fppe_value = float(fppe_match.group(3))
            continue
        hgt_match = _POS_HGT.match(token)
        if hgt_match is not None:
            hgt_epoch = float(hgt_match.group(1))
            hgt_mode = int(hgt_match.group(2))
            hgt_change = float(hgt_match.group(3))
            hgt_bias = float(hgt_match.group(4))
            if index + 1 < len(tokens):
                tail_match = _POS_HGT_TAIL.match(tokens[index + 1])
                if tail_match is not None:
                    hgt_secondary = float(tail_match.group(1))
                    hgt_msl = float(tail_match.group(2))
            continue
        flp0_match = _POS_FLP0.match(token)
        if flp0_match is not None:
            flp0_value = float(flp0_match.group(1))
            flp0_flag = int(flp0_match.group(2))
            continue
        set_match = _POS_SET.match(token)
        if set_match is not None:
            set_fields = (
                int(set_match.group(1)),
                int(set_match.group(2)),
                int(set_match.group(3)),
                int(set_match.group(4)),
                float(set_match.group(5)),
                int(set_match.group(6)),
            )
            continue
        set1_match = _POS_SET1.match(token)
        if set1_match is not None:
            set1_fields = (
                int(set1_match.group(1), 16),
                int(set1_match.group(2)),
            )
            continue
        xj_match = _POS_XJ.match(token)
        if xj_match is not None:
            xj_threshold = int(xj_match.group(1))
            continue
        bsce_match = _POS_BSCE.match(token)
        if bsce_match is not None:
            bsce_value = int(bsce_match.group(1), 16)
            continue
        if token.startswith("adr"):
            parts = token.split(",")
            if len(parts) == 3:
                extra.append((parts[0], parts[1] + "," + parts[2]))
                continue
        extra.append((token, token))

    return PosDebugData(
        week=int(match.group(4)),
        seconds_of_week=float(match.group(5)),
        tracked_satellites=int(match.group(6)),
        used_satellites=int(match.group(7)),
        mode_1=int(match.group(1)),
        mode_2=int(match.group(2)),
        mode_3=int(match.group(3)),
        message_type=656,
        previous_seconds_of_week=None,
        previous_tracked_satellites=None,
        ls_locked=None,
        ls_mode=None,
        ls_extra=None,
        filter_rate_hz=None,
        signal_count=None,
        rtk_gap=None,
        rtk_base_count=None,
        rtk_base_satellites=None,
        trailer=None,
        adr_locked=adr_locked,
        adr_total=adr_total,
        adr_rate=adr_rate,
        time_to_fix_mode=tfini_mode,
        time_to_fix_flags=tfini_flags,
        phase_bias_value=pb_value,
        phase_bias_flag=pb_flag,
        phase_bias_components=pb_components,
        doppler_epoch=dv_epoch,
        doppler_flag=dv_flag,
        doppler_velocity=dv_components,
        baseline_correction=br_value,
        data_interval_seconds=ddt_value,
        residual_phase_2_slot=rp2_slot,
        residual_phase_2_mode=rp2_mode,
        residual_phase_2_id=rp2_id,
        residual_phase_2_value=rp2_value,
        next_week_state=nwst2_state,
        next_week_satellites=nwst2_sat,
        next_week_flag=nwst2_flag,
        measurement_bit_rate=None,
        reference_filter_phase_slot=rfp0_slot,
        reference_filter_phase_value=rfp0_value,
        satellite_qualities=tuple(qualities),
        sl1_blocks=tuple(sl1_blocks),
        lse_blocks=tuple(lse_blocks),
        baseline_residuals=br3,
        doppler_filter=df_value,
        filter_30hz_value=f30_value,
        filter_30hz_flag=f30_flag,
        ppp_position_type=flpp_type,
        ppp_flag=flpp_flag,
        ppp_error_satellite=fppe_sat,
        ppp_error_position_type=fppe_type,
        ppp_error_value=fppe_value,
        height_epoch=hgt_epoch,
        height_mode=hgt_mode,
        height_change=hgt_change,
        height_bias=hgt_bias,
        height_secondary=hgt_secondary,
        height_msl=hgt_msl,
        filter_l1_phase_value=flp0_value,
        filter_l1_phase_flag=flp0_flag,
        settings=set_fields,
        settings_extended=set1_fields,
        position_jump_threshold=xj_threshold,
        position_jump_config=None,
        base_station_cycle_error=bsce_value,
        trailer_fields=trailer,
        extra=tuple(extra),
        tokens=tokens,
    )


@dataclass(frozen=True, slots=True)
class MptDebugData:
    """Parsed internal multi-GNSS point-positioning state from MPTDEBUGMSG."""

    week: int
    seconds_of_week: float
    tracked_satellites: int
    used_satellites: int
    ecef_m: tuple[float, float, float] | None
    tokens: tuple[str, ...]


_MPT_SAT = re.compile(
    r"^[0-9A-Fa-f]+,(\d+),(-?\d+(?:\.\d+)?),SatCnt:(\d+),(\d+),(-?\d+(?:\.\d+)?),"
)


def parse_mpt_debug(raw: bytes | str) -> MptDebugData | None:
    """Parse an MPTDEBUGMSG ($MPTDEBUG) line into structured positioning metadata."""
    text_line = (
        raw.decode("latin1", errors="replace") if isinstance(raw, bytes) else raw
    ).strip()
    if not text_line.startswith("$MPTDEBUG,") or not text_line.endswith("*End"):
        return None
    tokens = tuple(part for part in text_line[:-4].split(";") if part)
    week = 0
    sow = 0.0
    tracked = 0
    used = 0
    found = False
    ecef: tuple[float, float, float] | None = None
    for index, token in enumerate(tokens):
        sat_match = _MPT_SAT.match(token)
        if sat_match is not None:
            week = int(sat_match.group(1))
            sow = float(sat_match.group(2))
            tracked = int(sat_match.group(3))
            used = int(sat_match.group(4))
            found = True
        if token.startswith("tm1,") and index + 1 < len(tokens):
            coords = tokens[index + 1].split(",")
            if len(coords) == 3:
                try:
                    ecef = (float(coords[0]), float(coords[1]), float(coords[2]))
                except ValueError:
                    ecef = None
    if not found:
        return None
    return MptDebugData(
        week=week,
        seconds_of_week=sow,
        tracked_satellites=tracked,
        used_satellites=used,
        ecef_m=ecef,
        tokens=tokens,
    )
