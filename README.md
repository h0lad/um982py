# um982py

Python 3.12+ library and command-line tools for the Unicore UM982 GNSS receiver.

Some features may also work with the UM960 and UM980.
Serial access requires the receiver's port and baud rate; its default in this
library is 115200 baud. The examples below use 921600 as an example setting.

## Install and use

From a source checkout:

```bash
python -m pip install .
```

The CLI accepts a serial port or a transparent TCP-to-UART gateway:

```bash
um982py --port /dev/ttyUSB0 --baud 921600 version
um982py --port /dev/ttyUSB0 --baud 921600 satellites
um982py --port tcp://192.0.2.10:4001 doctor
um982py --port /dev/ttyUSB0 --baud 921600 output-rate --log GPGGA --rate-hz 10
```

Queries leave augmentation settings unchanged. Use `--augment` to enable
augmentation for the current receiver session without saving the configuration.
If a query times out, check the port, baud rate, power and serial permissions;
`doctor` can help inspect a reachable receiver. A receiver may respond before
it has a valid position: check the solution's `valid` flag before using it.

## Choose a workflow

| Goal | Requirements and starting point |
| --- | --- |
| Track a vehicle or locate a site | One antenna; [position example](#locate-a-field-site) or [live tracking](examples/live_position/README.md) |
| Obtain real-time corrected positions | Correction service and coverage; [NTRIP rover](examples/ntrip_client/README.md) or [satellite PPP](#watch-a-precise-position-converge) |
| Record data for later processing | Suitable observation time and processing products; [RINEX export](#record-observations-for-post-processing) |
| Determine vehicle orientation | Two fixed antennas and their mounting offset; [heading example](#get-the-direction-of-a-vehicle) |
| Diagnose signal reception | [Satellite reception](#check-satellite-reception) or [signal quality report](examples/signal_quality_report/README.md) |
| Work with precise timing | Linux PPS device and a separately verified time reference; [time transfer](examples/time_transfer/README.md) |

Receiver-reported precision and fix type are useful indicators, not independent
proof of accuracy. Choose correction coverage, observation duration and an
independent reference according to the application.

## Find the right API

| Task | Start here |
| --- | --- |
| Open a serial port or TCP gateway | `Receiver.connect(target)` |
| Identify the receiver | `receiver.version()` |
| Read position, heading, or velocity | `receiver.fix()`, `receiver.heading()`, `receiver.best_navigation()` |
| Query one receiver log | `receiver.read_log(Log.BESTNAV)` |
| Inspect satellites and their signals | `receiver.satellites()` |
| Follow positions | `receiver.positions(interval=1)` |
| Configure periodic receiver output | `receiver.set_output_rate(Log.GPGGA, 10)` |
| Start Galileo HAS or BeiDou PPP-B2b | `receiver.start_ppp(service="E6-HAS")` |
| Capture one log or several logs | `capture_live()` |
| Read a saved capture or one message | `load_records(path, Log.RANGE)` or `decode_message(data)` |
| Convert receiver time to UTC | `message_utc(record, leap_seconds=...)` |
| Read position and heading while applying NTRIP | `Rover.connect(target, ntrip_url=...)` |
| Wait for a fixed solution | `wait_for_fix(receiver, rtk_fixed=True)` |
| Record a track or survey a point | `TrackWriter(...)`, `survey_point(receiver)` |
| Calculate distance and bearing to a waypoint | `waypoint_direction(...)` |
| Export observations | `export_rinex()` |
| Convert coordinates and measure distance | `ecef_from_geodetic()`, `geodetic_from_ecef()`, `haversine_distance()` |
| Read a Linux PPS timestamp | `with PpsDevice(path) as device: device.fetch()` |
| Use asyncio | `AsyncReceiver.connect()` |

## Examples

Replace `/dev/ttyUSB0` and the baud rate with your receiver's settings.

### Use a corrected rover

Configure the receiver as a rover first and provide your caster details. The
session owns its receiver connection and stops the correction worker on exit.

```python
from um982py import Rover

with Rover.connect(
    "/dev/ttyUSB0", 921600, ntrip_url="https://caster.example:443/MOUNT"
) as rover:
    for update in rover.positions(interval=1):
        if update.position.valid:
            print(update.position.latitude, update.position.longitude)
            print(
                "Heading:",
                update.heading_deg,
                "correction age:",
                update.correction_age_s,
            )
```

Heading and pitch describe the antenna baseline and are `None` if a valid
heading from a matching receiver epoch is unavailable. Apply the antenna
mounting offset for vehicle heading. Correction delivery does not by itself
guarantee an RTK fixed solution; check the position type and correction health.
See the [API guide](docs/api.md#rover-and-field-workflows) for credentials,
recording, surveying and waypoint guidance.

### Locate a field site

```python
from um982py import Receiver

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    position = receiver.best_navigation()

if position.valid:
    print(f"{position.latitude}, {position.longitude}")
    print(
        f"Solution: {position.position_type}, satellites used: {position.satellites_used}"
    )
    for axis, std in (
        ("Latitude", position.latitude_std_m),
        ("Longitude", position.longitude_std_m),
        ("Height", position.height_std_m),
    ):
        if std is not None:
            print(f"{axis} standard deviation: {std:.2f} m")
else:
    print("No position available yet")
```

### Watch a precise position converge

Keep the antenna stationary and stop with Ctrl+C when the results are satisfactory:

```python
from um982py import Receiver, haversine_distance

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    ppp = receiver.start_ppp(service="E6-HAS")
    previous = None
    try:
        for fix in ppp.positions(interval=5):
            print(
                f"{fix.position_type}: horizontal std {fix.horizontal_std_m} m, "
                f"height std {fix.height_std_m} m, correction age {fix.correction_age_s} s"
            )
            if fix.valid and fix.latitude is not None and fix.longitude is not None:
                position = (fix.latitude, fix.longitude)
                print(f"Position: {position}")
                if previous is not None:
                    print(f"Change: {haversine_distance(*previous, *position):.3f} m")
                previous = position
            else:
                previous = None
    except KeyboardInterrupt:
        print("Stopped")
```

Use `service="B2B-PPP"` for BeiDou PPP-B2b. Setup verifies the signal group and
PPP service, and changes receiver settings for the current session when needed.
Check the session's `group_changed` and `service_changed` fields for changes.

### Record observations for post-processing

Collect one minute of observations and save them as a RINEX file:

```python
from um982py import Log, Receiver, capture_live, export_rinex

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    observations = capture_live(receiver, Log.RANGE, duration=60)

result = export_rinex(observations, marker_name="FIELD01")
result.write("field.obs")
print(f"Saved {result.epochs} epochs; omitted observations: {result.omitted}")
```

Choose a recording duration appropriate for your post-processing method.
`result.write()` replaces an existing file. Captures are held in memory; see the
[capture guide](docs/api.md#logs-captures-and-rinex) for long recordings and
recovering data after Ctrl+C.

### Get the direction of a vehicle

With two rigidly mounted antennas, read the heading of their baseline:

```python
from um982py import Receiver

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    heading = receiver.heading()

if heading.valid:
    print(f"Heading: {heading.degrees:.1f}° clockwise from true north")
else:
    print("Dual-antenna heading is not available yet")
```

Apply the measured antenna mounting offset if the baseline is not aligned with
the vehicle's forward direction.

### Check satellite reception

```python
from um982py import Receiver

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    for satellite in receiver.satellites():
        print(satellite.constellation, satellite.prn)
        for signal in satellite.signals:
            print(f"  {signal.name or signal.signal_id}: SNR {signal.snr}")
```

See the [API guide](docs/api.md) and [example catalogue](examples/README.md) for
more applications.

## Development

```bash
python -m pip install -e '.[dev]'
ruff check .
ruff format --check .
python -m mypy
python -m pytest
```

## License

AGPLv3
