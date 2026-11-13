"""L-band abbreviated output is a count followed by CSV rows."""

import pytest

from um982py import decode_message
from um982py.commands import Log
from um982py.commands.types import Port
from um982py.errors import ProtocolError
from um982py.messages import AbbreviatedAsciiMessage, Sentence
from um982py.protocol import StreamDecoder

TRACK = (
    b"#LBANDTRACKSTATUS,72,GPS,FINE,2372,206546800,19794,0,18,15;\r\n"
    b"<    2\r\n"
    b"<    5,IRSAT,1546240000,1200,0XC685,25673176,-22.4763,46.3300,"
    b"0.1000,0,5,7758176,0.0008,93,0\r\n"
    b"<    6,OCSAT,1545875000,1200,0X2873,18800,-24.6819,40.7400,"
    b"0.1000,0,0,0,0.0000,80,0\r\n"
)

BEAMS = (
    b"#LBANDBEAM,86,GPS,FINE,2372,200184000,19794,0,18,16;\r\n"
    b"< 1\r\n"
    b"< 1,ARSAT,1545245000,2400,0,-45.4644,46.6997,-98.0000,1,1,1,"
    b"0,0,0,2200,0X5C08,0XC685,0XE15AE893,0XE15AE893\r\n"
)


@pytest.mark.parametrize(
    ("wire", "log", "count"),
    [(TRACK, Log.LBANDTRACKSTATUS, 2), (BEAMS, Log.LBANDBEAM, 1)],
)
def test_lband_abbreviated_table(wire: bytes, log: Log, count: int) -> None:
    decoder = StreamDecoder(strict=True)
    frames = []
    for byte in wire:
        frames.extend(decoder.feed(bytes([byte])))
    decoder.finish()
    assert len(frames) == 1
    frame = frames[0]
    assert isinstance(frame, AbbreviatedAsciiMessage)
    assert frame.raw == wire and not frame.checksum_verified
    record = log.decode(frame)
    assert record.integer("count_beams") == count
    assert len(record.records("beams")) == count
    assert log.read(table=True).matches(frame)
    assert log.read(table=True).decode(frame) == record
    assert decode_message(wire).entries == record.entries
    assert log.output(table=True, port=Port.COM1).text == f"{log.value} COM1 1"
    assert log.stop(table=True, port=Port.COM1).text == f"UNLOG COM1 {log.value}"


def test_lband_table_values_and_zero_beams() -> None:
    track = decode_message(TRACK)
    first, second = track.records("beams")
    assert first["beam_id"] == 5 and first["beam_name"] == "IRSAT"
    assert first["service_id"] == 0xC685
    assert first.real("cn0") == pytest.approx(46.33)
    assert second["beam_name"] == "OCSAT"
    assert decode_message(BEAMS).records("beams")[0]["unique_word1"] == 0xE15AE893
    empty = BEAMS[: BEAMS.index(b"< 1")] + b"< 0\r\n"
    assert decode_message(empty).records("beams") == ()


def test_table_followed_by_another_frame() -> None:
    next_frame = b"$GNRMC,,V,,,,,,,,,,N,V*37\r\n"
    messages = StreamDecoder(strict=True).feed(TRACK + next_frame)
    assert len(messages) == 2
    assert isinstance(messages[0], AbbreviatedAsciiMessage)
    assert isinstance(messages[1], Sentence)
    assert messages[1].raw == next_frame


def test_lband_tables_reject_bad_counts_trailing_and_unsupported_logs() -> None:
    with pytest.raises(ProtocolError):
        decode_message(BEAMS.replace(b"< 1\r\n", b"< 31\r\n"))
    with pytest.raises(ProtocolError):
        decode_message(BEAMS[:-5])
    with pytest.raises(ProtocolError):
        decode_message(BEAMS + b"extra\r\n")
    with pytest.raises(ProtocolError, match="header"):
        decode_message(BEAMS.replace(b";\r\n", b"\r\n", 1))
    with pytest.raises(ProtocolError):
        StreamDecoder(strict=True).feed(BEAMS.replace(b"< 1,ARSAT", b"! 1,ARSAT"))
    with pytest.raises(ValueError):
        Log.BESTNAV.output(table=True)
    with pytest.raises(ValueError):
        Log.BESTNAV.read(table=True)
    with pytest.raises(ValueError):
        Log.BESTNAV.stop(table=True)
    with pytest.raises(ValueError):
        Log.LBANDBEAM.output(binary=True, table=True)
