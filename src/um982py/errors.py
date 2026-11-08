"""The exception hierarchy for receiver and protocol errors."""


class UM982Error(Exception):
    """Base class for receiver and protocol errors."""


class ProtocolError(UM982Error):
    pass


class ChecksumError(ProtocolError):
    pass


class TransportError(UM982Error):
    pass


class TransportClosed(TransportError):
    pass


class RecordingError(UM982Error):
    """The capture sink could not preserve received bytes."""


class ResponseTimeout(UM982Error, TimeoutError):
    pass


class CommandRejected(UM982Error):
    def __init__(self, command: str, response: str) -> None:
        self.command = command
        self.response = response
        super().__init__(f"{command}: {response}")


class BufferOverflow(UM982Error):
    pass
