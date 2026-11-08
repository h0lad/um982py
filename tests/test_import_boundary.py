"""Public imports should not require experimental receiver features."""

import importlib.util
import subprocess
import sys


def test_core_receiver_api_can_load_without_experimental_modules() -> None:
    code = """
import sys
import um982py
assert not any(name.startswith('um982py.') for name in sys.modules)
from um982py import (
    BestNavigation, FirmwareLog, Fix, Heading, Log, Receiver, ReceiverState,
    RinexMetadata, capture_live,
)
assert FirmwareLog.RANGE.value == 'RANGE'
assert Receiver and ReceiverState and capture_live
assert BestNavigation and Fix and Heading and Log and RinexMetadata
assert not any(name.startswith('um982py.experimental') for name in sys.modules)
from um982py.logs import FirmwareLog as LogCatalog
assert FirmwareLog is LogCatalog
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


def test_removed_compatibility_imports_are_not_exposed() -> None:
    import um982py
    import um982py.capture
    import um982py.experimental

    for name in ("capture_logs", "capture_records", "open_receiver", "capture_log"):
        assert not hasattr(um982py, name)
        assert not hasattr(um982py.capture, name)
    for name in ("FirmwareLog", "LogList", "firmware_info"):
        assert not hasattr(um982py.experimental, name)
    for name in ("logs", "layouts", "models", "diagnostics", "navigation", "b2b"):
        assert importlib.util.find_spec(f"um982py.experimental.{name}") is None
