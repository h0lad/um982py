from pathlib import Path
from typing import Self

import pytest
from examples.time_transfer import pps

from um982py import PpsEdge, PpsSnapshot


def test_example_reports_snapshots(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class FakeDevice:
        def __init__(self, path: Path) -> None:
            assert path == Path("/dev/test-pps")

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def fetch(self, *, timeout: float) -> PpsSnapshot:
            assert timeout == 1.5
            return PpsSnapshot(PpsEdge("assert", 3, 17, 20), None, 1)

    monkeypatch.setattr(pps, "PpsDevice", FakeDevice)
    assert (
        pps.main(["--device", "/dev/test-pps", "--timeout", "1.5", "--count", "1"]) == 0
    )
    assert (
        capsys.readouterr().out
        == "assert seq=3 realtime=17.000000020; clear unavailable\n"
    )
