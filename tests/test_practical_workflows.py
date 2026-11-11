import csv
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from xml.etree import ElementTree

import pytest

from conftest import FIXTURES, ReplayTransport, ascii_message, rtcm, sentence
from um982py import (
    Fix,
    Receiver,
    Rover,
    TrackWriter,
    survey_point,
    wait_for_fix,
    waypoint_direction,
)
from um982py.errors import ResponseTimeout
from um982py.messages.navigation import BestNavigation
from um982py.protocol.ascii import parse_ascii


def gga(utc: str, *, quality: int = 4, age: str = "2.0") -> bytes:
    return sentence(
        f"GNGGA,{utc},5232.0000,N,01322.0000,E,{quality},17,1.3,38.0,M,36.0,M,{age},1".encode()
    )


def fix(raw: bytes) -> Fix:
    return Fix.from_message(parse_ascii(raw))


def test_wait_for_fixed_position_and_age(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [0.0]
    monkeypatch.setattr("um982py.survey.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "um982py.survey.sleep", lambda value: clock.__setitem__(0, clock[0] + value)
    )
    replies = iter(
        [
            gga("120000", quality=1),
            gga("120001", age=""),
            gga("120002", age="3"),
            gga("120003", age="1"),
        ]
    )

    class ReceiverStub:
        timeout = 3.0

        def execute(self, command: object, *, timeout: float) -> Fix:
            return fix(next(replies))

    result = wait_for_fix(
        ReceiverStub(), timeout=5, interval=1, rtk_fixed=True, max_correction_age=2
    )  # type: ignore[arg-type]
    assert result.utc == "120003" and clock[0] == 3


def test_wait_for_fix_times_out_and_validates_without_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    monkeypatch.setattr("um982py.survey.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "um982py.survey.sleep", lambda value: clock.__setitem__(0, clock[0] + value)
    )

    class ReceiverStub:
        timeout = 1.0

        def execute(self, command: object, *, timeout: float) -> Fix:
            clock[0] += timeout
            raise ResponseTimeout("missing")

    receiver = ReceiverStub()
    with pytest.raises(ResponseTimeout, match="acceptable"):
        wait_for_fix(receiver, timeout=2, interval=0.1)  # type: ignore[arg-type]
    assert clock[0] == 2
    with pytest.raises(ValueError, match="interval"):
        wait_for_fix(receiver, interval=0)  # type: ignore[arg-type]


def test_survey_rejects_duplicate_epochs_and_invalid_fixes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clock = [0.0]
    monkeypatch.setattr("um982py.survey.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "um982py.survey.sleep", lambda value: clock.__setitem__(0, clock[0] + value)
    )
    replies = iter(
        [gga("120000"), gga("120000.00"), gga("120001", quality=1), gga("120002")]
    )

    class ReceiverStub:
        timeout = 1.0

        def execute(self, command: object, *, timeout: float) -> Fix:
            return fix(next(replies))

    result = survey_point(ReceiverStub(), duration=4, interval=1, rtk_fixed=True)  # type: ignore[arg-type]
    assert (result.samples, result.rejected, result.quality_counts) == (2, 2, ((4, 2),))
    assert result.latitude == pytest.approx(52.533333333333)
    assert result.ellipsoidal_height_m == pytest.approx(74.0, abs=1e-5)
    assert result.horizontal_scatter_m == pytest.approx(0, abs=1e-8)
    output = result.write_csv(tmp_path / "point.csv")
    with output.open(newline="") as stream:
        row = next(csv.DictReader(stream))
    assert row["samples"] == "2" and json.loads(row["quality_counts"]) == {"4": 2}
    with pytest.raises(FileExistsError):
        result.write_csv(output)


def test_waypoint_direction_wrap_and_undefined_bearing() -> None:
    east = waypoint_direction(0, 0, 0, 1, heading_deg=350)
    assert east.distance_m == pytest.approx(111195.08, rel=1e-5)
    assert east.bearing_deg == pytest.approx(90)
    assert east.turn_deg == pytest.approx(100)
    assert waypoint_direction(10, 20, 10, 20).bearing_deg is None
    assert waypoint_direction(0, 0, 0, 180).bearing_deg is None
    with pytest.raises(ValueError, match="heading_deg"):
        waypoint_direction(0, 0, 0, 1, heading_deg=360)


@pytest.mark.parametrize("fmt", ["gpx", "geojson", "csv"])
def test_track_writer_streams_valid_positions_without_overwriting(
    tmp_path: Path, fmt: str
) -> None:
    path = tmp_path / ("track." + fmt)
    sample = fix(gga("120000"))
    stamp = datetime(2024, 1, 1, tzinfo=UTC)
    with TrackWriter(path, format=fmt, reference_frame="WGS84") as writer:  # type: ignore[arg-type]
        writer.write(sample, timestamp=stamp)
        with pytest.raises(ValueError, match="invalid position"):
            writer.write(replace(sample, quality=0))
        writer.write(sample)
    if fmt == "gpx":
        root = ElementTree.parse(path).getroot()  # noqa: S314
        points = root.findall(".//{http://www.topografix.com/GPX/1/1}trkpt")
        assert len(points) == 2
        assert points[0].find("{http://www.topografix.com/GPX/1/1}ele").text == "38.0"
        assert (
            points[0].find("{http://www.topografix.com/GPX/1/1}time").text
            == "2024-01-01T00:00:00Z"
        )
    elif fmt == "geojson":
        features = json.loads(path.read_text())["features"]
        assert len(features) == 2
        assert features[0]["geometry"]["coordinates"] == pytest.approx(
            [13.366666666666667, 52.53333333333333, 74]
        )
        assert features[0]["properties"]["quality"] == "4"
    else:
        with path.open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == 2 and rows[0]["time_utc"] == "2024-01-01T00:00:00Z"
        assert rows[0]["ellipsoidal_height_m"] == "74.0"
    with (
        pytest.raises(FileExistsError),
        TrackWriter(path, format=fmt, reference_frame="WGS84"),
    ):  # type: ignore[arg-type]
        pass


@pytest.mark.parametrize(
    ("latitude", "longitude", "error"),
    [
        (float("nan"), 0, "coordinates must be finite"),
        (91, float("inf"), "coordinates must be finite"),
        (91, 181, "latitude must be"),
        (0, 181, "longitude must be"),
    ],
)
def test_track_writer_rejects_invalid_manual_coordinates(
    tmp_path: Path, latitude: float, longitude: float, error: str
) -> None:
    sample = replace(fix(gga("120000")), latitude=latitude, longitude=longitude)
    with (
        TrackWriter(
            tmp_path / "track.csv", format="csv", reference_frame="WGS84"
        ) as writer,
        pytest.raises(ValueError, match=error),
    ):
        writer.write(sample)


def test_rover_pairs_only_matching_heading_epochs() -> None:
    raw_nav = (FIXTURES / "bodies/BESTNAVA.bin").read_bytes()
    parsed = parse_ascii(raw_nav)
    assert BestNavigation.from_message(parsed).valid
    nav_fields = ",".join(parsed.fields)
    nav = ascii_message("BESTNAVA", nav_fields)
    heading_fields = (
        'SOL_COMPUTED,NARROW_INT,1.5,275.1,-2.0,0.0,0.1,0.2,"",10,8,8,8,0,00,0,0'
    )
    raw_heading = ascii_message("UNIHEADINGA", heading_fields)
    transport = ReplayTransport(
        {b"BESTNAVA\r\n": nav, b"UNIHEADINGA\r\n": raw_heading}, chunk=65536
    )
    receiver = Receiver(transport, timeout=0.5)
    with Rover(receiver) as rover:
        sample = rover.position()
        assert sample.position.valid
        assert sample.heading_deg == pytest.approx(275.1)
        assert sample.pitch_deg == pytest.approx(-2)
        assert sample.heading_offset_s == 0
        assert sample.heading_type.name == "NARROW_INT"
        assert sample.correction_age_s is None
        assert rover.correction_health() is None
        transport.responses[b"UNIHEADINGA\r\n"] = raw_heading.replace(
            b"2400,123000", b"2400,124000"
        )
        different_epoch_body = transport.responses[b"UNIHEADINGA\r\n"].split(b"*")[0][
            1:
        ]
        from um982py.protocol.checksums import unicore_crc32

        transport.responses[b"UNIHEADINGA\r\n"] = (
            b"#"
            + different_epoch_body
            + f"*{unicore_crc32(different_epoch_body):08x}\r\n".encode()
        )
        assert rover.position().heading_deg is None
    assert not transport.closed
    receiver.close()


def test_rover_relays_ntrip_while_reading_positions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.examples.test_ntrip_client import FakeSocket
    from um982py.streaming import ReceiverStream

    frame = rtcm((1005 << 4).to_bytes(2, "big"))
    socket = FakeSocket(b"HTTP/1.1 200 OK\r\n\r\n" + frame)
    monkeypatch.setattr("socket.create_connection", lambda *args: socket)
    transport = ReplayTransport(
        {
            b"GPGGA\r\n": gga("120000"),
            b"BESTNAVA\r\n": (FIXTURES / "bodies/BESTNAVA.bin").read_bytes(),
        },
        chunk=65536,
    )
    forwarded = Event()
    original = ReceiverStream.send_correction

    def send(stream: ReceiverStream, message: object) -> object:
        future = original(stream, message)  # type: ignore[arg-type]
        future.add_done_callback(lambda _: forwarded.set())
        return future

    monkeypatch.setattr(ReceiverStream, "send_correction", send)
    receiver = Receiver(transport, timeout=0.5)
    with Rover(receiver, ntrip_url="http://caster.example:2101/BASE") as rover:
        assert forwarded.wait(3)
        assert rover.position(heading=False).position.valid
        assert rover.wait_for_fix(timeout=2, rtk_fixed=True).rtk_fixed
        assert frame in transport.writes
        assert rover.correction_health().frames_forwarded >= 1
    assert b"Ntrip-GGA: $GPGGA," in socket.sent[0]
    assert not transport.closed
    receiver.close()


def test_rover_surfaces_terminal_correction_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from um982py.ntrip import NtripError
    from um982py.rtk_session import RtkSession

    def failed_run(session: RtkSession, stop: Event) -> None:
        raise NtripError("caster rejected credentials", status_code=401)

    monkeypatch.setattr(RtkSession, "run", failed_run)
    transport = ReplayTransport()
    receiver = Receiver(transport, timeout=0.1)
    with Rover(receiver, ntrip_url="http://caster.example/MOUNT") as rover:
        assert rover._thread is not None
        rover._thread.join(timeout=2)
        with pytest.raises(RuntimeError, match="correction relay failed") as error:
            rover.position(heading=False)
        assert isinstance(error.value.__cause__, NtripError)
    assert not transport.closed
    receiver.close()


def test_replaced_blocking_relay_is_not_exposed() -> None:
    import um982py
    import um982py.rtk_session

    assert not hasattr(um982py, "relay_ntrip")
    assert not hasattr(um982py.rtk_session, "relay_ntrip")


def test_rover_connect_closes_receiver_after_invalid_caster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = ReplayTransport()
    receiver = Receiver(transport)
    monkeypatch.setattr(
        Receiver, "connect", classmethod(lambda cls, *args, **kwargs: receiver)
    )
    with pytest.raises(ValueError, match="URL"):
        Rover.connect("unused", ntrip_url="invalid")
    assert transport.closed
