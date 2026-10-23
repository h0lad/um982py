"""Check that incomplete MSM4 observations cannot make the caster ready."""

import pytest
from examples.ntrip_server.caster import Hub, Limits
from examples.ntrip_server.station import Station

from tests.examples.test_ntrip_server import coordinate_frame, frame
from tests.examples.test_ntrip_server import station as station
from um982py.errors import ProtocolError


@pytest.mark.parametrize("kind", (1074, 1094, 1124))
def test_truncated_msm_observations_do_not_make_station_ready(
    station: Station, kind: int
) -> None:
    hub = Hub(station, Limits())
    hub.publish(coordinate_frame(station))
    # One satellite, one signal and one active cell require 236 bits.
    size = 30
    value = (kind << (size * 8 - 12)) | (station.station_id << (size * 8 - 24))
    for bit in (73, 137, 169):
        value |= 1 << (size * 8 - bit - 1)
    payload = value.to_bytes(size, "big")
    with pytest.raises(ProtocolError, match="observations are truncated"):
        hub.publish(frame(payload[:-1]))
    assert not hub.is_ready
    hub.publish(frame(payload))
    assert hub.is_ready


def test_truncated_msm_header_is_rejected(station: Station) -> None:
    payload = ((1094 << 12) | station.station_id).to_bytes(3, "big")
    with pytest.raises(ProtocolError, match="header is truncated"):
        station.validate_frame(frame(payload))
