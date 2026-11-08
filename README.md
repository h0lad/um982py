# um982py

Python 3.12+ library and command-line tools for the Unicore UM982 GNSS receiver.
It reads and configures the receiver, handles NMEA, Unicore and RTCM streams,
and provides tools for GNSS capture and analysis.

Some features may also work with the UM960 and UM980; these receivers have not
been tested.

See the [integration guide](docs/integration.md) for streaming, mobile RTK,
scientific sessions and configuration changes, and the
[validation matrix](docs/validation.md) for available evidence.

The [examples](examples/README.md) include reconnecting position streams,
segmented field recording, NTRIP discovery, post-processed RTK and RINEX export.
Coordinate transformations are available with `pip install 'um982py[geodesy]'`.

## Install and use

From a source checkout:

```bash
python -m pip install .
```

The CLI accepts a serial port or a transparent TCP-to-UART gateway:

```bash
um982py --port /dev/ttyUSB0 --baud 921600 version
um982py --port tcp://192.0.2.10:4001 doctor
```

Queries leave augmentation settings unchanged. Use `--augment` to enable
augmentation for the current receiver session without saving the configuration.
## Development

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

Configure the receiver as a rover before starting the relay. The session retries
transient caster failures and reports its state through `health()`.

```python
import os
from threading import Event

from um982py import NtripClient, Receiver, ReceiverStream, RtkSession
from um982py.commands import logging
from um982py.errors import ResponseTimeout
from um982py.messages import Sentence
from um982py.messages.navigation import Fix
from um982py.protocol.checksums import nmea_checksum


with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    stream = ReceiverStream(receiver)
    stream.start()

    def rover_gga() -> bytes | None:
        try:
            message = stream.execute(logging.request("GPGGA"), timeout=2).result()
        except ResponseTimeout:
            return None
        if isinstance(message, Sentence) and Fix.from_message(message).valid:
            body = ("GPGGA," + ",".join(message.fields)).encode("ascii")
            return b"$" + body + f"*{nmea_checksum(body):02X}\r\n".encode("ascii")
        return None

    def client() -> NtripClient:
        return NtripClient(
            os.environ["NTRIP_URL"],
            username=os.getenv("NTRIP_USERNAME"),
            password=os.getenv("NTRIP_PASSWORD"),
            initial_gga=rover_gga(),
        )

    session = RtkSession(stream, client, gga_provider=rover_gga)
    try:
        session.run(Event())
    except KeyboardInterrupt:
        pass
    finally:
        stream.close()
```

Set `NTRIP_URL` to the provider's mountpoint URL and, when required, set both
`NTRIP_USERNAME` and `NTRIP_PASSWORD`. Some casters require a valid initial fix
before connecting.

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
