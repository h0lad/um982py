from struct import pack

import pytest

from um982py.errors import ProtocolError
from um982py.experimental import (
    decode_matched_solution,
    matched_solution_output,
    matched_solution_read,
    matched_solution_stop,
)
from um982py.messages import BinaryHeader, BinaryMessage


def message(payload: bytes, message_id: int = 2020) -> BinaryMessage:
    header = BinaryHeader(0, message_id, len(payload), 0, 0, 2300, 123000, 0, 0, 0, 0)
    return BinaryMessage(header, payload, b"")


def test_decodes_neutral_fields_and_preserves_unknown_codes() -> None:
    payload = (
        bytes(36)
        + pack("<I", 1)
        + pack("<HHIdIdId", 14, 0, 5, 648.5, 4, -3.5, 999, 0.0)
    )
    result = decode_matched_solution(message(payload))
    assert result.satellites[0].satellite_id == 14
    assert result.satellites[0].status_codes == (5, 4, 999)
    assert result.satellites[0].status_labels == ("AMB_L1_FLOAT", "AMB_L2_FLOAT", None)
    assert result.satellites[0].values == (648.5, -3.5, 0.0)
    assert matched_solution_read().text == "MATCHEDSOLUTIONB"
    assert matched_solution_output().text == "MATCHEDSOLUTIONB ONCHANGED"
    assert matched_solution_stop().text == "UNLOG MATCHEDSOLUTIONB"


@pytest.mark.parametrize(
    "payload", [b"", bytes(36) + pack("<I", 1), bytes(36) + pack("<I", 81)]
)
def test_rejects_invalid_lengths_and_counts(payload: bytes) -> None:
    with pytest.raises(ProtocolError):
        decode_matched_solution(message(payload))


def test_rejects_wrong_message_and_nonfinite_values() -> None:
    with pytest.raises(ProtocolError, match="message ID"):
        decode_matched_solution(message(bytes(40), 1))
    payload = (
        bytes(36) + pack("<I", 1) + pack("<HHIdIdId", 1, 0, 0, float("nan"), 0, 0, 0, 0)
    )
    with pytest.raises(ProtocolError, match="Non-finite"):
        decode_matched_solution(message(payload))
