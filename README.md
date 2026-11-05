# What's this?

This is a Python (3.12+) library for the Unicore UM982 GNSS receiver.

Most likely quite a few features will also work the the UM960 and UM980. This is untested.


## Usage

The CLI accepts a serial port or a transparent TCP-to-UART gateway:

```bash
um982py --port /dev/ttyUSB0 --baud 921600 version
um982py --port tcp://192.0.2.10:4001 doctor
```
##  Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m mypy
python -m pytest
```

## Examples

### Monitor position and fix quality

```python
from time import sleep

from um982py import Receiver, record_epoch, solution_from_record
from um982py.commands import Log

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    for _ in range(60):
        position = receiver.read_log(Log.BESTNAV)
        quality = solution_from_record(record_epoch(position), position)
        if quality.is_available:
            print(
                f"{position.real('lat'):.9f}, {position.real('lon'):.9f} | "
                f"receiver std (N/E/up): {position.real('lat_std'):.3f}/"
                f"{position.real('lon_std'):.3f}/{position.real('hgt_std'):.3f} m | "
                f"{quality.position_label} | {quality.satellites_used} satellites | "
                f"fresh RTK: {quality.fresh_fixed}",
                flush=True,
            )
        else:
            print(f"Waiting for a position: {quality.solution_label}", flush=True)
        sleep(1)
```

The reported standard deviations are receiver estimates, not measured errors against
an independent reference. Latitude and longitude standard deviations are in metres.

### Read vehicle heading from two antennas

```python
from um982py import Receiver

# Two rigidly mounted antennas; set the measured baseline-to-vehicle offset.
mounting_offset_deg = 0.0
with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    heading = receiver.heading()

if heading.valid:
    vehicle_heading = (heading.degrees + mounting_offset_deg) % 360
    print(f"Heading: {vehicle_heading:.1f}° clockwise from true north")
else:
    print("Dual-antenna heading is not available yet")
```

### Feed NTRIP corrections to an RTK rover

```python
import os
from time import monotonic

from um982py import NtripClient, Receiver
from um982py.commands import logging, modes
from um982py.messages import RtcmMessage
from um982py.messages.navigation import Fix
from um982py.protocol import StreamDecoder
from um982py.protocol.checksums import nmea_checksum


def rover_gga(receiver: Receiver) -> bytes:
    sentence = receiver.execute(logging.request("GPGGA"))
    if not Fix.from_message(sentence).valid:
        raise RuntimeError("Wait for an initial position before connecting to NTRIP")
    body = ("GPGGA," + ",".join(sentence.fields)).encode("ascii")
    return b"$" + body + f"*{nmea_checksum(body):02X}\r\n".encode("ascii")


# Set NTRIP_URL to your provider's http(s)://host:port/mountpoint.
# Set NTRIP_USERNAME and NTRIP_PASSWORD if authentication is required.
with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    receiver.execute(modes.rover())
    with NtripClient(
        os.environ["NTRIP_URL"],
        username=os.getenv("NTRIP_USERNAME"),
        password=os.getenv("NTRIP_PASSWORD"),
        initial_gga=rover_gga(receiver),
    ) as caster:
        decoder = StreamDecoder(strict=True)
        next_gga = monotonic() + 10
        while data := caster.read():
            for message in decoder.feed(data):
                if isinstance(message, RtcmMessage):
                    receiver.send_correction(message)
            if monotonic() >= next_gga:
                caster.send_gga(rover_gga(receiver))
                next_gga = monotonic() + 10
        decoder.finish()
```

### Capture a measurement session and export RINEX

```python
from pathlib import Path

from um982py import Receiver, capture_live, export_rinex
from um982py.experimental import FirmwareLog
from um982py.rinex import RinexMetadata

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    session = capture_live(
        receiver, [FirmwareLog.RANGE], duration=60, interval=1, show_progress=True
    )

result = export_rinex(
    session["RANGE"],
    marker_name="FIELD01",
    metadata=RinexMetadata(receiver_type="UM982"),
)
Path("field.obs").write_text(result.text, encoding="ascii")
print(f"Exported {result.epochs} epochs, {result.satellite_records} satellite records")
print(f"Omitted observations: {result.omitted}")
```
## License

AGPLv3
