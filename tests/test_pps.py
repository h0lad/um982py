import ctypes
import errno
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from um982py import PpsDevice, PpsEdge, missed_pps_edges, pps_clock_offset_ns
from um982py import pps as module

linux_pps = pytest.mark.skipif(
    sys.platform != "linux"
    or platform.machine().lower() not in ("x86_64", "aarch64")
    or ctypes.sizeof(ctypes.c_void_p) != 8,
    reason="requires 64-bit Python on Linux x86-64 or AArch64",
)


def test_edges_compare_explicit_utc_without_float_rounding() -> None:
    utc = datetime(2024, 1, 1, tzinfo=UTC)
    edge = PpsEdge("assert", 1, 1704067200, 123456789)
    assert pps_clock_offset_ns(edge, utc) == 123456789
    assert (
        pps_clock_offset_ns(edge, utc.astimezone(timezone(timedelta(hours=2))))
        == 123456789
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        pps_clock_offset_ns(edge, utc.replace(tzinfo=None))


def test_sequence_gaps_wrap_and_reject_resets() -> None:
    edge = PpsEdge("assert", 2**32 - 2, 1, 0)
    assert missed_pps_edges(edge, PpsEdge("assert", 1, 2, 0)) == 2
    with pytest.raises(ValueError, match="advance or was reset"):
        missed_pps_edges(edge, edge)
    with pytest.raises(ValueError, match="advance or was reset"):
        missed_pps_edges(edge, PpsEdge("assert", 2**32 - 3, 2, 0))
    with pytest.raises(ValueError, match="same polarity"):
        missed_pps_edges(edge, PpsEdge("clear", 1, 2, 0))
    with pytest.raises(ValueError, match="nanoseconds"):
        PpsEdge("assert", 1, 0, 1_000_000_000)


@linux_pps
def test_fetch_reads_snapshots_and_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "pps"
    path.touch()

    def ioctl(fd: int, command: int, buffer: bytearray, mutate: bool) -> None:
        assert fd >= 0 and command == module._PPS_FETCH and mutate
        request = module._KernelFetch.from_buffer(buffer)
        assert (request.timeout.sec, request.timeout.nsec) == (1, 250_000_000)
        request.info.assert_sequence = 42
        request.info.assert_time.sec = 1704067200
        request.info.assert_time.nsec = 123456789
        request.info.current_mode = 3

    monkeypatch.setattr(module, "import_module", lambda _: SimpleNamespace(ioctl=ioctl))
    with PpsDevice(str(path)) as device:
        snapshot = device.fetch(timeout=1.25)
        assert snapshot.assert_edge == PpsEdge("assert", 42, 1704067200, 123456789)
        assert snapshot.clear_edge is None
        assert snapshot.mode == 3
        for timeout in (0, -1, float("inf"), float("nan"), 86401):
            with pytest.raises(ValueError, match="timeout"):
                device.fetch(timeout=timeout)
    device.close()
    with pytest.raises(ValueError, match="closed"):
        device.fetch()


@linux_pps
def test_wrapped_zero_sequence_and_missing_stamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "pps"
    path.touch()

    def ioctl(fd: int, command: int, buffer: bytearray, mutate: bool) -> None:
        request = module._KernelFetch.from_buffer(buffer)
        request.info.assert_time.sec = 1

    monkeypatch.setattr(module, "import_module", lambda _: SimpleNamespace(ioctl=ioctl))
    with PpsDevice(path) as device:
        snapshot = device.fetch()
    assert snapshot.assert_edge == PpsEdge("assert", 0, 1, 0)
    assert snapshot.clear_edge is None


@linux_pps
def test_timeout_propagates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "pps"
    path.touch()

    def ioctl(*args: object) -> None:
        raise TimeoutError(errno.ETIMEDOUT, "PPS timeout")

    monkeypatch.setattr(module, "import_module", lambda _: SimpleNamespace(ioctl=ioctl))
    with PpsDevice(path) as device, pytest.raises(TimeoutError):
        device.fetch()


def test_unsupported_platform_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module.sys, "platform", "win32")
    with pytest.raises(NotImplementedError, match="Linux PPS"):
        PpsDevice(Path("unused"))


def test_kernel_abi_matches_installed_c_headers(tmp_path: Path) -> None:
    cc = shutil.which("cc")
    if (
        sys.platform != "linux"
        or platform.machine() not in ("x86_64", "aarch64")
        or ctypes.sizeof(ctypes.c_void_p) != 8
        or not cc
    ):
        pytest.skip("requires a supported Linux architecture and C compiler")
    if not Path("/usr/include/linux/pps.h").exists():
        pytest.skip("Linux PPS headers unavailable")
    source = tmp_path / "abi.c"
    binary = tmp_path / "abi"
    source.write_text(
        "#include <stdio.h>\n#include <stddef.h>\n#include <sys/ioctl.h>\n"
        "#include <linux/pps.h>\n"
        'int main(void) { printf("%lu %zu %zu %zu %zu\\n", '
        "(unsigned long)PPS_FETCH, sizeof(struct pps_ktime), "
        "sizeof(struct pps_kinfo), sizeof(struct pps_fdata), "
        "offsetof(struct pps_fdata, timeout)); return 0; }\n"
    )
    subprocess.run(
        [cc, str(source), "-o", str(binary)], check=True, capture_output=True
    )
    actual = subprocess.check_output([str(binary)], text=True).split()
    assert list(map(int, actual)) == [
        module._PPS_FETCH,
        ctypes.sizeof(module._KernelTime),
        ctypes.sizeof(module._KernelInfo),
        ctypes.sizeof(module._KernelFetch),
        module._KernelFetch.timeout.offset,
    ]
