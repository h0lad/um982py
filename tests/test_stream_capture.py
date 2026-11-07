from pathlib import Path

import pytest

from conftest import SubscriptionTransport
from um982py.capture import iter_frames
from um982py.commands.types import Port
from um982py.experimental import FirmwareLog
from um982py.receiver import Receiver
from um982py.stream_capture import EpochTracker, iter_decoded_records, iter_live_records


def test_epoch_tracker_flags_gaps_and_duplicates() -> None:
    tracker = EpochTracker(expected_interval_s=1)
    assert tracker.observe(10) is None
    assert tracker.observe(11) is None
    assert tracker.observe(13).kind == "gap"  # type: ignore[union-attr]
    assert tracker.observe(13).kind == "non_increasing"  # type: ignore[union-attr]
    with pytest.raises(ValueError):
        tracker.observe(float("nan"))


def test_replay_decodes_lazily() -> None:
    path = Path("tests/fixtures/captures/RANGEB.bin")
    records = iter_decoded_records(iter_frames(path), [FirmwareLog.RANGE])
    name, record = next(records)
    assert name == record.name == "RANGE"
    records.close()


def test_stopping_live_iterator_restores_subscriptions() -> None:
    frame = Path("tests/fixtures/captures/RANGEB.bin").read_bytes()

    class StreamingTransport(SubscriptionTransport):
        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending and ("RANGEB", Port.COM1) in self.subscriptions:
                self.pending.extend(frame)
            return super().read(size, timeout)

    transport = StreamingTransport()
    with Receiver(transport, timeout=1) as receiver:
        records = iter_live_records(receiver, [FirmwareLog.RANGE], duration=5)
        assert next(records)[0] == "RANGE"
        records.close()
        assert transport.subscriptions == {}
