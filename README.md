# um982py

Python 3.12+ library and command-line tools for the Unicore UM982 GNSS receiver.

Some features may also work with the UM960 and UM980.

Validate the receiver firmware, positioning accuracy, timing and sustained
operation on the target system before deployment.

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

## Find the right API

| Task | Start here |
| --- | --- |
| Open a serial port or TCP gateway | `Receiver.connect(target)` |
| Identify the receiver | `receiver.version()` |
| Read position, heading, or velocity | `receiver.fix()`, `receiver.heading()`, `receiver.best_navigation()` |
| Query one receiver log | `receiver.read_log(Log.BESTNAV)` |
| Inspect satellites and their signals | `receiver.read_log(Log.SATSINFO).records("satellites")` |
| Capture one log or several logs | `capture_live()` |
| Read a saved capture | `load_records(path, log)` or `iter_frames(path)` |
| Relay NTRIP corrections | `relay_ntrip(receiver, url)` |
| Export observations | `export_rinex()` |
| Convert coordinates and measure distance | `ecef_from_geodetic()`, `geodetic_from_ecef()`, `haversine_distance()` |
| Read a Linux PPS timestamp | `with PpsDevice(path) as device: device.fetch()` |
| Use asyncio | `AsyncReceiver.connect()` |


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

from um982py import Receiver

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    for _ in range(60):
        fix = receiver.fix()
        if fix.valid:
            print(
                f"{fix.latitude}, {fix.longitude} | "
                f"quality: {fix.quality} | {fix.satellites} satellites | "
                f"RTK fixed: {fix.rtk_fixed}",
                flush=True,
            )
        else:
            print("Waiting for a position", flush=True)
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

Configure the receiver as a rover before starting the relay. It retries transient
caster failures and returns its health when stopped with a `threading.Event`.

```python
import os
from um982py import Receiver, relay_ntrip


with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    try:
        relay_ntrip(
            receiver,
            os.environ["NTRIP_URL"],
            username=os.getenv("NTRIP_USERNAME"),
            password=os.getenv("NTRIP_PASSWORD"),
        )
    except KeyboardInterrupt:
        pass
```

Set `NTRIP_URL` to the provider's mountpoint URL and, when required, set both
`NTRIP_USERNAME` and `NTRIP_PASSWORD`. Some casters require a valid initial fix
before connecting.

### Capture a measurement session and export RINEX

```python
from pathlib import Path

from um982py import FirmwareLog, Receiver, RinexMetadata, capture_live, export_rinex

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    observations = capture_live(
        receiver, FirmwareLog.RANGE, duration=60, interval=1, show_progress=True
    )

result = export_rinex(
    observations,
    marker_name="FIELD01",
    metadata=RinexMetadata(receiver_type="UM982"),
)
Path("field.obs").write_text(result.text, encoding="ascii")
print(f"Exported {result.epochs} epochs, {result.satellite_records} satellite records")
print(f"Omitted observations: {result.omitted}")
```

### Read speed and convert coordinates

```python
from um982py import Receiver, ecef_from_geodetic, geodetic_from_ecef

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    navigation = receiver.best_navigation()

if navigation.valid and navigation.datum == "WGS84":
    xyz = ecef_from_geodetic(
        navigation.latitude, navigation.longitude, navigation.ellipsoidal_height
    )
    print("ECEF metres:", xyz)
    print("Latitude, longitude, ellipsoidal height:", geodetic_from_ecef(*xyz))
if navigation.velocity_valid:
    print("Horizontal speed in m/s:", navigation.horizontal_speed)
```

The coordinate conversion uses WGS 84. The example checks the ASCII BESTNAV
datum before applying it; binary BESTNAV reports a numeric datum code instead.
`haversine_distance` uses a spherical approximation rather than an ellipsoidal
geodesic.

### Read a PPS edge

```python
from um982py import PpsDevice

with PpsDevice("/dev/pps0") as device:
    edge = device.fetch().assert_edge
    if edge is not None:
        print("Host CLOCK_REALTIME in nanoseconds:", edge.realtime_ns)
```

PPS timestamps use the host clock; comparing them to receiver UTC requires an
explicit association between a pulse and a receiver time. `fix.rtk_fixed`
reports GGA's fix type and does not check the freshness of corrections.

## License

AGPLv3
