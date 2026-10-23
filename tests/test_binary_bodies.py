from struct import pack, pack_into

import pytest

from test_bodies import binary_message
from um982py.commands import Log
from um982py.commands.catalog import RTCM_LOGS
from um982py.errors import ProtocolError
from um982py.messages import Record, decode_log

LENGTHS = {
    "VERSION": 308,
    "OBSVM": 4,
    "OBSVH": 4,
    "OBSVMCMP": 4,
    "OBSVHCMP": 4,
    "OBSVBASE": 4,
    "BASEINFO": 40,
    "GPSION": 76,
    "BD3ION": 40,
    "BDSION": 76,
    "GALION": 33,
    "GPSUTC": 48,
    "BD3UTC": 56,
    "BDSUTC": 48,
    "GALUTC": 64,
    "GPSEPH": 224,
    "QZSSEPH": 224,
    "BD3EPH": 264,
    "BDSEPH": 232,
    "GLOEPH": 144,
    "GALEPH": 220,
    "IRNSSEPH": 224,
    "AGRIC": 228,
    "PVTSLN": 224,
    "BESTNAV": 120,
    "BESTNAVXYZ": 112,
    "BESTNAVH": 120,
    "BESTNAVXYZH": 112,
    "BESTSAT": 4,
    "ADRNAV": 120,
    "ADRNAVH": 120,
    "PPPNAV": 72,
    "PPPNAVH": 72,
    "APPPNAV": 76,
    "RPPPNAV": 72,
    "LBANDAUTH": 80,
    "RPPPDOP": 42,
    "LBANDBEAM": 4,
    "LBANDTRACKSTATUS": 4,
    "LBANDUSERDATA": 4,
    "SPPNAV": 120,
    "SPPNAVH": 120,
    "STADOP": 42,
    "STADOPH": 42,
    "ADRDOP": 42,
    "ADRDOPH": 42,
    "PPPDOP": 42,
    "PPPDOP2": 42,
    "SPPDOP": 42,
    "SPPDOPH": 42,
    "SATSINFO": 6,
    "BASEPOS": 120,
    "SATELLITE": 16,
    "SATECEF": 4,
    "RECTIME": 44,
    "UNIHEADING": 44,
    "UNIHEADING2": 44,
    "HEADINGSTATUS": 32,
    "RTKSTATUS": 56,
    "AGNSSSTATUS": 96,
    "RTCSTATUS": 24,
    "JAMSTATUS": 8,
    "FREQJAMSTATUS": 12,
    "RTCMSTATUS": 22,
    "RTKSTATUS2": 56,
    "HWSTATUS": 40,
    "AGC": 20,
    "INFOPART1": 1,
    "INFOPART2": 1,
    "MSPOS": 104,
    "TROPINFO": 24,
    "PPPB2BINFO1": 40,
    "PPPB2BINFO2": 80,
    "PPPB2BINFO3": 8,
    "PPPB2BINFO4": 104,
    "PPPB2BINFO5": 152,
    "PPPB2BINFO6": 180,
    "PPPB2BINFO7": 212,
    "E6MASKBLOCK": 12,
    "E6ORBITBLOCK": 556,
    "E6CLOCKFULLBLOCK": 152,
    "E6CLOCKSUBBLOCK": 12,
    "E6CBIASBLOCK": 524,
    "E6PBIASBLOCK": 1036,
    "L6MDCTYPE1": 24,
    "L6MDCTYPE2": 24,
    "L6MDCTYPE3": 24,
    "L6MDCTYPE4": 24,
    "L6MDCTYPE5": 24,
    "L6MDCTYPE7": 184,
    "L1SMT47": 176,
    "L1SMT48": 36,
    "L1SMT49": 48,
    "L1SMT50": 84,
    "BSLNENUHD2": 60,
    "BSLNXYZHD2": 60,
    "DOPHD2": 28,
    "EVENTFLAG": 28,
    "EVENTSLN": 108,
}


def test_binary_inventory() -> None:
    # L1SMT have documented binary layouts but no documented binary command
    # syntax in R1.15, so they are covered here but not by binary requests.
    assert set(LENGTHS) == {
        log.value
        for log in Log
        if log.definition.binary_command is not None and log.value not in RTCM_LOGS
    } | {"L1SMT47", "L1SMT48", "L1SMT49", "L1SMT50"}


@pytest.mark.parametrize("name,size", LENGTHS.items())
def test_binary_body_extents(name: str, size: int) -> None:
    record = Log(name).decode(binary_message(name, bytes(size)))
    assert record.name == name
    with pytest.raises(ProtocolError):
        decode_log(binary_message(name, bytes(size - 1)))
    with pytest.raises(ProtocolError):
        decode_log(binary_message(name, bytes(size + 1)))


def test_dop_count_and_signed_satellite_channel() -> None:
    data = bytearray(46)
    pack_into("<f", data, 4, 1.25)
    pack_into("<HHH", data, 40, 2, 10, 43)
    record = decode_log(binary_message("STADOP", bytes(data)))
    assert record["prn"] == (10, 43)
    assert record["gdop"] == 1.25
    data = pack("<IIHhII", 1, 1, 52, -2, 0, 3)
    record = decode_log(binary_message("BESTSAT", data))
    satellite = record.records("satellites")[0]["satellite_id"]
    assert isinstance(satellite, Record)
    assert satellite.integer("prn") == 52
    assert satellite.integer("channel") == -2


def test_information_variable_lengths() -> None:
    data = b"\x02\x01\x03\0abc\x02\x02\0de"
    records = decode_log(binary_message("INFOPART1", data)).records("information")
    assert len(records) == 2
    assert records[0]["data"] == (97, 98, 99)
    assert records[1].integer("info_id") == 2
    assert records[1]["data"] == (100, 101)


def test_ppp_nested_corrections() -> None:
    data = bytearray(72)
    pack_into("<HBBIHHHh", data, 0, 219, 1, 1, 20631, 40, 1, 8, -199)
    record = decode_log(binary_message("PPPB2BINFO3", bytes(data)))
    bias = record.records("code_biases")[0]
    assert bias.integer("satellite_slot") == 40
    assert bias.integer("bias_count") == 1
    assert len(bias.records("corrections")) == 15
    assert bias.records("corrections")[0].integer("code_correction") == -199
    assert record.integer("seconds_of_day") == 20631
    assert "sow" not in record
    pack_into("<H", data, 10, 16)
    with pytest.raises(ProtocolError, match="bias count"):
        decode_log(binary_message("PPPB2BINFO3", bytes(data)))


def test_b2b_epoch_must_be_seconds_within_day() -> None:
    data = bytearray(40)
    pack_into("<I", data, 4, 86400)
    with pytest.raises(ProtocolError, match="epoch"):
        decode_log(binary_message("PPPB2BINFO1", bytes(data)))


def test_has_nested_systems() -> None:
    data = bytearray(120)
    pack_into("<H", data, 8, 2)
    pack_into("<H", data, 12, 0)
    pack_into("<H", data, 66, 2)
    data[14:19] = b"\x7f\xff\xfb\xdf\0"
    data[68:73] = b"\x73\xfa\x29\xe6\xd0"
    data[19:21] = b"\x81\x40"
    systems = decode_log(binary_message("E6MASKBLOCK", bytes(data))).records("systems")
    assert [system.integer("gnss_id") for system in systems] == [0, 2]
    assert systems[0]["satellite_mask"] == b"\x7f\xff\xfb\xdf\0"
    assert systems[0].integer("signal_mask") == 0x8140
    assert systems[1]["satellite_mask"] == b"\x73\xfa\x29\xe6\xd0"
    data = bytearray(180)
    pack_into("<h", data, 10, 2)
    pack_into("<H", data, 12, 0)
    pack_into("<h", data, 24, -4096)
    pack_into("<H", data, 96, 2)
    systems = decode_log(binary_message("E6CLOCKSUBBLOCK", bytes(data))).records(
        "systems"
    )
    assert len(systems) == 2
    assert systems[0]["delta_clock_corrections"] == (-4096,) + (0,) * 35
    assert systems[1].integer("gnss_id") == 2


def test_ppp_secondary_logs_decode_documented_binary_offsets() -> None:
    payload = bytearray(72)
    pack_into("<dddf", payload, 8, 40.5, 8.5, 123.0, 42.0)
    nav = decode_log(binary_message("PPPNAVH", bytes(payload)))
    assert nav.real("lat") == pytest.approx(40.5)
    assert nav.real("lon") == pytest.approx(8.5)
    assert nav.real("undulation") == pytest.approx(42.0)

    body = bytearray(46)
    pack_into("<f", body, 4, 1.25)
    pack_into("<HHH", body, 40, 2, 5, 9)
    dop = decode_log(binary_message("PPPDOP2", bytes(body)))
    assert dop.real("gdop") == pytest.approx(1.25)
    assert dop["prn"] == (5, 9)


def test_pppar_logs_share_ppp_binary_offsets() -> None:
    payload = bytearray(72)
    pack_into(
        "<IIdddfffff", payload, 0, 0, 69, 40.5, 8.5, 123.0, 42.0, 61, 0.5, 0.6, 0.7
    )
    payload[52:56] = b"9974"
    pack_into("<ffBBBBBBBB", payload, 56, 1.0, 2.0, 51, 49, 49, 47, 0, 0, 0xCF, 0xFF)
    for name in ("RPPPNAV",):
        record = decode_log(binary_message(name, bytes(payload)))
        assert record.real("lat") == pytest.approx(40.5)
        assert record.real("lon") == pytest.approx(8.5)
        assert record["stn_id"] == "9974"
        assert record.integer("galileo_bds3_sig_mask") == 0xCF
        assert record.integer("gps_glonass_and_bds2_sig_mask") == 0xFF

    appp_payload = bytes(payload[:68]) + pack("<ff", 1.5, -2.5)
    record = decode_log(binary_message("APPPNAV", appp_payload))
    assert record.real("lat") == pytest.approx(40.5)
    assert record["stn_id"] == "9974"
    assert record.real("reserved_3") == pytest.approx(1.5)
    assert record.real("reserved_4") == pytest.approx(-2.5)
    assert "galileo_bds3_sig_mask" not in record

    dop_body = bytearray(48)
    pack_into(
        "<Ifffffffff", dop_body, 0, 123, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 5.0
    )
    pack_into("<H", dop_body, 40, 3)
    pack_into("<HHH", dop_body, 42, 16, 25, 26)
    dop = decode_log(binary_message("RPPPDOP", bytes(dop_body)))
    assert dop.real("gdop") == pytest.approx(0.8)
    assert dop["prn"] == (16, 25, 26)


@pytest.mark.parametrize(
    ("subtype", "body"),
    [
        (1, bytes([2]) + b"\x81" * 5 + b"\x80\x01" + bytes([1]) + bytes(3) + bytes(40)),
        (2, b"\x03\x00\xff\xff\x02\x00\xfd\xff"),
        (3, b"\xff\xff"),
        (4, b"\xff\xff" * 7),
        (5, b"\xff\xff" * 7 + b"\x02\x00" * 7),
        (7, b"\x02\x00" * 80),
    ],
)
def test_madoca_binary_header_and_bounded_payload(subtype: int, body: bytes) -> None:
    # One GNSS group or correction, independent of its on-air mask semantics.
    header = pack("<IHHIHBBBBHHH", 36, 4073, subtype, 123, 5, 0, 11, 1, 0, 30, 1, 7)
    log = Log[f"L6MDCTYPE{subtype}"]
    record = decode_log(binary_message(log.value, header + body))
    assert record.integer("subtype") == subtype
    assert record.integer("correction_count") == 1
    if subtype == 1:
        assert record.records("masks")[0]["satellite_mask"] == b"\x81" * 5
    elif subtype == 2:
        assert record.records("orbit")[0].integer("radial") == -1
    elif subtype == 3:
        assert record["clock"] == (-1,)
    elif subtype == 4:
        assert record.records("code_bias")[0]["values"] == (-1,) * 7
    elif subtype == 5:
        assert record.records("phase_bias")[0]["indicators"] == (2,) * 7
    else:
        assert record["ura"] == (2,) * 80
    with pytest.raises(ProtocolError):
        decode_log(binary_message(log.value, header + body[:-1]))


def test_l1smt_binary_offsets_per_documented_tables() -> None:
    # L1SMT47 (7-112): 8 station-code bytes + 5 x 3 doubles + 6 reserved doubles.
    data = bytearray(176)
    data[0:8] = b"\xba\x0c\r\x0e?\x3f\x00\x00"
    for i in range(5):
        pack_into("<ddd", data, 8 + i * 24, 10.0 + i, 20.0 + i, 30.0 + i)
    record = decode_log(binary_message("L1SMT47", bytes(data)))
    assert record["gms_code"] == (0xBA, 0x0C, 13, 14, 63, 63, 0, 0)
    assert record.real("gms_lat1") == pytest.approx(10.0)
    assert record.real("gms_hgt5") == pytest.approx(34.0)

    # L1SMT48 (7-113): GPS/QZSS/GLO/GAL masks, RSV, BDS mask, RSV.
    data = bytearray(36)
    data[0:8] = bytes.fromhex("085e570800000000")
    data[8:10] = b"\x72\x00"
    data[24:32] = bytes.fromhex("deadbeefcafebabe")
    record = decode_log(binary_message("L1SMT48", bytes(data)))
    assert record["gps_mask"] == bytes.fromhex("085e570800000000")
    assert record["qzss_mask"] == b"\x72\x00"
    assert record["bds_mask"] == bytes.fromhex("deadbeefcafebabe")

    # L1SMT49 (7-114): IODI, MASK SV, IOD (24), IODP, 3 reserved.
    data = bytearray(48)
    pack_into("<I", data, 0, 7)
    data[4:8] = bytes.fromhex("ffff0000")
    pack_into("<I", data, 32, 9)
    record = decode_log(binary_message("L1SMT49", bytes(data)))
    assert record.integer("iodi") == 7
    assert record["mask_sv"] == bytes.fromhex("ffff0000")
    assert record.integer("iodp") == 9

    # L1SMT50 (7-115): IODP, IODI, GMS code/health, masks, 14 PRC floats.
    data = bytearray(84)
    pack_into("<II", data, 0, 3, 5)
    data[8] = 6
    data[9] = 1
    data[12:15] = bytes.fromhex("96e300")
    pack_into("<14f", data, 16, *([1.0] * 14))
    record = decode_log(binary_message("L1SMT50", bytes(data)))
    assert record.integer("iodp") == 3
    assert record.integer("iodi") == 5
    assert record["mask_sv"] == bytes.fromhex("96e300")
    assert record["prc"] == (1.0,) * 14


def test_lband_binary_offsets_and_bounded_groups() -> None:
    # LBANDAUTH: LSN/LbandAuth/ServiceEndDate/legacy/ L-bandSat/Reserved = 80.
    payload = (
        b"3000099".ljust(16, b"\x00")
        + b"ACTIVATED".ljust(16, b"\x00")
        + b"2025/10/31".ljust(16, b"\x00")
        + b"GLOBAL".ljust(16, b"\x00")
        + b"OCSAT".ljust(8, b"\x00")
        + b"\x00" * 8
    )
    record = decode_log(binary_message("LBANDAUTH", payload))
    assert record["lsn"] == "3000099"
    assert record["lband_auth"] == "ACTIVATED"
    assert record["service_end_date"] == "2025/10/31"
    assert record["legacy"] == ("GLOBAL",)
    assert record["lband_sat"] == "OCSAT"

    def beam(
        bid: int, name: bytes, freq: int, rate: int, elev: float, az: float, lon: float
    ) -> bytes:
        return (
            pack("<I", bid)
            + name.ljust(8, b"\x00")
            + pack("<IHH", freq, rate, 0)
            + pack("<fff", elev, az, lon)
            + b"\x01\x01\x01\x00\x00\x00"
            + pack("<H", 0x2200)
            + pack("<HH", 0x5C08, 0xC685)
            + pack("<II", 0xE15AE893, 0xE15AE893)
        )

    beams_payload = (
        pack("<I", 2)
        + beam(1, b"ARSAT", 1545245000, 2400, -45.4644, 46.6997, -98.0)
        + beam(2, b"SASAT", 1545815000, 1200, -54.2067, 344.9805, -54.0)
    )
    record = decode_log(binary_message("LBANDBEAM", beams_payload))
    assert record.integer("count_beams") == 2
    beams = record.records("beams")
    assert beams[0]["beam_name"] == "ARSAT"
    assert beams[0]["search_window"] == 0x2200
    assert beams[1]["frequency"] == 1545815000

    track_payload = (
        pack("<I", 1)
        + pack("<I", 5)
        + b"IRSAT".ljust(8, b"\x00")
        + pack("<IHH", 1546240000, 1200, 0xC685)
        + pack("<Ifff", 25666176, -23.9124, 47.79, 0.1)
        + pack("<HHIfII", 0, 5, 7756144, 0.0008, 0, 0)
    )
    record = decode_log(binary_message("LBANDTRACKSTATUS", track_payload))
    assert record.integer("count_beams") == 1
    beam = record.records("beams")[0]
    assert beam["beam_name"] == "IRSAT"
    assert beam.real("doppler") == pytest.approx(-23.9124)
    assert beam.real("bit_error_rate") == pytest.approx(0.0008)

    user_payload = pack("<HH", 5, 6) + bytes.fromhex("ce3d081cbe95")
    record = decode_log(binary_message("LBANDUSERDATA", user_payload))
    assert record.integer("beam_id") == 5
    assert record.integer("number_of_bytes") == 6
    assert b"".join(record["content"]) == bytes.fromhex("ce3d081cbe95")


def test_event_offsets_and_signed_values() -> None:
    data = bytearray(28)
    pack_into("<BBxxIIIiii", data, 0, 1, 0b1011, 2441, 330000, 999999999, 0, -1, -1)
    record = decode_log(binary_message("EVENTFLAG", bytes(data)))
    assert record.integer("subsecond") == 999999999
    assert record.integer("offset_second") == -1
    assert record.integer("status") == 0b1011
