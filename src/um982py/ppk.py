"""Run RTKLIB post-processing with explicit inputs and a provenance record."""

import hashlib
import json
import math
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal


class PostProcessingError(RuntimeError):
    """The external solver failed to produce a usable solution."""


@dataclass(frozen=True, slots=True)
class PpkResult:
    solution: Path
    manifest: Path
    epochs: int
    quality_counts: tuple[tuple[int, int], ...]


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _rinex(path: Path, allowed: str) -> None:
    with path.open("rb") as stream:
        header = stream.read(1024 * 1024)
    try:
        lines = header.decode("ascii").splitlines()
        first = lines[0]
        version = float(first[:9])
    except (UnicodeDecodeError, IndexError, ValueError) as error:
        raise ValueError(f"invalid RINEX header: {path}") from error
    if (
        not 2 <= version < 4
        or first[20:21] not in allowed
        or first[60:80].strip() != "RINEX VERSION / TYPE"
        or not any(line[60:80].strip() == "END OF HEADER" for line in lines)
    ):
        raise ValueError(f"invalid or unsupported RINEX header: {path}")


def _solutions(path: Path) -> tuple[int, tuple[tuple[int, int], ...]]:
    counts: dict[int, int] = {}
    with path.open(encoding="ascii") as stream:
        for line in stream:
            if not line.strip() or line.startswith("%"):
                continue
            fields = line.split()
            try:
                datetime.strptime(fields[0] + " " + fields[1], "%Y/%m/%d %H:%M:%S.%f")
                latitude, longitude, height = map(float, fields[2:5])
                quality, satellites = int(fields[5]), int(fields[6])
                if (
                    not all(
                        math.isfinite(value) for value in (latitude, longitude, height)
                    )
                    or not -90 <= latitude <= 90
                    or not -180 <= longitude <= 180
                    or quality < 1
                    or satellites < 0
                ):
                    raise ValueError
            except (IndexError, ValueError) as error:
                raise PostProcessingError("invalid RTKLIB solution record") from error
            counts[quality] = counts.get(quality, 0) + 1
    if not counts:
        raise PostProcessingError("RTKLIB produced no position solutions")
    return sum(counts.values()), tuple(sorted(counts.items()))


def run_ppk(
    rover: str | os.PathLike[str],
    base: str | os.PathLike[str],
    navigation: Sequence[str | os.PathLike[str]],
    output_dir: str | os.PathLike[str],
    *,
    base_ecef: tuple[float, float, float],
    reference_frame: str,
    reference_epoch: float | None = None,
    executable: str = "rnx2rtkp",
    mode: Literal["kinematic", "static"] = "kinematic",
    frequencies: int = 2,
    elevation_mask: float = 15.0,
    timeout: float = 3600.0,
) -> PpkResult:
    """Run RTKLIB on RINEX observations with an explicit base ECEF position.

    Write the solver output and logs to a new directory. The manifest records
    input hashes and options. Solver quality codes, reference frame and epoch
    stay as supplied. Match the frame and epoch to the observation metadata.
    """
    if len(base_ecef) != 3 or not all(math.isfinite(v) for v in base_ecef):
        raise ValueError("base_ecef must contain three finite coordinates")
    if not 5_000_000 <= math.hypot(*base_ecef) <= 8_000_000:
        raise ValueError("base_ecef must be an Earth-surface ECEF position in metres")
    if not reference_frame.strip():
        raise ValueError("reference_frame is required")
    if reference_epoch is not None and not math.isfinite(reference_epoch):
        raise ValueError("reference_epoch must be finite")
    if mode not in ("kinematic", "static") or frequencies not in (1, 2, 3):
        raise ValueError("unsupported mode or frequency count")
    if not math.isfinite(elevation_mask) or not 0 <= elevation_mask < 90:
        raise ValueError("elevation_mask must be in [0, 90) degrees")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if not navigation or len(navigation) > 14:
        raise ValueError("one to fourteen navigation files are required")
    resolved = [Path(path).resolve(strict=True) for path in (rover, base, *navigation)]
    for path, kind in zip(
        resolved, ("O", "O", *("NGHJL" for _ in navigation)), strict=True
    ):
        _rinex(path, kind)
    solver_name = shutil.which(executable)
    if solver_name is None:
        raise FileNotFoundError(f"RTKLIB executable not found: {executable}")
    solver = Path(solver_name).resolve(strict=True)
    input_hashes = {str(path): _sha256(path) for path in resolved}
    executable_hash = _sha256(solver)
    directory = Path(output_dir).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    solution = directory / "solution.pos"
    manifest_path = directory / "run.json"
    command = [
        str(solver),
        "-p",
        "2" if mode == "kinematic" else "3",
        "-f",
        str(frequencies),
        "-m",
        str(elevation_mask),
        "-t",
        "-r",
        *(format(value, ".15g") for value in base_ecef),
        "-o",
        str(solution),
        *(str(path) for path in resolved),
    ]
    manifest: dict[str, object] = {
        "schema": "um982py-ppk-1",
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "command": command,
        "executable_sha256": executable_hash,
        "input_sha256": input_hashes,
        "base_ecef_m": base_ecef,
        "reference_frame": reference_frame,
        "reference_epoch": reference_epoch,
    }

    def save() -> None:
        temporary = directory / "run.json.tmp"
        temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)

    save()
    try:
        with (
            (directory / "stdout.log").open("wb") as stdout,
            (directory / "stderr.log").open("wb") as stderr,
        ):
            completed = subprocess.run(  # noqa: S603
                command,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                timeout=timeout,
                check=False,
            )
        manifest["returncode"] = completed.returncode
        if completed.returncode != 0:
            raise PostProcessingError(
                f"RTKLIB exited with status {completed.returncode}"
            )
        if not solution.is_file():
            raise PostProcessingError("RTKLIB did not create a solution file")
        if any(_sha256(path) != input_hashes[str(path)] for path in resolved):
            raise PostProcessingError("a RINEX input changed during processing")
        if _sha256(solver) != executable_hash:
            raise PostProcessingError("RTKLIB executable changed during processing")
        epochs, quality_counts = _solutions(solution)
    except Exception as error:
        manifest.update(
            status="failed", error=str(error), ended_at=datetime.now(UTC).isoformat()
        )
        save()
        raise
    manifest.update(
        status="complete",
        ended_at=datetime.now(UTC).isoformat(),
        solution_sha256=_sha256(solution),
        epochs=epochs,
        quality_counts=dict(quality_counts),
    )
    save()
    return PpkResult(solution, manifest_path, epochs, quality_counts)
