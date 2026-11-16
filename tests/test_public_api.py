"""Keep the root small and specialist imports explicit, without legacy aliases."""

import importlib
import subprocess
import sys

import pytest

import um982py

CORE = {
    "AsyncReceiver",
    "Log",
    "Observations",
    "Position",
    "Receiver",
    "Rover",
    "capture_live",
    "decode_message",
    "load_records",
    "record_observations",
}


def test_root_discovery_and_star_import_expose_only_core_workflows() -> None:
    code = """
import sys
import um982py
expected = {
    'AsyncReceiver', 'Log', 'Observations', 'Position', 'Receiver', 'Rover',
    'capture_live', 'decode_message', 'load_records', 'record_observations',
}
assert set(um982py.__all__) == expected
assert {name for name in dir(um982py) if not name.startswith('_')} == expected
assert not any(name.startswith('um982py.') for name in sys.modules)
namespace = {}
exec('from um982py import *', namespace)
assert set(namespace) - {'__builtins__'} == expected
assert not any(name.startswith('um982py.experimental') for name in sys.modules)
assert not {'numpy', 'scipy', 'pyproj', 'georinex'} & sys.modules.keys()
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


@pytest.mark.parametrize(
    "module,names",
    [
        ("antenna", ("antenna_log", "swap_antenna")),
        ("live", ("PositionSession", "PositionSubscription", "PositionUpdate")),
        ("streaming", ("ReceiverStream", "Subscription", "StreamEvent")),
        ("rover_session", ("RoverSession", "RoverSessionHealth", "RoverUpdate")),
        ("rtk_session", ("RtkSession", "RtkHealth")),
        ("geodesy", ("ecef_from_geodetic", "haversine_distance")),
        ("adapters", ("navsatfix", "geojson_feature")),
        ("rtcm", ("decode_rtcm",)),
        ("rinex", ("RinexExport", "RinexMetadata", "export_rinex")),
        ("precise", ("PrecisePoint", "parse_sp3")),
        ("messages.navigation", ("Fix", "Heading", "BestNavigation")),
    ],
)
def test_specialist_apis_stay_in_their_modules_after_import(
    module: str, names: tuple[str, ...]
) -> None:
    specialist = importlib.import_module(f"um982py.{module}")
    for name in names:
        assert getattr(specialist, name) is not None
        assert name not in um982py.__all__
        assert name not in dir(um982py)
        with pytest.raises(AttributeError, match=name):
            getattr(um982py, name)


def test_removed_root_import_has_no_compatibility_fallback() -> None:
    with pytest.raises(ImportError, match="swap_antenna"):
        from um982py import swap_antenna

        assert swap_antenna


def test_unknown_names_still_raise_attribute_error() -> None:
    with pytest.raises(AttributeError, match="not_a_public_api"):
        assert um982py.not_a_public_api


def test_package_namespace_imports_remain_available() -> None:
    from um982py import antenna, capture, commands

    assert commands.Log is um982py.Log
    assert capture.capture_live is um982py.capture_live
    selected = antenna.antenna_log(commands.Log.RANGE, antenna=2)
    assert selected.wire_name(binary=True) == "RANGEHB"
    assert antenna.swap_antenna(selected).wire_name(binary=True) == "RANGEB"
    assert {"antenna_log", "swap_antenna"} <= set(antenna.__all__)
    assert set(um982py.__all__) == CORE
