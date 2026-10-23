"""Receiver query commands."""

from um982py.commands.core import Command
from um982py.commands.logging import request
from um982py.messages.frames import AsciiMessage, Message, Sentence
from um982py.messages.navigation import BestNavigation, Fix, Heading
from um982py.messages.version import Version


def version(*, binary: bool = False) -> Command[Version]:
    query = request("VERSIONB" if binary else "VERSIONA", message_id=37)
    return Command(query.text, query.matches, Version.from_message)


def best_navigation(
    *, binary: bool = False, antenna: int = 1
) -> Command[BestNavigation]:
    if antenna not in (1, 2):
        raise ValueError("antenna must be 1 or 2")
    name = "BESTNAVH" if antenna == 2 else "BESTNAV"
    query = request(name + ("B" if binary else "A"), message_id=2117 + antenna)
    return Command(query.text, query.matches, BestNavigation.from_message)


def fix(*, antenna: int = 1) -> Command[Fix]:
    if antenna not in (1, 2):
        raise ValueError("antenna must be 1 or 2")
    query = request("GPGGAH" if antenna == 2 else "GPGGA")
    return Command(query.text, query.matches, Fix.from_message)


def heading() -> Command[Heading]:
    query = request("GPTHS")
    return Command(query.text, query.matches, Heading.from_message)


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
