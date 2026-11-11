"""Check that example summaries do not corrupt JSON output."""

import json
from pathlib import Path

import pytest
from examples.base_station_survey import __main__ as survey
from examples.clock_stability import __main__ as clock
from examples.scintillation_monitor import __main__ as scintillation
from examples.time_transfer import __main__ as time_transfer

from tests.examples._new_api import observation, record
from um982py.messages import Record

FIXTURES = Path(__file__).parents[1] / "fixtures" / "captures"


@pytest.mark.parametrize("destination", ["stdout", "file"])
@pytest.mark.parametrize("example", ["survey", "clock", "scintillation", "time"])
def test_json_output_has_no_duplicate_text(
    example: str,
    destination: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if example == "survey":
        cli = survey
        args = ["--replay", str(FIXTURES / "BESTXYZB.bin")]
    elif example == "time":
        cli = time_transfer
        args = ["--replay", str(FIXTURES / "TIMEB.bin")]
    elif example == "clock":
        cli = clock
        args = ["--frames", "128"]
        records = [
            Record("TIME", (("clock_status", 0), ("clock_offset", i * i * 1e-9)))
            for i in range(128)
        ]
        monkeypatch.setattr(cli, "capture_records", lambda *a, **k: {"TIME": records})
        monkeypatch.setattr(cli, "uniform_interval", lambda *a: 1.0)
    else:
        cli = scintillation
        args = ["--window", "2"]
        records = [record(i, [observation(cn0=40 + i)]) for i in range(4)]
        monkeypatch.setattr(cli, "capture_records", lambda *a, **k: {"RANGE": records})

    path = tmp_path / "report.json"
    if destination == "file":
        args.extend(["--json", str(path)])
    assert cli.main(args) == 0
    output = capsys.readouterr()
    report = json.loads(path.read_text() if destination == "file" else output.out)
    assert report
    assert {
        "survey": "horizontal standard error",
        "clock": "tau ",
        "scintillation": "s4 proxy",
        "time": "gpst ",
    }[example] in output.err
    if destination == "file":
        assert output.out == ""
