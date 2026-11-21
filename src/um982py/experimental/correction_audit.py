"""Read correction and solution diagnostics in transcript order."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from um982py.commands import Log
from um982py.experimental.rtk_data import RtkData, decode_rtk_data
from um982py.experimental.velocity_data import VelocityData, decode_velocity_data
from um982py.messages import AsciiMessage, BinaryMessage, Message, Record, RtcmMessage
from um982py.rtcm import decode_rtcm

CORRECTION_AUDIT_LOGS = (Log.RTCM1032, Log.BASESATS, Log.SSR1ORBIT, Log.SSR1CLOCK)
_LOGS_BY_ID = {log.definition.message_id: log for log in CORRECTION_AUDIT_LOGS}
_LOGS_BY_ASCII = {log.wire_name(): log for log in CORRECTION_AUDIT_LOGS}


@dataclass(frozen=True, slots=True)
class CorrectionAuditFrame:
    """A selected frame and its original zero-based position in the stream."""

    frame_index: int
    data: Record | RtkData | VelocityData


def iter_correction_audit(
    messages: Iterable[Message],
) -> Iterator[CorrectionAuditFrame]:
    """Read RTCM input and receiver diagnostics from a mixed transcript.

    The caller supplies the capture order. Each decoded object retains its
    original message and any native time fields.
    """
    for index, message in enumerate(messages):
        if isinstance(message, RtcmMessage):
            yield CorrectionAuditFrame(index, decode_rtcm(message))
        elif isinstance(message, BinaryMessage):
            message_id = message.header.message_id
            if message_id in (215, 2027, 6007):
                yield CorrectionAuditFrame(index, decode_rtk_data(message))
            elif message_id == 95:
                yield CorrectionAuditFrame(index, decode_velocity_data(message))
            elif (log := _LOGS_BY_ID.get(message_id)) is not None:
                yield CorrectionAuditFrame(index, log.decode(message))
        elif (
            isinstance(message, AsciiMessage)
            and (log := _LOGS_BY_ASCII.get(message.name.upper())) is not None
        ):
            yield CorrectionAuditFrame(index, log.decode(message))
