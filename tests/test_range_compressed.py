"""Validates RANGECMP decoding against packed synthetic observations."""

import pytest

from test_protocol import binary
from um982py.errors import ProtocolError
from um982py.experimental import CompressedRange, decode_rangecmp
from um982py.experimental.range_compressed import _PSRSTD
from um982py.messages import AsciiMessage, LegacyAsciiHeader
from um982py.protocol import StreamDecoder

LIGHT_SPEED = 299792458.0
FOLD = 1 << 24
HALF_FOLD = 1 << 23
L1_HZ = 1575420000.0
L5_HZ = 1176450000.0
B1_HZ = 1561098000.0
G1_HZ = 1600875000.0

STATUS_L1 = 0x43
STATUS_L5 = (0 << 16) | (6 << 21) | 0x43
STATUS_B1 = (4 << 16) | (0 << 21) | 0x43
STATUS_G1 = (1 << 16) | (0 << 21) | 0x43
STATUS_UNKNOWN = (7 << 16) | 0x43


def pack_entry(
    *,
    status: int,
    prn: int,
    doppler_hz: float,
    pseudorange_m: float,
    phase_cycles: float,
    frequency_hz: float,
    pr_std_index: int = 10,
    adr_std_index: int = 7,
    lock_s: float = 100.0,
    cn0_db: int = 35,
    glo: int = 0,
) -> bytes:
    """Pack one synthetic entry with the firmware fold rule."""
    fold = round(pseudorange_m * frequency_hz / LIGHT_SPEED / FOLD)
    pred = phase_cycles + fold * FOLD
    half = HALF_FOLD if pred >= 0 else 0
    raw = (
        status
        | ((round(doppler_hz * 256) & 0xFFFFFFF) << 32)
        | (round(pseudorange_m * 128) << 60)
        | ((round((pred - half) * 256) & 0xFFFFFFFF) << 96)
        | (pr_std_index << 128)
        | (adr_std_index << 132)
        | (prn << 136)
        | (round(lock_s * 32) << 144)
        | ((cn0_db - 20) << 165)
        | (glo << 170)
    )
    return raw.to_bytes(24, "little")


def pack_frame(entries: tuple[bytes, ...]) -> bytes:
    """Frame synthetic entries with a binary count header."""
    return len(entries).to_bytes(4, "little") + b"".join(entries)


def decode_frame(payload: bytes) -> CompressedRange:
    """Decode a synthetic binary payload through the wire decoder."""
    (message,) = StreamDecoder(strict=True).feed(binary(payload, message_id=140))
    return decode_rangecmp(message)


def test_gps_l1_round_trip() -> None:
    prn, pseudorange = 17, 23907390.336
    phase = -pseudorange * L1_HZ / LIGHT_SPEED + 3.7
    entry = pack_entry(
        status=STATUS_L1,
        prn=prn,
        doppler_hz=-2673.013,
        pseudorange_m=pseudorange,
        phase_cycles=phase,
        frequency_hz=L1_HZ,
    )
    (observation,) = decode_frame(pack_frame((entry,))).observations
    assert observation.tracking_status == STATUS_L1
    assert observation.prn == prn
    assert observation.doppler_hz == pytest.approx(-2673.013, abs=1 / 256)
    assert observation.pseudorange_m == pytest.approx(pseudorange, abs=1 / 128)
    assert observation.carrier_phase_cycles == pytest.approx(phase, abs=1 / 256)
    assert observation.pseudorange_std_m == _PSRSTD[10]
    assert observation.carrier_phase_std_cycles == pytest.approx(8 / 512)
    assert observation.lock_time_s == pytest.approx(100.0, abs=1 / 32)
    assert observation.cn0_db_hz == 35
    assert observation.cn0_saturated is False
    assert observation.glonass_channel == 0
    assert observation.divergence_cycles == pytest.approx(3.7, abs=0.01)


def test_fold_selection_covers_both_branches() -> None:
    low = pack_entry(
        status=STATUS_L1,
        prn=7,
        doppler_hz=800.0,
        pseudorange_m=20234567.125,
        phase_cycles=-20234567.125 * L1_HZ / LIGHT_SPEED + 3.7,
        frequency_hz=L1_HZ,
    )
    high = pack_entry(
        status=STATUS_L1,
        prn=9,
        doppler_hz=-800.0,
        pseudorange_m=21000000.0,
        phase_cycles=-21000000.0 * L1_HZ / LIGHT_SPEED - 41.2,
        frequency_hz=L1_HZ,
    )
    first, second = decode_frame(pack_frame((low, high))).observations
    assert first.carrier_phase_cycles == pytest.approx(
        -20234567.125 * L1_HZ / LIGHT_SPEED + 3.7, abs=1 / 256
    )
    assert second.carrier_phase_cycles == pytest.approx(
        -21000000.0 * L1_HZ / LIGHT_SPEED - 41.2, abs=1 / 256
    )


def test_glonass_channel_sets_the_reconstruction_frequency() -> None:
    channel = -2
    pseudorange, phase = 21456789.5, -21456789.5 * G1_HZ / LIGHT_SPEED - 12.3
    entry = pack_entry(
        status=STATUS_G1,
        prn=11,
        doppler_hz=1500.25,
        pseudorange_m=pseudorange,
        phase_cycles=phase,
        frequency_hz=G1_HZ,
        glo=channel + 7,
    )
    (observation,) = decode_frame(pack_frame((entry,))).observations
    assert observation.glonass_channel == channel + 7
    assert observation.carrier_phase_cycles == pytest.approx(phase, abs=1 / 256)


def test_unknown_signal_leaves_phase_unresolved() -> None:
    entry = pack_entry(
        status=STATUS_UNKNOWN,
        prn=3,
        doppler_hz=100.0,
        pseudorange_m=22000000.0,
        phase_cycles=-100000000.0,
        frequency_hz=L1_HZ,
    )
    (observation,) = decode_frame(pack_frame((entry,))).observations
    assert observation.prn == 3
    assert observation.pseudorange_m == pytest.approx(22000000.0, abs=1 / 128)
    assert observation.carrier_phase_cycles is None
    assert observation.divergence_cycles is None


def test_cn0_saturation_is_flagged_at_both_ends() -> None:
    low = pack_entry(
        status=STATUS_L1,
        prn=5,
        doppler_hz=0.0,
        pseudorange_m=23000000.0,
        phase_cycles=-23000000.0 * L1_HZ / LIGHT_SPEED,
        frequency_hz=L1_HZ,
        cn0_db=20,
    )
    high = pack_entry(
        status=STATUS_B1,
        prn=8,
        doppler_hz=0.0,
        pseudorange_m=23000000.0,
        phase_cycles=-23000000.0 * B1_HZ / LIGHT_SPEED,
        frequency_hz=B1_HZ,
        cn0_db=51,
    )
    first, second = decode_frame(pack_frame((low, high))).observations
    assert (first.cn0_db_hz, first.cn0_saturated) == (20, True)
    assert (second.cn0_db_hz, second.cn0_saturated) == (51, True)


def test_ascii_hex_entries_decode_like_binary() -> None:
    entry = pack_entry(
        status=STATUS_L5,
        prn=21,
        doppler_hz=512.75,
        pseudorange_m=24123456.75,
        phase_cycles=-24123456.75 * L5_HZ / LIGHT_SPEED + 1.1,
        frequency_hz=L5_HZ,
    )
    binary_observation = decode_frame(pack_frame((entry,))).observations[0]
    hex_entry = entry.hex()
    message = AsciiMessage(
        LegacyAsciiHeader("RANGECMPA", ()),
        ("1", hex_entry),
        f"#RANGECMPA,1;1,{hex_entry}".encode(),
    )
    (ascii_observation,) = decode_rangecmp(message).observations
    assert ascii_observation == binary_observation


def test_wrong_message_id_is_rejected() -> None:
    entry = pack_entry(
        status=STATUS_L1,
        prn=1,
        doppler_hz=0.0,
        pseudorange_m=22000000.0,
        phase_cycles=-22000000.0 * L1_HZ / LIGHT_SPEED,
        frequency_hz=L1_HZ,
    )
    (message,) = StreamDecoder(strict=True).feed(
        binary(pack_frame((entry,)), message_id=43)
    )
    with pytest.raises(ProtocolError, match="message ID 140"):
        decode_rangecmp(message)


def test_truncated_and_mismatched_frames_are_rejected() -> None:
    entry = pack_entry(
        status=STATUS_L1,
        prn=1,
        doppler_hz=0.0,
        pseudorange_m=22000000.0,
        phase_cycles=-22000000.0 * L1_HZ / LIGHT_SPEED,
        frequency_hz=L1_HZ,
    )
    with pytest.raises(ProtocolError, match="Truncated"):
        decode_frame(b"\x01\x00")
    with pytest.raises(ProtocolError, match="count or body length"):
        decode_frame((2).to_bytes(4, "little") + entry)
    with pytest.raises(ProtocolError, match="count or body length"):
        decode_frame((300).to_bytes(4, "little"))


def test_ascii_count_and_encoding_errors_are_rejected() -> None:
    entry = pack_entry(
        status=STATUS_L1,
        prn=1,
        doppler_hz=0.0,
        pseudorange_m=22000000.0,
        phase_cycles=-22000000.0 * L1_HZ / LIGHT_SPEED,
        frequency_hz=L1_HZ,
    )
    valid = entry.hex()

    def ascii_message(fields: tuple[str, ...]) -> AsciiMessage:
        return AsciiMessage(LegacyAsciiHeader("RANGECMPA", ()), fields, b"#RANGECMPA")

    with pytest.raises(ProtocolError, match="Truncated"):
        decode_rangecmp(ascii_message(()))
    with pytest.raises(ProtocolError, match="entry count"):
        decode_rangecmp(ascii_message(("many", valid)))
    with pytest.raises(ProtocolError, match="count or body length"):
        decode_rangecmp(ascii_message(("2", valid)))
    with pytest.raises(ProtocolError, match="count or body length"):
        decode_rangecmp(ascii_message(("1", valid[:40])))
    with pytest.raises(ProtocolError, match="entry encoding"):
        decode_rangecmp(ascii_message(("1", "z" * 48)))
    other = AsciiMessage(LegacyAsciiHeader("RANGEA", ()), ("1", valid), b"")
    with pytest.raises(ProtocolError, match="Expected a RANGECMP frame"):
        decode_rangecmp(other)
