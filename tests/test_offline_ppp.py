"""Exercise the offline PPP workflow without network access or a receiver."""

from __future__ import annotations

import gzip
import io
import json
import math
import os
import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest
from examples.offline_ppp import __main__ as ppp
from examples.offline_ppp import solver

from tests.examples._new_api import observation as raw_observation
from tests.examples._new_api import record
from um982py.errors import TransportClosed
from um982py.field_data import file_sha256
from um982py.rinex import export_rinex


def header(content: str, label: str) -> str:
    return f"{content:<60}{label}\n"


def test_record_passes_raw_capture_and_station_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []

    def record(options: list[str]) -> int:
        captured.extend(options)
        return 0

    output = tmp_path / "occupation"
    metadata = tmp_path / "station.json"
    monkeypatch.setattr(ppp, "record_rinex", record)
    monkeypatch.setattr(ppp, "receiver_identity", lambda args: {"firmware": "test"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "offline_ppp",
            "record",
            "--port",
            "/dev/ttyUSB0",
            "--duration",
            "10",
            "--interval",
            "5",
            "--metadata",
            str(metadata),
            "--output-dir",
            str(output),
        ],
    )
    assert ppp.main() == 0
    assert captured[captured.index("--record") + 1] == str(output / "capture.bin")
    assert captured[captured.index("--metadata") + 1] == str(metadata)
    assert captured[captured.index("--frames") + 1] == "3"


def test_segmented_recording_preserves_incomplete_segment_and_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed = False

    def record(options: list[str]) -> int:
        nonlocal completed
        raw = Path(options[options.index("--record") + 1])
        obs = Path(options[options.index("--output") + 1])
        report = Path(options[options.index("--json") + 1])
        duration = float(options[options.index("--duration") + 1])
        raw.write_bytes(b"raw")
        obs.write_text("observations")
        span = duration - 1 if completed else 0
        report.write_text(
            json.dumps(
                {
                    "files": [
                        {"first_epoch_gps_seconds": 0, "last_epoch_gps_seconds": span}
                    ]
                }
            )
        )
        return 0

    output = tmp_path / "station"
    arguments = [
        "offline_ppp",
        "record",
        "--port",
        "/dev/test",
        "--duration",
        "40",
        "--interval",
        "1",
        "--segment-seconds",
        "20",
        "--min-free-mib",
        "0",
        "--output-dir",
        str(output),
    ]
    monkeypatch.setattr(ppp, "record_rinex", record)
    monkeypatch.setattr(ppp, "receiver_identity", lambda args: {"firmware": "test"})
    monkeypatch.setattr(sys, "argv", arguments)
    assert ppp.main() == 1
    assert (output / "segment-000001" / "capture.bin").read_bytes() == b"raw"
    completed = True
    monkeypatch.setattr(sys, "argv", [*arguments, "--resume"])
    assert ppp.main() == 0
    events = [
        json.loads(line)
        for line in (output / "segments.jsonl").read_text().splitlines()
    ]
    assert [event["status"] for event in events] == [
        "started",
        "incomplete",
        "started",
        "complete",
        "started",
        "complete",
    ]
    assert (output / "segment-000003" / "observation.obs").is_file()
    (output / "segment-000002" / "capture.bin").write_bytes(b"modified")
    assert ppp.main() == 1


def test_segmented_recording_retries_disconnect_and_checks_receiver_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def record(options: list[str]) -> int:
        nonlocal attempts
        attempts += 1
        raw = Path(options[options.index("--record") + 1])
        raw.write_bytes(b"partial" if attempts == 1 else b"complete")
        if attempts == 1:
            raise TransportClosed("disconnect")
        Path(options[options.index("--output") + 1]).write_text("observations")
        Path(options[options.index("--json") + 1]).write_text(
            json.dumps(
                {
                    "files": [
                        {"first_epoch_gps_seconds": 0, "last_epoch_gps_seconds": 19}
                    ]
                }
            )
        )
        return 0

    output = tmp_path / "station"
    args = [
        "offline_ppp",
        "record",
        "--port",
        "/dev/test",
        "--duration",
        "20",
        "--interval",
        "1",
        "--segment-seconds",
        "20",
        "--min-free-mib",
        "0",
        "--output-dir",
        str(output),
    ]
    monkeypatch.setattr(ppp, "record_rinex", record)
    monkeypatch.setattr(ppp, "receiver_identity", lambda args: {"firmware": "test"})
    monkeypatch.setattr(ppp.time, "sleep", sleeps.append)
    monkeypatch.setattr(sys, "argv", args)
    assert ppp.main() == 0
    assert sleeps == [1]
    assert (output / "segment-000001" / "capture.bin").read_bytes() == b"partial"
    assert (output / "segment-000002" / "capture.bin").read_bytes() == b"complete"
    assert attempts == 2


def test_segmented_recording_stops_if_receiver_configuration_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identities = iter(({"config": "one"}, {"config": "two"}))

    def record(options: list[str]) -> int:
        Path(options[options.index("--record") + 1]).write_bytes(b"raw")
        Path(options[options.index("--output") + 1]).write_text("observations")
        Path(options[options.index("--json") + 1]).write_text(
            json.dumps(
                {
                    "files": [
                        {"first_epoch_gps_seconds": 0, "last_epoch_gps_seconds": 19}
                    ]
                }
            )
        )
        return 0

    output = tmp_path / "station"
    monkeypatch.setattr(ppp, "record_rinex", record)
    monkeypatch.setattr(ppp, "receiver_identity", lambda args: next(identities))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "offline_ppp",
            "record",
            "--port",
            "/dev/test",
            "--duration",
            "40",
            "--interval",
            "1",
            "--segment-seconds",
            "20",
            "--min-free-mib",
            "0",
            "--output-dir",
            str(output),
        ],
    )
    assert ppp.main() == 1
    assert (output / "segment-000001" / "capture.bin").is_file()
    assert not (output / "segment-000002").exists()


def test_merge_uses_only_verified_complete_segments(tmp_path: Path) -> None:
    session = tmp_path / "session"
    session.mkdir()
    (session / "session.json").write_text(
        json.dumps({"schema": "um982py-offline-ppp-segments-1"})
    )
    events = []
    for index in (1, 2):
        segment = session / f"segment-{index:06d}"
        segment.mkdir()
        raw = segment / "capture.bin"
        obs = segment / "observation.obs"
        raw.write_bytes(b"capture")
        obs.write_text(export_rinex((record(index, [raw_observation()]),)).text)
        events.append(
            {
                "status": "complete",
                "segment": segment.name,
                "requested_seconds": 10,
                "capture_sha256": file_sha256(raw),
                "observation_sha256": file_sha256(obs),
            }
        )
    (session / "segments.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in events)
    )
    output = tmp_path / "merged.obs"
    ppp.merge_segments(session, output)
    report = json.loads((tmp_path / "merged.obs.json").read_text())
    assert report["epochs"] == 2 and report["boundary_phase_resets"] == 1
    (session / "segment-000002" / "capture.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        ppp.merge_segments(session, tmp_path / "untrusted.obs")


@pytest.fixture
def observation(tmp_path: Path) -> Path:
    path = tmp_path / "station.obs"
    path.write_text(
        header(f"{'SERIAL':<20}{'TESTANTENNA     NONE':<20}", "ANT # / TYPE")
        + header(f"{0.0:14.4f}{0.0:14.4f}{0.0:14.4f}", "ANTENNA: DELTA H/E/N")
        + header(f"{'':48}GPS", "TIME OF FIRST OBS")
        + header("", "END OF HEADER")
        + "> 2023 01 01 00 00  0.0000000  0  1\n",
        encoding="ascii",
    )
    return path


def test_download_records_adjacent_days_and_hashes(
    tmp_path: Path, observation: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def response(request: object, timeout: int) -> io.BytesIO:
        assert timeout == 60
        return io.BytesIO(gzip.compress(b"fixture product"))

    monkeypatch.setattr(ppp.urllib.request, "urlopen", response)
    destination = tmp_path / "products"
    ppp.download_products(observation, destination, "final")
    manifest = json.loads((destination / "products.json").read_text())
    assert manifest["gps_dates"] == ["2022-12-31", "2023-01-01", "2023-01-02"]
    assert len(manifest["files"]) == 12
    assert "COD0OPSFIN_20230010000_01D_05M_ORB.SP3.gz" in str(manifest)
    assert "COD0OPSFIN_20230010000_01D_01D_OSB.BIA.gz" in str(manifest)
    assert all(
        file_sha256(destination / f["path"]) == f["sha256"] for f in manifest["files"]
    )
    with pytest.raises(ValueError, match="empty"):
        ppp.download_products(observation, destination, "final")


def test_product_download_retries_transient_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def response(request: object, timeout: int) -> io.BytesIO:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise urllib.error.URLError("temporary failure")
        return io.BytesIO(gzip.compress(b"product"))

    monkeypatch.setattr(ppp.urllib.request, "urlopen", response)
    monkeypatch.setattr(ppp.time, "sleep", sleeps.append)
    output = tmp_path / "product"
    ppp.download_product("https://example.invalid/product.gz", output)
    assert attempts == 2 and sleeps == [0.5]
    assert output.read_bytes() == b"product"


def test_rejects_unknown_time_system_and_old_products(
    observation: Path,
) -> None:
    observation.write_text(observation.read_text().replace("GPS", "UTC"))
    with pytest.raises(ValueError, match="time system"):
        ppp.observation_dates(observation)
    with pytest.raises(ValueError, match="2022-11-27"):
        ppp.product_urls(date(2022, 11, 26), "final")


def test_solve_and_detect_corrupted_product(
    tmp_path: Path, observation: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    products = tmp_path / "products"
    products.mkdir()
    files = []
    for ext in ("sp3", "clk", "nav", "bia"):
        path = products / f"2023001.{ext}"
        path.write_text("fixture")
        files.append({"path": path.name, "sha256": file_sha256(path)})
    (products / "products.json").write_text(
        json.dumps(
            {
                "gps_dates": ["2023-01-01"],
                "files": files,
            }
        )
    )
    antex = tmp_path / "antenna.atx"
    antex.write_text(header("TESTANTENNA     NONE", "TYPE / SERIAL NO"))

    def fake_solver(
        obs: Path, paths: list[Path], calibration: Path, destination: Path
    ) -> dict[str, object]:
        assert obs == observation and calibration == antex
        assert len(paths) == 4 and destination.is_dir()
        return {
            "status": "ppp_output",
            "ppp_epochs": 1,
            "last_ppp_epoch": {"latitude_deg": 78.9, "satellites": 8},
        }

    monkeypatch.setattr(ppp, "process_observations", fake_solver)
    output = tmp_path / "result"
    assert ppp.solve(observation, products, antex, output) == 0
    report = json.loads((output / "report.json").read_text())
    assert report["ppp_epochs"] == 1
    assert report["last_ppp_epoch"]["latitude_deg"] == 78.9
    assert report["last_ppp_epoch"]["satellites"] == 8
    (products / "2023001.sp3").write_text("modified")
    with pytest.raises(ValueError, match="hash mismatch"):
        ppp.solve(observation, products, antex, tmp_path / "result2")


def test_rejects_unrecognised_antenna(tmp_path: Path, observation: Path) -> None:
    antex = tmp_path / "antenna.atx"
    antex.write_text(header("OTHER", "TYPE / SERIAL NO"))
    with pytest.raises(ValueError, match="not found"):
        ppp.verify_antenna(observation, antex)


def test_rejects_unknown_antenna_offset(tmp_path: Path, observation: Path) -> None:
    antex = tmp_path / "antenna.atx"
    antex.write_text(header("TESTANTENNA     NONE", "TYPE / SERIAL NO"))
    observation.write_text(
        observation.read_text().replace(
            header("", "END OF HEADER"),
            header("Antenna delta unknown; zeros are placeholders", "COMMENT")
            + header("", "END OF HEADER"),
        )
    )
    with pytest.raises(ValueError, match="offset is unknown"):
        ppp.verify_antenna(observation, antex)


@pytest.mark.parametrize(
    ("phase_header", "expected"),
    [("", "missing"), ("G", "unknown"), ("G L1C  0.00000", "declared_unverified")],
)
def test_phase_alignment_is_never_claimed_verified(
    observation: Path, phase_header: str, expected: str
) -> None:
    if phase_header:
        observation.write_text(
            observation.read_text().replace(
                header("", "END OF HEADER"),
                header(phase_header, "SYS / PHASE SHIFT") + header("", "END OF HEADER"),
            )
        )
    assert ppp.phase_alignment_status(observation) == expected


def test_missing_python_solver_is_reported(
    tmp_path: Path, observation: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(name: str) -> object:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(solver.importlib, "import_module", unavailable)
    with pytest.raises(ValueError, match=r"offline_ppp/requirements.txt"):
        solver.process_observations(observation, [], tmp_path / "a", tmp_path)


def test_rejects_power_failure_and_unhandled_half_cycle_flags(tmp_path: Path) -> None:
    obs = tmp_path / "event.obs"
    epoch = "> 2023 01 01 00 00 00.0000000  0  1\n"
    obs.write_text(header("", "END OF HEADER") + epoch + "G01" + " " * 14 + "2\n")
    with pytest.raises(ValueError, match="LLI"):
        solver.validate_rinex_flags(obs, [0])
    obs.write_text(header("", "END OF HEADER") + epoch[:31] + "1" + epoch[32:])
    with pytest.raises(ValueError, match="event"):
        solver.validate_rinex_flags(obs, [0])


def test_public_occupation_against_external_ppp_reference(tmp_path: Path) -> None:
    """Compare a two-hour IGS occupation with an independent daily PPP run.

    The optional directory contains station.obs (NYA200NOR 2023-01-01, first
    240 epochs), products/ from the rapid CODE download, and igs20.atx. The
    reference is a 24-hour RTKLIB/IGS-final result, not a surveyed ground truth.
    """
    root = os.environ.get("UM982_PPP_REFERENCE_DIR")
    if not root:
        pytest.skip("set UM982_PPP_REFERENCE_DIR to the public PPP reference files")
    pytest.importorskip("cssrlib")
    root_path = Path(root)
    output = tmp_path / "solution"
    assert (
        ppp.solve(
            root_path / "station.obs",
            root_path / "products",
            root_path / "igs20.atx",
            output,
        )
        == 0
    )
    report = json.loads((output / "report.json").read_text())
    assert report["ppp_epochs"] >= 200
    assert report["epochs_received"] == 240
    assert report["solution_span_seconds"] > 0
    assert report["satellites_used"]["minimum"] >= 6
    assert (
        report["engine_source"]["vcs_info"]["commit_id"]
        == "df0f26332498f1d581109f2ab1caffd68748e18c"
    )
    assert report["last_ppp_epoch"]["ecef_m"] == pytest.approx(
        [1202379.2822, 252474.6887, 6237786.6599], abs=0.5
    )


def test_nya1_against_published_code_network_solution(tmp_path: Path) -> None:
    """Compare 2 h of public observations with CODE's daily network estimate.

    Both use CODE products and NYA1 observations, so this is a published
    reference solution with potentially correlated errors, not ground truth.
    """
    root = os.environ.get("UM982_NYA1_REFERENCE_DIR")
    if not root:
        pytest.skip("set UM982_NYA1_REFERENCE_DIR to prepared NYA1 reference files")
    pytest.importorskip("cssrlib")
    root_path = Path(root)
    output = tmp_path / "solution"
    assert (
        ppp.solve(
            root_path / "station.obs",
            root_path / "products",
            root_path / "antenna.atx",
            output,
        )
        == 0
    )
    report = json.loads((output / "report.json").read_text())
    assert report["ppp_epochs"] >= 200
    reference = [1202433.58536398, 252632.426320401, 6237772.80808920]
    assert math.dist(report["last_ppp_epoch"]["ecef_m"], reference) < 0.25
