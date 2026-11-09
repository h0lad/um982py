"""Run the README snippets unchanged against recorded receiver responses."""

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import (
    ReplayTransport,
    SubscriptionTransport,
    acknowledgement,
    ascii_message,
)
from um982py import HIGH_ACCURACY_SIGNAL_GROUP, Receiver
from um982py.commands.types import Port
from um982py.messages import AsciiMessage
from um982py.protocol.ascii import parse_ascii
from um982py.rinex import RinexExport

ROOT = Path(__file__).resolve().parents[1]
SNIPPETS = dict(
    re.findall(
        r"^### ([^\n]+)\n(?:(?!^### ).)*?```python\n(.*?)```",
        (ROOT / "README.md").read_text(encoding="utf-8"),
        re.S | re.M,
    )
)


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
    exec(compile(SNIPPETS[example], "README.md", "exec"), namespace)  # noqa: S102
    assert transport.writes == [command] * queries
    assert transport.closed
    return namespace


def test_readme_position(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _run_snippet(
        "Locate a field site",
        "bodies/BESTNAVA.bin",
        b"BESTNAVA\r\n",
        monkeypatch,
        tmp_path,
    )
    assert capsys.readouterr().out == (
        "52.53369589952, 13.37633656974\n"
        "Solution: SINGLE, satellites used: 7\n"
        "Latitude standard deviation: 2.46 m\n"
        "Longitude standard deviation: 2.19 m\n"
        "Height standard deviation: 2.85 m\n"
    )


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
        "Locate a field site",
        ascii_message("BESTNAVA", ",".join(fields)),
        b"BESTNAVA\r\n",
        monkeypatch,
        tmp_path,
    )
    assert capsys.readouterr().out == "No position available yet\n"


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
    assert lines[0] == "System 0, PRN 29, signal 0: SNR 22"
    assert "System 0, PRN 26, signal 14: SNR 39" in lines


def test_readme_precise_position_can_be_interrupted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    samples = json.loads(
        (ROOT / "tests/fixtures/manual-examples-r1.4.json").read_text(encoding="utf-8")
    )
    raw = (samples["PPPNAVA"] + "\r\n").encode("ascii")
    message = parse_ascii(raw)
    assert isinstance(message, AsciiMessage)
    fields = list(message.fields)
    fields[2] = str(float(fields[2]) + 0.00001)
    moved = ascii_message("PPPNAVA", ",".join(fields))
    command = b"CONFIG PPP ENABLE E6-HAS\r\n"
    transport = ReplayTransport(
        {command: acknowledgement("CONFIG PPP ENABLE E6-HAS"), b"PPPNAVA\r\n": raw}
    )
    monkeypatch.setattr(
        Receiver, "serial", staticmethod(lambda *args: Receiver(transport, timeout=1))
    )
    monkeypatch.setattr(
        Receiver,
        "enable_augmentation",
        lambda receiver: SimpleNamespace(active_group=HIGH_ACCURACY_SIGNAL_GROUP),
    )
    pauses = 0

    def stop_after_two_readings(seconds: float) -> None:
        nonlocal pauses
        assert seconds == 5
        pauses += 1
        if pauses == 1:
            transport.responses[b"PPPNAVA\r\n"] = moved
        else:
            raise KeyboardInterrupt

    monkeypatch.setattr("time.sleep", stop_after_two_readings)
    exec(  # noqa: S102
        compile(SNIPPETS["Watch a precise position converge"], "README.md", "exec"), {}
    )
    output = capsys.readouterr().out
    assert output.count("Solution: SOL_COMPUTED, PPP_CONVERGING") == 2
    assert "Receiver std (lat, lon, height), m: 1.8755, 1.4254, 2.4821" in output
    assert "Change since previous reading: 1.112 m" in output
    assert output.endswith("Stopped\n")
    assert transport.writes == [command, b"PPPNAVA\r\n", b"PPPNAVA\r\n"]
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
    exec(  # noqa: S102
        compile(
            SNIPPETS["Record observations for post-processing"], "README.md", "exec"
        ),
        namespace,
    )
    result = namespace["result"]
    assert isinstance(result, RinexExport)
    assert result.epochs == 26
    assert result.satellite_records == 898
    assert result.signal_observations == 1524
    assert result.omitted == {
        "invalid_code_or_phase": 719,
        "unverified_l2c_component": 104,
    }
    assert transport.closed
    assert ("RANGEB", Port.COM1) not in transport.subscriptions
    text = (tmp_path / "field.obs").read_text(encoding="ascii")
    assert text == result.text
    assert text.startswith("     3.05")
    assert "FIELD01" in text
    assert text.count("\n> ") == 26
