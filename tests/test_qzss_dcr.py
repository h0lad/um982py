import pytest

from um982py.commands import Log
from um982py.messages.qzss_dcr import decode_qzqsm
from um982py.messages.record import Record
from um982py.protocol import StreamDecoder

PAYLOAD = "53AD54A4FB0001AF2FD8000000000000000000000000000000000013ECA2C98"


def test_manual_weather_report() -> None:
    wire = f"$QZQSM,56,{PAYLOAD}*0F\r\n".encode()
    report = decode_qzqsm(Log.QZQSM.decode(StreamDecoder(strict=True).feed(wire)[0]))
    assert (
        report.satellite_number,
        report.message_type,
        report.classification,
        report.category,
        report.version,
    ) == (56, 43, "priority", "weather", 1)
    assert report.weather is not None
    assert (
        report.weather.month,
        report.weather.day,
        report.weather.hour,
        report.weather.minute,
    ) == (9, 9, 7, 54)
    assert report.weather.information_type == "issue"
    assert report.weather.warning_state_code == 1
    assert len(report.weather.regions) == 1


def test_rejects_corruption_and_invalid_padding() -> None:
    def record(payload: str) -> Record:
        return Record("QZQSM", (("prn", 56), ("dc_message", payload)))

    with pytest.raises(ValueError, match="CRC"):
        decode_qzqsm(record(PAYLOAD[:20] + "1" + PAYLOAD[21:]))
    with pytest.raises(ValueError, match="padding"):
        decode_qzqsm(record(PAYLOAD[:-1] + "9"))
    with pytest.raises(ValueError, match="63 hexadecimal"):
        decode_qzqsm(record("invalid"))


def test_mt44_does_not_interpret_ambiguous_payload_as_legacy_dcr() -> None:
    # MT44 from the public QZSS L1S archive, GPS week 2442, second 259218.
    payload = "53B0C00DE0000000000000000000000000000000000000000000000002C3E68"
    report = decode_qzqsm(Record("QZQSM", (("prn", 186), ("dc_message", payload))))
    assert report.message_type == 44
    assert report.payload_hex == payload
    assert report.classification_code is None
    assert report.classification is None
    assert report.organization_code is None
    assert report.version is None


def test_public_archive_validation_checks_framing_and_crc() -> None:
    from examples.qzss_disaster_report.validate_archive import validate_archive

    payload = "53B0C00DE0000000000000000000000000000000000000000000000002C3E68"
    time = (2442 << 20) | 259218
    frame = int(payload, 16) >> 2
    archive = bytes([186]) + time.to_bytes(4, "big") + (frame << 6).to_bytes(32, "big")
    result = validate_archive(archive)
    assert result["records"] == 1
    assert result["first_gps_week_tow"] == (2442, 259218)
    assert result["accepted_dcr_by_type"] == {44: 1}
    assert result["rejected_dcr"] == {}
    assert result["nonzero_archive_spare"] == 0
    corrupt = bytearray(archive)
    corrupt[10] ^= 1
    assert validate_archive(bytes(corrupt))["rejected_dcr"] == {
        "invalid L1S CRC-24Q": 1
    }
    corrupt = bytearray(archive)
    corrupt[-1] |= 1
    assert validate_archive(bytes(corrupt))["nonzero_archive_spare"] == 1
    with pytest.raises(ValueError, match="36-byte"):
        validate_archive(archive[:-1])
