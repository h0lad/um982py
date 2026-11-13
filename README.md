# um982py

Python 3.12+ library and command-line tools for the Unicore UM982 GNSS receiver.

UM960 and UM980 have not been tested but might work to some extend.

## Install and use

From a source checkout:

```bash
python -m pip install .
```

Read a position in Python:

```python
from um982py import Receiver

with Receiver.connect("/dev/ttyUSB0") as receiver:
    position = receiver.fix()
    if position.valid:
        print(position.latitude, position.longitude)
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

Use `--augment` to enable augmentation. If the signal group changes, the
receiver saves it and reboots; other augmentation settings are not explicitly
saved. The reboot can discard other unsaved receiver settings. Use
`--augment --sbas-service QZSS` for QZSS SLAS; `AUTO` does not select SLAS.
Queries otherwise leave augmentation unchanged.

If a query times out, check the port, baud rate, power and serial permissions.
Use `doctor` to inspect the receiver. Check `valid` before using a position.
`Fix.possibly_predicted` flags the receiver's GGA signature for Doppler position
prediction; the signature alone does not prove prediction.

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
| Check live position freshness | `PositionMonitor(LiveLimits(max_gap_s=...)).status()` |
| Convert a position to ROS 2 | `navsatfix(position, stamp=..., frame_id=..., reference_frame="WGS84")` |
| Poll positions | `receiver.poll_positions(interval=1)` |
| Stream receiver output | `with receiver.stream_positions(duration=60) as positions: ...` |
| Configure periodic receiver output | `receiver.set_output_rate(Log.GPGGA, 10)` |
| Start satellite PPP | `receiver.start_ppp(service="E6-HAS")` |
| Capture one log or several logs | `capture_live()` |
| Read a saved capture or one message | `load_records(path, Log.RANGE)` or `decode_message(data)` |
| Decode an already framed message | `decode_log(frame)` |
| Decode RTCM correction fields | `decode_rtcm(data)` or `decode_message(data)` |
| Mask an elevation/azimuth sector | `receiver.execute(masking.azimuth(20, 90, 15, 45))` |
| Convert receiver time to UTC | `message_utc(record, leap_seconds=...)` |
| Read position and heading while applying NTRIP | `Rover.connect(target, ntrip_url=...)` |
| Wait for a fixed solution | `wait_for_fix(receiver, rtk_fixed=True)` |
| Record a track or survey a point | `TrackWriter(...)`, `survey_point(receiver)` |
| Calculate distance and bearing to a waypoint | `waypoint_direction(...)` |
| Export observations | `export_rinex()` |
| Convert coordinates and measure distance | `ecef_from_geodetic()`, `geodetic_from_ecef()`, `haversine_distance()` |
| Read a Linux PPS timestamp | `with PpsDevice(path) as device: device.fetch()` |
| Interpret receiver PPS or spoofing status | `receiver.pps_status()` or `receiver.spoof_info()` |
| Use asyncio | `AsyncReceiver.connect()` |

All receiver methods use `antenna=1` for the primary input and `antenna=2` for
the secondary input. `Fix`, `BestNavigation`, `PppSolution` and `RoverPosition`
share the `Position` interface: coordinates, validity, `rtk_fixed`, correction
age, GPS epoch, satellites used and ellipsoidal height. Unavailable values are
`None`. In particular, a GGA fix has UTC time of day but no date, so its GPS
epoch is unavailable. Source-specific information remains on each model.

`poll_positions()` queries the receiver once per iteration and waits between
queries. For subscribed receiver output, use the context manager below; it
restores the previous subscription when the block exits:

```python
with receiver.stream_positions(duration=60, rate_hz=1, antenna=1) as positions:
    for position in positions:
        if position.valid:
            print(position.latitude, position.longitude)
```

The receiver determines the delivered rate; repeated or missing epochs are
not concealed. `AsyncReceiver` offers the same methods with `async with` and
`async for`. `capture_live()` always returns a dictionary keyed by log name,
including when capturing one log; interrupted captures use the same shape.

For a reconnecting GGA session, pass each `PositionUpdate` to a
`PositionMonitor`. An application timer can call `monitor.status()` even when
no new fix arrives. It reports a missing or stale position and advances the
reported correction age since arrival. Check `PositionSession.health()` for
connection state. See [live position](examples/live_position/README.md).

The optional ROS 2 `navsatfix()` adapter accepts a GGA `Fix` or a
`BestNavigation` position. For BESTNAV, it supplies an east/north/up diagonal
covariance if all three receiver-reported standard deviations are available;
otherwise covariance is unknown. The caller supplies the ROS timestamp, frame,
and, for augmented fixes, the appropriate status and service mask. Install and
source ROS 2's `sensor_msgs` separately.

For example, inside a ROS 2 node that has chosen the appropriate status:

```python
from um982py import navsatfix


def to_ros_position(node, position, status):
    return navsatfix(
        position,
        stamp=node.get_clock().now().to_msg(),
        frame_id="gnss_antenna",
        reference_frame="WGS84",
        status=status,
    )
```

The timestamp in this example is the host's current ROS time, not a
receiver-derived measurement timestamp. Pass a matched measurement timestamp
if the application needs one.

## Read RTCM correction fields

Decode station coordinates and descriptions, GPS and GLONASS observations,
MSM messages, and broadcast ephemerides into immutable records:

```python
from um982py import decode_rtcm

record = decode_rtcm(frame_bytes)
body = record["fields"]
station_id = body["DF003"]  # Present in station and observation messages
```

`decode_message()` and `Log.RTCM1005.decode(message)` use the same decoder.
Fields use RTCM data-field identifiers and scaled wire units. Repeated
observations are grouped in `body["satellites"]` and MSM `body["cells"]`;
each MSM cell includes its satellite and signal mask indices. Epochs and MSM
ranges retain milliseconds; range rates use metres per second. Invalid-value
sentinels remain numeric, and weeks are not expanded across rollovers.

Every result retains its raw `payload` and `message_type`. Its `status` is
`decoded`, `unsupported`, or `unicore_private`. Private types 63, 1104 and 1105
remain raw, including Unicore's nonstandard use of the latter two IDs. Malformed
supported bodies raise `ProtocolError`; frame-only streaming and correction
forwarding continue to preserve raw data.

For an already parsed frame, `um982py.messages.decode_log(frame)` uses the
same decoder as `decode_message()`. If binary logs share an ID, pass the
expected log explicitly, for example `decode_log(frame, log=Log.BESTPOS)`.
Typed models such as `BestNavigation` can also be built with `from_record()`.

## Inspect receiver timing and spoofing status

The PPSSTATUS and SPOOFINFO logs expose their raw fields and documented
bit masks. For example, with an open receiver:

```python
from um982py.messages import SpoofSignal

pps = receiver.pps_status()
spoof = receiver.spoof_info()
print(pps.gps_week, pps.milliseconds_of_week, pps.pulse_error_ns)
print(spoof.gps_satellites, bool(spoof.signals & SpoofSignal.GPS_L1CA))
```

The reported satellite numbers are one-based mask positions; the raw masks
retain reserved bits. Receiver and firmware support determine availability.
For C-series L-band receivers, `Log.LBANDBEAM.read(table=True)` and
`Log.LBANDTRACKSTATUS.output(table=True)` use the documented table format. Table
frames expose `checksum_verified = False`; the receiver sends no checksum.

## Mask a sky sector

Exclude satellites within an elevation and azimuth range:

```python
from um982py.commands import masking

receiver.execute(masking.azimuth(20, 90, 15, 45))
```

Bounds are in degrees and must be ordered. The command uses `MASK AZIMUTH 1`;
sectors crossing north are rejected. Availability depends on receiver firmware.

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
`FREQJAMSTATUS`, `HWSTATUS`, `JAMSTATUS`, `PPSSTATUS` and `RTCSTATUS` output at
up to 1 Hz.

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
    records = capture_live(receiver, Log.BESTNAV, duration=10, rate_hz=10)[Log.BESTNAV]

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
    for update in rover.poll_positions(interval=1, heading=True):
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
Heading queries are optional and default to off, so single-antenna use does not
wait for a heading response.
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
        for fix in ppp.poll_positions(interval=5):
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
MADOCA PPP. `start_ppp()` changes the signal group and PPP service if needed.
The receiver saves a changed signal group and reboots; PPP service changes are
not explicitly saved. The session reports which settings changed. Group 7/0
supports B2b in base mode; `start_ppp()` checks the mode before using it.

For QZSS MADOCA correction telemetry, run:

```bash
um982py --port /dev/ttyUSB0 --baud 921600 --madoca ppp-diagnostics
```

Receiving correction messages does not confirm that the receiver applied them.

### Record observations for post-processing

Collect one minute of observations and save them as a RINEX file:

```python
from um982py import Log, Receiver, capture_live, export_rinex

with Receiver.serial("/dev/ttyUSB0", 921600) as receiver:
    observations = capture_live(receiver, Log.RANGE, duration=60)[Log.RANGE]

result = export_rinex(observations, marker_name="FIELD01")
result.write("field.obs")
print(f"Saved {result.epochs} epochs; omitted observations: {result.omitted}")
```

`result.write()` replaces an existing file. `capture_live()` stores decoded
records in memory; `InterruptedCapture.records` contains records received before
Ctrl+C. For long recordings, use `SessionRecorder` or the
[unattended station example](examples/unattended_station/README.md).

For `OBSVMCMP` and `OBSVHCMP` input, RINEX export includes valid pseudorange,
Doppler and signal strength. Carrier phase remains blank because the compressed
phase ambiguity has not been independently resolved; the omission count appears
in `result.omitted`.

For mixed capture rates, pass `intervals={Log.JAMSTATUS: 1}` alongside
`rate_hz=20` and `logs=[Log.RANGE, Log.JAMSTATUS]`. RANGE then uses 0.05 seconds
and JAMSTATUS uses 1 second. Both `capture_live()` and `iter_live_records()`
accept these overrides in seconds and restore previous subscriptions on exit.
Overrides must name selected periodic logs; event-only logs keep their
ONCHANGED trigger. When stopping a live iterator early, close it to restore
subscriptions.

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
