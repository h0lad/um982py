"""Run library recipes from the main and example READMEs against recorded data."""

import csv
import re
from io import StringIO
from pathlib import Path
from struct import pack_into, unpack_from
from types import CodeType, SimpleNamespace

import pytest

from conftest import (
    ReplayTransport,
    SubscriptionTransport,
    acknowledgement,
    ascii_message,
)
from um982py import Receiver, Rover
from um982py.commands.configuration import SignalGroup
from um982py.commands.types import Port
from um982py.messages import AsciiMessage
from um982py.ppp import PppSolution
from um982py.protocol.ascii import parse_ascii
from um982py.protocol.binary import BINARY_HEADER
from um982py.protocol.checksums import unicore_crc32
from um982py.rinex import RinexExport

ROOT = Path(__file__).resolve().parents[1]
SNIPPET_SOURCES = {
    title: (code, str(path.relative_to(ROOT)))
    for path in (
        ROOT / "README.md",
        ROOT / "examples/has_b2b_ppp_fix/README.md",
        ROOT / "examples/heading_attitude/README.md",
        ROOT / "examples/ntrip_client/README.md",
        ROOT / "examples/rinex_export/README.md",
        ROOT / "examples/satellite_monitor/README.md",
    )
    for title, code in re.findall(
        r"^#{2,6} ([^\n]+)\n(?:(?!^#{2,6} ).)*?^```python\n(.*?)^```",
        path.read_text(encoding="utf-8"),
        re.S | re.M,
    )
}
SNIPPETS = {
    title: compile(code, path, "exec")
    for title, (code, path) in SNIPPET_SOURCES.items()
}


def _configured_snippet(example: str, **settings: object) -> CodeType:
    code, path = SNIPPET_SOURCES[example]
    for name, value in settings.items():
        code, count = re.subn(
            rf"^{name} = .*$",
            lambda _, replacement=f"{name} = {value!r}": replacement,
            code,
            flags=re.M,
        )
        assert count == 1
    return compile(code, path, "exec")


def _run_snippet(
    example: str,
    capture: str | bytes,
    command: bytes,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    queries: int = 1,
) -> dict[str, object]:
    raw = (
        capture
        if isinstance(capture, bytes)
        else (ROOT / "tests" / "fixtures" / capture).read_bytes()
    )
    transport = ReplayTransport({command: raw}, chunk=7)

    def serial(port: str, baudrate: int, *, timeout: float = 3) -> Receiver:
        assert (port, baudrate) == ("/dev/ttyUSB0", 921600)
        assert timeout > 0
        return Receiver(transport, timeout=0.1)

    monkeypatch.setattr(Receiver, "serial", staticmethod(serial))
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {}
    exec(SNIPPETS[example], namespace)  # noqa: S102
    assert transport.writes == [command] * queries
    assert transport.closed
    return namespace


def test_readme_position(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_snippet(
        "Read one position",
        "bodies/BESTNAVA.bin",
        b"BESTNAVA\r\n",
        monkeypatch,
        tmp_path,
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ["52.53369589952 13.37633656974", "Solution: SINGLE"]
    assert float(lines[2].split(": ")[1]) == pytest.approx(
        (2.4576**2 + 2.1854**2) ** 0.5
    )
    assert float(lines[3].split(": ")[1]) == pytest.approx(2.852)


def test_readme_quick_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_snippet(
        "Quick start",
        "bodies/BESTNAVA.bin",
        b"BESTNAVA\r\n",
        monkeypatch,
        tmp_path,
    )
    assert capsys.readouterr().out == "52.53369589952 13.37633656974 SINGLE\n"


def test_readme_corrected_rover(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeRover:
        def __enter__(self) -> "FakeRover":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def poll_positions(
            self, *, interval: float, heading: bool
        ) -> list[SimpleNamespace]:
            assert interval == 1 and heading
            return [
                SimpleNamespace(
                    position=SimpleNamespace(valid=True, latitude=52.5, longitude=13.4),
                    heading_deg=90.0,
                    correction_age_s=2.0,
                )
            ]

    def connect(target: str, baudrate: int, *, ntrip_url: str) -> FakeRover:
        assert (target, baudrate, ntrip_url) == (
            "/dev/ttyUSB0",
            921600,
            "https://caster.example:443/MOUNT",
        )
        return FakeRover()

    monkeypatch.setattr(Rover, "connect", staticmethod(connect))
    exec(SNIPPETS["Use a corrected rover"], {})  # noqa: S102
    assert capsys.readouterr().out == ("52.5 13.4\nHeading: 90.0 correction age: 2.0\n")


def test_readme_position_without_solution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw = (ROOT / "tests/fixtures/bodies/BESTNAVA.bin").read_bytes()
    message = parse_ascii(raw)
    assert isinstance(message, AsciiMessage)
    fields = ("INSUFFICIENT_OBS", *message.fields[1:])
    _run_snippet(
        "Read one position",
        ascii_message("BESTNAVA", ",".join(fields)),
        b"BESTNAVA\r\n",
        monkeypatch,
        tmp_path,
    )
    assert capsys.readouterr().out == "No position available yet\n"


def _position_transport(
    monkeypatch: pytest.MonkeyPatch, service: str | None
) -> tuple[ReplayTransport, bytes]:
    command = b"BESTNAVA\r\n" if service is None else b"PPPNAVB\r\n"
    fixture = "bodies/BESTNAVA.bin" if service is None else "captures-extra/PPPNAVB.bin"
    transport = ReplayTransport(
        {command: (ROOT / "tests/fixtures" / fixture).read_bytes()}
    )

    def serial(port: str, baudrate: int, *, timeout: float = 3) -> Receiver:
        assert (port, baudrate) == ("/dev/ttyUSB0", 921600)
        return Receiver(transport, timeout=timeout)

    def configuration(receiver: Receiver) -> SimpleNamespace:
        assert service is not None
        return SimpleNamespace(
            signal_group=SignalGroup(3, 6), ppp_enabled=True, ppp_service=service
        )

    monkeypatch.setattr(Receiver, "serial", staticmethod(serial))
    monkeypatch.setattr(Receiver, "configuration", configuration)
    return transport, command


@pytest.mark.parametrize("service", ["E6-HAS", "B2B-PPP"])
def test_readme_single_ppp_position(
    service: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport, command = _position_transport(monkeypatch, service)
    namespace: dict[str, object] = {}
    exec(_configured_snippet("Read one position", service=service), namespace)  # noqa: S102
    position = namespace["position"]
    assert isinstance(position, PppSolution)
    assert position.valid and not position.converged
    output = capsys.readouterr().out
    assert "Solution: PPP_CONVERGING" in output
    assert "Horizontal RMS (m):" in output and "Vertical std (m):" in output
    assert transport.writes == [command]
    assert transport.closed


@pytest.mark.parametrize("service", [None, "E6-HAS", "B2B-PPP"])
def test_readme_precision_csv_preserves_status_and_missing_values(
    service: str | None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    transport, command = _position_transport(monkeypatch, service)
    clock = [0.0]

    def pause(seconds: float) -> None:
        assert seconds == 5
        clock[0] += seconds
        if service is not None:
            body = bytearray(transport.responses[command][:-4])
            pack_into("<I", body, BINARY_HEADER.size + 4, 69)  # PPP
            pack_into("<fff", body, BINARY_HEADER.size + 40, 0.1, 0.2, 0.3)
            if clock[0] >= 10:
                pack_into("<I", body, BINARY_HEADER.size, 1)  # INSUFFICIENT_OBS
            transport.responses[command] = bytes(body) + unicore_crc32(body).to_bytes(
                4, "little"
            )
        elif clock[0] >= 10:
            message = parse_ascii(transport.responses[command])
            assert isinstance(message, AsciiMessage)
            transport.responses[command] = ascii_message(
                "BESTNAVA", ",".join(("INSUFFICIENT_OBS", *message.fields[1:]))
            )

    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    monkeypatch.setattr("time.sleep", pause)
    exec(  # noqa: S102
        _configured_snippet(
            "Watch precision over time", service=service, duration_s=15
        ),
        {},
    )
    rows = list(csv.DictReader(StringIO(capsys.readouterr().out)))
    assert [float(row["elapsed_s"]) for row in rows] == [0, 5, 10]
    assert [row["valid"] for row in rows] == ["True", "True", "False"]
    assert float(rows[0]["horizontal_rms_m"]) > 0
    assert rows[2]["horizontal_rms_m"] == rows[2]["vertical_std_m"] == ""
    if service is None:
        assert all(row["converged"] == "" for row in rows)
        assert rows[0]["solution"] == "SINGLE"
    else:
        assert [row["converged"] for row in rows] == ["False", "True", "False"]
        assert rows[0]["solution"] == "PPP_CONVERGING"
        assert rows[1]["solution"] == "PPP"
        assert float(rows[1]["horizontal_rms_m"]) == pytest.approx(0.05**0.5)
        assert float(rows[1]["vertical_std_m"]) == pytest.approx(0.3)
        assert rows[0]["correction_age_s"] != ""
    assert transport.writes == [command] * 3
    assert transport.closed


@pytest.mark.parametrize(
    ("capture", "expected"),
    [
        ("captures-live/GNTHS.bin", "Heading: 275.1° clockwise from true north\n"),
        ("gpths.bin", "Dual-antenna heading is not available yet\n"),
    ],
)
def test_readme_heading(
    capture: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_snippet(
        "Get the direction of a vehicle", capture, b"GPTHS\r\n", monkeypatch, tmp_path
    )
    assert capsys.readouterr().out == expected


def test_readme_satellite_reception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_snippet(
        "Check satellite reception",
        "bodies/SATSINFOB.bin",
        b"SATSINFOB\r\n",
        monkeypatch,
        tmp_path,
    )
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "GPS 29"
    assert lines[1] == "  L1 C/A: SNR 22"
    assert "  L5 pilot: SNR 39" in lines


def test_readme_precise_position_can_be_interrupted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = (ROOT / "tests/fixtures/captures-extra/PPPNAVB.bin").read_bytes()
    body = bytearray(raw[:-4])
    latitude = unpack_from("<d", body, BINARY_HEADER.size + 8)[0]
    pack_into("<d", body, BINARY_HEADER.size + 8, latitude + 0.00001)
    moved = bytes(body) + unicore_crc32(body).to_bytes(4, "little")
    group = b"CONFIG SIGNALGROUP 3 6\r\n"
    service = b"CONFIG PPP ENABLE E6-HAS\r\n"
    transport = ReplayTransport(
        {
            group: acknowledgement("CONFIG SIGNALGROUP 3 6"),
            service: acknowledgement("CONFIG PPP ENABLE E6-HAS"),
            b"PPPNAVB\r\n": raw,
        }
    )
    monkeypatch.setattr(
        Receiver, "serial", staticmethod(lambda *args: Receiver(transport, timeout=1))
    )
    configs = iter(
        [
            SimpleNamespace(
                signal_group=SignalGroup(4, 5), ppp_enabled=False, ppp_service=None
            ),
            SimpleNamespace(
                signal_group=SignalGroup(3, 6), ppp_enabled=False, ppp_service=None
            ),
            SimpleNamespace(
                signal_group=SignalGroup(3, 6), ppp_enabled=True, ppp_service="E6-HAS"
            ),
        ]
    )
    monkeypatch.setattr(Receiver, "configuration", lambda receiver: next(configs))
    pauses = 0

    def stop_after_two_readings(seconds: float) -> None:
        nonlocal pauses
        assert seconds == 5
        pauses += 1
        if pauses == 1:
            transport.responses[b"PPPNAVB\r\n"] = moved
        else:
            raise KeyboardInterrupt

    monkeypatch.setattr("um982py.ppp.sleep", stop_after_two_readings)
    exec(SNIPPETS["Watch a precise position converge"], {})  # noqa: S102
    output = capsys.readouterr().out
    assert output.count("PPP_CONVERGING: horizontal RMS") == 2
    assert "height std 30.083" in output and "correction age 14.0 s" in output
    assert "Change: 1.112 m" in output
    assert output.endswith("Stopped\n")
    assert transport.writes == [group, service, b"PPPNAVB\r\n", b"PPPNAVB\r\n"]
    assert transport.closed


def test_readme_rinex(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clock = [0.0]

    class SessionTransport(SubscriptionTransport):
        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending:
                clock[0] += timeout
            return super().read(size, timeout)

    transport = SessionTransport()
    transport.after_write["RANGEB 1"] = (
        ROOT / "tests/fixtures/captures-live/RANGEA.bin"
    ).read_bytes()
    monkeypatch.setattr("um982py.capture.monotonic", lambda: clock[0])
    monkeypatch.setattr("um982py.receiver.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        Receiver, "serial", staticmethod(lambda *args: Receiver(transport, timeout=1))
    )
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {}
    exec(SNIPPETS["Record observations for post-processing"], namespace)  # noqa: S102
    result = namespace["result"]
    assert isinstance(result, RinexExport)
    assert result.epochs == 26
    assert result.satellite_records == 898
    assert result.signal_observations == 1628
    assert result.omitted == {
        "invalid_code_or_phase": 719,
    }
    assert transport.closed
    assert ("RANGEB", Port.COM1) not in transport.subscriptions
    text = (tmp_path / "field.obs").read_text(encoding="ascii")
    assert text == result.text
    assert text.startswith("     3.05")
    assert "FIELD01" in text
    assert text.count("\n> ") == 26
