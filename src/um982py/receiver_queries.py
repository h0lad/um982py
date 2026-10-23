"""Extended diagnostic queries."""

from um982py.commands.core import Command
from um982py.commands.logging import request
from um982py.receiver_models import (
    FirmwareInfo,
    LogList,
    PerformanceStatus,
    ReceiverSystemStatus,
)


def firmware_info(*, binary: bool = False) -> Command[FirmwareInfo]:
    query = request("FWINFOB" if binary else "FWINFOA", message_id=11277)
    return Command(query.text, query.matches, FirmwareInfo.from_message)


def log_list() -> Command[LogList]:
    query = request("LOGLISTA")
    return Command(query.text, query.matches, LogList.from_message)


def performance_status() -> Command[PerformanceStatus]:
    """Query RTOS task CPU utilization and NVM loop counters via PERFSTATA."""
    query = request("PERFSTATA")
    return Command(query.text, query.matches, PerformanceStatus.from_message)


def receiver_system_status() -> Command[ReceiverSystemStatus]:
    """Query hardware clock frequencies and component builds via RXSTATUSA."""
    query = request("RXSTATUSA")
    return Command(query.text, query.matches, ReceiverSystemStatus.from_message)
