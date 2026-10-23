"""Receiver port, signal and mask CONFIG commands."""

from dataclasses import dataclass
from typing import Literal

from um982py.commands.core import Command, action, number
from um982py.commands.types import Constellation, NmeaVersion, Parity, Port
from um982py.messages.frames import CommandResponse, Message, Sentence

SIGNAL_GROUP_BANDS: dict[int, str] = {
    0: "Disable the slave antenna",
    1: "BDS B1I/B3I/B1C/B2a/B2b, GPS L1C/A/L2C/L5, GLO G1/G2, "
    "GAL E1/E5a/E5b, QZSS L1C/A/L1S/L2C/L5",
    2: "BDS B1I/B3I/B1C/B2a/B2b, GPS L1C/A/L1C/L2C/L2P(Y)/L5, "
    "GLO G1/G2/G3, GAL E1/E5a/E5b/E6, QZSS L1C/A/L1C/L1S/L2C/L5, NavIC L5",
    3: "BDS B1I/B3I/B2a/B2b-PPP (B1C availability varies), "
    "GPS L1C/A/L2C/L5, GLO G1/G2, GAL E1/E5a/E5b/E6, "
    "QZSS L1C/A/L1C/B/L1S/L2C/L5/L6E/L6D (UM982 master, 20 Hz; firmware dependent)",
    4: "BDS B1I/B2a/B3I, GPS L1C/A/L2C/L5, GLO G1/G2, GAL E1/E5a/E5b, "
    "QZSS L1C/A/L1C/B/L1S/L2C/L5 (firmware dependent)",
    5: "BDS B1I/B2a/B3I, GPS L1C/A/L2C/L2P, GLO G1/G2, GAL E1/E5b, "
    "QZSS L1C/A/L1C/B/L2C (firmware dependent)",
    6: "BDS B1I/B3I, GPS L1C/A/L2C, GAL E1/E5b, "
    "QZSS L1C/A/L1C/B/L2C (UM982 slave, 20 Hz; firmware dependent)",
    7: "BDS B1I/B3I/B1C/B2a/B2b, GPS L1C/A/L2C/L5, GLO G1/G2, "
    "GAL E1/E5a/E5b/E6, QZSS L1C/A/L1C/B/L1S/L2C/L5 (firmware dependent)",
    8: "GPS L1C/A/L2C/L2P/L5, BDS B1I/B3I/B1C/B2a, GAL E1/E5a/E5b, "
    "QZSS L1C/A/L2C/L5 (UM980 50 Hz; firmware dependent)",
    9: "BDS B1I/B3I/B1C/B2a/B2b, GPS L1C/A/L2(Y)/L2C/L5, GLO G1/G2, "
    "GAL E1C/E5A/E5B, QZSS L1C/A/L2C/L5 (UB9A0 50 Hz)",
    10: "BDS B1I/B3I/B1C/B2a/B2b, GPS L1C/A/L2C/L2P/L5, GLO G1/G2, "
    "GAL E1/E5a/E5b/E6, QZSS L1C/A/L1S/L2C/L5/L6E/L6D, L-band "
    "(product and firmware dependent)",
}


@dataclass(frozen=True, slots=True)
class SignalGroup:
    """The configured master/slave frequency combination (SIGNALGROUP)."""

    master: int
    slave: int

    @property
    def master_bands(self) -> str:
        return SIGNAL_GROUP_BANDS.get(self.master, f"unknown group {self.master}")

    @property
    def slave_bands(self) -> str:
        return SIGNAL_GROUP_BANDS.get(self.slave, f"unknown group {self.slave}")

    @classmethod
    def from_message(cls, message: Message) -> "SignalGroup":
        if not (
            isinstance(message, Sentence)
            and message.name == "CONFIG"
            and message.fields[:1] == ("SIGNALGROUP",)
        ):
            raise ValueError("Not a SIGNALGROUP configuration record")
        tokens = message.fields[1].split()
        if len(tokens) < 3 or tokens[:2] != ["CONFIG", "SIGNALGROUP"]:
            raise ValueError("Malformed SIGNALGROUP configuration record")
        master = int(tokens[2])
        slave = int(tokens[3]) if len(tokens) > 3 else 0
        return cls(master, slave)


def serial_port(
    port: Port,
    baudrate: int,
    *,
    parity: Parity = Parity.NONE,
    stop_bits: Literal[1, 2] = 1,
) -> Command[CommandResponse]:
    if baudrate not in (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600):
        raise ValueError("Unsupported documented baud rate")
    if type(stop_bits) is not int or stop_bits not in (1, 2):
        raise ValueError("stop_bits must be 1 or 2")
    return action(
        f"CONFIG {Port(port).value} {baudrate} 8 {Parity(parity).value} {stop_bits}"
    )


def nmea_version(version: NmeaVersion) -> Command[CommandResponse]:
    return action(f"CONFIG NMEA0183 {NmeaVersion(version).value}")


def signal_group(
    master: int,
    slave: int | None = None,
    *,
    product: Literal["UM982", "UM980", "UB9A0"] = "UM982",
) -> Command[CommandResponse]:
    if type(master) is not int or (slave is not None and type(slave) is not int):
        raise ValueError("Signal group numbers must be integers")
    if product != "UM982":
        allowed = {"UM980": (1, 2, 8), "UB9A0": (2, 9)}
        if (
            product not in allowed
            or master not in allowed[product]
            or slave is not None
        ):
            raise ValueError("Unsupported single-antenna signal group")
        return action(f"CONFIG SIGNALGROUP {master}")
    selected_slave = 0 if slave is None else slave
    if (master, selected_slave) not in ((4, 5), (3, 6), (5, 0), (7, 0)):
        raise ValueError("Unsupported documented UM982 signal group pair")
    suffix = f" {selected_slave}" if slave is not None else ""
    return action(f"CONFIG SIGNALGROUP {master}{suffix}")


def receiver_input_type(
    port: Literal["COM2", "COM3"], mode: Literal["AUTO", "NONE", "RTCM"]
) -> Command[CommandResponse]:
    """Build an input-type command for COM2 or COM3, to be sent on COM1."""
    if port not in ("COM2", "COM3") or mode not in ("AUTO", "NONE", "RTCM"):
        raise ValueError("RXTYPE requires COM2 or COM3 and AUTO, NONE or RTCM")
    return action(f"CONFIG RXTYPE {port} {mode}")


def one_satellite_tracking(*, enabled: bool = True) -> Command[CommandResponse]:
    """Configure the receiver-level one-satellite tracking mode."""
    return action(f"CONFIG ONESATTRK {'ENABLE' if enabled else 'DISABLE'}")


def elevation_mask(degrees: float) -> Command[CommandResponse]:
    return action(f"MASK {number(degrees, -90, 90)}")


def constellation(
    system: Constellation, *, enabled: bool = True
) -> Command[CommandResponse]:
    return action(f"{'UNMASK' if enabled else 'MASK'} {Constellation(system).value}")


def command_checksums(*, enabled: bool) -> Command[CommandResponse]:
    return action(f"CONFIG CMDFORMAT {int(enabled)}")


def current_signal_group() -> Command[SignalGroup]:
    """Read the active frequency combination."""

    def matches(message: Message) -> bool:
        return (
            isinstance(message, Sentence)
            and message.name == "CONFIG"
            and message.fields[:1] == ("SIGNALGROUP",)
        )

    return Command("CONFIG", matches, SignalGroup.from_message)
