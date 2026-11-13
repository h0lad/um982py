from pathlib import Path

import pytest

from conftest import SubscriptionTransport
from um982py import (
    InterruptedCapture,
    Log,
    Observations,
    Receiver,
    load_records,
    record_observations,
)
from um982py.antenna import AntennaLog
from um982py.commands.types import Port
from um982py.messages import Record


def test_replayed_observations_provide_quality_and_rinex() -> None:
    path = Path(__file__).parent / "fixtures/captures-live/RANGEA.bin"
    observations = Observations(load_records(path, Log.RANGE))
    assert observations.quality().epochs == 26
    series = observations.signals(systems=(0,), signals=(0,))
    assert series
    assert all(key.system == 0 and key.signal == 0 for key in series)
    assert all(
        sample.key == key for key, samples in series.items() for sample in samples
    )
    exported = observations.to_rinex(marker_name="FIELD01")
    assert exported.epochs == 26
    assert "FIELD01" in exported.text
    assert exported.omitted["unverified_l2c_component"] == 104


def test_record_observations_restores_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [0.0]
    data = (Path(__file__).parent / "fixtures/captures-live/RANGEA.bin").read_bytes()

    class Transport(SubscriptionTransport):
        def read(self, size: int, timeout: float) -> bytes:
            if not self.pending:
                clock[0] += timeout
            return super().read(size, timeout)

    transport = Transport()
    transport.after_write["RANGEB 1"] = data
    monkeypatch.setattr("um982py.capture.monotonic", lambda: clock[0])
    monkeypatch.setattr("um982py.receiver.monotonic", lambda: clock[0])
    receiver = Receiver(transport, timeout=1)
    observations = record_observations(receiver, duration=2, frames=2)
    assert len(observations.records) == 2
    assert ("RANGEB", Port.COM1) not in transport.subscriptions
    assert not transport.closed
    with pytest.raises(ValueError, match="log must"):
        record_observations(receiver, duration=1, log=Log.BESTNAV)
    with pytest.raises(ValueError, match="log must"):
        record_observations(receiver, duration=1, log="RANGE")  # type: ignore[arg-type]
    receiver.close()


def test_record_observations_selects_secondary_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = []

    def capture(
        receiver: object, log: object, **kwargs: object
    ) -> dict[str, tuple[Record, ...]]:
        selected.append((log, kwargs))
        return {"OBSVM": ()}

    monkeypatch.setattr("um982py.observations.capture_live", capture)
    observations = record_observations(
        None,
        duration=5,
        rate_hz=2,
        antenna=2,
        log=Log.OBSVM,  # type: ignore[arg-type]
    )
    assert observations.records == ()
    assert isinstance(selected[0][0], AntennaLog)
    assert selected[0][0].wire is Log.OBSVH
    assert selected[0][1]["rate_hz"] == 2


def test_interrupted_recording_preserves_partial_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = Path(__file__).parent / "fixtures/captures-live/RANGEA.bin"
    partial = load_records(path, Log.RANGE)

    def interrupted(*args: object, **kwargs: object) -> None:
        raise InterruptedCapture({"RANGE": partial})

    monkeypatch.setattr("um982py.observations.capture_live", interrupted)
    with pytest.raises(InterruptedCapture) as caught:
        record_observations(None, duration=5)  # type: ignore[arg-type]
    assert Observations(caught.value.records["RANGE"]).to_rinex().epochs == 26
