"""Public imports should not require experimental receiver features."""

import importlib.util
import subprocess
import sys
from pathlib import Path


def test_core_receiver_api_can_load_without_experimental_modules() -> None:
    code = """
import sys
import um982py
assert not any(name.startswith('um982py.') for name in sys.modules)
from um982py import (
    BestNavigation, Log, Fix, Heading, Receiver,
    RinexMetadata, capture_live,
)
assert Log.RANGE.value == 'RANGE'
assert Receiver and capture_live
assert BestNavigation and Fix and Heading and Log and RinexMetadata
assert not any(name.startswith('um982py.experimental') for name in sys.modules)
from um982py.commands import Log as LogCatalog
assert Log is LogCatalog
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


def test_receiver_loads_log_layouts_only_when_decoding_a_log() -> None:
    code = """
import sys
from pathlib import Path
from um982py import Log, Receiver
from um982py.protocol.ascii import parse_ascii

assert Receiver
assert 'um982py.messages.layouts' not in sys.modules
message = parse_ascii(Path(sys.argv[1]).read_bytes())
assert Log.BESTNAV.decode(message).name == 'BESTNAV'
assert 'um982py.messages.layouts' in sys.modules
"""
    fixture = Path(__file__).parent / "fixtures/bodies/BESTNAVA.bin"
    subprocess.run([sys.executable, "-c", code, str(fixture)], check=True, timeout=10)


def test_rtcm_decoder_loads_only_rtcm_layouts() -> None:
    code = """
import sys
from um982py import decode_rtcm
assert decode_rtcm
assert 'um982py.messages.layouts.rtcm' in sys.modules
assert 'um982py.messages.layouts.navigation' not in sys.modules
assert 'um982py.messages.layouts.status' not in sys.modules
from um982py.messages.layouts import LAYOUTS
assert 'BESTNAV' in LAYOUTS
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


def test_removed_compatibility_imports_are_not_exposed() -> None:
    import um982py
    import um982py.capture
    import um982py.experimental

    assert not hasattr(um982py, "FirmwareLog")
    assert not hasattr(um982py, "gnss_range_samples")
    assert importlib.util.find_spec("um982py.logs") is None
    assert importlib.util.find_spec("um982py.messages.rtcm_layouts") is None

    for name in ("capture_logs", "capture_records", "open_receiver", "capture_log"):
        assert not hasattr(um982py, name)
        assert not hasattr(um982py.capture, name)
    for name in ("FirmwareLog", "LogList", "firmware_info"):
        assert not hasattr(um982py.experimental, name)
    for name in ("logs", "layouts", "models", "diagnostics", "navigation", "b2b"):
        assert importlib.util.find_spec(f"um982py.experimental.{name}") is None


def test_one_log_catalogue_covers_documented_and_extended_logs() -> None:
    from um982py import Log
    from um982py.commands.catalog import LOGS
    from um982py.commands.extended import EXTENDED_LOGS

    assert set(LOGS).isdisjoint(EXTENDED_LOGS)
    assert {log.value for log in Log} == set(LOGS) | set(EXTENDED_LOGS)
    assert Log.RANGE.definition.binary_command == "RANGEB"
    assert Log.BESTNAV.definition.binary_command == "BESTNAVB"
