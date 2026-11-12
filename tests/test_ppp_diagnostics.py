import pytest

from conftest import SubscriptionTransport
from um982py import Receiver
from um982py.commands.types import Port
from um982py.diagnostics import (
    PPP_LOGS,
    DiagnosticCapture,
    collect_diagnostics,
    ppp_diagnostics,
)
from um982py.errors import CommandRejected
from um982py.protocol.checksums import nmea_checksum


class ConfiguredTransport(SubscriptionTransport):
    def write(self, data: bytes, timeout: float) -> None:
        if data == b"CONFIG\r\n":
            self.writes.append(data)
            body = b"$CONFIG,SIGNALGROUP,CONFIG SIGNALGROUP 3 6"
            self.pending.extend(body + f"*{nmea_checksum(body):02X}\r\n".encode())
            return
        super().write(data, timeout)


def test_ppp_diagnostics_skip_removed_logs_and_restore_subscriptions() -> None:
    transport = ConfiguredTransport()
    transport.rejected.update({"PPPB2BINFO6B ONCHANGED", "PPPB2BINFO7B ONCHANGED"})
    transport.subscriptions = {
        ("PPPNAVB", Port.COM1): 0.2,
        ("GPGGA", Port.COM1): 1.0,
    }
    before = transport.subscriptions.copy()
    with Receiver(transport, timeout=0.05) as receiver:
        capture = collect_diagnostics(receiver, PPP_LOGS, seconds=0.001)
    commands = [data.decode().strip() for data in transport.writes]
    assert all(
        "PPPB2BINFO6" not in item and "PPPB2BINFO7" not in item for item in commands
    )
    assert "PPPB2BINFO5B ONCHANGED" in commands
    assert transport.subscriptions == before
    assert capture.subscriptions_restored and capture.configuration_restored


def test_rejected_ppp_log_restores_earlier_subscriptions() -> None:
    transport = ConfiguredTransport()
    transport.subscriptions = {("PPPNAVB", Port.COM1): 0.2}
    before = transport.subscriptions.copy()
    transport.rejected.add("PPPB2BINFO2B ONCHANGED")
    with Receiver(transport, timeout=0.05) as receiver, pytest.raises(CommandRejected):
        collect_diagnostics(receiver, PPP_LOGS, seconds=0.001)
    assert transport.subscriptions == before


@pytest.mark.parametrize(
    ("group", "expected"),
    [
        ("3 6", True),
        ("7 0", True),
        ("7", True),
        ("4 5", False),
        ("7 6", False),
        ("3", False),
    ],
)
def test_b2b_group_evidence(group: str, expected: bool) -> None:
    capture = DiagnosticCapture(
        {}, 1, True, True, (("SIGNALGROUP", f"CONFIG SIGNALGROUP {group}"),)
    )
    report = ppp_diagnostics(capture)
    assert report["b2b_documented_signal_group_met"] is expected
    assert report["correction_application_verified"] is False
