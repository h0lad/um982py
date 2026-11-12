"""Exercise the public PPP workflow with receiver responses."""

from __future__ import annotations

from dataclasses import dataclass, replace
from struct import pack_into
from threading import Event
from typing import TYPE_CHECKING

import pytest

from test_bodies import binary_message, manual_message
from um982py.commands import Log
from um982py.commands.configuration import SignalGroup
from um982py.errors import CommandRejected, ProtocolError, ResponseTimeout
from um982py.messages.enums import PositionType, SolutionStatus
from um982py.messages.record import Record
from um982py.ppp import PppSession, PppSolution, _start_ppp

if TYPE_CHECKING:
    from um982py.commands.core import Command
    from um982py.receiver import Receiver


@dataclass(frozen=True)
class Config:
    signal_group: SignalGroup | None
    ppp_enabled: bool | None
    ppp_service: str | None


class FakeReceiver:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.commands: list[str] = []
        self.queries = 0
        self.fail: str | None = None
        self.bad_readback: Config | None = None
        self.reads = 0

    def configuration(self) -> Config:
        self.queries += 1
        if self.queries > 1 and self.bad_readback is not None:
            return self.bad_readback
        return self.config

    def execute[T](self, command: Command[T], *, timeout: float | None = None) -> T:
        del timeout
        self.commands.append(command.text)
        if command.text == self.fail:
            raise CommandRejected(command.text, "refused")
        if command.text.startswith("CONFIG SIGNALGROUP"):
            self.config = replace(self.config, signal_group=SignalGroup(3, 6))
        elif command.text.startswith("CONFIG PPP ENABLE"):
            self.config = replace(
                self.config, ppp_enabled=True, ppp_service=command.text.split()[-1]
            )
        return None  # type: ignore[return-value]

    def read_log(self, log: Log, *, binary: bool | None = None) -> Record:
        assert log == Log.PPPNAV and binary is None
        self.reads += 1
        return Log.PPPNAV.decode(manual_message("PPPNAVA"))

    def _poll_query(
        self, command: Command[Record], on_message: object = None
    ) -> Record:
        assert command.text == "PPPNAVB" and on_message is None
        return self.read_log(Log.PPPNAV)


def _receiver(fake: FakeReceiver) -> Receiver:
    return fake  # type: ignore[return-value]


def test_setup_changes_only_group_and_requested_service_and_reports_both() -> None:
    receiver = FakeReceiver(Config(SignalGroup(4, 5), False, None))
    session = _start_ppp(_receiver(receiver), service="B2B-PPP")
    assert receiver.commands == ["CONFIG SIGNALGROUP 3 6", "CONFIG PPP ENABLE B2B-PPP"]
    assert session.previous_group == SignalGroup(4, 5)
    assert session.active_group == SignalGroup(3, 6)
    assert session.previous_enabled is False and session.previous_service is None
    assert session.group_changed and session.service_changed
    assert session.service == "B2B-PPP"


def test_madoca_setup_selects_signal_group_and_verifies_service() -> None:
    receiver = FakeReceiver(Config(SignalGroup(4, 5), False, None))
    session = _start_ppp(_receiver(receiver), service="L6MDCPPP")
    assert receiver.commands == ["CONFIG SIGNALGROUP 3 6", "CONFIG PPP ENABLE L6MDCPPP"]
    assert session.active_group == SignalGroup(3, 6)
    assert session.service == "L6MDCPPP"
    assert session.group_changed and session.service_changed


@pytest.mark.parametrize(
    ("group", "service"),
    [
        (SignalGroup(3, 6), "E6-HAS"),
        (SignalGroup(3, 6), "L6MDCPPP"),
        (SignalGroup(7, 0), "B2B-PPP"),
    ],
)
def test_setup_leaves_matching_configuration_unchanged(
    group: SignalGroup, service: str
) -> None:
    receiver = FakeReceiver(Config(group, True, service))
    session = _start_ppp(_receiver(receiver), service=service)  # type: ignore[arg-type]
    assert receiver.commands == []
    assert not session.group_changed and not session.service_changed


@pytest.mark.parametrize("service", ["E6-HAS", "AUTO", "L6MDCPPP"])
def test_base_station_signal_group_is_changed_for_other_services(service: str) -> None:
    receiver = FakeReceiver(Config(SignalGroup(7, 0), True, service))
    session = _start_ppp(_receiver(receiver), service=service)  # type: ignore[arg-type]
    assert receiver.commands == ["CONFIG SIGNALGROUP 3 6"]
    assert session.previous_group == SignalGroup(7, 0)
    assert session.active_group == SignalGroup(3, 6)
    assert session.group_changed and not session.service_changed


def test_lowercase_service_is_normalized_before_setting_and_readback() -> None:
    receiver = FakeReceiver(Config(SignalGroup(3, 6), False, None))
    session = _start_ppp(_receiver(receiver), service="e6-has")  # type: ignore[arg-type]
    assert receiver.commands == ["CONFIG PPP ENABLE E6-HAS"]
    assert session.service == "E6-HAS"


@pytest.mark.parametrize("service", ["INVALID", "SSR-RX", "", None, 3])
def test_unsupported_services_leave_receiver_untouched(service: object) -> None:
    receiver = FakeReceiver(Config(SignalGroup(4, 5), False, None))
    with pytest.raises(ValueError):
        _start_ppp(_receiver(receiver), service=service)  # type: ignore[arg-type]
    assert receiver.queries == 0 and receiver.commands == []


def test_unknown_ppp_setting_is_configured_and_verified() -> None:
    receiver = FakeReceiver(Config(SignalGroup(3, 6), None, None))
    session = _start_ppp(_receiver(receiver), service="AUTO")
    assert receiver.commands == ["CONFIG PPP ENABLE AUTO"]
    assert session.previous_enabled is None and session.service_changed


def test_matching_exclusive_service_remains_unchanged() -> None:
    from conftest import ReplayTransport
    from um982py import Receiver
    from um982py.protocol.checksums import nmea_checksum

    def config_line(text: str) -> bytes:
        body = b"$" + text.encode("ascii")
        return body + f"*{nmea_checksum(body):02X}\r\n".encode("ascii")

    transport = ReplayTransport(
        {
            b"CONFIG\r\n": config_line("CONFIG,SIGNALGROUP,CONFIG SIGNALGROUP 3 6")
            + config_line("CONFIG,PPP,CONFIG PPP ENABLE E6-HAS ONLY")
        }
    )
    with Receiver(transport, timeout=1) as receiver:
        session = receiver.start_ppp(service="E6-HAS")
        assert not session.service_changed
    assert transport.writes == [b"CONFIG\r\n"]


def test_setup_reports_possible_partial_changes_on_rejection() -> None:
    receiver = FakeReceiver(Config(SignalGroup(4, 5), False, None))
    receiver.fail = "CONFIG PPP ENABLE E6-HAS"
    with pytest.raises(CommandRejected) as caught:
        _start_ppp(_receiver(receiver))
    assert receiver.config.signal_group == SignalGroup(3, 6)
    assert any("settings may have changed" in note for note in caught.value.__notes__)
    assert receiver.commands == ["CONFIG SIGNALGROUP 3 6", "CONFIG PPP ENABLE E6-HAS"]


def test_signal_group_readback_must_match_before_enabling_ppp() -> None:
    receiver = FakeReceiver(Config(SignalGroup(4, 5), False, None))
    receiver.bad_readback = Config(SignalGroup(4, 5), False, None)
    with pytest.raises(ProtocolError, match="signal group readback") as caught:
        _start_ppp(_receiver(receiver))
    assert receiver.commands == ["CONFIG SIGNALGROUP 3 6"]
    assert any("settings may have changed" in note for note in caught.value.__notes__)


def test_unconfirmed_ppp_readback_fails_instead_of_claiming_success() -> None:
    receiver = FakeReceiver(Config(SignalGroup(3, 6), None, None))
    receiver.bad_readback = Config(SignalGroup(3, 6), None, None)
    with pytest.raises(ProtocolError, match="PPP readback"):
        _start_ppp(_receiver(receiver))
    assert receiver.commands == ["CONFIG PPP ENABLE E6-HAS"]


def test_failed_configuration_query_does_not_write_any_settings() -> None:
    class FailingReceiver(FakeReceiver):
        def configuration(self) -> Config:
            raise ResponseTimeout("CONFIG unavailable")

    receiver = FailingReceiver(Config(None, None, None))
    with pytest.raises(ResponseTimeout):
        _start_ppp(_receiver(receiver))
    assert receiver.commands == []


def test_ascii_and_binary_normalize_statuses_and_precision() -> None:
    ascii_solution = PppSolution.from_record(
        Log.PPPNAV.decode(manual_message("PPPNAVA"))
    )
    assert ascii_solution.solution_status == SolutionStatus.SOL_COMPUTED
    assert ascii_solution.position_type == PositionType.PPP_CONVERGING
    assert ascii_solution.valid and not ascii_solution.converged
    assert ascii_solution.latitude == pytest.approx(40.07899442145)
    assert ascii_solution.horizontal_std_m == pytest.approx(
        (1.8755**2 + 1.4254**2) ** 0.5
    )
    assert ascii_solution.correction_age_s == pytest.approx(1.0)

    body = bytearray(72)
    pack_into("<IIdddfIfff", body, 0, 0, 69, 40.0, 116.0, 60.0, -8.0, 61, 0.1, 0.2, 0.3)
    pack_into("<ff", body, 56, 1.0, 2.0)
    body[64:66] = bytes([25, 20])
    binary_solution = PppSolution.from_record(
        Log.PPPNAV.decode(binary_message("PPPNAV", bytes(body)))
    )
    assert binary_solution.solution_status == SolutionStatus.SOL_COMPUTED
    assert binary_solution.position_type == PositionType.PPP
    assert binary_solution.valid and binary_solution.converged
    assert binary_solution.ellipsoidal_height == pytest.approx(52.0)
    assert binary_solution.satellites_used == 20
    assert binary_solution.horizontal_std_m == pytest.approx((0.1**2 + 0.2**2) ** 0.5)
    assert ascii_solution.datum == binary_solution.datum == "WGS84"
    assert binary_solution.record["datum_id"] == 61

    pack_into("<I", body, 36, 12345)
    unknown = PppSolution.from_record(
        Log.PPPNAV.decode(binary_message("PPPNAV", bytes(body)))
    )
    assert unknown.datum == 12345


def test_unavailable_and_unknown_values_are_not_claimed_as_valid() -> None:
    original = Log.PPPNAV.decode(manual_message("PPPNAVA"))
    changes = {
        "sol_status": "INSUFFICIENT_OBS",
        "pos_type": "UNKNOWN",
        "lat_std": -1.0,
        "lon_std": None,
    }
    record = replace(
        original,
        entries=tuple(
            (key, changes.get(key, value)) for key, value in original.entries
        ),
    )
    fix = PppSolution.from_record(record)
    assert not fix.valid and not fix.converged
    assert fix.position_type == "UNKNOWN"
    assert fix.latitude_std_m is None and fix.horizontal_std_m is None


def test_polling_can_stop_after_a_read_and_propagates_errors() -> None:
    fake = FakeReceiver(Config(SignalGroup(3, 6), True, "E6-HAS"))
    session: PppSession = _start_ppp(_receiver(fake))
    stop = Event()
    positions = session.positions(interval=0.01, stop=stop)
    assert next(positions).valid
    stop.set()
    assert list(positions) == [] and fake.reads == 1
    with pytest.raises(ValueError, match="interval"):
        next(session.positions(interval=0))

    class FailingReceiver(FakeReceiver):
        def read_log(self, log: Log, *, binary: bool | None = None) -> Record:
            raise ResponseTimeout("no PPP response")

    failing = FailingReceiver(Config(SignalGroup(3, 6), True, "E6-HAS"))
    with pytest.raises(ResponseTimeout, match="no PPP response"):
        next(_start_ppp(_receiver(failing)).positions())


@pytest.mark.parametrize("service", ["E6-HAS", "L6MDCPPP"])
def test_receiver_start_ppp_queries_and_verifies_real_configuration(
    service: str,
) -> None:
    from conftest import ReplayTransport, acknowledgement
    from um982py import Receiver
    from um982py.protocol.checksums import nmea_checksum

    class ConfigTransport(ReplayTransport):
        def __init__(self) -> None:
            super().__init__(chunk=4096)
            self.group = (4, 5)
            self.service: str | None = None

        def write(self, data: bytes, timeout: float) -> None:
            del timeout
            self.writes.append(data)
            command = data.decode("ascii").strip()
            if command == "CONFIG":
                group = (
                    f"CONFIG,SIGNALGROUP,CONFIG SIGNALGROUP "
                    f"{self.group[0]} {self.group[1]}"
                )
                ppp = (
                    f"CONFIG,PPP,CONFIG PPP ENABLE {self.service}"
                    if self.service
                    else "CONFIG,PPP,CONFIG PPP DISABLE"
                )
                for line in (group, ppp):
                    body = b"$" + line.encode()
                    self.pending.extend(
                        body + f"*{nmea_checksum(body):02X}\r\n".encode()
                    )
            elif command == "CONFIG SIGNALGROUP 3 6":
                self.group = (3, 6)
                self.pending.extend(acknowledgement(command))
            elif command == f"CONFIG PPP ENABLE {service}":
                self.service = service
                self.pending.extend(acknowledgement(command))
            elif command == "PPPNAVB":
                fixture = Path(__file__).parent / "fixtures/captures-extra/PPPNAVB.bin"
                self.pending.extend(fixture.read_bytes())
            else:
                raise AssertionError(command)

    from pathlib import Path

    transport = ConfigTransport()
    with Receiver(transport, timeout=1) as receiver:
        ppp = receiver.start_ppp(service=service)  # type: ignore[arg-type]
        solution = ppp.position()
        assert ppp.group_changed and ppp.service_changed
        assert solution.valid and solution.position_type is PositionType.PPP_CONVERGING
        assert solution.horizontal_std_m is not None
    assert transport.writes == [
        b"CONFIG\r\n",
        b"CONFIG SIGNALGROUP 3 6\r\n",
        b"CONFIG\r\n",
        f"CONFIG PPP ENABLE {service}\r\n".encode(),
        b"CONFIG\r\n",
        b"PPPNAVB\r\n",
    ]
