"""Checks receiver-state restoration for shared example subscriptions."""

import pytest

from conftest import SubscriptionTransport
from um982py import Receiver
from um982py.commands import Log, Trigger
from um982py.commands.types import Port
from um982py.errors import CommandRejected, ResponseTimeout
from um982py.subscriptions import temporary_subscriptions


@pytest.mark.parametrize("fail_body", [False, True])
def test_temporary_subscriptions_restore_existing_logs(fail_body: bool) -> None:
    transport = SubscriptionTransport()
    transport.subscriptions = {
        ("BESTNAVA", Port.COM1): 10.0,
        ("BESTNAVA", Port.COM2): Trigger.ON_CHANGED,
        ("GPGGA", Port.COM1): 1.0,
    }
    before = transport.subscriptions.copy()
    with Receiver(transport) as receiver:
        try:
            with temporary_subscriptions(
                receiver,
                ("BESTNAVA", Log.BESTNAV.output(0.2)),
                ("SATSINFOA", Log.SATSINFO.output(1)),
            ):
                assert transport.subscriptions["BESTNAVA", Port.COM1] == 0.2
                assert ("SATSINFOA", Port.COM1) in transport.subscriptions
                if fail_body:
                    raise RuntimeError("collection failed")
        except RuntimeError as error:
            assert fail_body and str(error) == "collection failed"
    assert transport.subscriptions == before


def test_temporary_subscriptions_restore_explicit_port() -> None:
    transport = SubscriptionTransport()
    transport.subscriptions = {("BESTNAVA", Port.COM1): 10.0}
    before = transport.subscriptions.copy()
    with (
        Receiver(transport) as receiver,
        temporary_subscriptions(
            receiver, ("BESTNAVA", Log.BESTNAV.output(0.2, port=Port.COM3))
        ),
    ):
        assert transport.subscriptions["BESTNAVA", Port.COM3] == 0.2
    assert transport.subscriptions == before


def test_missing_acknowledgement_still_restores_applied_change() -> None:
    transport = SubscriptionTransport()
    transport.subscriptions = {("BESTNAVA", Port.COM1): 10.0}
    before = transport.subscriptions.copy()
    transport.silent.add("BESTNAVA 0.2")
    with (
        Receiver(transport, timeout=0.001) as receiver,
        pytest.raises(ResponseTimeout),
        temporary_subscriptions(receiver, ("BESTNAVA", Log.BESTNAV.output(0.2))),
    ):
        pytest.fail("the unacknowledged subscription must fail on entry")
    assert transport.subscriptions == before


def test_cleanup_failure_is_reported_and_other_logs_are_restored() -> None:
    transport = SubscriptionTransport()
    transport.subscriptions = {("BESTNAVA", Port.COM1): 10.0}
    transport.rejected.add("UNLOG SATSINFOA")
    with (
        Receiver(transport) as receiver,
        pytest.raises(ExceptionGroup) as caught,
        temporary_subscriptions(
            receiver,
            ("BESTNAVA", Log.BESTNAV.output(0.2)),
            ("SATSINFOA", Log.SATSINFO.output(1)),
        ),
    ):
        pass
    assert len(caught.value.exceptions) == 1
    assert isinstance(caught.value.exceptions[0], CommandRejected)
    assert transport.subscriptions["BESTNAVA", Port.COM1] == 10.0
    assert ("SATSINFOA", Port.COM1) in transport.subscriptions
