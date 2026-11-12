# um982py

Python 3.12+ library and command-line tools for the Unicore UM982 GNSS receiver.

UM960 and UM980 have not been tested.

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

Set the port and baud rate to match your receiver. The default is 115200 baud.
The examples use 921600 baud.

Use `--augment` to enable augmentation for the current session without saving
the settings. Use `--augment --sbas-service QZSS` for QZSS SLAS; `AUTO` does
not select SLAS. Queries otherwise leave augmentation unchanged.

If a query times out, check the port, baud rate, power and serial permissions.
Use `doctor` to inspect the receiver. Check `valid` before using a position.

## Choose a workflow

| Goal | Requirements and starting point |
| --- | --- |
| Track a vehicle or locate a site | One antenna. [Position example](#locate-a-field-site) or [live tracking](examples/live_position/README.md) |
| Obtain real-time corrected positions | Correction service and coverage. [NTRIP rover](examples/ntrip_client/README.md) or [satellite PPP](#watch-a-precise-position-converge) |
| Record data for later processing | [RINEX export](#record-observations-for-post-processing) |
| Determine vehicle orientation | Two fixed antennas and their mounting offset. [Heading example](#get-the-direction-of-a-vehicle) |
| Diagnose signal reception | [Satellite reception](#check-satellite-reception) or [signal quality report](examples/signal_quality_report/README.md) |
| Work with precise timing | Linux PPS device and a separately verified time reference. [Time transfer](examples/time_transfer/README.md) |

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
| Start satellite PPP | `receiver.start_ppp(service="E6-HAS")` |
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

## Receiver output rates

Configure periodic output on the receiver's host port:

```python
from um982py import Log, Receiver
from um982py.commands import Port

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    receiver.set_output_rate([Log.GPGGA, Log.BESTNAV], 10, port=Port.COM1, verify=True)
```

The documented N4 rates are 1, 2, 5, 10, 20 and 50 Hz. Unicore specifies
20 Hz RTK and heading for UM982; 50 Hz applies to specific products and
firmware. Available rates depend on the signal group and log. The API does not
change the signal group or save settings. If a command fails, earlier changes
can remain active. [Unicore UM982 specifications](https://en.unicorecomm.com/products/um982/)

`verify=True` requires a port and checks `LOGLIST`, not the delivered rate.
Check the receiver's time status, then measure the rate from distinct receiver
timestamps and check for gaps.
Capture preserves the receiver's messages without interpolation or added
samples. Repeated queries can return the same epoch; `positions(interval=...)`
sets the delay between queries, not the receiver output rate.

```python
from itertools import pairwise
from statistics import median
from um982py import Log, Receiver, capture_live
from um982py.capture import record_epoch

with Receiver.connect("/dev/ttyUSB0", 921600) as receiver:
    records = capture_live(receiver, Log.BESTNAV, duration=10, rate_hz=10)

epochs = [record_epoch(record) for record in records]
intervals = [later - earlier for earlier, later in pairwise(epochs)]
if intervals and all(interval > 0 for interval in intervals):
    print("Median Hz:", 1 / median(intervals), "largest gap:", max(intervals))
else:
    print("Not enough ordered epochs to measure the rate")
```

## Examples

### Use a corrected rover

Configure rover mode on the receiver and enter your caster details below.
On exit, the session closes the receiver connection and stops the correction worker.

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

Heading and pitch describe the baseline between the antennas. Both are `None`
if no valid heading matches the position epoch. Apply the offset between the
baseline and the vehicle's forward direction to get the vehicle's heading.
Pass `username` and `password` to `Rover.connect()` when the caster requires
credentials. See [NTRIP rover](examples/ntrip_client/README.md) for setup.

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

Keep the antenna stationary. Stop with Ctrl+C:

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

Use `service="B2B-PPP"` for BeiDou PPP-B2b or `service="L6MDCPPP"` for QZSS
MADOCA PPP. `start_ppp()` checks the signal group
and PPP service and changes them if needed. These settings apply to the current
receiver session. The `group_changed` and `service_changed` fields show which
settings changed.

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

`result.write()` replaces an existing file. `capture_live()` stores decoded
records in memory; `InterruptedCapture.records` contains records received before
Ctrl+C. For long recordings, use `SessionRecorder` or the
[unattended station example](examples/unattended_station/README.md).

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

See the [example catalogue](examples/README.md) for more applications. Use
`help()` on library objects for their parameters and behavior.

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
