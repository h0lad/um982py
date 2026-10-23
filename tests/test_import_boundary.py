"""Public imports should not require experimental receiver features."""

import subprocess
import sys


def test_core_receiver_api_can_load_without_experimental_modules() -> None:
    code = """
import sys
import um982py
assert not any(name.startswith('um982py.') for name in sys.modules)
from um982py import FirmwareLog, Receiver, ReceiverState, capture_live
assert FirmwareLog.RANGE.value == 'RANGE'
assert Receiver and ReceiverState and capture_live
assert not any(name.startswith('um982py.experimental') for name in sys.modules)
from um982py.experimental import FirmwareLog as ExtendedFirmwareLog
assert FirmwareLog is ExtendedFirmwareLog
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)
