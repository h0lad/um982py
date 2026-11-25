from um982py.commands.core import Command
from um982py.commands.logging import request
from um982py.messages.frames import AsciiMessage, Message, Sentence
from um982py.messages.navigation import BestNavigation, Fix, Heading
from um982py.messages.version import Version
from um982py.receiver_models import (
    FirmwareInfo,
    LogList,
    PerformanceStatus,
    ReceiverSystemStatus,
)


def version(*, binary: bool = False) -> Command[Version]:
    return request("VERSIONB" if binary else "VERSIONA", message_id=37).decoded_with(
        Version.from_message
    )


def best_navigation(
    *, binary: bool = False, antenna: int = 1
) -> Command[BestNavigation]:
    if type(antenna) is not int or antenna not in (1, 2):
        raise ValueError("antenna must be 1 or 2")
    name = "BESTNAVH" if antenna == 2 else "BESTNAV"
    return request(
        name + ("B" if binary else "A"), message_id=2117 + antenna
    ).decoded_with(BestNavigation.from_message)


def fix(*, antenna: int = 1) -> Command[Fix]:
    if type(antenna) is not int or antenna not in (1, 2):
        raise ValueError("antenna must be 1 or 2")
    return request("GPGGAH" if antenna == 2 else "GPGGA").decoded_with(Fix.from_message)


def heading() -> Command[Heading]:
    return request("GPTHS").decoded_with(Heading.from_message)


def mode() -> Command[Message]:
    return Command(
        "MODE",
        lambda message: isinstance(message, AsciiMessage) and message.name == "MODE",
        lambda message: message,
    )


def configuration() -> Command[Message]:
    return Command(
        "CONFIG",
        lambda message: isinstance(message, Sentence) and message.name == "CONFIG",
        lambda message: message,
    )


def masks() -> Command[Message]:
    return Command(
        "MASK",
        lambda message: (
            isinstance(message, Sentence)
            and message.name == "CONFIG"
            and message.fields[:1] == ("MASK",)
        ),
        lambda message: message,
    )


def firmware_info(*, binary: bool = False) -> Command[FirmwareInfo]:
    return request("FWINFOB" if binary else "FWINFOA", message_id=11277).decoded_with(
        FirmwareInfo.from_message
    )


def log_list() -> Command[LogList]:
    return request("LOGLISTA").decoded_with(LogList.from_message)


def performance_status() -> Command[PerformanceStatus]:
    """Query RTOS task CPU utilization and NVM loop counters via PERFSTATA."""
    return request("PERFSTATA").decoded_with(PerformanceStatus.from_message)


def receiver_system_status() -> Command[ReceiverSystemStatus]:
    """Query hardware clock frequencies and component builds via RXSTATUSA."""
    return request("RXSTATUSA").decoded_with(ReceiverSystemStatus.from_message)
