import csv
import json
from dataclasses import replace
from io import StringIO
from struct import pack

import pytest

from conftest import FIXTURES
from test_protocol import binary
from um982py.commands import Log
from um982py.commands.catalog import LOGS, RAW_CORRECTION_LOGS
from um982py.errors import ProtocolError
from um982py.messages import (
    AsciiMessage,
    BinaryMessage,
    LegacyAsciiHeader,
    Observation,
    Record,
    Sentence,
    TrackingStatus,
    decode_log,
)
from um982py.messages.layouts import LAYOUTS
from um982py.messages.nmea import SCHEMAS
from um982py.protocol import StreamDecoder
from um982py.protocol.ascii import parse_ascii
from um982py.protocol.checksums import unicore_crc32

EXAMPLES: dict[str, str] = json.loads(
    (FIXTURES / "manual-examples-r1.4.json").read_text()
)
CAPTURES = sorted((FIXTURES / "bodies").glob("*.bin"))


def manual_message(name: str) -> AsciiMessage | Sentence:
    raw = EXAMPLES[name]
    body = raw[1 : raw.index("*")]
    if ";" in body:
        fields = tuple(next(csv.reader(StringIO(body.split(";", 1)[1]))))
        return AsciiMessage(LegacyAsciiHeader(name, ()), fields, raw.encode())
    return Sentence(name, tuple(body.split(",")[1:]), raw.encode())


def binary_message(name: str, data: bytes) -> BinaryMessage:
    messages = StreamDecoder(strict=True).feed(
        binary(data, message_id=LOGS[name].message_id or 0)
    )
    message = messages[0]
    assert isinstance(message, BinaryMessage)
    return message


def test_body_inventory() -> None:
    documented = {
        name
        for name, definition in LOGS.items()
        if definition.section.startswith(("7.3.", "7.5."))
        or definition.section == "Appendix 3"
    }
    assert (
        set(LAYOUTS) | {"UNILOGLIST", "SATSINFO", "KSXT"} | RAW_CORRECTION_LOGS
        == documented
    )


@pytest.mark.parametrize("name", sorted(set(EXAMPLES) - {"MODE", "CONFIG"}))
def test_manual_body_examples(name: str) -> None:
    message = manual_message(name)
    if name == "PPPB2BINFO5A":
        with pytest.raises(ProtocolError, match="subtype"):
            decode_log(message)
        return
    record = decode_log(message)
    assert record.message is message
    assert record
    if isinstance(message, AsciiMessage):
        assert record.name == name.removesuffix("A")


@pytest.mark.parametrize("path", CAPTURES, ids=lambda p: p.stem)
def test_captured_bodies(path: object) -> None:
    from pathlib import Path

    assert isinstance(path, Path)
    messages = StreamDecoder(strict=True).feed(path.read_bytes())
    assert len(messages) == 1
    message = messages[0]
    decoded = decode_log(message)
    assert decoded.message is message
    if isinstance(message, BinaryMessage):
        for size in range(len(message.payload)):
            with pytest.raises(ProtocolError):
                decode_log(replace(message, payload=message.payload[:size]))
        with pytest.raises(ProtocolError):
            decode_log(replace(message, payload=message.payload + b"\0"))


@pytest.mark.parametrize("name", ["GPSION", "BD3ION", "GALUTC"])
def test_ionosphere_and_time_binary_agreement(name: str) -> None:
    def body(suffix: str) -> Record:
        message = StreamDecoder(strict=True).feed(
            (FIXTURES / "bodies" / f"{name}{suffix}.bin").read_bytes()
        )[0]
        return decode_log(message)

    a, b = body("A"), body("B")
    assert tuple(a) == tuple(b)
    for key in a:
        assert a[key] == pytest.approx(b[key])


def test_manual_navigation_values() -> None:
    navigation = decode_log(manual_message("BESTNAVA"))
    assert navigation["lat"] == pytest.approx(40.07899377676)
    assert navigation["datum_id"] == "WGS84"
    assert navigation["p_sol_status"] == "SOL_COMPUTED"
    ephemeris = decode_log(manual_message("GPSEPHA"))
    assert ephemeris.integer("prn") == 10
    assert ephemeris.real("a") > 26_000_000


def test_nested_satellites() -> None:
    record = decode_log(manual_message("SATSINFOA"))
    satellites = record.records("satellites")
    assert len(satellites) == record.integer("satellite_count") == 50
    assert satellites[0].integer("prn") == 2
    assert satellites[0].records("frequencies")[0].integer("snr") == 45
    ecef = decode_log(manual_message("SATECEFA"))
    assert len(ecef.records("satellites")) == ecef.integer("satnum")
    best = decode_log(manual_message("BESTSATA"))
    glonass = best.records("satellites")[12]["satellite_id"]
    assert isinstance(glonass, Record)
    assert glonass.integer("prn") == 42
    assert glonass.integer("channel") == 8


def test_uncompressed_observation_units() -> None:
    record = decode_log(manual_message("OBSVMA")).records("observations")[0]
    observation = Observation.from_record(record)
    assert observation.prn == 26
    assert observation.glonass_frequency is None
    assert observation.pseudorange_m == 21720097.812
    assert observation.carrier_phase_cycles == -114139892.254585
    assert observation.pseudorange_std_m == 0.52
    assert observation.carrier_phase_std_cycles == 0.0181
    assert observation.cn0_db_hz == 42.7
    assert observation.tracking.phase_valid
    assert observation.tracking.pseudorange_valid
    assert not observation.phase_is_modulo


def test_compressed_observation_bits() -> None:
    status = (1 << 16) | (6 << 21) | (1 << 26) | (1 << 12) | (1 << 10) | (7 << 5)
    bits = (
        status
        | (((1 << 28) - 256) << 32)
        | (2560 << 60)
        | (768 << 96)
        | (3 << 128)
        | (4 << 132)
        | (52 << 136)
        | (320 << 144)
        | (17 << 165)
        | (5 << 170)
    )
    message = binary_message("OBSVMCMP", pack("<I", 1) + bits.to_bytes(24, "little"))
    observation = Observation.from_record(
        decode_log(message).records("observations")[0]
    )
    assert observation.prn == 52
    assert observation.glonass_frequency == -2
    assert observation.pseudorange_m == 20
    assert observation.carrier_phase_cycles == 3
    assert observation.doppler_hz == -1
    assert observation.lock_seconds == 10
    assert observation.cn0_db_hz == 37
    assert observation.pseudorange_std_m == 0.169
    assert observation.carrier_phase_std_cycles == 5 / 512
    assert observation.phase_is_modulo
    assert observation.tracking.channel == 7
    assert observation.tracking.system == 1
    assert observation.tracking.signal == 6
    assert observation.tracking.l2c


def test_tracking_and_empty_observations() -> None:
    assert not TrackingStatus(0).phase_valid
    assert not TrackingStatus(0).pseudorange_valid
    assert (
        decode_log(binary_message("OBSVM", pack("<I", 0))).records("observations") == ()
    )
    with pytest.raises(ProtocolError):
        decode_log(binary_message("OBSVM", pack("<I", 0xFFFFFFFF)))
    with pytest.raises(ProtocolError):
        Observation.from_record(Record("bad", (("cmp_record", b"\0"),)))


@pytest.mark.parametrize("kind", sorted(SCHEMAS))
def test_nmea_count_validation(kind: str) -> None:
    name = kind if kind == "KSXT" else "GP" + kind
    with pytest.raises(ProtocolError):
        decode_log(Sentence(name, (), b""))
    with pytest.raises(ProtocolError):
        decode_log(Sentence(name, ("",) * (len(SCHEMAS[kind]) + 1), b""))


@pytest.mark.parametrize(
    "fields",
    [("", "1", "0"), ("1", "2", "0"), ("1", "1"), ("1", "1", "0", "0", "0")],
)
def test_bad_gsv(fields: tuple[str, ...]) -> None:
    with pytest.raises(ProtocolError):
        decode_log(Sentence("GPGSV", fields, b""))


def test_hpd_crc32() -> None:
    body = EXAMPLES["GPHPD"].split("*", 1)[0][1:].encode()
    raw = b"$" + body + f"*{unicore_crc32(body):08x}\r\n".encode()
    record = decode_log(parse_ascii(raw))
    assert record.integer("gps_week") == 2319
    assert record.real("latitude") == pytest.approx(40.0789783)
    assert record.real("east_velocity_difference") == pytest.approx(-0.001)
    assert "east_acceleration" not in record
    with pytest.raises(ProtocolError):
        parse_ascii(raw[:-4] + b"00\r\n")


LATEST_EXAMPLES: dict[str, str] = json.loads(
    (FIXTURES / "manual-examples-r1.15.json").read_text()
)


def manual_latest_message(name: str) -> AsciiMessage | Sentence:
    raw = LATEST_EXAMPLES[name]
    body = raw[1 : raw.index("*")]
    if ";" in body:
        fields = tuple(next(csv.reader(StringIO(body.split(";", 1)[1]))))
        return AsciiMessage(LegacyAsciiHeader(name, ()), fields, raw.encode())
    return Sentence(name, tuple(body.split(",")[1:]), raw.encode())


def test_apppnav_ascii_layout_documented_and_example_forms() -> None:
    message = manual_latest_message("APPPNAVA")
    assert isinstance(message, AsciiMessage)
    example = Log.APPPNAV.decode(message)
    assert example.integer("unverified_tail_3") == 0xCF
    assert example.integer("unverified_tail_4") == 0xFF
    assert "galileo_bds3_sig_mask" not in example
    from um982py.messages.solution_signals import SolutionSignals

    with pytest.raises(KeyError):
        SolutionSignals.from_record(example)
    table_form = replace(message, fields=(*message.fields[:17], "1.5", "-2.5"))
    record = Log.APPPNAV.decode(table_form)
    assert record.real("reserved_3") == 1.5
    assert record.real("reserved_4") == -2.5


def test_lband_auth_full_manual_example_preserves_legacy_field() -> None:
    raw = (
        b"#LBANDAUTHA,56,GPS,FINE,2384,119469000,21315,0,18,17;"
        b"3000099,ACTIVATED,2025/10/31,GLOBAL,OCSAT,*5a14e0ab\r\n"
    )
    message = StreamDecoder(strict=True).feed(raw)[0]
    record = Log.LBANDAUTH.decode(message)
    assert record["legacy"] == ("GLOBAL",)
    assert record["lband_sat"] == "OCSAT"
    assert record["reserved"] is None


def test_qzqsm_disaster_report_manual_example() -> None:
    wire = (
        b"$QZQSM,56,53AD54A4FB0001AF2FD8000000000000"
        b"000000000000000000000013ECA2C98*0F\r\n"
    )
    message = StreamDecoder(strict=True).feed(wire)[0]
    record = Log.QZQSM.decode(message)
    assert record.integer("prn") == 56
    assert record["dc_message"] == (
        "53AD54A4FB0001AF2FD8000000000000000000000000000000000013ECA2C98"
    )
    assert Log.QZQSM.output(1).text == "QZQSM 1"
    with pytest.raises(ValueError, match="binary"):
        Log.QZQSM.output(binary=True)
    with pytest.raises(ProtocolError, match="field count"):
        Log.QZQSM.decode(Sentence("QZQSM", ("56",), b""))


@pytest.mark.parametrize("name", ["PPPNAVHA", "PPPDOP2A"])
def test_manual_ppp_secondary_examples(name: str) -> None:
    log = Log.PPPNAVH if name == "PPPNAVHA" else Log.PPPDOP2
    record = log.decode(manual_latest_message(name))
    assert record.name == log.value
    if log is Log.PPPNAVH:
        assert record.real("lat") == pytest.approx(40.07898891173)
        assert record.real("lon") == pytest.approx(116.23660132069)
    else:
        assert record.integer("count_prn") == 41
        assert len(record["prn"]) == 41


@pytest.mark.parametrize(
    "name",
    [
        "L1SMT47A",
        "L1SMT48A",
        "L1SMT49A",
        "L1SMT50A",
        "L6MDCTYPE1A",
        "L6MDCTYPE2A",
        "L6MDCTYPE3A",
        "L6MDCTYPE4A",
        "L6MDCTYPE5A",
        "L6MDCTYPE7A",
    ],
)
def test_qzss_correction_payloads(name: str) -> None:
    from um982py.commands import Log, Trigger

    frame = StreamDecoder(strict=True).feed((LATEST_EXAMPLES[name] + "\r\n").encode())[
        0
    ]
    log_name = name.removesuffix("A")
    log = Log[log_name]
    assert log.output(Trigger.ON_CHANGED).text == log_name + "A ONCHANGED"
    record = log.decode(frame)
    assert record.name == log_name
    assert record.message is frame
    if log_name.startswith("L1SMT"):
        # ASCII carries an extra leading token compared with the binary layouts.
        if log is Log.L1SMT47:
            assert len(record["gms_code"]) == 6
            assert record.real("gms_lat1") == pytest.approx(24.72999944724)
            assert record.real("gms_hgt5") == pytest.approx(-100.0)
        elif log is Log.L1SMT48:
            assert record["prefix"] == (189, 1)
            assert record["gps_mask"] == bytes.fromhex("085e570800000000")
        elif log is Log.L1SMT49:
            assert record.integer("iodi") == 1
            assert len(record["iod"]) == 24
        else:
            assert record.integer("iodp") == 1
            assert len(record["prc"]) == 14
    else:
        assert record.integer("message_number") == 4073
        assert record.integer("subtype") == int(log_name.removeprefix("L6MDCTYPE"))


@pytest.mark.parametrize(
    "name",
    [
        "PPPB2BINFO1A",
        "PPPB2BINFO2A",
        "PPPB2BINFO3A",
        "PPPB2BINFO4A",
        "E6MASKBLOCKA",
        "E6ORBITBLOCKA",
        "E6CLOCKFULLBLOCKA",
        "E6CBIASBLOCKA",
    ],
)
def test_has_and_b2b_manual_examples(name: str) -> None:
    message = StreamDecoder(strict=True).feed(
        (LATEST_EXAMPLES[name] + "\r\n").encode()
    )[0]
    record = Log[name.removesuffix("A")].decode(message)
    assert record.name == name.removesuffix("A")
    assert record.message is message


@pytest.mark.parametrize(
    "name",
    [
        "APPPNAVA",
        "RPPPNAVA",
        "RPPPDOPA",
        "LBANDAUTHA",
        "LBANDBEAMA",
        "LBANDTRACKSTATUSA",
        "LBANDUSERDATAA",
        "RTKSTATUS2A",
    ],
)
def test_lband_and_pppar_ascii_examples(name: str) -> None:
    from um982py.commands import Log

    message = StreamDecoder(strict=True).feed(
        (LATEST_EXAMPLES[name] + "\r\n").encode()
    )[0]
    log = Log[name.removesuffix("A")]
    record = log.decode(message)
    assert record.name == log.value
    assert record.message is message
    if log is Log.APPPNAV:
        assert record.real("lat") == pytest.approx(40.07899484663)
        assert record.real("lon") == pytest.approx(116.23661087645)
        assert record.integer("count_svs") == 58
    elif log is Log.RPPPNAV:
        assert record.real("lat") == pytest.approx(35.74842120390)
        assert record.real("lon") == pytest.approx(139.66688275341)
        assert record["stn_id"] == "9974"
    elif log is Log.RPPPDOP:
        assert record.real("gdop") == pytest.approx(0.7968)
        assert len(record["prn"]) == record.integer("count_prn")
    elif log is Log.LBANDBEAM or log is Log.LBANDTRACKSTATUS:
        assert record.integer("count_beams") == 2
        assert len(record.records("beams")) == 2
    elif log is Log.LBANDUSERDATA:
        assert record.integer("number_of_bytes") == 6
        assert len(record["content"]) == 6
    elif log is Log.LBANDAUTH:
        assert record["lsn"] == "3000099"
    elif log is Log.RTKSTATUS2:
        assert record["gpssource"] == 0x89D24A00
        assert record["pos_type"] == "NARROW_INT"
        assert record["dual_rtk_flag"] == 0xFF
        assert record["adr_number"] == 110


def test_record_accessors() -> None:
    record = Record(
        "example", (("value", 1), ("text", "x"), ("children", (Record("child", ()),)))
    )
    assert tuple(record) == ("value", "text", "children")
    assert record.integer("value") == record.real("value") == 1
    assert len(record.records("children")) == 1
    with pytest.raises(KeyError):
        record["missing"]
    with pytest.raises(TypeError):
        record.integer("text")
    with pytest.raises(TypeError):
        record.real("text")
    with pytest.raises(TypeError):
        record.records("text")
